from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib import request


ROOT = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
PRIOR_RUN_DIR = ROOT / "four_person_once"
RUN_DIR = ROOT / "four_person_provider_only"
IDENTITY_DIR = ROOT / "identity_v3"
SOURCE_URL = "https://rh-hk-images-switch.xiaoyaoyou.com/input/openapi/bb1998e0e33d0207b93e0393a49369cc0d82b1365ae096abd296b2dde7113a8b.mp4"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def load_identity_urls() -> list[str]:
    data = json.loads((PRIOR_RUN_DIR / "identity_urls.json").read_text(encoding="utf-8"))
    urls = [str(item) for item in data["imageUrls"]]
    if len(urls) != 4:
        raise ValueError("identity URL authority must contain exactly four images")
    return urls


def prior_submitted_request_hashes() -> set[str]:
    hashes: set[str] = set()
    for path in ROOT.rglob("create_*.json"):
        match = re.fullmatch(r"create_([0-9a-f]{64})\.json", path.name)
        if match:
            hashes.add(match.group(1))
    return hashes


def request_sha(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_request() -> tuple[dict, dict]:
    sys.path.insert(0, str(SKILL_ROOT))
    from scripts.seedance_prompt_compiler import compile_provider_only_multi_subject_prompt

    bindings = [
        {
            "reference": "@Image1",
            "source_object_id": "SRC_MAN",
            "source_track_descriptor": "opening-center man in the black rainbow hoodie holding the dark phone",
            "replacement_scope": "person identity, face, hair, and skin",
            "wardrobe_policy": "replace_from_reference",
            "target_visual_anchor": "red mesh sleeveless top, bright green crossbody strap, silver chain",
        },
        {
            "reference": "@Image2",
            "source_object_id": "SRC_BLONDE",
            "source_track_descriptor": "opening-left blonde woman in the mint-green ruffle top",
            "replacement_scope": "person identity, face, hair, and skin",
            "wardrobe_policy": "replace_from_reference",
            "target_visual_anchor": "black thin-strap top and delicate pendant necklace",
        },
        {
            "reference": "@Image3",
            "source_object_id": "SRC_DARK",
            "source_track_descriptor": "opening-right dark-haired woman in the gray halter top with sunglasses on her head",
            "replacement_scope": "person identity, face, hair, and skin",
            "wardrobe_policy": "replace_from_reference",
            "target_visual_anchor": "light cream thin-strap top and pearl stud earrings",
        },
        {
            "reference": "@Image4",
            "source_object_id": "SRC_ALIEN",
            "source_track_descriptor": "gray alien-headed figure entering from frame-left at about 3.15 seconds in the black rainbow hoodie",
            "replacement_scope": "ragdoll-cat head identity",
            "wardrobe_policy": "preserve_source",
            "source_wardrobe_descriptor": "black hoodie",
        },
    ]
    compiled = compile_provider_only_multi_subject_prompt(source_video="@Video1", bindings=bindings)
    image_urls = load_identity_urls()
    payload = {
        "prompt": compiled["prompt"],
        "resolution": "720p",
        "duration": "11",
        "imageUrls": image_urls,
        "videoUrls": [SOURCE_URL],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }
    digest = request_sha(payload)
    identity_manifest = json.loads((IDENTITY_DIR / "identity_v3_manifest.json").read_text(encoding="utf-8"))
    audit = {
        "schema_version": "reinbow-four-person-provider-only/v1",
        "request_sha256": digest,
        "provider_only": True,
        "provider_create_calls": 1,
        "primary_change_variable": "positive_state_binding_v3",
        "image_tag_order": compiled["image_tags"],
        "source_object_order": compiled["source_object_ids"],
        "identity_image_sha256_order": [row["sha256"] for row in identity_manifest["assets"]],
        "image_url_count": len(image_urls),
        "video_url_count": 1,
        "binding_board_uploaded": False,
        "local_video_processing": False,
        "prompt_chars": len(payload["prompt"]),
    }
    return payload, audit


def assert_not_previously_submitted(run_dir: Path, digest: str) -> None:
    if (run_dir / f"create_{digest}.json").exists() or digest in prior_submitted_request_hashes():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()

    payload, audit = build_request()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "prompt.txt").write_text(payload["prompt"] + "\n", encoding="utf-8")
    (RUN_DIR / "request.redacted.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (RUN_DIR / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if audit["request_sha256"] in prior_submitted_request_hashes():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    if not args.submit:
        print(json.dumps({"status": "dry_run_pass", **audit}, ensure_ascii=False))
        return 0

    load_env()
    digest = audit["request_sha256"]
    assert_not_previously_submitted(RUN_DIR, digest)
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    (RUN_DIR / f"create_{digest}.json").write_text(
        json.dumps(created, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("CREATE_RESPONSE_MISSING_TASK_ID")
    while True:
        status = post_json(os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"], {"taskId": task_id})
        (RUN_DIR / "status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
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
