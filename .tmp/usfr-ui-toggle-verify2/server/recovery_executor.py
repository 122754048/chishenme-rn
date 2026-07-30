from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol

from .recovery_models import (
    FailureSignature,
    RecoveryCandidate,
    RecoveryCheckpoint,
    RecoveryStatus,
    StrategyManifest,
    canonical_sha256,
    require_sha256,
)


class RecoveryCapabilityBroker(Protocol):
    def discover(
        self,
        *,
        goal: Mapping[str, Any],
        failure: FailureSignature,
    ) -> Sequence[Mapping[str, Any]]: ...


class RecoveryStrategyExecutor(Protocol):
    def execute(
        self,
        *,
        strategy: StrategyManifest,
        context: Mapping[str, Any],
    ) -> RecoveryCandidate: ...


class FocusedRecoveryQc(Protocol):
    def evaluate(
        self,
        *,
        candidate: RecoveryCandidate,
        goal: Mapping[str, Any],
        intervals: Sequence[Mapping[str, int]],
    ) -> Mapping[str, Any]: ...


def _strategy_manifest(raw: Mapping[str, Any]) -> StrategyManifest:
    if not isinstance(raw, Mapping):
        raise ValueError("discovered recovery strategy must be an object")
    strategy_id = str(raw.get("strategy_id") or "").strip()
    tool_id = str(raw.get("tool_id") or "").strip()
    method = str(raw.get("method") or "").strip()
    context = dict(raw.get("context") or {})
    paid = raw.get("paid", False)
    sandbox_receipt = raw.get("sandbox_receipt")
    if method == "generated_code" and not isinstance(sandbox_receipt, Mapping):
        raise ValueError("generated-code recovery requires a sandbox receipt")
    canonical = {
        "strategy_id": strategy_id,
        "tool_id": tool_id,
        "method": method,
        "context": context,
        "paid": paid,
        "sandbox_receipt": dict(sandbox_receipt) if isinstance(sandbox_receipt, Mapping) else None,
    }
    return StrategyManifest(
        strategy_id=strategy_id,
        tool_id=tool_id,
        method=method,
        strategy_sha256=canonical_sha256(canonical),
        context=context,
        paid=paid,
        sandbox_receipt=canonical["sandbox_receipt"],
    )


def _require_candidate_receipts(
    candidate: RecoveryCandidate,
    *,
    strategy: StrategyManifest,
) -> None:
    kinds = {
        str(item.get("kind") or "").strip()
        for item in candidate.receipts
        if isinstance(item, Mapping)
    }
    for required in ("request", "response", "artifact"):
        if required not in kinds:
            raise ValueError(f"recovery candidate is missing {required} receipt")
    if strategy.paid and "provider_attempt" not in kinds:
        raise ValueError("paid recovery candidate is missing provider_attempt receipt")
    if strategy.method == "generated_code" and strategy.sandbox_receipt is None:
        raise ValueError("generated-code recovery requires a sandbox receipt")


def run_recovery_iteration(
    *,
    checkpoint: RecoveryCheckpoint,
    goal: Mapping[str, Any],
    broker: RecoveryCapabilityBroker,
    executor: RecoveryStrategyExecutor,
    focused_qc: FocusedRecoveryQc,
    persist: Callable[[RecoveryCheckpoint], RecoveryCheckpoint],
) -> RecoveryCheckpoint:
    """Execute exactly one resumable recovery iteration.

    Capability IDs are deployment data. This controller does not encode a
    tool/framework allowlist or an attempt ceiling.
    """

    if checkpoint.status not in {RecoveryStatus.REQUIRED, RecoveryStatus.PLANNING}:
        raise ValueError("recovery iteration requires REQUIRED or PLANNING status")
    goal_sha = require_sha256(goal.get("goal_contract_sha256"), "goal_contract_sha256")
    if goal_sha != checkpoint.goal_contract_sha256:
        raise ValueError("recovery goal contract changed")
    if checkpoint.failure is None:
        raise ValueError("recovery checkpoint requires a failure signature")

    planning = persist(
        replace(
            checkpoint,
            status=RecoveryStatus.PLANNING,
            next_action="discover_capabilities",
        )
    )
    discovered = broker.discover(goal=goal, failure=checkpoint.failure)
    if not isinstance(discovered, Sequence) or isinstance(discovered, (str, bytes, bytearray)):
        raise ValueError("recovery capability broker must return a sequence")
    if not discovered:
        return persist(
            replace(
                planning,
                status=RecoveryStatus.EXTERNAL_BLOCKED,
                next_action="await_external_capability",
            )
        )

    strategy = _strategy_manifest(discovered[0])
    prior_qc = dict(checkpoint.focused_qc or {})
    if (
        prior_qc.get("last_strategy_sha256") == strategy.strategy_sha256
        and prior_qc.get("improvement") is False
    ):
        raise ValueError("identical no-improvement strategy cannot be repeated")

    executing = persist(
        replace(
            planning,
            status=RecoveryStatus.EXECUTING,
            iteration=checkpoint.iteration + 1,
            strategy=strategy,
            candidate=None,
            next_action="execute_strategy",
        )
    )
    candidate = executor.execute(strategy=strategy, context=strategy.context)
    if not isinstance(candidate, RecoveryCandidate):
        raise ValueError("recovery executor must return a RecoveryCandidate")
    _require_candidate_receipts(candidate, strategy=strategy)

    verifying = persist(
        replace(
            executing,
            status=RecoveryStatus.VERIFYING,
            candidate=candidate,
            next_action="focused_qc",
        )
    )
    qc_result = focused_qc.evaluate(
        candidate=candidate,
        goal=goal,
        intervals=checkpoint.failure.intervals,
    )
    if not isinstance(qc_result, Mapping):
        raise ValueError("focused recovery QC must return an object")
    qc_payload = dict(qc_result)
    qc_payload["last_strategy_sha256"] = strategy.strategy_sha256
    qc_payload.setdefault("improvement", bool(qc_payload.get("passed")))
    achieved = qc_payload.get("passed") is True and qc_payload.get("hard_gates_passed") is True
    return persist(
        replace(
            verifying,
            status=RecoveryStatus.ACHIEVED if achieved else RecoveryStatus.REQUIRED,
            focused_qc=qc_payload,
            next_action="reinsert_artifact" if achieved else "discover_alternate_strategy",
        )
    )


__all__ = [
    "FocusedRecoveryQc",
    "RecoveryCapabilityBroker",
    "RecoveryStrategyExecutor",
    "run_recovery_iteration",
]
