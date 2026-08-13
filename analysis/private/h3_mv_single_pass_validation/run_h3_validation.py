from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

from server.runninghub_workflows import RunningHubWorkflowClient


ROOT = Path(r"C:\Users\zhaocx04\Documents\New project\analysis\private\h3_mv_single_pass_validation")
ENV_PATH = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
IMAGE_PATH = ROOT / "person_asset_1024.png"
VIDEO_PATH = ROOT / "source_15s.mp4"
AUDIO_PATH = ROOT / "song_90_105s.mp3"
AUDIT_PATH = ROOT / "request_audit.json"
RESULT_PATH = ROOT / "result.mp4"


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


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=300) as response:
        data = response.read(256 * 1024 * 1024 + 1)
    if not data or len(data) > 256 * 1024 * 1024:
        raise RuntimeError("H3 result is empty or exceeds 256 MB")
    destination.write_bytes(data)


def main() -> None:
    env = load_env()
    api_key = env["RUNNINGHUB_API_KEY"]
    base_url = env.get("RUNNINGHUB_BASE_URL", "https://www.runninghub.ai").rstrip("/")
    client = RunningHubWorkflowClient(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=300,
        poll_interval_seconds=5,
    )
    image_url = client.upload_media(IMAGE_PATH)
    video_url = client.upload_media(VIDEO_PATH)
    audio_url = client.upload_media(AUDIO_PATH)
    prompt = (
        "基于视频1进行一次完整MV编辑。将视频1中唯一的金发女性完整替换为图片1中的男性，"
        "全程保持图片1的脸、发型、男性身份和黑色服装。保持视频1的镜头、海边背景、身体动作、"
        "构图、节奏和转场。人物演唱音频1中的指定歌曲，嘴唇发音、呼吸和演唱表情与音频1精确同步。"
        "输出一条连续自然的竖屏MV。"
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
    create_url = f"{base_url}/openapi/v2/minimax/hailuo-h3/multimodal-to-video"
    submitted = client._post(url=create_url, payload=payload)
    task_id = str(submitted.get("taskId") or "").strip()
    if not task_id:
        raise RuntimeError("H3 create response omitted taskId; no automatic retry")
    status = str(submitted.get("status") or "").upper()
    response = submitted
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
        "contract": "runninghub-hailuo-h3-single-pass-mv-validation/v1",
        "task_id": task_id,
        "status": status,
        "endpoint": create_url,
        "payload_without_temporary_urls": {
            **payload,
            "imageUrls": ["uploaded-person-asset"],
            "videoUrls": ["uploaded-source-15s"],
            "audioUrls": ["uploaded-song-90-105s"],
        },
        "inputs": {
            "person_asset_sha256": sha256(IMAGE_PATH),
            "source_video_sha256": sha256(VIDEO_PATH),
            "song_audio_sha256": sha256(AUDIO_PATH),
        },
        "provider_response": response,
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if status != "SUCCESS":
        raise RuntimeError(
            f"H3 task failed: {response.get('errorCode')} {response.get('errorMessage')} {response.get('failedReason')}"
        )
    results = response.get("results")
    videos = [
        item for item in (results or [])
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
