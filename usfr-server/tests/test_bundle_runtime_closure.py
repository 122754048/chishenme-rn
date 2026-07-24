from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_bundle import (  # noqa: E402
    REQUIRED_MODULE_FILES,
    REQUIRED_SERVER_FILES,
    runtime_skill_sha256,
    verify_bundle,
)


REQUIRED_SEEDANCE_RUNTIME_SKILLS = (
    "seedance-20",
    "seedance-prompt",
    "seedance-antislop",
    "seedance-camera",
    "seedance-motion",
    "seedance-lighting",
    "seedance-characters",
    "seedance-audio",
    "seedance-sequence",
    "seedance-style",
    "seedance-vfx",
    "seedance-vocab-en",
    "seedance-vocab-es",
    "seedance-vocab-ja",
    "seedance-vocab-ko",
    "seedance-vocab-zh",
)


class BundleRuntimeClosureTest(unittest.TestCase):
    def test_server_and_bundled_direct_dependencies_are_required(self):
        self.assertIn("server/digests.py", REQUIRED_SERVER_FILES)
        self.assertIn("server/ephemeral_worker.py", REQUIRED_SERVER_FILES)
        self.assertIn("server/ephemeral_driver.py", REQUIRED_SERVER_FILES)
        self.assertIn("server/high_fidelity_projection.py", REQUIRED_SERVER_FILES)
        self.assertIn("server/audio_mixer.py", REQUIRED_SERVER_FILES)
        self.assertIn("server/performance_audio_contracts.py", REQUIRED_SERVER_FILES)
        for relative in (
            "scripts/config.py",
            "scripts/concat_videos.py",
            "scripts/media_quality.py",
            "scripts/segment_plan.py",
            "scripts/runninghub_image2.py",
            "scripts/seedance_submit.py",
            "scripts/timeline_splice.py",
        ):
            self.assertIn(relative, REQUIRED_MODULE_FILES["seedance-storyboard-replication"])
        self.assertIn(
            "scripts/adaptive_evidence_plan.py",
            REQUIRED_MODULE_FILES["analyze-reference-video-dynamics"],
        )

    def test_manifest_declares_direct_runtime_dependencies(self):
        manifest = json.loads(
            (ROOT / "references" / "bundle_manifest.json").read_text(encoding="utf-8")
        )
        runtime_paths = {item["path"] for item in manifest.get("runtime_files", [])}
        for relative in (
            "server/digests.py",
            "server/ephemeral_worker.py",
            "server/ephemeral_driver.py",
            "server/capabilities.py",
            "server/audio_mixer.py",
            "server/performance_audio_contracts.py",
            "bundled-skills/seedance-storyboard-replication/scripts/config.py",
            "bundled-skills/seedance-storyboard-replication/scripts/concat_videos.py",
            "bundled-skills/seedance-storyboard-replication/scripts/media_quality.py",
            "bundled-skills/seedance-storyboard-replication/scripts/segment_plan.py",
            "bundled-skills/seedance-storyboard-replication/scripts/runninghub_image2.py",
            "bundled-skills/seedance-storyboard-replication/scripts/seedance_submit.py",
            "bundled-skills/seedance-storyboard-replication/scripts/timeline_splice.py",
            "bundled-skills/analyze-reference-video-dynamics/scripts/probe_video.py",
            "bundled-skills/analyze-reference-video-dynamics/scripts/validate_dynamics.py",
            "bundled-skills/analyze-reference-video-dynamics/scripts/validate_dynamics_quality.py",
            "bundled-skills/analyze-reference-video-dynamics/scripts/validate_high_fidelity_extension.py",
            "bundled-skills/analyze-reference-video-dynamics/scripts/compare_analyzer_results.py",
            "bundled-skills/analyze-reference-video-dynamics/scripts/adaptive_evidence_plan.py",
            "bundled-skills/parse-app-store-evidence/scripts/parse_app_store.py",
            "bundled-skills/replicate-source-ui-overlays/scripts/overlay_frame_plan.py",
            "bundled-skills/replicate-source-ui-overlays/scripts/validate_overlay_contract.py",
            "schemas/stage_capabilities.schema.json",
        ):
            self.assertIn(relative, runtime_paths)

    def test_declared_dependency_files_exist(self):
        self.assertEqual(verify_bundle(ROOT), [])

    def test_seedance_runtime_closure_is_packaged_and_hash_verified(self):
        manifest_path = ROOT / "references" / "runtime_skill_manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = {item["name"]: item for item in manifest["dependencies"]}
        self.assertEqual(set(records), set(REQUIRED_SEEDANCE_RUNTIME_SKILLS))
        for name, record in records.items():
            package_path = record["package_path"]
            self.assertTrue(package_path.startswith("runtime-skills/seedance-20/"))
            self.assertEqual(runtime_skill_sha256(ROOT / package_path), record["sha256"])
            self.assertEqual(record["version"], "6.6.0")

        self.assertTrue((ROOT / "runtime-skills" / "seedance-20" / "LICENSE").is_file())


if __name__ == "__main__":
    unittest.main()
