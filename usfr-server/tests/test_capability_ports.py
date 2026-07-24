from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


class _Adapter:
    def __init__(self, capability: str, methods: tuple[str, ...]) -> None:
        self.capability = capability
        self.implementation = f"container://{capability}"
        self.version = "1.0.0"
        self.sha256 = hashlib.sha256(capability.encode("utf-8")).hexdigest()
        for method in methods:
            setattr(self, method, self._run)

    def _run(self, **_kwargs):
        if self.capability == "dynamics_analyzer":
            return {
                "source_dynamics_analysis": {
                    "source_cuts": [{"cut": 1, "start_us": 0, "end_us": 1}],
                    "source_events": [],
                    "extensions": {
                        "high_fidelity_hybrid_v1": {
                            "schema_version": 1,
                            "analysis_pass_count": 1,
                            "semantic_cuts": [],
                            "route_excluded_intervals": [{
                                "cut": 1,
                                "region_type": "opaque_ui_demo",
                                "start_us": 0,
                                "end_us": 1,
                                "transition_shell": {"kind": "hard_cut", "duration_ms": 0},
                                "technical_stream": {"width": 180, "height": 320, "fps_num": 30, "fps_den": 1},
                            }],
                        }
                    },
                }
            }
        if self.capability == "asr_transcriber":
            return {
                "audio_contract": {
                    "source_audio_sha256": "d" * 64,
                    "source_duration_ms": 1,
                    "segments": [],
                    "meaningful_silence": [],
                }
            }
        if self.capability == "ocr_ui_renderer":
            return {
                "ui_truth_card": {"screens": ["home"]},
                "ui_render_contract": {"screens": ["home"]},
                "rendered_media": {"object_key": "tenant/run/ui.mp4", "sha256": "a" * 64},
                "ocr_match_percent": 100,
                "layout_match_percent": 100,
            }
        if self.capability == "seedance20_compiler":
            return {"status": "ready", "profile": "seedance20_prescript_v1", "compiled_prompt_sha256": "b" * 64}
        if self.capability == "compositor":
            return {
                "output_artifact": {"object_key": "tenant/run/result.mp4", "sha256": "c" * 64},
                "timeline_manifest": {"regions": ["R01"]},
            }
        if self.capability == "qc_engine":
            return {"passed": True, "qc_report": {"status": "passed"}}
        return {"provider_id": "provider-1", "status": "ready"}


def _manifest_and_ports():
    from server.capabilities import REQUIRED_CAPABILITIES, build_stage_capability_manifest
    from server.capability_ports import REQUIRED_CAPABILITY_METHODS

    ports = {
        name: _Adapter(name, REQUIRED_CAPABILITY_METHODS[name])
        for name in REQUIRED_CAPABILITIES
    }
    records = {
        name: {
            "declared": True,
            "implementation": ports[name].implementation,
            "version": ports[name].version,
            "sha256": ports[name].sha256,
        }
        for name in REQUIRED_CAPABILITIES
    }
    return build_stage_capability_manifest(records), ports


def _candidate() -> dict:
    return {
        "candidate_region_id": "CR-01",
        "cut_ids": ["C01"],
        "required_factor_ids": ["HFH.C01.ACTION.ENDPOINT"],
        "allowed_split_cut_ids": [],
        "forbidden_split_cut_ids": ["C01"],
        "duration_ms": 8000,
        "primary_fidelity_spend": "motion",
        "secondary_fidelity_spend": "identity",
        "economized_factors": ["background_microtexture"],
        "mode": "fixed_b_image_reference",
        "single_take_or_multishot": "single_take",
        "shot_budget": [{"shot_id": "SHOT-01", "duration_ms": 8000, "primary_action": "open package", "endpoint": "package open"}],
        "reference_role_plan": [{"role": "storyboard", "slot": 1}],
        "background_strategy": "KEEP",
        "performance_strategy": {"gaze": "camera", "gesture": "two hands"},
        "action_state_requirements": [{"phase": "completed", "state": "package open", "required": True}],
        "audio_strategy": {"music_policy": "none", "ambience": "room tone", "foley_event_ids": [], "silence_window_ids": []},
        "voiceover_timing_plan": [],
        "prompt_carrier_plan": [],
        "postproduction_carrier_plan": [],
        "hard_blockers": [],
        "warnings": [],
    }


def _factor_coverage() -> list[dict]:
    return [{
        "factor_id": "HFH.C01.ACTION.ENDPOINT",
        "candidate_region_id": "CR-01",
        "source_pointer": "/source_fidelity_contract/C01/action/endpoint",
        "contract_pointer": "/contracts/source_fidelity_contract.json#/cuts/C01/action/endpoint",
        "carrier": "prompt",
        "criticality": "H",
    }]


class RuntimeCapabilityPortsTest(unittest.TestCase):
    def test_active_production_rejects_declared_manifest_without_runtime_ports(self):
        from server.capability_ports import validate_runtime_capability_ports

        manifest, _ = _manifest_and_ports()
        with self.assertRaisesRegex(ValueError, "runtime capability ports"):
            validate_runtime_capability_ports(
                {},
                manifest=manifest,
                production=True,
                profile_active=True,
            )

    def test_active_production_rejects_noop_or_missing_required_methods(self):
        from server.capabilities import REQUIRED_CAPABILITIES
        from server.capability_ports import validate_runtime_capability_ports

        manifest, ports = _manifest_and_ports()
        del ports["dynamics_analyzer"].analyze
        with self.assertRaisesRegex(ValueError, "dynamics_analyzer.*analyze"):
            validate_runtime_capability_ports(
                ports,
                manifest=manifest,
                production=True,
                profile_active=True,
            )

        ports, _ = ({name: object() for name in REQUIRED_CAPABILITIES}, manifest)
        with self.assertRaisesRegex(ValueError, "capability identity"):
            validate_runtime_capability_ports(
                ports,
                manifest=manifest,
                production=True,
                profile_active=True,
            )

    def test_manifest_identity_must_match_injected_adapter_bytes(self):
        from server.capability_ports import validate_runtime_capability_ports

        manifest, ports = _manifest_and_ports()
        ports["compositor"].sha256 = "f" * 64
        with self.assertRaisesRegex(ValueError, "compositor.*sha256"):
            validate_runtime_capability_ports(
                ports,
                manifest=manifest,
                production=True,
                profile_active=True,
            )

    def test_valid_runtime_ports_are_accepted_and_returned(self):
        from server.capability_ports import validate_runtime_capability_ports

        manifest, ports = _manifest_and_ports()
        bound = validate_runtime_capability_ports(
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        self.assertEqual(set(bound), set(ports))

    def test_stage_binding_requires_declared_capability_names(self):
        from server.capability_ports import CapabilityStagePort, validate_stage_port_bindings

        manifest, ports = _manifest_and_ports()

        class UnboundStage:
            def run(self, *, context, input_artifacts):
                return {"status": "ready"}

        with self.assertRaisesRegex(ValueError, "analyze_dynamics.*dynamics_analyzer"):
            validate_stage_port_bindings(
                {"analyze_dynamics": UnboundStage()},
                ports,
                manifest=manifest,
                production=True,
                profile_active=True,
            )

        bound_stage = CapabilityStagePort(
            "analyze_dynamics",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        self.assertIsNone(
            validate_stage_port_bindings(
                {"analyze_dynamics": bound_stage},
                ports,
                manifest=manifest,
                production=True,
                profile_active=True,
            )
        )

    def test_bound_stage_port_preserves_existing_handler_output(self):
        from server.capability_ports import BoundStagePort

        class ExistingStage:
            def run(self, *, context, input_artifacts):
                return {"canonical": context, "artifacts": input_artifacts}

        stage = BoundStagePort("build_script", ExistingStage())
        marker = object()
        output = stage.run(context=marker, input_artifacts=[])
        self.assertIs(output["canonical"], marker)
        self.assertEqual(stage.capability_names, ("seedance20_compiler",))

    def test_direct_capability_stage_rejects_a_spoofed_capability_label(self):
        from server.capability_ports import validate_stage_port_bindings

        manifest, ports = _manifest_and_ports()

        class SpoofedStage:
            capability_names = ("compositor",)

            def run(self, *, context, input_artifacts):
                return {"output_artifact": {"object_key": "fake", "sha256": "a" * 64}}

        with self.assertRaisesRegex(ValueError, "CapabilityStagePort"):
            validate_stage_port_bindings(
                {"splice_timeline": SpoofedStage()},
                ports,
                manifest=manifest,
                production=True,
                profile_active=True,
            )

    def test_bound_runtime_capability_delegates_to_real_adapter_with_identity(self):
        from server.capability_ports import BoundRuntimeCapability

        adapter = _Adapter("compositor", ("compose",))
        bound = BoundRuntimeCapability(
            capability="compositor",
            implementation=adapter.implementation,
            version=adapter.version,
            sha256=adapter.sha256,
            adapter=adapter,
        )
        self.assertEqual(bound.capability_identity()["sha256"], adapter.sha256)
        self.assertIn("output_artifact", bound.compose())

    def test_bound_runtime_capability_preserves_nested_composite_identity(self):
        from server.capability_ports import BoundRuntimeCapability

        class CompositeAdapter(_Adapter):
            def capability_identity(self):
                return {
                    "capability": self.capability,
                    "implementation": self.implementation,
                    "version": self.version,
                    "sha256": "e" * 64,
                    "dependencies": {"renderer": "nested-model"},
                }

        adapter = CompositeAdapter("compositor", ("compose",))
        bound = BoundRuntimeCapability(
            capability="compositor",
            implementation=adapter.implementation,
            version=adapter.version,
            sha256=adapter.sha256,
            adapter=adapter,
        )

        identity = bound.capability_identity()
        self.assertEqual(identity["sha256"], "e" * 64)
        self.assertEqual(identity["implementation"], adapter.implementation)

    def test_bound_runtime_capability_can_wrap_packaged_seedance_invocation_adapter(self):
        from server.capability_ports import BoundRuntimeCapability
        from server.seedance_invocations import SeedanceInvocationAdapter

        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "seedance-20" / "SKILL.md"
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text(
                "---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n",
                encoding="utf-8",
            )
            compiler = SeedanceInvocationAdapter(skill_file=skill)
            bound = BoundRuntimeCapability(
                capability="seedance20_compiler",
                implementation="container://seedance20-compiler",
                version="6.6.0",
                sha256=hashlib.sha256(skill.read_bytes()).hexdigest(),
                adapter=compiler,
            )
            artifact = bound.invoke_a(
                route="route_2",
                candidate_regions=[_candidate()],
                line_contracts=[],
                factor_coverage=_factor_coverage(),
                input_digests={"source": "d" * 64},
            )
            self.assertEqual(artifact["profile"], "seedance20_prescript_v1")

    def test_seedance_composite_stage_must_use_the_bound_invocation_adapter(self):
        from server.capability_ports import BoundRuntimeCapability, BoundStagePort, validate_stage_port_bindings

        manifest, ports = _manifest_and_ports()
        compiler = ports["seedance20_compiler"]
        bound_compiler = BoundRuntimeCapability(
            capability="seedance20_compiler",
            implementation=compiler.implementation,
            version=compiler.version,
            sha256=compiler.sha256,
            adapter=compiler,
        )
        ports["seedance20_compiler"] = bound_compiler
        stage_ports = {"build_script": BoundStagePort("build_script", lambda **_: {"script": "ok"})}
        with self.assertRaisesRegex(ValueError, "invocation adapter"):
            validate_stage_port_bindings(
                stage_ports,
                ports,
                manifest=manifest,
                production=True,
                profile_active=True,
                invocation_adapter=object(),
            )
        validate_stage_port_bindings(
            stage_ports,
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
            invocation_adapter=compiler,
        )

    def test_seedance_audit_stage_requires_bound_compiler_stage_port(self):
        from server.capability_ports import BoundStagePort, validate_stage_port_bindings

        manifest, ports = _manifest_and_ports()
        compiler = ports["seedance20_compiler"]

        class SpoofedAuditStage:
            capability_names = ("seedance20_compiler",)

            def run(self, *, context, input_artifacts):
                return {"provider_payload": {}}

        with self.assertRaisesRegex(ValueError, "BoundStagePort"):
            validate_stage_port_bindings(
                {"audit_seedance_request": SpoofedAuditStage()},
                ports,
                manifest=manifest,
                production=True,
                profile_active=True,
                invocation_adapter=compiler,
            )

        stage = BoundStagePort(
            "audit_seedance_request",
            lambda **_: {"provider_payload": {}},
        )
        self.assertEqual(stage.capability_names, ("seedance20_compiler",))
        self.assertIsNone(
            validate_stage_port_bindings(
                {"audit_seedance_request": stage},
                ports,
                manifest=manifest,
                production=True,
                profile_active=True,
                invocation_adapter=compiler,
            )
        )

    def test_stage_port_adapter_executes_bound_dynamics_and_audio_ports(self):
        from server.capability_ports import CapabilityStagePort

        class Context:
            snapshot = SimpleNamespace(
                slots_manifest={"slots": {"source_video": {"sha256": ["a" * 64]}}}
            )

            def __init__(self) -> None:
                self.published: list[dict] = []

            def publish_bytes(self, *, kind, data, content_type, expected_sha256):
                self.assertEqual(expected_sha256, hashlib.sha256(data).hexdigest())
                self.assertEqual(content_type, "application/json")
                self.published.append({"kind": kind, "data": data, "sha256": expected_sha256})
                return {"kind": kind, "sha256": expected_sha256, "artifact_id": f"{kind}-1"}

            def assertEqual(self, actual, expected):
                testcase.assertEqual(actual, expected)

        manifest, ports = _manifest_and_ports()
        testcase = self
        stage = CapabilityStagePort(
            "analyze_dynamics",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        context = Context()
        output = stage.run(context=context, input_artifacts=[])
        self.assertEqual(output["status"], "ready")
        self.assertEqual(output["capabilities"], ["asr_transcriber", "dynamics_analyzer"])
        self.assertIn("source_dynamics_analysis", output)
        self.assertIn("audio_contract", output)
        self.assertEqual(output["source_content_timeline"]["contract"], "source-content-timeline/v1")
        self.assertEqual(output["source_content_timeline"]["source_video_sha256"], "a" * 64)
        self.assertIn("source_content_timeline", [item["kind"] for item in output["published_artifacts"]])
        published_timeline = next(item["data"] for item in context.published if item["kind"] == "source_content_timeline")
        self.assertEqual(json.loads(published_timeline)["contract"], "source-content-timeline/v1")

    def test_active_dynamics_stage_rejects_missing_high_fidelity_extension(self):
        from server.capability_ports import CapabilityStagePort

        manifest, ports = _manifest_and_ports()
        ports["dynamics_analyzer"]._run = lambda **_: {
            "source_dynamics_analysis": {"source_cuts": [{"cut_id": "C01"}]}
        }
        ports["dynamics_analyzer"].analyze = ports["dynamics_analyzer"]._run
        stage = CapabilityStagePort(
            "analyze_dynamics",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "high-fidelity.*extension"):
            stage.run(context=object(), input_artifacts=[])

    def test_active_dynamics_stage_rejects_shallow_high_fidelity_extension(self):
        from server.capability_ports import CapabilityStagePort

        manifest, ports = _manifest_and_ports()
        ports["dynamics_analyzer"]._run = lambda **_: {
            "source_dynamics_analysis": {
                "source_cuts": [{"cut": 1, "start_us": 0, "end_us": 1}],
                "source_events": [],
                "extensions": {
                    "high_fidelity_hybrid_v1": {
                        "schema_version": 1,
                        "analysis_pass_count": 1,
                        "semantic_cuts": [],
                        "route_excluded_intervals": [],
                    }
                },
            }
        }
        ports["dynamics_analyzer"].analyze = ports["dynamics_analyzer"]._run
        stage = CapabilityStagePort(
            "analyze_dynamics",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "high-fidelity.*extension|semantic.*cover"):
            stage.run(context=object(), input_artifacts=[])

    def test_active_generated_ui_stage_rejects_png_or_missing_state_evidence(self):
        from server.capability_ports import CapabilityStagePort

        class Context:
            profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"}
            timeline_regions = ({"region_type": "generated_ui_demo"},)

        manifest, ports = _manifest_and_ports()
        stage = CapabilityStagePort(
            "resolve_ui_evidence",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "generated UI.*video.*state_evidence"):
            stage.run(context=Context(), input_artifacts=[])

    def test_active_generated_ui_stage_rejects_unbound_state_receipts(self):
        from server.capability_ports import CapabilityStagePort

        class Context:
            profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "active"}
            timeline_regions = ({"region_type": "generated_ui_demo"},)

        manifest, ports = _manifest_and_ports()
        ports["ocr_ui_renderer"].render_and_verify = lambda **_: {
            "ui_truth_card": {
                "states": [{
                    "state_id": "home",
                    "frame_ms": 100,
                    "expected_text": ["Home"],
                    "expected_layout": [],
                }],
            },
            "ui_render_contract": {"state_sequence": ["home"], "viewport": [180, 320]},
            "rendered_media": {
                "kind": "generated_ui_video",
                "object_key": "tenant/run/ui.mp4",
                "content_type": "video/mp4",
                "sha256": "a" * 64,
            },
            "ui_qc_report": {
                "ocr_match_percent": 100,
                "layout_match_percent": 100,
                "state_evidence": [{
                    "state_id": "home",
                    "ocr_match_percent": 100,
                    "layout_match_percent": 100,
                    "ocr_evidence": {},
                    "layout_evidence": {},
                }],
            },
            "ocr_match_percent": 100,
            "layout_match_percent": 100,
        }
        stage = CapabilityStagePort(
            "resolve_ui_evidence",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "frame|OCR|receipt|model"):
            stage.run(context=Context(), input_artifacts=[])

    def test_stage_port_rejects_status_only_sidecar_as_fake_execution(self):
        from server.capability_ports import CapabilityStagePort

        manifest, ports = _manifest_and_ports()
        ports["dynamics_analyzer"]._run = lambda **_: {"status": "ready"}
        ports["dynamics_analyzer"].analyze = ports["dynamics_analyzer"]._run
        stage = CapabilityStagePort(
            "analyze_dynamics",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "source_dynamics_analysis"):
            stage.run(context=object(), input_artifacts=[])

    def test_generated_ui_port_requires_exact_ocr_and_layout_evidence(self):
        from server.capability_ports import CapabilityStagePort

        manifest, ports = _manifest_and_ports()
        ports["ocr_ui_renderer"]._run = lambda **_: {
            "ui_truth_card": {"screens": ["home"]},
            "ui_render_contract": {"screens": ["home"]},
            "rendered_media": {"object_key": "tenant/run/ui.mp4", "sha256": "a" * 64},
            "ocr_match_percent": 99,
            "layout_match_percent": 100,
        }
        ports["ocr_ui_renderer"].render_and_verify = ports["ocr_ui_renderer"]._run
        stage = CapabilityStagePort(
            "resolve_ui_evidence",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "OCR.*100"):
            stage.run(context=object(), input_artifacts=[])

    def test_direct_stage_keeps_canonical_evidence_at_stage_output_boundary(self):
        from server.capability_ports import CapabilityStagePort

        manifest, ports = _manifest_and_ports()
        stage = CapabilityStagePort(
            "splice_timeline",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        output = stage.run(context=object(), input_artifacts=[])
        self.assertIn("output_artifact", output)
        self.assertIn("timeline_manifest", output)
        self.assertIn("capability_receipt", output)

    def test_active_qc_stage_rejects_technical_only_pass_from_custom_adapter(self):
        from server.capability_ports import CapabilityStagePort

        manifest, ports = _manifest_and_ports()
        stage = CapabilityStagePort(
            "run_qc",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "weighted|high-fidelity QC"):
            stage.run(context=object(), input_artifacts=[])

    def test_active_qc_stage_rejects_extension_without_current_media_bindings(self):
        """A valid weighted extension alone must not bypass output/source binding."""

        from server.capability_ports import CapabilityStagePort

        evidence = {
            "evidence_id": "QC-E-UNBOUND",
            "kind": "contract",
            "method": "deterministic_measurement",
            "source_ref": {
                "pointer": "/source/C01",
                "artifact_sha256": "a" * 64,
                "start_ms": 0,
                "end_ms": 100,
            },
            "target_ref": {
                "pointer": "/final/C01",
                "artifact_sha256": "b" * 64,
                "start_ms": 0,
                "end_ms": 100,
            },
            "observation": "the measured source and output contract match",
        }
        from high_fidelity_qc import WEIGHTS, build_qc_extension
        extension = build_qc_extension(
            dimensions={
                name: {
                    "score": 100,
                    "criticality": "H" if name == "voiceover_audio" else "M",
                    "evidence": [
                        dict(evidence, kind="asr")
                        if name == "voiceover_audio"
                        else dict(evidence)
                    ],
                }
                for name in WEIGHTS
            },
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
            factor_scores={
                "HFH.C01.ACTION.ENDPOINT": {
                    "score": 100,
                    "criticality": "H",
                    "evidence": [dict(evidence)],
                }
            },
        )
        manifest, ports = _manifest_and_ports()
        ports["qc_engine"].run = lambda **_: {
            "passed": True,
            "qc_report": {"status": "passed", "high_fidelity_qc_extension": extension},
            "high_fidelity_qc_extension": extension,
        }

        class Context:
            input_slots = ({"slot_id": "source_video", "present": True, "sha256": ["a" * 64]},)
            artifacts = ({"kind": "assembled_video", "sha256": "b" * 64},)

        stage = CapabilityStagePort(
            "run_qc",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "media_bindings|current final output"):
            stage.run(context=Context(), input_artifacts=[])

    def test_active_qc_stage_rejects_media_bindings_for_another_run(self):
        """A structurally valid extension must bind this run's final/source digests."""

        from high_fidelity_qc import WEIGHTS, build_qc_extension
        from server.capability_ports import CapabilityStagePort

        stale_source = "d" * 64
        stale_output = "c" * 64
        evidence = {
            "evidence_id": "QC-E-STALE",
            "kind": "contract",
            "method": "deterministic_measurement",
            "source_ref": {
                "pointer": "/source/C01",
                "artifact_sha256": stale_source,
                "start_ms": 0,
                "end_ms": 100,
            },
            "target_ref": {
                "pointer": "/final/C01",
                "artifact_sha256": stale_output,
                "start_ms": 0,
                "end_ms": 100,
            },
            "observation": "the measured source and output contract match",
        }
        extension = build_qc_extension(
            dimensions={
                name: {
                    "score": 100,
                    "criticality": "H" if name == "voiceover_audio" else "M",
                    "evidence": [
                        dict(evidence, kind="asr")
                        if name == "voiceover_audio"
                        else dict(evidence)
                    ],
                }
                for name in WEIGHTS
            },
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
            factor_scores={
                "HFH.C01.ACTION.ENDPOINT": {
                    "score": 100,
                    "criticality": "H",
                    "evidence": [dict(evidence)],
                }
            },
            media_bindings={
                "final_output_sha256": stale_output,
                "current_run_source_sha256s": [stale_source],
            },
        )
        manifest, ports = _manifest_and_ports()
        ports["qc_engine"].run = lambda **_: {
            "passed": True,
            "qc_report": {"status": "passed", "high_fidelity_qc_extension": extension},
            "high_fidelity_qc_extension": extension,
        }

        class Context:
            input_slots = ({"slot_id": "source_video", "present": True, "sha256": ["a" * 64]},)
            artifacts = ({"kind": "assembled_video", "sha256": "b" * 64},)

        stage = CapabilityStagePort(
            "run_qc",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "current final output|current run source"):
            stage.run(context=Context(), input_artifacts=[])

    def test_active_qc_stage_accepts_a_recomputed_evidence_bearing_extension(self):
        from high_fidelity_qc import WEIGHTS, _dimensions_digest, _factor_scores_digest, build_qc_extension
        from server.capability_ports import CapabilityStagePort, _canonical_sha256

        evidence = {
            "evidence_id": "QC-E-001",
            "kind": "contract",
            "method": "deterministic_measurement",
            "source_ref": {
                "pointer": "/source/C01",
                "artifact_sha256": "a" * 64,
                "start_ms": 0,
                "end_ms": 100,
            },
            "target_ref": {
                "pointer": "/final/C01",
                "artifact_sha256": "b" * 64,
                "start_ms": 0,
                "end_ms": 100,
            },
            "observation": "the measured source and output contract match",
        }
        dimensions = {
            name: {
                "score": 100,
                "criticality": "H" if name == "voiceover_audio" else "M",
                "evidence": [
                    dict(evidence, kind="asr")
                    if name == "voiceover_audio"
                    else dict(evidence)
                ],
            }
            for name in WEIGHTS
        }
        factor_scores = {
            "HFH.C01.ACTION.ENDPOINT": {
                "score": 100,
                "criticality": "H",
                "evidence": [dict(evidence)],
            }
        }
        response_payload = build_qc_extension(
            dimensions=dimensions,
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
            factor_scores=factor_scores,
            media_bindings={
                "final_output_sha256": "b" * 64,
                "current_run_source_sha256s": ["a" * 64],
            },
        )
        request_payload = {
            "schema_version": "high-fidelity-qc-evaluator-request/v1",
            "final_output_sha256": "b" * 64,
            "current_run_source_sha256s": ["a" * 64],
            "input_artifact_sha256s": [],
        }
        evaluator_receipt = {
            "schema_version": "high-fidelity-qc-evaluator-receipt/v1",
            "provenance": "independent_evaluator",
            "implementation": "tests.evidence-bound-qc",
            "version": "test-v1",
            "model_id": "test-qc-model",
            "model_sha256": "c" * 64,
            "request_sha256": _canonical_sha256(request_payload),
            "response_sha256": _canonical_sha256(response_payload),
            "dimensions_sha256": _dimensions_digest(dimensions),
            "factor_scores_sha256": _factor_scores_digest(factor_scores),
            "final_output_sha256": "b" * 64,
            "current_run_source_sha256s": ["a" * 64],
        }
        extension = build_qc_extension(
            dimensions=dimensions,
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
            factor_scores=factor_scores,
            media_bindings={
                "final_output_sha256": "b" * 64,
                "current_run_source_sha256s": ["a" * 64],
            },
            evaluator_receipt=evaluator_receipt,
        )
        manifest, ports = _manifest_and_ports()
        ports["qc_engine"].run = lambda **_: {
            "passed": True,
            "qc_report": {"status": "passed", "high_fidelity_qc_extension": extension},
            "high_fidelity_qc_extension": extension,
        }
        stage = CapabilityStagePort(
            "run_qc",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        class Context:
            input_slots = ({"slot_id": "source_video", "present": True, "sha256": ["a" * 64]},)
            artifacts = ({"kind": "assembled_video", "sha256": "b" * 64},)
            high_fidelity_qc_evaluator_identity = {
                "implementation": "tests.evidence-bound-qc",
                "version": "test-v1",
                "model_id": "test-qc-model",
                "model_sha256": "c" * 64,
            }

        output = stage.run(context=Context(), input_artifacts=[])
        self.assertTrue(output["high_fidelity_qc_extension"]["accepted"])

    def test_active_qc_stage_rejects_fabricated_evaluator_receipt_digests(self):
        """A custom status-only adapter cannot invent request/response SHA values."""

        from high_fidelity_qc import WEIGHTS, _dimensions_digest, _factor_scores_digest, build_qc_extension
        from server.capability_ports import CapabilityStagePort

        evidence = {
            "evidence_id": "QC-E-FABRICATED",
            "kind": "contract",
            "method": "deterministic_measurement",
            "source_ref": {
                "pointer": "/source/C01",
                "artifact_sha256": "a" * 64,
                "start_ms": 0,
                "end_ms": 100,
            },
            "target_ref": {
                "pointer": "/final/C01",
                "artifact_sha256": "b" * 64,
                "start_ms": 0,
                "end_ms": 100,
            },
            "observation": "the measured source and output contract match",
        }
        dimensions = {
            name: {
                "score": 100,
                "criticality": "H" if name == "voiceover_audio" else "M",
                "evidence": [
                    dict(evidence, kind="asr")
                    if name == "voiceover_audio"
                    else dict(evidence)
                ],
            }
            for name in WEIGHTS
        }
        factor_scores = {
            "HFH.C01.ACTION.ENDPOINT": {
                "score": 100,
                "criticality": "H",
                "evidence": [dict(evidence)],
            }
        }
        evaluator_receipt = {
            "schema_version": "high-fidelity-qc-evaluator-receipt/v1",
            "provenance": "independent_evaluator",
            "implementation": "tests.status-only-qc",
            "version": "test-v1",
            "model_id": "test-qc-model",
            "model_sha256": "c" * 64,
            "request_sha256": "d" * 64,
            "response_sha256": "e" * 64,
            "dimensions_sha256": _dimensions_digest(dimensions),
            "factor_scores_sha256": _factor_scores_digest(factor_scores),
            "final_output_sha256": "b" * 64,
            "current_run_source_sha256s": ["a" * 64],
        }
        extension = build_qc_extension(
            dimensions=dimensions,
            route_coverage=100,
            ui_ocr=100,
            hard_failures=[],
            factor_scores=factor_scores,
            media_bindings={
                "final_output_sha256": "b" * 64,
                "current_run_source_sha256s": ["a" * 64],
            },
            evaluator_receipt=evaluator_receipt,
        )
        manifest, ports = _manifest_and_ports()
        ports["qc_engine"].run = lambda **_: {
            "passed": True,
            "qc_report": {"status": "passed", "high_fidelity_qc_extension": extension},
            "high_fidelity_qc_extension": extension,
        }

        class Context:
            input_slots = ({"slot_id": "source_video", "present": True, "sha256": ["a" * 64]},)
            artifacts = ({"kind": "assembled_video", "sha256": "b" * 64},)
            high_fidelity_qc_evaluator_identity = {
                "implementation": "tests.status-only-qc",
                "version": "test-v1",
                "model_id": "test-qc-model",
                "model_sha256": "c" * 64,
            }

        stage = CapabilityStagePort(
            "run_qc",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "request SHA|response SHA|evaluator identity"):
            stage.run(context=Context(), input_artifacts=[])

    def test_compositor_rejects_a_local_output_path_in_production(self):
        from server.capability_ports import CapabilityStagePort

        manifest, ports = _manifest_and_ports()
        ports["compositor"]._run = lambda **_: {
            "output_artifact": {"object_key": r"C:\\worker\\result.mp4", "sha256": "c" * 64},
            "timeline_manifest": {"regions": ["R01"]},
        }
        ports["compositor"].compose = ports["compositor"]._run
        stage = CapabilityStagePort(
            "splice_timeline",
            ports,
            manifest=manifest,
            production=True,
            profile_active=True,
        )
        with self.assertRaisesRegex(ValueError, "local output"):
            stage.run(context=object(), input_artifacts=[])

if __name__ == "__main__":
    unittest.main()
