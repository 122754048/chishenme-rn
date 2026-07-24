import json
from pathlib import Path

from validation.compare_commercial_batch_runs import compare_shadow_runs, evaluate_release_gates
from validation.run_commercial_batch_shadow import validate_catalog


ROOT = Path(__file__).resolve().parent


def test_commercial_batch_catalog_covers_required_categories_routes_and_provider_exclusions():
    catalog = json.loads((ROOT / "commercial_batch_case_catalog.json").read_text(encoding="utf-8"))

    validate_catalog(catalog)
    cases = catalog["cases"]
    assert len(cases) >= 18
    assert {case["category"] for case in cases} >= {
        "physical_product", "app", "service", "brand", "creator", "mixed_media"
    }
    assert {case["expected_route"] for case in cases} >= {
        "language_only",
        "background_music_replace_sing",
        "composite_model_language",
        "composite_app_opaque_ui_tail_language",
    }
    assert all(case["forbidden_provider_inputs"] for case in cases)
    assert all(case["required_qa"] for case in cases)


def test_shadow_comparison_rejects_shared_hard_failures():
    observation = {
        "paid_provider_tasks_created": 0,
        "approval_events": 0,
        "source_contract_coverage": ["camera", "action", "audio"],
        "selling_point_claims": ["verified claim"],
        "hard_failures": {"ui": [], "audio": ["MUSIC_TIMELINE_MISMATCH"], "timeline": []},
        "timing_seconds": {
            "probe_dynamics": 1,
            "context_compile": 1,
            "provider_wait": 1,
            "assembly_qc": 1,
        },
        "active_seconds": 4,
        "final_qa_score": 95,
    }

    comparison = compare_shadow_runs(
        case_id="music-case",
        standard=observation,
        optimized=observation,
    )

    assert comparison["shadow_green"] is False


def test_release_gate_uses_average_ab_fidelity_without_ui_or_claim_regression():
    shadows = [{"shadow_green": True} for _ in range(18)]
    ab_results = [
        {"baseline_fidelity": 91, "optimized_fidelity": 90, "ui_regression": False, "claim_regression": False}
    ] + [
        {"baseline_fidelity": 90, "optimized_fidelity": 92, "ui_regression": False, "claim_regression": False}
        for _ in range(11)
    ]
    regressions = [{"hard_failures": []} for _ in range(30)]

    gates = evaluate_release_gates(
        shadow_comparisons=shadows,
        ab_results=ab_results,
        regression_results=regressions,
    )

    assert gates["release_ready"] is True
