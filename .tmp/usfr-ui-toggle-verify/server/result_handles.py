from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .errors import ReplicationError


_CANONICAL_FIELDS = {"v", "object_key", "sha256", "size_bytes"}
_HANDLE_CHARACTERS = re.compile(r"^[A-Za-z0-9_-]+$")
_LOWERCASE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_SIZE = hashlib.sha256().digest_size
_SEPARATOR = b"."


@dataclass(frozen=True)
class FinalResultRef:
    object_key: str
    sha256: str
    size_bytes: int


def issue_result_handle(ref: FinalResultRef, secret: bytes) -> str:
    try:
        if not isinstance(ref, FinalResultRef):
            raise _invalid_result_handle()
        payload = {
            "v": 1,
            "object_key": ref.object_key,
            "sha256": ref.sha256,
            "size_bytes": ref.size_bytes,
        }
        _validate_payload(payload)
        payload_bytes = _canonical_json(payload)
        signature = hmac.new(secret, payload_bytes, hashlib.sha256).digest()
        return _encode(payload_bytes + _SEPARATOR + signature)
    except ReplicationError:
        raise
    except (AttributeError, TypeError, UnicodeError, ValueError):
        raise _invalid_result_handle() from None


def verify_result_handle(handle: str, secret: bytes) -> FinalResultRef:
    try:
        raw = _decode(handle)
        payload_bytes, signature = _split(raw)
        expected_signature = hmac.new(
            secret,
            payload_bytes,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise _invalid_result_handle()

        payload = json.loads(payload_bytes.decode("utf-8"))
        ref = _validate_payload(payload)
        if payload_bytes != _canonical_json(payload):
            raise _invalid_result_handle()
        return ref
    except ReplicationError:
        raise
    except (
        AttributeError,
        binascii.Error,
        json.JSONDecodeError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        raise _invalid_result_handle() from None


def _decode(handle: str) -> bytes:
    if not isinstance(handle, str) or not handle:
        raise _invalid_result_handle()
    if "=" in handle or not _HANDLE_CHARACTERS.fullmatch(handle):
        raise _invalid_result_handle()
    if len(handle) % 4 == 1:
        raise _invalid_result_handle()

    encoded = handle.encode("ascii")
    padded = encoded + (b"=" * (-len(encoded) % 4))
    raw = base64.b64decode(padded, altchars=b"-_", validate=True)
    if _encode(raw) != handle:
        raise _invalid_result_handle()
    return raw


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _split(raw: bytes) -> tuple[bytes, bytes]:
    suffix_size = len(_SEPARATOR) + _SIGNATURE_SIZE
    if len(raw) <= suffix_size or raw[-suffix_size : -_SIGNATURE_SIZE] != _SEPARATOR:
        raise _invalid_result_handle()
    return raw[:-suffix_size], raw[-_SIGNATURE_SIZE:]


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _validate_payload(payload: Any) -> FinalResultRef:
    if type(payload) is not dict or set(payload) != _CANONICAL_FIELDS:
        raise _invalid_result_handle()
    if type(payload["v"]) is not int or payload["v"] != 1:
        raise _invalid_result_handle()

    object_key = payload["object_key"]
    sha256 = payload["sha256"]
    size_bytes = payload["size_bytes"]
    if type(object_key) is not str or not _is_safe_final_key(object_key):
        raise _invalid_result_handle()
    if type(sha256) is not str or not _LOWERCASE_SHA256.fullmatch(sha256):
        raise _invalid_result_handle()
    if type(size_bytes) is not int or size_bytes < 0:
        raise _invalid_result_handle()

    return FinalResultRef(
        object_key=object_key,
        sha256=sha256,
        size_bytes=size_bytes,
    )


def _is_safe_final_key(object_key: str) -> bool:
    parts = object_key.split("/")
    if len(parts) != 3 or parts[0] != "final" or parts[2] != "result.mp4":
        return False

    job_id = parts[1]
    return not _unsafe_segment(job_id)


def _unsafe_segment(value: str) -> bool:
    if not value or value in {".", ".."}:
        return True
    if any(character in value for character in "/\\?#%"):
        return True
    return any(unicodedata.category(character) in {"Cc", "Cs"} for character in value)


def _invalid_result_handle() -> ReplicationError:
    return ReplicationError(
        code="RESULT_HANDLE_INVALID",
        message="result handle is invalid",
        category="authorization",
        http_status=403,
    )
