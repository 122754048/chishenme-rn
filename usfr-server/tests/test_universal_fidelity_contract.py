from __future__ import annotations

import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEEDANCE_ROOT = ROOT / "bundled-skills" / "seedance-storyboard-replication"
sys.path.insert(0, str(SEEDANCE_ROOT / "scripts"))
from runninghub_seedance_submit import RUNNINGHUB_STANDARD_PAYLOAD_FIELDS  # noqa: E402


class UniversalFidelityFactoryContractTest(unittest.TestCase):
    def test_factory_contract_is_universal_and_keeps_speed_invariants(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        interface = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        combined = skill + "\n" + interface
        for required in (
            "Source Fidelity Contract",
            "physical product",
            "App or digital product",
            "service or brand video",
            "Level 0",
            "Level 1",
            "Level 2",
            "30-minute production target",
            "not a cancellation deadline",
            "cached contracts",
            "concurrent",
            "duplicate paid tasks",
        ):
            self.assertIn(required, combined)

    def test_factory_requires_the_three_mutually_exclusive_app_regions(self):
        main = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        bundled = (SEEDANCE_ROOT / "SKILL.md").read_text(encoding="utf-8")
        timeline = (SEEDANCE_ROOT / "references" / "timeline-slice-contract.md").read_text(
            encoding="utf-8"
        )
        combined = "\n".join((main, bundled, timeline))
        for required in (
            "excluded_app_end_card",
            "opaque_ui_demo",
            "generated_ui_demo",
            "ui_truth_card.json",
            "ui_render_contract.json",
            "transition_shell",
            "mutually exclusive",
        ):
            self.assertIn(required, combined)

    def test_app_end_card_has_exact_two_route_contract(self):
        timeline = (SEEDANCE_ROOT / "references" / "timeline-slice-contract.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "tail_video",
            "opaque replacement media",
            "omit from the text script",
            "omit from every storyboard",
            "omit from the Seedance prompt",
            "omit from paid generation duration",
            "preserve the source entry transition",
            "trim_to_active_content",
            "omit_source_tail",
            "last active frame",
            "no black filler",
        ):
            self.assertIn(required, timeline)

    def test_supplied_tail_card_applies_only_after_terminal_region_classification(self):
        main = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "Once a terminal source interval is classified as "
            "`excluded_app_end_card`",
            main,
        )

    def test_supplied_app_end_card_uses_active_content_duration_without_time_stretch(self):
        main = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        timeline = (SEEDANCE_ROOT / "references" / "timeline-slice-contract.md").read_text(
            encoding="utf-8"
        )
        combined = main + "\n" + timeline
        for required in (
            "trim_to_active_content",
            "leading and trailing black",
            "no final-frame padding",
            "no atempo",
            "effective replacement duration",
            "recalculate the source-to-output mapping",
            "omit_source_end_card",
        ):
            self.assertIn(required, combined)
        for forbidden in (
            "source_end_card_keep",
            "preserve the source interval locally",
            "complete natural duration",
        ):
            self.assertNotIn(forbidden, combined)

    def test_supplied_ui_preserves_active_duration_without_freeze_or_padding(self):
        main = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        bundled = (SEEDANCE_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for document in (main, bundled):
            with self.subTest(document=document[:40]):
                self.assertIn("preserve its active-content duration", document)
                self.assertIn("recalculate the source-to-output mapping", document)
                self.assertIn("no final-frame padding", document)
                self.assertIn("no audio padding", document)
                self.assertIn("no atempo", document)
                self.assertNotIn("final-frame padding without speed change", document)

    def test_generated_ui_requires_target_truth_and_exact_ocr(self):
        timeline = (SEEDANCE_ROOT / "references" / "timeline-slice-contract.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "target-owned UI evidence",
            "deterministic render",
            "OCR must match 100%",
            "garbled text",
            "pseudo-text",
            "layout",
            "block the run",
        ):
            self.assertIn(required, timeline)
        self.assertNotIn(
            "If the UI slice or Logo slice is not supplied, omit that interval entirely",
            timeline,
        )

    def test_media_splice_contract_is_fail_closed_for_black_padding_and_ui_evidence(self):
        main = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        bundled = (SEEDANCE_ROOT / "SKILL.md").read_text(encoding="utf-8")
        timeline = (SEEDANCE_ROOT / "references" / "timeline-slice-contract.md").read_text(
            encoding="utf-8"
        )
        universal = (ROOT / "references" / "universal-source-fidelity-contract.md").read_text(
            encoding="utf-8"
        )
        combined = "\n".join((main, bundled, timeline, universal))
        for required in (
            "12% safe cover-crop limit",
            "one full black frame",
            "no final-frame padding",
            "no audio padding",
            "splice-boundary black",
            "video stream duration",
            "ui_truth_card_sha256",
            "ui_render_contract_sha256",
            "ocr_match_percent",
            "layout_match_percent",
            "display rotation metadata",
            "display dimensions",
        ):
            self.assertIn(required, combined)

    def test_high_fidelity_profile_reference_freezes_framework_and_latest_media_policy(self):
        profile = (ROOT / "references" / "high-fidelity-hybrid-v1.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "seven fixed slots",
            "Route 1",
            "Route 2",
            "twelve semantic stages",
            "two approval types",
            "fixed-B",
            "at most two generated tasks",
            "Invocation A",
            "Invocation B",
            "trim_to_active_content",
            "omit_source_end_card",
            "at least 18",
            "at least 12 matched",
            "30-40",
        ):
            self.assertIn(required, profile)

    def test_deployable_docs_fail_closed_before_run_and_keep_local_only_technical_work(self):
        main = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        bundled = (SEEDANCE_ROOT / "SKILL.md").read_text(encoding="utf-8")
        universal = (ROOT / "references" / "universal-source-fidelity-contract.md").read_text(
            encoding="utf-8"
        )
        combined = "\n".join((main, bundled, universal))
        for required in (
            "INPUT_SOURCE_TOO_LONG",
            "before creating a formal run",
            "no reverse script",
            "no storyboard",
            "no Image Gen",
            "no CreateAsset",
            "no CreateVideo",
            "internal black intervals",
            "transition render receipt",
            "VIDEO_ENDS_BEFORE_AUDIO",
            "AUDIO_VIDEO_DURATION_DRIFT",
            "source identity, unauthorized brand/UI",
        ):
            self.assertIn(required, combined)

    def test_selling_point_mapping_is_evidence_backed(self):
        intent = (SEEDANCE_ROOT / "references" / "intent-analysis.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "Feature",
            "Mechanism",
            "Benefit",
            "Proof",
            "CTA",
            "unsupported",
            "selling_point_mapping.json",
        ):
            self.assertIn(required, intent)

    def test_final_prompt_is_recompiled_by_seedance20_and_requires_zero_ambiguity(self):
        bundled = (SEEDANCE_ROOT / "SKILL.md").read_text(encoding="utf-8")
        prompt = (SEEDANCE_ROOT / "references" / "seedance-prompt.md").read_text(
            encoding="utf-8"
        )
        combined = bundled + "\n" + prompt
        for required in (
            "recompile the final prompt through `seedance-20`",
            "zero ambiguity",
            "approved Cut order",
            "character lock",
            "product lock",
            "duration",
            "voiceover",
            "timeline-region routing",
            "internal request integrity approval",
        ):
            self.assertIn(required, combined)
        required_checks = {
            "approved_cut_order",
            "character_lock",
            "product_lock",
            "duration_and_timing",
            "voiceover_and_audio",
            "camera_action_continuity",
            "timeline_region_routing",
            "reference_role_mapping",
            "provider_parameters",
            "forbidden_fields",
        }
        self.assertTrue(
            {
                "approved_cut_order",
                "character_lock",
                "product_lock",
                "duration_and_timing",
                "voiceover_and_audio",
                "camera_action_continuity",
                "timeline_region_routing",
                "reference_role_mapping",
                "provider_parameters",
                "forbidden_fields",
            }.issubset(required_checks)
        )

    def test_bundled_fixed_b_and_packaged_seedance_route_are_fail_closed(self):
        bundled = (SEEDANCE_ROOT / "SKILL.md").read_text(encoding="utf-8")
        universal = (ROOT / "references" / "universal-source-fidelity-contract.md").read_text(
            encoding="utf-8"
        )
        normalized_bundled = " ".join(bundled.split())
        for required in (
            "`generateAudio=true`",
            "matching original source segment at `videoUrls[0]`",
            "`usfr-multimodal-reference-binding/v2`",
            "`continuous-present-role-order/v1`",
            "no legacy `reference_audios` field",
            "`background_music` extension is the sole exception",
            "`audioUrls[0]`",
            "`@Audio1`",
            "complete package-relative dependency snapshot",
            "root `seedance-20`, `seedance-prompt`, and `seedance-antislop`",
            "free-form/raw `compiled_prompt`",
        ):
            self.assertIn(required, normalized_bundled)
        combined = " ".join((bundled + "\n" + universal).split())
        self.assertIn("tenant-private object storage", combined)
        self.assertIn("server-side", combined)
        self.assertEqual(
            RUNNINGHUB_STANDARD_PAYLOAD_FIELDS,
            {
                "prompt", "resolution", "duration", "imageUrls", "videoUrls", "audioUrls",
                "generateAudio", "ratio", "realPersonMode", "conversionSlots", "returnLastFrame", "seed",
            },
        )

    def test_seedance_prompt_allows_only_the_current_frozen_source_slice_as_a_video_reference(self):
        prompt = " ".join(
            (SEEDANCE_ROOT / "references" / "seedance-prompt.md")
            .read_text(encoding="utf-8")
            .split()
        )

        self.assertIn("exactly one matching frozen original source segment at `videoUrls[0]`", prompt)
        self.assertIn("full source video must never be uploaded", prompt)
        self.assertIn("`usfr-video-reference/v1`", prompt)
        self.assertIn("opaque UI and tail media never enter the request", prompt)
        self.assertNotIn("`videoUrls=[]`", prompt)

    def test_storyboard_template_is_not_locked_to_ecommerce(self):
        storyboard = (
            SEEDANCE_ROOT / "references" / "daohuo_storyboard_prompt.md"
        ).read_text(encoding="utf-8")
        lowered = storyboard.lower()
        self.assertNotIn("vertical ecommerce ugc video", lowered)
        self.assertNotIn("ecommerce video titled", lowered)
        self.assertIn("{{CONTENT_TYPE}}", storyboard)
        self.assertIn("{{PRODUCT_OR_SERVICE_TYPE}}", storyboard)

    def test_factory_bundles_the_new_runtime_contract_references(self):
        for relative in (
            "references/universal-source-fidelity-contract.md",
            "bundled-skills/seedance-storyboard-replication/references/seedance-20-integrity-gate.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
