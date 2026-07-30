from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from .errors import ReplicationError
from .job_models import ArtifactRef


_SAFE_JOB = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class AliyunOssFinalStore:
    """Permanent, immutable final-video publisher backed by Alibaba OSS."""

    def __init__(
        self,
        *,
        internal_store: Any,
        bucket: Any,
        public_base_url: str,
        final_prefix: str = "usfr",
    ) -> None:
        if internal_store is None or not callable(getattr(internal_store, "download_to", None)):
            raise ValueError("internal_store must expose download_to")
        if bucket is None:
            raise ValueError("OSS bucket is required")
        base = str(public_base_url or "").strip().rstrip("/")
        if not base.startswith("https://"):
            raise ValueError("public_base_url must be HTTPS")
        prefix = str(final_prefix or "").strip().strip("/")
        if prefix and any(part in {"", ".", ".."} for part in prefix.split("/")):
            raise ValueError("final_prefix is invalid")
        self.internal_store = internal_store
        self.bucket = bucket
        self.public_base_url = base
        self.final_prefix = prefix

    def _key(self, job_id: str) -> str:
        if not isinstance(job_id, str) or _SAFE_JOB.fullmatch(job_id) is None:
            raise ReplicationError("INVALID_INPUT", "job_id is invalid")
        suffix = f"final/{job_id}/result.mp4"
        return f"{self.final_prefix}/{suffix}" if self.final_prefix else suffix

    def _public_url(self, key: str) -> str:
        return f"{self.public_base_url}/{quote(key, safe='/')}"

    @staticmethod
    def _metadata(meta: Any) -> tuple[int, str]:
        size = int(getattr(meta, "content_length", -1))
        headers = getattr(meta, "headers", {})
        headers = headers if isinstance(headers, dict) else dict(headers or {})
        digest = str(
            headers.get("x-oss-meta-sha256")
            or headers.get("X-Oss-Meta-Sha256")
            or headers.get("x_oss_meta_sha256")
            or ""
        ).lower()
        return size, digest

    def _ref(self, *, key: str, source: ArtifactRef) -> ArtifactRef:
        return replace(
            source,
            artifact_id=key,
            kind="final",
            object_key=key,
            content_type="video/mp4",
            metadata={"public_url": self._public_url(key), "storage": "aliyun_oss"},
        )

    def promote(self, *, job_id: str, source: ArtifactRef) -> ArtifactRef:
        if not isinstance(source, ArtifactRef) or source.content_type.casefold() != "video/mp4":
            raise ReplicationError("ARTIFACT_METADATA_MISMATCH", "final source must be a verified MP4")
        key = self._key(job_id)
        if self.bucket.object_exists(key):
            size, digest = self._metadata(self.bucket.get_object_meta(key))
            if size != source.size_bytes or digest != source.sha256:
                raise ReplicationError(
                    "ARTIFACT_CONFLICT",
                    "permanent OSS destination already contains different bytes",
                    category="artifact",
                    http_status=409,
                )
            return self._ref(key=key, source=source)

        with tempfile.TemporaryDirectory(prefix="usfr-final-") as directory:
            local = Path(directory) / "result.mp4"
            self.internal_store.download_to(
                object_key=source.object_key,
                destination=local,
                expected_sha256=source.sha256,
            )
            data_size = local.stat().st_size
            hasher = hashlib.sha256()
            with local.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            if data_size != source.size_bytes or digest != source.sha256:
                raise ReplicationError("ARTIFACT_METADATA_MISMATCH", "temporary final MP4 failed byte verification")
            with local.open("rb") as stream:
                response = self.bucket.put_object(
                    key,
                    stream,
                    headers={
                        "Content-Type": "video/mp4",
                        "x-oss-meta-sha256": source.sha256,
                        "Cache-Control": "public, max-age=31536000, immutable",
                    },
                )
            status = int(getattr(response, "status", 0) or 0)
            if status and not 200 <= status < 300:
                raise ReplicationError("OBJECT_STORE_UNAVAILABLE", "Alibaba OSS upload failed", retryable=True, http_status=503)
        size, observed_sha = self._metadata(self.bucket.get_object_meta(key))
        if size != source.size_bytes or observed_sha != source.sha256:
            raise ReplicationError("ARTIFACT_METADATA_MISMATCH", "Alibaba OSS final object failed verification")
        return self._ref(key=key, source=source)

    def has_final(self, job_id: str) -> bool:
        key = self._key(job_id)
        try:
            return bool(self.bucket.object_exists(key))
        except Exception as exc:
            raise ReplicationError(
                "OBJECT_STORE_UNAVAILABLE",
                "permanent OSS result state could not be verified",
                category="storage",
                retryable=True,
            ) from exc

    def validate_final_ref(self, job_id: str, ref: Mapping[str, Any] | ArtifactRef) -> bool:
        if isinstance(ref, ArtifactRef):
            value: Mapping[str, Any] = ref.to_dict()
        elif isinstance(ref, Mapping):
            value = ref
        else:
            raise ReplicationError(
                "ARTIFACT_METADATA_MISMATCH",
                "final reference is not the exact permanent OSS result",
                category="artifact",
            )
        key = self._key(job_id)
        sha256 = value.get("sha256")
        size_bytes = value.get("size_bytes")
        content_type = str(value.get("content_type") or "").casefold()
        if (
            value.get("object_key") != key
            or not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or content_type != "video/mp4"
        ):
            raise ReplicationError(
                "ARTIFACT_METADATA_MISMATCH",
                "final reference is not the exact permanent OSS result",
                category="artifact",
            )
        if not self.has_final(job_id):
            raise ReplicationError(
                "ARTIFACT_METADATA_MISMATCH",
                "the exact permanent OSS result is missing",
                category="artifact",
            )
        try:
            observed_size, observed_sha = self._metadata(self.bucket.get_object_meta(key))
        except Exception as exc:
            raise ReplicationError(
                "OBJECT_STORE_UNAVAILABLE",
                "permanent OSS result metadata could not be verified",
                category="storage",
                retryable=True,
            ) from exc
        if observed_size != size_bytes or observed_sha != sha256:
            raise ReplicationError(
                "ARTIFACT_METADATA_MISMATCH",
                "final reference does not match the exact permanent OSS result",
                category="artifact",
            )
        return True

    def delete_job(self, job_id: str, *, preserve_result: bool = False) -> int:
        del preserve_result
        self._key(job_id)
        return 0


__all__ = ["AliyunOssFinalStore"]
