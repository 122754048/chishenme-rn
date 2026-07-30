from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .recovery_models import (
    FailureSignature,
    FrozenGoalContract,
    canonical_sha256,
    require_sha256,
)


_REQUIRED_GOAL_FIELDS = (
    "source_fidelity",
    "approved_script_sha256",
    "approved_storyboard_sha256",
    "character_lock",
    "product_lock",
    "routes",
    "timing",
    "audio",
    "hard_gates",
)


def freeze_goal_contract(value: Mapping[str, Any]) -> FrozenGoalContract:
    if not isinstance(value, Mapping):
        raise ValueError("goal contract must be an object")
    missing = [name for name in _REQUIRED_GOAL_FIELDS if name not in value]
    if missing:
        raise ValueError("goal contract is missing: " + ", ".join(missing))
    payload = deepcopy(dict(value))
    return FrozenGoalContract(
        payload=payload,
        goal_contract_sha256=canonical_sha256(payload),
    )


def normalize_failure_signature(value: Mapping[str, Any]) -> FailureSignature:
    if not isinstance(value, Mapping):
        raise ValueError("failure evidence must be an object")
    stage = str(value.get("stage") or "").strip()
    code = str(value.get("code") or "").strip()
    if not stage or not code:
        raise ValueError("failure stage and code are required")
    evidence_sha256 = value.get("evidence_sha256")
    if evidence_sha256 is not None:
        evidence_sha256 = require_sha256(evidence_sha256, "evidence_sha256")
    intervals: list[dict[str, int]] = []
    for index, raw in enumerate(value.get("intervals") or []):
        if not isinstance(raw, Mapping):
            raise ValueError(f"failure interval {index} must be an object")
        start_ms = raw.get("start_ms")
        end_ms = raw.get("end_ms")
        if (
            isinstance(start_ms, bool)
            or isinstance(end_ms, bool)
            or not isinstance(start_ms, int)
            or not isinstance(end_ms, int)
            or start_ms < 0
            or end_ms <= start_ms
        ):
            raise ValueError(f"failure interval {index} is invalid")
        intervals.append({"start_ms": start_ms, "end_ms": end_ms})
    details = deepcopy(dict(value.get("details") or {}))
    canonical = {
        "stage": stage,
        "code": code,
        "evidence_sha256": evidence_sha256,
        "intervals": intervals,
        "details": details,
    }
    return FailureSignature(
        stage=stage,
        code=code,
        evidence_sha256=evidence_sha256,
        intervals=tuple(intervals),
        details=details,
        signature_sha256=canonical_sha256(canonical),
    )


def should_enter_recovery(
    *,
    unsupported: bool,
    hard_failure_signatures: Sequence[str],
    transient: bool,
) -> bool:
    if transient:
        return False
    if unsupported:
        return True
    signatures = tuple(hard_failure_signatures)
    for signature in signatures:
        require_sha256(signature, "hard_failure_signature")
    return len(signatures) >= 2 and signatures[-1] == signatures[-2]


__all__ = [
    "freeze_goal_contract",
    "normalize_failure_signature",
    "should_enter_recovery",
]
