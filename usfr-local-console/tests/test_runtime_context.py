import copy

import pytest

from app.runtime_context import (
    RuntimePacketError,
    compile_runtime_packet,
    validate_packet_lineage,
)


def _source_contract() -> dict[str, object]:
    return {
        "regions": [
            {"region_id": "c01", "start_ms": 0, "end_ms": 1000, "kind": "body"},
        ],
        "selling_points": ["verified feature proof"],
    }


def _execution_map() -> dict[str, object]:
    return {
        "source_analysis_sha256": "",
        "target_truth_sha256": "",
        "input_slots_sha256": "c" * 64,
        "run_mode": "composite_replication",
        "changed_layers": ["model", "language"],
        "regions": [
            {
                "region_id": "c01",
                "media_origin": "generated",
                "qa_profile": "generated_high_risk",
            }
        ],
        "skipped": [{"module": "tail_generation", "reason": "tail_video_supplied"}],
    }


def test_runtime_packet_contains_only_lineage_bound_stage_context():
    source_contract = _source_contract()
    target_truth = {"facts": {"new_model_image": {"source_sha256": "a" * 64}}}
    execution_map = _execution_map()

    packet = compile_runtime_packet(
        source_contract=source_contract,
        target_truth=target_truth,
        execution_map=execution_map,
        stage="storyboard_review_required",
    )

    assert packet["source_fidelity_contract_ref"]["sha256"]
    assert packet["target_truth"] == target_truth
    assert packet["execution_map"]["run_mode"] == "composite_replication"
    assert packet["route_cards"][0]["id"] == "model_replace"
    assert packet["qa_matrix"]["regions"][0]["region_id"] == "c01"
    assert "SKILL.md" not in str(packet)


def test_runtime_packet_rejects_changed_parent_contract_digest():
    packet = compile_runtime_packet(
        source_contract=_source_contract(),
        target_truth={"facts": {}},
        execution_map=_execution_map(),
        stage="storyboard_review_required",
    )
    changed = copy.deepcopy(packet)
    changed["lineage"]["source_contract_sha256"] = "0" * 64

    with pytest.raises(RuntimePacketError, match="RUNTIME_PACKET_LINEAGE_INVALID"):
        validate_packet_lineage(changed)


def test_runtime_packet_rejects_a_generated_region_that_is_not_in_the_frozen_source_contract():
    execution_map = _execution_map()
    execution_map["regions"][0]["region_id"] = "foreign-cut"

    with pytest.raises(RuntimePacketError, match="RUNTIME_PACKET_LINEAGE_INVALID"):
        compile_runtime_packet(
            source_contract=_source_contract(),
            target_truth={"facts": {}},
            execution_map=execution_map,
            stage="storyboard_review_required",
        )
