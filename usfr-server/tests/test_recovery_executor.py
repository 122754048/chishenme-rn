from __future__ import annotations

from dataclasses import replace

import pytest

from server.recovery_executor import run_recovery_iteration
from server.recovery_models import (
    FailureSignature,
    RecoveryCandidate,
    RecoveryCheckpoint,
    RecoveryStatus,
)


class Broker:
    def __init__(self, strategies):
        self.strategies = strategies

    def discover(self, *, goal, failure):
        return self.strategies


class Executor:
    def __init__(self, candidate):
        self.candidate = candidate
        self.seen = []

    def execute(self, *, strategy, context):
        self.seen.append(strategy)
        return self.candidate


class Qc:
    def __init__(self, result):
        self.result = result

    def evaluate(self, *, candidate, goal, intervals):
        return self.result


def _failure():
    return FailureSignature(
        stage="assembly",
        code="UNSUPPORTED_TRANSITION",
        signature_sha256="b" * 64,
        intervals=({"start_ms": 100, "end_ms": 500},),
    )


def _checkpoint():
    return RecoveryCheckpoint(
        goal_contract_sha256="a" * 64,
        status=RecoveryStatus.REQUIRED,
        failure=_failure(),
    )


def _candidate(*, receipts=None):
    return RecoveryCandidate(
        candidate_id="candidate-1",
        artifact_ref={"object_key": "temporary/job-1/recovery/candidate-1.mp4"},
        artifact_sha256="c" * 64,
        receipts=tuple(
            receipts
            or (
                {"kind": "request", "sha256": "d" * 64},
                {"kind": "response", "sha256": "e" * 64},
                {"kind": "artifact", "sha256": "c" * 64},
            )
        ),
    )


def test_arbitrary_deployed_tool_id_can_be_selected_and_passing_candidate_achieves() -> None:
    persisted = []
    executor = Executor(_candidate())
    result = run_recovery_iteration(
        checkpoint=_checkpoint(),
        goal={"goal_contract_sha256": "a" * 64, "hard_gates": ["timeline_100"]},
        broker=Broker([{"strategy_id": "s1", "tool_id": "custom-deployed-tool", "method": "hybrid", "context": {}}]),
        executor=executor,
        focused_qc=Qc({"passed": True, "hard_gates_passed": True, "score": 100}),
        persist=lambda value: persisted.append(value) or value,
    )
    assert executor.seen[0].tool_id == "custom-deployed-tool"
    assert result.status is RecoveryStatus.ACHIEVED
    assert [item.status for item in persisted] == [
        RecoveryStatus.PLANNING,
        RecoveryStatus.EXECUTING,
        RecoveryStatus.VERIFYING,
        RecoveryStatus.ACHIEVED,
    ]


def test_generated_code_requires_sandbox_receipt() -> None:
    with pytest.raises(ValueError, match="sandbox receipt"):
        run_recovery_iteration(
            checkpoint=_checkpoint(),
            goal={"goal_contract_sha256": "a" * 64},
            broker=Broker([{"strategy_id": "s1", "tool_id": "python", "method": "generated_code"}]),
            executor=Executor(_candidate()),
            focused_qc=Qc({"passed": True, "hard_gates_passed": True}),
            persist=lambda value: value,
        )


def test_paid_strategy_requires_provider_attempt_receipt() -> None:
    with pytest.raises(ValueError, match="provider_attempt"):
        run_recovery_iteration(
            checkpoint=_checkpoint(),
            goal={"goal_contract_sha256": "a" * 64},
            broker=Broker([{"strategy_id": "s1", "tool_id": "provider-x", "method": "regenerate", "paid": True}]),
            executor=Executor(_candidate()),
            focused_qc=Qc({"passed": True, "hard_gates_passed": True}),
            persist=lambda value: value,
        )


def test_identical_no_improvement_strategy_is_rejected_without_execution() -> None:
    first = run_recovery_iteration(
        checkpoint=_checkpoint(),
        goal={"goal_contract_sha256": "a" * 64},
        broker=Broker([{"strategy_id": "s1", "tool_id": "tool-x", "method": "hybrid"}]),
        executor=Executor(_candidate()),
        focused_qc=Qc({"passed": False, "hard_gates_passed": False, "score": 20, "improvement": False}),
        persist=lambda value: value,
    )
    assert first.status is RecoveryStatus.REQUIRED
    second_executor = Executor(_candidate())
    with pytest.raises(ValueError, match="no-improvement strategy"):
        run_recovery_iteration(
            checkpoint=replace(first, status=RecoveryStatus.REQUIRED),
            goal={"goal_contract_sha256": "a" * 64},
            broker=Broker([{"strategy_id": "s1", "tool_id": "tool-x", "method": "hybrid"}]),
            executor=second_executor,
            focused_qc=Qc({"passed": False, "hard_gates_passed": False}),
            persist=lambda value: value,
        )
    assert second_executor.seen == []


def test_candidate_requires_request_response_and_artifact_receipts() -> None:
    with pytest.raises(ValueError, match="response"):
        run_recovery_iteration(
            checkpoint=_checkpoint(),
            goal={"goal_contract_sha256": "a" * 64},
            broker=Broker([{"strategy_id": "s1", "tool_id": "tool-x", "method": "hybrid"}]),
            executor=Executor(_candidate(receipts=({"kind": "request"}, {"kind": "artifact"}))),
            focused_qc=Qc({"passed": True, "hard_gates_passed": True}),
            persist=lambda value: value,
        )
