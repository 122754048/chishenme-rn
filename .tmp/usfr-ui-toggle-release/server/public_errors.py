from __future__ import annotations

from typing import Any, Mapping

from .errors import ReplicationError


_PUBLIC_CODES = {
    "INVALID_REQUEST",
    "ACCESS_DENIED",
    "SOURCE_UNAVAILABLE",
    "UNSUPPORTED_MEDIA",
    "SOURCE_TOO_LONG",
    "REVIEW_NOT_ALLOWED",
    "PROCESSING_FAILED",
}


def project_public_error(exc: ReplicationError) -> dict[str, Any]:
    code = str(getattr(exc, "code", "") or "").upper()
    category = str(getattr(exc, "category", "") or "").lower()
    if code in {"INPUT_SOURCE_TOO_LONG", "SOURCE_TOO_LONG"}:
        result = {"code": "SOURCE_TOO_LONG", "message": "源视频不能超过 30 秒", "retryable": False}
    elif code in {"CAPABILITY_INVALID", "ACCESS_DENIED"} or category == "authorization":
        result = {"code": "ACCESS_DENIED", "message": "任务访问凭证无效", "retryable": False}
    elif code.startswith(("APPROVAL_", "REVIEW_", "REVISION_")):
        result = {"code": "REVIEW_NOT_ALLOWED", "message": "当前任务不能执行该审核操作", "retryable": False}
    elif code.startswith(("REMOTE_", "SOURCE_UNAVAILABLE", "OBJECT_DOWNLOAD")) or category == "network":
        result = {"code": "SOURCE_UNAVAILABLE", "message": "无法读取提交的 OSS 素材", "retryable": bool(exc.retryable)}
    elif code.startswith(("MEDIA_", "UNSUPPORTED_MEDIA", "IMAGE_", "AUDIO_DECODE", "VIDEO_DECODE")):
        result = {"code": "UNSUPPORTED_MEDIA", "message": "素材格式或媒体内容不受支持", "retryable": False}
    elif code.startswith(("INVALID_", "MIN_ONE_", "INPUT_")):
        result = {"code": "INVALID_REQUEST", "message": "提交内容不符合生成要求", "retryable": False}
    else:
        result = {"code": "PROCESSING_FAILED", "message": "视频生成失败，请重新提交任务", "retryable": bool(exc.retryable)}
    return result


def validate_public_error(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"code", "message", "retryable"}:
        raise ValueError("public_error must contain code, message, and retryable")
    code = value.get("code")
    message = value.get("message")
    retryable = value.get("retryable")
    if code not in _PUBLIC_CODES or not isinstance(message, str) or not message.strip() or not isinstance(retryable, bool):
        raise ValueError("public_error is invalid")
    return {"code": str(code), "message": message.strip(), "retryable": retryable}


__all__ = ["project_public_error", "validate_public_error"]
