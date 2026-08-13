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
SOURCE_VIDEO = Path(r"C:\Users\zhaocx04\Documents\我的POPO\mooc 2340.mp4")
PRODUCT_ASSET = CASE_DIR / "assets" / "product" / "01_TARGET_PINK_PHONE.png"
PRODUCT_MANIFEST = CASE_DIR / "assets" / "product" / "product_asset_manifest.json"
APPROVED_SCRIPT = WORKSPACE / "analysis" / "reverse_storyboard_script.md"
DYNAMICS = CASE_DIR / "source_dynamics_analysis.json"
VARIANT = os.environ.get("USFR_CASE_VARIANT", "initial").strip() or "initial"
RUN_DIR = CASE_DIR / ("seedance_run" if VARIANT == "initial" else "seedance_qc_retry")


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

    product = json.loads(PRODUCT_MANIFEST.read_text(encoding="utf-8"))
    if product.get("image_tag") != "@Image1" or product.get("asset_type") != "product":
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if sha_file(PRODUCT_ASSET) != product.get("board_sha256"):
        raise RuntimeError("TARGET_PRODUCT_ASSET_CHANGED")

    bindings = [{
        "tag": "TARGET_PINK_PHONE",
        "reference": "@Image1",
        "role": "product",
        "asset_type": "product",
        "replaces_tag": "SRC_LAPTOP_FAMILY",
        "source_object_descriptor": (
            "all closed laptop product tracks: the first left-to-right handoff, "
            "the second right-to-left handoff, and the final four-product stack"
        ),
        "replacement_scope": (
            "the complete product-family geometry, pale-pink color, front black screen, "
            "rear diagonal dual-camera layout, markings, and thin smartphone proportions"
        ),
        "preserve_scope": (
            "the source white background, locked camera, exact timing, hand tracks, entry and exit directions, "
            "contact, perspective, lighting, shadows, and occlusion"
        ),
        "binding_confidence": 0.99,
    }]
    action_instruction = (
        "00:00.20-00:01.00 pass one @Image1 phone left-to-right with realistic edge support; "
        "00:01.40-00:02.40 pass one @Image1 phone right-to-left; "
        "00:02.80-00:04.20 add matching @Image1 phones one by one into a thin front/back alternating stack; "
        "00:04.20-00:05.00 hold the completed stack; replace the source text with exact clean text "
        "你好，iPhone 15。 and iPhone 15 · 粉色"
    ) if VARIANT == "initial" else (
        "00:00.20-00:01.00 pass one pale-pink @Image1 phone left-to-right with realistic edge support; "
        "00:01.40-00:02.40 pass one pale-pink @Image1 phone right-to-left; "
        "00:02.80-00:04.20 place exactly four identical pale-pink @Image1 phones one by one into a thin stack, "
        "each unit retaining the same pale-pink body and diagonal dual cameras; "
        "00:04.20-00:05.00 hold exactly four identical pale-pink phones; "
        "the complete upper typography area contains exactly three clean lines: 你好，iPhone 15。 / iPhone 15 / iPhone 15 · 粉色; "
        "the complete audio state is silence"
    )
    replacements = [{
        "window": "00:00.000-00:05.000",
        "target": "TARGET_PINK_PHONE",
        "asset_type": "product",
        "execution_mode": "adapt_action",
        "change_id": "PHONE_HANDOFF_STACK_ADAPTATION" if VARIANT == "initial" else "PHONE_STACK_TEXT_SILENCE_QC_CORRECTION",
        "instruction": action_instruction,
    }]
    compiled = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=bindings,
        replacements=replacements,
        dialogue_changes=[],
        segment_window_ms=(0, 5000),
    )
    receipt = dict(compiled["provider_only_binding_receipt"])
    receipt["prompt_sha256"] = sha_text(compiled["prompt"])
    receipt = _validate_provider_only_binding_receipt(
        receipt,
        prompt=compiled["prompt"],
        image_tags=["@Image1"],
    )
    return {
        "prompt": compiled["prompt"],
        "complexity": compiled["complexity"],
        "audio_policy": compiled["audio_policy"],
        "lip_sync_policy": compiled["lip_sync_policy"],
        "bindings": bindings,
        "replacements": replacements,
        "binding_receipt": receipt,
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
            "imageUrls": [client.upload_file(PRODUCT_ASSET)],
            "videoUrls": [client.upload_file(SOURCE_VIDEO)],
            "image_tags": ["@Image1"],
            "image_sha256": [sha_file(PRODUCT_ASSET)],
            "video_sha256": sha_file(SOURCE_VIDEO),
        }
        urls_path.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if uploaded.get("image_tags") != ["@Image1"]:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if uploaded.get("image_sha256") != [sha_file(PRODUCT_ASSET)]:
        raise RuntimeError("TARGET_ASSET_BYTES_CHANGED")
    if uploaded.get("video_sha256") != sha_file(SOURCE_VIDEO):
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

    digest = sha_json(payload)
    script_sha = sha_file(APPROVED_SCRIPT)
    matcher_receipt = {
        "contract": "replication-matcher/v1",
        "classification": "adapt_fit",
        "source_video_sha256": sha_file(SOURCE_VIDEO),
        "approved_script_sha256": script_sha,
        "reason": "laptop handoff and stacking are adapted to realistic smartphone edge support and thin-product stacking",
    }
    segment_plan = {
        "contract": "video-edit-v2-segment-plan/v1",
        "segments": [{"segment_id": "SEG01", "start_ms": 0, "end_ms": 5000, "ratio": "adaptive"}],
        "cut_order_preserved": True,
        "provider_passes": 1,
        "complexity": compiled["complexity"],
        "audio_policy": compiled["audio_policy"],
        "lip_sync_policy": compiled["lip_sync_policy"],
    }
    audit = {
        "schema_version": "usfr-product-provider-only/v1",
        "request_sha256": digest,
        "source_video_sha256": sha_file(SOURCE_VIDEO),
        "approved_script_sha256": script_sha,
        "source_dynamics_sha256": sha_file(DYNAMICS),
        "matcher_receipt_sha256": sha_json(matcher_receipt),
        "segment_plan_sha256": sha_json(segment_plan),
        "binding_contract_sha256": compiled["binding_receipt"]["binding_contract_sha256"],
        "prompt_sha256": sha_text(compiled["prompt"]),
        "image_tag_order": ["@Image1"],
        "source_object_order": ["SRC_LAPTOP_FAMILY"],
        "image_sha256_order": uploaded["image_sha256"],
        "provider_create_calls_allowed": 1,
        "provider_only": True,
        "local_final_video_processing": False,
        "prompt_chars": len(compiled["prompt"]),
        "ratio": "adaptive",
        "duration": "5",
        "primary_change_variable": "approved_phone_action_adaptation" if VARIANT == "initial" else "exact_stack_text_and_silence_qc_correction",
    }
    (RUN_DIR / "prompt.txt").write_text(compiled["prompt"] + "\n", encoding="utf-8")
    (RUN_DIR / "provider_only_binding_receipt.json").write_text(json.dumps(compiled["binding_receipt"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "asset_bindings.json").write_text(json.dumps(compiled["bindings"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "matcher_receipt.json").write_text(json.dumps(matcher_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "segment_plan.json").write_text(json.dumps(segment_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "approval_preview.json").write_text(json.dumps({"request_sha256": digest, "approved_script_sha256": script_sha}, indent=2) + "\n", encoding="utf-8")
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
