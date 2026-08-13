from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from build_spatial_binding_board import build_board


ROOT = Path(__file__).resolve().parent


def test_build_board_is_deterministic_and_preserves_four_explicit_bindings(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"

    manifest_a = build_board(ROOT / "identity_v3", first)
    manifest_b = build_board(ROOT / "identity_v3", second)

    with Image.open(first) as image:
        assert image.size == (1080, 1920)
        assert image.mode == "RGB"
    assert manifest_a["bindings"] == [
        {"target_tag": "TARGET_BLONDE", "source_object_id": "SRC_BLONDE", "locator": "first-frame left"},
        {"target_tag": "TARGET_MAN", "source_object_id": "SRC_MAN", "locator": "first-frame center"},
        {"target_tag": "TARGET_DARK", "source_object_id": "SRC_DARK", "locator": "first-frame right"},
        {"target_tag": "TARGET_CAT", "source_object_id": "SRC_ALIEN", "locator": "enters from left at 3.15s"},
    ]
    assert manifest_a["sha256"] == manifest_b["sha256"]
    assert manifest_a["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()

