from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProductionReadinessStatusTest(unittest.TestCase):
    def test_status_records_latest_verified_gates_without_promoting_shadow(self):
        status = (ROOT / "references" / "production-readiness-status.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("1142 passed, 1 skipped", status)
        self.assertIn("in-process control-flow MP4", status)
        self.assertIn("real-material canonical splice MP4", status)
        self.assertIn("Docker", status)
        self.assertIn("USFR_PORT_FACTORY", status)
        self.assertIn("not ad-grade quality evidence", status)
        self.assertIn("36-case immutable release candidate", status)
        self.assertIn("incremental smoke/impact selection", status)
        self.assertIn("release-time lightweight verifier", status)
        self.assertIn("78 referenced fixture assets are absent", status)
        self.assertIn("optional backend policy remains default-disabled", status)
        self.assertIn("same-case evaluator receipts", status)
        self.assertIn("immutable case-result gate", status)
        self.assertIn("local fixture placeholders", status)
        self.assertIn("bounded case-matrix runner", status)
        self.assertIn("per-case checkpoint", status)
        self.assertIn("private fixture builder", status)
        self.assertIn("byte-level deduplication", status)
        self.assertIn("`3` Bundle-closure tests", status)
        self.assertIn("EVIDENCE_DIGEST_UNBOUND", status)
        self.assertIn("TRANSITION_OUTPUT_SHA256_MISMATCH", status)
        self.assertIn("current final MP4 SHA-256", status)
        self.assertIn("profile_snapshot", status)
        self.assertIn("stage_capability_manifest", status)
        self.assertIn("remains `Shadow`", status)
        self.assertIn("real model", status)
        self.assertIn("E2E evidence", status)
        self.assertIn("complete timeline renderer", status)
        self.assertIn("owned `uploads/{upload_scope}/`", status)
        self.assertIn("language-only object upload", status)
        self.assertIn("production-active final-audio delivery", status)
        self.assertIn("independently re-decodes current", status)
        self.assertIn("pre-bound/deferred regions", status)
        self.assertIn("canonical preflight before the first", status)


if __name__ == "__main__":
    unittest.main()
