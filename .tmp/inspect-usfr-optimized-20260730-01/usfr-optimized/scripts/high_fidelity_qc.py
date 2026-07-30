"""Deterministic high-fidelity QC extension for the existing QC stage."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping


WEIGHTS = {
    "timeline_route": 10,
    "background_lighting": 12,
    "composition_camera": 10,
    "performance": 14,
    "action_chain": 16,
    "truth": 12,
    "voiceover_audio": 8,
    "overlays": 5,
    "commercial": 8,
    "continuity_technical": 5,
}

EVIDENCE_METHODS = {
    "deterministic_measurement",
    "automatic_model_comparison",
    "human_review",
}
EVIDENCE_KINDS = {
    "frame",
    "audio",
    "asr",
    "ocr",
    "probe",
    "timeline",
    "contract",
    "human_review",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
EVALUATOR_RECEIPT_SCHEMA = "high-fidelity-qc-evaluator-receipt/v1"


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _dimensions_digest(value: Mapping[str, Any]) -> str:
    """Digest score/evidence payload without the derived weight field."""

    projected: dict[str, Any] = {}
    for name in sorted(value):
        item = value[name]
        if isinstance(item, Mapping):
            row = {key: child for key, child in item.items() if key != "weight"}
            if "score" in row:
                row["score"] = float(row["score"])
            projected[name] = row
        else:
            projected[name] = item
    return _canonical_sha(projected)


def _factor_scores_digest(value: Mapping[str, Any]) -> str:
    projected: dict[str, Any] = {}
    for factor_id, item in value.items():
        if isinstance(item, Mapping):
            row = dict(item)
            if "score" in row:
                row["score"] = float(row["score"])
            projected[factor_id] = row
        else:
            projected[factor_id] = item
    return _canonical_sha(projected)


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label}.artifact_sha256 must be lowercase SHA-256")
    return value


def _validate_anchor(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    frame_id = value.get("frame_id")
    has_frame = isinstance(frame_id, (str, int)) and not isinstance(frame_id, bool) and bool(str(frame_id).strip())
    start_ms, end_ms = value.get("start_ms"), value.get("end_ms")
    has_time = (
        isinstance(start_ms, int)
        and not isinstance(start_ms, bool)
        and isinstance(end_ms, int)
        and not isinstance(end_ms, bool)
        and 0 <= start_ms <= end_ms
    )
    if not (has_frame or has_time):
        raise ValueError(f"{label} requires frame_id or start_ms/end_ms")


def _validate_reference(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    pointer = value.get("pointer")
    if not isinstance(pointer, str) or not pointer.strip():
        raise ValueError(f"{label}.pointer is required")
    _require_digest(value.get("artifact_sha256"), label)
    _validate_anchor(value, label)


def _validate_evidence(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    evidence_id = value.get("evidence_id")
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        raise ValueError(f"{label}.evidence_id is required")
    if value.get("kind") not in EVIDENCE_KINDS:
        raise ValueError(f"{label}.kind is invalid")
    if value.get("method") not in EVIDENCE_METHODS:
        raise ValueError(f"{label}.method is invalid")
    _validate_reference(value.get("source_ref"), f"{label}.source_ref")
    _validate_reference(value.get("target_ref"), f"{label}.target_ref")
    observation = value.get("observation")
    if not isinstance(observation, str) or not observation.strip():
        raise ValueError(f"{label}.observation is required")
    return dict(value)


def _validate_media_bindings(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("media_bindings must be an object")
    final_output_sha256 = _require_digest(
        value.get("final_output_sha256"), "media_bindings.final_output"
    )
    raw_sources = value.get("current_run_source_sha256s")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError(
            "media_bindings.current_run_source_sha256s requires at least one digest"
        )
    source_sha256s: list[str] = []
    for index, digest in enumerate(raw_sources, start=1):
        source_sha256s.append(
            _require_digest(digest, f"media_bindings.current_run_source_sha256s[{index}]")
        )
    return {
        "final_output_sha256": final_output_sha256,
        "current_run_source_sha256s": sorted(set(source_sha256s)),
    }


def _validate_evaluator_receipt(
    value: Any,
    *,
    media_bindings: Mapping[str, Any] | None = None,
    expected_identity: Mapping[str, Any] | None = None,
    dimensions_sha256: str | None = None,
    factor_scores_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate evaluator provenance without treating it as semantic proof.

    The receipt is an independent evaluator's cryptographic/provenance
    envelope.  It does not make a score true; it only proves which evaluator,
    model, request/response bytes, and exact current media set produced the
    evidence supplied to this QC extension.
    """

    if not isinstance(value, Mapping):
        raise ValueError("evaluator receipt must be an object")
    receipt = dict(value)
    if receipt.get("schema_version") != EVALUATOR_RECEIPT_SCHEMA:
        raise ValueError("evaluator receipt schema_version is unsupported")
    if receipt.get("provenance") != "independent_evaluator":
        raise ValueError("evaluator receipt provenance must be independent_evaluator")
    for field in ("implementation", "version", "model_id"):
        if not isinstance(receipt.get(field), str) or not receipt[field].strip():
            raise ValueError(f"evaluator receipt {field} is required")
    for field in (
        "model_sha256",
        "request_sha256",
        "response_sha256",
        "dimensions_sha256",
        "factor_scores_sha256",
    ):
        _require_digest(receipt.get(field), f"evaluator receipt {field}")
    if dimensions_sha256 and str(receipt.get("dimensions_sha256")) != dimensions_sha256:
        raise ValueError("evaluator receipt dimensions digest does not match QC input")
    if factor_scores_sha256 and str(receipt.get("factor_scores_sha256")) != factor_scores_sha256:
        raise ValueError("evaluator receipt factor-scores digest does not match QC input")
    raw_sources = receipt.get("current_run_source_sha256s")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("evaluator receipt current_run_source_sha256s is required")
    source_digests = [
        _require_digest(item, f"evaluator receipt current_run_source_sha256s[{index}]")
        for index, item in enumerate(raw_sources, start=1)
    ]
    if len(set(source_digests)) != len(source_digests):
        raise ValueError("evaluator receipt current_run_source_sha256s must be unique")
    if source_digests != sorted(source_digests):
        raise ValueError("evaluator receipt current_run_source_sha256s must be sorted")
    final_output = _require_digest(
        receipt.get("final_output_sha256"),
        "evaluator receipt final_output_sha256",
    )
    if media_bindings is not None:
        if final_output != str(media_bindings.get("final_output_sha256") or ""):
            raise ValueError("evaluator receipt final output does not match media_bindings")
        expected_sources = sorted(
            str(item)
            for item in media_bindings.get("current_run_source_sha256s", [])
        )
        if source_digests != expected_sources:
            raise ValueError("evaluator receipt source set does not match media_bindings")
    if expected_identity is not None:
        for field in ("implementation", "version", "model_id", "model_sha256"):
            expected = str(expected_identity.get(field) or "")
            if expected and str(receipt.get(field) or "") != expected:
                raise ValueError(f"evaluator receipt {field} does not match bound evaluator identity")
    return receipt


def _validate_evidence_list(
    value: Any,
    label: str,
    *,
    media_bindings: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} requires at least one evidence record")
    result = []
    seen: set[str] = set()
    final_output_sha256 = str(
        (media_bindings or {}).get("final_output_sha256") or ""
    )
    allowed_sources = {
        str(item)
        for item in (media_bindings or {}).get("current_run_source_sha256s", [])
    }
    final_output_bound = False
    for index, item in enumerate(value, start=1):
        evidence = _validate_evidence(item, f"{label}[{index}]")
        evidence_id = evidence["evidence_id"]
        if evidence_id in seen:
            raise ValueError(f"{label} repeats evidence_id {evidence_id}")
        seen.add(evidence_id)
        if media_bindings is not None:
            source_sha = str(evidence["source_ref"]["artifact_sha256"])
            if source_sha not in allowed_sources:
                raise ValueError(
                    f"{label}[{index}].source_ref is not bound to a current run source artifact"
                )
            target_sha = str(evidence["target_ref"]["artifact_sha256"])
            if target_sha == final_output_sha256:
                final_output_bound = True
        result.append(evidence)
    if media_bindings is not None and not final_output_bound:
        raise ValueError(
            f"{label} requires evidence bound to the current final output artifact"
        )
    return result


def normalize_asr(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("ASR text must be a string")
    value = unicodedata.normalize("NFKC", value).lower()
    value = "".join(
        char
        for char in value
        if not unicodedata.category(char).startswith("P") or char in {"'", "’"}
    )
    return re.sub(r"\s+", " ", value).strip()


def _score(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}.score must be numeric")
    value = float(value)
    if value < 0 or value > 100:
        raise ValueError(f"{name}.score must be between 0 and 100")
    return value


def build_qc_extension(
    *,
    dimensions: Mapping[str, Mapping[str, Any]],
    route_coverage: float,
    ui_ocr: float | None,
    hard_failures: list[str],
    factor_scores: Mapping[str, Mapping[str, Any]] | None = None,
    media_bindings: Mapping[str, Any] | None = None,
    evaluator_receipt: Mapping[str, Any] | None = None,
    expected_evaluator_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if set(dimensions) != set(WEIGHTS):
        missing = sorted(set(WEIGHTS) - set(dimensions))
        extra = sorted(set(dimensions) - set(WEIGHTS))
        raise ValueError(f"QC dimensions must match weights; missing={missing}, extra={extra}")
    normalized_media_bindings = _validate_media_bindings(media_bindings)
    normalized_receipt = None
    normalized = {}
    total = 0.0
    for name, weight in WEIGHTS.items():
        item = dimensions[name]
        if not isinstance(item, Mapping):
            raise ValueError(f"QC dimension {name} must be an object")
        score = _score(item.get("score"), name)
        evidence = _validate_evidence_list(
            item.get("evidence"),
            f"QC dimension {name}.evidence",
            media_bindings=normalized_media_bindings,
        )
        criticality = item.get("criticality", "M")
        if criticality not in {"H", "M", "L"}:
            raise ValueError(f"QC dimension {name} criticality is invalid")
        if name == "voiceover_audio":
            if criticality != "H":
                raise ValueError(
                    "QC dimension voiceover_audio criticality must be H"
                )
            if not any(
                record.get("kind") in {"audio", "asr"}
                for record in evidence
            ):
                raise ValueError(
                    "QC dimension voiceover_audio requires final audio/ASR evidence"
                )
        normalized[name] = {**dict(item), "score": score, "weight": weight, "evidence": evidence}
        total += score * weight / 100.0
    if isinstance(route_coverage, bool) or not isinstance(route_coverage, (int, float)) or not 0 <= route_coverage <= 100:
        raise ValueError("route_coverage must be between 0 and 100")
    if ui_ocr is not None and (isinstance(ui_ocr, bool) or not isinstance(ui_ocr, (int, float)) or not 0 <= ui_ocr <= 100):
        raise ValueError("ui_ocr must be between 0 and 100")
    normalized_factors: dict[str, dict[str, Any]] = {}
    for factor_id, item in (factor_scores or {}).items():
        if not isinstance(factor_id, str) or not factor_id.strip():
            raise ValueError("factor_scores IDs must be non-empty strings")
        if not isinstance(item, Mapping):
            raise ValueError(f"factor_scores.{factor_id} must be an object")
        factor = dict(item)
        factor["score"] = _score(factor.get("score"), f"factor_scores.{factor_id}")
        factor["evidence"] = _validate_evidence_list(
            factor.get("evidence"),
            f"factor_scores.{factor_id}.evidence",
            media_bindings=normalized_media_bindings,
        )
        criticality = factor.get("criticality", "M")
        if criticality not in {"H", "M", "L"}:
            raise ValueError(f"factor_scores.{factor_id}.criticality is invalid")
        normalized_factors[factor_id] = factor

    if evaluator_receipt is not None:
        normalized_receipt = _validate_evaluator_receipt(
            evaluator_receipt,
            media_bindings=normalized_media_bindings,
            expected_identity=expected_evaluator_identity,
            dimensions_sha256=_dimensions_digest(dimensions),
            factor_scores_sha256=_factor_scores_digest(factor_scores or {}),
        )

    extension = {
        "schema_version": "high-fidelity-qc/v1",
        "profile": "high_fidelity_hybrid_v1",
        "dimensions": normalized,
        "total_score": round(total, 2),
        "route_coverage": float(route_coverage),
        "ui_ocr": None if ui_ocr is None else float(ui_ocr),
        "hard_failures": list(hard_failures),
        "factor_scores": normalized_factors,
    }
    if normalized_media_bindings is not None:
        extension["media_bindings"] = normalized_media_bindings
    if normalized_receipt is not None:
        extension["evaluator_receipt"] = normalized_receipt
    extension["accepted"] = _acceptance(extension)
    return extension


def _acceptance(report: Mapping[str, Any]) -> bool:
    if report.get("hard_failures"):
        return False
    if float(report.get("total_score", 0)) < 85:
        return False
    if float(report.get("route_coverage", 0)) != 100:
        return False
    if report.get("ui_ocr") is not None and float(report["ui_ocr"]) != 100:
        return False
    for item in (report.get("dimensions") or {}).values():
        if item.get("criticality") == "H" and float(item.get("score", 0)) < 90:
            return False
    for item in (report.get("factor_scores") or {}).values():
        if item.get("criticality") == "H" and float(item.get("score", 0)) < 90:
            return False
    return True


def validate_qc_extension(
    report: Mapping[str, Any],
    *,
    require_evaluator_receipt: bool = False,
    expected_evaluator_identity: Mapping[str, Any] | None = None,
) -> None:
    if not isinstance(report, Mapping) or report.get("schema_version") != "high-fidelity-qc/v1":
        raise ValueError("unsupported high-fidelity QC extension")
    dimensions = report.get("dimensions")
    if not isinstance(dimensions, Mapping):
        raise ValueError("QC dimensions are required")
    # Rebuild the score to prevent an operator/model from asserting a false pass.
    media_bindings = report.get("media_bindings")
    if require_evaluator_receipt:
        if not isinstance(media_bindings, Mapping):
            raise ValueError("active high-fidelity QC requires media_bindings")
        if not isinstance(report.get("evaluator_receipt"), Mapping):
            raise ValueError("active high-fidelity QC requires an evaluator receipt")
    rebuilt = build_qc_extension(
        dimensions=dimensions,
        route_coverage=report.get("route_coverage"),
        ui_ocr=report.get("ui_ocr"),
        hard_failures=list(report.get("hard_failures") or []),
        factor_scores=report.get("factor_scores") or {},
        media_bindings=media_bindings,
        evaluator_receipt=report.get("evaluator_receipt"),
        expected_evaluator_identity=expected_evaluator_identity,
    )
    if rebuilt["total_score"] != report.get("total_score"):
        raise ValueError("QC total score mismatch")
    if not rebuilt["accepted"] or report.get("accepted") is not True:
        raise ValueError("high-fidelity QC acceptance gates failed")
