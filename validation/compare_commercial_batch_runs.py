from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any


TIMING_METRICS = (
    "probe_dynamics",
    "context_compile",
    "provider_wait",
    "assembly_qc",
)
HARD_FAILURE_TYPES = ("ui", "audio", "timeline")


class ShadowComparisonError(ValueError):
    pass


def compare_shadow_runs(
    *,
    case_id: str,
    standard: Mapping[str, Any],
    optimized: Mapping[str, Any],
) -> dict[str, Any]:
    baseline = _normalize_observation(standard)
    candidate = _normalize_observation(optimized)
    contract_regressions = sorted(baseline["source_contract_coverage"] - candidate["source_contract_coverage"])
    claim_regression = baseline["selling_point_claims"] != candidate["selling_point_claims"]
    hard_failure_regressions = {
        kind: sorted(candidate["hard_failures"][kind] - baseline["hard_failures"][kind])
        for kind in HARD_FAILURE_TYPES
    }
    hard_failures = {
        kind: sorted(candidate["hard_failures"][kind] | baseline["hard_failures"][kind])
        for kind in HARD_FAILURE_TYPES
    }
    qa_regression = candidate["final_qa_score"] < baseline["final_qa_score"]
    return {
        "case_id": case_id,
        "shadow_green": not (
            contract_regressions
            or claim_regression
            or any(hard_failures.values())
            or any(hard_failure_regressions.values())
            or qa_regression
        ),
        "contract_regressions": contract_regressions,
        "claim_regression": claim_regression,
        "hard_failures": hard_failures,
        "hard_failure_regressions": hard_failure_regressions,
        "qa_regression": qa_regression,
        "standard_final_qa_score": baseline["final_qa_score"],
        "optimized_final_qa_score": candidate["final_qa_score"],
        "active_time_delta_seconds": candidate["active_seconds"] - baseline["active_seconds"],
        "provider_wait_delta_seconds": (
            candidate["timing_seconds"]["provider_wait"]
            - baseline["timing_seconds"]["provider_wait"]
        ),
        "timing_delta_seconds": {
            metric: candidate["timing_seconds"][metric] - baseline["timing_seconds"][metric]
            for metric in TIMING_METRICS
        },
    }


def evaluate_release_gates(
    *,
    shadow_comparisons: Sequence[Mapping[str, Any]],
    ab_results: Sequence[Mapping[str, Any]],
    regression_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    shadow_passed = len(shadow_comparisons) >= 18 and all(
        comparison.get("shadow_green") is True for comparison in shadow_comparisons
    )
    ab_results_valid = len(ab_results) >= 12 and all(_valid_ab_result(result) for result in ab_results)
    average_baseline_fidelity = average_fidelity(ab_results, "baseline_fidelity") if ab_results_valid else None
    average_optimized_fidelity = average_fidelity(ab_results, "optimized_fidelity") if ab_results_valid else None
    ab_quality_passed = (
        ab_results_valid
        and average_optimized_fidelity is not None
        and average_baseline_fidelity is not None
        and average_optimized_fidelity >= average_baseline_fidelity
    )
    regression_passed = len(regression_results) >= 30 and all(
        not result.get("hard_failures") for result in regression_results
    )
    return {
        "release_ready": shadow_passed and ab_quality_passed and regression_passed,
        "shadow_passed": shadow_passed,
        "ab_quality_passed": ab_quality_passed,
        "regression_passed": regression_passed,
        "shadow_case_count": len(shadow_comparisons),
        "ab_case_count": len(ab_results),
        "regression_case_count": len(regression_results),
        "average_baseline_fidelity": average_baseline_fidelity,
        "average_optimized_fidelity": average_optimized_fidelity,
    }


def validate_rollout_config(config: Mapping[str, Any]) -> dict[str, Any]:
    percent = config.get("initial_rollout_percent")
    if percent != 10:
        raise ShadowComparisonError("INITIAL_ROLLOUT_MUST_BE_10_PERCENT")
    metrics = config.get("required_timing_metrics")
    if not isinstance(metrics, list) or set(metrics) != set(TIMING_METRICS):
        raise ShadowComparisonError("ROLLOUT_TIMING_METRICS_INVALID")
    return {"initial_rollout_percent": percent, "required_timing_metrics": list(TIMING_METRICS)}


def average_fidelity(results: Sequence[Mapping[str, Any]], field: str) -> float:
    if not results:
        raise ShadowComparisonError("FIDELITY_RESULTS_REQUIRED")
    values = [result.get(field) for result in results]
    if any(not isinstance(value, (int, float)) for value in values):
        raise ShadowComparisonError("FIDELITY_SCORE_INVALID")
    return fmean(float(value) for value in values)


def _normalize_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(observation, Mapping):
        raise ShadowComparisonError("SHADOW_OBSERVATION_INVALID")
    if observation.get("paid_provider_tasks_created") != 0:
        raise ShadowComparisonError("SHADOW_PAID_PROVIDER_TASK_FORBIDDEN")
    if observation.get("approval_events") != 0:
        raise ShadowComparisonError("SHADOW_APPROVAL_EVENT_FORBIDDEN")
    coverage = _string_set(observation.get("source_contract_coverage"), "SOURCE_CONTRACT_COVERAGE_INVALID")
    claims = _string_set(observation.get("selling_point_claims"), "SELLING_POINT_CLAIMS_INVALID")
    hard_failures_raw = observation.get("hard_failures")
    if not isinstance(hard_failures_raw, Mapping):
        raise ShadowComparisonError("HARD_FAILURES_INVALID")
    hard_failures = {
        kind: _string_set(hard_failures_raw.get(kind, []), "HARD_FAILURES_INVALID")
        for kind in HARD_FAILURE_TYPES
    }
    timing_raw = observation.get("timing_seconds")
    if not isinstance(timing_raw, Mapping):
        raise ShadowComparisonError("TIMING_SECONDS_INVALID")
    timing = {}
    for metric in TIMING_METRICS:
        value = timing_raw.get(metric)
        if not isinstance(value, (int, float)) or value < 0:
            raise ShadowComparisonError("TIMING_SECONDS_INVALID")
        timing[metric] = float(value)
    active_seconds = observation.get("active_seconds")
    qa_score = observation.get("final_qa_score")
    if not isinstance(active_seconds, (int, float)) or active_seconds < 0:
        raise ShadowComparisonError("ACTIVE_SECONDS_INVALID")
    if not isinstance(qa_score, (int, float)) or not 0 <= qa_score <= 100:
        raise ShadowComparisonError("FINAL_QA_SCORE_INVALID")
    return {
        "source_contract_coverage": coverage,
        "selling_point_claims": claims,
        "hard_failures": hard_failures,
        "timing_seconds": timing,
        "active_seconds": float(active_seconds),
        "final_qa_score": float(qa_score),
    }


def _valid_ab_result(result: Mapping[str, Any]) -> bool:
    baseline = result.get("baseline_fidelity")
    optimized = result.get("optimized_fidelity")
    return (
        isinstance(baseline, (int, float))
        and isinstance(optimized, (int, float))
        and result.get("ui_regression") is False
        and result.get("claim_regression") is False
    )


def _string_set(value: object, error_code: str) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ShadowComparisonError(error_code)
    return set(value)
