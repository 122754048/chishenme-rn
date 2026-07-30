from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ReplicationError(Exception):
    code: str
    message: str
    category: str = "domain"
    retryable: bool = False
    user_action_required: bool = False
    stage: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    provider_code: str | None = None
    next_actions: list[str] = field(default_factory=list)
    http_status: int = 422

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def envelope(self, *, correlation_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        return {
            "schema_version": "replication/v1",
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "stage": self.stage,
            "run_id": run_id,
            "retryable": self.retryable,
            "user_action_required": self.user_action_required,
            "correlation_id": correlation_id,
            "occurred_at": datetime.now(UTC).isoformat(),
            "provider": self.provider,
            "provider_code": self.provider_code,
            "details": self.details,
            "next_actions": self.next_actions,
        }


class StateConflictError(ReplicationError):
    def __init__(self, message: str = "run state or expected version does not allow this command", **details: Any):
        super().__init__(
            code="STATE_CONFLICT",
            message=message,
            category="conflict",
            user_action_required=True,
            details=details,
            http_status=409,
        )


class IdempotencyConflictError(ReplicationError):
    def __init__(self, message: str = "idempotency key was reused with a different request digest", **details: Any):
        super().__init__(
            code="IDEMPOTENCY_CONFLICT",
            message=message,
            category="conflict",
            user_action_required=True,
            details=details,
            http_status=409,
        )


class ApprovalStaleError(ReplicationError):
    def __init__(self, message: str = "approval artifact hash is stale or does not match the run", **details: Any):
        super().__init__(
            code="APPROVAL_STALE",
            message=message,
            category="approval",
            user_action_required=True,
            details=details,
            http_status=409,
        )


class RevisionConflictError(ReplicationError):
    def __init__(self, message: str = "revision cannot change while a provider attempt is active", **details: Any):
        super().__init__(
            code="REVISION_CONFLICT",
            message=message,
            category="conflict",
            user_action_required=True,
            details=details,
            http_status=409,
        )


class ProviderAmbiguousError(ReplicationError):
    def __init__(self, message: str = "provider submission outcome is ambiguous and requires reconciliation", **details: Any):
        super().__init__(
            code="VIDEO_CREATE_AMBIGUOUS",
            message=message,
            category="provider",
            user_action_required=True,
            details=details,
            http_status=503,
        )


class CapabilityInvalidError(ReplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="CAPABILITY_INVALID",
            message="capability token is invalid",
            category="authorization",
            http_status=403,
        )


class JobGoneError(ReplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="JOB_GONE",
            message="job is no longer available",
            category="lifecycle",
            http_status=410,
        )


class ReviewNotApplicableError(ReplicationError):
    def __init__(self, message: str = "review is not applicable to this route", **details: Any):
        super().__init__(
            code="REVIEW_NOT_APPLICABLE",
            message=message,
            category="review",
            user_action_required=True,
            details=details,
            http_status=409,
        )
