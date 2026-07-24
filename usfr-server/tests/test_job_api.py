import uuid
from pathlib import Path

import fakeredis
from fastapi.testclient import TestClient

from server.fastapi_router import create_app
from server.redis_job_store import RedisEphemeralJobStore


class RecordingDriver:
    def __init__(self):
        self.job_ids = []

    def enqueue_next(self, job_id):
        self.job_ids.append(job_id)


def test_create_returns_one_time_capability_and_language_only_admission(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    store = RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix=f"job-{uuid.uuid4().hex}")
    client = TestClient(create_app(job_store=store, capability_secret=b"secret"))
    response = client.post("/api/v1/jobs", json={"slots": {"source_video": str(source)}, "output_language": "ja"})
    assert response.status_code == 202
    body = response.json()
    assert body["capability_token"]
    assert body["slots_manifest"]["output_language"] == "ja"
    job_id = body["job_id"]
    assert client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {body['capability_token']}"}).status_code == 200


def test_expected_version_and_revision_approval_are_cas_protected():
    store = RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix=f"job-{uuid.uuid4().hex}")
    client = TestClient(create_app(job_store=store, capability_secret=b"secret"))
    created = store.create_job(slots_manifest={"admission": {"can_proceed": True}}, capability_token_hash="0" * 64, ttl_seconds=3600)
    # Invalid/missing bearer is rejected before any CAS mutation.
    response = client.post(f"/api/v1/jobs/{created.job_id}/start", json={"expected_version": 1})
    assert response.status_code == 403


def test_start_enqueues_the_first_pipeline_stage(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    store = RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix=f"job-{uuid.uuid4().hex}")
    driver = RecordingDriver()
    client = TestClient(create_app(job_store=store, capability_secret=b"secret", stage_driver=driver))
    created = client.post(
        "/api/v1/jobs",
        json={"slots": {"source_video": str(source)}, "output_language": "ja"},
    ).json()
    response = client.post(
        f"/api/v1/jobs/{created['job_id']}/start",
        headers={"Authorization": f"Bearer {created['capability_token']}"},
        json={"expected_version": created["version"]},
    )
    assert response.status_code == 202
    assert driver.job_ids == [created["job_id"]]
