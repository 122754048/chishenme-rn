from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from server.capabilities import REQUIRED_CAPABILITIES, build_stage_capability_manifest
from server.orchestrator import stage_dedupe_key
from server.real_capabilities import (
    DeterministicUiRenderer,
    FfmpegCompositor,
    FfmpegDynamicsAnalyzer,
    WhisperAsrTranscriber,
)
from server.capability_ports import BoundRuntimeCapability


class _ModelBackend:
    def __init__(self, role: str, model_sha256: str) -> None:
        self.role = role
        self.model_sha256 = model_sha256

    def capability_identity(self):
        return {
            "implementation": f"tests:{self.role}",
            "version": "1.0.0",
            "model_id": f"{self.role}-model",
            "model_sha256": self.model_sha256,
            "evidence_binding": f"usfr-{self.role}-evidence/v1",
        }

    def analyze(self, **_kwargs):
        return {}

    def recognize(self, _path):
        return {}

    def transcribe(self, _path, **_kwargs):
        return {}

    def classify(self, _path, **_kwargs):
        return {}


class _Renderer:
    def __init__(self, marker: str) -> None:
        self.marker = marker

    def capability_identity(self):
        return {
            "implementation": "tests:renderer",
            "version": "1.0.0",
            "sha256": self.marker * 64,
        }

    def __call__(self, *_args, **_kwargs):
        return None


def _manifest_for(identity: dict) -> dict:
    records = {
        name: {
            "declared": True,
            "implementation": f"container://{name}",
            "version": "1.0.0",
            "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
        }
        for name in REQUIRED_CAPABILITIES
    }
    records["dynamics_analyzer"] = {
        "declared": True,
        "implementation": identity["implementation"],
        "version": identity["version"],
        "sha256": identity["sha256"],
    }
    return build_stage_capability_manifest(records)


class CompositeCapabilityIdentityTest(unittest.TestCase):
    def test_vlm_model_only_change_changes_dynamics_identity_manifest_and_dedupe(self) -> None:
        first = FfmpegDynamicsAnalyzer(
            semantic_analyzer=_ModelBackend("vlm", "1" * 64),
            production=True,
            sha256="a" * 64,
        ).capability_identity()
        second = FfmpegDynamicsAnalyzer(
            semantic_analyzer=_ModelBackend("vlm", "2" * 64),
            production=True,
            sha256="a" * 64,
        ).capability_identity()
        self.assertNotEqual(first["sha256"], second["sha256"])
        manifest_a, manifest_b = _manifest_for(first), _manifest_for(second)
        self.assertNotEqual(manifest_a["manifest_sha256"], manifest_b["manifest_sha256"])
        self.assertNotEqual(
            stage_dedupe_key("run", "analyze_dynamics", "f" * 64, "server-v1", capability_manifest_digest=manifest_a["manifest_sha256"]),
            stage_dedupe_key("run", "analyze_dynamics", "f" * 64, "server-v1", capability_manifest_digest=manifest_b["manifest_sha256"]),
        )

    def test_bound_runtime_capability_does_not_drop_nested_model_digest(self) -> None:
        first = BoundRuntimeCapability(
            capability="dynamics_analyzer",
            implementation="container://dynamics",
            version="1.0.0",
            sha256="a" * 64,
            adapter=FfmpegDynamicsAnalyzer(
                semantic_analyzer=_ModelBackend("vlm", "1" * 64),
                production=True,
                sha256="b" * 64,
            ),
        ).capability_identity()
        second = BoundRuntimeCapability(
            capability="dynamics_analyzer",
            implementation="container://dynamics",
            version="1.0.0",
            sha256="a" * 64,
            adapter=FfmpegDynamicsAnalyzer(
                semantic_analyzer=_ModelBackend("vlm", "2" * 64),
                production=True,
                sha256="b" * 64,
            ),
        ).capability_identity()

        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertNotEqual(
            _manifest_for(first)["manifest_sha256"],
            _manifest_for(second)["manifest_sha256"],
        )

    def test_ocr_model_only_change_changes_ui_renderer_identity(self) -> None:
        first = DeterministicUiRenderer(
            ocr_backend=_ModelBackend("ocr", "3" * 64),
            production=True,
            sha256="b" * 64,
        ).capability_identity()
        second = DeterministicUiRenderer(
            ocr_backend=_ModelBackend("ocr", "4" * 64),
            production=True,
            sha256="b" * 64,
        ).capability_identity()
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_asr_and_audio_event_model_changes_change_transcriber_identity(self) -> None:
        first = WhisperAsrTranscriber(
            transcriber=_ModelBackend("asr", "5" * 64),
            audio_event_classifier=_ModelBackend("audio", "6" * 64),
            production=True,
            sha256="c" * 64,
        ).capability_identity()
        changed_asr = WhisperAsrTranscriber(
            transcriber=_ModelBackend("asr", "7" * 64),
            audio_event_classifier=_ModelBackend("audio", "6" * 64),
            production=True,
            sha256="c" * 64,
        ).capability_identity()
        changed_audio = WhisperAsrTranscriber(
            transcriber=_ModelBackend("asr", "5" * 64),
            audio_event_classifier=_ModelBackend("audio", "8" * 64),
            production=True,
            sha256="c" * 64,
        ).capability_identity()
        self.assertNotEqual(first["sha256"], changed_asr["sha256"])
        self.assertNotEqual(first["sha256"], changed_audio["sha256"])

    def test_pinned_local_whisper_model_change_changes_transcriber_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "whisper.pt"
            model.write_bytes(b"model")
            first = WhisperAsrTranscriber(
                model_path=model,
                model_sha256="9" * 64,
                device="cpu",
                production=True,
                sha256="d" * 64,
            ).capability_identity()
            second = WhisperAsrTranscriber(
                model_path=model,
                model_sha256="a" * 64,
                device="cpu",
                production=True,
                sha256="d" * 64,
            ).capability_identity()
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_renderer_only_change_changes_ui_and_compositor_identity(self) -> None:
        ocr = _ModelBackend("ocr", "b" * 64)
        ui_a = DeterministicUiRenderer(
            ocr_backend=ocr,
            render_backend=_Renderer("1"),
            production=True,
            sha256="e" * 64,
        ).capability_identity()
        ui_b = DeterministicUiRenderer(
            ocr_backend=ocr,
            render_backend=_Renderer("2"),
            production=True,
            sha256="e" * 64,
        ).capability_identity()
        compositor_a = FfmpegCompositor(renderer=_Renderer("3"), production=True, sha256="f" * 64).capability_identity()
        compositor_b = FfmpegCompositor(renderer=_Renderer("4"), production=True, sha256="f" * 64).capability_identity()
        self.assertNotEqual(ui_a["sha256"], ui_b["sha256"])
        self.assertNotEqual(compositor_a["sha256"], compositor_b["sha256"])

    def test_ui_renderer_replacement_rebinds_its_production_identity(self) -> None:
        ui_renderer = DeterministicUiRenderer(
            ocr_backend=_ModelBackend("ocr", "b" * 64),
            render_backend=_Renderer("1"),
            production=True,
            sha256="e" * 64,
        )
        before = ui_renderer.capability_identity()
        replacement = _Renderer("2")

        ui_renderer.replace_render_backend(replacement)

        self.assertIs(ui_renderer.render_backend, replacement)
        self.assertNotEqual(before["sha256"], ui_renderer.capability_identity()["sha256"])
        self.assertIsNone(ui_renderer.validate_production_readiness())

    def test_production_rejects_unidentified_nested_renderers(self) -> None:
        with self.assertRaisesRegex(ValueError, "render backend.*capability_identity"):
            DeterministicUiRenderer(
                ocr_backend=_ModelBackend("ocr", "c" * 64),
                render_backend=lambda *_args: None,
                production=True,
                sha256="1" * 64,
            )
        with self.assertRaisesRegex(ValueError, "renderer.*capability_identity"):
            FfmpegCompositor(renderer=lambda *_args: None, production=True, sha256="2" * 64)


if __name__ == "__main__":
    unittest.main()
