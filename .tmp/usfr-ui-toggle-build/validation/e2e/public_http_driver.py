"""Black-box validation of the deliberately small public USFR HTTP API."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

import boto3


API = os.getenv("USFR_E2E_API", "http://api:8080").rstrip("/")
BUCKET = os.getenv("USFR_S3_BUCKET", "usfr-media")
S3_ENDPOINT = os.getenv("USFR_S3_ENDPOINT", "http://minio:9000")
PUBLIC_SOURCE_HOST = "e2e-oss.example"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])
    return result


def _clip(path: Path, *, color: str, frequency: int, duration: float) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=180x320:r=30:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    )


def _request(
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
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(
        f"{API}{path}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read()
            return response.status, json.loads(body.decode("utf-8")) if body else {}
    except HTTPError as exc:
        body = exc.read()
        return exc.code, json.loads(body.decode("utf-8")) if body else {}


def _wait_ready(timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{API}/readyz", timeout=5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            pass
        time.sleep(1)
    raise TimeoutError("USFR public API did not become ready")


def _ensure_bucket(client: Any) -> None:
    try:
        client.head_bucket(Bucket=BUCKET)
    except Exception:
        client.create_bucket(Bucket=BUCKET)
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{BUCKET}/*"],
            }
        ],
    }
    client.put_bucket_policy(Bucket=BUCKET, Policy=json.dumps(policy))


def _upload(client: Any, path: Path, key: str) -> str:
    client.upload_file(str(path), BUCKET, key, ExtraArgs={"ContentType": "video/mp4"})
    return f"https://{PUBLIC_SOURCE_HOST}/{key}"


def _assert_public_openapi() -> None:
    status, schema = _request("GET", "/openapi.json")
    if status != 200:
        raise RuntimeError("OpenAPI document is unavailable")
    expected = {
        "/api/v1/jobs",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/review",
    }
    if set(schema.get("paths") or {}) != expected:
        raise RuntimeError(f"public OpenAPI exposes unexpected paths: {sorted(schema.get('paths') or {})}")


def _download(url: str, destination: Path) -> None:
    with urlopen(url, timeout=30) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    if destination.stat().st_size == 0:
        raise RuntimeError("downloaded result is empty")


def _assert_playable(path: Path) -> None:
    probe = json.loads(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ]
        ).stdout
    )
    if {stream.get("codec_type") for stream in probe.get("streams", [])} != {"video", "audio"}:
        raise RuntimeError("result.mp4 is not a playable audio/video file")
    if float((probe.get("format") or {}).get("duration") or 0) <= 0:
        raise RuntimeError("result.mp4 has no positive duration")


def main() -> int:
    client = boto3.client("s3", endpoint_url=S3_ENDPOINT)
    _ensure_bucket(client)
    _wait_ready()
    _assert_public_openapi()

    with tempfile.TemporaryDirectory(prefix="usfr-public-http-e2e-") as directory:
        root = Path(directory)
        source = root / "source.mp4"
        ui = root / "ui.mp4"
        tail = root / "tail.mp4"
        _clip(source, color="red", frequency=440, duration=1.0)
        _clip(ui, color="blue", frequency=660, duration=0.8)
        _clip(tail, color="yellow", frequency=880, duration=0.6)

        prefix = f"e2e-public/{uuid.uuid4().hex}"
        payload = {
            "source_video": _upload(client, source, f"{prefix}/source.mp4"),
            "ui_operation_video": _upload(client, ui, f"{prefix}/ui.mp4"),
            "tail_video": _upload(client, tail, f"{prefix}/tail.mp4"),
        }
        idempotency_key = str(uuid.uuid4())
        status, created = _request(
            "POST",
            "/api/v1/jobs",
            payload=payload,
            idempotency_key=idempotency_key,
        )
        if status != 202 or set(created) != {"job_id", "access_token", "status"}:
            raise RuntimeError(f"public create response is invalid: {status} {created}")
        job_id = created["job_id"]
        token = created["access_token"]

        replay_status, replay = _request(
            "POST",
            "/api/v1/jobs",
            payload=payload,
            idempotency_key=idempotency_key,
        )
        if replay_status != 202 or replay != created:
            raise RuntimeError("Idempotency-Key replay did not return the same job and token")

        denied_status, denied = _request(
            "GET",
            f"/api/v1/jobs/{job_id}",
            token="wrong-token",
        )
        if denied_status not in {401, 403} or denied.get("code") != "ACCESS_DENIED":
            raise RuntimeError("wrong-token request was not rejected safely")

        seen_reviews: list[str] = []
        result_url = None
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            query_status, snapshot = _request(
                "GET",
                f"/api/v1/jobs/{job_id}",
                token=token,
            )
            if query_status != 200:
                raise RuntimeError(f"job query failed: {query_status} {snapshot}")
            state = snapshot.get("status")
            if state == "failed":
                raise RuntimeError(f"public job failed: {snapshot.get('error')}")
            if state == "completed":
                result_url = snapshot.get("result_url")
                break
            if state == "waiting_review":
                review = snapshot.get("review") or {}
                review_type = review.get("type")
                if review_type == "script":
                    json.loads(review.get("content") or "")
                elif review_type == "storyboard":
                    image_urls = review.get("image_urls") or []
                    if not image_urls:
                        raise RuntimeError("storyboard review has no image URL")
                    with urlopen(image_urls[0], timeout=20) as response:
                        if not response.read(8).startswith(b"\x89PNG"):
                            raise RuntimeError("storyboard preview is not a PNG")
                else:
                    raise RuntimeError(f"unexpected review type: {review_type}")
                if review_type in seen_reviews:
                    raise RuntimeError(f"review was requested more than once: {review_type}")
                seen_reviews.append(review_type)
                review_status, _ = _request(
                    "POST",
                    f"/api/v1/jobs/{job_id}/review",
                    payload={"action": "approve"},
                    token=token,
                )
                if review_status != 202:
                    raise RuntimeError(f"review approval failed: {review_status}")
            time.sleep(0.5)

        if seen_reviews != ["script", "storyboard"]:
            raise RuntimeError(f"expected script then storyboard review, observed {seen_reviews}")
        if not isinstance(result_url, str) or not result_url:
            raise TimeoutError("public job did not produce a permanent result URL")
        result = root / "result.mp4"
        _download(result_url, result)
        _assert_playable(result)

    print("public HTTP E2E passed: 3 endpoints, idempotency, token, 2 reviews, playable result.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
