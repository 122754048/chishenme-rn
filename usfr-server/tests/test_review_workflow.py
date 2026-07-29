from server.review_models import RevisionManifest
from server.review_workflow import (
    downstream_invalidations,
    resolve_review_route,
    select_storyboard_regeneration,
    validate_target_selling_point,
)


def test_route2_requires_script_then_storyboard():
    assert resolve_review_route(seedance_required=True, approved_script=None, current_script_inputs_sha256="a" * 64) == "route_2"


def test_matching_historical_script_still_requires_a_fresh_editable_review():
    approved = RevisionManifest.script(revision=2, object_key="temporary/j/scripts/r2.json", sha256="a" * 64, inputs_sha256="b" * 64)
    assert resolve_review_route(seedance_required=True, approved_script=approved, current_script_inputs_sha256="b" * 64) == "route_2"


def test_stale_approved_script_falls_back_to_route2():
    approved = RevisionManifest.script(revision=2, object_key="temporary/j/scripts/r2.json", sha256="a" * 64, inputs_sha256="b" * 64)
    assert resolve_review_route(seedance_required=True, approved_script=approved, current_script_inputs_sha256="c" * 64) == "route_2"


def test_local_only_has_no_review_artifacts():
    assert resolve_review_route(seedance_required=False, approved_script=None, current_script_inputs_sha256="d" * 64) == "local_only"


def test_storyboard_regeneration_includes_continuity_neighbors():
    selected = select_storyboard_regeneration(ordered_cut_ids=("C01", "C02", "C03"), requested_cut_ids=("C02",), continuity_affected_cut_ids=("C03",))
    assert selected == ("C02", "C03")


def test_script_invalidations_are_exact():
    assert downstream_invalidations("script") == ("storyboard", "segment_plan", "prompt_audit", "provider_plan", "assembly", "qc")


def test_target_selling_point_requires_evidence_backed_value_chain():
    mapping = validate_target_selling_point({
        "feature": "offline scan",
        "mechanism": "on-device recognition",
        "benefit": "works without network access",
        "proof": {"evidence_id": "APP-SCREEN-03"},
        "cta": "try offline mode",
    }, known_evidence_ids={"APP-SCREEN-03"})
    assert mapping["proof"]["evidence_id"] == "APP-SCREEN-03"
