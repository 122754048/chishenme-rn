from __future__ import annotations

import json
import math
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

import fakeredis
import pytest

from server.errors import JobGoneError, ReplicationError, StateConflictError
import server.redis_job_store as redis_job_store_module
from server.redis_job_store import RedisEphemeralJobStore


def make_store(prefix: str | None = None):
    redis_client = fakeredis.FakeRedis(decode_responses=False)
    prefix = prefix or f"test-usfr-{uuid.uuid4().hex}"
    return RedisEphemeralJobStore(redis_client, prefix=prefix), redis_client


def create_job(store: RedisEphemeralJobStore, *, ttl_seconds: int = 3600):
    return store.create_job(
        slots_manifest={"admission": {"can_proceed": True}},
        capability_token_hash="a" * 64,
        ttl_seconds=ttl_seconds,
    )


def test_create_get_round_trip_has_version_one_and_unpredictable_id():
    store, _ = make_store()
    job = create_job(store)
    assert job.version == 1
    assert job.state == "INTAKE_VALIDATED"
    assert len(job.job_id) >= 20
    assert store.get_job(job.job_id) == job
    assert store.get_job("missing") is None


def test_create_collision_does_not_overwrite_existing_job(monkeypatch):
    store, _ = make_store()
    fixed = uuid.UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr("server.redis_job_store.uuid.uuid4", lambda: fixed)
    first = create_job(store)
    with pytest.raises(StateConflictError):
        create_job(store)
    assert store.get_job(first.job_id) == first


def test_missing_job_mutation_raises_job_gone():
    store, _ = make_store()
    with pytest.raises(JobGoneError):
        store.cas_transition(job_id="gone", expected_version=1, command="start_analysis")


def test_cas_future_expected_version_rejects_read_advance_without_version_split(monkeypatch):
    store, redis_client = make_store()
    other = RedisEphemeralJobStore(redis_client, prefix=store.prefix)
    job = create_job(store)
    original = store._require_snapshot
    injected = False

    def read_then_advance(job_id):
        nonlocal injected
        snapshot = original(job_id)
        if not injected:
            injected = True
            other.cas_transition(job_id=job_id, expected_version=1, command="advance", ttl_seconds=3600)
        return snapshot

    monkeypatch.setattr(store, "_require_snapshot", read_then_advance)
    with pytest.raises(StateConflictError):
        store.cas_transition(job_id=job.job_id, expected_version=2, command="outer", updates={"state": "BROKEN"}, ttl_seconds=3600)
    raw = json.loads(redis_client.hget(f"{store.prefix}:{job.job_id}:job", "snapshot"))
    assert raw["version"] == int(redis_client.hget(f"{store.prefix}:{job.job_id}:job", "version"))
    assert store.get_job(job.job_id).version == 2


def test_cas_rejects_stale_version_without_partial_update():
    store, _ = make_store()
    job = create_job(store)
    transitioned = store.cas_transition(
        job_id=job.job_id,
        expected_version=1,
        command="start_analysis",
        updates={"state": "ANALYZING", "review_route": "manual"},
        invalidate=("qc", "assembly", "qc"),
        ttl_seconds=3600,
    )
    assert transitioned.version == 2
    assert transitioned.state == "ANALYZING"
    assert transitioned.review_route == "manual"
    assert transitioned.invalidated == ("qc", "assembly")
    with pytest.raises(StateConflictError):
        store.cas_transition(
            job_id=job.job_id,
            expected_version=1,
            command="start_analysis",
            updates={"state": "BROKEN"},
            ttl_seconds=3600,
        )
    current = store.get_job(job.job_id)
    assert current is not None
    assert current.version == 2
    assert current.state == "ANALYZING"


def test_job_owned_keys_share_absolute_expiry_and_cleanup_due():
    store, redis_client = make_store()
    job = create_job(store, ttl_seconds=30)
    store.cas_transition(job_id=job.job_id, expected_version=1, command="touch", ttl_seconds=30)
    keys = [
        f"{store.prefix}:{job.job_id}:job",
        f"{store.prefix}:{job.job_id}:scripts",
        f"{store.prefix}:{job.job_id}:storyboards",
        f"{store.prefix}:{job.job_id}:artifacts",
        f"{store.prefix}:{job.job_id}:stages",
        f"{store.prefix}:{job.job_id}:providers",
    ]
    expiries = [redis_client.execute_command("PEXPIRETIME", key) for key in keys if redis_client.exists(key)]
    assert expiries
    assert max(expiries) - min(expiries) <= 5
    assert abs(float(redis_client.zscore(f"{store.prefix}:cleanup:due", job.job_id)) - job.expires_at_ms) <= 5


def test_stage_claim_is_idempotent_and_fences_owner_and_dedupe():
    store, redis_client = make_store()
    job = create_job(store)
    first = store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=60)
    assert first.status == "CLAIMED"
    assert first.attempt == 1
    after_first = store.get_job(job.job_id)
    assert after_first is not None
    assert store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=60) == first
    after_noop_claim = store.get_job(job.job_id)
    assert after_noop_claim is not None
    assert after_noop_claim.version == after_first.version
    assert after_noop_claim.expires_at_ms == after_first.expires_at_ms
    with pytest.raises(StateConflictError):
        store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-b", ttl_seconds=60)
    with pytest.raises(StateConflictError):
        store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d2", owner="worker-a", ttl_seconds=60)
    completed = store.complete_stage(
        job_id=job.job_id,
        stage="analysis",
        dedupe_key="d1",
        owner="worker-a",
        output_artifact_ids=["a2", "a1"],
        ttl_seconds=60,
    )
    assert completed.status == "SUCCEEDED"
    assert completed.output_artifact_ids == ("a2", "a1")
    after_complete = store.get_job(job.job_id)
    assert after_complete is not None
    assert store.complete_stage(
        job_id=job.job_id,
        stage="analysis",
        dedupe_key="d1",
        owner="worker-a",
        output_artifact_ids=["other"],
        ttl_seconds=60,
    ) == completed
    after_noop_complete = store.get_job(job.job_id)
    assert after_noop_complete is not None
    assert after_noop_complete.version == after_complete.version
    assert after_noop_complete.expires_at_ms == after_complete.expires_at_ms
    with pytest.raises(StateConflictError):
        store.complete_stage(
            job_id=job.job_id,
            stage="analysis",
            dedupe_key="d1",
            owner="worker-b",
            output_artifact_ids=(),
            ttl_seconds=60,
        )
    lease_key = f"{store.prefix}:{job.job_id}:lease:render"
    store.claim_stage(job_id=job.job_id, stage="render", dedupe_key="r1", owner="worker-a", ttl_seconds=1)
    redis_client.delete(lease_key)
    reclaimed = store.claim_stage(job_id=job.job_id, stage="render", dedupe_key="r2", owner="worker-b", ttl_seconds=60)
    assert reclaimed.attempt == 2


def test_stage_completion_requires_current_lease():
    store, _ = make_store()
    job = create_job(store)
    store.claim_stage(job_id=job.job_id, stage="qc", dedupe_key="q1", owner="worker-a", ttl_seconds=60)
    with pytest.raises(StateConflictError):
        store.complete_stage(
            job_id=job.job_id,
            stage="qc",
            dedupe_key="q1",
            owner="worker-b",
            output_artifact_ids=(),
            ttl_seconds=60,
        )


def test_stage_reclaim_requires_new_owner_or_dedupe_and_fences_old_worker():
    store, redis_client = make_store()
    job = create_job(store)
    first = store.claim_stage(job_id=job.job_id, stage="render", dedupe_key="d1", owner="worker-a", ttl_seconds=60)
    redis_client.delete(f"{store.prefix}:{job.job_id}:lease:render")
    with pytest.raises(StateConflictError):
        store.claim_stage(job_id=job.job_id, stage="render", dedupe_key="d1", owner="worker-a", ttl_seconds=60)
    reclaimed = store.claim_stage(job_id=job.job_id, stage="render", dedupe_key="d2", owner="worker-a", ttl_seconds=60)
    assert reclaimed.attempt == first.attempt + 1
    with pytest.raises(StateConflictError):
        store.complete_stage(
            job_id=job.job_id,
            stage="render",
            dedupe_key="d1",
            owner="worker-a",
            output_artifact_ids=(),
            ttl_seconds=60,
        )


def test_stage_owner_dedupe_token_cannot_be_reused_after_an_intervening_claim():
    store, redis_client = make_store()
    job = create_job(store)
    store.claim_stage(job_id=job.job_id, stage="render", dedupe_key="d1", owner="worker-a", ttl_seconds=60)
    redis_client.delete(f"{store.prefix}:{job.job_id}:lease:render")
    store.claim_stage(job_id=job.job_id, stage="render", dedupe_key="d2", owner="worker-b", ttl_seconds=60)
    redis_client.delete(f"{store.prefix}:{job.job_id}:lease:render")
    with pytest.raises(StateConflictError):
        store.claim_stage(job_id=job.job_id, stage="render", dedupe_key="d1", owner="worker-a", ttl_seconds=60)


def test_stage_logical_deadline_allows_natural_reclaim_without_shortening_job():
    store, redis_client = make_store()
    job = create_job(store, ttl_seconds=100)
    first = store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=10)
    claimed = store.get_job(job.job_id)
    assert claimed is not None
    assert claimed.expires_at_ms == job.expires_at_ms
    redis_client.hset(
        f"{store.prefix}:{job.job_id}:stages",
        "@meta:analysis:lease_expires_at_ms",
        str(time.time_ns() // 1_000_000 - 1),
    )
    with pytest.raises(StateConflictError):
        store.complete_stage(
            job_id=job.job_id,
            stage="analysis",
            dedupe_key="d1",
            owner="worker-a",
            output_artifact_ids=(),
            ttl_seconds=10,
        )
    reclaimed = store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d2", owner="worker-b", ttl_seconds=10)
    assert reclaimed.attempt == first.attempt + 1
    assert store.get_job(job.job_id) is not None
    assert redis_client.execute_command("PEXPIRETIME", f"{store.prefix}:{job.job_id}:lease:analysis") == job.expires_at_ms


def test_stage_completion_shorter_ttl_does_not_shorten_existing_job_expiry(monkeypatch):
    now = time.time_ns() // 1_000_000
    monkeypatch.setattr(redis_job_store_module, "_now_ms", lambda: now)
    store, redis_client = make_store()
    job = create_job(store, ttl_seconds=100)
    store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=100)
    completed = store.complete_stage(
        job_id=job.job_id,
        stage="analysis",
        dedupe_key="d1",
        owner="worker-a",
        output_artifact_ids=(),
        ttl_seconds=10,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    assert current.expires_at_ms == job.expires_at_ms
    assert completed.status == "SUCCEEDED"
    keys = [
        f"{store.prefix}:{job.job_id}:job",
        f"{store.prefix}:{job.job_id}:stages",
        f"{store.prefix}:{job.job_id}:lease:analysis",
    ]
    expiries = [redis_client.execute_command("PEXPIRETIME", key) for key in keys]
    assert max(expiries) - min(expiries) <= 5
    assert abs(float(redis_client.zscore(f"{store.prefix}:cleanup:due", job.job_id)) - job.expires_at_ms) <= 5


def test_stage_complete_uses_redis_execution_clock_after_python_deadline(monkeypatch):
    store, _ = make_store()
    job = create_job(store, ttl_seconds=30)
    store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=1)
    original_eval = store._eval
    delayed = False

    def delayed_eval(script, keys, args):
        nonlocal delayed
        if not delayed and script is redis_job_store_module._STAGE_COMPLETE_LUA:
            delayed = True
            time.sleep(1.1)
        return original_eval(script, keys, args)

    monkeypatch.setattr(store, "_eval", delayed_eval)
    with pytest.raises(StateConflictError):
        store.complete_stage(
            job_id=job.job_id,
            stage="analysis",
            dedupe_key="d1",
            owner="worker-a",
            output_artifact_ids=(),
            ttl_seconds=1,
        )


def test_stage_claim_retries_reclaim_when_python_deadline_goes_stale_before_lua(monkeypatch):
    store, _ = make_store()
    job = create_job(store, ttl_seconds=30)
    first = store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=1)
    original_eval = store._eval
    delayed = False

    def delayed_eval(script, keys, args):
        nonlocal delayed
        if not delayed and script is redis_job_store_module._STAGE_CLAIM_LUA:
            delayed = True
            time.sleep(1.1)
        return original_eval(script, keys, args)

    monkeypatch.setattr(store, "_eval", delayed_eval)
    reclaimed = store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d2", owner="worker-b", ttl_seconds=10)
    assert reclaimed.attempt == first.attempt + 1


def test_stage_claim_retry_state_is_request_local_on_one_store(monkeypatch):
    store, _ = make_store()
    job = create_job(store, ttl_seconds=30)
    original_eval = store._eval
    barrier = threading.Barrier(2)
    local = threading.local()

    def controlled_eval(script, keys, args):
        if script is redis_job_store_module._STAGE_CLAIM_LUA and not getattr(local, "stale", False):
            local.stale = True
            barrier.wait(timeout=5)
            time.sleep(0.03)
            return [b"ATTEMPT_STALE", b"2"]
        return original_eval(script, keys, args)

    monkeypatch.setattr(store, "_eval", controlled_eval)

    def claim(stage):
        return store.claim_stage(job_id=job.job_id, stage=stage, dedupe_key=f"{stage}-d1", owner=f"{stage}-owner", ttl_seconds=10)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(claim, ("analysis-a", "analysis-b"))
    assert first.attempt == 1
    assert second.attempt == 1
    assert not hasattr(store, "_claim_retry_guard")


def test_stage_lua_reads_redis_time_for_logical_deadline_fences():
    source = Path(redis_job_store_module.__file__).read_text(encoding="utf-8")
    assert "redis.call('TIME')" in source
    assert "deadline <= tonumber(ARGV[13])" not in source


def test_stage_mutations_never_expire_global_due_zsets_or_drop_other_job_members():
    store, redis_client = make_store()
    other_job = create_job(store, ttl_seconds=30)
    other_attempt = store.begin_provider_attempt(
        job_id=other_job.job_id,
        expected_version=1,
        operation="CreateAsset",
        request_sha256="b" * 64,
    )
    job = create_job(store, ttl_seconds=30)
    store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=10)
    store.complete_stage(
        job_id=job.job_id,
        stage="analysis",
        dedupe_key="d1",
        owner="worker-a",
        output_artifact_ids=(),
        ttl_seconds=10,
    )
    cleanup_key = f"{store.prefix}:cleanup:due"
    provider_key = f"{store.prefix}:provider:due"
    assert redis_client.pttl(cleanup_key) == -1
    assert redis_client.pttl(provider_key) == -1
    assert redis_client.zscore(cleanup_key, other_job.job_id) is not None
    assert redis_client.zscore(provider_key, f"{other_job.job_id}:{other_attempt.attempt_id}") is not None


def test_every_lua_mutation_touches_all_job_owned_keys_only(monkeypatch):
    now = time.time_ns() // 1_000_000
    monkeypatch.setattr(redis_job_store_module, "_now_ms", lambda: now)
    store, redis_client = make_store()
    job = create_job(store, ttl_seconds=100)
    job_key = f"{store.prefix}:{job.job_id}:job"
    scripts_key = f"{store.prefix}:{job.job_id}:scripts"
    storyboards_key = f"{store.prefix}:{job.job_id}:storyboards"
    artifacts_key = f"{store.prefix}:{job.job_id}:artifacts"
    stages_key = f"{store.prefix}:{job.job_id}:stages"
    providers_key = f"{store.prefix}:{job.job_id}:providers"
    lease_key = f"{store.prefix}:{job.job_id}:lease:preexisting"
    owned_hashes = [scripts_key, storyboards_key, artifacts_key, stages_key, providers_key]
    for index, key in enumerate(owned_hashes, start=1):
        redis_client.hset(key, "seed", f"seed-{index}")
        redis_client.pexpireat(key, now + index * 1000)
    redis_client.hset(stages_key, "@leasekey:preexisting", lease_key)
    redis_client.set(lease_key, "preexisting-lease")
    redis_client.pexpireat(lease_key, now + 9000)
    redis_client.zadd(f"{store.prefix}:cleanup:due", {"other-job": now + 1})
    redis_client.zadd(f"{store.prefix}:provider:due", {"other-attempt": now + 1})
    current = store.cas_transition(job_id=job.job_id, expected_version=1, command="touch", ttl_seconds=100)
    appended = store.append_revision(job_id=job.job_id, kind="script", expected_version=current.version, manifest={"revision": 1, "sha256": "b" * 64}, invalidate_downstream=False, ttl_seconds=100)
    approved = store.approve_revision(job_id=job.job_id, kind="script", revision=1, expected_version=appended.version, expected_sha256="b" * 64, ttl_seconds=100)
    attempt = store.begin_provider_attempt(job_id=job.job_id, expected_version=approved.version, operation="CreateAsset", request_sha256="c" * 64)
    store.update_provider_attempt(
        job_id=job.job_id,
        expected_version=approved.version + 1,
        attempt=attempt.__class__(**{**attempt.to_dict(), "status": "RUNNING"}),
        ttl_seconds=100,
    )
    store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=100)
    store.complete_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", output_artifact_ids=(), ttl_seconds=100)
    snapshot = store.get_job(job.job_id)
    assert snapshot is not None
    all_owned = [job_key, scripts_key, storyboards_key, artifacts_key, stages_key, providers_key, lease_key]
    expiries = [redis_client.execute_command("PEXPIRETIME", key) for key in all_owned if redis_client.exists(key)]
    assert max(expiries) - min(expiries) <= 5
    assert abs(float(redis_client.zscore(f"{store.prefix}:cleanup:due", job.job_id)) - snapshot.expires_at_ms) <= 5
    assert redis_client.pttl(f"{store.prefix}:cleanup:due") == -1
    assert redis_client.pttl(f"{store.prefix}:provider:due") == -1
    assert redis_client.zscore(f"{store.prefix}:cleanup:due", "other-job") is not None
    assert redis_client.zscore(f"{store.prefix}:provider:due", "other-attempt") is not None


def test_nan_and_key_glob_inputs_are_rejected():
    with pytest.raises(ReplicationError):
        RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix="bad*")
    store, _ = make_store()
    with pytest.raises(ReplicationError):
        store.create_job(slots_manifest={"bad": math.nan}, capability_token_hash="a" * 64, ttl_seconds=60)
    job = create_job(store)
    with pytest.raises(ReplicationError):
        store.claim_stage(job_id=job.job_id, stage="render*", dedupe_key="d1", owner="worker-a", ttl_seconds=60)


def test_stage_names_cannot_enter_internal_sidecar_namespace():
    store, redis_client = make_store()
    job = create_job(store)
    safe = store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=60)
    stage_key = f"{store.prefix}:{job.job_id}:stages"
    before = redis_client.hgetall(stage_key)
    malicious = ("@meta:analysis:owner", "@leasekey:evil", "@seen:evil", "bad:stage", "*", "a" * 129)
    for stage in malicious:
        with pytest.raises(ReplicationError):
            store.claim_stage(job_id=job.job_id, stage=stage, dedupe_key="d2", owner="worker-b", ttl_seconds=60)
    assert redis_client.hgetall(stage_key) == before
    assert store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=60) == safe


def test_lease_expiry_touch_does_not_use_global_keys_scan():
    source = Path(redis_job_store_module.__file__).read_text(encoding="utf-8")
    assert "redis.call('KEYS'" not in source


def test_cleanup_fence_blocks_every_redis_mutation_lua_path():
    store, redis_client = make_store()

    def fence(job_id):
        redis_client.set(f"{store.prefix}:{job_id}:lease:cleanup", "fence", px=60000)

    job = create_job(store)
    fence(job.job_id)
    with pytest.raises(StateConflictError):
        store.cas_transition(job_id=job.job_id, expected_version=1, command="blocked", ttl_seconds=60)

    job = create_job(store)
    fence(job.job_id)
    with pytest.raises(StateConflictError):
        store.append_revision(
            job_id=job.job_id,
            kind="script",
            expected_version=1,
            manifest={"revision": 1, "sha256": "b" * 64},
            invalidate_downstream=False,
            ttl_seconds=60,
        )

    job = create_job(store)
    appended = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=1,
        manifest={"revision": 1, "sha256": "b" * 64},
        invalidate_downstream=False,
        ttl_seconds=60,
    )
    fence(job.job_id)
    with pytest.raises(StateConflictError):
        store.approve_revision(job_id=job.job_id, kind="script", revision=1, expected_version=appended.version, expected_sha256="b" * 64, ttl_seconds=60)

    job = create_job(store)
    fence(job.job_id)
    with pytest.raises(StateConflictError):
        store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="c" * 64)

    job = create_job(store)
    attempt = store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="c" * 64)
    fence(job.job_id)
    with pytest.raises(StateConflictError):
        store.update_provider_attempt(
            job_id=job.job_id,
            expected_version=2,
            attempt=attempt.__class__(**{**attempt.to_dict(), "status": "RUNNING"}),
            ttl_seconds=60,
        )

    job = create_job(store)
    fence(job.job_id)
    with pytest.raises(StateConflictError):
        store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=60)

    job = create_job(store)
    store.claim_stage(job_id=job.job_id, stage="analysis", dedupe_key="d1", owner="worker-a", ttl_seconds=60)
    fence(job.job_id)
    with pytest.raises(StateConflictError):
        store.complete_stage(
            job_id=job.job_id,
            stage="analysis",
            dedupe_key="d1",
            owner="worker-a",
            output_artifact_ids=(),
            ttl_seconds=60,
        )


def test_provider_retention_is_finite_and_authority_eventually_expires():
    redis_client = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis_client, prefix=f"retention-{uuid.uuid4().hex}", provider_retention_ms=100)
    job = create_job(store, ttl_seconds=1)
    store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="b" * 64)
    time.sleep(1.35)
    assert redis_client.exists(f"{store.prefix}:{job.job_id}:job") == 0
    assert redis_client.exists(f"{store.prefix}:{job.job_id}:providers") == 0
