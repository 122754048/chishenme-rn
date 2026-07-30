"""Content-addressed reuse of decoded source frames and ROI evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .errors import ReplicationError


def _key(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SharedFrameRef:
    object_key: str
    sha256: str
    source_sha256: str
    timestamp_us: int
    roi: tuple[int, int, int, int] | None


class SharedFrameEvidenceStore:
    """Deduplicate one `(source, timestamp, ROI)` decode across all stages."""

    def __init__(self, backend: Any, decoder: Any) -> None:
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
            raise ReplicationError("CONTRACT_INVALID", "shared frame source SHA-256 is required")
        if isinstance(timestamp_us, bool) or not isinstance(timestamp_us, int) or timestamp_us < 0:
            raise ReplicationError("CONTRACT_INVALID", "shared frame timestamp is invalid")
        normalized_roi = None if roi is None else tuple(int(value) for value in roi)
        if normalized_roi is not None and len(normalized_roi) != 4:
            raise ReplicationError("CONTRACT_INVALID", "shared frame ROI must contain four integers")
        digest_key = _key({"source_sha256": source_sha256, "timestamp_us": timestamp_us, "roi": normalized_roi})
        existing = self.backend.get(digest_key)
        if existing is not None:
            return SharedFrameRef(**dict(existing))
        create = getattr(self.decoder, "decode_and_publish", None)
        if not callable(create):
            raise ReplicationError("CAPABILITY_UNAVAILABLE", "shared frame decoder is not configured", retryable=True)
        created = create(source, timestamp_us=timestamp_us, roi=normalized_roi)
        if isinstance(created, SharedFrameRef):
            candidate = created
        elif isinstance(created, Mapping):
            candidate = SharedFrameRef(**dict(created))
        else:
            raise ReplicationError("CONTRACT_INVALID", "shared frame decoder returned an invalid reference")
        if candidate.source_sha256 != source_sha256 or candidate.timestamp_us != timestamp_us or candidate.roi != normalized_roi:
            raise ReplicationError("CONTRACT_INVALID", "shared frame decoder reference does not match request")
        put_if_absent = getattr(self.backend, "put_if_absent", None)
        if not callable(put_if_absent):
            raise ReplicationError("CONTRACT_INVALID", "shared frame backend lacks atomic put_if_absent")
        stored = put_if_absent(digest_key, asdict(candidate))
        return SharedFrameRef(**dict(stored or asdict(candidate)))


__all__ = ["SharedFrameEvidenceStore", "SharedFrameRef"]
