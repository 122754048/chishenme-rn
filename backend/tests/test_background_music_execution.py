from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2] / "usfr-server"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from app.background_music_execution import (  # noqa: E402
    DeploymentBackgroundMusicExecutionAdapter,
    BackgroundMusicStageDriver,
    BackgroundMusicStagePort,
    build_background_music_stage_plan,
)


class _Checkpoint:
    def __init__(self, status):
        self.status = status
        self.owner = None


class _Snapshot:
    def __init__(self):
        self.slots_manifest = {
            "admission": {"language_only": False},
            "extensions": {"background_music": {"sha256": "a" * 64}},
        }
        self.review_route = None
        self.version = 7
        self.approved_script_sha256 = None
        self.approved_storyboard_sha256 = None


class _JobStore:
    def __init__(self):
        self.snapshot = _Snapshot()
        self.checkpoints = {}

    def get_job(self, job_id):
        assert job_id == "music-job"
        return self.snapshot

    def get_stage_checkpoint(self, job_id, stage):
        assert job_id == "music-job"
        return self.checkpoints.get(stage)


class _Queue:
    def __init__(self):
        self.messages = []

    def enqueue(self, **message):
        self.messages.append(message)


@dataclass(frozen=True)
class _PortSnapshot:
    slots_manifest: dict[str, object]


@dataclass(frozen=True)
class _PortContext:
    snapshot: _PortSnapshot

    def materialize_slot(self, slot_id):
        return self.snapshot.slots_manifest["slots"][slot_id]["metadata"][0]


@dataclass(frozen=True)
class _ArtifactPortContext:
    snapshot: _PortSnapshot
    artifact_path: Path | None = None
    artifact_ref: dict[str, object] | None = None
    published: dict[str, bytes] = field(default_factory=dict)

    def materialize_slot(self, slot_id):
        return self.snapshot.slots_manifest["slots"][slot_id]["metadata"][0]

    def publish_bytes(self, *, kind, data, content_type, expected_sha256):
        assert kind == "music_timeline_contract"
        assert content_type == "application/json"
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        artifact_id = f"{kind}-{expected_sha256[:12]}"
        self.published[artifact_id] = data
        return {
            "artifact_id": artifact_id,
            "kind": kind,
            "sha256": expected_sha256,
        }

    @property
    def artifacts(self):
        return () if self.artifact_ref is None else (self.artifact_ref,)

    @contextmanager
    def materialize_artifact(self, kind, *, sha256=None, artifact_id=None):
        assert self.artifact_ref is not None
        assert kind == self.artifact_ref["kind"]
        assert sha256 == self.artifact_ref["sha256"]
        assert artifact_id == self.artifact_ref["artifact_id"]
        assert self.artifact_path is not None
        yield SimpleNamespace(path=self.artifact_path)


class _Port:
    def __init__(self, name):
        self.name = name

    def run(self, *, context, input_artifacts):
        del context, input_artifacts
        return {"port": self.name}


class _MusicPort:
    def background_music_capabilities(self):
        return {
            "source_music_timeline",
            "audio_asset_registration",
            "seedance_audio_reference",
            "exact_fragment_mix",
            "singing_qa",
        }

    def run(self, *, context, input_artifacts):
        del input_artifacts
        return {"port": "music", "audio": context.materialize_slot("background_music")}


class _AuditedMusicPort:
    def __init__(self, payload):
        self.payload = payload

    def run(self, *, context, input_artifacts):
        del context, input_artifacts
        return {
            "background_music_evidence": {
                "audio_asset_receipt": {
                    "asset_type": "Audio",
                    "asset_uri": "asset://asset-song",
                    "uploaded_audio_sha256": "b" * 64,
                    "status": "active",
                },
                "provider_payload": self.payload,
            }
        }


class _TimelineMusicPort:
    def __init__(self, contract):
        self.contract = contract

    def run(self, *, context, input_artifacts):
        del context, input_artifacts
        return {"background_music_evidence": {"music_timeline_contract": self.contract}}


class _MixMusicPort:
    def __init__(self, evidence):
        self.evidence = evidence

    def run(self, *, context, input_artifacts):
        del context, input_artifacts
        return {"background_music_evidence": self.evidence}


class _QcMusicPort(_MixMusicPort):
    pass


def test_background_music_stage_driver_runs_the_existing_generation_chain_and_preserves_approvals():
    store = _JobStore()
    queue = _Queue()
    driver = BackgroundMusicStageDriver(store, queue)

    assert driver.enqueue_next("music-job").stage == "bind_inputs"
    for stage in ("bind_inputs", "probe_source", "analyze_dynamics", "route_regions"):
        store.checkpoints[stage] = _Checkpoint("SUCCEEDED")

    assert driver.enqueue_next("music-job").stage == "build_script"
    store.checkpoints["build_script"] = _Checkpoint("SUCCEEDED")
    assert driver.enqueue_next("music-job") is None

    store.snapshot.approved_script_sha256 = "b" * 64
    assert driver.enqueue_next("music-job").stage == "generate_storyboards"
    store.checkpoints["generate_storyboards"] = _Checkpoint("SUCCEEDED")
    assert driver.enqueue_next("music-job") is None

    store.snapshot.approved_storyboard_sha256 = "c" * 64
    expected = (
        "compile_seedance20_prompt",
        "audit_seedance_request",
        "submit_provider_video",
        "wait_provider_video",
        "splice_timeline",
        "run_qc",
    )
    for stage in expected:
        assert driver.enqueue_next("music-job").stage == stage
        store.checkpoints[stage] = _Checkpoint("SUCCEEDED")

    assert [message["stage"] for message in queue.messages] == [
        "bind_inputs",
        "build_script",
        "generate_storyboards",
        *expected,
    ]


def test_background_music_stage_plan_keeps_the_active_high_fidelity_internal_stage_contracts():
    plan = build_background_music_stage_plan(
        {
            "admission": {"language_only": False},
            "extensions": {
                "background_music": {"sha256": "a" * 64},
                "high_fidelity_profile": {"profile": "high_fidelity_hybrid_v1"},
            },
            "routes": {
                "character": "source_preserve",
                "product": "source_preserve",
                "ui": "source_ui_keep",
            },
        },
        review_route=None,
    )
    by_name = {item["name"]: item for item in plan}

    assert "seedance_invocation_a" in by_name["build_script"]["internal_steps"]
    assert "seedance_invocation_b" in by_name["compile_seedance20_prompt"]["internal_steps"]
    assert "hybrid_compositor" in by_name["splice_timeline"]["internal_steps"]
    assert "high_fidelity_qc_extension" in by_name["run_qc"]["internal_steps"]


def test_background_music_stage_port_exposes_only_a_worker_scoped_materializable_audio_descriptor_to_music_handlers():
    background_music = {
        "object_key": "uploads/batch-scope/song.mp3",
        "sha256": "b" * 64,
        "size_bytes": 128,
        "content_type": "audio/mpeg",
        "duration_seconds": 30.0,
        "status": "completed",
    }
    context = _PortContext(
        _PortSnapshot(
            {
                "slots": {},
                "extensions": {"background_music": background_music},
            }
        )
    )
    port = BackgroundMusicStagePort(delegate=_Port("canonical"), music_delegate=_MusicPort())

    result = port.run(context=context, input_artifacts=[])

    assert result == {
        "port": "music",
        "audio": {
            **background_music,
            "store_verified": True,
        },
    }
    assert "background_music" not in context.snapshot.slots_manifest["slots"]


def test_background_music_provider_audit_requires_the_uploaded_audio_asset_and_exactly_one_audio1_content_item():
    context = _PortContext(
        _PortSnapshot(
            {
                "slots": {},
                "extensions": {
                    "background_music": {
                        "object_key": "uploads/batch-scope/song.mp3",
                        "sha256": "b" * 64,
                        "size_bytes": 128,
                        "content_type": "audio/mpeg",
                        "duration_seconds": 30.0,
                        "status": "completed",
                    }
                },
            }
        )
    )
    valid_payload = {
        "model": "seedance-2.0",
        "content": [
            {"type": "text", "text": "Use @Audio1 for the uploaded song."},
            {
                "type": "audio_url",
                "role": "reference_audio",
                "audio_url": {"url": "asset://asset-song"},
            },
        ],
    }
    port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(valid_payload),
    )

    assert port.run(context=context, input_artifacts=[])["background_music_evidence"]["provider_payload"] == valid_payload

    invalid_payload = {**valid_payload, "reference_audios": ["asset://asset-song"]}
    invalid_port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(invalid_payload),
    )
    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        invalid_port.run(context=context, input_artifacts=[])


def test_background_music_dynamics_requires_frame_exact_timeline_windows_with_continuous_uploaded_audio_ranges():
    context = _PortContext(
        _PortSnapshot(
            {
                "slots": {},
                "extensions": {
                    "background_music": {
                        "object_key": "uploads/batch-scope/song.mp3",
                        "sha256": "b" * 64,
                        "size_bytes": 128,
                        "content_type": "audio/mpeg",
                        "duration_seconds": 30.0,
                        "status": "completed",
                    }
                },
            }
        )
    )
    contract = {
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 1000,
            },
            {
                "source_start_frame": 60,
                "source_end_frame": 90,
                "output_start_frame": 60,
                "output_end_frame": 90,
                "uploaded_start_ms": 1000,
                "uploaded_end_ms": 2000,
            },
        ],
        "visible_singer_regions": [],
    }
    port = BackgroundMusicStagePort(
        stage="analyze_dynamics",
        delegate=_Port("canonical"),
        music_delegate=_TimelineMusicPort(contract),
    )

    assert port.run(context=context, input_artifacts=[])["background_music_evidence"]["music_timeline_contract"] == contract

    invalid = {
        **contract,
        "windows": [{**contract["windows"][0], "output_end_frame": 31}],
    }
    invalid_port = BackgroundMusicStagePort(
        stage="analyze_dynamics",
        delegate=_Port("canonical"),
        music_delegate=_TimelineMusicPort(invalid),
    )
    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_TIMELINE_MISMATCH"):
        invalid_port.run(context=context, input_artifacts=[])


def test_background_music_dynamics_publishes_the_validated_timeline_as_an_immutable_artifact(tmp_path):
    background_music = {
        "object_key": "uploads/batch-scope/song.mp3",
        "sha256": "b" * 64,
        "size_bytes": 128,
        "content_type": "audio/mpeg",
        "duration_seconds": 30.0,
        "status": "completed",
    }
    contract = {
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 1000,
            }
        ],
        "visible_singer_regions": [],
    }
    context = _ArtifactPortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": background_music}}),
        artifact_path=tmp_path / "unused.json",
    )
    port = BackgroundMusicStagePort(
        stage="analyze_dynamics",
        delegate=_Port("canonical"),
        music_delegate=_TimelineMusicPort(contract),
    )

    result = port.run(context=context, input_artifacts=[])

    reference = result["background_music_evidence"]["music_timeline_contract_artifact"]
    assert reference["kind"] == "music_timeline_contract"
    assert json.loads(context.published[reference["artifact_id"]]) == contract


def test_background_music_splice_requires_exact_uploaded_fragments_and_rejects_audio_transforms():
    background_music = {
        "object_key": "uploads/batch-scope/song.mp3",
        "sha256": "b" * 64,
        "size_bytes": 128,
        "content_type": "audio/mpeg",
        "duration_seconds": 30.0,
        "status": "completed",
    }
    context = _PortContext(_PortSnapshot({"slots": {}, "extensions": {"background_music": background_music}}))
    contract = {
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 1000,
            }
        ],
        "visible_singer_regions": [],
    }
    receipt = {
        "passed": True,
        "uploaded_audio_sha256": "b" * 64,
        "final_audio_sha256": "c" * 64,
        "window_receipts": [
            {
                **contract["windows"][0],
                "fragment_sha256": "d" * 64,
                "looped": False,
                "time_stretched": False,
                "pitch_shifted": False,
                "generated_substitute": False,
            }
        ],
    }
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort({"music_timeline_contract": contract, "mix_receipt": receipt}),
    )

    assert port.run(context=context, input_artifacts=[])["background_music_evidence"]["mix_receipt"] == receipt

    transformed = {
        **receipt,
        "window_receipts": [{**receipt["window_receipts"][0], "looped": True}],
    }
    invalid_port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort({"music_timeline_contract": contract, "mix_receipt": transformed}),
    )
    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_TRANSFORM_FORBIDDEN"):
        invalid_port.run(context=context, input_artifacts=[])


def test_background_music_splice_rejects_a_contract_that_differs_from_the_materialized_frozen_artifact(tmp_path):
    background_music = {
        "object_key": "uploads/batch-scope/song.mp3",
        "sha256": "b" * 64,
        "size_bytes": 128,
        "content_type": "audio/mpeg",
        "duration_seconds": 30.0,
        "status": "completed",
    }
    frozen_contract = {
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 1000,
            }
        ],
        "visible_singer_regions": [],
    }
    frozen_bytes = json.dumps(frozen_contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    frozen_sha256 = hashlib.sha256(frozen_bytes).hexdigest()
    artifact_path = tmp_path / "music_timeline_contract.json"
    artifact_path.write_bytes(frozen_bytes)
    artifact_ref = {
        "artifact_id": "music-contract-1",
        "kind": "music_timeline_contract",
        "sha256": frozen_sha256,
    }
    altered_contract = {
        **frozen_contract,
        "windows": [{**frozen_contract["windows"][0], "uploaded_start_ms": 1000, "uploaded_end_ms": 2000}],
    }
    receipt = {
        "passed": True,
        "uploaded_audio_sha256": "b" * 64,
        "final_audio_sha256": "c" * 64,
        "window_receipts": [
            {
                **altered_contract["windows"][0],
                "fragment_sha256": "d" * 64,
                "looped": False,
                "time_stretched": False,
                "pitch_shifted": False,
                "generated_substitute": False,
            }
        ],
    }
    context = _ArtifactPortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": background_music}}),
        artifact_path=artifact_path,
        artifact_ref=artifact_ref,
    )
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": altered_contract,
                "music_timeline_contract_artifact": artifact_ref,
                "mix_receipt": receipt,
            }
        ),
    )

    with pytest.raises(ValueError, match="MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH"):
        port.run(context=context, input_artifacts=[])


def test_background_music_qc_requires_singing_alignment_and_lip_sync_or_an_explicit_no_visible_singer_skip():
    background_music = {
        "object_key": "uploads/batch-scope/song.mp3",
        "sha256": "b" * 64,
        "size_bytes": 128,
        "content_type": "audio/mpeg",
        "duration_seconds": 30.0,
        "status": "completed",
    }
    context = _PortContext(_PortSnapshot({"slots": {}, "extensions": {"background_music": background_music}}))
    base_contract = {
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 1000,
            }
        ],
        "visible_singer_regions": [],
    }
    receipt = {
        "passed": True,
        "uploaded_audio_sha256": "b" * 64,
        "final_audio_sha256": "c" * 64,
        "window_receipts": [
            {
                **base_contract["windows"][0],
                "fragment_sha256": "d" * 64,
                "looped": False,
                "time_stretched": False,
                "pitch_shifted": False,
                "generated_substitute": False,
            }
        ],
    }
    skipped = {"status": "skipped", "reason": "no_visible_singing_person", "regions": []}
    port = BackgroundMusicStagePort(
        stage="run_qc",
        delegate=_Port("canonical"),
        music_delegate=_QcMusicPort(
            {
                "music_timeline_contract": base_contract,
                "mix_receipt": receipt,
                "singing_qa": skipped,
            }
        ),
    )

    assert port.run(context=context, input_artifacts=[])["background_music_evidence"]["singing_qa"] == skipped

    visible_contract = {**base_contract, "visible_singer_regions": [{"region_id": "s1", "visible": True}]}
    missing_singing_qa = BackgroundMusicStagePort(
        stage="run_qc",
        delegate=_Port("canonical"),
        music_delegate=_QcMusicPort(
            {
                "music_timeline_contract": visible_contract,
                "mix_receipt": receipt,
                "singing_qa": skipped,
            }
        ),
    )
    with pytest.raises(ValueError, match="SINGING_ALIGNMENT_REQUIRED"):
        missing_singing_qa.run(context=context, input_artifacts=[])


def test_deployment_music_adapter_wraps_only_existing_stage_ports_and_requires_real_music_capability_declarations():
    stages = (
        "analyze_dynamics",
        "build_script",
        "generate_storyboards",
        "compile_seedance20_prompt",
        "audit_seedance_request",
        "submit_provider_video",
        "wait_provider_video",
        "splice_timeline",
        "run_qc",
    )
    worker_manager = type(
        "WorkerManager",
        (),
        {"stage_ports": {stage: _Port(f"canonical-{stage}") for stage in stages}},
    )()
    adapter = DeploymentBackgroundMusicExecutionAdapter(
        music_stage_ports={stage: _MusicPort() for stage in stages}
    )
    canonical_driver = type("CanonicalDriver", (), {"enqueue_next": lambda self, job_id: job_id})()

    driver = adapter.install(
        job_store=object(),
        work_queue=object(),
        worker_manager=worker_manager,
        stage_driver=canonical_driver,
    )
    adapter.validate_startup()

    assert isinstance(driver, BackgroundMusicStageDriver)
    assert all(isinstance(worker_manager.stage_ports[stage], BackgroundMusicStagePort) for stage in stages)
