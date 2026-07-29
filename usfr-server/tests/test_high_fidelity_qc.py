import unittest
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from high_fidelity_qc import (  # noqa: E402
    _dimensions_digest,
    _factor_scores_digest,
    build_qc_extension,
    normalize_asr,
    validate_qc_extension,
)


class HighFidelityQCTest(unittest.TestCase):
    def _evidence(self, evidence_id, *, kind="frame", method="deterministic_measurement"):
        return {
            "evidence_id": evidence_id,
            "kind": kind,
            "method": method,
            "source_ref": {
                "artifact_sha256": "a" * 64,
                "pointer": "source_fidelity_contract#/cuts/C01",
                "start_ms": 0,
                "end_ms": 1000,
            },
            "target_ref": {
                "artifact_sha256": "b" * 64,
                "pointer": "final/result.mp4",
                "start_ms": 0,
                "end_ms": 1000,
            },
            "observation": "source and target anchors were compared",
        }

    def _dimensions(self):
        return {
            "timeline_route": {"score": 100, "criticality": "H", "evidence": [self._evidence("E-TIMELINE")]},
            "background_lighting": {"score": 90, "criticality": "M", "evidence": [self._evidence("E-BG")]},
            "composition_camera": {"score": 90, "criticality": "M", "evidence": [self._evidence("E-CAMERA")]},
            "performance": {"score": 90, "criticality": "H", "evidence": [self._evidence("E-PERFORMANCE")]},
            "action_chain": {"score": 90, "criticality": "H", "evidence": [self._evidence("E-ACTION")]},
            "truth": {"score": 90, "criticality": "H", "evidence": [self._evidence("E-TRUTH")]},
            "voiceover_audio": {"score": 90, "criticality": "H", "evidence": [self._evidence("E-AUDIO", kind="audio")]},
            "overlays": {"score": 90, "criticality": "M", "evidence": [self._evidence("E-OVERLAY")]},
            "commercial": {"score": 90, "criticality": "H", "evidence": [self._evidence("E-COMMERCIAL")]},
            "continuity_technical": {"score": 90, "criticality": "H", "evidence": [self._evidence("E-TECH", kind="probe")]},
        }

    def test_weighted_extension_passes_only_with_all_hard_gates(self):
        report = build_qc_extension(dimensions=self._dimensions(), route_coverage=100, ui_ocr=100, hard_failures=[])
        validate_qc_extension(report)
        self.assertGreaterEqual(report["total_score"], 85)

    def test_low_high_criticality_or_ui_ocr_is_hard_failure(self):
        dimensions = self._dimensions()
        dimensions["action_chain"]["score"] = 80
        report = build_qc_extension(dimensions=dimensions, route_coverage=100, ui_ocr=100, hard_failures=[])
        with self.assertRaises(ValueError):
            validate_qc_extension(report)

    def test_voiceover_audio_requires_high_criticality_and_audio_evidence(self):
        dimensions = self._dimensions()
        dimensions["voiceover_audio"]["criticality"] = "M"
        dimensions["voiceover_audio"]["score"] = 0
        with self.assertRaisesRegex(ValueError, "voiceover_audio.*criticality"):
            build_qc_extension(
                dimensions=dimensions,
                route_coverage=100,
                ui_ocr=100,
                hard_failures=[],
            )

        dimensions = self._dimensions()
        dimensions["voiceover_audio"]["evidence"] = [
            self._evidence("E-AUDIO-FRAME", kind="frame")
        ]
        with self.assertRaisesRegex(ValueError, "voiceover_audio.*audio/ASR"):
            build_qc_extension(
                dimensions=dimensions,
                route_coverage=100,
                ui_ocr=100,
                hard_failures=[],
            )
        dimensions = self._dimensions()
        report = build_qc_extension(dimensions=dimensions, route_coverage=100, ui_ocr=99, hard_failures=[])
        with self.assertRaises(ValueError):
            validate_qc_extension(report)

    def test_asr_normalization_preserves_negation_and_numbers(self):
        self.assertEqual(normalize_asr("  Don't  miss  2 offers! "), "don't miss 2 offers")

    def test_rejects_self_asserted_scores_without_traceable_source_and_target_evidence(self):
        dimensions = self._dimensions()
        dimensions["performance"]["evidence"] = [{"kind": "frame"}]
        with self.assertRaisesRegex(ValueError, "performance.*evidence"):
            build_qc_extension(
                dimensions=dimensions,
                route_coverage=100,
                ui_ocr=100,
                hard_failures=[],
            )

    def test_rejects_evidence_without_measurement_method_or_immutable_digest(self):
        dimensions = self._dimensions()
        del dimensions["action_chain"]["evidence"][0]["method"]
        with self.assertRaisesRegex(ValueError, "method"):
            build_qc_extension(dimensions=dimensions, route_coverage=100, ui_ocr=100, hard_failures=[])

        dimensions = self._dimensions()
        dimensions["truth"]["evidence"][0]["target_ref"]["artifact_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(ValueError, "artifact_sha256"):
            build_qc_extension(dimensions=dimensions, route_coverage=100, ui_ocr=100, hard_failures=[])

    def test_high_criticality_factor_score_requires_traceable_evidence(self):
        with self.assertRaisesRegex(ValueError, "factor_scores.*evidence"):
            build_qc_extension(
                dimensions=self._dimensions(),
                route_coverage=100,
                ui_ocr=100,
                hard_failures=[],
                factor_scores={"HFH.C01.PERFORMANCE.GAZE": {"score": 100, "criticality": "H", "evidence": []}},
            )

    def test_qc_schema_accepts_only_the_traceable_evidence_shape(self):
        from jsonschema import Draft202012Validator

        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "high_fidelity_qc.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        report = build_qc_extension(dimensions=self._dimensions(), route_coverage=100, ui_ocr=100, hard_failures=[])
        Draft202012Validator(schema).validate(report)

    def test_qc_schema_accepts_current_run_media_bindings(self):
        from jsonschema import Draft202012Validator

        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "high_fidelity_qc.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        report = build_qc_extension(
            dimensions=self._dimensions(),
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
            media_bindings={
                "final_output_sha256": "b" * 64,
                "current_run_source_sha256s": ["a" * 64],
            },
        )

        Draft202012Validator(schema).validate(report)

    def test_qc_schema_accepts_independent_evaluator_receipt(self):
        from high_fidelity_qc import _dimensions_digest, _factor_scores_digest
        from jsonschema import Draft202012Validator

        dimensions = self._dimensions()
        factors = {
            "HFH.C01.ACTION.ENDPOINT": {
                "score": 100,
                "criticality": "H",
                "evidence": [self._evidence("E-FACTOR")],
            }
        }
        media_bindings = {
            "final_output_sha256": "b" * 64,
            "current_run_source_sha256s": ["a" * 64],
        }
        receipt = {
            "schema_version": "high-fidelity-qc-evaluator-receipt/v1",
            "provenance": "independent_evaluator",
            "implementation": "tests.evidence-bound-qc",
            "version": "test-v1",
            "model_id": "test-qc-model",
            "model_sha256": "c" * 64,
            "request_sha256": "d" * 64,
            "response_sha256": "e" * 64,
            "dimensions_sha256": _dimensions_digest(dimensions),
            "factor_scores_sha256": _factor_scores_digest(factors),
            "final_output_sha256": "b" * 64,
            "current_run_source_sha256s": ["a" * 64],
        }
        report = build_qc_extension(
            dimensions=dimensions,
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
            factor_scores=factors,
            media_bindings=media_bindings,
            evaluator_receipt=receipt,
        )
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "high_fidelity_qc.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(report)

    def test_active_validation_requires_an_independent_evaluator_receipt(self):
        report = build_qc_extension(
            dimensions=self._dimensions(),
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
            media_bindings={
                "final_output_sha256": "b" * 64,
                "current_run_source_sha256s": ["a" * 64],
            },
        )
        with self.assertRaisesRegex(ValueError, "evaluator receipt"):
            validate_qc_extension(report, require_evaluator_receipt=True)

    def test_active_validation_requires_media_bindings_with_evaluator_receipt(self):
        report = build_qc_extension(
            dimensions=self._dimensions(),
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
        )
        report["evaluator_receipt"] = {
            "schema_version": "high-fidelity-qc-evaluator-receipt/v1",
            "provenance": "independent_evaluator",
            "implementation": "tests.evidence-bound-qc",
            "version": "test-v1",
            "model_id": "test-qc-model",
            "model_sha256": "c" * 64,
            "request_sha256": "d" * 64,
            "response_sha256": "e" * 64,
            "dimensions_sha256": _dimensions_digest(self._dimensions()),
            "factor_scores_sha256": _factor_scores_digest({}),
            "final_output_sha256": "b" * 64,
            "current_run_source_sha256s": ["a" * 64],
        }
        with self.assertRaisesRegex(ValueError, "media_bindings"):
            validate_qc_extension(report, require_evaluator_receipt=True)

    def test_active_evaluator_receipt_binds_exact_media_and_provenance(self):
        receipt = {
            "schema_version": "high-fidelity-qc-evaluator-receipt/v1",
            "provenance": "independent_evaluator",
            "implementation": "qa.qwen-vl-comparator",
            "version": "2026.07.21",
            "model_id": "qwen2.5-vl",
            "model_sha256": "c" * 64,
            "request_sha256": "d" * 64,
            "response_sha256": "e" * 64,
            "dimensions_sha256": _dimensions_digest(self._dimensions()),
            "factor_scores_sha256": _factor_scores_digest({}),
            "final_output_sha256": "b" * 64,
            "current_run_source_sha256s": ["a" * 64],
        }
        report = build_qc_extension(
            dimensions=self._dimensions(),
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
            media_bindings={
                "final_output_sha256": "b" * 64,
                "current_run_source_sha256s": ["a" * 64],
            },
            evaluator_receipt=receipt,
        )
        validate_qc_extension(report, require_evaluator_receipt=True)
        report["evaluator_receipt"]["final_output_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "evaluator receipt|final output"):
            validate_qc_extension(report, require_evaluator_receipt=True)


if __name__ == "__main__":
    unittest.main()
