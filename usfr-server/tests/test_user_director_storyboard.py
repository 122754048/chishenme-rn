from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_user_director_storyboard.py"
TEMPLATE = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "references" / "daohuo_storyboard_prompt.md"
spec = importlib.util.spec_from_file_location("validate_user_director_storyboard", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def _scope() -> dict:
    return {"status": "passed", "allowed_cut_ids": ["C01", "C02", "C03"], "excluded_cut_ids": ["C04"]}


def _prompt() -> str:
    return """Use case: infographic-diagram
Primary request:
Layout contract: usfr-cinematic-director-production-board/v1
Fixed layout:
- creative_header: title and shared creative direction.
- character_reference: identity and style evidence.
- face_hair_reference: face and hair detail views.
- wardrobe_style: wardrobe and accessory evidence.
- storyboard_grid: center ordered Cut cards.
- target_evidence: applicable target evidence or none.
- camera_movement_diagram: top-down camera and subject diagram.
- lighting: lighting direction.
- camera: camera direction.
- palette: approved palette.
- audio_tone: source audio and tone.
- mood: short mood keywords.
- cinematography_notes: continuity and finishing notes.
Storyboard cards:
1. Cut C01, 0.0-1.0s: opening.
2. Cut C02, 1.0-2.0s: action.
3. Cut C03, 2.0-3.0s: ending.
Exact allowed text:
TITLE; C01; C02; C03.
Text constraints:
Short labels only.
Avoid:
generic grid.
"""


def test_accepts_director_board_that_covers_every_allowed_cut_in_order() -> None:
    receipt = module.validate_user_director_storyboard(_prompt(), _scope(), TEMPLATE.read_bytes())

    assert receipt["approval_cut_ids"] == ["C01", "C02", "C03"]


def test_rejects_partial_board_created_from_provider_segments() -> None:
    partial_prompt = _prompt().replace("2. Cut C02, 1.0-2.0s: action.\n", "").replace("3. Cut C03, 2.0-3.0s: ending.\n", "")

    with pytest.raises(module.UserDirectorStoryboardError, match="coverage"):
        module.validate_user_director_storyboard(partial_prompt, _scope(), TEMPLATE.read_bytes())


def test_rejects_a_generic_seven_panel_grid_even_when_all_cuts_are_mentioned() -> None:
    generic = _prompt().replace(
        "- storyboard_grid: center ordered Cut cards.",
        "- storyboard_grid: generic seven-panel grid.",
    )

    with pytest.raises(module.UserDirectorStoryboardError, match="generic"):
        module.validate_user_director_storyboard(generic, _scope(), TEMPLATE.read_bytes())


def test_rejects_a_prompt_missing_one_fixed_professional_region() -> None:
    missing_camera = _prompt().replace("- camera_movement_diagram: top-down camera and subject diagram.\n", "")

    with pytest.raises(module.UserDirectorStoryboardError, match="layout"):
        module.validate_user_director_storyboard(missing_camera, _scope(), TEMPLATE.read_bytes())


def test_rejects_publication_without_the_mandatory_daohuo_template() -> None:
    with pytest.raises(module.UserDirectorStoryboardError, match="daohuo_storyboard_prompt"):
        module.validate_user_director_storyboard(_prompt(), _scope(), None)
