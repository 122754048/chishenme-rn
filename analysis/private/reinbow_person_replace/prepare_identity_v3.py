from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "identity_v3"

SPECS = [
    ("TARGET_MAN", Path(r"C:\Users\zhaocx04\Downloads\b844d4a9-7eba-4828-a612-271437623587.jpeg"), (0.00, 0.00, 1.00, 0.78)),
    ("TARGET_BLONDE", Path(r"C:\Users\zhaocx04\Downloads\ComfyUI_00001_bitce_1754378835.png"), (0.08, 0.00, 0.92, 0.84)),
    ("TARGET_DARK", Path(r"C:\Users\zhaocx04\Downloads\未命名项目-图层 4.png"), (0.02, 0.00, 0.98, 0.72)),
    ("TARGET_CAT", Path(r"C:\Users\zhaocx04\Downloads\jimeng-2025-08-12-5640-布偶猫蜷在藤编篮中，肉垫轻搭篮边，自然光透过百叶窗形成条纹光影，浅景深背景虚化，....png"), (0.08, 0.18, 0.92, 0.78)),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = []
    previews = []
    for index, (tag, source, fractions) in enumerate(SPECS, start=1):
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        width, height = image.size
        left, top, right, bottom = fractions
        crop = image.crop((int(width * left), int(height * top), int(width * right), int(height * bottom)))
        portrait = ImageOps.fit(crop, (1024, 1024), method=Image.Resampling.LANCZOS, centering=(0.5, 0.46))
        output = OUTPUT / f"{index:02d}_{tag}.png"
        portrait.save(output, format="PNG", optimize=True)
        previews.append(portrait.resize((384, 384), Image.Resampling.LANCZOS))
        rows.append({
            "slot": index,
            "reference": f"@Image{index}",
            "asset_tag": tag,
            "source_path": str(source),
            "identity_path": str(output),
            "sha256": sha256(output),
            "width": 1024,
            "height": 1024,
            "template_version": "model-identity-v3-local-crop",
        })
    contact = Image.new("RGB", (1536, 384), "white")
    for index, preview in enumerate(previews):
        contact.paste(preview, (index * 384, 0))
    contact.save(OUTPUT / "identity_v3_contact.png", format="PNG", optimize=True)
    (OUTPUT / "identity_v3_manifest.json").write_text(
        json.dumps({"schema_version": "usfr-model-identity-v3/v1", "assets": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
