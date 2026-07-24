from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import FrozenInstanceError
from pathlib import Path
from collections.abc import Callable
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

import server.result_handles as result_handles
from server.errors import ReplicationError
from server.result_handles import FinalResultRef, issue_result_handle, verify_result_handle


SECRET = b"s" * 32
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "result_handle.schema.json"
URLSAFE_HANDLE = re.compile(r"^[A-Za-z0-9_-]+$")
SIGNATURE_SIZE = hashlib.sha256().digest_size
SEPARATOR = b"."


def _canonical_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "v": 1,
        "object_key": "final/job-1/result.mp4",
        "sha256": "a" * 64,
        "size_bytes": 100,
    }
    payload.update(overrides)
    return payload


def _signed_handle(payload: Any, secret: bytes = SECRET) -> str:
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _signed_payload_bytes(payload_bytes, secret)


def _signed_payload_bytes(payload_bytes: bytes, secret: bytes = SECRET) -> str:
    signature = hmac.new(secret, payload_bytes, hashlib.sha256).digest()
    raw = payload_bytes + SEPARATOR + signature
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_handle(handle: str) -> bytes:
    padding = "=" * (-len(handle) % 4)
    return base64.urlsafe_b64decode(handle + padding)


def _encode_raw(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _assert_rejected(
    handle: object,
    secret: bytes = SECRET,
    *forbidden_values: Any,
) -> ReplicationError:
    with pytest.raises(ReplicationError) as raised:
        verify_result_handle(handle, secret)  # type: ignore[arg-type]
    error = raised.value
    assert error.retryable is False
    assert error.details == {}
    rendered = " ".join((str(error), repr(error), repr(error.envelope())))
    for value in forbidden_values:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        if value:
            assert str(value) not in rendered
    return error


def _raises_replication_error(operation: Callable[[], object]) -> bool:
    try:
        operation()
    except ReplicationError:
        return True
    return False


def test_result_handle_is_stateless_and_tamper_evident():
    ref = FinalResultRef(
        object_key="final/job-1/result.mp4",
        sha256="a" * 64,
        size_bytes=100,
    )

    handle = issue_result_handle(ref, SECRET)

    assert verify_result_handle(handle, SECRET) == ref
    tampered = handle[:-1] + ("A" if handle[-1] != "A" else "B")
    _assert_rejected(tampered, SECRET, tampered, ref.object_key, ref.sha256)


def test_result_handle_is_deterministic_url_safe_and_unpadded():
    first_ref = FinalResultRef(
        object_key="final/job-opaque_1~:@+;=,()/result.mp4",
        sha256="b" * 64,
        size_bytes=0,
    )
    equivalent_ref = FinalResultRef(
        size_bytes=0,
        sha256="b" * 64,
        object_key="final/job-opaque_1~:@+;=,()/result.mp4",
    )

    first = issue_result_handle(first_ref, SECRET)
    second = issue_result_handle(equivalent_ref, SECRET)

    assert first == second
    assert first
    assert "=" not in first
    assert URLSAFE_HANDLE.fullmatch(first)
    assert verify_result_handle(first, SECRET) == first_ref


def test_final_result_ref_is_frozen():
    ref = FinalResultRef(
        object_key="final/job-1/result.mp4",
        sha256="a" * 64,
        size_bytes=100,
    )

    with pytest.raises(FrozenInstanceError):
        ref.size_bytes = 101  # type: ignore[misc]


def test_wrong_secret_is_rejected_without_leaking_handle_or_payload():
    ref = FinalResultRef(
        object_key="final/sensitive-job-reference/result.mp4",
        sha256="c" * 64,
        size_bytes=101,
    )
    handle = issue_result_handle(ref, SECRET)
    wrong_secret = b"recognizable-wrong-result-secret"

    error = _assert_rejected(
        handle,
        wrong_secret,
        handle,
        ref.object_key,
        ref.sha256,
        SECRET,
        wrong_secret,
    )

    assert error.code == "RESULT_HANDLE_INVALID"


@pytest.mark.parametrize(
    "malformed",
    (
        "",
        "=",
        "AA=",
        "A",
        "AA+/",
        "not.valid",
        "Zm9v*",
        "é",
        None,
        b"bytes-not-text",
        123,
    ),
)
def test_malformed_base64_and_non_text_handles_are_rejected(malformed: object):
    _assert_rejected(malformed, SECRET, SECRET)


def test_modified_payload_is_rejected_before_json_is_parsed(monkeypatch):
    ref = FinalResultRef(
        object_key="final/job-1/result.mp4",
        sha256="a" * 64,
        size_bytes=100,
    )
    raw = _decode_handle(issue_result_handle(ref, SECRET))
    payload = raw[: -(SIGNATURE_SIZE + len(SEPARATOR))]
    signature_and_separator = raw[-(SIGNATURE_SIZE + len(SEPARATOR)) :]
    tampered_payload = payload.replace(b"job-1", b"job-2")
    assert tampered_payload != payload
    tampered = _encode_raw(tampered_payload + signature_and_separator)

    def fail_if_parsed(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("tampered payload was parsed before signature verification")

    monkeypatch.setattr(result_handles.json, "loads", fail_if_parsed)

    _assert_rejected(tampered, SECRET, tampered, "job-2", SECRET)


def test_modified_signature_is_rejected():
    handle = _signed_handle(_canonical_payload())
    raw = bytearray(_decode_handle(handle))
    raw[-1] ^= 1
    tampered = _encode_raw(bytes(raw))

    _assert_rejected(tampered, SECRET, tampered, SECRET)


def test_result_handle_verification_uses_constant_time_comparison(monkeypatch):
    handle = _signed_handle(_canonical_payload())
    calls: list[tuple[bytes, bytes]] = []
    original_compare_digest = result_handles.hmac.compare_digest

    def recording_compare_digest(actual: bytes, expected: bytes) -> bool:
        calls.append((actual, expected))
        return original_compare_digest(actual, expected)

    monkeypatch.setattr(
        result_handles.hmac,
        "compare_digest",
        recording_compare_digest,
    )

    verify_result_handle(handle, SECRET)

    assert len(calls) == 1
    assert len(calls[0][0]) == SIGNATURE_SIZE
    assert len(calls[0][1]) == SIGNATURE_SIZE


@pytest.mark.parametrize(
    "payload",
    (
        _canonical_payload(v=2),
        _canonical_payload(v="1"),
        _canonical_payload(v=True),
        _canonical_payload(sha256="A" * 64),
        _canonical_payload(sha256="a" * 63),
        _canonical_payload(sha256="g" * 64),
        _canonical_payload(sha256=123),
        _canonical_payload(size_bytes=-1),
        _canonical_payload(size_bytes=True),
        _canonical_payload(size_bytes=1.0),
        _canonical_payload(size_bytes="100"),
        _canonical_payload(object_key=123),
        [1, 2, 3],
    ),
)
def test_signed_payloads_with_invalid_values_or_types_are_rejected(payload: Any):
    handle = _signed_handle(payload)

    _assert_rejected(handle, SECRET, handle, SECRET)


@pytest.mark.parametrize("missing_field", ("v", "object_key", "sha256", "size_bytes"))
def test_signed_payloads_with_missing_fields_are_rejected(missing_field: str):
    payload = _canonical_payload()
    payload.pop(missing_field)

    _assert_rejected(_signed_handle(payload), SECRET, SECRET)


def test_signed_payload_with_additional_field_is_rejected():
    payload = _canonical_payload(extra="not-allowed")

    _assert_rejected(_signed_handle(payload), SECRET, "not-allowed", SECRET)


@pytest.mark.parametrize(
    "unsafe_key",
    (
        "",
        "final//result.mp4",
        "final/./result.mp4",
        "final/../result.mp4",
        "final/.%2e/result.mp4",
        "final/%2E%2e/result.mp4",
        "final/job%2Fchild/result.mp4",
        "final/job%5cchild/result.mp4",
        "final/job/child/result.mp4",
        "final\\job\\result.mp4",
        "final/job\\child/result.mp4",
        "final/job?/result.mp4",
        "final/job#/result.mp4",
        "final/job\nchild/result.mp4",
        "private/job/result.mp4",
        "/final/job/result.mp4",
        "final/job/final.mp4",
        "final/job/result.mp4?download=1",
        "final/job/result.mp4#fragment",
    ),
)
def test_unsafe_traversal_and_non_final_object_keys_are_rejected(unsafe_key: str):
    handle = _signed_handle(_canonical_payload(object_key=unsafe_key))

    _assert_rejected(handle, SECRET, unsafe_key, handle, SECRET)


@pytest.mark.parametrize(
    "unsafe_key",
    (
        pytest.param("final/%80/result.mp4", id="invalid-utf8-80"),
        pytest.param("final/%9f/result.mp4", id="invalid-utf8-9f"),
        pytest.param("final/\ud800/result.mp4", id="raw-surrogate"),
    ),
)
def test_python_and_schema_reject_invalid_utf8_and_surrogates(unsafe_key: str):
    payload = _canonical_payload(object_key=unsafe_key)
    ref = FinalResultRef(
        object_key=unsafe_key,
        sha256=payload["sha256"],
        size_bytes=payload["size_bytes"],
    )

    with pytest.raises(ReplicationError):
        issue_result_handle(ref, SECRET)

    payload_bytes = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    _assert_rejected(_signed_payload_bytes(payload_bytes), SECRET, SECRET)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


@pytest.mark.parametrize(
    "unsafe_key",
    (
        pytest.param("final/%E2%80%93/result.mp4", id="encoded-en-dash"),
        pytest.param("final/%C0%AF/result.mp4", id="overlong-slash"),
        pytest.param("final/job%name/result.mp4", id="literal-percent"),
        pytest.param("final/job%2/result.mp4", id="malformed-percent"),
        pytest.param("final/job%25name/result.mp4", id="encoded-percent"),
        pytest.param("final/job%41/result.mp4", id="encoded-ascii"),
    ),
)
def test_python_and_schema_reject_every_percent_in_job_id(unsafe_key: str):
    payload = _canonical_payload(object_key=unsafe_key)
    ref = FinalResultRef(
        object_key=unsafe_key,
        sha256=payload["sha256"],
        size_bytes=payload["size_bytes"],
    )
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    handle = _signed_payload_bytes(payload_bytes)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    rejection_results = (
        _raises_replication_error(lambda: issue_result_handle(ref, SECRET)),
        _raises_replication_error(lambda: verify_result_handle(handle, SECRET)),
        not Draft202012Validator(schema).is_valid(payload),
    )

    assert rejection_results == (True, True, True)


def test_python_and_schema_accept_raw_safe_unicode_job_id():
    ref = FinalResultRef(
        object_key="final/job\u2013name/result.mp4",
        sha256="a" * 64,
        size_bytes=100,
    )
    payload = _canonical_payload(object_key=ref.object_key)

    handle = issue_result_handle(ref, SECRET)

    assert verify_result_handle(handle, SECRET) == ref
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)


@pytest.mark.parametrize(
    "invalid_ref",
    (
        FinalResultRef("final/../result.mp4", "a" * 64, 100),
        FinalResultRef("final/job-1/result.mp4", "A" * 64, 100),
        FinalResultRef("final/job-1/result.mp4", "a" * 64, True),
    ),
)
def test_issue_result_handle_rejects_invalid_references(invalid_ref: FinalResultRef):
    with pytest.raises(ReplicationError) as raised:
        issue_result_handle(invalid_ref, SECRET)

    assert raised.value.retryable is False
    assert raised.value.details == {}


def test_result_handle_schema_is_valid_and_accepts_canonical_payload():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_canonical_payload())


@pytest.mark.parametrize(
    "invalid_payload",
    (
        _canonical_payload(extra="not-allowed"),
        _canonical_payload(v=2),
        _canonical_payload(v=True),
        _canonical_payload(object_key="final/../result.mp4"),
        _canonical_payload(object_key="final/.%2e/result.mp4"),
        _canonical_payload(object_key="final/%252e%252e/result.mp4"),
        _canonical_payload(object_key="final/job/child/result.mp4"),
        _canonical_payload(object_key="final/job%252Fchild/result.mp4"),
        _canonical_payload(object_key="private/job/result.mp4"),
        _canonical_payload(object_key="final/job?/result.mp4"),
        _canonical_payload(object_key="final/job\\child/result.mp4"),
        _canonical_payload(sha256="A" * 64),
        _canonical_payload(sha256="a" * 63),
        _canonical_payload(size_bytes=-1),
        _canonical_payload(size_bytes=True),
    ),
)
def test_result_handle_schema_rejects_invalid_payloads(
    invalid_payload: dict[str, Any],
):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid_payload)


@pytest.mark.parametrize("missing_field", ("v", "object_key", "sha256", "size_bytes"))
def test_result_handle_schema_requires_every_canonical_field(missing_field: str):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = _canonical_payload()
    payload.pop(missing_field)

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)
