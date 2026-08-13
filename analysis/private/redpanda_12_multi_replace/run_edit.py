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
SOURCE_VIDEO = Path(r"C:\Users\zhaocx04\Downloads\redpandacompress_12.mp4")
ASSET_DIR = CASE_DIR / "assets"
MANIFEST = ASSET_DIR / "asset_manifest.json"
SCRIPT = WORKSPACE / "analysis" / "reverse_storyboard_script.md"
DYNAMICS = CASE_DIR / "source_dynamics_analysis.json"
PASS1_DIR = CASE_DIR / "pass1_person_dialogue"
PASS2_DIR = CASE_DIR / "pass2_product_scene"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


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


def make_uploader():
    sys.path.insert(0, str(SKILL_ROOT))
    from server.production_ports import ProductionEnvironment, RunningHubSeedanceMediaUploader
    return RunningHubSeedanceMediaUploader(ProductionEnvironment(
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
    ))


def compile_authority() -> dict:
    sys.path.insert(0, str(SKILL_ROOT))
    from scripts.seedance_prompt_compiler import compile_edit_prompt, compile_provider_only_multi_object_prompt

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["assets"]
    by_tag = {row["tag"]: row for row in manifest}
    person = by_tag["TARGET_WOMAN"]
    full_bindings = [
        {
            "tag": "TARGET_WOMAN", "reference": "@Image1", "role": "model", "asset_type": "model",
            "replaces_tag": "SRC_PRESENTER",
            "source_object_descriptor": "the only opening-center seated male presenter with wavy dark hair, blue striped overshirt and white sleeves",
            "target_identity_descriptor": "adult woman with long dark hair in a low ponytail and the visible pink ribbed mock-neck long-sleeve top from @Image1",
            "replacement_scope": "person identity, hair and visible upper wardrobe",
            "preserve_scope": "source seated body track, mouth timing, gaze, gestures, hand contacts, microphone relationship, blocking, occlusion and timing",
            "binding_confidence": 0.99,
            "wardrobe_policy": "identity_and_wardrobe_from_reference", "target_wardrobe_evidence": "visible",
            "person_asset_profile": person["person_asset_profile"], "asset_mime_type": person["asset_mime_type"],
            "asset_width": person["asset_width"], "asset_height": person["asset_height"],
            "identity_subject_count": person["identity_subject_count"], "asset_layout": person["asset_layout"],
            "asset_composition": person["asset_composition"],
        },
        {
            "tag": "TARGET_SUNQUICK_ORANGE", "reference": "@Image2", "role": "product", "asset_type": "product",
            "replaces_tag": "SRC_GAME_DEVICE_FAMILY",
            "source_object_descriptor": "the opening black rectangular package and the handheld gaming-device product track on the center table",
            "replacement_scope": "entire product family geometry, color, markings, packaging and approved beverage demonstration action",
            "preserve_scope": "source timing, hand contact purpose, camera, perspective, scale, shadows and occlusion; 00:00.000-00:02.450 bottle front stands centered, 00:02.450-00:05.050 lift front label close then return, 00:05.050-00:06.750 twist cap open, 00:06.750-00:08.650 lift front label, 00:08.650-00:10.350 rotate side then front, 00:10.350-00:15.042 stable chest-height front-label display",
            "binding_confidence": 0.99,
        },
        {
            "tag": "TARGET_OPEN_OFFICE", "reference": "@Image3", "role": "scene", "asset_type": "scene",
            "replaces_tag": "SRC_ROOM_BACKGROUND",
            "source_object_descriptor": "the full room environment behind and around the presenter from the opening frame",
            "replacement_scope": "complete background environment",
            "preserve_scope": "presenter, foreground table, microphone, product interactions, camera framing, depth, lighting direction and timing",
            "binding_confidence": 0.99,
        },
    ]
    replacements = [
        {"window": "00:00.000-00:15.042", "target": "TARGET_WOMAN", "asset_type": "model", "instruction": "apply the approved person replacement"},
        {"window": "00:00.000-00:15.042", "target": "TARGET_SUNQUICK_ORANGE", "asset_type": "product", "instruction": "apply the approved bottle replacement and exact adapted bottle-action timeline"},
        {"window": "00:00.000-00:15.042", "target": "TARGET_OPEN_OFFICE", "asset_type": "scene", "instruction": "replace the source room with the approved open-office environment"},
    ]
    dialogue = [
        {"window": "00:00.000-00:02.450", "speaker": "TARGET_WOMAN", "text": "All right, let's check out this Sunquick Orange."},
        {"window": "00:02.450-00:05.050", "speaker": "TARGET_WOMAN", "text": "That bright orange bottle really stands out."},
        {"window": "00:05.050-00:06.750", "speaker": "TARGET_WOMAN", "text": "The cap twists right open, and there it is."},
        {"window": "00:06.750-00:08.650", "speaker": "TARGET_WOMAN", "text": "Here is the front label up close."},
        {"window": "00:08.650-00:10.350", "speaker": "TARGET_WOMAN", "text": "You can see the bottle from every side."},
        {"window": "00:10.350-00:12.800", "speaker": "TARGET_WOMAN", "text": "The orange color looks so vivid."},
        {"window": "00:12.800-00:15.042", "speaker": "TARGET_WOMAN", "text": "If you want a full pour test, tell me."},
    ]
    full = compile_edit_prompt(
        source_video="@Video1", asset_bindings=full_bindings, replacements=replacements,
        dialogue_changes=dialogue, approved_speaker_tags=["TARGET_WOMAN"], segment_window_ms=(0, 15042),
    )
    pass1 = compile_edit_prompt(
        source_video="@Video1", asset_bindings=[full_bindings[0]], replacements=[replacements[0]],
        dialogue_changes=dialogue, approved_speaker_tags=["TARGET_WOMAN"], segment_window_ms=(0, 15042),
    )
    pass1_prompt = pass1["prompt"] + " Render matching English subtitles for each approved dialogue window using the exact quoted dialogue."
    pass2_bindings = [
        {
            "reference": "@Image1", "asset_type": "product", "target_tag": "TARGET_SUNQUICK_ORANGE",
            "source_object_id": "SRC_GAME_DEVICE_FAMILY",
            "source_track_descriptor": full_bindings[1]["source_object_descriptor"],
            "replacement_scope": full_bindings[1]["replacement_scope"],
            "preserve_scope": full_bindings[1]["preserve_scope"], "binding_confidence": 0.99,
        },
        {
            "reference": "@Image2", "asset_type": "scene", "target_tag": "TARGET_OPEN_OFFICE",
            "source_object_id": "SRC_ROOM_BACKGROUND",
            "source_track_descriptor": full_bindings[2]["source_object_descriptor"],
            "replacement_scope": full_bindings[2]["replacement_scope"],
            "preserve_scope": full_bindings[2]["preserve_scope"], "binding_confidence": 0.99,
        },
    ]
    pass2 = compile_provider_only_multi_object_prompt(source_video="@Video1", bindings=pass2_bindings)
    return {
        "full_complexity": full["complexity"], "full_audio_policy": full["audio_policy"],
        "pass1_prompt": pass1_prompt, "pass1_receipt": {**pass1["provider_only_binding_receipt"], "prompt_sha256": sha_text(pass1_prompt)},
        "pass2_prompt": pass2["prompt"], "pass2_receipt": pass2["provider_only_binding_receipt"],
        "dialogue": dialogue, "manifest": manifest,
    }


def poll_and_download(task_id: str, run_dir: Path) -> None:
    while True:
        status = post_json(os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"], {"taskId": task_id})
        (run_dir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state = str(status.get("status") or "").upper()
        print(json.dumps({"taskId": task_id, "status": state}), flush=True)
        if state == "SUCCESS":
            url = next(row["url"] for row in status["results"] if row.get("outputType") == "mp4")
            with request.urlopen(url, timeout=180) as response:
                (run_dir / "result.mp4").write_bytes(response.read())
            return
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError(f"PROVIDER_{state}")
        time.sleep(10)


def prepare() -> dict:
    load_env()
    auth = compile_authority()
    # The compiler is the measured authority. score == threshold stays in one provider request.
    if auth["full_complexity"].get("decision") != "within_threshold":
        raise RuntimeError(f"ONE_PASS_NOT_AUTHORIZED: {auth['full_complexity']}")
    manifest = auth["manifest"]
    by_tag = {row["tag"]: row for row in manifest}
    uploader = make_uploader()
    PASS1_DIR.mkdir(parents=True, exist_ok=True)
    PASS2_DIR.mkdir(parents=True, exist_ok=True)
    upload_file = PASS1_DIR / "uploaded_media.json"
    old_upload = json.loads(upload_file.read_text(encoding="utf-8")) if upload_file.exists() else {}
    person_sha = by_tag["TARGET_WOMAN"]["asset_sha256"]
    uploaded = {
        "source_video_url": old_upload.get("source_video_url") or uploader.upload_media(SOURCE_VIDEO),
        "person_url": old_upload.get("person_url") if old_upload.get("person_sha256") == person_sha else uploader.upload_media(Path(by_tag["TARGET_WOMAN"]["asset_path"])),
        "product_url": old_upload.get("product_url") or uploader.upload_media(Path(by_tag["TARGET_SUNQUICK_ORANGE"]["asset_path"])),
        "scene_url": old_upload.get("scene_url") or uploader.upload_media(Path(by_tag["TARGET_OPEN_OFFICE"]["asset_path"])),
        "person_sha256": person_sha,
    }
    upload_file.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    full_prompt = compile_authority()["pass1_prompt"]
    # Recompile the one-pass compact prompt with all three ordered targets. The human/person line
    # remains first and unchanged in weight; product and scene bindings follow at @Image2/@Image3.
    sys.path.insert(0, str(SKILL_ROOT))
    from scripts.seedance_prompt_compiler import compile_edit_prompt
    person = next(row for row in manifest if row["tag"] == "TARGET_WOMAN")
    bindings = [
        {
            "tag": "TARGET_WOMAN", "reference": "@Image1", "role": "model", "asset_type": "model", "replaces_tag": "SRC_PRESENTER",
            "source_object_descriptor": "the only opening-center seated male presenter with wavy dark hair, blue striped overshirt and white sleeves",
            "target_identity_descriptor": "adult woman with long dark hair in a low ponytail and the visible pink ribbed mock-neck long-sleeve top from @Image1",
            "replacement_scope": "person identity, hair and visible upper wardrobe",
            "preserve_scope": "source seated body track, mouth timing, gaze, gestures, hand contacts, microphone relationship, blocking, occlusion and timing",
            "binding_confidence": 0.99, "wardrobe_policy": "identity_and_wardrobe_from_reference", "target_wardrobe_evidence": "visible",
            "person_asset_profile": person["person_asset_profile"], "asset_mime_type": person["asset_mime_type"], "asset_width": 1024, "asset_height": 1024,
            "identity_subject_count": 1, "asset_layout": "identity_dominant", "asset_composition": "upper_body_square",
        },
        {
            "tag": "TARGET_SUNQUICK_ORANGE", "reference": "@Image2", "role": "product", "asset_type": "product", "replaces_tag": "SRC_GAME_DEVICE_FAMILY",
            "source_object_descriptor": "the opening black rectangular package and the handheld gaming-device product track on the center table",
            "replacement_scope": "entire product family geometry, color, markings, packaging and approved beverage demonstration action",
            "preserve_scope": "source timing, hand contact purpose, camera, perspective, scale, shadows and occlusion; 00:00.000-00:02.450 bottle front stands centered, 00:02.450-00:05.050 lift front label close then return, 00:05.050-00:06.750 twist cap open, 00:06.750-00:08.650 lift front label, 00:08.650-00:10.350 rotate side then front, 00:10.350-00:15.042 stable chest-height front-label display",
            "binding_confidence": 0.99,
        },
        {
            "tag": "TARGET_OPEN_OFFICE", "reference": "@Image3", "role": "scene", "asset_type": "scene", "replaces_tag": "SRC_ROOM_BACKGROUND",
            "source_object_descriptor": "the full room environment behind and around the presenter from the opening frame",
            "replacement_scope": "complete background environment",
            "preserve_scope": "presenter, foreground table, microphone, product interactions, camera framing, depth, lighting direction and timing",
            "binding_confidence": 0.99,
        },
    ]
    dialogue = auth["dialogue"]
    compiled = compile_edit_prompt(
        source_video="@Video1", asset_bindings=bindings,
        replacements=[
            {"window": "00:00.000-00:15.042", "target": "TARGET_WOMAN", "asset_type": "model", "instruction": "apply the approved person replacement"},
            {"window": "00:00.000-00:15.042", "target": "TARGET_SUNQUICK_ORANGE", "asset_type": "product", "instruction": "apply the approved bottle replacement and exact adapted bottle-action timeline"},
            {"window": "00:00.000-00:15.042", "target": "TARGET_OPEN_OFFICE", "asset_type": "scene", "instruction": "replace the source room with the approved open-office environment"},
        ], dialogue_changes=dialogue, approved_speaker_tags=["TARGET_WOMAN"], segment_window_ms=(0, 15042),
    )
    full_prompt = compiled["prompt"] + " Render matching English subtitles for each approved dialogue window using the exact quoted dialogue."
    pass1_payload = {
        "prompt": full_prompt, "resolution": "720p", "duration": "15",
        "imageUrls": [uploaded["person_url"], uploaded["product_url"], uploaded["scene_url"]], "videoUrls": [uploaded["source_video_url"]], "audioUrls": [],
        "generateAudio": True, "ratio": "3:4", "realPersonMode": True, "conversionSlots": ["all"],
        "returnLastFrame": False, "seed": -1,
    }
    audit = {
        "schema_version": "usfr-fixed-two-pass-edit/v1", "full_complexity": auth["full_complexity"],
        "approved_script_sha256": sha_file(SCRIPT), "source_dynamics_sha256": sha_file(DYNAMICS),
        "source_video_sha256": sha_file(SOURCE_VIDEO), "pass_order": ["single_provider_request"],
        "pass1_request_sha256": sha_json(pass1_payload), "pass1_prompt_sha256": sha_text(full_prompt),
        "pass1_image_tags": ["@Image1", "@Image2", "@Image3"],
        "provider_only_binding_receipt": {**compiled["provider_only_binding_receipt"], "prompt_sha256": sha_text(full_prompt)},
        "asset_sha256_order": [row["asset_sha256"] for row in manifest],
    }
    (PASS1_DIR / "request.redacted.json").write_text(json.dumps(pass1_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (PASS1_DIR / "prompt.txt").write_text(full_prompt + "\n", encoding="utf-8")
    (CASE_DIR / "request_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "PREPARED", **audit}


def submit_pass1() -> dict:
    load_env()
    payload = json.loads((PASS1_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    digest = sha_json(payload)
    create_file = PASS1_DIR / f"create_{digest}.json"
    if create_file.exists():
        raise RuntimeError("UNCHANGED_PASS1_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_file.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("PASS1_TASK_ID_MISSING")
    (PASS1_DIR / "task_id.txt").write_text(task_id + "\n", encoding="utf-8")
    poll_and_download(task_id, PASS1_DIR)
    return {"status": "SUCCESS", "pass": 1, "taskId": task_id}


def prepare_pass2() -> dict:
    load_env()
    if not (PASS1_DIR / "result.mp4").is_file():
        raise RuntimeError("ACCEPTED_PASS1_REQUIRED")
    auth = compile_authority()
    uploaded = json.loads((PASS1_DIR / "uploaded_media.json").read_text(encoding="utf-8"))
    pass1_url_file = PASS2_DIR / "pass1_url.json"
    if pass1_url_file.exists():
        pass1_url = json.loads(pass1_url_file.read_text(encoding="utf-8"))["videoUrl"]
    else:
        pass1_url = make_uploader().upload_media(PASS1_DIR / "result.mp4")
        pass1_url_file.write_text(json.dumps({"videoUrl": pass1_url}, indent=2) + "\n", encoding="utf-8")
    payload = {
        "prompt": auth["pass2_prompt"], "resolution": "720p", "duration": "15",
        "imageUrls": [uploaded["product_url"], uploaded["scene_url"]], "videoUrls": [pass1_url], "audioUrls": [],
        "generateAudio": True, "ratio": "3:4", "realPersonMode": True, "conversionSlots": ["all"],
        "returnLastFrame": False, "seed": -1,
    }
    record = {
        "pass1_result_sha256": sha_file(PASS1_DIR / "result.mp4"),
        "pass2_request_sha256": sha_json(payload), "pass2_prompt_sha256": sha_text(auth["pass2_prompt"]),
        "image_order": ["TARGET_SUNQUICK_ORANGE", "TARGET_OPEN_OFFICE"],
    }
    (PASS2_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (PASS2_DIR / "request_audit.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "PASS2_PREPARED", **record}


def submit_pass2() -> dict:
    load_env()
    payload = json.loads((PASS2_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    digest = sha_json(payload)
    create_file = PASS2_DIR / f"create_{digest}.json"
    if create_file.exists():
        raise RuntimeError("UNCHANGED_PASS2_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_file.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("PASS2_TASK_ID_MISSING")
    (PASS2_DIR / "task_id.txt").write_text(task_id + "\n", encoding="utf-8")
    poll_and_download(task_id, PASS2_DIR)
    return {"status": "SUCCESS", "pass": 2, "taskId": task_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "submit-pass1", "prepare-pass2", "submit-pass2"])
    args = parser.parse_args()
    functions = {"prepare": prepare, "submit-pass1": submit_pass1, "prepare-pass2": prepare_pass2, "submit-pass2": submit_pass2}
    print(json.dumps(functions[args.action](), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
