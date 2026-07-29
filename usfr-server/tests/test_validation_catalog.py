from __future__ import annotations

from collections import Counter
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "validation" / "case_catalog.json"
MODULE = ROOT / "scripts" / "validation_catalog.py"


def _api():
    assert MODULE.is_file(), "validation catalog runner is missing"
    spec = importlib.util.spec_from_file_location("validation_catalog", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_catalog, module.select_cases


def test_catalog_contains_exact_36_fully_configured_cases() -> None:
    load_catalog, _ = _api()
    cases, smoke_ids = load_catalog(CATALOG)
    assert len(cases) == 36
    assert Counter(case["category"] for case in cases) == {
        "physical_product": 10,
        "app": 10,
        "service": 5,
        "brand": 4,
        "creator": 4,
        "mixed_media": 3,
    }
    assert len(smoke_ids) == 6
    assert smoke_ids <= {case["case_id"] for case in cases}
    for case in cases:
        assert case["source_fixture"]["sha256"]
        assert case["replacement_fixtures"]
        assert case["toolchain_sha256"]
        assert case["fixture_fingerprint"]
        assert case["coverage_tags"]
        assert case["expected"]["approval_count"] in {0, 1, 2}
        assert case["expected"]["hard_gates"]


def test_incremental_selection_is_impacted_union_fixed_smoke() -> None:
    load_catalog, select_cases = _api()
    cases, smoke_ids = load_catalog(CATALOG)
    selected = select_cases(cases, smoke_ids=smoke_ids, changed_tags={"generated_ui", "ja"})
    selected_ids = {case["case_id"] for case in selected}
    expected = smoke_ids | {
        case["case_id"]
        for case in cases
        if {"generated_ui", "ja"} & set(case["coverage_tags"])
    }
    assert selected_ids == expected
    assert len(selected) < 36


def test_full_matrix_requires_immutable_release_candidate_digest() -> None:
    load_catalog, select_cases = _api()
    cases, smoke_ids = load_catalog(CATALOG)
    with pytest.raises(ValueError, match="immutable release candidate"):
        select_cases(cases, smoke_ids=smoke_ids, full=True)
    selected = select_cases(
        cases,
        smoke_ids=smoke_ids,
        full=True,
        immutable_bundle_sha256="a" * 64,
    )
    assert len(selected) == 36


def test_execution_plan_reuses_only_exact_dependency_fingerprint() -> None:
    module = _api_module()
    cases, smoke_ids = module.load_catalog(CATALOG)
    selected = module.select_cases(cases, smoke_ids=smoke_ids)
    kwargs = {
        "bundle_sha256": "1" * 64,
        "capability_sha256": "2" * 64,
        "model_sha256": "3" * 64,
        "provider_sha256": "4" * 64,
        "max_parallel": 3,
    }
    first = module.build_execution_plan(selected, cache_records={}, **kwargs)
    assert first["max_parallel"] == 3
    assert first["fail_fast_hard_gates"] is True
    assert first["checkpoint_resume"] is True
    cached = {row["case_id"]: row["dependency_fingerprint"] for row in first["runnable_cases"]}
    second = module.build_execution_plan(selected, cache_records=cached, **kwargs)
    assert second["runnable_cases"] == []
    assert set(second["cache_hits"]) == set(cached)
    changed = module.build_execution_plan(
        selected,
        cache_records=cached,
        **{**kwargs, "model_sha256": "5" * 64},
    )
    assert len(changed["runnable_cases"]) == len(selected)


def test_catalog_json_has_no_local_paths() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    folded = text.casefold()
    assert "c:/users/" not in folded
    assert "\\users\\" not in folded
    assert ".codex/skills" not in folded
    json.loads(text)


def _api_module():
    assert MODULE.is_file(), "validation catalog runner is missing"
    spec = importlib.util.spec_from_file_location("validation_catalog_full", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
