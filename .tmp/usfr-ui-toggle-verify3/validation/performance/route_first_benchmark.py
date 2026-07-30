"""Compare same-case baseline and route-first candidate release evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_THRESHOLDS = Path(__file__).with_name("route_first_thresholds.json")


def _number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if result < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return result


def _count(value: Any, label: str) -> int:
    number = _number(value, label)
    if not number.is_integer():
        raise ValueError(f"{label} must be an integer")
    return int(number)


def _throughput(run: Mapping[str, Any], label: str) -> float:
    explicit = run.get("videos_per_hour")
    if explicit is not None:
        return _number(explicit, f"{label}.videos_per_hour")
    active_seconds = _number(run.get("active_seconds"), f"{label}.active_seconds")
    videos = _count(run.get("videos"), f"{label}.videos")
    if active_seconds <= 0 or videos <= 0:
        raise ValueError(f"{label} requires positive active_seconds and videos")
    return videos * 3600.0 / active_seconds


def load_thresholds(path: str | Path = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid route-first thresholds: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("route-first thresholds must be an object")
    return dict(payload)


def compare_runs(
    *,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Enforce speed gains only when quality and duplication gates also pass."""

    limits = dict(thresholds or load_thresholds())
    floors = limits.get("minimum_throughput_gain")
    if not isinstance(floors, Mapping):
        raise ValueError("minimum_throughput_gain must be an object")
    route_class = str(candidate.get("route_class") or "standard")
    if route_class not in floors:
        raise ValueError(f"unsupported route_class: {route_class}")

    baseline_quality = _number(baseline.get("quality"), "baseline.quality")
    candidate_quality = _number(candidate.get("quality"), "candidate.quality")
    maximum_quality_drop = _number(
        limits.get("maximum_quality_drop"), "maximum_quality_drop"
    )
    baseline_vph = _throughput(baseline, "baseline")
    candidate_vph = _throughput(candidate, "candidate")
    throughput_gain = candidate_vph / baseline_vph if baseline_vph else 0.0

    hard_failures = candidate.get("hard_failures", [])
    if isinstance(hard_failures, Sequence) and not isinstance(
        hard_failures, (str, bytes, bytearray)
    ):
        hard_failure_count = len(hard_failures)
    else:
        hard_failure_count = _count(hard_failures, "candidate.hard_failures")

    calls = candidate.get("calls")
    if not isinstance(calls, Mapping):
        raise ValueError("candidate.calls must be an object")
    normalized_calls = {
        str(name): _count(value, f"candidate.calls.{name}")
        for name, value in calls.items()
    }
    relevant_tools = candidate.get("relevant_tools", [])
    if not isinstance(relevant_tools, Sequence) or isinstance(
        relevant_tools, (str, bytes, bytearray)
    ):
        raise ValueError("candidate.relevant_tools must be an array")

    failures: list[str] = []
    if baseline_quality - candidate_quality > maximum_quality_drop:
        failures.append("quality_regression")
    if hard_failure_count > _count(
        limits.get("maximum_hard_failures"), "maximum_hard_failures"
    ):
        failures.append("hard_failure")
    if normalized_calls.get("full_source_semantic", 0) > _count(
        limits.get("maximum_full_source_semantic_calls"),
        "maximum_full_source_semantic_calls",
    ):
        failures.append("duplicate_full_source_analysis")
    maximum_tool_calls = _count(
        limits.get("maximum_relevant_tool_calls"), "maximum_relevant_tool_calls"
    )
    for tool_name in sorted({str(item) for item in relevant_tools}):
        if normalized_calls.get(tool_name, 0) > maximum_tool_calls:
            failures.append(f"duplicate_relevant_tool_call:{tool_name}")

    temporary_files = _count(
        candidate.get("temporary_files"), "candidate.temporary_files"
    )
    adaptive_manifest_files = _count(
        candidate.get("adaptive_manifest_files"),
        "candidate.adaptive_manifest_files",
    )
    if limits.get("temporary_file_policy") != "not_above_adaptive_manifest":
        raise ValueError("temporary_file_policy is unsupported")
    if temporary_files > adaptive_manifest_files:
        failures.append("temporary_file_overproduction")
    route_floor = _number(floors[route_class], f"minimum_throughput_gain.{route_class}")
    if throughput_gain < route_floor:
        failures.append("throughput_target_missed")

    return {
        "schema_version": "usfr-route-first-benchmark/v1",
        "passed": not failures,
        "failures": failures,
        "route_class": route_class,
        "metrics": {
            "baseline_quality": baseline_quality,
            "candidate_quality": candidate_quality,
            "quality_drop": baseline_quality - candidate_quality,
            "baseline_videos_per_hour": baseline_vph,
            "candidate_videos_per_hour": candidate_vph,
            "throughput_gain": round(throughput_gain, 6),
            "required_throughput_gain": route_floor,
            "candidate_active_seconds": candidate.get("active_seconds"),
            "calls": normalized_calls,
            "hard_failure_count": hard_failure_count,
            "temporary_files": temporary_files,
            "adaptive_manifest_files": adaptive_manifest_files,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate a route-first candidate against same-case baseline evidence."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    report = compare_runs(
        baseline=baseline,
        candidate=candidate,
        thresholds=load_thresholds(args.thresholds),
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
