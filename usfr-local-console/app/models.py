from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    version: int
    stage: str
    route: str
    output_language: str | None
    inputs: dict[str, dict[str, Any]]
    admission: dict[str, bool]
    routes: dict[str, str]
    provider: dict[str, Any] | None = None
    reviews: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] | None = None
    execution_map: dict[str, Any] | None = None
    route_preview: dict[str, Any] | None = None
    qa_receipt: dict[str, Any] | None = None
    timing_ledger: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "JobSnapshot":
        return cls(
            job_id=value["job_id"],
            version=value["version"],
            stage=value["stage"],
            route=value["route"],
            output_language=value.get("output_language"),
            inputs=value["inputs"],
            admission=value["admission"],
            routes=value["routes"],
            provider=value.get("provider"),
            reviews=value.get("reviews"),
            artifacts=value.get("artifacts"),
            execution_map=value.get("execution_map"),
            route_preview=value.get("route_preview"),
            qa_receipt=value.get("qa_receipt"),
            timing_ledger=value.get("timing_ledger"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "version": self.version,
            "stage": self.stage,
            "route": self.route,
            "output_language": self.output_language,
            "inputs": self.inputs,
            "admission": self.admission,
            "routes": self.routes,
            "provider": self.provider,
            "reviews": self.reviews,
            "artifacts": self.artifacts,
            "execution_map": self.execution_map,
            "route_preview": self.route_preview,
            "qa_receipt": self.qa_receipt,
            "timing_ledger": self.timing_ledger,
        }
