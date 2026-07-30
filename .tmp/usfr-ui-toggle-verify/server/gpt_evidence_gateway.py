"""Evidence-bound GPT Responses API gateway for packaged USFR capabilities.

The gateway deliberately accepts media *bytes*, never a worker/client path.
Every semantic response is bound to a canonical request digest, source bytes,
and the configured immutable model configuration before a stage can consume it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

from .production_ports import ProductionEnvironment


class GptEvidenceError(RuntimeError):
    """Raised when GPT evidence cannot be safely admitted to a USFR stage."""


_SCHEMA_VERSION = "usfr-gpt-evidence/v1"
_MAX_MEDIA_BYTES = 32 * 1024 * 1024


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _is_local_path(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    folded = text.casefold()
    return (
        text.startswith(("/", "\\"))
        or (len(text) > 1 and text[0].isalpha() and text[1] == ":")
        or folded.startswith(("file:", "local:", "path:", "~/.codex"))
        or ".codex/skills" in folded
        or ".codex\\skills" in folded
    )


def _output_text(response: Mapping[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    output = response.get("output")
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes, bytearray)):
        pieces: list[str] = []
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, Sequence) or isinstance(content, (str, bytes, bytearray)):
                continue
            for block in content:
                if isinstance(block, Mapping) and str(block.get("type") or "") in {"output_text", "text"}:
                    text = block.get("text")
                    if isinstance(text, str):
                        pieces.append(text)
        if pieces:
            return "\n".join(pieces).strip()
    raise GptEvidenceError("GPT response omitted structured output text")


def _responses_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise GptEvidenceError("GPT base URL must be a public HTTPS URL")
    normalized = base_url.rstrip("/")
    return normalized if normalized.endswith("/responses") else f"{normalized}/responses"


def _post_json(*, url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout_seconds: float) -> Mapping[str, Any]:
    request = urlrequest.Request(
        url,
        data=_canonical(dict(payload)),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlrequest.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - deployment configured HTTPS endpoint
            raw = response.read(8 * 1024 * 1024 + 1)
    except (urlerror.HTTPError, urlerror.URLError, TimeoutError, OSError) as exc:
        raise GptEvidenceError("GPT evidence request failed") from exc
    if len(raw) > 8 * 1024 * 1024:
        raise GptEvidenceError("GPT evidence response exceeded the byte limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GptEvidenceError("GPT evidence response was not JSON") from exc
    if not isinstance(value, Mapping):
        raise GptEvidenceError("GPT evidence response must be an object")
    return dict(value)


class GptEvidenceGateway:
    """A single credential boundary for all GPT-backed semantic evidence."""

    def __init__(
        self,
        *,
        config: ProductionEnvironment,
        request_json: Callable[..., Mapping[str, Any]] | None = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        if not isinstance(config, ProductionEnvironment):
            raise GptEvidenceError("a validated ProductionEnvironment is required")
        if timeout_seconds <= 0 or timeout_seconds > 600:
            raise GptEvidenceError("GPT evidence timeout must be in (0, 600]")
        self.config = config
        self._url = _responses_url(config.openai_base_url)
        self._request_json = request_json or _post_json
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_environment(cls) -> "GptEvidenceGateway":
        return cls(config=ProductionEnvironment.from_environ())

    def capability_identity(self) -> dict[str, str]:
        identity = {
            "implementation": "server.gpt_evidence_gateway:GptEvidenceGateway",
            "version": "1.0.0",
            "model_id": self.config.openai_model,
            "model_sha256": self.config.openai_model_config_sha256,
            "evidence_binding": _SCHEMA_VERSION,
        }
        return {**identity, "sha256": _sha256(identity)}

    def _request(
        self,
        *,
        purpose: str,
        evidence: Mapping[str, Any],
        media_bytes: bytes | None = None,
        media_content_type: str | None = None,
        media_items: Sequence[Mapping[str, Any]] | None = None,
        schema: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(evidence, Mapping):
            raise GptEvidenceError("GPT evidence must be an object")
        if not isinstance(purpose, str) or not purpose.strip():
            raise GptEvidenceError("GPT evidence purpose is required")
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": (
                    "Return only JSON that conforms to the requested schema. "
                    f"USFR evidence purpose: {purpose.strip()}.\n"
                    f"Evidence: {json.dumps(dict(evidence), ensure_ascii=False, sort_keys=True)}"
                ),
            }
        ]
        input_sha256s: list[str] = []
        if media_bytes is not None:
            if not isinstance(media_bytes, bytes) or not media_bytes:
                raise GptEvidenceError("GPT media evidence must be non-empty bytes")
            if len(media_bytes) > _MAX_MEDIA_BYTES:
                raise GptEvidenceError("GPT media evidence exceeded the byte limit")
            if not isinstance(media_content_type, str) or not media_content_type.startswith("image/"):
                raise GptEvidenceError("GPT media evidence must be an image with a MIME type")
            input_sha256s.append(_sha256(media_bytes))
            content.append(
                {
                    "type": "input_image",
                    "image_url": "data:%s;base64,%s" % (
                        media_content_type,
                        base64.b64encode(media_bytes).decode("ascii"),
                    ),
                }
            )
        if media_items is not None:
            if media_bytes is not None:
                raise GptEvidenceError("GPT evidence accepts either one media item or an ordered frame sequence")
            if not isinstance(media_items, Sequence) or isinstance(media_items, (str, bytes, bytearray)):
                raise GptEvidenceError("GPT frame evidence must be an ordered sequence")
            if not 1 <= len(media_items) <= 32:
                raise GptEvidenceError("GPT frame evidence must contain 1-32 images")
            total_bytes = 0
            for index, item in enumerate(media_items, start=1):
                if not isinstance(item, Mapping):
                    raise GptEvidenceError(f"GPT frame evidence {index} must be an object")
                data = item.get("bytes")
                content_type = item.get("content_type")
                if not isinstance(data, bytes) or not data:
                    raise GptEvidenceError(f"GPT frame evidence {index} must contain image bytes")
                if not isinstance(content_type, str) or not content_type.startswith("image/"):
                    raise GptEvidenceError(f"GPT frame evidence {index} must contain an image MIME type")
                total_bytes += len(data)
                if total_bytes > _MAX_MEDIA_BYTES:
                    raise GptEvidenceError("GPT frame evidence exceeded the byte limit")
                input_sha256s.append(_sha256(data))
                content.append(
                    {
                        "type": "input_image",
                        "image_url": "data:%s;base64,%s" % (
                            content_type,
                            base64.b64encode(data).decode("ascii"),
                        ),
                    }
                )
        payload: dict[str, Any] = {
            "model": self.config.openai_model,
            "input": [{"role": "user", "content": content}],
        }
        if schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "usfr_evidence",
                    "strict": True,
                    "schema": dict(schema),
                }
            }
        request_sha256 = _sha256(payload)
        api_key = os.getenv(self.config.openai_api_key_env)
        if not isinstance(api_key, str) or not api_key.strip():
            raise GptEvidenceError("GPT API credential is unavailable")
        response = self._request_json(
            url=self._url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {api_key}",
            },
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        try:
            value = json.loads(_output_text(response))
        except json.JSONDecodeError as exc:
            raise GptEvidenceError("GPT structured output was not valid JSON") from exc
        if not isinstance(value, Mapping):
            raise GptEvidenceError("GPT structured output must be an object")
        receipt = {
            "schema_version": _SCHEMA_VERSION,
            "request_sha256": request_sha256,
            "response_sha256": _sha256(dict(response)),
            "model_id": self.config.openai_model,
            "model_sha256": self.config.openai_model_config_sha256,
        }
        if input_sha256s:
            receipt["input_sha256"] = input_sha256s[0]
            receipt["input_sha256s"] = list(input_sha256s)
        return {
            "value": dict(value),
            "receipt": receipt,
            "input_sha256": input_sha256s[0] if len(input_sha256s) == 1 else None,
            "input_sha256s": list(input_sha256s),
        }

    def analyze(
        self,
        *,
        media_bytes: bytes | None = None,
        evidence: Mapping[str, Any],
        path: object | None = None,
    ) -> dict[str, Any]:
        if path is not None:
            if _is_local_path(path):
                raise GptEvidenceError("GPT evidence cannot accept a local path")
            raise GptEvidenceError("GPT evidence accepts media bytes, not a path reference")
        result = self._request(
            purpose="source video semantic analysis",
            evidence=evidence,
            media_bytes=media_bytes,
            media_content_type="image/jpeg" if media_bytes is not None else None,
        )
        return {**dict(result["value"]), "receipt": result["receipt"], "input_sha256": result["input_sha256"]}

    def analyze_images(
        self,
        *,
        frames: Sequence[Mapping[str, Any]],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Perform one semantic pass over an ordered, byte-bound frame set."""

        result = self._request(
            purpose="single-pass source video semantic analysis over ordered decoded frames",
            evidence=evidence,
            media_items=frames,
        )
        return {
            **dict(result["value"]),
            "receipt": result["receipt"],
            "frame_sha256s": list(result["input_sha256s"]),
        }

    def recognize(
        self,
        *,
        media_bytes: bytes,
        expected_text: Sequence[str] = (),
        media_content_type: str = "image/png",
    ) -> dict[str, Any]:
        expected = [str(item) for item in expected_text]
        result = self._request(
            purpose="OCR and normalized-layout evidence",
            evidence={"expected_text": expected},
            media_bytes=media_bytes,
            media_content_type=media_content_type,
        )
        return {
            **dict(result["value"]),
            "receipt": result["receipt"],
            "input_sha256": result["input_sha256"],
            "model_sha256": self.config.openai_model_config_sha256,
        }

    def evaluate(
        self,
        *,
        media_bytes: bytes,
        rubric: Mapping[str, Any],
        media_content_type: str = "image/png",
    ) -> dict[str, Any]:
        result = self._request(
            purpose="semantic quality evaluation",
            evidence={"rubric": dict(rubric)},
            media_bytes=media_bytes,
            media_content_type=media_content_type,
        )
        return {
            **dict(result["value"]),
            "receipt": result["receipt"],
            "input_sha256": result["input_sha256"],
            "model_sha256": self.config.openai_model_config_sha256,
        }


__all__ = ["GptEvidenceError", "GptEvidenceGateway"]
