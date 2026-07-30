from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import fakeredis
import pytest

from server.errors import StateConflictError
from server.analysis_scope import promote_deferred_tool
from server.ephemeral_driver import EphemeralStageDriver
from server.ephemeral_worker import EphemeralStageContext, EphemeralWorkerManager
from server.job_models import WorkMessage
from server.media_materializer import MediaMaterializer
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


class MetadataStage:
    def run(self, *, context, input_artifacts):
        del input_artifacts
        payload = b'{"decision":"ffmpeg"}'
        artifact = context.publish_artifact(
            kind="ui_renderer_decision",
            stream=__import__("io").BytesIO(payload),
            content_type="application/json",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            metadata={
                "decision": "ffmpeg",
                "reason": "remotion_adapter_unavailable",
                "enabled": False,
            },
        )
        return {"published_artifacts": [artifact]}


class ProbeOutputStage:
    def run(self, *, context, input_artifacts):
        del input_artifacts
        return {
            "source_probe": {
                "duration_us": 1_000_000,
                "fps": 30,
                "source_sha256": "a" * 64,
            },
            "work_dir": str(context.work_dir),
        }


class DependsOnProbeOutputStage:
    def __init__(self) -> None:
        self.observed = None

    def run(self, *, context, input_artifacts):
        del input_artifacts
        self.observed = context.stage_outputs["probe_source"]
        return {"status": "ready"}


class RouteRegionsOutputStage:
    def run(self, *, context, input_artifacts):
        del context, input_artifacts
        return {
            "timeline_regions": {
                "regions": [
                    {
                        "region_id": "ui-001",
                        "region_type": "generated_ui_demo",
                        "deterministic_ui_rebuild_allowed": True,
                    }
                ]
            }
        }


class DependsOnTimelineRegionsStage:
    def __init__(self) -> None:
        self.observed = None

    def run(self, *, context, input_artifacts):
        del input_artifacts
        self.observed = context.timeline_regions
        return {"status": "ready"}


class ScopeAwareStage:
    def __init__(self) -> None:
        self.observed = None

    def run(self, *, context, input_artifacts):
        del input_artifacts
        self.observed = context.analysis_scope
        return {"status": "ready"}


class ExecutionScopeAwareStage:
    def __init__(self) -> None:
        self.observed = None

    def run(self, *, context, input_artifacts):
        del input_artifacts
        self.observed = context.execution_scope
        return {"status": "ready"}


class RouteRegionsPromotionStage:
    def run(self, *, context, input_artifacts):
        del input_artifacts
        receipt = promote_deferred_tool(
            scope=context.analysis_scope,
            tool_name="ui_rebuild",
            region_ids=["ui-001"],
            reason="generated UI interval confirmed",
        )
        return {
            "timeline_regions": {
                "regions": [{"region_id": "ui-001", "region_type": "generated_ui_demo"}]
            },
            "tool_promotion_receipts": [receipt],
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
    client = MemoryS3()
    object_store = S3ObjectStore(client, bucket="test")
    temporary = TemporaryMediaStore(object_store)
    manager = EphemeralWorkerManager(
        job_store=store,
        temporary_store=temporary,
        stage_ports={"analyze_dynamics": Stage()},
        profile_bundle_resolver=SimpleNamespace(immutable=True),
        capability_ports={},
        materializer=MediaMaterializer(
            SimpleNamespace(
                head=lambda key: {
                    "object_key": key,
                    "sha256": object_store.head(key).sha256,
                    "size_bytes": object_store.head(key).size_bytes,
                    "content_type": object_store.head(key).content_type,
                },
                open_stream=lambda key: client.get_object(Bucket="test", Key=key)["Body"],
            )
        ),
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
    assert len(result["output_artifact_ids"]) == 2
    artifact = next(
        store.get_artifact(job.job_id, artifact_id)
        for artifact_id in result["output_artifact_ids"]
        if store.get_artifact(job.job_id, artifact_id).kind == "analysis"
    )
    assert artifact is not None
    assert artifact.object_key.startswith(f"temporary/{job.job_id}/")
    assert temporary.list_job_keys(job.job_id) == tuple(
        sorted(
            store.get_artifact(job.job_id, artifact_id).object_key
            for artifact_id in result["output_artifact_ids"]
        )
    )


def test_worker_persists_artifact_metadata_for_auditable_tool_decisions() -> None:
    store, temporary, manager = _runtime()
    manager.stage_ports["resolve_ui_evidence"] = MetadataStage()
    job = store.create_job(slots_manifest={"slots": {}}, capability_token_hash="a" * 64, ttl_seconds=3600)
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="resolve_ui_evidence",
        dedupe_key="ui-decision-1",
        owner="worker-1",
        ttl_seconds=60,
    )

    result = manager.process_work_message(
        message=WorkMessage(job.job_id, "resolve_ui_evidence", job.version, "ui-decision-1"),
        checkpoint=checkpoint,
        owner="worker-1",
    )

    artifact = next(
        store.get_artifact(job.job_id, artifact_id)
        for artifact_id in result["output_artifact_ids"]
        if store.get_artifact(job.job_id, artifact_id).kind == "ui_renderer_decision"
    )
    assert artifact is not None
    assert artifact.metadata == {
        "decision": "ffmpeg",
        "reason": "remotion_adapter_unavailable",
        "enabled": False,
    }
    assert temporary.list_job_keys(job.job_id) == tuple(
        sorted(
            store.get_artifact(job.job_id, artifact_id).object_key
            for artifact_id in result["output_artifact_ids"]
        )
    )


def test_worker_rehydrates_only_safe_prior_stage_output_for_later_stages() -> None:
    store, _temporary, manager = _runtime()
    dependent = DependsOnProbeOutputStage()
    manager.stage_ports = {
        "probe_source": ProbeOutputStage(),
        "analyze_dynamics": dependent,
    }
    job = store.create_job(slots_manifest={"slots": {}}, capability_token_hash="a" * 64, ttl_seconds=3600)
    first = store.claim_stage(
        job_id=job.job_id,
        stage="probe_source",
        dedupe_key="probe-1",
        owner="worker-1",
        ttl_seconds=60,
    )
    first_result = manager.process_work_message(
        message=WorkMessage(job.job_id, "probe_source", job.version, "probe-1"),
        checkpoint=first,
        owner="worker-1",
    )
    store.complete_stage(
        job_id=job.job_id,
        stage="probe_source",
        dedupe_key="probe-1",
        owner="worker-1",
        output_artifact_ids=first_result["output_artifact_ids"],
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    second = store.claim_stage(
        job_id=job.job_id,
        stage="analyze_dynamics",
        dedupe_key="dynamics-1",
        owner="worker-1",
        ttl_seconds=60,
    )

    manager.process_work_message(
        message=WorkMessage(job.job_id, "analyze_dynamics", current.version, "dynamics-1"),
        checkpoint=second,
        owner="worker-1",
    )

    assert dependent.observed == {
        "source_probe": {
            "duration_us": 1_000_000,
            "fps": 30,
            "source_sha256": "a" * 64,
        }

    }


def test_stage_context_materializes_verified_background_music_extension(tmp_path: Path):
    song = tmp_path / "song.mp3"
    song.write_bytes(b"verified-audio")

    class Materializer:
        @contextmanager
        def materialize(self, **kwargs):
            assert kwargs["object_key"] == "uploads/job/song.mp3"
            assert kwargs["expected_sha256"] == hashlib.sha256(song.read_bytes()).hexdigest()
            yield SimpleNamespace(path=song, sha256=kwargs["expected_sha256"])

    context = EphemeralStageContext(
        job_id="job", stage="audit_seedance_request",
        snapshot=SimpleNamespace(slots_manifest={
            "extensions": {"background_music": {
                "values": ["uploads/job/song.mp3"],
                "sha256": [hashlib.sha256(song.read_bytes()).hexdigest()],
                "metadata": [{
                    "object_key": "uploads/job/song.mp3", "sha256": hashlib.sha256(song.read_bytes()).hexdigest(), "size_bytes": len(song.read_bytes()),
                }],
            }}
        }),
        job_store=SimpleNamespace(), temporary_store=SimpleNamespace(), work_dir=tmp_path,
        materializer=Materializer(),
    )

    with context.materialize_extension("background_music") as media:
        assert media.path == song


def test_stage_context_exposes_provider_segment_metadata_for_timeline_binding(tmp_path: Path):
    artifact = SimpleNamespace(
        to_dict=lambda: {
            "artifact_id": "provider-artifact", "kind": "provider_video", "sha256": "a" * 64,
            "metadata": {"segment_id": "S01", "segment_plan_sha256": "b" * 64},
        }
    )
    context = EphemeralStageContext(
        job_id="job", stage="splice_timeline", snapshot=SimpleNamespace(slots_manifest={}),
        job_store=SimpleNamespace(list_artifacts=lambda _job_id: [artifact]), temporary_store=SimpleNamespace(), work_dir=tmp_path,
    )

    assert context.artifacts[0]["segment_id"] == "S01"
    assert context.artifacts[0]["segment_plan_sha256"] == "b" * 64


def test_worker_projects_frozen_route_regions_into_later_stage_context() -> None:
    store, _temporary, manager = _runtime()
    dependent = DependsOnTimelineRegionsStage()
    manager.stage_ports = {
        "route_regions": RouteRegionsOutputStage(),
        "resolve_ui_evidence": dependent,
    }
    job = store.create_job(slots_manifest={"slots": {}}, capability_token_hash="a" * 64, ttl_seconds=3600)
    first = store.claim_stage(
        job_id=job.job_id,
        stage="route_regions",
        dedupe_key="route-1",
        owner="worker-1",
        ttl_seconds=60,
    )
    first_result = manager.process_work_message(
        message=WorkMessage(job.job_id, "route_regions", job.version, "route-1"),
        checkpoint=first,
        owner="worker-1",
    )
    store.complete_stage(
        job_id=job.job_id,
        stage="route_regions",
        dedupe_key="route-1",
        owner="worker-1",
        output_artifact_ids=first_result["output_artifact_ids"],
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    second = store.claim_stage(
        job_id=job.job_id,
        stage="resolve_ui_evidence",
        dedupe_key="ui-1",
        owner="worker-1",
        ttl_seconds=60,
    )

    manager.process_work_message(
        message=WorkMessage(job.job_id, "resolve_ui_evidence", current.version, "ui-1"),
        checkpoint=second,
        owner="worker-1",
    )

    assert dependent.observed == (
        {
            "region_id": "ui-001",
            "region_type": "generated_ui_demo",
            "deterministic_ui_rebuild_allowed": True,
        },
    )


def test_worker_freezes_stage4_promotions_into_downstream_execution_scope() -> None:
    store, _temporary, manager = _runtime()
    dependent = ExecutionScopeAwareStage()
    manager.stage_ports = {
        "route_regions": RouteRegionsPromotionStage(),
        "resolve_ui_evidence": dependent,
    }
    manifest = {
        "slots": {
            "source_video": {"present": True},
            "ui_screenshot": {"present": True},
        },
        "routes": {"ui": "generated_ui_demo"},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    first = store.claim_stage(
        job_id=job.job_id, stage="route_regions", dedupe_key="route-scope", owner="worker-1", ttl_seconds=60,
    )
    first_result = manager.process_work_message(
        message=WorkMessage(job.job_id, "route_regions", job.version, "route-scope"),
        checkpoint=first,
        owner="worker-1",
    )
    store.complete_stage(
        job_id=job.job_id,
        stage="route_regions",
        dedupe_key="route-scope",
        owner="worker-1",
        output_artifact_ids=first_result["output_artifact_ids"],
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    second = store.claim_stage(
        job_id=job.job_id, stage="resolve_ui_evidence", dedupe_key="ui-scope", owner="worker-1", ttl_seconds=60,
    )

    manager.process_work_message(
        message=WorkMessage(job.job_id, "resolve_ui_evidence", current.version, "ui-scope"),
        checkpoint=second,
        owner="worker-1",
    )

    assert dependent.observed["finalized"] is True
    assert dependent.observed["tools"]["ui_rebuild"]["status"] == "required"
    assert dependent.observed["tools"]["target_ui_ocr"]["status"] == "skipped"


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


def test_legacy_route_one_still_contains_both_editable_approval_gates() -> None:
    plan = build_stage_plan(
        {
            "slots": {
                "source_video": {"present": True},
                "new_model_image": {"present": True},
            },
            "routes": {"character": "replace_from_slot"},
            "review_route": "route_1",
        },
    )

    assert [stage["name"] for stage in plan if stage["kind"] == "approval"] == [
        "await_script_approval",
        "await_storyboard_approval",
    ]
    assert next(stage for stage in plan if stage["name"] == "build_script").get("mode") != "reuse_approved"


def test_driver_clears_legacy_script_approval_before_new_run_enters_review() -> None:
    store, _temporary, _manager = _runtime()
    job = store.create_job(
        slots_manifest={
            "slots": {
                "source_video": {"present": True},
                "new_model_image": {"present": True},
            },
            "routes": {"character": "replace_from_slot"},
            "review_route": "route_1",
        },
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    job = store.cas_transition(
        job_id=job.job_id,
        expected_version=job.version,
        command="seed_legacy_review",
        updates={"review_route": "route_1", "approved_script_sha256": "a" * 64},
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(messages=[], enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0")
    driver = EphemeralStageDriver(store, queue)

    message = driver.enqueue_next(job.job_id)

    current = store.get_job(job.job_id)
    assert message is not None
    assert message.stage == "bind_inputs"
    assert current is not None
    assert current.review_route == "route_2"
    assert current.approved_script_sha256 is None


def test_worker_exposes_the_manifest_pre_route_scope_to_stage_ports() -> None:
    store, temporary, manager = _runtime()
    stage = ScopeAwareStage()
    manager.stage_ports = {"analyze_dynamics": stage}
    job = store.create_job(
        slots_manifest={
            "slots": {
                "source_video": {"present": True},
                "new_model_image": {"present": True},
            },
            "routes": {"character": "replace_from_slot", "ui": "source_ui_keep"},
        },
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="analyze_dynamics",
        dedupe_key="scope-1",
        owner="worker-1",
        ttl_seconds=60,
    )

    manager.process_work_message(
        message=WorkMessage(job.job_id, "analyze_dynamics", job.version, "scope-1"),
        checkpoint=checkpoint,
        owner="worker-1",
    )

    assert stage.observed["semantic_pass"]["focus"] == [
        "source_timeline",
        "character_identity",
        "camera",
        "action",
        "continuity",
    ]
    assert stage.observed["tools"]["app_store_evidence"]["status"] == "skipped"


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


def test_driver_recovers_existing_script_stage_once_after_confirmed_line_sidecar() -> None:
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="script-recovery-runtime")
    job = store.create_job(
        slots_manifest={
            "slots": {},
            "routes": {"product": "replace_from_slot"},
            "review_route": "route_2",
        },
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    for stage in (
        "bind_inputs",
        "probe_source",
        "analyze_dynamics",
        "route_regions",
        "parse_app_store_evidence",
        "resolve_ui_evidence",
        "build_script",
    ):
        checkpoint = store.claim_stage(
            job_id=job.job_id,
            stage=stage,
            dedupe_key=f"draft-{stage}",
            owner="worker",
            ttl_seconds=60,
        )
        store.complete_stage(
            job_id=job.job_id,
            stage=stage,
            dedupe_key=checkpoint.dedupe_key,
            owner="worker",
            output_artifact_ids=(),
            ttl_seconds=3600,
        )
    script_sha = "b" * 64
    current = store.get_job(job.job_id)
    assert current is not None
    appended = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=current.version,
        manifest={"revision": 1, "sha256": script_sha},
        invalidate_downstream=False,
        ttl_seconds=3600,
    )
    lines = []
    line_sha = hashlib.sha256(
        json.dumps(lines, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    approved = store.approve_revision(
        job_id=job.job_id,
        kind="script",
        revision=1,
        expected_version=appended.version,
        expected_sha256=script_sha,
        script_approval={
            "contract": "approved-script-lines/v1",
            "revision": 1,
            "script_sha256": script_sha,
            "source_content_timeline_sha256": "c" * 64,
            "line_contracts": lines,
            "line_contracts_sha256": line_sha,
            "visible_text_locks": [],
            "visible_text_locks_sha256": line_sha,
        },
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(messages=[], enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0")

    message = EphemeralStageDriver(store, queue).enqueue_next(job.job_id)

    assert message is not None
    assert message.stage == "build_script"
    assert message.expected_version == approved.version


def test_driver_recovers_new_script_revision_when_script_sha_is_unchanged() -> None:
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="same-sha-script-recovery-runtime")
    job = store.create_job(
        slots_manifest={
            "slots": {},
            "routes": {"product": "replace_from_slot"},
            "review_route": "route_2",
        },
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    for stage in (
        "bind_inputs",
        "probe_source",
        "analyze_dynamics",
        "route_regions",
        "parse_app_store_evidence",
        "resolve_ui_evidence",
        "build_script",
    ):
        checkpoint = store.claim_stage(
            job_id=job.job_id,
            stage=stage,
            dedupe_key=f"draft-{stage}",
            owner="worker",
            ttl_seconds=60,
        )
        store.complete_stage(
            job_id=job.job_id,
            stage=stage,
            dedupe_key=checkpoint.dedupe_key,
            owner="worker",
            output_artifact_ids=(),
            ttl_seconds=3600,
        )
    script_sha = "b" * 64
    lines = []
    line_sha = hashlib.sha256(
        json.dumps(lines, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    first = store.get_job(job.job_id)
    assert first is not None
    first_revision = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=first.version,
        manifest={"revision": 1, "sha256": script_sha},
        invalidate_downstream=False,
        ttl_seconds=3600,
    )
    first_approval = store.approve_revision(
        job_id=job.job_id,
        kind="script",
        revision=1,
        expected_version=first_revision.version,
        expected_sha256=script_sha,
        script_approval={
            "contract": "approved-script-lines/v1",
            "revision": 1,
            "script_sha256": script_sha,
            "source_content_timeline_sha256": "c" * 64,
            "line_contracts": lines,
            "line_contracts_sha256": line_sha,
            "visible_text_locks": [],
            "visible_text_locks_sha256": line_sha,
        },
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(messages=[], enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0")
    driver = EphemeralStageDriver(store, queue)
    recovery_one = driver.enqueue_next(job.job_id)
    assert recovery_one is not None and recovery_one.stage == "build_script"
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="build_script",
        dedupe_key=recovery_one.dedupe_key,
        owner="worker",
        ttl_seconds=60,
    )
    store.complete_stage(
        job_id=job.job_id,
        stage="build_script",
        dedupe_key=checkpoint.dedupe_key,
        owner="worker",
        output_artifact_ids=(),
        ttl_seconds=3600,
    )
    after_first_recovery = store.get_job(job.job_id)
    assert after_first_recovery is not None
    with pytest.raises(StateConflictError):
        store.claim_stage(
            job_id=job.job_id,
            stage="build_script",
            dedupe_key=recovery_one.dedupe_key,
            owner="duplicate-worker",
            ttl_seconds=60,
        )
    with pytest.raises(StateConflictError):
        store.claim_stage(
            job_id=job.job_id,
            stage="build_script",
            dedupe_key="f" * 64,
            owner="worker",
            ttl_seconds=60,
        )
    storyboard_revision = store.append_revision(
        job_id=job.job_id,
        kind="storyboard",
        expected_version=after_first_recovery.version,
        manifest={"revision": 1, "sha256": "e" * 64},
        invalidate_downstream=False,
        ttl_seconds=3600,
    )
    storyboard_approval = store.approve_revision(
        job_id=job.job_id,
        kind="storyboard",
        revision=1,
        expected_version=storyboard_revision.version,
        expected_sha256="e" * 64,
        ttl_seconds=3600,
    )

    after_storyboard_change = driver.enqueue_next(job.job_id)

    assert after_storyboard_change is not None
    assert after_storyboard_change.stage == "generate_storyboards"
    assert after_storyboard_change.expected_version == storyboard_approval.version
    second_revision = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=storyboard_approval.version,
        manifest={"revision": 2, "sha256": script_sha},
        invalidate_downstream=False,
        ttl_seconds=3600,
    )
    second_approval = store.approve_revision(
        job_id=job.job_id,
        kind="script",
        revision=2,
        expected_version=second_revision.version,
        expected_sha256=script_sha,
        script_approval={
            "contract": "approved-script-lines/v1",
            "revision": 2,
            "script_sha256": script_sha,
            "source_content_timeline_sha256": "d" * 64,
            "line_contracts": lines,
            "line_contracts_sha256": line_sha,
            "visible_text_locks": [],
            "visible_text_locks_sha256": line_sha,
        },
        ttl_seconds=3600,
    )

    recovery_two = driver.enqueue_next(job.job_id)

    assert recovery_two is not None
    assert recovery_two.stage == "build_script"
    assert recovery_two.expected_version == second_approval.version
    assert recovery_two.dedupe_key != recovery_one.dedupe_key


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
