from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib import request


ROOT = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
BOARD_DIR = ROOT / "current_boards"
RUN_DIR = ROOT / "current_S01"
SOURCE_URL = "https://rh-hk-images-switch.xiaoyaoyou.com/input/openapi/bb1998e0e33d0207b93e0393a49369cc0d82b1365ae096abd296b2dde7113a8b.mp4"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def image_urls() -> list[str]:
    names = ("main_male", "blonde_woman", "dark_hair_woman", "cat_humanoid")
    return [json.loads((BOARD_DIR / f"{name}.json").read_text(encoding="utf-8"))["result_url"] for name in names]


def request_sha(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_payload() -> tuple[dict, dict]:
    sys.path.insert(0, str(SKILL_ROOT))
    from scripts.seedance_prompt_compiler import compile_provider_only_multi_subject_prompt

    bindings = [
        {
            "reference": "@Image1",
            "source_object_id": "SRC_MAN",
            "source_track_descriptor": "opening-center man in the black Reinbow hoodie holding the dark phone",
            "replacement_scope": "person identity, face, hair, and skin",
            "wardrobe_policy": "preserve_source",
            "source_wardrobe_descriptor": "black Reinbow hoodie",
        },
        {
            "reference": "@Image2",
            "source_object_id": "SRC_LEFT_WOMAN",
            "source_track_descriptor": "opening-left woman in the mint-green ruffle top",
            "replacement_scope": "person identity, face, hair, and skin",
            "wardrobe_policy": "preserve_source",
            "source_wardrobe_descriptor": "mint-green ruffle top",
        },
        {
            "reference": "@Image3",
            "source_object_id": "SRC_RIGHT_WOMAN",
            "source_track_descriptor": "opening-right woman in the gray halter top with sunglasses on her head",
            "replacement_scope": "person identity, face, hair, and skin",
            "wardrobe_policy": "preserve_source",
            "source_wardrobe_descriptor": "gray halter top",
        },
        {
            "reference": "@Image4",
            "source_object_id": "SRC_ALIEN",
            "source_track_descriptor": "gray alien-headed figure entering from frame-left at about 3.15 seconds in the black Reinbow hoodie",
            "replacement_scope": "cat head identity only",
            "wardrobe_policy": "preserve_source",
            "source_wardrobe_descriptor": "black Reinbow hoodie and human body performance",
        },
    ]
    compiled = compile_provider_only_multi_subject_prompt(source_video="@Video1", bindings=bindings)
    payload = {
        "prompt": compiled["prompt"],
        "resolution": "720p",
        "duration": "11",
        "imageUrls": image_urls(),
        "videoUrls": [SOURCE_URL],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }
    audit = {
        "schema_version": "reinbow-current-assets-s01/v1",
        "request_sha256": request_sha(payload),
        "provider_only": True,
        "source_segment": "0.00-10.48s",
        "image_tag_order": compiled["image_tags"],
        "source_object_order": compiled["source_object_ids"],
        "local_video_processing": False,
    }
    return payload, audit


def post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = request.Request(url, data=body, headers={"Authorization": f"Bearer {os.environ['RUNNINGHUB_SEEDANCE_API_KEY']}", "Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}, method="POST")
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    payload, audit = build_payload()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    digest = audit["request_sha256"]
    (RUN_DIR / "prompt.txt").write_text(payload["prompt"] + "\n", encoding="utf-8")
    (RUN_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    create_path = RUN_DIR / f"create_{digest}.json"
    if create_path.exists():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    load_env()
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
            print(json.dumps({"status": "SUCCESS", "taskId": task_id, "request_sha256": digest}, ensure_ascii=False))
            return 0
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError(f"PROVIDER_{state}")
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
