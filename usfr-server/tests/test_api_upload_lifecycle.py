from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fakeredis
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from server.cleanup import CleanupSweeper
from server.fastapi_router import create_app
from server.object_store import (
    FinalVideoStore,
    S3ObjectStore,
    TemporaryMediaStore,
    UploadMediaStore,
)
from server.redis_job_store import RedisEphemeralJobStore

from test_object_lifecycle import MemoryS3


def _put(client: MemoryS3, key: str, body: bytes, content_type: str) -> dict:
    digest = hashlib.sha256(body).hexdigest()
    client.objects[key] = {
        "body": body,
        "content_type": content_type,
        "sha256": digest,
    }
    result = {
        "object_key": key,
        "sha256": digest,
        "size_bytes": len(body),
        "content_type": content_type,
        "status": "completed",
    }
    if content_type.startswith("video/"):
        result["duration_seconds"] = 1.0
    return result


def _runtime():
    redis = fakeredis.FakeRedis(decode_responses=False)
    jobs = RedisEphemeralJobStore(redis, prefix="upload-life")
    client = MemoryS3()
    objects = S3ObjectStore(client, bucket="private")
    temporary = TemporaryMediaStore(objects)
    uploads = UploadMediaStore(objects)
    final = FinalVideoStore(objects)
    app = create_app(
        job_store=jobs,
        capability_secret=b"s" * 32,
        object_store=objects,
    )
    return redis, jobs, client, objects, temporary, uploads, final, TestClient(app)


def _payload(client: MemoryS3, scope: str) -> dict:
    return {
        "upload_scope": scope,
        "slots": {
            "source_video": _put(
                client, f"uploads/{scope}/source.mp4", b"source", "video/mp4"
            ),
            "new_product_image": _put(
                client, f"uploads/{scope}/product.png", b"product", "image/png"
            ),
        },
        "output_language": "en",
    }


def test_api_upload_scope_is_owned_and_cleanup_leaves_only_final_namespace() -> None:
    redis, jobs, client, _objects, temporary, uploads, final, http = _runtime()
    payload = _payload(client, "scope-one")
    response = http.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    snapshot = jobs.get_job(job_id)
    assert snapshot.slots_manifest["upload_scope"] == "scope-one"
    assert uploads.list_scope("scope-one")

    assembled = temporary.put_bytes(
        job_id=job_id,
        logical_path="assembled.mp4",
        data=b"final-video",
        content_type="video/mp4",
    )
    promoted = final.promote(job_id=job_id, source=assembled)
    current = jobs.get_job(job_id)
    jobs.cas_transition(
        job_id=job_id,
        expected_version=current.version,
        command="test-final",
        updates={"state": "SUCCEEDED", "final_ref": promoted.to_dict()},
        ttl_seconds=3600,
    )
    sweeper = CleanupSweeper(
        redis,
        temporary,
        final,
        upload_store=uploads,
        prefix="upload-life",
    )
    assert sweeper.cleanup_job(job_id, preserve_final=True)
    assert uploads.list_scope("scope-one") == ()
    assert set(client.objects) == {f"final/{job_id}/result.mp4"}


def test_language_only_object_upload_is_verified_owned_and_cleaned() -> None:
    redis, jobs, client, _objects, temporary, uploads, final, http = _runtime()
    payload = {
        "upload_scope": "language-scope",
        "slots": {
            "source_video": _put(
                client,
                "uploads/language-scope/source.mp4",
                b"source",
                "video/mp4",
            )
        },
        "output_language": "zh",
    }
    response = http.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    snapshot = jobs.get_job(job_id)
    assert snapshot.slots_manifest["upload_scope"] == "language-scope"
    assert snapshot.slots_manifest["admission"]["language_only"] is True
    assert snapshot.slots_manifest["slots"]["source_video"]["metadata"][0][
        "store_verified"
    ] is True
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas" / "input_slots.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(snapshot.slots_manifest)

    sweeper = CleanupSweeper(
        redis,
        temporary,
        final,
        upload_store=uploads,
        prefix="upload-life",
    )
    assert sweeper.cleanup_job(job_id, preserve_final=False)
    assert uploads.list_scope("language-scope") == ()


def test_api_rejects_object_completion_without_scope_or_outside_scope() -> None:
    _redis, _jobs, client, _objects, _temporary, _uploads, _final, http = _runtime()
    payload = _payload(client, "scope-two")
    no_scope = dict(payload)
    no_scope.pop("upload_scope")
    response = http.post("/api/v1/jobs", json=no_scope)
    assert response.status_code == 400
    assert response.json()["code"] == "INPUT_SLOT_INVALID"

    payload["slots"]["source_video"] = _put(
        client, "uploads/foreign/source.mp4", b"foreign", "video/mp4"
    )
    response = http.post("/api/v1/jobs", json=payload)
    assert response.status_code == 400
    assert response.json()["code"] == "INPUT_SLOT_INVALID"

    payload = _payload(client, "scope-two")
    payload["slots"]["source_video"] = _put(
        client, "temporary/scope-two/source.mp4", b"temporary", "video/mp4"
    )
    response = http.post("/api/v1/jobs", json=payload)
    assert response.status_code == 400
    assert response.json()["code"] == "INPUT_SLOT_INVALID"


def test_cleanup_fails_closed_when_owned_upload_store_is_not_configured() -> None:
    redis, jobs, client, _objects, temporary, _uploads, final, http = _runtime()
    response = http.post("/api/v1/jobs", json=_payload(client, "scope-three"))
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    sweeper = CleanupSweeper(redis, temporary, final, prefix="upload-life")
    assert sweeper.cleanup_job(job_id, preserve_final=False) is False
    assert jobs.get_job(job_id) is not None
    assert any(key.startswith("uploads/scope-three/") for key in client.objects)


def test_upload_store_deletes_only_exact_scope_and_rejects_broad_prefix() -> None:
    _redis, _jobs, client, _objects, _temporary, uploads, _final, _http = _runtime()
    _put(client, "uploads/one/a.mp4", b"a", "video/mp4")
    _put(client, "uploads/two/b.mp4", b"b", "video/mp4")
    assert uploads.delete_scope("one") == 1
    assert "uploads/two/b.mp4" in client.objects
