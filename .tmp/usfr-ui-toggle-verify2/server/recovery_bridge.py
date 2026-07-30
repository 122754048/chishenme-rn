from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .errors import ReplicationError, StateConflictError
from .recovery_executor import (
    FocusedRecoveryQc,
    RecoveryCapabilityBroker,
    RecoveryStrategyExecutor,
    run_recovery_iteration,
)
from .recovery_models import RecoveryCheckpoint, RecoveryStatus
from .recovery_workflow import (
    freeze_goal_contract,
    normalize_failure_signature,
    should_enter_recovery,
)


@dataclass(frozen=True)
class RecoveryBridgeResult:
    artifact_ref: Mapping[str, Any]
    job_version: int
    checkpoint_sha256: str


class AdaptiveRecoveryBridge:
    """Fallback-only adapter that returns through the failed Artifact contract."""

    def __init__(
        self,
        job_store: Any,
        broker: RecoveryCapabilityBroker,
        executor: RecoveryStrategyExecutor,
        focused_qc: FocusedRecoveryQc,
        ttl_seconds: int = 3600,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("recovery ttl_seconds must be positive")
        self.job_store = job_store
        self.broker = broker
        self.executor = executor
        self.focused_qc = focused_qc
        self.ttl_seconds = ttl_seconds

    def recover_stage_failure(
        self,
        *,
        job_id: str,
        stage: str,
        failure: Mapping[str, Any],
        expected_version: int,
        goal: Mapping[str, Any],
        artifact_kind: str,
        unsupported: bool,
        hard_failure_signatures: Sequence[str],
        transient: bool,
    ) -> RecoveryBridgeResult | None:
        if not should_enter_recovery(
            unsupported=unsupported,
            hard_failure_signatures=hard_failure_signatures,
            transient=transient,
        ):
            return None
        if not stage or not artifact_kind:
            raise ValueError("recovery stage and artifact_kind are required")
        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            raise ReplicationError("JOB_GONE", "job is no longer available", http_status=410)
        if snapshot.version != expected_version:
            raise StateConflictError(
                details={"expected_version": expected_version, "actual_version": snapshot.version}
            )

        frozen_goal = freeze_goal_contract(goal)
        failure_payload = dict(failure)
        failure_payload.setdefault("stage", stage)
        signature = normalize_failure_signature(failure_payload)
        if signature.stage != stage:
            raise ValueError("recovery failure stage differs from failed stage")
        checkpoint = self.job_store.get_recovery_checkpoint(job_id)
        if checkpoint is None:
            checkpoint = RecoveryCheckpoint(
                goal_contract_sha256=frozen_goal.goal_contract_sha256,
                status=RecoveryStatus.REQUIRED,
                failure=signature,
            )
        elif checkpoint.goal_contract_sha256 != frozen_goal.goal_contract_sha256:
            raise StateConflictError("recovery goal contract changed")
        elif checkpoint.failure is None:
            raise ReplicationError("STATE_CORRUPT", "recovery checkpoint has no failure signature")

        current_version = expected_version

        def persist(value: RecoveryCheckpoint) -> RecoveryCheckpoint:
            nonlocal current_version
            updated = self.job_store.put_recovery_checkpoint(
                job_id=job_id,
                expected_version=current_version,
                checkpoint=value,
                ttl_seconds=self.ttl_seconds,
            )
            current_version = updated.version
            return value

        result = run_recovery_iteration(
            checkpoint=checkpoint,
            goal={
                **dict(frozen_goal.payload),
                "goal_contract_sha256": frozen_goal.goal_contract_sha256,
            },
            broker=self.broker,
            executor=self.executor,
            focused_qc=self.focused_qc,
            persist=persist,
        )
        if result.status is RecoveryStatus.EXTERNAL_BLOCKED:
            raise ReplicationError(
                "RECOVERY_EXTERNAL_BLOCKED",
                "adaptive recovery requires an external capability or authorization",
                category="provider",
                retryable=True,
                http_status=503,
            )
        if result.status is not RecoveryStatus.ACHIEVED or result.candidate is None:
            return None
        artifact_ref = dict(result.candidate.artifact_ref)
        if artifact_ref.get("kind") != artifact_kind:
            raise ReplicationError(
                "ARTIFACT_METADATA_MISMATCH",
                "recovery candidate kind differs from the failed stage Artifact contract",
                category="artifact",
            )
        if artifact_ref.get("sha256") != result.candidate.artifact_sha256:
            raise ReplicationError(
                "ARTIFACT_METADATA_MISMATCH",
                "recovery candidate Artifact digest is inconsistent",
                category="artifact",
            )
        return RecoveryBridgeResult(
            artifact_ref=artifact_ref,
            job_version=current_version,
            checkpoint_sha256=result.checkpoint_sha256,
        )


__all__ = ["AdaptiveRecoveryBridge", "RecoveryBridgeResult"]
