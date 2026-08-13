import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "bundled-skills" / "seedance-storyboard-replication"


class SourceFidelityDocumentationContractTest(unittest.TestCase):
    def test_document_ownership_is_layered(self):
        main = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        fixed = (ROOT / "references" / "fixed-input-slot-contract.md").read_text(encoding="utf-8")
        v2 = (ROOT / "references" / "video-edit-v2-contract.md").read_text(encoding="utf-8")
        storyboard = (BUNDLED / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Canonical runtime contract", main)
        self.assertIn("fixed-input-slots/v2", fixed)
        self.assertIn("uploaded_tags == binding_tags == prompt_tags", v2)
        self.assertIn("legacy quarantine", storyboard.casefold())
        self.assertIn("not a v2 workflow owner", storyboard)

    def test_main_documents_one_script_gate_ui_routes_and_audio_lane_semantics(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for required in (
            "one user file", "one script approval", "plan_segments",
            "source UI keep",
            "deterministic FFmpeg splice", "App asset board + Seedance edit",
            "music-only", "voice/dialogue", "H3 MV edit", "UI monologue",
        ):
            self.assertIn(required, text)
        self.assertNotIn("storyboard approval", text.casefold())

    def test_active_contracts_document_frame_midpoint_fallback_and_seam_qc(self):
        paths = (ROOT / "SKILL.md", ROOT / "references" / "video-edit-v2-contract.md")
        for path in paths:
            text = " ".join(path.read_text(encoding="utf-8").split())
            for required in (
                "natural Cut priority",
                "frame_midpoint_fallback",
                "fixed 24 fps grid",
                "forced-continuity-boundary/v1",
                "30 seconds",
                "identity",
                "object",
                "contact",
                "camera",
                "audio",
                "black frames",
                "duplicate frames",
                "missing frames",
            ):
                self.assertIn(required, text, msg=f"{path.name} is missing {required!r}")

    def test_canonical_contract_routes_physical_and_deterministic_text(self):
        text = " ".join((ROOT / "references" / "video-edit-v2-contract.md").read_text(encoding="utf-8").split())
        for required in (
            "generation_surface", "physical text", "deterministic_overlay",
            "deterministic_ui", "approved time window", "approved region",
        ):
            self.assertIn(required, text)

    def test_active_documents_do_not_restore_control_or_invocation_workflows(self):
        paths = (ROOT / "SKILL.md", BUNDLED / "SKILL.md", ROOT / "references" / "video-edit-v2-contract.md")
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for forbidden in ("replacement-control", "Invocation A", "Invocation B"):
            self.assertNotIn(forbidden, combined)

    def test_dependency_map_is_v2_authority_chain_with_legacy_quarantine(self):
        text = (ROOT / "references" / "dependency-map.md").read_text(encoding="utf-8")
        self.assertIn("intake → analysis/script approval → asset boards → plan_segments → compile/audit", text)
        self.assertIn("provider pass(es) → deterministic assembly/audio → QC", text)
        self.assertIn("server/audio_lane_router.py", text)
        self.assertIn("Legacy quarantine", text)
        self.assertIn("not a fallback", text)

    def test_active_v2_state_and_api_docs_do_not_restore_storyboard_gate(self):
        state = (ROOT / "references" / "run-state-machine.md").read_text(encoding="utf-8")
        api = (ROOT / "references" / "server-api-contract.md").read_text(encoding="utf-8")
        for text in (state, api):
            self.assertIn("one script approval", text)
            self.assertIn("Legacy quarantine", text)
        self.assertIn("plan_segments", state)
        for forbidden in ("await_storyboard_approval", "generate_storyboards", "storyboard approval"):
            self.assertNotIn(forbidden, state.casefold())
        self.assertNotIn("Equivalent storyboard list/revise/approve endpoints.", api)
