from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HighFidelityEvidenceMatrixTest(unittest.TestCase):
    def test_matrix_records_media_binding_hardening(self):
        matrix = (ROOT / "references" / "high-fidelity-evidence-matrix.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("TRANSITION_OUTPUT_SHA256_MISMATCH", matrix)
        self.assertIn("media_bindings", matrix)
        self.assertIn("current final MP4 SHA-256", matrix)
        self.assertIn("profile_snapshot", matrix)
        self.assertIn("stage_capability_manifest", matrix)
        self.assertIn("source-origin semantic layer pass", matrix)
        self.assertIn("media_origin != source_interval", matrix)

    def test_matrix_and_deployment_contract_record_closed_timeline_and_loader_rules(self):
        matrix = (ROOT / "references" / "high-fidelity-evidence-matrix.md").read_text(
            encoding="utf-8"
        )
        deployment = (
            ROOT / "references" / "deployment-runtime-contract.md"
        ).read_text(encoding="utf-8")
        combined = " ".join((matrix + "\n" + deployment).split())
        for required in (
            "global closed set",
            "ordinary generated media cannot bypass exact Segment/Cut bindings",
            "natural decoded media duration",
            "no padding, freeze, loop, or hidden retime",
            "per-Segment audio/video boundaries align",
            "every non-source carrier and every declared source transition",
            "exact final-output-bound receipt",
            "source and omitted routes reject any media binding",
            "manifest route, placement, and omission sets are exact",
            "absolute paths to bundled timeline and concat dependencies",
            "profile remains Shadow",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)


if __name__ == "__main__":
    unittest.main()
