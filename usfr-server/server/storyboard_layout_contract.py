"""Mandatory daohuo-template director-board renderer and publication gate."""

from __future__ import annotations

import hashlib
import io
import math
import re
from typing import Any, Mapping, Sequence


LAYOUT_ID = "usfr-cinematic-director-production-board/v1"
TEMPLATE_PATH = "bundled-skills/seedance-storyboard-replication/references/daohuo_storyboard_prompt.md"
BOARD_SIZE = (2048, 1152)
REQUIRED_TEMPLATE_ANCHORS = (
    "Use case: infographic-diagram",
    "Asset type: 16:9 cinematic pre-production storyboard",
    "Fixed layout:",
    "- Top: shared creative direction",
    "- Left: CHARACTER section",
    "- Center: STORYBOARD section",
    "- Right: TARGET EVIDENCE section",
    "- Bottom: large short labels for lighting, camera, palette, audio/tone, mood keywords, and cinematography notes.",
)
REQUIRED_REGIONS = (
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
)
REGIONS = {
    "creative_header": {"x": 0, "y": 0, "width": 2048, "height": 150},
    "character_reference": {"x": 0, "y": 150, "width": 340, "height": 390},
    "face_hair_reference": {"x": 0, "y": 540, "width": 340, "height": 220},
    "wardrobe_style": {"x": 0, "y": 760, "width": 340, "height": 190},
    "storyboard_grid": {"x": 340, "y": 150, "width": 1340, "height": 800},
    "target_evidence": {"x": 1680, "y": 150, "width": 368, "height": 330},
    "camera_movement_diagram": {"x": 1680, "y": 480, "width": 368, "height": 470},
    "lighting": {"x": 0, "y": 950, "width": 350, "height": 202},
    "camera": {"x": 350, "y": 950, "width": 350, "height": 202},
    "palette": {"x": 700, "y": 950, "width": 320, "height": 202},
    "audio_tone": {"x": 1020, "y": 950, "width": 350, "height": 202},
    "mood": {"x": 1370, "y": 950, "width": 300, "height": 202},
    "cinematography_notes": {"x": 1670, "y": 950, "width": 378, "height": 202},
}


class StoryboardLayoutError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_bytes(image: Any) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def _decode_image(payload: bytes | None, label: str) -> Any | None:
    if payload is None:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as opened:
            return opened.convert("RGB")
    except Exception as exc:
        raise StoryboardLayoutError(f"{label} is not a decodable image") from exc


def _validate_template(template_bytes: bytes | None) -> tuple[str, str]:
    if not isinstance(template_bytes, bytes) or not template_bytes:
        raise StoryboardLayoutError("daohuo_storyboard_prompt.md is a mandatory director-board dependency")
    try:
        text = template_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise StoryboardLayoutError("daohuo storyboard template contract must be UTF-8") from exc
    missing = [anchor for anchor in REQUIRED_TEMPLATE_ANCHORS if anchor not in text]
    if missing:
        raise StoryboardLayoutError("daohuo storyboard template contract is incomplete: " + ", ".join(missing))
    return text, _sha256(template_bytes)


def compile_daohuo_storyboard_prompt(
    *, template_bytes: bytes | None, values: Mapping[str, Any]
) -> dict[str, str]:
    """Compile the provider prompt only from the mandatory fenced template."""

    text, template_sha256 = _validate_template(template_bytes)
    match = re.search(r"```text\s*\n(Use case: infographic-diagram[\s\S]*?)\n```", text)
    if match is None:
        raise StoryboardLayoutError("daohuo storyboard template contract has no provider prompt block")
    prompt = match.group(1)

    def replace(match_value: re.Match[str]) -> str:
        key = match_value.group(1)
        if key not in values:
            raise StoryboardLayoutError(f"daohuo storyboard template value is missing: {key}")
        value = str(values[key]).strip()
        if not value:
            raise StoryboardLayoutError(f"daohuo storyboard template value is empty: {key}")
        return value

    prompt = re.sub(r"\{\{([A-Z0-9_]+)\}\}", replace, prompt)
    if "{{" in prompt or "}}" in prompt:
        raise StoryboardLayoutError("daohuo storyboard template contains unresolved placeholders")
    return {"prompt": prompt, "template_sha256": template_sha256, "template_path": TEMPLATE_PATH}


def render_director_board(
    *,
    visual_sheet_bytes: bytes,
    template_bytes: bytes | None,
    segment_id: str,
    cuts: Sequence[Mapping[str, Any]],
    direction_text: str,
    character_target_text: str,
    camera_text: str,
    continuity_text: str,
    character_reference_bytes: bytes | None = None,
    target_evidence_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Render the one template-bound approval board and a labels-free carrier."""

    _template_text, template_sha256 = _validate_template(template_bytes)
    if not cuts:
        raise StoryboardLayoutError("director board requires at least one Cut")
    cut_ids = [str(cut.get("cut_id") or "").strip() for cut in cuts]
    if any(not cut_id for cut_id in cut_ids) or len(set(cut_ids)) != len(cut_ids):
        raise StoryboardLayoutError("director board Cut IDs must be non-empty and unique")

    visual_sheet = _decode_image(visual_sheet_bytes, "director board visual sheet")
    assert visual_sheet is not None
    _decode_image(character_reference_bytes, "character reference")
    _decode_image(target_evidence_bytes, "target evidence")
    if visual_sheet.width * 9 != visual_sheet.height * 16:
        raise StoryboardLayoutError("template-generated Image2 director board must be exactly 16:9")

    # Image2 owns the complete board defined by daohuo_storyboard_prompt.md.
    # The server must never replace that approved artifact with a remembered
    # generic layout. It only records expected Cut-card geometry and derives a
    # separately hashed storyboard visual carrier from the center region.
    grid = REGIONS["storyboard_grid"]
    gx, gy, gw, gh = grid["x"], grid["y"], grid["width"], grid["height"]
    columns = len(cuts) if len(cuts) <= 7 else math.ceil(len(cuts) / 2)
    rows = math.ceil(len(cuts) / columns)
    gap = 8
    top = gy + 58
    cell_width = (gw - gap * (columns + 1)) // columns
    cell_height = (gh - 66 - gap * (rows + 1)) // rows
    card_boxes: list[dict[str, Any]] = []
    for index, cut in enumerate(cuts):
        column, row = index % columns, index // columns
        x = gx + gap + column * (cell_width + gap)
        y = top + gap + row * (cell_height + gap)
        card_boxes.append({"cut_id": cut_ids[index], "x": x, "y": y, "width": cell_width, "height": cell_height})

    approval_image_bytes = visual_sheet_bytes
    scale_x = visual_sheet.width / BOARD_SIZE[0]
    scale_y = visual_sheet.height / BOARD_SIZE[1]
    roi = (
        round(gx * scale_x),
        round(gy * scale_y),
        round((gx + gw) * scale_x),
        round((gy + gh) * scale_y),
    )
    execution_carrier_bytes = _png_bytes(visual_sheet.crop(roi))
    receipt = {
        "schema_version": "usfr-storyboard-layout-receipt/v2",
        "status": "passed",
        "layout_id": LAYOUT_ID,
        "template_path": TEMPLATE_PATH,
        "template_sha256": template_sha256,
        "template_anchors": list(REQUIRED_TEMPLATE_ANCHORS),
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
        "direction_text_sha256": _sha256(str(direction_text).encode("utf-8")),
        "character_target_text_sha256": _sha256(str(character_target_text).encode("utf-8")),
        "camera_text_sha256": _sha256(str(camera_text).encode("utf-8")),
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
        raise StoryboardLayoutError("storyboard layout receipt is not passed for the mandatory daohuo layout")
    if receipt.get("template_path") != TEMPLATE_PATH:
        raise StoryboardLayoutError("storyboard layout receipt is not bound to daohuo_storyboard_prompt.md")
    template_sha = receipt.get("template_sha256")
    if not isinstance(template_sha, str) or len(template_sha) != 64 or any(ch not in "0123456789abcdef" for ch in template_sha):
        raise StoryboardLayoutError("storyboard layout receipt has invalid template SHA-256")
    if receipt.get("template_anchors") != list(REQUIRED_TEMPLATE_ANCHORS):
        raise StoryboardLayoutError("storyboard layout receipt does not prove the complete daohuo template contract")
    if int(receipt.get("board_width") or 0) * 9 != int(receipt.get("board_height") or 0) * 16:
        raise StoryboardLayoutError("director board must be exactly 16:9")
    regions = receipt.get("regions")
    if not isinstance(regions, Mapping) or set(regions) != set(REQUIRED_REGIONS):
        raise StoryboardLayoutError("storyboard layout receipt is missing fixed regions")
    expected = [str(value) for value in expected_cut_ids]
    cards = receipt.get("cut_cards")
    card_ids = [str(card.get("cut_id") or "") for card in cards] if isinstance(cards, list) else []
    if receipt.get("cut_count") != len(expected) or receipt.get("cut_ids") != expected or card_ids != expected:
        raise StoryboardLayoutError("storyboard layout Cut coverage does not match the approved segment")
    for field in ("approval_board_sha256", "execution_carrier_sha256", "execution_carrier_source_roi_sha256"):
        value = receipt.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise StoryboardLayoutError(f"storyboard layout receipt has invalid {field}")
    if receipt.get("approval_board_sha256") == receipt.get("execution_carrier_sha256"):
        raise StoryboardLayoutError("approval board and Seedance execution carrier must be distinct")
    if receipt.get("execution_carrier_source") != "approved_board.storyboard_grid":
        raise StoryboardLayoutError("Seedance execution carrier is not bound to the approved storyboard grid")
    if receipt.get("execution_carrier_source_roi") != regions.get("storyboard_grid"):
        raise StoryboardLayoutError("Seedance execution carrier ROI differs from the approved storyboard grid")
    return dict(receipt)


__all__ = [
    "BOARD_SIZE",
    "LAYOUT_ID",
    "REGIONS",
    "REQUIRED_REGIONS",
    "REQUIRED_TEMPLATE_ANCHORS",
    "TEMPLATE_PATH",
    "StoryboardLayoutError",
    "compile_daohuo_storyboard_prompt",
    "render_director_board",
    "validate_storyboard_layout_receipt",
]
