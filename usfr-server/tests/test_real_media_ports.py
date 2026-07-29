from __future__ import annotations

from array import array
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any
import wave

from server.media_materializer import MaterializedMedia
from server.real_capabilities import (
    CapabilityUnavailable,
    FfmpegCompositor,
    FfmpegQcEngine,
    _canonical_sha256,
    _freeze_interval_failure_code,
    _validate_renderer_timeline_manifest,
)
from server.errors import ReplicationError
from server.timeline_renderer import BundledTimelineRenderer


_TIMELINE_SCRIPT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "bundled-skills"
    / "seedance-storyboard-replication"
    / "scripts"
)
if str(_TIMELINE_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_TIMELINE_SCRIPT_ROOT))
from timeline_splice import load_contract  # noqa: E402

_QC_SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(_QC_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_QC_SCRIPT_ROOT))
from high_fidelity_qc import _dimensions_digest, _factor_scores_digest  # noqa: E402


class _Context:
    def __init__(self, path: Path):
        self.path = path
        self.work_dir = path.parent / "work"
        self.work_dir.mkdir(exist_ok=True)
        self.timeline_regions = ()
        self.artifacts = ()
        self.profile_snapshot = None

    @contextmanager
    def materialize_slot(self, slot_id: str, *, index: int = 0):
        data = self.path.read_bytes()
        yield MaterializedMedia(
            path=self.path,
            job_id="job-test",
            object_key=f"tenant/source/{self.path.name}",
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            content_type="video/mp4",
            metadata={},
        )

    def publish_artifact(self, *, kind, stream, content_type, expected_sha256, metadata=None):
        data = stream.read()
        return {
            "kind": kind,
            "sha256": hashlib.sha256(data).hexdigest(),
            "uri": f"s3://tenant/{kind}",
            "metadata": {"object_key": f"tenant/{kind}", "size_bytes": len(data), "content_type": content_type, **(metadata or {})},
        }


class RendererTimelineManifestContractTest(unittest.TestCase):
    def test_active_manifest_requires_output_bound_receipt_for_every_non_source_placement(self):
        output_sha = "a" * 64
        regions = (
            {
                "region_id": "source",
                "source_start_us": 0,
                "source_end_us": 1_000_000,
                "region_type": "source_ui_keep",
                "media_origin": "source_interval",
                "assembly_policy": "splice_source_interval",
            },
            {
                "region_id": "opaque",
                "source_start_us": 1_000_000,
                "source_end_us": 2_000_000,
                "region_type": "opaque_ui_demo",
                "media_origin": "user_upload",
                "assembly_policy": "splice_opaque_media",
                "media_sha256": "b" * 64,
            },
        )
        manifest = {
            "final_output_sha256": output_sha,
            "actual_output_duration": 2.0,
            "placements": [
                {
                    "region_id": "source",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "region_type": "generated",
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                },
                {
                    "region_id": "opaque",
                    "source_start_us": 1_000_000,
                    "source_end_us": 2_000_000,
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                },
            ],
            "omitted_intervals": [],
        }
        with self.assertRaisesRegex(CapabilityUnavailable, "carrier receipt"):
            _validate_renderer_timeline_manifest(
                manifest,
                regions=regions,
                artifacts=(),
                output_sha256=output_sha,
            )

    def test_active_manifest_compares_normalized_route_fields(self):
        output_sha = "a" * 64
        regions = ({
            "region_id": "source",
            "source_start_us": 0,
            "source_end_us": 1_000_000,
            "region_type": "source_ui_keep",
            "media_origin": "source_interval",
            "assembly_policy": "splice_source_interval",
        },)
        manifest = {
            "final_output_sha256": output_sha,
            "actual_output_duration": 1.0,
            "placements": [{
                "region_id": "source",
                "source_start_us": 0,
                "source_end_us": 1_000_000,
                "region_type": "opaque_ui_demo",
                "media_origin": "source_interval",
                "assembly_policy": "splice_source_interval",
            }],
            "omitted_intervals": [],
        }
        with self.assertRaisesRegex(CapabilityUnavailable, "route"):
            _validate_renderer_timeline_manifest(
                manifest,
                regions=regions,
                artifacts=(),
                output_sha256=output_sha,
            )


class _ElasticTimelineContext(_Context):
    """Context whose source interval is longer than the elastic output."""

    def __init__(self, path: Path, manifest_path: Path):
        super().__init__(path)
        self.timeline_regions = (
            {
                "region_id": "short-tail",
                "source_start_us": 0,
                "source_end_us": 1_000_000,
            },
        )
        manifest_bytes = manifest_path.read_bytes()
        self._manifest_path = manifest_path
        self.artifacts = (
            {
                "kind": "assembled_video",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "metadata": {"object_key": "tenant/assembled.mp4"},
            },
            {
                "kind": "hybrid_composite_manifest",
                "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "metadata": {"object_key": "tenant/timeline.json"},
            },
        )

    @contextmanager
    def materialize_artifact(self, kind: str, *, index: int = 0):
        if kind == "assembled_video":
            path = self.path
            content_type = "video/mp4"
        elif kind == "hybrid_composite_manifest":
            path = self._manifest_path
            content_type = "application/json"
        else:
            raise KeyError(kind)
        data = path.read_bytes()
        yield MaterializedMedia(
            path=path,
            job_id="job-test",
            object_key=f"tenant/{path.name}",
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            content_type=content_type,
            metadata={},
        )


class RealMediaPortsTest(unittest.TestCase):
    @staticmethod
    def _weighted_qc_input(
        *,
        score: float = 100.0,
        route_coverage: float = 100.0,
        ui_ocr: float | None = 100.0,
        source_sha256: str = "a" * 64,
        output_sha256: str = "b" * 64,
    ):
        """Build a complete evidence-bearing HF QC input for integration tests."""

        dimensions = {}
        for name in (
            "timeline_route",
            "background_lighting",
            "composition_camera",
            "performance",
            "action_chain",
            "truth",
            "voiceover_audio",
            "overlays",
            "commercial",
            "continuity_technical",
        ):
            evidence_kind = "audio" if name == "voiceover_audio" else "frame"
            dimensions[name] = {
                "score": score,
                "criticality": "H"
                if name in {"performance", "action_chain", "truth", "voiceover_audio"}
                else "M",
                "evidence": [
                    {
                        "evidence_id": f"{name}-e1",
                        "kind": evidence_kind,
                        "method": "deterministic_measurement",
                        "source_ref": {
                            "pointer": f"/source/{name}",
                            "artifact_sha256": source_sha256,
                            "start_ms": 0,
                            "end_ms": 500,
                        },
                        "target_ref": {
                            "pointer": f"/target/{name}",
                            "artifact_sha256": output_sha256,
                            "start_ms": 0,
                            "end_ms": 500,
                        },
                        "observation": f"verified {name}",
                    }
                ],
            }

        factor_scores = {
            "HFH.C01.PERFORMANCE.GAZE": {
                "score": score,
                "criticality": "H",
                "evidence": [
                    {
                        "evidence_id": "factor-gaze-e1",
                        "kind": "frame",
                        "method": "automatic_model_comparison",
                        "source_ref": {
                            "pointer": "/source/performance/gaze",
                            "artifact_sha256": source_sha256,
                            "start_ms": 0,
                            "end_ms": 500,
                        },
                        "target_ref": {
                            "pointer": "/target/performance/gaze",
                            "artifact_sha256": output_sha256,
                            "start_ms": 0,
                            "end_ms": 500,
                        },
                        "observation": "gaze endpoint matches",
                    }
                ],
            }
        }
        return {
            "dimensions": dimensions,
            "route_coverage": route_coverage,
            "ui_ocr": ui_ocr,
            "hard_failures": [],
            "factor_scores": factor_scores,
            "evaluator_receipt": {
                "schema_version": "high-fidelity-qc-evaluator-receipt/v1",
                "provenance": "independent_evaluator",
                "implementation": "tests.evidence-bound-qc",
                "version": "test-v1",
                "model_id": "test-qc-model",
                "model_sha256": "c" * 64,
                "request_sha256": "d" * 64,
                "response_sha256": "e" * 64,
                "dimensions_sha256": _dimensions_digest(dimensions),
                "factor_scores_sha256": _factor_scores_digest(factor_scores),
                "final_output_sha256": output_sha256,
                "current_run_source_sha256s": [source_sha256],
            },
        }

    def _make_source(self, root: Path, *, color: str = "green") -> Path:
        source = root / f"{color}.mp4"
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=160x120:r=10:d=0.5",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            self.skipTest("ffmpeg unavailable")
        return source

    def _make_audio_source(self, root: Path) -> Path:
        source = root / "audio.mp4"
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=green:s=160x120:r=10:d=0.5",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=0.5",
                "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            self.skipTest("ffmpeg unavailable")
        return source

    @staticmethod
    def _final_audio_records(final_sha: str) -> tuple[dict, dict]:
        line = {
            "start_us": 50_000,
            "end_us": 350_000,
            "text": "Buy now",
            "meaning": "buy now",
            "delivery": "light_voice",
            "visible_speaker": False,
        }
        contract = {
            "output_language": "en",
            "exact_line_windows": [line],
            "foley_windows": [],
            "ambience_windows": [],
            "silence_windows": [],
        }
        evidence = {
            "final_output_sha256": final_sha,
            "output_language": "en",
            "exact_line_windows": [{**line, "lip_sync_match_percent": 100}],
            "foley_windows": [],
            "ambience_windows": [],
            "silence_windows": [],
            "unexpected_silence_windows": [],
            "integrated_lufs": -16.0,
            "true_peak_dbfs": -2.0,
            "max_boundary_sample_jump": 0.1,
            "stream_start_offset_us": 0,
            "terminal_drift_us": 0,
        }
        return contract, evidence

    def _production_evaluator(
        self,
        *,
        source_sha: str,
        final_audio_evidence: dict | None = None,
    ):
        test_case = self

        class Evaluator:
            def capability_identity(self):
                return {
                    "implementation": "tests.evidence-bound-qc",
                    "version": "test-v1",
                    "model_id": "test-qc-model",
                    "model_sha256": "c" * 64,
                    "evidence_binding": "usfr-qc-evaluator/v1",
                }

            def evaluate(self, **kwargs):
                qc_input = test_case._weighted_qc_input(
                    source_sha256=source_sha,
                    output_sha256=kwargs["final_output_sha256"],
                )
                if final_audio_evidence is not None:
                    qc_input["final_audio_qc_evidence"] = dict(final_audio_evidence)
                qc_input["evaluator_receipt"].update(
                    {
                        "request_sha256": _canonical_sha256(kwargs["request_payload"]),
                        "current_run_source_sha256s": list(
                            kwargs["current_run_source_sha256s"]
                        ),
                    }
                )
                response_payload = {
                    key: value
                    for key, value in qc_input.items()
                    if key != "evaluator_receipt"
                }
                qc_input["evaluator_receipt"]["response_sha256"] = _canonical_sha256(
                    response_payload
                )
                return {"qc_input": qc_input}

        return Evaluator()

    def test_qc_source_digest_collection_accepts_single_sha256_string(self):
        context = SimpleNamespace(
            input_slots=(
                {
                    "slot_id": "source_video",
                    "present": True,
                    "sha256": "a" * 64,
                },
            ),
            artifacts=(),
        )

        self.assertEqual(
            FfmpegQcEngine._current_run_source_sha256s(context, []),
            {"a" * 64},
        )

    def test_active_profile_requires_evidence_bearing_weighted_qc_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            report = FfmpegQcEngine().run(context=context, input_artifacts=[])
            self.assertFalse(report["passed"])
            self.assertIn(
                "HIGH_FIDELITY_QC_EVIDENCE_MISSING",
                report["qc_report"]["hard_failures"],
            )

    def test_production_qc_requires_injected_evaluator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            manifest = root / "timeline.json"
            manifest.write_text(json.dumps({"duration_us": 500_000}), encoding="utf-8")
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.input_slots = ({"slot_id": "source_video", "present": True, "sha256": [hashlib.sha256(source.read_bytes()).hexdigest()]},)
            context.profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"}
            report = FfmpegQcEngine(production=True, sha256="f" * 64).run(context=context, input_artifacts=[])
            self.assertFalse(report["passed"])
            self.assertIn("HIGH_FIDELITY_QC_EVALUATOR_MISSING", report["qc_report"]["hard_failures"])

    def test_production_qc_rejects_evaluator_without_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            media_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "timeline.json"
            manifest.write_text(json.dumps({"duration_us": 500_000}), encoding="utf-8")
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.input_slots = (({"slot_id": "source_video", "present": True, "sha256": [media_sha]}),)
            context.profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"}

            class Evaluator:
                def capability_identity(self):
                    return {
                        "implementation": "tests.evidence-bound-qc",
                        "version": "test-v1",
                        "model_id": "test-qc-model",
                        "model_sha256": "c" * 64,
                        "evidence_binding": "usfr-qc-evaluator/v1",
                    }

                def evaluate(self, **_kwargs):
                    qc_input = self_test._weighted_qc_input(
                        source_sha256=media_sha,
                        output_sha256=media_sha,
                    )
                    qc_input.pop("evaluator_receipt", None)
                    return {"qc_input": qc_input}

            self_test = self
            report = FfmpegQcEngine(production=True, evaluator=Evaluator(), sha256="f" * 64).run(
                context=context,
                input_artifacts=[],
            )
            self.assertFalse(report["passed"])
            self.assertTrue(any("no evaluator receipt" in failure for failure in report["qc_report"]["hard_failures"]))

    def test_production_qc_recomputes_evaluator_request_and_response_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            media_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "timeline.json"
            manifest.write_text(json.dumps({"duration_us": 500_000}), encoding="utf-8")
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.input_slots = ({"slot_id": "source_video", "present": True, "sha256": [media_sha]},)
            context.profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"}

            class Evaluator:
                def capability_identity(self):
                    return {
                        "implementation": "tests.evidence-bound-qc",
                        "version": "test-v1",
                        "model_id": "test-qc-model",
                        "model_sha256": "c" * 64,
                        "evidence_binding": "usfr-qc-evaluator/v1",
                    }

                def evaluate(self, **kwargs):
                    source_set = list(kwargs["current_run_source_sha256s"])
                    qc_input = self_test._weighted_qc_input(
                        source_sha256=media_sha,
                        output_sha256=media_sha,
                    )
                    qc_input["evaluator_receipt"].update(
                        {
                            "request_sha256": _canonical_sha256(kwargs["request_payload"]),
                            "current_run_source_sha256s": source_set,
                        }
                    )
                    response_payload = {key: value for key, value in qc_input.items() if key != "evaluator_receipt"}
                    qc_input["evaluator_receipt"]["response_sha256"] = _canonical_sha256(response_payload)
                    return {"qc_input": qc_input}

            self_test = self
            report = FfmpegQcEngine(production=True, evaluator=Evaluator(), sha256="f" * 64).run(
                context=context,
                input_artifacts=[],
            )
            self.assertTrue(report["passed"], report["qc_report"])

            class NoReceiptEvaluator(Evaluator):
                def evaluate(self, **kwargs):
                    result = super().evaluate(**kwargs)
                    result["qc_input"].pop("evaluator_receipt", None)
                    return result

            blocked = FfmpegQcEngine(production=True, evaluator=NoReceiptEvaluator(), sha256="f" * 64).run(
                context=context,
                input_artifacts=[],
            )
            self.assertFalse(blocked["passed"])
            self.assertTrue(any("evaluator receipt" in failure for failure in blocked["qc_report"]["hard_failures"]))

    def test_production_qc_binds_source_audio_performance_contract_into_evaluator_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            media_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "timeline.json"
            remux_receipt = {
                "schema_version": "source-audio-performance-remux/v1",
                "source_media_sha256": media_sha,
                "source_audio_sha256": "a" * 64,
                "request_sha256": "b" * 64,
                "final_output_sha256": media_sha,
                "forbidden_operations": ["atempo", "loop", "stretch", "freeze", "black_padding", "audio_padding"],
                "regions": [],
            }
            manifest.write_text(
                json.dumps({"duration_us": 500_000, "source_audio_performance_receipt": remux_receipt}),
                encoding="utf-8",
            )
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.input_slots = ({"slot_id": "source_video", "present": True, "sha256": [media_sha]},)
            context.profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"}
            # This test verifies only the evaluator request boundary.  A
            # synthetic sine fixture cannot satisfy a production loudness
            # target, so opt out of the unrelated technical audio measure.
            context.audio_qc_policy = {"measure": False}
            context.artifacts = (*context.artifacts, {"kind": "performance_line_contract", "sha256": "c" * 64})
            final_audio_contract, final_audio_evidence = self._final_audio_records(media_sha)
            context.final_audio_contract = final_audio_contract
            context.final_audio_qc_evidence = final_audio_evidence
            seen: dict[str, Any] = {}

            class Evaluator:
                def capability_identity(self):
                    return {
                        "implementation": "tests.evidence-bound-qc",
                        "version": "test-v1",
                        "model_id": "test-qc-model",
                        "model_sha256": "c" * 64,
                        "evidence_binding": "usfr-qc-evaluator/v1",
                    }

                def evaluate(self, **kwargs):
                    seen["source_audio_performance"] = kwargs["request_payload"].get("source_audio_performance")
                    qc_input = self_test._weighted_qc_input(source_sha256=media_sha, output_sha256=media_sha)
                    qc_input["source_audio_performance_qc_evidence"] = {
                        "schema_version": "source-audio-performance-qc/v1",
                        "final_output_sha256": media_sha,
                        "source_media_sha256": media_sha,
                        "source_audio_sha256": "a" * 64,
                        "remux_request_sha256": "b" * 64,
                        "performance_line_contract_sha256": "c" * 64,
                        "regions": [],
                        "lip_sync_windows": [],
                        "beat_action_windows": [],
                        "forbidden_operations_detected": [],
                        "stream_start_offset_us": 0,
                        "terminal_drift_us": 0,
                    }
                    qc_input["evaluator_receipt"].update(
                        {
                            "request_sha256": _canonical_sha256(kwargs["request_payload"]),
                            "current_run_source_sha256s": list(kwargs["current_run_source_sha256s"]),
                        }
                    )
                    response_payload = {key: value for key, value in qc_input.items() if key != "evaluator_receipt"}
                    qc_input["evaluator_receipt"]["response_sha256"] = _canonical_sha256(response_payload)
                    return {"qc_input": qc_input}

            self_test = self
            report = FfmpegQcEngine(production=True, evaluator=Evaluator(), sha256="f" * 64).run(
                context=context,
                input_artifacts=[],
            )

            self.assertTrue(report["passed"], report["qc_report"])
            self.assertEqual(seen["source_audio_performance"]["performance_line_contract_sha256"], "c" * 64)
            self.assertEqual(seen["source_audio_performance"]["remux_request_sha256"], "b" * 64)

    def test_source_audio_evaluator_request_requires_one_performance_line_contract(self):
        receipt = {
            "schema_version": "source-audio-performance-remux/v1",
            "source_media_sha256": "a" * 64,
            "source_audio_sha256": "b" * 64,
            "request_sha256": "c" * 64,
            "final_output_sha256": "d" * 64,
            "regions": [],
        }
        context = SimpleNamespace(artifacts=())

        with self.assertRaisesRegex(CapabilityUnavailable, "performance_line_contract"):
            FfmpegQcEngine._source_audio_performance_request(
                context,
                timeline_manifest={"source_audio_performance_receipt": receipt},
                final_output_sha256="d" * 64,
            )

    def test_production_source_audio_delivery_cannot_bypass_independent_evaluator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            media_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            receipt = {
                "schema_version": "source-audio-performance-remux/v1",
                "source_media_sha256": media_sha,
                "source_audio_sha256": "a" * 64,
                "request_sha256": "b" * 64,
                "final_output_sha256": media_sha,
                "forbidden_operations": ["atempo", "loop", "stretch", "freeze", "black_padding", "audio_padding"],
                "regions": [],
            }
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps({"duration_us": 500_000, "source_audio_performance_receipt": receipt}),
                encoding="utf-8",
            )
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.audio_qc_policy = {"measure": False}
            context.source_audio_performance_qc_evidence = {
                "schema_version": "source-audio-performance-qc/v1",
                "final_output_sha256": media_sha,
                "source_media_sha256": media_sha,
                "source_audio_sha256": "a" * 64,
                "remux_request_sha256": "b" * 64,
                "performance_line_contract_sha256": "c" * 64,
                "regions": [],
                "lip_sync_windows": [],
                "beat_action_windows": [],
                "forbidden_operations_detected": [],
                "stream_start_offset_us": 0,
                "terminal_drift_us": 0,
            }

            report = FfmpegQcEngine(production=True, sha256="f" * 64).run(
                context=context,
                input_artifacts=[],
            )

            self.assertFalse(report["passed"])
            self.assertIn(
                "SOURCE_AUDIO_PERFORMANCE_EVALUATOR_REQUEST_INVALID",
                report["qc_report"]["hard_failures"],
            )

    def test_production_qc_blocks_malformed_source_audio_remux_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps({"duration_us": 500_000, "source_audio_performance_receipt": "tampered"}),
                encoding="utf-8",
            )
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.audio_qc_policy = {"measure": False}

            report = FfmpegQcEngine(production=True, sha256="f" * 64).run(
                context=context,
                input_artifacts=[],
            )

            self.assertFalse(report["passed"])
            self.assertIn(
                "SOURCE_AUDIO_PERFORMANCE_EVALUATOR_REQUEST_INVALID",
                report["qc_report"]["hard_failures"],
            )

    def test_production_qc_blocks_evaluator_receipt_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            media_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "timeline.json"
            manifest.write_text(json.dumps({"duration_us": 500_000}), encoding="utf-8")
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.input_slots = ({"slot_id": "source_video", "present": True, "sha256": [media_sha]},)
            context.profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"}

            class Evaluator:
                def capability_identity(self):
                    return {
                        "implementation": "tests.evidence-bound-qc",
                        "version": "test-v1",
                        "model_id": "test-qc-model",
                        "model_sha256": "c" * 64,
                        "evidence_binding": "usfr-qc-evaluator/v1",
                    }

                def evaluate(self, **kwargs):
                    qc_input = self_test._weighted_qc_input(source_sha256=media_sha, output_sha256=media_sha)
                    qc_input["evaluator_receipt"]["request_sha256"] = "0" * 64
                    return {"qc_input": qc_input}

            self_test = self
            report = FfmpegQcEngine(production=True, evaluator=Evaluator(), sha256="f" * 64).run(
                context=context,
                input_artifacts=[],
            )
            self.assertFalse(report["passed"])
            self.assertTrue(any("request SHA" in failure for failure in report["qc_report"]["hard_failures"]))

    def test_active_profile_rejects_qc_evidence_bound_to_stale_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.high_fidelity_qc_input = self._weighted_qc_input(
                source_sha256=source_sha,
                output_sha256="0" * 64,
            )

            report = FfmpegQcEngine().run(context=context, input_artifacts=[])

            self.assertFalse(report["passed"])
            self.assertTrue(
                any(
                    "HIGH_FIDELITY_QC_EVIDENCE_INVALID" in failure
                    and "final output" in failure
                    for failure in report["qc_report"]["hard_failures"]
                ),
                report["qc_report"],
            )

    def test_active_profile_rejects_qc_evidence_from_foreign_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            output_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.high_fidelity_qc_input = self._weighted_qc_input(
                source_sha256="f" * 64,
                output_sha256=output_sha,
            )

            report = FfmpegQcEngine().run(context=context, input_artifacts=[])

            self.assertFalse(report["passed"])
            self.assertTrue(
                any(
                    "HIGH_FIDELITY_QC_EVIDENCE_INVALID" in failure
                    and "current run source" in failure
                    for failure in report["qc_report"]["hard_failures"]
                ),
                report["qc_report"],
            )

    def test_active_profile_publishes_validated_weighted_qc_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            media_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            context.high_fidelity_qc_input = self._weighted_qc_input(
                source_sha256=media_sha,
                output_sha256=media_sha,
            )
            report = FfmpegQcEngine().run(context=context, input_artifacts=[])
            self.assertTrue(report["passed"], report["qc_report"])
            extension = report["high_fidelity_qc_extension"]
            self.assertEqual(extension["schema_version"], "high-fidelity-qc/v1")
            self.assertTrue(extension["accepted"])
            self.assertGreaterEqual(extension["total_score"], 85)
            self.assertEqual(extension["route_coverage"], 100)
            self.assertEqual(extension["ui_ocr"], 100)
            self.assertEqual(report["qc_report"]["high_fidelity_qc_extension"], extension)

    def test_active_profile_blocks_weighted_qc_hard_gate_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            media_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            context.high_fidelity_qc_input = self._weighted_qc_input(
                score=80.0,
                source_sha256=media_sha,
                output_sha256=media_sha,
            )
            report = FfmpegQcEngine().run(context=context, input_artifacts=[])
            self.assertFalse(report["passed"])
            extension = report["high_fidelity_qc_extension"]
            self.assertFalse(extension["accepted"])
            self.assertIn("HIGH_FIDELITY_QC_EXTENSION_REJECTED", report["qc_report"]["hard_failures"])

    def test_legacy_profile_keeps_technical_qc_without_weighted_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            report = FfmpegQcEngine().run(context=context, input_artifacts=[])
            self.assertTrue(report["passed"], report["qc_report"])
            self.assertNotIn("high_fidelity_qc_extension", report)

    def test_active_compositor_blocks_source_speech_crossing_opaque_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.stage_outputs = {
                "analyze_dynamics": {
                    "audio_contract": {
                        "schema_version": "audio-contract/v1",
                        "segments": [
                            {
                                "segment_id": "A001",
                                "start_ms": 150,
                                "end_ms": 350,
                                "text": "protected source speech",
                            }
                        ],
                        "meaningful_silence": [],
                    }
                }
            }
            context.timeline_regions = (
                {
                    "region_id": "generated-live",
                    "region_type": "generated",
                    "media_origin": "generated_media",
                    "source_start_us": 0,
                    "source_end_us": 250_000,
                },
                {
                    "region_id": "opaque-ui",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "audio_policy": "opaque_audio_keep",
                    "source_start_us": 250_000,
                    "source_end_us": 500_000,
                },
            )

            with self.assertRaisesRegex(
                ReplicationError,
                "AUDIO_LAYER_POLICY_REQUIRED",
            ):
                FfmpegCompositor(allow_passthrough=True).compose(
                    context=context,
                    input_artifacts=[],
                )

    def test_bundled_timeline_renderer_completes_evidence_bound_audio_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            opaque = root / "opaque.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=10:d=0.5",
                    "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:d=0.5",
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(opaque),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            context = _Context(source)
            context.allow_local_paths = True
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.audio_contract = {
                "schema_version": "audio-contract/v1",
                "segments": [
                    {"segment_id": "A001", "start_ms": 100, "end_ms": 400}
                ],
            }
            context.timeline_regions = (
                {
                    "region_id": "opaque-ui",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                    "audio_policy": "evidence_bound_mix",
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                    "media_path": str(opaque),
                    "media_sha256": hashlib.sha256(opaque.read_bytes()).hexdigest(),
                },
            )

            renderer = BundledTimelineRenderer()
            rendered = FfmpegCompositor(renderer=renderer).compose(
                context=context,
                input_artifacts=[],
            )

            manifest = rendered["timeline_manifest"]
            receipts = manifest["audio_mixer_receipts"]
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]["region_id"], "opaque-ui")
            self.assertEqual(
                receipts[0]["final_output_sha256"],
                rendered["output_artifact"]["sha256"],
            )
            self.assertEqual(
                manifest["audio_route_guard"]["status"],
                "passed_final_bound_evidence_bound_mix",
            )

            def assert_no_local_paths(value):
                if isinstance(value, dict):
                    self.assertNotIn("media_path", value)
                    for nested in value.values():
                        assert_no_local_paths(nested)
                elif isinstance(value, list):
                    for nested in value:
                        assert_no_local_paths(nested)
                elif isinstance(value, str):
                    self.assertFalse(Path(value).is_absolute(), value)

            assert_no_local_paths(manifest)
            self.assertTrue(
                all("media_path" not in region for region in manifest["regions"])
            )

            from server.audio_mixer import (
                AudioMixerError,
                validate_evidence_bound_mix_receipts,
            )

            mutations = {
                "forged-request": lambda item: item.__setitem__(
                    "request_sha256", "0" * 64
                ),
                "wrong-region": lambda item: item.__setitem__(
                    "region_id", "other-region"
                ),
                "wrong-source-input": lambda item: item.__setitem__(
                    "source_media_sha256", "1" * 64
                ),
                "wrong-opaque-input": lambda item: item.__setitem__(
                    "opaque_media_sha256", "2" * 64
                ),
                "stale-final": lambda item: item.__setitem__(
                    "final_output_sha256", "3" * 64
                ),
                "forged-duck-curve": lambda item: item.__setitem__(
                    "duck_curve", [{"time_us": 0, "gain_db": 0.0}]
                ),
                "stale-mixer-identity": lambda item: item[
                    "capability_identity"
                ].__setitem__("sha256", "4" * 64),
                "worker-local-path-field": lambda item: item.__setitem__(
                    "worker_path", str(root / "receipt-worker.wav")
                ),
            }
            for label, mutate in mutations.items():
                forged = json.loads(json.dumps(receipts))
                mutate(forged[0])
                with self.subTest(label=label), self.assertRaises(AudioMixerError):
                    validate_evidence_bound_mix_receipts(
                        receipts=forged,
                        regions=context.timeline_regions,
                        audio_route_guard=manifest["audio_route_guard"],
                        placements=manifest["placements"],
                        source_media_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                        final_output_sha256=rendered["output_artifact"]["sha256"],
                        expected_mixer_identity=renderer.audio_mixer.capability_identity(),
                    )

    def test_bundled_renderer_remuxes_source_global_audio_without_changing_opaque_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source-performance.mp4"
            g01 = root / "g01.mp4"
            ui = root / "ui.mp4"
            g02 = root / "g02.mp4"
            output = root / "output.mp4"
            for path, color, frequency, duration in (
                (g01, "blue", 111, 1.0),
                (ui, "green", 440, 0.6),
                (g02, "purple", 222, 1.0),
            ):
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"color=c={color}:s=160x120:r=10:d={duration}",
                        "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:d={duration}",
                        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
                    ],
                    capture_output=True,
                )
                if result.returncode != 0:
                    self.skipTest("ffmpeg unavailable")
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=160x120:r=10:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=900:sample_rate=48000:duration=1",
                    "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            source_wav = root / "source-contract.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(source_wav)],
                check=True,
                capture_output=True,
            )
            source_audio_sha = hashlib.sha256(source_wav.read_bytes()).hexdigest()
            context = _Context(source)
            context.allow_local_paths = True
            context.source_media_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            context.source_audio_contracts = {
                "performance_audio_source_contract": {
                    "contract": "performance-audio-source/v1", "mode": "source_audio_replicate_v1",
                    "authorization": {"status": "user_default_authorized", "scope": "current_run_only"},
                    "source_audio_sha256": source_audio_sha, "provider_reference_audio": "forbidden",
                },
                "performance_timeline_contract": {
                    "contract": "performance-timeline/v1",
                    "performance_windows": [
                        {"region_id": "G01", "source_start_ms": 0, "source_end_ms": 1000, "audio_mode": "source_master"},
                        {"region_id": "G02", "source_start_ms": 2000, "source_end_ms": 3000, "audio_mode": "source_master"},
                    ],
                    "opaque_windows": [
                        {"region_id": "U01", "source_start_ms": 1000, "source_end_ms": 2000, "audio_mode": "opaque_audio_keep"},
                    ],
                },
                "audio_splice_policy": {
                    "contract": "audio-splice-policy/v1", "source_audio_sha256": source_audio_sha,
                    "generated_audio": "mute_then_replace_with_exact_source_global_window",
                    "opaque_audio": "keep_original_only",
                    "forbidden_operations": ["atempo", "loop", "stretch", "freeze", "black_padding", "audio_padding", "unsupported_mixing"],
                },
            }
            context.timeline_regions = (
                {"region_id": "G01", "region_type": "generated", "media_origin": "generated_media", "assembly_policy": "generate_region", "source_start_us": 0, "source_end_us": 1_000_000, "media_path": str(g01), "transition_shell": {"exit": {"type": "dissolve", "duration_seconds": 0.1}, "audio": {"policy": "crossfade", "fade_seconds": 0.05}}},
                {"region_id": "U01", "region_type": "opaque_ui_demo", "media_origin": "user_upload", "assembly_policy": "splice_opaque_media", "source_start_us": 1_000_000, "source_end_us": 2_000_000, "media_path": str(ui), "transition_shell": {"entry": {"type": "dissolve", "duration_seconds": 0.1}, "exit": {"type": "dissolve", "duration_seconds": 0.1}, "audio": {"policy": "crossfade", "fade_seconds": 0.05}}},
                {"region_id": "G02", "region_type": "generated", "media_origin": "generated_media", "assembly_policy": "generate_region", "source_start_us": 2_000_000, "source_end_us": 3_000_000, "media_path": str(g02), "transition_shell": {"entry": {"type": "dissolve", "duration_seconds": 0.1}, "audio": {"policy": "crossfade", "fade_seconds": 0.05}}},
            )

            rendered = BundledTimelineRenderer().render(source, output, context)

            receipt = rendered["timeline_manifest"]["source_audio_performance_receipt"]
            self.assertEqual(receipt["regions"][2]["source_start_us"], 2_000_000)
            self.assertEqual(receipt["regions"][1]["opaque_media_sha256"], hashlib.sha256(ui.read_bytes()).hexdigest())
            self.assertEqual(rendered["timeline_manifest"]["final_output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            g02_wav = root / "g02.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.7", "-t", "0.4", "-i", str(output), "-vn", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(g02_wav)],
                check=True,
                capture_output=True,
            )
            with wave.open(str(g02_wav), "rb") as handle:
                samples = array("h", handle.readframes(handle.getnframes()))

            def amplitude(frequency: int) -> float:
                real = sum(value * math.cos(2 * math.pi * frequency * index / 48_000) for index, value in enumerate(samples))
                imaginary = sum(value * math.sin(2 * math.pi * frequency * index / 48_000) for index, value in enumerate(samples))
                return math.hypot(real, imaginary) / len(samples)

            self.assertGreater(amplitude(900), amplitude(300) * 8)

    def test_prebound_and_deferred_receipts_merge_one_to_one(self):
        from server.real_capabilities import _merge_audio_mixer_receipts

        prebound = {"region_id": "prebound", "request_sha256": "a" * 64}
        deferred = {"region_id": "deferred", "request_sha256": "b" * 64}
        audio_regions = [
            {
                "region_id": "prebound",
                "audio_policy": "evidence_bound_mix",
                "mixer_receipt_status": "verified_prebound_receipt",
            },
            {
                "region_id": "deferred",
                "audio_policy": "evidence_bound_mix",
                "mixer_receipt_status": "pending_renderer_receipt",
            },
        ]
        regions = [
            {
                "region_id": "prebound",
                "audio_policy": "evidence_bound_mix",
                "mixer_receipt": prebound,
            },
            {"region_id": "deferred", "audio_policy": "evidence_bound_mix"},
        ]

        merged = _merge_audio_mixer_receipts(
            audio_regions=audio_regions,
            regions=regions,
            renderer_receipts=[deferred],
        )

        self.assertEqual(merged, [prebound, deferred])

    def test_public_manifest_sanitizer_preserves_routes_and_object_uris(self):
        from server.real_capabilities import (
            _public_manifest_artifact_descriptor,
            _sanitize_public_timeline_manifest,
        )

        sanitized = _sanitize_public_timeline_manifest(
            {
                "app_route": "/checkout",
                "asset_uri": "s3://tenant-bucket/runs/final.mp4",
                "object_uri": "object://tenant/final-manifest",
                "output_path": "assembled_video",
                "media_path": r"C:\worker\temporary\opaque.mp4",
            }
        )

        self.assertEqual(sanitized["app_route"], "/checkout")
        self.assertEqual(
            sanitized["asset_uri"],
            "s3://tenant-bucket/runs/final.mp4",
        )
        self.assertEqual(
            sanitized["object_uri"],
            "object://tenant/final-manifest",
        )
        self.assertEqual(sanitized["output_path"], "assembled_video")
        self.assertNotIn("media_path", sanitized)

        for worker_path in (
            r"C:\Users\worker\AppData\Local\Temp\mix.wav",
            "/tmp/usfr-worker/mix.wav",
        ):
            with self.subTest(worker_path=worker_path), self.assertRaises(
                CapabilityUnavailable
            ):
                _sanitize_public_timeline_manifest(
                    {"worker_path": worker_path}
                )
        descriptor = _public_manifest_artifact_descriptor(
            {
                "kind": "assembled_video",
                "sha256": "a" * 64,
                "uri": "file:///tmp/usfr-worker/output.mp4",
            },
            default_kind="assembled_video",
            expected_sha256="a" * 64,
        )
        self.assertNotIn("uri", descriptor)

    def test_manifest_rejection_happens_before_any_publisher_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            calls: list[str] = []

            def publisher(*, kind, stream, content_type, expected_sha256, metadata=None):
                calls.append(kind)
                data = stream.read()
                return {
                    "kind": kind,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "uri": f"s3://tenant/{kind}",
                }

            def renderer(source_path: Path, output_path: Path, _context):
                output_path.write_bytes(source_path.read_bytes())
                return {
                    "output_path": output_path,
                    "timeline_manifest": {
                        "worker_path": str(root / "worker-private.json")
                    },
                }

            context.publish_artifact = publisher
            with self.assertRaisesRegex(
                CapabilityUnavailable,
                "worker-local",
            ):
                FfmpegCompositor(renderer=renderer).compose(
                    context=context,
                    input_artifacts=[],
                )

            self.assertEqual(calls, [])

    def test_boolean_only_renderer_cannot_defer_evidence_mix_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_audio_source(Path(tmp))
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.audio_contract = {
                "schema_version": "audio-contract/v1",
                "segments": [
                    {"segment_id": "A001", "start_ms": 100, "end_ms": 400}
                ],
            }
            context.timeline_regions = (
                {
                    "region_id": "opaque-ui",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "audio_policy": "evidence_bound_mix",
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                },
            )

            class BooleanOnlyRenderer:
                supports_evidence_bound_mix = True

                def __call__(self, *_args, **_kwargs):
                    raise AssertionError("untrusted renderer must not run")

            with self.assertRaisesRegex(ReplicationError, "requires a mixer receipt"):
                FfmpegCompositor(renderer=BooleanOnlyRenderer()).compose(
                    context=context,
                    input_artifacts=[],
                )

    def test_production_compositor_rejects_missing_source_sha_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_audio_source(Path(tmp))

            class MissingShaContext(_Context):
                @contextmanager
                def materialize_slot(self, slot_id: str, *, index: int = 0):
                    yield SimpleNamespace(path=self.path)

            context = MissingShaContext(source)
            with self.assertRaisesRegex(
                CapabilityUnavailable,
                "immutable source media SHA-256",
            ):
                FfmpegCompositor(
                    renderer=BundledTimelineRenderer(
                        production=True,
                        sha256="a" * 64,
                    ),
                    production=True,
                    sha256="b" * 64,
                ).compose(context=context, input_artifacts=[])

    def test_legacy_bundled_renderer_does_not_remix_preexisting_evidence_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            context = _Context(source)
            context.allow_local_paths = True
            context.audio_contract = {
                "schema_version": "audio-contract/v1",
                "segments": [
                    {"segment_id": "A001", "start_ms": 100, "end_ms": 400}
                ],
            }
            context.timeline_regions = (
                {
                    "region_id": "legacy-mixed-ui",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                    "audio_policy": "evidence_bound_mix",
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                    "media_path": str(source),
                    "media_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
            )

            rendered = FfmpegCompositor(
                renderer=BundledTimelineRenderer(),
            ).compose(context=context, input_artifacts=[])

            self.assertEqual(rendered["status"], "ready")
            self.assertNotIn("audio_mixer_receipts", rendered["timeline_manifest"])

    def test_active_replacement_route_requires_canonical_audio_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.timeline_regions = ({
                "region_id": "opaque-ui",
                "region_type": "opaque_ui_demo",
                "media_origin": "user_upload",
                "source_start_us": 0,
                "source_end_us": 500_000,
            },)

            with self.assertRaisesRegex(ReplicationError, "AUDIO_CONTRACT_REQUIRED"):
                FfmpegCompositor(allow_passthrough=True).compose(
                    context=context,
                    input_artifacts=[],
                )

    def test_generated_ui_speech_overlap_requires_audio_layer_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.stage_outputs = {
                "analyze_dynamics": {
                    "audio_contract": {
                        "segments": [{
                            "segment_id": "A001",
                            "start_ms": 100,
                            "end_ms": 400,
                            "text": "speech crosses generated UI",
                        }],
                        "silence_windows": [],
                    }
                }
            }
            context.timeline_regions = ({
                "region_id": "generated-ui",
                "region_type": "generated_ui_demo",
                "media_origin": "generated_media",
                "source_start_us": 0,
                "source_end_us": 500_000,
            },)

            with self.assertRaisesRegex(
                ReplicationError,
                "AUDIO_LAYER_POLICY_REQUIRED",
            ):
                FfmpegCompositor(allow_passthrough=True).compose(
                    context=context,
                    input_artifacts=[],
                )

    def test_active_compositor_allows_speech_ending_at_opaque_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.stage_outputs = {
                "analyze_dynamics": {
                    "audio_contract": {
                        "schema_version": "audio-contract/v1",
                        "segments": [
                            {
                                "segment_id": "A001",
                                "start_ms": 50,
                                "end_ms": 250,
                                "text": "speech ends before replacement audio",
                            }
                        ],
                        "meaningful_silence": [],
                    }
                }
            }
            context.timeline_regions = (
                {
                    "region_id": "generated-live",
                    "region_type": "generated",
                    "media_origin": "generated_media",
                    "source_start_us": 0,
                    "source_end_us": 250_000,
                },
                {
                    "region_id": "opaque-ui",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "audio_policy": "opaque_audio_keep",
                    "source_start_us": 250_000,
                    "source_end_us": 500_000,
                },
            )

            result = FfmpegCompositor(allow_passthrough=True).compose(
                context=context,
                input_artifacts=[],
            )

            self.assertEqual(
                result["timeline_manifest"]["audio_route_guard"]["status"],
                "passed_no_unsupported_crossing",
            )
            self.assertEqual(
                result["timeline_manifest"]["audio_route_guard"]["crossing_count"],
                0,
            )

    def test_legacy_compositor_keeps_opaque_audio_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.stage_outputs = {
                "analyze_dynamics": {
                    "audio_contract": {
                        "schema_version": "audio-contract/v1",
                        "segments": [
                            {
                                "segment_id": "A001",
                                "start_ms": 150,
                                "end_ms": 350,
                                "text": "legacy source speech",
                            }
                        ],
                        "meaningful_silence": [],
                    }
                }
            }
            context.timeline_regions = (
                {
                    "region_id": "generated-live",
                    "region_type": "generated",
                    "media_origin": "generated_media",
                    "source_start_us": 0,
                    "source_end_us": 250_000,
                },
                {
                    "region_id": "opaque-ui",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "source_start_us": 250_000,
                    "source_end_us": 500_000,
                },
            )

            result = FfmpegCompositor(allow_passthrough=True).compose(
                context=context,
                input_artifacts=[],
            )

            self.assertNotIn("audio_route_guard", result["timeline_manifest"])

    def test_explicit_audio_layer_blocker_applies_before_active_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.audio_contract = {
                "contract": "audio-contract",
                "contract_version": 1,
                "status": "BLOCKED_AUDIO_LAYER_DECISION",
                "source_voiceover_crosses_opaque_ui": True,
                "events": [],
            }
            context.timeline_regions = (
                {
                    "region_id": "opaque-ui",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                },
            )

            with self.assertRaisesRegex(
                ReplicationError,
                "AUDIO_LAYER_POLICY_REQUIRED",
            ):
                FfmpegCompositor(allow_passthrough=True).compose(
                    context=context,
                    input_artifacts=[],
                )

    def test_explicit_audio_layer_blocker_is_not_hidden_when_regions_are_missing(self):
        """An upstream blocked routing decision must remain fail-closed even if
        a malformed/partial timeline omitted its opaque-region rows."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.audio_contract = {
                "contract": "audio-contract",
                "contract_version": 1,
                "status": "BLOCKED_AUDIO_LAYER_DECISION",
                "source_voiceover_crosses_opaque_ui": True,
                "events": [],
            }
            context.timeline_regions = ()

            with self.assertRaisesRegex(
                ReplicationError,
                "AUDIO_LAYER_POLICY_REQUIRED",
            ):
                FfmpegCompositor(allow_passthrough=True).compose(
                    context=context,
                    input_artifacts=[],
                )

    def test_ffmpeg_compositor_publishes_real_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=green:s=160x120:r=10:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            context = _Context(source)
            output = FfmpegCompositor(allow_passthrough=True).compose(context=context, input_artifacts=[])
            self.assertEqual(output["status"], "ready")
            self.assertEqual(output["output_artifact"]["kind"], "assembled_video")
            self.assertGreater(output["timeline_manifest"]["duration_us"], 0)
            self.assertEqual(
                output["timeline_manifest"]["output_duration_authority"],
                "actual_composited_media",
            )

    def test_silent_source_does_not_strip_generated_dialogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            generated = root / "generated-with-dialogue.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=10:d=0.5",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=0.5",
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(generated),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            context = _Context(source)
            context.allow_local_paths = True
            context.exact_line_contract = {
                "lines": [{
                    "line_id": "L01",
                    "speaker": "creator",
                    "text": "generated dialogue",
                    "start_ms": 0,
                    "end_ms": 400,
                }]
            }
            context.timeline_regions = ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated_media",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 500_000,
                "media_path": str(generated),
            },)
            compositor = FfmpegCompositor(
                renderer=BundledTimelineRenderer(
                    production=False,
                    sha256="a" * 64,
                )
            )

            compositor.compose(context=context, input_artifacts=[])
            output_path = context.work_dir / "composited.mp4"
            audio_probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "a",
                    "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(audio_probe.returncode, 0, audio_probe.stderr)
            self.assertIn("audio", audio_probe.stdout)

    def test_compositor_preserves_renderer_output_clock_and_audio_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            context = _Context(source)
            context.timeline_regions = ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated_media",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 500_000,
            },)

            def renderer(source_path: Path, output_path: Path, _context):
                output_path.write_bytes(source_path.read_bytes())
                return {
                    "output_path": output_path,
                    "timeline_manifest": {
                        "contract": "universal-timeline-regions",
                        "contract_version": 2,
                        "actual_output_duration": 0.5,
                        "final_output_sha256": source_sha,
                        "placements": [{
                            "region_id": "R01",
                            "region_type": "generated",
                            "output_start": 0.0,
                            "output_end": 0.5,
                        }],
                        "transition_renders": [{
                            "offset": 0.25,
                            "rendered": True,
                            "final_output_sha256": source_sha,
                        }],
                        "audio_lineage": [{
                            "bus": "dialogue",
                            "output_start": 0.0,
                            "output_end": 0.5,
                            "source_sha256": "c" * 64,
                        }],
                    },
                }

            output = FfmpegCompositor(renderer=renderer).compose(
                context=context,
                input_artifacts=[],
            )
            manifest = output["timeline_manifest"]

            self.assertEqual(manifest["placements"][0]["region_id"], "R01")
            self.assertEqual(manifest["transition_renders"][0]["offset"], 0.25)
            self.assertEqual(manifest["audio_lineage"][0]["bus"], "dialogue")
            self.assertEqual(manifest["final_output_sha256"], source_sha)

    def test_ffmpeg_compositor_carries_embedded_overlay_contract_into_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            overlay = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 500_000,
                "cuts": [],
            }
            context.timeline_regions = ({
                "region_id": "R01",
                "source_start_us": 0,
                "source_end_us": 500_000,
                "source_overlay_contract": overlay,
            },)
            output = FfmpegCompositor(allow_passthrough=True).compose(context=context, input_artifacts=[])
            self.assertEqual(output["timeline_manifest"]["source_overlay_contract"], overlay)
            self.assertEqual(
                output["timeline_manifest"]["source_overlay_contract_sha256"],
                hashlib.sha256(json.dumps(overlay, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            )

    def test_active_compositor_rejects_copy_only_renderer_for_semantic_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"}
            overlay = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 500_000,
                "cuts": [{
                    "cut": 1,
                    "start_us": 0,
                    "end_us": 500_000,
                    "source_overlays": [{"overlay_id": "cta-1", "start_us": 0, "end_us": 500_000}],
                }],
            }
            overlay_sha = hashlib.sha256(json.dumps(overlay, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": overlay_sha,
                "regions": [{
                    "region_id": "R01",
                    "overlays": [{
                        "overlay_id": "cta-1",
                        "validated": True,
                        "render_mode": "deterministic_text",
                        "payload": {
                            "text": "Target CTA",
                            "color": "white",
                            "font_size": 20,
                        },
                        "payload_sha256": hashlib.sha256(
                            json.dumps(
                                {"text": "Target CTA", "color": "white", "font_size": 20},
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest(),
                    }],
                }],
            }
            context.timeline_regions = ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 500_000,
                "source_overlay_contract": overlay,
                "overlay_render_mapping": mapping,
            },)

            def copy_only(source_path: Path, output_path: Path, _context):
                output_path.write_bytes(source_path.read_bytes())
                return output_path

            with self.assertRaisesRegex(ReplicationError, "OVERLAY_RENDER_RECEIPT_REQUIRED"):
                FfmpegCompositor(renderer=copy_only).compose(context=context, input_artifacts=[])

    def test_production_compositor_does_not_use_overlay_renderer_as_generated_timeline_renderer(self):
        """A semantic overlay must not make source pixels masquerade as generated output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            overlay = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 500_000,
                "cuts": [{
                    "cut": 1,
                    "start_us": 0,
                    "end_us": 500_000,
                    "source_overlays": [{
                        "overlay_id": "cta-1",
                        "start_us": 0,
                        "end_us": 500_000,
                        "start_rect": [0.1, 0.1, 0.4, 0.1],
                        "end_rect": [0.1, 0.1, 0.4, 0.1],
                        "start_rotation_deg": 0,
                        "end_rotation_deg": 0,
                        "start_opacity": 1,
                        "end_opacity": 1,
                    }],
                }],
            }
            overlay_sha = hashlib.sha256(
                json.dumps(overlay, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": overlay_sha,
                "regions": [{
                    "region_id": "R01",
                    "overlays": [{
                        "overlay_id": "cta-1",
                        "validated": True,
                        "render_mode": "deterministic_text",
                        "payload": {
                            "text": "Target CTA",
                            "color": "white",
                            "font_size": 20,
                        },
                        "payload_sha256": hashlib.sha256(
                            json.dumps(
                                {"text": "Target CTA", "color": "white", "font_size": 20},
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest(),
                    }],
                }],
            }
            context.timeline_regions = ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 500_000,
                "source_overlay_contract": overlay,
                "overlay_render_mapping": mapping,
            },)

            with self.assertRaisesRegex(CapabilityUnavailable, "timeline renderer is not configured"):
                FfmpegCompositor(production=True, sha256="b" * 64).compose(
                    context=context,
                    input_artifacts=[],
                )

    def test_production_compositor_rejects_explicit_overlay_renderer_for_non_source_timeline(self):
        """An injected semantic overlay renderer cannot stand in for timeline assembly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.timeline_regions = ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated_media",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 500_000,
            },)

            class OverlayOnlyRenderer:
                capability_kind = "overlay_renderer"

                def capability_identity(self):
                    return {
                        "implementation": "server.overlay_renderer:DeterministicOverlayRenderer",
                        "version": "test",
                        "sha256": "c" * 64,
                    }

                def __call__(self, source_path: Path, output_path: Path, _context):
                    output_path.write_bytes(source_path.read_bytes())
                    return output_path

            with self.assertRaisesRegex(CapabilityUnavailable, "timeline renderer is not configured"):
                FfmpegCompositor(
                    renderer=OverlayOnlyRenderer(),
                    production=True,
                    sha256="b" * 64,
                ).compose(context=context, input_artifacts=[])

    def test_active_compositor_accepts_receipt_bound_overlay_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"}
            overlay = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 500_000,
                "cuts": [{"cut": 1, "start_us": 0, "end_us": 500_000, "source_overlays": [{"overlay_id": "cta-1", "start_us": 0, "end_us": 500_000}]}],
            }
            overlay_sha = hashlib.sha256(json.dumps(overlay, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": overlay_sha,
                "regions": [{"region_id": "R01", "overlays": [{"overlay_id": "cta-1", "validated": True, "render_mode": "deterministic_text", "text": "Target CTA", "payload_sha256": "a" * 64}]}],
            }
            mapping_sha = hashlib.sha256(json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            context.timeline_regions = ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 500_000,
                "source_overlay_contract": overlay,
                "overlay_render_mapping": mapping,
            },)

            def receipt_renderer(source_path: Path, output_path: Path, _context):
                data = source_path.read_bytes()
                output_path.write_bytes(data)
                output_sha = hashlib.sha256(data).hexdigest()
                return {
                    "output_path": output_path,
                    "overlay_render_receipts": [{
                        "region_id": "R01",
                        "overlay_id": "cta-1",
                        "source_overlay_contract_sha256": overlay_sha,
                        "overlay_render_mapping_sha256": mapping_sha,
                        "payload_sha256": "a" * 64,
                        "output_sha256": output_sha,
                        "frame_windows": [{"start_us": 0, "end_us": 500_000}],
                    }],
                }

            output = FfmpegCompositor(renderer=receipt_renderer).compose(context=context, input_artifacts=[])
            self.assertEqual(len(output["overlay_render_receipts"]), 1)
            self.assertEqual(output["timeline_manifest"]["overlay_render_receipts"][0]["overlay_id"], "cta-1")

    def test_readable_overlay_receipt_requires_final_ocr_layout_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            overlay = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 500_000,
                "cuts": [{
                    "cut": 1,
                    "start_us": 0,
                    "end_us": 500_000,
                    "source_overlays": [{
                        "overlay_id": "cta-1",
                        "start_us": 0,
                        "end_us": 500_000,
                    }],
                }],
            }
            overlay_sha = hashlib.sha256(
                json.dumps(overlay, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            payload = {
                "text": "立即下载",
                "output_language": "zh",
                "font_sha256": "f" * 64,
                "glyph_coverage_sha256": "e" * 64,
                "verification_required": True,
            }
            payload_sha = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": overlay_sha,
                "regions": [{
                    "region_id": "R01",
                    "overlays": [{
                        "overlay_id": "cta-1",
                        "validated": True,
                        "render_mode": "deterministic_text",
                        "payload": payload,
                        "payload_sha256": payload_sha,
                    }],
                }],
            }
            mapping_sha = hashlib.sha256(
                json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            context.timeline_regions = ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 500_000,
                "source_overlay_contract": overlay,
                "overlay_render_mapping": mapping,
            },)

            def incomplete_renderer(source_path: Path, output_path: Path, _context):
                data = source_path.read_bytes()
                output_path.write_bytes(data)
                output_sha = hashlib.sha256(data).hexdigest()
                return {
                    "output_path": output_path,
                    "overlay_render_receipts": [{
                        "region_id": "R01",
                        "overlay_id": "cta-1",
                        "source_overlay_contract_sha256": overlay_sha,
                        "overlay_render_mapping_sha256": mapping_sha,
                        "payload_sha256": payload_sha,
                        "output_sha256": output_sha,
                        "final_output_sha256": output_sha,
                        "frame_windows": [{"start_us": 0, "end_us": 500_000}],
                    }],
                }

            with self.assertRaisesRegex(
                ReplicationError,
                "OVERLAY_RENDER_RECEIPT_REQUIRED",
            ):
                FfmpegCompositor(renderer=incomplete_renderer).compose(
                    context=context,
                    input_artifacts=[],
                )

    def test_active_overlay_receipts_flow_through_timeline_loader_manifest_and_qc(self):
        """Exercise the positive active-profile bridge end to end.

        The renderer may be deployment-owned, but its receipt contract must
        survive compositor publication, timeline contract loading, and final
        QC.  This deliberately uses a deterministic source-sized output so
        the test proves contract/evidence propagation without depending on a
        provider video backend.
        """

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            media_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            context.high_fidelity_qc_input = self._weighted_qc_input(
                source_sha256=media_sha,
                output_sha256=media_sha,
            )
            rect = {"x": 0.05, "y": 0.02, "width": 0.9, "height": 0.08}
            overlay = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 500_000,
                "source_width": 160,
                "source_height": 120,
                "coordinate_space": "rotation_corrected_source_visible_frame_normalized",
                "target_mapping": "source_normalized_composition_to_target_frame",
                "attachment": "screen_space",
                "time_range_semantics": "start_inclusive_end_exclusive",
                "cuts": [
                    {
                        "cut": 1,
                        "start_us": 0,
                        "end_us": 500_000,
                        "source_overlays": [
                            {
                                "overlay_id": "cta-1",
                                "kind": "cta_text",
                                "start_us": 0,
                                "end_us": 500_000,
                                "start_rect": rect,
                                "end_rect": rect,
                                "start_rotation_deg": 0,
                                "end_rotation_deg": 0,
                                "start_opacity": 1,
                                "end_opacity": 1,
                                "motion_phase": "static",
                                "motion_path": "screen-space hold",
                                "z_index": 20,
                                "layer_relation": "above generated subject",
                                "interpolation": "hold",
                                "observed_text": "Source CTA",
                                "keyframes": [
                                    {"time_us": 0, "bbox": rect, "rotation_deg": 0, "opacity": 1},
                                    {"time_us": 500_000, "bbox": rect, "rotation_deg": 0, "opacity": 1},
                                ],
                            }
                        ],
                    }
                ],
            }
            overlay_sha = hashlib.sha256(
                json.dumps(overlay, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": overlay_sha,
                "regions": [
                    {
                        "region_id": "R01",
                        "overlays": [
                            {
                                "overlay_id": "cta-1",
                                "validated": True,
                                "render_mode": "deterministic_text",
                                "text": "Target CTA",
                                "payload_sha256": "a" * 64,
                            }
                        ],
                    }
                ],
            }
            mapping_sha = hashlib.sha256(
                json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            context.timeline_regions = (
                {
                    "region_id": "R01",
                    "region_type": "generated",
                    "media_origin": "generated",
                    "assembly_policy": "generate_region",
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                    "source_overlay_contract": overlay,
                    "overlay_render_mapping": mapping,
                },
            )

            def receipt_renderer(source_path: Path, output_path: Path, _context):
                data = source_path.read_bytes()
                output_path.write_bytes(data)
                return {
                    "output_path": output_path,
                    "overlay_render_receipts": [
                        {
                            "region_id": "R01",
                            "overlay_id": "cta-1",
                            "source_overlay_contract_sha256": overlay_sha,
                            "overlay_render_mapping_sha256": mapping_sha,
                            "payload_sha256": "a" * 64,
                            "output_sha256": hashlib.sha256(data).hexdigest(),
                            "frame_windows": [{"start_us": 0, "end_us": 500_000}],
                        }
                    ],
                }

            composed = FfmpegCompositor(renderer=receipt_renderer).compose(
                context=context,
                input_artifacts=[],
            )
            manifest = dict(composed["timeline_manifest"])
            self.assertTrue(manifest["overlay_render_receipts_required"])
            self.assertEqual(len(manifest["overlay_render_receipts"]), 1)
            self.assertEqual(composed["manifest_artifact"]["kind"], "hybrid_composite_manifest")

            # timeline_splice consumes the same immutable contract/evidence,
            # with only the schema's target/source clock and media path added.
            timeline_payload = dict(manifest)
            timeline_payload.update(
                {
                    "source_duration_us": 500_000,
                    "source_fps": 10,
                    "target": {"width": 160, "height": 120, "fps": 10},
                    "regions": [
                        {
                            **dict(manifest["regions"][0]),
                            "media_path": str(source),
                            "media_origin": "generated_media",
                        }
                    ],
                }
            )
            timeline_path = root / "timeline.json"
            timeline_path.write_text(
                json.dumps(timeline_payload, ensure_ascii=False),
                encoding="utf-8",
            )
            loaded = load_contract(timeline_path)
            self.assertEqual(loaded.source_overlay_contract_sha256, overlay_sha)
            self.assertEqual(loaded.overlay_render_mapping_sha256, mapping_sha)

            context.timeline_manifest = manifest
            qc = FfmpegQcEngine().run(context=context, input_artifacts=[])
            self.assertTrue(qc["passed"], qc["qc_report"])
            self.assertTrue(qc["qc_report"]["checks"]["overlay_render_receipts"])
            self.assertTrue(qc["qc_report"]["high_fidelity_qc_extension"]["accepted"])

    def test_qc_engine_blocks_black_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=160x120:r=10:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            report = FfmpegQcEngine().run(context=_Context(source), input_artifacts=[])
            self.assertFalse(report["passed"])
            self.assertIn("BLACK_FRAME_DETECTED", report["qc_report"]["hard_failures"])

    def test_source_audio_performance_qc_blocks_delivery_without_evaluator_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            final_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            context = _Context(source)
            context.timeline_manifest = {
                "source_audio_performance_receipt": {
                    "schema_version": "source-audio-performance-remux/v1",
                    "source_media_sha256": final_sha,
                    "source_audio_sha256": "a" * 64,
                    "request_sha256": "b" * 64,
                    "final_output_sha256": final_sha,
                    "forbidden_operations": ["atempo", "loop", "stretch", "freeze", "black_padding", "audio_padding"],
                    "regions": [],
                }
            }

            report = FfmpegQcEngine().run(context=context, input_artifacts=[])

            self.assertFalse(report["passed"])
            self.assertIn(
                "SOURCE_AUDIO_PERFORMANCE_QC_EVIDENCE_MISSING",
                report["qc_report"]["hard_failures"],
            )

    def test_source_audio_performance_qc_accepts_evidence_bound_to_final_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            final_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            receipt = {
                "schema_version": "source-audio-performance-remux/v1",
                "source_media_sha256": final_sha,
                "source_audio_sha256": "a" * 64,
                "request_sha256": "b" * 64,
                "final_output_sha256": final_sha,
                "forbidden_operations": ["atempo", "loop", "stretch", "freeze", "black_padding", "audio_padding"],
                "regions": [],
            }
            context = _Context(source)
            context.timeline_manifest = {"source_audio_performance_receipt": receipt}
            context.source_audio_performance_qc_evidence = {
                "schema_version": "source-audio-performance-qc/v1",
                "final_output_sha256": final_sha,
                "source_media_sha256": final_sha,
                "source_audio_sha256": "a" * 64,
                "remux_request_sha256": "b" * 64,
                "performance_line_contract_sha256": "c" * 64,
                "regions": [],
                "lip_sync_windows": [],
                "beat_action_windows": [],
                "forbidden_operations_detected": [],
                "stream_start_offset_us": 0,
                "terminal_drift_us": 0,
            }

            report = FfmpegQcEngine().run(context=context, input_artifacts=[])

            self.assertTrue(report["passed"], report["qc_report"])
            self.assertEqual(
                report["qc_report"]["metrics"]["source_audio_performance_qc"]["status"],
                "passed",
            )

    def test_qc_engine_keeps_sparse_black_background_logo_active(self):
        """A black card with a small persistent logo is not a black frame."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sparse-logo-card.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                    "-vf", "drawbox=x=(iw-20)/2:y=(ih-20)/2:w=20:h=20:color=white:t=fill",
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            report = FfmpegQcEngine().run(context=_Context(source), input_artifacts=[])
            self.assertTrue(report["passed"], report["qc_report"])
            self.assertNotIn("BLACK_FRAME_DETECTED", report["qc_report"]["hard_failures"])

    def test_qc_engine_allows_declared_internal_black_content(self):
        """Only boundary black frames are blockers; an internal black shot is content."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "internal-black-shot.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=red:s=160x120:r=30:d=1",
                    "-f", "lavfi", "-i", "color=c=black:s=160x120:r=30:d=1",
                    "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=30:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
                    "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                    "-map", "[v]", "-map", "3:a", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            context = _Context(source)
            context.timeline_regions = (
                {"source_start_us": 0, "source_end_us": 3_000_000},
            )
            context.timeline_manifest = {
                "duration_us": 3_000_000,
                "placements": [{"output_start": 0.0, "output_end": 3.0}],
                "transition_renders": [],
            }
            report = FfmpegQcEngine().run(context=context, input_artifacts=[])
            self.assertTrue(report["passed"], report["qc_report"])
            self.assertNotIn("BLACK_FRAME_DETECTED", report["qc_report"]["hard_failures"])
            context.timeline_manifest["transition_renders"] = [
                {"offset": 1.0, "duration": 0.0}
            ]
            boundary_report = FfmpegQcEngine().run(
                context=context,
                input_artifacts=[],
            )
            self.assertFalse(boundary_report["passed"])
            self.assertIn(
                "BLACK_FRAME_DETECTED",
                boundary_report["qc_report"]["hard_failures"],
            )
            context.timeline_manifest = {
                "duration_us": 3_000_000,
                "regions": [{"source_start_us": 0}, {"source_start_us": 1_000_000}],
                "transition_renders": [],
            }
            missing_boundary_report = FfmpegQcEngine().run(
                context=context,
                input_artifacts=[],
            )
            self.assertFalse(missing_boundary_report["passed"])
            self.assertIn(
                "BLACK_FRAME_DETECTED",
                missing_boundary_report["qc_report"]["hard_failures"],
            )

    def test_qc_uses_compositor_manifest_for_elastic_output_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=green:s=160x120:r=10:d=0.8",
                    "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.8",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "timeline-splice-manifest/v1",
                        "duration_us": 800_000,
                        "regions": [{"source_start_us": 0, "source_end_us": 1_000_000}],
                        "source_duration_authority": "actual_composited_media",
                    }
                ),
                encoding="utf-8",
            )
            report = FfmpegQcEngine().run(
                context=_ElasticTimelineContext(source, manifest),
                input_artifacts=[],
            )
            self.assertTrue(report["passed"], report["qc_report"])
            self.assertTrue(report["qc_report"]["checks"]["route_timeline_coverage"])

    def test_qc_blocks_a_single_black_frame_at_30_fps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "single-black-frame.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i",
                    "color=c=green:s=160x120:r=30:d=0.5",
                    "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='eq(n,5)'",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            report = FfmpegQcEngine().run(context=_Context(source), input_artifacts=[])
            self.assertFalse(report["passed"], report["qc_report"])
            self.assertIn("BLACK_FRAME_DETECTED", report["qc_report"]["hard_failures"])

    def test_qc_blocks_a_repeated_frozen_tail_without_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "frozen-tail.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=0.6",
                    "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=30:d=1.2",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.8",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                    "-map", "[v]", "-map", "2:a", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            context = _Context(source)
            context.timeline_manifest = {
                "duration_us": 1_800_000,
                "placements": [
                    {
                        "region_type": "generated",
                        "media_origin": "generated_media",
                        "output_start": 0.0,
                        "output_end": 1.8,
                    }
                ],
                "transition_renders": [],
            }
            report = FfmpegQcEngine().run(context=context, input_artifacts=[])
            self.assertFalse(report["passed"], report["qc_report"])
            self.assertIn(
                "TRAILING_FREEZE_DETECTED",
                report["qc_report"]["hard_failures"],
            )

    def test_qc_blocks_large_audio_video_start_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "offset-audio.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=green:s=160x120:r=30:d=1.0",
                    "-itsoffset", "0.18", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:d=0.82",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            report = FfmpegQcEngine().run(context=_Context(source), input_artifacts=[])
            self.assertFalse(report["passed"], report["qc_report"])
            self.assertIn(
                "AUDIO_VIDEO_START_OFFSET",
                report["qc_report"]["hard_failures"],
            )

    def test_qc_measures_loudness_and_true_peak_and_blocks_out_of_range_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "quiet-audio.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=green:s=160x120:r=30:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                    "-filter_complex", "[1:a]volume=0.0001[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            context = _Context(source)
            context.audio_qc_policy = {
                "enforce": True,
                "integrated_lufs_min": -20.0,
                "integrated_lufs_max": -12.0,
                "true_peak_max_dbfs": -1.0,
            }
            report = FfmpegQcEngine().run(context=context, input_artifacts=[])
            quality = report["qc_report"]["metrics"]["audio_quality"]
            self.assertIsInstance(quality["integrated_lufs"], float)
            self.assertIsInstance(quality["true_peak_dbfs"], float)
            self.assertFalse(report["passed"])
            self.assertIn("AUDIO_LOUDNESS_OUT_OF_RANGE", report["qc_report"]["hard_failures"])

    def test_qc_attaches_final_audio_delivery_receipt_bound_to_current_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "delivery-audio.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=green:s=160x120:r=30:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            final_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            line = {
                "start_us": 100_000,
                "end_us": 500_000,
                "text": "Buy now",
                "meaning": "buy now",
                "delivery": "light_voice",
                "visible_speaker": False,
            }
            context = _Context(source)
            context.final_audio_qc_required = True
            context.final_audio_contract = {
                "output_language": "en",
                "exact_line_windows": [line],
            }
            context.final_audio_qc_evidence = {
                "final_output_sha256": final_sha,
                "output_language": "en",
                "exact_line_windows": [{**line, "lip_sync_match_percent": 100}],
                "foley_windows": [],
                "ambience_windows": [],
                "silence_windows": [],
                "unexpected_silence_windows": [],
                "integrated_lufs": -16.0,
                "true_peak_dbfs": -2.0,
                "max_boundary_sample_jump": 0.1,
                "stream_start_offset_us": 0,
                "terminal_drift_us": 0,
            }

            report = FfmpegQcEngine().run(context=context, input_artifacts=[])

            final_audio_qc = report["qc_report"]["metrics"]["final_audio_qc"]
            self.assertEqual(final_audio_qc["status"], "passed")
            self.assertEqual(final_audio_qc["final_output_sha256"], final_sha)
            self.assertTrue(report["qc_report"]["checks"]["final_audio_delivery"])

    def test_production_active_qc_requires_final_audio_contract_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps(
                    {
                        "duration_us": 500_000,
                        "audio_required": True,
                        "final_audio_qc_passed": True,
                        "final_audio_qc_score": 100,
                    }
                ),
                encoding="utf-8",
            )
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.input_slots = (
                {"slot_id": "source_video", "present": True, "sha256": [source_sha]},
            )
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.audio_qc_policy = {"measure": False}

            report = FfmpegQcEngine(
                production=True,
                evaluator=self._production_evaluator(source_sha=source_sha),
                sha256="f" * 64,
            ).run(context=context, input_artifacts=[])

            self.assertFalse(report["passed"], report["qc_report"])
            self.assertIn(
                "FINAL_AUDIO_QC_EVIDENCE_MISSING",
                report["qc_report"]["hard_failures"],
            )
            self.assertEqual(
                report["qc_report"]["metrics"]["final_audio_qc"]["status"],
                "missing",
            )
            self.assertFalse(report["qc_report"]["checks"]["final_audio_delivery"])

    def test_production_active_qc_accepts_manifest_contract_and_evaluator_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            contract, evidence = self._final_audio_records(source_sha)
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps(
                    {
                        "duration_us": 500_000,
                        "audio_required": True,
                        "final_audio_contract": contract,
                    }
                ),
                encoding="utf-8",
            )
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.input_slots = (
                {"slot_id": "source_video", "present": True, "sha256": [source_sha]},
            )
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.audio_qc_policy = {"measure": False}

            report = FfmpegQcEngine(
                production=True,
                evaluator=self._production_evaluator(
                    source_sha=source_sha,
                    final_audio_evidence=evidence,
                ),
                sha256="f" * 64,
            ).run(context=context, input_artifacts=[])

            final_audio_qc = report["qc_report"]["metrics"]["final_audio_qc"]
            self.assertTrue(report["passed"], report["qc_report"])
            self.assertEqual(final_audio_qc["status"], "passed")
            self.assertEqual(final_audio_qc["final_output_sha256"], source_sha)
            self.assertTrue(report["qc_report"]["checks"]["final_audio_delivery"])

    def test_production_active_qc_rejects_stale_final_audio_evidence_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            contract, evidence = self._final_audio_records("0" * 64)
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps(
                    {
                        "duration_us": 500_000,
                        "audio_required": True,
                        "final_audio_contract": contract,
                    }
                ),
                encoding="utf-8",
            )
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.input_slots = (
                {"slot_id": "source_video", "present": True, "sha256": [source_sha]},
            )
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.audio_qc_policy = {"measure": False}

            report = FfmpegQcEngine(
                production=True,
                evaluator=self._production_evaluator(
                    source_sha=source_sha,
                    final_audio_evidence=evidence,
                ),
                sha256="f" * 64,
            ).run(context=context, input_artifacts=[])

            final_audio_qc = report["qc_report"]["metrics"]["final_audio_qc"]
            self.assertFalse(report["passed"], report["qc_report"])
            self.assertIn("FINAL_AUDIO_QC_FAILED", report["qc_report"]["hard_failures"])
            self.assertEqual(final_audio_qc["status"], "failed")
            self.assertIn("current final output", final_audio_qc["error"])
            self.assertFalse(report["qc_report"]["checks"]["final_audio_delivery"])

    def test_production_active_qc_reports_malformed_final_audio_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            contract, evidence = self._final_audio_records(source_sha)
            contract["av_tolerance_us"] = "not-an-integer"
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps(
                    {
                        "duration_us": 500_000,
                        "audio_required": True,
                        "final_audio_contract": contract,
                    }
                ),
                encoding="utf-8",
            )
            context = _ElasticTimelineContext(source, manifest)
            context.timeline_regions = ()
            context.input_slots = (
                {"slot_id": "source_video", "present": True, "sha256": [source_sha]},
            )
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            context.audio_qc_policy = {"measure": False}

            report = FfmpegQcEngine(
                production=True,
                evaluator=self._production_evaluator(
                    source_sha=source_sha,
                    final_audio_evidence=evidence,
                ),
                sha256="f" * 64,
            ).run(context=context, input_artifacts=[])

            final_audio_qc = report["qc_report"]["metrics"]["final_audio_qc"]
            self.assertFalse(report["passed"], report["qc_report"])
            self.assertIn("FINAL_AUDIO_QC_FAILED", report["qc_report"]["hard_failures"])
            self.assertEqual(final_audio_qc["status"], "failed")
            self.assertIn("not-an-integer", final_audio_qc["error"])
            self.assertFalse(report["qc_report"]["checks"]["final_audio_delivery"])

    def test_shadow_qc_keeps_final_audio_delivery_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_audio_source(root)
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps({"duration_us": 500_000, "audio_required": True}),
                encoding="utf-8",
            )
            context = _ElasticTimelineContext(source, manifest)
            context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "shadow",
            }
            context.audio_qc_policy = {"measure": False}

            report = FfmpegQcEngine().run(context=context, input_artifacts=[])

            self.assertTrue(report["passed"], report["qc_report"])
            self.assertEqual(
                report["qc_report"]["metrics"]["final_audio_qc"]["status"],
                "not_requested",
            )
            self.assertTrue(report["qc_report"]["checks"]["final_audio_delivery"])

    def test_qc_serializes_silent_audio_measurements_without_non_finite_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "silent-audio.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=green:s=160x120:r=30:d=1",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=1",
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            context = _Context(source)
            context.audio_qc_policy = {"measure": True}

            report = FfmpegQcEngine().run(context=context, input_artifacts=[])
            quality = report["qc_report"]["metrics"]["audio_quality"]

            json.dumps(report, allow_nan=False)
            self.assertIsNone(quality["true_peak_dbfs"])
            self.assertEqual(quality["true_peak_state"], "negative_infinity")

    def test_qc_requires_final_audio_stream_when_exact_lines_expect_speech(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            context = _Context(source)
            context.exact_line_contract = {
                "schema_version": "exact-line-contract/v1",
                "lines": [
                    {
                        "line_id": "L01",
                        "speaker": "creator",
                        "locale": "en-US",
                        "text": "This line must be audible.",
                        "start_ms": 0,
                        "end_ms": 400,
                    }
                ],
            }

            report = FfmpegQcEngine().run(context=context, input_artifacts=[])

            self.assertFalse(report["passed"], report["qc_report"])
            self.assertIn(
                "FINAL_AUDIO_STREAM_REQUIRED",
                report["qc_report"]["hard_failures"],
            )

    def test_qc_blocks_audible_sample_jump_at_declared_transition_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "boundary-click.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=green:s=160x120:r=30:d=1",
                    "-f", "lavfi", "-i", "aevalsrc=if(lt(t\\,0.5)\\,0.8\\,-0.8):s=48000:d=1",
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            context = _Context(source)
            context.audio_qc_policy = {
                "enforce": True,
                "check_boundary_clicks": True,
                "max_boundary_sample_jump": 0.2,
            }
            context.timeline_manifest = {
                "duration_us": 1_000_000,
                "regions": [{"source_start_us": 0}, {"source_start_us": 500_000}],
                "transition_renders": [
                    {"offset": 0.5, "audio_fade_duration": 0.03}
                ],
            }
            report = FfmpegQcEngine().run(context=context, input_artifacts=[])
            quality = report["qc_report"]["metrics"]["audio_quality"]
            self.assertEqual(quality["boundary_count"], 1)
            self.assertFalse(report["passed"])
            self.assertIn("AUDIO_BOUNDARY_CLICK_DETECTED", report["qc_report"]["hard_failures"])

    def test_freeze_gate_requires_user_upload_duration_lineage(self):
        code = _freeze_interval_failure_code(
            ((0.0, 1.0),),
            duration=1.0,
            fps=30.0,
            timeline_manifest={
                "placements": [
                    {
                        "region_type": "opaque_ui_demo",
                        "media_origin": "user_upload",
                        "output_start": 0.0,
                        "output_end": 1.0,
                    }
                ]
            },
            minimum_duration=0.5,
        )
        self.assertEqual(code, "TRAILING_FREEZE_DETECTED")

    def test_production_qc_requires_the_published_timeline_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=green:s=160x120:r=10:d=0.8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            manifest = root / "timeline.json"
            manifest.write_text(json.dumps({"duration_us": 800_000}), encoding="utf-8")
            context = _ElasticTimelineContext(source, manifest)
            context.artifacts = (context.artifacts[0],)
            report = FfmpegQcEngine(production=True, sha256="a" * 64).run(
                context=context,
                input_artifacts=[],
            )
            self.assertFalse(report["passed"])
            self.assertIn("TIMELINE_MANIFEST_MISSING", report["qc_report"]["hard_failures"])


if __name__ == "__main__":
    unittest.main()
