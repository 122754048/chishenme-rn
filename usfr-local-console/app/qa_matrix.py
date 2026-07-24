from __future__ import annotations

from collections.abc import Mapping


class QaMatrixError(ValueError):
    pass


def build_qa_matrix(
    execution_map: Mapping[str, object], source_contract: Mapping[str, object]
) -> dict[str, object]:
    source_by_id = _source_regions(source_contract)
    mapped_regions = execution_map.get("regions") or []
    if not isinstance(mapped_regions, list):
        raise QaMatrixError("QA_MATRIX_INVALID")
    rows: list[dict[str, object]] = []
    for region in mapped_regions:
        if not isinstance(region, Mapping) or not isinstance(region.get("region_id"), str):
            raise QaMatrixError("QA_MATRIX_INVALID")
        region_id = region["region_id"]
        media_origin = str(region.get("media_origin") or "")
        source = source_by_id.get(region_id, {})
        required, skipped, risk_reasons = _checks_for_region(region, source, media_origin)
        rows.append(
            {
                "region_id": region_id,
                "media_origin": media_origin,
                "required_checks": required,
                "skipped_checks": skipped,
                "risk_reasons": risk_reasons,
                "evidence_inputs": [region_id],
            }
        )
    return {"schema_version": 1, "regions": rows, "final_technical_qc": True}


def validate_qa_coverage(*, qa_receipt: Mapping[str, object], qa_matrix: Mapping[str, object]) -> None:
    expected_rows = qa_matrix.get("regions") or []
    received_rows = qa_receipt.get("regions") or []
    if not isinstance(expected_rows, list) or not isinstance(received_rows, list):
        raise QaMatrixError("QA_COVERAGE_REQUIRED")
    expected_ids = [
        row.get("region_id")
        for row in expected_rows
        if isinstance(row, Mapping) and isinstance(row.get("region_id"), str)
    ]
    if len(expected_ids) != len(expected_rows) or len(set(expected_ids)) != len(expected_ids):
        raise QaMatrixError("QA_COVERAGE_REQUIRED")
    if any(not isinstance(row, Mapping) or not isinstance(row.get("region_id"), str) for row in received_rows):
        raise QaMatrixError("QA_COVERAGE_REQUIRED")
    received_ids = [row["region_id"] for row in received_rows]
    if len(received_ids) != len(set(received_ids)) or set(received_ids) != set(expected_ids):
        raise QaMatrixError("QA_COVERAGE_REQUIRED")
    received_by_id = {row["region_id"]: row for row in received_rows}
    for expected in expected_rows:
        if not isinstance(expected, Mapping) or not isinstance(expected.get("region_id"), str):
            raise QaMatrixError("QA_COVERAGE_REQUIRED")
        received = received_by_id.get(expected["region_id"])
        if not isinstance(received, Mapping) or not isinstance(received.get("checks"), Mapping):
            raise QaMatrixError("QA_COVERAGE_REQUIRED")
        checks = received["checks"]
        if expected.get("media_origin") in {"opaque_ui", "opaque_tail"}:
            if any(check in checks for check in expected.get("skipped_checks", [])):
                raise QaMatrixError("QA_OPAQUE_SEMANTIC_CHECK_FORBIDDEN")
        for check_id in expected.get("required_checks", []):
            evidence = checks.get(check_id)
            if not isinstance(evidence, Mapping) or evidence.get("passed") is not True:
                raise QaMatrixError("QA_COVERAGE_REQUIRED")
    final_technical = qa_receipt.get("final_technical")
    if qa_matrix.get("final_technical_qc") is True and (
        not isinstance(final_technical, Mapping) or final_technical.get("passed") is not True
    ):
        raise QaMatrixError("QA_COVERAGE_REQUIRED")


def _source_regions(source_contract: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    rows = source_contract.get("regions") or source_contract.get("cuts") or []
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("region_id") or row.get("cut_id") or row.get("id")): row
        for row in rows
        if isinstance(row, Mapping)
    }


def _checks_for_region(
    region: Mapping[str, object], source: Mapping[str, object], media_origin: str
) -> tuple[list[str], list[str], list[str]]:
    if media_origin in {"opaque_ui", "opaque_tail"}:
        return ["technical_stream", "timeline_placement"], ["ui_ocr_layout", "semantic_claims", "identity_consistency"], []
    if media_origin == "omitted":
        return [], ["all"], []
    if media_origin == "generated_ui":
        return ["ui_ocr_layout", "ui_animation", "timeline_placement"], [], ["generated_ui"]
    changed_layers = set(region.get("changed_layers") or [])
    required = ["timeline_placement"]
    skipped: list[str] = []
    risks: list[str] = []
    if "model" in changed_layers:
        required.append("identity_consistency")
    if "product" in changed_layers:
        required.append("product_truth")
    if source.get("close_face") is True or source.get("speaking") is True:
        risks.append("close_face_speaking")
        if "model" in changed_layers:
            required.append("lip_sync")
    if source.get("handheld_product") is True:
        risks.append("handheld_product")
        if "product" in changed_layers:
            required.append("hand_product_contact")
    if source.get("fast_hand_motion") is True or source.get("complex_motion") is True:
        risks.append("complex_motion")
        required.append("motion_continuity")
    if source.get("strong_transition") is True:
        risks.append("strong_transition")
        required.append("transition_integrity")
    return _dedupe(required), skipped, risks


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
