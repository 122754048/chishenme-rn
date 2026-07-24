from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


class RecoveryStatus(StrEnum):
    REQUIRED = "REQUIRED"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    ACHIEVED = "ACHIEVED"
    EXTERNAL_BLOCKED = "EXTERNAL_BLOCKED"


@dataclass(frozen=True)
class FrozenGoalContract:
    payload: Mapping[str, Any]
    goal_contract_sha256: str

    def __post_init__(self) -> None:
        require_sha256(self.goal_contract_sha256, "goal_contract_sha256")
        copied = deepcopy(dict(self.payload))
        if canonical_sha256(copied) != self.goal_contract_sha256:
            raise ValueError("goal contract digest does not match payload")
        object.__setattr__(self, "payload", copied)

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload": deepcopy(dict(self.payload)),
            "goal_contract_sha256": self.goal_contract_sha256,
        }


@dataclass(frozen=True)
class FailureSignature:
    stage: str
    code: str
    signature_sha256: str
    evidence_sha256: str | None = None
    intervals: tuple[Mapping[str, int], ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.stage or not self.code:
            raise ValueError("failure stage and code are required")
        require_sha256(self.signature_sha256, "signature_sha256")
        if self.evidence_sha256 is not None:
            require_sha256(self.evidence_sha256, "evidence_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "code": self.code,
            "signature_sha256": self.signature_sha256,
            "evidence_sha256": self.evidence_sha256,
            "intervals": [dict(item) for item in self.intervals],
            "details": deepcopy(dict(self.details)),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FailureSignature":
        payload = dict(value)
        payload["intervals"] = tuple(dict(item) for item in payload.get("intervals") or ())
        payload["details"] = dict(payload.get("details") or {})
        return cls(**payload)


@dataclass(frozen=True)
class StrategyManifest:
    strategy_id: str
    tool_id: str
    method: str
    strategy_sha256: str
    context: Mapping[str, Any] = field(default_factory=dict)
    paid: bool = False
    request_receipts: tuple[Mapping[str, Any], ...] = ()
    sandbox_receipt: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.tool_id or not self.method:
            raise ValueError("strategy identity, tool, and method are required")
        require_sha256(self.strategy_sha256, "strategy_sha256")
        if not isinstance(self.paid, bool):
            raise ValueError("strategy paid flag must be boolean")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StrategyManifest":
        payload = dict(value)
        payload["context"] = dict(payload.get("context") or {})
        payload["request_receipts"] = tuple(dict(item) for item in payload.get("request_receipts") or ())
        if payload.get("sandbox_receipt") is not None:
            payload["sandbox_receipt"] = dict(payload["sandbox_receipt"])
        return cls(**payload)


@dataclass(frozen=True)
class RecoveryCandidate:
    candidate_id: str
    artifact_ref: Mapping[str, Any]
    artifact_sha256: str
    receipts: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.artifact_ref:
            raise ValueError("candidate identity and artifact reference are required")
        require_sha256(self.artifact_sha256, "artifact_sha256")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecoveryCandidate":
        payload = dict(value)
        payload["artifact_ref"] = dict(payload.get("artifact_ref") or {})
        payload["receipts"] = tuple(dict(item) for item in payload.get("receipts") or ())
        return cls(**payload)


@dataclass(frozen=True)
class RecoveryCheckpoint:
    goal_contract_sha256: str
    status: RecoveryStatus
    iteration: int = 0
    failure: FailureSignature | None = None
    strategy: StrategyManifest | None = None
    candidate: RecoveryCandidate | None = None
    focused_qc: Mapping[str, Any] | None = None
    next_action: str | None = None

    def __post_init__(self) -> None:
        require_sha256(self.goal_contract_sha256, "goal_contract_sha256")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise ValueError("iteration must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecoveryCheckpoint":
        payload = dict(value)
        payload["status"] = RecoveryStatus(payload["status"])
        if isinstance(payload.get("failure"), Mapping):
            payload["failure"] = FailureSignature.from_dict(payload["failure"])
        if isinstance(payload.get("strategy"), Mapping):
            payload["strategy"] = StrategyManifest.from_dict(payload["strategy"])
        if isinstance(payload.get("candidate"), Mapping):
            payload["candidate"] = RecoveryCandidate.from_dict(payload["candidate"])
        if isinstance(payload.get("focused_qc"), Mapping):
            payload["focused_qc"] = dict(payload["focused_qc"])
        return cls(**payload)

    @property
    def checkpoint_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


__all__ = [
    "FailureSignature",
    "FrozenGoalContract",
    "RecoveryCandidate",
    "RecoveryCheckpoint",
    "RecoveryStatus",
    "StrategyManifest",
    "canonical_sha256",
    "require_sha256",
]
