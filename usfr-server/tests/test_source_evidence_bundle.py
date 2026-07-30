from __future__ import annotations

import pytest

from server.errors import ReplicationError
from server.source_evidence_bundle import (
    AnalysisInvocationLedger,
    build_source_evidence_bundle,
    validate_source_evidence_bundle,
)


def _scope() -> dict[str, str]:
    return {"scope_sha256": "a" * 64}


def test_bundle_is_stable_and_validates() -> None:
    first = build_source_evidence_bundle(
        probe={"duration_us": 2_000_000, "fps": 30},
        timeline={"regions": [{"region_id": "R01"}]},
        execution_scope=_scope(),
        semantic_evidence={"cuts": ["C01"]},
    )
    second = build_source_evidence_bundle(
        probe={"fps": 30, "duration_us": 2_000_000},
        timeline={"regions": [{"region_id": "R01"}]},
        execution_scope=_scope(),
        semantic_evidence={"cuts": ["C01"]},
    )

    assert first["source_evidence_bundle_sha256"] == second["source_evidence_bundle_sha256"]
    validate_source_evidence_bundle(first)


def test_bundle_rejects_tampering() -> None:
    bundle = build_source_evidence_bundle(
        probe={"duration_us": 2_000_000},
        timeline={"regions": []},
        execution_scope=_scope(),
    )
    bundle["timeline"]["regions"].append({"region_id": "R02"})
    with pytest.raises(ReplicationError, match="digest mismatch"):
        validate_source_evidence_bundle(bundle)


def test_bundle_rejects_a_second_full_source_analysis() -> None:
    ledger = AnalysisInvocationLedger()
    ledger.record("semantic_vlm", scope="full_source")
    with pytest.raises(ReplicationError, match="full source analysis already completed"):
        ledger.record("semantic_vlm", scope="full_source")
