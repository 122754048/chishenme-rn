from __future__ import annotations

import fakeredis
import pytest

from server.errors import ReplicationError, StateConflictError
from server.recovery_models import RecoveryCandidate, RecoveryCheckpoint, RecoveryStatus
from server.redis_job_store import RedisEphemeralJobStore


def _store():
    redis = fakeredis.FakeRedis(decode_responses=False)
    return RedisEphemeralJobStore(redis, prefix="recovery-test"), redis


def _job(store: RedisEphemeralJobStore):
    return store.create_job(
        slots_manifest={"admission": {"can_proceed": True}},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )


def test_recovery_checkpoint_cas_round_trip_restart_and_aligned_ttl() -> None:
    store, redis = _store()
    job = _job(store)
    checkpoint = RecoveryCheckpoint(
        goal_contract_sha256="b" * 64,
        status=RecoveryStatus.REQUIRED,
        iteration=1,
    )
    updated = store.put_recovery_checkpoint(
        job_id=job.job_id,
        expected_version=job.version,
        checkpoint=checkpoint,
        ttl_seconds=60,
    )
    assert updated.version == 2
    assert store.get_recovery_checkpoint(job.job_id) == checkpoint
    restarted = RedisEphemeralJobStore(redis, prefix=store.prefix)
    assert restarted.get_recovery_checkpoint(job.job_id) == checkpoint
    job_expiry = redis.execute_command("PEXPIRETIME", f"{store.prefix}:{job.job_id}:job")
    recovery_expiry = redis.execute_command("PEXPIRETIME", f"{store.prefix}:{job.job_id}:recovery")
    assert abs(job_expiry - recovery_expiry) <= 5


def test_recovery_checkpoint_rejects_stale_version_and_cleanup_fence() -> None:
    store, redis = _store()
    job = _job(store)
    checkpoint = RecoveryCheckpoint("b" * 64, RecoveryStatus.PLANNING)
    store.put_recovery_checkpoint(
        job_id=job.job_id,
        expected_version=job.version,
        checkpoint=checkpoint,
        ttl_seconds=60,
    )
    with pytest.raises(StateConflictError):
        store.put_recovery_checkpoint(
            job_id=job.job_id,
            expected_version=job.version,
            checkpoint=checkpoint,
            ttl_seconds=60,
        )
    redis.set(f"{store.prefix}:{job.job_id}:lease:cleanup", b"held", px=60_000)
    with pytest.raises(StateConflictError):
        store.clear_recovery_checkpoint(
            job_id=job.job_id,
            expected_version=2,
            ttl_seconds=60,
        )


def test_recovery_candidate_must_use_temporary_recovery_prefix() -> None:
    store, _ = _store()
    job = _job(store)
    candidate = RecoveryCandidate(
        candidate_id="candidate-1",
        artifact_ref={"object_key": f"final/{job.job_id}/result.mp4"},
        artifact_sha256="c" * 64,
    )
    checkpoint = RecoveryCheckpoint(
        goal_contract_sha256="b" * 64,
        status=RecoveryStatus.VERIFYING,
        candidate=candidate,
    )
    with pytest.raises(ReplicationError, match="temporary recovery"):
        store.put_recovery_checkpoint(
            job_id=job.job_id,
            expected_version=job.version,
            checkpoint=checkpoint,
            ttl_seconds=60,
        )


def test_clear_recovery_checkpoint_is_cas_and_removes_temporary_authority() -> None:
    store, redis = _store()
    job = _job(store)
    checkpoint = RecoveryCheckpoint("b" * 64, RecoveryStatus.REQUIRED)
    updated = store.put_recovery_checkpoint(
        job_id=job.job_id,
        expected_version=job.version,
        checkpoint=checkpoint,
        ttl_seconds=60,
    )
    cleared = store.clear_recovery_checkpoint(
        job_id=job.job_id,
        expected_version=updated.version,
        ttl_seconds=60,
    )
    assert cleared.version == updated.version + 1
    assert store.get_recovery_checkpoint(job.job_id) is None
    assert not redis.exists(f"{store.prefix}:{job.job_id}:recovery")
