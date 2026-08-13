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
IMAGE_PATH = ROOT / "person_asset_1024.png"
SOURCE_VIDEO = ROOT / "source_15s.mp4"
SILENT_VIDEO = ROOT / "source_15s_silent.mp4"
MIXED_AUDIO = ROOT / "mixed_song_ui_speech_15s.wav"
TASK_PATH = ROOT / "task_silent_video_mixed_audio.json"
AUDIT_PATH = ROOT / "request_audit_silent_video_mixed_audio.json"
RESULT_PATH = ROOT / "result_silent_video_mixed_audio.mp4"


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


def prepare_silent_video() -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(SOURCE_VIDEO), "-map", "0:v:0", "-an", "-c:v", "copy",
            str(SILENT_VIDEO),
        ],
        check=True,
    )


def probe(path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,sample_rate,channels",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=300) as response:
        data = response.read(256 * 1024 * 1024 + 1)
    if not data or len(data) > 256 * 1024 * 1024:
        raise RuntimeError("H3 result is empty or exceeds 256 MB")
    destination.write_bytes(data)


def main() -> None:
    if TASK_PATH.exists() or AUDIT_PATH.exists() or RESULT_PATH.exists():
        raise RuntimeError("SILENT_VIDEO_MIXED_AUDIO_EXPERIMENT_ALREADY_SUBMITTED")
    if not SILENT_VIDEO.exists():
        prepare_silent_video()
    video_probe = probe(SILENT_VIDEO)
    audio_probe = probe(MIXED_AUDIO)
    if any(row.get("codec_type") == "audio" for row in video_probe.get("streams", [])):
        raise RuntimeError("silent source video still contains an audio stream")
    video_duration = float(video_probe["format"]["duration"])
    audio_duration = float(audio_probe["format"]["duration"])
    if not 14.99 <= video_duration <= 15.05 or not 14.99 <= audio_duration <= 15.05:
        raise RuntimeError(
            f"input duration mismatch: video={video_duration}, audio={audio_duration}"
        )

    env = load_env()
    base_url = env.get("RUNNINGHUB_BASE_URL", "https://www.runninghub.ai").rstrip("/")
    client = RunningHubWorkflowClient(
        api_key=env["RUNNINGHUB_API_KEY"],
        base_url=base_url,
        timeout_seconds=300,
        poll_interval_seconds=5,
    )
    image_url = client.upload_media(IMAGE_PATH)
    video_url = client.upload_media(SILENT_VIDEO)
    audio_url = client.upload_media(MIXED_AUDIO)
    prompt = (
        "将视频1中的人物替换为图片1中的人物。使用音频1作为完整声音：0至4秒和10至15秒"
        "演唱音频1中的歌曲，4至10秒按音频1中的口播展示UI操作。人物口型与音频1同步，"
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
        "contract": "runninghub-hailuo-h3-silent-video-mixed-audio-experiment/v1",
        "task_id": task_id,
        "status": status,
        "endpoint": endpoint,
        "prompt": prompt,
        "audio_windows": [
            {"start_ms": 0, "end_ms": 4000, "kind": "target_song", "source": "song 01:30-01:34"},
            {"start_ms": 4000, "end_ms": 10000, "kind": "source_ui_speech", "source": "source 00:04-00:10"},
            {"start_ms": 10000, "end_ms": 15000, "kind": "target_song", "source": "song 01:40-01:45"},
        ],
        "payload_without_temporary_urls": {
            **payload,
            "imageUrls": ["uploaded-person-asset"],
            "videoUrls": ["uploaded-silent-source-video"],
            "audioUrls": ["uploaded-mixed-audio"],
        },
        "inputs": {
            "person_asset_sha256": sha256(IMAGE_PATH),
            "silent_source_video_sha256": sha256(SILENT_VIDEO),
            "mixed_audio_sha256": sha256(MIXED_AUDIO),
            "silent_source_video_probe": video_probe,
            "mixed_audio_probe": audio_probe,
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
