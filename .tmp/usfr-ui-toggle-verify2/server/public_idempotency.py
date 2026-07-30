from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import uuid
from typing import Any


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IdempotencyConflict(ValueError):
    pass


@dataclass(frozen=True)
class IdempotencyClaim:
    job_id: str
    request_sha256: str
    created: bool


class RedisIdempotencyStore:
    def __init__(self, redis_client: Any, *, prefix: str = "usfr") -> None:
        if redis_client is None:
            raise ValueError("redis_client is required")
        self.redis = redis_client
        self.prefix = str(prefix or "usfr")

    def _key(self, value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"{self.prefix}:public-idempotency:{digest}"

    @staticmethod
    def _validate(key: str, request_sha256: str, job_id: str, ttl_seconds: int) -> None:
        try:
            uuid.UUID(key)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Idempotency-Key must be a UUID") from exc
        if _SHA256.fullmatch(str(request_sha256 or "")) is None:
            raise ValueError("request_sha256 must be lowercase SHA-256")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("proposed_job_id is required")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")

    @staticmethod
    def _decode(raw: Any) -> dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        value = json.loads(str(raw))
        if not isinstance(value, dict):
            raise ValueError("idempotency record is invalid")
        return value

    def claim(
        self,
        *,
        key: str,
        request_sha256: str,
        proposed_job_id: str,
        ttl_seconds: int,
    ) -> IdempotencyClaim:
        self._validate(key, request_sha256, proposed_job_id, ttl_seconds)
        redis_key = self._key(key)
        record = {"job_id": proposed_job_id, "request_sha256": request_sha256}
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"))
        if self.redis.set(redis_key, encoded, nx=True, ex=ttl_seconds):
            return IdempotencyClaim(proposed_job_id, request_sha256, True)
        existing_raw = self.redis.get(redis_key)
        if existing_raw is None:
            return self.claim(
                key=key,
                request_sha256=request_sha256,
                proposed_job_id=proposed_job_id,
                ttl_seconds=ttl_seconds,
            )
        existing = self._decode(existing_raw)
        if existing.get("request_sha256") != request_sha256:
            raise IdempotencyConflict("Idempotency-Key was already used with a different request")
        job_id = str(existing.get("job_id") or "")
        if not job_id:
            raise ValueError("idempotency record has no job_id")
        return IdempotencyClaim(job_id, request_sha256, False)


__all__ = ["IdempotencyClaim", "IdempotencyConflict", "RedisIdempotencyStore"]
