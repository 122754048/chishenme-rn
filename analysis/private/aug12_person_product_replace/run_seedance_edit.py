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
SOURCE_VIDEO = Path(r"C:\Users\zhaocx04\Downloads\8月12日 (1).mp4")
ASSET_MANIFEST = CASE_DIR / "assets" / "asset_manifest.json"
APPROVED_SCRIPT = WORKSPACE / "analysis" / "reverse_storyboard_script.md"
DYNAMICS = CASE_DIR / "source_dynamics_analysis.json"
VARIANT = os.environ.get("USFR_CASE_VARIANT", "initial").strip() or "initial"
RUN_DIR = CASE_DIR / ("seedance_run" if VARIANT == "initial" else "seedance_provider_retry")


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
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
    scripts = SKILL_ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
    sys.path.insert(0, str(scripts))
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

    assets = json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))["assets"]
    person, product = assets
    person_path = Path(person["asset_path"])
    product_path = Path(product["asset_path"])
    if sha_file(person_path) != person["asset_sha256"] or sha_file(product_path) != product["asset_sha256"]:
        raise RuntimeError("TARGET_ASSET_BYTES_CHANGED")
    if [row["reference"] for row in assets] != ["@Image1", "@Image2"]:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")

    bindings = [
        {
            "tag": "TARGET_WOMAN",
            "reference": "@Image1",
            "role": "model",
            "asset_type": "model",
            "replaces_tag": "SRC_SEASIDE_WOMAN",
            "source_object_descriptor": "the only woman in the opening seaside convertible, beginning in right-facing profile and turning forward",
            "target_identity_descriptor": "long straight brown hair, exact female face, white fitted long-sleeve top, gray lower outfit, necklace and visible rings",
            "replacement_scope": "person identity, hair, complete visible wardrobe, and accessories",
            "preserve_scope": "the source seated body track, head turn, expression timing, gaze, arm position, convertible contact, blocking, lighting and occlusion",
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
            "tag": "TARGET_SUNQUICK_ORANGE",
            "reference": "@Image2",
            "role": "product",
            "asset_type": "product",
            "replaces_tag": "SRC_LIPSTICK_FAMILY",
            "source_object_descriptor": "the cosmetic product in the authorized adult commercial macro shot and both product components in the final warm-beige packshot",
            "replacement_scope": "the complete product geometry, orange screw cap, orange liquid, curved textured bottle, SUNQUICK logo, Oren Orange label and orange imagery",
            "preserve_scope": "the source macro-shot timing, warm luxury lighting, hand contact, product prominence, perspective, shadows, occlusion, final packshot framing and hold",
            "binding_confidence": 0.99,
        },
    ]
    replacements = [
        {
            "window": "00:00.000-00:04.567",
            "target": "TARGET_WOMAN",
            "asset_type": "model",
            "execution_mode": "direct_binding",
            "instruction": "apply the approved mapped person identity and wardrobe replacement",
        },
        {
            "window": "00:01.700-00:04.567",
            "target": "TARGET_SUNQUICK_ORANGE",
            "asset_type": "product",
            "execution_mode": "adapt_action",
            "change_id": "SUNQUICK_BOTTLE_OPERATION",
            "instruction": (
                "This is an authorized standard retail commercial edit featuring one adult presenter and a consumer beverage product; "
                "00:01.70-00:02.60 two hands hold @Image2 securely and one hand twists open its orange screw cap; "
                "00:02.60-00:03.45 gently tilt @Image2 to show the orange liquid, curved bottle and front SUNQUICK Oren Orange label; "
                "00:03.45-00:04.57 place one upright @Image2 bottle in the final warm-beige hero packshot with its front label facing camera; "
                "upper advertising text becomes exactly 这一刻，橙意正好, SUNQUICK, and Oren Orange; the complete audio state remains silence"
            ),
        },
    ]
    compiled = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=bindings,
        replacements=replacements,
        dialogue_changes=[],
        segment_window_ms=(0, 4567),
    )
    receipt = dict(compiled["provider_only_binding_receipt"])
    receipt["prompt_sha256"] = sha_text(compiled["prompt"])
    receipt = _validate_provider_only_binding_receipt(receipt, prompt=compiled["prompt"], image_tags=["@Image1", "@Image2"])
    return {
        "prompt": compiled["prompt"],
        "complexity": compiled["complexity"],
        "audio_policy": compiled["audio_policy"],
        "lip_sync_policy": compiled["lip_sync_policy"],
        "bindings": bindings,
        "replacements": replacements,
        "binding_receipt": receipt,
        "asset_paths": [person_path, product_path],
    }


def prepare() -> dict:
    load_env()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    compiled = compile_prompt()
    media_path = RUN_DIR / "uploaded_media.json"
    if media_path.exists():
        uploaded = json.loads(media_path.read_text(encoding="utf-8"))
    elif VARIANT != "initial" and (CASE_DIR / "seedance_run" / "uploaded_media.json").exists():
        uploaded = json.loads((CASE_DIR / "seedance_run" / "uploaded_media.json").read_text(encoding="utf-8"))
        media_path.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        client = uploader()
        uploaded = {
            "imageUrls": [client.upload_file(path) for path in compiled["asset_paths"]],
            "videoUrls": [client.upload_file(SOURCE_VIDEO)],
            "image_tags": ["@Image1", "@Image2"],
            "image_sha256": [sha_file(path) for path in compiled["asset_paths"]],
            "video_sha256": sha_file(SOURCE_VIDEO),
        }
        media_path.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if uploaded["image_tags"] != ["@Image1", "@Image2"] or uploaded["image_sha256"] != [sha_file(path) for path in compiled["asset_paths"]]:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if uploaded["video_sha256"] != sha_file(SOURCE_VIDEO):
        raise RuntimeError("SOURCE_VIDEO_BYTES_CHANGED")

    payload = {
        "prompt": compiled["prompt"],
        "resolution": "720p",
        "duration": "5",
        "imageUrls": uploaded["imageUrls"],
        "videoUrls": uploaded["videoUrls"],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "adaptive",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }
    from server.runninghub_standard_contract import validate_runninghub_standard_payload_contract
    validate_runninghub_standard_payload_contract(payload)
    request_sha = sha_json(payload)
    matcher = {
        "contract": "replication-matcher/v1",
        "classification": "adapt_fit",
        "reason": "the source lipstick application is adapted to evidence-supported bottle opening, controlled tilt and front-label packshot",
        "source_video_sha256": sha_file(SOURCE_VIDEO),
        "approved_script_sha256": sha_file(APPROVED_SCRIPT),
    }
    plan = {
        "contract": "video-edit-v2-segment-plan/v1",
        "segments": [{"segment_id": "SEG01", "start_ms": 0, "end_ms": 4567, "ratio": "adaptive"}],
        "provider_passes": 1,
        "cut_order_preserved": True,
        "complexity": compiled["complexity"],
        "audio_policy": compiled["audio_policy"],
    }
    audit = {
        "schema_version": "usfr-person-product-provider-only/v1",
        "request_sha256": request_sha,
        "source_video_sha256": sha_file(SOURCE_VIDEO),
        "approved_script_sha256": sha_file(APPROVED_SCRIPT),
        "source_dynamics_sha256": sha_file(DYNAMICS),
        "matcher_receipt_sha256": sha_json(matcher),
        "segment_plan_sha256": sha_json(plan),
        "binding_contract_sha256": compiled["binding_receipt"]["binding_contract_sha256"],
        "prompt_sha256": sha_text(compiled["prompt"]),
        "image_tag_order": ["@Image1", "@Image2"],
        "source_object_order": ["SRC_SEASIDE_WOMAN", "SRC_LIPSTICK_FAMILY"],
        "provider_create_calls_allowed": 1,
        "provider_only": True,
        "local_final_video_processing": False,
        "prompt_chars": len(compiled["prompt"]),
    }
    (RUN_DIR / "prompt.txt").write_text(compiled["prompt"] + "\n", encoding="utf-8")
    (RUN_DIR / "provider_only_binding_receipt.json").write_text(json.dumps(compiled["binding_receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "matcher_receipt.json").write_text(json.dumps(matcher, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "segment_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "approval_preview.json").write_text(json.dumps({"request_sha256": request_sha, "approved_script_sha256": sha_file(APPROVED_SCRIPT)}, indent=2) + "\n", encoding="utf-8")
    return {"status": "PREPARED", **audit}


def submit() -> dict:
    load_env()
    compiled = compile_prompt()
    payload = json.loads((RUN_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    audit = json.loads((RUN_DIR / "request_audit.json").read_text(encoding="utf-8"))
    preview = json.loads((RUN_DIR / "approval_preview.json").read_text(encoding="utf-8"))
    receipt = json.loads((RUN_DIR / "provider_only_binding_receipt.json").read_text(encoding="utf-8"))
    digest = sha_json(payload)
    if digest != audit["request_sha256"] or digest != preview["request_sha256"]:
        raise RuntimeError("AUDITED_REQUEST_CHANGED")
    if payload["prompt"] != compiled["prompt"] or receipt != compiled["binding_receipt"]:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if sha_file(APPROVED_SCRIPT) != preview["approved_script_sha256"]:
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
    print(json.dumps(prepare() if args.prepare else submit(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
