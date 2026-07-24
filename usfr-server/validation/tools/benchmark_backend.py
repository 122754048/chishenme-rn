"""Evaluate same-case optional video backend benchmarks without activating them."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import fmean
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BenchmarkContractError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _require_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise BenchmarkContractError(f"{field} must be a SHA-256")
    return value


def _require_score(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkContractError(f"{field} must be numeric")
    score = float(value)
    if not 0 <= score <= 100:
        raise BenchmarkContractError(f"{field} must be between 0 and 100")
    return score


def _validate_receipt(value: Any, field: str) -> None:
    if not isinstance(value, Mapping):
        raise BenchmarkContractError(f"{field} evaluator receipt is required")
    if not isinstance(value.get("evaluator"), str) or not value["evaluator"]:
        raise BenchmarkContractError(f"{field} evaluator receipt identity is required")
    _require_sha(value.get("model_sha256"), f"{field} evaluator model")
    _require_sha(value.get("receipt_sha256"), f"{field} evaluator receipt")


def _validate_side(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BenchmarkContractError(f"{field} result must be an object")
    _require_sha(value.get("final_sha256"), f"{field} final media")
    total_score = _require_score(value.get("total_score"), f"{field} total_score")
    factors = value.get("factor_scores")
    if not isinstance(factors, Mapping) or not factors:
        raise BenchmarkContractError(f"{field} factor_scores are required")
    factor_scores = {
        str(name): _require_score(score, f"{field} factor {name}")
        for name, score in factors.items()
        if isinstance(name, str) and name
    }
    if len(factor_scores) != len(factors):
        raise BenchmarkContractError(f"{field} factor names must be non-empty strings")
    hard_failures = value.get("hard_failures")
    if not isinstance(hard_failures, list) or any(
        not isinstance(item, str) or not item for item in hard_failures
    ):
        raise BenchmarkContractError(f"{field} hard_failures must be a string array")
    active_seconds = value.get("active_seconds")
    if (
        isinstance(active_seconds, bool)
        or not isinstance(active_seconds, (int, float))
        or float(active_seconds) <= 0
    ):
        raise BenchmarkContractError(f"{field} active_seconds must be positive")
    _validate_receipt(value.get("evaluator_receipt"), field)
    return {
        "total_score": total_score,
        "factor_scores": factor_scores,
        "hard_failures": tuple(hard_failures),
        "active_seconds": float(active_seconds),
    }


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _validate_carrier_receipts(report: Mapping[str, Any]) -> None:
    if report.get("requested_scope") != "complete_timeline_carrier":
        return
    receipts = report.get("carrier_receipts")
    if not isinstance(receipts, Mapping):
        raise BenchmarkContractError(
            "complete carrier replacement requires timeline, audio, and final receipts"
        )
    for field in (
        "timeline_receipt_sha256",
        "audio_receipt_sha256",
        "final_output_receipt_sha256",
    ):
        _require_sha(receipts.get(field), field)


def evaluate_report(
    report: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise BenchmarkContractError("benchmark report must be an object")
    if report.get("schema_version") != "usfr-backend-benchmark/v1":
        raise BenchmarkContractError("unsupported benchmark report schema")
    _require_sha(report.get("bundle_sha256"), "bundle")
    candidate = report.get("candidate")
    candidates = policy.get("candidates") if isinstance(policy, Mapping) else None
    if not isinstance(candidate, str) or not isinstance(candidates, Mapping):
        raise BenchmarkContractError("candidate policy is missing")
    candidate_policy = candidates.get(candidate)
    if not isinstance(candidate_policy, Mapping):
        raise BenchmarkContractError("candidate is not declared by policy")
    if report.get("domain") != candidate_policy.get("domain"):
        raise BenchmarkContractError("candidate benchmark domain does not match policy")
    if report.get("baseline_backend") != policy.get("default_backend"):
        raise BenchmarkContractError("benchmark baseline must use the default backend")
    _validate_carrier_receipts(report)

    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        raise BenchmarkContractError("benchmark cases are required")
    seen: set[str] = set()
    baseline_scores: list[float] = []
    candidate_scores: list[float] = []
    baseline_seconds: list[float] = []
    candidate_seconds: list[float] = []
    hard_regressions: list[str] = []

    for index, record in enumerate(cases):
        if not isinstance(record, Mapping):
            raise BenchmarkContractError(f"cases[{index}] must be an object")
        case_id = record.get("case_id")
        candidate_case_id = record.get("candidate_case_id", case_id)
        if (
            not isinstance(case_id, str)
            or not case_id
            or candidate_case_id != case_id
        ):
            raise BenchmarkContractError("baseline and candidate must use the same case")
        if case_id in seen:
            raise BenchmarkContractError("benchmark case IDs must be unique")
        seen.add(case_id)
        baseline = _validate_side(record.get("baseline"), f"{case_id} baseline")
        candidate_result = _validate_side(
            record.get("candidate"), f"{case_id} candidate"
        )
        if set(baseline["factor_scores"]) != set(candidate_result["factor_scores"]):
            raise BenchmarkContractError("baseline and candidate factor sets must match")
        if baseline["hard_failures"]:
            hard_regressions.append(f"{case_id}:baseline_not_release_eligible")
        hard_regressions.extend(
            f"{case_id}:{failure}" for failure in candidate_result["hard_failures"]
        )
        baseline_scores.append(baseline["total_score"])
        candidate_scores.append(candidate_result["total_score"])
        baseline_seconds.append(baseline["active_seconds"])
        candidate_seconds.append(candidate_result["active_seconds"])

    baseline_average = fmean(baseline_scores)
    candidate_average = fmean(candidate_scores)
    baseline_minimum = min(baseline_scores)
    candidate_minimum = min(candidate_scores)
    baseline_p95 = _p95(baseline_seconds)
    candidate_p95 = _p95(candidate_seconds)
    quality_improved = candidate_average > baseline_average
    minimum_quality_preserved = candidate_minimum >= baseline_minimum
    no_hard_regressions = not hard_regressions and minimum_quality_preserved
    speed_improved_without_quality_loss = (
        candidate_p95 < baseline_p95 and minimum_quality_preserved
    )
    eligible = no_hard_regressions and (
        quality_improved or speed_improved_without_quality_loss
    )
    reasons: list[str] = []
    if hard_regressions:
        reasons.append("hard gate regression")
    if not minimum_quality_preserved:
        reasons.append("minimum quality regressed")
    if not quality_improved and candidate_p95 >= baseline_p95:
        reasons.append("neither quality nor p95 speed improved")

    return {
        "schema_version": "usfr-backend-decision/v1",
        "candidate": candidate,
        "domain": report["domain"],
        "case_ids": sorted(seen),
        "report_sha256": hashlib.sha256(_canonical(report)).hexdigest(),
        "eligible": eligible,
        "quality_improved": quality_improved,
        "speed_improved_without_quality_loss": speed_improved_without_quality_loss,
        "no_hard_regressions": no_hard_regressions,
        "baseline_average_score": baseline_average,
        "candidate_average_score": candidate_average,
        "baseline_min_score": baseline_minimum,
        "candidate_min_score": candidate_minimum,
        "baseline_p95_seconds": baseline_p95,
        "candidate_p95_seconds": candidate_p95,
        "hard_regressions": hard_regressions,
        "reasons": reasons,
        "activation_effect": "none; production policy requires a separately reviewed immutable update",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a same-case optional video backend benchmark."
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    decision = evaluate_report(report, policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if decision["eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
