from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


CANVAS_SIZE = (1080, 1920)
PORTRAIT_SIZE = 280
FONT_PATHS = (
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
)
BINDINGS = (
    {
        "filename": "02_TARGET_BLONDE.png",
        "target_tag": "TARGET_BLONDE",
        "source_object_id": "SRC_BLONDE",
        "locator": "first-frame left",
        "xy": (45, 250),
        "color": (226, 174, 74),
    },
    {
        "filename": "01_TARGET_MAN.png",
        "target_tag": "TARGET_MAN",
        "source_object_id": "SRC_MAN",
        "locator": "first-frame center",
        "xy": (400, 250),
        "color": (73, 135, 220),
    },
    {
        "filename": "03_TARGET_DARK.png",
        "target_tag": "TARGET_DARK",
        "source_object_id": "SRC_DARK",
        "locator": "first-frame right",
        "xy": (755, 250),
        "color": (164, 100, 201),
    },
    {
        "filename": "04_TARGET_CAT.png",
        "target_tag": "TARGET_CAT",
        "source_object_id": "SRC_ALIEN",
        "locator": "enters from left at 3.15s",
        "xy": (45, 1110),
        "color": (74, 174, 157),
    },
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_PATHS:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _square_portrait(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGB")
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    return image.resize((PORTRAIT_SIZE, PORTRAIT_SIZE), Image.Resampling.LANCZOS)


def build_board(identity_dir: Path, output_path: Path) -> dict[str, Any]:
    identity_dir = Path(identity_dir)
    output_path = Path(output_path)
    canvas = Image.new("RGB", CANVAS_SIZE, (236, 236, 232))
    draw = ImageDraw.Draw(canvas)
    title_font = _font(42)
    tag_font = _font(30)
    detail_font = _font(23)

    draw.text((45, 55), "SPATIAL IDENTITY BINDING MAP", fill=(20, 20, 20), font=title_font)
    draw.text((45, 115), "MAPPING ONLY — @Image1..4 remain identity authorities", fill=(65, 65, 65), font=detail_font)
    draw.rounded_rectangle((35, 190, 1045, 760), radius=24, outline=(110, 110, 105), width=4)
    draw.text((45, 805), "LATER ENTRANT", fill=(20, 20, 20), font=tag_font)
    draw.rounded_rectangle((35, 865, 390, 1690), radius=24, outline=(110, 110, 105), width=4)

    manifest_bindings: list[dict[str, str]] = []
    for item in BINDINGS:
        source_path = identity_dir / str(item["filename"])
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        x, y = item["xy"]
        color = item["color"]
        portrait = _square_portrait(source_path)
        canvas.paste(portrait, (x, y))
        draw.rectangle((x - 5, y - 5, x + PORTRAIT_SIZE + 5, y + PORTRAIT_SIZE + 5), outline=color, width=10)
        draw.text((x, y + 305), str(item["target_tag"]), fill=(15, 15, 15), font=tag_font)
        draw.text((x, y + 350), f"replaces {item['source_object_id']}", fill=color, font=detail_font)
        draw.text((x, y + 390), str(item["locator"]), fill=(60, 60, 60), font=detail_font)
        manifest_bindings.append({
            "target_tag": str(item["target_tag"]),
            "source_object_id": str(item["source_object_id"]),
            "locator": str(item["locator"]),
        })

    draw.text((45, 1775), "Do not transfer background, wardrobe, pose, camera, motion or style from this board.", fill=(45, 45, 45), font=detail_font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=False, compress_level=9)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    manifest: dict[str, Any] = {
        "schema_version": "reinbow-spatial-binding-board/v1",
        "width": CANVAS_SIZE[0],
        "height": CANVAS_SIZE[1],
        "sha256": digest,
        "bindings": manifest_bindings,
    }
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    result = build_board(root / "identity_v3", root / "spatial_binding_board_v1.png")
    print(json.dumps(result, ensure_ascii=False))

