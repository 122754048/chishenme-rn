from __future__ import annotations

import json
import uuid

import fakeredis
import pytest

from server.errors import ApprovalStaleError, ReplicationError, StateConflictError
from server.redis_job_store import RedisEphemeralJobStore


def make_store():
    client = fakeredis.FakeRedis(decode_responses=False)
    return RedisEphemeralJobStore(client, prefix=f"revision-{uuid.uuid4().hex}"), client


def create_job(store):
    return store.create_job(
        slots_manifest={"admission": {"can_proceed": True}},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )


def manifest(revision: int, sha: str = "b" * 64, **extra):
    value = {"revision": revision, "sha256": sha}
    value.update(extra)
    return value


def test_script_append_installs_revision_and_deterministic_invalidations():
    store, redis_client = make_store()
    job = create_job(store)
    updated = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=1,
        manifest=manifest(1, source_ref={"object_key": "script/1.json"}),
        invalidate_downstream=True,
        ttl_seconds=3600,
    )
    assert updated.version == 2
    assert updated.current_script_revision == 1
    assert updated.approved_script_sha256 is None
    assert updated.current_storyboard_revision is None
    assert updated.approved_storyboard_sha256 is None
    assert updated.invalidated == ("storyboard", "segment_plan", "prompt_audit", "provider_plan", "assembly", "qc")
    raw = redis_client.hget(f"{store.prefix}:{job.job_id}:scripts", "1")
    assert raw == b'{"revision":1,"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","source_ref":{"object_key":"script/1.json"}}'


def test_storyboard_append_and_no_downstream_invalidation():
    store, _ = make_store()
    job = create_job(store)
    first = store.append_revision(
        job_id=job.job_id,
        kind="storyboard",
        expected_version=1,
        manifest=manifest(4),
        invalidate_downstream=False,
        ttl_seconds=3600,
    )
    assert first.current_storyboard_revision == 4
    assert first.approved_storyboard_sha256 is None
    assert first.invalidated == ()


def test_revision_append_requires_monotonic_and_exact_existing_manifest():
    store, _ = make_store()
    job = create_job(store)
    store.append_revision(job_id=job.job_id, kind="script", expected_version=1, manifest=manifest(1), invalidate_downstream=False, ttl_seconds=3600)
    with pytest.raises(StateConflictError):
        store.append_revision(job_id=job.job_id, kind="script", expected_version=2, manifest=manifest(1, "c" * 64), invalidate_downstream=False, ttl_seconds=3600)
    with pytest.raises(ReplicationError):
        store.append_revision(job_id=job.job_id, kind="script", expected_version=2, manifest=manifest(0), invalidate_downstream=False, ttl_seconds=3600)


def test_identical_old_revision_replay_is_not_a_noop_after_newer_revision():
    store, _ = make_store()
    job = create_job(store)
    first = manifest(1)
    second = manifest(2, "c" * 64)
    rev1 = store.append_revision(job_id=job.job_id, kind="script", expected_version=1, manifest=first, invalidate_downstream=False, ttl_seconds=3600)
    rev2 = store.append_revision(job_id=job.job_id, kind="script", expected_version=rev1.version, manifest=second, invalidate_downstream=False, ttl_seconds=3600)
    with pytest.raises(StateConflictError):
        store.append_revision(job_id=job.job_id, kind="script", expected_version=rev2.version, manifest=first, invalidate_downstream=False, ttl_seconds=3600)


def test_approve_requires_current_revision_and_exact_hash():
    store, _ = make_store()
    job = create_job(store)
    script = manifest(1)
    appended = store.append_revision(job_id=job.job_id, kind="script", expected_version=1, manifest=script, invalidate_downstream=False, ttl_seconds=3600)
    approved = store.approve_revision(job_id=job.job_id, kind="script", revision=1, expected_version=appended.version, expected_sha256="b" * 64, ttl_seconds=3600)
    assert approved.version == appended.version + 1
    assert approved.approved_script_sha256 == "b" * 64
    with pytest.raises(ApprovalStaleError):
        store.approve_revision(job_id=job.job_id, kind="script", revision=1, expected_version=approved.version, expected_sha256="c" * 64, ttl_seconds=3600)
    with pytest.raises(ApprovalStaleError):
        store.approve_revision(job_id=job.job_id, kind="script", revision=2, expected_version=approved.version, expected_sha256="b" * 64, ttl_seconds=3600)


def test_approval_uses_top_level_revision_not_nested_slots_manifest():
    store, _ = make_store()
    job = store.create_job(
        slots_manifest={"admission": {"can_proceed": True}, "current_script_revision": 1},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    rev1 = store.append_revision(job_id=job.job_id, kind="script", expected_version=1, manifest=manifest(1), invalidate_downstream=False, ttl_seconds=3600)
    rev2 = store.append_revision(job_id=job.job_id, kind="script", expected_version=rev1.version, manifest=manifest(2, "c" * 64), invalidate_downstream=False, ttl_seconds=3600)
    with pytest.raises(ApprovalStaleError):
        store.approve_revision(job_id=job.job_id, kind="script", revision=1, expected_version=rev2.version, expected_sha256="b" * 64, ttl_seconds=3600)


def test_expected_version_must_be_positive_for_revision_methods():
    store, _ = make_store()
    job = create_job(store)
    with pytest.raises(ReplicationError):
        store.append_revision(job_id=job.job_id, kind="script", expected_version=0, manifest=manifest(1), invalidate_downstream=False, ttl_seconds=3600)
    with pytest.raises(ReplicationError):
        store.approve_revision(job_id=job.job_id, kind="script", revision=1, expected_version=0, expected_sha256="b" * 64, ttl_seconds=3600)


def test_append_future_expected_version_rejects_read_advance(monkeypatch):
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
        store.append_revision(job_id=job.job_id, kind="script", expected_version=2, manifest=manifest(1), invalidate_downstream=False, ttl_seconds=3600)
    raw = store.redis.hget(f"{store.prefix}:{job.job_id}:job", "snapshot")
    assert json.loads(raw)["version"] == int(store.redis.hget(f"{store.prefix}:{job.job_id}:job", "version"))


def test_approve_future_expected_version_rejects_read_advance(monkeypatch):
    store, redis_client = make_store()
    other = RedisEphemeralJobStore(redis_client, prefix=store.prefix)
    job = create_job(store)
    appended = store.append_revision(job_id=job.job_id, kind="script", expected_version=1, manifest=manifest(1), invalidate_downstream=False, ttl_seconds=3600)
    original = store._require_snapshot
    injected = False

    def read_then_advance(job_id):
        nonlocal injected
        snapshot = original(job_id)
        if not injected:
            injected = True
            other.cas_transition(job_id=job_id, expected_version=appended.version, command="advance", ttl_seconds=3600)
        return snapshot

    monkeypatch.setattr(store, "_require_snapshot", read_then_advance)
    with pytest.raises(StateConflictError):
        store.approve_revision(job_id=job.job_id, kind="script", revision=1, expected_version=appended.version + 1, expected_sha256="b" * 64, ttl_seconds=3600)
    raw = json.loads(redis_client.hget(f"{store.prefix}:{job.job_id}:job", "snapshot"))
    assert raw["version"] == int(redis_client.hget(f"{store.prefix}:{job.job_id}:job", "version"))


def test_append_is_fenced_by_active_provider_attempt():
    store, _ = make_store()
    job = create_job(store)
    attempt = store.begin_provider_attempt(
        job_id=job.job_id,
        expected_version=1,
        operation="CreateVideo",
        request_sha256="c" * 64,
        segment_id="segment-1",
        segment_plan_sha256="d" * 64,
    )
    assert attempt.status == "SUBMITTING"
    with pytest.raises(ReplicationError) as raised:
        store.append_revision(job_id=job.job_id, kind="script", expected_version=2, manifest=manifest(1), invalidate_downstream=True, ttl_seconds=3600)
    assert raised.value.code == "REVISION_CONFLICT"
    assert raised.value.http_status == 409


def test_append_can_continue_after_provider_attempt_is_terminal():
    store, _ = make_store()
    job = create_job(store)
    attempt = store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateAsset", request_sha256="c" * 64)
    snapshot = store.get_job(job.job_id)
    assert snapshot is not None
    terminal = attempt.__class__(**{**attempt.to_dict(), "status": "SUCCEEDED"})
    updated = store.update_provider_attempt(job_id=job.job_id, expected_version=snapshot.version, attempt=terminal, ttl_seconds=3600)
    appended = store.append_revision(job_id=job.job_id, kind="script", expected_version=updated.version, manifest=manifest(1), invalidate_downstream=False, ttl_seconds=3600)
    assert appended.current_script_revision == 1
