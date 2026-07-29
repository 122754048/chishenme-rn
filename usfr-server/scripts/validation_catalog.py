#!/usr/bin/env python3
"""Validate and incrementally select the deployable 36-case catalog."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CATEGORY_COUNTS = {
    "physical_product": 10,
    "app": 10,
    "service": 5,
    "brand": 4,
    "creator": 4,
    "mixed_media": 3,
}
_LANGUAGES = {"en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"}


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _non_empty_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    return value


def _validate_case(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("catalog case must be an object")
    case = dict(raw)
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id is required")
    if case.get("category") not in _CATEGORY_COUNTS:
        raise ValueError(f"{case_id}.category is invalid")
    if case.get("route") not in {"route_1", "route_2", "local_only"}:
        raise ValueError(f"{case_id}.route is invalid")
    if case.get("output_language") not in _LANGUAGES:
        raise ValueError(f"{case_id}.output_language is invalid")
    source = case.get("source_fixture")
    if not isinstance(source, Mapping) or not isinstance(source.get("asset_id"), str):
        raise ValueError(f"{case_id}.source_fixture is invalid")
    _digest(source.get("sha256"), f"{case_id}.source_fixture.sha256")
    replacements = _non_empty_list(case.get("replacement_fixtures"), f"{case_id}.replacement_fixtures")
    for index, replacement in enumerate(replacements):
        if not isinstance(replacement, Mapping) or replacement.get("slot") not in {
            "new_product_image", "new_model_image", "ui_screenshot", "app_store_url",
            "ui_operation_video", "tail_video", "output_language",
        }:
            raise ValueError(f"{case_id}.replacement_fixtures[{index}] is invalid")
        _digest(replacement.get("sha256"), f"{case_id}.replacement_fixtures[{index}].sha256")
    _digest(case.get("toolchain_sha256"), f"{case_id}.toolchain_sha256")
    _digest(case.get("fixture_fingerprint"), f"{case_id}.fixture_fingerprint")
    tags = _non_empty_list(case.get("coverage_tags"), f"{case_id}.coverage_tags")
    if any(not isinstance(tag, str) or not tag for tag in tags):
        raise ValueError(f"{case_id}.coverage_tags contains an invalid tag")
    expected = case.get("expected")
    if not isinstance(expected, Mapping) or expected.get("approval_count") not in {0, 1, 2}:
        raise ValueError(f"{case_id}.expected is invalid")
    _non_empty_list(expected.get("hard_gates"), f"{case_id}.expected.hard_gates")
    generated = expected.get("generated_regions")
    if isinstance(generated, bool) or not isinstance(generated, int) or not 0 <= generated <= 2:
        raise ValueError(f"{case_id}.expected.generated_regions must be 0-2")
    return case


def load_catalog(path: str | Path) -> tuple[list[dict[str, Any]], set[str]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid validation catalog: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "usfr-validation-catalog/v1":
        raise ValueError("validation catalog schema_version is invalid")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("validation catalog cases must be an array")
    cases = [_validate_case(case) for case in raw_cases]
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("validation case IDs must be unique")
    counts = Counter(case["category"] for case in cases)
    if counts != Counter(_CATEGORY_COUNTS):
        raise ValueError(f"validation category counts are invalid: {dict(counts)}")
    smoke = payload.get("fixed_smoke_ids")
    if not isinstance(smoke, list) or len(smoke) != 6 or len(set(smoke)) != 6:
        raise ValueError("fixed_smoke_ids must contain six unique IDs")
    smoke_ids = set(smoke)
    missing = smoke_ids - set(ids)
    if missing:
        raise ValueError(f"fixed smoke cases are missing: {sorted(missing)}")
    return cases, smoke_ids


def select_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    smoke_ids: set[str],
    changed_tags: set[str] | None = None,
    full: bool = False,
    immutable_bundle_sha256: str | None = None,
) -> list[dict[str, Any]]:
    normalized = [_validate_case(case) for case in cases]
    if full:
        if not isinstance(immutable_bundle_sha256, str) or _SHA256.fullmatch(immutable_bundle_sha256) is None:
            raise ValueError("full matrix requires an immutable release candidate SHA-256")
        return normalized
    tags = set(changed_tags or ())
    return [
        case
        for case in normalized
        if case["case_id"] in smoke_ids or tags.intersection(case["coverage_tags"])
    ]


def build_execution_plan(
    cases: Sequence[Mapping[str, Any]],
    *,
    bundle_sha256: str,
    capability_sha256: str,
    model_sha256: str,
    provider_sha256: str,
    max_parallel: int = 4,
    cache_records: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a resumable plan; cache hits require an exact full fingerprint."""

    dependencies = {
        "bundle_sha256": _digest(bundle_sha256, "bundle_sha256"),
        "capability_sha256": _digest(capability_sha256, "capability_sha256"),
        "model_sha256": _digest(model_sha256, "model_sha256"),
        "provider_sha256": _digest(provider_sha256, "provider_sha256"),
    }
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or not 1 <= max_parallel <= 8:
        raise ValueError("max_parallel must be an integer from 1 to 8")
    cache = dict(cache_records or {})
    runnable: list[dict[str, Any]] = []
    hits: list[str] = []
    for case in (_validate_case(item) for item in cases):
        payload = {
            "case_id": case["case_id"],
            "fixture_fingerprint": case["fixture_fingerprint"],
            "toolchain_sha256": case["toolchain_sha256"],
            **dependencies,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if cache.get(case["case_id"]) == fingerprint:
            hits.append(case["case_id"])
        else:
            runnable.append({"case_id": case["case_id"], "dependency_fingerprint": fingerprint, "case": case})
    return {
        "schema_version": "usfr-validation-execution-plan/v1",
        "dependencies": dependencies,
        "max_parallel": max_parallel,
        "fail_fast_hard_gates": True,
        "checkpoint_resume": True,
        "cache_hits": hits,
        "runnable_cases": runnable,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select impacted USFR validation cases plus fixed smoke coverage")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--changed-tag", action="append", default=[])
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--immutable-bundle-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    cases, smoke_ids = load_catalog(args.catalog)
    selected = select_cases(
        cases,
        smoke_ids=smoke_ids,
        changed_tags=set(args.changed_tag),
        full=args.full,
        immutable_bundle_sha256=args.immutable_bundle_sha256,
    )
    result = {
        "schema_version": "usfr-validation-selection/v1",
        "mode": "full_release_candidate" if args.full else "incremental",
        "case_count": len(selected),
        "case_ids": [case["case_id"] for case in selected],
        "cases": selected,
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
