from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from .job_models import ArtifactRef, JobSnapshot, ProviderAttempt, StageCheckpoint
from .review_models import RevisionManifest
from .recovery_models import RecoveryCheckpoint


class EphemeralJobStore(Protocol):
    def create_job(
        self,
        *,
        slots_manifest: Mapping[str, Any],
        capability_token_hash: str,
        ttl_seconds: int,
        correlation_id: str | None = None,
    ) -> JobSnapshot:
        raise NotImplementedError

    def get_job(self, job_id: str) -> JobSnapshot | None:
        raise NotImplementedError

    def cas_transition(
        self,
        *,
        job_id: str,
        expected_version: int,
        command: str,
        updates: Mapping[str, Any] | None = None,
        invalidate: Sequence[str] = (),
        ttl_seconds: int | None = None,
    ) -> JobSnapshot:
        raise NotImplementedError

    def append_revision(
        self,
        *,
        job_id: str,
        kind: Literal["script", "storyboard"],
        expected_version: int,
        manifest: RevisionManifest,
        invalidate_downstream: bool,
        ttl_seconds: int,
    ) -> JobSnapshot:
        raise NotImplementedError

    def approve_revision(
        self,
        *,
        job_id: str,
        kind: Literal["script", "storyboard"],
        revision: int,
        expected_version: int,
        expected_sha256: str,
        script_approval: Mapping[str, Any] | None = None,
        ttl_seconds: int,
    ) -> JobSnapshot:
        raise NotImplementedError

    def get_script_approval(self, job_id: str, revision: int) -> Mapping[str, Any] | None:
        raise NotImplementedError

    def list_revisions(self, job_id: str, kind: Literal["script", "storyboard"]) -> tuple[RevisionManifest, ...]:
        raise NotImplementedError

    def get_current_revision(self, job_id: str, kind: Literal["script", "storyboard"]) -> RevisionManifest | None:
        raise NotImplementedError

    def touch_review_ttl(self, job_id: str, ttl_seconds: int) -> JobSnapshot:
        raise NotImplementedError

    def get_recovery_checkpoint(self, job_id: str) -> RecoveryCheckpoint | None:
        raise NotImplementedError

    def put_recovery_checkpoint(
        self,
        *,
        job_id: str,
        expected_version: int,
        checkpoint: RecoveryCheckpoint,
        ttl_seconds: int,
    ) -> JobSnapshot:
        raise NotImplementedError

    def clear_recovery_checkpoint(
        self,
        *,
        job_id: str,
        expected_version: int,
        ttl_seconds: int,
    ) -> JobSnapshot:
        raise NotImplementedError

    def put_artifact(self, *, job_id: str, artifact: ArtifactRef) -> ArtifactRef:
        raise NotImplementedError

    def get_artifact(self, job_id: str, artifact_id: str) -> ArtifactRef | None:
        raise NotImplementedError

    def list_artifacts(self, job_id: str) -> tuple[ArtifactRef, ...]:
        raise NotImplementedError

    def get_stage_checkpoint(self, job_id: str, stage: str) -> StageCheckpoint | None:
        raise NotImplementedError

    def begin_provider_attempt(
        self,
        *,
        job_id: str,
        expected_version: int,
        operation: Literal["CreateAsset", "CreateVideo"],
        request_sha256: str,
        segment_id: str | None = None,
        segment_plan_sha256: str | None = None,
    ) -> ProviderAttempt:
        raise NotImplementedError

    def list_provider_attempts(self, job_id: str) -> tuple[ProviderAttempt, ...]:
        raise NotImplementedError

    def update_provider_attempt(
        self,
        *,
        job_id: str,
        expected_version: int,
        attempt: ProviderAttempt,
        ttl_seconds: int,
    ) -> JobSnapshot:
        raise NotImplementedError

    def consume_provider_authorization_nonce(
        self,
        *,
        job_id: str,
        attempt_id: str,
        request_sha256: str,
        nonce: str,
        authorization_sha256: str,
        expires_at_ms: int,
    ) -> bool:
        """Atomically consume one server-minted CreateVideo authorization."""
        raise NotImplementedError

    def claim_stage(
        self,
        *,
        job_id: str,
        stage: str,
        dedupe_key: str,
        owner: str,
        ttl_seconds: int,
    ) -> StageCheckpoint:
        raise NotImplementedError

    def complete_stage(
        self,
        *,
        job_id: str,
        stage: str,
        dedupe_key: str,
        owner: str,
        output_artifact_ids: Sequence[str],
        ttl_seconds: int,
    ) -> StageCheckpoint:
        raise NotImplementedError
