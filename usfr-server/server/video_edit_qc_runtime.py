"""Runtime helpers for the server-owned v2 QC retry boundary."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import ReplicationError
from .seedance_request_audit_contract import canonical_audit_fingerprint
from .video_edit_qc_contract import (
    EVIDENCE_CONTRACT,
    RULESET_SHA256,
    canonical_sha256,
    require_sha256,
)


QC_RETRY_FAILURE_TYPES = frozenset(
    {
        "identity_replacement_incomplete",
        "replacement_incomplete",
        "preservation_drift",
        "dialogue_mismatch",
    }
)

V2_CURRENT_RUNTIME_STAGES: dict[str, tuple[str, ...]] = {
    "assembled_video": ("splice_timeline",),
    "provider_video": (
        "wait_provider_video_pass1",
        "wait_provider_video_pass2",
        "wait_provider_video",
    ),
    "hybrid_composite_manifest": ("splice_timeline",),
    "seedance_request_audit": (
        "compile_seedance20_prompt",
        "submit_provider_video",
    ),
}


@dataclass(frozen=True)
class QcRetryDecision:
    failure_type: str
    evidence_artifact_id: str
    evidence_sha256: str
    assembled_artifact_id: str
    assembled_sha256: str
    source_sha256: str
    approved_script_sha256: str
    timeline_manifest_sha256: str
    asset_binding_sha256: str
    details: Mapping[str, Any]

    @property
    def is_safety_blocker(self) -> bool:
        return self.failure_type == "safety_violation"


class QcRetryEvidenceError(ValueError):
    """A QC evidence receipt cannot authorize a retry."""

    def __init__(
        self,
        message: str,
        *,
        field: str = "video_edit_qc_evidence",
        code: str = "QC_EVIDENCE_INVALID",
    ) -> None:
        super().__init__(message)
        self.field = field
        self.code = code


def _invalid(message: str, *, field: str = "video_edit_qc_evidence") -> None:
    raise QcRetryEvidenceError(message, field=field)


def _artifact_rows(context: Any, kind: str) -> list[Mapping[str, Any]]:
    rows = [
        item
        for item in (getattr(context, "artifacts", ()) or ())
        if isinstance(item, Mapping) and str(item.get("kind") or "") == kind
    ]
    if not rows:
        job_store = getattr(context, "job_store", None)
        getter = getattr(job_store, "list_artifacts", None)
        if callable(getter):
            rows = [
                item.to_dict()
                for item in getter(getattr(context, "job_id", None))
                if str(item.kind or "") == kind
            ]
    if not rows:
        _invalid(f"current {kind} artifact is missing", field=kind)
    return rows


def v2_stage_output_artifact_id(stage_outputs: Any, kind: str) -> str | None:
    stages = V2_CURRENT_RUNTIME_STAGES.get(kind)
    if stages is None:
        return None
    if not isinstance(stage_outputs, Mapping):
        raise ValueError(f"current {kind} requires formal stage output")

    found: list[str] = []
    for stage_name in stages:
        stage_output = stage_outputs.get(stage_name)
        if not isinstance(stage_output, Mapping):
            continue
        candidates: list[Any] = []
        if "output_artifact" in stage_output:
            candidates.append(stage_output.get("output_artifact"))
        for field in ("published_artifacts", "output_artifacts"):
            value = stage_output.get(field)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                candidates.extend(value)
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            if str(candidate.get("kind") or "") != kind:
                continue
            artifact_id = str(candidate.get("artifact_id") or "")
            if artifact_id:
                found.append(artifact_id)

    unique = tuple(dict.fromkeys(found))
    if len(unique) > 1:
        raise ValueError(f"current {kind} stage output is ambiguous")
    if not unique:
        raise ValueError(f"current {kind} formal stage output is missing")
    return unique[0]


def _current_stage_output_artifact(context: Any, kind: str) -> Mapping[str, Any] | None:
    stage_outputs = getattr(context, "stage_outputs", None)
    try:
        artifact_id = v2_stage_output_artifact_id(stage_outputs, kind)
    except ValueError as exc:
        _invalid(str(exc), field=kind)
    if artifact_id is None:
        return None
    rows = [
        row for row in _artifact_rows(context, kind)
        if str(row.get("artifact_id") or "") == artifact_id
    ]
    if len(rows) != 1:
        _invalid(f"current {kind} stage output is not published", field=kind)
    return rows[0]


def _current_artifact(context: Any, kind: str) -> Mapping[str, Any]:
    rows = _artifact_rows(context, kind)
    row = _current_stage_output_artifact(context, kind)
    if row is None:
        if len(rows) != 1:
            _invalid(f"current {kind} artifact is ambiguous", field=kind)
        row = rows[0]
    try:
        require_sha256(row.get("sha256"), field=f"{kind}.sha256")
    except ValueError as exc:
        raise QcRetryEvidenceError(str(exc), field=kind) from exc
    if not str(row.get("artifact_id") or ""):
        _invalid(f"current {kind} artifact id is missing", field=kind)
    return row


def _unique_artifact(context: Any, kind: str) -> Mapping[str, Any]:
    rows = _artifact_rows(context, kind)
    if len(rows) != 1:
        _invalid(f"current {kind} artifact is ambiguous", field=kind)
    row = rows[0]
    try:
        require_sha256(row.get("sha256"), field=f"{kind}.sha256")
    except ValueError as exc:
        raise QcRetryEvidenceError(str(exc), field=kind) from exc
    if not str(row.get("artifact_id") or ""):
        _invalid(f"current {kind} artifact id is missing", field=kind)
    return row


def _read_artifact(context: Any, descriptor: Mapping[str, Any]) -> bytes:
    kind = str(descriptor.get("kind") or "")
    artifact_id = str(descriptor.get("artifact_id") or "")
    expected_sha = str(descriptor.get("sha256") or "").lower()
    try:
        with context.materialize_artifact(
            kind,
            artifact_id=artifact_id,
            sha256=expected_sha,
        ) as media:
            raw = Path(media.path).read_bytes()
    except ReplicationError as exc:
        code = (
            "ARTIFACT_NOT_FOUND"
            if exc.code == "ARTIFACT_NOT_FOUND"
            else "ARTIFACT_MATERIALIZE_UNAVAILABLE"
        )
        raise QcRetryEvidenceError(
            f"{kind} artifact cannot be materialized",
            field=kind,
            code=code,
        ) from exc
    except OSError as exc:
        raise QcRetryEvidenceError(
            f"{kind} artifact cannot be materialized",
            field=kind,
            code="ARTIFACT_MATERIALIZE_UNAVAILABLE",
        ) from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise QcRetryEvidenceError(
            f"{kind} artifact bytes differ from descriptor",
            field=kind,
            code="ARTIFACT_HASH_MISMATCH",
        )
    return raw


def _read_json(context: Any, descriptor: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        value = json.loads(_read_artifact(context, descriptor).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QcRetryEvidenceError(
            f"{descriptor.get('kind')} artifact is not canonical JSON",
            field=str(descriptor.get("kind") or "artifact"),
        ) from exc
    if not isinstance(value, Mapping):
        _invalid(
            f"{descriptor.get('kind')} artifact must be an object",
            field=str(descriptor.get("kind") or "artifact"),
        )
    return dict(value)


def _qc_invalid(exc: QcRetryEvidenceError) -> ReplicationError:
    return ReplicationError(
        "QC_EVIDENCE_INVALID",
        str(exc),
        category="quality",
        retryable=False,
        details={"lineage_field": exc.field},
    )


def _qc_retry_decision_for_assembled(
    context: Any,
    assembled: Mapping[str, Any],
    *,
    recovery: bool = False,
) -> QcRetryDecision:
    """Validate one failing QC receipt against a selected assembled artifact."""

    try:
        source = _unique_artifact(context, "source_video")
        timeline = (
            _unique_artifact(context, "hybrid_composite_manifest")
            if recovery
            else _current_artifact(context, "hybrid_composite_manifest")
        )
        asset = _unique_artifact(context, "asset_board_manifest")
        snapshot = getattr(context, "snapshot", None)
        script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
        require_sha256(script_sha, field="approved_script_sha256")
        assembled_sha = str(assembled.get("sha256") or "").lower()
        source_sha = str(source.get("sha256") or "").lower()
        timeline_sha = str(timeline.get("sha256") or "").lower()
        asset_sha = str(asset.get("sha256") or "").lower()
        candidates: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        for descriptor in _artifact_rows(context, "video_edit_qc_evidence"):
            evidence_sha = str(descriptor.get("sha256") or "").lower()
            try:
                require_sha256(evidence_sha, field="video_edit_qc_evidence.sha256")
            except ValueError as exc:
                raise QcRetryEvidenceError(str(exc)) from exc
            raw = _read_artifact(context, descriptor)
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise QcRetryEvidenceError(
                    "video_edit_qc_evidence is not canonical JSON"
                ) from exc
            if not isinstance(body, Mapping):
                _invalid("video_edit_qc_evidence must be an object")
            if (
                body.get("assembled_video_artifact_id") == assembled.get("artifact_id")
                and str(body.get("assembled_video_sha256") or "").lower() == assembled_sha
            ):
                candidates.append((descriptor, dict(body)))
        if len(candidates) != 1:
            _invalid(
                "exactly one current QC evidence receipt must match the assembled artifact",
                field="assembled_video_artifact_id",
            )
        descriptor, body = candidates[0]
        if body.get("contract") != EVIDENCE_CONTRACT:
            _invalid("QC evidence contract is invalid", field="contract")
        if str(body.get("ruleset_sha256") or "").lower() != RULESET_SHA256:
            _invalid("QC evidence ruleset is not authoritative", field="ruleset_sha256")
        if body.get("passed") is not False or body.get("overall_status") != "FAIL":
            _invalid("QC evidence is not a failing receipt", field="overall_status")
        failure_type = str(body.get("failure_type") or "").strip()
        if failure_type not in QC_RETRY_FAILURE_TYPES and failure_type != "safety_violation":
            _invalid("QC evidence failure type is not retry-authorized", field="failure_type")
        checks = body.get("checks")
        if not isinstance(checks, Mapping):
            _invalid("QC evidence checks are missing", field="checks")
        hard_failures = checks.get("hard_failures")
        if not isinstance(hard_failures, list) or not hard_failures:
            _invalid("QC evidence hard failures are missing", field="checks.hard_failures")
        expected = {
            "assembled_video_sha256": assembled_sha,
            "source_video_sha256": source_sha,
            "approved_script_sha256": script_sha,
            "timeline_manifest_sha256": timeline_sha,
            "asset_binding_sha256": asset_sha,
        }
        for field, value in expected.items():
            if str(body.get(field) or "").lower() != value:
                _invalid(f"QC evidence {field} is foreign or stale", field=field)
        details: dict[str, Any] = {}
        if failure_type == "safety_violation":
            edit_checks = checks.get("edit_checks")
            safety_checks = edit_checks.get("safety_checks") if isinstance(edit_checks, Mapping) else None
            failed_safety = [
                row for row in (safety_checks or ())
                if isinstance(row, Mapping) and str(row.get("verdict") or "").lower() == "fail"
            ]
            if len(failed_safety) != 1:
                _invalid("safety failure receipt is ambiguous", field="checks.edit_checks.safety_checks")
            details = {
                "scope": failed_safety[0].get("scope"),
                "check_id": failed_safety[0].get("check_id"),
            }
            if not details["scope"] or not details["check_id"]:
                _invalid("safety failure details are incomplete", field="checks.edit_checks.safety_checks")
        return QcRetryDecision(
            failure_type=failure_type,
            evidence_artifact_id=str(descriptor.get("artifact_id") or ""),
            evidence_sha256=str(descriptor.get("sha256") or "").lower(),
            assembled_artifact_id=str(assembled.get("artifact_id") or ""),
            assembled_sha256=assembled_sha,
            source_sha256=source_sha,
            approved_script_sha256=script_sha,
            timeline_manifest_sha256=timeline_sha,
            asset_binding_sha256=asset_sha,
            details=details,
        )
    except QcRetryEvidenceError as exc:
        raise _qc_invalid(exc) from exc


def current_qc_retry_decision(context: Any) -> QcRetryDecision:
    """Validate exactly one current failing QC receipt against current lineage."""

    try:
        return _qc_retry_decision_for_assembled(
            context,
            _current_artifact(context, "assembled_video"),
        )
    except QcRetryEvidenceError as exc:
        raise _qc_invalid(exc) from exc


def _submit_recovery_assembled(context: Any) -> Mapping[str, Any]:
    assembled_rows = _artifact_rows(context, "assembled_video")
    for row in assembled_rows:
        try:
            require_sha256(row.get("sha256"), field="assembled_video.sha256")
        except ValueError as exc:
            raise QcRetryEvidenceError(str(exc), field="assembled_video") from exc
        if not str(row.get("artifact_id") or ""):
            _invalid("assembled_video artifact id is missing", field="assembled_video")

    matches: list[Mapping[str, Any]] = []
    for descriptor in _artifact_rows(context, "video_edit_qc_evidence"):
        raw = _read_artifact(context, descriptor)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QcRetryEvidenceError(
                "video_edit_qc_evidence is not canonical JSON"
            ) from exc
        if not isinstance(body, Mapping):
            _invalid("video_edit_qc_evidence must be an object")
        bound = [
            row
            for row in assembled_rows
            if body.get("assembled_video_artifact_id") == row.get("artifact_id")
            and str(body.get("assembled_video_sha256") or "").lower()
            == str(row.get("sha256") or "").lower()
        ]
        if len(bound) > 1:
            _invalid(
                "assembled_video descriptor binding is ambiguous",
                field="assembled_video_artifact_id",
            )
        if len(bound) == 1:
            matches.append(bound[0])

    keys = {
        (str(row.get("artifact_id") or ""), str(row.get("sha256") or "").lower())
        for row in matches
    }
    if len(keys) != 1:
        _invalid(
            "exactly one immutable QC evidence receipt must bind one assembled artifact",
            field="assembled_video_artifact_id",
        )
    assembled = next(row for row in assembled_rows if (
        str(row.get("artifact_id") or ""),
        str(row.get("sha256") or "").lower(),
    ) == next(iter(keys)))
    _read_artifact(context, assembled)
    return assembled


def _submit_has_prior_qc_retry(context: Any) -> bool:
    attempts = getattr(context, "job_store", None).list_provider_attempts(context.job_id)
    if any(item.retry_index == 2 for item in attempts):
        return True
    for descriptor in _artifact_rows(context, "seedance_request_audit"):
        audit = _read_json(context, descriptor)
        rows = audit.get("segments")
        if isinstance(rows, list) and any(
            isinstance(row, Mapping) and is_qc_retry_row(row.get("retry"))
            for row in rows
        ):
            return True
    return False


def current_qc_retry_decision_for_submit(context: Any) -> QcRetryDecision:
    """Recover one QC retry authority after downstream stage invalidation.

    This path is limited to provider submission.  It uses the unique evidence
    binding to select the assembled bytes and never infers currentness from
    unrelated stage output or artifact ordering.
    """

    if _submit_has_prior_qc_retry(context):
        return current_qc_retry_decision(context)
    try:
        assembled = _submit_recovery_assembled(context)
        return _qc_retry_decision_for_assembled(context, assembled, recovery=True)
    except QcRetryEvidenceError as exc:
        raise _qc_invalid(exc) from exc


def formal_stage_artifact_identity(
    job_store: Any,
    job_id: str,
    *,
    stage: str,
    kind: str,
) -> tuple[str, str]:
    """Read one current immutable descriptor from a formal stage checkpoint."""

    checkpoint = job_store.get_stage_checkpoint(job_id, stage)
    if checkpoint is None or checkpoint.status != "SUCCEEDED":
        raise QcRetryEvidenceError(f"{stage} has no successful current checkpoint", field=stage)
    matches: list[tuple[str, str]] = []
    for artifact_id in checkpoint.output_artifact_ids:
        artifact = job_store.get_artifact(job_id, artifact_id)
        if artifact is None or str(getattr(artifact, "kind", "")) != kind:
            continue
        descriptor_id = str(getattr(artifact, "artifact_id", "") or "")
        descriptor_sha = str(getattr(artifact, "sha256", "") or "").lower()
        try:
            require_sha256(descriptor_sha, field=f"{kind}.sha256")
        except ValueError as exc:
            raise QcRetryEvidenceError(str(exc), field=kind) from exc
        if not descriptor_id:
            _invalid(f"{kind} artifact id is missing", field=kind)
        matches.append((descriptor_id, descriptor_sha))
    unique = tuple(dict.fromkeys(matches))
    if len(unique) != 1:
        raise QcRetryEvidenceError(
            f"{stage} must publish exactly one current {kind} descriptor",
            field=kind,
        )
    return unique[0]


_RETRY_ADJUSTMENTS = {
    "identity_replacement_incomplete": "strengthen approved identity lock in the changed windows",
    "replacement_incomplete": "strengthen the approved replacement in the changed windows",
    "preservation_drift": "preserve unchanged regions and source UI outside changed windows",
    "dialogue_mismatch": "match the approved changed dialogue exactly",
}


def is_qc_retry_row(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("retry_index") == 2
        and bool(str(value.get("failed_qc_evidence_artifact_id") or ""))
    )


def build_qc_retry_audit(
    audit: Mapping[str, Any],
    *,
    decision: QcRetryDecision,
    parent_attempts: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive one immutable retry audit from the already validated audit."""

    if not isinstance(audit, Mapping) or audit.get("schema_version") != "seedance-request-audit/v2":
        raise ValueError("QC retry requires a v2 seedance request audit")
    result = json.loads(json.dumps(dict(audit), ensure_ascii=False))
    segments = result.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("QC retry audit has no segments")
    adjustment = _RETRY_ADJUSTMENTS[decision.failure_type]
    target_changes = [{"failure_type": decision.failure_type, "adjustment": adjustment}]
    for raw in segments:
        if not isinstance(raw, dict):
            raise ValueError("QC retry audit segment is invalid")
        segment_id = str(raw.get("segment_id") or "")
        parent = parent_attempts.get(segment_id)
        if parent is None or parent.status != "SUCCEEDED":
            raise ValueError("QC retry parent attempt is not a successful candidate")
        retry = {
            "parent_attempt_id": parent.attempt_id,
            "parent_request_sha256": parent.request_sha256,
            "failed_qc_evidence_artifact_id": decision.evidence_artifact_id,
            "failed_qc_evidence_sha256": decision.evidence_sha256,
            "retry_index": 2,
            "failure_type": decision.failure_type,
            "assembled_video_artifact_id": decision.assembled_artifact_id,
            "assembled_video_sha256": decision.assembled_sha256,
            "source_video_sha256": decision.source_sha256,
            "approved_script_sha256": decision.approved_script_sha256,
            "timeline_manifest_sha256": decision.timeline_manifest_sha256,
            "segment_plan_sha256": str(raw.get("segment_plan_sha256") or "").lower(),
            "asset_board_manifest_sha256": decision.asset_binding_sha256,
            "target_changes": target_changes,
        }
        raw["retry"] = retry
        payload = raw.get("payload_template")
        if not isinstance(payload, dict):
            raise ValueError("QC retry payload template is invalid")
        prompt = str(payload.get("prompt") or "")
        if not prompt:
            raise ValueError("QC retry prompt is missing")
        payload["prompt"] = f"{prompt} QC repair: {adjustment}."
        binding = raw.get("video_reference_binding")
        if isinstance(binding, dict):
            binding["target_changes"] = target_changes
    result["stage_fingerprint"] = canonical_audit_fingerprint(result)
    return result


def audit_sha256(value: Mapping[str, Any]) -> str:
    return canonical_sha256(value)


__all__ = [
    "QC_RETRY_FAILURE_TYPES",
    "QcRetryDecision",
    "audit_sha256",
    "build_qc_retry_audit",
    "current_qc_retry_decision",
    "current_qc_retry_decision_for_submit",
    "formal_stage_artifact_identity",
    "is_qc_retry_row",
    "read_immutable_artifact",
]


read_immutable_artifact = _read_artifact
