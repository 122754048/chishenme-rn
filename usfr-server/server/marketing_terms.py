"""Server-owned neutral marketing language contract."""

from __future__ import annotations

import re
from typing import Final


class MarketingTermsError(ValueError):
    """Raised when copy leaves the approved neutral marketing vocabulary."""

    code: Final[str] = "CONTENT_SAFETY_BLOCKER"


_ALLOWED_SURFACES: Final[frozenset[str]] = frozenset({"script", "asset_board", "storyboard", "prompt"})
_NON_NEUTRAL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(?:objectif\w*|sexual\w*|sensual\w*|seduct\w*|erotic\w*|provocat\w*)\b"),
    re.compile(r"\b(?:hot|sexy)\b"),
)


def validate_neutral_marketing_terms(value: object, *, surface: str) -> None:
    """Validate one user-visible marketing string for every supported surface."""

    normalized_surface = str(surface or "").strip().casefold()
    if normalized_surface not in _ALLOWED_SURFACES:
        raise MarketingTermsError(f"unsupported marketing surface: {surface}")
    text = str(value or "").strip()
    if not text:
        raise MarketingTermsError("marketing terms are required")
    normalized = re.sub(r"[^\w]+", " ", text.casefold(), flags=re.UNICODE)
    if any(pattern.search(normalized) for pattern in _NON_NEUTRAL_PATTERNS):
        raise MarketingTermsError("marketing language is not neutral")


__all__ = ["MarketingTermsError", "validate_neutral_marketing_terms"]
