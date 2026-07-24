from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from server.recovery_models import RecoveryCheckpoint, RecoveryStatus
from server.recovery_workflow import (
    freeze_goal_contract,
    normalize_failure_signature,
    should_enter_recovery,
)


ROOT = Path(__file__).resolve().parents[1]


def test_unsupported_capability_enters_recovery_immediately() -> None:
    assert should_enter_recovery(
        unsupported=True,
        hard_failure_signatures=(),
        transient=False,
    )


def test_same_last_two_hard_failures_enter_recovery() -> None:
    assert should_enter_recovery(
        unsupported=False,
        hard_failure_signatures=("a" * 64, "b" * 64, "b" * 64),
        transient=False,
    )
    assert not should_enter_recovery(
        unsupported=False,
        hard_failure_signatures=("a" * 64, "b" * 64),
        transient=False,
    )


def test_transient_failure_never_counts_toward_recovery() -> None:
    assert not should_enter_recovery(
        unsupported=True,
        hard_failure_signatures=("c" * 64, "c" * 64),
        transient=True,
    )


def test_goal_contract_changes_when_any_frozen_authority_changes() -> None:
    base = {
        "source_fidelity": {"sha256": "a" * 64},
        "approved_script_sha256": "b" * 64,
        "approved_storyboard_sha256": "c" * 64,
        "character_lock": {"sha256": "d" * 64},
        "product_lock": {"sha256": "e" * 64},
        "routes": {"ui": "opaque", "tail": "omit"},
        "timing": {"cut_count": 2},
        "audio": {"language": "zh"},
        "hard_gates": ["timeline_100", "ocr_100"],
    }
    first = freeze_goal_contract(base)
    second = freeze_goal_contract({**base, "audio": {"language": "ja"}})
    assert first.goal_contract_sha256 != second.goal_contract_sha256
    assert first.payload["audio"]["language"] == "zh"


def test_failure_signature_is_order_stable_and_evidence_bound() -> None:
    first = normalize_failure_signature(
        {
            "stage": "qc_delivery",
            "code": "OCR_MISMATCH",
            "intervals": [{"start_ms": 100, "end_ms": 400}],
            "evidence_sha256": "f" * 64,
        }
    )
    second = normalize_failure_signature(
        {
            "evidence_sha256": "f" * 64,
            "intervals": [{"end_ms": 400, "start_ms": 100}],
            "code": "OCR_MISMATCH",
            "stage": "qc_delivery",
        }
    )
    assert first.signature_sha256 == second.signature_sha256


def test_checkpoint_has_no_fixed_attempt_ceiling_and_is_immutable() -> None:
    checkpoint = RecoveryCheckpoint(
        goal_contract_sha256="a" * 64,
        status=RecoveryStatus.REQUIRED,
        iteration=1_000_000,
    )
    assert checkpoint.iteration == 1_000_000
    try:
        checkpoint.iteration = 1
    except Exception:
        pass
    else:
        raise AssertionError("RecoveryCheckpoint must be immutable")


def test_checkpoint_schema_accepts_canonical_checkpoint() -> None:
    checkpoint = RecoveryCheckpoint(
        goal_contract_sha256="a" * 64,
        status=RecoveryStatus.PLANNING,
        iteration=3,
    )
    schema = json.loads(
        (ROOT / "schemas" / "recovery_checkpoint.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(checkpoint.to_dict())
