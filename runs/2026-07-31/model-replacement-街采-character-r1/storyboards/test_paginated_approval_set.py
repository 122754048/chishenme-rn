from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


RUN = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_revision_v4_is_two_page_director_board_only_set() -> None:
    manifest = json.loads((RUN / "storyboards" / "segment_01_v4_approval_set.json").read_text(encoding="utf-8-sig"))
    assert manifest["status"] == "awaiting_confirmation"
    assert manifest["user_visible_artifact_kinds"] == ["director_storyboard_png"]
    assert manifest["internal_artifacts_excluded"] == ["replacement_control_sheet"]
    assert [page["cut_ids"] for page in manifest["pages"]] == [
        ["C01", "C02", "C03"],
        ["C04", "C05", "C06", "C07"],
    ]


def test_each_page_is_exact_16_9_and_has_at_most_four_cuts() -> None:
    manifest = json.loads((RUN / "storyboards" / "segment_01_v4_approval_set.json").read_text(encoding="utf-8-sig"))
    for page in manifest["pages"]:
        path = RUN / page["path"]
        image = Image.open(path)
        assert image.width * 9 == image.height * 16
        assert 1 <= len(page["cut_ids"]) <= 4
        assert sha256(path) == page["sha256"]


def test_each_page_binds_updated_layout_authority_and_control_provenance() -> None:
    manifest = json.loads((RUN / "storyboards" / "segment_01_v4_approval_set.json").read_text(encoding="utf-8-sig"))
    template = Path(manifest["daohuo_storyboard_prompt_path"])
    assert sha256(template) == manifest["daohuo_storyboard_prompt_sha256"]
    control_sha = sha256(RUN / "reference_frames" / "replacement_control_sheet.png")
    for page in manifest["pages"]:
        assert page["reference_1_sha256"] == control_sha
        assert page["daohuo_storyboard_prompt_sha256"] == manifest["daohuo_storyboard_prompt_sha256"]
        assert page["raw_sha256"] != page["sha256"]
