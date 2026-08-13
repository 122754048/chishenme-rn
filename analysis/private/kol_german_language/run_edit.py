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
SOURCE_VIDEO = Path(r"C:\Users\zhaocx04\Downloads\尝试复刻的真人视频类型（有一定难度）\kol_ceylllln_6706496246289073157.mp4")
SCRIPT = WORKSPACE / "analysis" / "reverse_storyboard_script.md"
DYNAMICS = CASE_DIR / "source_dynamics_analysis.json"
RUN_DIR = CASE_DIR / "seedance_run"


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def post_json(url: str, payload: dict) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
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
    sys.path.insert(0, str(SKILL_ROOT))
    from server.production_ports import ProductionEnvironment, RunningHubSeedanceMediaUploader
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


def compile_prompt() -> dict:
    dialogue = [
        {"window": "00:00.000-00:02.000", "speaker": "SOURCE_DUO", "text": "Möchtest du auch neue Leute kennenlernen?"},
        {"window": "00:02.000-00:06.000", "speaker": "SOURCE_DUO", "text": "Du kannst Chaträumen beitreten und ganz einfach neue Freundschaften schließen."},
        {"window": "00:06.000-00:09.000", "speaker": "SOURCE_DUO", "text": "Schreib Nachrichten und chatte mit Menschen in deiner Nähe."},
        {"window": "00:09.000-00:11.000", "speaker": "SOURCE_DUO", "text": "Lade dir jetzt SUGO herunter."},
    ]
    prompt = "@Video1 将这个视频改为德语。"
    return {"prompt": prompt, "dialogue": dialogue, "compiled": {"prompt": prompt}}


def prepare() -> dict:
    load_env()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    compiled = compile_prompt()
    upload_file = RUN_DIR / "uploaded_media.json"
    if upload_file.exists():
        uploaded = json.loads(upload_file.read_text(encoding="utf-8"))
    else:
        uploaded = {"videoUrl": uploader().upload_media(SOURCE_VIDEO), "video_sha256": sha_file(SOURCE_VIDEO)}
        upload_file.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if uploaded["video_sha256"] != sha_file(SOURCE_VIDEO):
        raise RuntimeError("SOURCE_VIDEO_CHANGED")
    payload = {
        "prompt": compiled["prompt"],
        "resolution": "720p",
        "duration": "12",
        "imageUrls": [],
        "videoUrls": [uploaded["videoUrl"]],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }
    digest = sha_json(payload)
    audit = {
        "schema_version": "usfr-language-only-german/v1",
        "request_sha256": digest,
        "source_video_sha256": sha_file(SOURCE_VIDEO),
        "approved_script_sha256": sha_file(SCRIPT),
        "source_dynamics_sha256": sha_file(DYNAMICS),
        "prompt_sha256": sha_text(compiled["prompt"]),
        "output_language": "de-DE",
        "dialogue_windows": compiled["dialogue"],
        "image_reference_count": 0,
        "provider_create_calls_allowed": 1,
        "external_tts": False,
        "external_lip_sync": False,
    }
    (RUN_DIR / "prompt.txt").write_text(compiled["prompt"] + "\n", encoding="utf-8")
    (RUN_DIR / "request.redacted.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "request_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUN_DIR / "approval_preview.json").write_text(json.dumps({"request_sha256": digest, "approved_script_sha256": audit["approved_script_sha256"]}, indent=2) + "\n", encoding="utf-8")
    return {"status": "PREPARED", **audit}


def submit() -> dict:
    load_env()
    payload = json.loads((RUN_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    preview = json.loads((RUN_DIR / "approval_preview.json").read_text(encoding="utf-8"))
    digest = sha_json(payload)
    if digest != preview["request_sha256"] or sha_file(SCRIPT) != preview["approved_script_sha256"]:
        raise RuntimeError("APPROVED_AUTHORITY_CHANGED")
    create_file = RUN_DIR / f"create_{digest}.json"
    if create_file.exists():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_file.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("TASK_ID_MISSING")
    (RUN_DIR / "task_id.txt").write_text(task_id + "\n", encoding="utf-8")
    while True:
        status = post_json(os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"], {"taskId": task_id})
        (RUN_DIR / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state = str(status.get("status") or "").upper()
        print(json.dumps({"taskId": task_id, "status": state}), flush=True)
        if state == "SUCCESS":
            url = next(row["url"] for row in status["results"] if row.get("outputType") == "mp4")
            with request.urlopen(url, timeout=180) as response:
                (RUN_DIR / "result.mp4").write_bytes(response.read())
            return {"status": "SUCCESS", "taskId": task_id, "request_sha256": digest}
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError(f"PROVIDER_{state}")
        time.sleep(10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "submit"])
    args = parser.parse_args()
    result = prepare() if args.action == "prepare" else submit()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
