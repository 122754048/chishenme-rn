from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _region(**overrides: object) -> dict[str, object]:
    region: dict[str, object] = {
        "region_id": "R03",
        "region_type": "generated_ui_demo",
        "source_start_us": 4_000_000,
        "source_end_us": 6_000_000,
        "display_viewport": [720, 1280],
        "transition_shell": {"kind": "swipe_left"},
    }
    region.update(overrides)
    return region


def test_builds_frame_locked_contract_for_product_model_ui_rebuild() -> None:
    from server.ui_interaction_contract import build_source_ui_interaction_contract

    contract = build_source_ui_interaction_contract(
        _region(),
        fps_num=24,
        fps_den=1,
        source_language="en",
        output_language=None,
    )

    assert contract["schema_version"] == "source-ui-interaction/v1"
    assert contract["region_id"] == "R03"
    assert contract["frame_window"] == {"start": 96, "end_exclusive": 144}
    assert contract["source_fps"] == {"num": 24, "den": 1}
    assert contract["ui_roi"] == {
        "x": 0,
        "y": 0,
        "width": 720,
        "height": 1280,
        "coordinate_space": "display_pixels",
    }
    assert contract["language"] == {"source": "en", "target": "en", "mode": "preserve_source"}
    assert contract["motion"] == {
        "capture_scope": "ui_roi_only",
        "track_policy": "source_frame_locked",
        "supported_actions": ["drag", "scroll", "bounce", "scale", "rotate", "opacity", "tap"],
    }
    assert contract["validation"] == {
        "mode": "basic_anchor_only",
        "automatic_retry": False,
        "anchor_frames": [96, 143],
    }


def test_target_language_overrides_source_language_without_losing_utf8_policy() -> None:
    from server.ui_interaction_contract import build_source_ui_interaction_contract

    contract = build_source_ui_interaction_contract(
        _region(),
        fps_num=30,
        fps_den=1,
        source_language="en",
        output_language="ar",
    )

    assert contract["language"] == {"source": "en", "target": "ar", "mode": "localized"}
    assert contract["text_encoding"] == {"encoding": "utf-8", "replacement_glyphs_forbidden": True}


def test_freezes_explicit_pixel_ui_roi_without_expanding_analysis_scope() -> None:
    from server.ui_interaction_contract import build_source_ui_interaction_contract

    contract = build_source_ui_interaction_contract(
        _region(ui_roi=[12, 30, 640, 900]),
        fps_num=30_000,
        fps_den=1001,
        source_language="en",
        output_language="pt",
    )

    assert contract["source_fps"] == {"num": 30_000, "den": 1001}
    assert contract["ui_roi"] == {
        "x": 12,
        "y": 30,
        "width": 640,
        "height": 900,
        "coordinate_space": "display_pixels",
    }


def test_validation_rejects_ui_roi_outside_display_viewport() -> None:
    from server.ui_interaction_contract import UiInteractionContractError, build_source_ui_interaction_contract

    with pytest.raises(UiInteractionContractError, match="ROI"):
        build_source_ui_interaction_contract(
            _region(ui_roi=[700, 0, 100, 100]),
            fps_num=24,
            fps_den=1,
            source_language="en",
            output_language=None,
        )


def test_validation_rejects_a_mutated_frame_locked_contract() -> None:
    from server.ui_interaction_contract import (
        UiInteractionContractError,
        build_source_ui_interaction_contract,
        validate_source_ui_interaction_contract,
    )

    contract = build_source_ui_interaction_contract(
        _region(),
        fps_num=24,
        fps_den=1,
        source_language="en",
        output_language=None,
    )
    contract["frame_window"] = {"start": 96, "end_exclusive": 96}

    with pytest.raises(UiInteractionContractError):
        validate_source_ui_interaction_contract(contract)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_end_us", 4_000_000),
        ("display_viewport", [0, 1280]),
        ("region_type", "generated"),
    ],
)
def test_rejects_invalid_or_non_ui_source_interval(field: str, value: object) -> None:
    from server.ui_interaction_contract import UiInteractionContractError, build_source_ui_interaction_contract

    with pytest.raises(UiInteractionContractError):
        build_source_ui_interaction_contract(
            _region(**{field: value}),
            fps_num=24,
            fps_den=1,
            source_language="en",
            output_language=None,
        )
