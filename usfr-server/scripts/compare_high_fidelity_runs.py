#!/usr/bin/env python3
"""Compare baseline and high-fidelity shadow/A-B reports deterministically.

Each case must provide ``fidelity_score``, ``active_seconds``, and the complete
compatibility metric set.  The design gate requires at least 12 matched cases,
100% claim-evidence and exact-voiceover coverage, at least 90% action-chain
coverage, zero UI/claim regressions, and bounded active-time overhead.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


REQUIRED_COMPATIBILITY_METRICS = (
    "fixed_slots",
    "existing_approvals",
    "fixed_b_provider",
    "duplicate_task_protection",
    "claim_evidence_coverage",
    "exact_voiceover_content",
    "action_chain_coverage",
    "ui_errors",
    "claim_regressions",
    "hard_failures",
    "route_timeline_coverage",
    "high_criticality_factor_min",
    "ui_ocr",
)
_METRIC_ALIASES = {
    "claim_evidence_coverage": ("claim_evidence_coverage", "high_criticality_claim_evidence", "high_criticality_claim_evidence_percent"),
    "exact_voiceover_content": ("exact_voiceover_content", "exact_approved_voiceover_content", "voiceover_exact"),
    "action_chain_coverage": ("action_chain_coverage", "high_criticality_action_chain_coverage", "action_chain_coverage_percent"),
    "ui_errors": ("ui_errors", "ui_error_count"),
    "claim_regressions": ("claim_regressions", "false_claim_regressions"),
    "hard_failures": ("hard_failures", "hard_failure_count"),
    "route_timeline_coverage": ("route_timeline_coverage", "timeline_route_coverage"),
    "high_criticality_factor_min": ("high_criticality_factor_min", "high_criticality_min_score"),
    "ui_ocr": ("ui_ocr", "ui_ocr_percent"),
}


def _cases(report: Mapping[str, Any], label: str) -> dict[str, Mapping[str, Any]]:
    rows = report.get("cases", report.get("records"))
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{label} report must contain a non-empty cases/records array")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("case_id"), str) or not row["case_id"]:
            raise ValueError(f"{label} report has an invalid case row")
        if row["case_id"] in result:
            raise ValueError(f"{label} report repeats case {row['case_id']}")
        result[row["case_id"]] = row
    return result


def _number(row: Mapping[str, Any], key: str, label: str) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}.{key} must be numeric")
    return float(value)


def _compatibility_failures(row: Mapping[str, Any], label: str) -> list[str]:
    """Validate the design's compatibility/evidence metric closure.

    Missing metrics fail closed.  A report must not silently convert an absent
    compatibility field into a passing default.
    """

    metrics = row.get("compatibility_metrics")
    if not isinstance(metrics, Mapping):
        return [f"{label}:compatibility_metrics"]
    failures: list[str] = []
    for key in REQUIRED_COMPATIBILITY_METRICS:
        candidates = _METRIC_ALIASES.get(key, (key,))
        actual_key = next((candidate for candidate in candidates if candidate in metrics), None)
        if actual_key is None:
            failures.append(f"{label}:compatibility_metrics.{key}")
            continue
        value = metrics[actual_key]
        if key in {"fixed_slots", "existing_approvals", "fixed_b_provider", "duplicate_task_protection"}:
            if value is not True:
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key in {"claim_evidence_coverage", "exact_voiceover_content"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 100:
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key == "action_chain_coverage":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 90:
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key == "high_criticality_factor_min":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 90:
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key == "ui_ocr":
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 100):
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key == "route_timeline_coverage":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 100:
                failures.append(f"{label}:compatibility_metrics.{key}")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 0:
                failures.append(f"{label}:compatibility_metrics.{key}")
    return failures


def compare_reports(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return anchored fidelity/latency deltas and compatibility status."""

    old = _cases(baseline, "baseline")
    new = _cases(candidate, "candidate")
    if set(old) != set(new):
        raise ValueError("baseline and candidate case IDs must match exactly")
    deltas: list[dict[str, Any]] = []
    fidelity_deltas: list[float] = []
    overheads: list[float] = []
    compatibility_failures: list[str] = []
    for case_id in sorted(old):
        compatibility_failures.extend(_compatibility_failures(old[case_id], f"baseline:{case_id}"))
        compatibility_failures.extend(_compatibility_failures(new[case_id], f"candidate:{case_id}"))
        old_score = _number(old[case_id], "fidelity_score", f"baseline.{case_id}")
        new_score = _number(new[case_id], "fidelity_score", f"candidate.{case_id}")
        old_time = _number(old[case_id], "active_seconds", f"baseline.{case_id}")
        new_time = _number(new[case_id], "active_seconds", f"candidate.{case_id}")
        if not 0 <= old_score <= 100 or not 0 <= new_score <= 100:
            raise ValueError(f"{case_id}.fidelity_score must be between 0 and 100")
        if old_time <= 0:
            raise ValueError(f"baseline.{case_id}.active_seconds must be positive")
        if new_time <= 0:
            raise ValueError(f"candidate.{case_id}.active_seconds must be positive")
        fidelity_delta = new_score - old_score
        overhead_seconds = new_time - old_time
        overhead_budget_seconds = min(120.0, old_time * 0.10)
        overhead = overhead_seconds / old_time * 100.0
        fidelity_deltas.append(fidelity_delta)
        overheads.append(overhead)
        deltas.append(
            {
                "case_id": case_id,
                # Preserve the raw inputs needed by a deployment validator to
                # recompute this row.  Summary-only deltas are not sufficient
                # activation evidence because a caller could self-report a
                # fidelity/time aggregate without exposing its measurements.
                "baseline_fidelity_score": old_score,
                "candidate_fidelity_score": new_score,
                "baseline_active_seconds": old_time,
                "candidate_active_seconds": new_time,
                "baseline_compatibility_metrics": dict(old[case_id].get("compatibility_metrics") or {}),
                "candidate_compatibility_metrics": dict(new[case_id].get("compatibility_metrics") or {}),
                "fidelity_delta": round(fidelity_delta, 2),
                "active_overhead_seconds": round(overhead_seconds, 2),
                "active_overhead_percent": round(overhead, 2),
                "active_overhead_budget_seconds": round(overhead_budget_seconds, 2),
                "within_active_time_target": overhead_seconds <= overhead_budget_seconds,
            }
        )
    average_delta = sum(fidelity_deltas) / len(fidelity_deltas)
    average_overhead = sum(overheads) / len(overheads)
    compatibility = not compatibility_failures
    within_time_target = all(row["within_active_time_target"] for row in deltas)
    case_coverage_pass = len(deltas) >= 12
    return {
        "schema_version": "high-fidelity-comparison/v1",
        "baseline_status": baseline.get("status"),
        "candidate_status": candidate.get("status"),
        "case_count": len(deltas),
        "average_fidelity_delta": round(average_delta, 2),
        "average_active_overhead_percent": round(average_overhead, 2),
        "compatibility_pass": bool(compatibility),
        "compatibility_failures": compatibility_failures,
        "case_coverage_pass": case_coverage_pass,
        "target_case_count": 12,
        "metric_coverage_pass": not bool(compatibility_failures),
        "target_fidelity_delta": 10.0,
        "stretch_target_fidelity_delta": 15.0,
        "target_active_overhead_percent": 10.0,
        "within_active_time_target": within_time_target,
        "meets_targets": bool(compatibility and case_coverage_pass and average_delta >= 10.0 and within_time_target),
        "cases": deltas,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare high-fidelity baseline and candidate reports")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
        report = compare_reports(baseline, candidate)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"invalid comparison input: {exc}") from exc
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
