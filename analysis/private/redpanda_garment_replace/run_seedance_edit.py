from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib import request


CASE_DIR = Path(__file__).resolve().parent
WORKSPACE = Path(r"C:\Users\zhaocx04\Documents\New project")
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
SOURCE_VIDEO = Path(r"C:\Users\zhaocx04\Downloads\redpandacompress_Download - 2026-01-18T022759587.mp4")
GARMENT_ASSET = CASE_DIR / "assets" / "garment" / "01_TARGET_WHITE_LACE_DRESS.png"
GARMENT_MANIFEST = CASE_DIR / "assets" / "garment" / "garment_asset_manifest.json"
APPROVED_SCRIPT = WORKSPACE / "analysis" / "reverse_storyboard_script.md"
DYNAMICS = CASE_DIR / "source_dynamics_analysis.json"
RUN_DIR = CASE_DIR / "seedance_run"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_json(payload: object) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def post_json(url: str, payload: dict) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['RUNNINGHUB_SEEDANCE_API_KEY']}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def uploader():
    sys.path.insert(0, str(SKILL_ROOT))
    from server.production_ports import ProductionEnvironment, RunningHubSeedanceMediaUploader

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
    return RunningHubSeedanceMediaUploader(config)


def compile_prompt() -> dict:
    sys.path.insert(0, str(SKILL_ROOT))
    from scripts.seedance_prompt_compiler import compile_edit_prompt
    from server.packaged_stages import _validate_provider_only_binding_receipt

    manifest = json.loads(GARMENT_MANIFEST.read_text(encoding="utf-8"))
    if sha_file(GARMENT_ASSET) != manifest["board_sha256"]:
        raise RuntimeError("TARGET_GARMENT_ASSET_CHANGED")
    bindings = [{
        "tag": "TARGET_WHITE_LACE_DRESS",
        "reference": "@Image1",
        "role": "garment",
        "asset_type": "garment",
        "replaces_tag": "SRC_WHITE_CORSET_MINI_DRESS",
        "source_object_descriptor": "the white sleeveless fitted mini dress worn by the only woman from the opening frame",
        "replacement_scope": "complete visible garment appearance, material, color and construction",
        "preserve_scope": "wearer identity, hair, jewelry, body motion, fit contact, folds, phone occlusion, lighting, camera and timing",
        "binding_confidence": 0.99,
    }]
    replacements = [{
        "window": "00:00.000-00:14.900",
        "target": "TARGET_WHITE_LACE_DRESS",
        "asset_type": "garment",
        "instruction": "replace the source dress with the approved white floral-lace V-neck dress for the full video",
    }]
    dialogue = [
        {"window": "00:00.000-00:02.000", "speaker": "SRC_WOMAN", "text": "You guys, look what just came in."},
        {"window": "00:02.000-00:04.240", "speaker": "SRC_WOMAN", "text": "I cannot get over this lace dress."},
        {"window": "00:04.240-00:07.240", "speaker": "SRC_WOMAN", "text": "The V neckline and floral lace are so pretty."},
        {"window": "00:07.240-00:09.640", "speaker": "SRC_WOMAN", "text": "I love these flared sleeves and fitted waist."},
        {"window": "00:09.640-00:12.560", "speaker": "SRC_WOMAN", "text": "And look at those layered lace panels."},
        {"window": "00:12.560-00:14.900", "speaker": "SRC_WOMAN", "text": "This is such a pretty party dress."},
    ]
    compiled = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=bindings,
        replacements=replacements,
        dialogue_changes=dialogue,
        approved_speaker_tags=["SRC_WOMAN"],
        segment_window_ms=(0, 14900),
    )
    prompt = compiled["prompt"] + (
        " Render matching English subtitles for each approved dialogue window using the exact quoted dialogue, "
        "one line at a time in the source subtitle area."
    )
    receipt = dict(compiled["provider_only_binding_receipt"])
    receipt["prompt_sha256"] = sha_text(prompt)
    receipt = _validate_provider_only_binding_receipt(receipt, prompt=prompt, image_tags=["@Image1"])
    return {"prompt": prompt, "bindings": bindings, "replacements": replacements, "dialogue": dialogue, "binding_receipt": receipt}


def prepare() -> dict:
    load_env()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    compiled = compile_prompt()
    uploaded_file = RUN_DIR / "uploaded_media.json"
    if uploaded_file.exists():
        uploaded = json.loads(uploaded_file.read_text(encoding="utf-8"))
    else:
        media = uploader()
        uploaded = {
            "imageUrls": [media.upload_media(GARMENT_ASSET)],
            "videoUrls": [media.upload_media(SOURCE_VIDEO)],
            "image_tags": ["@Image1"],
            "image_sha256": [sha_file(GARMENT_ASSET)],
            "video_sha256": sha_file(SOURCE_VIDEO),
        }
        uploaded_file.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if uploaded["image_tags"] != ["@Image1"] or uploaded["image_sha256"] != [sha_file(GARMENT_ASSET)]:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    payload = {
        "prompt": compiled["prompt"],
        "resolution": "720p",
        "duration": "15",
        "imageUrls": uploaded["imageUrls"],
        "videoUrls": uploaded["videoUrls"],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }
    digest = sha_json(payload)
    audit = {
        "schema_version": "usfr-garment-dialogue-provider-only/v1",
        "request_sha256": digest,
        "source_video_sha256": sha_file(SOURCE_VIDEO),
        "approved_script_sha256": sha_file(APPROVED_SCRIPT),
        "source_dynamics_sha256": sha_file(DYNAMICS),
        "binding_contract_sha256": compiled["binding_receipt"]["binding_contract_sha256"],
        "prompt_sha256": sha_text(compiled["prompt"]),
        "image_tag_order": ["@Image1"],
        "source_object_order": ["SRC_WHITE_CORSET_MINI_DRESS"],
        "dialogue_windows": compiled["dialogue"],
        "provider_create_calls_allowed": 1,
    }
    (RUN_DIR / "prompt.txt").write_text(compiled["prompt"] + "\n", encoding="utf-8")
    (RUN_DIR / "provider_only_binding_receipt.json").write_text(json.dumps(compiled["binding_receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "approval_preview.json").write_text(json.dumps({"request_sha256": digest, "approved_script_sha256": audit["approved_script_sha256"]}, indent=2) + "\n", encoding="utf-8")
    return {"status": "PREPARED", **audit}


def submit() -> dict:
    load_env()
    payload = json.loads((RUN_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    audit = json.loads((RUN_DIR / "request_audit.json").read_text(encoding="utf-8"))
    preview = json.loads((RUN_DIR / "approval_preview.json").read_text(encoding="utf-8"))
    digest = sha_json(payload)
    if digest != audit["request_sha256"] or digest != preview["request_sha256"]:
        raise RuntimeError("AUDITED_REQUEST_CHANGED")
    if sha_file(APPROVED_SCRIPT) != preview["approved_script_sha256"]:
        raise RuntimeError("APPROVED_SCRIPT_CHANGED")
    create_file = RUN_DIR / f"create_{digest}.json"
    if create_file.exists():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_file.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("CREATE_RESPONSE_MISSING_TASK_ID")
    (RUN_DIR / "task_id.txt").write_text(task_id + "\n", encoding="utf-8")
    while True:
        status = post_json(os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"], {"taskId": task_id})
        (RUN_DIR / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state = str(status.get("status") or "").upper()
        if state == "SUCCESS":
            video_url = next(row["url"] for row in status["results"] if row.get("outputType") == "mp4")
            with request.urlopen(video_url, timeout=180) as response:
                (RUN_DIR / "result.mp4").write_bytes(response.read())
            return {"status": "SUCCESS", "taskId": task_id, "request_sha256": digest}
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError(f"PROVIDER_{state}")
        time.sleep(10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    if args.prepare == args.submit:
        raise SystemExit("choose exactly one of --prepare or --submit")
    result = prepare() if args.prepare else submit()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
