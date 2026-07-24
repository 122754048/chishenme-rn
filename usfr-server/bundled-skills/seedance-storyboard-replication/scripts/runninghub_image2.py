from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
import struct
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid

from config import DEFAULT_ENV_FILE, load_settings


MODEL_NAME = "gpt-image-2/image-to-image-official-stable"
MODEL_API_ID = "2046514150500524035"
SUBMIT_PATH = "/openapi/v2/rhart-image-g-2-official/image-to-image"
QUERY_PATH = "/openapi/v2/query"
UPLOAD_PATH = "/openapi/v2/media/upload/binary"
RUNNING_STATUSES = {"QUEUED", "RUNNING"}
TERMINAL_FAILURE_STATUSES = {"FAILED", "CANCELLED", "CANCELED"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class RunningHubError(RuntimeError):
    pass


class RunningHubTaskFailed(RunningHubError):
    pass


class RunningHubTimeout(RunningHubError):
    pass


def build_payload(
    prompt: str,
    image_urls: list[str],
    *,
    aspect_ratio: str = "16:9",
    resolution: str = "2k",
    quality: str = "medium",
) -> dict[str, Any]:
    prompt = prompt.strip()
    if not 1 <= len(prompt) <= 20000:
        raise ValueError("prompt must contain 1-20000 characters")
    if not 1 <= len(image_urls) <= 10:
        raise ValueError("imageUrls must contain 1-10 images")
    for url in image_urls:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("imageUrls must contain public HTTPS URLs")
    if aspect_ratio != "16:9":
        raise ValueError("storyboard image2 aspect ratio must be 16:9")
    if resolution not in {"1k", "2k", "4k"}:
        raise ValueError("resolution must be one of: 1k, 2k, 4k")
    if quality not in {"low", "medium", "high"}:
        raise ValueError("quality must be one of: low, medium, high")
    return {
        "prompt": prompt,
        "imageUrls": list(image_urls),
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
        "quality": quality,
    }


def validate_reference(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"reference image not found: {path}")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"unsupported reference image format: {path.suffix}")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError(f"reference image exceeds 10 MB: {path}")


def _json_bytes(payload: bytes) -> dict[str, Any]:
    if not payload:
        return {}
    parsed = json.loads(payload.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RunningHubError("RunningHub response must be a JSON object")
    return parsed


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    body = None
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, _json_bytes(response.read())
    except HTTPError as exc:
        return exc.code, _json_bytes(exc.read())


def _request_upload(
    *,
    url: str,
    headers: dict[str, str],
    file_path: Path,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    boundary = f"----CodexRunningHub{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8")
    body = prefix + file_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("ascii")
    upload_headers = {
        **headers,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    request = Request(url, data=body, headers=upload_headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, _json_bytes(response.read())
    except HTTPError as exc:
        return exc.code, _json_bytes(exc.read())


def _download(url: str, output_path: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RunningHubError("result URL must be public HTTPS")
    request = Request(url, method="GET")
    with urlopen(request, timeout=180) as response:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.read())


def _error_message(payload: dict[str, Any], fallback: str) -> str:
    return str(
        payload.get("errorMessage")
        or payload.get("message")
        or payload.get("msg")
        or fallback
    )


def _split_response(raw: Any) -> tuple[int, dict[str, Any]]:
    if isinstance(raw, tuple) and len(raw) == 2:
        return int(raw[0]), dict(raw[1])
    return 200, dict(raw)


class RunningHubClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://www.runninghub.ai",
        request_json: Callable[..., Any] | None = None,
        request_upload: Callable[..., Any] | None = None,
        download: Callable[[str, Path], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        request_timeout: float = 90,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.request_json = request_json or _request_json
        self.request_upload = request_upload or _request_upload
        self.download = download or _download
        self.sleep = sleep
        self.clock = clock
        self.request_timeout = request_timeout
        self.last_create_response: dict[str, Any] = {}
        self.last_status_response: dict[str, Any] = {}

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _check_response(
        self, raw: Any, *, context: str
    ) -> dict[str, Any]:
        status_code, payload = _split_response(raw)
        if status_code in {401, 403}:
            raise RunningHubError(
                f"RunningHub {context} rejected with HTTP {status_code}; "
                "check RUNNINGHUB_API_KEY"
            )
        if status_code >= 400:
            raise RunningHubError(
                f"RunningHub {context} failed with HTTP {status_code}: "
                f"{_error_message(payload, 'request failed')}"
            )
        if payload.get("code") not in (None, 0, "0", 200, "200"):
            raise RunningHubError(
                f"RunningHub {context} failed: "
                f"{_error_message(payload, 'unknown API error')}"
            )
        return payload

    def upload_image(self, path: Path) -> str:
        validate_reference(path)
        raw = self.request_upload(
            url=f"{self.base_url}{UPLOAD_PATH}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            file_path=path,
            timeout=self.request_timeout,
        )
        payload = self._check_response(raw, context="upload")
        data = payload.get("data") or {}
        url = data.get("download_url") if isinstance(data, dict) else None
        if not url:
            raise RunningHubError("RunningHub upload response omitted data.download_url")
        url = str(url)
        if url.startswith("/"):
            url = f"{self.base_url}{url}"
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RunningHubError("RunningHub upload did not return a public HTTPS URL")
        return url

    def create(self, payload: dict[str, Any]) -> str:
        # A create call may be billable. It is deliberately attempted only once.
        raw = self.request_json(
            method="POST",
            url=f"{self.base_url}{SUBMIT_PATH}",
            headers=self.headers,
            json_body=payload,
            timeout=self.request_timeout,
        )
        response = self._check_response(raw, context="submit")
        self.last_create_response = response
        task_id = response.get("taskId")
        if not task_id:
            raise RunningHubError("RunningHub submit response omitted taskId")
        return str(task_id)

    def query(self, task_id: str) -> dict[str, Any]:
        raw = self.request_json(
            method="POST",
            url=f"{self.base_url}{QUERY_PATH}",
            headers=self.headers,
            json_body={"taskId": task_id},
            timeout=self.request_timeout,
        )
        response = self._check_response(raw, context="query")
        self.last_status_response = response
        return response

    def wait_for_result(
        self,
        task_id: str,
        *,
        timeout: float = 1800,
        poll_interval: float = 5,
    ) -> str:
        deadline = self.clock() + timeout
        while True:
            response = self.query(task_id)
            status = str(response.get("status", "")).upper()
            if status == "SUCCESS":
                results = response.get("results") or []
                if not isinstance(results, list) or not results:
                    raise RunningHubError("successful RunningHub task omitted results")
                result = results[0]
                if not isinstance(result, dict) or not result.get("url"):
                    raise RunningHubError("RunningHub result omitted results[0].url")
                return str(result["url"])
            if status in TERMINAL_FAILURE_STATUSES:
                raise RunningHubTaskFailed(
                    _error_message(response, f"RunningHub task ended with {status}")
                )
            if status not in RUNNING_STATUSES:
                raise RunningHubError(
                    f"unknown RunningHub task status: {status or '<empty>'}"
                )
            if self.clock() >= deadline:
                raise RunningHubTimeout(f"RunningHub task {task_id} timed out")
            self.sleep(poll_interval)

    def download_result(self, url: str, output_path: Path) -> None:
        self.download(url, output_path)


def image_dimensions(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()[:32]
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        try:
            with path.open("rb") as stream:
                stream.read(2)
                while True:
                    marker_start = stream.read(1)
                    if not marker_start:
                        break
                    if marker_start != b"\xff":
                        continue
                    marker = stream.read(1)
                    while marker == b"\xff":
                        marker = stream.read(1)
                    if marker in {bytes([value]) for value in range(0xC0, 0xC4)}:
                        length = int.from_bytes(stream.read(2), "big")
                        segment = stream.read(length - 2)
                        return int.from_bytes(segment[3:5], "big"), int.from_bytes(segment[1:3], "big")
                    length_bytes = stream.read(2)
                    if len(length_bytes) != 2:
                        break
                    stream.seek(int.from_bytes(length_bytes, "big") - 2, 1)
        except OSError:
            return None
    return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_generation(
    *,
    client: RunningHubClient,
    prompt_file: Path,
    reference_images: list[Path],
    output_path: Path,
    artifact_stem: str,
    cut_id: str,
    revision_number: int,
    resume_task_id: str | None = None,
    timeout: float = 1800,
    poll_interval: float = 5,
    resolution: str = "2k",
    quality: str = "medium",
    revision_reason: str,
) -> str:
    if not artifact_stem.strip() or not cut_id.strip() or revision_number < 1:
        raise ValueError("artifact_stem, cut_id, and revision_number are required")
    started = time.monotonic()
    artifact_dir = output_path.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    prompt = prompt_file.read_text(encoding="utf-8-sig")
    for path in reference_images:
        validate_reference(path)

    if resume_task_id:
        task_id = resume_task_id
        request_record = {
            "resume_task_id": task_id,
            "prompt_file": str(prompt_file),
            "reference_images": [str(path) for path in reference_images],
        }
    else:
        try:
            uploaded_urls = [client.upload_image(path) for path in reference_images]
            payload = build_payload(
                prompt,
                uploaded_urls,
                resolution=resolution,
                quality=quality,
            )
            request_record = {
                **payload,
                "prompt": {"path": str(prompt_file), "characters": len(prompt.strip())},
                "reference_images": [str(path) for path in reference_images],
            }
            task_id = client.create(payload)
            write_json(
                artifact_dir / f"{cut_id}.create_response.json",
                client.last_create_response,
            )
        except Exception as exc:
            write_json(
                artifact_dir / "image2.failure.json",
                {
                    "task_id": None,
                    "stage": "upload_or_submit",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "automatic_paid_retry": False,
                },
            )
            raise

    write_json(artifact_dir / f"{cut_id}.request.redacted.json", request_record)
    (artifact_dir / f"{cut_id}.task_id.txt").write_text(task_id, encoding="utf-8")
    try:
        result_url = client.wait_for_result(
            task_id, timeout=timeout, poll_interval=poll_interval
        )
        write_json(artifact_dir / f"{cut_id}.status.json", client.last_status_response)
        client.download_result(result_url, output_path)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RunningHubError("RunningHub result download produced an empty file")
        dimensions = image_dimensions(output_path)
        elapsed = time.monotonic() - started
        write_json(
            artifact_dir / f"{cut_id}.meta.json",
            {
                "generator_kind": "image_model",
                "tool": "RunningHub OpenAPI v2",
                "model": MODEL_NAME,
                "model_api_id": MODEL_API_ID,
                "task_id": task_id,
                "prompt_path": str(prompt_file),
                "reference_inputs": [str(path) for path in reference_images],
                "output_path": str(output_path),
                "output_dimensions": list(dimensions) if dimensions else None,
                "generation_duration_seconds": round(elapsed, 3),
                "revision_reason": revision_reason,
                "revision_number": revision_number,
                "artifact_stem": artifact_stem,
                "cut_id": cut_id,
                "aspect_ratio": "16:9",
                "resolution": resolution,
                "quality": quality,
            },
        )
        return task_id
    except Exception as exc:
        if client.last_status_response:
            write_json(artifact_dir / f"{cut_id}.status.json", client.last_status_response)
        write_json(
            artifact_dir / f"{cut_id}.failure.json",
            {
                "task_id": task_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "automatic_paid_retry": False,
            },
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and save a real image2 storyboard with RunningHub."
    )
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--reference-image", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-stem", required=True)
    parser.add_argument("--cut-id", required=True)
    parser.add_argument("--revision-number", type=int, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--resume-task-id")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--poll-interval", type=float, default=5)
    parser.add_argument("--resolution", choices=("1k", "2k", "4k"), default="2k")
    parser.add_argument("--quality", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--revision-reason", required=True)
    args = parser.parse_args()

    settings = load_settings(args.env_file)
    settings.require_runninghub()
    client = RunningHubClient(
        settings.runninghub_api_key,
        base_url=settings.runninghub_base_url,
    )
    run_generation(
        client=client,
        prompt_file=args.prompt_file,
        reference_images=args.reference_image,
        output_path=args.output,
        artifact_stem=args.artifact_stem,
        cut_id=args.cut_id,
        revision_number=args.revision_number,
        resume_task_id=args.resume_task_id,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        resolution=args.resolution,
        quality=args.quality,
        revision_reason=args.revision_reason,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
