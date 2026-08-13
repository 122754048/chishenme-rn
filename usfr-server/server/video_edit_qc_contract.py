"""Shared server-owned contracts for v2 video-edit QC evidence."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


EVIDENCE_CONTRACT = "video-edit-qc-evidence/v2"
CHECKS_CONTRACT = "video-edit-qc-checks/v1"
RULESET_PAYLOAD: Mapping[str, Any] = {
    "contract": "video-edit-qc-rules/v1",
    "classifiers": {
        "identity": "replacement_checks.kind=identity and verdict=fail",
        "replacement": "replacement_checks.verdict=fail",
    },
    "evaluator_receipt": "high-fidelity-qc-evaluator-receipt/v1",
    "failure_priority": [
        "safety",
        "dialogue",
        "identity/replacement",
        "preservation",
        "boundary_subject",
        "boundary_lighting",
        "boundary_audio",
        "physical_text",
    ],
}


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


RULESET_SHA256 = canonical_sha256(RULESET_PAYLOAD)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_FAILURE_PRIORITY_KEYS = {
    "safety_violation": "safety",
    "dialogue_mismatch": "dialogue",
    "identity_replacement_incomplete": "identity/replacement",
    "replacement_incomplete": "identity/replacement",
    "preservation_drift": "preservation",
    "boundary_subject_jump": "boundary_subject",
    "boundary_lighting_jump": "boundary_lighting",
    "boundary_audio_pop": "boundary_audio",
    "physical_text_unreadable": "physical_text",
}

_FAILURE_HARD_CODES = {
    "safety_violation": "SAFETY_VIOLATION",
    "dialogue_mismatch": "DIALOGUE_MISMATCH",
    "identity_replacement_incomplete": "IDENTITY_REPLACEMENT_INCOMPLETE",
    "replacement_incomplete": "REPLACEMENT_INCOMPLETE",
    "preservation_drift": "PRESERVATION_DRIFT",
    "boundary_subject_jump": "BOUNDARY_SUBJECT_JUMP",
    "boundary_lighting_jump": "BOUNDARY_LIGHTING_JUMP",
    "boundary_audio_pop": "BOUNDARY_AUDIO_POP",
    "physical_text_unreadable": "PHYSICAL_TEXT_UNREADABLE",
}


def failure_priority_rank(failure_type: Any) -> int:
    key = _FAILURE_PRIORITY_KEYS.get(str(failure_type or ""))
    try:
        return list(RULESET_PAYLOAD["failure_priority"]).index(key)
    except (ValueError, TypeError):
        return 10_000


def failure_hard_code(failure_type: Any) -> str | None:
    return _FAILURE_HARD_CODES.get(str(failure_type or ""))


def require_sha256(value: Any, *, field: str) -> str:
    normalized = str(value or "").lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def require_ruleset_sha256(value: Any, *, field: str = "ruleset_sha256") -> str:
    normalized = require_sha256(value, field=field)
    if normalized != RULESET_SHA256:
        raise ValueError(f"{field} does not match the server QC ruleset")
    return normalized


__all__ = [
    "CHECKS_CONTRACT",
    "EVIDENCE_CONTRACT",
    "RULESET_PAYLOAD",
    "RULESET_SHA256",
    "canonical_sha256",
    "failure_hard_code",
    "failure_priority_rank",
    "require_ruleset_sha256",
    "require_sha256",
]
