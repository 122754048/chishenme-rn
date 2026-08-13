"""Deterministic Redis-queue driver for the twelve-stage video workflow."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any

from .job_models import WorkMessage
from .errors import ReplicationError
from .orchestrator import (
    _v2_approval_state,
    build_stage_plan,
    invalidate_stage_downstream,
    v2_stage_expected_input_fingerprint,
    v2_stage_checkpoint_is_current,
)
from .split_edit_runtime import (
    canonical_sha,
    load_formal_stage_output,
    resolve_split_stage_plan,
    split_contract_from_output,
    split_pass_score,
    split_provider_retry_dedupe,
)
from .video_edit_qc_runtime import QcRetryEvidenceError, formal_stage_artifact_identity


POST_APPROVAL_STAGES = (
    "segment_plan",
    "compile_h3_edit",
    "audit_h3_request",
    "submit_h3_edit",
    "wait_h3_edit",
    "compile_seedance20_prompt",
    "audit_seedance_request",
    "submit_provider_video",
    "wait_provider_video",
    "submit_provider_video_pass1",
    "wait_provider_video_pass1",
    "run_qc_pass1",
    "submit_provider_video_pass2",
    "wait_provider_video_pass2",
    "splice_timeline",
    "evaluate_voiceover_fallback",
    "replace_voiceover_audio",
    "run_qc",
)
SCRIPT_APPROVAL_STAGES = (
    "generate_asset_boards",
)
EXECUTABLE_STAGES = (
    "bind_inputs",
    "probe_source",
    "analyze_dynamics",
    "build_target_evidence",
    "route_regions",
    "parse_app_store_evidence",
    "resolve_ui_evidence",
    "build_script",
    "generate_storyboards",
    *SCRIPT_APPROVAL_STAGES,
    *POST_APPROVAL_STAGES,
)


def _dedupe(
    job_id: str,
    stage: str,
    snapshot: Any,
    *,
    input_fingerprint: str | None = None,
    contract_version: str | None = None,
) -> str:
    manifest = snapshot.slots_manifest
    extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
    v2_active = isinstance(extensions, Mapping) and extensions.get("edit_contract") == "video-edit-v2"
    payload_value = {
        "job_id": job_id,
        "stage": stage,
        "workflow_version": (
            manifest.get("workflow_version", "server-v1")
            if isinstance(manifest, Mapping)
            else "server-v1"
        ),
        "approved_script_sha256": snapshot.approved_script_sha256,
        "input_fingerprint": input_fingerprint,
        "contract_version": contract_version or "server-v1",
        "slots_manifest": manifest,
    }
    if not v2_active:
        payload_value["approved_storyboard_sha256"] = snapshot.approved_storyboard_sha256
    payload = json.dumps(
        payload_value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def script_recovery_dedupe(
    job_id: str,
    snapshot: Any,
    script_approval: Mapping[str, Any],
) -> str:
    """Return the immutable input identity for build-script confirmation recovery."""

    payload = json.dumps(
        {
            "job_id": job_id,
            "stage": "build_script",
            "current_script_revision": snapshot.current_script_revision,
            "approved_script_sha256": snapshot.approved_script_sha256,
            "script_approval": {
                "revision": script_approval.get("revision"),
                "script_sha256": script_approval.get("script_sha256"),
                "source_content_timeline_sha256": script_approval.get(
                    "source_content_timeline_sha256"
                ),
                "line_contracts_sha256": script_approval.get("line_contracts_sha256"),
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def qc_retry_dedupe(
    base_dedupe: str,
    evidence_sha256: str,
    assembled_sha256: str,
    *,
    evidence_artifact_id: str = "",
    assembled_artifact_id: str = "",
) -> str:
    payload = {
        "base_dedupe": base_dedupe,
        "evidence_artifact_id": str(evidence_artifact_id),
        "evidence_sha256": str(evidence_sha256).lower(),
        "assembled_artifact_id": str(assembled_artifact_id),
        "assembled_sha256": str(assembled_sha256).lower(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class EphemeralStageDriver:
    def __init__(self, job_store: Any, work_queue: Any) -> None:
        self.job_store = job_store
        self.work_queue = work_queue

    @staticmethod
    def runtime_stage(stage: Mapping[str, Any]) -> str:
        """Resolve a semantic v2 stage to the existing queued stage name."""

        return str(stage.get("runtime_stage") or stage.get("name") or "")

    def enqueue_qc_retry(
        self,
        job_id: str,
        *,
        evidence_sha256: str,
        assembled_sha256: str,
        evidence_artifact_id: str = "",
        assembled_artifact_id: str = "",
        owner: str = "qc-retry-worker",
    ) -> WorkMessage | None:
        """Claim and enqueue the one v2 QC retry without changing DAG order."""

        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            return None
        extensions = snapshot.slots_manifest.get("extensions") if isinstance(snapshot.slots_manifest, Mapping) else None
        if not isinstance(extensions, Mapping) or extensions.get("edit_contract") != "video-edit-v2":
            return None
        approval_state = _v2_approval_state(snapshot)
        plan = build_stage_plan(snapshot.slots_manifest, approval_state=approval_state)
        submit = next(
            (item for item in plan if self.runtime_stage(item) == "submit_provider_video"),
            None,
        )
        if submit is None:
            raise RuntimeError("v2 QC retry requires a submit_provider_video stage")
        semantic_stage = str(submit.get("name") or "")
        input_fingerprint = v2_stage_expected_input_fingerprint(
            plan,
            semantic_stage,
            checkpoint_lookup=lambda stage: self.job_store.get_stage_checkpoint(job_id, stage),
            approval_state=approval_state,
        )
        base_dedupe = _dedupe(
            job_id,
            "submit_provider_video",
            snapshot,
            input_fingerprint=input_fingerprint,
            contract_version=str(submit.get("contract_version") or "video-edit-v2"),
        )
        dedupe_key = qc_retry_dedupe(
            base_dedupe,
            evidence_sha256,
            assembled_sha256,
            evidence_artifact_id=evidence_artifact_id,
            assembled_artifact_id=assembled_artifact_id,
        )
        existing = self.job_store.get_stage_checkpoint(job_id, "submit_provider_video")
        if existing is not None and existing.status == "SUCCEEDED":
            invalidate = getattr(self.job_store, "invalidate_stage_checkpoints", None)
            if not callable(invalidate):
                raise RuntimeError("v2 QC retry requires durable downstream invalidation")
            downstream = invalidate_stage_downstream(plan, semantic_stage)
            runtime_by_name = {
                str(item.get("name") or ""): self.runtime_stage(item)
                for item in plan
            }
            stages_to_invalidate = [runtime_by_name[semantic_stage]]
            stages_to_invalidate.extend(
                runtime_by_name[str(item.get("name") or "")]
                for item in downstream
                if str(item.get("name") or "") in runtime_by_name
            )
            invalidate(
                job_id=job_id,
                expected_version=snapshot.version,
                stages=tuple(dict.fromkeys(stages_to_invalidate)),
                ttl_seconds=max(1, int((snapshot.expires_at_ms - time.time_ns() // 1_000_000) / 1000)),
            )
            return self.enqueue_qc_retry(
                job_id,
                evidence_artifact_id=evidence_artifact_id,
                evidence_sha256=evidence_sha256,
                assembled_artifact_id=assembled_artifact_id,
                assembled_sha256=assembled_sha256,
                owner=owner,
            )
        if existing is None or existing.status == "NEEDS_RECOMPUTE":
            checkpoint = self.job_store.claim_stage(
                job_id=job_id,
                stage="submit_provider_video",
                dedupe_key=dedupe_key,
                owner=owner,
                ttl_seconds=max(1, int((snapshot.expires_at_ms - time.time_ns() // 1_000_000) / 1000)),
            )
        elif existing.status == "CLAIMED" and existing.dedupe_key == dedupe_key:
            checkpoint = existing
        else:
            raise RuntimeError("submit_provider_video checkpoint is already bound to another request")
        message = WorkMessage(job_id, "submit_provider_video", snapshot.version, dedupe_key)
        self.work_queue.enqueue(
            job_id=message.job_id,
            stage=message.stage,
            expected_version=message.expected_version,
            dedupe_key=message.dedupe_key,
        )
        del checkpoint
        return message

    def enqueue_split_qc_retry(
        self,
        job_id: str,
        *,
        evidence_sha256: str,
        assembled_sha256: str,
        evidence_artifact_id: str = "",
        assembled_artifact_id: str = "",
        owner: str = "qc-retry-worker",
    ) -> WorkMessage | None:
        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            return None
        approval_state = _v2_approval_state(snapshot)
        plan = resolve_split_stage_plan(
            build_stage_plan(snapshot.slots_manifest, approval_state=approval_state),
            job_store=self.job_store,
            job_id=job_id,
        )
        submit = next(
            (item for item in plan if self.runtime_stage(item) == "submit_provider_video_pass2"),
            None,
        )
        if submit is None:
            raise ReplicationError("CONTRACT_INVALID", "split QC retry requires a pass2 submit stage")
        semantic_stage = str(submit.get("name") or "")
        attempts = [
            item for item in self.job_store.list_provider_attempts(job_id)
            if item.operation == "CreateVideo" and item.pass_index == 2
        ]
        retry_attempts = [item for item in attempts if item.retry_index == 2]
        if retry_attempts:
            return None
        if len([item for item in attempts if item.status == "SUCCEEDED"]) != 1:
            raise ReplicationError(
                "QC_EVIDENCE_INVALID",
                "split QC retry requires exactly one successful pass2 attempt",
                category="quality",
            )
        input_fingerprint = v2_stage_expected_input_fingerprint(
            plan,
            semantic_stage,
            checkpoint_lookup=lambda stage: self.job_store.get_stage_checkpoint(job_id, stage),
            approval_state=approval_state,
        )
        base_dedupe = _dedupe(
            job_id,
            "submit_provider_video_pass2",
            snapshot,
            input_fingerprint=input_fingerprint,
            contract_version=str(submit.get("contract_version") or "video-edit-v2"),
        )
        dedupe_key = qc_retry_dedupe(
            base_dedupe,
            evidence_sha256,
            assembled_sha256,
            evidence_artifact_id=evidence_artifact_id,
            assembled_artifact_id=assembled_artifact_id,
        )
        invalidate = getattr(self.job_store, "invalidate_stage_checkpoints", None)
        if not callable(invalidate):
            raise ReplicationError("CONTRACT_INVALID", "split QC retry requires durable checkpoint invalidation")
        downstream = invalidate_stage_downstream(plan, semantic_stage)
        semantic_to_runtime = {str(item.get("name") or ""): self.runtime_stage(item) for item in plan}
        stages = [semantic_to_runtime[semantic_stage]] + [
            semantic_to_runtime[str(item.get("name") or "")]
            for item in downstream
            if str(item.get("name") or "") in semantic_to_runtime
        ]
        invalidate(
            job_id=job_id,
            expected_version=snapshot.version,
            stages=tuple(dict.fromkeys(stages)),
            ttl_seconds=max(1, int((snapshot.expires_at_ms - time.time_ns() // 1_000_000) / 1000)),
        )
        current = self.job_store.get_job(job_id)
        if current is None:
            return None
        checkpoint = self.job_store.claim_stage(
            job_id=job_id,
            stage="submit_provider_video_pass2",
            dedupe_key=dedupe_key,
            owner=owner,
            ttl_seconds=max(1, int((current.expires_at_ms - time.time_ns() // 1_000_000) / 1000)),
        )
        del checkpoint
        message = WorkMessage(job_id, "submit_provider_video_pass2", current.version, dedupe_key)
        self.work_queue.enqueue(
            job_id=message.job_id,
            stage=message.stage,
            expected_version=message.expected_version,
            dedupe_key=message.dedupe_key,
        )
        return message

    def enqueue_split_provider_retry(
        self,
        job_id: str,
        *,
        owner: str = "qc-retry-worker",
    ) -> WorkMessage | None:
        """Requeue exactly one confirmed pass2 provider failure."""

        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            return None
        approval_state = _v2_approval_state(snapshot)
        plan = resolve_split_stage_plan(
            build_stage_plan(snapshot.slots_manifest, approval_state=approval_state),
            job_store=self.job_store,
            job_id=job_id,
        )
        submit = next(
            (item for item in plan if self.runtime_stage(item) == "submit_provider_video_pass2"),
            None,
        )
        if submit is None:
            raise ReplicationError("CONTRACT_INVALID", "split provider retry requires a pass2 submit stage")
        attempts = [
            item
            for item in self.job_store.list_provider_attempts(job_id)
            if item.operation == "CreateVideo" and item.pass_index == 2
        ]
        retry_attempts = [item for item in attempts if item.retry_index == 2]
        if retry_attempts:
            if any(item.status == "FAILED" and item.failure_kind == "provider" for item in retry_attempts):
                raise ReplicationError(
                    "SEEDANCE_EDIT_FAILED",
                    "provider edit failed after the allowed two billable attempts",
                    category="provider",
                    retryable=False,
                )
            return None
        failed = [
            item
            for item in attempts
            if item.status == "FAILED" and item.failure_kind == "provider" and item.retry_index is None
        ]
        if len(failed) != 1:
            raise ReplicationError(
                "PROVIDER_RETRY_INVALID",
                "split provider retry requires exactly one confirmed failed pass2 attempt",
                category="provider",
            )
        parent = failed[0]
        semantic_stage = str(submit.get("name") or "")
        input_fingerprint = v2_stage_expected_input_fingerprint(
            plan,
            semantic_stage,
            checkpoint_lookup=lambda stage: self.job_store.get_stage_checkpoint(job_id, stage),
            approval_state=approval_state,
        )
        base_dedupe = _dedupe(
            job_id,
            "submit_provider_video_pass2",
            snapshot,
            input_fingerprint=input_fingerprint,
            contract_version=str(submit.get("contract_version") or "video-edit-v2"),
        )
        dedupe_key = split_provider_retry_dedupe(
            base_dedupe,
            parent_attempt_id=parent.attempt_id,
            parent_request_sha256=parent.request_sha256,
        )
        invalidate = getattr(self.job_store, "invalidate_stage_checkpoints", None)
        if not callable(invalidate):
            raise ReplicationError("CONTRACT_INVALID", "split provider retry requires durable checkpoint invalidation")
        downstream = invalidate_stage_downstream(plan, semantic_stage)
        semantic_to_runtime = {str(item.get("name") or ""): self.runtime_stage(item) for item in plan}
        stages = [semantic_to_runtime[semantic_stage]] + [
            semantic_to_runtime[str(item.get("name") or "")]
            for item in downstream
            if str(item.get("name") or "") in semantic_to_runtime
        ]
        current = self.job_store.get_job(job_id)
        if current is None:
            return None
        invalidate(
            job_id=job_id,
            expected_version=current.version,
            stages=tuple(dict.fromkeys(stages)),
            ttl_seconds=max(1, int((current.expires_at_ms - time.time_ns() // 1_000_000) / 1000)),
        )
        current = self.job_store.get_job(job_id)
        if current is None:
            return None
        self.job_store.claim_stage(
            job_id=job_id,
            stage="submit_provider_video_pass2",
            dedupe_key=dedupe_key,
            owner=owner,
            ttl_seconds=max(1, int((current.expires_at_ms - time.time_ns() // 1_000_000) / 1000)),
        )
        message = WorkMessage(job_id, "submit_provider_video_pass2", current.version, dedupe_key)
        self.work_queue.enqueue(
            job_id=message.job_id,
            stage=message.stage,
            expected_version=message.expected_version,
            dedupe_key=message.dedupe_key,
        )
        return message

    def enqueue_next(self, job_id: str) -> WorkMessage | None:
        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            return None
        v2_active = bool(
            isinstance(snapshot.slots_manifest, Mapping)
            and isinstance(snapshot.slots_manifest.get("extensions"), Mapping)
            and snapshot.slots_manifest["extensions"].get("edit_contract") == "video-edit-v2"
        )
        if snapshot.review_route == "route_1" and not v2_active:
            # route_1 is a legacy "reuse an earlier approval" marker.  A new
            # generated-media run must always expose both editable review
            # gates, so retain the historical revision only as draft evidence
            # and clear its approval authority before planning work.
            snapshot = self.job_store.cas_transition(
                job_id=job_id,
                expected_version=snapshot.version,
                command="normalize_legacy_review_route",
                updates={
                    "review_route": "route_2",
                    "approved_script_sha256": None,
                    "approved_storyboard_sha256": None,
                },
            )
        approval_state = _v2_approval_state(snapshot) if v2_active else None
        plan = build_stage_plan(
            snapshot.slots_manifest,
            review_route=snapshot.review_route,
            approval_state=approval_state,
        )
        plan = resolve_split_stage_plan(
            plan,
            job_store=self.job_store,
            job_id=job_id,
        )
        compile_output = load_formal_stage_output(self.job_store, job_id, "compile_seedance20_prompt")
        compile_contract = compile_output.get("seedance_input_contract") if isinstance(compile_output, Mapping) else None
        complexity = compile_contract.get("complexity") if isinstance(compile_contract, Mapping) else None
        if isinstance(complexity, Mapping) and complexity.get("decision") == "manual_review_required":
            raise ReplicationError(
                "MANUAL_REVIEW_REQUIRED",
                "edit complexity requires manual review before provider submission",
                category="quality",
                retryable=False,
            )
        split_contract = split_contract_from_output(compile_output)
        if split_contract is not None:
            try:
                threshold = float(split_contract["complexity"]["threshold"])
                pass_one_score = split_pass_score(split_contract, 1)
            except (KeyError, TypeError, ValueError) as exc:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "split edit compile contract is invalid",
                    category="contract",
                ) from exc
            if pass_one_score > threshold:
                raise ReplicationError(
                    "MANUAL_REVIEW_REQUIRED",
                    "split edit pass one remains above the approved complexity threshold",
                    category="quality",
                    retryable=False,
                    details={"pass_one_score": pass_one_score, "threshold": threshold},
                )
        if split_contract is not None:
            failed_wait = load_formal_stage_output(self.job_store, job_id, "wait_provider_video_pass2")
            if isinstance(failed_wait, Mapping) and failed_wait.get("confirmed_failure") is True:
                return self.enqueue_split_provider_retry(job_id)
            qc_output = load_formal_stage_output(self.job_store, job_id, "run_qc")
            if isinstance(qc_output, Mapping) and qc_output.get("qc_passed") is False:
                failure_type = str(qc_output.get("failure_type") or "")
                if failure_type in {"identity_replacement_incomplete", "dialogue_mismatch"}:
                    raise ReplicationError(
                        "MANUAL_REVIEW_REQUIRED",
                        "final QC identifies a pass1 factor and cannot be retried as pass2",
                        category="quality",
                        retryable=False,
                        details={"failure_type": failure_type},
                    )
                if failure_type in {"replacement_incomplete", "preservation_drift"}:
                    try:
                        evidence_id, evidence_sha = formal_stage_artifact_identity(
                            self.job_store,
                            job_id,
                            stage="run_qc",
                            kind="video_edit_qc_evidence",
                        )
                        assembled_id, assembled_sha = formal_stage_artifact_identity(
                            self.job_store,
                            job_id,
                            stage="splice_timeline",
                            kind="assembled_video",
                        )
                    except QcRetryEvidenceError as exc:
                        raise ReplicationError(
                            "QC_EVIDENCE_INVALID",
                            "current split QC evidence descriptor is unavailable",
                            category="quality",
                            retryable=False,
                        ) from exc
                    return self.enqueue_split_qc_retry(
                        job_id,
                        evidence_artifact_id=evidence_id,
                        evidence_sha256=evidence_sha,
                        assembled_artifact_id=assembled_id,
                        assembled_sha256=assembled_sha,
                        owner="qc-retry-worker",
                    )

        def dedupe_for(item: Mapping[str, Any], runtime_stage: str) -> str:
            input_fingerprint = None
            contract_version = None
            if v2_active:
                input_fingerprint = v2_stage_expected_input_fingerprint(
                    plan,
                    str(item.get("name") or ""),
                    checkpoint_lookup=lambda stage_name: self.job_store.get_stage_checkpoint(job_id, stage_name),
                    approval_state=approval_state,
                )
                contract_version = str(item.get("contract_version") or "video-edit-v2")
            return _dedupe(
                job_id,
                runtime_stage,
                snapshot,
                input_fingerprint=input_fingerprint,
                contract_version=contract_version,
            )
        if v2_active:
            stale_stage: str | None = None
            for item in plan:
                semantic_stage = str(item.get("name") or "")
                if semantic_stage == "await_script_approval":
                    continue
                runtime_stage = self.runtime_stage(item)
                checkpoint = self.job_store.get_stage_checkpoint(job_id, runtime_stage)
                if checkpoint is None or checkpoint.status == "NEEDS_RECOMPUTE":
                    break
                if checkpoint.status == "CLAIMED":
                    expected_dedupe = dedupe_for(item, runtime_stage)
                    if checkpoint.dedupe_key != expected_dedupe:
                        stale_stage = semantic_stage
                    break
                if checkpoint.status != "SUCCEEDED":
                    break
                if not v2_stage_checkpoint_is_current(
                    plan,
                    semantic_stage,
                    checkpoint_lookup=lambda stage: self.job_store.get_stage_checkpoint(job_id, stage),
                    approval_state=approval_state,
                ):
                    stale_stage = semantic_stage
                    break
            if stale_stage is not None:
                downstream = invalidate_stage_downstream(plan, stale_stage)
                semantic_to_runtime = {
                    str(item.get("name") or ""): self.runtime_stage(item)
                    for item in plan
                }
                stages_to_invalidate = [semantic_to_runtime[stale_stage]] + [
                    semantic_to_runtime[str(item.get("name") or "")]
                    for item in downstream
                    if str(item.get("name") or "") in semantic_to_runtime
                ]
                invalidate = getattr(self.job_store, "invalidate_stage_checkpoints", None)
                if not callable(invalidate):
                    raise RuntimeError("v2 runtime requires durable stage checkpoint invalidation")
                current = self.job_store.get_job(job_id)
                if current is None:
                    return None
                invalidate(
                    job_id=job_id,
                    expected_version=current.version,
                    stages=tuple(dict.fromkeys(stages_to_invalidate)),
                    ttl_seconds=max(1, int((current.expires_at_ms - time.time_ns() // 1_000_000) / 1000)),
                )
                snapshot = self.job_store.get_job(job_id)
                if snapshot is None:
                    return None
                approval_state = _v2_approval_state(snapshot)
                plan = build_stage_plan(
                    snapshot.slots_manifest,
                    review_route=snapshot.review_route,
                    approval_state=approval_state,
                )
                plan = resolve_split_stage_plan(
                    plan,
                    job_store=self.job_store,
                    job_id=job_id,
                )
        language_only = bool(
            isinstance(snapshot.slots_manifest, dict)
            and isinstance(snapshot.slots_manifest.get("admission"), dict)
            and snapshot.slots_manifest["admission"].get("language_only")
        )
        plan_stage_names = [str(item.get("name") or "") for item in plan]
        if "parse_app_store_evidence" in plan_stage_names:
            early_dependencies = {
                "probe_source": ("bind_inputs",),
                "parse_app_store_evidence": ("bind_inputs",),
                "analyze_dynamics": ("probe_source",),
                "route_regions": ("analyze_dynamics",),
                "resolve_ui_evidence": ("route_regions", "parse_app_store_evidence"),
            }
            bind_checkpoint = self.job_store.get_stage_checkpoint(job_id, "bind_inputs")
            if bind_checkpoint is not None and bind_checkpoint.status == "SUCCEEDED":
                checkpoints = {
                    stage: self.job_store.get_stage_checkpoint(job_id, stage)
                    for stage in early_dependencies
                }
                enqueued: list[WorkMessage] = []
                for stage, dependencies in early_dependencies.items():
                    checkpoint = checkpoints[stage]
                    if checkpoint is not None and checkpoint.status in {"SUCCEEDED", "CLAIMED"}:
                        continue
                    if any(
                        (dependency_checkpoint := self.job_store.get_stage_checkpoint(job_id, dependency)) is None
                        or dependency_checkpoint.status != "SUCCEEDED"
                        for dependency in dependencies
                    ):
                        continue
                    dedupe_key = _dedupe(job_id, stage, snapshot)
                    message = WorkMessage(job_id, stage, snapshot.version, dedupe_key)
                    self.work_queue.enqueue(
                        job_id=message.job_id,
                        stage=message.stage,
                        expected_version=message.expected_version,
                        dedupe_key=message.dedupe_key,
                    )
                    enqueued.append(message)
                if enqueued:
                    return enqueued[0]
                if any(
                    checkpoint is None or checkpoint.status != "SUCCEEDED"
                    for checkpoint in checkpoints.values()
                ):
                    return None
        for item in plan:
            semantic_stage = str(item.get("name") or "")
            stage = self.runtime_stage(item)
            if semantic_stage == "await_script_approval":
                if not snapshot.approved_script_sha256:
                    return None
                continue
            if semantic_stage == "await_storyboard_approval":
                if not snapshot.approved_storyboard_sha256:
                    return None
                continue
            if stage not in EXECUTABLE_STAGES:
                continue
            if stage == "generate_storyboards" and not language_only and not snapshot.approved_script_sha256:
                return None
            if (
                not v2_active
                and
                stage in POST_APPROVAL_STAGES
                and not language_only
                and not snapshot.approved_storyboard_sha256
            ):
                return None
            checkpoint = self.job_store.get_stage_checkpoint(job_id, stage)
            if checkpoint is not None and checkpoint.status == "SUCCEEDED":
                # Script confirmation is a CAS-bound input to the existing
                # script semantic stage.  Its first lease produced only the
                # editable draft; after confirmation re-enter that same stage
                # exactly once so the worker can materialize final contracts
                # without adding another RunState stage or approval boundary.
                approval = None
                if (
                    stage == "build_script"
                    and snapshot.approved_script_sha256
                    and snapshot.current_script_revision is not None
                ):
                    getter = getattr(self.job_store, "get_script_approval", None)
                    if callable(getter):
                        approval = getter(job_id, snapshot.current_script_revision)
                recovery_dedupe = (
                    script_recovery_dedupe(job_id, snapshot, approval)
                    if stage == "build_script" and isinstance(approval, Mapping)
                    else dedupe_for(item, stage)
                )
                if (
                    stage == "build_script"
                    and approval is not None
                    and checkpoint.dedupe_key != recovery_dedupe
                ):
                    message = WorkMessage(job_id, stage, snapshot.version, recovery_dedupe)
                    self.work_queue.enqueue(
                        job_id=message.job_id,
                        stage=message.stage,
                        expected_version=message.expected_version,
                        dedupe_key=message.dedupe_key,
                    )
                    return message
                continue
            if checkpoint is not None and checkpoint.status == "CLAIMED":
                return None
            dedupe_key = dedupe_for(item, stage)
            message = WorkMessage(job_id, stage, snapshot.version, dedupe_key)
            self.work_queue.enqueue(
                job_id=message.job_id,
                stage=message.stage,
                expected_version=message.expected_version,
                dedupe_key=message.dedupe_key,
            )
            return message
        return None


__all__ = [
    "EphemeralStageDriver",
    "EXECUTABLE_STAGES",
    "POST_APPROVAL_STAGES",
    "SCRIPT_APPROVAL_STAGES",
    "qc_retry_dedupe",
]
