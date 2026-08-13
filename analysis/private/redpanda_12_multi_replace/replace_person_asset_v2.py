from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


CASE_DIR = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
SOURCE = Path(r"C:\Users\zhaocx04\Downloads\ComfyUI_00002_edckv_1754980342.png")
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
    output = ASSET_DIR / "01_TARGET_WOMAN_V2_IMAGE2.png"
    normalized_path = ASSET_DIR / "01_TARGET_WOMAN_V2_SAFE.png"
    receipt_path = ASSET_DIR / "01_TARGET_WOMAN_V2_IMAGE2.receipt.json"
    if output.exists() or normalized_path.exists() or receipt_path.exists():
        raise RuntimeError("UNCHANGED_V2_PERSON_ALREADY_CREATED")
    load_env()
    sys.path.insert(0, str(SKILL_ROOT))
    from server.runninghub_workflows import RunningHubWorkflowClient
    client = RunningHubWorkflowClient(
        api_key=os.environ["RUNNINGHUB_API_KEY"], base_url=os.environ["RUNNINGHUB_BASE_URL"],
        timeout_seconds=1800, poll_interval_seconds=10,
    )
    result = client.run_image2(
        prompt=(
            "Create one neutral professional upper-body identity portrait of the same clearly adult woman in the reference. "
            "Preserve her facial structure, long dark hair in a low ponytail, eye appearance, pink ribbed mock-neck long-sleeve top, and natural skin appearance. "
            "Exactly one adult person facing camera, arms relaxed below frame, shoulders and upper torso visible, no raised arms, no duplicate face, "
            "no panels, no labels, plain light-gray studio background, even soft lighting."
        ),
        reference_images=[SOURCE], template="model", aspect_ratio="16:9", resolution="2k", quality="medium",
    )
    output.write_bytes(result["image_bytes"])
    receipt_path.write_text(json.dumps(result["receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from PIL import Image, ImageOps
    with Image.open(output) as opened:
        normalized = ImageOps.fit(opened.convert("RGB"), (1024, 1024), method=Image.Resampling.LANCZOS, centering=(0.5, 0.43))
    normalized.save(normalized_path, format="PNG", optimize=True)
    manifest_path = ASSET_DIR / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    person = manifest["assets"][0]
    person.update({
        "source_path": str(SOURCE), "source_sha256": sha(SOURCE), "asset_path": str(normalized_path),
        "asset_sha256": sha(normalized_path), "generated_from_source_sha256": sha(SOURCE),
        "image2_task_id": result["task_id"], "receipt_path": str(receipt_path),
        "person_asset_profile": "model-identity-v3-local-crop", "asset_mime_type": "image/png",
        "asset_width": 1024, "asset_height": 1024, "identity_subject_count": 1,
        "asset_layout": "identity_dominant", "asset_composition": "upper_body_square",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "SUCCESS", "taskId": result["task_id"], "asset": str(normalized_path), "sha256": sha(normalized_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
