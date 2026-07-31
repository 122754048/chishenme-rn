from __future__ import annotations

import hashlib
import io

import pytest
from PIL import Image


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
TEMPLATE = (
    ROOT
    / "bundled-skills"
    / "seedance-storyboard-replication"
    / "references"
    / "daohuo_storyboard_prompt.md"
)


def _template_bytes() -> bytes:
    return TEMPLATE.read_bytes()


def _visual_sheet(*, width: int = 1600, height: int = 900) -> bytes:
    image = Image.new("RGB", (width, height), (32, 42, 56))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _cuts(count: int) -> list[dict[str, object]]:
    return [
        {
            "cut_id": f"C{index:02d}",
            "start_ms": (index - 1) * 1000,
            "end_ms": index * 1000,
            "scene": f"scene {index}",
            "action": f"action {index}",
            "camera": f"camera {index}",
        }
        for index in range(1, count + 1)
    ]


def test_renders_the_fixed_professional_layout_and_exact_cut_card_count() -> None:
    from server.storyboard_layout_contract import render_director_board, validate_storyboard_layout_receipt

    rendered = render_director_board(
        visual_sheet_bytes=_visual_sheet(),
        template_bytes=_template_bytes(),
        segment_id="S01",
        cuts=_cuts(7),
        direction_text="Preserve the approved source performance.",
        character_target_text="Use only the approved replacement identity.",
        camera_text="Match the source camera contract.",
        continuity_text="Keep hand, paper and tear continuity.",
    )

    receipt = validate_storyboard_layout_receipt(rendered["layout_receipt"], expected_cut_ids=[f"C{i:02d}" for i in range(1, 8)])
    assert receipt["layout_id"] == "usfr-cinematic-director-production-board/v1"
    assert receipt["template_path"] == "bundled-skills/seedance-storyboard-replication/references/daohuo_storyboard_prompt.md"
    assert receipt["template_sha256"] == hashlib.sha256(_template_bytes()).hexdigest()
    assert receipt["cut_count"] == 7
    assert [card["cut_id"] for card in receipt["cut_cards"]] == [f"C{i:02d}" for i in range(1, 8)]
    assert set(receipt["regions"]) == {
        "creative_header",
        "character_reference",
        "face_hair_reference",
        "wardrobe_style",
        "storyboard_grid",
        "target_evidence",
        "camera_movement_diagram",
        "lighting",
        "camera",
        "palette",
        "audio_tone",
        "mood",
        "cinematography_notes",
    }
    with Image.open(io.BytesIO(rendered["approval_image_bytes"])) as board:
        assert board.width * 9 == board.height * 16
    assert hashlib.sha256(rendered["approval_image_bytes"]).hexdigest() == receipt["approval_board_sha256"]
    assert hashlib.sha256(rendered["execution_carrier_bytes"]).hexdigest() == receipt["execution_carrier_sha256"]


def test_preserves_the_template_generated_image2_board_as_the_approval_artifact() -> None:
    from server.storyboard_layout_contract import render_director_board

    provider_board = _visual_sheet(width=1600, height=900)
    rendered = render_director_board(
        visual_sheet_bytes=provider_board,
        template_bytes=_template_bytes(),
        segment_id="S01",
        cuts=_cuts(3),
        direction_text="direction",
        character_target_text="character",
        camera_text="camera",
        continuity_text="continuity",
    )

    assert rendered["approval_image_bytes"] == provider_board


def test_rejects_a_seven_cut_board_receipt_with_only_six_cards() -> None:
    from server.storyboard_layout_contract import StoryboardLayoutError, render_director_board, validate_storyboard_layout_receipt

    rendered = render_director_board(
        visual_sheet_bytes=_visual_sheet(),
        template_bytes=_template_bytes(),
        segment_id="S01",
        cuts=_cuts(7),
        direction_text="direction",
        character_target_text="character",
        camera_text="camera",
        continuity_text="continuity",
    )
    receipt = dict(rendered["layout_receipt"])
    receipt["cut_cards"] = list(receipt["cut_cards"][:-1])

    with pytest.raises(StoryboardLayoutError, match="Cut coverage"):
        validate_storyboard_layout_receipt(receipt, expected_cut_ids=[f"C{i:02d}" for i in range(1, 8)])


def test_rejects_a_layout_receipt_missing_any_fixed_region() -> None:
    from server.storyboard_layout_contract import StoryboardLayoutError, render_director_board, validate_storyboard_layout_receipt

    rendered = render_director_board(
        visual_sheet_bytes=_visual_sheet(),
        template_bytes=_template_bytes(),
        segment_id="S01",
        cuts=_cuts(2),
        direction_text="direction",
        character_target_text="character",
        camera_text="camera",
        continuity_text="continuity",
    )
    receipt = dict(rendered["layout_receipt"])
    receipt["regions"] = dict(receipt["regions"])
    receipt["regions"].pop("camera_movement_diagram")

    with pytest.raises(StoryboardLayoutError, match="fixed regions"):
        validate_storyboard_layout_receipt(receipt, expected_cut_ids=["C01", "C02"])


def test_execution_carrier_is_cryptographically_bound_to_the_approved_board_roi() -> None:
    from server.storyboard_layout_contract import render_director_board, validate_storyboard_layout_receipt

    rendered = render_director_board(
        visual_sheet_bytes=_visual_sheet(),
        template_bytes=_template_bytes(),
        segment_id="S01",
        cuts=_cuts(3),
        direction_text="direction",
        character_target_text="character",
        camera_text="camera",
        continuity_text="continuity",
    )
    receipt = validate_storyboard_layout_receipt(rendered["layout_receipt"], expected_cut_ids=["C01", "C02", "C03"])

    assert receipt["execution_carrier_source"] == "approved_board.storyboard_grid"
    assert receipt["execution_carrier_source_roi"] == receipt["regions"]["storyboard_grid"]
    assert len(receipt["execution_carrier_source_roi_sha256"]) == 64


def test_missing_layout_receipt_can_never_authorize_storyboard_publication() -> None:
    from server.storyboard_layout_contract import StoryboardLayoutError, validate_storyboard_layout_receipt

    with pytest.raises(StoryboardLayoutError, match="receipt"):
        validate_storyboard_layout_receipt(None, expected_cut_ids=["C01"])


def test_refuses_to_render_without_the_mandatory_daohuo_template() -> None:
    from server.storyboard_layout_contract import StoryboardLayoutError, render_director_board

    with pytest.raises(StoryboardLayoutError, match="daohuo_storyboard_prompt"):
        render_director_board(
            visual_sheet_bytes=_visual_sheet(),
            template_bytes=None,
            segment_id="S01",
            cuts=_cuts(1),
            direction_text="direction",
            character_target_text="character",
            camera_text="camera",
            continuity_text="continuity",
        )


def test_refuses_a_substitute_template_that_lacks_the_fixed_director_board_contract() -> None:
    from server.storyboard_layout_contract import StoryboardLayoutError, render_director_board

    with pytest.raises(StoryboardLayoutError, match="template contract"):
        render_director_board(
            visual_sheet_bytes=_visual_sheet(),
            template_bytes=b"Use case: infographic-diagram\nFixed layout:\n- generic grid",
            segment_id="S01",
            cuts=_cuts(1),
            direction_text="direction",
            character_target_text="character",
            camera_text="camera",
            continuity_text="continuity",
        )
