from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib import request


ROOT = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
RUN_DIR = ROOT / "four_person_once"
IDENTITY_DIR = ROOT / "identity_v3"
BINDING_BOARD = ROOT / "spatial_binding_board_v1.png"
SOURCE_URL = "https://rh-hk-images-switch.xiaoyaoyou.com/input/openapi/bb1998e0e33d0207b93e0393a49369cc0d82b1365ae096abd296b2dde7113a8b.mp4"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


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


def request_sha(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    load_env()
    sys.path.insert(0, str(SKILL_ROOT))
    from server.production_ports import ProductionEnvironment, RunningHubSeedanceMediaUploader
    from scripts.seedance_prompt_compiler import compile_edit_prompt

    def make_uploader() -> RunningHubSeedanceMediaUploader:
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

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((IDENTITY_DIR / "identity_v3_manifest.json").read_text(encoding="utf-8"))
    url_file = RUN_DIR / "identity_urls.json"
    if url_file.exists():
        image_urls = json.loads(url_file.read_text(encoding="utf-8"))["imageUrls"]
    else:
        uploader = make_uploader()
        image_urls = [uploader.upload_media(Path(row["identity_path"])) for row in manifest["assets"]]
        url_file.write_text(json.dumps({"imageUrls": image_urls}, indent=2) + "\n", encoding="utf-8")

    board_manifest = json.loads(BINDING_BOARD.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    board_url_file = RUN_DIR / "spatial_binding_board_url.json"
    if board_url_file.exists():
        board_url = str(json.loads(board_url_file.read_text(encoding="utf-8"))["imageUrl"])
    else:
        board_url = make_uploader().upload_media(BINDING_BOARD)
        board_url_file.write_text(json.dumps({"imageUrl": board_url}, indent=2) + "\n", encoding="utf-8")

    bindings = [
        {
            "tag": tag,
            "reference": f"@Image{index}",
            "role": "model",
            "asset_type": "model",
            "replaces_tag": source_id,
            "source_object_descriptor": descriptor,
            "target_identity_descriptor": target_descriptor,
            "replacement_scope": scope,
            "preserve_scope": preserve,
            "binding_confidence": confidence,
            "identity_scope": "face_hair_skin",
        }
        for index, (tag, source_id, descriptor, target_descriptor, scope, preserve, confidence) in enumerate((
            ("TARGET_MAN", "SRC_MAN", "SRC_MAN: first frame center; black rainbow-circle hoodie; holds dark phone; later screen-right with red phone", "young Black man; very short shaved buzz cut; dark-brown skin; long oval face; strong brows; narrow dark eyes; broad lips; faint moustache", "face_hair_skin", "source hoodie, body, performance, hands, phones and motion", 0.99),
            ("TARGET_BLONDE", "SRC_BLONDE", "SRC_BLONDE: first frame left; long blonde hair; mint-green ruffle top", "young fair-skinned woman; long voluminous warm-blonde hair; high side-swept crown; hazel-green eyes; arched brows; defined pink-red lips", "face_hair_skin", "source mint-green clothes, body, position, gestures and motion", 0.98),
            ("TARGET_DARK", "SRC_DARK", "SRC_DARK: first frame right; long dark hair; sunglasses on head; gray halter top", "young fair-skinned woman; chin-length dark-brown curls; brown eyes; freckles across forehead, nose and cheeks; pearl stud earrings", "face_hair_skin", "source gray clothes, body, position, gestures and motion", 0.98),
            ("TARGET_CAT", "SRC_ALIEN", "SRC_ALIEN: enters from frame left at 3.15s; gray large-eye alien head; black rainbow-circle hoodie", "realistic ragdoll cat head; blue eyes; pink nose; white muzzle and forehead blaze; dark seal-point ears and eye mask", "head_identity_only", "source human-scale body, hoodie, hands, phone contact and motion", 0.99),
        ), start=1)
    ]
    compiled = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=bindings,
        replacements=[],
        dialogue_changes=[],
        segment_window_ms=(0, 10480),
    )
    prompt = compiled["prompt"] + (
        " Apply all four Subject-to-source replacements for the full source window. "
        "TARGET_CAT changes only the alien head to the realistic ragdoll-cat head from @Image4; keep human neck, limbs, hands and upright scale."
        " @Image5 is the spatial binding map only: left TARGET_BLONDE maps to SRC_BLONDE; center TARGET_MAN maps to SRC_MAN; right TARGET_DARK maps to SRC_DARK; later-left TARGET_CAT maps to SRC_ALIEN. @Image5 supplies mapping only, no independent identity, wardrobe, motion, camera, background or style."
    )
    payload = {
        "prompt": prompt,
        "resolution": "720p",
        "duration": "11",
        "imageUrls": [*image_urls, board_url],
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
    audit = {
        "schema_version": "reinbow-four-person-once/v1",
        "request_sha256": digest,
        "prompt_chars": len(prompt),
        "subject_order": [row["tag"] for row in bindings],
        "source_object_order": [row["replaces_tag"] for row in bindings],
        "identity_image_sha256_order": [row["sha256"] for row in manifest["assets"]],
        "binding_board_sha256": board_manifest["sha256"],
        "realPersonMode": payload["realPersonMode"],
        "conversionSlots": payload["conversionSlots"],
        "audio_policy": compiled["audio_policy"],
    }
    (RUN_DIR / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    (RUN_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert len(image_urls) == 4
    assert len(payload["imageUrls"]) == 5
    assert [row["reference"] for row in bindings] == ["@Image1", "@Image2", "@Image3", "@Image4"]
    assert all(f"Subject {i}@Image{i} replaces " in prompt for i in range(1, 5))
    assert "@Image5 is the spatial binding map only" in prompt
    assert len(prompt) <= 2500
    if not args.submit:
        print(json.dumps({"status": "dry_run_pass", **audit}, ensure_ascii=False))
        return 0

    create_file = RUN_DIR / f"create_{digest}.json"
    if create_file.exists():
        raise SystemExit("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_file.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise SystemExit("CREATE_RESPONSE_MISSING_TASK_ID")
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
            raise SystemExit(f"PROVIDER_{state}")
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
