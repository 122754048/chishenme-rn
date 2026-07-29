import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from seedance_prescript import (  # noqa: E402
    build_prescript_artifact,
    rebind_candidate_regions,
    validate_prescript_artifact,
)


def _candidate():
    return {
        "candidate_region_id": "CR-01",
        "cut_ids": ["C01"],
        "required_factor_ids": [
            "HFH.C01.SCENE.TOPOLOGY",
            "HFH.C01.CAMERA.PATH",
            "HFH.C01.LIGHTING.KEY",
            "HFH.C01.PERFORMANCE.STATE",
            "HFH.C01.ACTION.ENDPOINT",
            "HFH.C01.PRODUCT.TRUTH",
            "HFH.C01.COMMERCIAL.PROOF",
            "HFH.C01.CONTINUITY.OUT",
            "HFH.C01.AUDIO.SYNC",
        ],
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
        "action_state_requirements": [
            {"phase": "completed", "state": "package open", "required": True}
        ],
        "audio_strategy": {
            "music_policy": "none",
            "ambience": "low room tone",
            "foley_event_ids": [],
            "silence_window_ids": [],
        },
        "voiceover_timing_plan": [],
        "prompt_carrier_plan": [],
        "postproduction_carrier_plan": [],
        "hard_blockers": [],
        "warnings": [],
    }


def _factor_coverage(candidate: dict | None = None):
    candidate = candidate or _candidate()
    region_id = candidate["candidate_region_id"]
    return [
        {
            "factor_id": factor_id,
            "candidate_region_id": region_id,
            "source_pointer": f"/source_fidelity_contract/{factor_id}",
            "contract_pointer": f"/contracts/source_fidelity_contract.json#/{factor_id}",
            "carrier": "prompt",
            "criticality": "H",
        }
        for factor_id in candidate["required_factor_ids"]
    ]


def _projected_candidate(
    *,
    candidate_region_id: str = "CR-01",
    source_region_id: str = "R01",
    cut_id: str = "C01",
    start_ms: int = 0,
    end_ms: int = 8_000,
) -> dict:
    candidate = _candidate()
    duration_ms = end_ms - start_ms
    factor_ids = [
        factor_id.replace("C01", cut_id)
        for factor_id in candidate["required_factor_ids"]
    ]
    shot = {
        "shot_id": "SHOT-01",
        "cut_id": cut_id,
        "start_ms": 0,
        "end_ms": duration_ms,
        "duration_ms": duration_ms,
        "output_global_start_ms": start_ms,
        "output_global_end_ms": end_ms,
        "primary_action": "open package",
        "endpoint": "package open",
    }
    candidate.update(
        {
            "candidate_region_id": candidate_region_id,
            "source_region_id": source_region_id,
            "cut_ids": [cut_id],
            "required_factor_ids": factor_ids,
            "forbidden_split_cut_ids": [cut_id],
            "duration_ms": duration_ms,
            "output_global_start_ms": start_ms,
            "output_global_end_ms": end_ms,
            "retime_scale": 1.0,
            "shot_budget": [shot],
            "action_state_requirements": [
                {
                    "cut_id": cut_id,
                    "phase": "completed",
                    "state": "package open",
                    "start_ms": duration_ms - 1,
                    "end_ms": duration_ms,
                    "output_global_start_ms": end_ms - 1,
                    "output_global_end_ms": end_ms,
                    "required": True,
                }
            ],
            "canonical_segment": {
                "segment_id": None,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": duration_ms,
                "cut_ids": [cut_id],
                "shots": [copy.deepcopy(shot)],
            },
        }
    )
    return candidate


class PrescriptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.skill = Path(self.temp.name) / "seedance-20.md"
        self.skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_build_and_validate_pinned_snapshot(self):
        artifact = build_prescript_artifact(
            route="route_2",
            candidate_regions=[_candidate()],
            line_contracts=[],
            factor_coverage=_factor_coverage(),
            skill_file=self.skill,
            input_digests={"source": "a" * 64},
        )
        validate_prescript_artifact(artifact, self.skill, {"source": "a" * 64})
        self.assertEqual(artifact["profile"], "seedance20_prescript_v1")
        self.assertEqual(artifact["compiler"]["version"], "6.6.0")

    def test_hash_mismatch_and_route_authority_fail_closed(self):
        artifact = build_prescript_artifact(route="route_1", candidate_regions=[_candidate()], line_contracts=[], factor_coverage=_factor_coverage(), skill_file=self.skill, input_digests={})
        artifact["compiler"]["skill_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_prescript_artifact(artifact, self.skill, {})
        artifact = build_prescript_artifact(route="route_1", candidate_regions=[_candidate()], line_contracts=[], factor_coverage=_factor_coverage(), skill_file=self.skill, input_digests={})
        artifact["route_1_mutations"] = [{"field": "text", "value": "rewrite"}]
        with self.assertRaises(ValueError):
            validate_prescript_artifact(artifact, self.skill, {})

    def test_max_two_regions_four_reference_roles_and_legal_rebind(self):
        candidates = [
            _candidate(),
            dict(
                _candidate(),
                candidate_region_id="CR-02",
                cut_ids=["C02"],
                forbidden_split_cut_ids=["C02"],
                required_factor_ids=[
                    factor_id.replace("C01", "C02")
                    for factor_id in _candidate()["required_factor_ids"]
                ],
            ),
        ]
        artifact = build_prescript_artifact(route="route_2", candidate_regions=candidates, line_contracts=[], factor_coverage=_factor_coverage(candidates[0]) + _factor_coverage(candidates[1]), skill_file=self.skill, input_digests={})
        rebind_candidate_regions(artifact, [{"segment_id": "S01", "cut_ids": ["C01"], "start_ms": 0, "end_ms": 8000}, {"segment_id": "S02", "cut_ids": ["C02"], "start_ms": 8000, "end_ms": 16000}])
        self.assertEqual(artifact["candidate_regions"][0]["segment_id"], "S01")
        bad = copy.deepcopy(artifact)
        bad["candidate_regions"].append(dict(_candidate(), candidate_region_id="CR-03", cut_ids=["C03"]))
        with self.assertRaises(ValueError):
            validate_prescript_artifact(bad, self.skill, {})

    def test_proposed_split_boundary_is_frozen_and_rebinds_exact_global_bounds(self):
        first = _projected_candidate()
        second = _projected_candidate(
            candidate_region_id="CR-02",
            cut_id="C02",
            start_ms=8_000,
            end_ms=16_000,
        )
        artifact = build_prescript_artifact(
            route="route_2",
            candidate_regions=[first, second],
            line_contracts=[],
            factor_coverage=_factor_coverage(first) + _factor_coverage(second),
            skill_file=self.skill,
            input_digests={},
            proposed_split_boundary_ms=8_000,
        )

        self.assertEqual(artifact["proposed_split_boundary_ms"], 8_000)
        validate_prescript_artifact(artifact, self.skill, {})
        rebind_candidate_regions(
            artifact,
            [
                {
                    "segment_id": "S01",
                    "cut_ids": ["C01"],
                    "start_ms": 0,
                    "end_ms": 8_000,
                },
                {
                    "segment_id": "S02",
                    "cut_ids": ["C02"],
                    "start_ms": 8_000,
                    "end_ms": 16_000,
                },
            ],
        )

        shifted = copy.deepcopy(artifact)
        with self.assertRaisesRegex(ValueError, "global bounds"):
            rebind_candidate_regions(
                shifted,
                [
                    {
                        "segment_id": "S01",
                        "cut_ids": ["C01"],
                        "start_ms": 0,
                        "end_ms": 8_000,
                    },
                    {
                        "segment_id": "S02",
                        "cut_ids": ["C02"],
                        "start_ms": 9_000,
                        "end_ms": 17_000,
                    },
                ],
            )

    def test_same_source_two_candidate_prescript_requires_proposed_boundary(self):
        first = _projected_candidate()
        second = _projected_candidate(
            candidate_region_id="CR-02",
            cut_id="C02",
            start_ms=8_000,
            end_ms=16_000,
        )

        with self.assertRaisesRegex(ValueError, "proposed_split_boundary_ms is required"):
            build_prescript_artifact(
                route="route_2",
                candidate_regions=[first, second],
                line_contracts=[],
                factor_coverage=_factor_coverage(first) + _factor_coverage(second),
                skill_file=self.skill,
                input_digests={},
                projection_sha256="f" * 64,
            )

    def test_projection_bound_prescript_rejects_shot_action_and_canonical_timing_drift(self):
        mutations = []

        shot_drift = _projected_candidate()
        shot_drift["shot_budget"][0]["end_ms"] = 9_000
        shot_drift["shot_budget"][0]["output_global_end_ms"] = 9_000
        mutations.append((shot_drift, r"shot_budget\[1\].*bounds"))

        action_drift = _projected_candidate()
        action_drift["action_state_requirements"][0]["end_ms"] = 8_001
        action_drift["action_state_requirements"][0]["output_global_end_ms"] = 8_001
        mutations.append((action_drift, r"action_state_requirements\[1\].*bounds"))

        canonical_drift = _projected_candidate()
        canonical_drift["canonical_segment"]["shots"] = []
        mutations.append((canonical_drift, r"canonical_segment.*shots"))

        for candidate, error_pattern in mutations:
            with self.subTest(error_pattern=error_pattern), self.assertRaisesRegex(
                ValueError,
                error_pattern,
            ):
                build_prescript_artifact(
                    route="route_2",
                    candidate_regions=[candidate],
                    line_contracts=[],
                    factor_coverage=_factor_coverage(candidate),
                    skill_file=self.skill,
                    input_digests={},
                    projection_sha256="f" * 64,
                )

    def test_projection_bound_prescript_rejects_line_and_audio_windows_outside_candidate(self):
        from test_line_contract import _line

        candidate = _projected_candidate()
        candidate["voiceover_timing_plan"] = [
            {"line_id": "VO-001", "carrier": "prompt"}
        ]
        base_line = _line()
        base_line["candidate_region_id"] = candidate["candidate_region_id"]
        base_line["cut_id"] = "C01"
        base_line["time"]["cut_ids"] = ["C01"]

        mutations = []
        line_drift = copy.deepcopy(base_line)
        line_drift["time"].update(
            {"start_ms": 7_000, "end_ms": 8_001, "duration_ms": 1_001}
        )
        mutations.append((line_drift, "line VO-001"))
        for collection in ("proof_events", "foley_events", "silence_windows"):
            event_drift = copy.deepcopy(base_line)
            event_drift[collection][0].update({"start_ms": 7_999, "end_ms": 8_001})
            mutations.append((event_drift, collection))

        for line, label in mutations:
            with self.subTest(label=label), self.assertRaisesRegex(
                ValueError,
                rf"{label}.*candidate",
            ):
                build_prescript_artifact(
                    route="route_2",
                    candidate_regions=[candidate],
                    line_contracts=[line],
                    factor_coverage=_factor_coverage(candidate),
                    skill_file=self.skill,
                    input_digests={},
                    projection_sha256="f" * 64,
                )

    def test_candidate_requires_action_endpoint_background_and_audio_execution_fields(self):
        mutations = []
        missing_background = _candidate()
        del missing_background["background_strategy"]
        mutations.append((missing_background, "background_strategy"))
        missing_shots = _candidate()
        missing_shots["shot_budget"] = []
        mutations.append((missing_shots, "shot_budget"))
        missing_endpoint = _candidate()
        missing_endpoint["shot_budget"][0]["endpoint"] = ""
        mutations.append((missing_endpoint, "endpoint"))
        missing_completed_state = _candidate()
        missing_completed_state["action_state_requirements"][0]["phase"] = "contact"
        mutations.append((missing_completed_state, "completed"))
        missing_audio = _candidate()
        missing_audio["audio_strategy"] = {}
        mutations.append((missing_audio, "audio_strategy"))

        for candidate, expected in mutations:
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                build_prescript_artifact(
                    route="route_2",
                    candidate_regions=[candidate],
                    line_contracts=[],
                    factor_coverage=_factor_coverage(candidate),
                    skill_file=self.skill,
                    input_digests={},
                )

    def test_every_line_requires_a_candidate_region_and_explicit_carrier(self):
        from test_line_contract import _line

        candidate = _candidate()
        line = _line()
        candidate["voiceover_timing_plan"] = [
            {"line_id": line["line_id"], "carrier": "prompt"}
        ]
        build_prescript_artifact(
            route="route_2",
            candidate_regions=[candidate],
            line_contracts=[line],
            factor_coverage=_factor_coverage(candidate),
            skill_file=self.skill,
            input_digests={},
        )

        candidate["voiceover_timing_plan"][0].pop("carrier")
        with self.assertRaisesRegex(ValueError, "carrier"):
            build_prescript_artifact(
                route="route_2",
                candidate_regions=[candidate],
                line_contracts=[line],
                factor_coverage=_factor_coverage(candidate),
                skill_file=self.skill,
                input_digests={},
            )

    def test_generated_candidates_require_exact_non_empty_factor_coverage(self):
        candidate = _candidate()
        with self.assertRaisesRegex(ValueError, "factor_coverage"):
            build_prescript_artifact(
                route="route_2",
                candidate_regions=[candidate],
                line_contracts=[],
                factor_coverage=[],
                skill_file=self.skill,
                input_digests={},
                require_factor_coverage=True,
            )

    def test_projection_digest_is_frozen_between_invocation_a_and_b(self):
        projection_sha = "f" * 64
        candidate = _candidate()
        artifact = build_prescript_artifact(
            route="route_2",
            candidate_regions=[candidate],
            line_contracts=[],
            factor_coverage=_factor_coverage(),
            skill_file=self.skill,
            input_digests={"source": "a" * 64},
            projection_sha256=projection_sha,
        )
        self.assertEqual(artifact["projection_sha256"], projection_sha)
        validate_prescript_artifact(
            artifact,
            self.skill,
            {"source": "a" * 64},
            projection_sha256=projection_sha,
        )
        with self.assertRaisesRegex(ValueError, "projection digest"):
            validate_prescript_artifact(
                artifact,
                self.skill,
                {"source": "a" * 64},
                projection_sha256="0" * 64,
            )

        incomplete = _factor_coverage(candidate)[:-1]
        with self.assertRaisesRegex(ValueError, "factor coverage.*differs"):
            build_prescript_artifact(
                route="route_2",
                candidate_regions=[candidate],
                line_contracts=[],
                factor_coverage=incomplete,
                skill_file=self.skill,
                input_digests={},
                require_factor_coverage=True,
            )


if __name__ == "__main__":
    unittest.main()
