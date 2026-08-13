"""Small fail-closed guard for text and errors shown to the user."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class PublicContentPolicyError(ValueError):
    """Raised when user-visible content leaks implementation details."""


PUBLIC_FORBIDDEN_TERMS = (
    "image2",
    "seedance",
    "runninghub",
    "openai",
    "gpt",
    "whisper",
    "comfyui",
    "insightface",
    "provider",
    "workflow node",
    "nodeinfolist",
    "internal_stage",
    "generate_storyboards",
    "submit_provider_video",
)


def canonical_public_text(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise PublicContentPolicyError("用户内容无法安全显示") from exc


def assert_public_content_safe(value: object) -> None:
    text = canonical_public_text(value).casefold()
    if any(term in text for term in PUBLIC_FORBIDDEN_TERMS):
        raise PublicContentPolicyError("用户内容包含内部实现信息")


def public_safe_message(private_message: object) -> str:
    """Return a stable user message without exposing vendors or stage names."""

    text = str(private_message or "").casefold()
    if any(term in text for term in ("audio", "speech", "voice", "tts", "whisper")):
        return "语音处理暂时无法完成"
    if any(term in text for term in ("image", "storyboard", "ocr")):
        return "视觉内容处理暂时无法完成"
    if any(term in text for term in ("video", "seedance", "lip-sync", "lip sync")):
        return "视频处理暂时无法完成"
    return "当前任务暂时无法继续"


def public_error_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    """Project a private error into the minimum safe public contract."""

    result = {
        "schema_version": str(value.get("schema_version") or "replication/v1"),
        "code": str(value.get("code") or "TASK_FAILED"),
        "message": public_safe_message(value.get("message")),
        "run_id": value.get("run_id"),
        "retryable": bool(value.get("retryable")),
        "user_action_required": bool(value.get("user_action_required")),
        "correlation_id": value.get("correlation_id"),
        "occurred_at": value.get("occurred_at"),
    }
    assert_public_content_safe(result)
    return result


__all__ = [
    "PUBLIC_FORBIDDEN_TERMS",
    "PublicContentPolicyError",
    "assert_public_content_safe",
    "canonical_public_text",
    "public_error_envelope",
    "public_safe_message",
]
