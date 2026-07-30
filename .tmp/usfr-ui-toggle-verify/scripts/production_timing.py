"""Active/provider timing ledger for a factory run."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Callable, Optional


class ProductionTiming:
    """Persist timing state after every valid transition."""

    TARGET_SECONDS = 1800
    _APPROVALS = {"script", "storyboard"}

    def __init__(self, path: Path, clock: Callable[[], float]):
        self.path = Path(path)
        self.clock = clock
        self._state = self._load()

    @classmethod
    def _empty_state(cls) -> dict:
        return {
            "target_seconds": cls.TARGET_SECONDS,
            "started_at": None,
            "finished_at": None,
            "last_transition_at": None,
            "approval_wait_seconds": 0.0,
            "provider_seconds": 0.0,
            "stage_seconds": {},
            "skipped_stages": {},
            "stage_statuses": {},
            "profile_metrics": {},
            "stage_started_at": None,
            "stage_name": None,
            "stage_provider": False,
            "paused_at": None,
            "paused_gate": None,
        }

    @staticmethod
    def _number(name: str, value, *, optional: bool = False) -> Optional[float]:
        if value is None and optional:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite non-negative number")
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite non-negative number")
        return value

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty_state()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid production timing log: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("production timing log must be a JSON object")

        # Migrate the first ledger field names without resetting elapsed state.
        if "paused_gate" not in data and "approval_name" in data:
            data["paused_gate"] = data.pop("approval_name")
        if "paused_at" not in data and "approval_started_at" in data:
            data["paused_at"] = data.pop("approval_started_at")

        state = self._empty_state()
        state.update(data)
        state["target_seconds"] = self.TARGET_SECONDS
        self._validate_state(state)
        return state

    def _validate_state(self, state: dict) -> None:
        for field in (
            "started_at",
            "finished_at",
            "last_transition_at",
            "stage_started_at",
            "paused_at",
        ):
            state[field] = self._number(field, state[field], optional=True)
        for field in ("approval_wait_seconds", "provider_seconds"):
            state[field] = self._number(field, state[field])
        for field in ("end_to_end_seconds", "active_processing_seconds"):
            if field in state:
                state[field] = self._number(field, state[field])

        stages = state["stage_seconds"]
        if not isinstance(stages, dict):
            raise ValueError("stage_seconds must be a JSON object")
        for name, seconds in list(stages.items()):
            if not isinstance(name, str) or not name:
                raise ValueError("stage_seconds keys must be non-empty strings")
            stages[name] = self._number(f"stage_seconds[{name!r}]", seconds)

        skipped = state.get("skipped_stages", {})
        if not isinstance(skipped, dict):
            raise ValueError("skipped_stages must be a JSON object")
        for name, reason in skipped.items():
            if not isinstance(name, str) or not name:
                raise ValueError("skipped_stages keys must be non-empty strings")
            if not isinstance(reason, str) or not reason:
                raise ValueError("skipped_stages reasons must be non-empty strings")
        metrics = state.get("profile_metrics", {})
        if not isinstance(metrics, dict):
            raise ValueError("profile_metrics must be a JSON object")
        for name, metric in metrics.items():
            if not isinstance(name, str) or not name:
                raise ValueError("profile_metrics keys must be non-empty strings")
            if not isinstance(metric, dict):
                raise ValueError("profile_metrics entries must be JSON objects")
            samples = metric.get("samples", [])
            if not isinstance(samples, list):
                raise ValueError("profile_metrics samples must be a JSON array")
            for index, sample in enumerate(samples):
                self._number(f"profile_metrics[{name!r}].samples[{index}]", sample)
            status = metric.get("status")
            if status is not None and status not in {"succeeded", "failed", "skipped", "timeout"}:
                raise ValueError("profile metric status is invalid")
            for field in ("last_seconds", "p50_seconds", "p95_seconds"):
                if field in metric and metric[field] is not None:
                    self._number(f"profile_metrics[{name!r}].{field}", metric[field])
        statuses = state.get("stage_statuses", {})
        if not isinstance(statuses, dict):
            raise ValueError("stage_statuses must be a JSON object")
        for name, status in statuses.items():
            if not isinstance(name, str) or not name:
                raise ValueError("stage_statuses keys must be non-empty strings")
            if status not in {"running", "succeeded", "failed", "skipped", "timeout", "approval_waiting"}:
                raise ValueError("stage status is invalid")

        stage_name = state["stage_name"]
        stage_started = state["stage_started_at"]
        if (stage_name is None) != (stage_started is None):
            raise ValueError("stage_name and stage_started_at must be set together")
        if stage_name is not None and (not isinstance(stage_name, str) or not stage_name):
            raise ValueError("stage_name must be a non-empty string")
        if not isinstance(state["stage_provider"], bool):
            raise ValueError("stage_provider must be a boolean")
        if stage_name is None and state["stage_provider"]:
            raise ValueError("stage_provider cannot be true without an active stage")

        paused_gate = state["paused_gate"]
        paused_at = state["paused_at"]
        if (paused_gate is None) != (paused_at is None):
            raise ValueError("paused_gate and paused_at must be set together")
        if paused_gate is not None and paused_gate not in self._APPROVALS:
            raise ValueError("paused_gate must be script or storyboard")
        if stage_name is not None and paused_gate is not None:
            raise ValueError("stage and approval pause cannot be active together")

        started = state["started_at"]
        finished = state["finished_at"]
        if started is None and any(
            value is not None for value in (finished, stage_started, paused_at)
        ):
            raise ValueError("timing transitions require started_at")
        if finished is not None and (stage_name is not None or paused_gate is not None):
            raise ValueError("finished timing log cannot contain an active transition")
        if finished is not None and finished < started:
            raise ValueError("finished_at cannot be earlier than started_at")
        if finished is not None and state["approval_wait_seconds"] > finished - started:
            raise ValueError("approval_wait_seconds exceeds end-to-end elapsed time")

        recorded = [value for value in (started, finished, stage_started, paused_at) if value is not None]
        derived_last = max(recorded) if recorded else None
        if state["last_transition_at"] is None:
            state["last_transition_at"] = derived_last
        elif derived_last is not None and state["last_transition_at"] < derived_last:
            raise ValueError("last_transition_at cannot precede a recorded transition")

    def _now(self) -> float:
        now = self._number("clock value", self.clock())
        previous = self._state["last_transition_at"]
        if previous is not None and now < previous:
            raise RuntimeError(
                f"clock moved backwards: current {now} is earlier than {previous}"
            )
        return now

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self._state, handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _require_started(self) -> None:
        if self._state["started_at"] is None:
            raise RuntimeError("production timing has not started")
        if self._state["finished_at"] is not None:
            raise RuntimeError("production timing is already finished")

    def start(self) -> dict:
        if self._state["finished_at"] is not None:
            raise RuntimeError("production timing is already finished")
        now = self._now()
        if self._state["started_at"] is None:
            self._state["started_at"] = now
        self._state["last_transition_at"] = now
        self._persist()
        return dict(self._state)

    def start_stage(self, name: str, provider: bool = False) -> None:
        self._require_started()
        if self._state["paused_at"] is not None:
            raise RuntimeError("cannot start a stage during approval pause")
        if self._state["stage_name"] is not None:
            raise RuntimeError("a stage is already running")
        if not isinstance(name, str) or not name:
            raise ValueError("stage name is required")
        now = self._now()
        self._state.update(
            stage_name=name,
            stage_provider=bool(provider),
            stage_started_at=now,
            last_transition_at=now,
        )
        self._state["stage_statuses"][name] = "running"
        self._persist()

    def end_stage(self, name: Optional[str] = None) -> float:
        self._require_started()
        current = self._state["stage_name"]
        if current is None:
            raise RuntimeError("no stage is running")
        if name is not None and name != current:
            raise RuntimeError(f"stage mismatch: expected {current!r}, got {name!r}")
        now = self._now()
        elapsed = now - self._state["stage_started_at"]
        self._state["stage_seconds"][current] = (
            self._state["stage_seconds"].get(current, 0.0) + elapsed
        )
        if self._state["stage_provider"]:
            self._state["provider_seconds"] += elapsed
        self._state.update(
            stage_name=None,
            stage_provider=False,
            stage_started_at=None,
            last_transition_at=now,
        )
        self._state["stage_statuses"][current] = "succeeded"
        self._persist()
        return elapsed

    def record_skipped(self, name: str, *, reason: str) -> None:
        """Record an internal optional stage that was intentionally skipped.

        Skips are observability records only; they never remove time from the
        active ledger and cannot be recorded while another transition is open.
        """
        self._require_started()
        if not isinstance(name, str) or not name:
            raise ValueError("skipped stage name is required")
        if not isinstance(reason, str) or not reason:
            raise ValueError("skip reason is required")
        if self._state["stage_name"] is not None or self._state["paused_at"] is not None:
            raise RuntimeError("cannot record a skipped stage during an active transition")
        now = self._now()
        self._state["skipped_stages"][name] = reason
        self._state["stage_statuses"][name] = "skipped"
        self._state["last_transition_at"] = now
        self._persist()

    def record_profile_metric(self, name: str, *, duration_seconds: float, status: str) -> None:
        """Persist measured profile work without creating a new stage.

        Profile metrics are nested observations of an existing stage (for
        example Invocation A inside ``build_script``), so recording one while
        that stage is open must not be treated as a conflicting transition.
        Approval pauses remain forbidden because no work may be attributed to
        a user-wait interval.
        """
        self._require_started()
        if self._state["paused_at"] is not None:
            raise RuntimeError("cannot record a profile metric during approval pause")
        if not isinstance(name, str) or not name:
            raise ValueError("profile metric name is required")
        if status not in {"succeeded", "failed", "skipped", "timeout"}:
            raise ValueError("profile metric status is invalid")
        duration = self._number("duration_seconds", duration_seconds)
        if name in {"seedance_invocation_a", "invocation_a", "seedance20_invocation_a"} and duration > 120:
            raise ValueError("Invocation A duration exceeds hard timeout 120 seconds")
        now = self._now()
        metric = self._state["profile_metrics"].setdefault(
            name, {"samples": [], "status": status}
        )
        metric["samples"].append(duration)
        metric["status"] = status
        metric["last_seconds"] = duration
        self._state["stage_statuses"][name] = status
        self._state["last_transition_at"] = now
        self._persist()

    def pause_approval(self, kind: str) -> None:
        self._require_started()
        if kind not in self._APPROVALS:
            raise ValueError("approval pauses are limited to script and storyboard")
        if self._state["paused_at"] is not None:
            raise RuntimeError("approval is already paused")
        if self._state["stage_name"] is not None:
            raise RuntimeError("cannot pause approval during a running stage")
        now = self._now()
        self._state.update(paused_gate=kind, paused_at=now, last_transition_at=now)
        self._persist()

    def resume_approval(self, kind: str) -> float:
        self._require_started()
        if self._state["paused_at"] is None:
            raise RuntimeError("approval is not paused")
        if kind != self._state["paused_gate"]:
            raise RuntimeError("approval kind does not match paused approval")
        now = self._now()
        elapsed = now - self._state["paused_at"]
        self._state["approval_wait_seconds"] += elapsed
        self._state.update(paused_gate=None, paused_at=None, last_transition_at=now)
        self._persist()
        return elapsed

    def finish(self) -> dict:
        self._require_started()
        if self._state["paused_at"] is not None:
            raise RuntimeError("cannot finish during approval pause")
        if self._state["stage_name"] is not None:
            raise RuntimeError("cannot finish while a stage is running")
        ended = self._now()
        self._state["finished_at"] = ended
        self._state["last_transition_at"] = ended
        end_to_end = ended - self._state["started_at"]
        approval = self._state["approval_wait_seconds"]
        active = end_to_end - approval
        if active < 0:
            raise ValueError("approval_wait_seconds exceeds end-to-end elapsed time")
        stages = self._state["stage_seconds"]
        slowest = max(stages, key=stages.get) if stages else None
        result = {
            "target_seconds": self.TARGET_SECONDS,
            "end_to_end_seconds": end_to_end,
            "approval_wait_seconds": approval,
            "active_processing_seconds": active,
            "provider_seconds": self._state["provider_seconds"],
            "target_met": active <= self.TARGET_SECONDS,
            "slowest_stage": slowest,
            "stage_seconds": dict(stages),
            "skipped_stages": dict(self._state["skipped_stages"]),
            "stage_statuses": dict(self._state["stage_statuses"]),
            "profile_metrics": {},
        }
        for name, metric in self._state["profile_metrics"].items():
            samples = sorted(float(value) for value in metric.get("samples", []))
            if not samples:
                p50 = p95 = None
            else:
                p50 = samples[(len(samples) - 1) // 2]
                p95 = samples[min(len(samples) - 1, max(0, math.ceil(len(samples) * 0.95) - 1))]
            result["profile_metrics"][name] = {
                "samples": samples,
                "p50_seconds": p50,
                "p95_seconds": p95,
                "status": metric.get("status"),
                "last_seconds": metric.get("last_seconds"),
            }
        self._state.update(result)
        self._persist()
        return result
