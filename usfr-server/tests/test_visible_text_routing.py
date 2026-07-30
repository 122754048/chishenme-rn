import pytest

from server.visible_text_contract import (
    VisibleTextContractError,
    split_visible_text_locks_by_render_route,
    visible_text_render_route,
)


def _lock(kind: str) -> dict:
    return {
        "text_id": f"text-{kind}",
        "cut_ids": ["C01", "C02"],
        "start_ms": 0,
        "end_ms": 3200,
        "kind": kind,
        "source_evidence_sha256": "a" * 64,
        "approved_text": "Free chat nahi?",
        "disposition": "keep",
        "placement": {
            "carrier_id": "paper-1",
            "surface_relation": "centered on the front face of the paper",
            "motion_behavior": "moves, bends, and tears with the paper",
        },
    }


def test_diegetic_prop_text_routes_through_image2_and_seedance() -> None:
    assert visible_text_render_route(_lock("paper_text")) == "generation_surface"


def test_subtitle_routes_to_deterministic_post_overlay() -> None:
    assert visible_text_render_route(_lock("subtitle")) == "deterministic_overlay"


def test_ui_text_routes_to_the_ui_lane() -> None:
    assert visible_text_render_route(_lock("ui_text")) == "deterministic_ui"


def test_split_keeps_scene_text_out_of_the_flat_overlay_lane() -> None:
    paper = _lock("paper_text")
    subtitle = _lock("subtitle")
    routed = split_visible_text_locks_by_render_route([paper, subtitle])
    assert routed["generation_surface"] == [paper]
    assert routed["deterministic_overlay"] == [subtitle]


def test_scene_surface_text_requires_an_explicit_physical_carrier_contract() -> None:
    paper = _lock("paper_text")
    paper["placement"].pop("motion_behavior")

    with pytest.raises(VisibleTextContractError, match="carrier"):
        visible_text_render_route(paper)
