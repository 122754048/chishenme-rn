from fastapi.routing import APIRoute

from server.fastapi_router import RevisionApprovalModel, RevisionRequestModel, create_app


def test_request_models_expose_revision_cas_contract():
    assert {"expected_version", "expected_revision", "mode", "changed_cut_ids", "direct_patch", "instruction"} <= set(RevisionRequestModel.model_fields)
    assert {"expected_version", "expected_sha256"} <= set(RevisionApprovalModel.model_fields)


def test_forbidden_legacy_routes_are_not_exposed():
    app = create_app(job_store=object())
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert not any(path.startswith("/api/v1/replication") or "/events" in path or "/artifacts" in path for path in paths)
