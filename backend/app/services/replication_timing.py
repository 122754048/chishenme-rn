from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any
import time


class TimingLedger:
    """Append-only timing records for one replication job."""

    def __init__(self, *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._created_at = now()
        self._stages: list[dict[str, Any]] = []

    def start_stage(self, name: str, *, provider: bool = False, approval: bool = False) -> None:
        if not name or any(record["name"] == name and record["ended_at"] is None for record in self._stages):
            raise ValueError("TIMING_STAGE_INVALID")
        if approval and provider:
            raise ValueError("TIMING_STAGE_CLASSIFICATION_INVALID")
        if any(record["ended_at"] is None for record in self._stages):
            raise ValueError("TIMING_STAGE_OVERLAP")
        retry_count = sum(1 for record in self._stages if record["name"] == name)
        self._stages.append(
            {
                "name": name,
                "provider": provider,
                "approval": approval,
                "started_at": self._now(),
                "ended_at": None,
                "status": "running",
                "skipped_reason": None,
                "retry_count": retry_count,
                "cache_hit": False,
            }
        )

    def end_stage(self, name: str, *, status: str, skipped_reason: str | None = None) -> None:
        if status not in {"succeeded", "failed", "skipped"}:
            raise ValueError("TIMING_STAGE_STATUS_INVALID")
        if status == "skipped" and not skipped_reason:
            raise ValueError("TIMING_SKIP_REASON_REQUIRED")
        for record in reversed(self._stages):
            if record["name"] == name and record["ended_at"] is None:
                record["ended_at"] = self._now()
                record["status"] = status
                record["skipped_reason"] = skipped_reason
                return
        raise ValueError("TIMING_STAGE_NOT_RUNNING")

    def snapshot(self) -> dict[str, object]:
        completed = [record for record in self._stages if record["ended_at"] is not None]
        queue_wait_ms = 0
        previous_end = self._created_at
        for record in self._stages:
            queue_wait_ms += _milliseconds(record["started_at"] - previous_end)
            if record["ended_at"] is None:
                break
            previous_end = record["ended_at"]
        active_ms = sum(
            _milliseconds(record["ended_at"] - record["started_at"])
            for record in completed
            if not record["approval"]
        )
        provider_wait_ms = sum(
            _milliseconds(record["ended_at"] - record["started_at"])
            for record in completed
            if record["provider"]
        )
        approval_wait_ms = sum(
            _milliseconds(record["ended_at"] - record["started_at"])
            for record in completed
            if record["approval"]
        )
        return {
            "created_at": self._created_at,
            "queue_wait_ms": queue_wait_ms,
            "active_ms": active_ms,
            "provider_wait_ms": provider_wait_ms,
            "approval_wait_ms": approval_wait_ms,
            "retry_count": sum(int(record["retry_count"]) for record in self._stages),
            "cache_hit": any(bool(record["cache_hit"]) for record in self._stages),
            "stages": [dict(record) for record in self._stages],
        }

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, object], *, now: Callable[[], float] = time.time) -> "TimingLedger":
        created_at = snapshot.get("created_at")
        stages = snapshot.get("stages")
        if isinstance(created_at, bool) or not isinstance(created_at, (int, float)) or not isinstance(stages, list):
            raise ValueError("TIMING_LEDGER_STATE_INVALID")
        ledger = cls.__new__(cls)
        ledger._now = now
        ledger._created_at = float(created_at)
        ledger._stages = []
        required = {
            "name",
            "provider",
            "approval",
            "started_at",
            "ended_at",
            "status",
            "skipped_reason",
            "retry_count",
            "cache_hit",
        }
        for raw in stages:
            if not isinstance(raw, Mapping) or set(raw) != required:
                raise ValueError("TIMING_LEDGER_STATE_INVALID")
            if (
                not isinstance(raw["name"], str)
                or not isinstance(raw["provider"], bool)
                or not isinstance(raw["approval"], bool)
                or raw["provider"] and raw["approval"]
                or isinstance(raw["started_at"], bool)
                or not isinstance(raw["started_at"], (int, float))
                or raw["ended_at"] is not None and (
                    isinstance(raw["ended_at"], bool) or not isinstance(raw["ended_at"], (int, float))
                )
                or raw["status"] not in {"running", "succeeded", "failed", "skipped"}
                or raw["skipped_reason"] is not None and not isinstance(raw["skipped_reason"], str)
                or isinstance(raw["retry_count"], bool)
                or not isinstance(raw["retry_count"], int)
                or raw["retry_count"] < 0
                or not isinstance(raw["cache_hit"], bool)
            ):
                raise ValueError("TIMING_LEDGER_STATE_INVALID")
            ledger._stages.append(dict(raw))
        if any(record["ended_at"] is None for record in ledger._stages[:-1]):
            raise ValueError("TIMING_LEDGER_STATE_INVALID")
        return ledger


class RedisTimingLedgerStore:
    """Persist one append-only timing ledger per standard USFR job in Redis."""

    def __init__(
        self,
        redis_client: Any,
        *,
        prefix: str = "usfr:timing",
        now: Callable[[], float] = time.time,
    ) -> None:
        if not callable(getattr(redis_client, "get", None)) or not callable(getattr(redis_client, "set", None)):
            raise ValueError("TIMING_LEDGER_REDIS_REQUIRED")
        if not isinstance(prefix, str) or not prefix.strip() or not callable(now):
            raise ValueError("TIMING_LEDGER_CONFIGURATION_INVALID")
        self._redis = redis_client
        self._prefix = prefix.strip()
        self._now = now

    def create(self, job_id: str) -> None:
        if self._read(job_id) is not None:
            return
        ledger = TimingLedger(now=self._now)
        self._write(job_id, ledger)

    def start_stage(self, job_id: str, name: str, *, provider: bool = False, approval: bool = False) -> None:
        ledger = self._ledger(job_id)
        ledger.start_stage(name, provider=provider, approval=approval)
        self._write(job_id, ledger)

    def end_stage(
        self,
        job_id: str,
        name: str,
        *,
        status: str,
        skipped_reason: str | None = None,
    ) -> None:
        ledger = self._ledger(job_id)
        ledger.end_stage(name, status=status, skipped_reason=skipped_reason)
        self._write(job_id, ledger)

    def snapshot(self, job_id: str) -> dict[str, object] | None:
        ledger = self._read(job_id)
        return None if ledger is None else ledger.snapshot()

    def _key(self, job_id: str) -> str:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("TIMING_LEDGER_JOB_INVALID")
        return f"{self._prefix}:{job_id}"

    def _ledger(self, job_id: str) -> TimingLedger:
        ledger = self._read(job_id)
        if ledger is None:
            raise ValueError("TIMING_LEDGER_NOT_FOUND")
        return ledger

    def _read(self, job_id: str) -> TimingLedger | None:
        try:
            raw = self._redis.get(self._key(job_id))
        except Exception as error:
            raise RuntimeError("TIMING_LEDGER_STORE_UNAVAILABLE") from error
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("TIMING_LEDGER_STATE_INVALID") from error
        if not isinstance(payload, Mapping):
            raise ValueError("TIMING_LEDGER_STATE_INVALID")
        return TimingLedger.from_snapshot(payload, now=self._now)

    def _write(self, job_id: str, ledger: TimingLedger) -> None:
        snapshot = ledger.snapshot()
        payload = {"created_at": snapshot["created_at"], "stages": snapshot["stages"]}
        try:
            self._redis.set(self._key(job_id), json.dumps(payload, sort_keys=True, separators=(",", ":")))
        except Exception as error:
            raise RuntimeError("TIMING_LEDGER_STORE_UNAVAILABLE") from error


class TimedStagePort:
    """Observe a deployment StagePort without changing its USFR stage contract."""

    timing_stage_port = True

    def __init__(self, *, stage: str, delegate: Any, timing_ledger_store: RedisTimingLedgerStore) -> None:
        if not isinstance(stage, str) or not stage.strip() or not callable(getattr(delegate, "run", delegate)):
            raise ValueError("TIMING_STAGE_PORT_INVALID")
        if not callable(getattr(timing_ledger_store, "snapshot", None)) or not callable(
            getattr(timing_ledger_store, "start_stage", None)
        ) or not callable(getattr(timing_ledger_store, "end_stage", None)):
            raise ValueError("TIMING_STAGE_PORT_INVALID")
        self.stage = stage.strip()
        self.delegate = delegate
        self._timing_ledger_store = timing_ledger_store

    def run(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        job_id = getattr(context, "job_id", None)
        tracked = isinstance(job_id, str) and bool(job_id) and self._timing_ledger_store.snapshot(job_id) is not None
        if tracked:
            self._timing_ledger_store.start_stage(
                job_id,
                self.stage,
                provider=self.stage == "wait_provider_video",
            )
        operation = getattr(self.delegate, "run", self.delegate)
        try:
            result = operation(context=context, input_artifacts=input_artifacts)
        except Exception:
            if tracked:
                self._timing_ledger_store.end_stage(job_id, self.stage, status="failed")
            raise
        if not isinstance(result, Mapping):
            if tracked:
                self._timing_ledger_store.end_stage(job_id, self.stage, status="failed")
            raise ValueError("TIMING_STAGE_OUTPUT_INVALID")
        if tracked:
            skipped_reason = result.get("skipped_reason")
            skipped = result.get("status") == "skipped" or result.get("skipped") is True
            self._timing_ledger_store.end_stage(
                job_id,
                self.stage,
                status="skipped" if skipped else "succeeded",
                skipped_reason=str(skipped_reason) if skipped_reason is not None else None,
            )
        return result


class TimedStageDriver:
    """Observe existing approval gates before delegating canonical queue advance."""

    def __init__(self, *, delegate: Any, job_store: Any, timing_ledger_store: RedisTimingLedgerStore) -> None:
        if not callable(getattr(delegate, "enqueue_next", None)) or not callable(getattr(job_store, "get_job", None)):
            raise ValueError("TIMING_STAGE_DRIVER_INVALID")
        if not callable(getattr(timing_ledger_store, "snapshot", None)) or not callable(
            getattr(timing_ledger_store, "start_stage", None)
        ) or not callable(getattr(timing_ledger_store, "end_stage", None)):
            raise ValueError("TIMING_STAGE_DRIVER_INVALID")
        self.delegate = delegate
        self.job_store = job_store
        self._timing_ledger_store = timing_ledger_store

    @property
    def background_music_execution_contract(self) -> object:
        return getattr(self.delegate, "background_music_execution_contract", None)

    def enqueue_next(self, job_id: str) -> Any:
        self._sync_approval_waits(job_id)
        return self.delegate.enqueue_next(job_id)

    def _sync_approval_waits(self, job_id: str) -> None:
        if not isinstance(job_id, str) or not job_id or self._timing_ledger_store.snapshot(job_id) is None:
            return
        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            return
        review_route = getattr(snapshot, "review_route", None)
        script_waiting = (
            review_route not in {"route_1", "local_only"}
            and getattr(snapshot, "current_script_revision", None) is not None
            and not getattr(snapshot, "approved_script_sha256", None)
        )
        storyboard_waiting = (
            review_route != "local_only"
            and getattr(snapshot, "current_storyboard_revision", None) is not None
            and not getattr(snapshot, "approved_storyboard_sha256", None)
        )
        self._sync_approval(job_id, "script_approval", waiting=script_waiting)
        self._sync_approval(job_id, "storyboard_approval", waiting=storyboard_waiting)

    def _sync_approval(self, job_id: str, name: str, *, waiting: bool) -> None:
        receipt = self._timing_ledger_store.snapshot(job_id)
        if receipt is None:
            return
        stages = receipt.get("stages")
        if not isinstance(stages, list):
            raise ValueError("TIMING_LEDGER_STATE_INVALID")
        active = next(
            (
                record
                for record in reversed(stages)
                if isinstance(record, Mapping) and record.get("name") == name and record.get("ended_at") is None
            ),
            None,
        )
        if waiting and active is None:
            self._timing_ledger_store.start_stage(job_id, name, approval=True)
        elif not waiting and active is not None:
            self._timing_ledger_store.end_stage(job_id, name, status="succeeded")


def _milliseconds(seconds: float) -> int:
    return round(seconds * 1000)
