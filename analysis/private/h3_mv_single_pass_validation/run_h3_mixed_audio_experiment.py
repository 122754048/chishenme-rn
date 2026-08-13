from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from server.runninghub_workflows import RunningHubWorkflowClient


ROOT = Path(r"C:\Users\zhaocx04\Documents\New project\analysis\private\h3_mv_single_pass_validation")
ENV_PATH = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
SOURCE_ORIGINAL = Path(r"C:\Users\zhaocx04\Downloads\社交AI视频\MV.mp4")
SONG_ORIGINAL = Path(r"C:\Users\zhaocx04\Downloads\修炼爱情.mp3")
IMAGE_PATH = ROOT / "person_asset_1024.png"
VIDEO_PATH = ROOT / "source_15s.mp4"
MIXED_AUDIO_PATH = ROOT / "mixed_song_ui_speech_15s.wav"
TASK_PATH = ROOT / "task_mixed_audio.json"
AUDIT_PATH = ROOT / "request_audit_mixed_audio.json"
RESULT_PATH = ROOT / "result_mixed_audio.mp4"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def build_mixed_audio() -> None:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", "90", "-t", "4", "-i", str(SONG_ORIGINAL),
        "-ss", "4", "-t", "6", "-i", str(SOURCE_ORIGINAL),
        "-ss", "100", "-t", "5", "-i", str(SONG_ORIGINAL),
        "-filter_complex",
        "[0:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,atrim=0:4,asetpts=PTS-STARTPTS[a0];"
        "[1:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,atrim=0:6,asetpts=PTS-STARTPTS[a1];"
        "[2:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,atrim=0:5,asetpts=PTS-STARTPTS[a2];"
        "[a0][a1][a2]concat=n=3:v=0:a=1[out]",
        "-map", "[out]", "-c:a", "pcm_s16le", str(MIXED_AUDIO_PATH),
    ]
    subprocess.run(command, check=True)


def probe_duration(path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(completed.stdout.strip())


def download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=300) as response:
        data = response.read(256 * 1024 * 1024 + 1)
    if not data or len(data) > 256 * 1024 * 1024:
        raise RuntimeError("H3 result is empty or exceeds 256 MB")
    destination.write_bytes(data)


def main() -> None:
    if TASK_PATH.exists() or AUDIT_PATH.exists() or RESULT_PATH.exists():
        raise RuntimeError("MIXED_AUDIO_EXPERIMENT_ALREADY_SUBMITTED")
    if not MIXED_AUDIO_PATH.exists():
        build_mixed_audio()
    duration = probe_duration(MIXED_AUDIO_PATH)
    if not 14.99 <= duration <= 15.05:
        raise RuntimeError(f"mixed audio duration is invalid: {duration}")

    env = load_env()
    base_url = env.get("RUNNINGHUB_BASE_URL", "https://www.runninghub.ai").rstrip("/")
    client = RunningHubWorkflowClient(
        api_key=env["RUNNINGHUB_API_KEY"],
        base_url=base_url,
        timeout_seconds=300,
        poll_interval_seconds=5,
    )
    image_url = client.upload_media(IMAGE_PATH)
    video_url = client.upload_media(VIDEO_PATH)
    audio_url = client.upload_media(MIXED_AUDIO_PATH)
    prompt = (
        "将视频1中的人物替换为图片1中的人物。人物在0至4秒和10至15秒演唱音频1中的歌曲，"
        "口型与歌曲同步；4至10秒保持视频1的UI操作，并说音频1中该时段的原口播，口型与口播同步。"
        "保持视频1的镜头、动作、背景和剪辑节奏。"
    )
    payload = {
        "prompt": prompt,
        "imageUrls": [image_url],
        "videoUrls": [video_url],
        "audioUrls": [audio_url],
        "resolution": "768P",
        "duration": "15",
        "ratio": "adaptive",
    }
    endpoint = f"{base_url}/openapi/v2/minimax/hailuo-h3/multimodal-to-video"
    submitted = client._post(url=endpoint, payload=payload)
    task_id = str(submitted.get("taskId") or "").strip()
    if not task_id:
        raise RuntimeError("H3 create response omitted taskId; no automatic retry")
    TASK_PATH.write_text(
        json.dumps({"task_id": task_id, "submitted": submitted}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    response = submitted
    status = str(response.get("status") or "").upper()
    deadline = time.monotonic() + 1800
    while status not in {"SUCCESS", "FAILED"}:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"H3 task {task_id} did not finish within 1800 seconds")
        time.sleep(5)
        response = client._post(
            url=f"{base_url}/openapi/v2/query",
            payload={"taskId": task_id},
        )
        status = str(response.get("status") or "").upper()

    audit = {
        "contract": "runninghub-hailuo-h3-mixed-song-ui-speech-experiment/v1",
        "task_id": task_id,
        "status": status,
        "endpoint": endpoint,
        "prompt": prompt,
        "audio_windows": [
            {"start_ms": 0, "end_ms": 4000, "kind": "song", "source": "song 01:30-01:34"},
            {"start_ms": 4000, "end_ms": 10000, "kind": "source_ui_speech", "source": "video1 00:04-00:10"},
            {"start_ms": 10000, "end_ms": 15000, "kind": "song", "source": "song 01:40-01:45"},
        ],
        "payload_without_temporary_urls": {
            **payload,
            "imageUrls": ["uploaded-person-asset"],
            "videoUrls": ["uploaded-source-15s"],
            "audioUrls": ["uploaded-mixed-audio"],
        },
        "inputs": {
            "person_asset_sha256": sha256(IMAGE_PATH),
            "source_video_sha256": sha256(VIDEO_PATH),
            "mixed_audio_sha256": sha256(MIXED_AUDIO_PATH),
            "mixed_audio_duration": duration,
        },
        "provider_response": response,
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if status != "SUCCESS":
        raise RuntimeError(
            f"H3 task failed: {response.get('errorCode')} "
            f"{response.get('errorMessage')} {response.get('failedReason')}"
        )
    videos = [
        item for item in (response.get("results") or [])
        if isinstance(item, dict)
        and str(item.get("outputType") or "").lower() in {"mp4", "mov"}
        and str(item.get("url") or "").startswith("https://")
    ]
    if len(videos) != 1:
        raise RuntimeError(f"H3 expected exactly one video output, received {len(videos)}")
    download(str(videos[0]["url"]), RESULT_PATH)
    print(json.dumps({
        "taskId": task_id,
        "status": status,
        "result": str(RESULT_PATH),
        "sha256": sha256(RESULT_PATH),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
