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
        self.assertIn("Scene-surface text must be present in the replacement-control Image2 output", skill)
        self.assertIn("## 角色、场景与连续性锁定", skill)
        self.assertIn("## 逐镜反解", skill)

    def test_control_sheet_route_is_single_sheet_image2_only(self):
        documents = {
            "root skill": ROOT / "SKILL.md",
            "storyboard skill": BUNDLED / "SKILL.md",
            "director-board prompt template": BUNDLED / "references" / "daohuo_storyboard_prompt.md",
        }
        required = (
            "one complete source Cut contact sheet → one RunningHub Image2 call → one complete replacement-control sheet",
            "Per-Cut replacement generation and per-Cut source-frame validation are forbidden",
            "Local face swap, ComfyUI, InsightFace, desktop image editors, and any non-Image2 generator are forbidden",
            "A fixed-slot target image is target truth only and must never be accepted as the replacement-control sheet",
            "The director-board Image2 request must use the replacement-control sheet as reference image 1",
        )
        for name, path in documents.items():
            text = " ".join(path.read_text(encoding="utf-8").split())
            for phrase in required:
                with self.subTest(document=name, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_director_board_template_locks_control_sheet_priority(self):
        template = " ".join(
            (BUNDLED / "references" / "daohuo_storyboard_prompt.md")
            .read_text(encoding="utf-8")
            .split()
        )
        for required in (
            "Reference image 1 is the replacement-control sheet",
            "later target references for all non-authorized source attributes",
            "every other visual attribute from the replacement-control sheet must remain unchanged",
            "Do not alter the source pose, action, gesture, expression, gaze, mouth state",
        ):
            with self.subTest(required=required):
                self.assertIn(required, template)

    def test_final_seedance_references_are_fixed_for_source_fidelity_generation(self):
        for name, path in self.SOURCE_FIDELITY_REQUEST_DOCS.items():
            text = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(document=name):
                self.assertIn("`videoUrls[0]`", text)
                self.assertIn("usfr-multimodal-reference-binding/v2", text)
                self.assertIn("continuous-present-role-order/v1", text)
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

    def test_visible_text_is_routed_by_its_physical_carrier(self):
        documents = {
            "root skill": ROOT / "SKILL.md",
            "storyboard skill": BUNDLED / "SKILL.md",
            "prompt reference": BUNDLED / "references" / "seedance-prompt.md",
        }
        for name, path in documents.items():
            text = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(document=name):
                self.assertIn("scene-surface text", text)
                self.assertIn("deterministic overlay text", text)
                self.assertIn("moves, bends, folds, rotates, occludes, and tears with its carrier", text)
                self.assertIn("must be written explicitly into the Seedance Cut prompt", text)

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
