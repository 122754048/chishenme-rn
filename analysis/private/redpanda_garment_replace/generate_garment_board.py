from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


CASE_DIR = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
SOURCE_GARMENT = Path(r"C:\Users\zhaocx04\Downloads\img_gmkur.jpeg")
OUTPUT_DIR = CASE_DIR / "assets" / "garment"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT_DIR / "garment_asset_manifest.json"
    if manifest_path.exists():
        raise RuntimeError("UNCHANGED_GARMENT_BOARD_ALREADY_CREATED")
    load_env()
    sys.path.insert(0, str(SKILL_ROOT))
    from server.runninghub_workflows import RunningHubWorkflowClient

    client = RunningHubWorkflowClient(
        api_key=os.environ["RUNNINGHUB_API_KEY"],
        base_url=os.environ["RUNNINGHUB_BASE_URL"],
        timeout_seconds=1800,
        poll_interval_seconds=10,
    )
    source_sha = file_sha(SOURCE_GARMENT)
    binding = {
        "tag": "TARGET_WHITE_LACE_DRESS",
        "asset_type": "garment",
        "path": str(SOURCE_GARMENT),
        "reference_images": [str(SOURCE_GARMENT)],
        "source_asset_sha256": source_sha,
        "source_slot": "new_model_image",
        "source_index": 0,
        "asset_tag": "TARGET_WHITE_LACE_DRESS",
        "image_reference": "@Image1",
        "attraction_constraint": (
            "neutral garment evidence preserving the white floral lace V neckline, "
            "elbow-length flared sleeves, fitted waist, layered lace panels and skirt silhouette"
        ),
    }
    board = client.run_asset_board_batch([binding])[0]
    output_path = OUTPUT_DIR / "01_TARGET_WHITE_LACE_DRESS.png"
    output_path.write_bytes(board["board_bytes"])
    receipt_path = OUTPUT_DIR / "01_TARGET_WHITE_LACE_DRESS.receipt.json"
    receipt_path.write_text(json.dumps(board["receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "contract": "asset-board-manifest/v1",
        "image_index": 1,
        "image_tag": "@Image1",
        "target_tag": board["tag"],
        "asset_type": board["asset_type"],
        "source_asset_sha256": source_sha,
        "board_sha256": board["board_sha256"],
        "board_url": board["board_url"],
        "task_id": board["task_id"],
        "local_path": str(output_path),
        "receipt_path": str(receipt_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "SUCCESS", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
