"""RunningHub ComfyUI workflow adapters used by the packaged service.

The standard Seedance client intentionally owns only the paid video endpoint.
This module owns the non-Seedance workflow boundary: binary uploads, explicit
workflow node mutation, polling, and TXT-only Whisper results.  It never turns
an arbitrary workflow result into an ASR transcript and it never retries a
workflow create after an ambiguous response.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse
import uuid


class RunningHubWorkflowError(RuntimeError):
    """A ComfyUI workflow call cannot safely produce current-run evidence."""


_RUNNING = {"QUEUED", "RUNNING"}
_FAILED = {"FAILED", "CANCELLED", "CANCELED"}
_IMAGE2_SUBMIT_PATH = "/openapi/v2/rhart-image-g-2-official/image-to-image"
_TIMECODE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?)\s*--?>\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?)"
)
_BRACKET_TIMECODE = re.compile(
    r"\[(?P<start>\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?)\s*(?:-|-->|~)\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?)\]"
)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes | Mapping[str, Any]) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else _canonical(value)).hexdigest()


def _public_https_base(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RunningHubWorkflowError("RunningHub base URL must be HTTPS")
    if parsed.query or parsed.fragment:
        raise RunningHubWorkflowError("RunningHub base URL cannot contain a query or fragment")
    return parsed.geturl().rstrip("/")


def _response_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunningHubWorkflowError("RunningHub returned invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise RunningHubWorkflowError("RunningHub response must be a JSON object")
    return dict(value)


def _post_json(*, url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout_seconds: float) -> Mapping[str, Any]:
    request = urlrequest.Request(url, data=_canonical(payload), headers=dict(headers), method="POST")
    try:
        with urlrequest.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - validated deployment HTTPS host
            raw = response.read(8 * 1024 * 1024 + 1)
    except (urlerror.HTTPError, urlerror.URLError, TimeoutError, OSError) as exc:
        raise RunningHubWorkflowError("RunningHub workflow request failed") from exc
    if len(raw) > 8 * 1024 * 1024:
        raise RunningHubWorkflowError("RunningHub workflow response exceeded the byte limit")
    return _response_json(raw)


def _upload_binary(*, url: str, headers: Mapping[str, str], path: Path, timeout_seconds: float) -> str:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RunningHubWorkflowError("RunningHub upload requires a non-empty current-run file")
    if path.stat().st_size > 256 * 1024 * 1024:
        raise RunningHubWorkflowError("RunningHub upload exceeds the 256 MB workflow limit")
    boundary = f"----USFRRunningHub{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    body = prefix + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("ascii")
    request = urlrequest.Request(
        url,
        data=body,
        headers={**dict(headers), "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - validated deployment HTTPS host
            raw = response.read(8 * 1024 * 1024 + 1)
    except (urlerror.HTTPError, urlerror.URLError, TimeoutError, OSError) as exc:
        raise RunningHubWorkflowError("RunningHub workflow media upload failed") from exc
    if len(raw) > 8 * 1024 * 1024:
        raise RunningHubWorkflowError("RunningHub workflow upload response exceeded the byte limit")
    payload = _response_json(raw)
    data = payload.get("data")
    url_value = data.get("download_url") if isinstance(data, Mapping) else None
    parsed = urlparse(str(url_value or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RunningHubWorkflowError("RunningHub upload omitted a public HTTPS download_url")
    return parsed.geturl()


def _download_binary(*, url: str, timeout_seconds: float, maximum_bytes: int = 32 * 1024 * 1024) -> bytes:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RunningHubWorkflowError("RunningHub result URL must be public HTTPS")
    request = urlrequest.Request(parsed.geturl(), method="GET")
    try:
        with urlrequest.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - validated deployment HTTPS host
            data = response.read(maximum_bytes + 1)
    except (urlerror.HTTPError, urlerror.URLError, TimeoutError, OSError) as exc:
        raise RunningHubWorkflowError("RunningHub workflow result download failed") from exc
    if not data or len(data) > maximum_bytes:
        raise RunningHubWorkflowError("RunningHub workflow result is empty or exceeds the byte limit")
    return bytes(data)


def _timestamp_seconds(value: str) -> float:
    try:
        hours, minutes, seconds = value.replace(",", ".").split(":")
        result = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (TypeError, ValueError) as exc:
        raise RunningHubWorkflowError("Whisper TXT contains an invalid timestamp") from exc
    if result < 0:
        raise RunningHubWorkflowError("Whisper TXT timestamp cannot be negative")
    return round(result, 3)


def _normalise_segments(value: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous_end = 0.0
    for raw in value:
        try:
            start = float(raw.get("start", raw.get("start_seconds")))
            end = float(raw.get("end", raw.get("end_seconds")))
        except (TypeError, ValueError) as exc:
            raise RunningHubWorkflowError("Whisper TXT segment is missing numeric timestamps") from exc
        text = str(raw.get("text") or "").strip()
        if not text or start < 0 or end <= start or start + 0.001 < previous_end:
            raise RunningHubWorkflowError("Whisper TXT segments must be ordered, non-empty, and non-overlapping")
        result.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        previous_end = end
    if not result:
        raise RunningHubWorkflowError("Whisper TXT contains no timestamped lyrics or dialogue")
    return result


def parse_timestamped_txt(text: str) -> list[dict[str, Any]]:
    """Parse only timestamped Whisper TXT/SRT/VTT/JSON output.

    A plain lyric blob is deliberately rejected: the downstream source contract
    requires a real source timeline, so a provider must return word/line timing
    rather than allowing the service to invent it.
    """

    candidate = str(text or "").strip().lstrip("\ufeff")
    if not candidate:
        raise RunningHubWorkflowError("Whisper TXT is empty")
    if candidate.startswith(("{", "[")):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, Mapping):
            rows = payload.get("segments") or payload.get("results")
            if isinstance(rows, list) and all(isinstance(item, Mapping) for item in rows):
                return _normalise_segments(rows)
    matches = list(_TIMECODE.finditer(candidate)) or list(_BRACKET_TIMECODE.finditer(candidate))
    if not matches:
        raise RunningHubWorkflowError("Whisper TXT must contain timestamped subtitle lines")
    segments: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = _timestamp_seconds(match.group("start"))
        end = _timestamp_seconds(match.group("end"))
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(candidate)
        body = candidate[match.end() : block_end]
        lines = [line.strip() for line in body.splitlines() if line.strip() and not line.strip().isdigit()]
        text_value = " ".join(lines).strip()
        segments.append({"start": start, "end": end, "text": text_value})
    return _normalise_segments(segments)


class RunningHubWorkflowClient:
    """Minimal no-retry client for configured RunningHub ComfyUI workflows."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        request_json: Callable[..., Mapping[str, Any]] | None = None,
        upload_file: Callable[[Path], str] | None = None,
        download_file: Callable[[str], bytes] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 3.0,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise RunningHubWorkflowError("RUNNINGHUB_API_KEY is required")
        if timeout_seconds <= 0 or timeout_seconds > 1800 or poll_interval_seconds <= 0:
            raise RunningHubWorkflowError("RunningHub workflow timeout configuration is invalid")
        self._api_key = api_key.strip()
        self.base_url = _public_https_base(base_url)
        self._request_json = request_json or _post_json
        self._upload_file = upload_file or self._upload
        self._download_file = download_file or (
            lambda url: _download_binary(url=url, timeout_seconds=self.timeout_seconds)
        )
        self._sleep = sleep
        self._clock = clock
        self.timeout_seconds = float(timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _upload(self, path: Path) -> str:
        return _upload_binary(
            url=f"{self.base_url}/openapi/v2/media/upload/binary",
            headers={"Authorization": f"Bearer {self._api_key}"},
            path=path,
            timeout_seconds=self.timeout_seconds,
        )

    def upload_media(self, path: Path) -> str:
        """Upload lease-local media once and return RunningHub's temporary HTTPS URL."""

        return self._upload_file(Path(path))

    @staticmethod
    def _checked_response(value: Mapping[str, Any], *, operation: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise RunningHubWorkflowError(f"RunningHub {operation} response must be an object")
        code = value.get("code")
        if code not in (None, 0, "0", 200, "200"):
            raise RunningHubWorkflowError(
                f"RunningHub {operation} failed: {str(value.get('errorMessage') or value.get('message') or 'unknown error')}"
            )
        return dict(value)

    def _post(self, *, url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        value = self._request_json(
            url=url,
            headers=self._headers,
            payload=dict(payload),
            timeout_seconds=self.timeout_seconds,
        )
        return self._checked_response(value, operation="workflow")

    def run_whisper(
        self,
        *,
        audio_path: Path,
        workflow_id: str,
        input_node_id: str,
        input_field: str,
    ) -> dict[str, Any]:
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise RunningHubWorkflowError("RUNNINGHUB_WHISPER_WORKFLOW_ID is required")
        if not isinstance(input_node_id, str) or not input_node_id.isdecimal():
            raise RunningHubWorkflowError("RUNNINGHUB_WHISPER_INPUT_NODE_ID must be numeric")
        if not isinstance(input_field, str) or not input_field.strip():
            raise RunningHubWorkflowError("RUNNINGHUB_WHISPER_INPUT_FIELD is required")
        source = Path(audio_path)
        audio_sha256 = _sha256(source.read_bytes()) if source.is_file() else ""
        if len(audio_sha256) != 64:
            raise RunningHubWorkflowError("Whisper source audio is unavailable")
        uploaded_url = self._upload_file(source)
        parsed_upload = urlparse(str(uploaded_url or "").strip())
        if parsed_upload.scheme != "https" or not parsed_upload.hostname:
            raise RunningHubWorkflowError("RunningHub workflow upload returned a non-HTTPS media URL")
        payload = {
            "addMetadata": True,
            "nodeInfoList": [
                {
                    "nodeId": input_node_id,
                    "fieldName": input_field.strip(),
                    "fieldValue": parsed_upload.geturl(),
                }
            ],
            "instanceType": "default",
            "usePersonalQueue": "false",
        }
        submit_url = f"{self.base_url}/openapi/v2/run/workflow/{workflow_id.strip()}"
        submitted = self._post(url=submit_url, payload=payload)
        task_id = str(submitted.get("taskId") or "").strip()
        if not task_id:
            raise RunningHubWorkflowError("RunningHub Whisper create response omitted taskId; do not retry automatically")
        deadline = self._clock() + self.timeout_seconds
        last_response = submitted
        while True:
            response = self._post(url=f"{self.base_url}/openapi/v2/query", payload={"taskId": task_id})
            last_response = response
            status = str(response.get("status") or "").upper()
            if status == "SUCCESS":
                results = response.get("results")
                if not isinstance(results, list):
                    raise RunningHubWorkflowError("RunningHub Whisper success response omitted results")
                txt_items = [item for item in results if isinstance(item, Mapping) and str(item.get("outputType") or "").casefold() == "txt"]
                if len(txt_items) != 1:
                    raise RunningHubWorkflowError("RunningHub Whisper requires exactly one TXT result")
                text = txt_items[0].get("text")
                if not isinstance(text, str):
                    raise RunningHubWorkflowError("RunningHub Whisper TXT result omitted text")
                segments = parse_timestamped_txt(text)
                return {
                    "task_id": task_id,
                    "uploaded_audio_url": parsed_upload.geturl(),
                    "audio_sha256": audio_sha256,
                    "segments": segments,
                    "receipt": {
                        "schema_version": "runninghub-whisper-workflow/v1",
                        "workflow_id": workflow_id.strip(),
                        "input_node_id": input_node_id,
                        "input_field": input_field.strip(),
                        "request_sha256": _sha256(payload),
                        "response_sha256": _sha256(last_response),
                        "audio_sha256": audio_sha256,
                    },
                }
            if status in _FAILED:
                raise RunningHubWorkflowError(
                    f"RunningHub Whisper task {task_id} ended with {status}: {str(response.get('errorMessage') or response.get('message') or '')}"
                )
            if status not in _RUNNING:
                raise RunningHubWorkflowError("RunningHub Whisper returned an unsupported task status")
            if self._clock() >= deadline:
                raise RunningHubWorkflowError("RunningHub Whisper task timed out")
            self._sleep(self.poll_interval_seconds)

    def run_image2(
        self,
        *,
        prompt: str,
        reference_images: Sequence[Path],
        aspect_ratio: str = "16:9",
        resolution: str = "2k",
        quality: str = "medium",
    ) -> dict[str, Any]:
        """Generate one real Image2 storyboard image from current-run images.

        Upload and paid create are each deliberately single-attempt operations.
        A caller receiving an exception must surface/reconcile it; this adapter
        never retries or replaces an image with a deterministic collage.
        """

        text = str(prompt or "").strip()
        if not 1 <= len(text) <= 20_000:
            raise RunningHubWorkflowError("Image2 prompt must contain 1-20000 characters")
        if aspect_ratio != "16:9" or resolution != "2k" or quality != "medium":
            raise RunningHubWorkflowError("USFR storyboards require Image2 16:9, 2k, medium")
        refs = [Path(item) for item in reference_images]
        if not 1 <= len(refs) <= 10:
            raise RunningHubWorkflowError("Image2 requires one to ten current-run reference images")
        uploaded_urls = [self.upload_media(path) for path in refs]
        payload = {
            "prompt": text,
            "imageUrls": uploaded_urls,
            "aspectRatio": aspect_ratio,
            "resolution": resolution,
            "quality": quality,
        }
        submitted = self._post(url=f"{self.base_url}{_IMAGE2_SUBMIT_PATH}", payload=payload)
        task_id = str(submitted.get("taskId") or "").strip()
        if not task_id:
            raise RunningHubWorkflowError("RunningHub Image2 create response omitted taskId; do not retry automatically")
        deadline = self._clock() + self.timeout_seconds
        last_response: Mapping[str, Any] = submitted
        while True:
            response = self._post(url=f"{self.base_url}/openapi/v2/query", payload={"taskId": task_id})
            last_response = response
            status = str(response.get("status") or "").upper()
            if status == "SUCCESS":
                results = response.get("results")
                if not isinstance(results, list):
                    raise RunningHubWorkflowError("RunningHub Image2 success response omitted results")
                image = next(
                    (
                        item for item in results
                        if isinstance(item, Mapping)
                        and str(item.get("outputType") or "").casefold() == "png"
                        and isinstance(item.get("url"), str)
                    ),
                    None,
                )
                if not isinstance(image, Mapping):
                    raise RunningHubWorkflowError("RunningHub Image2 must return a PNG result for storyboard review")
                result_url = str(image["url"])
                data = _download_binary(url=result_url, timeout_seconds=self.timeout_seconds)
                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise RunningHubWorkflowError("RunningHub Image2 PNG result bytes are invalid")
                return {
                    "task_id": task_id,
                    "image_bytes": data,
                    "result_url": result_url,
                    "reference_urls": uploaded_urls,
                    "receipt": {
                        "schema_version": "runninghub-image2-storyboard/v1",
                        "request_sha256": _sha256(payload),
                        "response_sha256": _sha256(last_response),
                        "task_id": task_id,
                    },
                }
            if status in _FAILED:
                raise RunningHubWorkflowError(
                    f"RunningHub Image2 task {task_id} ended with {status}: {str(response.get('errorMessage') or response.get('message') or '')}"
                )
            if status not in _RUNNING:
                raise RunningHubWorkflowError("RunningHub Image2 returned an unsupported task status")
            if self._clock() >= deadline:
                raise RunningHubWorkflowError("RunningHub Image2 task timed out")
            self._sleep(self.poll_interval_seconds)

    def run_song_lip_sync_segments(
        self,
        *,
        uploaded_audio_kind: str,
        audio_path: Path,
        segments: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Run the pinned song-only AI App for one or two generated-person segments.

        UI/tail/non-song eligibility is rejected before any upload or paid
        create.  Each successfully created task is known by task ID and is
        polled only within its own worker; a create request is never retried.
        """

        if str(uploaded_audio_kind or "").strip() != "song":
            raise RunningHubWorkflowError("RUNNINGHUB_SONG_LIP_SYNC_REQUIRES_SONG_AUDIO")
        items = [dict(item) for item in segments if isinstance(item, Mapping)]
        if not 1 <= len(items) <= 2 or len(items) != len(segments):
            raise RunningHubWorkflowError("RUNNINGHUB_SONG_LIP_SYNC_REQUIRES_ONE_OR_TWO_SEGMENTS")
        source = Path(audio_path)
        if not source.is_file() or source.stat().st_size <= 0:
            raise RunningHubWorkflowError("RUNNINGHUB_SONG_LIP_SYNC_AUDIO_UNAVAILABLE")
        audio_sha256 = _sha256(source.read_bytes())
        seen_ids: set[str] = set()
        from .runninghub_song_lip_sync import build_song_lip_sync_provider_request

        for item in items:
            segment_id = str(item.get("segment_id") or "").strip()
            if not segment_id or segment_id in seen_ids or item.get("segment_type") != "generated_person":
                raise RunningHubWorkflowError("RUNNINGHUB_SONG_LIP_SYNC_SEGMENT_INELIGIBLE")
            seen_ids.add(segment_id)
            video_path = Path(str(item.get("video_path") or ""))
            if not video_path.is_file() or video_path.stat().st_size <= 0:
                raise RunningHubWorkflowError("RUNNINGHUB_SONG_LIP_SYNC_VIDEO_UNAVAILABLE")
            build_song_lip_sync_provider_request(
                audio_input="validated-audio", video_input="validated-video",
                song_start=item.get("song_start"), song_end=item.get("song_end"),
            )

        uploaded_audio_url = self.upload_media(source)
        prepared: list[dict[str, Any]] = []
        for item in items:
            segment_id = str(item["segment_id"]).strip()
            video_path = Path(str(item["video_path"]))
            video_bytes = video_path.read_bytes()
            request = build_song_lip_sync_provider_request(
                audio_input=uploaded_audio_url,
                video_input=self.upload_media(video_path),
                song_start=item.get("song_start"),
                song_end=item.get("song_end"),
            )
            prepared.append({
                "segment_id": segment_id,
                "song_start": str(item["song_start"]),
                "song_end": str(item["song_end"]),
                "video_sha256": _sha256(video_bytes),
                "request": request,
            })

        def run_one(item: Mapping[str, Any]) -> dict[str, Any]:
            request = item["request"]
            workflow_id = str(request["workflow_id"])
            payload = request["payload"]
            submitted = self._post(url=f"{self.base_url}/openapi/v2/run/ai-app/{workflow_id}", payload=payload)
            response_data = submitted.get("data")
            task_id = str(
                submitted.get("taskId")
                or (response_data.get("taskId") if isinstance(response_data, Mapping) else "")
                or ""
            ).strip()
            if not task_id:
                raise RunningHubWorkflowError("RunningHub song lip-sync create response omitted taskId; do not retry automatically")
            deadline = self._clock() + self.timeout_seconds
            last_response: Mapping[str, Any] = submitted
            while True:
                response = self._post(url=f"{self.base_url}/openapi/v2/query", payload={"taskId": task_id})
                last_response = response
                status = str(response.get("status") or "").upper()
                if status == "SUCCESS":
                    results = response.get("results")
                    mp4 = next((row for row in results or [] if isinstance(row, Mapping) and str(row.get("outputType") or "").casefold() == "mp4" and isinstance(row.get("url"), str)), None)
                    if not isinstance(mp4, Mapping):
                        raise RunningHubWorkflowError("RunningHub song lip-sync success omitted an MP4 result")
                    result_url = str(mp4["url"])
                    data = self._download_file(result_url)
                    if not data or b"ftyp" not in data[:64]:
                        raise RunningHubWorkflowError("RunningHub song lip-sync result is not MP4 bytes")
                    return {
                        "segment_id": item["segment_id"], "task_id": task_id, "result_url": result_url,
                        "video_bytes": data,
                        "receipt": {
                            "schema_version": "runninghub-song-lip-sync/v1", "workflow_id": workflow_id,
                            "request_sha256": _sha256(payload), "response_sha256": _sha256(last_response),
                            "task_id": task_id, "input_video_sha256": item["video_sha256"],
                            "input_audio_sha256": audio_sha256, "song_start": item["song_start"],
                            "song_end": item["song_end"], "output_video_sha256": _sha256(data),
                        },
                    }
                if status in _FAILED:
                    raise RunningHubWorkflowError(f"RunningHub song lip-sync task {task_id} ended with {status}")
                if status not in _RUNNING:
                    raise RunningHubWorkflowError("RunningHub song lip-sync returned an unsupported task status")
                if self._clock() >= deadline:
                    raise RunningHubWorkflowError("RunningHub song lip-sync task timed out")
                self._sleep(self.poll_interval_seconds)

        with ThreadPoolExecutor(max_workers=len(prepared)) as executor:
            completed = list(executor.map(run_one, prepared))
        return {"schema_version": "runninghub-song-lip-sync/v1", "uploaded_audio_url": uploaded_audio_url, "segments": completed}


__all__ = ["RunningHubWorkflowClient", "RunningHubWorkflowError", "parse_timestamped_txt"]
