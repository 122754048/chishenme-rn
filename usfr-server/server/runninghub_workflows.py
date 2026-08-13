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
from pathlib import Path
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse
import uuid

from .marketing_terms import validate_neutral_marketing_terms


class RunningHubWorkflowError(RuntimeError):
    """A ComfyUI workflow call cannot safely produce current-run evidence."""


class AssetBoardGenerationError(RunningHubWorkflowError):
    """An Image2 asset board failed and no original-image fallback is allowed."""

    code = "ASSET_BOARD_GENERATION_FAILED"


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


def _asset_template_version(asset_type: str) -> str:
    return "model-identity-v3" if asset_type == "model" else f"{asset_type}-v2"


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


def parse_plain_lyrics_txt(text: str) -> list[dict[str, str]]:
    """Legacy parser retained for isolated compatibility tests, not production routing."""

    candidate = str(text or "").strip().lstrip("\ufeff")
    lines = [line.strip() for line in candidate.splitlines() if line.strip()]
    if not lines:
        raise RunningHubWorkflowError("Whisper TXT contains no lyrics")
    return [{"text": line} for line in lines]


class RunningHubWorkflowClient:
    """Minimal no-retry client for configured RunningHub ComfyUI workflows."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        request_json: Callable[..., Mapping[str, Any]] | None = None,
        upload_file: Callable[[Path], str] | None = None,
        download_file: Callable[..., bytes] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 3.0,
        tts_config: Mapping[str, Any] | None = None,
        tts_timeout_seconds: float | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise RunningHubWorkflowError("RUNNINGHUB_API_KEY is required")
        if timeout_seconds <= 0 or timeout_seconds > 1800 or poll_interval_seconds <= 0:
            raise RunningHubWorkflowError("RunningHub workflow timeout configuration is invalid")
        self._api_key = api_key.strip()
        self.base_url = _public_https_base(base_url)
        self._request_json = request_json or _post_json
        self._upload_file = upload_file or self._upload
        self._download_file = download_file or _download_binary
        self._sleep = sleep
        self._clock = clock
        self.timeout_seconds = float(timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.tts_config = dict(tts_config or {})
        self.tts_timeout_seconds = float(tts_timeout_seconds or timeout_seconds)
        if self.tts_timeout_seconds <= 0 or self.tts_timeout_seconds > 1800:
            raise RunningHubWorkflowError("RUNNINGHUB_TTS_TIMEOUT_SECONDS is invalid")

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

    def _run_txt_transcription(
        self,
        *,
        media_path: Path,
        workflow_id: str,
        input_node_id: str,
        input_field: str,
        create_route: str,
        media_kind: str,
        text_parser: Callable[[str], list[dict[str, Any]]] = parse_timestamped_txt,
    ) -> dict[str, Any]:
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise RunningHubWorkflowError("RUNNINGHUB_SPEECH_WHISPER_WORKFLOW_ID is required")
        if not isinstance(input_node_id, str) or not input_node_id.isdecimal():
            raise RunningHubWorkflowError("RUNNINGHUB_SPEECH_WHISPER_INPUT_NODE_ID must be numeric")
        if not isinstance(input_field, str) or not input_field.strip():
            raise RunningHubWorkflowError("RUNNINGHUB_SPEECH_WHISPER_INPUT_FIELD is required")
        source = Path(media_path)
        source_sha256 = _sha256(source.read_bytes()) if source.is_file() else ""
        if len(source_sha256) != 64:
            raise RunningHubWorkflowError(f"Whisper source {media_kind} is unavailable")
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
        submit_url = f"{self.base_url}/openapi/v2/run/{create_route}/{workflow_id.strip()}"
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
                    result_url = str(txt_items[0].get("url") or "").strip()
                    parsed_result = urlparse(result_url)
                    if parsed_result.scheme != "https" or not parsed_result.hostname:
                        raise RunningHubWorkflowError("RunningHub Whisper TXT result omitted text")
                    try:
                        text = self._download_file(
                            url=parsed_result.geturl(),
                            timeout_seconds=self.timeout_seconds,
                            maximum_bytes=5 * 1024 * 1024,
                        ).decode("utf-8-sig")
                    except (OSError, UnicodeError, ValueError) as exc:
                        raise RunningHubWorkflowError("RunningHub Whisper TXT result could not be decoded") from exc
                segments = text_parser(text)
                return {
                    "task_id": task_id,
                    f"uploaded_{media_kind}_url": parsed_upload.geturl(),
                    f"{media_kind}_sha256": source_sha256,
                    "segments": segments,
                    "receipt": {
                        "schema_version": "runninghub-whisper-workflow/v1",
                        "workflow_id": workflow_id.strip(),
                        "input_node_id": input_node_id,
                        "input_field": input_field.strip(),
                        "request_sha256": _sha256(payload),
                        "response_sha256": _sha256(last_response),
                        f"{media_kind}_sha256": source_sha256,
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

    def run_speech_whisper(
        self,
        *,
        video_path: Path,
        workflow_id: str,
        input_node_id: str,
        input_field: str,
    ) -> dict[str, Any]:
        """Transcribe non-music speech by sending the original video to the AI App."""

        return self._run_txt_transcription(
            media_path=video_path,
            workflow_id=workflow_id,
            input_node_id=input_node_id,
            input_field=input_field,
            create_route="ai-app",
            media_kind="video",
        )

    def run_whisper(
        self,
        *,
        audio_path: Path,
        workflow_id: str,
        input_node_id: str,
        input_field: str,
        require_timestamps: bool = True,
    ) -> dict[str, Any]:
        """Legacy unbound compatibility path; packaged production never registers it."""

        if require_timestamps:
            return self._run_txt_transcription(
                media_path=audio_path,
                workflow_id=workflow_id,
                input_node_id=input_node_id,
                input_field=input_field,
                create_route="workflow",
                media_kind="audio",
            )
        return self._run_txt_transcription(
            media_path=audio_path,
            workflow_id=workflow_id,
            input_node_id=input_node_id,
            input_field=input_field,
            create_route="workflow",
            media_kind="audio",
            text_parser=parse_plain_lyrics_txt,
        )

    def _run_media_workflow(
        self,
        *,
        workflow_id: str,
        payload: Mapping[str, Any],
        accepted_types: frozenset[str],
        label: str,
        timeout_seconds: float,
        maximum_bytes: int,
        submit_kind: str = "workflow",
    ) -> dict[str, Any]:
        if submit_kind not in {"workflow", "ai-app"}:
            raise RunningHubWorkflowError("RunningHub media submit kind is unsupported")
        submitted = self._post(
            url=f"{self.base_url}/openapi/v2/run/{submit_kind}/{workflow_id}",
            payload=payload,
        )
        task_id = str(submitted.get("taskId") or "").strip()
        if not task_id:
            raise RunningHubWorkflowError(
                f"RunningHub {label} create response omitted taskId; do not retry automatically"
            )
        deadline = self._clock() + timeout_seconds
        last_response: Mapping[str, Any] = submitted
        while True:
            response = self._post(
                url=f"{self.base_url}/openapi/v2/query",
                payload={"taskId": task_id},
            )
            last_response = response
            status = str(response.get("status") or "").upper()
            if status == "SUCCESS":
                results = response.get("results")
                matches = [
                    item
                    for item in results or []
                    if isinstance(item, Mapping)
                    and str(item.get("outputType") or "").casefold() in accepted_types
                    and isinstance(item.get("url"), str)
                ]
                if len(matches) != 1:
                    raise RunningHubWorkflowError(
                        f"RunningHub {label} requires exactly one media result"
                    )
                output_type = str(matches[0]["outputType"]).casefold()
                result_url = str(matches[0]["url"]).strip()
                data = self._download_file(
                    url=result_url,
                    timeout_seconds=timeout_seconds,
                    maximum_bytes=maximum_bytes,
                )
                if not isinstance(data, bytes) or not data:
                    raise RunningHubWorkflowError(f"RunningHub {label} result media is empty")
                return {
                    "task_id": task_id,
                    "result_url": result_url,
                    "output_type": output_type,
                    "media_bytes": data,
                    "receipt": {
                        "task_id": task_id,
                        "workflow_id": workflow_id,
                        "request_sha256": _sha256(payload),
                        "response_sha256": _sha256(last_response),
                        "output_sha256": _sha256(data),
                    },
                }
            if status in _FAILED:
                raise RunningHubWorkflowError(f"RunningHub {label} task failed")
            if status not in _RUNNING:
                raise RunningHubWorkflowError(f"RunningHub {label} returned an unsupported task status")
            if self._clock() >= deadline:
                raise RunningHubWorkflowError(f"RunningHub {label} task timed out")
            self._sleep(self.poll_interval_seconds)

    def run_tts(
        self,
        text: str,
        language: str,
        timing: Mapping[str, Any],
        *,
        speaker: str,
        voice_reference_url: str | None = None,
    ) -> dict[str, Any]:
        exact_text = str(text or "")
        locale = str(language or "").strip()
        speaker_id = str(speaker or "").strip()
        reference_url = str(voice_reference_url or "").strip()
        start_ms = timing.get("start_ms") if isinstance(timing, Mapping) else None
        end_ms = timing.get("end_ms") if isinstance(timing, Mapping) else None
        if not exact_text.strip() or "\ufffd" in exact_text or "\x00" in exact_text:
            raise RunningHubWorkflowError("TTS exact text is invalid")
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale):
            raise RunningHubWorkflowError("TTS language must be a BCP-47 locale")
        if not speaker_id:
            raise RunningHubWorkflowError("TTS speaker assignment is required")
        if (
            isinstance(start_ms, bool)
            or isinstance(end_ms, bool)
            or not isinstance(start_ms, int)
            or not isinstance(end_ms, int)
            or start_ms < 0
            or end_ms <= start_ms
        ):
            raise RunningHubWorkflowError("TTS timing is invalid")
        frozen_timing = {"start_ms": start_ms, "end_ms": end_ms}
        mode = str(self.tts_config.get("mode") or "legacy_multi_input").strip().casefold()
        if mode == "voice_clone_two_input":
            if not reference_url:
                raise RunningHubWorkflowError("RunningHub voice-clone TTS reference audio is required")
            required = (
                "workflow_id",
                "reference_audio_node_id",
                "reference_audio_field",
                "text_node_id",
                "text_field",
            )
            config = {name: str(self.tts_config.get(name) or "").strip() for name in required}
            missing = [name for name, value in config.items() if not value]
            if missing:
                raise RunningHubWorkflowError(
                    f"RunningHub TTS configuration missing: {', '.join(missing)}"
                )
            if not config["reference_audio_node_id"].isdecimal() or not config["text_node_id"].isdecimal():
                raise RunningHubWorkflowError("RunningHub TTS node IDs must be numeric")
            node_info = [
                {
                    "nodeId": config["reference_audio_node_id"],
                    "fieldName": config["reference_audio_field"],
                    "fieldValue": reference_url,
                },
                {
                    "nodeId": config["text_node_id"],
                    "fieldName": config["text_field"],
                    "fieldValue": exact_text,
                },
            ]
            submit_kind = "ai-app"
        else:
            required = (
                "workflow_id",
                "text_node_id",
                "text_field",
                "language_node_id",
                "language_field",
                "speaker_node_id",
                "speaker_field",
                "timing_node_id",
                "timing_field",
            )
            config = {name: str(self.tts_config.get(name) or "").strip() for name in required}
            missing = [name for name, value in config.items() if not value]
            if missing:
                raise RunningHubWorkflowError(
                    f"RunningHub TTS configuration missing: {', '.join(missing)}"
                )
            if any(
                not config[name].isdecimal()
                for name in ("text_node_id", "language_node_id", "speaker_node_id", "timing_node_id")
            ):
                raise RunningHubWorkflowError("RunningHub TTS node IDs must be numeric")
            reference_config: dict[str, str] = {}
            if reference_url:
                reference_config = {
                    "reference_audio_node_id": str(self.tts_config.get("reference_audio_node_id") or "").strip(),
                    "reference_audio_field": str(self.tts_config.get("reference_audio_field") or "").strip(),
                }
                if not all(reference_config.values()):
                    raise RunningHubWorkflowError("RunningHub TTS reference audio configuration missing")
                if not reference_config["reference_audio_node_id"].isdecimal():
                    raise RunningHubWorkflowError("RunningHub TTS reference audio node ID must be numeric")
            node_info = [
                {"nodeId": config["text_node_id"], "fieldName": config["text_field"], "fieldValue": exact_text},
                {"nodeId": config["language_node_id"], "fieldName": config["language_field"], "fieldValue": locale},
                {"nodeId": config["speaker_node_id"], "fieldName": config["speaker_field"], "fieldValue": speaker_id},
                {"nodeId": config["timing_node_id"], "fieldName": config["timing_field"], "fieldValue": frozen_timing},
            ]
            if reference_url:
                node_info.append(
                    {
                        "nodeId": reference_config["reference_audio_node_id"],
                        "fieldName": reference_config["reference_audio_field"],
                        "fieldValue": reference_url,
                    }
                )
            submit_kind = "workflow"
        payload = {
            "addMetadata": True,
            "nodeInfoList": node_info,
            "instanceType": "default",
            "usePersonalQueue": False,
        }
        result = self._run_media_workflow(
            workflow_id=config["workflow_id"],
            payload=payload,
            accepted_types=frozenset({"mp3", "wav", "flac", "m4a", "aac", "ogg", "audio"}),
            label="TTS",
            timeout_seconds=self.tts_timeout_seconds,
            maximum_bytes=64 * 1024 * 1024,
            submit_kind=submit_kind,
        )
        result["audio_bytes"] = result.pop("media_bytes")
        result["receipt"].update(
            {
                "language": locale,
                "speaker": speaker_id,
                "timing": frozen_timing,
                "text_sha256": _sha256(exact_text.encode("utf-8")),
                "voice_reference_bound": bool(reference_url),
                "tts_mode": mode,
                "workflow_id": config["workflow_id"],
            }
        )
        return result

    def run_image2(
        self,
        *,
        prompt: str,
        reference_images: Sequence[Path],
        template: str | None = None,
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
        template_name = None
        if template is not None:
            template_name = str(template).strip().casefold()
            if template_name not in {"model", "garment", "scene", "product", "app"}:
                raise RunningHubWorkflowError("Image2 asset-board template is invalid")
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
                        "schema_version": "runninghub-image2-asset-board/v2" if template_name is not None else "runninghub-image2-storyboard/v1",
                        "request_sha256": _sha256(payload),
                        "response_sha256": _sha256(last_response),
                        "task_id": task_id,
                        **({"template": template_name, "template_version": _asset_template_version(template_name)} if template_name is not None else {}),
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

    def run_asset_board_batch(self, bindings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Generate one Image2 four-view board for each bound asset.

        This is intentionally a thin orchestration boundary over ``run_image2``;
        it preserves the paid request and receipt from the existing client and
        fails closed when any board cannot be produced.
        """

        templates = {
            "model": (
                "Create one dominant head-and-shoulders portrait of the approved person, centered and facing camera. "
                "Show exactly one person and one face, with no panels, alternate views, contact sheet, body turnaround, or duplicated head. "
                "Keep identity, facial structure, hair, skin tone, and distinctive facial details unchanged. "
                "Use neutral studio lighting, a plain background, and a clear unobstructed face. "
                "Approved presentation constraint: {attraction_constraint}."
            ),
            "garment": (
                "Create a four-view garment reference board: front construction, back construction, material close detail, and worn silhouette. "
                "Preserve fabric, seams, closures, print placement, color, fit, and scale. Use a neutral studio background and practical product presentation. "
                "Approved presentation constraint: {attraction_constraint}."
            ),
            "scene": (
                "Create a four-view scene reference board: establishing view, left spatial view, right spatial view, and lighting/material detail. "
                "Preserve architecture, prop placement, depth, time-of-day cues, and camera-facing geometry. "
                "Approved scene logic: {display_logic}. Keep the presentation neutral and observational."
            ),
            "product": (
                "Create a detailed product reference board with front hero view, side geometry, top or control surface view, bottom view, material/detail view, "
                "and functional features or control surfaces. Show the product first at its observed scale. "
                "Preserve exact shape, label placement, markings, controls, color, scale, and functional features. "
                "Approved product display logic: {display_logic}. Use a neutral commercial presentation without adding claims."
            ),
            "app": (
                "Create a four-view App evidence board from the ordered interface references: primary screen, task flow screen, confirmation or result screen, and layout/detail view. "
                "Preserve screen hierarchy, icons, typography geometry, brand colors, and navigation structure; do not invent UI copy. "
                "Approved App operation logic: {operation_logic}. Keep the interface presentation neutral and evidence-based."
            ),
        }
        boards: list[dict[str, Any]] = []
        for index, binding in enumerate(bindings, start=1):
            if not isinstance(binding, Mapping):
                raise AssetBoardGenerationError(f"{AssetBoardGenerationError.code}: binding {index} is invalid")
            tag = str(binding.get("tag") or "").strip()
            asset_type = str(binding.get("asset_type") or "").strip().casefold()
            path = Path(str(binding.get("path") or ""))
            raw_references = binding.get("reference_images")
            references = [Path(item) for item in raw_references] if isinstance(raw_references, Sequence) and not isinstance(raw_references, (str, bytes, bytearray)) else [path]
            if not tag or asset_type not in templates or not references or len(references) > 9 or any(not item.is_file() for item in references):
                raise AssetBoardGenerationError(f"{AssetBoardGenerationError.code}: binding {index} is invalid")
            prompt = templates[asset_type].format(
                attraction_constraint=str(binding.get("attraction_constraint") or "neutral, non-exaggerated product presentation"),
                display_logic=str(binding.get("display_logic") or "show the approved object at its observed scale and position"),
                operation_logic=str(binding.get("operation_logic") or "show the approved navigation and interaction sequence exactly"),
            )
            try:
                validate_neutral_marketing_terms(prompt, surface="asset_board")
                result = self.run_image2(
                    prompt=prompt,
                    reference_images=references,
                    template=asset_type,
                )
            except Exception as exc:
                raise AssetBoardGenerationError(f"{AssetBoardGenerationError.code}: {tag}") from exc
            image_bytes = result.get("image_bytes") if isinstance(result, Mapping) else None
            if not isinstance(result, Mapping) or not str(result.get("result_url") or "").strip() or not isinstance(result.get("receipt"), Mapping) or not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                raise AssetBoardGenerationError(f"{AssetBoardGenerationError.code}: {tag} returned no receipt")
            source_sha = str(binding.get("source_asset_sha256") or hashlib.sha256(path.read_bytes()).hexdigest()).lower()
            board_sha = hashlib.sha256(bytes(image_bytes)).hexdigest()
            request_record = {
                "asset_type": asset_type,
                "template_version": _asset_template_version(asset_type),
                "source_asset_sha256": source_sha,
            }
            for field in ("source_slot", "source_index", "asset_tag", "image_reference"):
                if field in binding:
                    request_record[field] = binding[field]
            raw_receipt = dict(result["receipt"])
            provider_request_sha = str(raw_receipt.get("request_sha256") or "")
            if not provider_request_sha:
                raise AssetBoardGenerationError(f"{AssetBoardGenerationError.code}: {tag} missing provider request receipt")
            request_record["provider_request_sha256"] = provider_request_sha
            provider_contract_sha = _sha256({
                "asset_type": asset_type,
                "template_version": _asset_template_version(asset_type),
                "source_asset_sha256": source_sha,
                "provider_request_sha256": provider_request_sha,
            })
            receipt = {
                "schema_version": "runninghub-asset-board/v2",
                "asset_type": asset_type,
                "template_version": _asset_template_version(asset_type),
                "source_asset_sha256": source_sha,
                "request_sha256": str(raw_receipt.get("request_sha256") or _sha256(request_record)),
                "response_sha256": str(raw_receipt.get("response_sha256") or _sha256(raw_receipt)),
                "task_id": str(result.get("task_id") or raw_receipt.get("task_id") or ""),
                "board_sha256": board_sha,
                "provider_asset_board_contract_sha256": provider_contract_sha,
                "provider_receipt": raw_receipt,
            }
            boards.append(
                {
                    "tag": tag,
                    "asset_type": asset_type,
                    "board_url": str(result["result_url"]),
                    "board_bytes": bytes(image_bytes),
                    "receipt": receipt,
                    "board_sha256": board_sha,
                    "task_id": str(result.get("task_id") or ""),
                }
            )
        return boards


__all__ = [
    "AssetBoardGenerationError",
    "RunningHubWorkflowClient",
    "RunningHubWorkflowError",
    "parse_plain_lyrics_txt",
    "parse_timestamped_txt",
]
