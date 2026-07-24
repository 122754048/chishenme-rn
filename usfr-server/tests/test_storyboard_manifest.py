import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts" / "storyboard_manifest.py"
spec = importlib.util.spec_from_file_location("storyboard_manifest", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def _cut(cut_id, sha=None):
    return {
        "cut_id": cut_id,
        "object_key": f"storyboards/r2/cuts/{cut_id}.png",
        "sha256": sha or (cut_id.lower() * 64)[:64],
        "width": 1920,
        "height": 1080,
    }


def test_manifest_freezes_exact_order_and_script_parent_sha():
    manifest = module.build_storyboard_manifest(
        revision_number=2,
        approved_script_sha256="a" * 64,
        ordered_cut_ids=["C01", "C02"],
        cut_images=[_cut("C01"), _cut("C02")],
    )
    assert manifest["cut_ids"] == ["C01", "C02"]
    assert manifest["approved_script_sha256"] == "a" * 64
    assert [item["cut_id"] for item in manifest["cut_images"]] == ["C01", "C02"]
    assert len(manifest["manifest_sha256"]) == 64


def test_partial_regeneration_reuses_single_cut_and_continuity_neighbors():
    previous = module.build_storyboard_manifest(
        revision_number=1,
        approved_script_sha256="a" * 64,
        ordered_cut_ids=["C01", "C02", "C03"],
        cut_images=[_cut("C01"), _cut("C02"), _cut("C03")],
    )
    manifest = module.build_storyboard_manifest(
        revision_number=2,
        approved_script_sha256="b" * 64,
        ordered_cut_ids=["C01", "C02", "C03"],
        cut_images=[_cut("C02", "b" * 64)],
        previous_manifest=previous,
        requested_cut_ids=["C02"],
        continuity=True,
    )
    assert [x["cut_id"] for x in manifest["cut_images"]] == ["C01", "C02", "C03"]
    assert manifest["cut_images"][0]["sha256"] == previous["cut_images"][0]["sha256"]
    assert manifest["cut_images"][1]["sha256"] == "b" * 64
    assert manifest["regenerated_cut_ids"] == ["C02"]


@pytest.mark.parametrize(
    "cuts, message",
    [
        (["C01", "C01"], "duplicate"),
        (["C01"], "missing"),
        (["C02", "C01"], "order"),
    ],
)
def test_manifest_rejects_duplicate_missing_or_reordered_cuts(cuts, message):
    with pytest.raises(ValueError, match=message):
        module.build_storyboard_manifest(
            revision_number=1,
            approved_script_sha256="a" * 64,
            ordered_cut_ids=["C01", "C02"],
            cut_images=[_cut(cut_id) for cut_id in cuts],
        )


def test_manifest_sidecars_are_unique_and_overview_is_not_authority(tmp_path):
    manifest = module.build_storyboard_manifest(
        revision_number=3,
        approved_script_sha256="a" * 64,
        ordered_cut_ids=["C01", "C02"],
        cut_images=[_cut("C01"), _cut("C02")],
        output_root=tmp_path,
    )
    paths = [item["object_key"] for item in manifest["cut_images"]]
    assert len(paths) == len(set(paths))
    assert manifest["overview"]["object_key"].endswith("r3/overview.png")
    overview = module.render_overview_grid(manifest, tmp_path / "overview.png")
    assert overview == tmp_path / "overview.png"
    module.validate_storyboard_manifest(manifest)
    tampered = dict(manifest)
    tampered["overview"] = {"object_key": "wrong.png", "sha256": "0" * 64}
    module.validate_storyboard_manifest(tampered)


def _segment_board(segment_id: str, sha: str, *, previous_board_sha256: str | None = None):
    value = {
        "segment_id": segment_id,
        "object_key": f"storyboards/r3/{segment_id}.png",
        "sha256": sha,
        "width": 2048,
        "height": 1152,
    }
    if previous_board_sha256 is not None:
        value["previous_board_sha256"] = previous_board_sha256
    return value


def _pair_continuity():
    return {
        "schema_version": "storyboard-continuity/v1",
        "character_identity_lock": {"character_id": "CHARACTER_A", "appearance": "long black hair"},
        "wardrobe_lock": {"top": "blue linen shirt", "bottom": "black trousers", "accessories": "silver watch"},
        "product_interaction_lock": {"hand": "right", "orientation": "label toward camera"},
        "segment_01_final_state": {"pose": "holds bottle at chest", "screen_direction": "faces right"},
        "segment_02_opening_state": {"pose": "holds bottle at chest", "screen_direction": "faces right"},
    }


def test_paired_storyboard_manifest_requires_second_board_to_bind_the_first_and_exposes_one_review():
    first_sha = "c" * 64
    manifest = module.build_paired_storyboard_manifest(
        revision_number=3,
        approved_script_sha256="a" * 64,
        segment_boards=[
            _segment_board("S01", first_sha),
            _segment_board("S02", "d" * 64, previous_board_sha256=first_sha),
        ],
        continuity_manifest=_pair_continuity(),
        continuity_qa={
            "status": "passed",
            "checked_fields": [
                "character_identity_lock",
                "wardrobe_lock",
                "product_interaction_lock",
                "screen_direction",
            ],
        },
    )

    assert manifest["review"]["approval_scope"] == "all_segments_together"
    assert manifest["segments"][1]["previous_board_sha256"] == first_sha
    assert manifest["continuity_qa"]["status"] == "passed"
    module.validate_paired_storyboard_manifest(manifest)


def test_paired_storyboard_manifest_rejects_missing_second_board_handoff():
    with pytest.raises(ValueError, match="previous_board_sha256"):
        module.build_paired_storyboard_manifest(
            revision_number=3,
            approved_script_sha256="a" * 64,
            segment_boards=[_segment_board("S01", "c" * 64), _segment_board("S02", "d" * 64)],
            continuity_manifest=_pair_continuity(),
            continuity_qa={"status": "passed", "checked_fields": ["wardrobe_lock"]},
        )


def test_paired_storyboard_regeneration_only_expands_downstream_continuations():
    assert module.select_paired_storyboard_regeneration(
        ordered_segment_ids=["S01", "S02"], failed_segment_ids=["S02"]
    ) == ["S02"]
    assert module.select_paired_storyboard_regeneration(
        ordered_segment_ids=["S01", "S02"], failed_segment_ids=["S01"]
    ) == ["S01", "S02"]

