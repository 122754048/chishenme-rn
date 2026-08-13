from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

from PIL import Image, ImageOps


CASE_DIR = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
PERSON_SOURCE = Path(r"C:\Users\zhaocx04\Downloads\8648a9162d0cc6c75565505e4a1d56a5961ae5ecc976aef3ea088e5a2b246510.png")
PRODUCT_SOURCE = Path(r"C:\Users\zhaocx04\Downloads\DC001.webp")
ASSET_DIR = CASE_DIR / "assets"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest_path = ASSET_DIR / "asset_manifest.json"
    if manifest_path.exists():
        raise RuntimeError("UNCHANGED_ASSETS_ALREADY_CREATED")
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    with Image.open(PERSON_SOURCE) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    # Preserve the clear face, white top, jewelry, and visible gray lower wardrobe.
    person = ImageOps.fit(image, (1024, 1024), method=Image.Resampling.LANCZOS, centering=(0.5, 0.48))
    person_path = ASSET_DIR / "01_TARGET_WOMAN.png"
    person.save(person_path, format="PNG", optimize=True)

    load_env()
    sys.path.insert(0, str(SKILL_ROOT))
    from server.runninghub_workflows import RunningHubWorkflowClient

    client = RunningHubWorkflowClient(
        api_key=os.environ["RUNNINGHUB_API_KEY"],
        base_url=os.environ["RUNNINGHUB_BASE_URL"],
        timeout_seconds=1800,
        poll_interval_seconds=10,
    )
    binding = {
        "tag": "TARGET_SUNQUICK_ORANGE",
        "asset_type": "product",
        "path": str(PRODUCT_SOURCE),
        "reference_images": [str(PRODUCT_SOURCE)],
        "source_asset_sha256": sha(PRODUCT_SOURCE),
        "source_slot": "new_product_image",
        "source_index": 0,
        "asset_tag": "TARGET_SUNQUICK_ORANGE",
        "image_reference": "@Image2",
        "display_logic": (
            "show one SUNQUICK Oren Orange bottle only; preserve the orange ribbed screw cap, orange liquid, "
            "curved textured bottle geometry, exact SUNQUICK logo, Oren Orange wording, orange imagery, "
            "front label and proportions from the supplied reference; provide clean front, side, cap, base and label detail views"
        ),
    }
    board = client.run_asset_board_batch([binding])[0]
    product_path = ASSET_DIR / "02_TARGET_SUNQUICK_ORANGE.png"
    product_path.write_bytes(board["board_bytes"])
    receipt_path = ASSET_DIR / "02_TARGET_SUNQUICK_ORANGE.receipt.json"
    receipt_path.write_text(json.dumps(board["receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = [
        {
            "reference": "@Image1",
            "tag": "TARGET_WOMAN",
            "asset_type": "model",
            "source_path": str(PERSON_SOURCE),
            "asset_path": str(person_path),
            "source_sha256": sha(PERSON_SOURCE),
            "asset_sha256": sha(person_path),
            "person_asset_profile": "model-identity-v3-local-crop",
            "asset_mime_type": "image/png",
            "asset_width": 1024,
            "asset_height": 1024,
            "identity_subject_count": 1,
            "asset_layout": "identity_dominant",
            "asset_composition": "full_body_square",
        },
        {
            "reference": "@Image2",
            "tag": "TARGET_SUNQUICK_ORANGE",
            "asset_type": "product",
            "source_path": str(PRODUCT_SOURCE),
            "asset_path": str(product_path),
            "source_sha256": sha(PRODUCT_SOURCE),
            "asset_sha256": board["board_sha256"],
            "task_id": board["task_id"],
            "receipt_path": str(receipt_path),
        },
    ]
    manifest_path.write_text(json.dumps({"schema_version": "usfr-multi-asset-manifest/v1", "assets": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "SUCCESS", "assets": rows}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
