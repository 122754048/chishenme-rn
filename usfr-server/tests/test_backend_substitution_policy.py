from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from validation.tools.benchmark_backend import BenchmarkContractError, evaluate_report


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "validation" / "high_fidelity" / "backend_policy.json"


def _receipt(char: str) -> dict[str, str]:
    return {
        "evaluator": "private-qc:v1",
        "model_sha256": char * 64,
        "receipt_sha256": ("f" if char != "f" else "e") * 64,
    }


def _side(*, score: float, seconds: float, char: str) -> dict[str, object]:
    return {
        "final_sha256": char * 64,
        "total_score": score,
        "factor_scores": {
            "timeline": 100.0,
            "audio_sync": 98.0,
            "readable_text": 100.0,
        },
        "hard_failures": [],
        "active_seconds": seconds,
        "evaluator_receipt": _receipt(char),
    }


def _report(
    *,
    baseline_scores: tuple[float, ...] = (90.0, 91.0),
    candidate_scores: tuple[float, ...] = (92.0, 93.0),
    baseline_seconds: tuple[float, ...] = (10.0, 12.0),
    candidate_seconds: tuple[float, ...] = (10.0, 11.0),
) -> dict[str, object]:
    cases = []
    for index, case_id in enumerate(("A01", "A03")):
        cases.append(
            {
                "case_id": case_id,
                "baseline": _side(
                    score=baseline_scores[index],
                    seconds=baseline_seconds[index],
                    char=str(index + 1),
                ),
                "candidate": _side(
                    score=candidate_scores[index],
                    seconds=candidate_seconds[index],
                    char=chr(ord("a") + index),
                ),
            }
        )
    return {
        "schema_version": "usfr-backend-benchmark/v1",
        "bundle_sha256": "b" * 64,
        "candidate": "hyperframes_html_ui",
        "domain": "complex_html_ui",
        "baseline_backend": "ffmpeg",
        "cases": cases,
    }


def test_production_policy_defaults_every_optional_backend_to_disabled() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["default_backend"] == "ffmpeg"
    assert set(policy["candidates"]) == {
        "hyperframes_html_ui",
        "remotion_react_ui",
        "video_use_boundary_qc",
        "mediabunny_preflight",
    }
    assert all(item["status"] == "disabled" for item in policy["candidates"].values())
    assert all(item["activation_report_sha256"] is None for item in policy["candidates"].values())


def test_quality_improvement_is_eligible_without_mutating_policy() -> None:
    decision = evaluate_report(_report(), json.loads(POLICY.read_text(encoding="utf-8")))
    assert decision["eligible"] is True
    assert decision["quality_improved"] is True
    assert decision["speed_improved_without_quality_loss"] is True
    assert json.loads(POLICY.read_text(encoding="utf-8"))["candidates"]["hyperframes_html_ui"]["status"] == "disabled"


def test_speed_gain_is_eligible_only_when_minimum_quality_does_not_drop() -> None:
    report = _report(
        baseline_scores=(90.0, 92.0),
        candidate_scores=(90.0, 92.0),
        baseline_seconds=(15.0, 20.0),
        candidate_seconds=(10.0, 12.0),
    )
    decision = evaluate_report(report, json.loads(POLICY.read_text(encoding="utf-8")))
    assert decision["eligible"] is True
    assert decision["quality_improved"] is False
    assert decision["speed_improved_without_quality_loss"] is True

    report = _report(
        baseline_scores=(90.0, 92.0),
        candidate_scores=(89.0, 94.0),
        baseline_seconds=(15.0, 20.0),
        candidate_seconds=(10.0, 12.0),
    )
    decision = evaluate_report(report, json.loads(POLICY.read_text(encoding="utf-8")))
    assert decision["eligible"] is False
    assert "minimum quality regressed" in decision["reasons"]


def test_hard_failure_blocks_candidate_even_when_faster_and_higher_scoring() -> None:
    report = _report()
    report["cases"][0]["candidate"]["hard_failures"] = ["ui_ocr_below_100"]
    decision = evaluate_report(report, json.loads(POLICY.read_text(encoding="utf-8")))
    assert decision["eligible"] is False
    assert decision["no_hard_regressions"] is False


def test_missing_independent_receipt_is_rejected() -> None:
    report = _report()
    report["cases"][0]["candidate"].pop("evaluator_receipt")
    with pytest.raises(BenchmarkContractError, match="evaluator receipt"):
        evaluate_report(report, json.loads(POLICY.read_text(encoding="utf-8")))


def test_case_set_mismatch_is_rejected() -> None:
    report = _report()
    report["cases"][1]["candidate_case_id"] = "foreign-case"
    with pytest.raises(BenchmarkContractError, match="same case"):
        evaluate_report(report, json.loads(POLICY.read_text(encoding="utf-8")))


def test_candidate_may_only_benchmark_its_declared_domain() -> None:
    report = _report()
    report["domain"] = "complete_timeline_carrier"
    with pytest.raises(BenchmarkContractError, match="domain"):
        evaluate_report(report, json.loads(POLICY.read_text(encoding="utf-8")))


def test_complete_timeline_substitution_requires_all_carrier_receipts() -> None:
    report = _report()
    report["candidate"] = "remotion_react_ui"
    report["domain"] = "programmable_overlays"
    report["requested_scope"] = "complete_timeline_carrier"
    with pytest.raises(BenchmarkContractError, match="timeline.*audio.*final"):
        evaluate_report(report, json.loads(POLICY.read_text(encoding="utf-8")))


def test_manifest_separates_runtime_policy_from_release_only_benchmark_tool() -> None:
    manifest = json.loads(
        (ROOT / "references" / "bundle_manifest.json").read_text(encoding="utf-8")
    )
    runtime = {item["path"] for item in manifest["runtime_files"]}
    release_tools = {item["path"] for item in manifest["release_tools"]}
    assert "validation/high_fidelity/backend_policy.json" in runtime
    assert "validation/tools/benchmark_backend.py" not in runtime
    assert "validation/tools/benchmark_backend.py" in release_tools


def test_cli_writes_decision_without_mutating_production_policy(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "decision.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    before = POLICY.read_bytes()
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "validation" / "tools" / "benchmark_backend.py"),
            "--report",
            str(report_path),
            "--policy",
            str(POLICY),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output_path.read_text(encoding="utf-8"))["eligible"] is True
    assert POLICY.read_bytes() == before
