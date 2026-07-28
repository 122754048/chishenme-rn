diff --git a/usfr-server/server/high_fidelity_ports.py b/usfr-server/server/high_fidelity_ports.py
index c882055..150a455 100644
--- a/usfr-server/server/high_fidelity_ports.py
+++ b/usfr-server/server/high_fidelity_ports.py
@@ -24,24 +24,24 @@ from typing import Any, Callable
 from .errors import ReplicationError
 
 
-_SEEDANCE_SUBMIT_MODULE: Any | None = None
+_RUNNINGHUB_SUBMIT_MODULE: Any | None = None
 _SHA256 = re.compile(r"^[0-9a-f]{64}$")
 
 
-def _load_seedance_submit_module() -> Any:
-    """Load the bundled fixed-B payload authority from deployed bytes."""
+def _load_runninghub_submit_module() -> Any:
+    """Load the bundled RunningHub fixed-B payload authority from deployed bytes."""
 
-    global _SEEDANCE_SUBMIT_MODULE
-    if _SEEDANCE_SUBMIT_MODULE is not None:
-        return _SEEDANCE_SUBMIT_MODULE
+    global _RUNNINGHUB_SUBMIT_MODULE
+    if _RUNNINGHUB_SUBMIT_MODULE is not None:
+        return _RUNNINGHUB_SUBMIT_MODULE
     script = (
         Path(__file__).resolve().parents[1]
         / "bundled-skills"
         / "seedance-storyboard-replication"
         / "scripts"
-        / "seedance_submit.py"
+        / "runninghub_seedance_submit.py"
     )
-    module_name = "usfr_high_fidelity_seedance_submit"
+    module_name = "usfr_high_fidelity_runninghub_submit"
     spec = importlib.util.spec_from_file_location(module_name, script)
     if spec is None or spec.loader is None:
         raise RuntimeError("bundled Seedance payload validator cannot be loaded")
@@ -52,7 +52,7 @@ def _load_seedance_submit_module() -> Any:
         spec.loader.exec_module(module)
     finally:
         sys.path.pop(0)
-    _SEEDANCE_SUBMIT_MODULE = module
+    _RUNNINGHUB_SUBMIT_MODULE = module
     return module
 
 
@@ -652,21 +652,16 @@ class HighFidelityStageAdapter:
             raw_payload = json.loads(
                 json.dumps(template, ensure_ascii=False)
             )
-            content = raw_payload.get("content")
-            if (
-                not isinstance(content, list)
-                or not content
-                or not isinstance(content[0], Mapping)
-            ):
+            if not isinstance(raw_payload.get("prompt"), str):
                 raise ReplicationError(
                     "PROMPT_INTEGRITY_FAILED",
-                    "provider_payload_template is missing its text carrier",
+                    "provider_payload_template is missing its direct prompt",
                     category="contract",
                     user_action_required=True,
                     details={"segment_id": segment_id},
                     http_status=422,
                 )
-            content[0] = {**dict(content[0]), "text": compiled_prompt}
+            raw_payload["prompt"] = compiled_prompt
         if not isinstance(raw_payload, Mapping):
             raise ReplicationError(
                 "PROMPT_INTEGRITY_FAILED",
@@ -677,15 +672,13 @@ class HighFidelityStageAdapter:
                 http_status=422,
             )
         payload = dict(raw_payload)
-        validator = _load_seedance_submit_module()
+        validator = _load_runninghub_submit_module()
         try:
-            validator._validate_audited_fixed_b_payload(payload)  # noqa: SLF001 - bundled authority
-            prompt = validator._payload_prompt(payload)  # noqa: SLF001 - bundled authority
-            validator._validate_route_integrity(payload, prompt)  # noqa: SLF001 - bundled authority
+            prompt = validator.validate_runninghub_standard_payload(payload, fixed_b=True)
             compiled_prompt = result.get("compiled_prompt")
             if compiled_prompt is not None and prompt != compiled_prompt:
                 raise ValueError("provider payload prompt differs from Invocation B output")
-            request_sha256 = validator.request_sha256(payload)
+            request_sha256 = validator.runninghub_standard_request_sha256(payload, fixed_b=True)
             for source_name, source in (("request", request), ("result", result)):
                 declared = source.get("request_sha256")
                 if declared is not None and declared != request_sha256:
diff --git a/usfr-server/tests/test_high_fidelity_ports.py b/usfr-server/tests/test_high_fidelity_ports.py
index 44c95f3..2f195a6 100644
--- a/usfr-server/tests/test_high_fidelity_ports.py
+++ b/usfr-server/tests/test_high_fidelity_ports.py
@@ -47,13 +47,18 @@ def _factor_coverage() -> list[dict]:
 
 def _provider_payload(prompt: str, *, duration: int = 8) -> dict:
     return {
-        "model": "seedance-2.0",
-        "content": [{"type": "text", "text": prompt}],
-        "generate_audio": True,
-        "ratio": "9:16",
-        "duration": duration,
-        "watermark": False,
+        "prompt": prompt,
         "resolution": "720p",
+        "duration": str(duration),
+        "imageUrls": ["https://media.example/board.png"],
+        "videoUrls": [],
+        "audioUrls": [],
+        "generateAudio": True,
+        "ratio": "9:16",
+        "realPersonMode": False,
+        "conversionSlots": [],
+        "returnLastFrame": False,
+        "seed": -1,
     }
 
 
@@ -69,6 +74,67 @@ def _request_sha(payload: dict) -> str:
 
 
 class HighFidelityPortsTest(unittest.TestCase):
+    def test_provider_binding_accepts_exact_runninghub_standard_payload(self):
+        payload = _provider_payload("Prompt for S01")
+
+        binding = HighFidelityStageAdapter._provider_binding(
+            segment_id="S01",
+            segment_plan_sha256="a" * 64,
+            request={"provider_payload": payload},
+            result={"compiled_prompt": "Prompt for S01"},
+        )
+
+        self.assertEqual(binding["provider_payload"], payload)
+        self.assertEqual(binding["request_sha256"], _request_sha(payload))
+
+    def test_provider_binding_substitutes_compiled_prompt_into_direct_template_prompt(self):
+        template = _provider_payload("stale template prompt")
+
+        binding = HighFidelityStageAdapter._provider_binding(
+            segment_id="S01",
+            segment_plan_sha256="a" * 64,
+            request={"provider_payload_template": template},
+            result={"compiled_prompt": "Exact approved prompt"},
+        )
+
+        self.assertEqual(binding["provider_payload"]["prompt"], "Exact approved prompt")
+        self.assertNotIn("content", binding["provider_payload"])
+
+    def test_provider_binding_rejects_legacy_content_asset_payload(self):
+        legacy_payload = {
+            "model": "seedance-2.0",
+            "content": [
+                {"type": "text", "text": "Prompt for S01"},
+                {
+                    "type": "image_url",
+                    "role": "reference_image",
+                    "image_url": {"url": "asset://asset-source-frame"},
+                },
+            ],
+            "generate_audio": True,
+            "ratio": "9:16",
+            "duration": 8,
+            "watermark": False,
+            "resolution": "720p",
+        }
+
+        with self.assertRaisesRegex(ReplicationError, "canonical"):
+            HighFidelityStageAdapter._provider_binding(
+                segment_id="S01",
+                segment_plan_sha256="a" * 64,
+                request={"provider_payload": legacy_payload},
+                result={"compiled_prompt": "Prompt for S01"},
+            )
+
+    def test_provider_binding_rejects_route_excluded_prompt_through_runninghub_validator(self):
+        with self.assertRaisesRegex(ReplicationError, "canonical"):
+            HighFidelityStageAdapter._provider_binding(
+                segment_id="S01",
+                segment_plan_sha256="a" * 64,
+                request={"provider_payload": _provider_payload("Preserve the source video framing.")},
+                result={"compiled_prompt": "Preserve the source video framing."},
+            )
+
     def test_invocation_b_blocks_source_audio_when_confirmed_performance_artifact_is_missing(self):
         with tempfile.TemporaryDirectory() as tmp:
             root = Path(tmp)

--- FULL UNTRACKED STANDARD SUBMITTER ---

from __future__ import annotations

"""RunningHub Standard Model adapter for USFR Seedance video tasks.

The adapter deliberately accepts only storyboard/target-image and optional
segment-bounded audio references.  Source-video, opaque UI and tail-video
references are not supported by this fixed-B USFR route and therefore cannot
reach the Seedance endpoint through this command.
"""

import argparse
import hashlib
import ipaddress
import json
import math
import mimetypes
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from config import DEFAULT_ENV_FILE, build_redacted_provider_preflight, load_settings


RUNNINGHUB_STANDARD_CREATE_URL = (
    "https://www.runninghub.cn/openapi/v2/bytedance/"
    "seedance-2.0-fast-token/multimodal-video"
)
RUNNINGHUB_STANDARD_QUERY_URL = "https://www.runninghub.cn/openapi/v2/query"
RUNNINGHUB_STANDARD_UPLOAD_URL = "https://www.runninghub.cn/openapi/v2/media/upload/binary"
RUNNINGHUB_RUNNING_STATUSES = {"QUEUED", "RUNNING"}
RUNNINGHUB_FAILURE_STATUSES = {"FAILED", "CANCELLED", "CANCELED"}
RUNNINGHUB_STANDARD_PAYLOAD_FIELDS = frozenset(
    {
        "prompt",
        "resolution",
        "duration",
        "imageUrls",
        "videoUrls",
        "audioUrls",
        "generateAudio",
        "ratio",
        "realPersonMode",
        "conversionSlots",
        "returnLastFrame",
        "seed",
    }
)
_ROUTE_LEAKAGE_MARKERS = (
    "source_video",
    "opaque_ui",
    "ui_demo",
    "opaque_ui_demo",
    "opaque_ui_video",
    "ui_demo_video",
    "generated_ui_demo",
    "generated_ui",
    "ui_render_contract",
    "ui_truth_card",
    "ui_qc_report",
    "ui_operation_video",
    "ui_media",
    "ui_rendered_media",
    "ui_media_sha256",
    "ui_ocr_evidence",
    "ui_layout_evidence",
    "animation_interval_evidence",
    "tail_video",
    "tail_card",
    "tail_card_video",
    "app_tail_card_video",
    "opaque_app_tail_card",
    "opaque_tail",
    "append_opaque_tail",
    "tail_truth_card",
    "tail_render_contract",
    "tail_qc_report",
    "tail_media",
    "tail_media_sha256",
    "rendered_media",
    "media_sha256",
    "qc_report",
    "transition_render_receipt",
    "transition_render_receipts",
    "source_ui_frames",
    "source_interval",
    "source_ui_keep",
    "transition_shell",
    "reference_videos",
    "reference_audios",
    "excluded_app_end_card",
    "omit_source_end_card",
    "excluded_region",
)
_ROUTE_LEAKAGE_EXACT_KEYS = {
    "ui_truth",
    "tail_truth",
    "ui_render",
    "tail_render",
    "ui_qc",
    "tail_qc",
}
_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]", re.DOTALL)


class PayloadError(ValueError):
    pass


class RunningHubSeedanceError(RuntimeError):
    pass


class TaskFailedError(RunningHubSeedanceError):
    pass


class PollTimeoutError(RunningHubSeedanceError):
    pass


def _require_public_https_urls(urls: list[str]) -> None:
    for value in urls:
        parsed = urlparse(value)
        try:
            hostname = parsed.hostname
        except ValueError as error:
            raise PayloadError("media URLs must be public HTTPS URLs") from error
        if parsed.scheme != "https" or not hostname:
            raise PayloadError("media URLs must be public HTTPS URLs")
        normalized_host = hostname.rstrip(".").casefold()
        if normalized_host == "localhost":
            raise PayloadError("media URLs must be public HTTPS URLs")
        try:
            address = ipaddress.ip_address(unquote(hostname).split("%", 1)[0])
        except ValueError:
            continue
        if not address.is_global:
            raise PayloadError("media URLs must be public HTTPS URLs")


def _route_tokens(value: str) -> list[str]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    separated = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", separated)
    return re.findall(r"[a-z0-9]+", separated.casefold())


def _canonical_route_key(value: str) -> str:
    return "_".join(_route_tokens(value))


def _route_leakage_matches(value: str) -> list[str]:
    tokens = _route_tokens(value)
    if not tokens:
        return []
    token_set = set(tokens)
    matches: list[str] = []
    for marker in _ROUTE_LEAKAGE_MARKERS:
        marker_tokens = _route_tokens(marker)
        width = len(marker_tokens)
        compact = "".join(marker_tokens)
        if compact in token_set or any(
            tokens[index : index + width] == marker_tokens
            for index in range(len(tokens) - width + 1)
        ):
            matches.append(marker)
    return matches


def _route_leakage_in_value(value: object) -> list[str]:
    matches: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                canonical_key = _canonical_route_key(key)
                if canonical_key in _ROUTE_LEAKAGE_EXACT_KEYS:
                    matches.append(key)
                matches.extend(_route_leakage_matches(key))
            matches.extend(_route_leakage_in_value(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            matches.extend(_route_leakage_in_value(child))
    elif isinstance(value, str):
        matches.extend(_route_leakage_matches(value))
    return list(dict.fromkeys(matches))


def _contains_unresolved_placeholder(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_unresolved_placeholder(key)
            or _contains_unresolved_placeholder(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unresolved_placeholder(child) for child in value)
    return isinstance(value, str) and _PLACEHOLDER_RE.search(value) is not None


def _validate_route_integrity(payload: Mapping[str, object]) -> None:
    leaked = _route_leakage_in_value(payload)
    if leaked:
        raise PayloadError(
            "route leakage detected in Seedance prompt or provider payload: "
            + ", ".join(leaked)
        )
    if _contains_unresolved_placeholder(payload):
        raise PayloadError("compiled prompt contains unresolved placeholders")


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

    if not isinstance(payload, Mapping) or set(payload) != RUNNINGHUB_STANDARD_PAYLOAD_FIELDS:
        raise PayloadError("standard Seedance payload contains unknown or missing provider fields")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or prompt != prompt.strip() or not 1 <= len(prompt) <= 20_480:
        raise PayloadError("prompt must contain 1-20480 trimmed characters")
    _validate_route_integrity(payload)
    resolution = payload.get("resolution")
    if resolution not in {"480p", "720p", "1080p", "2k", "4k"}:
        raise PayloadError("resolution is not supported by RunningHub Seedance")
    ratio = payload.get("ratio")
    if ratio not in {"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}:
        raise PayloadError("ratio is not supported by RunningHub Seedance")
    duration = payload.get("duration")
    if not isinstance(duration, str) or duration not in {str(value) for value in range(4, 16)}:
        raise PayloadError("duration must be a string between 4 and 15 seconds")
    image_urls = payload.get("imageUrls")
    audio_urls = payload.get("audioUrls")
    if not isinstance(image_urls, list) or not all(isinstance(url, str) for url in image_urls):
        raise PayloadError("imageUrls must be a list of public HTTPS URLs")
    if not isinstance(audio_urls, list) or not all(isinstance(url, str) for url in audio_urls):
        raise PayloadError("audioUrls must be a list of public HTTPS URLs")
    if len(image_urls) > 9:
        raise PayloadError("RunningHub Seedance accepts at most 9 images")
    if len(audio_urls) > 1:
        raise PayloadError("USFR accepts at most one segment audio reference")
    if payload.get("videoUrls") != []:
        raise PayloadError("standard Seedance payload cannot include video references")
    _require_public_https_urls([*image_urls, *audio_urls])
    if audio_urls and "@Audio1" not in prompt:
        raise PayloadError("uploaded-song audio requires @Audio1 in the prompt")
    real_person_mode = payload.get("realPersonMode")
    if not isinstance(real_person_mode, bool):
        raise PayloadError("realPersonMode must be a boolean")
    if payload.get("generateAudio") is not True:
        raise PayloadError("generateAudio must be enabled")
    if payload.get("conversionSlots") != (["all"] if real_person_mode else []):
        raise PayloadError("conversionSlots must match realPersonMode")
    if payload.get("returnLastFrame") is not False or payload.get("seed") != -1:
        raise PayloadError("returnLastFrame and seed must use the fixed USFR values")
    if fixed_b and (resolution != "720p" or ratio != "9:16"):
        raise PayloadError("fixed-B payload requires 720p and 9:16")
    return prompt


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
    if len(audio_urls) > 1:
        raise PayloadError("USFR accepts at most one segment audio reference")
    if audio_urls and "@Audio1" not in normalized_prompt:
        raise PayloadError("uploaded-song audio requires @Audio1 in the prompt")
    _require_public_https_urls(list(image_urls) + list(audio_urls))
    payload: dict[str, object] = {
        "prompt": normalized_prompt,
        "resolution": resolution,
        "duration": str(_provider_duration(duration)),
        "imageUrls": list(image_urls),
        # Deliberately frozen for source-fidelity fixed-B generation: source
        # video and non-generated UI/tail media must never become model input.
        "videoUrls": [],
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
    poll_interval: float = 20,
) -> str:
    deadline = None if timeout is None else client.clock() + timeout
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
        client.sleep(poll_interval)


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _request_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit an audited USFR Seedance task to RunningHub Standard Model API.")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--image-url", action="append", default=[])
    parser.add_argument("--image-file", action="append", type=Path, default=[])
    parser.add_argument("--audio-url", action="append", default=[])
    parser.add_argument("--audio-file", action="append", type=Path, default=[])
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
    parser.add_argument("--poll-interval", type=float, default=20)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings(args.env_file)
    if args.preflight:
        if any((args.prompt_file, args.image_url, args.image_file, args.audio_url, args.audio_file, args.duration, args.dry_run, args.poll, args.resume_task_id, args.approved_request_sha256)):
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
        if args.dry_run or args.approved_request_sha256:
            raise PayloadError("resume-task-id cannot be combined with a new request option")
        task_id = args.resume_task_id
    else:
        if args.prompt_file is None or args.duration is None:
            raise PayloadError("--prompt-file and --duration are required for a new Seedance request")
        prompt = args.prompt_file.read_text(encoding="utf-8-sig")
        image_urls = [*args.image_url, *(client.upload_file(path) for path in args.image_file)]
        audio_urls = [*args.audio_url, *(client.upload_file(path) for path in args.audio_file)]
        payload = build_runninghub_standard_payload(
            prompt, args.duration, args.ratio, image_urls, audio_urls, real_person_mode=args.real_person_mode
        )
        request_sha256 = _request_sha256(payload)
        _write_json(args.output_dir / "request.redacted.json", payload)
        _write_json(args.output_dir / "approval_preview.json", {"request_sha256": request_sha256})
        if args.dry_run:
            _write_json(args.output_dir / "status.json", {"status": "dry_run"})
            return 0
        if args.approved_request_sha256 != request_sha256:
            raise PayloadError("provide the exact --approved-request-sha256 from the audited dry run")
        task_id = client.create_video(payload)
        _write_json(args.output_dir / "create_response.json", client.last_response)
    (args.output_dir / "task_id.txt").write_text(str(task_id), encoding="utf-8")
    if args.poll:
        video_url = poll_runninghub_task(client, str(task_id), timeout=args.timeout, poll_interval=args.poll_interval)
        _write_json(args.output_dir / "status.json", client.last_status_response)
        client.download_video(video_url, args.output_dir / "result.mp4")
    else:
        _write_json(args.output_dir / "status.json", {"task_id": str(task_id), "status": "created"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

