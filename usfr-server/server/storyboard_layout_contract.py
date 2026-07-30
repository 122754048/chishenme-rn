"""Deterministic professional director-board layout and execution-carrier gate."""

from __future__ import annotations

import hashlib
import io
import math
import textwrap
from typing import Any, Mapping, Sequence


LAYOUT_ID = "usfr-professional-director-board/v1"
BOARD_SIZE = (1600, 900)
REQUIRED_REGIONS = (
    "direction_header",
    "character_target_column",
    "storyboard_grid",
    "camera_column",
    "continuity_footer",
)
REGIONS = {
    "direction_header": {"x": 0, "y": 0, "width": 1600, "height": 100},
    "character_target_column": {"x": 0, "y": 100, "width": 280, "height": 600},
    "storyboard_grid": {"x": 280, "y": 100, "width": 1040, "height": 600},
    "camera_column": {"x": 1320, "y": 100, "width": 280, "height": 600},
    "continuity_footer": {"x": 0, "y": 700, "width": 1600, "height": 200},
}


class StoryboardLayoutError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_bytes(image: Any) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def _font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    candidates = (
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_wrapped(draw: Any, text: str, box: tuple[int, int, int, int], *, size: int, fill: str, bold: bool = False) -> None:
    x0, y0, x1, y1 = box
    font = _font(size, bold=bold)
    average = max(1, size // 2)
    width_chars = max(8, (x1 - x0) // average)
    lines: list[str] = []
    for paragraph in str(text or "").splitlines() or [""]:
        lines.extend(textwrap.wrap(paragraph, width=width_chars, break_long_words=True) or [""])
    line_height = max(size + 5, int(size * 1.25))
    max_lines = max(1, (y1 - y0) // line_height)
    rendered = "\n".join(lines[:max_lines])
    draw.multiline_text((x0, y0), rendered, font=font, fill=fill, spacing=5)


def _extract_visual_cells(image: Any, count: int) -> list[Any]:
    from PIL import ImageOps

    columns = max(1, math.ceil(math.sqrt(count)))
    rows = max(1, math.ceil(count / columns))
    cells: list[Any] = []
    for index in range(count):
        column, row = index % columns, index // columns
        left = round(column * image.width / columns)
        top = round(row * image.height / rows)
        right = round((column + 1) * image.width / columns)
        bottom = round((row + 1) * image.height / rows)
        cells.append(ImageOps.fit(image.crop((left, top, right, bottom)), (480, 270)))
    return cells


def render_director_board(
    *,
    visual_sheet_bytes: bytes,
    segment_id: str,
    cuts: Sequence[Mapping[str, Any]],
    direction_text: str,
    character_target_text: str,
    camera_text: str,
    continuity_text: str,
) -> dict[str, Any]:
    """Render the approval board and a labels-free Seedance carrier from one visual sheet."""

    if not cuts:
        raise StoryboardLayoutError("director board requires at least one Cut")
    cut_ids = [str(cut.get("cut_id") or "").strip() for cut in cuts]
    if any(not cut_id for cut_id in cut_ids) or len(set(cut_ids)) != len(cut_ids):
        raise StoryboardLayoutError("director board Cut IDs must be non-empty and unique")
    try:
        from PIL import Image, ImageDraw, ImageOps

        with Image.open(io.BytesIO(visual_sheet_bytes)) as opened:
            visual_sheet = opened.convert("RGB")
    except Exception as exc:
        raise StoryboardLayoutError("director board visual sheet is not a decodable image") from exc

    cells = _extract_visual_cells(visual_sheet, len(cuts))
    grid_region = REGIONS["storyboard_grid"]
    columns = min(4, max(1, math.ceil(math.sqrt(len(cuts)))))
    rows = max(1, math.ceil(len(cuts) / columns))
    gap = 12
    cell_width = (grid_region["width"] - gap * (columns + 1)) // columns
    cell_height = (grid_region["height"] - gap * (rows + 1)) // rows
    visual_grid = Image.new("RGB", (grid_region["width"], grid_region["height"]), "#111827")
    card_boxes: list[dict[str, Any]] = []
    for index, (cut, cell) in enumerate(zip(cuts, cells)):
        column, row = index % columns, index // columns
        x = gap + column * (cell_width + gap)
        y = gap + row * (cell_height + gap)
        fitted = ImageOps.fit(cell, (cell_width, cell_height), method=Image.Resampling.LANCZOS)
        visual_grid.paste(fitted, (x, y))
        card_boxes.append(
            {
                "cut_id": cut_ids[index],
                "x": grid_region["x"] + x,
                "y": grid_region["y"] + y,
                "width": cell_width,
                "height": cell_height,
            }
        )

    execution_carrier_bytes = _png_bytes(visual_grid)
    board = Image.new("RGB", BOARD_SIZE, "#0b1220")
    draw = ImageDraw.Draw(board)
    for region_id, box in REGIONS.items():
        x0, y0 = box["x"], box["y"]
        x1, y1 = x0 + box["width"], y0 + box["height"]
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill="#111827", outline="#64748b", width=2)
    board.paste(visual_grid, (grid_region["x"], grid_region["y"]))
    draw.rectangle((0, 0, 1600, 100), fill="#172554")
    draw.rectangle((0, 700, 1600, 900), fill="#0f172a")
    _draw_wrapped(draw, f"DIRECTOR BOARD · {segment_id} · {LAYOUT_ID}\n{direction_text}", (28, 18, 1572, 90), size=24, fill="#ffffff", bold=True)
    _draw_wrapped(draw, "CHARACTER / TARGET\n" + character_target_text, (20, 125, 260, 675), size=20, fill="#e2e8f0", bold=True)
    _draw_wrapped(draw, "CAMERA / LIGHT\n" + camera_text, (1340, 125, 1580, 675), size=20, fill="#e2e8f0", bold=True)
    _draw_wrapped(draw, "CONTINUITY / TEXT ROUTE\n" + continuity_text, (28, 725, 1572, 875), size=20, fill="#e2e8f0", bold=True)
    label_font = _font(18, bold=True)
    for cut, card in zip(cuts, card_boxes):
        x0, y0 = int(card["x"]), int(card["y"])
        x1, y1 = x0 + int(card["width"]), y0 + int(card["height"])
        draw.rectangle((x0, y0, x1, y1), outline="#f8fafc", width=3)
        timing = f"{int(cut.get('start_ms') or 0)}-{int(cut.get('end_ms') or 0)}ms"
        label = f"{card['cut_id']} · {timing}"
        draw.rectangle((x0, y0, min(x1, x0 + 260), y0 + 32), fill="#000000")
        draw.text((x0 + 8, y0 + 5), label, font=label_font, fill="#ffffff")

    approval_image_bytes = _png_bytes(board)
    receipt = {
        "schema_version": "usfr-storyboard-layout-receipt/v1",
        "status": "passed",
        "layout_id": LAYOUT_ID,
        "segment_id": str(segment_id),
        "board_width": BOARD_SIZE[0],
        "board_height": BOARD_SIZE[1],
        "regions": {key: dict(value) for key, value in REGIONS.items()},
        "cut_count": len(cut_ids),
        "cut_ids": cut_ids,
        "cut_cards": card_boxes,
        "approval_board_sha256": _sha256(approval_image_bytes),
        "execution_carrier_sha256": _sha256(execution_carrier_bytes),
        "execution_carrier_source": "approved_board.storyboard_grid",
        "execution_carrier_source_roi": dict(REGIONS["storyboard_grid"]),
        "execution_carrier_source_roi_sha256": _sha256(execution_carrier_bytes),
    }
    validate_storyboard_layout_receipt(receipt, expected_cut_ids=cut_ids)
    return {
        "approval_image_bytes": approval_image_bytes,
        "execution_carrier_bytes": execution_carrier_bytes,
        "layout_receipt": receipt,
    }


def validate_storyboard_layout_receipt(
    receipt: Mapping[str, Any] | None,
    *,
    expected_cut_ids: Sequence[str],
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise StoryboardLayoutError("storyboard layout receipt is required")
    if receipt.get("status") != "passed" or receipt.get("layout_id") != LAYOUT_ID:
        raise StoryboardLayoutError("storyboard layout receipt is not passed for the fixed layout")
    regions = receipt.get("regions")
    if not isinstance(regions, Mapping) or set(regions) != set(REQUIRED_REGIONS):
        raise StoryboardLayoutError("storyboard layout receipt is missing fixed regions")
    expected = [str(value) for value in expected_cut_ids]
    cards = receipt.get("cut_cards")
    card_ids = [str(card.get("cut_id") or "") for card in cards] if isinstance(cards, list) else []
    if receipt.get("cut_count") != len(expected) or receipt.get("cut_ids") != expected or card_ids != expected:
        raise StoryboardLayoutError("storyboard layout Cut coverage does not match the approved segment")
    for field in (
        "approval_board_sha256",
        "execution_carrier_sha256",
        "execution_carrier_source_roi_sha256",
    ):
        value = receipt.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise StoryboardLayoutError(f"storyboard layout receipt has invalid {field}")
    if receipt.get("execution_carrier_source") != "approved_board.storyboard_grid":
        raise StoryboardLayoutError("Seedance execution carrier is not bound to the approved storyboard ROI")
    if receipt.get("execution_carrier_source_roi") != regions.get("storyboard_grid"):
        raise StoryboardLayoutError("Seedance execution carrier ROI differs from the approved storyboard grid")
    return dict(receipt)


__all__ = [
    "BOARD_SIZE",
    "LAYOUT_ID",
    "REGIONS",
    "REQUIRED_REGIONS",
    "StoryboardLayoutError",
    "render_director_board",
    "validate_storyboard_layout_receipt",
]
