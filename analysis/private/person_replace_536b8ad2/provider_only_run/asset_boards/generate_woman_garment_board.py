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
SOURCE_SHA = "8648a9162d0cc6c75565505e4a1d56a5961ae5ecc976aef3ea088e5a2b246510"
SOURCE_URL = f"https://rh-hk-images-switch.xiaoyaoyou.com/input/openapi/{SOURCE_SHA}.png"
PROMPT = (
    "Create a four-view garment reference board: front construction, back construction, material close detail, and worn silhouette. "
    "Preserve the exact white long-sleeve ribbed cropped top, gray high-waisted fitted leggings, seams, color, fit, and proportions from the reference. "
    "Use one neutral mannequin or anonymous worn silhouette, a neutral studio background, and no additional garments or accessories."
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
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['RUNNINGHUB_API_KEY']}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def prepare() -> dict:
    payload = {
        "prompt": PROMPT,
        "imageUrls": [SOURCE_URL],
        "aspectRatio": "16:9",
        "resolution": "2k",
        "quality": "medium",
    }
    digest = canonical_sha(payload)
    (HERE / "woman_garment.prompt.txt").write_text(PROMPT + "\n", encoding="utf-8")
    (HERE / "woman_garment.request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / "woman_garment.preview.json").write_text(json.dumps({"request_sha256": digest}, indent=2) + "\n", encoding="utf-8")
    return {"status": "prepared", "request_sha256": digest}


def query_and_download(task_id: str) -> dict:
    base = os.environ["RUNNINGHUB_BASE_URL"].rstrip("/")
    status = post_json(base + "/openapi/v2/query", {"taskId": task_id})
    (HERE / "woman_garment.status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = str(status.get("status") or "").upper()
    if state == "SUCCESS":
        url = next(row["url"] for row in status["results"] if str(row.get("outputType") or "").lower() == "png")
        with request.urlopen(url, timeout=180) as response:
            data = response.read()
        output = HERE / "Image2_TARGET_WOMAN_GARMENT.png"
        output.write_bytes(data)
        receipt = {
            "schema_version": "runninghub-asset-board/v2",
            "asset_type": "garment",
            "template_version": "garment-v2",
            "source_asset_sha256": SOURCE_SHA,
            "request_sha256": canonical_sha(json.loads((HERE / "woman_garment.request.redacted.json").read_text(encoding="utf-8"))),
            "task_id": task_id,
            "board_sha256": hashlib.sha256(data).hexdigest(),
            "board_url": url,
        }
        (HERE / "Image2_TARGET_WOMAN_GARMENT.receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "SUCCESS", **receipt}
    return {"status": state, "task_id": task_id}


def submit() -> dict:
    load_env()
    payload = json.loads((HERE / "woman_garment.request.redacted.json").read_text(encoding="utf-8"))
    digest = canonical_sha(payload)
    create_path = HERE / f"woman_garment.create_{digest}.json"
    task_path = HERE / "woman_garment.task_id.txt"
    if create_path.exists() or task_path.exists():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    base = os.environ["RUNNINGHUB_BASE_URL"].rstrip("/")
    created = post_json(base + "/openapi/v2/rhart-image-g-2-official/image-to-image", payload)
    create_path.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("CREATE_RESPONSE_MISSING_TASK_ID")
    task_path.write_text(task_id, encoding="utf-8")
    while True:
        result = query_and_download(task_id)
        if result["status"] == "SUCCESS":
            return result
        if result["status"] in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError("ASSET_BOARD_GENERATION_FAILED")
        time.sleep(10)


def resume() -> dict:
    load_env()
    task_id = (HERE / "woman_garment.task_id.txt").read_text(encoding="utf-8").strip()
    return query_and_download(task_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "submit", "resume"))
    args = parser.parse_args()
    result = prepare() if args.mode == "prepare" else submit() if args.mode == "submit" else resume()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
