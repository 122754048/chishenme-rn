"""Shared validation for evidence-bound marketing analysis rows."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from .marketing_terms import MarketingTermsError, validate_neutral_marketing_terms


ASSET_TYPES = frozenset({"model", "garment", "scene", "product", "app"})
PER_ASSET_FIELDS = frozenset(
    {
        "asset_tag",
        "asset_type",
        "selling_points",
        "pain_points",
        "pain_point_mapping",
        "display_method_library",
        "display_operation_adaptation",
        "operation_logic",
    }
)


class MarketingAnalysisContractError(ValueError):
    """Stable, module-local error for invalid marketing analysis data."""

    def __init__(self, code: str, field: str, reason: str) -> None:
        self.code = code
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def normalize_neutral_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketingAnalysisContractError("NON_EMPTY_TEXT_INVALID", field, "must be non-empty text")
    text = value.strip()
    try:
        validate_neutral_marketing_terms(text, surface="script")
    except MarketingTermsError as exc:
        raise MarketingAnalysisContractError(exc.code, field, "is not neutral marketing language") from exc
    return text


def normalize_analysis_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not 3 <= len(value) <= 5:
        raise MarketingAnalysisContractError("ANALYSIS_LIST_INVALID", field, "must contain three to five items")
    values = [normalize_neutral_text(item, field=f"{field}[{index}]") for index, item in enumerate(value)]
    if len(set(values)) != len(values):
        raise MarketingAnalysisContractError("ANALYSIS_LIST_DUPLICATE", field, "contains duplicate items")
    return values


def normalize_pain_point_mapping(
    value: Any,
    *,
    selling_points: Sequence[str],
    pain_points: Sequence[str],
    field: str,
) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) != len(pain_points):
        raise MarketingAnalysisContractError("PAIN_POINT_MAPPING_INVALID", field, "must map every pain point exactly once")
    mapping: list[dict[str, str]] = []
    seen_pains: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise MarketingAnalysisContractError("PAIN_POINT_MAPPING_INVALID", f"{field}[{index}]", "must be an object")
        mapped_pain = normalize_neutral_text(item.get("pain_point"), field=f"{field}[{index}].pain_point")
        mapped_selling = normalize_neutral_text(item.get("selling_point"), field=f"{field}[{index}].selling_point")
        if mapped_pain in seen_pains or mapped_pain not in pain_points or mapped_selling not in selling_points:
            raise MarketingAnalysisContractError("PAIN_POINT_MAPPING_INVALID", field, "does not reference the same analysis row")
        seen_pains.add(mapped_pain)
        mapping.append({"pain_point": mapped_pain, "selling_point": mapped_selling})
    if seen_pains != set(pain_points):
        raise MarketingAnalysisContractError("PAIN_POINT_MAPPING_INVALID", field, "does not cover every pain point")
    return mapping


def normalize_display_method_library(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise MarketingAnalysisContractError("DISPLAY_METHOD_LIBRARY_INVALID", field, "must be a non-empty array")
    methods = [normalize_neutral_text(item, field=f"{field}[{index}]") for index, item in enumerate(value)]
    if len(set(methods)) != len(methods):
        raise MarketingAnalysisContractError("DISPLAY_METHOD_LIBRARY_DUPLICATE", field, "contains duplicate items")
    return methods


def normalize_per_asset_analysis_row(
    row: Mapping[str, Any],
    *,
    field: str,
    allowed_asset_types: Collection[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise MarketingAnalysisContractError("PER_ASSET_SHAPE_INVALID", field, "must be an object")
    if set(row) != PER_ASSET_FIELDS:
        raise MarketingAnalysisContractError("PER_ASSET_SHAPE_INVALID", field, "has an invalid shape")
    asset_tag = row.get("asset_tag")
    asset_type = row.get("asset_type")
    if not isinstance(asset_tag, str) or not asset_tag.strip():
        raise MarketingAnalysisContractError("ASSET_IDENTITY_INVALID", f"{field}.asset_tag", "must be non-empty text")
    allowed_types = {str(item).strip().casefold() for item in (allowed_asset_types or ASSET_TYPES)}
    if not isinstance(asset_type, str) or asset_type.strip().casefold() not in allowed_types:
        raise MarketingAnalysisContractError("ASSET_IDENTITY_INVALID", f"{field}.asset_type", "is invalid")
    selling_points = normalize_analysis_list(row.get("selling_points"), field=f"{field}.selling_points")
    pain_points = normalize_analysis_list(row.get("pain_points"), field=f"{field}.pain_points")
    return {
        "asset_tag": asset_tag.strip(),
        "asset_type": asset_type.strip().casefold(),
        "selling_points": selling_points,
        "pain_points": pain_points,
        "pain_point_mapping": normalize_pain_point_mapping(
            row.get("pain_point_mapping"),
            selling_points=selling_points,
            pain_points=pain_points,
            field=f"{field}.pain_point_mapping",
        ),
        "display_method_library": normalize_display_method_library(
            row.get("display_method_library"),
            field=f"{field}.display_method_library",
        ),
        "display_operation_adaptation": normalize_neutral_text(
            row.get("display_operation_adaptation"),
            field=f"{field}.display_operation_adaptation",
        ),
        "operation_logic": normalize_neutral_text(
            row.get("operation_logic"),
            field=f"{field}.operation_logic",
        ),
    }


__all__ = [
    "ASSET_TYPES",
    "PER_ASSET_FIELDS",
    "MarketingAnalysisContractError",
    "normalize_analysis_list",
    "normalize_display_method_library",
    "normalize_neutral_text",
    "normalize_pain_point_mapping",
    "normalize_per_asset_analysis_row",
]
