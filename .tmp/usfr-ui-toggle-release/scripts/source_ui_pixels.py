"""Deterministic source-UI pixel handling for local USFR runs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw


SOURCE_UI_RENDER_MODE = "source_pixels"
OPAQUE_UI_RENDER_MODE = "uploaded_video_pixels"
AUTHORIZED_REPLACEMENT_MODE = "source_pixels_with_deterministic_authorized_replacement"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rect(rect: Sequence[int], *, width: int, height: int) -> tuple[int, int, int, int]:
    if len(rect) != 4 or any(not isinstance(value, int) or isinstance(value, bool) for value in rect):
        raise ValueError("replacement rect must contain four integer values")
    x, y, rect_width, rect_height = rect
    if x < 0 or y < 0 or rect_width < 1 or rect_height < 1 or x + rect_width > width or y + rect_height > height:
        raise ValueError("replacement rect must be fully inside the source frame")
    return x, y, rect_width, rect_height


def _cover(image: Image.Image, *, width: int, height: int) -> Image.Image:
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(width, round(image.width * scale)), max(height, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _outside_changed_pixels(before: Image.Image, after: Image.Image, rect: tuple[int, int, int, int]) -> int:
    x, y, width, height = rect
    before_pixels = before.convert("RGB").load()
    after_pixels = after.convert("RGB").load()
    changed = 0
    for row in range(before.height):
        for column in range(before.width):
            if x <= column < x + width and y <= row < y + height:
                continue
            if before_pixels[column, row] != after_pixels[column, row]:
                changed += 1
    return changed


def compose_authorized_replacement(
    *,
    source_path: Path,
    replacement_path: Path,
    output_path: Path,
    rect: Sequence[int],
    corner_radius: int = 0,
) -> dict[str, Any]:
    """Replace only an approved UI rectangle while preserving all other pixels."""
    source_path = Path(source_path)
    replacement_path = Path(replacement_path)
    output_path = Path(output_path)
    source = Image.open(source_path).convert("RGBA")
    replacement = Image.open(replacement_path).convert("RGBA")
    x, y, width, height = _rect(rect, width=source.width, height=source.height)
    if not isinstance(corner_radius, int) or corner_radius < 0 or corner_radius * 2 > min(width, height):
        raise ValueError("corner_radius is invalid for the replacement rect")

    target = _cover(replacement, width=width, height=height)
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=corner_radius, fill=255)
    rendered = source.copy()
    rendered.alpha_composite(target, (x, y), (0, 0, width, height))
    if corner_radius:
        # Restore source pixels in the rounded-off corners after compositing.
        source_crop = source.crop((x, y, x + width, y + height))
        rounded = Image.composite(target, source_crop, mask)
        rendered.paste(rounded, (x, y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered.convert("RGB").save(output_path, format="PNG")
    outside_changed = _outside_changed_pixels(source, rendered, (x, y, width, height))
    if outside_changed:
        raise RuntimeError("source UI replacement changed pixels outside the authorized rect")
    return {
        "schema_version": "usfr-source-ui-pixels/v1",
        "render_mode": AUTHORIZED_REPLACEMENT_MODE,
        "source_path": str(source_path),
        "source_sha256": _sha256(source_path),
        "replacement_path": str(replacement_path),
        "replacement_sha256": _sha256(replacement_path),
        "output_path": str(output_path),
        "output_sha256": _sha256(output_path),
        "source_dimensions": [source.width, source.height],
        "authorized_rect": [x, y, width, height],
        "corner_radius": corner_radius,
        "outside_authorized_rect_changed_pixels": outside_changed,
    }


def source_ui_model_partition(regions: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Split UI source pixels, opaque uploads, and model-eligible generated cuts."""
    source_pixel_cut_ids: list[str] = []
    opaque_ui_cut_ids: list[str] = []
    image_model_allowed_cut_ids: list[str] = []
    for index, raw_region in enumerate(regions):
        if not isinstance(raw_region, Mapping):
            raise ValueError(f"timeline region {index} must be an object")
        region = dict(raw_region)
        cut_ids = region.get("source_cut_ids")
        if not isinstance(cut_ids, list) or not cut_ids or any(not isinstance(cut_id, str) or not cut_id for cut_id in cut_ids):
            raise ValueError(f"timeline region {index} must declare source_cut_ids")
        region_type = str(region.get("region_type") or "")
        if region_type == "opaque_ui_demo":
            if (
                region.get("media_origin") != "user_upload"
                or region.get("assembly_policy") != "splice_opaque_media"
                or region.get("include_in_seedance") is not False
                or region.get("storyboard_render_mode") != OPAQUE_UI_RENDER_MODE
            ):
                raise ValueError("uploaded UI operation video must remain opaque and out of every redraw lane")
            opaque_ui_cut_ids.extend(cut_ids)
        elif region_type == "source_ui_keep":
            if (
                region.get("media_origin") != "source_interval"
                or region.get("include_in_seedance") is not False
                or region.get("storyboard_render_mode") != SOURCE_UI_RENDER_MODE
                or region.get("control_keyframe_render_mode") != SOURCE_UI_RENDER_MODE
            ):
                raise ValueError("source_ui_keep must use source pixels and cannot enter model generation")
            source_pixel_cut_ids.extend(cut_ids)
        elif region.get("media_origin") in {"generated", "generated_media"}:
            image_model_allowed_cut_ids.extend(cut_ids)
    for collection in (source_pixel_cut_ids, opaque_ui_cut_ids, image_model_allowed_cut_ids):
        if len(collection) != len(set(collection)):
            raise ValueError("a Cut cannot belong to multiple UI/model lanes")
    if set(source_pixel_cut_ids) & set(opaque_ui_cut_ids):
        raise ValueError("a Cut cannot be both source UI and uploaded opaque UI")
    return {
        "source_pixel_cut_ids": source_pixel_cut_ids,
        "image_model_allowed_cut_ids": image_model_allowed_cut_ids,
        "opaque_ui_cut_ids": opaque_ui_cut_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an exact source-UI frame with one authorized replacement rectangle.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--replacement", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rect", required=True, help="x,y,width,height in source-frame pixels")
    parser.add_argument("--corner-radius", type=int, default=0)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        rect = [int(value) for value in args.rect.split(",")]
    except ValueError as error:
        raise ValueError("--rect must be x,y,width,height") from error
    receipt = compose_authorized_replacement(
        source_path=args.source,
        replacement_path=args.replacement,
        output_path=args.output,
        rect=rect,
        corner_radius=args.corner_radius,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
