from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from server.errors import ReplicationError
from server.media_materializer import MaterializedMedia
from server.real_capabilities import (
    FfmpegDynamicsAnalyzer,
    WhisperAsrTranscriber,
    DeterministicUiRenderer,
    BundledAppStoreEvidenceParser,
    CapabilityUnavailable,
    _probe,
)
from server.audio_backends import EvidenceBoundHttpAudioEventBackend


class _Context:
    def __init__(
        self,
        source: Path,
        *,
        ui: Path | None = None,
        ui_metadata: dict | None = None,
        app_artifact: Path | None = None,
        app_metadata: dict | None = None,
        profile_snapshot: dict | None = None,
        timeline_regions: tuple[dict, ...] = (),
        stage_outputs: dict | None = None,
    ) -> None:
        self.source = source
        self.ui = ui
        self.app_artifact = app_artifact
        self.work_dir = source.parent / "work"
        self.work_dir.mkdir(exist_ok=True)
        self.run_id = "run-test"
        self.job_id = "run-test"
        self.stage = "analyze_dynamics"
        self.timeline_regions = timeline_regions
        self.profile_snapshot = profile_snapshot
        self.stage_outputs = dict(stage_outputs or {})
        self.published: list[dict] = []
        self.materialized_artifact_kinds: list[str] = []
        self.input_slots = (
            {
                "slot_id": "source_video",
                "present": True,
                "values": [str(source)],
                "metadata": [{}],
            },
            {
                "slot_id": "ui_screenshot",
                "present": ui is not None,
                "values": [str(ui)] if ui is not None else [],
                "metadata": [dict(ui_metadata or {})] if ui is not None else [],
            },
            {
                "slot_id": "app_store_url",
                "present": app_artifact is not None,
                "values": ["https://apps.apple.com/app/id1"] if app_artifact is not None else [],
                "metadata": [{}] if app_artifact is not None else [],
            },
        )
        self.artifacts = (
            {
                "kind": "app_store_screenshot",
                "sha256": hashlib.sha256(app_artifact.read_bytes()).hexdigest(),
                "metadata": dict(app_metadata or {}),
            },
        ) if app_artifact is not None else ()

    @contextmanager
    def materialize_slot(self, slot_id: str, *, index: int = 0):
        if slot_id == "source_video":
            path = self.source
        elif slot_id == "ui_screenshot" and self.ui is not None:
            path = self.ui
        else:
            raise KeyError(slot_id)
        data = path.read_bytes()
        yield MaterializedMedia(
            path=path,
            job_id=self.job_id,
            object_key=f"temporary/{self.job_id}/inputs/{path.name}",
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            content_type="video/mp4" if path.suffix == ".mp4" else "image/png",
            metadata={},
        )

    @contextmanager
    def materialize_artifact(self, kind: str, *, index: int = 0):
        if kind != "app_store_screenshot" or self.app_artifact is None or index != 0:
            raise KeyError((kind, index))
        self.materialized_artifact_kinds.append(kind)
        data = self.app_artifact.read_bytes()
        yield MaterializedMedia(
            path=self.app_artifact,
            job_id=self.job_id,
            object_key=f"temporary/{self.job_id}/app-store/{self.app_artifact.name}",
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            content_type="image/jpeg",
            metadata=dict(self.artifacts[0]["metadata"]),
        )

    def publish_artifact(self, *, kind, stream, content_type, expected_sha256, metadata=None):
        data = stream.read()
        actual = hashlib.sha256(data).hexdigest()
        assert actual == expected_sha256
        descriptor = {
            "kind": kind,
            "sha256": actual,
            "uri": f"s3://tenant-test/{kind}/{actual}",
            "metadata": {
                "object_key": f"tenant-test/{kind}/{actual}",
                "content_type": content_type,
                "size_bytes": len(data),
                "published_bytes": data,
                **(metadata or {}),
            },
        }
        self.published.append(descriptor)
        return descriptor


class _EvidenceBoundClassifier:
    def __init__(self, callback):
        self.callback = callback

    def capability_identity(self):
        return {
            "implementation": "tests:_EvidenceBoundClassifier",
            "version": "1",
            "model_id": "test-audio-events",
            "model_sha256": "e" * 64,
            "evidence_binding": "usfr-audio-evidence/v1",
        }

    def classify(self, path, **kwargs):
        events = self.callback(path, **kwargs)
        encoded = json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {
            "events": events,
            "evidence": {
                "evidence_binding": "usfr-audio-evidence/v1",
                "request_sha256": "6" * 64,
                "response_sha256": "7" * 64,
                "input_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                "events_sha256": hashlib.sha256(encoded).hexdigest(),
                "model_id": "test-audio-events",
                "model_sha256": "e" * 64,
            },
        }


class _EvidenceBoundAsrBackend:
    def __init__(self, callback):
        self.callback = callback

    def capability_identity(self):
        return {
            "implementation": "tests:_EvidenceBoundAsrBackend",
            "version": "1",
            "model_id": "test-asr",
            "model_sha256": "f" * 64,
            "evidence_binding": "usfr-asr-evidence/v1",
        }

    def transcribe(self, path, **kwargs):
        segments = self.callback(path)
        encoded = json.dumps(segments, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {
            "segments": segments,
            "language": kwargs.get("language") or "en",
            "evidence": {
                "evidence_binding": "usfr-asr-evidence/v1",
                "request_sha256": "8" * 64,
                "response_sha256": "9" * 64,
                "input_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                "segments_sha256": hashlib.sha256(encoded).hexdigest(),
                "model_id": "test-asr",
                "model_sha256": "f" * 64,
            },
        }


class _EvidenceBoundSemanticBackend:
    def __init__(self, callback):
        self.callback = callback

    def capability_identity(self):
        return {
            "implementation": "tests:_EvidenceBoundSemanticBackend",
            "version": "1",
            "model_id": "test-vlm",
            "model_sha256": "c" * 64,
            "evidence_binding": "usfr-vlm-evidence/v1",
        }

    def analyze(self, *, path, probe, cuts, evidence_plan, context=None):
        value = dict(
            self.callback(
                path=path,
                probe=probe,
                cuts=cuts,
                evidence_plan=evidence_plan,
                context=context,
            )
        )
        value["backend_evidence"] = {
            "request_sha256": "1" * 64,
            "response_sha256": "2" * 64,
            "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "frame_sha256s": ["3" * 64],
            "model_id": "test-vlm",
            "model_sha256": "c" * 64,
        }
        return value


def _high_fidelity_semantic_payload(duration_us: int) -> dict:
    midpoint = duration_us // 2

    def evidence(evidence_id: str, *, kind: str = "frame") -> dict:
        return {
            "evidence_id": evidence_id,
            "kind": kind,
            "start_us": 0,
            "end_us": duration_us,
            "frame": 0 if kind == "frame" else None,
            "method": "evidence-bound adaptive semantic pass",
            "observed_inferred_planned": "observed",
            "confidence": 0.96,
        }

    return {
        "source_cuts": [{
            "cut": 1,
            "start_us": 0,
            "end_us": duration_us,
            "subject_presence": "identifiable",
            "content_roles": ["creator", "product", "commercial_proof"],
            "scene": "creator leans toward a tabletop microphone with the product centered",
            "action": "creator approaches, contacts, demonstrates, and settles into a completed hold",
            "camera": "locked medium close-up with a small source-matched push-in",
            "transition": "continuous",
            "end_state": "product proof visible and both hands settled",
            "certainty": "certain",
            "evidence_refs": [{"kind": "frame", "start_us": 0, "end_us": duration_us, "method": "adaptive frame evidence"}],
        }],
        "source_events": [{
            "event": 1,
            "kind": "ambience",
            "start_us": 0,
            "end_us": duration_us,
            "source_cut_start": 1,
            "source_cut_end": 1,
            "text": "",
            "certainty": "certain",
        }],
        "extensions": {
            "high_fidelity_hybrid_v1": {
                "schema_version": 1,
                "analysis_pass_count": 1,
                "semantic_cuts": [{
                    "cut": 1,
                    "scene_topology": {
                        "entities": [{"entity_id": "creator", "layer": "foreground", "bbox": [0.18, 0.08, 0.58, 0.78], "z_order": 3, "relation_to_camera": "faces camera across the table"}],
                        "spatial_relations": ["microphone remains between mouth and product"],
                        "occlusion_order": ["creator", "hands", "product"],
                        "table_line_y": 0.68,
                        "horizon_y": 0.30,
                        "negative_space": [0.78, 0.05, 0.18, 0.40],
                    },
                    "framing_migration": {"strategy": "crop", "anchors": [{"anchor_id": "creator", "bbox": [0.18, 0.08, 0.58, 0.78]}], "topology_constraint": "keep face, microphone, hands, product, and table line in the same relationship"},
                    "lighting": {"key_origin": "camera-left", "key_vector": [-0.7, -0.1, 0.5], "hardness": "soft", "contrast_ratio": 2.2, "color_temperature_k": 4200, "shadow_vector": [0.4, 0.2, 0.0]},
                    "performance": {
                        "applicability": "person_present",
                        "posture": "slight forward lean with level shoulders",
                        "gaze_phases": [{"start_us": 0, "end_us": duration_us, "target": "product then camera"}],
                        "expression_phases": [{"start_us": 0, "end_us": duration_us, "state": "quiet focus turning to confirmation"}],
                        "gesture_phases": [{"start_us": 0, "end_us": duration_us, "hand": "both", "path": "table to product and back to a settled hold", "end_state": "hands settled around the demonstrated product"}],
                        "objective": "prove the target use visibly",
                        "visible_tactic": "perform the complete action while keeping the proof readable",
                        "emotional_turn": "focus changes to confirmation",
                        "microphone_relation": "mouth remains one palm from the tabletop microphone",
                    },
                    "object_action": {
                        "state_sequence": [
                            {"phase": "before", "start_us": 0, "end_us": midpoint, "state": "hands beside product"},
                            {"phase": "completed", "start_us": midpoint, "end_us": duration_us, "state": "product proof visible and both hands settled"},
                        ],
                        "hand_ownership": "creator both hands",
                        "contact_points": ["fingertips to product controls"],
                        "movement_trajectory": "hands move inward, contact, then settle",
                        "completed_end_state": "product proof visible and both hands settled",
                        "caused_audio_event_ids": [1],
                    },
                    "speech_audio": {
                        "exact_asr_event_ids": [],
                        "audio_event_mappings": [{"event_id": 1, "role": "ambience", "synced_factor_id": "HFH.C01.AUDIO.SYNC", "evidence": [evidence("E-AUDIO", kind="audio")]}],
                        "meaningful_silence_ranges": [],
                    },
                    "evidence": [evidence("E-CUT")],
                    "observed_inferred_planned": "observed",
                    "confidence": 0.96,
                    "uncertainty": [],
                    "criticality": "H",
                    "blocker_threshold": 0.85,
                }],
                "route_excluded_intervals": [],
            }
        },
    }


def _source_overlay_contract(duration_us: int) -> dict:
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
            {"time_us": 0, "bbox": {"x": 0.10, "y": 0.80, "width": 0.30, "height": 0.10}, "rotation_deg": 0, "opacity": 1},
            {"time_us": duration_us, "bbox": {"x": 0.10, "y": 0.80, "width": 0.30, "height": 0.10}, "rotation_deg": 0, "opacity": 1},
        ],
        "observed_text": "BUY NOW",
    }
    return {
        "contract": "source-ui-overlay-motion",
        "contract_version": 1,
        "reference_duration_us": duration_us,
        "source_width": 160,
        "source_height": 120,
        "coordinate_space": "rotation_corrected_source_visible_frame_normalized",
        "target_mapping": "source_normalized_composition_to_target_frame",
        "attachment": "screen_space",
        "time_range_semantics": "start_inclusive_end_exclusive",
        "cuts": [{"cut": 1, "start_us": 0, "end_us": duration_us, "source_overlays": [overlay]}],
        "notes": ["sidecar-provided source overlay evidence"],
    }


class _EvidenceBoundOcrBackend:
    def __init__(self, callback, *, corrupt_records_hash: bool = False):
        self.callback = callback
        self.corrupt_records_hash = corrupt_records_hash

    def capability_identity(self):
        return {
            "implementation": "tests:_EvidenceBoundOcrBackend",
            "version": "1",
            "model_id": "test-ocr",
            "model_sha256": "d" * 64,
            "evidence_binding": "usfr-ocr-evidence/v1",
        }

    def recognize(self, path):
        records = self.callback(path)
        encoded = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {
            "records": records,
            "evidence": {
                "request_sha256": "4" * 64,
                "response_sha256": "5" * 64,
                "input_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                "records_sha256": ("0" * 64) if self.corrupt_records_hash else hashlib.sha256(encoded).hexdigest(),
                "model_id": "test-ocr",
                "model_sha256": "d" * 64,
            },
        }


class RealCapabilityProbeContractTest(unittest.TestCase):
    def test_probe_uses_video_duration_ts_instead_of_longer_container_audio(self) -> None:
        """The service output clock is the video stream, not AAC overhang."""

        payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 180,
                    "height": 320,
                    "avg_frame_rate": "30/1",
                    "time_base": "1/90000",
                    "duration_ts": "90000",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "time_base": "1/48000",
                    "duration": "1.5",
                },
            ],
            "format": {"duration": "1.5"},
        }
        completed = type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(payload),
                "stderr": "",
            },
        )()
        with patch(
            "server.real_capabilities._executable",
            return_value="ffprobe",
        ), patch("server.real_capabilities._run", return_value=completed):
            probe = _probe(Path("audio-overhang.mp4"))

        self.assertEqual(probe["duration_us"], 1_000_000)
        self.assertEqual(probe["video_duration_us"], 1_000_000)
        self.assertEqual(probe["audio_duration_us"], 1_500_000)


class RealCapabilitySmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.video = self.root / "source.mp4"
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=red:s=160x120:r=10:d=0.6",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:d=0.6",
                "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=10:d=0.6",
                "-filter_complex", "[0:v][2:v]concat=n=2:v=1:a=0[v]",
                "-map", "[v]", "-map", "1:a", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(self.video),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            self.skipTest("ffmpeg is unavailable")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dynamics_covers_exact_video_and_exposes_evidence(self) -> None:
        context = _Context(self.video)
        result = FfmpegDynamicsAnalyzer(allow_heuristic=True, production=False).analyze(context=context, input_artifacts=[])
        analysis = result["source_dynamics_analysis"]
        self.assertGreaterEqual(len(analysis["source_cuts"]), 1)
        self.assertEqual(analysis["source_cuts"][0]["start_us"], 0)
        self.assertEqual(analysis["source_cuts"][-1]["end_us"], analysis["reference_duration_us"])
        self.assertTrue(result["evidence"]["probe"])

    def test_dynamics_reuses_verified_probe_source_output_without_reprobing(self) -> None:
        source_sha256 = hashlib.sha256(self.video.read_bytes()).hexdigest()
        cached_probe = _probe(self.video)
        cached_probe["sha256"] = source_sha256
        context = _Context(
            self.video,
            stage_outputs={"probe_source": {"probe": cached_probe}},
        )
        analyzer = FfmpegDynamicsAnalyzer(allow_heuristic=True, production=False)
        # A verified probe_source output is the fast path.  If the analyzer
        # calls ffprobe again this test fails deterministically.
        with patch("server.real_capabilities._probe", side_effect=AssertionError("unexpected second probe")):
            result = analyzer.analyze(context=context, input_artifacts=[])
        self.assertEqual(result["evidence"]["probe"]["source_sha256"], source_sha256)
        self.assertEqual(result["source_dynamics_analysis"]["reference_duration_us"], cached_probe["duration_us"])

    def test_dynamics_reuses_verified_probe_artifact_metadata_without_reprobing(self) -> None:
        source_sha256 = hashlib.sha256(self.video.read_bytes()).hexdigest()
        cached_probe = _probe(self.video)
        cached_probe["sha256"] = source_sha256
        context = _Context(self.video)
        context.stage_outputs = {}
        context.artifacts = (
            {
                "kind": "probe_source",
                "metadata": {"probe": cached_probe},
            },
        )
        with patch("server.real_capabilities._probe", side_effect=AssertionError("unexpected second probe")):
            result = FfmpegDynamicsAnalyzer(allow_heuristic=True, production=False).analyze(
                context=context,
                input_artifacts=[],
            )
        self.assertEqual(result["evidence"]["probe"]["source_sha256"], source_sha256)

    def test_dynamics_rejects_stale_verified_probe_source_output(self) -> None:
        cached_probe = _probe(self.video)
        cached_probe["sha256"] = "0" * 64
        context = _Context(
            self.video,
            stage_outputs={"probe_source": {"probe": cached_probe}},
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "probe_source.*SHA"):
            FfmpegDynamicsAnalyzer(allow_heuristic=True, production=False).analyze(
                context=context,
                input_artifacts=[],
            )

    def test_dynamics_rejects_verified_probe_without_frame_rate(self) -> None:
        cached_probe = _probe(self.video)
        cached_probe["sha256"] = hashlib.sha256(self.video.read_bytes()).hexdigest()
        cached_probe["fps_num"] = 0
        cached_probe["fps_den"] = 0
        cached_probe["fps"] = "0/0"
        context = _Context(
            self.video,
            stage_outputs={"probe_source": {"probe": cached_probe}},
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "frame rate"):
            FfmpegDynamicsAnalyzer(allow_heuristic=True, production=False).analyze(
                context=context,
                input_artifacts=[],
            )

    def test_dynamics_rejects_verified_probe_duration_drift(self) -> None:
        cached_probe = _probe(self.video)
        cached_probe["sha256"] = hashlib.sha256(self.video.read_bytes()).hexdigest()
        cached_probe["duration_us"] += 500_000
        context = _Context(
            self.video,
            stage_outputs={"probe_source": {"probe": cached_probe}},
        )
        # Bind an independent upload-completion duration claim so the cache
        # validator has a source-of-truth duration to compare against.
        context.input_slots = tuple(
            {
                **slot,
                "metadata": ([{"duration_seconds": 2.0}] if slot.get("slot_id") == "source_video" else slot.get("metadata")),
            }
            for slot in context.input_slots
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "duration"):
            FfmpegDynamicsAnalyzer(allow_heuristic=True, production=False).analyze(
                context=context,
                input_artifacts=[],
            )

    def test_semantic_backend_may_supply_adaptive_cut_boundaries(self) -> None:
        context = _Context(self.video)

        def semantic(**kwargs):
            duration = int(kwargs["probe"]["duration_us"])
            midpoint = duration // 2
            return {
                "source_cuts": [
                    {"start_us": 0, "end_us": midpoint, "scene": "first evidence-backed phase"},
                    {"start_us": midpoint, "end_us": duration, "scene": "second evidence-backed phase"},
                ]
            }

        result = FfmpegDynamicsAnalyzer(
            semantic_analyzer=_EvidenceBoundSemanticBackend(semantic),
            production=True,
            sha256="c" * 64,
        ).analyze(context=context, input_artifacts=[])
        self.assertEqual(len(result["source_dynamics_analysis"]["source_cuts"]), 2)
        self.assertEqual(result["source_dynamics_analysis"]["source_cuts"][1]["end_us"], result["source_dynamics_analysis"]["reference_duration_us"])

    def test_dynamics_emits_and_forwards_the_single_pass_evidence_plan(self) -> None:
        captured: dict[str, dict] = {}

        class EvidencePlanBackend:
            def capability_identity(self):
                return {
                    "implementation": "tests:EvidencePlanBackend",
                    "version": "1",
                    "model_id": "test-vlm",
                    "model_sha256": "c" * 64,
                    "evidence_binding": "usfr-vlm-evidence/v1",
                }

            def analyze(self, *, path, probe, cuts, evidence_plan, context=None):
                captured["evidence_plan"] = dict(evidence_plan)
                duration = int(probe["duration_us"])
                return {
                    "source_cuts": [{"start_us": 0, "end_us": duration, "scene": "single-pass evidence"}],
                    "source_events": [],
                    "backend_evidence": {
                        "request_sha256": "1" * 64,
                        "response_sha256": "2" * 64,
                        "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                        "frame_sha256s": ["3" * 64],
                        "model_id": "test-vlm",
                        "model_sha256": "c" * 64,
                    },
                }

        result = FfmpegDynamicsAnalyzer(
            semantic_analyzer=EvidencePlanBackend(),
            production=True,
            sha256="c" * 64,
        ).analyze(context=_Context(self.video), input_artifacts=[])

        plan = result["evidence_plan"]
        self.assertEqual(captured["evidence_plan"], plan)
        self.assertEqual(plan["contract"], "high-fidelity-evidence-plan")
        self.assertEqual(plan["analysis_pass_count"], 1)
        self.assertEqual(plan["source"]["sha256"], hashlib.sha256(self.video.read_bytes()).hexdigest())
        self.assertEqual(result["evidence"]["evidence_plan_sha256"], plan["plan_sha256"])
        self.assertNotIn(str(self.video), json.dumps(plan, ensure_ascii=False))

    def test_active_high_fidelity_dynamics_preserves_and_validates_deep_extension(self) -> None:
        context = _Context(
            self.video,
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
        )

        def semantic(**kwargs):
            return _high_fidelity_semantic_payload(int(kwargs["probe"]["duration_us"]))

        result = FfmpegDynamicsAnalyzer(
            semantic_analyzer=_EvidenceBoundSemanticBackend(semantic),
            production=True,
            sha256="c" * 64,
        ).analyze(context=context, input_artifacts=[])
        extension = result["source_dynamics_analysis"]["extensions"]["high_fidelity_hybrid_v1"]
        self.assertEqual(extension["analysis_pass_count"], 1)
        self.assertEqual(
            extension["semantic_cuts"][0]["performance"]["microphone_relation"],
            "mouth remains one palm from the tabletop microphone",
        )

    def test_semantic_backend_preserves_optional_source_overlay_contract(self) -> None:
        context = _Context(self.video)

        def semantic(**kwargs):
            value = _high_fidelity_semantic_payload(int(kwargs["probe"]["duration_us"]))
            value["source_overlay_contract"] = _source_overlay_contract(int(kwargs["probe"]["duration_us"]))
            return value

        result = FfmpegDynamicsAnalyzer(
            semantic_analyzer=_EvidenceBoundSemanticBackend(semantic),
            production=True,
            sha256="c" * 64,
        ).analyze(context=context, input_artifacts=[])
        self.assertEqual(
            result["source_dynamics_analysis"]["source_overlay_contract"]["contract"],
            "source-ui-overlay-motion",
        )

    def test_active_high_fidelity_dynamics_rejects_shallow_semantic_output(self) -> None:
        context = _Context(
            self.video,
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
        )

        def semantic(**kwargs):
            duration = int(kwargs["probe"]["duration_us"])
            return {"source_cuts": [{"start_us": 0, "end_us": duration, "scene": "coarse scene"}]}

        with self.assertRaisesRegex(CapabilityUnavailable, "high-fidelity.*extension"):
            FfmpegDynamicsAnalyzer(
                semantic_analyzer=_EvidenceBoundSemanticBackend(semantic),
                production=True,
                sha256="c" * 64,
            ).analyze(context=context, input_artifacts=[])

    def test_asr_can_use_injected_backend_and_builds_silence_contract(self) -> None:
        def fake_transcriber(_path: Path):
            return [{"start": 0.1, "end": 0.4, "text": "hello", "confidence": 0.99}]

        context = _Context(self.video)
        result = WhisperAsrTranscriber(transcriber=fake_transcriber, production=False).transcribe(context=context, input_artifacts=[])
        self.assertEqual(result["audio_contract"]["segments"][0]["text"], "hello")
        self.assertIsInstance(result["audio_contract"]["silence_windows"], list)
        self.assertRegex(result["audio_contract"]["source_audio_sha256"], r"^[0-9a-f]{64}$")

    def test_ui_renderer_requires_ocr_backend_in_strict_mode(self) -> None:
        context = _Context(self.video)
        with self.assertRaises(CapabilityUnavailable):
            DeterministicUiRenderer(production=False).render_and_verify(context=context, input_artifacts=[])

    def test_active_generated_ui_rejects_single_png_without_video_state_evidence(self) -> None:
        ui = self._ui_fixture()
        context = _Context(
            self.video,
            ui=ui,
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
            timeline_regions=({"region_type": "generated_ui_demo"},),
        )
        adapter = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(lambda _path: self._ocr_records()),
            expected_text=["BUY NOW"],
            expected_layout=[{"text": "BUY NOW", "bbox": [60, 20, 140, 50]}],
            production=True,
            sha256="b" * 64,
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "video.*state_evidence"):
            adapter.render_and_verify(context=context, input_artifacts=[])

    def test_active_generated_ui_builds_state_evidence_from_real_video_and_bound_ocr(self) -> None:
        """The renderer may return media/truth only; OCR remains independent."""
        ui = self._ui_fixture()
        truth = {
            "approved_copy": ["BUY NOW"],
            "states": [
                {
                    "state_id": "home",
                    "frame_ms": 100,
                    "expected_text": ["BUY NOW"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "BUY NOW", "bbox": [60, 20, 140, 50]}
                    ],
                },
                {
                    "state_id": "confirm",
                    "frame_ms": 250,
                    "expected_text": ["BUY NOW"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "BUY NOW", "bbox": [60, 20, 140, 50]}
                    ],
                },
            ],
        }
        render_contract = {
            "route": "generated_ui_demo",
            "viewport": [200, 100],
            "state_sequence": ["home", "confirm"],
        }

        class _VideoRenderer:
            def capability_identity(self):
                return {
                    "implementation": "tests:_VideoRenderer",
                    "version": "1",
                    "sha256": "e" * 64,
                }

            def __call__(self, source, output, _context):
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                        "-i", str(source), "-t", "0.4", "-vf", "fps=10,format=yuv420p",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output),
                    ],
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
                return {
                    "video_path": str(output),
                    "ui_truth_card": truth,
                    "ui_render_contract": render_contract,
                }

        context = _Context(
            self.video,
            ui=ui,
            ui_metadata={
                "ui_truth_card": truth,
                "ui_render_contract": render_contract,
                "truth_basis": "target-owned-upload",
            },
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
            timeline_regions=({"region_type": "generated_ui_demo"},),
        )
        adapter = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(lambda _path: self._ocr_records()),
            render_backend=_VideoRenderer(),
            production=True,
            sha256="b" * 64,
        )
        result = adapter.render_and_verify(context=context, input_artifacts=[])
        self.assertEqual(result["ocr_match_percent"], 100)
        self.assertEqual(result["layout_match_percent"], 100)
        self.assertEqual(len(result["ui_qc_report"]["state_evidence"]), 2)
        self.assertEqual(result["published_artifacts"][0]["kind"], "generated_ui_video")
        self.assertTrue(result["published_artifacts"][0]["metadata"]["parent_digests"])
        self.assertEqual(context.published[0]["metadata"]["content_type"], "video/mp4")

    def test_active_generated_ui_derives_truth_from_uploaded_screenshot(self) -> None:
        """A screenshot-only slot must produce an executable immutable UI truth card."""
        ui = self._ui_fixture()
        truth_seen = {}

        class _VideoRenderer:
            def capability_identity(self):
                return {
                    "implementation": "tests:_VideoRenderer",
                    "version": "1",
                    "sha256": "e" * 64,
                }

            def __call__(self, source, output, _context, *, truth, render_contract):
                truth_seen["truth"] = truth
                truth_seen["contract"] = render_contract
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                        "-i", str(source), "-t", "0.4", "-vf", "fps=10,format=yuv420p",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output),
                    ],
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
                return {"video_path": str(output)}

        context = _Context(
            self.video,
            ui=ui,
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
            timeline_regions=({"region_type": "generated_ui_demo"},),
        )
        result = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(lambda _path: self._ocr_records()),
            render_backend=_VideoRenderer(),
            production=True,
            sha256="b" * 64,
        ).render_and_verify(context=context, input_artifacts=[])

        self.assertEqual(result["ui_truth_card"], truth_seen["truth"])
        self.assertEqual(result["ui_truth_card"]["states"][0]["expected_text"], ["BUY NOW"])
        self.assertEqual(result["ui_truth_card"]["states"][0]["expected_layout"][0]["bbox"], [60, 20, 140, 50])
        self.assertEqual(result["ui_render_contract"]["state_sequence"], ["state-001"])
        self.assertEqual(result["truth_basis"], "target-owned-upload")

    def test_bundled_app_store_parser_publishes_evidence_before_ui_resolution(self) -> None:
        context = _Context(self.video)
        context.input_slots = (
            {
                "slot_id": "app_store_url",
                "present": True,
                "values": ["https://play.google.com/store/apps/details?id=com.example.app"],
                "metadata": [{}],
            },
        )

        def fake_runner(command, **kwargs):
            output_dir = Path(command[command.index("--output-dir") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            screenshot = output_dir / "screenshot_001.png"
            Image.new("RGB", (200, 100), "white").save(screenshot)
            screenshot_sha = hashlib.sha256(screenshot.read_bytes()).hexdigest()
            bundle = {
                "contract": "app-store-evidence",
                "contract_version": 1,
                "provider": "google_play",
                "requested_url": command[1],
                "final_url": command[1],
                "canonical_url": command[1],
                "store_app_id": "com.example.app",
                "name": "Example App",
                "storefront": "default",
                "language": "default",
                "page_sha256": "a" * 64,
                "pixel_truth_mode": "replacement_pixels",
                "screenshots": [
                    {
                        "media_role": "app_screenshot",
                        "store_media_ordinal": 1,
                        "source_url": "https://play-lh.googleusercontent.com/example",
                        "final_url": "https://play-lh.googleusercontent.com/example",
                        "content_type": "image/png",
                        "size_bytes": screenshot.stat().st_size,
                        "sha256": screenshot_sha,
                        "file_path": screenshot.name,
                        "width": 200,
                        "height": 100,
                    }
                ],
                "screenshot_device_families": ["phone"],
                "warnings": [],
            }
            (output_dir / "app_store_evidence_bundle.json").write_text(
                json.dumps(bundle), encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, str(output_dir / "app_store_evidence_bundle.json"), "")

        with patch("server.real_capabilities.subprocess.run", side_effect=fake_runner):
            result = BundledAppStoreEvidenceParser().run(context=context, input_artifacts=[])

        self.assertEqual(
            [item["kind"] for item in result["published_artifacts"]],
            ["app_store_evidence", "app_store_screenshot"],
        )
        screenshot_metadata = result["published_artifacts"][1]["metadata"]
        self.assertEqual(screenshot_metadata["truth_basis"], "parsed-app-store-evidence")
        self.assertEqual(screenshot_metadata["store_app_id"], "com.example.app")

    def test_active_generated_ui_never_trusts_renderer_self_report(self) -> None:
        """A renderer-supplied 100% report cannot bypass independent OCR."""
        ui = self._ui_fixture()
        truth = {
            "approved_copy": ["BUY NOW"],
            "states": [
                {
                    "state_id": "home",
                    "frame_ms": 100,
                    "expected_text": ["BUY NOW"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "BUY NOW", "bbox": [60, 20, 140, 50]}
                    ],
                }
            ],
        }
        render_contract = {
            "route": "generated_ui_demo",
            "viewport": [200, 100],
            "state_sequence": ["home"],
        }
        calls = {"ocr": 0}

        class _CountingOcr(_EvidenceBoundOcrBackend):
            def recognize(self, path):
                calls["ocr"] += 1
                return super().recognize(path)

        class _SelfReportingRenderer:
            def capability_identity(self):
                return {
                    "implementation": "tests:_SelfReportingRenderer",
                    "version": "1",
                    "sha256": "f" * 64,
                }

            def __call__(self, source, output, _context):
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                        "-i", str(source), "-t", "0.3", "-vf", "fps=10,format=yuv420p",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output),
                    ],
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
                return {
                    "video_path": str(output),
                    "ui_truth_card": truth,
                    "ui_render_contract": render_contract,
                    "ui_qc_report": {
                        "passed": True,
                        "ocr_match_percent": 100,
                        "layout_match_percent": 100,
                        "state_evidence": [
                            {
                                "state_id": "home",
                                "frame_ms": 100,
                                "frame_sha256": "0" * 64,
                                "decoded_frame_sha256": "0" * 64,
                                "ocr_match_percent": 100,
                                "layout_match_percent": 100,
                                "ocr_evidence": {"input_sha256": "0" * 64, "records": [], "records_sha256": "0" * 64},
                                "layout_evidence": {"input_sha256": "0" * 64, "records": [], "records_sha256": "0" * 64},
                            }
                        ],
                    },
                }

        context = _Context(
            self.video,
            ui=ui,
            ui_metadata={
                "ui_truth_card": truth,
                "ui_render_contract": render_contract,
                "truth_basis": "target-owned-upload",
            },
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
            timeline_regions=({"region_type": "generated_ui_demo"},),
        )
        adapter = DeterministicUiRenderer(
            ocr_backend=_CountingOcr(lambda _path: self._ocr_records()),
            render_backend=_SelfReportingRenderer(),
            production=True,
            sha256="b" * 64,
        )
        result = adapter.render_and_verify(context=context, input_artifacts=[])
        self.assertEqual(calls["ocr"], 1)
        self.assertEqual(result["ui_qc_report"]["state_evidence"][0]["ocr_evidence"]["records"][0]["text"], "BUY NOW")

    def test_active_generated_ui_rejects_renderer_modified_truth(self) -> None:
        """The target screenshot/evidence owns truth; a renderer may not rewrite it."""
        ui = self._ui_fixture()
        truth = {
            "approved_copy": ["BUY NOW"],
            "states": [
                {
                    "state_id": "home",
                    "frame_ms": 100,
                    "expected_text": ["BUY NOW"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "BUY NOW", "bbox": [60, 20, 140, 50]}
                    ],
                }
            ],
        }
        render_contract = {
            "route": "generated_ui_demo",
            "viewport": [200, 100],
            "state_sequence": ["home"],
        }
        source_metadata = {
            "ui_truth_card": truth,
            "ui_render_contract": render_contract,
            "truth_basis": "target-owned-upload",
        }
        mutated_truth = {
            **truth,
            "states": [
                {
                    **truth["states"][0],
                    "expected_text": ["HACKED"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "HACKED", "bbox": [60, 20, 140, 50]}
                    ],
                }
            ],
        }

        class _MutatingRenderer:
            def capability_identity(self):
                return {"implementation": "tests:_MutatingRenderer", "version": "1", "sha256": "f" * 64}

            def __call__(self, source, output, _context):
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                        "-i", str(source), "-t", "0.3", "-vf", "fps=10,format=yuv420p",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output),
                    ],
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
                return {
                    "video_path": str(output),
                    "ui_truth_card": mutated_truth,
                    "ui_render_contract": render_contract,
                }

        context = _Context(
            self.video,
            ui=ui,
            ui_metadata=source_metadata,
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
            timeline_regions=({"region_type": "generated_ui_demo"},),
        )
        adapter = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(lambda _path: self._ocr_records()),
            render_backend=_MutatingRenderer(),
            production=True,
            sha256="b" * 64,
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "truth.*renderer|renderer.*truth"):
            adapter.render_and_verify(context=context, input_artifacts=[])

    def test_active_generated_ui_renderer_cannot_mutate_truth_argument_in_place(self) -> None:
        ui = self._ui_fixture()
        truth = {
            "approved_copy": ["BUY NOW"],
            "states": [
                {
                    "state_id": "home",
                    "frame_ms": 100,
                    "expected_text": ["BUY NOW"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "BUY NOW", "bbox": [60, 20, 140, 50]}
                    ],
                }
            ],
        }
        render_contract = {
            "route": "generated_ui_demo",
            "viewport": [200, 100],
            "state_sequence": ["home"],
        }

        class _InPlaceMutatingRenderer:
            def capability_identity(self):
                return {"implementation": "tests:_InPlaceMutatingRenderer", "version": "1", "sha256": "f" * 64}

            def __call__(self, source, output, _context, *, truth=None, render_contract=None):
                truth["states"][0]["expected_text"][0] = "HACKED"
                truth["states"][0]["expected_layout"][0]["text"] = "HACKED"
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                        "-i", str(source), "-t", "0.3", "-vf", "fps=10,format=yuv420p",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output),
                    ],
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
                return {"video_path": str(output)}

        context = _Context(
            self.video,
            ui=ui,
            ui_metadata={
                "ui_truth_card": truth,
                "ui_render_contract": render_contract,
                "truth_basis": "target-owned-upload",
            },
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
            timeline_regions=({"region_type": "generated_ui_demo"},),
        )
        result = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(lambda _path: self._ocr_records()),
            render_backend=_InPlaceMutatingRenderer(),
            production=True,
            sha256="b" * 64,
        ).render_and_verify(context=context, input_artifacts=[])
        self.assertEqual(result["ui_truth_card"], truth)
        self.assertEqual(result["ui_truth_card"]["states"][0]["expected_text"], ["BUY NOW"])

    def test_active_generated_ui_qc_samples_animation_intervals(self) -> None:
        """State-frame checks alone are insufficient; transitions get independent OCR evidence."""
        ui = self._ui_fixture()
        truth = {
            "approved_copy": ["BUY NOW"],
            "states": [
                {
                    "state_id": "home",
                    "frame_ms": 100,
                    "expected_text": ["BUY NOW"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "BUY NOW", "bbox": [60, 20, 140, 50]}
                    ],
                },
                {
                    "state_id": "confirm",
                    "frame_ms": 250,
                    "expected_text": ["BUY NOW"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "BUY NOW", "bbox": [60, 20, 140, 50]}
                    ],
                },
            ],
        }
        render_contract = {
            "route": "generated_ui_demo",
            "viewport": [200, 100],
            "state_sequence": ["home", "confirm"],
            "animation_qc": {"samples_per_interval": 2},
        }
        source_metadata = {
            "ui_truth_card": truth,
            "ui_render_contract": render_contract,
            "truth_basis": "target-owned-upload",
        }
        calls = {"ocr": 0}

        class _CountingOcr(_EvidenceBoundOcrBackend):
            def recognize(self, path):
                calls["ocr"] += 1
                return super().recognize(path)

        class _VideoRenderer:
            def capability_identity(self):
                return {"implementation": "tests:_VideoRenderer", "version": "1", "sha256": "e" * 64}

            def __call__(self, source, output, _context):
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                        "-i", str(source), "-t", "0.4", "-vf", "fps=10,format=yuv420p",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output),
                    ],
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
                return {"video_path": str(output)}

        context = _Context(
            self.video,
            ui=ui,
            ui_metadata=source_metadata,
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
            timeline_regions=({"region_type": "generated_ui_demo"},),
        )
        result = DeterministicUiRenderer(
            ocr_backend=_CountingOcr(lambda _path: self._ocr_records()),
            render_backend=_VideoRenderer(),
            production=True,
            sha256="b" * 64,
        ).render_and_verify(context=context, input_artifacts=[])
        report = result["ui_qc_report"]
        self.assertGreaterEqual(calls["ocr"], 4)  # 2 declared states + 2 interval samples
        self.assertEqual(report["animation_ocr_match_percent"], 100)
        self.assertEqual(report["animation_layout_match_percent"], 100)
        self.assertEqual(len(report["animation_interval_evidence"]), 1)
        self.assertEqual(len(report["animation_interval_evidence"][0]["samples"]), 2)

    def test_active_generated_ui_rejects_garbled_animation_text(self) -> None:
        ui = self._ui_fixture()
        truth = {
            "approved_copy": ["BUY NOW"],
            "states": [
                {
                    "state_id": "home",
                    "frame_ms": 100,
                    "expected_text": ["BUY NOW"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "BUY NOW", "bbox": [60, 20, 140, 50]}
                    ],
                },
                {
                    "state_id": "confirm",
                    "frame_ms": 250,
                    "expected_text": ["BUY NOW"],
                    "expected_layout": [
                        {"element_id": "buy", "role": "button", "text": "BUY NOW", "bbox": [60, 20, 140, 50]}
                    ],
                },
            ],
        }
        render_contract = {
            "route": "generated_ui_demo",
            "viewport": [200, 100],
            "state_sequence": ["home", "confirm"],
            "animation_qc": {"samples_per_interval": 1},
        }
        source_metadata = {"ui_truth_card": truth, "ui_render_contract": render_contract, "truth_basis": "target-owned-upload"}
        calls = {"ocr": 0}

        class _VideoRenderer:
            def capability_identity(self):
                return {"implementation": "tests:_VideoRenderer", "version": "1", "sha256": "e" * 64}

            def __call__(self, source, output, _context):
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                        "-i", str(source), "-t", "0.4", "-vf", "fps=10,format=yuv420p",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output),
                    ],
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
                return {"video_path": str(output)}

        def ocr(_path):
            calls["ocr"] += 1
            if calls["ocr"] > 2:
                return [{"text": "BUY \ufffd NOW", "bbox": [60, 20, 140, 50], "confidence": 0.99}]
            return self._ocr_records()

        context = _Context(
            self.video,
            ui=ui,
            ui_metadata=source_metadata,
            profile_snapshot={"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"},
            timeline_regions=({"region_type": "generated_ui_demo"},),
        )
        with self.assertRaisesRegex(ReplicationError, "animation.*text|garbled|replacement"):
            DeterministicUiRenderer(
                ocr_backend=_EvidenceBoundOcrBackend(ocr),
                render_backend=_VideoRenderer(),
                production=True,
                sha256="b" * 64,
            ).render_and_verify(context=context, input_artifacts=[])

    def test_generated_ui_rejects_stale_ocr_records_digest(self) -> None:
        ui = self._ui_fixture()
        backend = _EvidenceBoundOcrBackend(lambda _path: self._ocr_records(), corrupt_records_hash=True)
        raw = backend.recognize(ui)
        adapter = DeterministicUiRenderer(
            ocr_backend=backend,
            production=True,
            sha256="b" * 64,
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "records SHA"):
            adapter._validate_generated_ui_ocr_evidence(
                raw["evidence"],
                input_sha256=raw["evidence"]["input_sha256"],
                records=raw["records"],
            )

    def test_production_identity_requires_explicit_adapter_sha(self) -> None:
        with self.assertRaisesRegex(ValueError, "deployment byte SHA-256"):
            WhisperAsrTranscriber(
                transcriber=_EvidenceBoundAsrBackend(lambda _path: []),
                production=True,
            )
        with self.assertRaisesRegex(ValueError, "deployment byte SHA-256"):
            DeterministicUiRenderer(ocr_backend=lambda _path: [], production=True)

    def test_production_whisper_requires_pinned_model_path_sha_and_device(self) -> None:
        with self.assertRaisesRegex(ValueError, "model_path"):
            WhisperAsrTranscriber(production=True, sha256="a" * 64)
        with self.assertRaisesRegex(ValueError, "model_path"):
            WhisperAsrTranscriber(
                production=True,
                download_root=self.root,
                model_sha256="a" * 64,
                device="cpu",
                sha256="a" * 64,
            )

    def test_production_asr_rejects_bare_transcriber_callback(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence-bound ASR backend"):
            WhisperAsrTranscriber(
                transcriber=lambda _path: [],
                production=True,
                sha256="a" * 64,
            )

    def test_asr_uses_acoustic_silence_without_claiming_semantic_meaning(self) -> None:
        def fake_transcriber(_path: Path):
            return [{"start": 0.1, "end": 0.4, "text": "hello", "confidence": 0.99}]

        def fake_silence(_path: Path):
            return [{"start_ms": 420, "end_ms": 590}]

        context = _Context(self.video)
        result = WhisperAsrTranscriber(
            transcriber=fake_transcriber,
            silence_detector=fake_silence,
            production=False,
        ).transcribe(context=context, input_artifacts=[])
        contract = result["audio_contract"]
        self.assertEqual(contract["silence_windows"], [
            {
                "start_ms": 420,
                "end_ms": 590,
                "kind": "acoustic_silence",
                "semantic_meaning": "unclassified",
            }
        ])
        self.assertEqual(contract["meaningful_silence"], [])

    def test_production_asr_requires_audio_event_classifier(self) -> None:
        context = _Context(self.video)
        adapter = WhisperAsrTranscriber(
            transcriber=_EvidenceBoundAsrBackend(
                lambda _path: [{"start": 0.1, "end": 0.4, "text": "hello"}]
            ),
            silence_detector=lambda _path: [],
            production=True,
            sha256="a" * 64,
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "audio event classifier"):
            adapter.transcribe(context=context, input_artifacts=[])

    def test_production_asr_rejects_bare_audio_event_classifier(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence-bound audio event classifier"):
            WhisperAsrTranscriber(
                transcriber=_EvidenceBoundAsrBackend(lambda _path: []),
                audio_event_classifier=lambda _path, **_kwargs: [],
                production=True,
                sha256="a" * 64,
            )

    def test_production_asr_accepts_evidence_bound_audio_backend(self) -> None:
        backend = EvidenceBoundHttpAudioEventBackend(
            endpoint="https://audio.internal/classify",
            model_id="yamnet-v1",
            model_sha256="a" * 64,
            production=True,
        )
        adapter = WhisperAsrTranscriber(
            transcriber=_EvidenceBoundAsrBackend(lambda _path: []),
            audio_event_classifier=backend,
            production=True,
            sha256="b" * 64,
        )
        self.assertIs(adapter.audio_event_classifier, backend)

    def test_production_asr_allows_video_without_audio_without_classifier(self) -> None:
        silent_video = self.root / "silent.mp4"
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=160x120:r=10:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent_video),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            self.skipTest("ffmpeg is unavailable")
        adapter = WhisperAsrTranscriber(
            transcriber=_EvidenceBoundAsrBackend(lambda _path: []),
            production=True,
            sha256="d" * 64,
        )
        contract = adapter.transcribe(context=_Context(silent_video), input_artifacts=[])["audio_contract"]
        self.assertEqual(contract["audio_events"], [])
        self.assertEqual(contract["silence_windows"][0]["semantic_meaning"], "no_audio_stream")

    def test_audio_event_classifier_supplies_foley_ambience_and_meaningful_silence(self) -> None:
        context = _Context(self.video)

        def classify(_path: Path, **_kwargs):
            return [
                {"event_id": "E1", "kind": "foley", "start_ms": 100, "end_ms": 180, "label": "click"},
                {"event_id": "E2", "kind": "ambience", "start_ms": 0, "end_ms": 600, "label": "room tone"},
                {"event_id": "E3", "kind": "silence", "start_ms": 420, "end_ms": 590, "meaningful": True},
            ]

        adapter = WhisperAsrTranscriber(
            transcriber=_EvidenceBoundAsrBackend(
                lambda _path: [{"start": 0.1, "end": 0.4, "text": "hello"}]
            ),
            silence_detector=lambda _path: [{"start_ms": 420, "end_ms": 590}],
            audio_event_classifier=_EvidenceBoundClassifier(classify),
            production=True,
            sha256="a" * 64,
        )
        contract = adapter.transcribe(context=context, input_artifacts=[])["audio_contract"]
        self.assertEqual([item["kind"] for item in contract["audio_events"]], ["foley", "ambience", "silence"])
        self.assertEqual(contract["meaningful_silence"][0]["event_id"], "E3")

    def test_production_asr_rejects_receipt_bound_to_wrong_wav(self) -> None:
        class WrongInputAsr(_EvidenceBoundAsrBackend):
            def transcribe(self, path, **kwargs):
                result = super().transcribe(path, **kwargs)
                result["evidence"]["input_sha256"] = "0" * 64
                return result

        adapter = WhisperAsrTranscriber(
            transcriber=WrongInputAsr(lambda _path: [{"start": 0.1, "end": 0.2, "text": "hello"}]),
            audio_event_classifier=_EvidenceBoundClassifier(lambda _path, **_kwargs: []),
            production=True,
            sha256="a" * 64,
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "extracted WAV SHA"):
            adapter.transcribe(context=_Context(self.video), input_artifacts=[])

    def test_production_audio_event_backend_requires_returned_receipt(self) -> None:
        class MissingReceiptClassifier(_EvidenceBoundClassifier):
            def classify(self, path, **kwargs):
                return {"events": self.callback(path, **kwargs)}

        adapter = WhisperAsrTranscriber(
            transcriber=_EvidenceBoundAsrBackend(lambda _path: [{"start": 0.1, "end": 0.2, "text": "hello"}]),
            audio_event_classifier=MissingReceiptClassifier(lambda _path, **_kwargs: []),
            production=True,
            sha256="a" * 64,
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "no evidence receipt"):
            adapter.transcribe(context=_Context(self.video), input_artifacts=[])

    def _ui_fixture(self, suffix: str = ".jpg") -> Path:
        path = self.root / f"ui{suffix}"
        image = Image.new("RGB", (200, 100), "white")
        image.save(path)
        return path

    @staticmethod
    def _ocr_records(*, shifted: bool = False, extra: bool = False):
        records = [
            {"text": "BUY NOW", "bbox": [60, 20, 140, 50], "confidence": 0.99},
        ]
        if shifted:
            records[0]["bbox"] = [5, 60, 85, 90]
        if extra:
            records.append({"text": "WRONG", "bbox": [10, 70, 70, 90], "confidence": 0.99})
        return records

    def test_ui_renderer_reencodes_png_and_verifies_text_and_layout(self) -> None:
        ui = self._ui_fixture(".jpg")
        expected_layout = [{"text": "BUY NOW", "bbox": [60, 20, 140, 50]}]
        context = _Context(self.video, ui=ui)
        result = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(lambda _path: self._ocr_records()),
            expected_text=["BUY NOW"],
            expected_layout=expected_layout,
            production=True,
            sha256="b" * 64,
        ).render_and_verify(context=context, input_artifacts=[])
        published = context.published[0]
        self.assertEqual(published["metadata"]["content_type"], "image/png")
        self.assertTrue(published["metadata"]["published_bytes"].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result["ocr_match_percent"], 100)
        self.assertEqual(result["layout_match_percent"], 100)

    def test_ui_renderer_rejects_extra_text_instead_of_reporting_100(self) -> None:
        ui = self._ui_fixture()
        context = _Context(self.video, ui=ui)
        adapter = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(lambda _path: self._ocr_records(extra=True)),
            expected_text=["BUY NOW"],
            expected_layout=[{"text": "BUY NOW", "bbox": [60, 20, 140, 50]}],
            production=True,
            sha256="b" * 64,
        )
        with self.assertRaisesRegex(ReplicationError, "text does not exactly match"):
            adapter.render_and_verify(context=context, input_artifacts=[])

    def test_ui_renderer_rejects_shifted_layout_instead_of_reporting_100(self) -> None:
        ui = self._ui_fixture()
        context = _Context(self.video, ui=ui)
        adapter = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(lambda _path: self._ocr_records(shifted=True)),
            expected_text=["BUY NOW"],
            expected_layout=[{"text": "BUY NOW", "bbox": [60, 20, 140, 50]}],
            production=True,
            sha256="b" * 64,
        )
        with self.assertRaisesRegex(ReplicationError, "layout does not match"):
            adapter.render_and_verify(context=context, input_artifacts=[])

    def test_ui_renderer_rejects_stale_ocr_records_digest(self) -> None:
        ui = self._ui_fixture()
        context = _Context(self.video, ui=ui)
        adapter = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(
                lambda _path: self._ocr_records(), corrupt_records_hash=True
            ),
            expected_text=["BUY NOW"],
            expected_layout=[{"text": "BUY NOW", "bbox": [60, 20, 140, 50]}],
            production=True,
            sha256="b" * 64,
        )
        with self.assertRaisesRegex(CapabilityUnavailable, "records SHA"):
            adapter.render_and_verify(context=context, input_artifacts=[])

    def test_ui_renderer_uses_parsed_app_store_artifact_not_raw_url(self) -> None:
        app_image = self._ui_fixture()
        truth = {
            "expected_text": ["BUY NOW"],
            "expected_layout": [{"text": "BUY NOW", "bbox": [60, 20, 140, 50]}],
        }
        context = _Context(self.video, app_artifact=app_image, app_metadata=truth)
        result = DeterministicUiRenderer(
            ocr_backend=_EvidenceBoundOcrBackend(lambda _path: self._ocr_records()),
            app_evidence_artifact_kind="app_store_screenshot",
            production=True,
            sha256="b" * 64,
        ).render_and_verify(context=context, input_artifacts=[])
        self.assertEqual(context.materialized_artifact_kinds, ["app_store_screenshot"])
        self.assertEqual(result["ui_truth_card"]["truth_basis"], "parsed-app-store-evidence")

    def test_production_ui_renderer_forbids_self_consistency(self) -> None:
        with self.assertRaisesRegex(ValueError, "self consistency"):
            DeterministicUiRenderer(
                ocr_backend=lambda _path: self._ocr_records(),
                allow_self_consistency=True,
                production=True,
                sha256="b" * 64,
            )


if __name__ == "__main__":
    unittest.main()
