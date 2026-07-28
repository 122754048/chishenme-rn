import json
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_bundle import (  # noqa: E402
    REQUIRED_MODULE_FILES,
    REQUIRED_RUNTIME_CONTRACTS,
    REQUIRED_SERVER_FILES,
    REQUIRED_DEPLOYMENT_FILES,
    REQUIRED_TOP_LEVEL_FILES,
    verify_bundle,
)


class FactorySkillContractTest(unittest.TestCase):
    def test_frontmatter_and_interface(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(skill, r"(?m)^name: universal-source-fidelity-replication$")
        self.assertIn("Use when", skill)
        interface = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "Universal Source-Fidelity Replication"', interface)
        self.assertIn("$universal-source-fidelity-replication", interface)

    def test_complete_workflow_and_approval_gates(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for required in (
            "parse-app-store-evidence",
            "analyze-reference-video-dynamics",
            "replicate-source-ui-overlays",
            "seedance-storyboard-replication",
            "weighted commercial intent",
            "Opaque slice branch",
            "RunningHub image2",
            "RunningHub Standard Model",
            "timeline_splice.py",
            "确认反解分镜脚本",
            "确认故事板",
            "timing_log.json",
            "qc_report.json",
            "final/result.mp4",
        ):
            self.assertIn(required, skill)

    def test_active_seedance_submission_contract_uses_runninghub_standard_model(self):
        bundled_root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
        documents = {
            "root skill": ROOT / "SKILL.md",
            "storyboard skill": bundled_root / "SKILL.md",
            "deployment guide": ROOT / "references" / "server-deployment-step-by-step.md",
            "workspace environment example": ROOT.parent / ".env.example",
            "bundled environment example": bundled_root / "references" / "seedance.env.example",
        }
        combined = "\n".join(
            document.read_text(encoding="utf-8") for document in documents.values()
        )
        for required in (
            "runninghub_seedance_submit.py",
            "seedance-2.0-fast-token/multimodal-video",
            "RUNNINGHUB_SEEDANCE_API_KEY",
            "usfr-video-reference/v1",
            "videoUrls[0]",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)
        for forbidden in (
            "Youdao",
            "youdao",
            "scripts/seedance_submit.py",
            "asset://",
        ):
            for name, document in documents.items():
                with self.subTest(document=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, document.read_text(encoding="utf-8"))

        manifest = (ROOT / "references" / "bundle_manifest.json").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py",
            manifest,
        )
        self.assertNotIn(
            "bundled-skills/seedance-storyboard-replication/scripts/seedance_submit.py",
            manifest,
        )

    def test_fixed_slot_admission_and_source_defaults_are_documented(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        contract = (
            ROOT / "references" / "fixed-input-slot-contract.md"
        ).read_text(encoding="utf-8")
        for required in (
            "source_video",
            "new_product_image",
            "new_model_image",
            "ui_screenshot",
            "app_store_url",
            "ui_operation_video",
            "tail_video",
            "MIN_ONE_OPTIONAL_INPUT_REQUIRED",
            "source_ui_keep",
            "omit_source_end_card",
            "scripts/bind_input_slots.py",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill + contract)

    def test_app_store_evidence_contract_covers_google_play_and_server_execution(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        normalized = " ".join(skill.split())
        for required in (
            "official Apple App Store or Google Play URL",
            "play.google.com/store/apps/details?id=...",
            "Google package ID",
            "`hl` parameter maps to `language`",
            "`gl` parameter maps to `storefront`",
            "official Google Play media hosts",
            "ordered screenshot",
            "metadata_only",
            "never hand the URL to a generator",
            "private temporary object prefix",
            "server Worker",
            "local temporary directory",
            "logical run directory",
            "never means reading the user's workstation",
            "object-store-backed source interval",
            "RedisEphemeralJobStore",
            "slots_manifest",
            "temporary/{job_id}/...",
            "final/{job_id}/result.mp4",
            "artifact metadata + signed download",
            "once per run",
        ):
            with self.subTest(required=required):
                self.assertIn(required, normalized)

    def test_factory_has_only_script_and_storyboard_approval_types(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("\u786e\u8ba4 Seedance \u63d0\u793a\u8bcd", skill)
        self.assertNotIn("\u786e\u8ba4\u5267\u60c5\u5207\u70b9", skill)
        self.assertIn("确认反解分镜脚本", skill)
        self.assertIn("确认故事板", skill)
        self.assertNotIn("确认 Seedance 提示词", skill)
        self.assertIn("storyboard approval triggers autonomous Seedance", skill)

    def test_factory_preserves_quality_while_targeting_thirty_minutes(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for required in (
            "30-minute production target",
            "not a cancellation deadline",
            "GPT",
            "adaptive keyframes",
            "RunningHub image2",
            "seedance-20",
            "script-to-prompt parity audit",
            "qc_report.json",
        ):
            self.assertIn(required, skill)

    def test_high_fidelity_source_to_prompt_projection_and_skill_router_are_documented(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for required in (
            "scripts/skill_router.py",
            "scripts/seedance_prompt_compiler.py",
            "Source decomposition and prompt projection contract",
            "scene topology",
            "microphone relationship",
            "completed endpoint",
            "proof/Foley/silence",
            "Invocation A (pre-script)",
            "Invocation B (post-storyboard)",
            "dependency snapshot as A",
            "package-relative logical paths",
            "never a workstation path",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill)

    def test_latest_projection_transition_and_qc_hardening_are_documented(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        normalized = " ".join(skill.split())
        for required in (
            "server/high_fidelity_projection.py",
            "technical-only `passed=true`",
            "weighted high-fidelity QC extension",
            "`xfade=transition=dissolve`",
            "alpha-ramped overlay",
            "semantic overlay layer is declared but no validated overlay render mapping exists",
            "source_overlay_contract",
            "overlay_render_mapping",
            "OVERLAY_RENDER_MAPPING_REQUIRED",
        ):
            with self.subTest(required=required):
                self.assertIn(required, normalized)

    def test_twelve_semantic_stages_have_an_operational_mapping_contract(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        runtime = (ROOT / "references" / "deployment-runtime-contract.md").read_text(encoding="utf-8")
        combined = " ".join((skill + "\n" + runtime).split())
        for required in (
            "12 semantic stages",
            "operational stage mapping",
            "deferred target truth",
            "Fixed image-slot binding is the target-truth boundary",
            "deferred stage itself",
            "build_semantic_stage_mapping",
            "does not add a job-state stage",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

    def test_production_qc_evaluator_contract_covers_all_stage_ports(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        references = "\n".join(
            (
                (ROOT / "references" / "high-fidelity-hybrid-v1.md").read_text(encoding="utf-8"),
                (ROOT / "references" / "high-fidelity-evidence-matrix.md").read_text(encoding="utf-8"),
            )
        )
        combined = " ".join((skill + "\n" + references).split())
        for required in (
            "all production QC StagePort",
            "qc_evaluator_response",
            "deployment-injected evaluator",
            "real HTTPS semantic evaluator",
            "EvidenceBoundHttpSemanticQcEvaluator",
            "USFR_QC_EVALUATOR_ENDPOINT",
            "media_base64",
            "never sends a worker path",
            "request payload is compared exactly with the actual final/source/input artifact digests",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

    def test_skill_router_is_manifested_and_bundled(self):
        self.assertIn("scripts/skill_router.py", (ROOT / "references" / "bundle_manifest.json").read_text(encoding="utf-8"))
        self.assertIn("scripts/skill_router.py", (ROOT / "scripts" / "verify_bundle.py").read_text(encoding="utf-8"))

    def test_seedance_review_binding_contract_is_explicit(self):
        skill = (ROOT / "bundled-skills" / "seedance-storyboard-replication" / "SKILL.md").read_text(encoding="utf-8")
        reference = (ROOT / "bundled-skills" / "seedance-storyboard-replication" / "references" / "fukeGem.md").read_text(encoding="utf-8")
        combined = skill + "\n" + reference
        for required in ("arbitrary review iterations", "approved_storyboard_manifest_sha256", "approved_storyboard_cut_sha256s", "output_language"):
            self.assertIn(required, combined)

    def test_success_delivery_is_video_only(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("successful final response contains only final/result.mp4", skill)
        self.assertIn("blocker messages are allowed only when delivery cannot continue", skill)

    def test_bundle_is_self_contained(self):
        self.assertEqual(verify_bundle(ROOT), [])

    def test_bundle_requires_runtime_integrity_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "references").mkdir(parents=True)
            (root / "references" / "bundle_manifest.json").write_text(
                json.dumps(
                    {"modules": [{"name": name} for name in REQUIRED_MODULE_FILES]}
                ),
                encoding="utf-8",
            )
            for module, required_files in REQUIRED_MODULE_FILES.items():
                module_root = root / "bundled-skills" / module
                for relative in required_files:
                    path = module_root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("placeholder", encoding="utf-8")
            failures = verify_bundle(root)
            expected = [
                *[f"runtime file not declared: {relative}" for relative in REQUIRED_TOP_LEVEL_FILES],
                "runtime file not declared: references/fixed-input-slot-contract.md",
                *[f"runtime file not declared: {relative}" for relative in REQUIRED_SERVER_FILES],
                *[f"deployment file not declared: {relative}" for relative in REQUIRED_DEPLOYMENT_FILES],
                *[f"missing runtime contract: {root / relative}" for relative in REQUIRED_RUNTIME_CONTRACTS],
                *[f"missing top-level runtime file: {root / relative}" for relative in REQUIRED_TOP_LEVEL_FILES],
                *[f"missing server runtime file: {root / relative}" for relative in REQUIRED_SERVER_FILES],
                *[f"missing deployment file: {root / relative}" for relative in REQUIRED_DEPLOYMENT_FILES],
            ]
            self.assertEqual(failures, expected)

    def test_integrity_reference_documents_machine_enforced_schema(self):
        integrity = (
            ROOT
            / "bundled-skills"
            / "seedance-storyboard-replication"
            / "references"
            / "seedance-20-integrity-gate.md"
        ).read_text(encoding="utf-8")
        for heading in (
            "## Audit artifact schema and compiler provenance",
            "## Frozen contract digests and contract index",
            "## Factor coverage and payload-path resolution",
            "## Postproduction and route exclusions",
            "## Empty-state and compact route-leakage checks",
            "## Prompt/script/request mutation locks",
        ):
            self.assertIn(heading, integrity)
        for field in (
            "auditor",
            "status",
            "professional_gate",
            "capability_check",
            "allocation_check",
            "reference_role_check",
            "directing_coherence_check",
            "anti_slop_check",
            "approved_storyboard_sha256",
            "source_fidelity_contract_sha256",
            "timeline_regions_sha256",
            "character_lock_sha256",
            "product_truth_sha256",
            "selling_point_mapping_sha256",
            "audio_contract_sha256",
            "continuity_manifest_sha256",
            "contract_index",
            "contract_pointer",
            "factor_coverage_ledger",
            "payload_path",
            "prompt_carried",
            "reference_carried",
            "payload_carried",
            "postproduction_carried",
            "route_excluded",
            "ambiguities",
            "unresolved_placeholders",
        ):
            self.assertIn(field, integrity)

    def test_reference_video_analysis_is_gpt_keyframe_only(self):
        factory = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        dynamics_root = ROOT / "bundled-skills" / "analyze-reference-video-dynamics"
        dynamics = (dynamics_root / "SKILL.md").read_text(encoding="utf-8")
        combined = factory + "\n" + dynamics
        for required in (
            "GPT",
            "adaptive keyframes",
            "contact sheets",
            "boundary frames",
            "separate audio transcription",
        ):
            self.assertIn(required, combined)
        for forbidden in (
            "Kimi",
            "Qwen",
            "external-analyzer",
            "external full-video",
            "youdao_kimi_video_analyze.py",
        ):
            self.assertNotIn(forbidden, combined)
        for removed in (
            "scripts/build_external_analyzer_packet.py",
            "scripts/youdao_kimi_video_analyze.py",
            "references/external-video-analyzer-contract.md",
            "references/youdao-kimi-k27-api.md",
            "references/youdao-qwen37plus-api.md",
        ):
            self.assertFalse((dynamics_root / removed).exists(), removed)

    def test_factory_does_not_allow_paid_task_before_digest_approval(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("No paid task before exact internal parity/integrity audit", skill)
        self.assertIn("Submit only the internally audited and validated digest", skill)
        self.assertIn("duplicate paid tasks", skill)

    def test_internal_integrity_wording_is_not_user_approval(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("Submit only the approved digest", skill)
        self.assertNotIn("No paid task before exact approval", skill)
        self.assertNotIn("prompt approval", skill)
        self.assertIn("internal prompt/digest integrity validation", skill)

    def test_bundled_seedance_workflow_uses_internal_audit_and_safe_concurrency(self):
        root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        api = (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8")
        combined = "\n".join((skill, api))
        self.assertNotIn("\u786e\u8ba4 Seedance \u63d0\u793a\u8bcd", combined)
        self.assertNotIn("\u786e\u8ba4\u5267\u60c5\u5207\u70b9", combined)
        self.assertNotIn("explicit user approval of that exact digest", combined)
        for required in (
            "seedance-20",
            "script-to-prompt parity audit",
            "--approved-request-sha256",
            "runninghub_seedance_submit.py --dry-run",
            "RunningHub Standard Model",
            "usfr-video-reference/v1",
            "videoUrls[0]",
            "audioUrls",
            "independent single-task",
            "two-segment concurrency",
            "statefully and without a deadline",
            "Factory executor owns two-segment concurrency",
            "final/result.mp4",
            "complete approved Cuts",
            "four-image",
            "reference_videos",
            "reference_audios",
            "duplicate paid",
            "final QC",
        ):
            self.assertIn(required, combined)
        self.assertNotIn("scripts/seedance_submit.py", combined)
        self.assertNotIn("asset://", combined)
        dry_run = skill.index("runninghub_seedance_submit.py --dry-run")
        parity = skill.index("script-to-prompt parity audit")
        digest = skill.index("--approved-request-sha256")
        self.assertLess(dry_run, parity)
        self.assertLess(parity, digest)

    def test_generated_ui_and_opaque_app_regions_stay_out_of_seedance_semantics(self):
        factory = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        bundled = (
            ROOT
            / "bundled-skills"
            / "seedance-storyboard-replication"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        integrity = (
            ROOT
            / "bundled-skills"
            / "seedance-storyboard-replication"
            / "references"
            / "seedance-20-integrity-gate.md"
        ).read_text(encoding="utf-8")
        combined = "\n".join((factory, bundled, integrity))
        storyboard_prompt = (
            ROOT
            / "bundled-skills"
            / "seedance-storyboard-replication"
            / "references"
            / "daohuo_storyboard_prompt.md"
        ).read_text(encoding="utf-8")
        reverse_script = (
            ROOT
            / "bundled-skills"
            / "seedance-storyboard-replication"
            / "references"
            / "fukeGem.md"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "`generated_ui_demo` regions enter semantic scripts/storyboards and paid generation",
            bundled,
        )
        self.assertNotIn(
            "include only `generated_ui_demo` and ordinary generated intervals in the semantic script",
            reverse_script,
        )
        self.assertNotIn(
            "For generated_ui_demo, visualize only",
            storyboard_prompt,
        )
        self.assertIn(
            "generated_ui_demo is excluded from the semantic script and every storyboard",
            storyboard_prompt,
        )
        self.assertIn(
            "generated_ui_demo is excluded from the semantic script and every storyboard",
            reverse_script,
        )
        for required in (
            "generated UI remains",
            "deterministic UI renderer/timeline lane",
            "route that shell as a separate",
            "ordinary generated region",
            "generated_ui_demo",
            "excluded_app_end_card",
            "omit_source_end_card",
            "mapping keys",
        ):
            self.assertIn(required, combined)

    def test_high_fidelity_profile_names_canonical_analysis_envelope_and_ab_digest(self):
        factory = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        combined = factory
        for required in (
            "high-fidelity-analysis-envelope",
            "adaptive evidence plan",
            "raw dynamics",
            "projection_sha256",
            "Invocation A and B use that",
            "same rich shot/factor projection",
            "parent digests",
        ):
            self.assertIn(required, combined)

    def test_audited_factory_steps_name_the_standard_model_request_digest(self):
        root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
        factory = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        api = (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8")
        sections = {
            "factory audited sequence": factory[
                factory.index("9. **Compile and audit the exact RunningHub Standard Model request internally**") :
                factory.index("11. **Assemble final video**")
            ],
            "bundled submission sequence": skill[
                skill.index("## RunningHub Standard Model Seedance Submission") :
                skill.index("## Download, Concatenation, and QC")
            ],
            "standard-model API": api,
        }
        for label, section in sections.items():
            with self.subTest(section=label):
                self.assertIn("--approved-request-sha256", section)
                self.assertNotIn("--audited-request-sha256", section)
                self.assertNotIn("--seedance-input-contract", section)

    def test_integrity_reference_documents_live_seedance20_snapshot_recheck(self):
        integrity = (
            ROOT
            / "bundled-skills"
            / "seedance-storyboard-replication"
            / "references"
            / "seedance-20-integrity-gate.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("does not independently\nrecompute", integrity)
        self.assertIn("loads the installed skill file and recomputes", integrity)

    def test_duration_planning_counts_only_effective_generated_regions(self):
        storyboard_root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
        skill = (storyboard_root / "SKILL.md").read_text(encoding="utf-8")
        storyboard_prompt = (
            storyboard_root / "references" / "daohuo_storyboard_prompt.md"
        ).read_text(encoding="utf-8")
        segment_planner = (storyboard_root / "scripts" / "segment_plan.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("4–15 second task limits", skill)
        self.assertNotIn("1–15 second task limits", skill)
        self.assertIn("必须为 4-15 秒", storyboard_prompt)
        self.assertNotIn("必须为 1-15 秒", storyboard_prompt)
        self.assertIn("Plan 4-15 second Seedance segments", segment_planner)
        self.assertNotIn("Plan 1-15 second Seedance segments", segment_planner)
        self.assertRegex(skill, r"Opaque and source-origin\s+intervals never count toward")
        self.assertIn("each contiguous generated region", skill)

    def test_resume_documentation_is_a_side_effect_free_known_task_route(self):
        root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
        documents = {
            "factory": (ROOT / "SKILL.md").read_text(encoding="utf-8"),
            "bundled": (root / "SKILL.md").read_text(encoding="utf-8"),
            "integrity": (root / "references" / "seedance-20-integrity-gate.md").read_text(encoding="utf-8"),
            "prompt": (root / "references" / "seedance-prompt.md").read_text(encoding="utf-8"),
            "api": (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8"),
        }
        for label, document in documents.items():
            with self.subTest(document=label):
                self.assertRegex(
                    document,
                    r"does not require\s+a\s+new\s+prompt\s+or\s+duration",
                )
                self.assertRegex(
                    document,
                    r"performs no\s+asset\s+preparation\s+or\s+payload\s+build",
                )
                self.assertRegex(
                    document,
                    r"cannot\s+be\s+combined\s+with\s+`--dry-run`",
                )

    def test_paid_create_is_documented_as_non_retryable(self):
        root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
        documents = (
            (ROOT / "SKILL.md").read_text(encoding="utf-8"),
            (root / "SKILL.md").read_text(encoding="utf-8"),
            (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8"),
        )
        required = (
            "paid Seedance create is never automatically retried after a 429, 5xx, "
            "timeout, connection reset, or ambiguous response"
        )
        for document in documents:
            with self.subTest(document=document[:40]):
                self.assertIn(required.lower(), " ".join(document.split()).lower())

    def test_asset_registration_is_documented_as_non_retryable(self):
        root = ROOT / "bundled-skills" / "seedance-storyboard-replication"
        documents = (
            (ROOT / "SKILL.md").read_text(encoding="utf-8"),
            (root / "SKILL.md").read_text(encoding="utf-8"),
            (root / "references" / "runninghub-standard-seedance-api.md").read_text(encoding="utf-8"),
        )
        required = (
            "RunningHub media upload is never automatically retried after a 429, 5xx, "
            "timeout, connection reset, or ambiguous response"
        )
        for document in documents:
            with self.subTest(document=document[:40]):
                self.assertIn(required.lower(), " ".join(document.split()).lower())

    def test_production_timing_transition_contract(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for required in (
            "first input probe",
            'pause_approval("script")',
            'pause_approval("storyboard")',
            "RunningHub image2 wait",
            "RunningHub Standard Model Seedance wait",
            "provider=True",
            "after final MP4 QC",
            "same log path",
            "measurement only",
        ):
            self.assertIn(required, skill)

    def test_skill_and_bundled_timeline_name_exact_segment_and_receipt_closure(self):
        skill = " ".join((ROOT / "SKILL.md").read_text(encoding="utf-8").split())
        timeline = " ".join((
            ROOT
            / "bundled-skills"
            / "seedance-storyboard-replication"
            / "references"
            / "timeline-slice-contract.md"
        ).read_text(encoding="utf-8").split())
        for required in (
            "exact canonical audited provider payload",
            "`create_video(request)` is the preferred Provider protocol",
            "canonical `segment_plan` JSON and its `segment_plan_sha256` are the only Segment-membership authority",
            "duplicate, missing, or extra Segment IDs fail closed",
            "absolute paths to bundled timeline and concat dependencies",
        ):
            with self.subTest(document="skill", required=required):
                self.assertIn(required, skill)
        for required in (
            "frozen Segments and Cuts form one global closed set",
            "ordinary generated media cannot bypass exact Segment/Cut bindings",
            "natural decoded media duration",
            "no padding, freeze, loop, or hidden retime",
            "per-Segment audio/video boundaries align",
            "every non-source carrier and every declared source transition",
            "exact final-output-bound receipt",
            "source and omitted routes reject any media binding",
            "manifest route, placement, and omission sets are exact",
        ):
            with self.subTest(document="timeline", required=required):
                self.assertIn(required, timeline)


if __name__ == "__main__":
    unittest.main()
