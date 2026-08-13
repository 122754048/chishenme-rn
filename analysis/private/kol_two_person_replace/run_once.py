from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib import request

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
SOURCE_VIDEO = Path(r"C:\Users\zhaocx04\Downloads\尝试复刻的真人视频类型（有一定难度）\kol_ceylllln_6706496246289073157.mp4")
TARGETS = (
    ("TARGET_MAN", Path(r"C:\Users\zhaocx04\Downloads\generation-c333f816-8e22-47d7-a52e-7398f9dd183d.png")),
    ("TARGET_WOMAN", Path(r"C:\Users\zhaocx04\Downloads\generation-699a9d18-cc64-4c6c-ab2b-882697ad8c5d.png")),
)
ASSET_DIR = ROOT / "identity_v3"
RUN_DIR = ROOT / "provider_once"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {os.environ['RUNNINGHUB_SEEDANCE_API_KEY']}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def request_sha(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare_assets() -> list[dict]:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (tag, source) in enumerate(TARGETS, start=1):
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        # Source portraits already contain clear face and upper-body wardrobe evidence.
        # Centered square crop preserves that evidence without generative modification.
        portrait = ImageOps.fit(image, (1024, 1024), method=Image.Resampling.LANCZOS, centering=(0.5, 0.38))
        output = ASSET_DIR / f"{index:02d}_{tag}.png"
        portrait.save(output, format="PNG", optimize=True)
        rows.append({
            "slot": index,
            "reference": f"@Image{index}",
            "asset_tag": tag,
            "source_path": str(source),
            "identity_path": str(output),
            "sha256": sha256(output),
            "width": 1024,
            "height": 1024,
            "mime_type": "image/png",
            "person_asset_profile": "model-identity-v3-local-crop",
            "identity_subject_count": 1,
            "asset_layout": "identity_dominant",
            "asset_composition": "upper_body_square",
        })
    (ASSET_DIR / "identity_v3_manifest.json").write_text(
        json.dumps({"schema_version": "usfr-model-identity-v3/v1", "assets": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    load_env()
    sys.path.insert(0, str(SKILL_ROOT))
    from server.production_ports import ProductionEnvironment, RunningHubSeedanceMediaUploader
    from scripts.seedance_prompt_compiler import compile_provider_only_multi_object_prompt

    config = ProductionEnvironment(
        openai_api_key_env="OPENAI_API_KEY",
        capability_secret_env="USFR_CAPABILITY_SECRET",
        openai_base_url="https://unused.invalid",
        openai_model="unused",
        openai_model_config_sha256="0" * 64,
        runninghub_api_key_env="RUNNINGHUB_API_KEY",
        runninghub_base_url=os.environ["RUNNINGHUB_BASE_URL"],
        runninghub_seedance_api_key_env="RUNNINGHUB_SEEDANCE_API_KEY",
        runninghub_seedance_create_url=os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"],
        runninghub_seedance_query_url=os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"],
        runninghub_seedance_upload_url=os.environ["RUNNINGHUB_SEEDANCE_UPLOAD_URL"],
        runninghub_seedance_model_id="seedance-2.0-token",
        runninghub_seedance_config_sha256=os.environ.get("RUNNINGHUB_SEEDANCE_CONFIG_SHA256", "0" * 64),
    )
    uploader = RunningHubSeedanceMediaUploader(config)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    assets = prepare_assets()
    urls_file = RUN_DIR / "uploaded_urls.json"
    if urls_file.exists():
        uploaded = json.loads(urls_file.read_text(encoding="utf-8"))
    else:
        uploaded = {
            "videoUrl": uploader.upload_media(SOURCE_VIDEO),
            "imageUrls": [uploader.upload_media(Path(row["identity_path"])) for row in assets],
        }
        urls_file.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    bindings = [
        {
            "reference": "@Image1",
            "asset_type": "model",
            "target_tag": "TARGET_MAN",
            "source_object_id": "SRC_OPENING_LEFT",
            "source_track_descriptor": "opening-left dark-haired person in a tan faux-fur coat over a white top",
            "replacement_scope": "identity and wardrobe",
            "preserve_scope": "source body track, mouth timing, gaze, expressions, gestures, framing, occlusion and timing",
            "binding_confidence": 0.99,
            "person_asset_profile": "model-identity-v3-local-crop",
            "asset_mime_type": "image/png",
            "asset_width": 1024,
            "asset_height": 1024,
            "identity_subject_count": 1,
            "asset_layout": "identity_dominant",
            "asset_composition": "upper_body_square",
            "wardrobe_policy": "identity_and_wardrobe_from_reference",
            "target_wardrobe_evidence": "visible",
            "target_identity_descriptor": "adult man with short dark hair and trimmed beard, wearing the black short-sleeve crew-neck shirt from @Image1",
        },
        {
            "reference": "@Image2",
            "asset_type": "model",
            "target_tag": "TARGET_WOMAN",
            "source_object_id": "SRC_OPENING_RIGHT",
            "source_track_descriptor": "opening-right long reddish-haired person in a black top, moving partly out through frame-right near the end",
            "replacement_scope": "identity and wardrobe",
            "preserve_scope": "source body track, mouth timing, gaze, expressions, gestures, framing, occlusion and timing",
            "binding_confidence": 0.99,
            "person_asset_profile": "model-identity-v3-local-crop",
            "asset_mime_type": "image/png",
            "asset_width": 1024,
            "asset_height": 1024,
            "identity_subject_count": 1,
            "asset_layout": "identity_dominant",
            "asset_composition": "upper_body_square",
            "wardrobe_policy": "identity_and_wardrobe_from_reference",
            "target_wardrobe_evidence": "visible",
            "target_identity_descriptor": "adult woman with long dark wavy hair, wearing the light fitted top and dark high-waisted skirt from @Image2",
        },
    ]
    compiled = compile_provider_only_multi_object_prompt(source_video="@Video1", bindings=bindings)
    prompt = compiled["prompt"]
    payload = {
        "prompt": prompt,
        "resolution": "720p",
        "duration": "12",
        "imageUrls": uploaded["imageUrls"],
        "videoUrls": [uploaded["videoUrl"]],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }
    digest = request_sha(payload)
    audit = {
        "schema_version": "kol-two-person-provider-once/v1",
        "request_sha256": digest,
        "source_video_sha256": sha256(SOURCE_VIDEO),
        "approved_script_sha256": sha256(ROOT.parent.parent / "reverse_storyboard_script.md"),
        "prompt_sha256": compiled["prompt_sha256"],
        "binding_contract_sha256": compiled["binding_contract_sha256"],
        "provider_only_binding_receipt": compiled["provider_only_binding_receipt"],
        "image_sha256_order": [row["sha256"] for row in assets],
        "subject_order": ["TARGET_MAN", "TARGET_WOMAN"],
        "source_object_order": compiled["source_object_ids"],
    }
    (RUN_DIR / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    (RUN_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert compiled["image_tags"] == ["@Image1", "@Image2"]
    assert len(payload["imageUrls"]) == 2
    assert all(f"Subject {index}:" in prompt and f"@Image{index}" in prompt for index in (1, 2))
    if not args.submit:
        print(json.dumps({"status": "dry_run_pass", **audit}, ensure_ascii=False))
        return 0

    create_file = RUN_DIR / f"create_{digest}.json"
    if create_file.exists():
        raise SystemExit("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_file.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise SystemExit("CREATE_RESPONSE_MISSING_TASK_ID")
    while True:
        status = post_json(os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"], {"taskId": task_id})
        (RUN_DIR / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state = str(status.get("status") or "").upper()
        if state == "SUCCESS":
            video_url = next(row["url"] for row in status["results"] if row.get("outputType") == "mp4")
            with request.urlopen(video_url, timeout=180) as response:
                (RUN_DIR / "result.mp4").write_bytes(response.read())
            print(json.dumps({"status": "SUCCESS", "taskId": task_id, "request_sha256": digest}, ensure_ascii=False))
            return 0
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise SystemExit(f"PROVIDER_{state}")
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
