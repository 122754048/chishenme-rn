from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import fakeredis

from server.ephemeral_driver import EphemeralStageDriver
from server.ephemeral_worker import EphemeralWorkerManager
from server.job_models import WorkMessage
from server.object_store import FinalVideoStore, S3ObjectStore, TemporaryMediaStore
from server.orchestrator import build_stage_plan
from server.redis_job_store import RedisEphemeralJobStore
from server.review_models import RevisionManifest

from test_object_lifecycle import MemoryS3


class Stage:
    def run(self, *, context, input_artifacts):
        payload = b"stage-output"
        return {
            "published_artifacts": [
                context.publish_bytes(
                    kind="analysis",
                    data=payload,
                    content_type="application/json",
                    expected_sha256=hashlib.sha256(payload).hexdigest(),
                )
            ]
        }


class ScriptStage:
    def run(self, *, context, input_artifacts):
        del input_artifacts
        payload = b'{"cuts":[{"cut_id":"c1"}]}'
        published = context.publish_bytes(
            kind="script_revision",
            data=payload,
            content_type="application/json",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
        return {
            "published_artifacts": [published],
            "script_revision": RevisionManifest(
                kind="script",
                revision=1,
                object_key=published["object_key"],
                sha256=published["sha256"],
                inputs_sha256="d" * 64,
                created_at=datetime.now(timezone.utc).isoformat(),
                output_language="en",
            ),
        }


class QcFinalStage:
    def run(self, *, context, input_artifacts):
        del input_artifacts
        payload = b"playable-mp4-bytes"
        published = context.publish_bytes(
            kind="assembled_video",
            data=payload,
            content_type="video/mp4",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
        return {
            "published_artifacts": [published],
            "qc_passed": True,
            "final_artifact_id": published["artifact_id"],
        }


def _runtime():
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="ephemeral-runtime")
    object_store = S3ObjectStore(MemoryS3(), bucket="test")
    temporary = TemporaryMediaStore(object_store)
    manager = EphemeralWorkerManager(
        job_store=store,
        temporary_store=temporary,
        stage_ports={"analyze_dynamics": Stage()},
        profile_bundle_resolver=SimpleNamespace(immutable=True),
        capability_ports={},
    )
    return store, temporary, manager


def test_worker_processes_job_scoped_message_and_publishes_temporary_artifact() -> None:
    store, temporary, manager = _runtime()
    job = store.create_job(slots_manifest={"slots": {}}, capability_token_hash="a" * 64, ttl_seconds=3600)
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="analyze_dynamics",
        dedupe_key="d1",
        owner="worker-1",
        ttl_seconds=60,
    )
    result = manager.process_work_message(
        message=WorkMessage(job.job_id, "analyze_dynamics", job.version, "d1"),
        checkpoint=checkpoint,
        owner="worker-1",
    )
    assert len(result["output_artifact_ids"]) == 1
    artifact = store.get_artifact(job.job_id, result["output_artifact_ids"][0])
    assert artifact is not None
    assert artifact.object_key.startswith(f"temporary/{job.job_id}/")
    assert temporary.list_job_keys(job.job_id) == (artifact.object_key,)


def test_driver_starts_at_first_executable_stage_before_approvals() -> None:
    store, _temporary, _manager = _runtime()
    job = store.create_job(
        slots_manifest={"slots": {}, "routes": {"product": "replace_from_slot"}, "review_route": "route_2"},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    def enqueue(**kwargs):
        message = WorkMessage(**kwargs)
        queue.messages.append(message)
        return "1-0"

    queue = SimpleNamespace(messages=[], enqueue=enqueue)
    driver = EphemeralStageDriver(store, queue)
    message = driver.enqueue_next(job.job_id)
    assert message is not None
    assert message.stage == "bind_inputs"


def test_language_only_replacement_still_enters_script_and_seedance_workflow() -> None:
    plan = build_stage_plan(
        {
            "slots": {"source_video": {"present": True}},
            "routes": {},
            "output_language": "ja",
            "admission": {"language_only": True},
            "review_route": "local_only",
        },
        review_route="route_2",
    )
    names = [stage["name"] for stage in plan]
    assert "build_script" in names
    assert "generate_storyboards" in names
    assert "await_script_approval" not in names
    assert "await_storyboard_approval" not in names
    assert "compile_seedance20_prompt" in names
    assert "submit_provider_video" in names


def test_worker_appends_script_revision_before_driver_reaches_approval() -> None:
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="revision-runtime")
    object_store = S3ObjectStore(MemoryS3(), bucket="test")
    manager = EphemeralWorkerManager(
        job_store=store,
        temporary_store=TemporaryMediaStore(object_store),
        stage_ports={"build_script": ScriptStage()},
        profile_bundle_resolver=SimpleNamespace(immutable=True),
        capability_ports={},
    )
    job = store.create_job(slots_manifest={"slots": {}, "review_route": "route_2"}, capability_token_hash="a" * 64, ttl_seconds=3600)
    checkpoint = store.claim_stage(job_id=job.job_id, stage="build_script", dedupe_key="script-1", owner="worker", ttl_seconds=60)
    manager.process_work_message(
        message=WorkMessage(job.job_id, "build_script", job.version, "script-1"),
        checkpoint=checkpoint,
        owner="worker",
    )
    snapshot = store.get_job(job.job_id)
    assert snapshot is not None and snapshot.current_script_revision == 1
    assert store.get_current_revision(job.job_id, "script").sha256 == hashlib.sha256(b'{"cuts":[{"cut_id":"c1"}]}').hexdigest()


def test_worker_promotes_only_qc_passed_mp4_to_exact_final_key() -> None:
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="final-runtime")
    client = MemoryS3()
    object_store = S3ObjectStore(client, bucket="test")
    manager = EphemeralWorkerManager(
        job_store=store,
        temporary_store=TemporaryMediaStore(object_store),
        final_store=FinalVideoStore(object_store),
        stage_ports={"run_qc": QcFinalStage()},
        profile_bundle_resolver=SimpleNamespace(immutable=True),
        capability_ports={},
    )
    job = store.create_job(slots_manifest={"slots": {}}, capability_token_hash="a" * 64, ttl_seconds=3600)
    checkpoint = store.claim_stage(job_id=job.job_id, stage="run_qc", dedupe_key="qc-1", owner="worker", ttl_seconds=60)
    manager.process_work_message(
        message=WorkMessage(job.job_id, "run_qc", job.version, "qc-1"),
        checkpoint=checkpoint,
        owner="worker",
    )
    snapshot = store.get_job(job.job_id)
    assert snapshot is not None and snapshot.state == "SUCCEEDED"
    assert snapshot.final_ref["object_key"] == f"final/{job.job_id}/result.mp4"
    assert snapshot.final_ref["content_type"] == "video/mp4"
    assert f"final/{job.job_id}/result.mp4" in client.objects


def test_driver_pauses_at_script_and_storyboard_approval_boundaries() -> None:
    store, _temporary, _manager = _runtime()
    job = store.create_job(
        slots_manifest={"slots": {}, "routes": {"product": "replace_from_slot"}, "review_route": "route_2"},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(messages=[], enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0")
    driver = EphemeralStageDriver(store, queue)
    for stage in ("bind_inputs", "probe_source", "analyze_dynamics", "route_regions", "build_script"):
        message = driver.enqueue_next(job.job_id)
        assert message is not None and message.stage == stage
        checkpoint = store.claim_stage(job_id=job.job_id, stage=stage, dedupe_key=message.dedupe_key, owner="worker", ttl_seconds=60)
        store.complete_stage(job_id=job.job_id, stage=stage, dedupe_key=checkpoint.dedupe_key, owner="worker", output_artifact_ids=(), ttl_seconds=3600)
    assert driver.enqueue_next(job.job_id) is None

    current = store.get_job(job.job_id)
    assert current is not None
    store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="test_approved",
        updates={
            "approved_script_sha256": "b" * 64,
            "state": "SCRIPT_APPROVED",
        },
        ttl_seconds=3600,
    )
    message = driver.enqueue_next(job.job_id)
    assert message is not None and message.stage == "generate_storyboards"
    checkpoint = store.claim_stage(job_id=job.job_id, stage=message.stage, dedupe_key=message.dedupe_key, owner="worker", ttl_seconds=60)
    store.complete_stage(job_id=job.job_id, stage=message.stage, dedupe_key=checkpoint.dedupe_key, owner="worker", output_artifact_ids=(), ttl_seconds=3600)
    assert driver.enqueue_next(job.job_id) is None

    current = store.get_job(job.job_id)
    assert current is not None
    storyboard_approved = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="test_storyboard_approved",
        updates={"approved_storyboard_sha256": "c" * 64, "state": "STORYBOARD_APPROVED"},
        ttl_seconds=3600,
    )
    message = driver.enqueue_next(job.job_id)
    assert message is not None and message.stage == "compile_seedance20_prompt"
    assert message.expected_version == storyboard_approved.version
