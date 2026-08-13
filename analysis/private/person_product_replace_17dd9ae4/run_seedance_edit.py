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
SOURCE_VIDEO = Path(r"C:\Users\zhaocx04\Downloads\新建文件夹 (28)\17dd9ae4-3af9-486a-8135-4f1658f4e804-11e0ebcd31a00379.mp4")
PERSON_ASSET = CASE_DIR / "assets" / "person" / "01_TARGET_WOMAN.png"
PERSON_MANIFEST = CASE_DIR / "assets" / "person" / "person_asset_manifest.json"
PRODUCT_ASSET = CASE_DIR / "assets" / "product" / "02_TARGET_SUNNY_POP_PRODUCT.png"
PRODUCT_MANIFEST = CASE_DIR / "assets" / "product" / "product_asset_manifest.json"
APPROVED_SCRIPT = WORKSPACE / "analysis" / "reverse_storyboard_script.md"
DYNAMICS = CASE_DIR / "source_dynamics_analysis.json"
VARIANT = os.environ.get("USFR_CASE_VARIANT", "initial").strip() or "initial"
RUN_DIR = CASE_DIR / ("seedance_run" if VARIANT == "initial" else "seedance_retry_timed_action_v2")


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_json(payload: object) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def uploader():
    script_dir = SKILL_ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
    sys.path.insert(0, str(script_dir))
    from runninghub_seedance_submit import RunningHubStandardSeedanceClient

    return RunningHubStandardSeedanceClient(
        os.environ["RUNNINGHUB_SEEDANCE_API_KEY"],
        create_url=os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"],
        query_url=os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"],
        upload_url=os.environ["RUNNINGHUB_SEEDANCE_UPLOAD_URL"],
    )


def compile_prompt() -> dict:
    sys.path.insert(0, str(SKILL_ROOT))
    from scripts.seedance_prompt_compiler import compile_edit_prompt
    from server.packaged_stages import _validate_provider_only_binding_receipt

    person = json.loads(PERSON_MANIFEST.read_text(encoding="utf-8"))["assets"][0]
    product = json.loads(PRODUCT_MANIFEST.read_text(encoding="utf-8"))
    if sha_file(PERSON_ASSET) != person["sha256"]:
        raise RuntimeError("TARGET_PERSON_ASSET_CHANGED")
    if sha_file(PRODUCT_ASSET) != product["board_sha256"]:
        raise RuntimeError("TARGET_PRODUCT_ASSET_CHANGED")

    product_preserve_scope = (
        "source timing, camera, track, perspective, shadows, and occlusion; use one realistic 300ml bottle on the main hand track, natural cap opening and one sip, label rotation, close display, matching table bottles, and warm-orange bottle visibility in the dark-reveal phase"
        if VARIANT == "initial"
        else "source camera, track, perspective, shadows, and occlusion; at 00:00.000-00:01.680 hold the front label, 00:01.680-00:03.250 open the cap and sip once, 00:03.900-00:06.917 rotate the label then move the bottle close, 00:06.917-00:09.500 hold the warm-orange bottle beside a relaxed closed-mouth smile, and 00:09.500-00:11.042 point while holding the front label; matching SUNNY POP bottles remain on the table"
    )
    bindings = [
        {
            "tag": "TARGET_WOMAN",
            "reference": "@Image1",
            "role": "model",
            "asset_type": "model",
            "replaces_tag": "SRC_PRESENTER",
            "source_object_descriptor": "opening-center seated presenter in the pale sweater and green bandana, handling the green candy",
            "target_identity_descriptor": "curly red-brown hair, exact female face, colorful patterned blouse, dangling silver earrings, layered silver necklaces",
            "replacement_scope": "person identity, hair, visible wardrobe, and accessories",
            "preserve_scope": "source body track, expressions, gaze, gestures, hand contacts, blocking, occlusion, and timing",
            "binding_confidence": 0.99,
            "identity_scope": "face_hair_skin",
            "wardrobe_policy": "identity_and_wardrobe_from_reference",
            "target_wardrobe_evidence": "visible",
            "person_asset_profile": person["person_asset_profile"],
            "asset_mime_type": person["asset_mime_type"],
            "asset_width": person["asset_width"],
            "asset_height": person["asset_height"],
            "identity_subject_count": person["identity_subject_count"],
            "asset_layout": person["asset_layout"],
            "asset_composition": person["asset_composition"],
        },
        {
            "tag": "TARGET_SUNNY_POP_PRODUCT",
            "reference": "@Image2",
            "role": "product",
            "asset_type": "product",
            "replaces_tag": "SRC_GREEN_CONFECTION_FAMILY",
            "source_object_descriptor": "opening green candy product track: handheld unwrapped piece, wrapped close-up, and table units",
            "replacement_scope": "entire product family geometry, color, markings, packaging, and demonstration action",
            "preserve_scope": product_preserve_scope,
            "binding_confidence": 0.97,
        },
    ]
    replacements = [
        {
            "window": "00:00.000-00:11.042",
            "target": "TARGET_WOMAN",
            "asset_type": "model",
            "instruction": "apply the approved mapped person replacement",
        },
        {
            "window": "00:00.000-00:11.042",
            "target": "TARGET_SUNNY_POP_PRODUCT",
            "asset_type": "product",
            "instruction": "apply the approved mapped product replacement and bottle actions",
        },
    ]
    dialogue = [
        {"window": "00:00.000-00:01.680", "speaker": "TARGET_WOMAN", "text": "Sunny Pop, fresh orange juice."},
        {"window": "00:03.900-00:05.740", "speaker": "TARGET_WOMAN", "text": "Cold pressed, no added sugar."},
        {"window": "00:07.320-00:09.220", "speaker": "TARGET_WOMAN", "text": "Fresh sunshine in every sip."},
        {"window": "00:09.800-00:10.860", "speaker": "TARGET_WOMAN", "text": "Try Sunny Pop."},
    ]
    compiled = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=bindings,
        replacements=replacements,
        dialogue_changes=dialogue,
        segment_window_ms=(0, 11042),
    )
    receipt = dict(compiled["provider_only_binding_receipt"])
    receipt["prompt_sha256"] = sha_text(compiled["prompt"])
    receipt = _validate_provider_only_binding_receipt(
        receipt,
        prompt=compiled["prompt"],
        image_tags=["@Image1", "@Image2"],
    )
    return {
        "prompt": compiled["prompt"],
        "complexity": compiled["complexity"],
        "audio_policy": compiled["audio_policy"],
        "lip_sync_policy": compiled["lip_sync_policy"],
        "bindings": bindings,
        "replacements": replacements,
        "dialogue": dialogue,
        "binding_receipt": receipt,
        "variant": VARIANT,
    }


def prepare() -> dict:
    load_env()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    compiled = compile_prompt()
    urls_path = RUN_DIR / "uploaded_media.json"
    if urls_path.exists():
        uploaded = json.loads(urls_path.read_text(encoding="utf-8"))
    elif VARIANT != "initial" and (CASE_DIR / "seedance_run" / "uploaded_media.json").exists():
        uploaded = json.loads((CASE_DIR / "seedance_run" / "uploaded_media.json").read_text(encoding="utf-8"))
        urls_path.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        client = uploader()
        uploaded = {
            "imageUrls": [client.upload_file(PERSON_ASSET), client.upload_file(PRODUCT_ASSET)],
            "videoUrls": [client.upload_file(SOURCE_VIDEO)],
            "image_tags": ["@Image1", "@Image2"],
            "image_sha256": [sha_file(PERSON_ASSET), sha_file(PRODUCT_ASSET)],
            "video_sha256": sha_file(SOURCE_VIDEO),
        }
        urls_path.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if uploaded.get("image_tags") != ["@Image1", "@Image2"]:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if uploaded.get("image_sha256") != [sha_file(PERSON_ASSET), sha_file(PRODUCT_ASSET)]:
        raise RuntimeError("TARGET_ASSET_BYTES_CHANGED")
    if uploaded.get("video_sha256") != sha_file(SOURCE_VIDEO):
        raise RuntimeError("SOURCE_VIDEO_BYTES_CHANGED")

    payload = {
        "prompt": compiled["prompt"],
        "resolution": "720p",
        "duration": "11",
        "imageUrls": uploaded["imageUrls"],
        "videoUrls": uploaded["videoUrls"],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "3:4",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }
    sys.path.insert(0, str(SKILL_ROOT))
    from server.runninghub_standard_contract import validate_runninghub_standard_payload_contract

    validate_runninghub_standard_payload_contract(payload)
    digest = sha_json(payload)
    script_sha = sha_file(APPROVED_SCRIPT)
    dynamics_sha = sha_file(DYNAMICS)
    matcher_receipt = {
        "contract": "replication-matcher/v1",
        "classification": "adapt_fit",
        "source_video_sha256": sha_file(SOURCE_VIDEO),
        "approved_script_sha256": script_sha,
        "reason": "source edible candy interaction is adapted to realistic bottle opening, drinking, label display, and warm dark-reveal product presentation",
    }
    segment_plan = {
        "contract": "video-edit-v2-segment-plan/v1",
        "segments": [{"segment_id": "SEG01", "start_ms": 0, "end_ms": 11042, "ratio": "3:4"}],
        "cut_order_preserved": True,
        "provider_passes": 1,
        "complexity": compiled["complexity"],
        "audio_policy": compiled["audio_policy"],
        "lip_sync_policy": compiled["lip_sync_policy"],
    }
    audit = {
        "schema_version": "usfr-person-product-provider-only/v1",
        "request_sha256": digest,
        "source_video_sha256": sha_file(SOURCE_VIDEO),
        "approved_script_sha256": script_sha,
        "source_dynamics_sha256": dynamics_sha,
        "matcher_receipt_sha256": sha_json(matcher_receipt),
        "segment_plan_sha256": sha_json(segment_plan),
        "binding_contract_sha256": compiled["binding_receipt"]["binding_contract_sha256"],
        "prompt_sha256": sha_text(compiled["prompt"]),
        "image_tag_order": ["@Image1", "@Image2"],
        "source_object_order": ["SRC_PRESENTER", "SRC_GREEN_CONFECTION_FAMILY"],
        "image_sha256_order": uploaded["image_sha256"],
        "provider_create_calls_allowed": 1,
        "provider_only": True,
        "local_final_video_processing": False,
        "prompt_chars": len(compiled["prompt"]),
        "ratio": "3:4",
        "duration": "11",
        "variant": VARIANT,
        "primary_change_variable": "initial_locked_prompt" if VARIANT == "initial" else "explicit_positive_action_timeline",
    }
    (RUN_DIR / "prompt.txt").write_text(compiled["prompt"] + "\n", encoding="utf-8")
    (RUN_DIR / "provider_only_binding_receipt.json").write_text(
        json.dumps(compiled["binding_receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RUN_DIR / "asset_bindings.json").write_text(
        json.dumps(compiled["bindings"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RUN_DIR / "matcher_receipt.json").write_text(
        json.dumps(matcher_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RUN_DIR / "segment_plan.json").write_text(
        json.dumps(segment_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RUN_DIR / "request.redacted.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RUN_DIR / "request_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RUN_DIR / "approval_preview.json").write_text(
        json.dumps({"request_sha256": digest, "approved_script_sha256": script_sha}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"status": "PREPARED", **audit}


def submit() -> dict:
    load_env()
    compiled = compile_prompt()
    payload = json.loads((RUN_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    audit = json.loads((RUN_DIR / "request_audit.json").read_text(encoding="utf-8"))
    preview = json.loads((RUN_DIR / "approval_preview.json").read_text(encoding="utf-8"))
    receipt = json.loads((RUN_DIR / "provider_only_binding_receipt.json").read_text(encoding="utf-8"))
    digest = sha_json(payload)
    if digest != audit.get("request_sha256") or digest != preview.get("request_sha256"):
        raise RuntimeError("AUDITED_REQUEST_CHANGED")
    if payload.get("prompt") != compiled["prompt"] or receipt != compiled["binding_receipt"]:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if sha_file(APPROVED_SCRIPT) != preview.get("approved_script_sha256"):
        raise RuntimeError("APPROVED_SCRIPT_CHANGED")
    create_path = RUN_DIR / f"create_{digest}.json"
    if create_path.exists():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")

    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_path.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
