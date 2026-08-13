from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from urllib import request


RUN_DIR = Path(__file__).resolve().parent
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
VIDEO_URL = "https://rh-hk-images-switch.xiaoyaoyou.com/input/openapi/096232caa5fdb33d7c12d5b5594560e153b482197e643ba25ad0423387e5eee0.mp4"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def request_sha(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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


def validate_authority() -> tuple[str, dict, dict]:
    prompt = (RUN_DIR / "prompt.txt").read_text(encoding="utf-8-sig")
    receipt = json.loads((RUN_DIR / "provider_only_binding_receipt.json").read_text(encoding="utf-8"))
    manifest = json.loads((RUN_DIR / "asset_board_manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(prompt.encode()).hexdigest() != receipt.get("prompt_sha256"):
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    tags = ["@Image1", "@Image2", "@Image3"]
    if receipt.get("image_tags") != tags:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if manifest.get("uploaded_tags") != tags or manifest.get("binding_tags") != tags or manifest.get("prompt_tags") != tags:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if [row.get("image_tag") for row in manifest.get("assets", [])] != tags:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if not prompt.startswith("编辑视频：") or any(tag not in prompt for tag in tags):
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    return prompt, receipt, manifest


def prepare() -> dict:
    prompt, receipt, manifest = validate_authority()
    image_urls = [row["board_url"] for row in manifest["assets"]]
    payload = {
        "prompt": prompt,
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
    digest = request_sha(payload)
    audit = {
        "schema_version": "usfr-provider-only-request-audit/v1",
        "request_sha256": digest,
        "provider_only": True,
        "provider_create_calls_allowed": 1,
        "qc_retry_of_task_id": "2087117868105093122",
        "qc_retry_reason": "missing canonical target asset boards caused partial female identity retention",
        "image_tag_order": receipt["image_tags"],
        "source_object_order": receipt["source_object_ids"],
        "asset_board_sha256_order": [row["board_sha256"] for row in manifest["assets"]],
        "asset_board_task_id_order": [row["task_id"] for row in manifest["assets"]],
        "image_url_count": 3,
        "video_url_count": 1,
        "binding_board_uploaded": False,
        "local_final_video_processing": False,
        "prompt_sha256": receipt["prompt_sha256"],
        "binding_contract_sha256": receipt["binding_contract_sha256"],
        "prompt_chars": len(prompt),
    }
    (RUN_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "approval_preview.json").write_text(json.dumps({"request_sha256": digest}, indent=2) + "\n", encoding="utf-8")
    return {"status": "prepared", "request_sha256": digest}


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
    validate_authority()
    payload = json.loads((RUN_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    digest = request_sha(payload)
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
    task_id = (RUN_DIR / "task_id.txt").read_text(encoding="utf-8").strip()
    return query(task_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "submit", "resume"))
    args = parser.parse_args()
    result = prepare() if args.mode == "prepare" else submit() if args.mode == "submit" else resume()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
