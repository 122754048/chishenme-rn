from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from validation.compare_commercial_batch_runs import (
    ShadowComparisonError,
    compare_shadow_runs,
    evaluate_release_gates,
    validate_rollout_config,
)


REQUIRED_CATEGORIES = frozenset(
    {"physical_product", "app", "service", "brand", "creator", "mixed_media"}
)
REQUIRED_ROUTES = frozenset(
    {
        "language_only",
        "background_music_replace_sing",
        "composite_model_language",
        "composite_app_opaque_ui_tail_language",
    }
)


class CatalogValidationError(ValueError):
    pass


def validate_catalog(catalog: Mapping[str, Any]) -> None:
    if not isinstance(catalog, Mapping):
        raise CatalogValidationError("COMMERCIAL_BATCH_CATALOG_INVALID")
    cases = catalog.get("cases")
    if not isinstance(cases, list) or len(cases) < 18:
        raise CatalogValidationError("COMMERCIAL_BATCH_CASE_COUNT_INVALID")
    shadow_execution = catalog.get("shadow_execution")
    if not isinstance(shadow_execution, Mapping):
        raise CatalogValidationError("SHADOW_EXECUTION_POLICY_INVALID")
    if shadow_execution.get("provider_mode") != "observe_existing_only":
        raise CatalogValidationError("SHADOW_PAID_PROVIDER_TASK_FORBIDDEN")
    if shadow_execution.get("approval_mode") != "none":
        raise CatalogValidationError("SHADOW_APPROVAL_EVENT_FORBIDDEN")
    validate_rollout_config(_mapping(catalog.get("release_policy"), "ROLLOUT_POLICY_INVALID"))
    case_ids: set[str] = set()
    categories: set[str] = set()
    routes: set[str] = set()
    for case in cases:
        _validate_case(_mapping(case, "COMMERCIAL_BATCH_CASE_INVALID"), case_ids)
        categories.add(case["category"])
        routes.add(case["expected_route"])
    if not REQUIRED_CATEGORIES <= categories:
        raise CatalogValidationError("COMMERCIAL_BATCH_CATEGORY_COVERAGE_INVALID")
    if not REQUIRED_ROUTES <= routes:
        raise CatalogValidationError("COMMERCIAL_BATCH_ROUTE_COVERAGE_INVALID")


def run_shadow_comparison(
    *,
    catalog: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Mapping[str, Any]]],
    ab_results: list[Mapping[str, Any]],
    regression_results: list[Mapping[str, Any]],
) -> dict[str, Any]:
    validate_catalog(catalog)
    comparisons = []
    for case in catalog["cases"]:
        case_observations = observations.get(case["case_id"])
        if not isinstance(case_observations, Mapping):
            raise CatalogValidationError("SHADOW_OBSERVATION_MISSING")
        comparisons.append(
            compare_shadow_runs(
                case_id=case["case_id"],
                standard=_mapping(case_observations.get("standard"), "SHADOW_STANDARD_MISSING"),
                optimized=_mapping(case_observations.get("optimized"), "SHADOW_OPTIMIZED_MISSING"),
            )
        )
    return {
        "comparisons": comparisons,
        "release_gates": evaluate_release_gates(
            shadow_comparisons=comparisons,
            ab_results=ab_results,
            regression_results=regression_results,
        ),
    }


def _validate_case(case: Mapping[str, Any], case_ids: set[str]) -> None:
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id or case_id in case_ids:
        raise CatalogValidationError("COMMERCIAL_BATCH_CASE_ID_INVALID")
    case_ids.add(case_id)
    if case.get("category") not in REQUIRED_CATEGORIES:
        raise CatalogValidationError("COMMERCIAL_BATCH_CATEGORY_INVALID")
    route = case.get("expected_route")
    if route not in REQUIRED_ROUTES:
        raise CatalogValidationError("COMMERCIAL_BATCH_ROUTE_INVALID")
    inputs = _mapping(case.get("inputs"), "COMMERCIAL_BATCH_INPUTS_INVALID")
    if not isinstance(inputs.get("source_video"), str) or not inputs["source_video"]:
        raise CatalogValidationError("COMMERCIAL_BATCH_SOURCE_VIDEO_REQUIRED")
    _string_list(case.get("required_qa"), "COMMERCIAL_BATCH_REQUIRED_QA_INVALID")
    _string_list(case.get("forbidden_provider_inputs"), "COMMERCIAL_BATCH_PROVIDER_EXCLUSIONS_INVALID")
    _validate_route_inputs(route, inputs)


def _validate_route_inputs(route: str, inputs: Mapping[str, Any]) -> None:
    extensions = inputs.get("extensions", {})
    if not isinstance(extensions, Mapping) or set(extensions) - {"background_music"}:
        raise CatalogValidationError("COMMERCIAL_BATCH_EXTENSIONS_INVALID")
    material_inputs = {key for key, value in inputs.items() if key != "extensions" and value}
    has_music = isinstance(extensions.get("background_music"), str) and bool(extensions["background_music"])
    if route == "language_only":
        if material_inputs != {"source_video", "output_language"} or has_music:
            raise CatalogValidationError("LANGUAGE_ONLY_CASE_INPUTS_INVALID")
    elif route == "background_music_replace_sing":
        if material_inputs != {"source_video"} or not has_music:
            raise CatalogValidationError("BACKGROUND_MUSIC_CASE_INPUTS_INVALID")
    elif route == "composite_model_language":
        if not {"source_video", "new_model_image", "output_language"} <= material_inputs or has_music:
            raise CatalogValidationError("COMPOSITE_MODEL_LANGUAGE_CASE_INPUTS_INVALID")
    elif route == "composite_app_opaque_ui_tail_language":
        required = {"source_video", "app_store_url", "ui_operation_video", "tail_video", "output_language"}
        if not required <= material_inputs or has_music:
            raise CatalogValidationError("COMPOSITE_APP_CASE_INPUTS_INVALID")


def _mapping(value: object, error_code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogValidationError(error_code)
    return value


def _string_list(value: object, error_code: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise CatalogValidationError(error_code)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare standard and optimized USFR shadow receipts.")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    payload = json.loads(args.observations.read_text(encoding="utf-8"))
    result = run_shadow_comparison(
        catalog=catalog,
        observations=_mapping(payload.get("observations"), "SHADOW_OBSERVATIONS_INVALID"),
        ab_results=_list(payload.get("ab_results"), "AB_RESULTS_INVALID"),
        regression_results=_list(payload.get("regression_results"), "REGRESSION_RESULTS_INVALID"),
    )
    args.output.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return 0 if result["release_gates"]["release_ready"] else 2


def _list(value: object, error_code: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise CatalogValidationError(error_code)
    return value


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CatalogValidationError, ShadowComparisonError) as error:
        raise SystemExit(str(error)) from error
