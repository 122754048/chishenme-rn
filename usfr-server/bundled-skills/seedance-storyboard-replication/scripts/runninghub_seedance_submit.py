from __future__ import annotations

"""RunningHub Standard Model adapter for audited USFR Seedance video tasks."""

import argparse
import hashlib
import json
import math
import mimetypes
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))
SCOPE_SCRIPT_DIR = SERVER_ROOT / "scripts"
if str(SCOPE_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCOPE_SCRIPT_DIR))

from config import DEFAULT_ENV_FILE, build_redacted_provider_preflight, load_settings
from server.runninghub_standard_contract import (
    RUNNINGHUB_STANDARD_SEEDANCE_FIELDS as RUNNINGHUB_STANDARD_PAYLOAD_FIELDS,
    RunningHubStandardPayloadError,
    image_reference_binding_sha256,
    validate_public_https_url,
    validate_image_reference_binding,
    validate_runninghub_standard_payload_contract,
    validate_video_reference_binding,
)
from source_video_reference import (
    SourceVideoReferenceError,
    materialize_source_video_reference,
)
from timeline_scope_preflight import validate_scope_receipt_for_text


RUNNINGHUB_STANDARD_CREATE_URL = (
    "https://www.runninghub.cn/openapi/v2/bytedance/"
    "seedance-2.0-fast-token/multimodal-video"
)
RUNNINGHUB_STANDARD_QUERY_URL = "https://www.runninghub.cn/openapi/v2/query"
RUNNINGHUB_STANDARD_UPLOAD_URL = "https://www.runninghub.cn/openapi/v2/media/upload/binary"
RUNNINGHUB_RUNNING_STATUSES = {"QUEUED", "RUNNING"}
RUNNINGHUB_FAILURE_STATUSES = {"FAILED", "CANCELLED", "CANCELED"}
_TEXT_DEGRADATION = re.compile(r"\?{3,}")


class PayloadError(ValueError):
    pass


class RunningHubSeedanceError(RuntimeError):
    pass


class TaskFailedError(RunningHubSeedanceError):
    pass


class PollTimeoutError(RunningHubSeedanceError):
    pass


def _create_error_details(response: Mapping[str, object]) -> tuple[str, str]:
    error_code = str(response.get("errorCode") or "").strip()
    error_message = str(response.get("errorMessage") or response.get("message") or "").strip()
    return error_code, error_message


def _require_public_https_urls(urls: list[str]) -> None:
    for value in urls:
        try:
            validate_public_https_url(value)
        except RunningHubStandardPayloadError as error:
            raise PayloadError(str(error)) from error


def _provider_duration(duration: int | float) -> int:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise PayloadError("duration must be a number of seconds")
    if not math.isfinite(duration):
        raise PayloadError("duration must be a finite number of seconds")
    provider_duration = math.ceil(duration)
    if not 4 <= provider_duration <= 15:
        raise PayloadError("duration must be between 4 and 15 seconds")
    return provider_duration


def validate_runninghub_standard_payload(
    payload: Mapping[str, object], *, fixed_b: bool = False
) -> str:
    """Validate an exact RunningHub standard-model payload and return its prompt."""

    try:
        validate_runninghub_standard_payload_contract(payload)
    except RunningHubStandardPayloadError as error:
        raise PayloadError(str(error)) from error
    if fixed_b and (payload["resolution"] != "720p" or payload["ratio"] != "9:16"):
        raise PayloadError("fixed-B payload requires 720p and 9:16")
    return str(payload["prompt"])


def runninghub_standard_request_sha256(
    payload: Mapping[str, object], *, fixed_b: bool = False
) -> str:
    """Return the immutable digest of a validated RunningHub standard payload."""

    validate_runninghub_standard_payload(payload, fixed_b=fixed_b)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_runninghub_standard_payload(
    prompt: str,
    duration: int | float,
    ratio: str,
    image_urls: list[str],
    audio_urls: list[str],
    *,
    video_urls: list[str] | None = None,
    real_person_mode: bool,
    resolution: str = "720p",
) -> dict[str, object]:
    """Build the exact documented RunningHub standard-model request body."""

    normalized_prompt = str(prompt or "").strip()
    if not 1 <= len(normalized_prompt) <= 20_480:
        raise PayloadError("prompt must contain 1-20480 characters")
    if resolution not in {"480p", "720p", "1080p", "2k", "4k"}:
        raise PayloadError("resolution is not supported by RunningHub Seedance")
    if ratio not in {"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}:
        raise PayloadError("ratio is not supported by RunningHub Seedance")
    if len(image_urls) > 9:
        raise PayloadError("RunningHub Seedance accepts at most 9 images")
    normalized_video_urls = list(video_urls or [])
    if len(normalized_video_urls) > 1:
        raise PayloadError("USFR accepts exactly zero or one segment video reference")
    if len(audio_urls) > 1:
        raise PayloadError("USFR accepts at most one segment audio reference")
    if audio_urls and "@Audio1" not in normalized_prompt:
        raise PayloadError("uploaded-song audio requires @Audio1 in the prompt")
    _require_public_https_urls(list(image_urls) + normalized_video_urls + list(audio_urls))
    payload: dict[str, object] = {
        "prompt": normalized_prompt,
        "resolution": resolution,
        "duration": str(_provider_duration(duration)),
        "imageUrls": list(image_urls),
        "videoUrls": normalized_video_urls,
        "audioUrls": list(audio_urls),
        "generateAudio": True,
        "ratio": ratio,
        "realPersonMode": bool(real_person_mode),
        "conversionSlots": ["all"] if real_person_mode else [],
        "returnLastFrame": False,
        "seed": -1,
    }
    validate_runninghub_standard_payload(payload)
    return payload


def _read_json(response: Any) -> dict[str, Any]:
    raw = response.read()
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunningHubSeedanceError("RunningHub returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RunningHubSeedanceError("RunningHub response must be a JSON object")
    return value


def _urllib_request_json(
    *, method: str, url: str, headers: dict[str, str], json_body: dict[str, object], timeout: float
) -> tuple[int, dict[str, Any]]:
    request = Request(
        url,
        data=json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), _read_json(response)
    except HTTPError as error:
        return int(error.code), _read_json(error)


def _download_file(url: str, output_path: Path) -> None:
    request = Request(url, method="GET")
    with urlopen(request, timeout=180) as response:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.read())


class RunningHubStandardSeedanceClient:
    """No-retry client for the RunningHub Seedance standard model."""

    def __init__(
        self,
        api_key: str,
        *,
        create_url: str = RUNNINGHUB_STANDARD_CREATE_URL,
        query_url: str = RUNNINGHUB_STANDARD_QUERY_URL,
        upload_url: str = RUNNINGHUB_STANDARD_UPLOAD_URL,
        request_json: Callable[..., tuple[int, dict[str, Any]]] | None = None,
        download: Callable[[str, Path], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not str(api_key or "").strip():
            raise RunningHubSeedanceError("RUNNINGHUB_SEEDANCE_API_KEY is required")
        self.api_key = str(api_key)
        self.create_url = create_url
        self.query_url = query_url
        self.upload_url = upload_url
        self.request_json = request_json or _urllib_request_json
        self.download = download or _download_file
        self.sleep = sleep
        self.clock = clock
        self.last_response: dict[str, Any] = {}
        self.last_status_response: dict[str, Any] = {}

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, url: str, body: dict[str, object]) -> dict[str, Any]:
        try:
            status, response = self.request_json(
                method="POST", url=url, headers=self._headers, json_body=body, timeout=90
            )
        except Exception as error:
            raise RunningHubSeedanceError(
                "RunningHub request failed; paid create outcome is ambiguous and was not retried"
            ) from error
        if status in {401, 403}:
            raise RunningHubSeedanceError(
                f"RunningHub request rejected with HTTP {status}; check RUNNINGHUB_SEEDANCE_API_KEY"
            )
        if not 200 <= status < 300:
            message = str(response.get("errorMessage") or response.get("message") or "request failed")
            raise RunningHubSeedanceError(f"RunningHub request failed with HTTP {status}: {message}")
        return response

    def create_video(self, payload: dict[str, object]) -> str:
        validate_runninghub_standard_payload(payload)
        response = self._post(self.create_url, payload)
        self.last_response = response
        task_id = str(response.get("taskId") or "").strip()
        if not task_id:
            error_code, error_message = _create_error_details(response)
            if error_code:
                detail = f": {error_message}" if error_message else ""
                raise RunningHubSeedanceError(
                    f"RunningHub paid create rejected with {error_code}{detail}; do not retry automatically"
                )
            raise RunningHubSeedanceError(
                "RunningHub paid create response omitted taskId; do not retry automatically"
            )
        return task_id

    def get_status(self, task_id: str) -> dict[str, Any]:
        task = str(task_id or "").strip()
        if not task:
            raise RunningHubSeedanceError("taskId is required")
        response = self._post(self.query_url, {"taskId": task})
        self.last_status_response = response
        return response

    def upload_file(self, path: Path) -> str:
        source = Path(path)
        if not source.is_file():
            raise PayloadError(f"upload file does not exist: {source}")
        boundary = f"----usfr-{uuid4().hex}"
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        body = b"".join(
            (
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="file"; filename="{source.name}"\r\n'
                    f"Content-Type: {mime_type}\r\n\r\n"
                ).encode(),
                source.read_bytes(),
                f"\r\n--{boundary}--\r\n".encode(),
            )
        )
        request = Request(
            self.upload_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                result = _read_json(response)
        except HTTPError as error:
            result = _read_json(error)
            message = str(result.get("message") or result.get("errorMessage") or "upload failed")
            raise RunningHubSeedanceError(f"RunningHub upload failed with HTTP {error.code}: {message}") from error
        data = result.get("data")
        url = str(data.get("download_url") if isinstance(data, dict) else "").strip()
        _require_public_https_urls([url])
        return url

    def download_video(self, video_url: str, output_path: Path) -> None:
        _require_public_https_urls([video_url])
        self.download(video_url, output_path)


def poll_runninghub_task(
    client: RunningHubStandardSeedanceClient,
    task_id: str,
    *,
    timeout: float | None = None,
    poll_interval: float = 3,
) -> str:
    deadline = None if timeout is None else client.clock() + timeout
    poll_index = 0
    schedule = (3.0, 5.0, 8.0, 12.0, 15.0)
    while True:
        response = client.get_status(task_id)
        status = str(response.get("status") or "").upper()
        if status == "SUCCESS":
            results = response.get("results")
            if not isinstance(results, list):
                raise RunningHubSeedanceError("RunningHub success response omitted results")
            for item in results:
                if isinstance(item, Mapping) and str(item.get("outputType") or "").lower() == "mp4":
                    url = str(item.get("url") or "").strip()
                    _require_public_https_urls([url])
                    return url
            raise RunningHubSeedanceError("RunningHub success response omitted an MP4 result")
        if status in RUNNINGHUB_FAILURE_STATUSES:
            message = str(response.get("errorMessage") or response.get("message") or status)
            raise TaskFailedError(message)
        if status not in RUNNINGHUB_RUNNING_STATUSES:
            raise RunningHubSeedanceError(f"unknown RunningHub task status: {status or '<empty>'}")
        if deadline is not None and client.clock() >= deadline:
            raise PollTimeoutError(f"RunningHub task {task_id} timed out")
        if poll_interval == 3:
            delay = schedule[min(poll_index, len(schedule) - 1)]
        else:
            delay = min(15.0, max(0.1, poll_interval) * (1.5 ** poll_index))
        client.sleep(delay)
        poll_index += 1


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_SENSITIVE_RESPONSE_KEY_PARTS = ("authorization", "credential", "key", "secret", "token", "signature")


def _redact_provider_response(value: Any, *, key: str = "") -> Any:
    if any(part in key.casefold() for part in _SENSITIVE_RESPONSE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key): _redact_provider_response(child, key=str(child_key))
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_provider_response(child) for child in value]
    return value


def write_create_reconciliation_receipt(
    output_dir: Path,
    client: RunningHubStandardSeedanceClient,
) -> Path:
    """Persist a non-sensitive receipt when a create response lacks a task ID."""

    path = output_dir / "create_reconciliation.json"
    error_code, error_message = _create_error_details(client.last_response)
    receipt: dict[str, object] = {
        "status": "REJECTED" if error_code else "AMBIGUOUS",
        "task_id": None,
        "automatic_paid_retry": False,
        "response": _redact_provider_response(client.last_response),
    }
    if error_code:
        receipt["error_code"] = error_code
        receipt["error_message"] = error_message
    _write_json(path, receipt)
    return path


def _request_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_bindings(paths: list[Path], urls: list[str]) -> list[dict[str, str]]:
    if len(paths) != len(urls):
        raise PayloadError("uploaded asset binding count mismatch")
    return [
        {
            "sha256": _file_sha256(path),
            "url": url,
        }
        for path, url in zip(paths, urls, strict=True)
    ]


def _read_json_object(path: Path, *, error_message: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PayloadError(error_message) from error
    if not isinstance(value, dict):
        raise PayloadError(error_message)
    return value


def _prepare_source_video_reference(args: argparse.Namespace) -> None:
    """Materialize the one permitted source-video reference before upload."""

    if args.source_video_file is None:
        if args.segment_plan_file is not None:
            raise PayloadError("--segment-plan-file requires --source-video-file")
        return
    if args.video_file or args.video_url:
        raise PayloadError("--source-video-file cannot be combined with --video-file or --video-url")
    if args.segment_plan_file is None:
        raise PayloadError("--source-video-file requires --segment-plan-file")
    if not args.segment_id:
        raise PayloadError("--source-video-file requires --segment-id")
    segment_plan = _read_json_object(
        args.segment_plan_file,
        error_message="the frozen --segment-plan-file is unavailable or invalid",
    )
    try:
        reference = materialize_source_video_reference(
            source_video=args.source_video_file,
            segment_plan=segment_plan,
            segment_id=args.segment_id,
            output_dir=args.output_dir / "source_video_references",
        )
    except SourceVideoReferenceError as error:
        raise PayloadError(str(error)) from error
    supplied_metadata = (
        ("--source-video-sha256", args.source_video_sha256, reference.source_video_sha256),
        ("--source-slice-sha256", args.source_slice_sha256, reference.source_slice_sha256),
        ("--segment-start-ms", args.segment_start_ms, reference.start_ms),
        ("--segment-end-ms", args.segment_end_ms, reference.end_ms),
    )
    for label, supplied, expected in supplied_metadata:
        if supplied is not None and supplied != expected:
            raise PayloadError(f"{label} differs from the frozen source video reference")
    args.video_file = [reference.path]
    args.source_video_sha256 = reference.source_video_sha256
    args.source_slice_sha256 = reference.source_slice_sha256
    args.segment_start_ms = reference.start_ms
    args.segment_end_ms = reference.end_ms
    args.segment_plan_sha256 = hashlib.sha256(
        json.dumps(segment_plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    args.source_video_reference_artifact_id = f"source-reference:{reference.source_slice_sha256}"


def _load_approved_payload(output_dir: Path, approved_sha256: str) -> dict[str, object]:
    payload = _read_json_object(
        output_dir / "request.redacted.json",
        error_message="audited dry-run request is unavailable",
    )
    approval_preview = _read_json_object(
        output_dir / "approval_preview.json",
        error_message="audited dry-run approval preview is unavailable",
    )
    stored_sha256 = str(approval_preview.get("request_sha256") or "").strip()
    request_sha256 = _request_sha256(payload)
    if not stored_sha256 or stored_sha256 != request_sha256 or approved_sha256 != request_sha256:
        raise PayloadError("provide the exact --approved-request-sha256 from the audited dry run")
    validate_runninghub_standard_payload(payload, fixed_b=True)
    _validate_prompt_text_integrity(str(payload.get("prompt") or ""))
    return payload


def _validate_file_bindings(
    *,
    paths: list[Path],
    direct_urls: list[str],
    payload_urls: object,
    binding_key: str,
    asset_bindings: Mapping[str, object],
) -> None:
    if not isinstance(payload_urls, list) or not all(isinstance(url, str) for url in payload_urls):
        raise PayloadError("audited dry-run payload media URLs are invalid")
    raw_bindings = asset_bindings.get(binding_key, [])
    if not isinstance(raw_bindings, list) or not all(isinstance(binding, Mapping) for binding in raw_bindings):
        raise PayloadError("audited dry-run asset bindings are invalid")
    if paths:
        if len(paths) != len(raw_bindings):
            raise PayloadError("submitted asset files do not match the audited dry run")
        for path, binding in zip(paths, raw_bindings, strict=True):
            if _file_sha256(path) != str(binding.get("sha256") or ""):
                raise PayloadError("submitted asset files do not match the audited dry run")
        bound_urls = [str(binding.get("url") or "") for binding in raw_bindings]
        if list(payload_urls) != [*direct_urls, *bound_urls]:
            raise PayloadError("submitted asset URLs do not match the audited dry run")
    elif direct_urls and list(payload_urls) != direct_urls:
        raise PayloadError("submitted asset URLs do not match the audited dry run")


def _parse_target_changes(values: list[str]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for value in values:
        kind, separator, evidence = str(value).partition(":")
        if not separator or not kind or not evidence:
            raise PayloadError("--target-change must use kind:sha256 or output_language:language")
        if kind == "output_language":
            changes.append({"kind": kind, "value": evidence})
        else:
            changes.append({"kind": kind, "sha256": evidence})
    return changes


_IMAGE_ROLE_MANIFEST_FIELDS = frozenset({"schema_version", "approval_set_sha256", "images"})
_IMAGE_ROLE_ROW_FIELDS = frozenset(
    {"role", "artifact_name", "sha256", "cut_ids", "page", "approval_set_sha256", "purpose"}
)


def _build_image_reference_binding(
    *,
    payload: Mapping[str, object],
    image_urls: list[str],
    image_files: list[Path],
    direct_url_count: int,
    manifest_path: Path | None,
) -> dict[str, object]:
    """Compile the pre-upload role manifest into exact provider URL bindings."""

    if manifest_path is None:
        raise PayloadError("Seedance images require --image-role-manifest")
    manifest = _read_json_object(
        manifest_path,
        error_message="the --image-role-manifest is unavailable or invalid",
    )
    if set(manifest) != _IMAGE_ROLE_MANIFEST_FIELDS or manifest.get("schema_version") != "usfr-image-role-manifest/v1":
        raise PayloadError("--image-role-manifest must use the complete usfr-image-role-manifest/v1 schema")
    rows = manifest.get("images")
    if not isinstance(rows, list) or len(rows) != len(image_urls) or not 1 <= len(rows) <= 9:
        raise PayloadError("--image-role-manifest must describe every one-to-nine image exactly once")
    if direct_url_count < 0 or direct_url_count + len(image_files) != len(image_urls):
        raise PayloadError("image role manifest order differs from direct/uploaded image order")
    bindings: list[dict[str, object]] = []
    for index, (row, url) in enumerate(zip(rows, image_urls, strict=True), start=1):
        if not isinstance(row, Mapping) or set(row) != _IMAGE_ROLE_ROW_FIELDS:
            raise PayloadError("--image-role-manifest contains an incomplete image descriptor")
        descriptor = dict(row)
        declared_sha = str(descriptor.get("sha256") or "").lower()
        if index > direct_url_count:
            path = image_files[index - direct_url_count - 1]
            if descriptor.get("artifact_name") != path.name or declared_sha != _file_sha256(path):
                raise PayloadError("uploaded image bytes or artifact name differ from --image-role-manifest")
        descriptor.update({"image_index": index, "tag": f"@Image{index}", "url": url})
        bindings.append(descriptor)
    binding = {
        "schema_version": "usfr-multimodal-reference-binding/v2",
        "ordered_image_urls": list(image_urls),
        "approval_set_sha256": manifest.get("approval_set_sha256"),
        "image_bindings": bindings,
        "slot_policy": "continuous-present-role-order/v1",
        "forbidden_artifact_names": ["seedance_execution_carrier.png"],
    }
    try:
        validate_image_reference_binding(payload, binding)
    except RunningHubStandardPayloadError as error:
        raise PayloadError(str(error)) from error
    return binding


def _build_video_reference_binding(
    *,
    video_urls: list[str],
    video_files: list[Path],
    image_reference_binding: Mapping[str, object] | None,
    source_video_sha256: str | None,
    source_slice_sha256: str | None,
    segment_id: str | None,
    segment_start_ms: int | None,
    segment_end_ms: int | None,
    segment_plan_sha256: str | None,
    source_video_reference_artifact_id: str | None,
    target_change_values: list[str],
) -> dict[str, object] | None:
    metadata = (
        source_video_sha256,
        source_slice_sha256,
        segment_id,
        segment_start_ms,
        segment_end_ms,
        segment_plan_sha256,
        source_video_reference_artifact_id,
        target_change_values,
    )
    if not video_urls:
        if video_files or any(value is not None and value != [] for value in metadata):
            raise PayloadError("video-reference metadata requires exactly one --video-file or --video-url")
        return None
    if len(video_urls) != 1 or len(video_files) > 1:
        raise PayloadError("USFR accepts exactly one source segment video reference")
    if image_reference_binding is None:
        raise PayloadError("a source video reference requires the complete multimodal image binding")
    if not source_video_sha256 or not segment_id or segment_start_ms is None or segment_end_ms is None:
        raise PayloadError(
            "a source video reference requires --source-video-sha256, --segment-id, --segment-start-ms, and --segment-end-ms"
        )
    actual_slice_sha256 = _file_sha256(video_files[0]) if video_files else source_slice_sha256
    if source_slice_sha256 and video_files and source_slice_sha256 != actual_slice_sha256:
        raise PayloadError("--source-slice-sha256 differs from the supplied --video-file")
    if not actual_slice_sha256:
        raise PayloadError("a --video-url requires --source-slice-sha256")
    if not segment_plan_sha256 or not source_video_reference_artifact_id:
        raise PayloadError("a source video reference requires frozen segment-plan and source-slice artifact bindings")
    return {
        "schema_version": "usfr-video-reference/v1",
        "url": video_urls[0],
        "source_video_sha256": source_video_sha256,
        "source_slice_sha256": actual_slice_sha256,
        "segment_id": segment_id,
        "segment_plan_sha256": segment_plan_sha256,
        "source_video_reference_artifact_id": source_video_reference_artifact_id,
        "start_ms": segment_start_ms,
        "end_ms": segment_end_ms,
        "image_reference_binding_sha256": image_reference_binding_sha256(image_reference_binding),
        "target_changes": _parse_target_changes(target_change_values),
    }


def _validate_approved_payload_matches_submission(
    payload: Mapping[str, object],
    *,
    output_dir: Path,
    prompt: str,
    duration: int | float,
    ratio: str,
    real_person_mode: bool,
    image_files: list[Path],
    image_urls: list[str],
    image_role_manifest: Path | None,
    audio_files: list[Path],
    audio_urls: list[str],
    video_files: list[Path],
    video_urls: list[str],
    source_video_sha256: str | None,
    source_slice_sha256: str | None,
    segment_id: str | None,
    segment_start_ms: int | None,
    segment_end_ms: int | None,
    segment_plan_sha256: str | None,
    source_video_reference_artifact_id: str | None,
    target_change_values: list[str],
) -> None:
    expected = {
        "prompt": str(prompt or "").strip(),
        "duration": str(_provider_duration(duration)),
        "ratio": ratio,
        "realPersonMode": bool(real_person_mode),
        "conversionSlots": ["all"] if real_person_mode else [],
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise PayloadError("submission parameters do not match the audited dry run")
    if image_files or image_urls or image_role_manifest or audio_files or video_files or video_urls:
        asset_bindings = _read_json_object(
            output_dir / "asset_bindings.json",
            error_message="audited dry-run asset bindings are unavailable",
        )
        _validate_file_bindings(
            paths=image_files,
            direct_urls=image_urls,
            payload_urls=payload.get("imageUrls"),
            binding_key="image_file_bindings",
            asset_bindings=asset_bindings,
        )
        _validate_file_bindings(
            paths=video_files,
            direct_urls=video_urls,
            payload_urls=payload.get("videoUrls"),
            binding_key="video_file_bindings",
            asset_bindings=asset_bindings,
        )
        stored_video_reference = asset_bindings.get("video_reference")
        stored_image_reference = asset_bindings.get("image_reference_binding")
        expected_image_reference = _build_image_reference_binding(
            payload=payload,
            image_urls=list(payload.get("imageUrls") or []),
            image_files=image_files,
            direct_url_count=len(image_urls),
            manifest_path=image_role_manifest,
        )
        if stored_image_reference != expected_image_reference:
            raise PayloadError("submitted image reference binding differs from the audited dry run")
        expected_video_reference = _build_video_reference_binding(
            video_urls=list(payload.get("videoUrls") or []),
            video_files=video_files,
            image_reference_binding=expected_image_reference,
            source_video_sha256=source_video_sha256,
            source_slice_sha256=source_slice_sha256,
            segment_id=segment_id,
            segment_start_ms=segment_start_ms,
            segment_end_ms=segment_end_ms,
            segment_plan_sha256=segment_plan_sha256,
            source_video_reference_artifact_id=source_video_reference_artifact_id,
            target_change_values=target_change_values,
        )
        if stored_video_reference != expected_video_reference:
            raise PayloadError("submitted video reference differs from the audited dry run")
        try:
            validate_video_reference_binding(payload, expected_video_reference)
        except RunningHubStandardPayloadError as error:
            raise PayloadError(str(error)) from error
        _validate_file_bindings(
            paths=audio_files,
            direct_urls=audio_urls,
            payload_urls=payload.get("audioUrls"),
            binding_key="audio_file_bindings",
            asset_bindings=asset_bindings,
        )


def _validate_prompt_text_integrity(prompt: str) -> None:
    if "\ufffd" in prompt or "\x00" in prompt or _TEXT_DEGRADATION.search(prompt):
        raise PayloadError("prompt contains a replacement or question-mark placeholder")


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit an audited USFR Seedance task to RunningHub Standard Model API.")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--scope-receipt", type=Path)
    parser.add_argument("--image-url", action="append", default=[])
    parser.add_argument("--image-file", action="append", type=Path, default=[])
    parser.add_argument("--image-role-manifest", type=Path)
    parser.add_argument("--audio-url", action="append", default=[])
    parser.add_argument("--audio-file", action="append", type=Path, default=[])
    parser.add_argument("--video-url", action="append", default=[])
    parser.add_argument("--video-file", action="append", type=Path, default=[])
    parser.add_argument("--source-video-file", type=Path)
    parser.add_argument("--segment-plan-file", type=Path)
    parser.add_argument("--source-video-sha256")
    parser.add_argument("--source-slice-sha256")
    parser.add_argument("--segment-id")
    parser.add_argument("--segment-start-ms", type=int)
    parser.add_argument("--segment-end-ms", type=int)
    parser.add_argument("--target-change", action="append", default=[])
    parser.add_argument("--duration", type=float)
    parser.add_argument("--ratio", default="9:16")
    parser.add_argument("--real-person-mode", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approved-request-sha256")
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--resume-task-id")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--poll-interval", type=float, default=3)
    args = parser.parse_args()
    if (args.audio_url or args.audio_file) and args.source_video_file is None:
        parser.error("audio references require an orchestrated --source-video-file segment")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings(args.env_file)
    if args.preflight:
        if any((args.prompt_file, args.scope_receipt, args.image_url, args.image_file, args.image_role_manifest, args.audio_url, args.audio_file, args.video_url, args.video_file, args.source_video_file, args.segment_plan_file, args.source_video_sha256, args.source_slice_sha256, args.segment_id, args.segment_start_ms, args.segment_end_ms, args.target_change, args.duration, args.dry_run, args.poll, args.resume_task_id, args.approved_request_sha256)):
            raise PayloadError("--preflight cannot be combined with a Seedance task option")
        _write_json(args.output_dir / "provider_preflight.json", build_redacted_provider_preflight(args.env_file))
        return 0
    settings.require_seedance()
    client = RunningHubStandardSeedanceClient(
        settings.runninghub_seedance_api_key,
        create_url=settings.runninghub_seedance_create_url,
        query_url=settings.runninghub_seedance_query_url,
        upload_url=settings.runninghub_seedance_upload_url,
    )
    if args.resume_task_id:
        if args.dry_run or args.approved_request_sha256 or args.image_role_manifest or args.audio_url or args.audio_file or args.video_url or args.video_file or args.source_video_file or args.segment_plan_file or args.source_video_sha256 or args.source_slice_sha256 or args.segment_id or args.segment_start_ms is not None or args.segment_end_ms is not None or args.target_change:
            raise PayloadError("resume-task-id cannot be combined with a new request option")
        task_id = args.resume_task_id
    else:
        if args.prompt_file is None or args.scope_receipt is None or args.duration is None:
            raise PayloadError("--prompt-file, --scope-receipt, and --duration are required for a new Seedance request")
        prompt = args.prompt_file.read_text(encoding="utf-8-sig")
        _validate_prompt_text_integrity(prompt)
        validate_scope_receipt_for_text(json.loads(args.scope_receipt.read_text(encoding="utf-8-sig")), prompt)
        _prepare_source_video_reference(args)
        if args.dry_run:
            uploaded_image_urls = [client.upload_file(path) for path in args.image_file]
            uploaded_audio_urls = [client.upload_file(path) for path in args.audio_file]
            uploaded_video_urls = [client.upload_file(path) for path in args.video_file]
            image_urls = [*args.image_url, *uploaded_image_urls]
            video_urls = [*args.video_url, *uploaded_video_urls]
            payload = build_runninghub_standard_payload(
                prompt,
                args.duration,
                args.ratio,
                image_urls,
                [*args.audio_url, *uploaded_audio_urls],
                video_urls=video_urls,
                real_person_mode=args.real_person_mode,
            )
            image_reference = _build_image_reference_binding(
                payload=payload,
                image_urls=image_urls,
                image_files=args.image_file,
                direct_url_count=len(args.image_url),
                manifest_path=args.image_role_manifest,
            )
            video_reference = _build_video_reference_binding(
                video_urls=video_urls,
                video_files=args.video_file,
                image_reference_binding=image_reference,
                source_video_sha256=args.source_video_sha256,
                source_slice_sha256=args.source_slice_sha256,
                segment_id=args.segment_id,
                segment_start_ms=args.segment_start_ms,
                segment_end_ms=args.segment_end_ms,
                segment_plan_sha256=args.segment_plan_sha256,
                source_video_reference_artifact_id=args.source_video_reference_artifact_id,
                target_change_values=args.target_change,
            )
            try:
                validate_image_reference_binding(payload, image_reference)
                validate_video_reference_binding(payload, video_reference)
            except RunningHubStandardPayloadError as error:
                raise PayloadError(str(error)) from error
            request_sha256 = _request_sha256(payload)
            _write_json(args.output_dir / "request.redacted.json", payload)
            _write_json(args.output_dir / "approval_preview.json", {"request_sha256": request_sha256})
            _write_json(
                args.output_dir / "asset_bindings.json",
                {
                    "schema_version": "runninghub-standard-seedance-asset-bindings/v1",
                    "image_file_bindings": _file_bindings(args.image_file, uploaded_image_urls),
                    "image_reference_binding": image_reference,
                    "audio_file_bindings": _file_bindings(args.audio_file, uploaded_audio_urls),
                    "video_file_bindings": _file_bindings(args.video_file, uploaded_video_urls),
                    "video_reference": video_reference,
                },
            )
            _write_json(args.output_dir / "status.json", {"status": "dry_run"})
            return 0
        if not args.approved_request_sha256:
            raise PayloadError("provide the exact --approved-request-sha256 from the audited dry run")
        payload = _load_approved_payload(args.output_dir, args.approved_request_sha256)
        _validate_approved_payload_matches_submission(
            payload,
            output_dir=args.output_dir,
            prompt=prompt,
            duration=args.duration,
            ratio=args.ratio,
            real_person_mode=args.real_person_mode,
            image_files=args.image_file,
            image_urls=args.image_url,
            image_role_manifest=args.image_role_manifest,
            audio_files=args.audio_file,
            audio_urls=args.audio_url,
            video_files=args.video_file,
            video_urls=args.video_url,
            source_video_sha256=args.source_video_sha256,
            source_slice_sha256=args.source_slice_sha256,
            segment_id=args.segment_id,
            segment_start_ms=args.segment_start_ms,
            segment_end_ms=args.segment_end_ms,
            segment_plan_sha256=args.segment_plan_sha256,
            source_video_reference_artifact_id=args.source_video_reference_artifact_id,
            target_change_values=args.target_change,
        )
        try:
            task_id = client.create_video(payload)
        except RunningHubSeedanceError:
            if client.last_response:
                write_create_reconciliation_receipt(args.output_dir, client)
            raise
        _write_json(args.output_dir / "create_response.json", client.last_response)
    (args.output_dir / "task_id.txt").write_text(str(task_id), encoding="utf-8")
    if args.poll:
        try:
            video_url = poll_runninghub_task(
                client, str(task_id), timeout=args.timeout, poll_interval=args.poll_interval
            )
        except TaskFailedError as error:
            _write_json(
                args.output_dir / "failure.json",
                {
                    "task_id": str(task_id),
                    "status": "failed",
                    "error_message": str(error),
                    "provider_status": _redact_provider_response(client.last_status_response),
                },
            )
            raise
        _write_json(args.output_dir / "status.json", client.last_status_response)
        client.download_video(video_url, args.output_dir / "result.mp4")
    else:
        _write_json(args.output_dir / "status.json", {"task_id": str(task_id), "status": "created"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
