from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from PIL import Image

from server.real_capabilities import DeterministicUiRenderer, FfmpegDynamicsAnalyzer
from server.vision_backends import (
    EvidenceBoundHttpOcrBackend,
    EvidenceBoundHttpSemanticQcEvaluator,
    EvidenceBoundHttpVlmBackend,
    VisionBackendUnavailable,
    _qc_dimensions_digest,
    _qc_factor_scores_digest,
    _canonical_sha256,
    _validate_hf_extension_response,
)


def _adaptive_evidence_plan(*, source_sha256: str, duration_us: int, width: int, height: int, fps: int) -> dict:
    script = (
        Path(__file__).resolve().parents[1]
        / "bundled-skills"
        / "analyze-reference-video-dynamics"
        / "scripts"
        / "adaptive_evidence_plan.py"
    )
    spec = importlib.util.spec_from_file_location("test_adaptive_evidence_plan", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_evidence_plan(
        {
            "contract": "reference-video-probe",
            "contract_version": 1,
            "duration_us": duration_us,
            "source_width": width,
            "source_height": height,
            "fps_num": fps,
            "fps_den": 1,
            "scene_cut_candidates_us": [],
            "audio_streams": [],
        },
        source_sha256=source_sha256,
    )


class _JsonHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    response_factory = staticmethod(lambda payload: {})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(payload)
        response = type(self).response_factory(payload)
        data = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args) -> None:
        return


@contextmanager
def _json_server(response_factory):
    handler = type("Handler", (_JsonHandler,), {"requests": [], "response_factory": staticmethod(response_factory)})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/analyze", handler.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class EvidenceBoundVisionBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.model_sha = "a" * 64

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _active_context():
        class Context:
            profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }

        return Context()

    @staticmethod
    def _hf_extension(duration_us: int, frame_sha: str) -> dict:
        midpoint = duration_us // 2

        def evidence(evidence_id: str) -> dict:
            return {
                "evidence_id": evidence_id,
                "kind": "frame",
                "start_us": 0,
                "end_us": duration_us,
                "frame": 0,
                "frame_sha256": frame_sha,
                "method": "evidence-bound semantic pass",
                "observed_inferred_planned": "observed",
                "confidence": 0.98,
            }

        return {
            "schema_version": 1,
            "analysis_pass_count": 1,
            "semantic_cuts": [{
                "cut": 1,
                "scene_topology": {
                    "entities": [{
                        "entity_id": "scene",
                        "layer": "foreground",
                        "bbox": [0.0, 0.0, 1.0, 1.0],
                        "z_order": 0,
                        "relation_to_camera": "fills the frame",
                    }],
                    "spatial_relations": ["scene remains continuous"],
                    "occlusion_order": ["scene"],
                    "table_line_y": None,
                    "horizon_y": None,
                    "negative_space": [0.0, 0.0, 1.0, 1.0],
                },
                "framing_migration": {
                    "strategy": "crop",
                    "anchors": [{"anchor_id": "scene", "bbox": [0.0, 0.0, 1.0, 1.0]}],
                    "topology_constraint": "preserve the full scene",
                },
                "lighting": {
                    "key_origin": "front",
                    "key_vector": [0.0, 0.0, 1.0],
                    "shadow_vector": [0.0, 0.0, 0.0],
                    "hardness": "soft",
                    "contrast_ratio": 1.0,
                    "color_temperature_k": 5000,
                },
                "performance": {
                    "applicability": "not_applicable",
                    "not_applicable_reason": "no identifiable performer",
                },
                "object_action": {
                    "state_sequence": [
                        {"phase": "before", "start_us": 0, "end_us": midpoint, "state": "scene stable"},
                        {"phase": "completed", "start_us": midpoint, "end_us": duration_us, "state": "scene stable"},
                    ],
                    "hand_ownership": "none",
                    "contact_points": ["none"],
                    "movement_trajectory": "no movement",
                    "completed_end_state": "scene stable",
                    "caused_audio_event_ids": [1],
                },
                "speech_audio": {
                    "exact_asr_event_ids": [],
                    "audio_event_mappings": [{
                        "event_id": 1,
                        "role": "ambience",
                        "synced_factor_id": "HFH.C01.AUDIO.AMBIENCE",
                        "evidence": [evidence("E-AUDIO")],
                    }],
                    "meaningful_silence_ranges": [],
                },
                "evidence": [evidence("E-CUT")],
                "observed_inferred_planned": "observed",
                "confidence": 0.98,
                "uncertainty": [],
                "criticality": "H",
                "blocker_threshold": 0.85,
            }],
            "route_excluded_intervals": [],
        }

    @staticmethod
    def _overlay_contract(duration_us: int, *, width: int = 96, height: int = 64) -> dict:
        overlay = {
            "overlay_id": "cta-1",
            "kind": "cta_text",
            "start_us": 0,
            "end_us": duration_us,
            "start_rect": {"x": 0.10, "y": 0.80, "width": 0.30, "height": 0.10},
            "end_rect": {"x": 0.10, "y": 0.80, "width": 0.30, "height": 0.10},
            "start_rotation_deg": 0,
            "end_rotation_deg": 0,
            "start_opacity": 1,
            "end_opacity": 1,
            "motion_phase": "static",
            "motion_path": "static screen-space hold",
            "layer_relation": "above source scene",
            "z_index": 10,
            "interpolation": "hold",
            "keyframes": [
                {
                    "time_us": 0,
                    "bbox": {"x": 0.10, "y": 0.80, "width": 0.30, "height": 0.10},
                    "rotation_deg": 0,
                    "opacity": 1,
                },
                {
                    "time_us": duration_us,
                    "bbox": {"x": 0.10, "y": 0.80, "width": 0.30, "height": 0.10},
                    "rotation_deg": 0,
                    "opacity": 1,
                },
            ],
            "observed_text": "BUY NOW",
        }
        return {
            "contract": "source-ui-overlay-motion",
            "contract_version": 1,
            "reference_duration_us": duration_us,
            "source_width": width,
            "source_height": height,
            "coordinate_space": "rotation_corrected_source_visible_frame_normalized",
            "target_mapping": "source_normalized_composition_to_target_frame",
            "attachment": "screen_space",
            "time_range_semantics": "start_inclusive_end_exclusive",
            "cuts": [{"cut": 1, "start_us": 0, "end_us": duration_us, "source_overlays": [overlay]}],
            "notes": ["sidecar-provided source overlay evidence"],
        }

    def test_production_renderer_rejects_bare_ocr_callable(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence-bound OCR backend"):
            DeterministicUiRenderer(
                ocr_backend=lambda _path: [{"text": "BUY", "bbox": [0, 0, 10, 10]}],
                expected_text=["BUY"],
                expected_layout=[{"text": "BUY", "bbox": [0, 0, 10, 10]}],
                production=True,
                sha256="b" * 64,
            )

    def test_production_dynamics_rejects_bare_semantic_callable(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence-bound VLM backend"):
            FfmpegDynamicsAnalyzer(
                semantic_analyzer=lambda **_kwargs: {"source_cuts": []},
                production=True,
                sha256="c" * 64,
            )

    def test_http_ocr_backend_binds_response_to_exact_image_and_model(self) -> None:
        image_path = self.root / "ui.png"
        Image.new("RGB", (120, 60), "white").save(image_path)

        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-ocr-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "input_sha256": payload["input_sha256"],
                "model": {"id": "pp-ocrv5", "sha256": self.model_sha},
                "records": [
                    {"text": "BUY NOW", "bbox": [20, 10, 100, 40], "confidence": 0.998},
                ],
            }

        with _json_server(response) as (endpoint, requests):
            backend = EvidenceBoundHttpOcrBackend(
                endpoint=endpoint,
                model_id="pp-ocrv5",
                model_sha256=self.model_sha,
                production=False,
            )
            result = backend.recognize(image_path)

        self.assertEqual(result["records"][0]["text"], "BUY NOW")
        self.assertEqual(result["evidence"]["input_sha256"], hashlib.sha256(image_path.read_bytes()).hexdigest())
        self.assertEqual(result["evidence"]["model_sha256"], self.model_sha)
        wire = json.dumps(requests[0], ensure_ascii=False)
        self.assertNotIn(str(image_path), wire)
        self.assertNotIn("file://", wire)

    def test_http_semantic_qc_evaluator_sends_media_bytes_and_binds_receipt(self) -> None:
        video = self.root / "final.mp4"
        video_bytes = b"deterministic-final-mp4-bytes"
        video.write_bytes(video_bytes)
        final_sha = hashlib.sha256(video_bytes).hexdigest()
        source_sha = "b" * 64
        dimensions = {
            "timeline_route": {
                "score": 100,
                "criticality": "H",
                "evidence": [],
            }
        }
        factor_scores = {
            "HFH.C01.ACTION.ENDPOINT": {
                "score": 100,
                "criticality": "H",
                "evidence": [],
            }
        }
        source_audio_performance = {
            "performance_line_contract_sha256": "c" * 64,
            "final_output_sha256": final_sha,
            "source_media_sha256": source_sha,
            "source_audio_sha256": "a" * 64,
            "remux_request_sha256": "d" * 64,
            "regions": [
                {
                    "region_id": "G01",
                    "audio_mode": "source_master",
                    "output_start_us": 0,
                    "output_end_us": 500_000,
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                }
            ],
        }

        def response(payload: dict) -> dict:
            qc_input = {
                "dimensions": dimensions,
                "factor_scores": factor_scores,
                "route_coverage": 100,
                "ui_ocr": None,
                "hard_failures": [],
            }
            receipt = {
                "schema_version": "high-fidelity-qc-evaluator-receipt/v1",
                "provenance": "independent_evaluator",
                "implementation": "server.vision_backends:EvidenceBoundHttpSemanticQcEvaluator",
                "version": "1.0.0",
                "model_id": "qc-model",
                "model_sha256": self.model_sha,
                "request_sha256": payload["evaluator_request_sha256"],
                "response_sha256": _canonical_sha256(qc_input),
                "dimensions_sha256": _qc_dimensions_digest(dimensions),
                "factor_scores_sha256": _qc_factor_scores_digest(factor_scores),
                "final_output_sha256": payload["media_sha256"],
                "current_run_source_sha256s": [source_sha],
            }
            return {
                "schema_version": "usfr-qc-evaluator/v1",
                "request_sha256": payload["request_sha256"],
                "model": {"id": "qc-model", "sha256": self.model_sha},
                "evaluator_request_sha256": payload["evaluator_request_sha256"],
                "media_sha256": payload["media_sha256"],
                "qc_input": {**qc_input, "evaluator_receipt": receipt},
            }

        request_payload = {
            "schema_version": "high-fidelity-qc-evaluator-request/v1",
            "final_output_sha256": final_sha,
            "current_run_source_sha256s": [source_sha],
            "input_artifact_sha256s": [],
            "source_audio_performance": source_audio_performance,
        }
        request_sha = _canonical_sha256(request_payload)
        with _json_server(response) as (endpoint, requests):
            evaluator = EvidenceBoundHttpSemanticQcEvaluator(
                endpoint=endpoint,
                model_id="qc-model",
                model_sha256=self.model_sha,
                production=False,
            )
            result = evaluator.evaluate(
                path=video,
                input_artifacts=[],
                final_output_sha256=final_sha,
                current_run_source_sha256s=[source_sha],
                source_audio_performance=source_audio_performance,
                request_payload=request_payload,
                request_sha256=request_sha,
            )

        self.assertEqual(result["qc_input"]["evaluator_receipt"]["request_sha256"], request_sha)
        self.assertEqual(result["qc_input"]["evaluator_receipt"]["final_output_sha256"], final_sha)
        wire = json.dumps(requests[0], ensure_ascii=False)
        self.assertNotIn(str(video), wire)
        self.assertEqual(
            requests[0]["evaluator_request"]["source_audio_performance"],
            source_audio_performance,
        )
        self.assertEqual(
            hashlib.sha256(
                __import__("base64").b64decode(requests[0]["media_base64"])
            ).hexdigest(),
            final_sha,
        )

    def test_http_semantic_qc_evaluator_rejects_stale_media_binding(self) -> None:
        video = self.root / "final-stale.mp4"
        video.write_bytes(b"final-bytes")
        final_sha = hashlib.sha256(video.read_bytes()).hexdigest()
        source_sha = "c" * 64

        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-qc-evaluator/v1",
                "request_sha256": payload["request_sha256"],
                "model": {"id": "qc-model", "sha256": self.model_sha},
                "evaluator_request_sha256": payload["evaluator_request_sha256"],
                "media_sha256": "0" * 64,
                "qc_input": {},
            }

        request_payload = {
            "schema_version": "high-fidelity-qc-evaluator-request/v1",
            "final_output_sha256": final_sha,
            "current_run_source_sha256s": [source_sha],
            "input_artifact_sha256s": [],
        }
        with _json_server(response) as (endpoint, _requests):
            evaluator = EvidenceBoundHttpSemanticQcEvaluator(
                endpoint=endpoint,
                model_id="qc-model",
                model_sha256=self.model_sha,
                production=False,
            )
            with self.assertRaisesRegex(VisionBackendUnavailable, "media SHA"):
                evaluator.evaluate(
                    path=video,
                    input_artifacts=[],
                    final_output_sha256=final_sha,
                    current_run_source_sha256s=[source_sha],
                    request_payload=request_payload,
                    request_sha256=_canonical_sha256(request_payload),
                )

    def test_http_semantic_qc_evaluator_rejects_request_payload_not_bound_to_actual_media(self) -> None:
        video = self.root / "final-request-mismatch.mp4"
        video_bytes = b"request-bound-final-bytes"
        video.write_bytes(video_bytes)
        final_sha = hashlib.sha256(video_bytes).hexdigest()
        source_sha = "d" * 64
        request_payload = {
            "schema_version": "high-fidelity-qc-evaluator-request/v1",
            "final_output_sha256": "0" * 64,
            "current_run_source_sha256s": [source_sha],
            "input_artifact_sha256s": [],
        }

        with self.assertRaisesRegex(VisionBackendUnavailable, "request payload.*final_output_sha256"):
            evaluator = EvidenceBoundHttpSemanticQcEvaluator(
                endpoint="http://127.0.0.1:1/unreachable",
                model_id="qc-model",
                model_sha256=self.model_sha,
                production=False,
            )
            evaluator.evaluate(
                path=video,
                input_artifacts=[],
                final_output_sha256=final_sha,
                current_run_source_sha256s=[source_sha],
                request_payload=request_payload,
                request_sha256=_canonical_sha256(request_payload),
            )

    def test_http_ocr_backend_rejects_stale_or_fabricated_response(self) -> None:
        image_path = self.root / "ui.png"
        Image.new("RGB", (80, 40), "white").save(image_path)

        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-ocr-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "input_sha256": "0" * 64,
                "model": {"id": "pp-ocrv5", "sha256": self.model_sha},
                "records": [{"text": "BUY", "bbox": [1, 1, 20, 20], "confidence": 1.0}],
            }

        with _json_server(response) as (endpoint, _requests):
            backend = EvidenceBoundHttpOcrBackend(
                endpoint=endpoint,
                model_id="pp-ocrv5",
                model_sha256=self.model_sha,
                production=False,
            )
            with self.assertRaisesRegex(VisionBackendUnavailable, "input SHA"):
                backend.recognize(image_path)

    def test_http_vlm_backend_sends_hashed_frames_not_a_worker_path(self) -> None:
        video = self.root / "source.mp4"
        encoded = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=96x64:r=5:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
        )
        if encoded.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        duration_us = 400_000
        cuts = [{"cut": 1, "start_us": 0, "end_us": duration_us}]

        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-vlm-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "frame_sha256s": [item["sha256"] for item in payload["frames"]],
                "model": {"id": "qwen2.5-vl", "sha256": self.model_sha},
                "source_cuts": [
                    {
                        "start_us": 0,
                        "end_us": duration_us,
                        "scene": "blue background",
                        "action": "no subject movement",
                        "camera": "locked camera",
                        "transition": "continuous",
                        "end_state": "blue frame",
                        "certainty": "certain",
                        "worker_path": str(video),
                        "evidence_refs": [
                            {
                                "kind": "frame",
                                "frame_sha256": payload["frames"][0]["sha256"],
                                "path": str(video),
                            }
                        ],
                    }
                ],
                "source_events": [],
            }

        with _json_server(response) as (endpoint, requests):
            backend = EvidenceBoundHttpVlmBackend(
                endpoint=endpoint,
                model_id="qwen2.5-vl",
                model_sha256=self.model_sha,
                production=False,
                max_frames=2,
            )
            result = backend.analyze(
                path=video,
                probe={"duration_us": duration_us, "width": 96, "height": 64, "fps": 5.0},
                cuts=cuts,
                context=type("Context", (), {"routes": {"ui": "opaque_ui_demo", "tail": "omit_source_end_card"}})(),
            )

        self.assertEqual(result["source_cuts"][0]["scene"], "blue background")
        self.assertEqual(requests[0]["route_policy"]["ui_route"], "opaque_ui_demo")
        self.assertEqual(requests[0]["route_policy"]["tail_route"], "omit_source_end_card")
        self.assertTrue(result["backend_evidence"]["frame_sha256s"])
        self.assertNotIn("worker_path", result["source_cuts"][0])
        self.assertNotIn("path", result["source_cuts"][0]["evidence_refs"][0])
        self.assertNotIn(str(video), json.dumps(result, ensure_ascii=False))
        wire = json.dumps(requests[0], ensure_ascii=False)
        self.assertNotIn(str(video), wire)
        self.assertNotIn("file://", wire)

    def test_http_vlm_request_is_bound_to_the_adaptive_evidence_plan(self) -> None:
        video = self.root / "planned-source.mp4"
        encoded = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=green:s=96x64:r=5:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
        )
        if encoded.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        duration_us = 400_000
        source_sha256 = hashlib.sha256(video.read_bytes()).hexdigest()
        plan = _adaptive_evidence_plan(
            source_sha256=source_sha256,
            duration_us=duration_us,
            width=96,
            height=64,
            fps=5,
        )

        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-vlm-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "frame_sha256s": [item["sha256"] for item in payload["frames"]],
                "model": {"id": "qwen2.5-vl", "sha256": self.model_sha},
                "source_cuts": [{
                    "start_us": 0,
                    "end_us": duration_us,
                    "scene": "green background",
                    "action": "no subject movement",
                    "camera": "locked camera",
                    "transition": "continuous",
                    "end_state": "green frame",
                    "certainty": "certain",
                    "evidence_refs": [{"kind": "frame", "frame_sha256": payload["frames"][0]["sha256"]}],
                }],
                "source_events": [],
            }

        with _json_server(response) as (endpoint, requests):
            backend = EvidenceBoundHttpVlmBackend(
                endpoint=endpoint,
                model_id="qwen2.5-vl",
                model_sha256=self.model_sha,
                production=False,
                max_frames=2,
            )
            result = backend.analyze(
                path=video,
                probe={"duration_us": duration_us, "width": 96, "height": 64, "fps": 5.0},
                cuts=[{"cut": 1, "start_us": 0, "end_us": duration_us}],
                evidence_plan=plan,
            )

        self.assertEqual(requests[0]["evidence_plan"], plan)
        self.assertEqual(result["backend_evidence"]["evidence_plan_sha256"], plan["plan_sha256"])
        self.assertNotIn(str(video), json.dumps(requests[0]["evidence_plan"], ensure_ascii=False))

    def test_active_http_vlm_preserves_and_validates_full_hf_extension(self) -> None:
        video = self.root / "active-source.mp4"
        encoded = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=96x64:r=5:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
        )
        if encoded.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        duration_us = 400_000
        cuts = [{"cut": 1, "start_us": 0, "end_us": duration_us}]

        def response(payload: dict) -> dict:
            frame_sha = payload["frames"][0]["sha256"]
            return {
                "schema_version": "usfr-vlm-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "frame_sha256s": [item["sha256"] for item in payload["frames"]],
                "model": {"id": "qwen2.5-vl", "sha256": self.model_sha},
                "source_cuts": [{
                    "start_us": 0,
                    "end_us": duration_us,
                    "scene": "blue background",
                    "action": "stable scene",
                    "camera": "locked camera",
                    "transition": "continuous",
                    "end_state": "blue frame",
                    "certainty": "certain",
                    "evidence_refs": [{"kind": "frame", "frame_sha256": frame_sha}],
                }],
                "source_events": [{
                    "event": 1,
                    "kind": "ambience",
                    "start_us": 0,
                    "end_us": duration_us,
                    "source_cut_start": 1,
                    "source_cut_end": 1,
                    "text": "room tone",
                    "certainty": "certain",
                }],
                "extensions": {
                    "high_fidelity_hybrid_v1": self._hf_extension(duration_us, frame_sha),
                },
            }

        with _json_server(response) as (endpoint, _requests):
            backend = EvidenceBoundHttpVlmBackend(
                endpoint=endpoint,
                model_id="qwen2.5-vl",
                model_sha256=self.model_sha,
                production=False,
                max_frames=2,
            )
            result = backend.analyze(
                path=video,
                probe={"duration_us": duration_us, "width": 96, "height": 64, "fps": 5.0},
                cuts=cuts,
                context=self._active_context(),
            )

        extension = result["extensions"]["high_fidelity_hybrid_v1"]
        self.assertEqual(extension["analysis_pass_count"], 1)
        self.assertEqual(extension["semantic_cuts"][0]["cut"], 1)
        self.assertIn(
            result["backend_evidence"]["frame_sha256s"][0],
            [item["frame_sha256"] for item in extension["semantic_cuts"][0]["evidence"]],
        )

    def test_active_http_vlm_rejects_source_cut_evidence_from_another_cut(self) -> None:
        video = self.root / "active-cross-cut-source.mp4"
        encoded = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=96x64:r=5:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
        )
        if encoded.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        duration_us = 400_000

        def response(payload: dict) -> dict:
            frame_from_first = payload["frames"][0]["sha256"]
            frame_from_last = payload["frames"][-1]["sha256"]
            return {
                "schema_version": "usfr-vlm-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "frame_sha256s": [item["sha256"] for item in payload["frames"]],
                "model": {"id": "qwen2.5-vl", "sha256": self.model_sha},
                "source_cuts": [
                    {
                        "start_us": 0,
                        "end_us": 200_000,
                        "scene": "first scene",
                        "action": "first action",
                        "camera": "locked camera",
                        "transition": "continuous",
                        "end_state": "first end",
                        "certainty": "certain",
                        "evidence_refs": [{"kind": "frame", "frame_sha256": frame_from_last}],
                    },
                    {
                        "start_us": 200_000,
                        "end_us": duration_us,
                        "scene": "second scene",
                        "action": "second action",
                        "camera": "locked camera",
                        "transition": "continuous",
                        "end_state": "second end",
                        "certainty": "certain",
                        "evidence_refs": [{"kind": "frame", "frame_sha256": frame_from_first}],
                    },
                ],
                "source_events": [],
            }

        with _json_server(response) as (endpoint, _requests):
            backend = EvidenceBoundHttpVlmBackend(
                endpoint=endpoint,
                model_id="qwen2.5-vl",
                model_sha256=self.model_sha,
                production=False,
                max_frames=4,
            )
            with self.assertRaisesRegex(VisionBackendUnavailable, "source Cut.*(inside.*Cut timing|ambiguous.*timestamp)"):
                backend.analyze(
                    path=video,
                    probe={"duration_us": duration_us, "width": 96, "height": 64, "fps": 5.0},
                    cuts=[
                        {"cut": 1, "start_us": 0, "end_us": 200_000},
                        {"cut": 2, "start_us": 200_000, "end_us": duration_us},
                    ],
                    context=self._active_context(),
                )

    def test_active_http_vlm_rejects_missing_hf_extension(self) -> None:
        video = self.root / "active-missing-extension.mp4"
        encoded = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=96x64:r=5:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
        )
        if encoded.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        duration_us = 400_000

        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-vlm-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "frame_sha256s": [item["sha256"] for item in payload["frames"]],
                "model": {"id": "qwen2.5-vl", "sha256": self.model_sha},
                "source_cuts": [{
                    "start_us": 0,
                    "end_us": duration_us,
                    "scene": "blue background",
                    "action": "stable scene",
                    "camera": "locked camera",
                    "transition": "continuous",
                    "end_state": "blue frame",
                    "certainty": "certain",
                    "evidence_refs": [{"kind": "frame", "frame_sha256": payload["frames"][0]["sha256"]}],
                }],
                "source_events": [],
            }

        with _json_server(response) as (endpoint, _requests):
            backend = EvidenceBoundHttpVlmBackend(
                endpoint=endpoint,
                model_id="qwen2.5-vl",
                model_sha256=self.model_sha,
                production=False,
                max_frames=2,
            )
            with self.assertRaisesRegex(VisionBackendUnavailable, "high-fidelity.*extension"):
                backend.analyze(
                    path=video,
                    probe={"duration_us": duration_us, "width": 96, "height": 64, "fps": 5.0},
                    cuts=[{"cut": 1, "start_us": 0, "end_us": duration_us}],
                    context=self._active_context(),
                )

    def test_non_active_http_vlm_accepts_legacy_response_without_extension(self) -> None:
        # Existing non-profile deployments must continue to consume the
        # original source_cuts/source_events response shape.
        video = self.root / "legacy-source.mp4"
        encoded = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=96x64:r=5:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
        )
        if encoded.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        duration_us = 400_000

        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-vlm-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "frame_sha256s": [item["sha256"] for item in payload["frames"]],
                "model": {"id": "qwen2.5-vl", "sha256": self.model_sha},
                "source_cuts": [{
                    "start_us": 0,
                    "end_us": duration_us,
                    "scene": "blue background",
                    "action": "stable scene",
                    "camera": "locked camera",
                    "transition": "continuous",
                    "end_state": "blue frame",
                    "certainty": "certain",
                    "evidence_refs": [{"kind": "frame", "frame_sha256": payload["frames"][0]["sha256"]}],
                }],
                "source_events": [],
            }

        with _json_server(response) as (endpoint, _requests):
            backend = EvidenceBoundHttpVlmBackend(
                endpoint=endpoint,
                model_id="qwen2.5-vl",
                model_sha256=self.model_sha,
                production=False,
                max_frames=2,
            )
            result = backend.analyze(
                path=video,
                probe={"duration_us": duration_us, "width": 96, "height": 64, "fps": 5.0},
                cuts=[{"cut": 1, "start_us": 0, "end_us": duration_us}],
            )
        self.assertNotIn("extensions", result)
        self.assertEqual(result["source_cuts"][0]["start_us"], 0)

    def test_active_http_vlm_requires_extension_frame_digest_binding(self) -> None:
        video = self.root / "active-unbound-extension.mp4"
        encoded = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=96x64:r=5:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
        )
        if encoded.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        duration_us = 400_000

        def response(payload: dict) -> dict:
            extension = self._hf_extension(duration_us, payload["frames"][0]["sha256"])
            # Removing all extension-level frame references leaves only the
            # top-level sampled-frame list; active HF must reject that weaker
            # binding because factor evidence could have come from another
            # frame set.
            for record in extension["semantic_cuts"][0]["evidence"]:
                record.pop("frame_sha256", None)
            for mapping in extension["semantic_cuts"][0]["speech_audio"]["audio_event_mappings"]:
                for record in mapping["evidence"]:
                    record.pop("frame_sha256", None)
            return {
                "schema_version": "usfr-vlm-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "frame_sha256s": [item["sha256"] for item in payload["frames"]],
                "model": {"id": "qwen2.5-vl", "sha256": self.model_sha},
                "source_cuts": [{
                    "start_us": 0,
                    "end_us": duration_us,
                    "scene": "blue background",
                    "action": "stable scene",
                    "camera": "locked camera",
                    "transition": "continuous",
                    "end_state": "blue frame",
                    "certainty": "certain",
                    "evidence_refs": [{"kind": "frame", "frame_sha256": payload["frames"][0]["sha256"]}],
                }],
                "source_events": [{
                    "event": 1,
                    "kind": "ambience",
                    "start_us": 0,
                    "end_us": duration_us,
                    "source_cut_start": 1,
                    "source_cut_end": 1,
                    "text": "room tone",
                    "certainty": "certain",
                }],
                "extensions": {"high_fidelity_hybrid_v1": extension},
            }

        with _json_server(response) as (endpoint, _requests):
            backend = EvidenceBoundHttpVlmBackend(
                endpoint=endpoint,
                model_id="qwen2.5-vl",
                model_sha256=self.model_sha,
                production=False,
                max_frames=2,
            )
            with self.assertRaisesRegex(VisionBackendUnavailable, "frame.*binding"):
                backend.analyze(
                    path=video,
                    probe={"duration_us": duration_us, "width": 96, "height": 64, "fps": 5.0},
                    cuts=[{"cut": 1, "start_us": 0, "end_us": duration_us}],
                    context=self._active_context(),
                )

    def test_active_hf_extension_rejects_frame_digest_outside_its_cut(self) -> None:
        """Semantic evidence must be time-bound, not merely hash-bound."""

        duration_us = 400_000
        frame_sha = "d" * 64
        extension = self._hf_extension(duration_us, frame_sha)
        with self.assertRaisesRegex(
            VisionBackendUnavailable,
            "inside.*Cut|time.*bound|outside.*Cut|ambiguous.*timestamp",
        ):
            _validate_hf_extension_response(
                extension,
                source_cuts=[
                    {"cut": 1, "start_us": 0, "end_us": duration_us},
                ],
                source_events=[
                    {
                        "event": 1,
                        "kind": "ambience",
                        "start_us": 0,
                        "end_us": duration_us,
                        "source_cut_start": 1,
                        "source_cut_end": 1,
                    }
                ],
                frame_sha256s=[frame_sha],
                frame_timestamps={frame_sha: [500_000]},
            )

    def test_active_hf_extension_rejects_source_cut_with_foreign_sample(self) -> None:
        """A source Cut cannot cite a sampled frame from another Cut."""

        duration_us = 400_000
        frame_sha = "e" * 64
        extension = self._hf_extension(duration_us, frame_sha)
        with self.assertRaisesRegex(
            VisionBackendUnavailable,
            "inside.*Cut|time.*bound|outside.*Cut|ambiguous.*timestamp",
        ):
            _validate_hf_extension_response(
                extension,
                source_cuts=[
                    {"cut": 1, "start_us": 0, "end_us": duration_us},
                ],
                source_events=[
                    {
                        "event": 1,
                        "kind": "ambience",
                        "start_us": 0,
                        "end_us": duration_us,
                        "source_cut_start": 1,
                        "source_cut_end": 1,
                    }
                ],
                frame_sha256s=[frame_sha],
                frame_timestamps={frame_sha: [duration_us]},
            )

    def test_active_hf_extension_rejects_mixed_explicit_and_bare_cross_cut_refs(self) -> None:
        duration_us = 400_000
        frame_in = "1" * 64
        frame_out = "2" * 64
        extension = self._hf_extension(duration_us, frame_in)
        extension["semantic_cuts"][0]["evidence"][0]["timestamp_us"] = 100_000
        extension["semantic_cuts"][0]["evidence"].append(
            {
                "evidence_id": "E-CROSS-CUT",
                "kind": "frame",
                "start_us": 0,
                "end_us": duration_us,
                "frame": 0,
                "frame_sha256": frame_out,
                "method": "evidence-bound semantic pass",
                "observed_inferred_planned": "observed",
                "confidence": 0.98,
            }
        )
        with self.assertRaisesRegex(VisionBackendUnavailable, "bare digest|ambiguous|inside.*Cut"):
            _validate_hf_extension_response(
                extension,
                source_cuts=[{"cut": 1, "start_us": 0, "end_us": duration_us}],
                source_events=[
                    {
                        "event": 1,
                        "kind": "ambience",
                        "start_us": 0,
                        "end_us": duration_us,
                        "source_cut_start": 1,
                        "source_cut_end": 1,
                    }
                ],
                frame_sha256s=[frame_in, frame_out],
                frame_timestamps={frame_in: [100_000], frame_out: [500_000]},
            )

    def test_active_timestamps_keep_one_sample_per_cut_before_optional_anchors(self) -> None:
        backend = EvidenceBoundHttpVlmBackend(
            endpoint="https://vlm.internal/analyze",
            model_id="qwen2.5-vl",
            model_sha256=self.model_sha,
            production=False,
            max_frames=6,
        )
        cuts = [
            {"cut": 1, "start_us": 0, "end_us": 200_000},
            {"cut": 2, "start_us": 200_000, "end_us": 400_000},
            {"cut": 3, "start_us": 400_000, "end_us": 600_000},
        ]
        timestamps = backend._timestamps(duration_us=600_000, fps=10.0, cuts=cuts)
        self.assertEqual(len(timestamps), 6)
        for cut in cuts:
            self.assertTrue(
                any(cut["start_us"] <= value < cut["end_us"] for value in timestamps),
                f"missing sampled frame for Cut {cut['cut']}",
            )

    def test_active_vlm_fails_closed_when_frame_budget_leaves_a_cut_uncovered(self) -> None:
        video = self.root / "coverage-source.mp4"
        video.write_bytes(b"source-bytes")
        backend = EvidenceBoundHttpVlmBackend(
            endpoint="https://vlm.internal/analyze",
            model_id="qwen2.5-vl",
            model_sha256=self.model_sha,
            production=False,
            max_frames=2,
        )
        backend._timestamps = lambda **_kwargs: [0, 100_000]  # type: ignore[method-assign]
        with self.assertRaisesRegex(VisionBackendUnavailable, "frame.*coverage|sample.*Cut"):
            backend.analyze(
                path=video,
                probe={"duration_us": 400_000, "width": 96, "height": 64, "fps": 5.0},
                cuts=[
                    {"cut": 1, "start_us": 0, "end_us": 200_000},
                    {"cut": 2, "start_us": 200_000, "end_us": 400_000},
                ],
                context=self._active_context(),
            )

    def test_http_vlm_preserves_optional_validated_source_overlay_contract(self) -> None:
        video = self.root / "overlay-source.mp4"
        encoded = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=96x64:r=5:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
        )
        if encoded.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        duration_us = 400_000

        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-vlm-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "frame_sha256s": [item["sha256"] for item in payload["frames"]],
                "model": {"id": "qwen2.5-vl", "sha256": self.model_sha},
                "source_cuts": [{
                    "start_us": 0,
                    "end_us": duration_us,
                    "scene": "blue background",
                    "action": "stable scene",
                    "camera": "locked camera",
                    "transition": "continuous",
                    "end_state": "blue frame",
                    "certainty": "certain",
                    "evidence_refs": [{"kind": "frame", "frame_sha256": payload["frames"][0]["sha256"]}],
                }],
                "source_events": [],
                "source_overlay_contract": self._overlay_contract(duration_us),
            }

        with _json_server(response) as (endpoint, _requests):
            backend = EvidenceBoundHttpVlmBackend(
                endpoint=endpoint,
                model_id="qwen2.5-vl",
                model_sha256=self.model_sha,
                production=False,
                max_frames=2,
            )
            result = backend.analyze(
                path=video,
                probe={"duration_us": duration_us, "width": 96, "height": 64, "fps": 5.0},
                cuts=[{"cut": 1, "start_us": 0, "end_us": duration_us}],
            )

        self.assertEqual(result["source_overlay_contract"]["contract"], "source-ui-overlay-motion")
        self.assertEqual(result["source_overlay_contract"]["cuts"][0]["end_us"], duration_us)
        self.assertEqual(
            result["backend_evidence"]["source_overlay_contract_sha256"],
            hashlib.sha256(json.dumps(result["source_overlay_contract"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        )

    def test_http_vlm_rejects_invalid_optional_source_overlay_contract(self) -> None:
        video = self.root / "invalid-overlay-source.mp4"
        encoded = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=96x64:r=5:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ],
            capture_output=True,
        )
        if encoded.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        duration_us = 400_000

        def response(payload: dict) -> dict:
            contract = self._overlay_contract(duration_us)
            contract["unexpected_field"] = "must fail closed"
            return {
                "schema_version": "usfr-vlm-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "frame_sha256s": [item["sha256"] for item in payload["frames"]],
                "model": {"id": "qwen2.5-vl", "sha256": self.model_sha},
                "source_cuts": [{
                    "start_us": 0,
                    "end_us": duration_us,
                    "scene": "blue background",
                    "action": "stable scene",
                    "camera": "locked camera",
                    "transition": "continuous",
                    "end_state": "blue frame",
                    "certainty": "certain",
                    "evidence_refs": [{"kind": "frame", "frame_sha256": payload["frames"][0]["sha256"]}],
                }],
                "source_events": [],
                "source_overlay_contract": contract,
            }

        with _json_server(response) as (endpoint, _requests):
            backend = EvidenceBoundHttpVlmBackend(
                endpoint=endpoint,
                model_id="qwen2.5-vl",
                model_sha256=self.model_sha,
                production=False,
                max_frames=2,
            )
            with self.assertRaisesRegex(VisionBackendUnavailable, "overlay.*unsupported|overlay.*invalid"):
                backend.analyze(
                    path=video,
                    probe={"duration_us": duration_us, "width": 96, "height": 64, "fps": 5.0},
                    cuts=[{"cut": 1, "start_us": 0, "end_us": duration_us}],
                )


if __name__ == "__main__":
    unittest.main()
