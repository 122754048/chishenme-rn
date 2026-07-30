"""Route-aware QC planning without weakening the final hard gates.

The final media always receives the same deterministic base checks.  Semantic
or model-assisted follow-up is restricted to the named factor that is below
its approved threshold; one failed factor is never authority to rerun every
unrelated QA dimension.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


BASE_CHECKS = (
    "decode",
    "video_stream",
    "required_audio",
    "duration",
    "fps",
    "black_boundaries",
    "timeline_placement",
    "final_object_verification",
)


def _score(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("score")
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_qc_plan(
    *,
    route: str,
    hard_failures: Sequence[str],
    factor_scores: Mapping[str, Any],
    threshold: float = 90.0,
) -> dict[str, Any]:
    """Return the immutable final-QC execution plan.

    Missing or malformed factor evidence is escalated instead of silently
    accepted.  ``hard_failures`` remains blocking evidence and does not remove
    any base check.
    """

    normalized_threshold = float(threshold)
    escalated: list[str] = []
    for factor, raw_score in factor_scores.items():
        score = _score(raw_score)
        if score is None or score < normalized_threshold:
            escalated.append(str(factor))
    escalated.sort()
    return {
        "schema_version": "usfr-qc-plan/v1",
        "route": str(route or "unknown"),
        "base_checks": list(BASE_CHECKS),
        "hard_failures": [str(item) for item in hard_failures],
        "factor_threshold": normalized_threshold,
        "escalated_factors": escalated,
        "prohibited_full_rerun": True,
    }


__all__ = ["BASE_CHECKS", "build_qc_plan"]
