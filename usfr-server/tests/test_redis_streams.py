from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import fakeredis
import pytest

from server.errors import IdempotencyConflictError, ReplicationError
from server.job_models import WorkMessage
from server.redis_job_store import RedisEphemeralJobStore
from server.redis_streams import RedisWorkQueue, WorkDelivery


@pytest.fixture
def redis_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=False)


@pytest.fixture
def queue(redis_client: fakeredis.FakeRedis) -> RedisWorkQueue:
    return RedisWorkQueue(redis_client, prefix=f"test-{uuid.uuid4().hex}")


def _args(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "job_id": "job-1",
        "stage": "probe_source",
        "expected_version": 2,
        "dedupe_key": "d" * 64,
    }
    values.update(overrides)
    return values


def test_constructor_creates_group_idempotently(redis_client: fakeredis.FakeRedis) -> None:
    prefix = f"group-{uuid.uuid4().hex}"
    first = RedisWorkQueue(redis_client, prefix=prefix)
    message_id = first.enqueue(**_args())
    delivery = first.read(consumer="worker-1")[0]
    second = RedisWorkQueue(redis_client, prefix=prefix)
    assert second.read(consumer="worker-2") == ()
    assert second.pending_count() == 1
    assert delivery.message_id == message_id


def test_enqueue_stores_exact_four_fields_and_rejects_invalid_inputs(queue: RedisWorkQueue) -> None:
    message_id = queue.enqueue(**_args())
    raw = queue.redis.xrange(queue.stream_key, message_id, message_id)
    assert len(raw) == 1
    assert set(raw[0][1]) == {b"job_id", b"stage", b"expected_version", b"dedupe_key"}
    assert raw[0][1][b"job_id"] == b"job-1"
    assert raw[0][1][b"stage"] == b"probe_source"
    assert raw[0][1][b"expected_version"] == b"2"
    assert raw[0][1][b"dedupe_key"] == b"d" * 64

    invalid = (
        {"job_id": "", "stage": "probe_source", "expected_version": 2, "dedupe_key": "d" * 64},
        {"job_id": "job*1", "stage": "probe_source", "expected_version": 2, "dedupe_key": "d" * 64},
        {"job_id": "job-1", "stage": "bad stage", "expected_version": 2, "dedupe_key": "d" * 64},
        {"job_id": "job-1", "stage": "probe_source", "expected_version": True, "dedupe_key": "d" * 64},
        {"job_id": "job-1", "stage": "probe_source", "expected_version": 0, "dedupe_key": "d" * 64},
        {"job_id": "job-1", "stage": "probe_source", "expected_version": 2, "dedupe_key": ""},
    )
    for values in invalid:
        with pytest.raises(ReplicationError):
            queue.enqueue(**values)


def test_enqueue_dedupe_is_idempotent_and_conflicts_on_changed_message(queue: RedisWorkQueue) -> None:
    first = queue.enqueue(**_args())
    assert queue.enqueue(**_args()) == first
    with pytest.raises(IdempotencyConflictError):
        queue.enqueue(**_args(stage="render_video"))
    assert queue.redis.xlen(queue.stream_key) == 1


def test_read_returns_immutable_delivery_without_ack(queue: RedisWorkQueue) -> None:
    message_id = queue.enqueue(**_args())
    deliveries = queue.read(consumer="worker-1", count=1, block_ms=1)
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert isinstance(delivery, WorkDelivery)
    assert delivery.message_id == message_id
    assert delivery.message == WorkMessage("job-1", "probe_source", 2, "d" * 64)
    with pytest.raises((AttributeError, TypeError)):
        delivery.message_id = "other"  # type: ignore[misc]
    assert queue.pending_count() == 1


def test_ack_cleans_stream_and_dedupe_indexes(queue: RedisWorkQueue) -> None:
    message_id = queue.enqueue(**_args())
    queue.read(consumer="worker-1", block_ms=1)
    assert queue.ack(message_id) is True
    assert queue.pending_count() == 0
    assert queue.redis.xrange(queue.stream_key, message_id, message_id) == []
    assert queue.redis.hget(queue.active_dedupe_key, "d" * 64) is None
    assert queue.redis.hget(queue.message_dedupe_key, message_id) is None
    assert queue.ack(message_id) is False
    assert queue.ack("9999999999999-0") is False


def test_ack_unknown_does_not_damage_another_message(queue: RedisWorkQueue) -> None:
    first = queue.enqueue(**_args(dedupe_key="a" * 64))
    second = queue.enqueue(**_args(job_id="job-2", dedupe_key="b" * 64))
    queue.read(consumer="worker-1", count=2, block_ms=1)
    assert queue.ack("9999999999999-0") is False
    assert queue.pending_count() == 2
    assert queue.ack(first) is True
    assert queue.pending_count() == 1
    assert queue.redis.hget(queue.active_dedupe_key, "b" * 64) == second.encode()


def test_ack_derives_dedupe_from_stream_when_reverse_index_is_missing(queue: RedisWorkQueue) -> None:
    message_id = queue.enqueue(**_args())
    queue.read(consumer="worker-1", block_ms=1)
    queue.redis.hdel(queue.message_dedupe_key, message_id)
    assert queue.ack(message_id) is True
    assert queue.pending_count() == 0
    assert queue.redis.hget(queue.active_dedupe_key, "d" * 64) is None
    assert queue.redis.hget(queue.message_dedupe_key, message_id) is None


def test_ack_corrupt_reverse_index_never_removes_another_dedupe(queue: RedisWorkQueue) -> None:
    first = queue.enqueue(**_args(dedupe_key="a" * 64))
    second = queue.enqueue(**_args(job_id="job-2", dedupe_key="b" * 64))
    queue.read(consumer="worker-1", count=2, block_ms=1)
    queue.redis.hset(queue.message_dedupe_key, first, "b" * 64)
    assert queue.ack(first) is True
    assert queue.pending_count() == 1
    assert queue.redis.xrange(queue.stream_key, first, first) == []
    assert queue.redis.hget(queue.active_dedupe_key, "a" * 64) is None
    assert queue.redis.hget(queue.active_dedupe_key, "b" * 64) == second.encode()
    assert queue.redis.hget(queue.message_dedupe_key, first) is None


def test_ack_deleted_stream_entry_can_clear_pending_ghost(queue: RedisWorkQueue) -> None:
    message_id = queue.enqueue(**_args())
    queue.read(consumer="worker-1", block_ms=1)
    queue.redis.xdel(queue.stream_key, message_id)
    assert queue.ack(message_id) is True
    assert queue.pending_count() == 0
    assert queue.redis.hget(queue.active_dedupe_key, "d" * 64) is None
    assert queue.redis.hget(queue.message_dedupe_key, message_id) is None


def test_ack_orphan_reverse_unknown_id_does_not_remove_any_mapping(queue: RedisWorkQueue) -> None:
    orphan_id = "9999999999999-0"
    queue.redis.hset(queue.message_dedupe_key, orphan_id, "orphan")
    queue.redis.hset(queue.active_dedupe_key, "orphan", orphan_id)
    assert queue.ack(orphan_id) is False
    assert queue.redis.hget(queue.message_dedupe_key, orphan_id) == b"orphan"
    assert queue.redis.hget(queue.active_dedupe_key, "orphan") == orphan_id.encode()


def test_ack_rejects_corrupt_existing_entry_without_ack(queue: RedisWorkQueue) -> None:
    bad_id = queue.redis.xadd(queue.stream_key, {"job_id": "job-1", "unexpected": "payload"})
    queue.redis.xreadgroup(queue.group, "worker-1", {queue.stream_key: ">"}, count=1, block=None)
    queue.redis.hset(queue.message_dedupe_key, bad_id, "d" * 64)
    queue.redis.hset(queue.active_dedupe_key, "d" * 64, bad_id)
    with pytest.raises(ReplicationError) as exc_info:
        queue.ack(bad_id.decode())
    assert exc_info.value.code == "QUEUE_CORRUPT"
    assert queue.pending_count() == 1


def test_ack_rejects_existing_entry_with_unsafe_stage_without_ack(queue: RedisWorkQueue) -> None:
    bad_id = queue.redis.xadd(queue.stream_key, {
        "job_id": "job-1",
        "stage": "bad stage",
        "expected_version": "1",
        "dedupe_key": "d" * 64,
    })
    queue.redis.xreadgroup(queue.group, "worker-1", {queue.stream_key: ">"}, count=1, block=None)
    with pytest.raises(ReplicationError) as exc_info:
        queue.ack(bad_id.decode())
    assert exc_info.value.code == "QUEUE_CORRUPT"
    assert queue.pending_count() == 1


def test_promote_due_preflights_entire_batch_before_mutating(queue: RedisWorkQueue) -> None:
    first_dedupe = "a" * 64
    second_dedupe = "b" * 64
    assert queue.schedule(**_args(job_id="first", dedupe_key=first_dedupe), due_at_ms=10)
    assert queue.schedule(**_args(job_id="second", dedupe_key=second_dedupe), due_at_ms=10)
    conflicting_id = queue.enqueue(job_id="wrong", stage="other", expected_version=9, dedupe_key=second_dedupe)
    before_stream = queue.redis.xlen(queue.stream_key)
    before_active = queue.redis.hgetall(queue.active_dedupe_key)
    with pytest.raises(IdempotencyConflictError):
        queue.promote_due(now_ms=10, limit=10)
    assert queue.redis.xlen(queue.stream_key) == before_stream
    assert queue.redis.hgetall(queue.active_dedupe_key) == before_active
    assert queue.redis.zrange(queue.scheduled_key, 0, -1) == [first_dedupe.encode(), second_dedupe.encode()]
    assert queue.redis.hget(queue.active_dedupe_key, second_dedupe) == conflicting_id.encode()

    queue.read(consumer="worker-1", count=1, block_ms=1)
    assert queue.ack(conflicting_id)
    promoted = queue.promote_due(now_ms=10, limit=10)
    assert len(promoted) == 2
    assert queue.redis.xlen(queue.stream_key) == 2


def test_schedule_rebuilds_stale_zset_only_and_partial_sidecars(queue: RedisWorkQueue) -> None:
    dedupe = "z" * 64
    queue.redis.zadd(queue.scheduled_key, {dedupe: 1})
    assert queue.schedule(**_args(dedupe_key=dedupe), due_at_ms=5) is True
    assert queue.redis.zscore(queue.scheduled_key, dedupe) == 5
    assert queue.redis.hget(queue.scheduled_data_key, f"@job:{dedupe}") == b"job-1"

    dedupe_partial = "p" * 64
    queue.redis.zadd(queue.scheduled_key, {dedupe_partial: 2})
    queue.redis.hset(queue.scheduled_data_key, f"@job:{dedupe_partial}", "old")
    assert queue.schedule(**_args(dedupe_key=dedupe_partial), due_at_ms=6) is True
    assert queue.redis.zscore(queue.scheduled_key, dedupe_partial) == 6
    assert queue.redis.hget(queue.scheduled_data_key, f"@stage:{dedupe_partial}") == b"probe_source"


def test_schedule_sidecar_only_is_rebuilt(queue: RedisWorkQueue) -> None:
    dedupe = "s" * 64
    queue.redis.hset(queue.scheduled_data_key, f"@job:{dedupe}", "old")
    assert queue.schedule(**_args(dedupe_key=dedupe), due_at_ms=7) is True
    assert queue.redis.zscore(queue.scheduled_key, dedupe) == 7
    assert queue.redis.hget(queue.scheduled_data_key, f"@due:{dedupe}") == b"7"


def test_read_checkpoint_then_explicit_ack_contract() -> None:
    redis_client = fakeredis.FakeRedis(decode_responses=False)
    prefix = f"checkpoint-{uuid.uuid4().hex}"
    store = RedisEphemeralJobStore(redis_client, prefix=prefix)
    queue = RedisWorkQueue(redis_client, prefix=prefix)
    snapshot = store.create_job(
        slots_manifest={"admission": {"can_proceed": True}},
        capability_token_hash="a" * 64,
        ttl_seconds=60,
    )
    dedupe = "c" * 64
    store.claim_stage(job_id=snapshot.job_id, stage="probe_source", dedupe_key=dedupe, owner="worker-1", ttl_seconds=60)
    message_id = queue.enqueue(job_id=snapshot.job_id, stage="probe_source", expected_version=2, dedupe_key=dedupe)
    delivery = queue.read(consumer="worker-1", block_ms=1)[0]
    assert delivery.message_id == message_id
    assert queue.pending_count() == 1
    store.complete_stage(
        job_id=snapshot.job_id,
        stage="probe_source",
        dedupe_key=dedupe,
        owner="worker-1",
        output_artifact_ids=(),
        ttl_seconds=60,
    )
    assert queue.ack(message_id) is True
    assert queue.pending_count() == 0


def test_promote_concurrent_queue_instances_emit_one_message() -> None:
    redis_client = fakeredis.FakeRedis(decode_responses=False)
    prefix = f"race-{uuid.uuid4().hex}"
    first = RedisWorkQueue(redis_client, prefix=prefix)
    second = RedisWorkQueue(redis_client, prefix=prefix)
    dedupe = "r" * 64
    assert first.schedule(**_args(dedupe_key=dedupe), due_at_ms=1)

    def promote(queue_instance: RedisWorkQueue) -> tuple[str, ...]:
        return queue_instance.promote_due(now_ms=1, limit=10)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(promote, (first, second)))
    assert sorted(sum((list(result) for result in results), []))
    assert sum(len(result) for result in results) == 1
    assert redis_client.xlen(first.stream_key) == 1


def test_promote_rejects_malformed_sidecar_without_mutation(queue: RedisWorkQueue) -> None:
    dedupe = "m" * 64
    assert queue.schedule(**_args(dedupe_key=dedupe), due_at_ms=1)
    queue.redis.hset(queue.scheduled_data_key, f"@version:{dedupe}", "not-an-integer")
    with pytest.raises(ReplicationError):
        queue.promote_due(now_ms=1, limit=10)
    assert queue.redis.xlen(queue.stream_key) == 0
    assert queue.redis.zrange(queue.scheduled_key, 0, -1) == [dedupe.encode()]


def test_promote_cleans_stale_active_index_and_recreates_message(queue: RedisWorkQueue) -> None:
    dedupe = "t" * 64
    stale_id = queue.enqueue(**_args(dedupe_key=dedupe))
    queue.redis.xdel(queue.stream_key, stale_id)
    assert queue.schedule(**_args(dedupe_key=dedupe), due_at_ms=1)
    promoted = queue.promote_due(now_ms=1, limit=10)
    assert len(promoted) == 1
    assert promoted[0] != stale_id


def test_schedule_and_promote_reject_integer_precision_overflow(queue: RedisWorkQueue) -> None:
    safe = 2**53
    assert queue.schedule(**_args(dedupe_key="u" * 64), due_at_ms=safe)
    with pytest.raises(ReplicationError):
        queue.schedule(**_args(dedupe_key="v" * 64), due_at_ms=safe + 1)
    with pytest.raises(ReplicationError):
        queue.promote_due(now_ms=safe + 1, limit=1)


def test_stream_id_fence_compares_large_decimal_components_without_float_rounding(queue: RedisWorkQueue) -> None:
    queue.redis.set(queue.last_id_key, "9007199254740991-0")
    message_id = queue.enqueue(**_args(dedupe_key="w" * 64))
    assert message_id == "9007199254740991-1"


def test_idempotency_conflict_details_are_flat(queue: RedisWorkQueue) -> None:
    queue.enqueue(**_args())
    with pytest.raises(IdempotencyConflictError) as exc_info:
        queue.enqueue(**_args(stage="other"))
    assert exc_info.value.details["dedupe_key"] == "d" * 64


def test_dedupe_can_be_reused_after_ack(queue: RedisWorkQueue) -> None:
    first = queue.enqueue(**_args())
    queue.read(consumer="worker-1", block_ms=1)
    assert queue.ack(first)
    second = queue.enqueue(**_args())
    assert second != first


def test_reclaim_moves_idle_pending_entry_without_ack(queue: RedisWorkQueue) -> None:
    message_id = queue.enqueue(**_args())
    queue.read(consumer="worker-1", block_ms=1)
    time.sleep(0.02)
    reclaimed = queue.reclaim(consumer="worker-2", min_idle_ms=1, count=1)
    assert len(reclaimed) == 1
    assert reclaimed[0].message_id == message_id
    assert reclaimed[0].message == WorkMessage("job-1", "probe_source", 2, "d" * 64)
    assert queue.pending_count() == 1
    assert queue.reclaim(consumer="worker-3", min_idle_ms=1000, count=1) == ()


def test_schedule_is_idempotent_and_conflicts_on_changed_content(queue: RedisWorkQueue) -> None:
    assert queue.schedule(**_args(), due_at_ms=100) is True
    assert queue.schedule(**_args(), due_at_ms=100) is False
    with pytest.raises(IdempotencyConflictError):
        queue.schedule(**_args(stage="other_stage"), due_at_ms=101)


def test_promote_due_orders_and_deduplicates(queue: RedisWorkQueue) -> None:
    assert queue.schedule(**_args(job_id="job-2", dedupe_key="b" * 64), due_at_ms=10)
    assert queue.schedule(**_args(job_id="job-1", dedupe_key="a" * 64), due_at_ms=10)
    assert queue.schedule(**_args(job_id="job-3", dedupe_key="c" * 64), due_at_ms=20)
    first = queue.promote_due(now_ms=10, limit=10)
    assert len(first) == 2
    assert queue.redis.zcard(queue.scheduled_key) == 1
    assert queue.promote_due(now_ms=10, limit=10) == ()
    assert queue.redis.xlen(queue.stream_key) == 2
    assert queue.redis.hget(queue.active_dedupe_key, "a" * 64) == first[0].encode()
    assert queue.redis.hget(queue.active_dedupe_key, "b" * 64) == first[1].encode()


def test_promote_reuses_identical_active_message_and_conflicts_different_active(queue: RedisWorkQueue) -> None:
    active = queue.enqueue(**_args())
    assert queue.schedule(**_args(), due_at_ms=1) is True
    assert queue.promote_due(now_ms=1, limit=10) == (active,)
    assert queue.redis.xlen(queue.stream_key) == 1

    assert queue.schedule(**_args(job_id="other"), due_at_ms=2) is True
    with pytest.raises(IdempotencyConflictError):
        queue.promote_due(now_ms=2, limit=10)
    assert queue.redis.zcard(queue.scheduled_key) == 1


def test_pending_count_handles_empty_group(queue: RedisWorkQueue) -> None:
    assert queue.pending_count() == 0


def test_queue_entries_do_not_contain_forbidden_payload_fields(queue: RedisWorkQueue) -> None:
    message_id = queue.enqueue(**_args())
    fields = queue.redis.xrange(queue.stream_key, message_id, message_id)[0][1]
    forbidden = {b"tenant_id", b"user_id", b"script", b"prompt", b"payload", b"media", b"token", b"event", b"artifact"}
    assert set(fields).isdisjoint(forbidden)
