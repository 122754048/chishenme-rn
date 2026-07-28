from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import wave

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
from server.job_models import ProviderAttempt  # noqa: E402


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
    published_paths: dict[str, tuple[dict[str, object], Path]] = field(default_factory=dict)
    job_id: str = "music-job"
    job_store: object = field(default_factory=lambda: _ProviderAttemptStore())

    def materialize_slot(self, slot_id):
        return self.snapshot.slots_manifest["slots"][slot_id]["metadata"][0]

    def publish_bytes(self, *, kind, data, content_type, expected_sha256):
        assert kind in {
            "music_timeline_contract",
            "background_music_audit_receipt",
            "background_music_execution_request",
            "background_music_provider_raw_response",
            "background_music_provider_submission",
            "background_music_provider_output",
        }
        assert content_type == "application/json"
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        artifact_id = f"{kind}-{expected_sha256[:12]}"
        self.published[artifact_id] = data
        reference = {
            "artifact_id": artifact_id,
            "kind": kind,
            "sha256": expected_sha256,
        }
        if self.artifact_path is not None:
            path = self.artifact_path.parent / f"{artifact_id}.json"
            path.write_bytes(data)
            self.published_paths[artifact_id] = (reference, path)
        return reference

    @property
    def artifacts(self):
        original = () if self.artifact_ref is None else (self.artifact_ref,)
        return original + tuple(reference for reference, _ in self.published_paths.values())

    @contextmanager
    def materialize_artifact(self, kind, *, sha256=None, artifact_id=None):
        if (
            self.artifact_ref is not None
            and kind == self.artifact_ref["kind"]
            and sha256 == self.artifact_ref["sha256"]
            and artifact_id == self.artifact_ref["artifact_id"]
        ):
            assert self.artifact_path is not None
            yield SimpleNamespace(path=self.artifact_path)
            return
        reference, path = self.published_paths[artifact_id]
        assert kind == reference["kind"]
        assert sha256 == reference["sha256"]
        yield SimpleNamespace(path=path)


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


@dataclass(frozen=True)
class _MediaPortContext:
    snapshot: _PortSnapshot
    uploaded_path: Path
    artifact_entries: tuple[tuple[dict[str, object], Path], ...]
    published_entries: dict[str, tuple[dict[str, object], Path]] = field(default_factory=dict)
    provider_lineage: dict[str, object] = field(default_factory=dict)
    job_id: str = "music-job"
    job_store: object = field(default_factory=lambda: _ProviderAttemptStore())

    @property
    def artifacts(self):
        return tuple(reference for reference, _ in self.artifact_entries) + tuple(
            reference for reference, _ in self.published_entries.values()
        )

    def publish_bytes(self, *, kind, data, content_type, expected_sha256):
        assert content_type in {"application/json", "video/mp4"}
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        artifact_id = f"{kind}-{expected_sha256[:12]}"
        suffix = ".mp4" if content_type == "video/mp4" else ".json"
        path = self.uploaded_path.parent / f"{artifact_id}{suffix}"
        path.write_bytes(data)
        reference = {"artifact_id": artifact_id, "kind": kind, "sha256": expected_sha256}
        self.published_entries[artifact_id] = (reference, path)
        return reference

    @contextmanager
    def materialize_slot(self, slot_id, *, index=0):
        assert slot_id == "background_music"
        assert index == 0
        yield SimpleNamespace(path=self.uploaded_path)

    @contextmanager
    def materialize_artifact(self, kind, *, sha256=None, artifact_id=None):
        entry = next(
            (
                (reference, path)
                for reference, path in self.artifact_entries + tuple(self.published_entries.values())
                if reference["kind"] == kind
                and reference["sha256"] == sha256
                and reference["artifact_id"] == artifact_id
            ),
            None,
        )
        assert entry is not None
        yield SimpleNamespace(path=entry[1])


class _ProviderAttemptStore:
    def __init__(self) -> None:
        self.snapshot = SimpleNamespace(version=1, expires_at_ms=9_999_999_999_999)
        self.attempts: list[ProviderAttempt] = []
        self.events: list[str] = []

    def get_job(self, job_id):
        assert job_id == "music-job"
        return self.snapshot

    def list_provider_attempts(self, job_id):
        assert job_id == "music-job"
        return tuple(self.attempts)

    def begin_provider_attempt(
        self, *, job_id, expected_version, operation, request_sha256, segment_id=None, segment_plan_sha256=None
    ):
        assert job_id == "music-job"
        assert expected_version == self.snapshot.version
        attempt = ProviderAttempt(
            attempt_id=f"attempt-{len(self.attempts) + 1}",
            operation=operation,
            request_sha256=request_sha256,
            status="SUBMITTING",
            segment_id=segment_id,
            segment_plan_sha256=segment_plan_sha256,
        )
        self.attempts.append(attempt)
        self.events.append("begin")
        self.snapshot.version += 1
        return attempt

    def update_provider_attempt(self, *, job_id, expected_version, attempt, ttl_seconds):
        assert job_id == "music-job"
        assert expected_version == self.snapshot.version
        assert ttl_seconds > 0
        index = next(index for index, current in enumerate(self.attempts) if current.attempt_id == attempt.attempt_id)
        self.attempts[index] = attempt
        self.events.append(attempt.status)
        self.snapshot.version += 1
        return self.snapshot


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
            "frozen_provider_submit",
            "provider_task_lineage_lookup",
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
                "provider": "runninghub",
                "runninghub_audio_url": "https://runninghub.example/openapi/song-clip.mp3",
                "uploaded_audio_sha256": "b" * 64,
                "duration_seconds": 2.0,
                "clip_kind": "seedance_segment",
                "seedance_segment": {"start_ms": 0, "end_ms": 2_000},
                "status": "completed",
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
        del input_artifacts
        _complete_music_timing(self.contract)
        return {"background_music_evidence": {"music_timeline_contract": self.contract}}


class _MixMusicPort:
    def __init__(self, evidence):
        self.evidence = evidence

    def run(self, *, context, input_artifacts):
        del input_artifacts
        execution = self.evidence.get("music_execution_contract") if isinstance(self.evidence, dict) else None
        if isinstance(execution, dict) and "music_execution_audit_binding" not in self.evidence:
            self.evidence["music_execution_audit_binding"] = {
                "execution_contract_sha256": execution["execution_contract_sha256"],
                "seedance_payload_sha256": execution["seedance_payload_sha256"],
            }
        return {"background_music_evidence": {**getattr(context, "provider_lineage", {}), **self.evidence}}


class _QcMusicPort(_MixMusicPort):
    pass


class _CopiedReceiptSubmitPort:
    def run(self, *, context, input_artifacts):
        del context, input_artifacts
        raise AssertionError("submit must use trusted frozen provider method")

    def submit_frozen_background_music(self, *, context, input_artifacts, execution_contract, provider_payload):
        del context
        request = next(item for item in input_artifacts if item.get("kind") == "background_music_execution_request")
        return {
            "background_music_evidence": {
                "music_execution_contract": execution_contract,
                "provider_payload": provider_payload,
                "music_execution_audit_receipt_artifact": next(
                    item for item in input_artifacts if item.get("kind") == "background_music_audit_receipt"
                ),
                "music_execution_audit_binding": background_music_execution._execution_binding(execution_contract),
                "provider_submission_receipt": request["request_binding"],
            }
        }


class _VerifiedProviderAdapter:
    def __init__(self, *, video_bytes: bytes | None = None):
        self.create_requests = []
        self.lookup_intents = []
        self.download_intents = []
        self.video_bytes = video_bytes

    def capability_identity(self):
        return {
            "capability": "provider_adapter",
            "implementation": "tests.VerifiedProviderAdapter",
            "version": "1.0.0",
            "sha256": "f" * 64,
        }

    def create_video(self, request):
        self.create_requests.append(request)
        return {"task_id": "provider-task-1", "status": "submitted"}

    def lookup(self, intent):
        self.lookup_intents.append(intent)
        return {
            "task_id": "provider-task-1",
            "status": "completed",
            "output": {"kind": "provider_video", "identity": "provider-output-1"},
        }

    def download(self, task_id, destination):
        self.download_intents.append(task_id)
        if self.video_bytes is None:
            raise ValueError("provider video bytes unavailable")
        Path(destination).write_bytes(self.video_bytes)
        return {
            "provider": "test-provider",
            "sha256": hashlib.sha256(self.video_bytes).hexdigest(),
            "size_bytes": len(self.video_bytes),
        }


class _WrongTaskProviderAdapter(_VerifiedProviderAdapter):
    def lookup(self, intent):
        self.lookup_intents.append(intent)
        return {"task_id": "another-task", "status": "completed"}


def _uploaded_music() -> dict[str, object]:
    return {
        "object_key": "uploads/batch-scope/song.mp3",
        "sha256": "b" * 64,
        "size_bytes": 128,
        "content_type": "audio/mpeg",
        "duration_seconds": 30.0,
        "status": "completed",
    }


def _complete_music_timing(contract: dict[str, object]) -> None:
    contract.setdefault("meaningful_silence_output_intervals", [])
    windows = contract.get("windows")
    if not isinstance(windows, list):
        return
    for window in windows:
        if not isinstance(window, dict):
            continue
        source_start = int(window.get("uploaded_start_ms") or 0)
        source_end = int(window.get("uploaded_end_ms") or 0)
        output_start = int(window.get("output_start_ms") or source_start)
        output_end = int(window.get("output_end_ms") or source_end)
        window.setdefault("output_start_ms", output_start)
        window.setdefault("output_end_ms", output_end)
        bounds = {
            "source_start_ms": source_start,
            "source_end_ms": source_end,
            "output_start_ms": output_start,
            "output_end_ms": output_end,
        }
        for field in ("source_entry", "source_exit", "fade_in", "fade_out", "silence_before", "silence_after", "transition"):
            window.setdefault(field, dict(bounds))
    contract.setdefault(
        "output_duration_ms",
        max((int(window["output_end_ms"]) for window in windows if isinstance(window, dict)), default=0),
    )
    if int(contract["output_duration_ms"]) < 2_000:
        prior_end = int(contract["output_duration_ms"])
        contract["meaningful_silence_output_intervals"] = [
            *contract["meaningful_silence_output_intervals"],
            {"output_start_ms": prior_end, "output_end_ms": 2_000},
        ]
        contract["output_duration_ms"] = 2_000


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
                "output_start_ms": 0,
                "output_end_ms": 1000,
                "source_entry": {"source_start_ms": 0, "source_end_ms": 0, "output_start_ms": 0, "output_end_ms": 0},
                "source_exit": {"source_start_ms": 1000, "source_end_ms": 1000, "output_start_ms": 1000, "output_end_ms": 1000},
                "fade_in": {"source_start_ms": 0, "source_end_ms": 0, "output_start_ms": 0, "output_end_ms": 0},
                "fade_out": {"source_start_ms": 880, "source_end_ms": 1000, "output_start_ms": 880, "output_end_ms": 1000},
                "silence_before": {"source_start_ms": 0, "source_end_ms": 0, "output_start_ms": 0, "output_end_ms": 0},
                "silence_after": {"source_start_ms": 1000, "source_end_ms": 1000, "output_start_ms": 1000, "output_end_ms": 1000},
                "transition": {"source_start_ms": 880, "source_end_ms": 1000, "output_start_ms": 880, "output_end_ms": 1000},
            }
        ],
        "visible_singer_regions": [],
        "meaningful_silence_output_intervals": [{"output_start_ms": 1000, "output_end_ms": 2000}],
        "output_duration_ms": 2000,
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
                "lip_sync": {
                    "face_visibility": "locked medium close-up, face fully visible",
                    "articulation": "clear syllable-by-syllable mouth articulation",
                    "end_state": "mouth closes at the line end",
                },
                "action": {
                    "start": "hand rests on the product",
                    "beat_action": "finger taps the product on the beat",
                    "end": "hand remains on the product",
                },
                "expression": {
                    "start": "calm",
                    "peak": "confident smile",
                    "end": "calm smile",
                },
                "emotion": "confident",
                "end_pose": "face forward with hand on the product",
                "criticality": "HIGH",
            }
        ],
    }


def _confirmed_sung_source_timeline(*, confidence: float = 0.95) -> dict[str, object]:
    return {
        "contract": "source-content-timeline/v1",
        "approved_seedance_visual_payload": _approved_visual_seedance_payload(),
        "audio_lines": [
            {
                "line_id": "source-song-line-01",
                "content_type": "sung",
                "start_ms": 0,
                "end_ms": 1000,
                "confidence": confidence,
                "speaker_assignment": {
                    "status": "CONFIRMED",
                    "speaker_id": "CHARACTER_A",
                    "visibility": "on_camera",
                    "confidence": confidence,
                    "evidence_sha256": "a" * 64,
                },
            }
        ],
    }


def _non_singing_source_timeline() -> dict[str, object]:
    return {
        "contract": "source-content-timeline/v1",
        "approved_seedance_visual_payload": _approved_visual_seedance_payload(),
        "audio_lines": [],
    }


def _approved_visual_seedance_payload() -> dict[str, object]:
    return {
        "prompt": "Keep the approved visual performance, camera, and product proof.",
        "resolution": "720p",
        "duration": "5",
        "imageUrls": ["https://runninghub.example/openapi/approved-storyboard.png"],
        "videoUrls": [],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": False,
        "conversionSlots": [],
        "returnLastFrame": False,
        "seed": -1,
    }


def test_background_music_payload_inherits_the_approved_visual_request_and_only_adds_audio() -> None:
    source_timeline = {
        **_non_singing_source_timeline(),
        "approved_seedance_visual_payload": _approved_visual_seedance_payload(),
    }
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        source_content_timeline=source_timeline,
    )

    payload = execution["provider_payload"]
    assert set(payload) == {
        "prompt", "resolution", "duration", "imageUrls", "videoUrls", "audioUrls",
        "generateAudio", "ratio", "realPersonMode", "conversionSlots", "returnLastFrame", "seed",
    }
    assert payload["imageUrls"] == ["https://runninghub.example/openapi/approved-storyboard.png"]
    assert payload["audioUrls"] == ["https://runninghub.example/openapi/song-clip.mp3"]
    assert payload["videoUrls"] == []
    assert "model" not in payload
    assert "@Audio1" in payload["prompt"]


def _audio_asset_receipt() -> dict[str, object]:
    return {
        "asset_type": "Audio",
        "provider": "runninghub",
        "runninghub_audio_url": "https://runninghub.example/openapi/song-clip.mp3",
        "duration_seconds": 2.0,
        "clip_kind": "seedance_segment",
        "seedance_segment": {"start_ms": 0, "end_ms": 2_000},
        "status": "completed",
        "uploaded_audio_sha256": "b" * 64,
    }


def _audio_asset_receipt_for_timeline(
    contract: dict[str, object],
    *,
    uploaded_audio_sha256: str = "b" * 64,
) -> dict[str, object]:
    starts = [
        item["output_start_ms"]
        for item in [*contract["windows"], *contract["meaningful_silence_output_intervals"]]
        if isinstance(item, dict)
    ]
    start_ms = min(starts)
    end_ms = int(contract["output_duration_ms"])
    return {
        **_audio_asset_receipt(),
        "uploaded_audio_sha256": uploaded_audio_sha256,
        "duration_seconds": (end_ms - start_ms) / 1_000,
        "seedance_segment": {"start_ms": start_ms, "end_ms": end_ms},
    }


def _execution_contract_for(
    music_timeline_contract: dict[str, object],
    *,
    intent: str = "background_music_replacement",
) -> dict[str, object]:
    _complete_music_timing(music_timeline_contract)
    return background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=music_timeline_contract,
        audio_asset_receipt=_audio_asset_receipt_for_timeline(music_timeline_contract),
        source_content_timeline=(
            _confirmed_sung_source_timeline()
            if intent == "verified_singing"
            else _non_singing_source_timeline()
        ),
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
                "pcm_fragment_sha256": "e" * 64,
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


def _pcm_wav_bytes(raw_pcm: bytes) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(48_000)
            wav.writeframes(raw_pcm)
        return buffer.getvalue()


def _materialized_music_case(
    tmp_path: Path,
    contract: dict[str, object],
    *,
    intent: str = "background_music_replacement",
    video_audio_bytes: bytes | None = None,
    extra_video_audio_bytes: bytes | None = None,
    video_audio_offset_seconds: float = 0.0,
    with_provider_lineage: bool = False,
) -> tuple[dict[str, object], dict[str, object], _MediaPortContext, dict[str, object], dict[str, object]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    _complete_music_timing(contract)
    music_pcm = b"\x01\x00\x01\x00" * 48_000
    uploaded_pcm = music_pcm * 2
    uploaded_bytes = _pcm_wav_bytes(uploaded_pcm)
    final_audio_bytes = _pcm_wav_bytes(music_pcm + b"\0" * len(music_pcm))
    uploaded = {
        **_uploaded_music(),
        "object_key": "uploads/batch-scope/song.wav",
        "content_type": "audio/wav",
        "sha256": hashlib.sha256(uploaded_bytes).hexdigest(),
        "size_bytes": len(uploaded_bytes),
    }
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=uploaded,
        music_timeline_contract=contract,
        audio_asset_receipt=_audio_asset_receipt_for_timeline(
            contract,
            uploaded_audio_sha256=uploaded["sha256"],
        ),
        source_content_timeline=(
            _confirmed_sung_source_timeline()
            if intent == "verified_singing"
            else _non_singing_source_timeline()
        ),
        performance_line_contract=_verified_performance_line_contract() if intent == "verified_singing" else None,
    )
    timeline_bytes = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timeline_reference = {
        "artifact_id": "music-timeline",
        "kind": "music_timeline_contract",
        "sha256": hashlib.sha256(timeline_bytes).hexdigest(),
    }
    audit_receipt = {
        "contract": "background_music_audit_receipt/v1",
        **background_music_execution._execution_binding(execution),
        "music_timeline_contract_sha256": timeline_reference["sha256"],
        "performance_line_contract_sha256": execution["performance_line_contract_sha256"],
    }
    audit_bytes = json.dumps(audit_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    audit_reference = {
        "artifact_id": "music-audit",
        "kind": "background_music_audit_receipt",
        "sha256": hashlib.sha256(audit_bytes).hexdigest(),
    }
    request_payload = {
        "contract": "background_music_execution_request/v1",
        "music_execution_contract": execution,
        "provider_payload": execution["provider_payload"],
        "audit_receipt_artifact": audit_reference,
        "request_binding": {
            **background_music_execution._execution_binding(execution),
            "provider_payload": execution["provider_payload"],
        },
    }
    request_bytes = json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request_reference = {
        "artifact_id": "music-request",
        "kind": "background_music_execution_request",
        "sha256": hashlib.sha256(request_bytes).hexdigest(),
    }
    performance_entry: tuple[dict[str, object], Path] | None = None
    if intent == "verified_singing":
        performance_bytes = json.dumps(
            execution["performance_line_contract"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        performance_reference = {
            "artifact_id": "performance-lines",
            "kind": "performance_line_contract",
            "sha256": hashlib.sha256(performance_bytes).hexdigest(),
        }
        performance_path = tmp_path / "performance-lines.json"
        performance_path.write_bytes(performance_bytes)
        performance_entry = (performance_reference, performance_path)
    uploaded_path = tmp_path / "uploaded.wav"
    timeline_path = tmp_path / "timeline.json"
    audit_path = tmp_path / "audit.json"
    request_path = tmp_path / "request.json"
    final_audio_path = tmp_path / "mix.wav"
    final_video_path = tmp_path / "final.mp4"
    uploaded_path.write_bytes(uploaded_bytes)
    timeline_path.write_bytes(timeline_bytes)
    audit_path.write_bytes(audit_bytes)
    request_path.write_bytes(request_bytes)
    final_audio_path.write_bytes(final_audio_bytes)
    video_audio_path = tmp_path / "video-audio.wav"
    video_audio_path.write_bytes(final_audio_bytes if video_audio_bytes is None else video_audio_bytes)
    extra_input: list[str] = []
    extra_mapping: list[str] = []
    extra_disposition: list[str] = []
    if extra_video_audio_bytes is not None:
        extra_audio_path = tmp_path / "extra-video-audio.wav"
        extra_audio_path.write_bytes(extra_video_audio_bytes)
        extra_input = ["-i", str(extra_audio_path)]
        extra_mapping = ["-map", "2:a:0"]
        extra_disposition = ["-disposition:a:0", "0", "-disposition:a:1", "default"]
    offset_args = ["-itsoffset", str(video_audio_offset_seconds)] if video_audio_offset_seconds else []
    generated = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:r=30:d=2",
            *offset_args,
            "-i",
            str(video_audio_path),
            *extra_input,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            *extra_mapping,
            "-c:v",
            "mpeg4",
            "-c:a",
            "pcm_s16le",
            *extra_disposition,
            "-shortest",
            "-f",
            "mov",
            str(final_video_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr.decode("utf-8", errors="replace")
    final_video_bytes = final_video_path.read_bytes()
    final_audio_reference = {
        "artifact_id": "final-audio",
        "kind": "audio_mix",
        "sha256": hashlib.sha256(final_audio_bytes).hexdigest(),
    }
    final_video_reference = {
        "artifact_id": "final-video",
        "kind": "final_video",
        "sha256": hashlib.sha256(final_video_bytes).hexdigest(),
    }
    context = _MediaPortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": uploaded}}),
        uploaded_path=uploaded_path,
        artifact_entries=((timeline_reference, timeline_path),)
        + ((performance_entry,) if performance_entry is not None else ())
        + (
            (audit_reference, audit_path),
            (request_reference, request_path),
            (final_audio_reference, final_audio_path),
            (final_video_reference, final_video_path),
        ),
    )
    pcm_fragment_sha = hashlib.sha256(music_pcm).hexdigest()
    receipt = {
        "passed": True,
        "mode": execution["mode"],
        "uploaded_audio_sha256": uploaded["sha256"],
        "final_audio_sha256": final_audio_reference["sha256"],
        "final_video_sha256": final_video_reference["sha256"],
        "final_audio_artifact": final_audio_reference,
        "final_video_artifact": final_video_reference,
        "forbidden_operations": list(background_music_execution.FORBIDDEN_MUSIC_OPERATIONS),
        "window_receipts": [
            {
                **execution["source_music_windows"][0],
                "fragment_sha256": pcm_fragment_sha,
                "uploaded_fragment_sha256": pcm_fragment_sha,
                "final_audio_fragment_sha256": pcm_fragment_sha,
                "pcm_fragment_sha256": pcm_fragment_sha,
                "uploaded_byte_offset": 0,
                "uploaded_byte_length": len(uploaded_bytes),
                "final_audio_byte_offset": 0,
                "final_audio_byte_length": len(final_audio_bytes),
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
    if with_provider_lineage:
        context.provider_lineage.update(_completed_provider_lineage(context=context, receipt=receipt))
    return execution, receipt, context, timeline_reference, audit_reference


def _completed_provider_lineage(*, context, receipt):
    final_video_reference = receipt["final_video_artifact"]
    with context.materialize_artifact(
        final_video_reference["kind"],
        artifact_id=final_video_reference["artifact_id"],
        sha256=final_video_reference["sha256"],
    ) as final_video:
        provider = _VerifiedProviderAdapter(video_bytes=final_video.path.read_bytes())
    submit = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )
    submit.run(context=context, input_artifacts=[])
    completed = BackgroundMusicStagePort(
        stage="wait_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    ).run(context=context, input_artifacts=[])["background_music_evidence"]
    output_reference = completed["provider_output_artifact"]
    task_id = completed["provider_submission_receipt"]["provider_task_id"]
    receipt.update(
        {
            "provider_output_artifact": output_reference,
            "final_video_provider_output_artifact": output_reference,
            "provider_task_id": task_id,
            "final_video_provider_task_id": task_id,
        }
    )
    return {
        "provider_submission_receipt": completed["provider_submission_receipt"],
        "provider_submission_artifact": completed["provider_submission_artifact"],
        "provider_output_artifact": output_reference,
    }


def _rewrite_published_json(context, reference, payload):
    _, path = context.published_entries.pop(reference["artifact_id"])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(encoded)
    rewritten = {**reference, "sha256": hashlib.sha256(encoded).hexdigest()}
    context.published_entries[rewritten["artifact_id"]] = (rewritten, path)
    return rewritten


def test_uploaded_song_is_the_final_audio_authority_without_time_or_pitch_transform():
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        source_content_timeline=_confirmed_sung_source_timeline(),
        performance_line_contract=_verified_performance_line_contract(),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED"):
        background_music_execution.execute_background_music(
            execution_contract=execution,
            final_mix_receipt=_final_mix_receipt(execution_contract=execution),
        )

    payload = execution["provider_payload"]
    assert payload["audioUrls"] == ["https://runninghub.example/openapi/song-clip.mp3"]
    assert "content" not in payload
    assert "asset://" not in json.dumps(payload)
    text = payload["prompt"]
    assert "@Audio1" in text
    assert '"Hold on"' in text
    assert "Line L01" in text
    assert "Cut C01" in text
    assert "CHARACTER_A" in text
    assert "global source time 0-1000 ms" in text
    assert "local segment time 0-1000 ms" in text
    assert "beat anchors 240 ms" in text
    assert "locked medium close-up, face fully visible" in text
    assert "finger taps the product on the beat" in text
    assert execution["performance_line_contract_sha256"] in text
    assert execution["performance_line_contract_sha256"] == hashlib.sha256(
        json.dumps(_verified_performance_line_contract(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_background_music_execution_requires_a_duration_bound_runninghub_upload_receipt():
    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        background_music_execution.compile_background_music_execution_contract(
            uploaded_audio=_uploaded_music(),
            music_timeline_contract=_music_timeline(),
            audio_asset_receipt={**_audio_asset_receipt(), "duration_seconds": 29.0},
            source_content_timeline=_non_singing_source_timeline(),
            performance_line_contract=None,
        )


@pytest.mark.parametrize("duration_seconds", [16.0, 30.0])
def test_background_music_execution_rejects_a_full_or_oversized_runninghub_audio_upload(
    duration_seconds: float,
):
    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        background_music_execution.compile_background_music_execution_contract(
            uploaded_audio={**_uploaded_music(), "duration_seconds": duration_seconds},
            music_timeline_contract=_music_timeline(),
            audio_asset_receipt={
                **_audio_asset_receipt(),
                "duration_seconds": duration_seconds,
                "clip_kind": "seedance_segment",
                "seedance_segment": {"start_ms": 0, "end_ms": int(duration_seconds * 1_000)},
            },
            source_content_timeline=_non_singing_source_timeline(),
            performance_line_contract=None,
        )


def test_background_music_execution_accepts_a_two_second_runninghub_segment_clip_for_a_longer_song():
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt={
            **_audio_asset_receipt(),
            "duration_seconds": 2.0,
            "clip_kind": "seedance_segment",
            "seedance_segment": {"start_ms": 0, "end_ms": 2_000},
        },
        source_content_timeline=_non_singing_source_timeline(),
        performance_line_contract=None,
    )

    assert execution["provider_payload"]["audioUrls"] == [
        "https://runninghub.example/openapi/song-clip.mp3"
    ]
    assert execution["uploaded_audio"]["duration_seconds"] == 30.0
    assert execution["audio_asset_receipt"]["duration_seconds"] == 2.0


def test_background_music_execution_rejects_a_self_consistent_clip_for_the_wrong_frozen_output_segment():
    timeline = _music_timeline()
    timeline["output_duration_ms"] = 2_000
    timeline["meaningful_silence_output_intervals"] = [{"output_start_ms": 1_000, "output_end_ms": 2_000}]

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        background_music_execution.compile_background_music_execution_contract(
            uploaded_audio=_uploaded_music(),
            music_timeline_contract=timeline,
            audio_asset_receipt={
                **_audio_asset_receipt(),
                "seedance_segment": {"start_ms": 2_000, "end_ms": 4_000},
            },
            source_content_timeline=_non_singing_source_timeline(),
            performance_line_contract=None,
        )


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


def test_background_music_execution_rejects_random_self_consistent_sha_claims_without_materialized_media_proof():
    uploaded_bytes = b"uploaded-song-bytes"
    final_audio_bytes = uploaded_bytes
    final_video_bytes = b"final-mp4-bytes"
    uploaded = {**_uploaded_music(), "sha256": hashlib.sha256(uploaded_bytes).hexdigest()}
    asset = {**_audio_asset_receipt(), "uploaded_audio_sha256": uploaded["sha256"]}
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=uploaded,
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=asset,
        source_content_timeline=_non_singing_source_timeline(),
        performance_line_contract=None,
    )
    receipt = _final_mix_receipt(execution_contract=execution)
    receipt.update(
        {
            "uploaded_audio_sha256": uploaded["sha256"],
            "final_audio_sha256": "c" * 64,
            "final_video_sha256": "d" * 64,
                "final_audio_artifact": {"kind": "audio_mix", "artifact_id": "audio", "sha256": "c" * 64},
                "final_video_artifact": {"kind": "final_video", "artifact_id": "video", "sha256": "d" * 64},
        }
    )
    receipt["window_receipts"][0].update(
        {
            "uploaded_byte_offset": 0,
            "uploaded_byte_length": len(uploaded_bytes),
            "final_audio_byte_offset": 0,
            "final_audio_byte_length": len(final_audio_bytes),
        }
    )

    def materialize(kind, _reference):
        return {
            "uploaded_audio": uploaded_bytes,
            "final_audio": final_audio_bytes,
            "final_video": final_video_bytes,
        }[kind]

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED"):
        background_music_execution.execute_background_music(
            execution_contract=execution,
            final_mix_receipt=receipt,
            materialize_bytes=materialize,
        )


def test_uploaded_song_falls_back_to_background_music_when_a_singing_line_falls_outside_its_frozen_music_window():
    line_outside_window = _verified_performance_line_contract()
    line_outside_window["cuts"][0]["source_time"] = {"start_ms": 200, "end_ms": 1200}
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        source_content_timeline=_confirmed_sung_source_timeline(),
        performance_line_contract=line_outside_window,
    )

    assert execution["mode"] == "background_music_replacement"
    assert execution["lyric_lip_sync_policy"] == "No lyric lip-sync"


def test_frozen_music_timing_evidence_is_mandatory_and_final_receipts_must_echo_it():
    incomplete_timeline = _music_timeline()
    incomplete_timeline["windows"][0].pop("source_entry")
    with pytest.raises(ValueError, match="MUSIC_TIMING_EVIDENCE_REQUIRED"):
        background_music_execution.compile_background_music_execution_contract(
            uploaded_audio=_uploaded_music(),
            music_timeline_contract=incomplete_timeline,
            audio_asset_receipt=_audio_asset_receipt(),
            source_content_timeline=_non_singing_source_timeline(),
            performance_line_contract=None,
        )

    execution = _execution_contract_for(_music_timeline())
    receipt = _final_mix_receipt(execution_contract=execution)
    receipt["window_receipts"][0]["transition"] = {
        **receipt["window_receipts"][0]["transition"],
        "output_end_ms": 999,
    }
    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED"):
        background_music_execution.execute_background_music(
            execution_contract=execution,
            final_mix_receipt=receipt,
        )

    beat_outside_line = _verified_performance_line_contract()
    beat_outside_line["cuts"][0]["beat_anchors_ms"] = [1_000]
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        source_content_timeline=_confirmed_sung_source_timeline(),
        performance_line_contract=beat_outside_line,
    )

    assert execution["mode"] == "background_music_replacement"


def test_background_music_mode_has_explicit_no_lyric_lip_sync_when_singing_evidence_is_unverified():
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        source_content_timeline=_confirmed_sung_source_timeline(),
        performance_line_contract=None,
    )

    assert execution["mode"] == "background_music_replacement"
    assert execution["lyric_lip_sync_policy"] == "No lyric lip-sync"
    assert "No lyric lip-sync" in execution["provider_payload"]["prompt"]


def test_verified_singing_seedance_prompt_locks_the_confirmed_singer_to_the_exact_audio1_lyrics():
    execution = _execution_contract_for(_music_timeline(), intent="verified_singing")

    text = execution["provider_payload"]["prompt"]

    assert "Song to perform: the exact uploaded track @Audio1." in text
    assert "CHARACTER_A is the only on-camera singer for this line." in text
    assert 'CHARACTER_A must sing only this exact lyric from @Audio1: "Hold on".' in text
    assert "Do not translate, paraphrase, add, omit, move, or reassign any lyric." in text


def test_verified_singing_seedance_prompt_forbids_any_song_except_audio1_and_assigns_exact_lyrics_to_the_singer():
    execution = _execution_contract_for(_music_timeline(), intent="verified_singing")

    text = execution["provider_payload"]["prompt"]

    assert "@Audio1 is the only song that may be performed." in text
    assert 'CHARACTER_A must sing only this exact lyric from @Audio1: "Hold on".' in text


def test_background_music_uses_the_frozen_source_timeline_route_instead_of_caller_intent():
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        source_content_timeline=_confirmed_sung_source_timeline(),
        performance_line_contract=_verified_performance_line_contract(),
    )

    assert execution["mode"] == "verified_singing"
    assert execution["uploaded_audio_route"]["mode"] == "pending_uploaded_lyrics"
    assert "user_confirmed_intent" not in execution


def test_background_music_contract_does_not_accept_a_caller_selected_intent():
    with pytest.raises(TypeError):
        background_music_execution.compile_background_music_execution_contract(
            uploaded_audio=_uploaded_music(),
            music_timeline_contract=_music_timeline(),
            audio_asset_receipt=_audio_asset_receipt(),
            source_content_timeline=_confirmed_sung_source_timeline(),
            performance_line_contract=_verified_performance_line_contract(),
            user_confirmed_intent="background_music_replacement",
        )


def test_background_music_falls_back_to_bgm_when_the_eligible_song_has_no_verified_lyrics():
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        source_content_timeline=_confirmed_sung_source_timeline(),
        performance_line_contract=None,
    )

    assert execution["mode"] == "background_music_replacement"
    assert execution["uploaded_audio_route"]["mode"] == "pending_uploaded_lyrics"
    assert execution["lyric_lip_sync_policy"] == "No lyric lip-sync"


def test_verified_singing_builds_the_final_lip_sync_request_only_for_its_generated_singer_region():
    execution = _execution_contract_for(_music_timeline(), intent="verified_singing")

    requests = background_music_execution.build_verified_singing_lip_sync_requests(
        execution_contract=execution,
        rendered_regions=[
            {
                "region_id": "C01",
                "media_origin": "generated",
                "audio_input": "song-window.wav",
                "video_input": "generated-singer.mp4",
            },
            {
                "region_id": "source-ui",
                "media_origin": "source_interval",
                "audio_input": "must-not-be-used.wav",
                "video_input": "must-not-be-used.mp4",
            },
        ],
    )

    assert requests == [
        {
            "line_id": "L01",
            "cut_id": "C01",
            "speaker_id": "CHARACTER_A",
            "provider_request": {
                "workflow_id": "2080140197518823426",
                "payload": {
                    "nodeInfoList": [
                        {"nodeId": "3", "fieldName": "audio", "fieldValue": "song-window.wav", "description": "audio"},
                        {"nodeId": "6", "fieldName": "video", "fieldValue": "generated-singer.mp4", "description": "video"},
                    ],
                    "instanceType": "default",
                    "usePersonalQueue": False,
                },
            },
        }
    ]


def test_background_music_never_builds_a_final_lip_sync_request():
    execution = _execution_contract_for(_music_timeline())

    requests = background_music_execution.build_verified_singing_lip_sync_requests(
        execution_contract=execution,
        rendered_regions=[
            {
                "region_id": "C01",
                "media_origin": "generated",
                "audio_input": "must-not-be-used.wav",
                "video_input": "must-not-be-used.mp4",
            }
        ],
    )

    assert requests == []


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
        source_content_timeline=_non_singing_source_timeline(),
        performance_line_contract=None,
    )
    valid_payload = execution["provider_payload"]
    port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(valid_payload, execution_contract=execution),
    )

    audited = port.run(context=context, input_artifacts=[])
    evidence = audited["background_music_evidence"]
    assert evidence["provider_payload"] == valid_payload
    audit_reference = evidence["music_execution_audit_receipt_artifact"]
    assert audit_reference["kind"] == "background_music_audit_receipt"
    assert json.loads(context.published[audit_reference["artifact_id"]])["execution_contract_sha256"] == execution[
        "execution_contract_sha256"
    ]

    invalid_payload = {**valid_payload, "reference_audios": ["https://runninghub.example/openapi/other.mp3"]}
    invalid_port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(invalid_payload, execution_contract=execution),
    )
    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        invalid_port.run(context=context, input_artifacts=[])


def test_real_audit_execution_request_submits_once_with_its_canonical_payload(tmp_path):
    context = _music_audit_context(tmp_path)
    execution = _execution_contract_for(_music_timeline())
    audited = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(execution["provider_payload"], execution_contract=execution),
    ).run(context=context, input_artifacts=[])
    request_reference = audited["background_music_evidence"]["music_execution_request_artifact"]
    published_request = json.loads(context.published[request_reference["artifact_id"]])
    assert published_request["request_binding"] == {
        **background_music_execution._execution_binding(execution),
        "provider_payload": execution["provider_payload"],
    }
    provider = _VerifiedProviderAdapter()

    BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    ).run(context=context, input_artifacts=[])

    assert provider.create_requests == [execution["provider_payload"]]


def test_seedance_compile_stage_requires_the_canonical_background_music_execution_contract():
    context = _PortContext(_PortSnapshot({"slots": {}, "extensions": {"background_music": _uploaded_music()}}))
    execution = _execution_contract_for(_music_timeline())
    altered_payload = {
        **execution["provider_payload"],
        "prompt": "Use @Audio1 but transform the uploaded song.",
    }
    port = BackgroundMusicStagePort(
        stage="compile_seedance20_prompt",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {"music_execution_contract": {**execution, "provider_payload": altered_payload}, "provider_payload": altered_payload}
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_SEEDANCE_COMPILE_INVALID"):
        port.run(context=context, input_artifacts=[])


def test_seedance_compile_requires_materialized_frozen_timeline_provenance_before_delegate_runs():
    execution = _execution_contract_for(_music_timeline())
    port = BackgroundMusicStagePort(
        stage="compile_seedance20_prompt",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {"music_execution_contract": execution, "provider_payload": execution["provider_payload"]}
        ),
    )
    context = _PortContext(_PortSnapshot({"slots": {}, "extensions": {"background_music": _uploaded_music()}}))

    with pytest.raises(ValueError, match="MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED"):
        port.run(context=context, input_artifacts=[])


def test_music_timing_requires_structured_source_and_output_boundaries():
    timeline = _music_timeline()
    timeline["windows"][0]["source_entry"] = "hard_cut"

    with pytest.raises(ValueError, match="MUSIC_TIMING_EVIDENCE_REQUIRED"):
        background_music_execution.compile_background_music_execution_contract(
            uploaded_audio=_uploaded_music(),
            music_timeline_contract=timeline,
            audio_asset_receipt=_audio_asset_receipt(),
            source_content_timeline=_non_singing_source_timeline(),
            performance_line_contract=None,
        )


def test_background_music_provider_audit_rejects_a_payload_that_differs_from_the_frozen_execution_contract():
    context = _PortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": _uploaded_music()}})
    )
    execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt=_audio_asset_receipt(),
        source_content_timeline=_confirmed_sung_source_timeline(),
        performance_line_contract=_verified_performance_line_contract(),
    )
    altered_payload = {
        **execution["provider_payload"],
        "prompt": "Use @Audio1 and invent a new lyric.",
    }
    port = BackgroundMusicStagePort(
        stage="audit_seedance_request",
        delegate=_Port("canonical"),
        music_delegate=_AuditedMusicPort(altered_payload, execution_contract=execution),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID"):
        port.run(context=context, input_artifacts=[])


def test_provider_submission_rejects_a_post_audit_self_consistent_contract_swap(tmp_path):
    original = _execution_contract_for(_music_timeline())
    audit_receipt = {
        "contract": "background_music_audit_receipt/v1",
        **background_music_execution._execution_binding(original),
    }
    encoded = json.dumps(audit_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    reference = {
        "artifact_id": "music-audit-receipt",
        "kind": "background_music_audit_receipt",
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
    path = tmp_path / "music-audit-receipt.json"
    path.write_bytes(encoded)
    swapped = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio=_uploaded_music(),
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt={
            **_audio_asset_receipt(),
            "runninghub_audio_url": "https://runninghub.example/openapi/replaced-song.mp3",
        },
        source_content_timeline=_non_singing_source_timeline(),
        performance_line_contract=None,
    )
    port = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_execution_contract": swapped,
                "provider_payload": swapped["provider_payload"],
                "music_execution_audit_receipt_artifact": reference,
            }
        ),
    )
    context = _MultiArtifactPortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": _uploaded_music()}}),
        artifact_entries=((reference, path),),
    )

    with pytest.raises(ValueError, match="(?:MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED|BACKGROUND_MUSIC_AUDIT_RECEIPT_MISMATCH)"):
        port.run(context=context, input_artifacts=[])


def test_provider_submit_requires_a_receipt_echoing_the_pre_submit_frozen_payload(tmp_path):
    execution, _, context, _, audit_reference = _materialized_music_case(tmp_path, _music_timeline())
    port = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
            }
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_ADAPTER_REQUIRED"):
        port.run(context=context, input_artifacts=[])


def test_provider_submit_rejects_a_copied_pre_submit_binding_without_provider_task_receipt(tmp_path):
    execution, _, context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    port = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_ADAPTER_REQUIRED"):
        port.run(context=context, input_artifacts=[])


def test_provider_adapter_submits_the_materialized_request_and_waits_for_its_exact_task(tmp_path):
    execution, receipt, context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    final_video = receipt["final_video_artifact"]
    with context.materialize_artifact(
        final_video["kind"], artifact_id=final_video["artifact_id"], sha256=final_video["sha256"]
    ) as materialized:
        provider = _VerifiedProviderAdapter(video_bytes=materialized.path.read_bytes())
    submit = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )

    submitted = submit.run(context=context, input_artifacts=[])

    assert provider.create_requests == [execution["provider_payload"]]
    evidence = submitted["background_music_evidence"]
    receipt = evidence["provider_submission_receipt"]
    assert receipt["provider_task_id"] == "provider-task-1"
    assert receipt["provider_raw_response_artifact"]["kind"] == "background_music_provider_raw_response"
    raw_reference = receipt["provider_raw_response_artifact"]
    assert json.loads(context.published_entries[raw_reference["artifact_id"]][1].read_bytes()) == {
        "status": "submitted",
        "task_id": "provider-task-1",
    }

    wait = BackgroundMusicStagePort(
        stage="wait_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )
    completed = wait.run(context=context, input_artifacts=[])

    assert provider.lookup_intents == [{"taskId": "provider-task-1"}]
    assert completed["background_music_evidence"]["provider_submission_receipt"] == receipt
    output_reference = completed["background_music_evidence"]["provider_output_artifact"]
    assert output_reference["kind"] == "background_music_provider_output"
    output = json.loads(context.published_entries[output_reference["artifact_id"]][1].read_bytes())
    assert output["provider_submission_artifact"] == evidence["provider_submission_artifact"]
    assert output["execution_request_artifact"]["kind"] == "background_music_execution_request"
    assert output["execution_contract_sha256"] == execution["execution_contract_sha256"]
    assert output["seedance_payload_sha256"] == execution["seedance_payload_sha256"]
    attempt = context.job_store.attempts[0]
    assert context.job_store.events == ["begin", "RUNNING", "SUCCEEDED"]
    assert attempt.status == "SUCCEEDED"
    assert attempt.provider_task_id == "provider-task-1"
    assert attempt.response_sha256 == receipt["provider_raw_response_sha256"]


def test_provider_lookup_materializes_the_exact_provider_video_before_publishing_output(tmp_path):
    _, receipt, context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    final_video = receipt["final_video_artifact"]
    with context.materialize_artifact(
        final_video["kind"], artifact_id=final_video["artifact_id"], sha256=final_video["sha256"]
    ) as materialized:
        provider_video_bytes = materialized.path.read_bytes()
    provider = _VerifiedProviderAdapter(video_bytes=provider_video_bytes)
    submit = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )
    submit.run(context=context, input_artifacts=[])

    completed = BackgroundMusicStagePort(
        stage="wait_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    ).run(context=context, input_artifacts=[])["background_music_evidence"]

    output_reference = completed["provider_output_artifact"]
    output = json.loads(context.published_entries[output_reference["artifact_id"]][1].read_bytes())
    provider_video_reference = output["provider_video_artifact"]
    assert provider.download_intents == ["provider-task-1"]
    assert provider_video_reference["kind"] == "background_music_provider_video"
    assert provider_video_reference["sha256"] == hashlib.sha256(provider_video_bytes).hexdigest()
    assert context.published_entries[provider_video_reference["artifact_id"]][1].read_bytes() == provider_video_bytes


def test_provider_submission_stage_output_keeps_the_raw_response_only_as_an_artifact(tmp_path):
    """A paid submit must survive the worker's JSON-only stage checkpoint."""

    execution, _, context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    provider = _VerifiedProviderAdapter()
    submitted = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    ).run(context=context, input_artifacts=[])

    evidence = submitted["background_music_evidence"]
    assert "provider_raw_response" not in evidence
    assert evidence["provider_submission_receipt"]["provider_raw_response_artifact"]["kind"] == (
        "background_music_provider_raw_response"
    )

    from server.ephemeral_worker import _stage_output_value

    assert _stage_output_value(submitted) == submitted


def test_provider_task_identity_is_checkpointed_before_raw_response_artifact_publication(tmp_path):
    """A post-charge artifact-store failure must not lose the Provider task ID."""

    class _RawResponsePublicationFailureContext(_MediaPortContext):
        def publish_bytes(self, *, kind, data, content_type, expected_sha256):
            if kind == "background_music_provider_raw_response":
                raise RuntimeError("object storage temporarily unavailable")
            return super().publish_bytes(
                kind=kind,
                data=data,
                content_type=content_type,
                expected_sha256=expected_sha256,
            )

    execution, _, base_context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    context = _RawResponsePublicationFailureContext(
        base_context.snapshot,
        uploaded_path=base_context.uploaded_path,
        artifact_entries=base_context.artifact_entries,
        published_entries=base_context.published_entries,
        provider_lineage=base_context.provider_lineage,
    )
    provider = _VerifiedProviderAdapter()
    submit = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED"):
        submit.run(context=context, input_artifacts=[])

    assert provider.create_requests == [execution["provider_payload"]]
    attempt = context.job_store.attempts[0]
    assert attempt.status == "RUNNING"
    assert attempt.provider_task_id == "provider-task-1"
    assert isinstance(attempt.response_sha256, str) and len(attempt.response_sha256) == 64


def test_provider_submit_freezes_and_reuses_the_running_attempt_instead_of_creating_a_second_paid_task(tmp_path):
    execution, _, context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    provider = _VerifiedProviderAdapter()
    submit = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )

    first = submit.run(context=context, input_artifacts=[])
    attempt = context.job_store.attempts[0]

    assert context.job_store.events == ["begin", "RUNNING"]
    assert attempt.operation == "CreateVideo"
    assert attempt.status == "RUNNING"
    assert attempt.provider_task_id == "provider-task-1"
    assert attempt.request_sha256 == execution["seedance_payload_sha256"]
    assert attempt.response_sha256 == first["background_music_evidence"]["provider_submission_receipt"][
        "provider_raw_response_sha256"
    ]

    resumed = submit.run(context=context, input_artifacts=[])

    assert provider.create_requests == [execution["provider_payload"]]
    assert context.job_store.events == ["begin", "RUNNING"]
    assert resumed["background_music_evidence"]["provider_submission_receipt"]["provider_attempt_id"] == attempt.attempt_id


def test_provider_adapter_without_a_bound_media_download_fails_closed():
    class _MetadataOnlyProvider(_VerifiedProviderAdapter):
        download = None

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_ADAPTER_INVALID"):
        BackgroundMusicStagePort(
            stage="wait_provider_video",
            delegate=_Port("canonical"),
            music_delegate=_CopiedReceiptSubmitPort(),
            provider_adapter=_MetadataOnlyProvider(),
        )


def test_provider_submit_rejects_an_execution_request_with_a_noncanonical_extra_binding_field(tmp_path):
    execution, _, context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    request_reference, request_path = next(
        entry for entry in context.artifact_entries if entry[0]["kind"] == "background_music_execution_request"
    )
    request = json.loads(request_path.read_bytes())
    request["request_binding"]["untrusted_extra"] = "must-not-reach-provider"
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request_path.write_bytes(encoded)
    request_reference["sha256"] = hashlib.sha256(encoded).hexdigest()
    provider = _VerifiedProviderAdapter()
    port = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED"):
        port.run(context=context, input_artifacts=[])

    assert provider.create_requests == []


def test_video_visual_receipt_rejects_matching_pixels_with_retimed_frame_pts(tmp_path):
    frames = (("red", bytes((255, 0, 0))), ("green", bytes((0, 255, 0))), ("blue", bytes((0, 0, 255))))
    for name, pixel in frames:
        (tmp_path / f"{name}.ppm").write_bytes(b"P6\n16 16\n255\n" + pixel * (16 * 16))

    def render(name, durations):
        manifest = tmp_path / f"{name}.ffconcat"
        entries = ["ffconcat version 1.0"]
        for frame, duration in zip(("red", "green", "blue"), durations):
            entries.extend((f"file '{tmp_path / f'{frame}.ppm'}'", f"duration {duration}"))
        entries.append(f"file '{tmp_path / 'blue.ppm'}'")
        manifest.write_text("\n".join(entries), encoding="utf-8")
        output = tmp_path / f"{name}.mp4"
        generated = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(manifest),
                "-vsync", "vfr", "-c:v", "libx264", "-crf", "0", "-bf", "0",
                "-video_track_timescale", "1000", "-f", "mov", str(output),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert generated.returncode == 0, generated.stderr.decode("utf-8", errors="replace")
        return output

    source_receipt = BackgroundMusicStagePort._decode_video_visual_receipt(
        render("source", (0.2, 0.3, 0.5))
    )
    retimed_receipt = BackgroundMusicStagePort._decode_video_visual_receipt(
        render("retimed", (0.3, 0.2, 0.5))
    )
    assert source_receipt["decoded_rgb24_sha256"] == retimed_receipt["decoded_rgb24_sha256"], (
        source_receipt,
        retimed_receipt,
    )
    assert source_receipt["frame_count"] == retimed_receipt["frame_count"]
    assert source_receipt["duration_ms"] == retimed_receipt["duration_ms"]
    assert source_receipt != retimed_receipt


def test_background_music_splice_rejects_a_final_video_with_matching_audio_but_different_provider_visuals(tmp_path):
    contract = _music_timeline()
    execution, receipt, context, timeline_reference, audit_reference = _materialized_music_case(
        tmp_path, contract, with_provider_lineage=True
    )
    changed_video_path = tmp_path / "changed-visuals.mp4"
    source_video = receipt["final_video_artifact"]
    with context.materialize_artifact(
        source_video["kind"], artifact_id=source_video["artifact_id"], sha256=source_video["sha256"]
    ) as materialized:
        generated = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=white:s=16x16:r=30:d=1",
                "-i", str(materialized.path),
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "mpeg4", "-c:a", "copy",
                "-shortest", "-f", "mov", str(changed_video_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    assert generated.returncode == 0, generated.stderr.decode("utf-8", errors="replace")
    changed_video = changed_video_path.read_bytes()
    changed_reference = context.publish_bytes(
        kind="final_video_changed_visuals",
        data=changed_video,
        content_type="video/mp4",
        expected_sha256=hashlib.sha256(changed_video).hexdigest(),
    )
    receipt["final_video_artifact"] = changed_reference
    receipt["final_video_sha256"] = changed_reference["sha256"]
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": receipt,
            }
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_VIDEO_PROOF_REQUIRED"):
        port.run(context=context, input_artifacts=[])


def test_provider_submit_rejects_a_self_consistent_request_with_a_different_audit_before_create(tmp_path):
    execution, _, context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    request_reference, request_path = next(
        entry for entry in context.artifact_entries if entry[0]["kind"] == "background_music_execution_request"
    )
    forged_execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio={
            **_uploaded_music(),
            "sha256": execution["uploaded_audio_sha256"],
            "content_type": "audio/wav",
        },
        music_timeline_contract=_music_timeline(),
        audio_asset_receipt={
            **_audio_asset_receipt(),
            "uploaded_audio_sha256": execution["uploaded_audio_sha256"],
            "runninghub_audio_url": "https://runninghub.example/openapi/forged-song.mp3",
        },
        source_content_timeline=_non_singing_source_timeline(),
        performance_line_contract=None,
    )
    forged_request = {
        "contract": "background_music_execution_request/v1",
        "music_execution_contract": forged_execution,
        "provider_payload": forged_execution["provider_payload"],
        "audit_receipt_artifact": {
            "artifact_id": "forged-audit",
            "kind": "background_music_audit_receipt",
            "sha256": "a" * 64,
        },
        "request_binding": {
            **background_music_execution._execution_binding(forged_execution),
            "provider_payload": forged_execution["provider_payload"],
        },
    }
    forged_bytes = json.dumps(forged_request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request_path.write_bytes(forged_bytes)
    request_reference["sha256"] = hashlib.sha256(forged_bytes).hexdigest()
    provider = _VerifiedProviderAdapter()
    port = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_AUDIT_RECEIPT_MISMATCH"):
        port.run(context=context, input_artifacts=[])

    assert provider.create_requests == []


def test_background_music_splice_requires_exact_provider_output_lineage(tmp_path):
    contract = _music_timeline()
    execution, receipt, context, timeline_reference, audit_reference = _materialized_music_case(tmp_path, contract)
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": receipt,
            }
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_OUTPUT_LINEAGE_REQUIRED"):
        port.run(context=context, input_artifacts=[])


def test_background_music_splice_rejects_a_final_video_claimed_for_another_provider_task(tmp_path):
    contract = _music_timeline()
    execution, receipt, context, timeline_reference, audit_reference = _materialized_music_case(
        tmp_path, contract, with_provider_lineage=True
    )
    receipt["final_video_provider_task_id"] = "another-provider-task"
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": receipt,
            }
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_OUTPUT_LINEAGE_REQUIRED"):
        port.run(context=context, input_artifacts=[])


def test_background_music_splice_rejects_submission_not_bound_to_the_current_frozen_request(tmp_path):
    contract = _music_timeline()
    execution, receipt, context, timeline_reference, audit_reference = _materialized_music_case(
        tmp_path, contract, with_provider_lineage=True
    )
    lineage = context.provider_lineage
    submission_reference = lineage["provider_submission_artifact"]
    submission = json.loads(context.published_entries[submission_reference["artifact_id"]][1].read_bytes())
    forged_execution = background_music_execution.compile_background_music_execution_contract(
        uploaded_audio={**_uploaded_music(), "sha256": execution["uploaded_audio_sha256"], "content_type": "audio/wav"},
        music_timeline_contract=contract,
        audio_asset_receipt={
            **_audio_asset_receipt(),
            "uploaded_audio_sha256": execution["uploaded_audio_sha256"],
            "runninghub_audio_url": "https://runninghub.example/openapi/another-audited-song.mp3",
        },
        source_content_timeline=_non_singing_source_timeline(),
        performance_line_contract=None,
    )
    submission["music_execution_contract"] = forged_execution
    submission["provider_payload"] = forged_execution["provider_payload"]
    rewritten_submission = _rewrite_published_json(context, submission_reference, submission)
    output_reference = lineage["provider_output_artifact"]
    output = json.loads(context.published_entries[output_reference["artifact_id"]][1].read_bytes())
    output["provider_submission_artifact"] = {
        **rewritten_submission,
        "kind": "background_music_provider_submission",
    }
    output["provider_payload"] = forged_execution["provider_payload"]
    rewritten_output = _rewrite_published_json(context, output_reference, output)
    lineage.update(
        {
            "provider_submission_artifact": rewritten_submission,
            "provider_submission_receipt": submission,
            "provider_output_artifact": rewritten_output,
        }
    )
    receipt.update(
        {
            "provider_output_artifact": rewritten_output,
            "final_video_provider_output_artifact": rewritten_output,
        }
    )
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": receipt,
            }
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_OUTPUT_LINEAGE_REQUIRED"):
        port.run(context=context, input_artifacts=[])


def test_provider_wait_rejects_a_lookup_response_for_another_task(tmp_path):
    _, _, context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    provider = _WrongTaskProviderAdapter()
    submit = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )
    submit.run(context=context, input_artifacts=[])
    wait = BackgroundMusicStagePort(
        stage="wait_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_LOOKUP_REQUIRED"):
        wait.run(context=context, input_artifacts=[])


def test_provider_wait_rejects_a_submission_that_points_to_an_unmaterialized_request(tmp_path):
    _, _, context, _, _ = _materialized_music_case(tmp_path, _music_timeline())
    provider = _VerifiedProviderAdapter()
    submit = BackgroundMusicStagePort(
        stage="submit_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )
    submission = submit.run(context=context, input_artifacts=[])["background_music_evidence"]["provider_submission_artifact"]
    submission_reference, submission_path = context.published_entries.pop(submission["artifact_id"])
    forged = json.loads(submission_path.read_bytes())
    forged["execution_request_artifact"] = {
        "artifact_id": "unrelated-request",
        "kind": "background_music_execution_request",
        "sha256": "e" * 64,
    }
    forged_bytes = json.dumps(forged, sort_keys=True, separators=(",", ":")).encode("utf-8")
    forged_reference = {**submission_reference, "sha256": hashlib.sha256(forged_bytes).hexdigest()}
    submission_path.write_bytes(forged_bytes)
    context.published_entries[forged_reference["artifact_id"]] = (forged_reference, submission_path)
    wait = BackgroundMusicStagePort(
        stage="wait_provider_video",
        delegate=_Port("canonical"),
        music_delegate=_CopiedReceiptSubmitPort(),
        provider_adapter=provider,
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED"):
        wait.run(context=context, input_artifacts=[])


def test_pcm_timeline_uses_global_zero_clock_for_declared_leading_and_trailing_silence():
    contract = _music_timeline()
    window = contract["windows"][0]
    window["output_start_ms"] = 1_000
    window["output_end_ms"] = 2_000
    for field in ("source_entry", "source_exit", "fade_in", "fade_out", "silence_before", "silence_after", "transition"):
        event = window[field]
        event["output_start_ms"] += 1_000
        event["output_end_ms"] += 1_000
    contract["output_duration_ms"] = 3_000
    contract["meaningful_silence_output_intervals"] = [
        {"output_start_ms": 0, "output_end_ms": 1_000},
        {"output_start_ms": 2_000, "output_end_ms": 3_000},
    ]
    execution = _execution_contract_for(contract)
    source_pcm = b"\x01\x00\x01\x00" * 48_000
    final_pcm = (b"\0" * len(source_pcm)) + source_pcm + (b"\0" * len(source_pcm))

    background_music_execution._validate_pcm_timeline(
        execution_contract=execution,
        final_mix_receipt={"window_receipts": [{"pcm_fragment_sha256": hashlib.sha256(source_pcm).hexdigest()}]},
        uploaded_pcm=source_pcm,
        final_audio_pcm=final_pcm,
    )


@pytest.mark.parametrize(
    "silence_intervals",
    [
        [{"output_start_ms": 2_000, "output_end_ms": 3_000}],
        [{"output_start_ms": 0, "output_end_ms": 500}, {"output_start_ms": 2_000, "output_end_ms": 3_000}],
        [{"output_start_ms": 0, "output_end_ms": 1_000}],
        [{"output_start_ms": 0, "output_end_ms": 1_500}, {"output_start_ms": 2_000, "output_end_ms": 3_000}],
    ],
)
def test_pcm_timeline_rejects_undeclared_or_overlapping_global_silence(silence_intervals):
    contract = _music_timeline()
    window = contract["windows"][0]
    window["output_start_ms"] = 1_000
    window["output_end_ms"] = 2_000
    for field in ("source_entry", "source_exit", "fade_in", "fade_out", "silence_before", "silence_after", "transition"):
        window[field]["output_start_ms"] += 1_000
        window[field]["output_end_ms"] += 1_000
    contract["output_duration_ms"] = 3_000
    contract["meaningful_silence_output_intervals"] = [
        {"output_start_ms": 0, "output_end_ms": 1_000},
        {"output_start_ms": 2_000, "output_end_ms": 3_000},
    ]
    execution = _execution_contract_for(contract)
    execution["music_timeline_contract"] = {
        **execution["music_timeline_contract"],
        "meaningful_silence_output_intervals": silence_intervals,
    }
    source_pcm = b"\x01\x00\x01\x00" * 48_000
    final_pcm = (b"\0" * len(source_pcm)) + source_pcm + (b"\0" * len(source_pcm))

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH"):
        background_music_execution._validate_pcm_timeline(
            execution_contract=execution,
            final_mix_receipt={"window_receipts": [{"pcm_fragment_sha256": hashlib.sha256(source_pcm).hexdigest()}]},
            uploaded_pcm=source_pcm,
            final_audio_pcm=final_pcm,
        )


def test_background_music_provider_audit_revalidates_the_mode_contract_instead_of_trusting_delegate_text(tmp_path):
    context = _music_audit_context(tmp_path)
    execution = _execution_contract_for(_music_timeline())
    unsafe_payload = {
        **execution["provider_payload"],
        "prompt": "Use @Audio1 and make the performer lyric lip-sync every word.",
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
        source_content_timeline=_confirmed_sung_source_timeline(),
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


def test_background_music_splice_requires_exact_uploaded_fragments_and_rejects_audio_transforms(tmp_path):
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
    execution, receipt, context, timeline_reference, audit_reference = _materialized_music_case(
        tmp_path, contract, with_provider_lineage=True
    )
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": receipt,
            }
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
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": transformed,
            }
        ),
    )
    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_TRANSFORM_FORBIDDEN"):
        invalid_port.run(context=context, input_artifacts=[])


def test_background_music_splice_fails_closed_without_materialized_source_and_final_media(tmp_path):
    contract = _music_timeline()
    execution = _execution_contract_for(contract)
    timeline_bytes = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timeline_reference = {
        "artifact_id": "music-timeline",
        "kind": "music_timeline_contract",
        "sha256": hashlib.sha256(timeline_bytes).hexdigest(),
    }
    audit_receipt = {
        "contract": "background_music_audit_receipt/v1",
        **background_music_execution._execution_binding(execution),
        "music_timeline_contract_sha256": timeline_reference["sha256"],
        "performance_line_contract_sha256": None,
    }
    audit_bytes = json.dumps(audit_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    audit_reference = {
        "artifact_id": "music-audit",
        "kind": "background_music_audit_receipt",
        "sha256": hashlib.sha256(audit_bytes).hexdigest(),
    }
    timeline_path = tmp_path / "timeline.json"
    audit_path = tmp_path / "audit.json"
    timeline_path.write_bytes(timeline_bytes)
    audit_path.write_bytes(audit_bytes)
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "mix_receipt": _final_mix_receipt(execution_contract=execution),
                "music_execution_audit_receipt_artifact": audit_reference,
            }
        ),
    )
    context = _MultiArtifactPortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": _uploaded_music()}}),
        artifact_entries=((timeline_reference, timeline_path), (audit_reference, audit_path)),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_OUTPUT_LINEAGE_REQUIRED"):
        port.run(context=context, input_artifacts=[])


def test_background_music_splice_rejects_a_final_video_whose_materialized_audio_differs(tmp_path):
    contract = _music_timeline()
    execution, receipt, context, timeline_reference, audit_reference = _materialized_music_case(
        tmp_path,
        contract,
        video_audio_bytes=_pcm_wav_bytes(b"\x02\x00\x02\x00" * 4_800),
        with_provider_lineage=True,
    )
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": receipt,
            }
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_VIDEO_AUDIO_MISMATCH"):
        port.run(context=context, input_artifacts=[])


def test_background_music_splice_rejects_a_final_video_with_an_unverified_default_audio_track(tmp_path):
    contract = _music_timeline()
    execution, receipt, context, timeline_reference, audit_reference = _materialized_music_case(
        tmp_path,
        contract,
        extra_video_audio_bytes=_pcm_wav_bytes(b"\x02\x00\x02\x00" * 4_800),
        with_provider_lineage=True,
    )
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": receipt,
            }
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED"):
        port.run(context=context, input_artifacts=[])


@pytest.mark.parametrize("offset", [0.2, -0.1])
def test_background_music_splice_rejects_delayed_or_advanced_final_video_audio_pts(tmp_path, offset):
    contract = _music_timeline()
    execution, receipt, context, timeline_reference, audit_reference = _materialized_music_case(
        tmp_path,
        contract,
        video_audio_offset_seconds=offset,
        with_provider_lineage=True,
    )
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": receipt,
            }
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_(VIDEO_AUDIO|VIDEO_TIMELINE)_MISMATCH"):
        port.run(context=context, input_artifacts=[])


@pytest.mark.parametrize("variant", ["gap", "outside", "repeat"])
def test_frozen_milliseconds_reject_gap_window_outside_audio_and_repeated_pcm(variant):
    execution = _execution_contract_for(_music_timeline())
    source_pcm = b"\x01\x00\x01\x00" * 48_000
    digest = hashlib.sha256(source_pcm).hexdigest()
    receipt = {"window_receipts": [{"pcm_fragment_sha256": digest}]}
    if variant == "gap":
        final_pcm = source_pcm[:96_000] + (b"\0" * 96_000)
    elif variant == "outside":
        final_pcm = source_pcm + (b"\0" * 192)
    else:
        final_pcm = source_pcm + source_pcm

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH"):
        background_music_execution._validate_pcm_timeline(
            execution_contract=execution,
            final_mix_receipt=receipt,
            uploaded_pcm=source_pcm,
            final_audio_pcm=final_pcm,
        )


def test_background_music_splice_rejects_a_contract_that_differs_from_the_materialized_frozen_artifact(tmp_path):
    background_music = {
        "object_key": "uploads/batch-scope/song.mp3",
        "sha256": "b" * 64,
        "size_bytes": 128,
        "content_type": "audio/mpeg",
        "duration_seconds": 30.0,
        "status": "completed",
    }
    frozen_contract = _music_timeline()
    frozen_bytes = json.dumps(frozen_contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    frozen_sha256 = hashlib.sha256(frozen_bytes).hexdigest()
    artifact_path = tmp_path / "music_timeline_contract.json"
    artifact_path.write_bytes(frozen_bytes)
    artifact_ref = {
        "artifact_id": "music-contract-1",
        "kind": "music_timeline_contract",
        "sha256": frozen_sha256,
    }
    altered_window = {
        **frozen_contract["windows"][0],
        "uploaded_start_ms": 1000,
        "uploaded_end_ms": 2000,
    }
    for field in ("source_entry", "source_exit", "fade_in", "fade_out", "silence_before", "silence_after", "transition"):
        altered_window[field] = {
            **altered_window[field],
            "source_start_ms": altered_window[field]["source_start_ms"] + 1000,
            "source_end_ms": altered_window[field]["source_end_ms"] + 1000,
        }
    altered_contract = {**frozen_contract, "windows": [altered_window]}
    execution = _execution_contract_for(altered_contract)
    receipt = _final_mix_receipt(execution_contract=execution)
    audit_receipt = {
        "contract": "background_music_audit_receipt/v1",
        **background_music_execution._execution_binding(execution),
        "music_timeline_contract_sha256": frozen_sha256,
        "performance_line_contract_sha256": None,
    }
    audit_bytes = json.dumps(audit_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    audit_path = tmp_path / "music-audit-receipt.json"
    audit_path.write_bytes(audit_bytes)
    audit_ref = {
        "artifact_id": "music-audit-1",
        "kind": "background_music_audit_receipt",
        "sha256": hashlib.sha256(audit_bytes).hexdigest(),
    }
    context = _MultiArtifactPortContext(
        _PortSnapshot({"slots": {}, "extensions": {"background_music": background_music}}),
        artifact_entries=((artifact_ref, artifact_path), (audit_ref, audit_path)),
    )
    port = BackgroundMusicStagePort(
        stage="splice_timeline",
        delegate=_Port("canonical"),
        music_delegate=_MixMusicPort(
            {
                "music_timeline_contract": altered_contract,
                "music_timeline_contract_artifact": artifact_ref,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_ref,
                "mix_receipt": receipt,
            }
        ),
    )

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_OUTPUT_LINEAGE_REQUIRED"):
        port.run(context=context, input_artifacts=[])


def test_background_music_qc_requires_singing_alignment_and_lip_sync_or_an_explicit_no_visible_singer_skip(tmp_path):
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
    execution, receipt, context, timeline_reference, audit_reference = _materialized_music_case(
        tmp_path, base_contract, with_provider_lineage=True
    )
    skipped = {"status": "skipped", "reason": "no_lyric_lip_sync", "regions": []}
    port = BackgroundMusicStagePort(
        stage="run_qc",
        delegate=_Port("canonical"),
        music_delegate=_QcMusicPort(
            {
                "music_timeline_contract": base_contract,
                "music_timeline_contract_artifact": timeline_reference,
                "music_execution_contract": execution,
                "provider_payload": execution["provider_payload"],
                "music_execution_audit_receipt_artifact": audit_reference,
                "mix_receipt": receipt,
                "singing_qa": skipped,
            }
        ),
    )

    assert port.run(context=context, input_artifacts=[])["background_music_evidence"]["singing_qa"] == skipped

    visible_contract = {**base_contract, "visible_singer_regions": [{"region_id": "s1", "visible": True}]}
    visible_execution, visible_receipt, visible_context, visible_timeline, visible_audit = _materialized_music_case(
        tmp_path / "visible", visible_contract, intent="verified_singing", with_provider_lineage=True
    )
    missing_singing_qa = BackgroundMusicStagePort(
        stage="run_qc",
        delegate=_Port("canonical"),
        music_delegate=_QcMusicPort(
            {
                "music_timeline_contract": visible_contract,
                "music_timeline_contract_artifact": visible_timeline,
                "music_execution_contract": visible_execution,
                "provider_payload": visible_execution["provider_payload"],
                "music_execution_audit_receipt_artifact": visible_audit,
                "mix_receipt": visible_receipt,
                "singing_qa": skipped,
            }
        ),
    )
    with pytest.raises(ValueError, match="SINGING_ALIGNMENT_REQUIRED"):
        missing_singing_qa.run(context=visible_context, input_artifacts=[])


def test_background_music_splice_fails_closed_without_an_immutable_audit_receipt():
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

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED"):
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
    provider = _VerifiedProviderAdapter()
    worker_manager = type(
        "WorkerManager",
        (),
        {
            "stage_ports": {stage: _Port(f"canonical-{stage}") for stage in stages},
            "capability_ports": {"provider_adapter": provider},
        },
    )()
    adapter = DeploymentBackgroundMusicExecutionAdapter(
        music_stage_ports={stage: _MusicPort() for stage in stages},
        provider_adapter=provider,
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


def test_deployment_music_adapter_rejects_a_provider_method_rebound_after_startup():
    stages = tuple(background_music_execution.MUSIC_STAGE_PORTS)
    provider = _VerifiedProviderAdapter()
    worker_manager = type(
        "WorkerManager",
        (),
        {
            "stage_ports": {stage: _Port(f"canonical-{stage}") for stage in stages},
            "capability_ports": {"provider_adapter": provider},
        },
    )()
    adapter = DeploymentBackgroundMusicExecutionAdapter(
        music_stage_ports={stage: _MusicPort() for stage in stages},
        provider_adapter=provider,
    )
    adapter.install(
        job_store=object(),
        work_queue=object(),
        worker_manager=worker_manager,
        stage_driver=type("CanonicalDriver", (), {"enqueue_next": lambda self, job_id: job_id})(),
    )
    provider.lookup = lambda intent: {"task_id": intent["taskId"], "status": "completed"}

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_ADAPTER_INVALID"):
        adapter.validate_startup()


def test_deployment_music_adapter_rejects_a_capability_identity_method_rebound_after_startup():
    stages = tuple(background_music_execution.MUSIC_STAGE_PORTS)
    provider = _VerifiedProviderAdapter()
    worker_manager = type(
        "WorkerManager",
        (),
        {
            "stage_ports": {stage: _Port(f"canonical-{stage}") for stage in stages},
            "capability_ports": {"provider_adapter": provider},
        },
    )()
    adapter = DeploymentBackgroundMusicExecutionAdapter(
        music_stage_ports={stage: _MusicPort() for stage in stages},
        provider_adapter=provider,
    )
    adapter.install(
        job_store=object(),
        work_queue=object(),
        worker_manager=worker_manager,
        stage_driver=type("CanonicalDriver", (), {"enqueue_next": lambda self, job_id: job_id})(),
    )
    original_identity = provider.capability_identity()
    provider.capability_identity = lambda: original_identity

    with pytest.raises(ValueError, match="BACKGROUND_MUSIC_PROVIDER_ADAPTER_INVALID"):
        adapter.validate_startup()
