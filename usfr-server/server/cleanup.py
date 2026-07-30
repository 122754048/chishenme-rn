"""Idempotent job-scoped object and Redis cleanup."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Mapping
from typing import Any, Iterable

from .errors import ReplicationError
from .object_store import FinalVideoStore, TemporaryMediaStore


_ACTIVE_PROVIDER = {"SUBMITTING", "RUNNING", "AMBIGUOUS"}
_SAFE_JOB = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_ACQUIRE_CLEANUP_LUA = r"""
local fields = redis.call('HKEYS', KEYS[2])
for _, field in ipairs(fields) do
    if string.sub(field, 1, 8) == '@status:' then
        local status = redis.call('HGET', KEYS[2], field)
        if status == 'SUBMITTING' or status == 'RUNNING' or status == 'AMBIGUOUS' then
            return {'ACTIVE'}
        end
    end
end
if redis.call('EXISTS', KEYS[1]) == 1 then
    return {'BUSY'}
end
local acquired = redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2])
if acquired then
    return {'OK'}
end
return {'BUSY'}
"""


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _safe_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or not job_id or len(job_id) > 128 or any(ch not in _SAFE_JOB for ch in job_id) or job_id[0] not in _SAFE_JOB - set("._-"):
        raise ReplicationError("INVALID_INPUT", "job_id is invalid", category="lifecycle", http_status=400)
    return job_id


class CleanupSweeper:
    def __init__(
        self,
        redis_client: Any,
        temporary_store: TemporaryMediaStore,
        final_store: FinalVideoStore,
        *,
        upload_store: Any | None = None,
        prefix: str = "usfr",
        lease_ms: int = 60_000,
    ) -> None:
        if redis_client is None:
            raise ValueError("redis_client is required")
        if not isinstance(prefix, str) or not prefix or any(ch.isspace() or ch in "*?[]{}" for ch in prefix):
            raise ValueError("prefix is invalid")
        if isinstance(lease_ms, bool) or not isinstance(lease_ms, int) or lease_ms <= 0:
            raise ValueError("lease_ms must be positive")
        self.redis = redis_client
        self.temporary_store = temporary_store
        self.final_store = final_store
        self.upload_store = upload_store
        self.prefix = prefix.rstrip(":")
        self.lease_ms = lease_ms

    @property
    def cleanup_due_key(self) -> str:
        return f"{self.prefix}:cleanup:due"

    @property
    def provider_due_key(self) -> str:
        return f"{self.prefix}:provider:due"

    @property
    def temporary_cleanup_due_key(self) -> str:
        return f"{self.prefix}:temporary-cleanup:due"

    def schedule_temporary_cleanup(
        self,
        *,
        job_id: str,
        terminal_at_ms: int,
        retention_seconds: int = 172800,
    ) -> None:
        _safe_job_id(job_id)
        if isinstance(terminal_at_ms, bool) or not isinstance(terminal_at_ms, int) or terminal_at_ms <= 0:
            raise ReplicationError("INVALID_INPUT", "terminal_at_ms must be a positive integer", category="lifecycle", http_status=400)
        if isinstance(retention_seconds, bool) or not isinstance(retention_seconds, int) or retention_seconds < 0:
            raise ReplicationError("INVALID_INPUT", "retention_seconds must be non-negative", category="lifecycle", http_status=400)
        self.redis.zadd(
            self.temporary_cleanup_due_key,
            {job_id: terminal_at_ms + retention_seconds * 1000},
        )

    def due_temporary_jobs(self, *, now_ms: int, limit: int = 100) -> tuple[str, ...]:
        if isinstance(now_ms, bool) or not isinstance(now_ms, int):
            raise ReplicationError("INVALID_INPUT", "now_ms must be an integer", category="lifecycle", http_status=400)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ReplicationError("INVALID_INPUT", "limit must be positive", category="lifecycle", http_status=400)
        try:
            rows = self.redis.zrangebyscore(self.temporary_cleanup_due_key, "-inf", now_ms, start=0, num=limit)
        except TypeError:
            rows = self.redis.zrangebyscore(self.temporary_cleanup_due_key, "-inf", now_ms)[:limit]
        return tuple(_decode(item) for item in rows)

    def purge_temporary_job(self, job_id: str) -> bool:
        """Delete only temporary media; public job metadata and final MP4 remain."""

        job_id = _safe_job_id(job_id)
        token = self._acquire(job_id)
        if token is None:
            return False
        try:
            if self._provider_active(job_id):
                self.redis.zadd(self.temporary_cleanup_due_key, {job_id: self._now_ms() + self.lease_ms})
                return False
            snapshot = self._snapshot(job_id)
            self._validate_final_ref(job_id, snapshot)
            self.temporary_store.delete_job(job_id)
            slots_manifest = (snapshot or {}).get("slots_manifest")
            upload_scope = slots_manifest.get("upload_scope") if isinstance(slots_manifest, Mapping) else None
            if upload_scope and self.upload_store is not None:
                self.upload_store.delete_scope(str(upload_scope))
            self.redis.zrem(self.temporary_cleanup_due_key, job_id)
            return True
        except Exception:
            self.redis.zadd(self.temporary_cleanup_due_key, {job_id: self._now_ms() + self.lease_ms})
            return False
        finally:
            self._release(job_id, token)

    def sweep_temporary_once(self, now_ms: int, *, limit: int = 100) -> tuple[str, ...]:
        processed: list[str] = []
        for job_id in self.due_temporary_jobs(now_ms=now_ms, limit=limit):
            if self.purge_temporary_job(job_id):
                processed.append(job_id)
        return tuple(processed)

    def _job_prefix(self, job_id: str) -> str:
        return f"{self.prefix}:{_safe_job_id(job_id)}:"

    def _lease_key(self, job_id: str) -> str:
        return f"{self._job_prefix(job_id)}lease:cleanup"

    def _acquire(self, job_id: str) -> str | None:
        token = secrets.token_urlsafe(18)
        try:
            result = self.redis.eval(
                _ACQUIRE_CLEANUP_LUA,
                2,
                self._lease_key(job_id),
                f"{self._job_prefix(job_id)}providers",
                token,
                self.lease_ms,
            )
        except Exception as exc:
            raise ReplicationError("STORE_ERROR", "cleanup lease could not be acquired", category="lifecycle", retryable=True) from exc
        status = _decode(result[0] if isinstance(result, (list, tuple)) and result else result)
        return token if status == "OK" else None

    def _release(self, job_id: str, token: str) -> None:
        key = self._lease_key(job_id)
        script = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"
        try:
            self.redis.eval(script, 1, key, token)
        except Exception:
            # Never fall back to a racy GET+DEL.  The TTL is the only safe
            # recovery path when compare-and-delete cannot execute atomically.
            return

    def _provider_active(self, job_id: str) -> bool:
        key = f"{self._job_prefix(job_id)}providers"
        try:
            fields = self.redis.hgetall(key) or {}
        except Exception as exc:
            raise ReplicationError("STORE_ERROR", "provider state could not be read", category="lifecycle", retryable=True) from exc
        for raw_field, raw_value in fields.items():
            field = _decode(raw_field)
            value = _decode(raw_value).upper()
            if field.startswith("@status:") and value in _ACTIVE_PROVIDER:
                return True
            if not field.startswith("@"):
                try:
                    payload = json.loads(_decode(raw_value))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict) and str(payload.get("status", "")).upper() in _ACTIVE_PROVIDER:
                    return True
        return False

    def _snapshot(self, job_id: str) -> dict[str, Any] | None:
        key = f"{self._job_prefix(job_id)}job"
        raw = self.redis.hget(key, "snapshot")
        if raw is None:
            return None
        try:
            value = json.loads(_decode(raw))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReplicationError("STATE_CORRUPT", "stored job snapshot is invalid", category="lifecycle") from exc
        return value if isinstance(value, dict) else None

    def _validate_final_ref(self, job_id: str, snapshot: Mapping[str, Any] | None) -> None:
        if not snapshot or snapshot.get("final_ref") is None:
            return
        ref = snapshot.get("final_ref")
        if not isinstance(ref, Mapping):
            raise ReplicationError("ARTIFACT_METADATA_MISMATCH", "snapshot final_ref is malformed", category="artifact")
        expected_key = f"final/{_safe_job_id(job_id)}/result.mp4"
        object_key = ref.get("object_key")
        sha256 = ref.get("sha256")
        content_type = str(ref.get("content_type") or "").lower()
        size = ref.get("size_bytes")
        if (
            object_key != expected_key
            or not isinstance(sha256, str)
            or _SHA256.fullmatch(sha256) is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or content_type != "video/mp4"
        ):
            raise ReplicationError("ARTIFACT_METADATA_MISMATCH", "snapshot final_ref does not match the exact final video", category="artifact")
        object_store = getattr(self.final_store, "object_store", None)
        head = getattr(object_store, "head", None)
        if not callable(head):
            raise ReplicationError("OBJECT_STORE_UNAVAILABLE", "final object state cannot be verified", category="storage", retryable=True)
        try:
            observed = head(expected_key)
        except ReplicationError as exc:
            if exc.code == "ARTIFACT_NOT_FOUND":
                raise ReplicationError("ARTIFACT_METADATA_MISMATCH", "snapshot final_ref points to a missing object", category="artifact") from exc
            raise
        except Exception as exc:
            raise ReplicationError("OBJECT_STORE_UNAVAILABLE", "final object state could not be verified", category="storage", retryable=True) from exc
        observed_key = getattr(observed, "object_key", None)
        observed_sha = getattr(observed, "sha256", None)
        observed_size = getattr(observed, "size_bytes", None)
        observed_type = str(getattr(observed, "content_type", "") or "").lower()
        if isinstance(observed, Mapping):
            observed_key = observed.get("object_key") or observed.get("key")
            observed_sha = observed.get("sha256")
            observed_size = observed.get("size_bytes")
            observed_type = str(observed.get("content_type") or "").lower()
        if (
            observed_key != expected_key
            or observed_sha != sha256
            or observed_size != size
            or observed_type != "video/mp4"
        ):
            raise ReplicationError("ARTIFACT_METADATA_MISMATCH", "snapshot final_ref does not match final object metadata", category="artifact")

    def _preserve_for_job(self, job_id: str) -> bool:
        snapshot = self._snapshot(job_id)
        self._validate_final_ref(job_id, snapshot)
        state = str((snapshot or {}).get("state") or "").upper()
        successful = bool(snapshot and snapshot.get("final_ref") is not None) or state in {
            "SUCCEEDED",
            "SUCCESS",
            "COMPLETED",
            "FINAL",
            "FINALIZED",
            "DONE",
        }
        destructive = state in {"FAILED", "EXPIRED", "CANCELLED", "ABORTED"}
        object_store = getattr(self.final_store, "object_store", None)
        head = getattr(object_store, "head", None)
        if callable(head):
            try:
                head(f"final/{_safe_job_id(job_id)}/result.mp4")
                return not destructive
            except ReplicationError as exc:
                if exc.code == "ARTIFACT_NOT_FOUND":
                    return successful
                raise
            except Exception as exc:
                raise ReplicationError("OBJECT_STORE_UNAVAILABLE", "final object state could not be verified", category="storage", retryable=True) from exc
        # A custom final store without a HEAD capability cannot establish
        # whether a final object exists; fail closed rather than deleting it.
        raise ReplicationError("OBJECT_STORE_UNAVAILABLE", "final object state cannot be verified", category="storage", retryable=True)

    def _delete_objects(self, job_id: str, *, preserve_final: bool) -> None:
        # These wrappers validate the exact job prefix.  No caller-provided broad
        # prefix reaches the provider.
        snapshot = self._snapshot(job_id)
        self._validate_final_ref(job_id, snapshot)
        object_store = getattr(self.final_store, "object_store", None)
        head = getattr(object_store, "head", None)
        if not callable(head):
            raise ReplicationError("OBJECT_STORE_UNAVAILABLE", "final object state cannot be verified", category="storage", retryable=True)
        try:
            head(f"final/{_safe_job_id(job_id)}/result.mp4")
        except ReplicationError as exc:
            if exc.code != "ARTIFACT_NOT_FOUND":
                raise
        except Exception as exc:
            raise ReplicationError("OBJECT_STORE_UNAVAILABLE", "final object state could not be verified", category="storage", retryable=True) from exc
        self.temporary_store.delete_job(job_id)
        slots_manifest = (snapshot or {}).get("slots_manifest")
        upload_scope = (
            slots_manifest.get("upload_scope")
            if isinstance(slots_manifest, Mapping)
            else None
        )
        if upload_scope:
            if self.upload_store is None:
                raise ReplicationError(
                    "OBJECT_STORE_UNAVAILABLE",
                    "owned upload scope cannot be deleted without UploadMediaStore",
                    category="storage",
                    retryable=True,
                )
            self.upload_store.delete_scope(str(upload_scope))
        self.final_store.delete_job(job_id, preserve_result=preserve_final)

    def _job_owned_keys(self, job_id: str) -> tuple[str, ...]:
        prefix = self._job_prefix(job_id)
        keys: list[str] = []
        scanner = getattr(self.redis, "scan_iter", None)
        if callable(scanner):
            for key in scanner(match=f"{prefix}*"):
                text = _decode(key)
                if text.startswith(prefix) and text != self._lease_key(job_id):
                    keys.append(text)
        else:
            # Explicit known keys are sufficient for minimal Redis-compatible fakes.
            keys.extend(
                [
                    f"{prefix}job",
                    f"{prefix}scripts",
                    f"{prefix}storyboards",
                    f"{prefix}artifacts",
                    f"{prefix}stages",
                    f"{prefix}providers",
                    f"{prefix}recovery",
                ]
            )
        # Dynamic stage leases are discovered from the per-job stage index below.
        stages_key = f"{prefix}stages"
        try:
            stage_fields = self.redis.hgetall(stages_key) or {}
        except Exception:
            stage_fields = {}
        for raw_field, raw_value in stage_fields.items():
            field = _decode(raw_field)
            if field.startswith("@leasekey:"):
                lease_key = _decode(raw_value)
                if lease_key.startswith(prefix + "lease:"):
                    keys.append(lease_key)
        return tuple(sorted(set(keys)))

    def _remove_redis_authority(self, job_id: str) -> None:
        # Delete only per-job keys; global queues are handled by exact member
        # removal below and are never matched by the per-job scan.
        keys = self._job_owned_keys(job_id)
        if keys:
            self.redis.delete(*keys)
        self.redis.zrem(self.cleanup_due_key, job_id)
        self.redis.zrem(self.temporary_cleanup_due_key, job_id)
        # Provider due members are job_id:attempt_id.  Iterate members and remove
        # only exact job-scoped entries, leaving other jobs intact.
        members: Iterable[Any]
        scanner = getattr(self.redis, "zscan_iter", None)
        if callable(scanner):
            members = (item[0] for item in scanner(self.provider_due_key))
        else:
            members = self.redis.zrange(self.provider_due_key, 0, -1)
        remove: list[str] = []
        prefix = f"{job_id}:"
        for member in members:
            text = _decode(member)
            if text.startswith(prefix):
                remove.append(text)
        if remove:
            self.redis.zrem(self.provider_due_key, *remove)

    def cleanup_job(self, job_id: str, *, preserve_final: bool) -> bool:
        job_id = _safe_job_id(job_id)
        if not isinstance(preserve_final, bool):
            raise ReplicationError("INVALID_INPUT", "preserve_final must be boolean", category="lifecycle", http_status=400)
        token = self._acquire(job_id)
        if token is None:
            return False
        try:
            try:
                provider_active = self._provider_active(job_id)
            except ReplicationError as exc:
                if exc.code == "STATE_CONFLICT":
                    self.redis.zadd(self.cleanup_due_key, {job_id: self._now_ms() + self.lease_ms})
                    return False
                raise
            if provider_active:
                # Keep the due member recoverable and release our lease.  A short
                # delay prevents a hot loop while reconciliation is in progress.
                self.redis.zadd(self.cleanup_due_key, {job_id: self._now_ms() + self.lease_ms})
                return False
            try:
                self._delete_objects(job_id, preserve_final=preserve_final)
            except Exception:
                # Redis authority is deliberately retained until every object
                # deletion succeeds; the due member remains for retry.
                self.redis.zadd(self.cleanup_due_key, {job_id: self._now_ms() + self.lease_ms})
                return False
            self._remove_redis_authority(job_id)
            return True
        finally:
            self._release(job_id, token)

    def sweep_once(self, now_ms: int, *, limit: int = 100) -> tuple[str, ...]:
        if isinstance(now_ms, bool) or not isinstance(now_ms, int):
            raise ReplicationError("INVALID_INPUT", "now_ms must be an integer", category="lifecycle", http_status=400)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ReplicationError("INVALID_INPUT", "limit must be a positive integer", category="lifecycle", http_status=400)
        try:
            members = self.redis.zrangebyscore(self.cleanup_due_key, "-inf", now_ms, start=0, num=limit)
        except TypeError:
            members = self.redis.zrangebyscore(self.cleanup_due_key, "-inf", now_ms)[:limit]
        processed: list[str] = []
        for raw in members:
            job_id = _decode(raw)
            try:
                _safe_job_id(job_id)
            except ReplicationError:
                # Corrupt member is removed only by exact member, never via a broad
                # queue deletion; it cannot influence another job.
                self.redis.zrem(self.cleanup_due_key, raw)
                continue
            try:
                preserve_final = self._preserve_for_job(job_id)
            except Exception:
                self.redis.zadd(self.cleanup_due_key, {job_id: self._now_ms() + self.lease_ms})
                continue
            if self.cleanup_job(job_id, preserve_final=preserve_final):
                processed.append(job_id)
        return tuple(processed)

    @staticmethod
    def _now_ms() -> int:
        import time

        return time.time_ns() // 1_000_000


__all__ = ["CleanupSweeper"]
