"""Drive one real-MP4 Jobs API flow inside the Docker E2E profile."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3

from server.cleanup import CleanupSweeper
from server.packaged_factory import build_runtime


API = os.getenv("USFR_E2E_API", "http://api:8080").rstrip("/")
BUCKET = os.getenv("USFR_S3_BUCKET", "usfr-media")
SCOPE = "container-e2e"


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


def _duration(path: Path) -> float:
    return float(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
        ).stdout.strip()
    )


def _request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{API}{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as exc:
        body = exc.read().decode()
        return exc.code, json.loads(body) if body else {}


def _wait_ready(timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _ = _request("GET", "/readyz")
            if status == 200:
                return
        except (OSError, URLError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise TimeoutError("Jobs API did not become ready")


def _ensure_bucket(client: Any, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client.head_bucket(Bucket=BUCKET)
            return
        except Exception as exc:
            last_error = exc
        try:
            client.create_bucket(Bucket=BUCKET)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise TimeoutError("MinIO bucket did not become ready") from last_error


def _wait_revisions(job_id: str, kind: str, token: str, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    path = f"/api/v1/jobs/{job_id}/{kind}"
    while time.monotonic() < deadline:
        status, body = _request("GET", path, token=token)
        if status == 200 and body.get("revisions"):
            return body["revisions"][-1]
        time.sleep(0.5)
    raise TimeoutError(f"{kind} revision was not produced")


def _job(job_id: str, token: str) -> dict[str, Any]:
    status, body = _request("GET", f"/api/v1/jobs/{job_id}", token=token)
    if status != 200:
        raise RuntimeError(body)
    return body


def _upload(client: Any, path: Path, object_key: str) -> dict[str, Any]:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    client.put_object(
        Bucket=BUCKET,
        Key=object_key,
        Body=payload,
        ContentType="video/mp4",
        Metadata={"sha256": digest},
    )
    return {
        "object_key": object_key,
        "sha256": digest,
        "size_bytes": len(payload),
        "content_type": "video/mp4",
        "duration_seconds": _duration(path),
        "status": "completed",
    }


def _assert_final_media(client: Any, key: str, destination: Path) -> None:
    client.download_file(BUCKET, key, str(destination))
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
                str(destination),
            ]
        ).stdout
    )
    if {stream["codec_type"] for stream in probe["streams"]} != {"video", "audio"}:
        raise RuntimeError("final result.mp4 is not a playable audio/video file")
    scan = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(destination),
            "-vf",
            "blackdetect=d=0.02:pix_th=0.10",
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    if "black_start" in scan.stderr:
        raise RuntimeError("final result.mp4 contains a black interval")


def main() -> int:
    client = boto3.client("s3", endpoint_url=os.getenv("USFR_S3_ENDPOINT"))
    _ensure_bucket(client)
    before_keys = {
        item["Key"]
        for item in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    }
    _wait_ready()
    with tempfile.TemporaryDirectory(prefix="usfr-container-e2e-") as temporary:
        root = Path(temporary)
        source = root / "source.mp4"
        ui = root / "ui.mp4"
        tail = root / "tail.mp4"
        _clip(source, color="red", frequency=440, duration=1.0)
        _clip(ui, color="blue", frequency=660, duration=0.8)
        _clip(tail, color="yellow", frequency=880, duration=0.6)
        slots = {
            "source_video": _upload(client, source, f"uploads/{SCOPE}/source.mp4"),
            "ui_operation_video": _upload(client, ui, f"uploads/{SCOPE}/ui.mp4"),
            "tail_video": _upload(client, tail, f"uploads/{SCOPE}/tail.mp4"),
        }
        status, created = _request(
            "POST",
            "/api/v1/jobs",
            payload={
                "upload_scope": SCOPE,
                "slots": slots,
                "output_language": "zh",
            },
        )
        if status != 202:
            raise RuntimeError(created)
        job_id = created["job_id"]
        token = created["capability_token"]
        status, started = _request(
            "POST",
            f"/api/v1/jobs/{job_id}/start",
            token=token,
            payload={"expected_version": created["version"]},
        )
        if status != 202:
            raise RuntimeError(started)

        script = _wait_revisions(job_id, "scripts", token)
        current = _job(job_id, token)
        status, approved = _request(
            "POST",
            f"/api/v1/jobs/{job_id}/scripts/{script['revision']}/approve",
            token=token,
            payload={
                "expected_version": current["version"],
                "expected_sha256": script["sha256"],
            },
        )
        if status != 202:
            raise RuntimeError(approved)

        storyboard = _wait_revisions(job_id, "storyboards", token)
        current = _job(job_id, token)
        status, approved = _request(
            "POST",
            f"/api/v1/jobs/{job_id}/storyboards/{storyboard['revision']}/approve",
            token=token,
            payload={
                "expected_version": current["version"],
                "expected_sha256": storyboard["sha256"],
            },
        )
        if status != 202:
            raise RuntimeError(approved)

        deadline = time.monotonic() + 180
        result: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            status, body = _request(
                "GET", f"/api/v1/jobs/{job_id}/result", token=token
            )
            if status == 200 and body.get("result"):
                result = body["result"]
                break
            time.sleep(0.5)
        if result is None:
            raise TimeoutError("final result.mp4 was not published")
        final_key = f"final/{job_id}/result.mp4"
        if result.get("object_key") != final_key:
            raise RuntimeError("final result key is not authoritative")
        _assert_final_media(client, final_key, root / "result.mp4")

        runtime = build_runtime()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            checkpoint = runtime.job_store.get_stage_checkpoint(job_id, "run_qc")
            if checkpoint is not None and checkpoint.status == "SUCCEEDED":
                break
            time.sleep(0.2)
        else:
            raise TimeoutError("run_qc checkpoint was not committed before cleanup")
        if not isinstance(runtime.cleanup_sweeper, CleanupSweeper):
            raise RuntimeError("packaged runtime did not expose CleanupSweeper")
        if not runtime.cleanup_sweeper.cleanup_job(job_id, preserve_final=True):
            raise RuntimeError("CleanupSweeper did not complete")
        keys = {
            item["Key"]
            for item in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
        }
        current_temporary_prefix = f"temporary/{job_id}/"
        current_upload_prefix = f"uploads/{SCOPE}/"
        current_residue = {
            key
            for key in keys
            if key.startswith((current_temporary_prefix, current_upload_prefix))
        }
        new_keys = keys - before_keys
        if current_residue or new_keys != {final_key}:
            raise RuntimeError(
                "current-job final-only assertion failed; "
                f"new_keys={sorted(new_keys)}, residue={sorted(current_residue)}"
            )
    print("container video E2E passed: two approvals, QC, CleanupSweeper, current-job result.mp4 only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
