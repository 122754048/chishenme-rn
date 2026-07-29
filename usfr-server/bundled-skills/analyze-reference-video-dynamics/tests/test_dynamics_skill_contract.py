import copy
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_dynamics import validate  # noqa: E402


def valid_contract():
    return {
        "contract": "reference-video-dynamics",
        "contract_version": 1,
        "reference_duration_us": 1_000_000,
        "source_width": 720,
        "source_height": 1280,
        "fps_num": 30,
        "fps_den": 1,
        "source_cut_count": 1,
        "source_cuts": [
            {
                "cut": 1,
                "start_us": 0,
                "end_us": 1_000_000,
                "subject_presence": "identifiable",
                "content_roles": ["creator"],
                "scene": "creator at a table",
                "action": "raises the product and settles into a hold",
                "camera": "locked medium shot",
                "transition": "starts on first decoded frame",
                "end_state": "product held upright at chest height",
                "certainty": "certain",
            }
        ],
        "source_events": [
            {
                "event": 1,
                "kind": "dialogue",
                "start_us": 0,
                "end_us": 1_000_000,
                "source_cut_start": 1,
                "source_cut_end": 1,
                "text": "example",
                "certainty": "certain",
            }
        ],
        "notes": [],
    }


class DynamicsSkillContractTest(unittest.TestCase):
    def test_skill_requires_gpt_adaptive_evidence(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for required in (
            "GPT",
            "adaptive keyframes",
            "contact sheets",
            "boundary frames",
            "separate audio transcription",
        ):
            self.assertIn(required, skill)

    def test_skill_freezes_and_hands_off_one_server_safe_evidence_plan(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for required in (
            "scripts/adaptive_evidence_plan.py",
            "evidence_plan",
            "semantic backend",
            "request SHA-256",
            "lease-local path",
        ):
            self.assertIn(required, skill)

    def test_external_video_upload_files_are_absent(self):
        for relative in (
            "scripts/build_external_analyzer_packet.py",
            "scripts/youdao_kimi_video_analyze.py",
            "references/external-video-analyzer-contract.md",
            "references/youdao-kimi-k27-api.md",
            "references/youdao-qwen37plus-api.md",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_external_analyzer_provenance_is_rejected(self):
        candidate = copy.deepcopy(valid_contract())
        candidate["analysis_provenance"] = {
            "semantic_analyzer_provider": "external",
            "input_mode": "full_video",
            "probe_supplied": True,
            "external_output_untrusted_until_validated": True,
        }
        with self.assertRaisesRegex(
            ValueError, "external analyzer provenance is not allowed"
        ):
            validate(candidate)


if __name__ == "__main__":
    unittest.main()
