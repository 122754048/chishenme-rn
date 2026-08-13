from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import fakeredis
import pytest

from server.errors import ReplicationError, StateConflictError
from server.ephemeral_driver import EphemeralStageDriver, _dedupe
from server.ephemeral_worker import EphemeralStageContext, EphemeralWorkerManager
from server.job_models import WorkMessage
from server.media_materializer import MediaMaterializer
from server.object_store import FinalVideoStore, S3ObjectStore, TemporaryMediaStore
from server.orchestrator import (
    _v2_approval_output_fingerprint,
    build_stage_execution_record,
    build_stage_plan,
    v2_stage_expected_input_fingerprint,
)
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


def test_v2_stage_completion_persists_runtime_fingerprints() -> None:
    store, _temporary, _manager = _runtime()
    job = store.create_job(
        slots_manifest={"extensions": {"edit_contract": "video-edit-v2"}, "slots": {}},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key="v2-bind",
        owner="worker-v2",
        ttl_seconds=60,
    )
    completed = store.complete_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=checkpoint.dedupe_key,
        owner="worker-v2",
        output_artifact_ids=(),
        input_fingerprint="1" * 64,
        output_fingerprint="2" * 64,
        contract_version="video-edit-v2",
        ttl_seconds=3600,
    )
    assert completed.status == "SUCCEEDED"
    assert completed.input_fingerprint == "1" * 64
    assert completed.output_fingerprint == "2" * 64
    assert completed.contract_version == "video-edit-v2"
    restored = store.get_stage_checkpoint(job.job_id, "bind_inputs")
    assert restored is not None
    assert restored.output_fingerprint == "2" * 64


def test_v2_worker_result_contains_executed_stage_fingerprint_record() -> None:
    store, _temporary, manager = _runtime()

    class V2BindStage:
        def run(self, *, context, input_artifacts):
            del context, input_artifacts
            return {"bound": True}

    manager.stage_ports = {"bind_inputs": V2BindStage()}
    job = store.create_job(
        slots_manifest={"extensions": {"edit_contract": "video-edit-v2"}, "slots": {}},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    bind_input = build_stage_plan(job.slots_manifest)[0]["expected_input_fingerprint"]
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=_dedupe(
            job.job_id,
            "bind_inputs",
            job,
            input_fingerprint=bind_input,
            contract_version="video-edit-v2",
        ),
        owner="worker-v2",
        ttl_seconds=60,
    )
    result = manager.process_work_message(
        message=WorkMessage(job.job_id, "bind_inputs", job.version, checkpoint.dedupe_key),
        checkpoint=checkpoint,
        owner="worker-v2",
    )
    record = result["stage_execution"]
    assert record["status"] == "SUCCEEDED"
    assert record["contract_version"] == "video-edit-v2"
    assert len(record["input_fingerprint"]) == 64
    assert len(record["output_fingerprint"]) == 64


def test_v2_plan_routes_probe_source_before_real_durable_dynamics_port() -> None:
    plan = build_stage_plan(
        {
            "extensions": {"edit_contract": "video-edit-v2"},
            "slots": {"source_video": {"present": True}},
            "routes": {},
        }
    )
    names = [str(item["name"]) for item in plan]
    assert names.index("probe_source") < names.index("analyze_source")
    analyze = next(item for item in plan if item["name"] == "analyze_source")
    assert "probe_source" in analyze["depends_on"]


def test_v2_approved_script_is_a_runtime_dependency_without_phantom_checkpoint() -> None:
    store, _temporary, manager = _runtime()

    class AssetBoardStage:
        def run(self, *, context, input_artifacts):
            del context, input_artifacts
            return {"status": "board-ready"}

    manager.stage_ports = {"generate_asset_boards": AssetBoardStage()}
    job = store.create_job(
        slots_manifest={
            "extensions": {"edit_contract": "video-edit-v2"},
            "slots": {"source_video": {"present": True}, "new_model_image": {"present": True}},
            "routes": {"character": "replace_from_slot"},
        },
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    approved = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="approve_script_for_v2_runtime",
        updates={
            "current_script_revision": 1,
            "approved_script_sha256": "b" * 64,
            "state": "SCRIPT_APPROVED",
        },
        ttl_seconds=3600,
    )
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="generate_asset_boards",
        dedupe_key=_dedupe(
            job.job_id,
            "generate_asset_boards",
            approved,
            input_fingerprint=v2_stage_expected_input_fingerprint(
                build_stage_plan(
                    job.slots_manifest,
                    approval_state={"script_revision": 1, "script_sha256": "b" * 64},
                ),
                "generate_asset_boards",
                checkpoint_lookup=lambda stage_name: store.get_stage_checkpoint(job.job_id, stage_name),
                approval_state={"script_revision": 1, "script_sha256": "b" * 64},
            ),
            contract_version="video-edit-v2",
        ),
        owner="worker-v2",
        ttl_seconds=60,
    )

    result = manager.process_work_message(
        message=WorkMessage(job.job_id, "generate_asset_boards", approved.version, checkpoint.dedupe_key),
        checkpoint=checkpoint,
        owner="worker-v2",
    )

    assert result["output"]["status"] == "board-ready"


def test_v2_direct_dependencies_use_only_approved_script_and_asset_boards() -> None:
    plan = build_stage_plan(
        {
            "extensions": {"edit_contract": "video-edit-v2"},
            "slots": {
                "source_video": {"present": True},
                "new_model_image": {"present": True},
            },
            "routes": {"character": "replace_from_slot"},
        }
    )
    segment_plan = next(item for item in plan if item["name"] == "plan_segments")
    compiler = next(item for item in plan if item["name"] == "compile_edit_prompt")
    names = [item["name"] for item in plan]
    assert "generate_sketch_storyboard" not in names
    assert "await_storyboard_approval" not in names
    assert segment_plan["depends_on"] == [
        "analyze_source",
        "await_script_approval",
        "generate_asset_boards",
    ]
    assert "await_script_approval" in compiler["depends_on"]
    assert "await_storyboard_approval" not in compiler["depends_on"]


def test_v2_driver_reaches_segment_plan_after_script_approval_without_storyboard() -> None:
    store, _temporary, _manager = _runtime()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {
            "source_video": {"present": True},
            "new_model_image": {"present": True},
        },
        "routes": {"character": "replace_from_slot"},
    }
    job = store.create_job(
        slots_manifest=manifest,
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    approved = store.cas_transition(
        job_id=job.job_id,
        expected_version=job.version,
        command="approve_v2_script_without_storyboard",
        updates={
            "current_script_revision": 1,
            "approved_script_sha256": "b" * 64,
            "state": "SCRIPT_APPROVED",
        },
        ttl_seconds=3600,
    )
    approval_state = {
        "script_revision": approved.current_script_revision,
        "script_sha256": approved.approved_script_sha256,
    }
    plan = build_stage_plan(manifest, approval_state=approval_state)
    executed: dict[str, dict[str, object]] = {
        "await_script_approval": {
            "status": "SUCCEEDED",
            "output_fingerprint": _v2_approval_output_fingerprint(
                "await_script_approval", approval_state
            ),
        },
    }
    pre_segment_names = {
        "bind_inputs",
        "probe_source",
        "analyze_source",
        "build_target_evidence",
        "build_edit_script",
        "await_script_approval",
        "generate_asset_boards",
    }
    for stage in plan:
        name = str(stage["name"])
        if name == "plan_segments" or name not in pre_segment_names:
            break
        if name == "await_script_approval":
            continue
        output = hashlib.sha256(f"single-approval:{name}".encode("utf-8")).hexdigest()
        record = build_stage_execution_record(
            plan,
            name,
            executed=executed,
            output_fingerprint=output,
        )
        executed[name] = record
        runtime = str(stage.get("runtime_stage") or name)
        checkpoint = store.claim_stage(
            job_id=job.job_id,
            stage=runtime,
            dedupe_key=f"single-approval-{runtime}",
            owner="worker",
            ttl_seconds=60,
        )
        store.complete_stage(
            job_id=job.job_id,
            stage=runtime,
            dedupe_key=checkpoint.dedupe_key,
            owner="worker",
            output_artifact_ids=(),
            input_fingerprint=record["input_fingerprint"],
            output_fingerprint=output,
            contract_version="video-edit-v2",
            ttl_seconds=3600,
        )
    queue = SimpleNamespace(
        messages=[],
        enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0",
    )

    message = EphemeralStageDriver(store, queue).enqueue_next(job.job_id)

    assert message is not None
    assert message.stage == "segment_plan"


def test_driver_requeues_earliest_v2_stage_and_persists_downstream_invalidation() -> None:
    store, _temporary, _manager = _runtime()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}},
        "routes": {},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    plan = build_stage_plan(manifest)
    bind = store.claim_stage(job_id=job.job_id, stage="bind_inputs", dedupe_key="bind-v2", owner="worker", ttl_seconds=60)
    store.complete_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=bind.dedupe_key,
        owner="worker",
        output_artifact_ids=(),
        input_fingerprint=plan[0]["expected_input_fingerprint"],
        output_fingerprint="c" * 64,
        contract_version="video-edit-v2",
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    changed = dict(manifest)
    changed["routes"] = {"tail": "keep_source_tail_card"}
    changed_job = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="change_v2_manifest_input",
        updates={"slots_manifest": changed},
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(messages=[], enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0")

    message = EphemeralStageDriver(store, queue).enqueue_next(job.job_id)

    assert message is not None and message.stage == "bind_inputs"
    invalidated = store.get_stage_checkpoint(job.job_id, "bind_inputs")
    assert invalidated is not None and invalidated.status == "NEEDS_RECOMPUTE"
    assert changed_job.version < (store.get_job(job.job_id).version if store.get_job(job.job_id) else 0)


def test_v2_language_compound_uses_only_h3_provider_stages() -> None:
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2", "change_language": True},
        "output_language": "de",
        "admission": {"language_only": False},
        "slots": {
            "source_video": {"present": True},
            "new_model_image": {"present": True},
            "new_product_image": {"present": True},
        },
        "routes": {"character": "replace_from_slot", "product": "replace_from_slot"},
    }
    names = [str(stage["name"]) for stage in build_stage_plan(manifest)]
    assert "compile_h3_edit" in names
    assert "audit_h3_request" in names
    assert "submit_h3_edit" in names
    assert "wait_h3_edit" in names
    assert "compile_edit_prompt" not in names
    assert "run_song_lip_sync" not in names


def test_v2_mv_song_uses_h3_without_post_generation_lip_sync() -> None:
    manifest = {
        "extensions": {
            "edit_contract": "video-edit-v2",
            "background_music": {"kind": "song"},
        },
        "audio_plan": {"mv_lip_sync_route": "song_lipsync"},
        "slots": {"source_video": {"present": True}, "new_model_image": {"present": True}},
        "routes": {"character": "replace_from_slot"},
    }
    names = [str(stage["name"]) for stage in build_stage_plan(manifest)]
    assert names.count("submit_h3_edit") == 1
    assert "run_song_lip_sync" not in names
    assert "submit_provider_edit" not in names


def test_script_approval_change_invalidates_asset_board_and_successors_only() -> None:
    store, _temporary, _manager = _runtime()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {
            "source_video": {"present": True},
            "new_model_image": {"present": True},
        },
        "routes": {"character": "replace_from_slot"},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    current = store.get_job(job.job_id)
    assert current is not None
    approved = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="seed_script_approval_for_invalidation",
        updates={
            "current_script_revision": 1,
            "approved_script_sha256": "b" * 64,
            "current_storyboard_revision": 1,
            "approved_storyboard_sha256": "c" * 64,
        },
        ttl_seconds=3600,
    )
    approval_state = {
        "script_revision": approved.current_script_revision,
        "script_sha256": approved.approved_script_sha256,
        "storyboard_revision": approved.current_storyboard_revision,
        "storyboard_sha256": approved.approved_storyboard_sha256,
    }
    plan = build_stage_plan(manifest, approval_state=approval_state)
    executed: dict[str, dict[str, object]] = {
        "await_script_approval": {
            "status": "SUCCEEDED",
            "output_fingerprint": _v2_approval_output_fingerprint("await_script_approval", approval_state),
        },
        "await_storyboard_approval": {
            "status": "SUCCEEDED",
            "output_fingerprint": _v2_approval_output_fingerprint("await_storyboard_approval", approval_state),
        },
    }
    runtime_by_name = {str(item["name"]): str(item.get("runtime_stage") or item["name"]) for item in plan}
    for stage in plan:
        name = str(stage["name"])
        if name in {"await_script_approval", "await_storyboard_approval"}:
            continue
        output_fingerprint = hashlib.sha256(f"executed:{name}".encode("utf-8")).hexdigest()
        record = build_stage_execution_record(
            plan,
            name,
            executed=executed,
            output_fingerprint=output_fingerprint,
        )
        executed[name] = record
        runtime = runtime_by_name[name]
        checkpoint = store.claim_stage(job_id=job.job_id, stage=runtime, dedupe_key=f"seed-{runtime}", owner="worker", ttl_seconds=60)
        store.complete_stage(
            job_id=job.job_id,
            stage=runtime,
            dedupe_key=checkpoint.dedupe_key,
            owner="worker",
            output_artifact_ids=(),
            input_fingerprint=record["input_fingerprint"],
            output_fingerprint=output_fingerprint,
            contract_version="video-edit-v2",
            ttl_seconds=3600,
        )
    current = store.get_job(job.job_id)
    assert current is not None
    changed_job = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="change_approved_script_revision",
        updates={
            "current_script_revision": 2,
            "approved_script_sha256": "d" * 64,
        },
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(messages=[], enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0")

    message = EphemeralStageDriver(store, queue).enqueue_next(job.job_id)

    assert message is not None and message.stage == "generate_asset_boards"
    assert changed_job.version < (store.get_job(job.job_id).version if store.get_job(job.job_id) else 0)
    assert store.get_stage_checkpoint(job.job_id, "bind_inputs").status == "SUCCEEDED"
    assert store.get_stage_checkpoint(job.job_id, "analyze_dynamics").status == "SUCCEEDED"
    assert store.get_stage_checkpoint(job.job_id, "generate_asset_boards").status == "NEEDS_RECOMPUTE"
    assert store.get_stage_checkpoint(job.job_id, "compile_seedance20_prompt").status == "NEEDS_RECOMPUTE"


def test_v2_legacy_storyboard_change_does_not_invalidate_script_authority() -> None:
    store, _temporary, _manager = _runtime()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {
            "source_video": {"present": True},
            "new_model_image": {"present": True},
        },
        "routes": {"character": "replace_from_slot"},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    current = store.get_job(job.job_id)
    assert current is not None
    approved = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="seed_v2_script_with_legacy_storyboard_metadata",
        updates={
            "current_script_revision": 1,
            "approved_script_sha256": "b" * 64,
            "current_storyboard_revision": 1,
            "approved_storyboard_sha256": "c" * 64,
        },
        ttl_seconds=3600,
    )
    approval_state = {
        "script_revision": approved.current_script_revision,
        "script_sha256": approved.approved_script_sha256,
    }
    plan = build_stage_plan(manifest, approval_state=approval_state)
    executed: dict[str, dict[str, object]] = {
        "await_script_approval": {"status": "SUCCEEDED", "output_fingerprint": _v2_approval_output_fingerprint("await_script_approval", approval_state)},
    }
    runtime_by_name = {str(item["name"]): str(item.get("runtime_stage") or item["name"]) for item in plan}
    for stage in plan:
        name = str(stage["name"])
        if name == "await_script_approval":
            continue
        output_fingerprint = hashlib.sha256(f"storyboard-seeded:{name}".encode("utf-8")).hexdigest()
        record = build_stage_execution_record(plan, name, executed=executed, output_fingerprint=output_fingerprint)
        executed[name] = record
        runtime = runtime_by_name[name]
        checkpoint = store.claim_stage(job_id=job.job_id, stage=runtime, dedupe_key=f"story-seeded-{runtime}", owner="worker", ttl_seconds=60)
        store.complete_stage(
            job_id=job.job_id,
            stage=runtime,
            dedupe_key=checkpoint.dedupe_key,
            owner="worker",
            output_artifact_ids=(),
            input_fingerprint=record["input_fingerprint"],
            output_fingerprint=output_fingerprint,
            contract_version="video-edit-v2",
            ttl_seconds=3600,
        )
    current = store.get_job(job.job_id)
    assert current is not None
    changed = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="change_legacy_storyboard_metadata",
        updates={"current_storyboard_revision": 2, "approved_storyboard_sha256": "e" * 64},
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(messages=[], enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0")

    message = EphemeralStageDriver(store, queue).enqueue_next(job.job_id)

    assert message is None
    assert changed.version == (store.get_job(job.job_id).version if store.get_job(job.job_id) else 0)
    assert store.get_stage_checkpoint(job.job_id, "generate_asset_boards").status == "SUCCEEDED"
    assert store.get_stage_checkpoint(job.job_id, "segment_plan").status == "SUCCEEDED"
    assert store.get_stage_checkpoint(job.job_id, "run_qc").status == "SUCCEEDED"


def test_script_approval_virtual_dependency_runs_segment_plan_and_binds_revision() -> None:
    store, _temporary, manager = _runtime()

    class SegmentStage:
        def run(self, *, context, input_artifacts):
            del context, input_artifacts
            return {"status": "segment-ready"}

    manager.stage_ports = {"segment_plan": SegmentStage()}
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}},
        "routes": {},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    current = store.get_job(job.job_id)
    assert current is not None
    approved = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="approve_script_for_segment_plan",
        updates={
            "current_script_revision": 1,
            "approved_script_sha256": "b" * 64,
        },
        ttl_seconds=3600,
    )
    approval_state = {
        "script_revision": approved.current_script_revision,
        "script_sha256": approved.approved_script_sha256,
    }
    plan = build_stage_plan(manifest, approval_state=approval_state)
    executed: dict[str, dict[str, object]] = {
        "await_script_approval": {
            "status": "SUCCEEDED",
            "output_fingerprint": _v2_approval_output_fingerprint("await_script_approval", approval_state),
        },
    }
    for stage_name in (
        "bind_inputs",
        "probe_source",
        "analyze_source",
        "build_edit_script",
        "generate_asset_boards",
    ):
        stage = next(item for item in plan if item["name"] == stage_name)
        output = hashlib.sha256(f"segment-seeded:{stage_name}".encode("utf-8")).hexdigest()
        record = build_stage_execution_record(plan, stage_name, executed=executed, output_fingerprint=output)
        executed[stage_name] = record
        runtime_stage = str(stage.get("runtime_stage") or stage_name)
        checkpoint = store.claim_stage(job_id=job.job_id, stage=runtime_stage, dedupe_key=f"seed-{runtime_stage}", owner="worker", ttl_seconds=60)
        store.complete_stage(
            job_id=job.job_id,
            stage=runtime_stage,
            dedupe_key=checkpoint.dedupe_key,
            owner="worker",
            output_artifact_ids=(),
            input_fingerprint=record["input_fingerprint"],
            output_fingerprint=output,
            contract_version="video-edit-v2",
            ttl_seconds=3600,
        )
    current = store.get_job(job.job_id)
    assert current is not None
    current = store.get_job(job.job_id)
    assert current is not None
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="segment_plan",
        dedupe_key=_dedupe(
            job.job_id,
            "segment_plan",
            current,
            input_fingerprint=v2_stage_expected_input_fingerprint(
                plan,
                "plan_segments",
                checkpoint_lookup=lambda stage_name: store.get_stage_checkpoint(job.job_id, stage_name),
                approval_state=approval_state,
            ),
            contract_version="video-edit-v2",
        ),
        owner="worker",
        ttl_seconds=60,
    )

    result = manager.process_work_message(
        message=WorkMessage(job.job_id, "segment_plan", current.version, checkpoint.dedupe_key),
        checkpoint=checkpoint,
        owner="worker",
    )

    assert result["output"]["status"] == "segment-ready"
    expected = build_stage_execution_record(
        plan,
        "plan_segments",
        executed=executed,
        output_fingerprint=hashlib.sha256(b"segment-plan-output").hexdigest(),
    )
    assert result["stage_execution"]["input_fingerprint"] == expected["input_fingerprint"]


def test_claimed_v2_downstream_is_invalidated_and_old_worker_lease_is_fenced() -> None:
    store, _temporary, manager = _runtime()
    manager.stage_ports["bind_inputs"] = Stage()
    manager.stage_ports["generate_asset_boards"] = Stage()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {
            "source_video": {"present": True},
            "new_model_image": {"present": True},
        },
        "routes": {"character": "replace_from_slot"},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    current = store.get_job(job.job_id)
    assert current is not None
    approved = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="seed_claimed_stage_approval",
        updates={"current_script_revision": 1, "approved_script_sha256": "b" * 64},
        ttl_seconds=3600,
    )
    plan = build_stage_plan(manifest, approval_state={"script_revision": 1, "script_sha256": "b" * 64})
    executed: dict[str, dict[str, object]] = {}
    for stage_name in (
        "bind_inputs",
        "probe_source",
        "analyze_source",
        "build_target_evidence",
        "build_edit_script",
    ):
        stage = next(item for item in plan if item["name"] == stage_name)
        output = hashlib.sha256(f"claimed-seeded:{stage_name}".encode()).hexdigest()
        record = build_stage_execution_record(plan, stage_name, executed=executed, output_fingerprint=output)
        executed[stage_name] = record
        runtime = str(stage.get("runtime_stage") or stage_name)
        checkpoint = store.claim_stage(job_id=job.job_id, stage=runtime, dedupe_key=f"seed-{runtime}", owner="worker", ttl_seconds=60)
        store.complete_stage(
            job_id=job.job_id,
            stage=runtime,
            dedupe_key=checkpoint.dedupe_key,
            owner="worker",
            output_artifact_ids=(),
            input_fingerprint=record["input_fingerprint"],
            output_fingerprint=output,
            contract_version="video-edit-v2",
            ttl_seconds=3600,
        )
    current = store.get_job(job.job_id)
    assert current is not None
    claimed = store.claim_stage(
        job_id=job.job_id,
        stage="generate_asset_boards",
        dedupe_key="old-asset-board-message",
        owner="old-worker",
        ttl_seconds=60,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    changed = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="change_claimed_stage_approval",
        updates={"current_script_revision": 2, "approved_script_sha256": "c" * 64},
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(messages=[], enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0")

    message = EphemeralStageDriver(store, queue).enqueue_next(job.job_id)

    invalidated = store.get_stage_checkpoint(job.job_id, "generate_asset_boards")
    assert message is not None and message.stage == "generate_asset_boards"
    assert invalidated is not None and invalidated.status == "NEEDS_RECOMPUTE"
    with pytest.raises(StateConflictError):
        store.complete_stage(
            job_id=job.job_id,
            stage="generate_asset_boards",
            dedupe_key=claimed.dedupe_key,
            owner="old-worker",
            output_artifact_ids=(),
            ttl_seconds=3600,
        )
    assert changed.version < (store.get_job(job.job_id).version if store.get_job(job.job_id) else 0)


def test_old_v2_work_message_is_rejected_before_handler_after_approval_changes() -> None:
    store, _temporary, manager = _runtime()
    calls: list[str] = []

    class Handler:
        def run(self, *, context, input_artifacts):
            del context, input_artifacts
            calls.append("called")
            return {"unexpected": True}

    manager.stage_ports = {"generate_asset_boards": Handler()}
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}, "new_model_image": {"present": True}},
        "routes": {"character": "replace_from_slot"},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    current = store.get_job(job.job_id)
    assert current is not None
    old = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="old_approval_message",
        updates={"current_script_revision": 1, "approved_script_sha256": "b" * 64},
        ttl_seconds=3600,
    )
    from server.ephemeral_driver import _dedupe
    old_dedupe = _dedupe(job.job_id, "generate_asset_boards", old)
    current = store.get_job(job.job_id)
    assert current is not None
    changed = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="new_approval_before_old_delivery",
        updates={"current_script_revision": 2, "approved_script_sha256": "c" * 64},
        ttl_seconds=3600,
    )
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="generate_asset_boards",
        dedupe_key=old_dedupe,
        owner="worker",
        ttl_seconds=60,
    )

    with pytest.raises(ReplicationError) as error:
        manager.process_work_message(
            message=WorkMessage(job.job_id, "generate_asset_boards", old.version, old_dedupe),
            checkpoint=checkpoint,
            owner="worker",
        )

    assert error.value.code == "STAGE_FINGERPRINT_STALE"
    assert calls == []
    assert changed.version < (store.get_job(job.job_id).version if store.get_job(job.job_id) else 0)


def test_needs_recompute_reclaim_complete_advances_to_next_v2_stage() -> None:
    store, _temporary, manager = _runtime()
    manager.stage_ports["bind_inputs"] = Stage()
    manager.stage_ports["probe_source"] = Stage()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}},
        "routes": {},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    current = store.get_job(job.job_id)
    assert current is not None
    old_plan = build_stage_plan(manifest)
    old_bind = store.claim_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=_dedupe(job.job_id, "bind_inputs", current),
        owner="old-worker",
        ttl_seconds=60,
    )
    store.complete_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=old_bind.dedupe_key,
        owner="old-worker",
        output_artifact_ids=(),
        input_fingerprint=old_plan[0]["expected_input_fingerprint"],
        output_fingerprint="a" * 64,
        contract_version="video-edit-v2",
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    stale = store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="make_v2_input_stale",
        updates={"slots_manifest": {**manifest, "routes": {"tail": "keep_source_tail_card"}}},
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(messages=[], enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0")
    driver = EphemeralStageDriver(store, queue)
    first = driver.enqueue_next(job.job_id)
    assert first is not None and first.stage == "bind_inputs"
    invalidated = store.get_stage_checkpoint(job.job_id, "bind_inputs")
    assert invalidated is not None and invalidated.status == "NEEDS_RECOMPUTE"
    checkpoint = store.claim_stage(job_id=job.job_id, stage="bind_inputs", dedupe_key=first.dedupe_key, owner="worker", ttl_seconds=60)
    result = manager.process_work_message(
        message=WorkMessage(job.job_id, "bind_inputs", stale.version, first.dedupe_key),
        checkpoint=checkpoint,
        owner="worker",
    )
    store.complete_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=checkpoint.dedupe_key,
        owner="worker",
        output_artifact_ids=result["output_artifact_ids"],
        input_fingerprint=result["stage_execution"]["input_fingerprint"],
        output_fingerprint=result["stage_execution"]["output_fingerprint"],
        contract_version=result["stage_execution"]["contract_version"],
        ttl_seconds=3600,
    )
    next_message = driver.enqueue_next(job.job_id)

    restored = store.get_stage_checkpoint(job.job_id, "bind_inputs")
    assert restored is not None and restored.status == "SUCCEEDED"
    assert next_message is not None and next_message.stage == "probe_source"


def test_v2_dedupe_identity_ignores_accumulated_invalidations() -> None:
    store, _temporary, _manager = _runtime()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}},
        "routes": {},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    current = store.get_job(job.job_id)
    assert current is not None
    input_fingerprint = "1" * 64
    clean = _dedupe(
        job.job_id,
        "bind_inputs",
        current,
        input_fingerprint=input_fingerprint,
        contract_version="video-edit-v2",
    )
    historically_invalidated = replace(current, invalidated=("bind_inputs", "probe_source"))
    after_history = _dedupe(
        job.job_id,
        "bind_inputs",
        historically_invalidated,
        input_fingerprint=input_fingerprint,
        contract_version="video-edit-v2",
    )

    assert after_history == clean


def test_same_v2_stage_reclaims_after_two_distinct_input_fingerprints() -> None:
    store, _temporary, _manager = _runtime()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}},
        "routes": {},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    current = store.get_job(job.job_id)
    assert current is not None
    input_one = "1" * 64
    input_two = "2" * 64
    input_three = "3" * 64
    first = _dedupe(job.job_id, "bind_inputs", current, input_fingerprint=input_one, contract_version="video-edit-v2")
    second = _dedupe(job.job_id, "bind_inputs", current, input_fingerprint=input_two, contract_version="video-edit-v2")
    third = _dedupe(job.job_id, "bind_inputs", current, input_fingerprint=input_three, contract_version="video-edit-v2")
    assert len({first, second, third}) == 3
    claimed = store.claim_stage(job_id=job.job_id, stage="bind_inputs", dedupe_key=first, owner="worker", ttl_seconds=60)
    store.complete_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=claimed.dedupe_key,
        owner="worker",
        output_artifact_ids=(),
        input_fingerprint=input_one,
        output_fingerprint="a" * 64,
        contract_version="video-edit-v2",
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    store.invalidate_stage_checkpoints(
        job_id=job.job_id,
        expected_version=current.version,
        stages=("bind_inputs",),
        ttl_seconds=3600,
    )
    claimed_two = store.claim_stage(job_id=job.job_id, stage="bind_inputs", dedupe_key=second, owner="worker", ttl_seconds=60)
    store.complete_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=claimed_two.dedupe_key,
        owner="worker",
        output_artifact_ids=(),
        input_fingerprint=input_two,
        output_fingerprint="b" * 64,
        contract_version="video-edit-v2",
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    store.invalidate_stage_checkpoints(
        job_id=job.job_id,
        expected_version=current.version,
        stages=("bind_inputs",),
        ttl_seconds=3600,
    )
    claimed_three = store.claim_stage(job_id=job.job_id, stage="bind_inputs", dedupe_key=third, owner="worker", ttl_seconds=60)

    assert claimed_three.status == "CLAIMED"


def test_v2_script_revision_uses_real_append_and_approve_api_for_runtime_fingerprint() -> None:
    store, _temporary, _manager = _runtime()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}, "new_model_image": {"present": True}},
        "routes": {"character": "replace_from_slot"},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    script_bytes = b'{"cuts":[{"cut_id":"C01"}]}'
    script_sha = hashlib.sha256(script_bytes).hexdigest()
    current = store.get_job(job.job_id)
    assert current is not None
    appended = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=current.version,
        manifest=RevisionManifest(
            kind="script",
            revision=1,
            object_key=f"temporary/{job.job_id}/script.json",
            sha256=script_sha,
            inputs_sha256="d" * 64,
            created_at=datetime.now(timezone.utc).isoformat(),
            output_language="en",
        ),
        invalidate_downstream=True,
        ttl_seconds=3600,
    )
    line_sha = hashlib.sha256(b"[]").hexdigest()
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
            "source_content_timeline_sha256": "e" * 64,
            "line_contracts": [],
            "line_contracts_sha256": line_sha,
            "visible_text_locks": [],
            "visible_text_locks_sha256": line_sha,
        },
        ttl_seconds=3600,
    )
    approval = store.get_script_approval(job.job_id, 1)
    assert approved.approved_script_sha256 == script_sha
    assert approval is not None and approval["script_sha256"] == script_sha
    plan = build_stage_plan(
        manifest,
        approval_state={"script_revision": 1, "script_sha256": script_sha},
    )
    board = next(item for item in plan if item["name"] == "generate_asset_boards")
    assert board["static_inputs"]["approved_script"]["revision"] == 1
    assert board["static_inputs"]["approved_script"]["sha256"] == script_sha


def test_worker_does_not_hydrate_stale_v2_checkpoint_output() -> None:
    store, _temporary, manager = _runtime()
    manager.stage_ports["bind_inputs"] = Stage()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}},
        "routes": {},
    }
    job = store.create_job(slots_manifest=manifest, capability_token_hash="a" * 64, ttl_seconds=3600)
    plan = build_stage_plan(manifest)
    bind = store.claim_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=_dedupe(
            job.job_id,
            "bind_inputs",
            job,
            input_fingerprint=plan[0]["expected_input_fingerprint"],
            contract_version="video-edit-v2",
        ),
        owner="worker",
        ttl_seconds=60,
    )
    bind_result = manager.process_work_message(
        message=WorkMessage(job.job_id, "bind_inputs", job.version, bind.dedupe_key),
        checkpoint=bind,
        owner="worker",
    )
    store.complete_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=bind.dedupe_key,
        owner="worker",
        output_artifact_ids=bind_result["output_artifact_ids"],
        input_fingerprint=plan[0]["expected_input_fingerprint"],
        output_fingerprint="d" * 64,
        contract_version="video-edit-v2",
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    changed = dict(manifest)
    changed["routes"] = {"tail": "keep_source_tail_card"}
    store.cas_transition(
        job_id=job.job_id,
        expected_version=current.version,
        command="change_v2_manifest_before_hydrate",
        updates={"slots_manifest": changed},
        ttl_seconds=3600,
    )
    current = store.get_job(job.job_id)
    assert current is not None
    context = EphemeralStageContext(
        job_id=job.job_id,
        stage="probe_source",
        snapshot=current,
        job_store=store,
        temporary_store=_temporary,
        work_dir=Path("."),
        materializer=manager.materializer,
    )

    manager._hydrate_stage_outputs(context, v2_plan=build_stage_plan(changed))

    assert "bind_inputs" not in context.stage_outputs


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
    manager.materializer = SimpleNamespace(
        materialize=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("small stage outputs must hydrate from their verified Redis inline cache")
        )
    )
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


def test_driver_enqueues_app_store_evidence_in_parallel_with_source_probe() -> None:
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="ephemeral-runtime-dag")
    job = store.create_job(
        slots_manifest={
            "slots": {
                "source_video": {"present": True},
                "app_store_url": {"present": True},
            },
            "routes": {"ui": "generated_ui_demo"},
        },
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    bind = store.claim_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key="bind-1",
        owner="worker",
        ttl_seconds=60,
    )
    store.complete_stage(
        job_id=job.job_id,
        stage="bind_inputs",
        dedupe_key=bind.dedupe_key,
        owner="worker",
        output_artifact_ids=(),
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(
        messages=[],
        enqueue=lambda **kwargs: queue.messages.append(WorkMessage(**kwargs)) or "1-0",
    )

    first = EphemeralStageDriver(store, queue).enqueue_next(job.job_id)

    assert first is not None and first.stage == "probe_source"
    assert [message.stage for message in queue.messages] == [
        "probe_source",
        "parse_app_store_evidence",
    ]


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


def test_stage_context_keeps_historical_v2_artifacts_visible_outside_qc_authority(tmp_path: Path):
    def descriptor(artifact_id: str, kind: str, sha256: str):
        return SimpleNamespace(
            to_dict=lambda: {
                "artifact_id": artifact_id,
                "kind": kind,
                "sha256": sha256,
                "metadata": {},
            }
        )

    old_assembled = descriptor("assembled-old", "assembled_video", "a" * 64)
    current_assembled = descriptor("assembled-current", "assembled_video", "b" * 64)
    old_timeline = descriptor("timeline-old", "hybrid_composite_manifest", "c" * 64)
    current_timeline = descriptor("timeline-current", "hybrid_composite_manifest", "d" * 64)
    rows = [old_assembled, current_assembled, old_timeline, current_timeline]
    splice_output = {
        "published_artifacts": [
            current_assembled.to_dict(),
            current_timeline.to_dict(),
        ]
    }
    v2_context = EphemeralStageContext(
        job_id="job",
        stage="assemble_audio",
        snapshot=SimpleNamespace(slots_manifest={"extensions": {"edit_contract": "video-edit-v2"}}),
        job_store=SimpleNamespace(list_artifacts=lambda _job_id: rows),
        temporary_store=SimpleNamespace(),
        work_dir=tmp_path,
        stage_outputs={"splice_timeline": splice_output},
    )
    non_v2_context = EphemeralStageContext(
        job_id="job",
        stage="assemble_audio",
        snapshot=SimpleNamespace(slots_manifest={"extensions": {}}),
        job_store=SimpleNamespace(list_artifacts=lambda _job_id: rows),
        temporary_store=SimpleNamespace(),
        work_dir=tmp_path,
        stage_outputs={"splice_timeline": splice_output},
    )

    expected = {"assembled-old", "assembled-current", "timeline-old", "timeline-current"}
    assert {item["artifact_id"] for item in v2_context.artifacts} == expected
    assert {item["artifact_id"] for item in non_v2_context.artifacts} == expected


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


def test_language_only_replacement_goes_through_seedance_edit_without_tts_or_lip_sync() -> None:
    plan = build_stage_plan(
        {
            "slots": {"source_video": {"present": True}},
            "routes": {},
            "output_language": "ja",
            "admission": {"language_only": True},
        },
    )
    names = [stage["name"] for stage in plan]
    # Language-only now flows through the standard Seedance edit path:
    # Seedance 2.0 rewrites spoken lines into the target language directly,
    # so no separate TTS + non-song lip-sync stages are scheduled.
    assert "build_script" in names
    assert "compile_seedance20_prompt" in names
    assert "submit_provider_video" in names
    assert "run_tts" not in names
    assert "run_final_lip_sync" not in names


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
