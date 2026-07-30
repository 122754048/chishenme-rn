"""Content-addressed decoded-frame references shared across USFR stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class SharedFrameRef:
    object_key: str
    sha256: str
    source_sha256: str
    timestamp_us: int
    roi: tuple[int, int, int, int] | None = None


class SharedFrameEvidenceStore:
    def __init__(self, *, backend: Any, decoder: Any) -> None:
        self.backend = backend
        self.decoder = decoder

    def get_or_create(
        self,
        source: Any,
        *,
        timestamp_us: int,
        roi: tuple[int, int, int, int] | None = None,
    ) -> SharedFrameRef:
        source_sha256 = str(getattr(source, "sha256", "") or "").lower()
        if len(source_sha256) != 64:
            raise ValueError("shared frame source SHA-256 is invalid")
        if not isinstance(timestamp_us, int) or isinstance(timestamp_us, bool) or timestamp_us < 0:
            raise ValueError("shared frame timestamp is invalid")
        normalized_roi = tuple(int(value) for value in roi) if roi is not None else None
        if normalized_roi is not None and (len(normalized_roi) != 4 or any(value < 0 for value in normalized_roi)):
            raise ValueError("shared frame ROI is invalid")
        key = _sha(
            {
                "source_sha256": source_sha256,
                "timestamp_us": timestamp_us,
                "roi": normalized_roi,
            }
        )
        existing = self.backend.get(key)
        if existing is not None:
            row = dict(existing)
            row["roi"] = tuple(row["roi"]) if row.get("roi") is not None else None
            return SharedFrameRef(**row)
        created = self.decoder.decode_and_publish(
            source,
            timestamp_us=timestamp_us,
            roi=normalized_roi,
        )
        if not isinstance(created, SharedFrameRef):
            raise ValueError("shared frame decoder returned an invalid reference")
        if created.source_sha256 != source_sha256 or created.timestamp_us != timestamp_us or created.roi != normalized_roi:
            raise ValueError("shared frame decoder returned mismatched evidence")
        self.backend.put_if_absent(key, asdict(created))
        current = self.backend.get(key)
        row = dict(current if current is not None else asdict(created))
        row["roi"] = tuple(row["roi"]) if row.get("roi") is not None else None
        return SharedFrameRef(**row)


def build_shared_frame_manifest(
    *,
    source_sha256: str,
    frames: list[dict[str, Any]],
    carrier_object_key: str,
    carrier_sha256: str,
) -> dict[str, Any]:
    normalized = [dict(item) for item in frames]
    identities = [
        (item.get("timestamp_us"), tuple(item.get("roi") or ()))
        for item in normalized
    ]
    if not normalized or len(identities) != len(set(identities)):
        raise ValueError("shared frame manifest contains duplicate or empty frame evidence")
    manifest: dict[str, Any] = {
        "contract": "usfr-shared-frame-manifest/v1",
        "source_sha256": source_sha256,
        "frame_count": len(normalized),
        "frames": normalized,
        "carrier": {
            "kind": "source_keyframe_sheet",
            "object_key": carrier_object_key,
            "sha256": carrier_sha256,
        },
    }
    manifest["manifest_sha256"] = _sha(manifest)
    return manifest


__all__ = ["SharedFrameEvidenceStore", "SharedFrameRef", "build_shared_frame_manifest"]
