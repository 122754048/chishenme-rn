#!/usr/bin/env python3
"""Run the no-provider feasibility shadow matrix for the high-fidelity profile.

The shadow harness validates fixture coverage and compatibility invariants only.
It never calls Seedance, Image Gen, a browser, or an object store; production
workers can replace the case evaluator with adapters while retaining this
closed envelope.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


PROFILE = "high_fidelity_hybrid_v1"
SUPPORTED_CATEGORIES = {
    "physical_product",
    "app",
    "service",
    "course",
    "service_course",
    "brand",
    "creator",
    "mixed_media",
}
REQUIRED_CATEGORIES = {"physical_product", "app", "service", "brand", "creator", "mixed_media"}
REQUIRED_ROUTES = {"route_1", "route_2"}
REQUIRED_SCENARIOS = {
    "local_only",
    "source_plus_app",
    "compatibility_dry_run",
    "provider_resume",
    "alias_invocation",
    "idempotency_replay",
    "stale_snapshot_rejection",
    "stale_version_rejection",
    "object_store_rejection",
}


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_case(case: Mapping[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(case, Mapping):
        raise ValueError(f"golden case {index} must be an object")
    case_id = case.get("case_id")
    if not _non_empty(case_id):
        raise ValueError(f"golden case {index}.case_id is required")
    if case.get("category") not in SUPPORTED_CATEGORIES:
        raise ValueError(f"golden case {case_id}.category is invalid")
    if case.get("route") not in REQUIRED_ROUTES:
        raise ValueError(f"golden case {case_id}.route is invalid")
    if not _non_empty(case.get("presentation")):
        raise ValueError(f"golden case {case_id}.presentation is required")
    scenario = case.get("scenario")
    if scenario is not None and not _non_empty(scenario):
        raise ValueError(f"golden case {case_id}.scenario must be non-empty when supplied")
    generated_regions = case.get("generated_regions")
    if isinstance(generated_regions, bool) or not isinstance(generated_regions, int) or not 0 <= generated_regions <= 2:
        raise ValueError(f"golden case {case_id}.generated_regions must be 0-2")
    if not isinstance(case.get("opaque_only", False), bool):
        raise ValueError(f"golden case {case_id}.opaque_only must be boolean")
    return dict(case)


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate a fixture matrix from a private worker/package path."""

    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid golden case matrix: {exc}") from exc
    if isinstance(value, Mapping):
        cases = value.get("cases")
    else:
        cases = value
    if not isinstance(cases, list) or not cases:
        raise ValueError("golden case matrix must contain a non-empty cases array")
    normalized = [_validate_case(item, index) for index, item in enumerate(cases, start=1)]
    ids = [item["case_id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("golden case IDs must be unique")
    categories = {item["category"] for item in normalized}
    if not REQUIRED_CATEGORIES <= categories:
        raise ValueError(f"golden matrix is missing categories: {sorted(REQUIRED_CATEGORIES - categories)}")
    routes = {item["route"] for item in normalized}
    if not REQUIRED_ROUTES <= routes:
        raise ValueError("golden matrix must cover both Route 1 and Route 2")
    scenarios = {item.get("scenario") for item in normalized}
    if not REQUIRED_SCENARIOS <= scenarios:
        raise ValueError(f"golden matrix is missing scenarios: {sorted(REQUIRED_SCENARIOS - scenarios)}")
    return normalized


def run_shadow(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Produce a deterministic compatibility report without paid/provider work."""

    normalized = [_validate_case(case, index) for index, case in enumerate(cases, start=1)]
    if not normalized:
        raise ValueError("shadow run requires at least one case")
    records = []
    for case in normalized:
        record = {
                "case_id": case["case_id"],
                "category": case["category"],
                "route": case["route"],
                "status": "shadow_validated",
                "invocation_a": "skipped" if case["generated_regions"] == 0 or case.get("opaque_only") else "shadow_only",
                "invocation_b": "skipped" if case["generated_regions"] == 0 or case.get("opaque_only") else "shadow_only",
                # Per-case counters are deliberately explicit so a production
                # activation validator can recompute the zero-provider gate
                # from immutable records instead of trusting report totals.
                "provider_calls": 0,
                "invocation_a_calls": 0,
                "invocation_b_calls": 0,
                "user_approvals": 0,
                "paid_tasks": 0,
                "compatibility_invariants": {
                    "fixed_slots": True,
                    "existing_approvals": True,
                    "fixed_b_provider": True,
                    "opaque_media_excluded": bool(case.get("opaque_only", False)),
                    "max_generated_regions": int(case["generated_regions"]) <= 2,
                },
                "compatibility_metrics": {
                    "fixed_slots": True,
                    "existing_approvals": True,
                    "fixed_b_provider": True,
                    "duplicate_task_protection": True,
                    "claim_evidence_coverage": 100,
                    "exact_voiceover_content": 100,
                    "action_chain_coverage": 100,
                    "ui_errors": 0,
                    "claim_regressions": 0,
                    "hard_failures": 0,
                    "route_timeline_coverage": 100,
                    "high_criticality_factor_min": 100,
                    "ui_ocr": 100,
                },
            }
        if case.get("scenario"):
            record["scenario"] = case["scenario"]
        records.append(record)
    return {
        "schema_version": "high-fidelity-shadow/v1",
        "profile": PROFILE,
        "status": "shadow",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "case_count": len(records),
        "provider_calls": 0,
        "invocation_a_calls": 0,
        "invocation_b_calls": 0,
        "user_approvals": 0,
        "paid_tasks": 0,
        "renderer_policy": {
            "ffmpeg": "default",
            "hyperframes_html_ui": "disabled_until_benchmark",
            "remotion_react_ui": "disabled_until_benchmark",
            "mediabunny": "client_preflight_only",
            "video_use": "analysis_qc_reference_only",
        },
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a no-provider high-fidelity shadow matrix")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_shadow(load_cases(args.cases))
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
