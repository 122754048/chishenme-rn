"""Deterministic Redis-queue driver for the twelve-stage video workflow."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .job_models import WorkMessage
from .orchestrator import build_stage_plan


POST_APPROVAL_STAGES = (
    "segment_plan",
    "compile_seedance20_prompt",
    "audit_seedance_request",
    "submit_provider_video",
    "wait_provider_video",
    "splice_timeline",
    "run_qc",
)
EXECUTABLE_STAGES = (
    "bind_inputs",
    "probe_source",
    "analyze_dynamics",
    "route_regions",
    "parse_app_store_evidence",
    "resolve_ui_evidence",
    "build_script",
    "generate_storyboards",
    *POST_APPROVAL_STAGES,
)


def _dedupe(job_id: str, stage: str, snapshot: Any) -> str:
    payload = json.dumps(
        {
            "job_id": job_id,
            "stage": stage,
            "approved_script_sha256": snapshot.approved_script_sha256,
            "approved_storyboard_sha256": snapshot.approved_storyboard_sha256,
            "slots_manifest": snapshot.slots_manifest,
        },
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


class EphemeralStageDriver:
    def __init__(self, job_store: Any, work_queue: Any) -> None:
        self.job_store = job_store
        self.work_queue = work_queue

    def enqueue_next(self, job_id: str) -> WorkMessage | None:
        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            return None
        if snapshot.review_route == "route_1":
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
        plan = build_stage_plan(
            snapshot.slots_manifest,
            review_route=snapshot.review_route,
        )
        language_only = bool(
            isinstance(snapshot.slots_manifest, dict)
            and isinstance(snapshot.slots_manifest.get("admission"), dict)
            and snapshot.slots_manifest["admission"].get("language_only")
        )
        for item in plan:
            stage = str(item.get("name") or "")
            if stage == "await_script_approval":
                if not snapshot.approved_script_sha256:
                    return None
                continue
            if stage == "await_storyboard_approval":
                if not snapshot.approved_storyboard_sha256:
                    return None
                continue
            if stage not in EXECUTABLE_STAGES:
                continue
            if stage == "generate_storyboards" and not language_only and not snapshot.approved_script_sha256:
                return None
            if stage in POST_APPROVAL_STAGES and not language_only and not snapshot.approved_storyboard_sha256:
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
                    else _dedupe(job_id, stage, snapshot)
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
            dedupe_key = _dedupe(job_id, stage, snapshot)
            message = WorkMessage(job_id, stage, snapshot.version, dedupe_key)
            self.work_queue.enqueue(
                job_id=message.job_id,
                stage=message.stage,
                expected_version=message.expected_version,
                dedupe_key=message.dedupe_key,
            )
            return message
        return None


__all__ = ["EphemeralStageDriver", "EXECUTABLE_STAGES", "POST_APPROVAL_STAGES"]
