from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "source_pixel_card_compositor.py"
spec = importlib.util.spec_from_file_location("source_pixel_card_compositor", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_compositor_places_source_frame_without_changing_pixels_outside_card(tmp_path) -> None:
    base_path = tmp_path / "base.png"
    source_path = tmp_path / "source.png"
    output_path = tmp_path / "output.png"
    Image.new("RGB", (100, 80), (10, 20, 30)).save(base_path)
    Image.new("RGB", (20, 60), (220, 30, 40)).save(source_path)

    receipt = module.composite_source_pixel_cards(
        base_path=base_path,
        output_path=output_path,
        cards=[{"cut_id": "C01", "source_path": str(source_path), "rect": [20, 10, 40, 50], "fit": "contain"}],
    )

    rendered = Image.open(output_path).convert("RGB")
    assert rendered.getpixel((0, 0)) == (10, 20, 30)
    assert rendered.getpixel((40, 35)) == (220, 30, 40)
    assert receipt["outside_card_rect_changed_pixels"] == 0
    assert receipt["cards"][0]["cut_id"] == "C01"


def test_compositor_uses_only_source_pixels_for_each_declared_card(tmp_path) -> None:
    base_path = tmp_path / "base.png"
    source_path = tmp_path / "source.png"
    Image.new("RGB", (100, 80), (10, 20, 30)).save(base_path)
    Image.new("RGB", (20, 60), (220, 30, 40)).save(source_path)

    try:
        module.composite_source_pixel_cards(
            base_path=base_path,
            output_path=tmp_path / "output.png",
            cards=[{"cut_id": "C01", "source_path": str(source_path), "rect": [80, 60, 40, 50], "fit": "contain"}],
        )
    except ValueError as error:
        assert "card rect" in str(error)
    else:
        raise AssertionError("out-of-bounds source-pixel card was accepted")
