from __future__ import annotations

from hashlib import sha256
import hashlib
import json
from pathlib import Path
import shutil
import sys
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _configure_environment(monkeypatch) -> None:
    # Endpoint host pinning is a production boundary.  These unit tests use
    # non-routable documentation hosts, so resolve them deterministically
    # without performing a real DNS request.
    import server.production_ports as production_ports

    monkeypatch.setattr(production_ports, "_resolve_hostname", lambda _host: ("8.8.8.8",))
    settings = {
        "OPENAI_API_KEY": "test-openai-key",
        "USFR_CAPABILITY_SECRET": "test-capability-secret",
        "OPENAI_BASE_URL": "https://api.example.test/v1",
        "OPENAI_MODEL": "gpt-test",
        "OPENAI_MODEL_CONFIG_SHA256": "a" * 64,
        "RUNNINGHUB_API_KEY": "test-runninghub-key",
        "RUNNINGHUB_SEEDANCE_API_KEY": "test-seedance-key",
        "RUNNINGHUB_BASE_URL": "https://runninghub.example.test",
        "RUNNINGHUB_SEEDANCE_CREATE_URL": "https://runninghub.example.test/openapi/v2/bytedance/seedance-2.0-token/multimodal-video",
        "RUNNINGHUB_SEEDANCE_QUERY_URL": "https://runninghub.example.test/openapi/v2/query",
        "RUNNINGHUB_SEEDANCE_UPLOAD_URL": "https://runninghub.example.test/openapi/v2/media/upload/binary",
        "RUNNINGHUB_SEEDANCE_CONFIG_SHA256": "b" * 64,
        "RUNNINGHUB_SPEECH_WHISPER_WORKFLOW_ID": "2080170949061038081",
        "RUNNINGHUB_SPEECH_WHISPER_INPUT_NODE_ID": "1",
        "RUNNINGHUB_SPEECH_WHISPER_INPUT_FIELD": "video",
        "USFR_PROFILE_MODE": "shadow",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)


def test_packaged_port_factory_has_exact_stage_and_capability_sets(monkeypatch) -> None:
    from server.capabilities import REQUIRED_CAPABILITIES
    from server.ephemeral_driver import EXECUTABLE_STAGES
    from server.packaged_ports import build_ports

    _configure_environment(monkeypatch)
    ports = build_ports()

    assert set(ports["stage_ports"]) == set(EXECUTABLE_STAGES)
    assert set(ports["capability_ports"]) == set(REQUIRED_CAPABILITIES)


def test_packaged_port_factory_exposes_h3_single_model_edit_stages(monkeypatch) -> None:
    from server.ephemeral_driver import EXECUTABLE_STAGES
    from server.packaged_ports import build_ports

    _configure_environment(monkeypatch)
    ports = build_ports()

    required = {"compile_h3_edit", "audit_h3_request", "submit_h3_edit", "wait_h3_edit"}
    assert required.issubset(EXECUTABLE_STAGES)
    assert required.issubset(ports["stage_ports"])
    assert "run_song_lip_sync" not in EXECUTABLE_STAGES


def test_v2_runtime_plan_and_packaged_ports_keep_probe_before_durable_dynamics(monkeypatch) -> None:
    from server.ephemeral_driver import EXECUTABLE_STAGES
    from server.orchestrator import build_stage_plan
    from server.packaged_ports import build_ports
    from server.production_ports import _DurableDynamicsEvidenceStage

    _configure_environment(monkeypatch)
    ports = build_ports()
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}},
        "routes": {},
    }
    plan = build_stage_plan(manifest)
    names = [str(item["name"]) for item in plan]

    assert "probe_source" in EXECUTABLE_STAGES
    assert names.index("probe_source") < names.index("analyze_source")
    assert type(ports["stage_ports"]["probe_source"]).__name__ == "ProbeSourceStage"
    assert isinstance(ports["stage_ports"]["analyze_dynamics"], _DurableDynamicsEvidenceStage)


def test_packaged_ports_are_package_relative_and_never_load_a_workstation_skill(monkeypatch) -> None:
    from server.packaged_ports import build_ports

    _configure_environment(monkeypatch)
    ports = build_ports()

    serialized = repr(ports)
    assert ".codex" not in serialized.casefold()
    assert "C:\\Users" not in serialized


def test_packaged_ports_bind_runninghub_whisper_instead_of_a_local_whisper_fallback(monkeypatch) -> None:
    from server.packaged_ports import build_ports

    _configure_environment(monkeypatch)
    ports = build_ports()
    asr = ports["capability_ports"]["asr_transcriber"].adapter

    assert callable(asr.transcriber)
    assert asr.allow_model_download is False
    assert asr.model_path is None
    assert asr.transcriber_media_kind == "source_video"


def test_packaged_ports_bind_voice_clone_two_input_tts_config(monkeypatch) -> None:
    from server.packaged_ports import build_ports

    _configure_environment(monkeypatch)
    monkeypatch.setenv("RUNNINGHUB_TTS_MODE", "voice_clone_two_input")
    monkeypatch.setenv("RUNNINGHUB_TTS_WORKFLOW_ID", "2080177717619118082")
    monkeypatch.setenv("RUNNINGHUB_TTS_REFERENCE_AUDIO_NODE_ID", "4")
    monkeypatch.setenv("RUNNINGHUB_TTS_REFERENCE_AUDIO_FIELD", "audio")
    monkeypatch.setenv("RUNNINGHUB_TTS_TEXT_NODE_ID", "11")
    monkeypatch.setenv("RUNNINGHUB_TTS_TEXT_FIELD", "prompt")

    client = build_ports()["stage_ports"]["replace_voiceover_audio"].workflow_client

    assert client.tts_config == {
        "mode": "voice_clone_two_input",
        "workflow_id": "2080177717619118082",
        "reference_audio_node_id": "4",
        "reference_audio_field": "audio",
        "text_node_id": "11",
        "text_field": "prompt",
    }


def test_packaged_ports_bind_the_uploaded_audio_classifier_when_the_extension_capability_is_configured(monkeypatch) -> None:
    from server.packaged_ports import build_ports
    from server.uploaded_audio_contract import EvidenceBoundHttpUploadedAudioClassifier

    _configure_environment(monkeypatch)
    monkeypatch.setenv("USFR_UPLOADED_AUDIO_CLASSIFIER_ENDPOINT", "https://audio.example.test/v1/classify")
    monkeypatch.setenv("USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_ID", "music-classifier")
    monkeypatch.setenv("USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_SHA256", "c" * 64)

    ports = build_ports()
    bind_stage = ports["stage_ports"]["bind_inputs"]

    assert isinstance(bind_stage.uploaded_audio_classifier, EvidenceBoundHttpUploadedAudioClassifier)


def test_packaged_ports_use_the_seedance_key_for_audit_media_uploads_not_the_workflow_key(monkeypatch) -> None:
    import server.packaged_ports as packaged_ports

    _configure_environment(monkeypatch)
    workflow_keys: list[str] = []
    standard_keys: list[str] = []

    class WorkflowClient:
        def __init__(self, *, api_key: str, base_url: str, **_kwargs) -> None:
            del base_url
            workflow_keys.append(api_key)

        def run_speech_whisper(self, **_kwargs):
            return {"segments": []}

        def run_image2(self, **_kwargs):
            raise AssertionError("factory construction must not submit Image2")

        def run_tts(self, *_args, **_kwargs):
            raise AssertionError("factory construction must not submit TTS")

        def upload_media(self, _path: Path) -> str:
            raise AssertionError("factory construction must not upload lip-sync media")

        def run_final_lip_sync(self, *_args, **_kwargs):
            raise AssertionError("factory construction must not submit lip sync")

    class SeedanceMediaUploader:
        def __init__(self, config) -> None:
            standard_keys.append(config.runninghub_seedance_api_key_env)

        def upload_media(self, _path: Path) -> str:
            raise AssertionError("factory construction must not upload media")

    monkeypatch.setattr(packaged_ports, "RunningHubWorkflowClient", WorkflowClient)
    monkeypatch.setattr(packaged_ports, "RunningHubSeedanceMediaUploader", SeedanceMediaUploader, raising=False)
    ports = packaged_ports.build_ports()

    audit_stage = ports["stage_ports"]["audit_seedance_request"].handler
    assert workflow_keys == ["test-runninghub-key"]
    assert standard_keys == ["RUNNINGHUB_SEEDANCE_API_KEY"]
    assert type(audit_stage.media_uploader) is SeedanceMediaUploader


def test_gateway_semantic_backend_binds_gpt_cuts_to_decoded_frame_bytes(tmp_path: Path) -> None:
    from server.packaged_ports import _GatewaySemanticBackend

    source = tmp_path / "source.mp4"
    source.write_bytes(b"current-source-video")
    observed: dict[str, object] = {}

    class Gateway:
        def capability_identity(self):
            return {"model_id": "gpt-test", "model_sha256": "a" * 64}

        def analyze_images(self, *, frames, evidence):
            observed["frames"] = frames
            observed["evidence"] = evidence
            digests = {
                frame["timestamp_us"]: sha256(frame["bytes"]).hexdigest()
                for frame in frames
            }
            first, second = digests[0], digests[1_000_000]
            return {
                "source_cuts": [
                    {
                        "start_us": 0,
                        "end_us": 1_000_000,
                        "scene": "speaker faces camera",
                        "action": "speaker points to product",
                        "camera": "locked portrait close-up",
                        "transition": "hard cut",
                        "end_state": "hand remains beside product",
                        "certainty": "observed",
                        "evidence_refs": [{"frame_sha256": first, "timestamp_us": 0}],
                    },
                    {
                        "start_us": 1_000_000,
                        "end_us": 2_000_000,
                        "scene": "product close-up",
                        "action": "camera reveals product label",
                        "camera": "slow push-in",
                        "transition": "end",
                        "end_state": "label fills frame",
                        "certainty": "observed",
                        "evidence_refs": [{"frame_sha256": second, "timestamp_us": 1_000_000}],
                    },
                ],
                "source_events": [
                    {"start_us": 0, "end_us": 2_000_000, "kind": "speech", "text": "spoken product claim", "certainty": "observed"}
                ],
                "receipt": {"request_sha256": "b" * 64, "response_sha256": "c" * 64},
            }

    backend = _GatewaySemanticBackend(
        Gateway(),
        frame_extractor=lambda _path, timestamp_us: f"frame-{timestamp_us}".encode(),
    )
    result = backend.analyze(
        path=source,
        probe={"duration_us": 2_000_000, "fps": 30},
        cuts=[{"start_us": 0, "end_us": 1_000_000}, {"start_us": 1_000_000, "end_us": 2_000_000}],
        evidence_plan={"evidence": {"adaptive_keyframes": [{"time_us": 0}, {"time_us": 1_000_000}]}},
    )

    assert {0, 1_000_000}.issubset({frame["timestamp_us"] for frame in observed["frames"]})
    assert result["backend_evidence"]["source_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert {sha256(b"frame-0").hexdigest(), sha256(b"frame-1000000").hexdigest()}.issubset(
        set(result["backend_evidence"]["frame_sha256s"])
    )
    assert result["source_cuts"][1]["camera"] == "slow push-in"


def test_packaged_ports_do_not_ship_unavailable_workflow_stage_placeholders(monkeypatch) -> None:
    from server.packaged_ports import build_ports

    _configure_environment(monkeypatch)
    ports = build_ports()

    assert not any(type(port).__name__ == "_UnavailableWorkflowStage" for port in ports["stage_ports"].values())


def test_generate_asset_boards_is_registered_in_port_driver_and_runtime_mapping(monkeypatch) -> None:
    from server.ephemeral_driver import EXECUTABLE_STAGES, EphemeralStageDriver
    from server.packaged_ports import build_ports

    _configure_environment(monkeypatch)
    assert "generate_asset_boards" in EXECUTABLE_STAGES
    ports = build_ports()
    assert "generate_asset_boards" in ports["stage_ports"]
    assert EphemeralStageDriver.runtime_stage({"name": "generate_asset_boards"}) == "generate_asset_boards"


def _phase4_make_video(path: Path, color: str, duration: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssertionError("ffmpeg is required for the real compositor boundary test")
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=30:d={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _phase5_make_tone_video(path: Path, color: str, frequency: int, duration: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssertionError("ffmpeg is required for the real song assembly boundary test")
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=30:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
            "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )


def _phase4_forbidden_plan_failures(
    plan: list[dict[str, object]], expected_ui_route: str, expected_tail_route: str
) -> list[str]:
    names = {str(item["name"]) for item in plan}
    failures: list[str] = []
    required = {
        "bind_inputs", "probe_source", "analyze_source", "build_edit_script",
        "await_script_approval", "generate_asset_boards", "plan_segments",
        "assemble_edit_timeline", "run_edit_qc",
    }
    if required - names:
        failures.append(f"missing deterministic stages: {sorted(required - names)}")
    forbidden = {
        "generate_sketch_storyboard", "await_storyboard_approval", "compile_edit_prompt", "audit_edit_request",
        "submit_provider_edit", "wait_provider_edit", "generated_ui_demo", "ocr_ui_renderer",
        "run_tts", "run_final_lip_sync", "replace_voiceover_audio",
    }
    if forbidden & names:
        failures.append(f"semantic/provider stages scheduled: {sorted(forbidden & names)}")
    if any(str(dep) not in names for item in plan for dep in item.get("depends_on") or ()):
        failures.append("plan has dangling dependencies")
    if any(item.get("provider") for item in plan):
        failures.append("deterministic route still schedules a provider stage")
    segment_plan = next(item for item in plan if item["name"] == "plan_segments")
    if segment_plan.get("depends_on") != ["analyze_source", "await_script_approval", "generate_asset_boards"]:
        failures.append("plan_segments must retain the v2 single-approval dependency contract")
    assemble = next(item for item in plan if item["name"] == "assemble_edit_timeline")
    if assemble.get("ui_route") != expected_ui_route:
        failures.append(f"wrong deterministic UI route: {assemble.get('ui_route')!r}")
    if assemble.get("tail_route") != expected_tail_route:
        failures.append(f"wrong deterministic tail route: {assemble.get('tail_route')!r}")
    return failures


def _phase4_timeline_case(
    tmp_path: Path, name: str, source: Path, operation: Path,
    operation_sha: str, *, has_ui: bool, has_tail: bool,
):
    def region(kind, region_id, start_us, end_us, **fields):
        return {
            "region_type": kind, "region_id": region_id,
            "source_start_us": start_us, "source_end_us": end_us, **fields,
        }

    ui_end = 1_500_000 if has_tail else 2_000_000
    canonical_regions = [region(
        "generated", "body", 0, 1_000_000 if has_ui else 1_500_000,
        media_path=str(source), media_origin="source_interval",
        assembly_policy="splice_source_interval",
    )]
    if has_ui:
        canonical_regions.append(region(
            "opaque_ui_demo", "ui", 1_000_000, ui_end,
            media_path=str(operation), media_origin="user_upload",
            assembly_policy="splice_opaque_ui", media_sha256=operation_sha,
            approved_insertion_cut=True,
            transition_shell={"entry": {"type": "hard_cut"}, "exit": {"type": "hard_cut"}},
        ))
    if has_tail:
        canonical_regions.append(region(
            "excluded_app_end_card", "source-tail", 1_500_000, 2_000_000,
            media_path=str(source), media_origin="source_interval",
            assembly_policy="splice_source_interval",
            transition_shell={"entry": {"type": "hard_cut"}},
        ))
    from server.timeline_renderer import _timeline_module
    path = tmp_path / f"{name}-timeline.json"
    path.write_text(json.dumps({
        "source_duration_us": 2_000_000, "source_fps": 30,
        "target": {"width": 64, "height": 64, "fps": 30},
        "regions": canonical_regions,
    }), encoding="utf-8")
    canonical = _timeline_module().load_contract(path)
    terminal = next((item for item in canonical.regions if item.kind == "excluded_app_end_card"), None)
    ui = next((item for item in canonical.regions if item.kind == "opaque_ui_demo"), None)
    boundary = (
        {"start_ms": round(terminal.source_start * 1_000), "end_ms": round(terminal.source_end * 1_000)}
        if terminal else None
    )
    window = (
        {"start_ms": round(ui.source_start * 1_000), "end_ms": round(ui.source_end * 1_000)}
        if ui else None
    )
    body_end = round(
        (ui.source_start if ui else terminal.source_start if terminal else canonical.regions[-1].source_end)
        * 1_000_000
    )
    timeline_regions = [region(
        "source_interval", "body", 0, body_end,
        media_origin="source_interval", assembly_policy="splice_source_interval",
        placement_kind="source_body",
    )]
    if ui:
        timeline_regions.append(region(
            "opaque_ui_demo", "ui", round(ui.source_start * 1_000_000),
            round(ui.source_end * 1_000_000), media_origin="opaque_ui",
            assembly_policy="splice_opaque_ui", source_slot="ui_operation_video",
            placement_kind="ui_operation_video",
        ))
    if terminal:
        timeline_regions.append(region(
            "opaque_tail", "tail", round(terminal.source_start * 1_000_000),
            round(terminal.source_end * 1_000_000), media_origin="opaque_tail",
            assembly_policy="splice_opaque_tail", source_slot="tail_video",
            placement_kind="tail_video", source_tail_detected=False,
        ))
    return boundary, window, timeline_regions




def _phase4_recording_context(
    tmp_path: Path,
    name: str,
    slot_paths: dict[str, Path],
    timeline_regions: list[dict[str, object]],
    expected_receipt_inputs: dict[str, object],
):
    class Context:
        work_dir = tmp_path / f"work-{name}"
        artifacts: list[dict[str, object]] = []
        profile_snapshot: dict[str, object] = {}
        expect_audio = False
        recorded_materializations: list[dict[str, str]] = []

        @contextmanager
        def materialize_slot(self, slot_id: str):
            path = self.slot_paths[slot_id]
            yield SimpleNamespace(path=path, sha256=sha256(path.read_bytes()).hexdigest())

        def publish_artifact(self, *, kind, stream, content_type, expected_sha256, metadata):
            data = stream.read()
            assert sha256(data).hexdigest() == expected_sha256
            artifact = {
                "artifact_id": f"published-{name}-{len(self.artifacts) + 1}",
                "kind": kind,
                "sha256": expected_sha256,
                "content_type": content_type,
                "object_key": f"temporary/phase4/{name}-{len(self.artifacts) + 1}",
                "metadata": dict(metadata),
            }
            self.artifacts.append(artifact)
            return artifact

    Context.slot_paths = dict(slot_paths)
    Context.timeline_regions = list(timeline_regions)
    Context.expected_receipt_inputs = dict(expected_receipt_inputs)
    return Context


def _phase4_recording_renderer(*, emit_transition_receipts: bool = True, capture_coexisting_plans: bool = False):
    class RecordingTimelineRenderer:
        capability_kind = "timeline_renderer"

        def __init__(self, *, production: bool = False):
            del production
            self.emit_transition_receipts = emit_transition_receipts

        def capability_identity(self):
            return {
                "capability": "timeline_renderer",
                "implementation": "tests:Phase4RecordingRenderer",
                "version": "phase4-shared-red-v1",
                "sha256": "3" * 64,
            }

        def __call__(self, source, output, context):
            if hasattr(context, "render_calls"):
                context.render_calls += 1
            captured_overlay_plan = getattr(context, "overlay_render_plan", None)
            if hasattr(context, "overlay_plan_calls"):
                if captured_overlay_plan is not None:
                    context.overlay_plan_calls += 1
                context.captured_overlay_plan = captured_overlay_plan
            if capture_coexisting_plans:
                context.captured_overlay_plans = {
                    "approved_overlay_plan": getattr(context, "approved_overlay_plan", None),
                    "source_overlay_plan": getattr(context, "source_overlay_plan", None),
                    "legacy_overlay_render_plan": captured_overlay_plan,
                }
            expected = context.expected_receipt_inputs
            for item in expected["materialize_slots"]:
                with context.materialize_slot(item["slot_id"]) as media:
                    context.recorded_materializations.append({
                        "slot": item["slot_id"],
                        "sha256": sha256(Path(media.path).read_bytes()).hexdigest(),
                    })
            output.write_bytes(source.read_bytes())
            output_sha = sha256(output.read_bytes()).hexdigest()
            placements = [
                {
                    "kind": region["placement_kind"],
                    "region_id": region.get("region_id"),
                    "source_start_us": region.get("source_start_us"),
                    "source_end_us": region.get("source_end_us"),
                    "assembly_policy": region.get("assembly_policy"),
                }
                for region in context.timeline_regions
            ]
            receipt = {
                "contract_version": "1.0",
                **dict(expected.get("base_receipt_fields", expected["receipt_fields"])),
            }
            approved_overlay_plan = getattr(context, "approved_overlay_plan", None)
            if not isinstance(approved_overlay_plan, dict):
                approved_overlay_plan = captured_overlay_plan
            if isinstance(approved_overlay_plan, dict):
                receipt["overlay_plan_sha256"] = approved_overlay_plan.get("overlay_plan_sha256")
                receipt["approved_script_sha256"] = approved_overlay_plan.get("approved_script_sha256")
                receipt["approved_script_revision"] = approved_overlay_plan.get("approved_script_revision")
            source_receipt_fields = expected.get("source_overlay_receipt_fields")
            if isinstance(source_receipt_fields, dict):
                receipt.update(source_receipt_fields)
            receipt.update({
                "renderer_identity": self.capability_identity(),
                "compositor_identity": expected["compositor_identity"],
                "output_sha256": output_sha,
                "output_lineage": {
                    **dict(expected["lineage"]),
                    "output_sha256": output_sha,
                },
                "placements": placements,
            })
            source_overlay_receipts = expected.get("source_overlay_receipts")
            result = {
                "timeline_manifest": {
                    "transition_renders": [receipt] if self.emit_transition_receipts else [],
                }
            }
            if isinstance(source_overlay_receipts, list):
                result["overlay_render_receipts"] = [
                    {**dict(item), "output_sha256": output_sha}
                    for item in source_overlay_receipts
                ]
            return result

    return RecordingTimelineRenderer


def _phase4_approved_overlay_case(tmp_path: Path, source: Path):
    import fakeredis

    from server.approved_edit_contract import build_approved_edit_script
    from server.ephemeral_service import ReplicationService
    from server.redis_job_store import RedisEphemeralJobStore
    from server.review_models import RevisionManifest
    from server.visible_text_contract import visible_text_locks_sha256

    draft_rows = [
        {
            "change_id": "OV02",
            "kind": "text",
            "start_ms": 1_000,
            "end_ms": 1_400,
            "text_target": "title-main",
            "layer": "overlay",
            "text": "Planner title",
            "instruction": "render approved title in post layer",
        },
        {
            "change_id": "PH01",
            "kind": "text",
            "start_ms": 100,
            "end_ms": 300,
            "text_target": "physical-text",
            "layer": "physical",
            "text": "Printed surface label",
            "instruction": "preserve approved physical surface text",
        },
        {
            "change_id": "OV01",
            "kind": "text",
            "start_ms": 400,
            "end_ms": 700,
            "text_target": "subtitle",
            "layer": "overlay",
            "text": "Approved price $19",
            "instruction": "render approved subtitle in post layer",
        },
    ]
    approved_edit_script = build_approved_edit_script([], [
        {**row, "text": "User approved title"} if row["change_id"] == "OV02" else dict(row)
        for row in draft_rows
    ])
    script_payload = json.dumps(
        {"contract": "approved-edit-script/v1", "approved_edit_script": build_approved_edit_script([], draft_rows)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    script_path = tmp_path / "script-revision-1.json"
    script_path.write_bytes(script_payload)
    script_sha = sha256(script_payload).hexdigest()

    store = RedisEphemeralJobStore(
        fakeredis.FakeRedis(decode_responses=False),
        prefix="phase4-overlay-red",
    )
    job = store.create_job(
        slots_manifest={"extensions": {"edit_contract": "video-edit-v2"}, "slots": {}},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    service = ReplicationService(job_store=store)
    revision = RevisionManifest.script(
        revision=1,
        object_key="temporary/phase4-overlay/script-r1.json",
        sha256=script_sha,
        inputs_sha256=sha256(b"script-inputs").hexdigest(),
    )
    completed = service.complete_script_revision(
        job.job_id,
        expected_version=job.version,
        manifest=revision,
    )
    service.approve_script_revision(
        job.job_id,
        revision=1,
        expected_version=completed.version,
        expected_sha256=script_sha,
        line_contracts=[],
        source_content_timeline_sha256="c" * 64,
        visible_text_locks=[],
        visible_text_locks_sha256=visible_text_locks_sha256([]),
        approved_edit_script=approved_edit_script,
    )
    approval = store.get_script_approval(job.job_id, 1)
    assert approval is not None
    assert approval["approved_edit_script"]["change_rows"][0]["change_id"] == "PH01"
    assert approval["approved_edit_script"]["change_rows"][2]["text"] == "User approved title"

    overlay_rows = [
        {
            key: row[key]
            for key in ("change_id", "start_ms", "end_ms", "text_target", "layer", "text", "instruction")
        }
        for row in approval["approved_edit_script"]["change_rows"]
        if row.get("kind") == "text" and row.get("layer") == "overlay"
    ]
    overlay_plan_body = {
        "contract": "approved-overlay-plan/v1",
        "approved_script_revision": 1,
        "approved_script_sha256": script_sha,
        "source_video_sha256": sha256(source.read_bytes()).hexdigest(),
        "overlays": overlay_rows,
    }
    overlay_plan_sha = sha256(
        json.dumps(overlay_plan_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    overlay_plan = {**overlay_plan_body, "overlay_plan_sha256": overlay_plan_sha}
    overlay_plan_bytes = json.dumps(
        overlay_plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    overlay_plan_path = tmp_path / "approved-overlay-plan.json"
    overlay_plan_path.write_bytes(overlay_plan_bytes)
    overlay_descriptor = {
        "artifact_id": "approved-overlay-plan-1",
        "kind": "approved-overlay-plan/v1",
        "sha256": sha256(overlay_plan_bytes).hexdigest(),
        "metadata": {"approved_script_sha256": script_sha, "revision": 1},
    }
    sidecar_bytes = json.dumps(
        approval, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    sidecar_path = tmp_path / "approved-script-lines-v2.json"
    sidecar_path.write_bytes(sidecar_bytes)
    sidecar_descriptor = {
        "artifact_id": "approved-script-lines-1",
        "kind": "approved-script-lines/v2",
        "sha256": sha256(sidecar_bytes).hexdigest(),
        "metadata": {"revision": 1, "script_sha256": script_sha},
    }
    _boundary, _window, timeline_regions = _phase4_timeline_case(
        tmp_path, "overlay", source, source, sha256(source.read_bytes()).hexdigest(), has_ui=False, has_tail=True
    )
    timeline_regions = [dict(timeline_regions[0])]
    timeline_regions[0]["source_end_us"] = 2_000_000
    expected = {
        "contract": "approved-overlay-composite/v1",
        "receipt_fields": {
            "contract": "approved-overlay-composite/v1",
            "approved_script_revision": 1,
            "approved_script_sha256": script_sha,
            "overlay_plan_sha256": overlay_plan_sha,
            "source_video_sha256": sha256(source.read_bytes()).hexdigest(),
        },
        "base_receipt_fields": {
            "contract": "approved-overlay-composite/v1",
            "source_video_sha256": sha256(source.read_bytes()).hexdigest(),
        },
        "lineage": {
            "approved_script_revision": 1,
            "approved_script_sha256": script_sha,
            "overlay_plan_sha256": overlay_plan_sha,
            "source_video_sha256": sha256(source.read_bytes()).hexdigest(),
        },
        "compositor_identity": None,
        "materialize_slots": [],
        "placement_kinds": ["source_body"],
    }
    Context = _phase4_recording_context(tmp_path, "overlay", {"source_video": source}, timeline_regions, expected)
    context = Context()
    context.job_id = job.job_id
    context.snapshot = store.get_job(job.job_id)
    context.job_store = store
    context.render_calls = 0
    context.overlay_plan_calls = 0
    context.captured_overlay_plan = None
    context.input_artifacts = [sidecar_descriptor, overlay_descriptor]
    context.artifacts = [sidecar_descriptor, overlay_descriptor]

    @contextmanager
    def materialize_artifact(_kind: str, *, artifact_id: str, sha256: str, **_kwargs):
        paths = {
            sidecar_descriptor["artifact_id"]: sidecar_path,
            overlay_descriptor["artifact_id"]: overlay_plan_path,
        }
        path = paths[artifact_id]
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != sha256:
            from server.errors import ReplicationError

            raise ReplicationError("ARTIFACT_HASH_MISMATCH", "recorded artifact SHA is stale")
        yield SimpleNamespace(path=path, sha256=actual)

    context.materialize_artifact = materialize_artifact
    return context, store, expected, overlay_plan, overlay_plan_sha, overlay_descriptor


def _phase4_tamper_overlay(
    *, tamper: str, context, tmp_path: Path, store, overlay_plan: dict[str, object], overlay_descriptor: dict[str, object]
) -> None:
    from dataclasses import replace

    sidecar_descriptor = context.input_artifacts[0]
    script_sha = str(sidecar_descriptor["metadata"]["script_sha256"])
    if tamper == "stale_script":
        approval = store.get_script_approval(context.job_id, 1)
        assert approval["script_sha256"] == script_sha
        assert sidecar_descriptor["metadata"]["script_sha256"] == script_sha
        context.snapshot = replace(context.snapshot, approved_script_sha256="0" * 64)
        assert context.snapshot.approved_script_sha256 != approval["script_sha256"]
        assert context.snapshot.approved_script_sha256 != sidecar_descriptor["metadata"]["script_sha256"]
        return
    if tamper == "overlay_artifact_sha":
        path = tmp_path / "approved-overlay-plan.json"
        overlay_descriptor["sha256"] = "0" * 64
        assert sha256(path.read_bytes()).hexdigest() != overlay_descriptor["sha256"]
    else:
        poisoned_rows = [
            {
                "change_id": "PH01",
                "start_ms": 100,
                "end_ms": 300,
                "text_target": "physical-text",
                "layer": "physical",
                "text": "Printed surface label",
                "instruction": "send physical text to post compositor",
            },
            dict(overlay_plan["overlays"][0]),
            {**dict(overlay_plan["overlays"][1]), "text": "Planner title"},
        ]
        poison_body = {key: value for key, value in overlay_plan.items() if key != "overlay_plan_sha256"}
        poison_body["overlays"] = poisoned_rows
        poison_plan_sha = sha256(
            json.dumps(poison_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        poison_bytes = json.dumps(
            {**poison_body, "overlay_plan_sha256": poison_plan_sha},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        (tmp_path / "approved-overlay-plan.json").write_bytes(poison_bytes)
        overlay_descriptor["sha256"] = sha256(poison_bytes).hexdigest()
        overlay_descriptor["metadata"] = {"approved_script_sha256": script_sha, "revision": 1}
        assert overlay_descriptor["sha256"] != overlay_plan["overlay_plan_sha256"]
    context.input_artifacts = [sidecar_descriptor, overlay_descriptor]


def _phase4_song_manifest_case(tmp_path: Path, source: Path):
    from server.approved_edit_contract import build_approved_edit_script
    from server.performance_audio_contracts import canonical_json_sha256

    source_sha = sha256(source.read_bytes()).hexdigest()
    audio_plan = {
        "mv_lip_sync_route": "song_lipsync",
        "ui_monologue_protection_windows": [{"start_ms": 2500, "end_ms": 5500}],
    }
    source_timeline = {
        "contract": "source-content-timeline/v1",
        "source_video_sha256": source_sha,
        "song_windows": [{"event_id": "song-1", "start_ms": 0, "end_ms": 8000}],
    }
    source_classification = {
        "contract": "uploaded-audio-classification/v1",
        "kind": "song",
        "source_sha256": "e" * 64,
    }
    source_timeline_path = tmp_path / "source-content-timeline.json"
    source_timeline_path.write_text(
        json.dumps(source_timeline, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    source_classification_path = tmp_path / "uploaded-audio-classification.json"
    source_classification_path.write_text(
        json.dumps(source_classification, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    lineage = {
        "approved_audio_plan_revision": 1,
        "approved_audio_plan_sha256": canonical_json_sha256(audio_plan),
        "approved_script_sha256": "b" * 64,
        "source_timeline_sha256": sha256(source_timeline_path.read_bytes()).hexdigest(),
        "source_classification_sha256": sha256(source_classification_path.read_bytes()).hexdigest(),
        "new_song_sha256": "e" * 64,
        "provider_output_sha256": "f" * 64,
    }
    workflow = "runninghub-song-lip-sync/v1"
    segment_rows = []
    segment_artifacts = []
    for index, (start_ms, end_ms, input_sha, output_sha) in enumerate(
        ((0, 2500, "1" * 64, "2" * 64), (5500, 8000, "3" * 64, "4" * 64)),
        start=1,
    ):
        segment_id = f"song-window-{index:02d}"
        receipt = {
            "segment_id": segment_id,
            "input_sha256": input_sha,
            "song_start": f"0:{start_ms // 1000:02d}.{start_ms % 1000:03d}",
            "song_end": f"0:{end_ms // 1000:02d}.{end_ms % 1000:03d}",
            "output_sha256": output_sha,
            "workflow_identity": workflow,
        }
        metadata = {
            "segment_id": segment_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "input_clip_sha256": input_sha,
            "output_sha256": output_sha,
            "workflow_identity": workflow,
            "workflow_receipt": dict(receipt),
        }
        artifact = {
            "artifact_id": f"song-segment-{index}",
            "kind": "song_lip_sync_segment_video",
            "sha256": output_sha,
            "metadata": metadata,
        }
        segment_artifacts.append(artifact)
        segment_rows.append({
            "segment_id": segment_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "input_clip_sha256": input_sha,
            "output_sha256": output_sha,
            "artifact": artifact,
            "workflow_receipt": receipt,
            "workflow_identity": workflow,
        })
    manifest_body = {
        "contract": "song-lip-sync-segment-manifest/v1",
        "schema_version": "song-lip-sync-segment-manifest/v1",
        "contract_version": "1",
        **lineage,
        "original_song_windows": [{"start_ms": 0, "end_ms": 8000}],
        "effective_song_windows": [
            {"start_ms": 0, "end_ms": 2500},
            {"start_ms": 5500, "end_ms": 8000},
        ],
        "ui_monologue_protection_windows": [{"start_ms": 2500, "end_ms": 5500}],
        "segments": segment_rows,
        "protected_source_intervals": [{
            "start_ms": 2500,
            "end_ms": 5500,
            "provider_output_sha256": lineage["provider_output_sha256"],
        }],
        "assembly_order": [
            {"kind": "lip_sync", "start_ms": 0, "end_ms": 2500},
            {"kind": "protected_source", "start_ms": 2500, "end_ms": 5500},
            {"kind": "lip_sync", "start_ms": 5500, "end_ms": 8000},
        ],
        "workflow_identity": workflow,
    }
    manifest = {**manifest_body, "manifest_sha256": canonical_json_sha256(manifest_body)}
    manifest_path = tmp_path / "song-lip-sync-segment-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    manifest_descriptor = {
        "artifact_id": "song-manifest-1",
        "kind": "song_lip_sync_segment_manifest",
        "sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        "metadata": {"manifest_sha256": manifest["manifest_sha256"], **lineage},
    }
    provider_artifact = {
        "artifact_id": "provider-video-1",
        "kind": "provider_video",
        "sha256": lineage["provider_output_sha256"],
    }
    source_timeline_descriptor = {
        "artifact_id": "source-timeline-1",
        "kind": "source_content_timeline",
        "sha256": lineage["source_timeline_sha256"],
    }
    source_classification_descriptor = {
        "artifact_id": "source-classification-1",
        "kind": "uploaded_audio_classification",
        "sha256": lineage["source_classification_sha256"],
    }
    _boundary, _window, timeline_regions = _phase4_timeline_case(
        tmp_path, "song-manifest", source, source, source_sha, has_ui=False, has_tail=True
    )
    timeline_regions = [dict(timeline_regions[0])]
    timeline_regions[0]["source_end_us"] = 2_000_000
    expected = {
        "contract": "song-lip-sync-assembly/v1",
        "receipt_fields": {"contract": "song-lip-sync-assembly/v1", "source_video_sha256": source_sha},
        "base_receipt_fields": {"contract": "song-lip-sync-assembly/v1", "source_video_sha256": source_sha},
        "lineage": {"source_video_sha256": source_sha},
        "compositor_identity": None,
        "materialize_slots": [],
        "placement_kinds": ["source_body"],
    }
    Context = _phase4_recording_context(tmp_path, "song-manifest", {"source_video": source}, timeline_regions, expected)
    context = Context()
    context.snapshot = SimpleNamespace(
        current_script_revision=1,
        approved_script_sha256=lineage["approved_script_sha256"],
        slots_manifest={
            "extensions": {"background_music": {"kind": "song", "sha256": [lineage["new_song_sha256"]]}},
            "audio_plan": {"mv_lip_sync_route": "song_lipsync"},
        },
    )
    context.render_calls = 0
    context.song_lip_sync_lineage = dict(lineage)
    context.job_id = "song-manifest-job"
    context.job_store = SimpleNamespace(
        get_script_approval=lambda job_id, revision: {
            "contract": "approved-script-lines/v2",
            "revision": revision,
            "script_sha256": lineage["approved_script_sha256"],
            "audio_plan": dict(audio_plan),
            "audio_plan_sha256": lineage["approved_audio_plan_sha256"],
            "approved_edit_script": build_approved_edit_script([], []),
        }
    )
    context.artifacts = [
        manifest_descriptor,
        provider_artifact,
        source_timeline_descriptor,
        source_classification_descriptor,
        *segment_artifacts,
    ]
    context.manifest_path = manifest_path

    @contextmanager
    def materialize_artifact(_kind: str, *, artifact_id: str, sha256: str, **_kwargs):
        paths = {
            manifest_descriptor["artifact_id"]: manifest_path,
            source_timeline_descriptor["artifact_id"]: source_timeline_path,
            source_classification_descriptor["artifact_id"]: source_classification_path,
        }
        path = paths[artifact_id]
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != sha256:
            from server.errors import ReplicationError

            raise ReplicationError("ARTIFACT_HASH_MISMATCH", "song manifest descriptor SHA is stale", category="artifact")
        yield SimpleNamespace(path=path, sha256=actual)

    context.materialize_artifact = materialize_artifact
    context.input_artifacts = [manifest_descriptor]
    return context, manifest, manifest_descriptor, lineage


def _phase4_rehash_song_manifest(manifest: dict[str, object]) -> dict[str, object]:
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    from server.performance_audio_contracts import canonical_json_sha256

    return {**body, "manifest_sha256": canonical_json_sha256(body)}


def _phase4_replace_song_manifest(context, descriptor, manifest) -> None:
    context.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    descriptor["sha256"] = sha256(context.manifest_path.read_bytes()).hexdigest()
    descriptor["metadata"]["manifest_sha256"] = manifest["manifest_sha256"]


def _phase5_bind_song_media(context, media_paths: dict[str, Path]) -> None:
    original_materialize_artifact = context.materialize_artifact

    @contextmanager
    def materialize_artifact(kind: str, *, artifact_id: str, sha256: str, **kwargs):
        media_path = media_paths.get(artifact_id)
        if media_path is not None:
            actual = hashlib.sha256(media_path.read_bytes()).hexdigest()
            if actual != sha256:
                from server.errors import ReplicationError

                raise ReplicationError(
                    "ARTIFACT_HASH_MISMATCH",
                    "song render media descriptor SHA is stale",
                    category="artifact",
                )
            yield SimpleNamespace(path=media_path, sha256=actual)
            return
        with original_materialize_artifact(
            kind, artifact_id=artifact_id, sha256=sha256, **kwargs
        ) as media:
            yield media

    context.materialize_artifact = materialize_artifact


def _phase5_prepare_song_media_case(
    tmp_path: Path, source: Path, segment_media: list[Path]
):
    context, manifest, descriptor, lineage = _phase4_song_manifest_case(tmp_path, source)
    source_sha = sha256(source.read_bytes()).hexdigest()

    provider = next(item for item in context.artifacts if item.get("kind") == "provider_video")
    provider["sha256"] = source_sha
    manifest["provider_output_sha256"] = source_sha
    manifest["protected_source_intervals"][0]["provider_output_sha256"] = source_sha
    context.song_lip_sync_lineage["provider_output_sha256"] = source_sha

    if len(segment_media) != len(manifest["segments"]):
        raise AssertionError("song media count must match the approved segment rows")
    for row, media_path in zip(manifest["segments"], segment_media, strict=True):
        output_sha = sha256(media_path.read_bytes()).hexdigest()
        row["output_sha256"] = output_sha
        row["workflow_receipt"]["output_sha256"] = output_sha
        row["artifact"]["sha256"] = output_sha
        row["artifact"]["metadata"]["output_sha256"] = output_sha
        row["artifact"]["metadata"]["workflow_receipt"] = dict(row["workflow_receipt"])
        descriptor_row = next(
            item for item in context.artifacts
            if item.get("artifact_id") == row["artifact"]["artifact_id"]
        )
        descriptor_row["sha256"] = output_sha
        descriptor_row["content_type"] = "video/mp4"
        descriptor_row["metadata"]["output_sha256"] = output_sha
        descriptor_row["metadata"]["workflow_receipt"] = dict(row["workflow_receipt"])

    manifest = _phase4_rehash_song_manifest(manifest)
    _phase4_replace_song_manifest(context, descriptor, manifest)
    end_ms = max(int(item["end_ms"]) for item in manifest["original_song_windows"])
    context.timeline_regions = [{
        "region_type": "source_interval",
        "region_id": "provider-source",
        "source_start_us": 0,
        "source_end_us": end_ms * 1000,
        "media_origin": "source_interval",
        "assembly_policy": "splice_source_interval",
        "slot_id": "source_video",
        "placement_kind": "source_body",
    }]
    context.input_artifacts = [descriptor]
    media_paths = {
        provider["artifact_id"]: source,
        **{
            row["artifact"]["artifact_id"]: media_path
            for row, media_path in zip(manifest["segments"], segment_media, strict=True)
        },
    }
    _phase5_bind_song_media(context, media_paths)
    return context, manifest, descriptor, lineage


def _phase5_prepare_nonfull_song_case(
    tmp_path: Path, source: Path, segment_media: list[tuple[int, int, Path]]
):
    from copy import deepcopy
    from server.performance_audio_contracts import canonical_json_sha256

    context, manifest, descriptor, lineage = _phase4_song_manifest_case(tmp_path, source)
    source_sha = sha256(source.read_bytes()).hexdigest()
    source_timeline_path = tmp_path / "source-content-timeline.json"
    original_windows = [
        {"start_ms": 1000, "end_ms": 4000},
        {"start_ms": 6000, "end_ms": 8000},
    ]
    protection_windows = [{"start_ms": 2500, "end_ms": 3000}]
    effective_windows = [
        {"start_ms": 1000, "end_ms": 2500},
        {"start_ms": 3000, "end_ms": 4000},
        {"start_ms": 6000, "end_ms": 8000},
    ]
    source_timeline_path.write_text(
        json.dumps({
            "contract": "source-content-timeline/v1",
            "source_video_sha256": source_sha,
            "song_windows": [
                {"event_id": "song-1", **original_windows[0]},
                {"event_id": "song-2", **original_windows[1]},
            ],
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    audio_plan = {
        "mv_lip_sync_route": "song_lipsync",
        "ui_monologue_protection_windows": protection_windows,
    }
    timeline_sha = sha256(source_timeline_path.read_bytes()).hexdigest()
    lineage.update({
        "approved_audio_plan_sha256": canonical_json_sha256(audio_plan),
        "source_timeline_sha256": timeline_sha,
        "provider_output_sha256": source_sha,
    })
    provider = next(item for item in context.artifacts if item.get("kind") == "provider_video")
    provider["sha256"] = source_sha
    context.song_lip_sync_lineage.update(lineage)
    context.snapshot.slots_manifest["audio_plan"] = dict(audio_plan)
    source_descriptor = next(
        item for item in context.artifacts if item.get("kind") == "source_content_timeline"
    )
    source_descriptor["sha256"] = timeline_sha
    approval = context.job_store.get_script_approval(context.job_id, 1)
    context.job_store = SimpleNamespace(
        get_script_approval=lambda _job_id, _revision: {
            **approval,
            "audio_plan": dict(audio_plan),
            "audio_plan_sha256": lineage["approved_audio_plan_sha256"],
        }
    )

    workflow_identity = manifest["workflow_identity"]
    rows = []
    descriptors = []
    for index, (start_ms, end_ms, media_path) in enumerate(segment_media, start=1):
        output_sha = sha256(media_path.read_bytes()).hexdigest()
        segment_id = f"song-nonfull-{index:02d}"
        input_sha = sha256(f"song-input-{index}".encode("utf-8")).hexdigest()
        receipt = {
            "segment_id": segment_id,
            "input_sha256": input_sha,
            "song_start": f"0:{start_ms // 1000:02d}.{start_ms % 1000:03d}",
            "song_end": f"0:{end_ms // 1000:02d}.{end_ms % 1000:03d}",
            "output_sha256": output_sha,
            "workflow_identity": workflow_identity,
        }
        artifact = {
            "artifact_id": f"song-nonfull-segment-{index}",
            "kind": "song_lip_sync_segment_video",
            "sha256": output_sha,
            "metadata": {
                "segment_id": segment_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "input_clip_sha256": input_sha,
                "output_sha256": output_sha,
                "workflow_identity": workflow_identity,
                "workflow_receipt": dict(receipt),
            },
        }
        row = {
            "segment_id": segment_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "input_clip_sha256": input_sha,
            "output_sha256": output_sha,
            "artifact": artifact,
            "workflow_receipt": receipt,
            "workflow_identity": workflow_identity,
        }
        rows.append(row)
        descriptors.append(artifact)

    manifest.update(lineage)
    manifest["original_song_windows"] = original_windows
    manifest["effective_song_windows"] = effective_windows
    manifest["ui_monologue_protection_windows"] = protection_windows
    manifest["segments"] = rows
    manifest["protected_source_intervals"] = [
        {**protection_windows[0], "provider_output_sha256": source_sha}
    ]
    manifest["assembly_order"] = [
        {"kind": "lip_sync", **effective_windows[0]},
        {"kind": "protected_source", **protection_windows[0]},
        {"kind": "lip_sync", **effective_windows[1]},
        {"kind": "lip_sync", **effective_windows[2]},
    ]
    context.artifacts = [
        item for item in context.artifacts
        if item.get("kind") != "song_lip_sync_segment_video"
    ] + descriptors
    manifest = _phase4_rehash_song_manifest(manifest)
    _phase4_replace_song_manifest(context, descriptor, manifest)
    context.timeline_regions = [{
        "region_type": "source_interval",
        "region_id": "provider-source",
        "source_start_us": 0,
        "source_end_us": 10_000_000,
        "media_origin": "source_interval",
        "assembly_policy": "splice_source_interval",
        "slot_id": "source_video",
        "placement_kind": "source_body",
    }]
    context.input_artifacts = [descriptor]
    _phase5_bind_song_media(
        context,
        {
            "provider-video-1": source,
            **{
                row["artifact"]["artifact_id"]: media_path
                for row, (_start, _end, media_path) in zip(rows, segment_media, strict=True)
            },
        },
    )
    return context, manifest, descriptor, lineage


def _phase4_song_manifest_tamper(manifest: dict[str, object], tamper: str) -> dict[str, object]:
    from copy import deepcopy

    poisoned = deepcopy(manifest)
    if tamper == "artifact_sha":
        poisoned["segments"][0]["artifact"]["sha256"] = "9" * 64
    elif tamper == "artifact_kind":
        poisoned["segments"][0]["artifact"]["kind"] = "song_lip_sync_video"
    elif tamper == "artifact_metadata":
        poisoned["segments"][0]["artifact"]["metadata"]["start_ms"] = 999
    elif tamper == "workflow_receipt":
        poisoned["segments"][0]["workflow_receipt"]["output_sha256"] = "9" * 64
    elif tamper == "protected_provider":
        poisoned["protected_source_intervals"][0]["provider_output_sha256"] = "9" * 64
    elif tamper == "stale_provider":
        poisoned["provider_output_sha256"] = "9" * 64
        poisoned["protected_source_intervals"][0]["provider_output_sha256"] = "9" * 64
    elif tamper == "assembly_order":
        poisoned["assembly_order"] = list(reversed(poisoned["assembly_order"]))
    elif tamper == "workflow_identity":
        poisoned["workflow_identity"] = "runninghub-song-lip-sync/v2"
    elif tamper == "approved_protection_windows":
        poisoned["ui_monologue_protection_windows"] = [{"start_ms": 3000, "end_ms": 5000}]
    elif tamper == "approved_audio_plan_revision":
        poisoned["approved_audio_plan_revision"] = 2
    elif tamper in {
        "approved_audio_plan_sha256",
        "approved_script_sha256",
        "source_timeline_sha256",
        "source_classification_sha256",
        "new_song_sha256",
    }:
        poisoned[tamper] = "9" * 64
    else:
        raise AssertionError(f"unknown song manifest tamper: {tamper}")
    return _phase4_rehash_song_manifest(poisoned)


def _phase4_rebind_song_manifest_windows(manifest: dict[str, object], *, shift_ms: int) -> dict[str, object]:
    from copy import deepcopy

    poisoned = deepcopy(manifest)

    def shifted(interval: dict[str, int]) -> dict[str, int]:
        return {
            "start_ms": interval["start_ms"] + shift_ms,
            "end_ms": interval["end_ms"] + shift_ms,
        }

    poisoned["original_song_windows"] = [shifted(item) for item in manifest["original_song_windows"]]
    poisoned["effective_song_windows"] = [shifted(item) for item in manifest["effective_song_windows"]]
    poisoned["ui_monologue_protection_windows"] = [
        shifted(item) for item in manifest["ui_monologue_protection_windows"]
    ]
    for row, window in zip(poisoned["segments"], poisoned["effective_song_windows"], strict=True):
        row["start_ms"], row["end_ms"] = window["start_ms"], window["end_ms"]
        receipt = row["workflow_receipt"]
        receipt["song_start"] = f"0:{window['start_ms'] // 1000:02d}.{window['start_ms'] % 1000:03d}"
        receipt["song_end"] = f"0:{window['end_ms'] // 1000:02d}.{window['end_ms'] % 1000:03d}"
        metadata = row["artifact"]["metadata"]
        metadata["start_ms"], metadata["end_ms"] = window["start_ms"], window["end_ms"]
        metadata["workflow_receipt"] = dict(receipt)
    poisoned["protected_source_intervals"] = [
        {
            **shifted(item),
            "provider_output_sha256": item["provider_output_sha256"],
        }
        for item in manifest["protected_source_intervals"]
    ]
    poisoned["assembly_order"] = [
        {"kind": item["kind"], **shifted(item)} for item in manifest["assembly_order"]
    ]
    return _phase4_rehash_song_manifest(poisoned)


def _phase4_add_source_overlay_contract(context) -> dict[str, object]:
    payload = {"text": "Source approved caption", "verification_required": False}
    source_contract = {
        "contract": "source-ui-overlay-motion",
        "contract_version": 1,
        "reference_duration_us": 2_000_000,
        "cuts": [{
            "cut_id": "C01",
            "start_us": 0,
            "end_us": 2_000_000,
            "source_overlays": [{
                "overlay_id": "source-overlay-1",
                "kind": "subtitle",
                "start_us": 100_000,
                "end_us": 900_000,
                "observed_text": "Source caption",
            }],
        }],
    }
    source_contract_sha = sha256(
        json.dumps(source_contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload_sha = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    source_mapping = {
        "contract": "target-overlay-render-mapping",
        "contract_version": 1,
        "source_overlay_contract_sha256": source_contract_sha,
        "regions": [{
            "region_id": "body",
            "overlays": [{
                "overlay_id": "source-overlay-1",
                "validated": True,
                "render_mode": "deterministic_text",
                "text": "Source approved caption",
                "payload": payload,
                "payload_sha256": payload_sha,
            }],
        }],
    }
    source_mapping_sha = sha256(
        json.dumps(source_mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    context.timeline_regions[0].update({
        "region_type": "generated",
        "media_origin": "generated_media",
        "assembly_policy": "generate_region",
        "source_overlay_contract": source_contract,
        "source_overlay_contract_sha256": source_contract_sha,
        "overlay_render_mapping": source_mapping,
        "overlay_render_mapping_sha256": source_mapping_sha,
    })
    source_plan = {
        "source_overlay_contract_sha256": source_contract_sha,
        "overlay_render_mapping_sha256": source_mapping_sha,
        "required_payloads": {
            ("body", "source-overlay-1"): {
                "payload_sha256": payload_sha,
                "render_mode": "deterministic_text",
                "verification_required": False,
            }
        },
    }
    context.expected_receipt_inputs["source_overlay_receipt_fields"] = {
        "source_overlay_contract_sha256": source_contract_sha,
        "overlay_render_mapping_sha256": source_mapping_sha,
    }
    context.expected_receipt_inputs["source_overlay_receipts"] = [{
        "region_id": "body",
        "overlay_id": "source-overlay-1",
        "source_overlay_contract_sha256": source_contract_sha,
        "overlay_render_mapping_sha256": source_mapping_sha,
        "payload_sha256": payload_sha,
        "frame_windows": [{"start_ms": 100, "end_ms": 900}],
    }]
    return {
        "source_overlay_contract_sha256": source_contract_sha,
        "overlay_render_mapping_sha256": source_mapping_sha,
        "source_plan": source_plan,
    }


def _phase4_receipt_failures(result, expected: dict[str, object]) -> list[str]:
    manifest = result.get("timeline_manifest") or {}
    receipt = (manifest.get("transition_renders") or [{}])[0]
    output_sha = (result.get("output_artifact") or {}).get("sha256")
    failures: list[str] = []
    if receipt.get("contract") != expected["contract"] or receipt.get("contract_version") != "1.0":
        failures.append("receipt contract/version is invalid")
    for field, value in expected["receipt_fields"].items():
        if receipt.get(field) != value:
            failures.append(f"receipt field mismatch: {field}")
    if receipt.get("renderer_identity", {}).get("version") != "phase4-shared-red-v1":
        failures.append("receipt omits renderer identity/version")
    if receipt.get("compositor_identity") != expected["compositor_identity"]:
        failures.append("receipt omits compositor identity/version")
    if receipt.get("output_sha256") != output_sha:
        failures.append("receipt output SHA differs from published artifact")
    lineage = receipt.get("output_lineage") or {}
    for field, value in expected["lineage"].items():
        if lineage.get(field) != value:
            failures.append(f"output lineage mismatch: {field}")
    placements = receipt.get("placements") or []
    if [item.get("kind") for item in placements] != expected["placement_kinds"]:
        failures.append("placement order does not follow timeline regions")
    return failures


def _phase4_build_ports(
    monkeypatch, *, emit_transition_receipts: bool = True, capture_coexisting_plans: bool = False
):
    import server.packaged_ports as packaged_ports

    monkeypatch.setattr(
        packaged_ports,
        "BundledTimelineRenderer",
        _phase4_recording_renderer(
            emit_transition_receipts=emit_transition_receipts,
            capture_coexisting_plans=capture_coexisting_plans,
        ),
    )
    _configure_environment(monkeypatch)
    ports = packaged_ports.build_ports()
    compositor_port = ports["capability_ports"]["compositor"]
    return ports, compositor_port.adapter.capability_identity()


def test_v2_ui_operation_video_only_uses_deterministic_splice_and_preserves_source_ui_when_empty(
    tmp_path: Path, monkeypatch
) -> None:
    from bind_input_slots import bind_slots, validate_slots
    from server.orchestrator import build_stage_plan

    source = tmp_path / "source.mp4"
    operation = tmp_path / "ui-operation.mp4"
    _phase4_make_video(source, "black", 2.0)
    _phase4_make_video(operation, "blue", 2.0)
    source_sha = sha256(source.read_bytes()).hexdigest()
    operation_sha = sha256(operation.read_bytes()).hexdigest()
    manifest = bind_slots({"source_video": source, "ui_operation_video": operation}, edit_mode="v2")
    assert manifest["routes"]["ui"] == "splice_ui_operation_video"
    plan = build_stage_plan(manifest)
    failures = _phase4_forbidden_plan_failures(
        plan, "ffmpeg_deterministic_splice", "remove_source_tail_card"
    )

    _boundary, window, timeline_regions = _phase4_timeline_case(
        tmp_path, "ui-only", source, operation, operation_sha, has_ui=True, has_tail=False
    )

    ports, compositor_identity = _phase4_build_ports(monkeypatch)
    expected = {
        "contract": "ui-operation-video-splice/v1",
        "receipt_fields": {
            "contract": "ui-operation-video-splice/v1",
            "source_video_sha256": source_sha,
            "ui_operation_video_sha256": operation_sha,
            "source_ui_window": window,
        },
        "lineage": {
            "source_video_sha256": source_sha,
            "ui_operation_video_sha256": operation_sha,
            "source_ui_window": window,
        },
        "compositor_identity": compositor_identity,
        "materialize_slots": [{"slot_id": "ui_operation_video", "sha256": operation_sha}],
        "placement_kinds": ["source_body", "ui_operation_video"],
    }
    Context = _phase4_recording_context(
        tmp_path, "ui-only", {"source_video": source, "ui_operation_video": operation},
        timeline_regions, expected,
    )
    result_context = Context()
    result = ports["stage_ports"]["splice_timeline"].run(context=result_context, input_artifacts=[])
    failures.extend(_phase4_receipt_failures(result, expected))
    if result_context.recorded_materializations != [{"slot": "ui_operation_video", "sha256": operation_sha}]:
        failures.append("operation slot was not materialized exactly once")

    no_ui = validate_slots({"source_video": source}, edit_mode="v2")
    no_ui_plan = build_stage_plan(no_ui)
    if no_ui["routes"]["ui"] != "preserve_source_ui":
        failures.append("no-UI route is not preserve_source_ui")
    no_ui_names = {str(item["name"]) for item in no_ui_plan}
    if {"generated_ui_demo", "ocr_ui_renderer"} & no_ui_names:
        failures.append("no-UI plan contains generated UI stages")
    if "generate_asset_boards" not in no_ui_names:
        failures.append("no-UI v2 plan is missing its zero-paid asset-board contract stage")
    assert not failures, "\\n".join(failures)


def test_v2_tail_video_routes_deterministic_assembly_for_tail_only_and_ui_tail_cases(
    tmp_path: Path, monkeypatch
) -> None:
    from bind_input_slots import bind_slots
    from server.orchestrator import build_stage_plan

    source = tmp_path / "source.mp4"
    operation = tmp_path / "ui-operation.mp4"
    tail = tmp_path / "tail.mp4"
    _phase4_make_video(source, "black", 2.0)
    _phase4_make_video(operation, "blue", 0.5)
    _phase4_make_video(tail, "yellow", 0.6)
    source_sha = sha256(source.read_bytes()).hexdigest()
    operation_sha = sha256(operation.read_bytes()).hexdigest()
    tail_sha = sha256(tail.read_bytes()).hexdigest()
    ports, compositor_identity = _phase4_build_ports(monkeypatch)
    failures: list[str] = []

    cases = (
        ("tail-only", {"source_video": source, "tail_video": tail}, False),
        ("ui-and-tail", {"source_video": source, "ui_operation_video": operation, "tail_video": tail}, True),
    )
    for case_name, slot_values, has_ui in cases:
        manifest = bind_slots(slot_values, edit_mode="v2")
        failures.extend(
            f"{case_name}: {item}"
            for item in _phase4_forbidden_plan_failures(
                build_stage_plan(manifest),
                "ffmpeg_deterministic_splice" if has_ui else "preserve_source_ui",
                "splice_tail_video",
            )
        )
        boundary, window, timeline_regions = _phase4_timeline_case(
            tmp_path, case_name, source, operation, operation_sha,
            has_ui=has_ui, has_tail=True,
        )
        expected = {
            "contract": "deterministic-video-assembly/v1",
            "receipt_fields": {
                "contract": "deterministic-video-assembly/v1",
                "source_video_sha256": source_sha,
                "tail_video_sha256": tail_sha,
                "terminal_boundary": boundary,
            },
            "lineage": {
                "source_video_sha256": source_sha,
                "tail_video_sha256": tail_sha,
                "terminal_boundary": boundary,
            },
            "compositor_identity": compositor_identity,
            "materialize_slots": (
                [{"slot_id": "ui_operation_video", "sha256": operation_sha}] if has_ui else []
            ) + [{"slot_id": "tail_video", "sha256": tail_sha}],
            "placement_kinds": ["source_body"] + (["ui_operation_video"] if has_ui else []) + ["tail_video"],
        }
        Context = _phase4_recording_context(
            tmp_path, case_name,
            {"source_video": source, "ui_operation_video": operation, "tail_video": tail},
            timeline_regions, expected,
        )
        result_context = Context()
        try:
            result = ports["stage_ports"]["splice_timeline"].run(context=result_context, input_artifacts=[])
        except Exception as exc:
            failures.append(f"{case_name}: real splice_timeline StagePort failed: {exc}")
            continue
        failures.extend(f"{case_name}: {item}" for item in _phase4_receipt_failures(result, expected))
        expected_slots = [
            {"slot": "ui_operation_video", "sha256": operation_sha}
        ] if has_ui else []
        expected_slots.append({"slot": "tail_video", "sha256": tail_sha})
        if result_context.recorded_materializations != expected_slots:
            failures.append(f"{case_name}: UI/tail slots were not materialized exactly once")

    assert not failures, "\\n".join(failures)


def test_v2_approved_overlay_sidecar_reaches_real_splice_boundary_and_excludes_physical_text(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.mp4"
    _phase4_make_video(source, "black", 2.0)
    context, _store, expected, overlay_plan, _overlay_plan_sha, _overlay_descriptor = (
        _phase4_approved_overlay_case(tmp_path, source)
    )
    ports, compositor_identity = _phase4_build_ports(monkeypatch)
    expected["compositor_identity"] = compositor_identity
    context.expected_receipt_inputs["compositor_identity"] = compositor_identity

    result = ports["stage_ports"]["splice_timeline"].run(
        context=context, input_artifacts=context.input_artifacts
    )
    failures = _phase4_receipt_failures(result, expected)
    captured = context.captured_overlay_plan
    if captured is None:
        failures.append("approved-script-lines/v2 did not produce an overlay render plan")
    else:
        if captured != overlay_plan:
            failures.append("overlay plan did not round-trip the approved sidecar")
        overlays = captured.get("overlays") or []
        if any(row.get("layer") != "overlay" for row in overlays):
            failures.append("physical/surface text entered the post overlay plan")
        if [row.get("change_id") for row in overlays] != ["OV01", "OV02"]:
            failures.append("overlay rows are not in canonical time/change order")
        if [row.get("text") for row in overlays] != ["Approved price $19", "User approved title"]:
            failures.append("overlay plan did not use the user-approved text")
    if context.render_calls != 1:
        failures.append("compositor was not called exactly once")
    if context.overlay_plan_calls != 1:
        failures.append("overlay renderer/plan was not invoked exactly once")

    plain_expected = {
        "contract": "plain-source-composite/v1",
        "receipt_fields": {
            "contract": "plain-source-composite/v1",
            "source_video_sha256": sha256(source.read_bytes()).hexdigest(),
        },
        "lineage": {"source_video_sha256": sha256(source.read_bytes()).hexdigest()},
        "compositor_identity": compositor_identity,
        "materialize_slots": [],
        "placement_kinds": ["source_body"],
    }
    _boundary, _window, regions = _phase4_timeline_case(
        tmp_path, "plain-source", source, source, sha256(source.read_bytes()).hexdigest(), has_ui=False, has_tail=True
    )
    regions = [dict(regions[0])]
    regions[0]["source_end_us"] = 2_000_000
    PlainContext = _phase4_recording_context(tmp_path, "plain-source", {"source_video": source}, regions, plain_expected)
    plain_context = PlainContext()
    plain_context.render_calls = 0
    plain_context.overlay_plan_calls = 0
    plain_context.captured_overlay_plan = None
    plain_result = ports["stage_ports"]["splice_timeline"].run(
        context=plain_context, input_artifacts=[]
    )
    failures.extend(_phase4_receipt_failures(plain_result, plain_expected))
    if plain_context.overlay_plan_calls != 0 or plain_context.captured_overlay_plan is not None:
        failures.append("overlay renderer/plan ran for an overlay-free source")
    assert not failures, "\\n".join(failures)


@pytest.mark.parametrize("tamper", ["stale_script", "overlay_artifact_sha", "poison_overlay_content"])
def test_v2_approved_overlay_sidecar_and_plan_fail_closed_when_stale(
    tmp_path: Path, monkeypatch, tamper: str
) -> None:
    from server.errors import ReplicationError

    source = tmp_path / f"{tamper}-source.mp4"
    _phase4_make_video(source, "black", 2.0)
    context, store, expected, overlay_plan, _overlay_plan_sha, overlay_descriptor = (
        _phase4_approved_overlay_case(tmp_path, source)
    )
    _phase4_tamper_overlay(
        tamper=tamper,
        context=context,
        tmp_path=tmp_path,
        store=store,
        overlay_plan=overlay_plan,
        overlay_descriptor=overlay_descriptor,
    )
    ports, compositor_identity = _phase4_build_ports(monkeypatch)
    expected["compositor_identity"] = compositor_identity
    context.expected_receipt_inputs["compositor_identity"] = compositor_identity

    if tamper == "poison_overlay_content":
        try:
            ports["stage_ports"]["splice_timeline"].run(
                context=context, input_artifacts=context.input_artifacts
            )
        except ReplicationError as error:
            assert error.code == "CONTRACT_INVALID"
            assert error.category == "contract"
            assert context.captured_overlay_plan is None
            assert context.render_calls == 0
        else:
            assert context.captured_overlay_plan == overlay_plan, (
                "poison overlay content reached renderer instead of being rejected or rebuilt"
            )
            assert context.overlay_plan_calls == 1
    else:
        expected_error = {
            "stale_script": ("APPROVAL_STALE", "contract"),
            "overlay_artifact_sha": ("ARTIFACT_HASH_MISMATCH", "artifact"),
        }[tamper]
        with pytest.raises(ReplicationError) as error:
            ports["stage_ports"]["splice_timeline"].run(
                context=context, input_artifacts=context.input_artifacts
            )
        assert (error.value.code, error.value.category) == expected_error
    assert store.get_job(context.job_id) is not None


def test_v2_approved_overlay_and_source_overlay_plans_reach_renderer_without_overwrite(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "coexisting-overlay-source.mp4"
    _phase4_make_video(source, "black", 2.0)
    context, _store, expected, approved_plan, _plan_sha, _descriptor = (
        _phase4_approved_overlay_case(tmp_path, source)
    )
    source_overlay = _phase4_add_source_overlay_contract(context)
    ports, compositor_identity = _phase4_build_ports(
        monkeypatch, capture_coexisting_plans=True
    )
    expected["compositor_identity"] = compositor_identity
    context.expected_receipt_inputs["compositor_identity"] = compositor_identity

    result = ports["stage_ports"]["splice_timeline"].run(
        context=context, input_artifacts=context.input_artifacts
    )
    captured = context.captured_overlay_plans
    assert captured["approved_overlay_plan"] == approved_plan
    assert captured["source_overlay_plan"] == source_overlay["source_plan"]
    assert captured["approved_overlay_plan"] != captured["source_overlay_plan"]

    manifest = result["timeline_manifest"]
    receipt = manifest["transition_renders"][0]
    assert receipt["approved_script_revision"] == approved_plan["approved_script_revision"]
    assert receipt["approved_script_sha256"] == approved_plan["approved_script_sha256"]
    assert receipt["overlay_plan_sha256"] == approved_plan["overlay_plan_sha256"]
    assert receipt["source_overlay_contract_sha256"] == source_overlay["source_overlay_contract_sha256"]
    assert receipt["overlay_render_mapping_sha256"] == source_overlay["overlay_render_mapping_sha256"]
    assert manifest["approved_overlay_plan_sha256"] == approved_plan["overlay_plan_sha256"]
    assert manifest["source_overlay_contract_sha256"] == source_overlay["source_overlay_contract_sha256"]
    assert manifest["overlay_render_mapping_sha256"] == source_overlay["overlay_render_mapping_sha256"]


def test_v2_approved_overlay_source_overlay_plan_context_write_failure_fails_closed_before_renderer(
    tmp_path: Path, monkeypatch
) -> None:
    from server.real_capabilities import CapabilityUnavailable

    source = tmp_path / "source-overlay-context-failure.mp4"
    _phase4_make_video(source, "black", 2.0)
    context, _store, expected, _approved_plan, _plan_sha, _descriptor = (
        _phase4_approved_overlay_case(tmp_path, source)
    )
    _phase4_add_source_overlay_contract(context)
    ports, compositor_identity = _phase4_build_ports(
        monkeypatch, capture_coexisting_plans=True
    )
    expected["compositor_identity"] = compositor_identity
    context.expected_receipt_inputs["compositor_identity"] = expected["compositor_identity"]

    def reject_source_overlay_plan(self, name, value):
        if name == "source_overlay_plan":
            raise RuntimeError("source overlay plan storage unavailable")
        object.__setattr__(self, name, value)

    type(context).__setattr__ = reject_source_overlay_plan

    with pytest.raises(CapabilityUnavailable) as error:
        ports["stage_ports"]["splice_timeline"].run(
            context=context, input_artifacts=context.input_artifacts
        )

    assert error.value.code == "CAPABILITY_UNAVAILABLE"
    assert error.value.category == "capability"
    assert "verified source overlay plan" in str(error.value)
    assert context.render_calls == 0


def test_v2_approved_overlay_receipt_without_transition_renders_keeps_full_lineage(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "empty-transition-overlay-source.mp4"
    _phase4_make_video(source, "black", 2.0)
    context, _store, expected, approved_plan, _plan_sha, _descriptor = (
        _phase4_approved_overlay_case(tmp_path, source)
    )
    ports, compositor_identity = _phase4_build_ports(
        monkeypatch, emit_transition_receipts=False
    )
    expected["compositor_identity"] = compositor_identity
    context.expected_receipt_inputs["compositor_identity"] = compositor_identity

    result = ports["stage_ports"]["splice_timeline"].run(
        context=context, input_artifacts=context.input_artifacts
    )
    receipt = result["timeline_manifest"]["approved_overlay_receipt"]
    assert receipt["approved_script_revision"] == approved_plan["approved_script_revision"]
    assert receipt["approved_script_sha256"] == approved_plan["approved_script_sha256"]
    assert receipt["overlay_plan_sha256"] == approved_plan["overlay_plan_sha256"]
    assert receipt["source_video_sha256"] == approved_plan["source_video_sha256"]
    assert receipt["output_sha256"] == result["output_artifact"]["sha256"]
    assert receipt["renderer_identity"] == {
        "capability": "timeline_renderer",
        "implementation": "tests:Phase4RecordingRenderer",
        "version": "phase4-shared-red-v1",
        "sha256": "3" * 64,
    }
    assert receipt["compositor_identity"] == compositor_identity

    assembled = next(
        item for item in context.artifacts if item.get("kind") == "assembled_video"
    )
    metadata = assembled["metadata"]
    assert metadata["renderer_identity"] == receipt["renderer_identity"]
    assert metadata["compositor_identity"] == compositor_identity


@pytest.mark.parametrize(
    "tamper",
    [
        "artifact_sha",
        "artifact_kind",
        "artifact_metadata",
        "workflow_receipt",
        "protected_provider",
        "stale_provider",
        "assembly_order",
        "approved_audio_plan_revision",
        "approved_audio_plan_sha256",
        "approved_script_sha256",
        "source_timeline_sha256",
        "source_classification_sha256",
        "new_song_sha256",
        "ambiguity",
    ],
)
def test_v2_song_lip_sync_manifest_poison_and_stale_lineage_fail_closed(
    tmp_path: Path, monkeypatch, tamper: str
) -> None:
    from server.errors import ReplicationError

    source = tmp_path / f"song-manifest-{tamper}.mp4"
    _phase4_make_video(source, "black", 2.0)
    context, manifest, descriptor, _lineage = _phase4_song_manifest_case(tmp_path, source)
    if tamper == "ambiguity":
        poisoned = _phase4_song_manifest_tamper(manifest, "approved_script_sha256")
        context.input_artifacts = [{"song_lip_sync_segment_manifest": poisoned}, descriptor]
    else:
        poisoned = _phase4_song_manifest_tamper(manifest, tamper)
        _phase4_replace_song_manifest(context, descriptor, poisoned)
        context.input_artifacts = [descriptor]

    ports, compositor_identity = _phase4_build_ports(monkeypatch)
    context.expected_receipt_inputs["compositor_identity"] = compositor_identity

    with pytest.raises(ReplicationError) as error:
        ports["stage_ports"]["splice_timeline"].run(
            context=context, input_artifacts=context.input_artifacts
        )

    assert (error.value.code, error.value.category) == ("CONTRACT_INVALID", "contract")
    assert context.render_calls == 0


@pytest.mark.parametrize(
    "tamper",
    [
        "workflow_identity",
        "approved_protection_windows",
        "source_timeline_windows",
        "audio_plan_content_sha_mismatch",
    ],
)
def test_v2_song_lip_sync_manifest_derived_lineage_fail_closed(
    tmp_path: Path, monkeypatch, tamper: str
) -> None:
    from copy import deepcopy
    from server.errors import ReplicationError

    source = tmp_path / f"song-derived-lineage-{tamper}.mp4"
    _phase4_make_video(source, "black", 2.0)
    context, manifest, descriptor, _lineage = _phase4_song_manifest_case(tmp_path, source)
    if tamper == "source_timeline_windows":
        poisoned = _phase4_rebind_song_manifest_windows(manifest, shift_ms=1_000)
    elif tamper == "audio_plan_content_sha_mismatch":
        poisoned = _phase4_rehash_song_manifest(deepcopy(manifest))
        approval = context.job_store.get_script_approval(context.job_id, 1)
        poisoned_audio_plan = deepcopy(approval["audio_plan"])
        poisoned_audio_plan["ui_monologue_protection_windows"] = [
            {"start_ms": 3000, "end_ms": 5000}
        ]
        context.job_store = SimpleNamespace(
            get_script_approval=lambda _job_id, _revision: {
                **approval,
                "audio_plan": poisoned_audio_plan,
                "audio_plan_sha256": approval["audio_plan_sha256"],
            }
        )
    else:
        poisoned = _phase4_song_manifest_tamper(manifest, tamper)
    _phase4_replace_song_manifest(context, descriptor, poisoned)
    context.input_artifacts = [descriptor]

    ports, compositor_identity = _phase4_build_ports(monkeypatch)
    context.expected_receipt_inputs["compositor_identity"] = compositor_identity

    with pytest.raises(ReplicationError) as error:
        ports["stage_ports"]["splice_timeline"].run(
            context=context, input_artifacts=context.input_artifacts
        )

    assert (error.value.code, error.value.category) == ("CONTRACT_INVALID", "contract")
    assert context.render_calls == 0


def test_v2_song_lip_sync_manifest_drives_real_multi_window_pixels(
    tmp_path: Path, monkeypatch
) -> None:
    """RED: real assembly must render lip/protected/lip media, not only copy provider source."""

    from array import array
    import math
    import wave

    import cv2

    from server.packaged_ports import build_ports

    source = tmp_path / "provider-green.mp4"
    lip_one = tmp_path / "lip-red.mp4"
    lip_two = tmp_path / "lip-blue.mp4"

    def make_tone_video(path: Path, color: str, frequency: int, duration: float) -> None:
        ffmpeg = shutil.which("ffmpeg")
        assert ffmpeg
        subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=30:d={duration}",
                "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
                "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-c:a", "aac", "-shortest",
                str(path),
            ],
            check=True,
        )

    make_tone_video(source, "green", 440, 8.0)
    make_tone_video(lip_one, "red", 660, 2.5)
    make_tone_video(lip_two, "blue", 880, 2.5)
    context, manifest, descriptor, _lineage = _phase4_song_manifest_case(tmp_path, source)
    source_sha = sha256(source.read_bytes()).hexdigest()

    provider = next(item for item in context.artifacts if item.get("kind") == "provider_video")
    provider["sha256"] = source_sha
    manifest["provider_output_sha256"] = source_sha
    manifest["protected_source_intervals"][0]["provider_output_sha256"] = source_sha
    context.song_lip_sync_lineage["provider_output_sha256"] = source_sha

    for index, media_path in enumerate((lip_one, lip_two)):
        output_sha = sha256(media_path.read_bytes()).hexdigest()
        row = manifest["segments"][index]
        row["output_sha256"] = output_sha
        row["workflow_receipt"]["output_sha256"] = output_sha
        row["artifact"]["sha256"] = output_sha
        row["artifact"]["metadata"]["output_sha256"] = output_sha
        row["artifact"]["metadata"]["workflow_receipt"] = dict(row["workflow_receipt"])
        descriptor_row = next(
            item for item in context.artifacts
            if item.get("artifact_id") == row["artifact"]["artifact_id"]
        )
        descriptor_row["sha256"] = output_sha
        descriptor_row["content_type"] = "video/mp4"
        descriptor_row["metadata"]["output_sha256"] = output_sha
        descriptor_row["metadata"]["workflow_receipt"] = dict(row["workflow_receipt"])

    manifest = _phase4_rehash_song_manifest(manifest)
    _phase4_replace_song_manifest(context, descriptor, manifest)
    context.timeline_regions = [{
        "region_type": "source_interval",
        "region_id": "provider-source",
        "source_start_us": 0,
        "source_end_us": 8_000_000,
        "media_origin": "source_interval",
        "assembly_policy": "splice_source_interval",
        "slot_id": "source_video",
        "placement_kind": "source_body",
    }]
    context.input_artifacts = [descriptor]

    original_materialize_artifact = context.materialize_artifact
    media_paths = {
        provider["artifact_id"]: source,
        manifest["segments"][0]["artifact"]["artifact_id"]: lip_one,
        manifest["segments"][1]["artifact"]["artifact_id"]: lip_two,
    }

    @contextmanager
    def materialize_artifact(kind: str, *, artifact_id: str, sha256: str, **kwargs):
        media_path = media_paths.get(artifact_id)
        if media_path is not None:
            actual = hashlib.sha256(media_path.read_bytes()).hexdigest()
            if actual != sha256:
                from server.errors import ReplicationError

                raise ReplicationError(
                    "ARTIFACT_HASH_MISMATCH",
                    "song render media descriptor SHA is stale",
                    category="artifact",
                )
            yield SimpleNamespace(path=media_path, sha256=actual)
            return
        with original_materialize_artifact(kind, artifact_id=artifact_id, sha256=sha256, **kwargs) as media:
            yield media

    context.materialize_artifact = materialize_artifact

    _configure_environment(monkeypatch)
    ports = build_ports()
    result = ports["stage_ports"]["splice_timeline"].run(
        context=context, input_artifacts=context.input_artifacts
    )
    output_path = context.work_dir / "composited.mp4"
    assert output_path.is_file()
    assert result["timeline_manifest"]["song_lip_sync_segment_manifest_sha256"] == manifest["manifest_sha256"]
    assert result["output_artifact"]["sha256"] == sha256(output_path.read_bytes()).hexdigest()

    capture = cv2.VideoCapture(str(output_path))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps > 0 else 0
    assert 7.8 <= duration <= 8.2

    def sample_bgr(milliseconds: int) -> tuple[float, float, float]:
        capture.set(cv2.CAP_PROP_POS_MSEC, milliseconds)
        ok, frame = capture.read()
        assert ok
        mean = frame.mean(axis=(0, 1))
        return float(mean[0]), float(mean[1]), float(mean[2])

    blue_at_1s, green_at_1s, red_at_1s = sample_bgr(1000)
    blue_at_4s, green_at_4s, red_at_4s = sample_bgr(4000)
    blue_at_6_5s, green_at_6_5s, red_at_6_5s = sample_bgr(6500)
    failures: list[str] = []
    if not (red_at_1s > green_at_1s and red_at_1s > blue_at_1s):
        failures.append(f"1s expected red, got BGR=({blue_at_1s:.1f},{green_at_1s:.1f},{red_at_1s:.1f})")
    if not (green_at_4s > red_at_4s and green_at_4s > blue_at_4s):
        failures.append(f"4s expected green, got BGR=({blue_at_4s:.1f},{green_at_4s:.1f},{red_at_4s:.1f})")
    if not (blue_at_6_5s > red_at_6_5s and blue_at_6_5s > green_at_6_5s):
        failures.append(f"6.5s expected blue, got BGR=({blue_at_6_5s:.1f},{green_at_6_5s:.1f},{red_at_6_5s:.1f})")

    decoded_audio = tmp_path / "assembled-mono.wav"
    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(output_path),
                "-vn", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(decoded_audio),
            ],
            check=True,
        )
        with wave.open(str(decoded_audio), "rb") as handle:
            samples = array("h", handle.readframes(handle.getnframes()))
        sample_rate = 48_000

        def tone_amplitude(start_ms: int, frequency: int) -> float:
            start = int(start_ms * sample_rate / 1000)
            chunk = samples[start : start + 4_800]
            real = sum(value * math.cos(2 * math.pi * frequency * index / sample_rate) for index, value in enumerate(chunk, start=start))
            imaginary = sum(value * math.sin(2 * math.pi * frequency * index / sample_rate) for index, value in enumerate(chunk, start=start))
            return math.hypot(real, imaginary) / max(len(chunk), 1)

        for start_ms, expected_frequency in ((1000, 660), (4000, 440), (6500, 880)):
            scores = {
                frequency: tone_amplitude(start_ms, frequency)
                for frequency in (440, 660, 880)
            }
            if scores[expected_frequency] <= 1.25 * max(
                score for frequency, score in scores.items() if frequency != expected_frequency
            ):
                failures.append(
                    f"{start_ms}ms expected {expected_frequency}Hz audio, got {scores}"
                )
    except (OSError, subprocess.CalledProcessError, wave.Error) as exc:
        failures.append(f"assembled audio could not be sampled: {exc}")

    assert not failures, "; ".join(failures)


def test_v2_song_lip_sync_manifest_preserves_provider_outside_nonfull_song_windows(
    tmp_path: Path, monkeypatch
) -> None:
    import cv2

    source = tmp_path / "provider-green-10s.mp4"
    lip_one = tmp_path / "lip-red-1.mp4"
    lip_two = tmp_path / "lip-blue-2.mp4"
    lip_three = tmp_path / "lip-yellow-3.mp4"
    _phase5_make_tone_video(source, "green", 440, 10.0)
    _phase5_make_tone_video(lip_one, "red", 660, 1.5)
    _phase5_make_tone_video(lip_two, "blue", 880, 1.0)
    _phase5_make_tone_video(lip_three, "yellow", 990, 2.0)

    context, _manifest, descriptor, _lineage = _phase5_prepare_nonfull_song_case(
        tmp_path,
        source,
        [(1000, 2500, lip_one), (3000, 4000, lip_two), (6000, 8000, lip_three)],
    )
    from server.packaged_ports import build_ports

    _configure_environment(monkeypatch)
    ports = build_ports()
    compositor_identity = ports["capability_ports"]["compositor"].adapter.capability_identity()
    context.expected_receipt_inputs["compositor_identity"] = compositor_identity
    result = ports["stage_ports"]["splice_timeline"].run(
        context=context, input_artifacts=context.input_artifacts
    )
    output_path = context.work_dir / "composited.mp4"
    capture = cv2.VideoCapture(str(output_path))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps > 0 else 0
    failures: list[str] = []
    if not 9.8 <= duration <= 10.2:
        failures.append(f"non-song provider timeline was compressed to {duration:.3f}s")

    def sample_color(milliseconds: int) -> tuple[float, float, float] | None:
        capture.set(cv2.CAP_PROP_POS_MSEC, milliseconds)
        ok, frame = capture.read()
        if not ok:
            return None
        mean = frame.mean(axis=(0, 1))
        return float(mean[0]), float(mean[1]), float(mean[2])

    samples = {time: sample_color(time) for time in (500, 1500, 2750, 3500, 5000, 6500, 9000)}
    if samples[500] is None or samples[9000] is None:
        failures.append("provider head/tail intervals are missing")
    else:
        for time in (500, 9000):
            blue, green, red = samples[time]
            if not (green > red and green > blue):
                failures.append(f"{time}ms did not preserve provider green media")
    if samples[1500] is not None:
        blue, green, red = samples[1500]
        if not (red > green and red > blue):
            failures.append("1500ms did not render lip segment one")
    if samples[2750] is not None:
        blue, green, red = samples[2750]
        if not (green > red and green > blue):
            failures.append("protected 2750ms interval did not preserve provider media")
    if samples[3500] is not None:
        blue, green, red = samples[3500]
        if not (blue > red and blue > green):
            failures.append("3500ms did not render lip segment two")
    if samples[6500] is not None:
        blue, green, red = samples[6500]
        if not (red > blue and green > blue):
            failures.append("6500ms did not render lip segment three")

    receipts = result["timeline_manifest"].get("song_lip_sync_render_receipts", [])
    passthrough = [item for item in receipts if item.get("kind") == "provider_passthrough"]
    if not passthrough:
        failures.append("implicit provider passthrough receipts are missing")
    assert not failures, "; ".join(failures)


def test_v2_song_lip_sync_allow_passthrough_uses_rendered_song_base(
    tmp_path: Path,
) -> None:
    import cv2

    from server.real_capabilities import FfmpegCompositor

    source = tmp_path / "provider-green-passthrough.mp4"
    lip_one = tmp_path / "lip-red-passthrough.mp4"
    lip_two = tmp_path / "lip-blue-passthrough.mp4"
    _phase5_make_tone_video(source, "green", 440, 8.0)
    _phase5_make_tone_video(lip_one, "red", 660, 2.5)
    _phase5_make_tone_video(lip_two, "blue", 880, 2.5)
    context, _manifest, descriptor, _lineage = _phase5_prepare_song_media_case(
        tmp_path, source, [lip_one, lip_two]
    )

    FfmpegCompositor(allow_passthrough=True).compose(
        context=context, input_artifacts=[descriptor]
    )
    output_path = context.work_dir / "composited.mp4"
    capture = cv2.VideoCapture(str(output_path))
    capture.set(cv2.CAP_PROP_POS_MSEC, 1000)
    ok, frame = capture.read()
    assert ok
    blue, green, red = frame.mean(axis=(0, 1))
    assert red > green and red > blue


def test_v2_song_lip_sync_short_segment_fails_interval_audio_contract(
    tmp_path: Path, monkeypatch
) -> None:
    from server.errors import ReplicationError
    from server.packaged_ports import build_ports

    source = tmp_path / "provider-green-short-segment.mp4"
    lip_short = tmp_path / "lip-red-short.mp4"
    lip_two = tmp_path / "lip-blue-short-case.mp4"
    _phase5_make_tone_video(source, "green", 440, 8.0)
    _phase5_make_tone_video(lip_short, "red", 660, 1.5)
    _phase5_make_tone_video(lip_two, "blue", 880, 2.5)
    context, _manifest, descriptor, _lineage = _phase5_prepare_song_media_case(
        tmp_path, source, [lip_short, lip_two]
    )

    _configure_environment(monkeypatch)
    ports = build_ports()
    with pytest.raises(ReplicationError) as error:
        ports["stage_ports"]["splice_timeline"].run(
            context=context, input_artifacts=[descriptor]
        )

    assert (error.value.code, error.value.category) == (
        "PROVIDER_RESULT_INVALID",
        "audio",
    )


def test_v2_song_lip_sync_concat_audio_drift_fails_closed_before_passthrough(
    tmp_path: Path, monkeypatch
) -> None:
    from server.errors import ReplicationError
    from server.real_capabilities import FfmpegCompositor
    import server.timeline_renderer as timeline_renderer

    source = tmp_path / "provider-green-drift.mp4"
    lip_one = tmp_path / "lip-red-drift.mp4"
    lip_two = tmp_path / "lip-blue-drift.mp4"
    invalid_composite = tmp_path / "invalid-no-audio-composite.mp4"
    _phase5_make_tone_video(source, "green", 440, 8.0)
    _phase5_make_tone_video(lip_one, "red", 660, 2.5)
    _phase5_make_tone_video(lip_two, "blue", 880, 2.5)
    _phase4_make_video(invalid_composite, "black", 8.0)
    context, _manifest, descriptor, _lineage = _phase5_prepare_song_media_case(
        tmp_path, source, [lip_one, lip_two]
    )

    timeline = timeline_renderer._timeline_module()

    def concat_with_invalid_audio(segment_paths, output_path, *, expect_audio=True):
        del segment_paths, expect_audio
        shutil.copyfile(invalid_composite, output_path)
        raise timeline.ConcatError(
            "AUDIO_VIDEO_DURATION_DRIFT: synthetic generated output has no audio"
        )

    monkeypatch.setattr(timeline, "concat_segments", concat_with_invalid_audio)
    with pytest.raises(ReplicationError) as error:
        FfmpegCompositor(allow_passthrough=True).compose(
            context=context, input_artifacts=[descriptor]
        )

    assert (error.value.code, error.value.category) == (
        "PROVIDER_RESULT_INVALID",
        "audio",
    )
