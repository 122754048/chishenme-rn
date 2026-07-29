"""Strict activation-evidence fixture used by profile/worker contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def strict_activation_evidence(root: Path) -> dict[str, Any]:
    # Imports are kept local so this helper is test-only and does not become a
    # production dependency of the deployable Skill bundle.
    import sys

    scripts = root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from compare_high_fidelity_runs import compare_reports
    from run_high_fidelity_shadow import load_cases, run_shadow

    shadow = run_shadow(load_cases(root / "validation" / "high_fidelity" / "golden_cases.json"))
    metrics = {
        "fixed_slots": True,
        "existing_approvals": True,
        "fixed_b_provider": True,
        "duplicate_task_protection": True,
        "claim_evidence_coverage": 100,
        "exact_voiceover_content": 100,
        "action_chain_coverage": 95,
        "ui_errors": 0,
        "claim_regressions": 0,
        "hard_failures": 0,
        "route_timeline_coverage": 100,
        "high_criticality_factor_min": 95,
        "ui_ocr": 100,
    }
    baseline = {
        "status": "baseline",
        "cases": [
            {"case_id": f"C{index:02d}", "fidelity_score": 60, "active_seconds": 100, "compatibility_metrics": metrics}
            for index in range(12)
        ],
    }
    candidate = {
        "status": "hybrid",
        "cases": [
            {"case_id": f"C{index:02d}", "fidelity_score": 70, "active_seconds": 105, "compatibility_metrics": metrics}
            for index in range(12)
        ],
    }
    matched = compare_reports(baseline, candidate)
    regression = {
        "status": "passed",
        "passed": True,
        "hard_failures": 0,
        "ui_errors": 0,
        "claim_regressions": 0,
        "cases": [
            {"case_id": f"R{index:02d}", "passed": True, "hard_failures": 0, "ui_errors": 0, "claim_regressions": 0}
            for index in range(30)
        ],
    }
    reports = {"shadow": shadow, "matched_ab": matched, "regression": regression}
    sections: dict[str, dict[str, Any]] = {}
    for name, report in reports.items():
        report_bytes = _canonical(report)
        report_sha = hashlib.sha256(report_bytes).hexdigest()
        receipt: dict[str, Any] = {
            "receipt_id": f"activation-{name}",
            "artifact_id": f"activation-{name}",
            "uri": f"artifact://activation/{name}.json",
            "object_key": f"activation/{name}.json",
            "sha256": report_sha,
            "size_bytes": len(report_bytes),
            "content_type": "application/json",
            "immutable": True,
            "server_minted": True,
        }
        receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
        sections[name] = {"report": report, "report_sha256": report_sha, "publication_receipt": receipt}
    aggregate = {
        "shadow_case_count": len(shadow["records"]),
        "matched_ab_case_count": len(matched["cases"]),
        "average_fidelity_delta": matched["average_fidelity_delta"],
        "regression_case_count": len(regression["cases"]),
        "report_sha256": {name: section["report_sha256"] for name, section in sections.items()},
    }
    return {
        "schema_version": "high-fidelity-activation-evidence/v1",
        **sections,
        "aggregate": aggregate,
        "aggregate_sha256": hashlib.sha256(_canonical(aggregate)).hexdigest(),
    }

