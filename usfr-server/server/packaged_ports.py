"""Packaged production port assembly for the deployable USFR service.

The package owns this factory so Docker Compose never has to import a module
from the operator's workstation.  It deliberately creates real capability
adapters only; a route that has no executable packaged implementation is
reported as unavailable before it can reach a paid provider boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .bundle_resolver import ImmutableBundleResolver
from .capabilities import REQUIRED_CAPABILITIES
from .capability_ports import BoundRuntimeCapability, BoundStagePort, CapabilityStagePort
from .ephemeral_driver import EXECUTABLE_STAGES
from .errors import ReplicationError
from .gpt_evidence_gateway import GptEvidenceGateway
from .runninghub_workflows import RunningHubWorkflowClient
from .packaged_stages import (
    BindInputsStage,
    ProbeSourceStage,
    RouteRegionsStage,
    SeedanceAuditStage,
    SeedancePromptStage,
    SegmentPlanStage,
    StoryboardStage,
    SubmitProviderVideoStage,
    WaitProviderVideoStage,
)
from .production_ports import (
    EvidenceBoundGptPlanner,
    ProductionEnvironment,
    RunningHubSeedanceMediaUploader,
    RunningHubSeedanceProvider,
    _DurableDynamicsEvidenceStage,
    _ScriptRevisionStage,
    _StoryboardRevisionStage,
)
from .real_capabilities import (
    BundledAppStoreEvidenceParser,
    DeterministicUiRenderer,
    FfmpegCompositor,
    FfmpegDynamicsAnalyzer,
    FfmpegQcEngine,
    WhisperAsrTranscriber,
)
from .seedance_invocations import SeedanceInvocationAdapter
from .timeline_renderer import BundledTimelineRenderer
from .uploaded_audio_contract import EvidenceBoundHttpUploadedAudioClassifier


class PackagedPortsError(RuntimeError):
    """Raised when the immutable bundle cannot construct its service ports."""


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _active_profile() -> bool:
    return (os.getenv("USFR_PROFILE_MODE", "shadow") or "shadow").strip().casefold() in {
        "active",
        "production",
    }


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bundle_resolver() -> ImmutableBundleResolver:
    root = _package_root()
    return ImmutableBundleResolver.from_package_manifest(
        root / "references" / "runtime_skill_manifest.json",
        package_root=root,
    )


def _uploaded_audio_classifier(*, production: bool) -> EvidenceBoundHttpUploadedAudioClassifier | None:
    """Bind the optional music-extension classifier only when fully configured."""

    required = (
        "USFR_UPLOADED_AUDIO_CLASSIFIER_ENDPOINT",
        "USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_ID",
        "USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_SHA256",
    )
    present = [name for name in required if (os.getenv(name, "") or "").strip()]
    if not present:
        return None
    if len(present) != len(required):
        missing = ", ".join(name for name in required if name not in present)
        raise PackagedPortsError(f"uploaded audio classifier configuration is incomplete: {missing}")
    try:
        return EvidenceBoundHttpUploadedAudioClassifier.from_environment(production=production)
    except (KeyError, ValueError) as exc:
        raise PackagedPortsError("uploaded audio classifier configuration is invalid") from exc


class _GatewaySemanticBackend:
    """One GPT semantic pass over ordered, decoded source-frame evidence."""

    _MAX_FRAMES = 32

    def __init__(
        self,
        gateway: GptEvidenceGateway,
        *,
        frame_extractor: Any | None = None,
    ) -> None:
        self.gateway = gateway
        self._frame_extractor = frame_extractor or self._extract_jpeg

    def capability_identity(self) -> dict[str, str]:
        identity = self.gateway.capability_identity()
        return {
            "implementation": "server.packaged_ports:_GatewaySemanticBackend",
            "version": "1.0.0",
            "model_id": identity["model_id"],
            "model_sha256": identity["model_sha256"],
            "evidence_binding": "usfr-gpt-semantic-video/v1",
            "transport": "openai-responses",
            "sha256": _sha256(identity),
        }

    @staticmethod
    def _source_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError as exc:
            raise ReplicationError(
                "CAPABILITY_UNAVAILABLE",
                "the current leased source video could not be read for GPT evidence",
                category="capability",
                retryable=True,
                http_status=503,
            ) from exc
        return digest.hexdigest()

    @staticmethod
    def _text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ReplicationError(
                "CAPABILITY_UNAVAILABLE",
                f"GPT semantic output omitted {field}",
                category="capability",
                user_action_required=True,
                http_status=503,
            )
        text = value.strip()
        folded = text.casefold()
        if text.startswith(("/", "\\")) or (len(text) > 1 and text[1] == ":") or "~/.codex" in folded:
            raise ReplicationError(
                "CAPABILITY_UNAVAILABLE",
                f"GPT semantic output {field} contains a forbidden local path",
                category="capability",
                user_action_required=True,
                http_status=503,
            )
        return text

    @staticmethod
    def _extract_jpeg(path: Path, timestamp_us: int) -> bytes:
        executable = shutil.which("ffmpeg")
        if not executable:
            raise ReplicationError(
                "CAPABILITY_UNAVAILABLE",
                "ffmpeg is required to extract GPT source evidence frames",
                category="capability",
                user_action_required=True,
                http_status=503,
            )
        command = [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp_us / 1_000_000:.6f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=768:-2:force_original_aspect_ratio=decrease",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
        try:
            result = subprocess.run(command, check=False, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReplicationError(
                "CAPABILITY_UNAVAILABLE",
                "GPT source evidence frame extraction failed",
                category="capability",
                retryable=True,
                http_status=503,
            ) from exc
        if result.returncode != 0 or not result.stdout:
            raise ReplicationError(
                "CAPABILITY_UNAVAILABLE",
                "GPT source evidence frame extraction produced no decoded image",
                category="capability",
                user_action_required=True,
                http_status=503,
            )
        return bytes(result.stdout)

    def _timestamps(
        self,
        *,
        probe: Mapping[str, Any],
        cuts: Sequence[Mapping[str, Any]],
        evidence_plan: Mapping[str, Any] | None,
    ) -> list[int]:
        try:
            duration_us = int(probe.get("duration_us"))
            fps = float(probe.get("fps") or 0)
        except (TypeError, ValueError) as exc:
            raise ReplicationError(
                "CAPABILITY_UNAVAILABLE",
                "verified source probe is missing duration or frame rate",
                category="capability",
                user_action_required=True,
                http_status=503,
            ) from exc
        if duration_us <= 0:
            raise ReplicationError("CAPABILITY_UNAVAILABLE", "verified source duration is invalid", category="capability", http_status=503)
        step_us = max(1_000, int(round(1_000_000 / fps))) if fps > 0 else 33_333
        final_frame_us = max(0, duration_us - step_us)
        values: set[int] = {0, final_frame_us}
        if isinstance(evidence_plan, Mapping):
            evidence = evidence_plan.get("evidence")
            keyframes = evidence.get("adaptive_keyframes") if isinstance(evidence, Mapping) else None
            if isinstance(keyframes, Sequence) and not isinstance(keyframes, (str, bytes, bytearray)):
                for row in keyframes:
                    if isinstance(row, Mapping):
                        try:
                            values.add(max(0, min(final_frame_us, int(row.get("time_us")))))
                        except (TypeError, ValueError):
                            continue
        for row in cuts:
            if not isinstance(row, Mapping):
                continue
            try:
                start = max(0, int(row.get("start_us")))
                end = min(duration_us, int(row.get("end_us")))
            except (TypeError, ValueError):
                continue
            if end > start:
                values.add(min(final_frame_us, start))
                values.add(min(final_frame_us, start + (end - start) // 2))
        ordered = sorted(values)
        if len(ordered) > self._MAX_FRAMES:
            # Preserve frame-zero/end and sample the remaining ordered evidence
            # evenly.  Every decoder Cut still needs a sample; a source with
            # more than 32 temporal Cuts is blocked rather than silently
            # omitting evidence for a claimed semantic Cut.
            if len(cuts) > self._MAX_FRAMES:
                raise ReplicationError(
                    "CAPABILITY_UNAVAILABLE",
                    "source has more semantic Cuts than the configured GPT frame evidence budget",
                    category="capability",
                    user_action_required=True,
                    http_status=503,
                )
            positions = [round(index * (len(ordered) - 1) / (self._MAX_FRAMES - 1)) for index in range(self._MAX_FRAMES)]
            ordered = [ordered[index] for index in dict.fromkeys(positions)]
        for index, row in enumerate(cuts, start=1):
            try:
                start, end = int(row.get("start_us")), int(row.get("end_us"))
            except (TypeError, ValueError) as exc:
                raise ReplicationError("CAPABILITY_UNAVAILABLE", "decoder Cut timing is invalid", category="capability", http_status=503) from exc
            if not any(start <= timestamp < end for timestamp in ordered):
                raise ReplicationError(
                    "CAPABILITY_UNAVAILABLE",
                    f"GPT evidence budget has no decoded frame inside source Cut {index}",
                    category="capability",
                    user_action_required=True,
                    http_status=503,
                )
        return ordered

    def analyze(
        self,
        *,
        path: Path,
        probe: Mapping[str, Any],
        cuts: Sequence[Mapping[str, Any]],
        evidence_plan: Mapping[str, Any] | None = None,
        analysis_scope: Mapping[str, Any] | None = None,
        context: Any | None = None,
    ) -> Mapping[str, Any]:
        del context
        source = Path(path)
        if not source.is_file():
            raise ReplicationError("CAPABILITY_UNAVAILABLE", "leased source video is unavailable for GPT analysis", category="capability", http_status=503)
        source_sha256 = self._source_sha256(source)
        timestamps = self._timestamps(probe=probe, cuts=cuts, evidence_plan=evidence_plan)
        frames: list[dict[str, Any]] = []
        for timestamp_us in timestamps:
            data = self._frame_extractor(source, timestamp_us)
            if not isinstance(data, bytes) or not data:
                raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT evidence extractor returned no frame bytes", category="capability", http_status=503)
            frames.append({"bytes": data, "content_type": "image/jpeg", "timestamp_us": timestamp_us})
        frame_records = [
            {"timestamp_us": row["timestamp_us"], "frame_sha256": hashlib.sha256(row["bytes"]).hexdigest()}
            for row in frames
        ]
        request_evidence: dict[str, Any] = {
            "source_sha256": source_sha256,
            "source": {
                "duration_us": int(probe.get("duration_us") or 0),
                "width": int(probe.get("width") or probe.get("source_width") or 0),
                "height": int(probe.get("height") or probe.get("source_height") or 0),
                "fps": float(probe.get("fps") or 0),
            },
            "decoder_cuts": [
                {"start_us": int(row.get("start_us")), "end_us": int(row.get("end_us"))}
                for row in cuts
                if isinstance(row, Mapping)
            ],
            "frames": frame_records,
            "response_rules": {
                "source_cuts": "return ordered contiguous Cuts from 0 through the exact duration; each Cut needs scene, action, camera, transition, end_state, certainty and a frame_sha256+timestamp_us evidence ref from the listed frames",
                "source_events": "return time-bounded visual/audio events; never invent product claims, text, UI content, or unseen actions",
                "opaque_policy": "do not analyze supplied opaque UI/tail media or infer their semantic content",
            },
        }
        if isinstance(evidence_plan, Mapping):
            request_evidence["evidence_plan_sha256"] = evidence_plan.get("plan_sha256")
        if isinstance(analysis_scope, Mapping):
            request_evidence["analysis_scope"] = dict(analysis_scope)
        try:
            response = self.gateway.analyze_images(frames=frames, evidence=request_evidence)
        except Exception as exc:
            if isinstance(exc, ReplicationError):
                raise
            raise ReplicationError(
                "CAPABILITY_UNAVAILABLE",
                "GPT source-frame semantic analysis failed",
                category="capability",
                retryable=True,
                http_status=503,
            ) from exc
        if not isinstance(response, Mapping):
            raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT source-frame analysis returned no object", category="capability", http_status=503)
        payload = response.get("source_dynamics_analysis") if isinstance(response.get("source_dynamics_analysis"), Mapping) else response
        raw_cuts = payload.get("source_cuts") if isinstance(payload, Mapping) else None
        raw_events = payload.get("source_events") if isinstance(payload, Mapping) else None
        if not isinstance(raw_cuts, Sequence) or isinstance(raw_cuts, (str, bytes, bytearray)) or not raw_cuts:
            raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT semantic output omitted source Cuts", category="capability", http_status=503)
        if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes, bytearray)):
            raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT semantic output omitted source events", category="capability", http_status=503)
        frame_times = {record["frame_sha256"]: record["timestamp_us"] for record in frame_records}
        clean_cuts: list[dict[str, Any]] = []
        cursor = 0
        duration_us = int(probe.get("duration_us") or 0)
        for index, row in enumerate(raw_cuts, start=1):
            if not isinstance(row, Mapping):
                raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT source Cut is invalid", category="capability", http_status=503)
            try:
                start_us, end_us = int(row.get("start_us")), int(row.get("end_us"))
            except (TypeError, ValueError) as exc:
                raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT source Cut timing is invalid", category="capability", http_status=503) from exc
            if start_us != cursor or end_us <= start_us or end_us > duration_us:
                raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT source Cuts must be contiguous from frame zero to the decoded end", category="capability", http_status=503)
            references = row.get("evidence_refs")
            if not isinstance(references, Sequence) or isinstance(references, (str, bytes, bytearray)):
                raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT source Cut omitted decoded-frame evidence", category="capability", http_status=503)
            clean_refs: list[dict[str, Any]] = []
            for reference in references:
                if not isinstance(reference, Mapping):
                    continue
                digest = str(reference.get("frame_sha256") or "").lower()
                try:
                    timestamp_us = int(reference.get("timestamp_us"))
                except (TypeError, ValueError):
                    continue
                if frame_times.get(digest) == timestamp_us:
                    clean_refs.append({"kind": "frame", "frame_sha256": digest, "timestamp_us": timestamp_us})
            if not clean_refs or not any(start_us <= item["timestamp_us"] < end_us for item in clean_refs):
                raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT source Cut lacks a local decoded-frame reference", category="capability", http_status=503)
            clean_cuts.append(
                {
                    "cut": index,
                    "start_us": start_us,
                    "end_us": end_us,
                    "scene": self._text(row.get("scene"), "source Cut scene"),
                    "action": self._text(row.get("action"), "source Cut action"),
                    "camera": self._text(row.get("camera"), "source Cut camera"),
                    "transition": self._text(row.get("transition"), "source Cut transition"),
                    "end_state": self._text(row.get("end_state"), "source Cut end_state"),
                    "certainty": self._text(row.get("certainty"), "source Cut certainty"),
                    "evidence_refs": clean_refs,
                }
            )
            cursor = end_us
        if cursor != duration_us:
            raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT source Cuts do not cover the decoded end", category="capability", http_status=503)
        clean_events: list[dict[str, Any]] = []
        for index, row in enumerate(raw_events, start=1):
            if not isinstance(row, Mapping):
                continue
            try:
                start_us, end_us = int(row.get("start_us")), int(row.get("end_us"))
            except (TypeError, ValueError):
                continue
            if not (0 <= start_us < end_us <= duration_us):
                continue
            clean_events.append(
                {
                    "event": index,
                    "start_us": start_us,
                    "end_us": end_us,
                    "kind": self._text(row.get("kind"), "source event kind"),
                    "text": str(row.get("text") or "").strip(),
                    "certainty": self._text(row.get("certainty"), "source event certainty"),
                }
            )
        receipt = response.get("receipt")
        if not isinstance(receipt, Mapping) or not all(
            isinstance(receipt.get(field), str) and len(str(receipt[field])) == 64
            for field in ("request_sha256", "response_sha256")
        ):
            raise ReplicationError("CAPABILITY_UNAVAILABLE", "GPT semantic output is missing an evidence receipt", category="capability", http_status=503)
        result: dict[str, Any] = {
            "source_cuts": clean_cuts,
            "source_events": clean_events,
            "backend_evidence": {
                "schema_version": "usfr-gpt-semantic-video/v1",
                "request_sha256": str(receipt["request_sha256"]),
                "response_sha256": str(receipt["response_sha256"]),
                "source_sha256": source_sha256,
                "frame_sha256s": [record["frame_sha256"] for record in frame_records],
                "frame_evidence": frame_records,
                "model_id": self.gateway.capability_identity()["model_id"],
                "model_sha256": self.gateway.capability_identity()["model_sha256"],
            },
        }
        if isinstance(payload, Mapping) and isinstance(payload.get("extensions"), Mapping):
            result["extensions"] = dict(payload["extensions"])
        if isinstance(payload, Mapping) and isinstance(payload.get("source_overlay_contract"), Mapping):
            result["source_overlay_contract"] = dict(payload["source_overlay_contract"])
        return result


def _wrapped_capability(*, capability: str, adapter: Any, config: ProductionEnvironment) -> BoundRuntimeCapability:
    identity = getattr(adapter, "capability_identity", lambda: {})()
    payload = {
        "capability": capability,
        "adapter": dict(identity) if isinstance(identity, Mapping) else {},
        "openai_model": config.openai_model,
        "openai_model_config_sha256": config.openai_model_config_sha256,
        "runninghub_seedance_config_sha256": config.runninghub_seedance_config_sha256,
    }
    return BoundRuntimeCapability(
        capability=capability,
        implementation=f"server.packaged_ports:{capability}",
        version="1.0.0",
        sha256=_sha256(payload),
        adapter=adapter,
    )


def build_ports() -> dict[str, Any]:
    """Return the complete package-relative StagePort/capability mapping.

    Construction validates all mandatory GPT, RunningHub, Whisper-workflow,
    and immutable-Skill prerequisites.  It performs no media upload and no
    provider create operation.
    """

    config = ProductionEnvironment.from_environ()
    workflow_id = (os.getenv("RUNNINGHUB_WHISPER_WORKFLOW_ID", "") or "").strip()
    input_node_id = (os.getenv("RUNNINGHUB_WHISPER_INPUT_NODE_ID", "") or "").strip()
    if not workflow_id or not input_node_id:
        raise PackagedPortsError(
            "RUNNINGHUB_WHISPER_WORKFLOW_ID and RUNNINGHUB_WHISPER_INPUT_NODE_ID are required"
        )
    if not input_node_id.isdecimal():
        raise PackagedPortsError("RUNNINGHUB_WHISPER_INPUT_NODE_ID must be a numeric workflow node ID")

    active = _active_profile()
    uploaded_audio_classifier = _uploaded_audio_classifier(production=active)
    gateway = GptEvidenceGateway(config=config)
    semantic_backend = _GatewaySemanticBackend(gateway)
    dynamics = FfmpegDynamicsAnalyzer(
        semantic_analyzer=semantic_backend,
        allow_heuristic=False,
        production=active,
        sha256=_sha256({"adapter": "ffmpeg-dynamics", "gateway": semantic_backend.capability_identity()}),
    )
    # A source ASR run must use the selected RunningHub workflow.  Do not
    # silently fall back to a downloaded local Whisper model in a deployment.
    workflow_client = RunningHubWorkflowClient(
        api_key=os.getenv(config.runninghub_api_key_env, ""),
        base_url=config.runninghub_base_url,
    )

    def runninghub_whisper_transcriber(audio_path: Path, *, language: str | None = None) -> Sequence[Mapping[str, Any]]:
        # The configured workflow is the ASR authority.  ``language`` remains
        # a downstream source-language hint because RunningHub's generic
        # workflow API exposes only the user-configured audio node here.
        del language
        result = workflow_client.run_whisper(
            audio_path=audio_path,
            workflow_id=workflow_id,
            input_node_id=input_node_id,
            input_field=(os.getenv("RUNNINGHUB_WHISPER_INPUT_FIELD", "audio") or "audio").strip(),
        )
        return [dict(item) for item in result["segments"] if isinstance(item, Mapping)]

    asr = WhisperAsrTranscriber(
        transcriber=runninghub_whisper_transcriber,
        production=False,
        allow_model_download=False,
    )
    ui_renderer = DeterministicUiRenderer(production=False)
    resolver = _bundle_resolver()
    invocation_adapter = SeedanceInvocationAdapter(bundle_resolver=resolver, production=False)
    timeline_renderer = BundledTimelineRenderer(production=active)
    compositor = FfmpegCompositor(
        renderer=timeline_renderer,
        production=active,
        sha256=_sha256({"adapter": "ffmpeg-compositor", "renderer": timeline_renderer.capability_identity()}),
    )
    qc = FfmpegQcEngine(
        production=active,
        sha256=_sha256({"adapter": "ffmpeg-qc", "gateway": gateway.capability_identity()}),
    )
    provider = RunningHubSeedanceProvider(config)
    seedance_media_uploader = RunningHubSeedanceMediaUploader(config)
    capability_ports = {
        "dynamics_analyzer": _wrapped_capability(capability="dynamics_analyzer", adapter=dynamics, config=config),
        "asr_transcriber": _wrapped_capability(capability="asr_transcriber", adapter=asr, config=config),
        "ocr_ui_renderer": _wrapped_capability(capability="ocr_ui_renderer", adapter=ui_renderer, config=config),
        "seedance20_compiler": _wrapped_capability(capability="seedance20_compiler", adapter=invocation_adapter, config=config),
        "compositor": _wrapped_capability(capability="compositor", adapter=compositor, config=config),
        "qc_engine": _wrapped_capability(capability="qc_engine", adapter=qc, config=config),
        "provider_adapter": _wrapped_capability(capability="provider_adapter", adapter=provider, config=config),
    }
    if set(capability_ports) != set(REQUIRED_CAPABILITIES):
        raise PackagedPortsError("packaged capability set does not match the canonical service contract")

    planner = EvidenceBoundGptPlanner(config)
    direct_dynamics = CapabilityStagePort(
        "analyze_dynamics", capability_ports, production=False, profile_active=False
    )
    stage_ports: dict[str, Any] = {
        "bind_inputs": BindInputsStage(uploaded_audio_classifier=uploaded_audio_classifier),
        "probe_source": ProbeSourceStage(),
        "route_regions": RouteRegionsStage(),
        "segment_plan": SegmentPlanStage(),
        "compile_seedance20_prompt": SeedancePromptStage(
            invocation_adapter=invocation_adapter,
            uploaded_song_transcriber=runninghub_whisper_transcriber,
        ),
        "audit_seedance_request": SeedanceAuditStage(
            provider=provider,
            media_uploader=seedance_media_uploader,
            audit_secret=os.getenv(config.capability_secret_env, ""),
        ),
        "submit_provider_video": SubmitProviderVideoStage(
            provider=provider,
            audit_secret=os.getenv(config.capability_secret_env, ""),
        ),
        "wait_provider_video": WaitProviderVideoStage(provider=provider),
    }
    stage_ports["analyze_dynamics"] = _DurableDynamicsEvidenceStage(direct_dynamics)
    stage_ports["parse_app_store_evidence"] = BundledAppStoreEvidenceParser()
    stage_ports["resolve_ui_evidence"] = CapabilityStagePort(
        "resolve_ui_evidence", capability_ports, production=False, profile_active=False
    )
    stage_ports["build_script"] = BoundStagePort("build_script", _ScriptRevisionStage(planner))
    stage_ports["generate_storyboards"] = StoryboardStage(planner, image_client=workflow_client)
    stage_ports["compile_seedance20_prompt"] = BoundStagePort(
        "compile_seedance20_prompt", stage_ports["compile_seedance20_prompt"]
    )
    stage_ports["audit_seedance_request"] = BoundStagePort(
        "audit_seedance_request", stage_ports["audit_seedance_request"]
    )
    stage_ports["splice_timeline"] = CapabilityStagePort(
        "splice_timeline", capability_ports, production=False, profile_active=False
    )
    stage_ports["run_qc"] = CapabilityStagePort(
        "run_qc", capability_ports, production=False, profile_active=False
    )
    if set(stage_ports) != set(EXECUTABLE_STAGES):
        raise PackagedPortsError("packaged stage set does not match the canonical service contract")
    return {
        "stage_ports": stage_ports,
        "capability_ports": capability_ports,
        "invocation_adapter": invocation_adapter,
        "recovery_bridge": None,
    }


__all__ = ["PackagedPortsError", "build_ports"]
