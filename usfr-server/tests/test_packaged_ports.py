from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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
        "RUNNINGHUB_SEEDANCE_CREATE_URL": "https://runninghub.example.test/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
        "RUNNINGHUB_SEEDANCE_QUERY_URL": "https://runninghub.example.test/openapi/v2/query",
        "RUNNINGHUB_SEEDANCE_UPLOAD_URL": "https://runninghub.example.test/openapi/v2/media/upload/binary",
        "RUNNINGHUB_SEEDANCE_CONFIG_SHA256": "b" * 64,
        "RUNNINGHUB_WHISPER_WORKFLOW_ID": "workflow-123",
        "RUNNINGHUB_WHISPER_INPUT_NODE_ID": "12",
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
        def __init__(self, *, api_key: str, base_url: str) -> None:
            del base_url
            workflow_keys.append(api_key)

        def run_whisper(self, **_kwargs):
            return {"segments": []}

        def run_image2(self, **_kwargs):
            raise AssertionError("factory construction must not submit Image2")

    class SeedanceMediaUploader:
        def __init__(self, config) -> None:
            standard_keys.append(config.runninghub_seedance_api_key_env)

        def upload_media(self, _path: Path) -> str:
            raise AssertionError("factory construction must not upload media")

    monkeypatch.setattr(packaged_ports, "RunningHubWorkflowClient", WorkflowClient)
    monkeypatch.setattr(packaged_ports, "RunningHubSeedanceMediaUploader", SeedanceMediaUploader, raising=False)
    ports = packaged_ports.build_ports()

    audit_stage = ports["stage_ports"]["audit_seedance_request"].handler
    wait_stage = ports["stage_ports"]["wait_provider_video"]
    assert workflow_keys == ["test-runninghub-key"]
    assert standard_keys == ["RUNNINGHUB_SEEDANCE_API_KEY"]
    assert type(audit_stage.media_uploader) is SeedanceMediaUploader
    assert type(wait_stage.song_lip_sync_client) is WorkflowClient


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
