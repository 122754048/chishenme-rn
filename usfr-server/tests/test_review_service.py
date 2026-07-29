import hashlib
import json
import uuid

import fakeredis
import pytest

from server.errors import ReplicationError, ReviewNotApplicableError
from server.job_models import ArtifactRef
from server.redis_job_store import RedisEphemeralJobStore
from server.review_models import RevisionManifest, RevisionRequest
from server.ephemeral_service import ReplicationService


@pytest.fixture
def store():
    return RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix=f"review-{uuid.uuid4().hex}")


@pytest.fixture
def job(store):
    return store.create_job(slots_manifest={"admission": {"can_proceed": True}}, capability_token_hash="a" * 64, ttl_seconds=3600)


@pytest.fixture
def service(store):
    return ReplicationService(job_store=store)


def test_script_revision_invalidates_all_downstream_refs(service, store, job):
    job = store.cas_transition(job_id=job.job_id, expected_version=job.version, command="set_route", updates={"review_route": "route_2", "state": "SCRIPT_AWAITING_APPROVAL"})
    revised = service.request_script_revision(job.job_id, expected_version=job.version, request=RevisionRequest("instruction", 1, ("C03",), None, "replace the product proof"))
    assert revised.invalidated == ("storyboard", "segment_plan", "prompt_audit", "provider_plan", "assembly", "qc")
    assert revised.approved_storyboard_sha256 is None


def test_local_only_review_is_rejected(service, store, job):
    job = store.cas_transition(job_id=job.job_id, expected_version=job.version, command="set_route", updates={"review_route": "local_only"})
    with pytest.raises(ReviewNotApplicableError):
        service.list_script_revisions(job.job_id)


def test_complete_and_approve_revision(service, store, job):
    job = store.cas_transition(job_id=job.job_id, expected_version=job.version, command="set_route", updates={"review_route": "route_2"})
    manifest = RevisionManifest.script(revision=1, object_key="temporary/j/scripts/r1.json", sha256="b" * 64, inputs_sha256="c" * 64)
    appended = service.complete_script_revision(job.job_id, expected_version=job.version, manifest=manifest)
    approved = service.approve_script_revision(job.job_id, revision=1, expected_version=appended.version, expected_sha256="b" * 64)
    assert approved.approved_script_sha256 == "b" * 64
    assert service.list_script_revisions(job.job_id)[0].revision == 1


def test_source_audio_script_approval_requires_an_atomic_confirmed_line_sidecar(service, store, job):
    job = store.cas_transition(job_id=job.job_id, expected_version=job.version, command="set_route", updates={"review_route": "route_2"})
    for artifact_id, kind, sha256 in (
        ("audio-source", "performance_audio_source_contract", "a" * 64),
        ("audio-lyrics", "audio_lyrics_beat_contract", "b" * 64),
    ):
        store.put_artifact(
            job_id=job.job_id,
            artifact=ArtifactRef(
                artifact_id=artifact_id,
                kind=kind,
                object_key=f"temporary/{job.job_id}/{artifact_id}.json",
                sha256=sha256,
                content_type="application/json",
                size_bytes=1,
            ),
        )
    manifest = RevisionManifest.script(revision=1, object_key="temporary/j/scripts/r1.json", sha256="c" * 64, inputs_sha256="d" * 64)
    appended = service.complete_script_revision(job.job_id, expected_version=job.version, manifest=manifest)

    with pytest.raises(ReplicationError, match="line_contracts"):
        service.approve_script_revision(
            job.job_id,
            revision=1,
            expected_version=appended.version,
            expected_sha256="c" * 64,
        )


def test_frozen_timeline_approval_requires_visible_text_locks(service, store, job):
    job = store.cas_transition(job_id=job.job_id, expected_version=job.version, command="set_route", updates={"review_route": "route_2"})
    manifest = RevisionManifest.script(revision=1, object_key="temporary/j/scripts/r1.json", sha256="c" * 64, inputs_sha256="d" * 64)
    appended = service.complete_script_revision(job.job_id, expected_version=job.version, manifest=manifest)

    with pytest.raises(ReplicationError, match="visible_text_locks"):
        service.approve_script_revision(
            job.job_id,
            revision=1,
            expected_version=appended.version,
            expected_sha256="c" * 64,
            line_contracts=[],
            source_content_timeline_sha256="e" * 64,
        )


def test_empty_visible_text_locks_are_valid_for_a_frozen_timeline(service, store, job):
    job = store.cas_transition(job_id=job.job_id, expected_version=job.version, command="set_route", updates={"review_route": "route_2"})
    manifest = RevisionManifest.script(revision=1, object_key="temporary/j/scripts/r1.json", sha256="c" * 64, inputs_sha256="d" * 64)
    appended = service.complete_script_revision(job.job_id, expected_version=job.version, manifest=manifest)
    empty_locks_sha256 = hashlib.sha256(
        json.dumps([], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    approved = service.approve_script_revision(
        job.job_id,
        revision=1,
        expected_version=appended.version,
        expected_sha256="c" * 64,
        line_contracts=[],
        source_content_timeline_sha256="e" * 64,
        visible_text_locks=[],
        visible_text_locks_sha256=empty_locks_sha256,
    )

    assert approved.approved_script_sha256 == "c" * 64
    assert store.get_script_approval(job.job_id, 1)["visible_text_locks"] == []
