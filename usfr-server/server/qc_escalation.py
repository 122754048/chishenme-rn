"""Base QC plus factor-specific escalation planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


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


def build_qc_plan(
    *,
    route: str,
    hard_failures: Sequence[str] = (),
    factor_scores: Mapping[str, float] = {},
    threshold: float = 90.0,
) -> dict[str, Any]:
    escalated = sorted(
        str(factor)
        for factor, score in factor_scores.items()
        if float(score) < float(threshold)
    )
    return {
        "contract": "usfr-qc-escalation/v1",
        "route": str(route or "unknown"),
        "base_checks": list(BASE_CHECKS),
        "hard_failures": [str(item) for item in hard_failures],
        "escalated_factors": escalated,
        "threshold": float(threshold),
        "prohibited_full_rerun": True,
    }


__all__ = ["BASE_CHECKS", "build_qc_plan"]
