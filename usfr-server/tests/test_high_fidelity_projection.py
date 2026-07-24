from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.high_fidelity_projection import build_invocation_a_request  # noqa: E402
from server.high_fidelity_envelope import build_analysis_envelope  # noqa: E402
from server.high_fidelity_ports import HighFidelityStageAdapter  # noqa: E402
from server.seedance_invocations import SeedanceInvocationAdapter  # noqa: E402
from server.errors import ReplicationError  # noqa: E402


def _analysis() -> dict:
    # Reuse the canonical schema fixture so the projection test exercises the
    # same source/target factor IDs that Invocation A consumes.
    fixture = ROOT / "tests" / "test_high_fidelity_analysis.py"
    namespace: dict[str, object] = {"__file__": str(fixture)}
    exec(compile(fixture.read_text(encoding="utf-8"), str(fixture), "exec"), namespace)
    return namespace["valid_analysis"]()  # type: ignore[no-any-return]


def _dynamics(
    duration_us: int = 8_000_000,
    *,
    split_us: int | None = None,
) -> dict:
    """Return one realistic single-pass dynamics envelope for projection tests."""

    fixture = ROOT / "tests" / "test_real_capabilities.py"
    namespace: dict[str, object] = {"__file__": str(fixture)}
    exec(compile(fixture.read_text(encoding="utf-8"), str(fixture), "exec"), namespace)
    value = namespace["_high_fidelity_semantic_payload"](duration_us)  # type: ignore[no-any-return]
    if split_us is not None:
        if not 0 < split_us < duration_us:
            raise ValueError("split_us must fall inside the source duration")
        source = deepcopy(value["source_cuts"][0])
        first = deepcopy(source)
        first.update({"cut": 1, "start_us": 0, "end_us": split_us})
        second = deepcopy(source)
        second.update({"cut": 2, "start_us": split_us, "end_us": duration_us})
        value["source_cuts"] = [first, second]
        value["source_events"][0]["source_cut_end"] = 2

        extension = value["extensions"]["high_fidelity_hybrid_v1"]
        first_semantic = deepcopy(extension["semantic_cuts"][0])
        second_semantic = deepcopy(first_semantic)
        first_semantic["cut"] = 1
        second_semantic["cut"] = 2
        first_semantic["object_action"]["state_sequence"] = [
            {
                "phase": "before",
                "start_us": 0,
                "end_us": split_us // 2,
                "state": "hands beside product",
            },
            {
                "phase": "completed",
                "start_us": split_us // 2,
                "end_us": split_us,
                "state": "first Cut endpoint complete",
            },
        ]
        second_semantic["object_action"]["state_sequence"] = [
            {
                "phase": "before",
                "start_us": split_us,
                "end_us": split_us + (duration_us - split_us) // 2,
                "state": "second Cut begins from the approved handoff",
            },
            {
                "phase": "completed",
                "start_us": split_us + (duration_us - split_us) // 2,
                "end_us": duration_us,
                "state": "second Cut endpoint complete",
            },
        ]
        extension["semantic_cuts"] = [first_semantic, second_semantic]
    return {
        "contract": "reference-video-dynamics",
        "contract_version": 1,
        "reference_duration_us": duration_us,
        "source_width": 1080,
        "source_height": 1920,
        "fps_num": 30,
        "fps_den": 1,
        "source_cut_count": len(value["source_cuts"]),
        **value,
    }


def _audio_contract(duration_ms: int = 8_000) -> dict:
    return {
        "schema_version": "audio-contract/v1",
        "source_duration_ms": duration_ms,
        "segments": [],
        "silence_windows": [{"start_ms": 0, "end_ms": duration_ms, "kind": "meaningful_silence"}],
        "meaningful_silence": [{"start_ms": 0, "end_ms": duration_ms, "kind": "meaningful_silence"}],
        "audio_events": [{"event_id": "1", "kind": "ambience", "start_ms": 0, "end_ms": duration_ms}],
    }


def _projection_context(
    *,
    duration_ms: int,
    split_ms: int,
    route: str = "route_2",
):
    regions = ({
        "region_id": "R01",
        "region_type": "generated",
        "media_origin": "generated",
        "assembly_policy": "generate_region",
        "source_start_us": 0,
        "source_end_us": duration_ms * 1000,
        "cut_ids": ["C01", "C02"],
    },)
    envelope = build_analysis_envelope(
        high_fidelity_analysis=_analysis(),
        source_dynamics_analysis=_dynamics(
            duration_ms * 1000,
            split_us=split_ms * 1000,
        ),
        audio_contract=_audio_contract(duration_ms),
        timeline_regions={"regions": list(regions)},
    )
    return type(
        "ProjectionContext",
        (_Context,),
        {
            "artifacts": (),
            "timeline_regions": regions,
            "execution_route": route,
            "stage_outputs": {
                "analyze_dynamics": {"analysis_envelope": envelope}
            },
        },
    )


def _second_cut_line() -> dict:
    from test_line_contract import _line

    line = _line()
    line["cut_id"] = "C02"
    line["candidate_region_id"] = "R01"
    line["time"].update(
        {
            "start_ms": 8_000,
            "end_ms": 9_600,
            "duration_ms": 1_600,
            "cut_ids": ["C02"],
        }
    )
    line["proof_events"][0].update({"start_ms": 10_400, "end_ms": 11_200})
    line["foley_events"][0].update({"start_ms": 11_200, "end_ms": 12_000})
    line["silence_windows"][0].update({"start_ms": 9_600, "end_ms": 10_400})
    return line


class _Context:
    stage = "build_script"
    timeline_regions = (
        {
            "region_id": "R01",
            "region_type": "generated",
            "media_origin": "generated",
            "assembly_policy": "generate_region",
            "source_start_us": 0,
            "source_end_us": 8_000_000,
            "cut_ids": ["C01"],
        },
    )
    input_slots = (
        {"slot_id": "source_video", "present": True, "sha256": ["a" * 64]},
        {"slot_id": "new_product_image", "present": True, "sha256": ["b" * 64]},
        {"slot_id": "new_model_image", "present": True, "sha256": ["c" * 64]},
    )
    profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
    execution_route = "route_2"
    artifacts = (
        {
            "kind": "high_fidelity_analysis",
            "metadata": {"inline_json": _analysis()},
        },
    )

    @contextmanager
    def materialize_artifact(self, kind: str):
        raise AssertionError(f"unexpected materialization for inline artifact: {kind}")
        yield  # pragma: no cover


class HighFidelityProjectionTest(unittest.TestCase):
    def test_route_two_long_region_requires_explicit_proposed_split_boundary(self):
        context_type = _projection_context(duration_ms=18_000, split_ms=9_000)

        with self.assertRaisesRegex(
            ReplicationError,
            "proposed_split_boundary_ms",
        ):
            build_invocation_a_request(context_type(), {})

    def test_route_two_long_region_projects_two_provisional_candidates(self):
        context_type = _projection_context(duration_ms=18_000, split_ms=9_000)

        request = build_invocation_a_request(
            context_type(),
            {"proposed_split_boundary_ms": 9_000},
        )

        self.assertEqual(request["proposed_split_boundary_ms"], 9_000)
        self.assertEqual(
            [candidate["cut_ids"] for candidate in request["candidate_regions"]],
            [["C01"], ["C02"]],
        )
        self.assertEqual(
            [candidate["duration_ms"] for candidate in request["candidate_regions"]],
            [9_000, 9_000],
        )
        self.assertEqual(
            [
                (
                    candidate["output_global_start_ms"],
                    candidate["output_global_end_ms"],
                )
                for candidate in request["candidate_regions"]
            ],
            [(0, 9_000), (9_000, 18_000)],
        )
        self.assertEqual(
            [segment["cut_ids"] for segment in request["canonical_segments"]],
            [["C01"], ["C02"]],
        )

    def test_route_two_sixteen_second_region_retimes_every_approved_timing(self):
        context_type = _projection_context(duration_ms=16_000, split_ms=8_000)

        request = build_invocation_a_request(
            context_type(),
            {"line_contracts": [_second_cut_line()]},
        )

        self.assertEqual(len(request["candidate_regions"]), 1)
        candidate = request["candidate_regions"][0]
        self.assertEqual(candidate["duration_ms"], 15_000)
        self.assertEqual(candidate["retime_scale"], 0.9375)
        self.assertEqual(
            [
                (
                    shot["cut_id"],
                    shot["output_global_start_ms"],
                    shot["output_global_end_ms"],
                    shot["start_ms"],
                    shot["end_ms"],
                )
                for shot in candidate["shot_budget"]
            ],
            [
                ("C01", 0, 7_500, 0, 7_500),
                ("C02", 7_500, 15_000, 7_500, 15_000),
            ],
        )
        line = request["line_contracts"][0]
        self.assertEqual(line["candidate_region_id"], candidate["candidate_region_id"])
        self.assertEqual(
            (line["time"]["start_ms"], line["time"]["end_ms"]),
            (7_500, 9_000),
        )
        self.assertEqual(
            (
                line["proof_events"][0]["start_ms"],
                line["proof_events"][0]["end_ms"],
            ),
            (9_750, 10_500),
        )
        self.assertEqual(
            (
                line["foley_events"][0]["start_ms"],
                line["foley_events"][0]["end_ms"],
            ),
            (10_500, 11_250),
        )
        self.assertEqual(
            (
                line["silence_windows"][0]["start_ms"],
                line["silence_windows"][0]["end_ms"],
            ),
            (9_000, 9_750),
        )
        completed = [
            state
            for state in candidate["action_state_requirements"]
            if state["phase"] == "completed"
        ]
        self.assertTrue(completed)
        self.assertEqual(max(state["end_ms"] for state in completed), 15_000)
        self.assertEqual(
            candidate["voiceover_timing_plan"],
            [{"line_id": line["line_id"], "carrier": "prompt"}],
        )

    def test_route_one_cannot_silently_retime_a_sixteen_second_region(self):
        context_type = _projection_context(
            duration_ms=16_000,
            split_ms=8_000,
            route="route_1",
        )

        with self.assertRaisesRegex(
            ReplicationError,
            "Route 1.*output timing",
        ):
            build_invocation_a_request(context_type(), {})

    def test_route_one_retime_requires_approved_script_timing_digest(self):
        dynamics = _dynamics(16_000_000, split_us=8_000_000)
        dynamics["source_cuts"][0].update(
            {"output_start_ms": 0, "output_end_ms": 7_500}
        )
        dynamics["source_cuts"][1].update(
            {"output_start_ms": 7_500, "output_end_ms": 15_000}
        )
        action_rows = []
        for cut_index, semantic_cut in enumerate(
            dynamics["extensions"]["high_fidelity_hybrid_v1"]["semantic_cuts"],
            start=1,
        ):
            cut_output_start = 0 if cut_index == 1 else 7_500
            for state_index, state in enumerate(
                semantic_cut["object_action"]["state_sequence"]
            ):
                local_start = 0 if state_index == 0 else 3_750
                local_end = 3_750 if state_index == 0 else 7_500
                state.update(
                    {
                        "output_start_ms": cut_output_start + local_start,
                        "output_end_ms": cut_output_start + local_end,
                    }
                )
                action_rows.append(
                    {
                        "cut_id": f"C{cut_index:02d}",
                        "phase": state["phase"],
                        "output_start_ms": state["output_start_ms"],
                        "output_end_ms": state["output_end_ms"],
                    }
                )
        regions = (
            {
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 16_000_000,
                "output_start_ms": 0,
                "output_end_ms": 15_000,
                "cut_ids": ["C01", "C02"],
            },
        )
        envelope = build_analysis_envelope(
            high_fidelity_analysis=_analysis(),
            source_dynamics_analysis=dynamics,
            audio_contract=_audio_contract(16_000),
            timeline_regions={"regions": list(regions)},
        )
        context_type = type(
            "ApprovedRouteOneContext",
            (_Context,),
            {
                "artifacts": (),
                "timeline_regions": regions,
                "execution_route": "route_1",
                "stage_outputs": {
                    "analyze_dynamics": {"analysis_envelope": envelope}
                },
            },
        )

        with self.assertRaisesRegex(
            ReplicationError,
            "Route 1.*approved script",
        ):
            build_invocation_a_request(context_type(), {})

        timing_payload = {
            "regions": [
                {
                    "region_id": "R01",
                    "output_start_ms": 0,
                    "output_end_ms": 15_000,
                    "cut_ids": ["C01", "C02"],
                }
            ],
            "cuts": [
                {
                    "cut_id": "C01",
                    "output_start_ms": 0,
                    "output_end_ms": 7_500,
                },
                {
                    "cut_id": "C02",
                    "output_start_ms": 7_500,
                    "output_end_ms": 15_000,
                },
            ],
            "action_states": action_rows,
        }
        output_timing_sha256 = hashlib.sha256(
            json.dumps(
                timing_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        script_sha256 = "d" * 64
        request = build_invocation_a_request(
            context_type(),
            {
                "timing_authority": {
                    "kind": "approved_script",
                    "script_sha256": script_sha256,
                    "output_timing_sha256": output_timing_sha256,
                }
            },
        )

        self.assertEqual(
            request["timing_authority"],
            {
                "kind": "approved_script",
                "script_sha256": script_sha256,
                "output_timing_sha256": output_timing_sha256,
            },
        )
        self.assertEqual(request["input_digests"]["approved_script"], script_sha256)
        self.assertEqual(
            request["input_digests"]["approved_output_timing"],
            output_timing_sha256,
        )

    def test_active_production_requires_immutable_evidence_digest_binding(self):
        class ProductionContext(_Context):
            allow_local_paths = False
            profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }

        with self.assertRaisesRegex(ReplicationError, "EVIDENCE_DIGEST_UNBOUND"):
            build_invocation_a_request(ProductionContext(), {})

    def test_active_production_accepts_evidence_bound_to_uploaded_or_published_bytes(self):
        analysis = deepcopy(_analysis())

        def bind(value):
            if isinstance(value, dict):
                if "evidence_id" in value:
                    value["artifact_sha256"] = "b" * 64
                for child in value.values():
                    bind(child)
            elif isinstance(value, list):
                for child in value:
                    bind(child)

        bind(analysis)

        class BoundProductionContext(_Context):
            allow_local_paths = False
            profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            artifacts = (
                {
                    "kind": "high_fidelity_analysis",
                    "metadata": {"inline_json": analysis},
                },
            )

        request = build_invocation_a_request(BoundProductionContext(), {})
        self.assertEqual(request["candidate_regions"][0]["cut_ids"], ["C01"])

    def test_active_production_cannot_bypass_canonical_invocation_a_projection(self):
        class BoundProductionContext(_Context):
            allow_local_paths = False
            profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            artifacts = (
                {
                    "kind": "high_fidelity_analysis",
                    "metadata": {"inline_json": _analysis()},
                },
            )

        with self.assertRaisesRegex(ReplicationError, "canonical Invocation A projection"):
            build_invocation_a_request(
                BoundProductionContext(),
                {"invocation_a_request": {"candidate_regions": []}},
            )

    def test_projects_authoritative_analysis_into_invocation_a_request(self):
        request = build_invocation_a_request(_Context(), {})
        self.assertEqual(request["route"], "route_2")
        self.assertEqual(request["candidate_regions"][0]["cut_ids"], ["C01"])
        self.assertIn("F-PROD-001", request["candidate_regions"][0]["required_factor_ids"])
        self.assertEqual(
            {item["factor_id"] for item in request["factor_coverage"]},
            set(request["candidate_regions"][0]["required_factor_ids"]),
        )
        self.assertEqual(request["input_digests"]["new_product_image"], "b" * 64)

    def test_projection_excludes_generated_ui_and_route_only_ui_variants(self):
        route_variants = (
            {"region_type": "generated_ui_demo"},
            {"region_type": "generated-ui-demo"},
            {"region_type": "generatedUiDemo"},
            {"region_type": "generated_ui"},
            {"assembly_policy": "generate_ui"},
            {"region_type": "ui_demo"},
            {"region_type": "uiDemo"},
            {"region_type": "tail_card"},
            {"region_type": "tailCard"},
            {"region_type": "opaque_ui_video"},
            {"region_type": "ui_operation_video"},
            {"region_type": "tail_video"},
            {"region_type": "tail_card_video"},
            {"region_type": "app_tail_card_video"},
            {"region_type": "source_ui_frames"},
            {"region_type": "transition_shell"},
            {"region_type": "excluded_region"},
            {"region_type": "future_route_only"},
        )
        for mutation in route_variants:
            with self.subTest(mutation=mutation):
                region = {**dict(_Context.timeline_regions[0]), **mutation}
                context_type = type(
                    "GeneratedUiContext",
                    (_Context,),
                    {"timeline_regions": (region,)},
                )
                request = build_invocation_a_request(context_type(), {})
                self.assertEqual(request["candidate_regions"], [])
                self.assertEqual(request["factor_coverage"], [])

    def test_build_script_bridge_projects_request_before_invocation_a(self):
        class Invocation:
            def __init__(self):
                self.payload = None

            def invoke_a(self, *, context, **payload):
                self.payload = payload
                return {"profile": "seedance20_prescript_v1", "status": "ready"}

        invocation = Invocation()
        context = _Context()
        result = HighFidelityStageAdapter(invocation).run_stage(
            context=context,
            handler=lambda **_: {"script": "projected"},
        )
        self.assertEqual(result["script"], "projected")
        self.assertIn("candidate_regions", invocation.payload)

    def test_projected_payload_matches_the_strict_invocation_a_signature(self):
        class StrictInvocation:
            def invoke_a(
                self,
                *,
                context,
                route,
                candidate_regions,
                line_contracts,
                factor_coverage,
                input_digests,
            ):
                return {
                    "profile": "seedance20_prescript_v1",
                    "status": "ready",
                    "candidate_count": len(candidate_regions),
                }

        result = HighFidelityStageAdapter(StrictInvocation()).run_stage(
            context=_Context(),
            handler=lambda **_: {"script": "projected"},
        )
        self.assertEqual(result["invocation_a"]["candidate_count"], 1)

    def test_route_one_projection_remains_read_only_route_one(self):
        context = _Context()
        context.execution_route = "route_1"
        request = build_invocation_a_request(context, {})
        self.assertEqual(request["route"], "route_1")

    def test_projection_can_consume_analysis_returned_by_the_same_build_script_handler(self):
        class Context(_Context):
            artifacts = ()

        class Invocation:
            def invoke_a(self, *, context, **payload):
                return {
                    "profile": "seedance20_prescript_v1",
                    "status": "ready",
                    "factor_count": len(payload["factor_coverage"]),
                }

        result = HighFidelityStageAdapter(Invocation()).run_stage(
            context=Context(),
            handler=lambda **_: {
                "script": "projected",
                "high_fidelity_analysis": _analysis(),
            },
        )
        self.assertGreater(result["invocation_a"]["factor_count"], 0)

    def test_projection_rejects_legacy_analysis_mislabeled_as_raw_dynamics_stage_output(self):
        class Context(_Context):
            artifacts = ()
            stage_outputs = {
                "analyze_dynamics": {
                    "source_dynamics_analysis": _analysis(),
                    "audio_contract": {
                        "segments": [],
                        "silence_windows": [],
                    },
                }
            }

        with self.assertRaisesRegex(ReplicationError, "canonical high-fidelity analysis envelope"):
            build_invocation_a_request(Context(), {})

    def test_raw_dynamics_stage_output_cannot_be_used_as_high_fidelity_analysis(self):
        class Context(_Context):
            artifacts = ()
            stage_outputs = {
                "analyze_dynamics": {
                    "source_dynamics_analysis": _dynamics(),
                    "audio_contract": _audio_contract(),
                }
            }

        with self.assertRaisesRegex(ReplicationError, "canonical high-fidelity analysis envelope"):
            build_invocation_a_request(Context(), {})

    def test_canonical_envelope_projects_rich_shots_and_projection_digest(self):
        envelope = build_analysis_envelope(
            high_fidelity_analysis=_analysis(),
            source_dynamics_analysis=_dynamics(),
            audio_contract=_audio_contract(),
            timeline_regions={"regions": list(_Context.timeline_regions)},
        )

        class Context(_Context):
            artifacts = ()
            stage_outputs = {"analyze_dynamics": {"analysis_envelope": envelope}}

        request = build_invocation_a_request(Context(), {})
        candidate = request["candidate_regions"][0]
        shot = candidate["shot_budget"][0]
        self.assertEqual(request["projection_sha256"], envelope["projection_sha256"])
        self.assertEqual((shot["start_ms"], shot["end_ms"]), (0, 8_000))
        for field in (
            "scene",
            "camera",
            "lighting",
            "performance",
            "action",
            "product_or_ui_truth",
            "commercial_proof",
            "transition",
            "continuity",
            "audio",
            "factor_ids",
        ):
            self.assertIn(field, shot)
        self.assertEqual(candidate["canonical_segment"]["shots"][0], shot)

    def test_canonical_envelope_rejects_reversed_or_out_of_range_asr_segment(self):
        audio = _audio_contract()
        audio["segments"] = [
            {
                "segment_id": "A001",
                "start_ms": 9_000,
                "end_ms": 1_000,
                "text": "invalid timing",
            }
        ]

        with self.assertRaisesRegex(ValueError, "audio segment.*timing"):
            build_analysis_envelope(
                high_fidelity_analysis=_analysis(),
                source_dynamics_analysis=_dynamics(),
                audio_contract=audio,
            )

    def test_canonical_envelope_reconciles_source_speech_text_with_asr(self):
        dynamics = _dynamics()
        dynamics["source_events"] = [
            {
                "event": 1,
                "kind": "dialogue",
                "start_us": 0,
                "end_us": 900_000,
                "text": "source approved words",
            }
        ]
        audio = _audio_contract()
        audio["segments"] = [
            {
                "segment_id": "A001",
                "start_ms": 0,
                "end_ms": 900,
                "text": "different words",
            }
        ]

        with self.assertRaisesRegex(ValueError, "speech text.*ASR"):
            build_analysis_envelope(
                high_fidelity_analysis=_analysis(),
                source_dynamics_analysis=dynamics,
                audio_contract=audio,
            )

    def test_spoken_generated_region_requires_exact_line_contract(self):
        dynamics = _dynamics()
        dynamics["source_events"] = [
            {
                "event": 1,
                "kind": "voiceover",
                "start_us": 0,
                "end_us": 900_000,
                "text": "approved source words",
            }
        ]
        audio = _audio_contract()
        audio["segments"] = [
            {
                "segment_id": "A001",
                "start_ms": 0,
                "end_ms": 900,
                "text": "approved source words",
            }
        ]
        envelope = build_analysis_envelope(
            high_fidelity_analysis=_analysis(),
            source_dynamics_analysis=dynamics,
            audio_contract=audio,
            timeline_regions={"regions": list(_Context.timeline_regions)},
        )

        class Context(_Context):
            artifacts = ()
            stage_outputs = {"analyze_dynamics": {"analysis_envelope": envelope}}

        with self.assertRaisesRegex(ReplicationError, "EXACT_LINE_CONTRACT_REQUIRED"):
            build_invocation_a_request(Context(), {})

    def test_canonical_envelope_parent_digest_must_belong_to_the_current_run(self):
        envelope = build_analysis_envelope(
            high_fidelity_analysis=_analysis(),
            source_dynamics_analysis=_dynamics(),
            audio_contract=_audio_contract(),
            parent_digests={"source_video": "d" * 64},
        )

        class Context(_Context):
            artifacts = ()
            stage_outputs = {"analyze_dynamics": {"analysis_envelope": envelope}}

        with self.assertRaisesRegex(ReplicationError, "parent digest"):
            build_invocation_a_request(Context(), {})

    def test_projection_is_accepted_by_the_packaged_invocation_a_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text(
                "---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n",
                encoding="utf-8",
            )
            adapter = SeedanceInvocationAdapter(skill_file=skill)
            result = HighFidelityStageAdapter(adapter).run_stage(
                context=_Context(),
                handler=lambda **_: {"script": "projected"},
            )
        self.assertEqual(result["invocation_a"]["profile"], "seedance20_prescript_v1")


if __name__ == "__main__":
    unittest.main()
