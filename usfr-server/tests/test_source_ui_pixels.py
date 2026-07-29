from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "source_ui_pixels.py"
spec = importlib.util.spec_from_file_location("source_ui_pixels", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_authorized_ui_replacement_preserves_every_pixel_outside_its_rectangle(tmp_path) -> None:
    source_path = tmp_path / "source.png"
    target_path = tmp_path / "target.png"
    output_path = tmp_path / "output.png"
    source = Image.new("RGB", (40, 60), (12, 34, 56))
    source.putpixel((0, 0), (255, 255, 255))
    source.save(source_path)
    Image.new("RGB", (20, 10), (220, 10, 40)).save(target_path)

    receipt = module.compose_authorized_replacement(
        source_path=source_path,
        replacement_path=target_path,
        output_path=output_path,
        rect=(8, 12, 20, 30),
        corner_radius=4,
    )

    rendered = Image.open(output_path).convert("RGB")
    assert rendered.getpixel((0, 0)) == (255, 255, 255)
    assert rendered.getpixel((20, 27)) == (220, 10, 40)
    assert receipt["outside_authorized_rect_changed_pixels"] == 0
    assert receipt["render_mode"] == "source_pixels_with_deterministic_authorized_replacement"


def test_authorized_ui_replacement_rejects_any_rectangle_outside_the_source_frame(tmp_path) -> None:
    source_path = tmp_path / "source.png"
    target_path = tmp_path / "target.png"
    Image.new("RGB", (40, 60), (12, 34, 56)).save(source_path)
    Image.new("RGB", (20, 10), (220, 10, 40)).save(target_path)

    with pytest.raises(ValueError, match="replacement rect"):
        module.compose_authorized_replacement(
            source_path=source_path,
            replacement_path=target_path,
            output_path=tmp_path / "output.png",
            rect=(30, 45, 20, 30),
            corner_radius=4,
        )


def test_source_ui_partition_forbids_model_generation_for_source_pixel_cuts() -> None:
    partition = module.source_ui_model_partition([
        {
            "region_type": "source_ui_keep",
            "source_cut_ids": ["C01", "C02"],
            "media_origin": "source_interval",
            "include_in_seedance": False,
            "storyboard_render_mode": "source_pixels",
            "control_keyframe_render_mode": "source_pixels",
        },
        {
            "region_type": "character_replacement_performance",
            "source_cut_ids": ["C03"],
            "media_origin": "generated_media",
            "include_in_seedance": True,
        },
    ])

    assert partition == {
        "source_pixel_cut_ids": ["C01", "C02"],
        "image_model_allowed_cut_ids": ["C03"],
        "opaque_ui_cut_ids": [],
    }


def test_uploaded_ui_operation_video_is_opaque_and_never_enters_any_redraw_lane() -> None:
    partition = module.source_ui_model_partition([
        {
            "region_type": "opaque_ui_demo",
            "source_cut_ids": ["C01", "C02"],
            "media_origin": "user_upload",
            "assembly_policy": "splice_opaque_media",
            "include_in_seedance": False,
            "storyboard_render_mode": "uploaded_video_pixels",
        },
        {
            "region_type": "character_replacement_performance",
            "source_cut_ids": ["C03"],
            "media_origin": "generated_media",
            "include_in_seedance": True,
        },
    ])

    assert partition == {
        "source_pixel_cut_ids": [],
        "image_model_allowed_cut_ids": ["C03"],
        "opaque_ui_cut_ids": ["C01", "C02"],
    }
