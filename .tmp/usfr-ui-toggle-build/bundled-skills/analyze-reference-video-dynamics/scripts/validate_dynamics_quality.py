#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

from validate_dynamics import validate


GENERIC_END_STATE = re.compile(
    r"^\s*(continues?(?:\s+to\s+(?:the\s+)?next\s+cut)?|continue|"
    r"same\s+as\s+before|unchanged|n/?a)\s*[.!]?\s*$",
    re.IGNORECASE,
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def metrics(value: dict[str, Any]) -> dict[str, Any]:
    cuts = value["source_cuts"]
    events = value["source_events"]
    duration_s = value["reference_duration_us"] / 1_000_000
    field_average_chars = {}
    field_unique_ratio = {}
    for field in ("scene", "action", "camera", "transition", "end_state"):
        texts = [str(cut.get(field) or "").strip() for cut in cuts]
        field_average_chars[field] = (
            sum(len(text) for text in texts) / len(texts) if texts else 0
        )
        field_unique_ratio[field] = (
            len(set(texts)) / len(texts) if texts else 0
        )
    return {
        "duration_s": duration_s,
        "cut_count": len(cuts),
        "cuts_per_10s": len(cuts) / duration_s * 10,
        "event_count": len(events),
        "events_per_10s": len(events) / duration_s * 10,
        "event_kinds": sorted({str(event.get("kind")) for event in events}),
        "generic_end_state_count": sum(
            bool(GENERIC_END_STATE.fullmatch(str(cut.get("end_state") or "")))
            for cut in cuts
        ),
        "field_average_chars": field_average_chars,
        "field_unique_ratio": field_unique_ratio,
    }


def compare(
    candidate: dict[str, Any],
    probe: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    validate(candidate, probe)
    candidate_metrics = metrics(candidate)
    failures: list[str] = []
    warnings: list[str] = []

    if candidate_metrics["generic_end_state_count"]:
        failures.append(
            f"{candidate_metrics['generic_end_state_count']} Cuts use generic end_state placeholders"
        )

    notes_text = " ".join(
        str(item) for item in candidate.get("notes", [])
    ).lower()
    event_kinds = set(candidate_metrics["event_kinds"])
    if any(marker in notes_text for marker in ("subtitle", "caption", "on-screen text")):
        if "subtitle" not in event_kinds:
            failures.append("notes report visible subtitles/captions but no subtitle events exist")
    if "music" in notes_text and "music" not in event_kinds:
        failures.append("notes report music but no music events exist")

    cuts = candidate["source_cuts"]
    long_generic = []
    for cut in cuts:
        duration_s = (cut["end_us"] - cut["start_us"]) / 1_000_000
        action = str(cut.get("action") or "").lower()
        if duration_s > 4 and any(
            phrase in action
            for phrase in (
                "speaks and gestures",
                "continues speaking",
                "explains",
                "talks to camera",
            )
        ):
            long_generic.append(cut["cut"])
    if long_generic:
        failures.append(
            "long Cuts retain vague multi-phase actions: "
            + ", ".join(map(str, long_generic))
        )

    baseline_metrics = metrics(baseline) if baseline is not None else None
    if baseline_metrics is not None:
        density_ratio = (
            candidate_metrics["cuts_per_10s"] / baseline_metrics["cuts_per_10s"]
        )
        event_density_ratio = (
            candidate_metrics["events_per_10s"]
            / baseline_metrics["events_per_10s"]
        )
        if density_ratio < 0.65:
            failures.append(
                f"Cut density is {density_ratio:.2%} of approved baseline; minimum is 65%"
            )
        if event_density_ratio < 0.50:
            failures.append(
                f"event density is {event_density_ratio:.2%} of approved baseline; minimum is 50%"
            )
        for field in ("action", "transition", "end_state"):
            base_avg = baseline_metrics["field_average_chars"][field]
            candidate_avg = candidate_metrics["field_average_chars"][field]
            ratio = candidate_avg / base_avg if base_avg else 1
            if ratio < 0.55:
                failures.append(
                    f"{field} average detail is {ratio:.2%} of approved baseline; minimum is 55%"
                )
        if (
            candidate_metrics["field_unique_ratio"]["end_state"] < 0.65
            and baseline_metrics["field_unique_ratio"]["end_state"] >= 0.90
        ):
            failures.append(
                "end_state variety is materially below the approved baseline"
            )

    if len(event_kinds) == 1:
        warnings.append("only one event kind is present; confirm the source truly lacks other audio/text layers")

    return {
        "contract": "reference-video-dynamics-quality-report",
        "contract_version": 1,
        "status": "VALID" if not failures else "INVALID",
        "candidate_metrics": candidate_metrics,
        "baseline_metrics": baseline_metrics,
        "failures": failures,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate semantic quality and compare dynamics analysis with an approved baseline."
    )
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        candidate = load(args.analysis)
        probe = load(args.probe)
        baseline = load(args.baseline) if args.baseline else None
        report = compare(candidate, probe, baseline)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(report["status"])
        for failure in report["failures"]:
            print(f"FAIL: {failure}", file=sys.stderr)
        for warning in report["warnings"]:
            print(f"WARN: {warning}", file=sys.stderr)
        return 0 if report["status"] == "VALID" else 2
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

