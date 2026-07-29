from __future__ import annotations

import re
from typing import Any

import pytest

import server.capability_tokens as capability_tokens
from server.capability_tokens import (
    hash_capability,
    issue_capability,
    verify_capability,
)
from server.errors import CapabilityInvalidError, JobGoneError, ReplicationError


SECRET = b"s" * 32
URLSAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
LOWERCASE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _assert_error_does_not_leak(error: ReplicationError, *values: Any) -> None:
    rendered = " ".join((str(error), repr(error), repr(error.envelope())))
    for value in values:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        if value:
            assert str(value) not in rendered
    assert error.details == {}


def test_capability_round_trip_stores_only_digest():
    token, digest = issue_capability(SECRET)

    assert token not in digest
    assert digest == hash_capability(token, SECRET)
    assert verify_capability(token, digest, SECRET) is None


def test_issued_capabilities_are_distinct_and_well_formed():
    first_token, first_digest = issue_capability(SECRET)
    second_token, second_digest = issue_capability(SECRET)

    assert first_token != second_token
    assert first_digest != second_digest
    for token in (first_token, second_token):
        assert token
        assert "=" not in token
        assert URLSAFE_TOKEN.fullmatch(token)
    for digest in (first_digest, second_digest):
        assert digest
        assert LOWERCASE_SHA256.fullmatch(digest)


def test_wrong_capability_is_403_without_leaking_credentials():
    token, digest = issue_capability(SECRET)
    wrong_token = "recognizably-wrong-capability"

    with pytest.raises(CapabilityInvalidError) as raised:
        verify_capability(wrong_token, digest, SECRET)

    error = raised.value
    assert isinstance(error, ReplicationError)
    assert error.code == "CAPABILITY_INVALID"
    assert error.category == "authorization"
    assert error.http_status == 403
    assert error.retryable is False
    _assert_error_does_not_leak(error, token, wrong_token, digest, SECRET)


def test_wrong_secret_is_403_without_leaking_expected_values():
    token, digest = issue_capability(SECRET)
    wrong_secret = b"recognizable-wrong-secret-material"

    with pytest.raises(CapabilityInvalidError) as raised:
        verify_capability(token, digest, wrong_secret)

    error = raised.value
    assert error.http_status == 403
    _assert_error_does_not_leak(error, token, digest, SECRET, wrong_secret)


@pytest.mark.parametrize(
    "malformed_digest",
    (
        "",
        "short",
        "g" * 64,
        "A" * 64,
        None,
        123,
        b"a" * 64,
    ),
)
def test_malformed_digest_is_403(malformed_digest: object):
    token, _ = issue_capability(SECRET)

    with pytest.raises(CapabilityInvalidError) as raised:
        verify_capability(token, malformed_digest, SECRET)  # type: ignore[arg-type]

    assert raised.value.http_status == 403
    _assert_error_does_not_leak(raised.value, token, malformed_digest, SECRET)


@pytest.mark.parametrize(
    "malformed_token",
    (None, 123, b"recognizable-malformed-capability-bytes"),
)
def test_malformed_token_is_403(malformed_token: object):
    _, digest = issue_capability(SECRET)

    with pytest.raises(CapabilityInvalidError) as raised:
        verify_capability(malformed_token, digest, SECRET)  # type: ignore[arg-type]

    assert raised.value.http_status == 403
    _assert_error_does_not_leak(raised.value, malformed_token, digest, SECRET)


@pytest.mark.parametrize(
    "malformed_token",
    (
        "",
        "too-short",
        "a" * 42,
        "a" * 44,
        ("a" * 42) + "=",
        ("a" * 42) + "!",
    ),
)
def test_matching_digest_does_not_authorize_malformed_token(malformed_token: str):
    digest = hash_capability(malformed_token, SECRET)

    with pytest.raises(CapabilityInvalidError):
        verify_capability(malformed_token, digest, SECRET)


def test_capability_verification_uses_constant_time_comparison(monkeypatch):
    token, digest = issue_capability(SECRET)
    calls: list[tuple[str, str]] = []
    original_compare_digest = capability_tokens.hmac.compare_digest

    def recording_compare_digest(actual: str, expected: str) -> bool:
        calls.append((actual, expected))
        return original_compare_digest(actual, expected)

    monkeypatch.setattr(
        capability_tokens.hmac,
        "compare_digest",
        recording_compare_digest,
    )

    verify_capability(token, digest, SECRET)

    assert calls == [(digest, digest)]


def test_expired_job_error_is_410():
    error = JobGoneError()

    assert error.code == "JOB_GONE"
    assert error.category == "lifecycle"
    assert error.http_status == 410
    assert error.retryable is False
    assert error.details == {}
