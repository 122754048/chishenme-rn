from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server.audio_backends import (
    AudioBackendUnavailable,
    BackgroundMusicCompositor,
    EvidenceBoundHttpAudioEventBackend,
    MusicTimelineAnalyzer,
    OptionalInputExtension,
    input_contract_v2_extensions,
    validate_final_audio_qc,
)
from server.audio_route_guard import validate_audio_route_contract
from server.errors import ReplicationError


class _JsonHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    response_factory = staticmethod(lambda _payload: {})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(payload)
        data = json.dumps(type(self).response_factory(payload)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args) -> None:
        return


def _server(response_factory):
    handler = type("Handler", (_JsonHandler,), {"requests": [], "response_factory": staticmethod(response_factory)})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}/classify", handler.requests


class EvidenceBoundAudioBackendTest(unittest.TestCase):
    def test_explicit_audio_route_policies_cover_source_generated_opaque_tail_and_languages(self) -> None:
        languages = ("en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh")
        for language in languages:
            with self.subTest(language=language):
                context = SimpleNamespace(
                    output_language=language,
                    audio_contract={
                        "schema_version": "audio-contract/v1",
                        "output_language": language,
                        "segments": [{
                            "segment_id": "A1",
                            "start_ms": 100,
                            "end_ms": 400,
                            "text": "translated exact line",
                            "meaning": "buy now",
                            "delivery": "whisper",
                            "visible_speaker": True,
                        }],
                    },
                )
                result = validate_audio_route_contract(
                    context=context,
                    regions=[
                        {
                            "region_id": "source",
                            "region_type": "source_ui_keep",
                            "media_origin": "source_interval",
                            "source_start_us": 0,
                            "source_end_us": 100_000,
                        },
                        {
                            "region_id": "generated",
                            "region_type": "generated",
                            "media_origin": "generated_media",
                            "source_start_us": 100_000,
                            "source_end_us": 400_000,
                            "generate_audio": True,
                            "output_language": language,
                            "exact_line_windows": [{
                                "start_us": 100_000,
                                "end_us": 400_000,
                                "text": "translated exact line",
                                "meaning": "buy now",
                                "delivery": "whisper",
                                "visible_speaker": True,
                            }],
                        },
                        {
                            "region_id": "opaque",
                            "region_type": "opaque_ui_demo",
                            "media_origin": "user_upload",
                            "source_start_us": 400_000,
                            "source_end_us": 700_000,
                            "has_audio": True,
                        },
                        {
                            "region_id": "tail",
                            "region_type": "opaque_tail",
                            "media_origin": "user_upload",
                            "source_start_us": 700_000,
                            "source_end_us": 1_000_000,
                            "has_audio": True,
                        },
                    ],
                    active_high_fidelity=True,
                )
                self.assertEqual(
                    [item["audio_policy"] for item in result["regions"]],
                    [
                        "source_audio_keep",
                        "generated_audio_contract",
                        "opaque_audio_keep",
                        "opaque_audio_keep",
                    ],
                )

    def test_source_speech_crossing_opaque_requires_evidence_bound_mix_receipt(self) -> None:
        base_context = SimpleNamespace(
            audio_contract={
                "schema_version": "audio-contract/v1",
                "segments": [{"segment_id": "A1", "start_ms": 100, "end_ms": 400}],
            },
            final_output_sha256="f" * 64,
        )
        region = {
            "region_id": "opaque",
            "region_type": "opaque_ui_demo",
            "media_origin": "user_upload",
            "source_start_us": 200_000,
            "source_end_us": 500_000,
            "has_audio": True,
        }
        with self.assertRaisesRegex(ReplicationError, "AUDIO_LAYER_POLICY_REQUIRED"):
            validate_audio_route_contract(
                context=base_context,
                regions=[region],
                active_high_fidelity=True,
            )
        with self.assertRaisesRegex(ReplicationError, "requires a mixer receipt"):
            validate_audio_route_contract(
                context=base_context,
                regions=[{**region, "audio_policy": "evidence_bound_mix"}],
                active_high_fidelity=True,
            )
        receipt = {
            "source_wav_sha256": "a" * 64,
            "opaque_wav_sha256": "b" * 64,
            "request_sha256": "c" * 64,
            "output_wav_sha256": "d" * 64,
            "duck_curve": [{"time_us": 200_000, "gain_db": -12.0}],
            "final_output_sha256": "f" * 64,
        }
        result = validate_audio_route_contract(
            context=base_context,
            regions=[
                {
                    **region,
                    "audio_policy": "evidence_bound_mix",
                    "mixer_receipt": receipt,
                }
            ],
            active_high_fidelity=True,
        )
        self.assertEqual(result["regions"][0]["audio_policy"], "evidence_bound_mix")
        self.assertEqual(result["regions"][0]["mixer_receipt_sha256"], hashlib.sha256(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest())

    def test_bundled_mixer_capability_may_defer_evidence_bound_mix_receipt(self) -> None:
        context = SimpleNamespace(
            audio_contract={
                "schema_version": "audio-contract/v1",
                "segments": [
                    {"segment_id": "A1", "start_ms": 100, "end_ms": 400}
                ],
            }
        )

        result = validate_audio_route_contract(
            context=context,
            regions=[
                {
                    "region_id": "opaque",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                    "has_audio": True,
                    "audio_policy": "evidence_bound_mix",
                }
            ],
            active_high_fidelity=True,
            defer_evidence_bound_mix_receipts=True,
        )

        self.assertEqual(result["status"], "pending_evidence_bound_mix")
        self.assertEqual(
            result["regions"][0]["mixer_receipt_status"],
            "pending_renderer_receipt",
        )

    def test_opaque_audio_keep_requires_target_audio(self) -> None:
        context = SimpleNamespace(audio_contract={"schema_version": "audio-contract/v1", "segments": []})
        with self.assertRaisesRegex(ReplicationError, "opaque_audio_keep"):
            validate_audio_route_contract(
                context=context,
                regions=[{
                    "region_id": "opaque",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                    "has_audio": False,
                }],
                active_high_fidelity=True,
            )

    def test_final_audio_qc_verifies_whisper_lipsync_events_loudness_silence_and_drift(self) -> None:
        contract = {
            "output_language": "zh",
            "exact_line_windows": [{
                "start_us": 100_000,
                "end_us": 500_000,
                "text": "立即购买",
                "meaning": "buy now",
                "delivery": "whisper",
                "visible_speaker": True,
            }],
            "foley_windows": [{"start_us": 520_000, "end_us": 560_000, "label": "tap"}],
            "ambience_windows": [{"start_us": 0, "end_us": 1_000_000, "label": "room"}],
            "silence_windows": [{"start_us": 600_000, "end_us": 700_000, "meaningful": True}],
        }
        evidence = {
            "final_output_sha256": "f" * 64,
            "output_language": "zh",
            "exact_line_windows": [{
                "start_us": 100_000,
                "end_us": 500_000,
                "text": "立即购买",
                "meaning": "buy now",
                "delivery": "whisper",
                "visible_speaker": True,
                "lip_sync_match_percent": 100,
            }],
            "foley_windows": contract["foley_windows"],
            "ambience_windows": contract["ambience_windows"],
            "silence_windows": contract["silence_windows"],
            "unexpected_silence_windows": [],
            "integrated_lufs": -16.0,
            "true_peak_dbfs": -2.0,
            "max_boundary_sample_jump": 0.1,
            "stream_start_offset_us": 10_000,
            "terminal_drift_us": 20_000,
        }
        report = validate_final_audio_qc(
            contract=contract,
            evidence=evidence,
            final_output_sha256="f" * 64,
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["exact_line_match_percent"], 100)
        self.assertEqual(report["lip_sync_match_percent"], 100)

    def test_final_audio_qc_blocks_unexpected_silence_loudness_jump_and_terminal_drift(self) -> None:
        contract = {
            "output_language": "en",
            "exact_line_windows": [{
                "start_us": 0,
                "end_us": 300_000,
                "text": "Buy now",
                "meaning": "buy now",
                "delivery": "light_voice",
                "visible_speaker": False,
            }],
        }
        base = {
            "final_output_sha256": "f" * 64,
            "output_language": "en",
            "exact_line_windows": [{
                **contract["exact_line_windows"][0],
                "lip_sync_match_percent": 100,
            }],
            "foley_windows": [],
            "ambience_windows": [],
            "silence_windows": [],
            "integrated_lufs": -16.0,
            "true_peak_dbfs": -2.0,
            "max_boundary_sample_jump": 0.1,
            "stream_start_offset_us": 0,
            "terminal_drift_us": 0,
        }
        mutations = (
            {"unexpected_silence_windows": [{"start_us": 100_000, "end_us": 200_000}]},
            {"unexpected_silence_windows": [], "integrated_lufs": -40.0},
            {"unexpected_silence_windows": [], "max_boundary_sample_jump": 0.9},
            {"unexpected_silence_windows": [], "terminal_drift_us": 200_000},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(AudioBackendUnavailable):
                validate_final_audio_qc(
                    contract=contract,
                    evidence={**base, **mutation},
                    final_output_sha256="f" * 64,
                )

    def test_input_contract_v2_music_extension_reports_capability_availability(self) -> None:
        self.assertTrue(hasattr(OptionalInputExtension, "extension_id"))
        self.assertTrue(hasattr(MusicTimelineAnalyzer, "analyze_music_timeline"))
        self.assertTrue(hasattr(BackgroundMusicCompositor, "compose_background_music"))
        unavailable = input_contract_v2_extensions(music_execution_available=False)
        self.assertTrue(unavailable["background_music"]["public_input"])
        self.assertFalse(unavailable["background_music"]["enabled"])
        self.assertEqual(
            unavailable["background_music"]["required_capability"],
            "background_music_execution/v1",
        )
        self.assertEqual(unavailable["background_music"]["availability"], "capability_unavailable")

        available = input_contract_v2_extensions(music_execution_available=True)
        self.assertTrue(available["background_music"]["enabled"])
        self.assertEqual(available["background_music"]["availability"], "enabled")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audio.wav"
        self.path.write_bytes(b"RIFF" + bytes(range(64)))
        self.model_sha = "a" * 64

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_posts_audio_bytes_and_validates_model_and_input_evidence(self) -> None:
        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-audio-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "input_sha256": payload["input_sha256"],
                "model": {"id": "yamnet-v1", "sha256": self.model_sha},
                "events": [
                    {"event_id": "E1", "kind": "foley", "label": "click", "start_ms": 10, "end_ms": 80},
                    {"event_id": "E2", "kind": "silence", "label": "pause", "start_ms": 100, "end_ms": 160, "meaningful": True},
                ],
            }

        server, thread, endpoint, requests = _server(response)
        try:
            backend = EvidenceBoundHttpAudioEventBackend(
                endpoint=endpoint,
                model_id="yamnet-v1",
                model_sha256=self.model_sha,
                production=False,
            )
            self.assertEqual(backend.capability_identity()["evidence_binding"], "usfr-audio-evidence/v1")
            receipt = backend.classify(self.path, segments=[{"start_ms": 0, "end_ms": 30}], silence_windows=[])
            events = receipt["events"]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual([item["kind"] for item in events], ["foley", "silence"])
        self.assertEqual(requests[0]["input_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertNotIn(str(self.path), json.dumps(requests[0]))
        self.assertIn("audio_b64", requests[0])
        self.assertEqual(receipt["evidence"]["input_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertNotIn("last_evidence", vars(backend))

    def test_context_projection_drops_worker_paths_before_transport(self) -> None:
        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-audio-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "input_sha256": payload["input_sha256"],
                "model": {"id": "yamnet-v1", "sha256": self.model_sha},
                "events": [
                    {
                        "event_id": "E1",
                        "kind": "foley",
                        "label": "tap",
                        "start_ms": 1,
                        "end_ms": 10,
                        "worker_path": str(self.path),
                    }
                ],
            }

        server, thread, endpoint, requests = _server(response)
        try:
            backend = EvidenceBoundHttpAudioEventBackend(
                endpoint=endpoint,
                model_id="yamnet-v1",
                model_sha256=self.model_sha,
                production=False,
            )
            events = backend(
                self.path,
                segments=[{"start_ms": 0, "end_ms": 20, "text": "hello", "path": str(self.path)}],
                silence_windows=[{"start_ms": 20, "end_ms": 30, "worker_path": str(self.path)}],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        wire = json.dumps(requests[0], ensure_ascii=False)
        self.assertNotIn(str(self.path), wire)
        self.assertNotIn("worker_path", wire)
        self.assertNotIn("worker_path", events[0])

    def test_rejects_stale_input_hash_and_out_of_range_events(self) -> None:
        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-audio-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "input_sha256": "0" * 64,
                "model": {"id": "yamnet-v1", "sha256": self.model_sha},
                "events": [{"event_id": "E1", "kind": "foley", "start_ms": -1, "end_ms": 20}],
            }

        server, thread, endpoint, _requests = _server(response)
        try:
            backend = EvidenceBoundHttpAudioEventBackend(
                endpoint=endpoint,
                model_id="yamnet-v1",
                model_sha256=self.model_sha,
                production=False,
            )
            with self.assertRaisesRegex(AudioBackendUnavailable, "input SHA"):
                backend(self.path, segments=[], silence_windows=[])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_rejects_non_boolean_meaningful_flag(self) -> None:
        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-audio-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "input_sha256": payload["input_sha256"],
                "model": {"id": "yamnet-v1", "sha256": self.model_sha},
                "events": [{"event_id": "E1", "kind": "silence", "start_ms": 10, "end_ms": 20, "meaningful": "false"}],
            }

        server, thread, endpoint, _requests = _server(response)
        try:
            backend = EvidenceBoundHttpAudioEventBackend(
                endpoint=endpoint,
                model_id="yamnet-v1",
                model_sha256=self.model_sha,
                production=False,
            )
            with self.assertRaisesRegex(AudioBackendUnavailable, "meaningful"):
                backend(self.path, segments=[], silence_windows=[], duration_ms=100)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_rejects_out_of_range_event_confidence(self) -> None:
        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-audio-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "input_sha256": payload["input_sha256"],
                "model": {"id": "yamnet-v1", "sha256": self.model_sha},
                "events": [{"event_id": "E1", "kind": "music", "start_ms": 10, "end_ms": 20, "confidence": 2}],
            }

        server, thread, endpoint, _requests = _server(response)
        try:
            backend = EvidenceBoundHttpAudioEventBackend(
                endpoint=endpoint,
                model_id="yamnet-v1",
                model_sha256=self.model_sha,
                production=False,
            )
            with self.assertRaisesRegex(AudioBackendUnavailable, "confidence"):
                backend(self.path, segments=[], silence_windows=[], duration_ms=100)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_production_requires_explicit_model_identity(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceBoundHttpAudioEventBackend(
                endpoint="https://audio.internal/classify",
                model_id="yamnet-v1",
                model_sha256="bad",
                production=True,
            )

    def test_production_requires_https_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            EvidenceBoundHttpAudioEventBackend(
                endpoint="http://audio.internal/classify",
                model_id="yamnet-v1",
                model_sha256=self.model_sha,
                production=True,
            )

    def test_from_environment_binds_endpoint_and_model_identity(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "USFR_AUDIO_EVENT_ENDPOINT": "http://127.0.0.1:9000/classify",
                "USFR_AUDIO_EVENT_MODEL_ID": "yamnet-v1",
                "USFR_AUDIO_EVENT_MODEL_SHA256": self.model_sha,
            },
            clear=False,
        ):
            backend = EvidenceBoundHttpAudioEventBackend.from_environment(production=False)
        self.assertEqual(backend.endpoint, "http://127.0.0.1:9000/classify")
        self.assertEqual(backend.model_id, "yamnet-v1")

class SourceAudioPerformanceQcTest(unittest.TestCase):
    def test_rejects_wrong_g02_or_lip_and_beat_drift(self) -> None:
        from server.audio_backends import validate_source_audio_performance_qc

        remux = {
            "schema_version": "source-audio-performance-remux/v1",
            "source_media_sha256": "a" * 64,
            "source_audio_sha256": "b" * 64,
            "request_sha256": "c" * 64,
            "final_output_sha256": "d" * 64,
            "forbidden_operations": ["atempo", "loop", "stretch", "freeze", "black_padding", "audio_padding"],
            "regions": [
                {"region_id": "G01", "audio_mode": "source_master", "source_start_us": 0, "source_end_us": 1_000_000},
                {"region_id": "U01", "audio_mode": "opaque_audio_keep", "opaque_media_sha256": "e" * 64},
                {"region_id": "G02", "audio_mode": "source_master", "source_start_us": 2_000_000, "source_end_us": 3_000_000},
            ],
        }
        evidence = {
            "schema_version": "source-audio-performance-qc/v1",
            "final_output_sha256": "d" * 64,
            "source_media_sha256": "a" * 64,
            "source_audio_sha256": "b" * 64,
            "remux_request_sha256": "c" * 64,
            "performance_line_contract_sha256": "f" * 64,
            "regions": remux["regions"],
            "lip_sync_windows": [{"region_id": "G01", "error_ms": 120}, {"region_id": "G02", "error_ms": 120}],
            "beat_action_windows": [{"region_id": "G01", "error_ms": 160}, {"region_id": "G02", "error_ms": 160}],
            "forbidden_operations_detected": [],
            "stream_start_offset_us": 0,
            "terminal_drift_us": 0,
        }
        self.assertTrue(
            validate_source_audio_performance_qc(
                remux_receipt=remux,
                evidence=evidence,
                final_output_sha256="d" * 64,
            )["passed"]
        )
        wrong_g02 = {**evidence, "regions": [*evidence["regions"]]}
        wrong_g02["regions"][2] = {**wrong_g02["regions"][2], "source_start_us": 0}
        with self.assertRaisesRegex(AudioBackendUnavailable, "region"):
            validate_source_audio_performance_qc(remux_receipt=remux, evidence=wrong_g02, final_output_sha256="d" * 64)
        with self.assertRaisesRegex(AudioBackendUnavailable, "lip-sync"):
            validate_source_audio_performance_qc(
                remux_receipt=remux,
                evidence={**evidence, "lip_sync_windows": [{"region_id": "G01", "error_ms": 121}, {"region_id": "G02", "error_ms": 120}]},
                final_output_sha256="d" * 64,
            )


if __name__ == "__main__":
    unittest.main()
