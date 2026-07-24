from __future__ import annotations

import json
import uuid

import fakeredis
import pytest

from server.errors import IdempotencyConflictError, ReplicationError, RevisionConflictError, StateConflictError
from server.job_models import ProviderAttempt
from server.redis_job_store import RedisEphemeralJobStore


def make_store():
    client = fakeredis.FakeRedis(decode_responses=False)
    return RedisEphemeralJobStore(client, prefix=f"provider-{uuid.uuid4().hex}"), client


def create_job(store):
    return store.create_job(
        slots_manifest={"admission": {"can_proceed": True}},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )


def test_begin_persists_submitting_and_exact_segment_identity():
    store, client = make_store()
    job = create_job(store)
    attempt = store.begin_provider_attempt(
        job_id=job.job_id,
        expected_version=1,
        operation="CreateVideo",
        request_sha256="b" * 64,
        segment_id="seg-07",
        segment_plan_sha256="c" * 64,
    )
    assert attempt.status == "SUBMITTING"
    assert attempt.attempt_id
    raw = client.hget(f"{store.prefix}:{job.job_id}:providers", attempt.attempt_id)
    assert raw is not None
    assert json.loads(raw) == attempt.to_dict()
    assert client.zcard(f"{store.prefix}:provider:due") == 1


def test_duplicate_active_pair_is_rejected_but_terminal_attempt_can_repeat():
    store, _ = make_store()
    job = create_job(store)
    first = store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="b" * 64, segment_id="seg", segment_plan_sha256="c" * 64)
    snapshot = store.get_job(job.job_id)
    assert snapshot is not None
    with pytest.raises(IdempotencyConflictError):
        store.begin_provider_attempt(job_id=job.job_id, expected_version=snapshot.version, operation="CreateVideo", request_sha256="b" * 64, segment_id="seg", segment_plan_sha256="c" * 64)
    terminal = ProviderAttempt(**{**first.to_dict(), "status": "SUCCEEDED"})
    updated = store.update_provider_attempt(job_id=job.job_id, expected_version=snapshot.version, attempt=terminal, ttl_seconds=3600)
    second = store.begin_provider_attempt(job_id=job.job_id, expected_version=updated.version, operation="CreateVideo", request_sha256="b" * 64, segment_id="seg", segment_plan_sha256="c" * 64)
    assert second.attempt_id != first.attempt_id


def test_provider_update_requires_version_and_preserves_immutable_identity():
    store, _ = make_store()
    job = create_job(store)
    first = store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateAsset", request_sha256="b" * 64, segment_id="seg", segment_plan_sha256="c" * 64)
    current = store.get_job(job.job_id)
    assert current is not None
    running = ProviderAttempt(**{**first.to_dict(), "status": "RUNNING", "provider_task_id": "task-1"})
    updated = store.update_provider_attempt(job_id=job.job_id, expected_version=current.version, attempt=running, ttl_seconds=3600)
    assert updated.version == current.version + 1
    assert store.get_job(job.job_id) is not None
    stale = ProviderAttempt(**{**running.to_dict(), "status": "FAILED", "attempt_id": "other"})
    with pytest.raises(StateConflictError):
        store.update_provider_attempt(job_id=job.job_id, expected_version=updated.version, attempt=stale, ttl_seconds=3600)
    with pytest.raises(StateConflictError):
        store.update_provider_attempt(job_id=job.job_id, expected_version=current.version, attempt=running, ttl_seconds=3600)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("operation", "CreateVideo"),
        ("request_sha256", "d" * 64),
        ("segment_id", "other-segment"),
        ("segment_plan_sha256", "e" * 64),
    ),
)
def test_provider_update_rejects_each_immutable_identity_change(field, replacement):
    store, client = make_store()
    job = create_job(store)
    first = store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateAsset", request_sha256="b" * 64, segment_id="seg", segment_plan_sha256="c" * 64)
    changed = dict(first.to_dict())
    changed[field] = replacement
    if field == "segment_id":
        changed["segment_plan_sha256"] = "e" * 64
    if field == "segment_plan_sha256":
        changed["segment_id"] = "other-segment"
    with pytest.raises(StateConflictError):
        store.update_provider_attempt(job_id=job.job_id, expected_version=2, attempt=ProviderAttempt(**changed), ttl_seconds=3600)
    assert json.loads(client.hget(f"{store.prefix}:{job.job_id}:providers", first.attempt_id)) == first.to_dict()


def test_terminal_attempt_cannot_reopen_or_create_second_active_due_entry():
    store, client = make_store()
    job = create_job(store)
    first = store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="b" * 64, segment_id="seg", segment_plan_sha256="c" * 64)
    terminal = ProviderAttempt(**{**first.to_dict(), "status": "SUCCEEDED"})
    after_terminal = store.update_provider_attempt(job_id=job.job_id, expected_version=2, attempt=terminal, ttl_seconds=3600)
    second = store.begin_provider_attempt(job_id=job.job_id, expected_version=after_terminal.version, operation="CreateVideo", request_sha256="b" * 64, segment_id="seg", segment_plan_sha256="c" * 64)
    with pytest.raises(StateConflictError):
        store.update_provider_attempt(
            job_id=job.job_id,
            expected_version=after_terminal.version + 1,
            attempt=ProviderAttempt(**{**first.to_dict(), "status": "RUNNING"}),
            ttl_seconds=3600,
        )
    stored_first = json.loads(client.hget(f"{store.prefix}:{job.job_id}:providers", first.attempt_id))
    stored_second = json.loads(client.hget(f"{store.prefix}:{job.job_id}:providers", second.attempt_id))
    assert stored_first["status"] == "SUCCEEDED"
    assert stored_second["status"] == "SUBMITTING"
    assert client.zcard(f"{store.prefix}:provider:due") == 1


def test_terminal_identical_update_is_idempotent_without_version_or_ttl_change():
    store, _ = make_store()
    job = create_job(store)
    first = store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateAsset", request_sha256="b" * 64)
    terminal = ProviderAttempt(**{**first.to_dict(), "status": "FAILED"})
    after = store.update_provider_attempt(job_id=job.job_id, expected_version=2, attempt=terminal, ttl_seconds=3600)
    replay = store.update_provider_attempt(job_id=job.job_id, expected_version=after.version, attempt=terminal, ttl_seconds=1)
    assert replay == after


def test_provider_expected_version_must_be_positive():
    store, _ = make_store()
    job = create_job(store)
    with pytest.raises(ReplicationError):
        store.begin_provider_attempt(job_id=job.job_id, expected_version=0, operation="CreateAsset", request_sha256="b" * 64)


def test_provider_begin_future_expected_version_rejects_read_advance(monkeypatch):
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
        store.begin_provider_attempt(job_id=job.job_id, expected_version=2, operation="CreateAsset", request_sha256="b" * 64)
    raw = json.loads(redis_client.hget(f"{store.prefix}:{job.job_id}:job", "snapshot"))
    assert raw["version"] == int(redis_client.hget(f"{store.prefix}:{job.job_id}:job", "version"))


def test_provider_update_future_expected_version_rejects_read_advance(monkeypatch):
    store, redis_client = make_store()
    other = RedisEphemeralJobStore(redis_client, prefix=store.prefix)
    job = create_job(store)
    first = store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateAsset", request_sha256="b" * 64)
    attempt = ProviderAttempt(**{**first.to_dict(), "status": "RUNNING"})
    original = store._require_snapshot
    injected = False

    def read_then_advance(job_id):
        nonlocal injected
        snapshot = original(job_id)
        if not injected:
            injected = True
            other.cas_transition(job_id=job_id, expected_version=2, command="advance", ttl_seconds=3600)
        return snapshot

    monkeypatch.setattr(store, "_require_snapshot", read_then_advance)
    with pytest.raises(StateConflictError):
        store.update_provider_attempt(job_id=job.job_id, expected_version=3, attempt=attempt, ttl_seconds=3600)
    raw = json.loads(redis_client.hget(f"{store.prefix}:{job.job_id}:job", "snapshot"))
    assert raw["version"] == int(redis_client.hget(f"{store.prefix}:{job.job_id}:job", "version"))


def test_ambiguous_attempt_survives_new_store_and_fences_revision():
    store, client = make_store()
    job = create_job(store)
    attempt = store.begin_provider_attempt(job_id=job.job_id, expected_version=1, operation="CreateVideo", request_sha256="b" * 64, segment_id="seg", segment_plan_sha256="c" * 64)
    current = store.get_job(job.job_id)
    assert current is not None
    ambiguous = ProviderAttempt(**{**attempt.to_dict(), "status": "AMBIGUOUS"})
    store.update_provider_attempt(job_id=job.job_id, expected_version=current.version, attempt=ambiguous, ttl_seconds=3600)
    restarted = RedisEphemeralJobStore(client, prefix=store.prefix)
    persisted = restarted.get_job(job.job_id)
    assert persisted is not None
    persisted_attempt = client.hget(f"{store.prefix}:{job.job_id}:providers", attempt.attempt_id)
    assert json.loads(persisted_attempt)["status"] == "AMBIGUOUS"
    with pytest.raises(RevisionConflictError):
        restarted.append_revision(job_id=job.job_id, kind="script", expected_version=persisted.version, manifest={"revision": 1, "sha256": "d" * 64}, invalidate_downstream=True, ttl_seconds=3600)
