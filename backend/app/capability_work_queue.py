"""Route existing USFR work messages onto deployment-owned capability queues."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
import uuid


CAPABILITY_QUEUES = (
    "probe_dynamics",
    "asr_localization",
    "storyboard_generation",
    "provider_poll",
    "assembly_qc",
)

_STAGE_CAPABILITY = {
    "bind_inputs": "probe_dynamics",
    "probe_source": "probe_dynamics",
    "analyze_dynamics": "probe_dynamics",
    "route_regions": "probe_dynamics",
    "parse_app_store_evidence": "probe_dynamics",
    "resolve_ui_evidence": "probe_dynamics",
    "build_script": "asr_localization",
    "segment_plan": "storyboard_generation",
    "generate_storyboards": "storyboard_generation",
    "compile_seedance20_prompt": "storyboard_generation",
    "audit_seedance_request": "storyboard_generation",
    "submit_provider_video": "storyboard_generation",
    "wait_provider_video": "provider_poll",
    "splice_timeline": "assembly_qc",
    "run_qc": "assembly_qc",
}


@dataclass(frozen=True)
class RoutedWorkDelivery:
    """A canonical delivery with enough origin information to ACK safely."""

    message_id: str
    message: Any


@dataclass(frozen=True)
class _CapacityLease:
    capability: str
    slot_key: str
    token: str


_RELEASE_CAPACITY_LEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisCapabilityCapacityGate:
    """Shared Redis lease slots enforcing limits across Worker replicas."""

    def __init__(self, redis_client: Any, *, prefix: str, lease_ms: int) -> None:
        if not all(callable(getattr(redis_client, method, None)) for method in ("get", "set", "eval")):
            raise ValueError("CAPACITY_GATE_REDIS_REQUIRED")
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError("CAPACITY_GATE_PREFIX_INVALID")
        if isinstance(lease_ms, bool) or not isinstance(lease_ms, int) or lease_ms <= 0:
            raise ValueError("CAPACITY_GATE_LEASE_INVALID")
        self._redis = redis_client
        self._prefix = prefix.strip().rstrip(":")
        self._lease_ms = lease_ms
        self._limits: dict[str, int] = {}

    def configure(self, capability: str, limit: int) -> None:
        if capability not in CAPABILITY_QUEUES:
            raise ValueError("CAPABILITY_WORKER_INVALID")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("CAPABILITY_CONCURRENCY_INVALID")
        policy_key = self._policy_key(capability)
        try:
            created = self._redis.set(policy_key, str(limit), nx=True)
            observed = str(limit) if created else self._text(self._redis.get(policy_key))
        except Exception as error:
            raise ValueError("CAPACITY_GATE_UNAVAILABLE") from error
        if observed != str(limit):
            raise ValueError("CAPACITY_CONCURRENCY_POLICY_CONFLICT")
        self._limits[capability] = limit

    def acquire(self, capability: str) -> _CapacityLease | None:
        limit = self._limits.get(capability)
        if limit is None:
            raise ValueError("CAPACITY_CONCURRENCY_UNCONFIGURED")
        token = uuid.uuid4().hex
        try:
            for slot in range(limit):
                slot_key = self._slot_key(capability, slot)
                if self._redis.set(slot_key, token, nx=True, px=self._lease_ms):
                    return _CapacityLease(capability=capability, slot_key=slot_key, token=token)
        except Exception as error:
            raise ValueError("CAPACITY_GATE_UNAVAILABLE") from error
        return None

    def release(self, lease: _CapacityLease) -> bool:
        try:
            released = self._redis.eval(_RELEASE_CAPACITY_LEASE_LUA, 1, lease.slot_key, lease.token)
        except Exception as error:
            raise ValueError("CAPACITY_GATE_UNAVAILABLE") from error
        try:
            return int(released) == 1
        except (TypeError, ValueError) as error:
            raise ValueError("CAPACITY_GATE_UNAVAILABLE") from error

    def _policy_key(self, capability: str) -> str:
        return f"{self._prefix}:{capability}:limit"

    def _slot_key(self, capability: str, slot: int) -> str:
        return f"{self._prefix}:{capability}:slot:{slot}"

    @staticmethod
    def _text(value: object) -> str:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return str(value or "")


class CapabilityQueueControl:
    """Deployment configuration handle for one worker capability."""

    def __init__(self, routed_queue: "CapabilityRoutedWorkQueue", capability: str) -> None:
        self._routed_queue = routed_queue
        self._capability = capability

    def set_concurrency_limit(self, limit: int) -> None:
        self._routed_queue.set_concurrency_limit(self._capability, limit)


class CapabilityRoutedWorkQueue:
    """Multiplex existing WorkQueue ports without changing the USFR message schema."""

    def __init__(
        self,
        queues: Mapping[str, Any],
        *,
        worker_capability: str | None = None,
        capacity_gate: RedisCapabilityCapacityGate | None = None,
    ) -> None:
        missing = set(CAPABILITY_QUEUES) - set(queues)
        if missing:
            raise ValueError("CAPABILITY_WORK_QUEUE_MISSING")
        for name in CAPABILITY_QUEUES:
            queue = queues[name]
            if not all(callable(getattr(queue, method, None)) for method in ("enqueue", "read", "reclaim", "ack")):
                raise ValueError("CAPABILITY_WORK_QUEUE_INVALID")
        if worker_capability is not None and worker_capability not in CAPABILITY_QUEUES:
            raise ValueError("CAPABILITY_WORKER_INVALID")
        self._queues = {name: queues[name] for name in CAPABILITY_QUEUES}
        self._worker_capability = worker_capability
        self._capacity_gate = capacity_gate
        self._capacity_leases: dict[str, _CapacityLease] = {}
        self._read_cursor = 0
        self._concurrency_limits: dict[str, int] = {}
        self.capability_controls = {
            capability: CapabilityQueueControl(self, capability)
            for capability in CAPABILITY_QUEUES
        }

    @property
    def concurrency_limits(self) -> Mapping[str, int]:
        return dict(self._concurrency_limits)

    def set_concurrency_limit(self, capability: str, limit: int) -> None:
        if capability not in self._queues:
            raise ValueError("CAPABILITY_WORKER_INVALID")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("CAPABILITY_CONCURRENCY_INVALID")
        if self._capacity_gate is not None:
            self._capacity_gate.configure(capability, limit)
        self._concurrency_limits[capability] = limit

    @staticmethod
    def capability_for_stage(stage: str) -> str:
        try:
            return _STAGE_CAPABILITY[stage]
        except KeyError as error:
            raise ValueError("CAPABILITY_STAGE_UNSUPPORTED") from error

    def enqueue(
        self,
        *,
        job_id: str,
        stage: str,
        expected_version: int,
        dedupe_key: str,
    ) -> str:
        capability = self.capability_for_stage(stage)
        return self._queues[capability].enqueue(
            job_id=job_id,
            stage=stage,
            expected_version=expected_version,
            dedupe_key=dedupe_key,
        )

    def read(self, *, consumer: str, count: int = 1, block_ms: int = 0) -> tuple[RoutedWorkDelivery, ...]:
        return self._deliver("read", consumer=consumer, count=count, block_ms=block_ms)

    def reclaim(
        self,
        *,
        consumer: str,
        min_idle_ms: int,
        count: int = 10,
    ) -> tuple[RoutedWorkDelivery, ...]:
        return self._deliver(
            "reclaim",
            consumer=consumer,
            count=count,
            min_idle_ms=min_idle_ms,
        )

    def ack(self, message_id: str) -> bool:
        capability, separator, origin_message_id = str(message_id).partition("|")
        if not separator or capability not in self._queues or not origin_message_id:
            raise ValueError("CAPABILITY_WORK_MESSAGE_ID_INVALID")
        lease = self._capacity_leases.get(str(message_id))
        if self._capacity_gate is not None and lease is None:
            raise ValueError("CAPACITY_LEASE_UNKNOWN")
        acknowledged = bool(self._queues[capability].ack(origin_message_id))
        if acknowledged and lease is not None:
            self._capacity_gate.release(lease)
            self._capacity_leases.pop(str(message_id), None)
        return acknowledged

    def _deliver(self, operation: str, *, consumer: str, count: int, **kwargs: int) -> tuple[RoutedWorkDelivery, ...]:
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("CAPABILITY_WORK_COUNT_INVALID")
        if self._capacity_gate is not None:
            return self._deliver_with_capacity(
                operation,
                consumer=consumer,
                count=count,
                **kwargs,
            )
        names = self._read_names()
        deliveries: list[RoutedWorkDelivery] = []
        for index, capability in enumerate(names):
            remaining = count - len(deliveries)
            if remaining <= 0:
                break
            queue = self._queues[capability]
            options = {"consumer": consumer, "count": remaining, **kwargs}
            if operation == "read":
                options["block_ms"] = kwargs.get("block_ms", 0) if index == 0 else 0
            raw = getattr(queue, operation)(**options)
            for delivery in raw:
                message_id = str(getattr(delivery, "message_id", "") or "")
                message = getattr(delivery, "message", None)
                if not message_id or message is None:
                    raise ValueError("CAPABILITY_WORK_DELIVERY_INVALID")
                routed_message_id = f"{capability}|{message_id}"
                if self._capacity_gate is not None:
                    lease = self._capacity_gate.acquire(capability)
                    if lease is None:
                        continue
                    self._capacity_leases[routed_message_id] = lease
                deliveries.append(RoutedWorkDelivery(routed_message_id, message))
                if len(deliveries) == count:
                    break
        return tuple(deliveries)

    def _deliver_with_capacity(
        self,
        operation: str,
        *,
        consumer: str,
        count: int,
        **kwargs: int,
    ) -> tuple[RoutedWorkDelivery, ...]:
        """Acquire a shared slot before reading so capped messages stay unread."""

        if self._capacity_gate is None:
            raise ValueError("CAPACITY_GATE_UNAVAILABLE")
        deliveries: list[RoutedWorkDelivery] = []
        for index, capability in enumerate(self._read_names()):
            queue = self._queues[capability]
            while len(deliveries) < count:
                lease = self._capacity_gate.acquire(capability)
                if lease is None:
                    break
                options = {"consumer": consumer, "count": 1, **kwargs}
                if operation == "read":
                    options["block_ms"] = kwargs.get("block_ms", 0) if index == 0 else 0
                raw = tuple(getattr(queue, operation)(**options))
                if not raw:
                    self._capacity_gate.release(lease)
                    break
                if len(raw) != 1:
                    self._capacity_gate.release(lease)
                    raise ValueError("CAPABILITY_WORK_DELIVERY_COUNT_INVALID")
                delivery = raw[0]
                message_id = str(getattr(delivery, "message_id", "") or "")
                message = getattr(delivery, "message", None)
                if not message_id or message is None:
                    self._capacity_gate.release(lease)
                    raise ValueError("CAPABILITY_WORK_DELIVERY_INVALID")
                routed_message_id = f"{capability}|{message_id}"
                self._capacity_leases[routed_message_id] = lease
                deliveries.append(RoutedWorkDelivery(routed_message_id, message))
                if len(deliveries) == count:
                    break
        return tuple(deliveries)

    def _read_names(self) -> tuple[str, ...]:
        if self._worker_capability is not None:
            return (self._worker_capability,)
        names = CAPABILITY_QUEUES
        start = self._read_cursor % len(names)
        self._read_cursor += 1
        return names[start:] + names[:start]


__all__ = [
    "CAPABILITY_QUEUES",
    "CapabilityQueueControl",
    "CapabilityRoutedWorkQueue",
    "RedisCapabilityCapacityGate",
    "RoutedWorkDelivery",
]
