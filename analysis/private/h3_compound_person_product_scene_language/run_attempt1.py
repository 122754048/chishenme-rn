from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path

from server.runninghub_workflows import RunningHubWorkflowClient


ROOT = Path(r"C:\Users\zhaocx04\Documents\New project\analysis\private\h3_compound_person_product_scene_language")
ENV_PATH = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
SOURCE_VIDEO = Path(r"C:\Users\zhaocx04\Downloads\redpandacompress_12.mp4")
ASSET_ROOT = Path(r"C:\Users\zhaocx04\Documents\New project\analysis\private\redpanda_12_multi_replace\assets")
PERSON_ASSET = ASSET_ROOT / "01_TARGET_WOMAN_V2_SAFE.png"
PRODUCT_ASSET = ASSET_ROOT / "02_TARGET_SUNQUICK_ORANGE.png"
SCENE_ASSET = ASSET_ROOT / "03_TARGET_OPEN_OFFICE.png"
TASK_PATH = ROOT / "task_attempt1.json"
AUDIT_PATH = ROOT / "request_audit_attempt1.json"
RESULT_PATH = ROOT / "result_attempt1.mp4"


GERMAN_LINES = (
    "Schauen wir uns diese Sunquick Orange an. "
    "Die leuchtend orange Flasche fällt sofort auf. "
    "Der Deckel lässt sich einfach aufdrehen. "
    "Hier seht ihr das Etikett aus der Nähe. "
    "Wenn ihr einen vollständigen Gießtest sehen wollt, sagt Bescheid."
)


PROMPT = (
    "将视频1中的人物替换为图片1中的人物。"
    "将原商品替换为图片2中的橙汁瓶，按原动作依次展示瓶身、开盖并近距离展示标签。"
    "将背景替换为图片3中的开放办公室。"
    f"人物用德语说：{GERMAN_LINES} 人物口型与德语同步。"
    "保持视频1的镜头、手部动作和剪辑节奏。"
)


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
    with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=300) as response:
        data = response.read(256 * 1024 * 1024 + 1)
    if not data or len(data) > 256 * 1024 * 1024:
        raise RuntimeError("H3 result is empty or exceeds 256 MB")
    destination.write_bytes(data)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if TASK_PATH.exists() or AUDIT_PATH.exists() or RESULT_PATH.exists():
        raise RuntimeError("H3_COMPOUND_ATTEMPT1_ALREADY_SUBMITTED")
    for path in (SOURCE_VIDEO, PERSON_ASSET, PRODUCT_ASSET, SCENE_ASSET):
        if not path.is_file():
            raise FileNotFoundError(path)

    env = load_env()
    base_url = env.get("RUNNINGHUB_BASE_URL", "https://www.runninghub.ai").rstrip("/")
    client = RunningHubWorkflowClient(
        api_key=env["RUNNINGHUB_API_KEY"],
        base_url=base_url,
        timeout_seconds=300,
        poll_interval_seconds=5,
    )
    image_urls = [
        client.upload_media(PERSON_ASSET),
        client.upload_media(PRODUCT_ASSET),
        client.upload_media(SCENE_ASSET),
    ]
    video_url = client.upload_media(SOURCE_VIDEO)
    payload = {
        "prompt": PROMPT,
        "imageUrls": image_urls,
        "videoUrls": [video_url],
        "audioUrls": [],
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
        "contract": "runninghub-hailuo-h3-compound-person-product-scene-language/v1",
        "attempt": 1,
        "changed_variable": "first compound capability measurement",
        "task_id": task_id,
        "status": status,
        "endpoint": endpoint,
        "prompt": PROMPT,
        "index_contract": {
            "imageUrls[0]": "图片1/person",
            "imageUrls[1]": "图片2/product",
            "imageUrls[2]": "图片3/scene",
            "videoUrls[0]": "视频1/source video",
        },
        "payload_without_temporary_urls": {
            **payload,
            "imageUrls": ["uploaded-person-asset", "uploaded-product-asset", "uploaded-scene-asset"],
            "videoUrls": ["uploaded-source-video"],
        },
        "input_sha256": {
            "source_video": sha256(SOURCE_VIDEO),
            "person": sha256(PERSON_ASSET),
            "product": sha256(PRODUCT_ASSET),
            "scene": sha256(SCENE_ASSET),
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
