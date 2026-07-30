from __future__ import annotations

import re

from .errors import ReplicationError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def require_sha256(value: object, *, field: str) -> str:
    """Validate a strict lowercase SHA-256 digest at the domain boundary."""
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"{field} must be a 64-character lowercase hexadecimal SHA-256 digest",
            category="contract",
            user_action_required=True,
            details={"field": field},
            http_status=422,
        )
    return value
