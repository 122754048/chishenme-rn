from app.target_truth import AppEvidenceCache, app_evidence_required, build_target_truth, cache_key_for_app_store


def test_app_evidence_is_required_only_for_consuming_generated_carriers():
    generated_ui = {
        "app_evidence": {"required": True, "purpose": ["generated_device_screen"]},
        "regions": [{"media_origin": "generated_ui"}],
    }
    opaque_only = {
        "app_evidence": {"required": False, "purpose": []},
        "regions": [{"media_origin": "opaque_ui"}, {"media_origin": "source_interval"}],
    }
    generated_without_app = {
        "app_evidence": {"required": False, "purpose": []},
        "regions": [{"media_origin": "generated"}],
    }

    assert app_evidence_required(generated_ui) is True
    assert app_evidence_required(opaque_only) is False
    assert app_evidence_required(generated_without_app) is False


def test_app_store_cache_key_is_stable_for_equivalent_url_and_purpose_order():
    first = cache_key_for_app_store(
        "https://PLAY.google.com/store/apps/details?gl=US&id=com.example.app&hl=en",
        ("claim_truth", "generated_device_screen"),
    )
    second = cache_key_for_app_store(
        "https://play.google.com/store/apps/details?hl=en&id=com.example.app&gl=US",
        ("generated_device_screen", "claim_truth"),
    )

    assert first == second


def test_app_store_cache_keeps_locale_and_parser_revisions_separate_and_resolves_each_key_once(tmp_path):
    cache = AppEvidenceCache(tmp_path)
    calls = []

    def resolve() -> dict[str, object]:
        calls.append("resolved")
        return {
            "bundle_sha256": "a" * 64,
            "canonical_url": "https://play.google.com/store/apps/details?id=com.example.app",
            "app_id": "com.example.app",
            "screenshots": [{"sha256": "b" * 64, "source": "official"}],
            "icon": {"sha256": "c" * 64, "source": "official"},
            "allowed_claims": ["profile discovery"],
            "blocked_claims": [],
        }

    first = cache.get_or_resolve(
        url="https://play.google.com/store/apps/details?id=com.example.app",
        purpose=("claim_truth",),
        store_locale="en-US",
        parser_version="official-store-v2",
        resolver=resolve,
    )
    second = cache.get_or_resolve(
        url="https://play.google.com/store/apps/details?id=com.example.app",
        purpose=("claim_truth",),
        store_locale="en-US",
        parser_version="official-store-v2",
        resolver=resolve,
    )
    changed_locale = cache.get_or_resolve(
        url="https://play.google.com/store/apps/details?id=com.example.app",
        purpose=("claim_truth",),
        store_locale="de-DE",
        parser_version="official-store-v2",
        resolver=resolve,
    )

    assert calls == ["resolved", "resolved"]
    assert first == second
    assert first["cache_key"] != changed_locale["cache_key"]


def test_target_truth_exposes_only_verified_claims_and_input_lineage():
    truth = build_target_truth(
        slots={"new_model_image": {"sha256": "a" * 64}},
        app_evidence={
            "bundle_sha256": "b" * 64,
            "allowed_claims": ["profile discovery"],
            "blocked_claims": ["guaranteed dates"],
        },
    )

    assert truth["facts"]["new_model_image"]["source_sha256"] == "a" * 64
    assert truth["app_evidence_bundle_sha256"] == "b" * 64
    assert truth["allowed_claims"] == ["profile discovery"]
    assert truth["blocked_claims"] == ["guaranteed dates"]
