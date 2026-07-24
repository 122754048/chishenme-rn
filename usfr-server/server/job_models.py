from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping


ProviderOperation = Literal["CreateAsset", "CreateVideo"]
ProviderAttemptStatus = Literal[
    "PREPARED",
    "SUBMITTING",
    "RUNNING",
    "AMBIGUOUS",
    "SUCCEEDED",
    "FAILED",
]


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    object_key: str
    sha256: str
    content_type: str
    size_bytes: int
    revision: int | None = None
    segment_id: str | None = None
    segment_plan_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderAttempt:
    attempt_id: str
    operation: ProviderOperation
    request_sha256: str
    status: ProviderAttemptStatus
    segment_id: str | None
    segment_plan_sha256: str | None
    provider_task_id: str | None = None
    response_sha256: str | None = None

    @classmethod
    def new(
        cls,
        *,
        attempt_id: str,
        operation: ProviderOperation,
        request_sha256: str,
        segment_id: str | None = None,
        segment_plan_sha256: str | None = None,
    ) -> ProviderAttempt:
        return cls(
            attempt_id=attempt_id,
            operation=operation,
            request_sha256=request_sha256,
            status="PREPARED",
            segment_id=segment_id,
            segment_plan_sha256=segment_plan_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProviderAttempt:
        return cls(**dict(value))


@dataclass(frozen=True)
class StageCheckpoint:
    stage: str
    dedupe_key: str
    status: Literal["CLAIMED", "SUCCEEDED", "FAILED"]
    attempt: int
    output_artifact_ids: tuple[str, ...] = ()
    owner: str | None = None


@dataclass(frozen=True)
class WorkMessage:
    job_id: str
    stage: str
    expected_version: int
    dedupe_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    state: str
    version: int
    capability_token_hash: str
    capability_token_version: int
    slots_manifest: Mapping[str, Any]
    expires_at_ms: int
    review_route: str | None = None
    current_script_revision: int | None = None
    approved_script_sha256: str | None = None
    current_storyboard_revision: int | None = None
    approved_storyboard_sha256: str | None = None
    final_ref: Mapping[str, Any] | None = None
    invalidated: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def new(
        cls,
        *,
        job_id: str,
        capability_token_hash: str,
        slots_manifest: Mapping[str, Any],
        expires_at_ms: int,
    ) -> JobSnapshot:
        return cls(
            job_id=job_id,
            state="INTAKE_VALIDATED",
            version=1,
            capability_token_hash=capability_token_hash,
            capability_token_version=1,
            slots_manifest=dict(slots_manifest),
            expires_at_ms=expires_at_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> JobSnapshot:
        payload = dict(value)
        payload["invalidated"] = tuple(payload.get("invalidated", ()))
        return cls(**payload)
