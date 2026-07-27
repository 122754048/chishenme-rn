"""Development-only local functional harness for the background-music extension.

This runner exercises the existing StagePort validation boundary with archived
local media. It is not a Provider implementation and must not be installed in
the commercial deployment adapter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import subprocess
import struct
import sys
from types import SimpleNamespace

from app.background_music_execution import (
    BackgroundMusicStagePort,
    compile_background_music_execution_contract,
)
from server.job_models import ProviderAttempt


LOCAL_MVP_ENVIRONMENT = "development-only"
_AUDIO_ACTIVITY_RMS_THRESHOLD = 0.02
_PCM_OUTPUT_FORMATS = {
    "s16": ("s16le", "pcm_s16le", 2),
    "s16p": ("s16le", "pcm_s16le", 2),
    "s32": ("s32le", "pcm_s32le", 4),
    "s32p": ("s32le", "pcm_s32le", 4),
    "flt": ("f32le", "pcm_f32le", 4),
    "fltp": ("f32le", "pcm_f32le", 4),
    "dbl": ("f64le", "pcm_f64le", 8),
    "dblp": ("f64le", "pcm_f64le", 8),
}


class DevelopmentOnlyBackgroundMusicMvpError(ValueError):
    """Raised when the deterministic local MVP cannot create a valid receipt."""


@dataclass
class _Snapshot:
    slots_manifest: dict[str, object]


@dataclass(frozen=True)
class _DecodedPcm:
    data: bytes
    sample_rate: int
    channels: int
    sample_format: str
    codec: str
    bytes_per_sample: int

    @property
    def bytes_per_frame(self) -> int:
        return self.channels * self.bytes_per_sample


@dataclass
class _LocalProviderAttemptStore:
    version: int = 1
    expires_at_ms: int = 9_999_999_999_999
    attempts: list[ProviderAttempt] = field(default_factory=list)

    def get_job(self, job_id: str) -> "_LocalProviderAttemptStore":
        if job_id != "local-background-music-mvp":
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_PROVIDER_ATTEMPT_INVALID")
        return self

    def list_provider_attempts(self, job_id: str) -> tuple[ProviderAttempt, ...]:
        self.get_job(job_id)
        return tuple(self.attempts)

    def begin_provider_attempt(
        self,
        *,
        job_id: str,
        expected_version: int,
        operation: str,
        request_sha256: str,
        segment_id: str | None = None,
        segment_plan_sha256: str | None = None,
    ) -> ProviderAttempt:
        self.get_job(job_id)
        if expected_version != self.version or operation != "CreateVideo":
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_PROVIDER_ATTEMPT_INVALID")
        attempt = ProviderAttempt(
            attempt_id=f"local-attempt-{len(self.attempts) + 1}",
            operation="CreateVideo",
            request_sha256=request_sha256,
            status="SUBMITTING",
            segment_id=segment_id,
            segment_plan_sha256=segment_plan_sha256,
        )
        self.attempts.append(attempt)
        self.version += 1
        return attempt

    def update_provider_attempt(
        self,
        *,
        job_id: str,
        expected_version: int,
        attempt: ProviderAttempt,
        ttl_seconds: int,
    ) -> "_LocalProviderAttemptStore":
        self.get_job(job_id)
        if expected_version != self.version or ttl_seconds <= 0:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_PROVIDER_ATTEMPT_INVALID")
        index = next(
            (index for index, current in enumerate(self.attempts) if current.attempt_id == attempt.attempt_id),
            None,
        )
        if index is None:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_PROVIDER_ATTEMPT_INVALID")
        self.attempts[index] = attempt
        self.version += 1
        return self


@dataclass
class _LocalStageContext:
    snapshot: _Snapshot
    contracts_dir: Path
    _artifacts: list[dict[str, object]]
    job_id: str = "local-background-music-mvp"
    job_store: _LocalProviderAttemptStore = field(default_factory=_LocalProviderAttemptStore)

    @contextmanager
    def materialize_slot(self, slot_id: str):
        slots = self.snapshot.slots_manifest.get("slots")
        if not isinstance(slots, Mapping):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SLOT_CONTEXT_INVALID")
        descriptor = slots.get(slot_id)
        if not isinstance(descriptor, Mapping):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SLOT_CONTEXT_INVALID")
        metadata = descriptor.get("metadata")
        if not isinstance(metadata, list) or len(metadata) != 1 or not isinstance(metadata[0], Mapping):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SLOT_CONTEXT_INVALID")
        archive_path = metadata[0].get("archive_path")
        if not isinstance(archive_path, str) or not archive_path:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SLOT_CONTEXT_INVALID")
        yield SimpleNamespace(path=Path(archive_path))

    def publish_bytes(self, *, kind: str, data: bytes, content_type: str, expected_sha256: str) -> dict[str, str]:
        if not isinstance(kind, str) or not kind or content_type not in {"application/json", "audio/wav", "video/mp4"}:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_CONTRACT_PUBLISH_INVALID")
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_CONTRACT_PUBLISH_INVALID")
        artifact_id = f"{kind}-{expected_sha256[:16]}"
        suffix = {"application/json": ".json", "audio/wav": ".wav", "video/mp4": ".mp4"}[content_type]
        path = self.contracts_dir / f"{artifact_id}{suffix}"
        path.write_bytes(data)
        artifact = {
            "artifact_id": artifact_id,
            "kind": kind,
            "path": str(path),
            "sha256": expected_sha256,
        }
        self._artifacts[:] = [item for item in self._artifacts if item.get("kind") != kind]
        self._artifacts.append(artifact)
        return {key: str(artifact[key]) for key in ("artifact_id", "kind", "sha256")}

    @property
    def artifacts(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(item) for item in self._artifacts)

    @contextmanager
    def materialize_artifact(self, kind: str, *, sha256: str | None = None, artifact_id: str | None = None):
        matches = [
            item
            for item in self._artifacts
            if item.get("kind") == kind and item.get("sha256") == sha256 and item.get("artifact_id") == artifact_id
        ]
        if len(matches) != 1:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_CONTRACT_ARTIFACT_MISSING")
        yield SimpleNamespace(path=Path(str(matches[0]["path"])))


class _StaticStagePort:
    def __init__(self, result: Mapping[str, object]) -> None:
        self._result = dict(result)

    def run(self, *, context: object, input_artifacts: list[Mapping[str, object]]) -> Mapping[str, object]:
        del context, input_artifacts
        return self._result


class _LocalProviderAdapter:
    """Deterministic local provider used only to exercise the StagePort lineage."""

    def __init__(self, *, source_video: Path) -> None:
        self._source_video = Path(source_video)
        self._requests: list[Mapping[str, object]] = []

    def capability_identity(self) -> dict[str, str]:
        return {
            "implementation": "background_music_local_mvp.LocalProviderAdapter",
            "version": "1",
            "sha256": "d" * 64,
        }

    def create_video(self, request: Mapping[str, object]) -> dict[str, str]:
        self._requests.append(dict(request))
        return {"task_id": "local-background-music-task", "status": "submitted"}

    def lookup(self, intent: Mapping[str, object]) -> dict[str, object]:
        if intent.get("taskId") != "local-background-music-task" or len(self._requests) != 1:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_PROVIDER_LOOKUP_INVALID")
        return {
            "task_id": "local-background-music-task",
            "status": "completed",
            "output": {"kind": "local_source_video_passthrough"},
        }

    def download(self, task_id: str, destination: str) -> dict[str, object]:
        if task_id != "local-background-music-task" or not self._source_video.is_file():
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_PROVIDER_DOWNLOAD_INVALID")
        data = self._source_video.read_bytes()
        Path(destination).write_bytes(data)
        return {"sha256": _sha256_bytes(data), "size_bytes": len(data)}


class DevelopmentOnlyBackgroundMusicMvpHarness:
    """Run a deterministic local media loop without a network Provider or TTS."""

    def __init__(self, *, run_root: Path) -> None:
        self._run_root = Path(run_root)

    def run(
        self,
        *,
        source_video: Path,
        background_music: Path,
        visible_singer_regions: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        console_job = self._create_console_job(source_video=source_video, background_music=background_music)
        source = _mapping(console_job, "inputs")["source_video"]
        uploaded = self._background_music_input(_mapping(console_job, "inputs")["background_music"])
        source_path = Path(str(source["archive_path"]))
        uploaded_path = Path(str(uploaded["archive_path"]))
        source_pcm = self._decode_pcm(source_path)
        source_analysis = self._analyze_source_audio_activity(source_path, source_pcm)
        uploaded_pcm = self._decode_pcm(uploaded_path)
        contract = self._build_timeline_contract(
            source_analysis=source_analysis,
            uploaded_pcm=uploaded_pcm,
            visible_singer_regions=visible_singer_regions,
        )
        context = self._stage_context(source=source, uploaded=uploaded)
        timeline_result = BackgroundMusicStagePort(
            stage="analyze_dynamics",
            delegate=_StaticStagePort({"stage": "canonical_analyze_dynamics"}),
            music_delegate=_StaticStagePort(
                {"background_music_evidence": {"music_timeline_contract": contract}}
            ),
        ).run(context=context, input_artifacts=[])
        timeline_evidence = _evidence(timeline_result)
        timeline_reference = _mapping(timeline_evidence, "music_timeline_contract_artifact")
        frozen_contract = self._materialize_frozen_contract(context=context, reference=timeline_reference)
        audio_asset_receipt = self._audio_asset_receipt(uploaded)
        performance_line_contract = self._performance_line_contract(
            contract=frozen_contract,
            visible_singer_regions=visible_singer_regions,
        )
        if performance_line_contract is not None:
            self._publish_json_artifact(
                context=context,
                kind="performance_line_contract",
                payload=performance_line_contract,
            )
        user_confirmed_intent = (
            "verified_singing" if performance_line_contract is not None else "background_music_replacement"
        )
        execution_contract = compile_background_music_execution_contract(
            uploaded_audio=uploaded,
            music_timeline_contract=frozen_contract,
            audio_asset_receipt=audio_asset_receipt,
            user_confirmed_intent=user_confirmed_intent,
            performance_line_contract=performance_line_contract,
        )
        provider_payload = _mapping(execution_contract, "provider_payload")
        BackgroundMusicStagePort(
            stage="compile_seedance20_prompt",
            delegate=_StaticStagePort({"stage": "canonical_compile_seedance20_prompt"}),
            music_delegate=_StaticStagePort(
                {
                    "background_music_evidence": {
                        "music_execution_contract": execution_contract,
                        "provider_payload": provider_payload,
                    }
                }
            ),
        ).run(context=context, input_artifacts=[])
        audit_result = BackgroundMusicStagePort(
            stage="audit_seedance_request",
            delegate=_StaticStagePort({"stage": "canonical_audit_seedance_request"}),
            music_delegate=_StaticStagePort(
                {
                    "background_music_evidence": {
                        "audio_asset_receipt": audio_asset_receipt,
                        "provider_payload": provider_payload,
                        "music_execution_contract": execution_contract,
                    }
                }
            ),
        ).run(context=context, input_artifacts=[])
        audit_evidence = _evidence(audit_result)
        provider_execution, provider_evidence = self._run_provider_stages(
            context=context,
            source_video=source_path,
        )
        final_audio_path, final_video_path, mix_receipt = self._mix_exact_uploaded_fragments(
            source_analysis=source_analysis,
            source_video=source_path,
            uploaded=uploaded,
            uploaded_pcm=uploaded_pcm,
            contract=frozen_contract,
        )
        final_video_sha256 = _sha256_file(final_video_path)
        final_audio_reference = self._publish_media_artifact(
            context=context,
            kind="final_audio",
            path=final_audio_path,
            content_type="audio/wav",
        )
        final_video_reference = self._publish_media_artifact(
            context=context,
            kind="final_video",
            path=final_video_path,
            content_type="video/mp4",
        )
        singing_qa = self._singing_qa(
            contract=frozen_contract,
            uploaded=uploaded,
            final_video_sha256=final_video_sha256,
            verified_singing=execution_contract["mode"] == "verified_singing",
        )
        mix_receipt = self._bind_singing_receipts(mix_receipt=mix_receipt, singing_qa=singing_qa)
        provider_task_id = _mapping(provider_evidence, "provider_submission_receipt")["provider_task_id"]
        provider_output_artifact = _mapping(provider_evidence, "provider_output_artifact")
        mix_receipt.update(
            {
                "mode": execution_contract["mode"],
                "forbidden_operations": execution_contract["forbidden_operations"],
                "final_audio_artifact": final_audio_reference,
                "final_video_artifact": final_video_reference,
                "final_video_sha256": final_video_sha256,
                "provider_output_artifact": provider_output_artifact,
                "final_video_provider_output_artifact": provider_output_artifact,
                "provider_task_id": provider_task_id,
                "final_video_provider_task_id": provider_task_id,
            }
        )
        mix_evidence = {
            "music_timeline_contract": frozen_contract,
            "music_timeline_contract_artifact": timeline_reference,
            "music_execution_contract": execution_contract,
            "provider_payload": provider_payload,
            "music_execution_audit_receipt_artifact": _mapping(
                audit_evidence, "music_execution_audit_receipt_artifact"
            ),
            "music_execution_audit_binding": _mapping(audit_evidence, "music_execution_audit_binding"),
            "provider_submission_receipt": _mapping(provider_evidence, "provider_submission_receipt"),
            "provider_submission_artifact": _mapping(provider_evidence, "provider_submission_artifact"),
            "provider_output_artifact": provider_output_artifact,
            "mix_receipt": mix_receipt,
        }
        BackgroundMusicStagePort(
            stage="splice_timeline",
            delegate=_StaticStagePort({"stage": "canonical_splice_timeline"}),
            music_delegate=_StaticStagePort({"background_music_evidence": mix_evidence}),
        ).run(context=context, input_artifacts=[])
        BackgroundMusicStagePort(
            stage="run_qc",
            delegate=_StaticStagePort({"stage": "canonical_run_qc"}),
            music_delegate=_StaticStagePort(
                {
                    "background_music_evidence": {
                        **mix_evidence,
                        "singing_qa": singing_qa,
                    }
                }
            ),
        ).run(context=context, input_artifacts=[])
        self._write_json("provider/provider_payload.json", provider_payload)
        self._write_json("provider/execution.json", provider_execution)
        self._write_json("receipts/audio_asset.json", audio_asset_receipt)
        self._write_json("receipts/final_mix.json", mix_receipt)
        self._write_json("qa/singing_qa.json", singing_qa)
        return {
            "environment": LOCAL_MVP_ENVIRONMENT,
            "route": "background_music_replace_sing",
            "language_only": False,
            "tts_used": False,
            "intake": {"source_video": source, "background_music": uploaded},
            "console_job": console_job,
            "source_analysis": source_analysis,
            "audio_asset_receipt": audio_asset_receipt,
            "provider_payload": provider_payload,
            "provider_execution": provider_execution,
            "music_execution_contract": execution_contract,
            "music_execution_audit_receipt_artifact": mix_evidence[
                "music_execution_audit_receipt_artifact"
            ],
            "provider_output_artifact": provider_output_artifact,
            "music_timeline_contract": frozen_contract,
            "music_timeline_contract_artifact": timeline_reference,
            "music_timeline_contract_sha256": _sha256_bytes(_canonical_json_bytes(frozen_contract)),
            "mix_receipt": mix_receipt,
            "final_audio_path": str(final_audio_path),
            "final_video_path": str(final_video_path),
            "final_video_sha256": final_video_sha256,
            "singing_qa": singing_qa,
            "limitations": [
                "deterministic local StagePort and Provider harness only",
                "no commercial Provider request or generated video was submitted",
                "visible-singer receipts validate contract wiring, not production media QA",
            ],
        }

    @staticmethod
    def _materialize_frozen_contract(
        *,
        context: _LocalStageContext,
        reference: Mapping[str, object],
    ) -> dict[str, object]:
        artifact_id = reference.get("artifact_id")
        digest = reference.get("sha256")
        matching = [artifact for artifact in context.artifacts if artifact.get("kind") == "music_timeline_contract"]
        if len(matching) != 1 or not isinstance(artifact_id, str) or not isinstance(digest, str):
            raise DevelopmentOnlyBackgroundMusicMvpError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        try:
            with context.materialize_artifact(
                "music_timeline_contract",
                artifact_id=artifact_id,
                sha256=digest,
            ) as materialized:
                encoded = materialized.path.read_bytes()
            decoded = json.loads(encoded)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise DevelopmentOnlyBackgroundMusicMvpError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED") from error
        if hashlib.sha256(encoded).hexdigest() != digest or not isinstance(decoded, dict):
            raise DevelopmentOnlyBackgroundMusicMvpError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH")
        return decoded

    def _create_console_job(self, *, source_video: Path, background_music: Path) -> dict[str, object]:
        source = Path(source_video)
        music = Path(background_music)
        if not source.is_file() or not music.is_file():
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_INPUT_MISSING")
        console_root = self._run_root / "console"
        console_root.mkdir(parents=True, exist_ok=True)
        console_dir = Path(__file__).resolve().parents[2] / "usfr-local-console"
        script = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "from app.jobs import FileJobStore\n"
            "from app.slots import build_intake, validate_intake\n"
            "store = FileJobStore(Path(sys.argv[1]))\n"
            "job = store.create(validate_intake(build_intake(source_video=Path(sys.argv[2]), background_music=Path(sys.argv[3]))))\n"
            "payload = job.as_dict()\n"
            "job_dir = store.job_dir(job.job_id)\n"
            "for record in payload['inputs'].values():\n"
            "    if isinstance(record, dict) and record.get('relative_path'):\n"
            "        record['archive_path'] = str(job_dir / record['relative_path'])\n"
            "print(json.dumps({**payload, 'job_dir': str(job_dir)}, ensure_ascii=True))\n"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-c", script, str(console_root), str(source), str(music)],
                check=True,
                capture_output=True,
                cwd=console_dir,
                text=True,
            )
            payload = json.loads(completed.stdout)
        except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as error:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_CONSOLE_INTAKE_FAILED") from error
        if not isinstance(payload, dict) or payload.get("route") != "composite_replication":
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_CONSOLE_ROUTE_INVALID")
        inputs = payload.get("inputs")
        if not isinstance(inputs, Mapping) or set(("source_video", "background_music")) - set(inputs):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_CONSOLE_INTAKE_FAILED")
        return payload

    def _background_music_input(self, record: object) -> dict[str, object]:
        if not isinstance(record, Mapping):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_CONSOLE_INTAKE_FAILED")
        archive_path = record.get("archive_path")
        if not isinstance(archive_path, str) or not Path(archive_path).is_file():
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_CONSOLE_INTAKE_FAILED")
        content_type = str(record.get("mime_type") or _content_type(Path(archive_path))).lower()
        if not content_type.startswith("audio/"):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_INPUT_TYPE_INVALID")
        receipt = dict(record)
        receipt.update(
            {
                "content_type": content_type,
                "duration_seconds": self._probe_duration(Path(archive_path)),
                "object_key": str(record.get("relative_path") or ""),
                "size_bytes": int(record.get("byte_count") or 0),
                "status": "completed",
                "provider_route": "seedance_audio_reference",
                "provider_asset_type": "Audio",
                "provider_content_item_type": "audio_url",
                "prompt_reference_tag": "@Audio1",
                "forbidden_provider_field": "reference_audios",
                "final_audio_source": "uploaded_exact_audio",
                "allow_loop_or_time_stretch": False,
            }
        )
        return receipt

    def _stage_context(self, *, source: Mapping[str, object], uploaded: Mapping[str, object]) -> _LocalStageContext:
        del source
        manifest = {
            "admission": {"language_only": False},
            "extensions": {"background_music": dict(uploaded)},
            "slots": {},
        }
        contracts_dir = self._run_root / "contracts"
        contracts_dir.mkdir(parents=True, exist_ok=True)
        return _LocalStageContext(snapshot=_Snapshot(slots_manifest=manifest), contracts_dir=contracts_dir, _artifacts=[])

    def _analyze_source_audio_activity(self, source_video: Path, source_pcm: _DecodedPcm) -> dict[str, object]:
        metadata = self._probe_video(source_video)
        frame_rate = Fraction(str(metadata["frame_rate"]))
        frame_count = int(metadata["frame_count"])
        active_frames: list[int] = []
        for frame in range(frame_count):
            start_sample = round(frame * source_pcm.sample_rate / float(frame_rate))
            end_sample = round((frame + 1) * source_pcm.sample_rate / float(frame_rate))
            if _pcm_rms(
                source_pcm.data[
                    start_sample * source_pcm.bytes_per_frame : end_sample * source_pcm.bytes_per_frame
                ],
                sample_format=source_pcm.sample_format,
            ) >= _AUDIO_ACTIVITY_RMS_THRESHOLD:
                active_frames.append(frame)
        windows = _contiguous_frame_windows(active_frames)
        if not windows:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SOURCE_MUSIC_ACTIVITY_REQUIRED")
        return {
            "audio_activity_windows": windows,
            "classification": "development-only-audio-activity-proxy",
            "duration_seconds": float(metadata["duration_seconds"]),
            "frame_count": frame_count,
            "frame_rate": str(metadata["frame_rate"]),
        }

    @staticmethod
    def _run_provider_stages(
        *,
        context: _LocalStageContext,
        source_video: Path,
    ) -> tuple[dict[str, object], Mapping[str, object]]:
        provider = _LocalProviderAdapter(source_video=source_video)
        submit = BackgroundMusicStagePort(
            stage="submit_provider_video",
            delegate=_StaticStagePort({"stage": "canonical_submit_provider_video"}),
            music_delegate=_StaticStagePort({"background_music_evidence": {}}),
            provider_adapter=provider,
        ).run(context=context, input_artifacts=[])
        waited = BackgroundMusicStagePort(
            stage="wait_provider_video",
            delegate=_StaticStagePort({"stage": "canonical_wait_provider_video"}),
            music_delegate=_StaticStagePort({"background_music_evidence": {}}),
            provider_adapter=provider,
        ).run(context=context, input_artifacts=[])
        receipt = {"status": "completed", "output": "local_source_video_passthrough"}
        return (
            {
                "environment": LOCAL_MVP_ENVIRONMENT,
                "submit_provider_video": dict(receipt),
                "wait_provider_video": dict(receipt),
            },
            _evidence(waited),
        )

    def _build_timeline_contract(
        self,
        *,
        source_analysis: Mapping[str, object],
        uploaded_pcm: _DecodedPcm,
        visible_singer_regions: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        frame_rate = Fraction(str(source_analysis["frame_rate"]))
        windows = source_analysis.get("audio_activity_windows")
        frame_count = source_analysis.get("frame_count")
        if not isinstance(windows, list) or isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SOURCE_MUSIC_ACTIVITY_REQUIRED")
        output_duration_ms = round(frame_count * 1000 / float(frame_rate))
        output_duration_samples = round(frame_count * uploaded_pcm.sample_rate / float(frame_rate))
        uploaded_cursor_samples = 0
        contract_windows: list[dict[str, object]] = []
        for raw_window in windows:
            start_frame = raw_window.get("source_start_frame") if isinstance(raw_window, Mapping) else None
            end_frame = raw_window.get("source_end_frame") if isinstance(raw_window, Mapping) else None
            if not isinstance(start_frame, int) or not isinstance(end_frame, int) or end_frame <= start_frame:
                raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SOURCE_MUSIC_ACTIVITY_REQUIRED")
            window_samples = round(end_frame * uploaded_pcm.sample_rate / float(frame_rate)) - round(
                start_frame * uploaded_pcm.sample_rate / float(frame_rate)
            )
            uploaded_end_samples = uploaded_cursor_samples + window_samples
            if uploaded_end_samples * uploaded_pcm.bytes_per_frame > len(uploaded_pcm.data):
                raise DevelopmentOnlyBackgroundMusicMvpError("BACKGROUND_MUSIC_DURATION_INSUFFICIENT")
            uploaded_start_ms = round(uploaded_cursor_samples * 1000 / uploaded_pcm.sample_rate)
            uploaded_end_ms = round(uploaded_end_samples * 1000 / uploaded_pcm.sample_rate)
            output_start_ms = round(start_frame * 1000 / float(frame_rate))
            output_end_ms = round(end_frame * 1000 / float(frame_rate))
            source_entry = {
                "source_start_ms": uploaded_start_ms,
                "source_end_ms": uploaded_start_ms,
                "output_start_ms": output_start_ms,
                "output_end_ms": output_start_ms,
            }
            source_exit = {
                "source_start_ms": uploaded_end_ms,
                "source_end_ms": uploaded_end_ms,
                "output_start_ms": output_end_ms,
                "output_end_ms": output_end_ms,
            }
            contract_windows.append(
                {
                    "source_start_frame": start_frame,
                    "source_end_frame": end_frame,
                    "output_start_frame": start_frame,
                    "output_end_frame": end_frame,
                    "source_start_ms": output_start_ms,
                    "source_end_ms": output_end_ms,
                    "uploaded_start_ms": uploaded_start_ms,
                    "uploaded_end_ms": uploaded_end_ms,
                    "output_start_ms": output_start_ms,
                    "output_end_ms": output_end_ms,
                    "uploaded_start_sample": uploaded_cursor_samples,
                    "uploaded_end_sample": uploaded_end_samples,
                    "output_start_sample": round(start_frame * uploaded_pcm.sample_rate / float(frame_rate)),
                    "output_end_sample": round(end_frame * uploaded_pcm.sample_rate / float(frame_rate)),
                    "source_entry": source_entry,
                    "source_exit": source_exit,
                    "fade_in": dict(source_entry),
                    "fade_out": dict(source_exit),
                    "silence_before": dict(source_entry),
                    "silence_after": dict(source_exit),
                    "transition": dict(source_exit),
                }
            )
            uploaded_cursor_samples = uploaded_end_samples
        meaningful_silence: list[dict[str, int]] = []
        previous_end_ms = 0
        for window in contract_windows:
            start_ms = window["output_start_ms"]
            if start_ms > previous_end_ms:
                meaningful_silence.append(
                    {"output_start_ms": previous_end_ms, "output_end_ms": start_ms}
                )
            previous_end_ms = window["output_end_ms"]
        if previous_end_ms < output_duration_ms:
            meaningful_silence.append(
                {"output_start_ms": previous_end_ms, "output_end_ms": output_duration_ms}
            )
        return {
            "visible_singer_regions": [dict(region) for region in visible_singer_regions],
            "windows": contract_windows,
            "meaningful_silence_output_intervals": meaningful_silence,
            "output_duration_ms": output_duration_ms,
            "output_duration_samples": output_duration_samples,
        }

    @staticmethod
    def _performance_line_contract(
        *,
        contract: Mapping[str, object],
        visible_singer_regions: Sequence[Mapping[str, object]],
    ) -> dict[str, object] | None:
        windows = contract.get("windows")
        if not isinstance(windows, list):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_TIMELINE_INVALID")
        visible = [region for region in visible_singer_regions if region.get("visible") is True]
        if not visible:
            return None
        cuts: list[dict[str, object]] = []
        for index, region in enumerate(visible, start=1):
            region_id = region.get("region_id")
            lyrics = region.get("lyrics")
            start_frame = region.get("source_start_frame")
            end_frame = region.get("source_end_frame")
            if (
                not isinstance(region_id, str)
                or not region_id
                or not isinstance(lyrics, str)
                or not lyrics.strip()
                or isinstance(start_frame, bool)
                or isinstance(end_frame, bool)
                or not isinstance(start_frame, int)
                or not isinstance(end_frame, int)
                or end_frame <= start_frame
            ):
                return None
            matching_window = next(
                (
                    window
                    for window in windows
                    if isinstance(window, Mapping)
                    and window.get("source_start_frame") <= start_frame
                    and end_frame <= window.get("source_end_frame")
                ),
                None,
            )
            if not isinstance(matching_window, Mapping):
                return None
            source_start_ms = matching_window.get("source_start_ms")
            source_end_ms = matching_window.get("source_end_ms")
            if not isinstance(source_start_ms, int) or not isinstance(source_end_ms, int):
                raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_TIMELINE_INVALID")
            evidence_sha256 = _sha256_bytes(_canonical_json_bytes(dict(region)))
            cuts.append(
                {
                    "line_id": f"local-singing-{index}",
                    "cut_id": region_id,
                    "content_type": "sung",
                    "speaker_assignment": {
                        "status": "CONFIRMED",
                        "speaker_id": f"CHARACTER_{index}",
                        "evidence_sha256": evidence_sha256,
                    },
                    "source_time": {"start_ms": source_start_ms, "end_ms": source_end_ms},
                    "segment_time": {"start_ms": source_start_ms, "end_ms": source_end_ms},
                    "performance_mode": "singing",
                    "lyric_status": "verified",
                    "exact_sung_text": lyrics.strip(),
                    "beat_anchors_ms": [source_start_ms + max(1, (source_end_ms - source_start_ms) // 2)],
                    "lip_sync": {
                        "face_visibility": "locked medium close-up, face visible",
                        "articulation": "clear syllable-by-syllable articulation",
                        "end_state": "mouth closes at the line end",
                    },
                    "action": {
                        "start": "hold the approved opening pose",
                        "beat_action": "make one small beat-synced gesture",
                        "end": "hold the approved end pose",
                    },
                    "expression": {
                        "start": "neutral focus",
                        "peak": "engaged singing expression",
                        "end": "settled expression",
                    },
                    "emotion": "engaged",
                    "end_pose": "face remains visible in the approved end pose",
                    "criticality": "HIGH",
                }
            )
        return {"contract": "performance-line/v1", "cuts": cuts}

    @staticmethod
    def _publish_json_artifact(
        *,
        context: _LocalStageContext,
        kind: str,
        payload: Mapping[str, object],
    ) -> dict[str, str]:
        data = _canonical_json_bytes(payload)
        reference = context.publish_bytes(
            kind=kind,
            data=data,
            content_type="application/json",
            expected_sha256=_sha256_bytes(data),
        )
        return {**reference, "kind": kind}

    @staticmethod
    def _publish_media_artifact(
        *,
        context: _LocalStageContext,
        kind: str,
        path: Path,
        content_type: str,
    ) -> dict[str, str]:
        data = Path(path).read_bytes()
        reference = context.publish_bytes(
            kind=kind,
            data=data,
            content_type=content_type,
            expected_sha256=_sha256_bytes(data),
        )
        return {**reference, "kind": kind}

    def _audio_asset_receipt(self, uploaded: Mapping[str, object]) -> dict[str, object]:
        digest = str(uploaded["sha256"])
        return {
            "AssetType": "Audio",
            "asset_type": "Audio",
            "asset_uri": f"asset://asset-{digest[:16]}",
            "status": "active",
            "uploaded_audio_sha256": digest,
        }

    @staticmethod
    def _provider_payload(audio_asset_receipt: Mapping[str, object]) -> dict[str, object]:
        asset_uri = str(audio_asset_receipt["asset_uri"])
        return {
            "content": [
                {
                    "text": "Use @Audio1 as the uploaded-song reference. Preserve the frozen frame windows without looping, time stretch, pitch shift, or generated replacement.",
                    "type": "text",
                },
                {
                    "audio_url": {"url": asset_uri},
                    "role": "reference_audio",
                    "type": "audio_url",
                },
            ],
            "model": "seedance-2.0",
        }

    def _mix_exact_uploaded_fragments(
        self,
        *,
        source_analysis: Mapping[str, object],
        source_video: Path,
        uploaded: Mapping[str, object],
        uploaded_pcm: _DecodedPcm,
        contract: Mapping[str, object],
    ) -> tuple[Path, Path, dict[str, object]]:
        frame_rate = Fraction(str(source_analysis["frame_rate"]))
        frame_count = int(source_analysis["frame_count"])
        final_pcm = bytearray(
            round(frame_count * uploaded_pcm.sample_rate / float(frame_rate)) * uploaded_pcm.bytes_per_frame
        )
        receipts: list[dict[str, object]] = []
        windows = contract.get("windows")
        if not isinstance(windows, list):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_TIMELINE_INVALID")
        for window in windows:
            if not isinstance(window, Mapping):
                raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_TIMELINE_INVALID")
            start_frame = int(window["output_start_frame"])
            end_frame = int(window["output_end_frame"])
            output_start_sample = round(start_frame * uploaded_pcm.sample_rate / float(frame_rate))
            output_end_sample = round(end_frame * uploaded_pcm.sample_rate / float(frame_rate))
            fragment_samples = output_end_sample - output_start_sample
            uploaded_start_sample = window.get("uploaded_start_sample")
            uploaded_end_sample = window.get("uploaded_end_sample")
            if (
                isinstance(uploaded_start_sample, bool)
                or isinstance(uploaded_end_sample, bool)
                or not isinstance(uploaded_start_sample, int)
                or not isinstance(uploaded_end_sample, int)
                or uploaded_end_sample - uploaded_start_sample != fragment_samples
                or round(uploaded_start_sample * 1000 / uploaded_pcm.sample_rate) != window.get("uploaded_start_ms")
                or round(uploaded_end_sample * 1000 / uploaded_pcm.sample_rate) != window.get("uploaded_end_ms")
            ):
                raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_TIMELINE_INVALID")
            fragment = uploaded_pcm.data[
                uploaded_start_sample * uploaded_pcm.bytes_per_frame : uploaded_end_sample * uploaded_pcm.bytes_per_frame
            ]
            if len(fragment) != fragment_samples * uploaded_pcm.bytes_per_frame:
                raise DevelopmentOnlyBackgroundMusicMvpError("BACKGROUND_MUSIC_DURATION_INSUFFICIENT")
            final_pcm[
                output_start_sample * uploaded_pcm.bytes_per_frame : output_end_sample * uploaded_pcm.bytes_per_frame
            ] = fragment
            receipts.append(
                {
                    **dict(window),
                    "fragment_sha256": _sha256_bytes(fragment),
                    "generated_substitute": False,
                    "looped": False,
                    "pitch_shifted": False,
                    "time_stretched": False,
                }
            )
        self._verify_final_pcm(
            final_pcm=bytes(final_pcm),
            receipts=receipts,
            frame_rate=frame_rate,
            uploaded_pcm=uploaded_pcm,
        )
        silence_window_receipts = self._record_final_audio_evidence(
            final_pcm=bytes(final_pcm),
            receipts=receipts,
            frame_count=frame_count,
            frame_rate=frame_rate,
            uploaded_pcm=uploaded_pcm,
        )
        final_audio_path = self._run_root / "mix" / "final_uploaded_song_mix.wav"
        final_audio_path.parent.mkdir(parents=True, exist_ok=True)
        raw_audio_path = self._run_root / "mix" / f"final_uploaded_song_mix.{uploaded_pcm.sample_format}"
        raw_audio_path.write_bytes(final_pcm)
        self._run_command(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                uploaded_pcm.sample_format,
                "-ar",
                str(uploaded_pcm.sample_rate),
                "-ac",
                str(uploaded_pcm.channels),
                "-i",
                str(raw_audio_path),
                "-c:a",
                uploaded_pcm.codec,
                str(final_audio_path),
            ]
        )
        final_video_path = self._mux_final_video(
            source_video=source_video,
            final_audio_path=final_audio_path,
            uploaded_pcm=uploaded_pcm,
        )
        if self._decode_pcm(final_video_path).data != bytes(final_pcm):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_FINAL_VIDEO_AUDIO_MISMATCH")
        for receipt in receipts:
            uploaded_start_sample = int(receipt["uploaded_start_sample"])
            uploaded_end_sample = int(receipt["uploaded_end_sample"])
            output_start_sample = round(int(receipt["output_start_frame"]) * uploaded_pcm.sample_rate / float(frame_rate))
            output_end_sample = round(int(receipt["output_end_frame"]) * uploaded_pcm.sample_rate / float(frame_rate))
            uploaded_start_ms = int(receipt["uploaded_start_ms"])
            uploaded_end_ms = int(receipt["uploaded_end_ms"])
            output_start_ms = int(receipt["output_start_ms"])
            output_end_ms = int(receipt["output_end_ms"])
            uploaded_pcm_fragment = uploaded_pcm.data[
                uploaded_start_sample * uploaded_pcm.bytes_per_frame : uploaded_end_sample * uploaded_pcm.bytes_per_frame
            ]
            final_pcm_fragment = bytes(final_pcm)[
                output_start_sample * uploaded_pcm.bytes_per_frame : output_end_sample * uploaded_pcm.bytes_per_frame
            ]
            if uploaded_pcm_fragment != final_pcm_fragment:
                raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_EXACT_FRAGMENT_MISMATCH")
            fragment_sha256 = _sha256_bytes(uploaded_pcm_fragment)
            receipt.update(
                {
                    "fragment_sha256": fragment_sha256,
                    "uploaded_fragment_sha256": fragment_sha256,
                    "final_audio_fragment_sha256": fragment_sha256,
                    "pcm_fragment_sha256": fragment_sha256,
                    "atempo_applied": False,
                    "speed_changed": False,
                    "silence_padded": False,
                }
            )
        pcm_format = {
            "sample_rate": uploaded_pcm.sample_rate,
            "channels": uploaded_pcm.channels,
            "sample_format": uploaded_pcm.sample_format,
        }
        return final_audio_path, final_video_path, {
            "final_audio_sha256": _sha256_file(final_audio_path),
            "passed": True,
            "uploaded_audio_sha256": uploaded["sha256"],
            "window_receipts": receipts,
            "silence_window_receipts": silence_window_receipts,
            "uploaded_pcm_format": pcm_format,
            "final_audio_pcm_format": pcm_format,
        }

    @staticmethod
    def _verify_final_pcm(
        *,
        final_pcm: bytes,
        receipts: Sequence[Mapping[str, object]],
        frame_rate: Fraction,
        uploaded_pcm: _DecodedPcm,
    ) -> None:
        for receipt in receipts:
            start_sample = round(int(receipt["output_start_frame"]) * uploaded_pcm.sample_rate / float(frame_rate))
            end_sample = round(int(receipt["output_end_frame"]) * uploaded_pcm.sample_rate / float(frame_rate))
            uploaded_start_sample = int(receipt["uploaded_start_sample"])
            uploaded_end_sample = int(receipt["uploaded_end_sample"])
            expected = uploaded_pcm.data[
                uploaded_start_sample * uploaded_pcm.bytes_per_frame : uploaded_end_sample * uploaded_pcm.bytes_per_frame
            ]
            observed = final_pcm[start_sample * uploaded_pcm.bytes_per_frame : end_sample * uploaded_pcm.bytes_per_frame]
            if expected != observed or _sha256_bytes(expected) != receipt.get("fragment_sha256"):
                raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_EXACT_FRAGMENT_MISMATCH")

    @staticmethod
    def _record_final_audio_evidence(
        *,
        final_pcm: bytes,
        receipts: list[dict[str, object]],
        frame_count: int,
        frame_rate: Fraction,
        uploaded_pcm: _DecodedPcm,
    ) -> list[dict[str, object]]:
        silence_receipts: list[dict[str, object]] = []
        prior_end_frame = 0
        for receipt in receipts:
            start_frame = int(receipt["output_start_frame"])
            end_frame = int(receipt["output_end_frame"])
            start_sample = round(start_frame * uploaded_pcm.sample_rate / float(frame_rate))
            end_sample = round(end_frame * uploaded_pcm.sample_rate / float(frame_rate))
            receipt["final_audio_fragment_sha256"] = _sha256_bytes(
                final_pcm[start_sample * uploaded_pcm.bytes_per_frame : end_sample * uploaded_pcm.bytes_per_frame]
            )
            if start_frame > prior_end_frame:
                silence_receipts.append(
                    DevelopmentOnlyBackgroundMusicMvpHarness._silence_receipt(
                        final_pcm=final_pcm,
                        start_frame=prior_end_frame,
                        end_frame=start_frame,
                        frame_rate=frame_rate,
                        uploaded_pcm=uploaded_pcm,
                    )
                )
            prior_end_frame = end_frame
        if prior_end_frame < frame_count:
            silence_receipts.append(
                DevelopmentOnlyBackgroundMusicMvpHarness._silence_receipt(
                    final_pcm=final_pcm,
                    start_frame=prior_end_frame,
                    end_frame=frame_count,
                    frame_rate=frame_rate,
                    uploaded_pcm=uploaded_pcm,
                )
            )
        if any(receipt["all_zero"] is not True for receipt in silence_receipts):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SOURCE_PAUSE_MISMATCH")
        return silence_receipts

    @staticmethod
    def _silence_receipt(
        *,
        final_pcm: bytes,
        start_frame: int,
        end_frame: int,
        frame_rate: Fraction,
        uploaded_pcm: _DecodedPcm,
    ) -> dict[str, object]:
        start_sample = round(start_frame * uploaded_pcm.sample_rate / float(frame_rate))
        end_sample = round(end_frame * uploaded_pcm.sample_rate / float(frame_rate))
        fragment = final_pcm[start_sample * uploaded_pcm.bytes_per_frame : end_sample * uploaded_pcm.bytes_per_frame]
        return {
            "output_start_frame": start_frame,
            "output_end_frame": end_frame,
            "all_zero": not any(fragment),
        }

    def _mux_final_video(
        self,
        *,
        source_video: Path,
        final_audio_path: Path,
        uploaded_pcm: _DecodedPcm,
    ) -> Path:
        final_video_path = self._run_root / "mix" / "final_uploaded_song_mix.mov"
        self._run_command(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source_video),
                "-i",
                str(final_audio_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                uploaded_pcm.codec,
                "-shortest",
                str(final_video_path),
            ]
        )
        if not final_video_path.is_file():
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_FINAL_VIDEO_MISSING")
        return final_video_path

    @staticmethod
    def _singing_qa(
        *,
        contract: Mapping[str, object],
        uploaded: Mapping[str, object],
        final_video_sha256: str,
        verified_singing: bool,
    ) -> dict[str, object]:
        if not verified_singing:
            return {"status": "skipped", "reason": "no_lyric_lip_sync", "regions": []}
        regions = contract.get("visible_singer_regions")
        if not isinstance(regions, list):
            raise DevelopmentOnlyBackgroundMusicMvpError("SINGING_ALIGNMENT_REQUIRED")
        visible = [region for region in regions if isinstance(region, Mapping) and region.get("visible") is True]
        if not visible:
            return {"status": "skipped", "reason": "no_visible_singing_person", "regions": []}
        receipts = []
        for region in visible:
            region_id = region.get("region_id")
            lyrics = region.get("lyrics")
            start_frame = region.get("source_start_frame")
            end_frame = region.get("source_end_frame")
            if (
                not isinstance(region_id, str)
                or not region_id
                or not isinstance(lyrics, str)
                or not lyrics.strip()
                or not isinstance(start_frame, int)
                or not isinstance(end_frame, int)
                or end_frame <= start_frame
            ):
                raise DevelopmentOnlyBackgroundMusicMvpError("SINGING_ALIGNMENT_REQUIRED")
            phonemes = [character.upper() for character in lyrics if character.isalnum()]
            if not phonemes:
                raise DevelopmentOnlyBackgroundMusicMvpError("SINGING_ALIGNMENT_REQUIRED")
            alignment = {
                "final_video_sha256": final_video_sha256,
                "kind": "lyrics_phoneme_alignment",
                "lyrics": lyrics,
                "phonemes": phonemes,
                "region_id": region_id,
                "source_end_frame": end_frame,
                "source_start_frame": start_frame,
                "uploaded_audio": uploaded["sha256"],
            }
            lip_sync = {
                "final_video_sha256": final_video_sha256,
                "kind": "singing_lip_sync_qa",
                "phoneme_alignment_sha256": _sha256_bytes(_canonical_json_bytes(alignment)),
                "region_id": region_id,
                "source_end_frame": end_frame,
                "source_start_frame": start_frame,
            }
            alignment_digest = _sha256_bytes(
                _canonical_json_bytes(alignment)
            )
            lip_sync_digest = _sha256_bytes(
                _canonical_json_bytes(lip_sync)
            )
            receipts.append(
                {
                    "region_id": region_id,
                    "lyrics_phoneme_alignment": {**alignment, "passed": True, "receipt_sha256": alignment_digest},
                    "lip_sync_qa": {**lip_sync, "passed": True, "receipt_sha256": lip_sync_digest},
                }
            )
        return {"status": "passed", "mode": LOCAL_MVP_ENVIRONMENT, "regions": receipts}

    @staticmethod
    def _bind_singing_receipts(
        *,
        mix_receipt: Mapping[str, object],
        singing_qa: Mapping[str, object],
    ) -> dict[str, object]:
        status = singing_qa.get("status")
        regions = singing_qa.get("regions")
        if not isinstance(regions, list):
            raise DevelopmentOnlyBackgroundMusicMvpError("SINGING_FINAL_RECEIPT_REQUIRED")
        if status == "skipped":
            if singing_qa.get("reason") not in {"no_visible_singing_person", "no_lyric_lip_sync"} or regions:
                raise DevelopmentOnlyBackgroundMusicMvpError("SINGING_FINAL_RECEIPT_REQUIRED")
            return {**mix_receipt, "singing_receipts": []}
        if status != "passed":
            raise DevelopmentOnlyBackgroundMusicMvpError("SINGING_FINAL_RECEIPT_REQUIRED")
        receipts: list[dict[str, str]] = []
        for region in regions:
            if not isinstance(region, Mapping):
                raise DevelopmentOnlyBackgroundMusicMvpError("SINGING_FINAL_RECEIPT_REQUIRED")
            alignment = region.get("lyrics_phoneme_alignment")
            lip_sync = region.get("lip_sync_qa")
            region_id = region.get("region_id")
            if (
                not isinstance(region_id, str)
                or not isinstance(alignment, Mapping)
                or not isinstance(lip_sync, Mapping)
                or not isinstance(alignment.get("receipt_sha256"), str)
                or not isinstance(lip_sync.get("receipt_sha256"), str)
            ):
                raise DevelopmentOnlyBackgroundMusicMvpError("SINGING_FINAL_RECEIPT_REQUIRED")
            receipts.append(
                {
                    "alignment_receipt_sha256": alignment["receipt_sha256"],
                    "lip_sync_receipt_sha256": lip_sync["receipt_sha256"],
                    "region_id": region_id,
                }
            )
        return {**mix_receipt, "singing_receipts": receipts}

    def _probe_video(self, path: Path) -> dict[str, object]:
        payload = self._ffprobe(
            path,
            select_streams="v:0",
            entries="stream=r_frame_rate,avg_frame_rate,nb_read_frames:format=duration",
            count_frames=True,
        )
        streams = payload.get("streams")
        if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], Mapping):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SOURCE_VIDEO_INVALID")
        frame_rate = streams[0].get("r_frame_rate")
        average_frame_rate = streams[0].get("avg_frame_rate")
        frame_count = streams[0].get("nb_read_frames")
        format_data = payload.get("format")
        duration = format_data.get("duration") if isinstance(format_data, Mapping) else None
        try:
            if (
                Fraction(str(frame_rate)) <= 0
                or Fraction(str(frame_rate)) != Fraction(str(average_frame_rate))
                or int(frame_count) <= 0
                or float(duration) <= 0
            ):
                raise ValueError
        except (TypeError, ValueError, ZeroDivisionError) as error:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_SOURCE_VIDEO_INVALID") from error
        self._validate_constant_frame_pts(path=path, frame_rate=Fraction(str(frame_rate)), frame_count=int(frame_count))
        return {"duration_seconds": float(duration), "frame_rate": str(frame_rate), "frame_count": int(frame_count)}

    def _validate_constant_frame_pts(self, *, path: Path, frame_rate: Fraction, frame_count: int) -> None:
        payload = self._ffprobe(path, select_streams="v:0", entries="frame=best_effort_timestamp_time")
        frames = payload.get("frames")
        if not isinstance(frames, list) or len(frames) != frame_count:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_FRAME_PTS_REQUIRED")
        try:
            timestamps = [float(frame["best_effort_timestamp_time"]) for frame in frames if isinstance(frame, Mapping)]
        except (KeyError, TypeError, ValueError) as error:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_FRAME_PTS_REQUIRED") from error
        if len(timestamps) != frame_count:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_FRAME_PTS_REQUIRED")
        expected_interval = 1 / float(frame_rate)
        if any(abs(current - prior - expected_interval) > 0.000_01 for prior, current in zip(timestamps, timestamps[1:])):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_VARIABLE_FRAME_RATE_UNSUPPORTED")

    def _probe_duration(self, path: Path) -> float:
        payload = self._ffprobe(path, entries="format=duration")
        format_data = payload.get("format")
        duration = format_data.get("duration") if isinstance(format_data, Mapping) else None
        try:
            value = float(duration)
        except (TypeError, ValueError) as error:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_AUDIO_INVALID") from error
        if value <= 0:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_AUDIO_INVALID")
        return value

    def _decode_pcm(self, path: Path) -> _DecodedPcm:
        format_data = self._probe_audio_format(path)
        completed = self._run_command(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-vn",
                "-c:a",
                str(format_data["codec"]),
                "-f",
                str(format_data["sample_format"]),
                "pipe:1",
            ]
        )
        decoded = _DecodedPcm(data=completed.stdout, **format_data)
        if not decoded.data or len(decoded.data) % decoded.bytes_per_frame:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_AUDIO_INVALID")
        return decoded

    def _probe_audio_format(self, path: Path) -> dict[str, object]:
        payload = self._ffprobe(path, select_streams="a:0", entries="stream=sample_rate,channels,sample_fmt")
        streams = payload.get("streams")
        if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], Mapping):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_AUDIO_INVALID")
        try:
            sample_rate = int(streams[0].get("sample_rate"))
            channels = int(streams[0].get("channels"))
        except (TypeError, ValueError) as error:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_AUDIO_INVALID") from error
        if sample_rate <= 0 or channels <= 0:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_AUDIO_INVALID")
        input_format = streams[0].get("sample_fmt")
        output_format = _PCM_OUTPUT_FORMATS.get(str(input_format))
        if output_format is None:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_AUDIO_FORMAT_UNSUPPORTED")
        sample_format, codec, bytes_per_sample = output_format
        return {
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_format": sample_format,
            "codec": codec,
            "bytes_per_sample": bytes_per_sample,
        }

    def _ffprobe(
        self,
        path: Path,
        *,
        entries: str,
        select_streams: str | None = None,
        count_frames: bool = False,
    ) -> dict[str, object]:
        command = ["ffprobe", "-v", "error"]
        if count_frames:
            command.append("-count_frames")
        if select_streams is not None:
            command.extend(("-select_streams", select_streams))
        command.extend(("-show_entries", entries, "-of", "json", str(path)))
        completed = self._run_command(command)
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_MEDIA_PROBE_INVALID") from error
        if not isinstance(payload, dict):
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_MEDIA_PROBE_INVALID")
        return payload

    @staticmethod
    def _run_command(command: list[str]) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(command, check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_MEDIA_COMMAND_FAILED") from error

    def _write_json(self, relative_path: str, payload: Mapping[str, object]) -> None:
        path = self._run_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_canonical_json_bytes(payload))


def _mapping(value: Mapping[str, object], key: str) -> dict[str, object]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_STAGE_EVIDENCE_INVALID")
    return dict(item)


def _evidence(result: Mapping[str, object]) -> Mapping[str, object]:
    evidence = result.get("background_music_evidence")
    if not isinstance(evidence, Mapping):
        raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_STAGE_EVIDENCE_INVALID")
    return evidence


def _content_type(path: Path) -> str:
    values = {
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".mov": "video/quicktime",
        ".mp4": "video/mp4",
        ".wav": "audio/wav",
    }
    content_type = values.get(path.suffix.lower())
    if content_type is None:
        raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_INPUT_TYPE_INVALID")
    return content_type


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pcm_rms(data: bytes, *, sample_format: str) -> float:
    if not data:
        return 0.0
    spec = {
        "s16le": ("h", 32_768),
        "s32le": ("i", 2_147_483_648),
        "f32le": ("f", 1),
        "f64le": ("d", 1),
    }.get(sample_format)
    if spec is None:
        raise DevelopmentOnlyBackgroundMusicMvpError("LOCAL_MVP_AUDIO_FORMAT_UNSUPPORTED")
    code, normalizer = spec
    values = struct.iter_unpack(f"<{code}", data)
    total = 0.0
    count = 0
    for (sample,) in values:
        normalized = float(sample) / normalizer
        total += normalized * normalized
        count += 1
    if not count:
        return 0.0
    return math.sqrt(total / count)


def _contiguous_frame_windows(active_frames: Sequence[int]) -> list[dict[str, int]]:
    if not active_frames:
        return []
    windows: list[dict[str, int]] = []
    start = active_frames[0]
    prior = start
    for frame in active_frames[1:]:
        if frame != prior + 1:
            windows.append({"source_start_frame": start, "source_end_frame": prior + 1})
            start = frame
        prior = frame
    windows.append({"source_start_frame": start, "source_end_frame": prior + 1})
    return windows


__all__ = [
    "DevelopmentOnlyBackgroundMusicMvpError",
    "DevelopmentOnlyBackgroundMusicMvpHarness",
    "LOCAL_MVP_ENVIRONMENT",
]
