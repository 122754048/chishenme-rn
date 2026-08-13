from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


RUN_DIR = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
SOURCE_IMAGES = [
    Path(r"C:\Users\zhaocx04\Downloads\8648a9162d0cc6c75565505e4a1d56a5961ae5ecc976aef3ea088e5a2b246510.png"),
    Path(r"C:\Users\zhaocx04\Downloads\Batch_00004_myhhx_1768465153.png"),
]


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
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
            "tag": "TARGET_WOMAN_MODEL",
            "asset_type": "model",
            "path": str(SOURCE_IMAGES[0]),
            "reference_images": [str(SOURCE_IMAGES[0])],
            "source_asset_sha256": file_sha(SOURCE_IMAGES[0]),
            "source_slot": "new_model_image",
            "source_index": 0,
            "asset_tag": "TARGET_WOMAN_MODEL",
            "image_reference": "@Image1",
            "attraction_constraint": "faithful identity evidence with the visible white top and jewelry preserved exactly",
        },
        {
            "tag": "TARGET_MAN_MODEL",
            "asset_type": "model",
            "path": str(SOURCE_IMAGES[1]),
            "reference_images": [str(SOURCE_IMAGES[1])],
            "source_asset_sha256": file_sha(SOURCE_IMAGES[1]),
            "source_slot": "new_model_image",
            "source_index": 1,
            "asset_tag": "TARGET_MAN_MODEL",
            "image_reference": "@Image2",
            "attraction_constraint": "faithful identity evidence with the visible white T-shirt, silver chain, white sunglasses, and spiked hair preserved exactly",
        },
    ]
    boards = client.run_asset_board_batch(bindings)
    output_dir = RUN_DIR / "asset_boards"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for index, board in enumerate(boards, start=1):
        path = output_dir / f"Image{index}_{board['tag']}.png"
        path.write_bytes(board["board_bytes"])
        receipt_path = output_dir / f"Image{index}_{board['tag']}.receipt.json"
        receipt_path.write_text(json.dumps(board["receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_rows.append(
            {
                "image_index": index,
                "image_tag": f"@Image{index}",
                "target_tag": board["tag"],
                "asset_type": board["asset_type"],
                "source_asset_sha256": bindings[index - 1]["source_asset_sha256"],
                "board_sha256": board["board_sha256"],
                "board_url": board["board_url"],
                "task_id": board["task_id"],
                "local_path": str(path),
                "receipt_path": str(receipt_path),
            }
        )
    manifest = {
        "contract": "asset-board-manifest/v1",
        "approved_script_sha256": "af05f154e4e5822f758e9cba794858b7fbe9d5ee66b5ea27464210182fea7954",
        "uploaded_tags": ["@Image1", "@Image2"],
        "binding_tags": ["@Image1", "@Image2"],
        "prompt_tags": ["@Image1", "@Image2"],
        "assets": manifest_rows,
    }
    (output_dir / "asset_board_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "SUCCESS", "boards": manifest_rows}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
