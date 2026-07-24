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
import app.background_music_execution as background_music_execution  # noqa: E402


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


@dataclass(frozen=True)
class _MultiArtifactPortContext:
    snapshot: _PortSnapshot
    artifact_entries: tuple[tuple[dict[str, object], Path], ...]

    @property
    def artifacts(self):
        return tuple(reference for reference, _ in self.artifact_entries)

    @contextmanager
    def materialize_artifact(self, kind, *, sha256=None, artifact_id=None):
        reference = next(
            (
                item
                for item in self.artifacts
                if item["artifact_id"] == artifact_id and item["kind"] == kind and item["sha256"] == sha256
            ),
            None,
        )
        assert reference is not None
        path = next(path for item, path in self.artifact_entries if item["artifact_id"] == artifact_id)
        yield SimpleNamespace(path=path)


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
    def __init__(self, payload, *, execution_contract=None):
        self.payload = payload
        self.execution_contract = execution_contract

    def run(self, *, context, input_artifacts):
        del context, input_artifacts
        evidence = {
            "audio_asset_receipt": {
                "asset_type": "Audio",
                "asset_uri": "asset://asset-song",
                "uploaded_audio_sha256": "b" * 64,
                "status": "active",
            },
            "provider_payload": self.payload,
        }
        if self.execution_contract is not None:
            evidence["music_execution_contract"] = self.execution_contract
        return {"background_music_evidence": evidence}


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


def _uploaded_music() -> dict[str, object]:
    return {
        "object_key": "uploads/batch-scope/song.mp3",
        "sha256": "b" * 64,
        "size_bytes": 128,
        "content_type": "audio/mpeg",
        "duration_seconds": 30.0,
        "status": "completed",
    }


def _music_timeline() -> dict[str, object]:
    return {
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 1000,
                "source_start_ms": 0,
                "source_end_ms": 1000,
                "source_entry": "hard_cut",
                "source_exit": "dissolve",
                "fade_in_ms": 0,
                "fade_out_ms": 120,
                "silence_before": False,
                "silence_after": True,
                "transition": "cross_dissolve",
            }
        ],
        "visible_singer_regions": [],
    }


def _verified_performance_line_contract() -> dict[str, object]:
    return {
        "contract": "performance-line/v1",
        "cuts": [
            {
                "line_id": "L01",
                "cut_id": "C01",
                "content_type": "sung",
                "speaker_assignment": {
                    "status": "CONFIRMED",
                    "speaker_id": "CHARACTER_A",
                    "evidence_sha256": "a" * 64,
                },
                "source_time": {"start_ms": 0, "end_ms": 1000},
                "segment_time": {"start_ms": 0, "end_ms": 1000},
                "performance_mode": "singing",
                "lyric_status": "verified",
                "exact_sung_text": "Hold on",
                "beat_anchors_ms": [240],
            }
        ],
    }


def _audio_asset_receipt() -> dict[str, object]:
    return {
        "asset_type": "Audio",
        "asset_uri": "asset://asset-song",
        "status": "active",
        "uploaded_audio_sha256": "b" * 64,
    }


def _execution_contract_for(
    music_timeline_contract: dict[str, object],
    *,
    intent: str = "background_music_replacement",
) -> dict[str, object]:
    return background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=music_timeline_contract,
        audio_asset_receipt=_audio_asset_receipt(),
        user_confirmed_intent=intent,
        performance_line_contract=_verified_performance_line_contract() if intent == "verified_singing" else None,
    )


def _music_audit_context(tmp_path: Path, *, timeline: dict[str, object] | None = None) -> _ArtifactPortContext:
    contract = timeline or _music_timeline()
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path = tmp_path / "music_timeline_contract.json"
    path.write_bytes(encoded)
    return _ArtifactPortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": _uploaded_music()}}),
        artifact_path=path,
        artifact_ref={
            "artifact_id": "music-contract",
            "kind": "music_timeline_contract",
            "sha256": hashlib.sha256(encoded).hexdigest(),
        },
    )


def _final_mix_receipt(*, execution_contract: dict[str, object]) -> dict[str, object]:
    window = execution_contract["source_music_windows"][0]
    return {
        "passed": True,
        "mode": execution_contract["mode"],
        "uploaded_audio_sha256": "b" * 64,
        "final_audio_sha256": "c" * 64,
        "final_video_sha256": "d" * 64,
        "forbidden_operations": ["loop", "atempo", "stretch", "pitch_shift", "silence_padding"],
        "window_receipts": [
            {
                **window,
                "fragment_sha256": "e" * 64,
                "uploaded_fragment_sha256": "e" * 64,
                "final_audio_fragment_sha256": "e" * 64,
                "looped": False,
                "atempo_applied": False,
                "speed_changed": False,
                "time_stretched": False,
                "pitch_shifted": False,
                "silence_padded": False,
                "generated_substitute": False,
            }
        ],
    }


def test_uploaded_song_is_the_final_audio_authority_without_time_or_pitch_transform():
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        user_confirmed_intent="verified_singing",
        performance_line_contract=_verified_performance_line_contract(),
    )

    receipt = background_music_execution.execute_background_music(
        execution_contract=execution,
        final_mix_receipt=_final_mix_receipt(execution_contract=execution),
    )

    assert receipt["forbidden_operations"] == ["loop", "atempo", "stretch", "pitch_shift", "silence_padding"]
    assert receipt["uploaded_audio_sha256"] == "b" * 64
    assert receipt["final_video_sha256"] == "d" * 64
    assert receipt["source_music_windows"] == _music_timeline()["windows"]
    text = execution["provider_payload"]["content"][0]["text"]
    assert "@Audio1" in text
    assert "Hold on" in text
    assert execution["performance_line_contract_sha256"] == hashlib.sha256(
        json.dumps(_verified_performance_line_contract(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_background_music_execution_rejects_a_final_segment_sha_that_does_not_match_the_uploaded_segment():
    execution = _execution_contract_for(_music_timeline())
    receipt = _final_mix_receipt(execution_contract=execution)
    receipt["window_receipts"][0]["final_audio_fragment_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED"):
        background_music_execution.execute_background_music(
            execution_contract=execution,
            final_mix_receipt=receipt,
        )


def test_background_music_execution_rejects_any_atempo_or_speed_change():
    execution = _execution_contract_for(_music_timeline())
    receipt = _final_mix_receipt(execution_contract=execution)
    receipt["window_receipts"][0]["speed_changed"] = True

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_TRANSFORM_FORBIDDEN"):
        background_music_execution.execute_background_music(
            execution_contract=execution,
            final_mix_receipt=receipt,
        )


def test_verified_singing_fails_closed_when_a_line_or_beat_falls_outside_its_frozen_music_window():
    line_outside_window = _verified_performance_line_contract()
    line_outside_window["cuts"][0]["source_time"] = {"start_ms": 200, "end_ms": 1200}
    with pytest.raises(ValueError, match="VERIFIED_SINGING_WINDOW_REQUIRED"):
        background_music_execution.compile_background_music_execution_contract(
            uploaded_audio=_uploaded_music(),
            music_timeline_contract=_music_timeline(),
            audio_asset_receipt=_audio_asset_receipt(),
            user_confirmed_intent="verified_singing",
            performance_line_contract=line_outside_window,
        )

    beat_outside_line = _verified_performance_line_contract()
    beat_outside_line["cuts"][0]["beat_anchors_ms"] = [1_000]
    with pytest.raises(ValueError, match="VERIFIED_SINGING_EVIDENCE_REQUIRED"):
        background_music_execution.compile_background_music_execution_contract(
            uploaded_audio=_uploaded_music(),
            music_timeline_contract=_music_timeline(),
            audio_asset_receipt=_audio_asset_receipt(),
            user_confirmed_intent="verified_singing",
            performance_line_contract=beat_outside_line,
        )


def test_background_music_mode_has_explicit_no_lyric_lip_sync_and_singing_fails_closed_without_verified_evidence():
    with pytest.raises(ValueError, match="VERIFIED_SINGING_EVIDENCE_REQUIRED"):
        background_music_execution.compile_background_music_execution_contract(
            uploaded_audio=_uploaded_music(),
            music_timeline_contract=_music_timeline(),
            audio_asset_receipt=_audio_asset_receipt(),
            user_confirmed_intent="verified_singing",
            performance_line_contract=None,
        )

    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        user_confirmed_intent="background_music_replacement",
        performance_line_contract=None,
    )

    assert execution["mode"] == "background_music_replacement"
    assert execution["lyric_lip_sync_policy"] == "No lyric lip-sync"
    assert "No lyric lip-sync" in execution["provider_payload"]["content"][0]["text"]


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


def test_background_music_provider_audit_requires_the_uploaded_audio_asset_and_exactly_one_audio1_content_item(tmp_path):
    context = _music_audit_context(tmp_path)
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        user_confirmed_intent="background_music_replacement",
        performance_line_contract=None,
    )
    valid_payload = execution["provider_payload"]
    port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(valid_payload, execution_contract=execution),
    )

    assert port.run(context=context, input_artifacts=[])["background_music_evidence"]["provider_payload"] == valid_payload

    invalid_payload = {**valid_payload, "reference_audios": ["asset://asset-song"]}
    invalid_port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(invalid_payload, execution_contract=execution),
    )
    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        invalid_port.run(context=context, input_artifacts=[])


def test_background_music_provider_audit_rejects_a_payload_that_differs_from_the_frozen_execution_contract():
    context = _PortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": _uploaded_music()}})
    )
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        user_confirmed_intent="verified_singing",
        performance_line_contract=_verified_performance_line_contract(),
    )
    altered_payload = {
        **execution["provider_payload"],
        "content": [
            {"type": "text", "text": "Use @Audio1 and invent a new lyric."},
            execution["provider_payload"]["content"][1],
        ],
    }
    port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(altered_payload, execution_contract=execution),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        port.run(context=context, input_artifacts=[])


def test_background_music_provider_audit_revalidates_the_mode_contract_instead_of_trusting_delegate_text(tmp_path):
    context = _music_audit_context(tmp_path)
    execution = _execution_contract_for(_music_timeline())
    unsafe_payload = {
        **execution["provider_payload"],
        "content": [
            {"type": "text", "text": "Use @Audio1 and make the performer lyric lip-sync every word."},
            execution["provider_payload"]["content"][1],
        ],
    }
    forged_execution = {**execution, "provider_payload": unsafe_payload}
    port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(unsafe_payload, execution_contract=forged_execution),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        port.run(context=context, input_artifacts=[])


def test_background_music_provider_audit_rejects_a_self_consistent_forged_singing_contract_without_matching_frozen_artifacts(tmp_path):
    music_timeline = _music_timeline()
    confirmed_performance = _verified_performance_line_contract()
    forged_performance = _verified_performance_line_contract()
    forged_performance["cuts"][0]["exact_sung_text"] = "Invented lyric"
    music_bytes = json.dumps(music_timeline, sort_keys=True, separators=(",", ":")).encode("utf-8")
    performance_bytes = json.dumps(confirmed_performance, sort_keys=True, separators=(",", ":")).encode("utf-8")
    music_path = tmp_path / "music_timeline_contract.json"
    performance_path = tmp_path / "performance_line_contract.json"
    music_path.write_bytes(music_bytes)
    performance_path.write_bytes(performance_bytes)
    music_reference = {
        "artifact_id": "music-contract",
        "kind": "music_timeline_contract",
        "sha256": hashlib.sha256(music_bytes).hexdigest(),
    }
    performance_reference = {
        "artifact_id": "performance-contract",
        "kind": "performance_line_contract",
        "sha256": hashlib.sha256(performance_bytes).hexdigest(),
    }
    context = _MultiArtifactPortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": _uploaded_music()}}),
        artifact_entries=((music_reference, music_path), (performance_reference, performance_path)),
    )
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=music_timeline,
        audio_asset_receipt=_audio_asset_receipt(),
        user_confirmed_intent="verified_singing",
        performance_line_contract=forged_performance,
    )
    port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(execution["provider_payload"], execution_contract=execution),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        port.run(context=context, input_artifacts=[])


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
    execution = _execution_contract_for(contract)
    receipt = _final_mix_receipt(execution_contract=execution)
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {"music_timeline_contract": contract, "music_execution_contract": execution, "mix_receipt": receipt}
        ),
    )

    assert port.run(context=context, input_artifacts=[])["background_music_evidence"]["mix_receipt"] == receipt

    transformed = {
        **receipt,
        "window_receipts": [{**receipt["window_receipts"][0], "looped": True}],
    }
    invalid_port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {"music_timeline_contract": contract, "music_execution_contract": execution, "mix_receipt": transformed}
        ),
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
    execution = _execution_contract_for(altered_contract)
    receipt = _final_mix_receipt(execution_contract=execution)
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
                "music_execution_contract": execution,
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
                "source_start_ms": 0,
                "source_end_ms": 1000,
            }
        ],
        "visible_singer_regions": [],
    }
    execution = _execution_contract_for(base_contract)
    receipt = _final_mix_receipt(execution_contract=execution)
    skipped = {"status": "skipped", "reason": "no_lyric_lip_sync", "regions": []}
    port = BackgroundMusicStagePort(
        stage="run_qc",
        delegate=_Port("canonical"),
        music_delegate=_QcMusicPort(
            {
                "music_timeline_contract": base_contract,
                "music_execution_contract": execution,
                "mix_receipt": receipt,
                "singing_qa": skipped,
            }
        ),
    )

    assert port.run(context=context, input_artifacts=[])["background_music_evidence"]["singing_qa"] == skipped

    visible_contract = {**base_contract, "visible_singer_regions": [{"region_id": "s1", "visible": True}]}
    visible_execution = _execution_contract_for(visible_contract, intent="verified_singing")
    visible_receipt = _final_mix_receipt(execution_contract=visible_execution)
    missing_singing_qa = BackgroundMusicStagePort(
        stage="run_qc",
        delegate=_Port("canonical"),
        music_delegate=_QcMusicPort(
            {
                "music_timeline_contract": visible_contract,
                "music_execution_contract": visible_execution,
                "mix_receipt": visible_receipt,
                "singing_qa": skipped,
            }
        ),
    )
    with pytest.raises(ValueError, match="SINGING_ALIGNMENT_REQUIRED"):
        missing_singing_qa.run(context=context, input_artifacts=[])


def test_background_music_splice_fails_closed_without_the_frozen_execution_contract():
    contract = {
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 1000,
                "source_start_ms": 0,
                "source_end_ms": 1000,
            }
        ],
        "visible_singer_regions": [],
    }
    execution = _execution_contract_for(contract)
    context = _PortContext(_PortSnapshot({"slots": {}, "extensions": {"background_music": _uploaded_music()}}))
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {"music_timeline_contract": contract, "mix_receipt": _final_mix_receipt(execution_contract=execution)}
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_EXECUTION_CONTRACT_REQUIRED"):
        port.run(context=context, input_artifacts=[])


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
