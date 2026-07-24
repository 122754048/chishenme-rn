from pathlib import Path
import unittest


FACTORY_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = FACTORY_ROOT.parent
CANONICAL_ROOT = FACTORY_ROOT


class SkillAliasContractTest(unittest.TestCase):
    def test_canonical_skill_has_new_name_and_invocation(self):
        skill = (CANONICAL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(skill, r"(?m)^name: universal-source-fidelity-replication$")
        interface = (CANONICAL_ROOT / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("$universal-source-fidelity-replication", interface)

    def test_deployable_bundle_contains_no_legacy_entry_skills(self):
        legacy_paths = (
            SKILLS_ROOT / "tiktok-ai-video-replication-factory" / "SKILL.md",
            SKILLS_ROOT / "seedance-storyboard-replication" / "SKILL.md",
        )
        for path in legacy_paths:
            with self.subTest(path=path):
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
