"""Run all three public endpoints over a real local TCP socket.

This smoke test is for hosts without Docker. It validates HTTP/OpenAPI,
idempotency, job-scoped bearer auth, both reviews, and final MP4 download.
The container E2E remains the deployment-level worker/object-store test.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

import fakeredis
from PIL import Image
import uvicorn

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.public_fastapi_router import create_public_app
from server.job_models import ArtifactRef
from server.redis_job_store import RedisEphemeralJobStore
from server.review_models import RevisionManifest, StoryboardCutRef
from server.visible_text_contract import visible_text_locks_sha256


class ReviewObjectStore:
    def __init__(self, root: Path, public_base_url: str) -> None:
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self.objects[key] = data
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def download_to(self, *, object_key: str, destination: Path, expected_sha256: str) -> Path:
        data = self.objects[object_key]
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise RuntimeError("review object hash mismatch")
        destination.write_bytes(data)
        return destination

    def signed_get(self, *, object_key: str, expires_seconds: int) -> str:
        del expires_seconds
        return f"{self.public_base_url}/{object_key}"


class ImmediateReviewDriver:
    def __init__(self, jobs: RedisEphemeralJobStore, objects: ReviewObjectStore, result_url: str) -> None:
        self.jobs = jobs
        self.objects = objects
        self.result_url = result_url

    def enqueue_next(self, job_id: str) -> None:
        snapshot = self.jobs.get_job(job_id)
        if snapshot is None:
            raise RuntimeError("job disappeared")
        script = self.jobs.get_current_revision(job_id, "script")
        storyboard = self.jobs.get_current_revision(job_id, "storyboard")
        if script is None:
            timeline = {
                "contract": "source-content-timeline/v1",
                "visible_text": [],
                "audio_lines": [],
            }
            timeline_body = json.dumps(timeline, ensure_ascii=False, sort_keys=True).encode("utf-8")
            timeline_key = f"temporary/{job_id}/source-content-timeline.json"
            timeline_digest = self.objects.put(timeline_key, timeline_body)
            self.jobs.put_artifact(
                job_id=job_id,
                artifact=ArtifactRef(
                    f"source-content-timeline-{job_id}",
                    "source_content_timeline",
                    timeline_key,
                    timeline_digest,
                    "application/json",
                    len(timeline_body),
                ),
            )
            locks: list[dict[str, Any]] = []
            body = json.dumps(
                {
                    "cuts": [
                        {
                            "cut_id": "C01",
                            "start_ms": 0,
                            "end_ms": 800,
                            "scene": "creator scene",
                            "action": "presents replacement product",
                            "camera": "medium close-up",
                            "dialogue": "Try the replacement product",
                            "delivery": "natural",
                        }
                    ],
                    "visible_text_locks": locks,
                    "visible_text_locks_sha256": visible_text_locks_sha256(locks),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            key = f"temporary/{job_id}/reviews/script-1.json"
            digest = self.objects.put(key, body)
            self.jobs.append_revision(
                job_id=job_id,
                kind="script",
                expected_version=snapshot.version,
                manifest=RevisionManifest(
                    kind="script",
                    revision=1,
                    object_key=key,
                    sha256=digest,
                    inputs_sha256="1" * 64,
                    created_at=datetime.now(UTC).isoformat(),
                ),
                invalidate_downstream=True,
                ttl_seconds=3600,
            )
            return
        if snapshot.approved_script_sha256 == script.sha256 and storyboard is None:
            image_key = f"temporary/{job_id}/reviews/storyboard-1.png"
            image_path = self.objects.root / image_key
            image_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (180, 320), "#1f6feb").save(image_path, format="PNG")
            image_bytes = image_path.read_bytes()
            image_digest = self.objects.put(image_key, image_bytes)
            manifest_body = json.dumps({"cuts": [{"cut_id": "C01", "object_key": image_key}]}).encode()
            manifest_key = f"temporary/{job_id}/reviews/storyboard-1.json"
            manifest_digest = self.objects.put(manifest_key, manifest_body)
            current = self.jobs.get_job(job_id)
            self.jobs.append_revision(
                job_id=job_id,
                kind="storyboard",
                expected_version=current.version,
                manifest=RevisionManifest(
                    kind="storyboard",
                    revision=1,
                    object_key=manifest_key,
                    sha256=manifest_digest,
                    inputs_sha256="2" * 64,
                    created_at=datetime.now(UTC).isoformat(),
                    parent_script_sha256=script.sha256,
                    cut_images=(
                        StoryboardCutRef("C01", image_key, image_digest, 180, 320),
                    ),
                ),
                invalidate_downstream=True,
                ttl_seconds=3600,
            )
            return
        if storyboard is not None and snapshot.approved_storyboard_sha256 == storyboard.sha256:
            current = self.jobs.get_job(job_id)
            self.jobs.cas_transition(
                job_id=job_id,
                expected_version=current.version,
                command="local-http-smoke-complete",
                updates={
                    "state": "SUCCEEDED",
                    "final_ref": {
                        "object_key": f"usfr/final/{job_id}/result.mp4",
                        "sha256": "f" * 64,
                        "content_type": "video/mp4",
                        "size_bytes": 1,
                        "metadata": {"public_url": self.result_url},
                    },
                },
                ttl_seconds=3600,
            )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_request(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(
        f"{base_url}{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _make_result(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=180x320:r=30:d=0.8",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=550:sample_rate=48000:duration=0.8",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="usfr-local-http-") as directory:
        root = Path(directory)
        result = root / "result.mp4"
        _make_result(result)
        static_port = _free_port()
        from functools import partial
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

        static_server = ThreadingHTTPServer(
            ("127.0.0.1", static_port),
            partial(SimpleHTTPRequestHandler, directory=str(root)),
        )
        static_thread = threading.Thread(target=static_server.serve_forever, daemon=True)
        static_thread.start()

        redis = fakeredis.FakeRedis(decode_responses=False)
        jobs = RedisEphemeralJobStore(redis, prefix="local-http-smoke")
        static_base = f"http://127.0.0.1:{static_port}"
        objects = ReviewObjectStore(root, static_base)
        driver = ImmediateReviewDriver(jobs, objects, f"{static_base}/result.mp4")
        app = create_public_app(
            job_store=jobs,
            capability_secret=b"local-http-smoke-secret-32-bytes!",
            stage_driver=driver,
            object_store=objects,
            ttl_seconds=3600,
        )
        api_port = _free_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning")
        server = uvicorn.Server(config)
        api_thread = threading.Thread(target=server.run, daemon=True)
        api_thread.start()
        base_url = f"http://127.0.0.1:{api_port}"
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("local HTTP server did not start")

        status, openapi = _json_request(base_url, "GET", "/openapi.json")
        expected_paths = {
            "/api/v1/jobs",
            "/api/v1/jobs/{job_id}",
            "/api/v1/jobs/{job_id}/review",
        }
        if status != 200 or set(openapi.get("paths") or {}) != expected_paths:
            raise RuntimeError("public OpenAPI contract mismatch")

        payload = {
            "source_video": "https://bucket.oss-cn-hangzhou.aliyuncs.com/source.mp4",
            "new_model_images": ["https://bucket.oss-cn-hangzhou.aliyuncs.com/model.jpg"],
        }
        key = str(uuid.uuid4())
        status, created = _json_request(base_url, "POST", "/api/v1/jobs", payload=payload, idempotency_key=key)
        if status != 202:
            raise RuntimeError(created)
        replay_status, replay = _json_request(base_url, "POST", "/api/v1/jobs", payload=payload, idempotency_key=key)
        if replay_status != 202 or replay != created:
            raise RuntimeError("idempotent create replay failed")
        job_id, token = created["job_id"], created["access_token"]
        denied_status, denied = _json_request(base_url, "GET", f"/api/v1/jobs/{job_id}", token="wrong-token")
        if denied_status not in {401, 403} or denied.get("code") != "ACCESS_DENIED":
            raise RuntimeError("job-scoped token rejection failed")

        reviews = []
        while True:
            query_status, snapshot = _json_request(base_url, "GET", f"/api/v1/jobs/{job_id}", token=token)
            if query_status != 200:
                raise RuntimeError(snapshot)
            if snapshot["status"] == "completed":
                with urlopen(snapshot["result_url"], timeout=10) as response:
                    downloaded = response.read()
                if not downloaded:
                    raise RuntimeError("result URL returned no bytes")
                break
            review = snapshot.get("review")
            if review:
                reviews.append(review["type"])
                approve_status, _ = _json_request(
                    base_url,
                    "POST",
                    f"/api/v1/jobs/{job_id}/review",
                    payload={"action": "approve"},
                    token=token,
                )
                if approve_status != 202:
                    raise RuntimeError("review approval failed")
            time.sleep(0.05)
        if reviews != ["script", "storyboard"]:
            raise RuntimeError(f"review order mismatch: {reviews}")

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(result)],
            capture_output=True,
            text=True,
            check=True,
        )
        if float(json.loads(probe.stdout)["format"]["duration"]) <= 0:
            raise RuntimeError("final MP4 is not playable")

        server.should_exit = True
        api_thread.join(timeout=5)
        static_server.shutdown()
        static_thread.join(timeout=5)
    print("local public HTTP smoke passed: create/query/review, auth, idempotency, playable result")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
