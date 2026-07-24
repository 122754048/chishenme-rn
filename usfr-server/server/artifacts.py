from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import BinaryIO, Protocol

from .errors import ReplicationError
from .object_store import ArtifactRef, FinalVideoStore, ObjectStore, S3ObjectStore, TemporaryMediaStore


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ArtifactStore(Protocol):
    def put_stream(self, *, run_id: str, artifact_id: str, stream: BinaryIO, content_type: str, expected_sha256: str | None = None) -> dict[str, object]: ...
    def download_path(self, *, run_id: str, artifact_id: str) -> Path: ...


class LocalArtifactStore:
    """Atomic local development store with the same ownership boundary as object storage."""

    def __init__(self, root: Path, *, max_bytes: int = 512 * 1024 * 1024) -> None:
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    def _validate_segment(self, value: str) -> None:
        if not _SAFE_SEGMENT.fullmatch(value):
            raise ReplicationError(
                code="INPUT_SLOT_INVALID",
                message="run_id and artifact_id must be safe single path segments",
                category="input",
                user_action_required=True,
                http_status=400,
            )

    def put_stream(
        self,
        *,
        run_id: str,
        artifact_id: str,
        stream: BinaryIO,
        content_type: str,
        expected_sha256: str | None = None,
    ) -> dict[str, object]:
        self._validate_segment(run_id)
        self._validate_segment(artifact_id)
        if not content_type:
            raise ReplicationError("INPUT_SLOT_INVALID", "content_type is required", category="input", http_status=400)
        destination_dir = (self.root / run_id).resolve()
        if self.root not in destination_dir.parents and destination_dir != self.root:
            raise ReplicationError("INPUT_SLOT_INVALID", "artifact path escaped store root", category="input", http_status=400)
        destination_dir.mkdir(parents=True, exist_ok=True)
        final_path = destination_dir / artifact_id
        fd, temporary = tempfile.mkstemp(prefix=f".{artifact_id}.", dir=str(destination_dir))
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(fd, "wb") as output:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ReplicationError("INPUT_SLOT_INVALID", "artifact exceeds configured size limit", category="input", user_action_required=True, http_status=413)
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            sha256 = digest.hexdigest()
            if expected_sha256 and sha256 != expected_sha256:
                raise ReplicationError(
                    code="ARTIFACT_HASH_MISMATCH",
                    message="uploaded bytes do not match expected SHA-256",
                    category="artifact",
                    user_action_required=True,
                    details={"expected": expected_sha256, "actual": sha256},
                    http_status=422,
                )
            with self._lock:
                if final_path.exists():
                    existing_digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
                    if existing_digest != sha256:
                        raise ReplicationError(
                            "ARTIFACT_CONFLICT",
                            "artifact_id is immutable and already contains different bytes",
                            category="artifact",
                            user_action_required=True,
                            details={"run_id": run_id, "artifact_id": artifact_id, "existing_sha256": existing_digest, "incoming_sha256": sha256},
                            http_status=409,
                        )
                    return {
                        "artifact_id": artifact_id,
                        "run_id": run_id,
                        "path": str(final_path),
                        "uri": f"artifact://{run_id}/{artifact_id}",
                        "content_type": content_type,
                        "size_bytes": final_path.stat().st_size,
                        "sha256": sha256,
                        "replayed": True,
                    }
                try:
                    # Hard-link publication is an atomic create-without-
                    # overwrite operation on the same filesystem.  Unlike
                    # os.replace(), a second process cannot clobber the first
                    # completed artifact between the existence check and
                    # publication.
                    os.link(temporary, final_path)
                    os.unlink(temporary)
                except FileExistsError:
                    existing_digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
                    if existing_digest != sha256:
                        raise ReplicationError(
                            "ARTIFACT_CONFLICT",
                            "artifact_id is immutable and already contains different bytes",
                            category="artifact",
                            user_action_required=True,
                            details={"run_id": run_id, "artifact_id": artifact_id, "existing_sha256": existing_digest, "incoming_sha256": sha256},
                            http_status=409,
                        )
                    return {
                        "artifact_id": artifact_id,
                        "run_id": run_id,
                        "path": str(final_path),
                        "uri": f"artifact://{run_id}/{artifact_id}",
                        "content_type": content_type,
                        "size_bytes": final_path.stat().st_size,
                        "sha256": sha256,
                        "replayed": True,
                    }
                except OSError as exc:
                    raise ReplicationError(
                        "ARTIFACT_STORE_UNAVAILABLE",
                        "local artifact store cannot publish atomically on this filesystem",
                        category="storage",
                        retryable=True,
                        details={"run_id": run_id, "artifact_id": artifact_id},
                        http_status=503,
                    ) from exc
            return {
                "artifact_id": artifact_id,
                "run_id": run_id,
                "path": str(final_path),
                "uri": f"artifact://{run_id}/{artifact_id}",
                "content_type": content_type,
                "size_bytes": size,
                "sha256": sha256,
            }
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def download_path(self, *, run_id: str, artifact_id: str) -> Path:
        self._validate_segment(run_id)
        self._validate_segment(artifact_id)
        path = (self.root / run_id / artifact_id).resolve()
        root = self.root
        if root not in path.parents:
            raise ReplicationError("INPUT_SLOT_INVALID", "artifact path escaped store root", category="input", http_status=400)
        if not path.is_file():
            raise ReplicationError("ARTIFACT_NOT_FOUND", "artifact does not exist", category="artifact", http_status=404)
        return path

    def signed_download(self, *, run_id: str, artifact_id: str, expires_seconds: int = 300) -> str:
        """Development URL placeholder; production adapters return a signed HTTPS URL."""
        self.download_path(run_id=run_id, artifact_id=artifact_id)
        return f"artifact://{run_id}/{artifact_id}?expires={expires_seconds}"


__all__ = [
    "ArtifactRef",
    "ArtifactStore",
    "FinalVideoStore",
    "LocalArtifactStore",
    "ObjectStore",
    "S3ObjectStore",
    "TemporaryMediaStore",
]
