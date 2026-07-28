import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT.parent
LEGACY_FACTORY = SKILLS_ROOT / "tiktok-ai-video-replication-factory"
LEGACY_SEEDANCE = SKILLS_ROOT / "seedance-storyboard-replication"
SEEDANCE_ROOT = ROOT / "bundled-skills" / "seedance-storyboard-replication"


class SkillCleanupContractTest(unittest.TestCase):
    def test_lightweight_bundle_has_no_legacy_control_plane_files(self):
        forbidden = (
            "server/repository.py",
            "server/service.py",
            "server/driver.py",
            "server/worker.py",
            "server/runtime.py",
            "server/models.py",
            "server/state_machine.py",
            "server/migrations/001_initial.sql",
            "server/migrations/002_segment_scoped_create_video.sql",
            "schemas/run.schema.json",
            "schemas/event.schema.json",
            "references/event-contract.md",
            "references/persistence-contract.md",
            "BASELINE.md",
        )
        existing = [relative for relative in forbidden if (ROOT / relative).exists()]
        self.assertEqual(existing, [])

    def test_legacy_factory_is_routing_only(self):
        self.assertFalse(LEGACY_FACTORY.exists())

    def test_legacy_seedance_entry_is_routing_only(self):
        self.assertFalse(LEGACY_SEEDANCE.exists())

    def test_canonical_runtime_has_no_retired_cos_or_ark_surface(self):
        self.assertFalse((SEEDANCE_ROOT / "scripts" / "cos_publish.py").exists())
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                SEEDANCE_ROOT / "scripts" / "config.py",
                SEEDANCE_ROOT / "scripts" / "runninghub_seedance_submit.py",
                SEEDANCE_ROOT / "references" / "seedance.env.example",
            )
        ).lower()
        for retired in (
            "tencent_cos",
            "tkagent_cos",
            "cos_publish",
            "ark_api_key",
            "ark_base_url",
            "ark_seedance_model",
            "arkseedanceclient",
            "youdao",
            "asset://",
        ):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, combined)

    def test_populated_directories_have_no_gitkeep(self):
        self.assertEqual(list(ROOT.rglob(".gitkeep")), [])

    def test_skill_frontmatter_files_have_no_utf8_bom(self):
        skill_files = [ROOT / "SKILL.md", *ROOT.rglob("SKILL.md")]
        for path in skill_files:
            with self.subTest(path=path):
                self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_bundle_manifest_has_no_standalone_source_paths(self):
        manifest = json.loads(
            (ROOT / "references" / "bundle_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        for module in manifest["modules"]:
            self.assertNotIn("source", module)
            self.assertTrue(module["bundled_path"].startswith("bundled-skills/"))

    def test_only_the_runninghub_standard_submitter_remains(self):
        submit = (SEEDANCE_ROOT / "scripts" / "runninghub_seedance_submit.py").read_text(
            encoding="utf-8"
        )
        timeline = (SEEDANCE_ROOT / "scripts" / "timeline_splice.py").read_text(
            encoding="utf-8"
        )
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertFalse((SEEDANCE_ROOT / "scripts" / "seedance_submit.py").exists())
        self.assertFalse((SEEDANCE_ROOT / "references" / "youdao-api.md").exists())
        self.assertIn("--approved-request-sha256", submit)
        self.assertIn("LEGACY_KIND_MAP", timeline)
        for required in (
            "seedance-2.0-fast-token",
            "720p",
            "9:16",
            "seedance-20",
            "opaque_ui_demo",
            "generated_ui_demo",
            "excluded_app_end_card",
        ):
            self.assertIn(required, skill + submit + timeline)


if __name__ == "__main__":
    unittest.main()
