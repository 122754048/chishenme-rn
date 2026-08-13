from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


CASE_DIR = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
SOURCE = Path(r"C:\Users\zhaocx04\Downloads\e618bd14b370041408e0c9b729f3edd57aaeb9077707705e2593173c843e8d96.jpg")
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
    output = ASSET_DIR / "01_TARGET_WOMAN_IMAGE2.png"
    receipt_path = ASSET_DIR / "01_TARGET_WOMAN_IMAGE2.receipt.json"
    if output.exists() or receipt_path.exists():
        raise RuntimeError("UNCHANGED_IMAGE2_PERSON_ALREADY_CREATED")
    load_env()
    sys.path.insert(0, str(SKILL_ROOT))
    from server.runninghub_workflows import RunningHubWorkflowClient

    client = RunningHubWorkflowClient(
        api_key=os.environ["RUNNINGHUB_API_KEY"], base_url=os.environ["RUNNINGHUB_BASE_URL"],
        timeout_seconds=1800, poll_interval_seconds=10,
    )
    result = client.run_image2(
        prompt=(
            "Create one neutral, professional upper-body identity portrait of the same adult woman in the reference. "
            "Preserve her facial structure, dark updo, straight bangs, eye appearance, and visible black lace collared top. "
            "Show exactly one adult person, facing camera, arms relaxed below frame, shoulders visible, no raised arms, "
            "no duplicate face, no panels, no labels, plain light-gray studio background, even soft lighting."
        ),
        reference_images=[SOURCE], template="model", aspect_ratio="16:9", resolution="2k", quality="medium",
    )
    output.write_bytes(result["image_bytes"])
    receipt_path.write_text(json.dumps(result["receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = ASSET_DIR / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    person = manifest["assets"][0]
    person.update({
        "asset_path": str(output), "asset_sha256": sha(output), "generated_from_source_sha256": sha(SOURCE),
        "image2_task_id": result["task_id"], "receipt_path": str(receipt_path),
        "person_asset_profile": "model-identity-v3-local-crop", "asset_mime_type": "image/png",
        "asset_width": 2048, "asset_height": 1152, "identity_subject_count": 1,
        "asset_layout": "identity_dominant", "asset_composition": "upper_body_square",
    })
    # Normalize the official Image2 output deterministically to the required 1024-square person contract.
    from PIL import Image, ImageOps
    with Image.open(output) as opened:
        normalized = ImageOps.fit(opened.convert("RGB"), (1024, 1024), method=Image.Resampling.LANCZOS, centering=(0.5, 0.42))
    normalized_path = ASSET_DIR / "01_TARGET_WOMAN_SAFE.png"
    normalized.save(normalized_path, format="PNG", optimize=True)
    person.update({"asset_path": str(normalized_path), "asset_sha256": sha(normalized_path), "asset_width": 1024, "asset_height": 1024})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "SUCCESS", "taskId": result["task_id"], "asset_path": str(normalized_path), "sha256": sha(normalized_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
