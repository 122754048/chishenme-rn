from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "control_keyframe_contract.py"
spec = importlib.util.spec_from_file_location("control_keyframe_contract", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def _source_dynamics() -> dict:
    return {
        "source_cuts": [
            {"cut": 1, "start_us": 0, "end_us": 1_000_000},
            {"cut": 2, "start_us": 1_000_000, "end_us": 2_000_000},
            {"cut": 3, "start_us": 2_000_000, "end_us": 3_000_000},
        ]
    }


def test_builds_exactly_one_control_panel_for_each_source_cut() -> None:
    manifest = module.build_control_keyframe_manifest(_source_dynamics())

    assert manifest["panel_count"] == 3
    assert [panel["cut_id"] for panel in manifest["panels"]] == ["C01", "C02", "C03"]
    assert manifest["fixed_panel_count"] is None


def test_rejects_missing_or_extra_control_panels() -> None:
    manifest = module.build_control_keyframe_manifest(_source_dynamics())
    manifest["panels"].pop()
    manifest["panel_count"] = 2

    with pytest.raises(module.ControlKeyframeContractError, match="match source Cuts"):
        module.validate_control_keyframe_manifest(_source_dynamics(), manifest)


def test_rejects_legacy_fixed_panel_count_rule() -> None:
    manifest = module.build_control_keyframe_manifest(_source_dynamics())
    manifest["fixed_panel_count"] = 9

    with pytest.raises(module.ControlKeyframeContractError, match="fixed panel count"):
        module.validate_control_keyframe_manifest(_source_dynamics(), manifest)


def test_requires_source_keyframe_lineage_for_replacement_control_sheet() -> None:
    source = _source_dynamics()
    manifest = module.build_control_keyframe_manifest(
        source,
        source_video_sha256="a" * 64,
        source_keyframes=[
            {"cut_id": "C01", "timestamp_us": 0, "sha256": "1" * 64},
            {"cut_id": "C02", "timestamp_us": 1_000_000, "sha256": "2" * 64},
            {"cut_id": "C03", "timestamp_us": 2_000_000, "sha256": "3" * 64},
        ],
        source_keyframe_sheet_sha256="4" * 64,
        replacement_control_sheet_sha256="5" * 64,
        replacement_target_sha256s=["6" * 64],
    )

    receipt = module.validate_control_keyframe_manifest(source, manifest)

    assert receipt["source_keyframe_sheet_sha256"] == "4" * 64
    assert receipt["replacement_control_sheet_sha256"] == "5" * 64
    assert receipt["required_director_board_reference_sha256"] == "5" * 64
    assert receipt["final_seedance_reference_contract"] == {
        "source_video_required": True,
        "director_board_required_at_image_slot": 1,
        "internal_artifacts_forbidden": [
            "source_keyframe_sheet",
            "replacement_control_sheet",
        ],
    }


def test_rejects_control_sheet_without_source_keyframe_lineage() -> None:
    with pytest.raises(module.ControlKeyframeContractError, match="source keyframe lineage"):
        module.validate_control_keyframe_manifest(
            _source_dynamics(), module.build_control_keyframe_manifest(_source_dynamics())
        )


def test_source_preserve_board_still_uses_the_source_keyframe_to_control_sheet_chain() -> None:
    source = _source_dynamics()
    manifest = module.build_control_keyframe_manifest(
        source,
        source_video_sha256="a" * 64,
        source_keyframes=[
            {"cut_id": "C01", "timestamp_us": 0, "sha256": "1" * 64},
            {"cut_id": "C02", "timestamp_us": 1_000_000, "sha256": "2" * 64},
            {"cut_id": "C03", "timestamp_us": 2_000_000, "sha256": "3" * 64},
        ],
        source_keyframe_sheet_sha256="4" * 64,
        replacement_control_sheet_sha256="5" * 64,
        replacement_target_sha256s=[],
    )

    receipt = module.validate_control_keyframe_manifest(source, manifest)

    assert receipt["replacement_target_sha256s"] == []
