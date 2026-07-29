from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from validation.tools.validate_case_results import (
    case_dependency_fingerprint,
    validate_case_results,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "validation" / "case_catalog.json"


def _catalog(*, publish_fixtures: bool) -> dict:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if publish_fixtures:
        for case in catalog["cases"]:
            records = [case["source_fixture"], *case["replacement_fixtures"]]
            for record in records:
                asset_id = record["asset_id"]
                if asset_id.startswith("fixtures/"):
                    record["asset_id"] = f"private-validation/{asset_id}"
    return catalog


def _context() -> dict[str, str]:
    return {
        "bundle_sha256": "a" * 64,
        "capability_sha256": "b" * 64,
        "model_sha256": "c" * 64,
        "provider_sha256": "d" * 64,
        "prompt_compiler_sha256": "e" * 64,
    }


def _result(case: dict, context: dict[str, str], *, executed: bool = True) -> dict:
    source_sha = case["source_fixture"]["sha256"]
    final_sha = (case["case_id"].lower().encode("utf-8").hex() + "f" * 64)[:64]
    gates = case["expected"]["hard_gates"]
    tags = set(case["coverage_tags"])
    generated_ui = case["expected"]["ui_route"] == "generated_ui_demo"
    readable_text = bool(tags & {"overlay_text", "readable_text"})
    return {
        "case_id": case["case_id"],
        "execution_status": "executed" if executed else "reused",
        "dependency_fingerprint": case_dependency_fingerprint(case, context),
        "fixture_receipt": {
            "verified": True,
            "receipt_sha256": "1" * 64,
            "source_sha256": source_sha,
            "replacement_sha256": [
                item["sha256"] for item in case["replacement_fixtures"]
            ],
        },
        "final_sha256": final_sha,
        "total_score": 92.0,
        "factor_scores": {gate: 95.0 for gate in gates},
        "route_percent": 100.0,
        "timeline_percent": 100.0,
        "ui_ocr_percent": 100.0 if generated_ui else None,
        "ui_layout_percent": 100.0 if generated_ui else None,
        "text_ocr_percent": 100.0 if readable_text else None,
        "text_layout_percent": 100.0 if readable_text else None,
        "claim_failures": [],
        "hard_failures": [],
        "active_seconds": 30.0,
        "provider_seconds": 18.0,
        "approval_wait_seconds": 0.0,
        "checkpoint_status": "complete",
        "media_probe": {
            "playable": True,
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        "evaluator_receipt": {
            "verified": True,
            "evaluator": "private-semantic-qc:v1",
            "model_sha256": context["model_sha256"],
            "request_sha256": "2" * 64,
            "response_sha256": "3" * 64,
            "receipt_sha256": "4" * 64,
            "source_sha256": source_sha,
            "final_sha256": final_sha,
        },
    }


def _report(catalog: dict, *, mode: str = "immutable_release") -> dict:
    context = _context()
    cases = [
        _result(case, context, executed=(mode == "immutable_release"))
        for case in catalog["cases"]
    ]
    selected = [case["case_id"] for case in catalog["cases"]]
    if mode == "incremental":
        selected = catalog["fixed_smoke_ids"]
        for result in cases:
            result["execution_status"] = (
                "executed" if result["case_id"] in selected else "reused"
            )
    return {
        "schema_version": "usfr-case-matrix-results/v1",
        "mode": mode,
        "dependency_context": context,
        "selected_case_ids": selected,
        "cases": cases,
    }


def test_current_placeholder_catalog_cannot_be_immutable_release_evidence() -> None:
    catalog = _catalog(publish_fixtures=False)
    failures = validate_case_results(catalog, _report(catalog))
    assert any("private object" in failure for failure in failures)


def test_complete_private_36_case_release_passes_contract() -> None:
    catalog = _catalog(publish_fixtures=True)
    assert validate_case_results(catalog, _report(catalog)) == []


def test_immutable_release_requires_all_36_cases_executed_now() -> None:
    catalog = _catalog(publish_fixtures=True)
    report = _report(catalog)
    report["cases"].pop()
    report["cases"][0]["execution_status"] = "reused"
    failures = validate_case_results(catalog, report)
    assert any("exact 36-case" in failure for failure in failures)
    assert any("cannot reuse" in failure for failure in failures)


def test_generated_ui_requires_exact_ocr_and_layout() -> None:
    catalog = _catalog(publish_fixtures=True)
    report = _report(catalog)
    result = next(item for item in report["cases"] if item["case_id"] == "A03")
    result["ui_ocr_percent"] = 99.0
    failures = validate_case_results(catalog, report)
    assert any("A03" in failure and "UI OCR/layout" in failure for failure in failures)


def test_hard_failure_claim_or_high_critical_regression_blocks_release() -> None:
    catalog = _catalog(publish_fixtures=True)
    report = _report(catalog)
    first = report["cases"][0]
    first["hard_failures"] = ["black_boundary"]
    first["claim_failures"] = ["unsupported_claim"]
    first["factor_scores"][next(iter(first["factor_scores"]))] = 89.0
    failures = validate_case_results(catalog, report)
    assert any("hard failure" in failure for failure in failures)
    assert any("Claim failure" in failure for failure in failures)
    assert any("high-critical factor" in failure for failure in failures)


def test_evaluator_receipt_must_bind_current_final_and_source_media() -> None:
    catalog = _catalog(publish_fixtures=True)
    report = _report(catalog)
    result = report["cases"][0]
    result["evaluator_receipt"]["final_sha256"] = "9" * 64
    result["evaluator_receipt"]["source_sha256"] = "8" * 64
    failures = validate_case_results(catalog, report)
    assert any("evaluator receipt media binding" in failure for failure in failures)


def test_foreign_dependency_context_or_stale_reuse_is_rejected() -> None:
    catalog = _catalog(publish_fixtures=True)
    report = _report(catalog, mode="incremental")
    reused = next(item for item in report["cases"] if item["execution_status"] == "reused")
    reused["dependency_fingerprint"] = "0" * 64
    report["cases"][0]["dependency_fingerprint"] = "f" * 64
    failures = validate_case_results(catalog, report)
    assert sum("dependency fingerprint" in failure for failure in failures) >= 2


def test_incremental_run_requires_selected_cases_executed_and_all_reuse_exact() -> None:
    catalog = _catalog(publish_fixtures=True)
    report = _report(catalog, mode="incremental")
    assert validate_case_results(catalog, report) == []
    selected = report["selected_case_ids"][0]
    next(item for item in report["cases"] if item["case_id"] == selected)[
        "execution_status"
    ] = "reused"
    failures = validate_case_results(catalog, report)
    assert any("selected case must execute" in failure for failure in failures)


def test_cli_writes_machine_readable_release_rejection(tmp_path: Path) -> None:
    catalog = _catalog(publish_fixtures=False)
    report_path = tmp_path / "results.json"
    output_path = tmp_path / "validation.json"
    report_path.write_text(json.dumps(_report(catalog)), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "validation" / "tools" / "validate_case_results.py"),
            "--catalog",
            str(CATALOG_PATH),
            "--results",
            str(report_path),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any("private object" in failure for failure in payload["failures"])


def test_case_result_validator_is_release_only_and_not_in_runtime_image() -> None:
    manifest = json.loads(
        (ROOT / "references" / "bundle_manifest.json").read_text(encoding="utf-8")
    )
    runtime = {item["path"] for item in manifest["runtime_files"]}
    release_tools = {item["path"] for item in manifest["release_tools"]}
    path = "validation/tools/validate_case_results.py"
    assert path in release_tools
    assert path not in runtime


def test_quality_activation_contract_names_executable_result_gate() -> None:
    contract = (ROOT / "references" / "quality-activation-contract.md").read_text(
        encoding="utf-8"
    )
    assert "validate_case_results.py" in contract
    assert "all 36 cases must be executed" in contract
    assert "OCR/layout must equal 100%" in contract
