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
PERSON_SOURCE = Path(r"C:\Users\zhaocx04\Downloads\e618bd14b370041408e0c9b729f3edd57aaeb9077707705e2593173c843e8d96.jpg")
PRODUCT_SOURCE = Path(r"C:\Users\zhaocx04\Downloads\DC001.webp")
SCENE_SOURCE = Path(r"C:\Users\zhaocx04\Downloads\3f687f6c48339d1ec17db21e4d9a3af2.jpg")
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

    # The supplied portrait already provides one clear identity and visible upper wardrobe.
    # Deterministic normalization preserves those pixels without generative modification.
    with Image.open(PERSON_SOURCE) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    person = ImageOps.fit(image, (1024, 1024), method=Image.Resampling.LANCZOS, centering=(0.5, 0.42))
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
    bindings = [
        {
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
                "show one Sunquick Orange bottle with orange ribbed cap, orange liquid, curved bottle geometry, "
                "and the exact front label, logo, orange imagery and visible markings from the source image; "
                "all views describe this single bottle"
            ),
        },
        {
            "tag": "TARGET_OPEN_OFFICE",
            "asset_type": "scene",
            "path": str(SCENE_SOURCE),
            "reference_images": [str(SCENE_SOURCE)],
            "source_asset_sha256": sha(SCENE_SOURCE),
            "source_slot": "new_model_image",
            "source_index": 1,
            "asset_tag": "TARGET_OPEN_OFFICE",
            "image_reference": "@Image3",
            "display_logic": (
                "preserve the open-plan office with concrete floor, white desks, office chairs, exposed ceiling ducts, "
                "black pendant lights, distant workstations and daylight from the rear windows; exclude invented branding"
            ),
        },
    ]
    boards = client.run_asset_board_batch(bindings)
    rows = [{
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
        "asset_composition": "upper_body_square",
    }]
    for index, board in enumerate(boards, start=2):
        output = ASSET_DIR / f"{index:02d}_{board['tag']}.png"
        output.write_bytes(board["board_bytes"])
        receipt = ASSET_DIR / f"{index:02d}_{board['tag']}.receipt.json"
        receipt.write_text(json.dumps(board["receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows.append({
            "reference": f"@Image{index}",
            "tag": board["tag"],
            "asset_type": board["asset_type"],
            "source_path": str(bindings[index - 2]["path"]),
            "asset_path": str(output),
            "source_sha256": bindings[index - 2]["source_asset_sha256"],
            "asset_sha256": board["board_sha256"],
            "task_id": board["task_id"],
            "receipt_path": str(receipt),
        })
    manifest_path.write_text(json.dumps({"schema_version": "usfr-multi-asset-manifest/v1", "assets": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "SUCCESS", "assets": rows}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
