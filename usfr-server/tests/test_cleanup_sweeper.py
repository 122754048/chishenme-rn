from __future__ import annotations

import fakeredis
import pytest
import json

from server.cleanup import CleanupSweeper
from server.object_store import FinalVideoStore, S3ObjectStore, TemporaryMediaStore
from server.redis_job_store import RedisEphemeralJobStore
from server.recovery_models import RecoveryCheckpoint, RecoveryStatus
from server.errors import StateConflictError

from test_object_lifecycle import MemoryS3


def _stores_and_job(*, ttl_seconds: int = 3600, retention_ms: int = 300_000):
    client = MemoryS3()
    object_store = S3ObjectStore(client, bucket="private-test")
    temporary = TemporaryMediaStore(object_store)
    final = FinalVideoStore(object_store)
    redis = fakeredis.FakeRedis(decode_responses=False)
    jobs = RedisEphemeralJobStore(redis, prefix="usfr-test", provider_retention_ms=retention_ms)
    job = jobs.create_job(slots_manifest={}, capability_token_hash="a" * 64, ttl_seconds=ttl_seconds)
    sweeper = CleanupSweeper(redis, temporary, final, prefix="usfr-test")
    return client, redis, jobs, job, temporary, final, sweeper


def test_success_cleanup_keeps_only_final_video():
    client, _redis, jobs, job, temporary, final, sweeper = _stores_and_job()
    source = temporary.put_bytes(job_id=job.job_id, logical_path="assembled.mp4", data=b"video", content_type="video/mp4")
    final_ref = final.promote(job_id=job.job_id, source=source)
    assert sweeper.cleanup_job(job.job_id, preserve_final=True)
    assert temporary.list_job_keys(job.job_id) == ()
    assert final.exists(final_ref)
    assert jobs.get_job(job.job_id) is None
    assert all(not key.startswith(f"temporary/{job.job_id}/") for key in client.objects)


def test_cleanup_removes_recovery_checkpoint_authority():
    _client, redis, jobs, job, _temporary, _final, sweeper = _stores_and_job()
    jobs.put_recovery_checkpoint(
        job_id=job.job_id,
        expected_version=job.version,
        checkpoint=RecoveryCheckpoint("b" * 64, RecoveryStatus.REQUIRED),
        ttl_seconds=3600,
    )
    recovery_key = f"usfr-test:{job.job_id}:recovery"
    assert redis.exists(recovery_key)
    assert sweeper.cleanup_job(job.job_id, preserve_final=False)
    assert not redis.exists(recovery_key)


def test_failed_cleanup_can_remove_final_when_requested():
    client, _redis, jobs, job, temporary, final, sweeper = _stores_and_job()
    source = temporary.put_bytes(job_id=job.job_id, logical_path="assembled.mp4", data=b"video", content_type="video/mp4")
    final_ref = final.promote(job_id=job.job_id, source=source)
    assert sweeper.cleanup_job(job.job_id, preserve_final=False)
    assert not final.exists(final_ref)
    assert jobs.get_job(job.job_id) is None
    assert not any(key.startswith(f"final/{job.job_id}/") for key in client.objects)


def test_object_deletion_failure_leaves_redis_authority_for_retry():
    _client, redis, jobs, job, temporary, final, _sweeper = _stores_and_job()

    class BrokenTemporary:
        def __getattr__(self, name):
            return getattr(temporary, name)

        def delete_job(self, job_id):
            raise RuntimeError("object store down")

    sweeper = CleanupSweeper(redis, BrokenTemporary(), final, prefix="usfr-test")
    assert not sweeper.cleanup_job(job.job_id, preserve_final=True)
    assert jobs.get_job(job.job_id) is not None
    assert redis.zscore("usfr-test:cleanup:due", job.job_id) is not None


def test_active_provider_blocks_cleanup_and_lease_contention_skips():
    _client, redis, jobs, job, temporary, final, sweeper = _stores_and_job()
    jobs.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="b" * 64)
    assert not sweeper.cleanup_job(job.job_id, preserve_final=False)
    assert jobs.get_job(job.job_id) is not None
    lease_key = f"usfr-test:{job.job_id}:lease:cleanup"
    redis.set(lease_key, b"other", nx=True, px=60000)
    assert not sweeper.cleanup_job(job.job_id, preserve_final=False)
    assert redis.exists(lease_key)


def test_sweep_once_only_processes_due_jobs_and_preserves_other_global_state():
    client, redis, jobs, job, temporary, final, sweeper = _stores_and_job()
    other = jobs.create_job(slots_manifest={}, capability_token_hash="c" * 64, ttl_seconds=3600)
    redis.set("usfr-test:global:stream", b"keep")
    redis.zadd("usfr-test:cleanup:due", {job.job_id: 1, other.job_id: 999999999999})
    processed = sweeper.sweep_once(2, limit=1)
    assert processed == (job.job_id,)
    assert jobs.get_job(job.job_id) is None
    assert jobs.get_job(other.job_id) is not None
    assert redis.exists("usfr-test:global:stream")
    assert all(not key.startswith(f"temporary/{other.job_id}/") for key in client.objects)


def test_preserve_final_removes_siblings_but_keeps_exact_result():
    client, _redis, jobs, job, temporary, final, sweeper = _stores_and_job()
    source = temporary.put_bytes(job_id=job.job_id, logical_path="assembled.mp4", data=b"video", content_type="video/mp4")
    result = final.promote(job_id=job.job_id, source=source)
    client.objects[f"final/{job.job_id}/history.mp4"] = {"body": b"old", "content_type": "video/mp4", "sha256": "a" * 64}
    assert sweeper.cleanup_job(job.job_id, preserve_final=True)
    assert result.object_key in client.objects
    assert f"final/{job.job_id}/history.mp4" not in client.objects
    assert jobs.get_job(job.job_id) is None


def test_final_head_timeout_blocks_sweep_and_preserves_authority():
    client, redis, jobs, job, temporary, final, sweeper = _stores_and_job()
    source = temporary.put_bytes(job_id=job.job_id, logical_path="assembled.mp4", data=b"video", content_type="video/mp4")
    result = final.promote(job_id=job.job_id, source=source)
    original_head = final.object_store.head

    def timeout_head(_key):
        raise RuntimeError("timeout")

    final.object_store.head = timeout_head
    redis.zadd("usfr-test:cleanup:due", {job.job_id: 1})
    assert sweeper.sweep_once(2) == ()
    assert jobs.get_job(job.job_id) is not None
    assert redis.zscore("usfr-test:cleanup:due", job.job_id) is not None
    final.object_store.head = original_head
    assert result.object_key in client.objects


def test_cleanup_release_does_not_get_del_when_compare_lua_fails():
    client, base_redis, jobs, job, temporary, final, _sweeper = _stores_and_job()

    class EvalFailsRedis:
        def __init__(self, inner):
            self.inner = inner
            self.calls = 0

        def eval(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return self.inner.eval(*args, **kwargs)
            raise RuntimeError("eval unavailable")

        def __getattr__(self, name):
            return getattr(self.inner, name)

    redis = EvalFailsRedis(base_redis)
    sweeper = CleanupSweeper(redis, temporary, final, prefix="usfr-test", lease_ms=60000)
    assert sweeper.cleanup_job(job.job_id, preserve_final=True)
    assert redis.exists(f"usfr-test:{job.job_id}:lease:cleanup")


def test_cleanup_fence_rejects_all_redis_mutations_after_acquisition():
    _client, redis, jobs, job, temporary, final, sweeper = _stores_and_job()
    token = sweeper._acquire(job.job_id)
    assert token is not None
    with pytest.raises(StateConflictError):
        jobs.cas_transition(job_id=job.job_id, expected_version=1, command="blocked", ttl_seconds=60)
    with pytest.raises(StateConflictError):
        jobs.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="b" * 64)


def test_cleanup_fence_acquisition_races_provider_begin(monkeypatch):
    _client, redis, jobs, job, temporary, final, sweeper = _stores_and_job()

    def race(_job_id):
        jobs.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="b" * 64)
        return False

    monkeypatch.setattr(sweeper, "_provider_active", race)
    assert not sweeper.cleanup_job(job.job_id, preserve_final=False)
    assert jobs.get_job(job.job_id) is not None


def test_active_provider_authority_survives_logical_ttl_and_cleanup_boundary():
    client, redis, jobs, job, temporary, _final, sweeper = _stores_and_job(ttl_seconds=1, retention_ms=2_000)
    source = temporary.put_bytes(job_id=job.job_id, logical_path="pending.mp4", data=b"video", content_type="video/mp4")
    attempt = jobs.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="b" * 64)
    job_key = f"usfr-test:{job.job_id}:job"
    providers_key = f"usfr-test:{job.job_id}:providers"
    logical_expiry = job.expires_at_ms
    physical_expiry = redis.execute_command("PEXPIRETIME", job_key)
    assert physical_expiry >= logical_expiry + 1_500
    import time

    time.sleep(1.2)
    now = time.time_ns() // 1_000_000
    assert redis.exists(job_key)
    assert redis.exists(providers_key)
    assert jobs.get_job(job.job_id) is not None
    assert source.object_key in client.objects
    assert sweeper.sweep_once(now, limit=10) == ()
    assert redis.zscore("usfr-test:provider:due", f"{job.job_id}:{attempt.attempt_id}") is not None
    current = jobs.get_job(job.job_id)
    assert current is not None
    updated = jobs.update_provider_attempt(
        job_id=job.job_id,
        expected_version=current.version,
        attempt=attempt.__class__(**{**attempt.to_dict(), "status": "RUNNING"}),
        ttl_seconds=1,
    )
    assert updated.version == current.version + 1
    assert redis.execute_command("PEXPIRETIME", job_key) <= updated.expires_at_ms + 2_500


@pytest.mark.parametrize(
    "field, value",
    [
        ("content_type", "application/octet-stream"),
        ("sha256", "f" * 64),
        ("size_bytes", 999),
        ("object_key", "final/job-other/result.mp4"),
    ],
)
def test_corrupt_snapshot_final_ref_blocks_cleanup(field, value):
    client, redis, jobs, job, temporary, final, sweeper = _stores_and_job()
    source = temporary.put_bytes(job_id=job.job_id, logical_path="assembled.mp4", data=b"video", content_type="video/mp4")
    final_ref = final.promote(job_id=job.job_id, source=source)
    temporary.put_bytes(job_id=job.job_id, logical_path="leftover.bin", data=b"left", content_type="application/octet-stream")
    corrupted = final_ref.to_dict()
    corrupted[field] = value
    job_key = f"usfr-test:{job.job_id}:job"
    snapshot = json.loads(redis.hget(job_key, "snapshot"))
    snapshot["final_ref"] = corrupted
    redis.hset(job_key, "snapshot", json.dumps(snapshot, sort_keys=True, separators=(",", ":")))
    redis.zadd("usfr-test:cleanup:due", {job.job_id: 1})
    assert sweeper.sweep_once(2) == ()
    assert jobs.get_job(job.job_id) is not None
    assert final_ref.object_key in client.objects
    assert temporary.list_job_keys(job.job_id)


def test_malformed_snapshot_final_ref_blocks_cleanup():
    client, redis, jobs, job, temporary, final, sweeper = _stores_and_job()
    source = temporary.put_bytes(job_id=job.job_id, logical_path="assembled.mp4", data=b"video", content_type="video/mp4")
    final_ref = final.promote(job_id=job.job_id, source=source)
    job_key = f"usfr-test:{job.job_id}:job"
    snapshot = json.loads(redis.hget(job_key, "snapshot"))
    snapshot["final_ref"] = {"object_key": final_ref.object_key}
    redis.hset(job_key, "snapshot", json.dumps(snapshot, sort_keys=True, separators=(",", ":")))
    redis.zadd("usfr-test:cleanup:due", {job.job_id: 1})
    assert sweeper.sweep_once(2) == ()
    assert jobs.get_job(job.job_id) is not None
    assert final_ref.object_key in client.objects
