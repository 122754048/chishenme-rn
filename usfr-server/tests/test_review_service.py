import uuid

import fakeredis
import pytest

from server.errors import ReviewNotApplicableError
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
