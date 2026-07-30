#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from validate_dynamics_quality import compare, metrics


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ratio_score(candidate: float, baseline: float) -> float:
    if baseline <= 0:
        return 1.0
    return min(candidate / baseline, 1.0)


def score(candidate: dict[str, Any], baseline: dict[str, Any]) -> tuple[float, dict[str, float]]:
    cm = metrics(candidate)
    bm = metrics(baseline)
    parts = {
        "cut_density": 25 * ratio_score(cm["cuts_per_10s"], bm["cuts_per_10s"]),
        "event_density": 15 * ratio_score(cm["events_per_10s"], bm["events_per_10s"]),
        "action_detail": 15 * ratio_score(
            cm["field_average_chars"]["action"], bm["field_average_chars"]["action"]
        ),
        "transition_detail": 10 * ratio_score(
            cm["field_average_chars"]["transition"], bm["field_average_chars"]["transition"]
        ),
        "end_state_detail": 15 * ratio_score(
            cm["field_average_chars"]["end_state"], bm["field_average_chars"]["end_state"]
        ),
        "end_state_variety": 10 * ratio_score(
            cm["field_unique_ratio"]["end_state"], bm["field_unique_ratio"]["end_state"]
        ),
        "event_kind_coverage": 10 * ratio_score(
            len(cm["event_kinds"]), len(bm["event_kinds"])
        ),
    }
    total = sum(parts.values())
    total -= min(cm["generic_end_state_count"] * 5, 25)
    return max(total, 0), parts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare validated external video analyzers against an approved original-workflow baseline."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    baseline = load(args.baseline)
    probe = load(args.probe)
    results = []
    for raw in args.candidate:
        if "=" not in raw:
            raise SystemExit("--candidate must be name=path")
        name, path_text = raw.split("=", 1)
        path = Path(path_text)
        candidate = load(path)
        quality = compare(candidate, probe, baseline)
        total, parts = score(candidate, baseline)
        provenance = candidate.get("analysis_provenance") or {}
        results.append(
            {
                "name": name,
                "path": str(path.resolve()),
                "provider": provenance.get("semantic_analyzer_provider"),
                "model": provenance.get("semantic_analyzer_model"),
                "quality_status": quality["status"],
                "quality_failures": quality["failures"],
                "metrics": quality["candidate_metrics"],
                "score": round(total, 3),
                "score_parts": {key: round(value, 3) for key, value in parts.items()},
                "eligible": quality["status"] == "VALID",
            }
        )

    eligible = sorted(
        (item for item in results if item["eligible"]),
        key=lambda item: item["score"],
        reverse=True,
    )
    output = {
        "contract": "video-analyzer-comparison",
        "contract_version": 1,
        "baseline": str(args.baseline.resolve()),
        "scoring_policy": (
            "same video/probe/rules/baseline; schema and semantic quality validation "
            "are mandatory; score measures baseline-level density, specificity, "
            "end-state quality, and event coverage"
        ),
        "candidates": sorted(results, key=lambda item: item["score"], reverse=True),
        "recommended": eligible[0]["name"] if eligible else None,
        "status": "VALID" if eligible else "NO_ELIGIBLE_CANDIDATE",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output["recommended"] or "NO_ELIGIBLE_CANDIDATE")
    return 0 if eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())

