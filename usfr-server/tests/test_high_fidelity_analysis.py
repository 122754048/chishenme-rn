from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "high_fidelity_analysis.py"
SCHEMA = ROOT / "schemas" / "high_fidelity_analysis.schema.json"


LEGACY_WEIGHTS = {
    "commercial_goal": 20,
    "attention_hook": 15,
    "character_or_creator_appeal": 10,
    "product_proof": 20,
    "emotional_promise": 10,
    "social_or_trust_signal": 10,
    "cta_conversion": 8,
    "pacing_and_format": 5,
    "platform_compliance": 2,
}


def load_module():
    if not SCRIPT.is_file():
        raise AssertionError(f"missing implementation: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("high_fidelity_analysis", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(evidence_id: str, *, kind: str = "frame", state_id: str | None = None):
    value = {
        "evidence_id": evidence_id,
        "origin": "slot",
        "object_key": f"tenant/run/evidence/{evidence_id}.json",
        "kind": kind,
        "start_ms": 0,
        "end_ms": 900,
        "frame": 12,
        "method": "frame boundary review",
        "observed_inferred_planned": "observed",
        "confidence": 0.95,
    }
    if state_id is not None:
        value["state_id"] = state_id
    return value


def intent_node(
    node_id: str,
    stage: str,
    cut_id: str,
    weight_share: dict[str, int],
):
    total = sum(weight_share.values())
    return {
        "node_id": node_id,
        "stage": stage,
        "status": "active",
        "cut_ids": [cut_id],
        "time_ranges": [{"start_ms": 0, "end_ms": 900}],
        "audience_state_before": "not yet persuaded",
        "audience_state_after": f"advanced through {stage}",
        "commercial_job": f"perform the {stage} persuasion job",
        "presentation_archetype": "evidence-led demonstration",
        "attention_mechanism": "visible state change",
        "proof_mechanism": "observable result",
        "emotional_identity_function": "make the outcome relevant",
        "trust_objection_function": "show rather than assert",
        "cta_relationship": "moves toward the approved next action",
        "evidence": [evidence(f"E-{node_id}")],
        "observed_inferred_planned": "observed",
        "confidence": 0.94,
        "uncertainty": [],
        "criticality": "H" if stage in {"Attention", "Belief", "Action"} else "M",
        "blocker_threshold": 0.8,
        "legacy_projection": {
            "legacy_intent_keys": list(weight_share),
            "weight_share": weight_share,
            "cut_allocation": {cut_id: total},
            "projection_reason": "assign each legacy point once to an evidenced Cut",
        },
    }


def valid_analysis():
    nodes = [
        intent_node(
            "SIG-ATT",
            "Attention",
            "C01",
            {"attention_hook": 15, "character_or_creator_appeal": 10},
        ),
        intent_node("SIG-CUR", "Curiosity", "C02", {"pacing_and_format": 5}),
        intent_node(
            "SIG-UND",
            "Understanding",
            "C03",
            {"commercial_goal": 10, "product_proof": 10},
        ),
        intent_node(
            "SIG-BEL",
            "Belief",
            "C04",
            {"product_proof": 10, "social_or_trust_signal": 10},
        ),
        intent_node("SIG-DES", "Desire", "C05", {"emotional_promise": 10}),
        intent_node(
            "SIG-ACT",
            "Action",
            "C06",
            {"commercial_goal": 10, "cta_conversion": 8},
        ),
        intent_node("SIG-LOOP", "Loop", "C07", {"platform_compliance": 2}),
    ]
    target_node = {
        "node_id": "TVG-001",
        "target_truth_refs": ["slot:new_product_image:sha256"],
        "feature": "verified push-button operation",
        "mechanism": "the supplied product evidence shows the control",
        "benefit": "the user can start the demonstrated action directly",
        "proof": ["PF-001"],
        "audience_relevance": "reduces setup effort",
        "objection_resolved": "the action is visibly demonstrated",
        "trust_signal": "target-owned product evidence",
        "cta": "view the product details",
        "evidence": [evidence("E-TARGET")],
        "observed_inferred_planned": "planned",
        "confidence": 0.95,
        "uncertainty": [],
        "criticality": "H",
        "blocker_threshold": 0.8,
    }
    migrations = [
        {
            "edge_id": f"ME-{index:02d}",
            "source_node_id": node["node_id"],
            "target_node_id": "TVG-001",
            "mapping": "exact",
            "invariant_ids": [f"INV-{index:02d}"],
            "invariant_summary": "preserve the source commercial job and proof burden",
            "changed_form": "replace only target product truth",
            "proof_equivalence": "exact",
            "evidence": [evidence(f"E-ME-{index:02d}")],
            "observed_inferred_planned": "planned",
            "fidelity_level": 1,
            "route": "REPLACE",
            "confidence": 0.92,
            "uncertainty": [],
            "criticality": node["criticality"],
            "blocker_threshold": 0.8,
        }
        for index, node in enumerate(nodes, start=1)
    ]
    claim = {
        "claim_id": "CLM-001",
        "claim_class": "feature",
        "claim_risk_class": "ordinary",
        "source_expression": {
            "cut_ids": ["C03"],
            "time_range": {"start_ms": 1800, "end_ms": 2700},
            "modalities": ["visual", "action"],
        },
        "source_evidence": [evidence("E-CLAIM-SOURCE")],
        "target_truth_refs": ["slot:new_product_image:sha256"],
        "target_evidence": [evidence("E-CLAIM-TARGET")],
        "support_status": "supported",
        "analysis_disposition": "exact",
        "feature": "verified push-button operation",
        "mechanism": "the visible button starts the demonstrated action",
        "benefit": "direct operation",
        "proof": ["PF-001"],
        "audience_relevance": "reduces setup effort",
        "objection_resolved": "the control is visible",
        "trust_signal": "target-owned evidence",
        "cta": "view the product details",
        "proof_substitution": "exact",
        "route": "REPLACE",
        "route_by_layer": {"product": "COMPOSITE", "speech": "REPLACE"},
        "carrier": "deterministic_composite",
        "observed_inferred_planned": "planned",
        "confidence": 0.95,
        "uncertainty": [],
        "criticality": "H",
        "blocker_threshold": 0.8,
        "risk_flags": [],
    }
    affordance = {
        "affordance_id": "AFF-001",
        "target_kind": "physical_product",
        "source_primitive_id": "ACT-001",
        "source_commercial_function": "demonstrate direct operation",
        "source_state_sequence": ["idle", "contact", "activated"],
        "target_truth_refs": ["slot:new_product_image:sha256"],
        "target_affordance": "press the verified control",
        "target_state_sequence": [
            {"state_id": "idle", "evidence_refs": ["E-AFF-IDLE"]},
            {"state_id": "activated", "evidence_refs": ["E-AFF-ACTIVE"]},
        ],
        "target_proof_event": "visible activation result",
        "proof_event_ids": ["PF-001"],
        "audio_event_ids": ["AU-001"],
        "physical_feasibility": "feasible",
        "temporal_feasibility": "feasible",
        "evidence_feasibility": "feasible",
        "match_level": "exact",
        "fidelity_level": 1,
        "route": "COMPOSITE",
        "fallback_route": "REMOVE",
        "carrier": "deterministic_composite",
        "match_reason": "the target evidence shows the same observable state change",
        "evidence": [
            evidence("E-AFF-IDLE", state_id="idle"),
            evidence("E-AFF-ACTIVE", state_id="activated"),
        ],
        "observed_inferred_planned": "planned",
        "confidence": 0.93,
        "uncertainty": [],
        "criticality": "H",
        "blocker_threshold": 0.8,
    }
    return {
        "contract": "high-fidelity-analysis",
        "contract_version": 1,
        "profile": "high_fidelity_hybrid_v1",
        "parent_digests": {
            "source_fidelity_contract_sha256": "a" * 64,
            "target_truth_sha256": "b" * 64,
        },
        "legacy_intent_weights": LEGACY_WEIGHTS.copy(),
        "source_intent_graph": {
            "sequence": [
                "Attention",
                "Curiosity",
                "Understanding",
                "Belief",
                "Desire",
                "Action",
                "Loop",
            ],
            "nodes": nodes,
        },
        "target_value_graph": {"nodes": [target_node]},
        "migration_edges": migrations,
        "claim_atoms": [claim],
        "affordance_ledger": [affordance],
        "layer_ledger": [
            {
                "cut_id": "C01",
                "layers": [
                    {
                        "factor_id": "F-BG-001",
                        "layer_id": "background",
                        "route": "KEEP",
                        "fidelity_level": 0,
                        "carrier": "source_interval",
                        "changes_output": False,
                        "evidence": [evidence("E-BG")],
                        "observed_inferred_planned": "observed",
                        "confidence": 0.96,
                        "uncertainty": [],
                        "criticality": "M",
                        "blocker_threshold": 0.8,
                    },
                    {
                        "factor_id": "F-PROD-001",
                        "layer_id": "product",
                        "route": "COMPOSITE",
                        "fidelity_level": 0,
                        "carrier": "deterministic_composite",
                        "changes_output": True,
                        "evidence": [evidence("E-PROD")],
                        "observed_inferred_planned": "planned",
                        "confidence": 0.96,
                        "uncertainty": [],
                        "criticality": "H",
                        "blocker_threshold": 0.8,
                    },
                ],
            },
            {
                "cut_id": "C02",
                "layers": [
                    {
                        "factor_id": "F-ACT-001",
                        "layer_id": "performance",
                        "route": "REPLACE",
                        "fidelity_level": 1,
                        "carrier": "seedance_generation",
                        "changes_output": True,
                        "evidence": [evidence("E-ACT")],
                        "observed_inferred_planned": "planned",
                        "confidence": 0.91,
                        "uncertainty": [],
                        "criticality": "H",
                        "blocker_threshold": 0.8,
                    }
                ],
            },
        ],
        "route_exclusions": [],
    }


class HighFidelityAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_schema_is_valid_draft_2020_12(self):
        self.assertTrue(SCHEMA.is_file(), SCHEMA)
        from jsonschema import Draft202012Validator

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(valid_analysis())

    def test_validates_and_projects_the_exact_legacy_nine_key_contract(self):
        value = valid_analysis()
        self.module.validate_analysis(value)
        projection = self.module.project_legacy_intent(value)
        self.assertEqual(projection["weights"], LEGACY_WEIGHTS)
        self.assertEqual(sum(projection["weights"].values()), 100)
        self.assertEqual(
            [row["stage"] for row in projection["cut_allocation"]],
            value["source_intent_graph"]["sequence"],
        )

    def test_rejects_legacy_weights_that_do_not_total_100(self):
        value = valid_analysis()
        value["legacy_intent_weights"]["commercial_goal"] -= 1
        with self.assertRaisesRegex(ValueError, "must total 100"):
            self.module.validate_analysis(value)

    def test_rejects_projection_points_that_are_not_assigned_exactly_once(self):
        value = valid_analysis()
        value["source_intent_graph"]["nodes"][0]["legacy_projection"][
            "weight_share"
        ]["attention_hook"] -= 1
        value["source_intent_graph"]["nodes"][0]["legacy_projection"][
            "cut_allocation"
        ]["C01"] -= 1
        with self.assertRaisesRegex(ValueError, "projection does not equal legacy weights"):
            self.module.validate_analysis(value)

    def test_rejects_claim_disposition_projection_mismatch(self):
        value = valid_analysis()
        value["claim_atoms"][0]["analysis_disposition"] = "partial"
        with self.assertRaisesRegex(ValueError, "must project to reinterpreted"):
            self.module.validate_analysis(value)

    def test_unsupported_claim_is_recorded_but_cannot_reach_script_projection(self):
        value = valid_analysis()
        claim = value["claim_atoms"][0]
        claim.update(
            {
                "support_status": "unsupported",
                "analysis_disposition": "prohibited",
                "target_evidence": [],
                "proof": [],
                "proof_substitution": "none",
                "route": "REMOVE",
                "route_by_layer": {"speech": "REMOVE", "overlay": "REMOVE"},
                "carrier": "route_excluded",
            }
        )
        self.module.validate_analysis(value)
        selling_points = self.module.project_selling_point_mapping(value)
        script_claims = self.module.project_script_claims(value)
        self.assertEqual(selling_points[0]["status"], "unsupported")
        self.assertFalse(selling_points[0]["script_eligible"])
        self.assertEqual(script_claims, [])

    def test_rejects_high_criticality_factor_without_evidence_or_carrier(self):
        value = valid_analysis()
        layer = value["layer_ledger"][0]["layers"][1]
        layer["evidence"] = []
        layer["carrier"] = ""
        with self.assertRaisesRegex(ValueError, "high-criticality.*evidence"):
            self.module.validate_analysis(value)

    def test_rejects_high_criticality_factor_below_its_blocker_threshold(self):
        value = valid_analysis()
        value["layer_ledger"][0]["layers"][1]["confidence"] = 0.7
        with self.assertRaisesRegex(ValueError, "below blocker threshold"):
            self.module.validate_analysis(value)

    def test_rejects_high_criticality_claim_below_its_blocker_threshold(self):
        value = valid_analysis()
        value["claim_atoms"][0]["confidence"] = 0.7
        with self.assertRaisesRegex(ValueError, "below blocker threshold"):
            self.module.validate_analysis(value)

    def test_app_screenshot_cannot_prove_an_unseen_ui_state(self):
        value = valid_analysis()
        affordance = value["affordance_ledger"][0]
        affordance["target_kind"] = "app"
        affordance["evidence"] = [
            evidence("E-UI-HOME", kind="screenshot", state_id="home")
        ]
        affordance["target_state_sequence"] = [
            {"state_id": "home", "evidence_refs": ["E-UI-HOME"]},
            {"state_id": "result", "evidence_refs": []},
        ]
        with self.assertRaisesRegex(ValueError, "unseen UI state result"):
            self.module.validate_analysis(value)

    def test_aggregates_cut_layers_from_actual_carriers(self):
        value = valid_analysis()
        self.module.validate_analysis(value)
        aggregate = self.module.aggregate_layer_ledger(value["layer_ledger"])
        self.assertEqual(
            aggregate,
            [
                {
                    "cut_id": "C01",
                    "media_origin": "composite",
                    "assembly_policy": "compose_region",
                    "changes_output": True,
                },
                {
                    "cut_id": "C02",
                    "media_origin": "generated",
                    "assembly_policy": "generate_region",
                    "changes_output": True,
                },
            ],
        )

    def test_projection_exports_frozen_high_criticality_factor_sources(self):
        projection = self.module.build_projection(valid_analysis())
        self.assertEqual(
            projection["required_factor_ids"],
            ["F-ACT-001", "F-PROD-001"],
        )
        self.assertEqual(
            [row["factor_id"] for row in projection["factor_sources"]],
            projection["required_factor_ids"],
        )
        self.assertEqual(
            {row["source_pointer"] for row in projection["factor_sources"]},
            {
                "/layer_ledger/C01/product/F-PROD-001",
                "/layer_ledger/C02/performance/F-ACT-001",
            },
        )

    def test_sidecar_requires_a_non_empty_layer_ledger(self):
        value = valid_analysis()
        value["layer_ledger"] = []
        with self.assertRaisesRegex(ValueError, "layer_ledger must be non-empty"):
            self.module.validate_analysis(value)

    def test_route_exclusion_accepts_only_technical_evidence(self):
        value = valid_analysis()
        value["route_exclusions"] = [
            {
                "region_id": "R-OPAQUE-UI",
                "reason": "opaque UI content is excluded from semantic analysis",
                "technical_evidence": [evidence("E-OPAQUE-BOUNDARY")],
            }
        ]
        self.module.validate_analysis(value)
        value["route_exclusions"][0]["semantic_claim"] = "must not be inspected"
        with self.assertRaisesRegex(ValueError, "technical metadata only"):
            self.module.validate_analysis(value)

    def test_functional_analogous_proof_requires_level_2_reinterpretation(self):
        value = valid_analysis()
        edge = value["migration_edges"][0]
        edge.update(
            {
                "mapping": "functional",
                "proof_equivalence": "analogous",
                "fidelity_level": 1,
                "route": "REPLACE",
            }
        )
        with self.assertRaisesRegex(ValueError, "analogous functional proof"):
            self.module.validate_analysis(value)

    def test_every_factor_requires_explicit_provenance_and_uncertainty(self):
        value = valid_analysis()
        del value["source_intent_graph"]["nodes"][0]["observed_inferred_planned"]
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.module.validate_analysis(value)
        value = valid_analysis()
        del value["claim_atoms"][0]["uncertainty"]
        with self.assertRaisesRegex(ValueError, "uncertainty"):
            self.module.validate_analysis(value)

    def test_canonical_references_define_the_additive_analysis_sidecar(self):
        universal = (ROOT / "references" / "universal-source-fidelity-contract.md").read_text(
            encoding="utf-8"
        )
        intent = (
            ROOT
            / "bundled-skills"
            / "seedance-storyboard-replication"
            / "references"
            / "intent-analysis.md"
        ).read_text(encoding="utf-8")
        combined = universal + "\n" + intent
        for required in (
            "high_fidelity_analysis.json",
            "Source Intent Graph",
            "Attention -> Curiosity -> Understanding -> Belief -> Desire -> Action -> Loop",
            "Target Value Graph",
            "claim atom",
            "affordance ledger",
            "layer ledger",
            "supported|unsupported|reinterpreted",
            "exact|functional|intent_only|unsupported",
            "legacy nine-key",
            "total 100",
            "does not change the public workflow",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

    def test_bundle_registers_analysis_runtime_and_dynamics_validator(self):
        manifest = json.loads(
            (ROOT / "references" / "bundle_manifest.json").read_text(encoding="utf-8")
        )
        runtime_paths = {item["path"] for item in manifest["runtime_files"]}
        self.assertIn("scripts/high_fidelity_analysis.py", runtime_paths)
        self.assertIn("schemas/high_fidelity_analysis.schema.json", runtime_paths)
        verify_spec = importlib.util.spec_from_file_location(
            "verify_bundle_for_analysis", ROOT / "scripts" / "verify_bundle.py"
        )
        assert verify_spec and verify_spec.loader
        verify_module = importlib.util.module_from_spec(verify_spec)
        verify_spec.loader.exec_module(verify_module)
        self.assertIn("scripts/high_fidelity_analysis.py", verify_module.REQUIRED_TOP_LEVEL_FILES)
        self.assertIn(
            "schemas/high_fidelity_analysis.schema.json",
            verify_module.REQUIRED_RUNTIME_CONTRACTS,
        )
        self.assertIn(
            "scripts/validate_high_fidelity_extension.py",
            verify_module.REQUIRED_MODULE_FILES["analyze-reference-video-dynamics"],
        )


if __name__ == "__main__":
    unittest.main()
