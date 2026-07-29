import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "bundled-skills" / "seedance-storyboard-replication"


class SourceFidelityDocumentationContractTest(unittest.TestCase):
    SOURCE_FIDELITY_REQUEST_DOCS = {
        "root skill": ROOT / "SKILL.md",
        "fixed-slot contract": ROOT / "references" / "fixed-input-slot-contract.md",
        "deployment guide": ROOT / "references" / "server-deployment-step-by-step.md",
        "storyboard skill": BUNDLED / "SKILL.md",
        "integrity gate": BUNDLED / "references" / "seedance-20-integrity-gate.md",
        "provider reference": BUNDLED / "references" / "runninghub-standard-seedance-api.md",
        "prompt reference": BUNDLED / "references" / "seedance-prompt.md",
        "source-fidelity contract": ROOT / "references" / "universal-source-fidelity-contract.md",
    }

    def test_root_skill_mandates_the_visual_provenance_chain(self):
        skill = " ".join((ROOT / "SKILL.md").read_text(encoding="utf-8").split())
        self.assertIn(
            "source Cut frames → replacement-control sheet → approved director board",
            skill,
        )
        self.assertIn("deterministically materialized on the approved director board", skill)
        self.assertIn("## 角色、场景与连续性锁定", skill)
        self.assertIn("## 逐镜反解", skill)

    def test_final_seedance_references_are_fixed_for_source_fidelity_generation(self):
        for name, path in self.SOURCE_FIDELITY_REQUEST_DOCS.items():
            text = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(document=name):
                self.assertIn("matching original source segment at `videoUrls[0]`", text)
                self.assertIn("approved director board at `imageUrls[0]` / `@Image1`", text)
                self.assertIn("only fixed-slot target references", text)
                self.assertIn("must never be sent to Seedance", text)
                self.assertIn("2-15 second", text)
                self.assertIn("full source video must never be uploaded", text)

    def test_source_fidelity_docs_do_not_offer_an_empty_video_reference_escape_hatch(self):
        forbidden = (
            "`videoUrls=[]`",
            "video-reference run may carry",
            "When `videoUrls[0]` is present",
            "upstream analysis input only",
            "may carry exactly one matching source slice",
        )
        for name, path in self.SOURCE_FIDELITY_REQUEST_DOCS.items():
            text = " ".join(path.read_text(encoding="utf-8").split())
            for phrase in forbidden:
                with self.subTest(document=name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_confirmed_visible_text_is_a_deterministic_board_layer_not_seedance_glyph_work(self):
        documents = {
            "root skill": ROOT / "SKILL.md",
            "storyboard skill": BUNDLED / "SKILL.md",
            "prompt reference": BUNDLED / "references" / "seedance-prompt.md",
        }
        for name, path in documents.items():
            text = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(document=name):
                self.assertIn("deterministic approved-text layer", text)
                self.assertIn("must not generate, read, or transcribe", text)
                self.assertIn("model-generated scene text", text)
                self.assertIn("does not suppress the deterministic approved-text layer", text)

    def test_audio_song_contract_is_preserved(self):
        skill = " ".join((ROOT / "SKILL.md").read_text(encoding="utf-8").split())
        for required in (
            "Without an uploaded audio extension, keep the original source audio.",
            "timestamped lyrics in the editable script",
            "explicitly confirmed on-camera performer",
            "Multi-person/multi-vocalist ambiguity blocks",
            "cut-in/cut-out matches the source video exactly",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill)
