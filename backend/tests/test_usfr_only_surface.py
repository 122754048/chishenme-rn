from app.main import app
from app.config import settings


def test_backend_exposes_only_usfr_runtime_surfaces():
    routes = {route.path for route in app.routes}

    assert "/health" in routes
    assert "/api/v1/replication" in routes
    assert "/api/v1/commercial-batches/{path:path}" in routes

    assert "/creative/reverse" not in routes
    assert "/creative/seedance/submit" not in routes
    assert "/creative/imagegen/submit" not in routes
    assert "/auth/register" not in routes
    assert "/plans" not in routes
    assert "/billing/alipay/create-order" not in routes
    assert "/discovery/nearby-restaurants" not in routes


def test_backend_settings_retain_only_usfr_runtime_configuration():
    assert settings.app_name == "usfr-backend"
    for legacy_field in (
        "jwt_secret",
        "db_path",
        "alipay_app_id",
        "revenuecat_webhook_secret",
        "google_places_api_key",
        "openai_api_key",
        "seedance_api_key",
    ):
        assert not hasattr(settings, legacy_field)
