from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
import importlib.util
from unittest.mock import patch

from server.errors import ReplicationError
from server.seedance_invocations import (
    SeedanceInvocationAdapter,
    _build_prompt_approval_binding,
    _sha_json,
    _validate_projection_segment_parity,
)


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
    return [{"factor_id": "HFH.C01.ACTION.ENDPOINT", "candidate_region_id": "CR-01", "source_pointer": "/source/C01/action/endpoint", "contract_pointer": "/contracts/source_fidelity_contract.json#/cuts/C01/action/endpoint", "carrier": "prompt", "criticality": "H"}]


def _line(*, offset_ms: int = 0) -> dict:
    """A global-time line with proof, Foley, and protected silence windows."""

    start = 200 + offset_ms
    end = 1850 + offset_ms
    return {
        "line_id": "VO-001",
        "cut_id": "C01",
        "candidate_region_id": "CR-01",
        "segment_id": None,
        "speaker": {
            "id": "CHARACTER_A",
            "role": "creator",
            "visibility": "on_camera",
            "voice_policy": "generic rights-cleared target voice; no source voice imitation",
        },
        "language": {"bcp47": "en-US", "script": "Latn"},
        "time": {
            "time_base": "output_global_ms",
            "start_ms": start,
            "end_ms": end,
            "duration_ms": end - start,
            "duration_is_derived": True,
            "segment_start_ms": None,
            "segment_end_ms": None,
            "cut_ids": ["C01"],
            "cross_cut_reason": None,
            "planned_safe_margin_ms": 250,
        },
        "text": {
            "exact": "All right, let's open it.",
            "normalized": "all right let's open it",
            "pronunciation_notes": [],
        },
        "delivery": {
            "tone": "close-mic conversational",
            "pace": "brisk",
            "emphasis": ["open"],
            "volume": "natural",
            "breath": "single breath group",
            "mic_distance": "close",
            "accent_or_locale": "natural target locale",
        },
        "lip_sync": {
            "priority": "high",
            "face_visibility": "clear frontal mouth",
            "occlusion": "none",
            "head_motion_limit": "small",
            "articulation": "clear",
            "allowed_tolerance_ms": 200,
            "speaker_face_ref": "CHARACTER_A",
        },
        "proof_events": [
            {
                "id": "PROOF-001",
                "kind": "package_contact",
                "modality": ["visual", "audio"],
                "start_ms": 1900 + offset_ms,
                "end_ms": 2050 + offset_ms,
                "claim_ids": ["CLM-001"],
                "required": True,
                "hard_fail": True,
            }
        ],
        "foley_events": [
            {
                "id": "FOLEY-001",
                "kind": "package_friction",
                "start_ms": 2100 + offset_ms,
                "end_ms": 2350 + offset_ms,
                "relation": "after_line",
                "onset_tolerance_ms": 200,
                "required": True,
                "loudness_policy": "audible_but_does_not_mask_dialogue",
            }
        ],
        "silence_windows": [
            {
                "id": "SIL-001",
                "start_ms": 1850 + offset_ms,
                "end_ms": 2100 + offset_ms,
                "kind": "post_line_pause",
                "min_quiet_dbfs": -30.0,
                "required": True,
            }
        ],
        "music_policy": {"mode": "none", "windows": []},
        "claim_ids": ["CLM-001"],
        "qc_contract": {
            "asr_profile": "en-US-canonical-v1",
            "speaker_check": "role",
            "language_check": "BCP-47 detector en-US",
            "line_tolerance_ms": 350,
            "proof_sync_tolerance_ms": 200,
            "foley_sync_tolerance_ms": 200,
            "hard_fail_flags": ["word_change"],
        },
        "criticality": "H",
    }


def _skill_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for name in ("seedance-20", "seedance-prompt", "seedance-antislop"):
        path = root / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nname: {name}\nmetadata:\n  version: 6.6.0\n---\n",
            encoding="utf-8",
        )
        files[name] = path
    return files


def _compiler_checks() -> dict[str, bool]:
    return {
        "professional_gate": True,
        "capability_check": True,
        "allocation_check": True,
        "reference_role_check": True,
        "directing_coherence_check": True,
        "anti_slop_check": True,
        "route_exclusion_check": True,
        "line_parity_check": True,
    }


def _segment_request() -> dict:
    return {
        "segment_id": "S01",
        "duration_ms": 8000,
        "opening_state": "The creator holds the closed package beside the microphone.",
        "shots": [
            {
                "shot_id": "SHOT-01",
                "start_ms": 0,
                "end_ms": 8000,
                "shot_scale": "stable medium shot",
                "camera": "locked camera",
                "performance": "slight forward lean, gaze on package then camera, focused expression, hands move slowly beside the microphone",
                "action": "open the package",
                "endpoint": "package fully open",
                "scene": "same tabletop topology",
                "lighting": "same motivated key light",
                "product_or_ui_truth": "target package geometry and opening method remain exact",
                "commercial_proof": "completed opening visibly proves the approved use claim",
                "transition": "source-matched clean cut",
                "continuity": "open package centered with hands settled",
                "audio": "room tone and package friction",
                "factor_ids": ["HFH.C01.ACTION.ENDPOINT"],
            }
        ],
        "reference_roles": [{"slot": 1, "tag": "@Image1", "role": "approved storyboard"}],
        "locks": ["preserve target product geometry"],
        "negative_constraints": [],
    }


class SeedanceInvocationAdapterTest(unittest.TestCase):
    def test_default_activation_mode_uses_production_bundle_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_files = _skill_files(root)
            fake_profile_module = type(
                "ProfileModule",
                (),
                {"validate_profile_snapshot": staticmethod(lambda *_args, **_kwargs: None)},
            )()
            with patch(
                "server.seedance_invocations._load_script_module",
                return_value=fake_profile_module,
            ):
                with self.assertRaisesRegex(ReplicationError, "immutable bundle resolver"):
                    SeedanceInvocationAdapter(
                        skill_file=skill_files["seedance-20"],
                        prompt_skill_files=skill_files,
                        profile_snapshot={
                            "profile": "high_fidelity_hybrid_v1",
                            "activation_mode": "default",
                        },
                    )

    def _active_adapter_and_prescript(self, root: Path, *, line_offset_ms: int = 0):
        skill_files = _skill_files(root)
        adapter = SeedanceInvocationAdapter(
            skill_file=skill_files["seedance-20"],
            prompt_skill_files=skill_files,
        )
        line = _line(offset_ms=line_offset_ms)
        candidate = _candidate()
        candidate["voiceover_timing_plan"] = [{"line_id": "VO-001", "carrier": "prompt"}]
        candidate["audio_strategy"]["foley_event_ids"] = ["FOLEY-001"]
        candidate["audio_strategy"]["silence_window_ids"] = ["SIL-001"]
        prescript = adapter.invoke_a(
            route="route_2",
            candidate_regions=[candidate],
            line_contracts=[line],
            factor_coverage=_factor_coverage(),
            input_digests={"source": "a" * 64},
        )
        context = type(
            "Context",
            (),
            {"profile_snapshot": {"profile": "high_fidelity_hybrid_v1"}},
        )()
        return adapter, prescript, context

    def test_active_invocation_b_requires_final_segment_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter, prescript, context = self._active_adapter_and_prescript(root)
            with self.assertRaises(ReplicationError) as error:
                adapter.invoke_b(
                    context=context,
                    prescript_artifact=prescript,
                    input_digests={"source": "a" * 64},
                    prompt_request={
                        "segment": _segment_request(),
                        "line_contracts": [_line()],
                        "factors": {},
                        "compiler_checks": _compiler_checks(),
                    },
                    final_cut_ids=["C01"],
                )
        self.assertEqual(error.exception.code, "PROMPT_INTEGRITY_FAILED")
        self.assertIn("segment plan", str(error.exception).lower())

    def test_active_invocation_b_rejects_global_lines_when_plan_is_not_rebound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter, prescript, context = self._active_adapter_and_prescript(
                root,
                line_offset_ms=5000,
            )
            global_line = _line(offset_ms=5000)
            with self.assertRaises(ReplicationError) as error:
                adapter.invoke_b(
                    context=context,
                    prescript_artifact=prescript,
                    input_digests={"source": "a" * 64},
                    segment_plan={
                        "segments": [
                            {
                                "segment_id": "S01",
                                "start_ms": 5000,
                                "end_ms": 13000,
                                "duration_ms": 8000,
                                "cut_ids": ["C01"],
                            }
                        ]
                    },
                    prompt_request={
                        "segment": _segment_request(),
                        "line_contracts": [global_line],
                        "factors": {},
                        "compiler_checks": _compiler_checks(),
                    },
                    final_cut_ids=["C01"],
                )
        self.assertEqual(error.exception.code, "PROMPT_INTEGRITY_FAILED")
        self.assertIn("segment-local", str(error.exception.details.get("reason", "")).lower())

    def test_active_invocation_b_rebinds_line_proof_foley_and_silence_to_segment_local_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter, prescript, context = self._active_adapter_and_prescript(
                root,
                line_offset_ms=5000,
            )
            result = adapter.invoke_b(
                context=context,
                prescript_artifact=prescript,
                input_digests={"source": "a" * 64},
                segment_plan={
                    "segments": [
                        {
                            "segment_id": "S01",
                            "start_ms": 5000,
                            "end_ms": 13000,
                            "duration_ms": 8000,
                            "cut_ids": ["C01"],
                        }
                    ]
                },
                prompt_request={
                    "segment": _segment_request(),
                    "line_contracts": None,
                    "factors": {},
                    "compiler_checks": _compiler_checks(),
                },
                final_cut_ids=["C01"],
            )
        self.assertEqual(result["status"], "ready")
        prompt = result["compiled_prompt"]
        self.assertIn("Dialogue 0.20-1.85s", prompt)
        self.assertIn("PROOF-001 1.90-2.05s", prompt)
        self.assertIn("FOLEY-001 2.10-2.35s", prompt)
        self.assertIn("SIL-001 1.85-2.10s", prompt)
        self.assertNotIn("Dialogue 5.20-6.85s", prompt)

    def test_invocation_a_and_b_share_pinned_skill_and_preserve_line_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            adapter = SeedanceInvocationAdapter(skill_file=skill)
            a = adapter.invoke_a(
                route="route_2",
                candidate_regions=[_candidate()],
                line_contracts=[],
                factor_coverage=_factor_coverage(),
                input_digests={"source": "a" * 64},
            )
            b = adapter.invoke_b(
                prescript_artifact=a,
                input_digests={"source": "a" * 64},
                compiled_prompt='Cut 1, 00.00-08.00s. No dialogue. Open the package and finish with the package open.',
                final_cut_ids=["C01"],
            )
        self.assertEqual(b["status"], "ready")
        self.assertEqual(b["skill_sha256"], a["compiler"]["skill_sha256"])
        self.assertEqual(b["prescript_sha256"], a["compiler"]["output_sha256"])

    def test_invocation_a_and_b_require_the_same_analysis_projection_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            adapter = SeedanceInvocationAdapter(skill_file=skill)
            projection_sha = "f" * 64
            prescript = adapter.invoke_a(
                route="route_2",
                candidate_regions=[_candidate()],
                line_contracts=[],
                factor_coverage=_factor_coverage(),
                input_digests={"source": "a" * 64},
                projection_sha256=projection_sha,
            )
            accepted = adapter.invoke_b(
                prescript_artifact=prescript,
                input_digests={"source": "a" * 64},
                projection_sha256=projection_sha,
                compiled_prompt="Cut 1, 00.00-08.00s.",
                final_cut_ids=["C01"],
            )
            self.assertEqual(accepted["projection_sha256"], projection_sha)
            with self.assertRaises(ReplicationError) as mismatch:
                adapter.invoke_b(
                    prescript_artifact=prescript,
                    input_digests={"source": "a" * 64},
                    projection_sha256="0" * 64,
                    compiled_prompt="Cut 1, 00.00-08.00s.",
                    final_cut_ids=["C01"],
                )
        self.assertEqual(mismatch.exception.code, "PROMPT_INTEGRITY_FAILED")
        self.assertIn("projection digest", str(mismatch.exception.details.get("reason", "")))

    def test_projection_bound_invocation_b_cannot_rewrite_rich_shots_or_factors(self):
        candidate = _candidate()
        rich_segment = _segment_request()
        candidate["required_factor_ids"] = ["HFH.C01.ACTION.ENDPOINT"]
        candidate["canonical_segment"] = {
            "segment_id": None,
            "duration_ms": 8000,
            "cut_ids": ["C01"],
            "shots": deepcopy(rich_segment["shots"]),
        }
        artifact = {
            "projection_sha256": "f" * 64,
            "candidate_regions": [candidate],
        }
        current = {"segment_id": "S01", "duration_ms": 8000, "cut_ids": ["C01"]}
        _validate_projection_segment_parity(artifact, current, rich_segment)
        changed = deepcopy(rich_segment)
        changed["shots"][0]["camera"] = "unapproved handheld orbit"
        with self.assertRaisesRegex(ValueError, "camera"):
            _validate_projection_segment_parity(artifact, current, changed)

    def test_projection_parity_freezes_all_shot_timing_fields(self):
        candidate = _candidate()
        rich_segment = _segment_request()
        rich_segment["shots"][0].update(
            {
                "cut_id": "C01",
                "duration_ms": 8_000,
                "output_global_start_ms": 0,
                "output_global_end_ms": 8_000,
            }
        )
        candidate["required_factor_ids"] = ["HFH.C01.ACTION.ENDPOINT"]
        candidate["canonical_segment"] = {
            "segment_id": None,
            "duration_ms": 8_000,
            "cut_ids": ["C01"],
            "shots": deepcopy(rich_segment["shots"]),
        }
        artifact = {
            "projection_sha256": "f" * 64,
            "candidate_regions": [candidate],
        }
        current = {"segment_id": "S01", "duration_ms": 8_000, "cut_ids": ["C01"]}

        for field, value in (
            ("cut_id", "C99"),
            ("duration_ms", 7_999),
            ("output_global_start_ms", 1),
            ("output_global_end_ms", 7_999),
        ):
            changed = deepcopy(rich_segment)
            changed["shots"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                _validate_projection_segment_parity(artifact, current, changed)

    def test_projection_bound_provisional_candidates_require_exact_global_segment_bounds(self):
        first = _candidate()
        first_segment = _segment_request()
        first["canonical_segment"] = {
            "segment_id": None,
            "start_ms": 0,
            "end_ms": 8_000,
            "duration_ms": 8_000,
            "cut_ids": ["C01"],
            "shots": deepcopy(first_segment["shots"]),
        }

        second = deepcopy(first)
        second["candidate_region_id"] = "CR-02"
        second["cut_ids"] = ["C02"]
        second["forbidden_split_cut_ids"] = ["C02"]
        second["required_factor_ids"] = ["HFH.C02.ACTION.ENDPOINT"]
        second_segment = deepcopy(first_segment)
        second_segment["segment_id"] = "S02"
        second_segment["duration_ms"] = 8_000
        second_segment["shots"][0]["factor_ids"] = ["HFH.C02.ACTION.ENDPOINT"]
        second["canonical_segment"] = {
            "segment_id": None,
            "start_ms": 8_000,
            "end_ms": 16_000,
            "duration_ms": 8_000,
            "cut_ids": ["C02"],
            "shots": deepcopy(second_segment["shots"]),
        }

        artifact = {
            "projection_sha256": "f" * 64,
            "candidate_regions": [first, second],
        }
        _validate_projection_segment_parity(
            artifact,
            {
                "segment_id": "S01",
                "start_ms": 0,
                "end_ms": 8_000,
                "duration_ms": 8_000,
                "cut_ids": ["C01"],
            },
            first_segment,
        )
        _validate_projection_segment_parity(
            artifact,
            {
                "segment_id": "S02",
                "start_ms": 8_000,
                "end_ms": 16_000,
                "duration_ms": 8_000,
                "cut_ids": ["C02"],
            },
            second_segment,
        )

        shifted = {
            "segment_id": "S02",
            "start_ms": 9_000,
            "end_ms": 17_000,
            "duration_ms": 8_000,
            "cut_ids": ["C02"],
        }
        with self.assertRaisesRegex(ValueError, "global bounds"):
            _validate_projection_segment_parity(artifact, shifted, second_segment)

    def test_invocation_b_rejects_shifted_unselected_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_files = _skill_files(root)
            adapter = SeedanceInvocationAdapter(
                skill_file=skill_files["seedance-20"],
                prompt_skill_files=skill_files,
            )
            context = type(
                "Context",
                (),
                {"profile_snapshot": {"profile": "high_fidelity_hybrid_v1"}},
            )()
            projection_sha256 = "f" * 64

            first_segment = _segment_request()
            first_segment["negative_constraints"] = ["No dialogue"]
            first_segment["no_speech_contracts"] = [
                {
                    "cut_id": "C01",
                    "speech_mode": "none",
                    "allowed_audio": ["room tone", "package friction"],
                    "forbidden_audio": ["dialogue", "voiceover"],
                }
            ]
            first_segment["shots"][0].update(
                {
                    "cut_id": "C01",
                    "duration_ms": 8_000,
                    "output_global_start_ms": 0,
                    "output_global_end_ms": 8_000,
                    "primary_action": first_segment["shots"][0]["action"],
                }
            )
            first = _candidate()
            first.update(
                {
                    "source_region_id": "R01",
                    "output_global_start_ms": 0,
                    "output_global_end_ms": 8_000,
                    "retime_scale": 1.0,
                    "shot_budget": deepcopy(first_segment["shots"]),
                    "action_state_requirements": [
                        {
                            "cut_id": "C01",
                            "phase": "completed",
                            "state": "package fully open",
                            "start_ms": 7_999,
                            "end_ms": 8_000,
                            "output_global_start_ms": 7_999,
                            "output_global_end_ms": 8_000,
                            "required": True,
                        }
                    ],
                    "canonical_segment": {
                        "segment_id": None,
                        "start_ms": 0,
                        "end_ms": 8_000,
                        "duration_ms": 8_000,
                        "cut_ids": ["C01"],
                        "shots": deepcopy(first_segment["shots"]),
                    },
                }
            )

            second_segment = deepcopy(first_segment)
            second_segment["segment_id"] = "S02"
            second_segment["shots"][0].update(
                {
                    "cut_id": "C02",
                    "output_global_start_ms": 8_000,
                    "output_global_end_ms": 16_000,
                    "factor_ids": ["HFH.C02.ACTION.ENDPOINT"],
                }
            )
            second = deepcopy(first)
            second.update(
                {
                    "candidate_region_id": "CR-02",
                    "cut_ids": ["C02"],
                    "required_factor_ids": ["HFH.C02.ACTION.ENDPOINT"],
                    "forbidden_split_cut_ids": ["C02"],
                    "output_global_start_ms": 8_000,
                    "output_global_end_ms": 16_000,
                    "shot_budget": deepcopy(second_segment["shots"]),
                    "action_state_requirements": [
                        {
                            "cut_id": "C02",
                            "phase": "completed",
                            "state": "package fully open",
                            "start_ms": 7_999,
                            "end_ms": 8_000,
                            "output_global_start_ms": 15_999,
                            "output_global_end_ms": 16_000,
                            "required": True,
                        }
                    ],
                    "canonical_segment": {
                        "segment_id": None,
                        "start_ms": 8_000,
                        "end_ms": 16_000,
                        "duration_ms": 8_000,
                        "cut_ids": ["C02"],
                        "shots": deepcopy(second_segment["shots"]),
                    },
                }
            )
            factor_coverage = _factor_coverage() + [
                {
                    **_factor_coverage()[0],
                    "factor_id": "HFH.C02.ACTION.ENDPOINT",
                    "candidate_region_id": "CR-02",
                    "source_pointer": "/source/C02/action/endpoint",
                    "contract_pointer": "/contracts/source_fidelity_contract.json#/cuts/C02/action/endpoint",
                }
            ]
            prescript = adapter.invoke_a(
                context=context,
                route="route_2",
                candidate_regions=[first, second],
                line_contracts=[],
                factor_coverage=factor_coverage,
                input_digests={"source": "a" * 64},
                projection_sha256=projection_sha256,
                proposed_split_boundary_ms=8_000,
            )

            with self.assertRaises(ReplicationError) as error:
                adapter.invoke_b(
                    context=context,
                    prescript_artifact=prescript,
                    input_digests={"source": "a" * 64},
                    projection_sha256=projection_sha256,
                    segment_id="S01",
                    segment_plan={
                        "segments": [
                            {
                                "segment_id": "S01",
                                "start_ms": 0,
                                "end_ms": 8_000,
                                "duration_ms": 8_000,
                                "cut_ids": ["C01"],
                            },
                            {
                                "segment_id": "S02",
                                "start_ms": 9_000,
                                "end_ms": 17_000,
                                "duration_ms": 8_000,
                                "cut_ids": ["C02"],
                            },
                        ]
                    },
                    prompt_request={
                        "segment": first_segment,
                        "line_contracts": [],
                        "factors": {},
                        "compiler_checks": _compiler_checks(),
                    },
                    final_cut_ids=["C01", "C02"],
                )

        self.assertEqual(error.exception.code, "PROMPT_INTEGRITY_FAILED")
        self.assertIn(
            "approved segment plan",
            str(error.exception.details.get("reason", "")),
        )

    def test_invocation_b_rejects_generated_ui_and_tail_route_markers_in_raw_prompt(self):
        for leaked_marker in (
            "uiDemo",
            "opaque_ui_demo",
            "generated_ui_demo",
            "opaqueAppTailCard",
            "tailCard",
            "renderedMedia",
            "mediaSha256",
            "qcReport",
            "excluded_app_end_card",
            "omit_source_end_card",
            "excludedRegion",
        ):
            with self.subTest(leaked_marker=leaked_marker), tempfile.TemporaryDirectory() as tmp:
                skill = Path(tmp) / "SKILL.md"
                skill.write_text(
                    "---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n",
                    encoding="utf-8",
                )
                adapter = SeedanceInvocationAdapter(skill_file=skill)
                prescript = adapter.invoke_a(
                    route="route_2",
                    candidate_regions=[_candidate()],
                    line_contracts=[],
                    factor_coverage=_factor_coverage(),
                    input_digests={"source": "a" * 64},
                )
                with self.assertRaises(ReplicationError) as error:
                    adapter.invoke_b(
                        prescript_artifact=prescript,
                        input_digests={"source": "a" * 64},
                        compiled_prompt=(
                            "Cut 1, 00.00-08.00s. No dialogue. "
                            f"Reproduce {leaked_marker} inside the generated shot."
                        ),
                        final_cut_ids=["C01"],
                )
                self.assertEqual(error.exception.code, "PROMPT_INTEGRITY_FAILED")
                self.assertTrue(error.exception.details.get("leaked_fields"))

    def test_invocation_b_route_matching_preserves_token_boundaries(self):
        for legitimate_text in (
            "show a detail video of the package texture",
            "keep the resource interval stable for the camera move",
        ):
            with self.subTest(legitimate_text=legitimate_text), tempfile.TemporaryDirectory() as tmp:
                skill = Path(tmp) / "SKILL.md"
                skill.write_text(
                    "---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n",
                    encoding="utf-8",
                )
                adapter = SeedanceInvocationAdapter(skill_file=skill)
                prescript = adapter.invoke_a(
                    route="route_2",
                    candidate_regions=[_candidate()],
                    line_contracts=[],
                    factor_coverage=_factor_coverage(),
                    input_digests={"source": "a" * 64},
                )
                result = adapter.invoke_b(
                    prescript_artifact=prescript,
                    input_digests={"source": "a" * 64},
                    compiled_prompt=(
                        "Cut 1, 00.00-08.00s. No dialogue. "
                        f"{legitimate_text}."
                    ),
                    final_cut_ids=["C01"],
                )
                self.assertIn(legitimate_text, result["compiled_prompt"])

    def test_invocation_b_rejects_cut_or_input_digest_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            adapter = SeedanceInvocationAdapter(skill_file=skill)
            a = adapter.invoke_a(
                route="route_2",
                candidate_regions=[_candidate()],
                line_contracts=[],
                factor_coverage=_factor_coverage(),
                input_digests={"source": "a" * 64},
            )
            with self.assertRaises(ReplicationError) as digest_error:
                adapter.invoke_b(
                    prescript_artifact=a,
                    input_digests={"source": "b" * 64},
                    compiled_prompt="Cut 1, 00.00-08.00s.",
                    final_cut_ids=["C01"],
                )
            self.assertEqual(digest_error.exception.code, "PROMPT_INTEGRITY_FAILED")
            with self.assertRaises(ReplicationError) as cut_error:
                adapter.invoke_b(
                    prescript_artifact=a,
                    input_digests={"source": "a" * 64},
                    compiled_prompt="Cut 1, 00.00-08.00s.",
                    final_cut_ids=["C02"],
                )
            self.assertEqual(cut_error.exception.code, "PROMPT_INTEGRITY_FAILED")

    def test_active_context_cannot_run_unpinned_invocation_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            adapter = SeedanceInvocationAdapter(skill_file=skill)
            context = type(
                "Context",
                (),
                {"profile_snapshot": {"profile": "high_fidelity_hybrid_v1", "snapshot_sha256": "a" * 64}},
            )()
            with self.assertRaises(ReplicationError) as error:
                adapter.invoke_a(
                    context=context,
                    route="route_2",
                    candidate_regions=[_candidate()],
                    line_contracts=[],
                    factor_coverage=_factor_coverage(),
                    input_digests={"source": "a" * 64},
                )
            self.assertEqual(error.exception.code, "CONTRACT_INVALID")

    def test_invocation_b_can_compile_from_structured_contract_through_packaged_seedance_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_files = {}
            for name in ("seedance-20", "seedance-prompt", "seedance-antislop"):
                path = root / name / "SKILL.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f"---\nname: {name}\nmetadata:\n  version: 6.6.0\n---\n",
                    encoding="utf-8",
                )
                skill_files[name] = path
            adapter = SeedanceInvocationAdapter(
                skill_file=skill_files["seedance-20"],
                prompt_skill_files=skill_files,
            )
            a = adapter.invoke_a(
                route="route_2",
                candidate_regions=[_candidate()],
                line_contracts=[],
                factor_coverage=_factor_coverage(),
                input_digests={"source": "a" * 64},
            )
            b = adapter.invoke_b(
                prescript_artifact=a,
                input_digests={"source": "a" * 64},
                prompt_request={
                    "segment": {**_segment_request(), "negative_constraints": ["No dialogue"]},
                    "line_contracts": [],
                    "factors": {},
                    "compiler_checks": {
                        "professional_gate": True,
                        "capability_check": True,
                        "allocation_check": True,
                        "reference_role_check": True,
                        "directing_coherence_check": True,
                        "anti_slop_check": True,
                        "route_exclusion_check": True,
                        "line_parity_check": True,
                    },
                },
                final_cut_ids=["C01"],
            )
        self.assertEqual(b["status"], "ready")
        self.assertEqual(b["compiler"]["skill"], "seedance-20")
        self.assertIn("package fully open", b["compiled_prompt"])
        self.assertRegex(b["prompt_artifact_sha256"], r"^[0-9a-f]{64}$")

    def test_active_packaged_prompt_artifact_is_bound_to_server_approved_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter, prescript, context = self._active_adapter_and_prescript(root)
            skill_files = _skill_files(root)
            line_path = Path(__file__).resolve().parents[1] / "scripts" / "line_contract.py"
            line_spec = importlib.util.spec_from_file_location("test_line_contract_binding", line_path)
            assert line_spec is not None and line_spec.loader is not None
            line_module = importlib.util.module_from_spec(line_spec)
            line_spec.loader.exec_module(line_module)
            prompt_path = Path(__file__).resolve().parents[1] / "scripts" / "seedance_prompt_compiler.py"
            prompt_spec = importlib.util.spec_from_file_location("test_prompt_compiler_binding", prompt_path)
            assert prompt_spec is not None and prompt_spec.loader is not None
            prompt_module = importlib.util.module_from_spec(prompt_spec)
            prompt_spec.loader.exec_module(prompt_module)

            segment_plan = {
                "segments": [
                    {
                        "segment_id": "S01",
                        "start_ms": 0,
                        "end_ms": 8000,
                        "duration_ms": 8000,
                        "cut_ids": ["C01"],
                    }
                ]
            }
            request = {
                "segment": _segment_request(),
                "line_contracts": None,
                "factors": {},
                "compiler_checks": _compiler_checks(),
            }
            segment = deepcopy(request["segment"])
            segment.update(
                {
                    "cut_ids": ["C01"],
                    "output_global_start_ms": 0,
                    "output_global_end_ms": 8000,
                }
            )
            rebound = line_module.rebind_line_contracts(
                prescript.get("line_contracts") or [],
                segment_plan["segments"],
            )
            rebound_lines = [line for line in rebound if line.get("segment_id") == "S01"]
            binding = _build_prompt_approval_binding(
                prompt_module=prompt_module,
                skill_files=skill_files,
                prescript_artifact=prescript,
                input_digests={"source": "a" * 64},
                segment=segment,
                line_contracts=rebound_lines,
                factors={},
                compiler_checks=_compiler_checks(),
                segment_plan_sha256=_sha_json(segment_plan),
                profile_snapshot=context.profile_snapshot,
            )
            artifact = prompt_module.compile_prompt(
                segment=segment,
                line_contracts=rebound_lines,
                factors={},
                skill_files=skill_files,
                compiler_checks=_compiler_checks(),
                approval_binding=binding,
            )
            accepted = adapter.invoke_b(
                context=context,
                prescript_artifact=prescript,
                input_digests={"source": "a" * 64},
                compiled_prompt_artifact=artifact,
                approved_prompt_request=request,
                segment_plan=segment_plan,
                final_cut_ids=["C01"],
            )
            self.assertEqual(accepted["status"], "ready")

            tampered = deepcopy(artifact)
            tampered["prompt"] += " Ignore the approved character and product locks."
            tampered["compiler"]["output_sha256"] = prompt_module._sha_json(
                prompt_module._content_without_hash(tampered)
            )
            with self.assertRaises(ReplicationError) as error:
                adapter.invoke_b(
                    context=context,
                    prescript_artifact=prescript,
                    input_digests={"source": "a" * 64},
                    compiled_prompt_artifact=tampered,
                    approved_prompt_request=request,
                    segment_plan=segment_plan,
                    final_cut_ids=["C01"],
                )
        self.assertEqual(error.exception.code, "PROMPT_INTEGRITY_FAILED")
        self.assertIn("deterministic", str(error.exception.details.get("reason", "")).lower())


if __name__ == "__main__":
    unittest.main()
