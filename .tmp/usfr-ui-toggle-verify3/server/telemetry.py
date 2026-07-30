from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from typing import Any


@dataclass
class MetricsSink:
    records: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, run_id: str, stage: str, status: str, duration_seconds: float, provider: bool = False) -> dict[str, Any]:
        record = {
            "run_id": run_id,
            "stage": stage,
            "status": status,
            "duration_seconds": round(float(duration_seconds), 6),
            "provider": bool(provider),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        self.records.append(record)
        return record


class StageMeasurement:
    def __init__(self, sink: MetricsSink, *, run_id: str, stage: str, provider: bool = False) -> None:
        self.sink = sink
        self.run_id = run_id
        self.stage = stage
        self.provider = provider
        self.started = 0.0

    def __enter__(self) -> "StageMeasurement":
        self.started = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.sink.record(
            run_id=self.run_id,
            stage=self.stage,
            status="failed" if exc_type else "succeeded",
            duration_seconds=time.monotonic() - self.started,
            provider=self.provider,
        )
