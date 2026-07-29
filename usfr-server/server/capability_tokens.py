from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from .errors import CapabilityInvalidError


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def issue_capability(secret: bytes) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_capability(token, secret)


def hash_capability(token: str, secret: bytes) -> str:
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_capability(token: str, expected_digest: str, secret: bytes) -> None:
    try:
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise CapabilityInvalidError
        if not isinstance(expected_digest, str) or not _SHA256_HEX.fullmatch(
            expected_digest
        ):
            raise CapabilityInvalidError
        actual_digest = hash_capability(token, secret)
        if not hmac.compare_digest(actual_digest, expected_digest):
            raise CapabilityInvalidError
    except CapabilityInvalidError:
        raise
    except (AttributeError, TypeError, ValueError):
        raise CapabilityInvalidError from None
