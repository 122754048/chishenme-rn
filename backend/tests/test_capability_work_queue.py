from dataclasses import dataclass

from app.capability_work_queue import CapabilityRoutedWorkQueue, RedisCapabilityCapacityGate


@dataclass(frozen=True)
class _Message:
    job_id: str
    stage: str
    expected_version: int
    dedupe_key: str


@dataclass(frozen=True)
class _Delivery:
    message_id: str
    message: _Message


class _Queue:
    def __init__(self):
        self.enqueued = []
        self.deliveries = []
        self.acked = []
        self.reclaimed = []

    def enqueue(self, **message):
        self.enqueued.append(message)
        return f"entry-{len(self.enqueued)}"

    def read(self, *, consumer, count, block_ms):
        del consumer, count, block_ms
        deliveries, self.deliveries = self.deliveries, []
        return tuple(deliveries)

    def reclaim(self, *, consumer, min_idle_ms, count):
        del consumer, min_idle_ms, count
        deliveries, self.reclaimed = self.reclaimed, []
        return tuple(deliveries)

    def ack(self, message_id):
        self.acked.append(message_id)
        return True


class _CapacityRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, *, nx=False, px=None):
        del px
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def eval(self, _script, _numkeys, key, token):
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1


def _queues():
    return {
        name: _Queue()
        for name in (
            "probe_dynamics",
            "asr_localization",
            "storyboard_generation",
            "provider_poll",
            "assembly_qc",
        )
    }


def test_capability_routed_queue_sends_standard_stage_messages_to_their_worker_queue():
    queues = _queues()
    routed = CapabilityRoutedWorkQueue(queues)

    routed.enqueue(job_id="job-1", stage="analyze_dynamics", expected_version=2, dedupe_key="probe-key")
    routed.enqueue(job_id="job-1", stage="build_script", expected_version=3, dedupe_key="asr-key")
    routed.enqueue(job_id="job-1", stage="generate_storyboards", expected_version=4, dedupe_key="boards-key")
    routed.enqueue(job_id="job-1", stage="wait_provider_video", expected_version=5, dedupe_key="poll-key")
    routed.enqueue(job_id="job-1", stage="run_qc", expected_version=6, dedupe_key="qc-key")

    assert [queue.enqueued[0]["stage"] for queue in queues.values()] == [
        "analyze_dynamics",
        "build_script",
        "generate_storyboards",
        "wait_provider_video",
        "run_qc",
    ]


def test_capability_routed_queue_reads_only_the_assigned_worker_capability_and_acks_the_origin_queue():
    queues = _queues()
    queues["probe_dynamics"].deliveries.append(
        _Delivery("1-0", _Message("job-probe", "analyze_dynamics", 2, "probe-key"))
    )
    queues["provider_poll"].deliveries.append(
        _Delivery("2-0", _Message("job-poll", "wait_provider_video", 3, "poll-key"))
    )
    routed = CapabilityRoutedWorkQueue(queues, worker_capability="provider_poll")

    deliveries = routed.read(consumer="worker-a", count=1, block_ms=0)

    assert [(delivery.message_id, delivery.message.job_id) for delivery in deliveries] == [
        ("provider_poll|2-0", "job-poll")
    ]
    assert queues["probe_dynamics"].deliveries[0].message.job_id == "job-probe"
    assert routed.ack("provider_poll|2-0") is True
    assert queues["provider_poll"].acked == ["2-0"]


def test_capability_routed_queue_exposes_per_capability_concurrency_controls():
    routed = CapabilityRoutedWorkQueue(_queues())

    routed.capability_controls["assembly_qc"].set_concurrency_limit(4)

    assert routed.concurrency_limits == {"assembly_qc": 4}


def test_redis_capacity_gate_limits_two_worker_replicas_and_releases_only_after_ack():
    redis = _CapacityRedis()
    gate = RedisCapabilityCapacityGate(redis, prefix="usfr:commercial:capacity", lease_ms=60_000)
    first_queues = _queues()
    second_queues = _queues()
    first_queues["probe_dynamics"].deliveries.append(
        _Delivery("1-0", _Message("job-one", "analyze_dynamics", 2, "probe-one"))
    )
    second_queues["probe_dynamics"].deliveries.append(
        _Delivery("2-0", _Message("job-two", "analyze_dynamics", 2, "probe-two"))
    )
    first_worker = CapabilityRoutedWorkQueue(
        first_queues,
        worker_capability="probe_dynamics",
        capacity_gate=gate,
    )
    second_worker = CapabilityRoutedWorkQueue(
        second_queues,
        worker_capability="probe_dynamics",
        capacity_gate=gate,
    )
    first_worker.set_concurrency_limit("probe_dynamics", 1)
    second_worker.set_concurrency_limit("probe_dynamics", 1)

    first = first_worker.read(consumer="worker-one", count=1)
    blocked = second_worker.read(consumer="worker-two", count=1)

    assert [delivery.message_id for delivery in first] == ["probe_dynamics|1-0"]
    assert blocked == ()
    assert first_worker.ack("probe_dynamics|1-0") is True

    released = second_worker.read(consumer="worker-two", count=1)

    assert [delivery.message_id for delivery in released] == ["probe_dynamics|2-0"]
