from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from urllib import request


HERE = Path(__file__).resolve().parent
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
IDENTITY_BOARD_SHA = "437547d67d1f1f9c9efa2c609efc04d0a796bf34ac30f41977d47ba563e3eb51"
GARMENT_BOARD_SHA = "f6a9e871bd6a7e0295112d9ae631858f30cde713e157300db6204a4f83efe6e0"
IDENTITY_BOARD_URL = "https://rh-hk-images-1252422369.cos.ap-hongkong.myqcloud.com/3089a1eade4b6ac1030e8f9a8e476490/output/7bb18f3c-ceb5-4a0f-b55f-87ab13771bec.png"
GARMENT_BOARD_URL = "https://rh-hk-images-1252422369.cos.ap-hongkong.myqcloud.com/3089a1eade4b6ac1030e8f9a8e476490/output/d9996f4f-8014-438d-a0a2-611e641f413a.png"
PROMPT = (
    "Create one clean full-body studio model reference. "
    "Use the woman identity and long dark-brown hair from the first reference. "
    "Use the complete white long-sleeve cropped top and gray high-waisted leggings from the second reference. "
    "One person, standing front-facing and visible head to toe, with neutral lighting and a plain light-gray background."
)


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def canonical_sha(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def post_json(url: str, payload: dict) -> dict:
    req = request.Request(url, data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(), headers={"Authorization": f"Bearer {os.environ['RUNNINGHUB_API_KEY']}", "Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}, method="POST")
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def prepare() -> dict:
    payload = {"prompt": PROMPT, "imageUrls": [IDENTITY_BOARD_URL, GARMENT_BOARD_URL], "aspectRatio": "16:9", "resolution": "2k", "quality": "medium"}
    digest = canonical_sha(payload)
    (HERE / "woman_fullbody.request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / "woman_fullbody.preview.json").write_text(json.dumps({"request_sha256": digest}, indent=2) + "\n", encoding="utf-8")
    return {"status": "prepared", "request_sha256": digest}


def query(task_id: str) -> dict:
    base = os.environ["RUNNINGHUB_BASE_URL"].rstrip("/")
    status = post_json(base + "/openapi/v2/query", {"taskId": task_id})
    (HERE / "woman_fullbody.status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = str(status.get("status") or "").upper()
    if state == "SUCCESS":
        url = next(row["url"] for row in status["results"] if str(row.get("outputType") or "").lower() == "png")
        with request.urlopen(url, timeout=180) as response:
            data = response.read()
        output = HERE / "Image1_TARGET_WOMAN_FULLBODY_MODEL.png"
        output.write_bytes(data)
        receipt = {"schema_version": "runninghub-asset-board/v2", "asset_type": "model", "template_version": "model-fullbody-identity-wardrobe-v2", "upstream_board_sha256": [IDENTITY_BOARD_SHA, GARMENT_BOARD_SHA], "request_sha256": canonical_sha(json.loads((HERE / "woman_fullbody.request.redacted.json").read_text(encoding="utf-8"))), "task_id": task_id, "board_sha256": hashlib.sha256(data).hexdigest(), "board_url": url}
        (HERE / "Image1_TARGET_WOMAN_FULLBODY_MODEL.receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "SUCCESS", **receipt}
    return {"status": state, "task_id": task_id}


def submit() -> dict:
    load_env()
    payload = json.loads((HERE / "woman_fullbody.request.redacted.json").read_text(encoding="utf-8"))
    digest = canonical_sha(payload)
    create_path = HERE / f"woman_fullbody.create_{digest}.json"
    task_path = HERE / f"woman_fullbody.task_{digest}.txt"
    if create_path.exists() or task_path.exists():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_BASE_URL"].rstrip("/") + "/openapi/v2/rhart-image-g-2-official/image-to-image", payload)
    create_path.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("CREATE_RESPONSE_MISSING_TASK_ID")
    task_path.write_text(task_id, encoding="utf-8")
    while True:
        result = query(task_id)
        if result["status"] == "SUCCESS":
            return result
        if result["status"] in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError("ASSET_BOARD_GENERATION_FAILED")
        time.sleep(10)


def resume() -> dict:
    load_env()
    payload = json.loads((HERE / "woman_fullbody.request.redacted.json").read_text(encoding="utf-8"))
    digest = canonical_sha(payload)
    return query((HERE / f"woman_fullbody.task_{digest}.txt").read_text(encoding="utf-8").strip())


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("mode", choices=("prepare", "submit", "resume")); args = parser.parse_args()
    result = prepare() if args.mode == "prepare" else submit() if args.mode == "submit" else resume()
    print(json.dumps(result, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
