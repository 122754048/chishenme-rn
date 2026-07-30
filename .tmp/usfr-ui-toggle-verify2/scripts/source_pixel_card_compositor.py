"""Place exact source-pixel evidence cards onto a generated storyboard or control sheet."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _card_rect(value: Any, *, width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or len(value) != 4:
        raise ValueError("card rect must contain x,y,width,height")
    if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        raise ValueError("card rect must contain integers")
    x, y, card_width, card_height = value
    if x < 0 or y < 0 or card_width < 1 or card_height < 1 or x + card_width > width or y + card_height > height:
        raise ValueError("card rect must be fully inside the base image")
    return x, y, card_width, card_height


def _fit_source(source: Image.Image, *, width: int, height: int, fit: str) -> Image.Image:
    if fit not in {"contain", "cover"}:
        raise ValueError("card fit must be contain or cover")
    scale = min(width / source.width, height / source.height) if fit == "contain" else max(width / source.width, height / source.height)
    resized = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    if fit == "cover":
        left = (resized.width - width) // 2
        top = (resized.height - height) // 2
        return resized.crop((left, top, left + width, top + height))
    card = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    card.alpha_composite(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
    return card


def _outside_card_rect_changed_pixels(before: Image.Image, after: Image.Image, rects: Sequence[tuple[int, int, int, int]]) -> int:
    before_pixels = before.convert("RGB").load()
    after_pixels = after.convert("RGB").load()
    changed = 0
    for y in range(before.height):
        for x in range(before.width):
            if any(left <= x < left + width and top <= y < top + height for left, top, width, height in rects):
                continue
            if before_pixels[x, y] != after_pixels[x, y]:
                changed += 1
    return changed


def composite_source_pixel_cards(
    *,
    base_path: Path,
    output_path: Path,
    cards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create one review image whose declared UI cards are direct source pixels."""
    base_path = Path(base_path)
    output_path = Path(output_path)
    base = Image.open(base_path).convert("RGBA")
    rendered = base.copy()
    rendered_cards: list[dict[str, Any]] = []
    rects: list[tuple[int, int, int, int]] = []
    for index, raw_card in enumerate(cards):
        if not isinstance(raw_card, Mapping):
            raise ValueError(f"card {index} must be an object")
        cut_id = raw_card.get("cut_id")
        if not isinstance(cut_id, str) or not cut_id:
            raise ValueError(f"card {index} must declare cut_id")
        source_path_value = raw_card.get("source_path")
        if not isinstance(source_path_value, str) or not source_path_value:
            raise ValueError(f"card {cut_id} must declare source_path")
        source_path = Path(source_path_value)
        rect = _card_rect(raw_card.get("rect"), width=base.width, height=base.height)
        if any(_rectangles_overlap(rect, previous) for previous in rects):
            raise ValueError("source-pixel card rects cannot overlap")
        source = Image.open(source_path).convert("RGBA")
        fit = str(raw_card.get("fit") or "contain")
        rendered.alpha_composite(_fit_source(source, width=rect[2], height=rect[3], fit=fit), (rect[0], rect[1]))
        rects.append(rect)
        rendered_cards.append(
            {
                "cut_id": cut_id,
                "source_path": str(source_path),
                "source_sha256": _sha256(source_path),
                "rect": list(rect),
                "fit": fit,
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered.convert("RGB").save(output_path, format="PNG")
    outside_changed = _outside_card_rect_changed_pixels(base, rendered, rects)
    if outside_changed:
        raise RuntimeError("source-pixel card composition changed pixels outside declared card rects")
    return {
        "schema_version": "usfr-source-pixel-cards/v1",
        "base_path": str(base_path),
        "base_sha256": _sha256(base_path),
        "output_path": str(output_path),
        "output_sha256": _sha256(output_path),
        "cards": rendered_cards,
        "outside_card_rect_changed_pixels": outside_changed,
    }


def _rectangles_overlap(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    left_a, top_a, width_a, height_a = first
    left_b, top_b, width_b, height_b = second
    return left_a < left_b + width_b and left_b < left_a + width_a and top_a < top_b + height_b and top_b < top_a + height_a


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose source-pixel UI cards into a review image.")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--cards-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    loaded = json.loads(args.cards_file.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, Mapping) or not isinstance(loaded.get("cards"), list):
        raise ValueError("cards file must contain a cards array")
    receipt = composite_source_pixel_cards(base_path=args.base, output_path=args.output, cards=loaded["cards"])
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
