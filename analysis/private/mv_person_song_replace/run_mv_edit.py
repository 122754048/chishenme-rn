from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib import request

from PIL import Image, ImageFilter, ImageOps


RUN_DIR = Path(__file__).resolve().parent
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
SOURCE = Path(r"C:\Users\zhaocx04\Downloads\社交AI视频\MV.mp4")
SONG = Path(r"C:\Users\zhaocx04\Downloads\修炼爱情.mp3")
PERSON_SOURCE = Path(r"C:\Users\zhaocx04\Downloads\repainting_1728631015039_.png")
PERSON_ASSET = RUN_DIR / "target_man_identity_v3.png"
SOURCE_EDIT = RUN_DIR / "source_edit_0_15.mp4"
SONG_WINDOW = RUN_DIR / "song_01m30s_17p033s.wav"
PROVIDER_RESULT = RUN_DIR / "provider_result.mp4"
FINAL_RESULT = RUN_DIR / "result.mp4"
SOURCE_DURATION = 17.033333
SEEDANCE_DURATION = 15.0
SONG_OFFSET = 90.0


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


def canonical_sha(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def run_ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def prepare_media() -> dict[str, str]:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(PERSON_SOURCE) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    background = ImageOps.fit(source, (1024, 1024), method=Image.Resampling.LANCZOS).filter(
        ImageFilter.GaussianBlur(24)
    )
    foreground = source.copy()
    foreground.thumbnail((900, 1024), Image.Resampling.LANCZOS)
    x = (1024 - foreground.width) // 2
    y = (1024 - foreground.height) // 2
    background.paste(foreground, (x, y))
    background.save(PERSON_ASSET, format="PNG", optimize=True)

    run_ffmpeg("-i", str(SOURCE), "-t", f"{SEEDANCE_DURATION:.3f}", "-map", "0:v:0", "-an", "-c:v", "copy", SOURCE_EDIT.as_posix())
    run_ffmpeg(
        "-ss", f"{SONG_OFFSET:.3f}", "-t", f"{SOURCE_DURATION:.6f}", "-i", str(SONG),
        "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", SONG_WINDOW.as_posix(),
    )
    manifest = {
        "schema_version": "usfr-mv-person-song-assets/v1",
        "source_video_sha256": sha256_file(SOURCE),
        "source_edit_sha256": sha256_file(SOURCE_EDIT),
        "song_source_sha256": sha256_file(SONG),
        "song_window_sha256": sha256_file(SONG_WINDOW),
        "song_start_seconds": SONG_OFFSET,
        "song_end_seconds": round(SONG_OFFSET + SOURCE_DURATION, 6),
        "person_source_sha256": sha256_file(PERSON_SOURCE),
        "person_asset_sha256": sha256_file(PERSON_ASSET),
        "person_asset_profile": "model-identity-v3-local-crop",
        "asset_mime_type": "image/png",
        "asset_width": 1024,
        "asset_height": 1024,
        "identity_subject_count": 1,
        "asset_layout": "identity_dominant",
        "asset_composition": "full_body_square",
        "wardrobe_policy": "identity_and_wardrobe_from_reference",
        "target_wardrobe_evidence": "visible",
    }
    (RUN_DIR / "asset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def environment() -> object:
    sys.path.insert(0, str(SKILL_ROOT))
    from server.production_ports import ProductionEnvironment

    return ProductionEnvironment(
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
    )


def compile_prompt(manifest: dict[str, str]) -> dict[str, object]:
    sys.path.insert(0, str(SKILL_ROOT))
    from scripts.seedance_prompt_compiler import compile_edit_prompt

    binding = {
        "tag": "TARGET_MAN",
        "reference": "@Image1",
        "role": "model",
        "asset_type": "model",
        "replaces_tag": "SRC_PERFORMER",
        "source_object_descriptor": (
            "the blonde woman in the opening beach performance, her upload-photo thumbnails in the App interface, "
            "and the same generated performer returning at 10 seconds"
        ),
        "target_identity_descriptor": (
            "young man with swept black hair, defined dark brows, black layered long coat and knitwear, "
            "silver chains and dark accessories"
        ),
        "replacement_scope": "identity_and_wardrobe",
        "preserve_scope": (
            "source body motion, singing performance, camera, beach, App layout, UI operation, timing, overlays, "
            "visible text and brand tail"
        ),
        "binding_confidence": 0.99,
        "identity_scope": "face_hair_skin_body_wardrobe",
        "wardrobe_policy": "identity_and_wardrobe_from_reference",
        "target_wardrobe_evidence": "visible",
        "person_asset_profile": manifest["person_asset_profile"],
        "asset_mime_type": manifest["asset_mime_type"],
        "asset_width": manifest["asset_width"],
        "asset_height": manifest["asset_height"],
        "identity_subject_count": manifest["identity_subject_count"],
        "asset_layout": manifest["asset_layout"],
        "asset_composition": manifest["asset_composition"],
    }
    compiled = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[binding],
        replacements=[{
            "change_id": "PERSON-01",
            "window": "00:00.000-00:15.000",
            "target": "TARGET_MAN",
            "asset_type": "model",
            "execution_mode": "direct_binding",
            "instruction": "replace the approved continuing performer identity and wardrobe",
        }],
        dialogue_changes=[],
        segment_window_ms=(0, 15000),
    )
    prompt = str(compiled["prompt"]).strip() + " Keep every source UI element, visible text, subtitle, logo and CTA unchanged."
    (RUN_DIR / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    return {"prompt": prompt, "compiled": compiled, "binding": binding}


def post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
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
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("PROVIDER_RESPONSE_INVALID")
    return value


def prepare_request() -> dict[str, object]:
    load_env()
    manifest = prepare_media()
    compiled = compile_prompt(manifest)
    from server.production_ports import RunningHubSeedanceMediaUploader

    uploader = RunningHubSeedanceMediaUploader(environment())
    image_url = uploader.upload_media(PERSON_ASSET)
    video_url = uploader.upload_media(SOURCE_EDIT)
    payload = {
        "prompt": compiled["prompt"],
        "resolution": "720p",
        "duration": "15",
        "imageUrls": [image_url],
        "videoUrls": [video_url],
        "audioUrls": [],
        "generateAudio": False,
        "ratio": "9:16",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }
    digest = canonical_sha(payload)
    receipt = compiled["compiled"].get("provider_only_binding_receipt")
    audit = {
        "schema_version": "usfr-mv-person-song-request-audit/v1",
        "request_sha256": digest,
        "prompt_sha256": hashlib.sha256((compiled["prompt"] + "\n").encode("utf-8")).hexdigest(),
        "image_tag_order": ["@Image1"],
        "source_object_order": ["SRC_PERFORMER"],
        "person_asset_sha256": manifest["person_asset_sha256"],
        "source_edit_sha256": manifest["source_edit_sha256"],
        "song_window_sha256": manifest["song_window_sha256"],
        "song_windows": [
            {"video_start": 0, "video_end": 4, "song_start": "01:30", "song_end": "01:34"},
            {"video_start": 10, "video_end": 15, "song_start": "01:40", "song_end": "01:45"},
        ],
        "provider_only_binding_receipt": receipt,
        "preserve_visible_text": True,
        "create_calls_allowed": {"seedance": 1, "song_lip_sync_segments": 2},
    }
    (RUN_DIR / "request.redacted.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RUN_DIR / "request_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"status": "prepared", "request_sha256": digest, "audit": audit}


def submit_seedance() -> dict[str, object]:
    load_env()
    payload = json.loads((RUN_DIR / "request.redacted.json").read_text(encoding="utf-8"))
    audit = json.loads((RUN_DIR / "request_audit.json").read_text(encoding="utf-8"))
    digest = canonical_sha(payload)
    if digest != audit.get("request_sha256"):
        raise RuntimeError("AUDITED_REQUEST_CHANGED")
    create_path = RUN_DIR / f"seedance_create_{digest}.json"
    if create_path.exists():
        raise RuntimeError("UNCHANGED_REQUEST_ALREADY_SUBMITTED")
    created = post_json(os.environ["RUNNINGHUB_SEEDANCE_CREATE_URL"], payload)
    create_path.write_text(json.dumps(created, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise RuntimeError("CREATE_RESPONSE_MISSING_TASK_ID")
    while True:
        status = post_json(os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"], {"taskId": task_id})
        (RUN_DIR / "seedance_status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        state = str(status.get("status") or "").upper()
        if state == "SUCCESS":
            results = status.get("results")
            if not isinstance(results, list):
                raise RuntimeError("PROVIDER_RESULTS_MISSING")
            video_url = next(str(row["url"]) for row in results if isinstance(row, dict) and row.get("outputType") == "mp4")
            with request.urlopen(video_url, timeout=180) as response:
                PROVIDER_RESULT.write_bytes(response.read())
            return {"status": "SUCCESS", "taskId": task_id, "request_sha256": digest}
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError(f"PROVIDER_{state}")
        time.sleep(10)


def run_lip_sync_and_assemble() -> dict[str, object]:
    load_env()
    if not PROVIDER_RESULT.is_file():
        raise RuntimeError("PROVIDER_RESULT_MISSING")
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))
    segment_a = RUN_DIR / "provider_person_00_04.mp4"
    segment_b = RUN_DIR / "provider_person_10_15.mp4"
    run_ffmpeg("-ss", "0", "-t", "4", "-i", str(PROVIDER_RESULT), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", segment_a.as_posix())
    run_ffmpeg("-ss", "10", "-t", "5", "-i", str(PROVIDER_RESULT), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", segment_b.as_posix())

    from server.runninghub_workflows import RunningHubWorkflowClient

    client = RunningHubWorkflowClient(
        api_key=os.environ["RUNNINGHUB_API_KEY"],
        base_url=os.environ["RUNNINGHUB_BASE_URL"],
        timeout_seconds=1800,
        poll_interval_seconds=10,
    )
    response = client.run_song_lip_sync_segments(
        uploaded_audio_kind="song",
        audio_path=SONG,
        segments=[
            {"segment_id": "SING-01", "segment_type": "generated_person", "video_path": str(segment_a), "song_start": "01:30", "song_end": "01:34"},
            {"segment_id": "SING-02", "segment_type": "generated_person", "video_path": str(segment_b), "song_start": "01:40", "song_end": "01:45"},
        ],
    )
    output_by_id: dict[str, Path] = {}
    receipts: list[dict[str, object]] = []
    for row in response["segments"]:
        output = RUN_DIR / f"{row['segment_id']}_lip_sync.mp4"
        output.write_bytes(row["video_bytes"])
        output_by_id[str(row["segment_id"])] = output
        receipts.append(dict(row["receipt"]))
    (RUN_DIR / "song_lip_sync_receipts.json").write_text(
        json.dumps(receipts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    middle = RUN_DIR / "provider_04_10.mp4"
    tail = RUN_DIR / "source_15_17p033.mp4"
    run_ffmpeg("-ss", "4", "-t", "6", "-i", str(PROVIDER_RESULT), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", middle.as_posix())
    run_ffmpeg("-ss", "15", "-t", f"{SOURCE_DURATION - 15:.6f}", "-i", str(SOURCE), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", tail.as_posix())
    video_only = RUN_DIR / "assembled_video_only.mp4"
    run_ffmpeg(
        "-i", str(output_by_id["SING-01"]), "-i", str(middle), "-i", str(output_by_id["SING-02"]), "-i", str(tail),
        "-filter_complex",
        "[0:v]fps=30,scale=1080:1920,setsar=1[v0];[1:v]fps=30,scale=1080:1920,setsar=1[v1];"
        "[2:v]fps=30,scale=1080:1920,setsar=1[v2];[3:v]fps=30,scale=1080:1920,setsar=1[v3];"
        "[v0][v1][v2][v3]concat=n=4:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", video_only.as_posix(),
    )
    run_ffmpeg(
        "-i", str(video_only), "-i", str(SONG_WINDOW), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", FINAL_RESULT.as_posix(),
    )
    result = {
        "schema_version": "usfr-mv-person-song-result/v1",
        "result_path": str(FINAL_RESULT),
        "result_sha256": sha256_file(FINAL_RESULT),
        "provider_result_sha256": sha256_file(PROVIDER_RESULT),
        "song_window_sha256": sha256_file(SONG_WINDOW),
        "lip_sync_segment_sha256s": {key: sha256_file(path) for key, path in output_by_id.items()},
    }
    (RUN_DIR / "result_receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "submit", "finish"))
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare_request()
    elif args.action == "submit":
        result = submit_seedance()
    else:
        result = run_lip_sync_and_assemble()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
