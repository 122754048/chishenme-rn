from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "timeline_scope_preflight.py"
spec = importlib.util.spec_from_file_location("timeline_scope_preflight", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def _input_slots() -> dict:
    return {
        "slots": {"tail_video": {"present": False}},
        "routes": {"tail": "omit_source_end_card"},
    }


def _timeline() -> dict:
    return {
        "schema_version": "usfr-timeline-regions/v1",
        "source_end_ms": 13700,
        "final_output_end_ms": 11333,
        "regions": [
            {
                "region_id": "R01",
                "source_cut_ids": ["C01", "C02", "C03"],
                "start_ms": 0,
                "end_ms": 5000,
                "region_type": "source_ui_keep",
                "media_origin": "source_interval",
                "assembly_policy": "source_ui_keep",
                "include_in_script": True,
                "include_in_storyboard": True,
                "include_in_seedance": False,
                "storyboard_render_mode": "source_pixels",
                "control_keyframe_render_mode": "source_pixels",
            },
            {
                "region_id": "R02",
                "source_cut_ids": ["C04", "C05", "C06"],
                "start_ms": 5000,
                "end_ms": 11333,
                "media_origin": "generated_media",
                "assembly_policy": "replace_character_from_slot",
                "include_in_script": True,
                "include_in_storyboard": True,
                "include_in_seedance": True,
            },
            {
                "region_id": "R03",
                "source_cut_ids": ["C07", "C08"],
                "start_ms": 11333,
                "end_ms": 13700,
                "media_origin": "excluded",
                "assembly_policy": "omit_source_end_card",
                "include_in_script": False,
                "include_in_storyboard": False,
                "include_in_seedance": False,
                "prohibited_artifact_terms": ["end-card", "download", "CTA"],
            },
        ],
    }


def _segment_plan() -> dict:
    return {
        "schema_version": "usfr-segment-plan/v1",
        "source_duration_ms": 13700,
        "segments": [
            {
                "segment_id": "S01",
                "start_ms": 5000,
                "end_ms": 11333,
                "duration_ms": 6333,
                "cut_ids": ["C04", "C05", "C06"],
            }
        ],
    }


def test_missing_tail_scope_rejects_a_storyboard_that_leaks_excluded_end_card() -> None:
    with pytest.raises(ValueError, match="OMITTED_SOURCE_END_CARD_LEAK"):
        module.build_scope_receipt(
            input_slots=_input_slots(),
            timeline_regions=_timeline(),
            segment_plan=_segment_plan(),
            text_artifacts={"storyboard": "C01 through C08, ending with a black download CTA."},
        )


def test_missing_tail_scope_freezes_only_preceding_body_and_authorizes_clean_artifacts() -> None:
    receipt = module.build_scope_receipt(
        input_slots=_input_slots(),
        timeline_regions=_timeline(),
        segment_plan=_segment_plan(),
        text_artifacts={
            "script": "C01-C03 keep the app structure. C04-C06 end on the desert performance at 11.333s.",
            "control": "One ordered panel per source Cut retains the app structure and desert performance through the final singer close-up.",
            "storyboard": "Six cut cards cover C01-C06 and end at 11.333 seconds on the singer.",
        },
    )

    assert receipt["status"] == "passed"
    assert receipt["final_output_end_ms"] == 11333
    assert receipt["allowed_cut_ids"] == ["C01", "C02", "C03", "C04", "C05", "C06"]
    assert receipt["excluded_cut_ids"] == ["C07", "C08"]
    assert receipt["source_pixel_cut_ids"] == ["C01", "C02", "C03"]
    assert receipt["image_model_allowed_cut_ids"] == ["C04", "C05", "C06"]


def test_missing_tail_scope_rejects_seedance_plan_that_extends_into_omitted_interval() -> None:
    plan = _segment_plan()
    plan["segments"][0]["end_ms"] = 13700
    plan["segments"][0]["duration_ms"] = 8700
    plan["segments"][0]["cut_ids"].append("C07")

    with pytest.raises(ValueError, match="OMITTED_SOURCE_END_CARD_LEAK"):
        module.build_scope_receipt(
            input_slots=_input_slots(),
            timeline_regions=_timeline(),
            segment_plan=plan,
            text_artifacts={"seedance": "C04-C07 desert performance."},
        )


def test_scope_receipt_admits_only_the_exact_preflighted_prompt() -> None:
    prompt = "Six cut cards cover C01-C06 and end at 11.333 seconds on the singer."
    receipt = module.build_scope_receipt(
        input_slots=_input_slots(),
        timeline_regions=_timeline(),
        segment_plan=_segment_plan(),
        text_artifacts={"storyboard": prompt},
    )

    module.validate_scope_receipt_for_text(receipt, prompt)

    with pytest.raises(ValueError, match="OMITTED_SOURCE_END_CARD_LEAK"):
        module.validate_scope_receipt_for_text(receipt, "C01 through C08 with an end-card.")


def test_missing_tail_scope_excludes_a_contiguous_cluster_of_terminal_regions() -> None:
    timeline = _timeline()
    timeline["regions"][-1:] = [
        {
            "region_id": "R03",
            "source_cut_ids": ["C07"],
            "start_ms": 11333,
            "end_ms": 11700,
            "media_origin": "excluded",
            "assembly_policy": "omit_source_end_card",
            "include_in_script": False,
            "include_in_storyboard": False,
            "include_in_seedance": False,
            "prohibited_artifact_terms": ["violet graphic"],
        },
        {
            "region_id": "R04",
            "source_cut_ids": ["C08"],
            "start_ms": 11700,
            "end_ms": 13700,
            "media_origin": "excluded",
            "assembly_policy": "omit_source_end_card",
            "include_in_script": False,
            "include_in_storyboard": False,
            "include_in_seedance": False,
            "prohibited_artifact_terms": ["store artwork"],
        },
    ]

    receipt = module.build_scope_receipt(
        input_slots=_input_slots(),
        timeline_regions=timeline,
        segment_plan=_segment_plan(),
        text_artifacts={"storyboard": "C01-C06 stop on the final singer close-up."},
    )

    assert receipt["excluded_cut_ids"] == ["C07", "C08"]
    assert receipt["final_output_end_ms"] == 11333
