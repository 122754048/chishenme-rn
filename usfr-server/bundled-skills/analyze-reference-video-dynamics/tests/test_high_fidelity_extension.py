from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_high_fidelity_extension.py"


def load_module():
    if not SCRIPT.is_file():
        raise AssertionError(f"missing implementation: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("validate_high_fidelity_extension", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_contract():
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
                "content_roles": ["creator", "product"],
                "scene": "creator at a table",
                "action": "reaches, presses the product, and settles into a hold",
                "camera": "locked medium shot",
                "transition": "starts on first decoded frame",
                "end_state": "finger released and product active",
                "certainty": "certain",
            }
        ],
        "source_events": [
            {
                "event": 1,
                "kind": "dialogue",
                "start_us": 0,
                "end_us": 900_000,
                "source_cut_start": 1,
                "source_cut_end": 1,
                "text": "example",
                "certainty": "certain",
            }
        ],
        "notes": [],
    }


def ev(evidence_id: str):
    return {
        "evidence_id": evidence_id,
        "kind": "frame",
        "start_us": 0,
        "end_us": 1_000_000,
        "frame": 12,
        "method": "adaptive boundary frame review",
        "observed_inferred_planned": "observed",
        "confidence": 0.95,
    }


def valid_extension_contract():
    value = base_contract()
    value["extensions"] = {
        "high_fidelity_hybrid_v1": {
            "schema_version": 1,
            "analysis_pass_count": 1,
            "semantic_cuts": [
                {
                    "cut": 1,
                    "scene_topology": {
                        "entities": [
                            {
                                "entity_id": "creator",
                                "layer": "foreground",
                                "bbox": [0.20, 0.10, 0.55, 0.75],
                                "z_order": 3,
                                "relation_to_camera": "faces camera across table",
                            },
                            {
                                "entity_id": "product",
                                "layer": "foreground",
                                "bbox": [0.48, 0.55, 0.18, 0.20],
                                "z_order": 4,
                                "relation_to_camera": "between creator and lens",
                            },
                        ],
                        "spatial_relations": ["product rests on tabletop in front of creator"],
                        "occlusion_order": ["creator", "hand", "product"],
                        "table_line_y": 0.67,
                        "horizon_y": 0.32,
                        "negative_space": [0.76, 0.08, 0.20, 0.42],
                    },
                    "framing_migration": {
                        "strategy": "crop",
                        "anchors": [
                            {"anchor_id": "creator", "bbox": [0.20, 0.10, 0.55, 0.75]},
                            {"anchor_id": "product", "bbox": [0.48, 0.55, 0.18, 0.20]},
                        ],
                        "topology_constraint": "keep creator, tabletop, and product relationship",
                    },
                    "lighting": {
                        "key_origin": "camera-left",
                        "key_vector": [-0.7, -0.2, 0.5],
                        "hardness": "soft",
                        "contrast_ratio": 2.5,
                        "color_temperature_k": 4200,
                        "shadow_vector": [0.4, 0.2, 0.0],
                    },
                    "performance": {
                        "applicability": "person_present",
                        "posture": "slight forward lean with shoulders level",
                        "gaze_phases": [
                            {"start_us": 0, "end_us": 500_000, "target": "product"},
                            {"start_us": 500_000, "end_us": 1_000_000, "target": "camera"},
                        ],
                        "expression_phases": [
                            {"start_us": 0, "end_us": 1_000_000, "state": "focused and quiet"}
                        ],
                        "gesture_phases": [
                            {
                                "start_us": 0,
                                "end_us": 1_000_000,
                                "hand": "right",
                                "path": "table to control and back to a settled hold",
                                "end_state": "index finger released from control",
                            }
                        ],
                        "objective": "demonstrate the product quietly",
                        "visible_tactic": "press the control while keeping the product readable",
                        "emotional_turn": "focus changes to confirmation",
                        "microphone_relation": "mouth remains one palm from tabletop microphone",
                    },
                    "object_action": {
                        "state_sequence": [
                            {"phase": "before", "start_us": 0, "end_us": 150_000, "state": "idle"},
                            {"phase": "approach", "start_us": 150_000, "end_us": 350_000, "state": "finger approaches"},
                            {"phase": "contact", "start_us": 350_000, "end_us": 500_000, "state": "finger contacts control"},
                            {"phase": "applied_force", "start_us": 500_000, "end_us": 650_000, "state": "control depressed"},
                            {"phase": "proof", "start_us": 650_000, "end_us": 850_000, "state": "activation visible"},
                            {"phase": "completed", "start_us": 850_000, "end_us": 1_000_000, "state": "finger released and product active"},
                        ],
                        "hand_ownership": "creator right hand",
                        "contact_points": ["right index fingertip to product control"],
                        "movement_trajectory": "downward press then upward release",
                        "completed_end_state": "finger released and product active",
                        "caused_audio_event_ids": [1],
                    },
                    "speech_audio": {
                        "exact_asr_event_ids": [1],
                        "audio_event_mappings": [
                            {
                                "event_id": 1,
                                "role": "dialogue",
                                "synced_factor_id": "object_action:proof",
                                "evidence": [ev("E-AUDIO-1")],
                            }
                        ],
                        "meaningful_silence_ranges": [],
                    },
                    "evidence": [ev("E-CUT-1")],
                    "observed_inferred_planned": "observed",
                    "confidence": 0.94,
                    "uncertainty": [],
                    "criticality": "H",
                    "blocker_threshold": 0.8,
                }
            ],
            "route_excluded_intervals": [],
        }
    }
    return value


class HighFidelityDynamicsExtensionTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_legacy_contract_without_extension_remains_valid(self):
        self.module.validate_high_fidelity_extension(base_contract())

    def test_validates_complete_single_pass_extension(self):
        self.module.validate_high_fidelity_extension(valid_extension_contract())

    def test_rejects_a_second_routine_full_video_pass(self):
        value = valid_extension_contract()
        value["extensions"]["high_fidelity_hybrid_v1"]["analysis_pass_count"] = 2
        with self.assertRaisesRegex(ValueError, "analysis_pass_count must be 1"):
            self.module.validate_high_fidelity_extension(value)

    def test_rejects_missing_performance_phase_detail(self):
        for field in ("posture", "gaze_phases", "expression_phases", "gesture_phases"):
            value = valid_extension_contract()
            del value["extensions"]["high_fidelity_hybrid_v1"]["semantic_cuts"][0][
                "performance"
            ][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                self.module.validate_high_fidelity_extension(value)

    def test_rejects_missing_completed_object_action_endpoint(self):
        value = valid_extension_contract()
        action = value["extensions"]["high_fidelity_hybrid_v1"]["semantic_cuts"][0][
            "object_action"
        ]
        action["state_sequence"] = action["state_sequence"][:-1]
        action["completed_end_state"] = ""
        with self.assertRaisesRegex(ValueError, "completed action endpoint"):
            self.module.validate_high_fidelity_extension(value)

    def test_rejects_geometry_outside_normalized_space(self):
        value = valid_extension_contract()
        value["extensions"]["high_fidelity_hybrid_v1"]["semantic_cuts"][0][
            "scene_topology"
        ]["entities"][0]["bbox"] = [0.8, 0.1, 0.4, 0.6]
        with self.assertRaisesRegex(ValueError, "normalized bbox"):
            self.module.validate_high_fidelity_extension(value)

    def test_rejects_missing_framing_migration(self):
        value = valid_extension_contract()
        del value["extensions"]["high_fidelity_hybrid_v1"]["semantic_cuts"][0][
            "framing_migration"
        ]
        with self.assertRaisesRegex(ValueError, "framing_migration"):
            self.module.validate_high_fidelity_extension(value)

    def test_rejects_missing_audio_proof_mapping(self):
        value = valid_extension_contract()
        value["extensions"]["high_fidelity_hybrid_v1"]["semantic_cuts"][0][
            "speech_audio"
        ]["audio_event_mappings"] = []
        with self.assertRaisesRegex(ValueError, "audio event 1 is not mapped"):
            self.module.validate_high_fidelity_extension(value)

    def test_rejects_high_criticality_cut_below_blocker_threshold(self):
        value = valid_extension_contract()
        value["extensions"]["high_fidelity_hybrid_v1"]["semantic_cuts"][0][
            "confidence"
        ] = 0.7
        with self.assertRaisesRegex(ValueError, "below blocker threshold"):
            self.module.validate_high_fidelity_extension(value)

    def test_rejects_source_identity_or_brand_leakage_fields(self):
        value = valid_extension_contract()
        value["extensions"]["high_fidelity_hybrid_v1"]["semantic_cuts"][0][
            "source_person_name"
        ] = "private source identity"
        with self.assertRaisesRegex(ValueError, "source identity leakage"):
            self.module.validate_high_fidelity_extension(value)

    def test_rejects_configured_source_identity_tokens_inside_generic_text(self):
        value = valid_extension_contract()
        value["extensions"]["high_fidelity_hybrid_v1"]["semantic_cuts"][0][
            "performance"
        ]["objective"] = "quietly promote SourceBrand"
        with self.assertRaisesRegex(ValueError, "forbidden source identity token"):
            self.module.validate_high_fidelity_extension(
                value, forbidden_source_terms=["SourceBrand"]
            )

    def test_route_excluded_interval_carries_only_technical_metadata(self):
        value = base_contract()
        value["extensions"] = {
            "high_fidelity_hybrid_v1": {
                "schema_version": 1,
                "analysis_pass_count": 1,
                "semantic_cuts": [],
                "route_excluded_intervals": [
                    {
                        "cut": 1,
                        "region_type": "opaque_ui_demo",
                        "start_us": 0,
                        "end_us": 1_000_000,
                        "transition_shell": {"kind": "dissolve", "duration_ms": 120},
                        "technical_stream": {"width": 720, "height": 1280, "fps_num": 30, "fps_den": 1},
                    }
                ],
            }
        }
        self.module.validate_high_fidelity_extension(value)
        value["extensions"]["high_fidelity_hybrid_v1"]["route_excluded_intervals"][0][
            "semantic_claim"
        ] = "must never be inspected"
        with self.assertRaisesRegex(ValueError, "technical metadata only"):
            self.module.validate_high_fidelity_extension(value)

    def test_references_describe_additive_single_pass_extension(self):
        dynamics = (ROOT / "references" / "dynamics-contract.md").read_text(encoding="utf-8")
        quality = (ROOT / "references" / "analysis-quality-contract.md").read_text(encoding="utf-8")
        combined = dynamics + "\n" + quality
        for required in (
            "extensions.high_fidelity_hybrid_v1",
            "single semantic pass",
            "normalized",
            "framing migration",
            "expression",
            "gaze",
            "posture",
            "gesture",
            "completed end state",
            "route-excluded",
            "technical metadata only",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

    def test_skill_runs_optional_validator_without_a_second_analysis_pass(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("validate_high_fidelity_extension.py", skill)
        self.assertIn("same single semantic pass", skill)
        self.assertIn("Legacy runs skip this additive validator", skill)


if __name__ == "__main__":
    unittest.main()
