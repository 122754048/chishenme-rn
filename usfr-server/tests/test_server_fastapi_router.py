import uuid

import fakeredis
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from server.fastapi_router import JobCreateModel, create_app
from server.redis_job_store import RedisEphemeralJobStore


def _client():
    store = RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix=f"api-{uuid.uuid4().hex}")
    return TestClient(create_app(job_store=store, capability_secret=b"test-secret")), store


def test_jobs_route_set_is_exact():
    client, _ = _client()
    paths = {route.path for route in client.app.routes if isinstance(route, APIRoute)}
    assert paths == {
        "/api/v1/jobs",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/start",
        "/api/v1/jobs/{job_id}/scripts",
        "/api/v1/jobs/{job_id}/scripts/revise",
        "/api/v1/jobs/{job_id}/scripts/{revision}/approve",
        "/api/v1/jobs/{job_id}/storyboards",
        "/api/v1/jobs/{job_id}/storyboards/revise",
        "/api/v1/jobs/{job_id}/storyboards/{revision}/approve",
        "/api/v1/jobs/{job_id}/provider/reconcile",
        "/api/v1/jobs/{job_id}/result",
    }


def test_bearer_capability_is_required_for_non_create_routes():
    client, _ = _client()
    response = client.get("/api/v1/jobs/missing")
    assert response.status_code == 403


def test_job_create_model_exposes_background_music_as_an_extension_not_a_slot():
    payload = JobCreateModel.model_validate(
        {
            "slots": {"source_video": {"object_key": "uploads/job/source.mp4"}},
            "background_music": {"object_key": "uploads/job/song.mp3"},
        }
    )
    assert payload.background_music == {"object_key": "uploads/job/song.mp3"}
