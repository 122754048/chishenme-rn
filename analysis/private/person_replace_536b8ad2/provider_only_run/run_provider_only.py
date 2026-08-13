from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from urllib import request


RUN_DIR = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
PROMPT_FILE = RUN_DIR / "prompt.txt"
BINDING_RECEIPT_FILE = RUN_DIR / "provider_only_binding_receipt.json"
SOURCE_FILE = RUN_DIR / "source_video_references" / "source-reference-SEG01.mp4"
IMAGE_FILES = [
    Path(r"C:\Users\zhaocx04\Downloads\8648a9162d0cc6c75565505e4a1d56a5961ae5ecc976aef3ea088e5a2b246510.png"),
    Path(r"C:\Users\zhaocx04\Downloads\Batch_00004_myhhx_1768465153.png"),
]
EXPECTED_IMAGE_SHA256 = [
    "8648a9162d0cc6c75565505e4a1d56a5961ae5ecc976aef3ea088e5a2b246510",
    "feaa0b922da12e8462fa17277d59978fc3e433cf08a954666b4da4223f5a738d",
]


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


def request_sha(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def validate_binding() -> tuple[str, dict]:
    prompt = PROMPT_FILE.read_text(encoding="utf-8-sig")
    receipt = json.loads(BINDING_RECEIPT_FILE.read_text(encoding="utf-8"))
    actual_prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if receipt.get("contract") != "provider-only-multi-object-binding/v1":
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if receipt.get("prompt_sha256") != actual_prompt_sha:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if receipt.get("image_tags") != ["@Image1", "@Image2"]:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if receipt.get("source_object_ids") != ["SRC_WOMAN", "SRC_MAN"]:
        raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    if not prompt.startswith("编辑视频："):
        raise RuntimeError("PROMPT_PREFIX_INVALID")
    for index, tag in enumerate(receipt["image_tags"], start=1):
        if tag != f"@Image{index}" or tag not in prompt:
            raise RuntimeError("SOURCE_OBJECT_BINDING_REQUIRED")
    for path, expected in zip(IMAGE_FILES, EXPECTED_IMAGE_SHA256, strict=True):
        if sha256_file(path) != expected:
            raise RuntimeError("TARGET_ASSET_BYTES_CHANGED")
    if not SOURCE_FILE.is_file():
        raise RuntimeError("SOURCE_REFERENCE_MISSING")
    return prompt, receipt


def upload_file(path: Path) -> str:
    import sys

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


def prepare() -> dict:
    load_env()
    prompt, receipt = validate_binding()
    request_path = RUN_DIR / "request.redacted.json"
    preview_path = RUN_DIR / "approval_preview.json"
    if request_path.is_file() and preview_path.is_file():
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        preview = json.loads(preview_path.read_text(encoding="utf-8"))
        if request_sha(payload) == preview.get("request_sha256"):
            return {"status": "prepared_reused", **preview}
    image_urls = [upload_file(path) for path in IMAGE_FILES]
    video_url = upload_file(SOURCE_FILE)
    payload = {
        "prompt": prompt,
        "resolution": "720p",
        "duration": "15",
        "imageUrls": image_urls,
        "videoUrls": [video_url],
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
        "image_tag_order": receipt["image_tags"],
        "source_object_order": receipt["source_object_ids"],
        "image_sha256_order": EXPECTED_IMAGE_SHA256,
        "image_url_count": 2,
        "video_url_count": 1,
        "binding_board_uploaded": False,
        "local_final_video_processing": False,
        "prompt_sha256": receipt["prompt_sha256"],
        "binding_contract_sha256": receipt["binding_contract_sha256"],
        "prompt_chars": len(prompt),
    }
    request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preview_path.write_text(json.dumps({"request_sha256": digest}, indent=2) + "\n", encoding="utf-8")
    return {"status": "prepared", "request_sha256": digest}


def submit() -> dict:
    load_env()
    validate_binding()
    payload = json.loads((RUN_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    preview = json.loads((RUN_DIR / "approval_preview.json").read_text(encoding="utf-8"))
    digest = request_sha(payload)
    if digest != preview.get("request_sha256"):
        raise RuntimeError("AUDITED_REQUEST_CHANGED")
    create_path = RUN_DIR / f"create_{digest}.json"
    if create_path.exists():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_path.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("CREATE_RESPONSE_MISSING_TASK_ID")
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
