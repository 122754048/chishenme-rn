from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib import request

from PIL import Image


RUN_DIR = Path(__file__).resolve().parent
PROJECT_DIR = RUN_DIR.parent
ASSET_DIR = PROJECT_DIR / "canonical_person_assets"
ASSET_MANIFEST = ASSET_DIR / "person_asset_manifest.json"
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
VIDEO_URL = "https://rh-hk-images-switch.xiaoyaoyou.com/input/openapi/096232caa5fdb33d7c12d5b5594560e153b482197e643ba25ad0423387e5eee0.mp4"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def post_json(url: str, payload: dict) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['RUNNINGHUB_SEEDANCE_API_KEY']}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def upload_file(path: Path) -> str:
    script_dir = SKILL_ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
    sys.path.insert(0, str(script_dir))
    from runninghub_seedance_submit import RunningHubStandardSeedanceClient

    client = RunningHubStandardSeedanceClient(
        os.environ["RUNNINGHUB_SEEDANCE_API_KEY"],
        create_url=os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"],
        query_url=os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"],
        upload_url=os.environ["RUNNINGHUB_SEEDANCE_UPLOAD_URL"],
    )
    return client.upload_file(path)


def compile_authority() -> tuple[dict, dict]:
    sys.path.insert(0, str(SKILL_ROOT))
    from scripts.seedance_prompt_compiler import compile_provider_only_multi_object_prompt

    manifest = json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "usfr-person-asset-manifest/v1" or len(manifest.get("assets", [])) != 2:
        raise RuntimeError("PERSON_ASSET_FORMAT_REQUIRED")
    rows = manifest["assets"]
    for index, row in enumerate(rows, start=1):
        path = Path(row["identity_path"])
        with Image.open(path) as opened:
            if opened.format != "PNG" or opened.size != (1024, 1024):
                raise RuntimeError("PERSON_ASSET_FORMAT_REQUIRED")
        if (
            row.get("reference") != f"@Image{index}"
            or row.get("person_asset_profile") != "model-identity-v3-local-crop"
            or row.get("asset_layout") != "identity_dominant"
            or row.get("identity_subject_count") != 1
            or sha256_file(path) != row.get("sha256")
        ):
            raise RuntimeError("PERSON_ASSET_FORMAT_REQUIRED")
    common = {
        "person_asset_profile": "model-identity-v3-local-crop",
        "asset_mime_type": "image/png",
        "asset_width": 1024,
        "asset_height": 1024,
        "identity_subject_count": 1,
        "asset_layout": "identity_dominant",
        "asset_composition": "upper_body_square",
    }
    bindings = [
        {
            **common,
            "reference": "@Image1",
            "asset_type": "model",
            "target_tag": "TARGET_WOMAN",
            "source_object_id": "SRC_WOMAN",
            "source_track_descriptor": "opening center-right woman holding her phone in the street interview",
            "replacement_scope": "person identity, face, hair, skin, and visible wardrobe",
            "preserve_scope": "source body motion, expressions, gaze, gestures, phone contact, perspective, lighting, occlusion, background, text, audio, and timing",
            "binding_confidence": 0.98,
            "wardrobe_policy": "identity_and_wardrobe_from_reference",
            "target_wardrobe_evidence": "visible",
            "target_identity_descriptor": "blue-gray-eyed brunette with long dark-brown hair, white ribbed long-sleeve cropped top, gray high-waisted fitted leggings, necklace, and rings",
        },
        {
            **common,
            "reference": "@Image2",
            "asset_type": "model",
            "target_tag": "TARGET_MAN",
            "source_object_id": "SRC_MAN",
            "source_track_descriptor": "opening frame-left male interviewer holding the microphone",
            "replacement_scope": "person identity, face, hair, skin, and visible upper wardrobe",
            "preserve_scope": "source lower-body light shorts, body motion, microphone contact, expressions, gaze, gestures, perspective, lighting, occlusion, background, text, audio, and timing",
            "binding_confidence": 0.98,
            "wardrobe_policy": "identity_and_wardrobe_from_reference",
            "target_wardrobe_evidence": "visible",
            "target_identity_descriptor": "Black man with spiked black hair and orange center patch, white wraparound sunglasses on his forehead, diamond studs, thick silver chain, and oversized white T-shirt; the source light shorts remain",
        },
    ]
    compiled = compile_provider_only_multi_object_prompt(source_video="@Video1", bindings=bindings)
    return compiled, manifest


def prepare() -> dict:
    load_env()
    compiled, manifest = compile_authority()
    asset_paths = [Path(row["identity_path"]) for row in manifest["assets"]]
    image_urls = [upload_file(path) for path in asset_paths]
    payload = {
        "prompt": compiled["prompt"],
        "resolution": "720p",
        "duration": "15",
        "imageUrls": image_urls,
        "videoUrls": [VIDEO_URL],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }
    digest = sha_json(payload)
    (RUN_DIR / "prompt.txt").write_text(compiled["prompt"] + "\n", encoding="utf-8")
    (RUN_DIR / "provider_only_binding_receipt.json").write_text(json.dumps(compiled["provider_only_binding_receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {
        "schema_version": "usfr-provider-only-request-audit/v1",
        "request_sha256": digest,
        "provider_only": True,
        "provider_create_calls_allowed": 1,
        "primary_change_variable": "canonical_1024_square_person_assets",
        "image_tag_order": compiled["image_tags"],
        "source_object_order": compiled["source_object_ids"],
        "person_asset_profile": "model-identity-v3-local-crop",
        "image_sha256_order": [row["sha256"] for row in manifest["assets"]],
        "image_url_count": 2,
        "video_url_count": 1,
        "binding_board_uploaded": False,
        "local_final_video_processing": False,
        "prompt_sha256": compiled["prompt_sha256"],
        "binding_contract_sha256": compiled["binding_contract_sha256"],
        "prompt_chars": len(compiled["prompt"]),
    }
    (RUN_DIR / "request_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "approval_preview.json").write_text(json.dumps({"request_sha256": digest}, indent=2) + "\n", encoding="utf-8")
    return {"status": "prepared", "request_sha256": digest, "prompt_chars": len(compiled["prompt"])}


def query(task_id: str) -> dict:
    status = post_json(os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"], {"taskId": task_id})
    (RUN_DIR / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = str(status.get("status") or "").upper()
    if state == "SUCCESS":
        url = next(row["url"] for row in status["results"] if row.get("outputType") == "mp4")
        with request.urlopen(url, timeout=180) as response:
            (RUN_DIR / "result.mp4").write_bytes(response.read())
    return {"taskId": task_id, "status": state}


def submit() -> dict:
    load_env()
    compile_authority()
    payload = json.loads((RUN_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    digest = sha_json(payload)
    preview = json.loads((RUN_DIR / "approval_preview.json").read_text(encoding="utf-8"))
    if digest != preview.get("request_sha256"):
        raise RuntimeError("AUDITED_REQUEST_CHANGED")
    create_path = RUN_DIR / f"create_{digest}.json"
    task_path = RUN_DIR / "task_id.txt"
    if create_path.exists() or task_path.exists():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_path.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("CREATE_RESPONSE_MISSING_TASK_ID")
    task_path.write_text(task_id, encoding="utf-8")
    while True:
        result = query(task_id)
        if result["status"] == "SUCCESS":
            return {**result, "request_sha256": digest}
        if result["status"] in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError(f"PROVIDER_{result['status']}")
        time.sleep(10)


def resume() -> dict:
    load_env()
    return query((RUN_DIR / "task_id.txt").read_text(encoding="utf-8").strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "submit", "resume"))
    args = parser.parse_args()
    result = prepare() if args.mode == "prepare" else submit() if args.mode == "submit" else resume()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
