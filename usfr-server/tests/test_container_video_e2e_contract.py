from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from server.capabilities import REQUIRED_CAPABILITIES
from server.capability_ports import REQUIRED_CAPABILITY_METHODS
from server.ephemeral_driver import EXECUTABLE_STAGES


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def test_e2e_port_factory_covers_every_stage_and_capability() -> None:
    module = importlib.import_module("validation.e2e.ports")
    ports = module.build_ports()
    assert set(ports["stage_ports"]) == set(EXECUTABLE_STAGES)
    assert set(ports["capability_ports"]) == set(REQUIRED_CAPABILITIES)
    assert all(
        callable(port) or callable(getattr(port, "run", None))
        for port in ports["stage_ports"].values()
    )
    for name, methods in REQUIRED_CAPABILITY_METHODS.items():
        adapter = ports["capability_ports"][name]
        assert all(callable(getattr(adapter, method, None)) for method in methods)
        identity = adapter.capability_identity()
        assert identity["capability"] == name
        assert len(identity["sha256"]) == 64


@pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="FFmpeg is required")
def test_e2e_ports_render_a_playable_generated_ui_tail_sequence(tmp_path: Path) -> None:
    module = importlib.import_module("validation.e2e.ports")

    class CaptureContext:
        def __init__(self) -> None:
            self.work_dir = tmp_path
            self.payloads = {}

        def publish_bytes(self, *, kind, data, **_):
            self.payloads[kind] = data
            return {"artifact_id": kind, "kind": kind, "sha256": "a" * 64}

    generated_context = CaptureContext()
    module.ProviderVideoStage().run(context=generated_context, input_artifacts=[])
    generated = tmp_path / "provider.mp4"
    generated.write_bytes(generated_context.payloads["provider_video"])

    def clip(path: Path, color: str, frequency: int, duration: float) -> None:
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=180x320:r=30:d={duration}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(path),
            ],
            check=True,
        )

    ui = tmp_path / "ui.mp4"
    tail = tmp_path / "tail.mp4"
    clip(ui, "blue", 660, 0.8)
    clip(tail, "yellow", 880, 0.6)

    class SpliceContext(CaptureContext):
        @contextmanager
        def materialize_artifact(self, kind):
            assert kind == "provider_video"
            yield SimpleNamespace(path=generated)

        @contextmanager
        def materialize_slot(self, slot):
            yield SimpleNamespace(path={"ui_operation_video": ui, "tail_video": tail}[slot])

    splice_context = SpliceContext()
    module.SpliceStage().run(context=splice_context, input_artifacts=[])
    assembled = tmp_path / "result.mp4"
    assembled.write_bytes(splice_context.payloads["assembled_video"])
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(assembled)],
        capture_output=True,
        text=True,
        check=True,
    )
    metadata = json.loads(probe.stdout)
    assert {stream["codec_type"] for stream in metadata["streams"]} == {"video", "audio"}
    assert 2.0 < float(metadata["format"]["duration"]) < 2.3


def test_dockerfile_keeps_e2e_code_out_of_default_production_target() -> None:
    dockerfile = (ROOT / "deployment" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM runtime AS e2e" in dockerfile
    assert "COPY validation/e2e /opt/usfr/validation/e2e" in dockerfile
    assert "FROM runtime AS production" in dockerfile
    assert dockerfile.rfind("FROM runtime AS production") > dockerfile.rfind(
        "COPY validation/e2e /opt/usfr/validation/e2e"
    )


def test_compose_full_e2e_uses_packaged_fake_ports_and_python_driver() -> None:
    compose = (ROOT / "deployment" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "USFR_DOCKER_TARGET" in compose
    assert "USFR_PORT_FACTORY: ${USFR_PORT_FACTORY:-}" in compose
    assert "validation.e2e.ports:build_ports" in compose
    assert "USFR_READINESS_ONLY: false" in compose
    assert "worker:" in compose
    assert "python" in compose
    assert "validation.e2e.driver" in compose
    assert "curlimages/curl" not in compose
    assert 'restart: "no"' in compose
    driver = (ROOT / "validation" / "e2e" / "driver.py").read_text(encoding="utf-8")
    assert "create_bucket" in driver


def test_e2e_driver_declares_two_approvals_cleanup_and_final_only_assertion() -> None:
    driver = (ROOT / "validation" / "e2e" / "driver.py").read_text(
        encoding="utf-8"
    )
    for required in (
        "/scripts/",
        "/storyboards/",
        "CleanupSweeper",
        "run_qc",
        "before_keys",
        "final/",
        "temporary/",
        "result.mp4",
    ):
        assert required in driver
