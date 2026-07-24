"""Validate incremental or immutable USFR case-matrix quality evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTEXT_FIELDS = (
    "bundle_sha256",
    "capability_sha256",
    "model_sha256",
    "provider_sha256",
    "prompt_compiler_sha256",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def case_dependency_fingerprint(
    case: Mapping[str, Any], dependency_context: Mapping[str, Any]
) -> str:
    payload = {
        "case": case,
        "dependency_context": {
            field: dependency_context.get(field) for field in _CONTEXT_FIELDS
        },
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _private_fixture_failures(case: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    records = [case.get("source_fixture"), *(case.get("replacement_fixtures") or [])]
    for record in records:
        if not isinstance(record, Mapping):
            continue
        asset_id = record.get("asset_id")
        if not isinstance(asset_id, str):
            continue
        if asset_id.startswith("fixtures/"):
            failures.append(
                f"{case.get('case_id')}: immutable release fixture requires a private object reference"
            )
    return failures


def _score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    return score if 0 <= score <= 100 else None


def _receipt_failures(
    case: Mapping[str, Any], result: Mapping[str, Any], final_sha: str
) -> list[str]:
    case_id = str(case.get("case_id"))
    failures: list[str] = []
    source = case.get("source_fixture")
    source_sha = source.get("sha256") if isinstance(source, Mapping) else None
    replacements = case.get("replacement_fixtures") or []
    replacement_sha = [
        item.get("sha256") for item in replacements if isinstance(item, Mapping)
    ]

    fixture = result.get("fixture_receipt")
    if (
        not isinstance(fixture, Mapping)
        or fixture.get("verified") is not True
        or not _valid_sha(fixture.get("receipt_sha256"))
        or fixture.get("source_sha256") != source_sha
        or fixture.get("replacement_sha256") != replacement_sha
    ):
        failures.append(f"{case_id}: fixture receipt binding is invalid")

    evaluator = result.get("evaluator_receipt")
    if not isinstance(evaluator, Mapping):
        failures.append(f"{case_id}: independent evaluator receipt is required")
        return failures
    required_hashes = (
        "model_sha256",
        "request_sha256",
        "response_sha256",
        "receipt_sha256",
    )
    if (
        evaluator.get("verified") is not True
        or not isinstance(evaluator.get("evaluator"), str)
        or not evaluator.get("evaluator")
        or any(not _valid_sha(evaluator.get(field)) for field in required_hashes)
    ):
        failures.append(f"{case_id}: independent evaluator receipt is invalid")
    if (
        evaluator.get("source_sha256") != source_sha
        or evaluator.get("final_sha256") != final_sha
    ):
        failures.append(f"{case_id}: evaluator receipt media binding is invalid")
    return failures


def _case_failures(
    case: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
) -> list[str]:
    case_id = str(case.get("case_id"))
    failures: list[str] = []
    expected_fingerprint = case_dependency_fingerprint(case, context)
    if result.get("dependency_fingerprint") != expected_fingerprint:
        failures.append(f"{case_id}: dependency fingerprint does not match current release")

    final_sha = result.get("final_sha256")
    if not _valid_sha(final_sha):
        failures.append(f"{case_id}: final MP4 SHA-256 is required")
        final_sha = ""
    failures.extend(_receipt_failures(case, result, final_sha))

    total_score = _score(result.get("total_score"))
    if total_score is None or total_score < 85:
        failures.append(f"{case_id}: total quality score must be at least 85")
    factors = result.get("factor_scores")
    expected = case.get("expected")
    hard_gates = expected.get("hard_gates") if isinstance(expected, Mapping) else None
    if not isinstance(factors, Mapping) or not isinstance(hard_gates, list):
        failures.append(f"{case_id}: high-critical factor evidence is missing")
    else:
        for factor in hard_gates:
            score = _score(factors.get(factor))
            if score is None or score < 90:
                failures.append(
                    f"{case_id}: high-critical factor {factor} must be at least 90"
                )

    if _score(result.get("route_percent")) != 100:
        failures.append(f"{case_id}: route fidelity must be 100%")
    if _score(result.get("timeline_percent")) != 100:
        failures.append(f"{case_id}: timeline fidelity must be 100%")
    expected_ui = expected.get("ui_route") if isinstance(expected, Mapping) else None
    if expected_ui == "generated_ui_demo" and (
        _score(result.get("ui_ocr_percent")) != 100
        or _score(result.get("ui_layout_percent")) != 100
    ):
        failures.append(f"{case_id}: generated UI OCR/layout must be 100%")
    tags = set(case.get("coverage_tags") or [])
    if tags & {"overlay_text", "readable_text"} and (
        _score(result.get("text_ocr_percent")) != 100
        or _score(result.get("text_layout_percent")) != 100
    ):
        failures.append(f"{case_id}: readable text OCR/layout must be 100%")

    hard_failures = result.get("hard_failures")
    if not isinstance(hard_failures, list) or hard_failures:
        failures.append(f"{case_id}: hard failure list must be empty")
    claim_failures = result.get("claim_failures")
    if not isinstance(claim_failures, list) or claim_failures:
        failures.append(f"{case_id}: Claim failure list must be empty")

    active = result.get("active_seconds")
    provider = result.get("provider_seconds")
    approval = result.get("approval_wait_seconds")
    if isinstance(active, bool) or not isinstance(active, (int, float)) or active <= 0:
        failures.append(f"{case_id}: active timing is invalid")
    for field, value in (("provider", provider), ("approval wait", approval)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            failures.append(f"{case_id}: {field} timing is invalid")
    if result.get("checkpoint_status") != "complete":
        failures.append(f"{case_id}: checkpoint is not complete")
    probe = result.get("media_probe")
    if (
        not isinstance(probe, Mapping)
        or probe.get("playable") is not True
        or not probe.get("video_codec")
        or not probe.get("audio_codec")
    ):
        failures.append(f"{case_id}: playable audio/video final MP4 is required")
    return failures


def validate_case_results(
    catalog: Mapping[str, Any], report: Mapping[str, Any]
) -> list[str]:
    failures: list[str] = []
    if not isinstance(catalog, Mapping) or catalog.get("schema_version") != "usfr-validation-catalog/v1":
        return ["invalid validation catalog"]
    if not isinstance(report, Mapping) or report.get("schema_version") != "usfr-case-matrix-results/v1":
        return ["invalid case-matrix result report"]
    mode = report.get("mode")
    if mode not in {"incremental", "immutable_release"}:
        return ["case-matrix mode must be incremental or immutable_release"]
    context = report.get("dependency_context")
    if not isinstance(context, Mapping) or any(
        not _valid_sha(context.get(field)) for field in _CONTEXT_FIELDS
    ):
        return ["dependency context is incomplete or invalid"]

    catalog_cases = catalog.get("cases")
    results = report.get("cases")
    if not isinstance(catalog_cases, list) or not isinstance(results, list):
        return ["catalog and result cases must be arrays"]
    case_map = {
        case.get("case_id"): case
        for case in catalog_cases
        if isinstance(case, Mapping) and isinstance(case.get("case_id"), str)
    }
    result_map = {
        result.get("case_id"): result
        for result in results
        if isinstance(result, Mapping) and isinstance(result.get("case_id"), str)
    }
    if len(case_map) != 36 or set(result_map) != set(case_map):
        failures.append("result report must cover the exact 36-case catalog")

    selected_raw = report.get("selected_case_ids")
    selected = set(selected_raw) if isinstance(selected_raw, list) else set()
    smoke = set(catalog.get("fixed_smoke_ids") or [])
    if not selected or not selected.issubset(case_map):
        failures.append("selected_case_ids are invalid")
    if mode == "incremental" and not smoke.issubset(selected):
        failures.append("incremental selection must include the fixed smoke set")
    if mode == "immutable_release" and selected != set(case_map):
        failures.append("immutable release must select all 36 cases")

    for case_id, case in case_map.items():
        if mode == "immutable_release":
            failures.extend(_private_fixture_failures(case))
        result = result_map.get(case_id)
        if not isinstance(result, Mapping):
            continue
        execution_status = result.get("execution_status")
        if mode == "immutable_release" and execution_status != "executed":
            failures.append(f"{case_id}: immutable release cannot reuse a case")
        if mode == "incremental":
            if case_id in selected and execution_status != "executed":
                failures.append(f"{case_id}: selected case must execute")
            if case_id not in selected and execution_status != "reused":
                failures.append(f"{case_id}: unchanged case must use exact reuse evidence")
        failures.extend(_case_failures(case, result, context))
    return sorted(set(failures))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate incremental or immutable USFR case-matrix evidence."
    )
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    report = json.loads(args.results.read_text(encoding="utf-8"))
    failures = validate_case_results(catalog, report)
    payload = {
        "schema_version": "usfr-case-matrix-validation/v1",
        "passed": not failures,
        "mode": report.get("mode") if isinstance(report, Mapping) else None,
        "bundle_sha256": (
            report.get("dependency_context", {}).get("bundle_sha256")
            if isinstance(report, Mapping)
            and isinstance(report.get("dependency_context"), Mapping)
            else None
        ),
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
