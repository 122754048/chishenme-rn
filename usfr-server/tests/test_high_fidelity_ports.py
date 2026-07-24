from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from server.high_fidelity_ports import HighFidelityStageAdapter
from server.errors import ReplicationError
from server.seedance_invocations import SeedanceInvocationAdapter

from test_performance_audio_contracts import _approved_lines, _lines


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


def _provider_payload(prompt: str, *, duration: int = 8) -> dict:
    return {
        "model": "seedance-2.0-fast",
        "content": [{"type": "text", "text": prompt}],
        "generate_audio": True,
        "ratio": "9:16",
        "duration": duration,
        "watermark": False,
        "resolution": "720p",
    }


def _request_sha(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class HighFidelityPortsTest(unittest.TestCase):
    def test_invocation_b_blocks_source_audio_when_confirmed_performance_artifact_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {"segments": [{"segment_id": "S01", "start_ms": 0, "end_ms": 8_000, "duration_ms": 8_000, "cut_ids": ["C01"]}]}
            plan_path = root / "segment_plan.json"
            plan_path.write_bytes(json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()

            class Invocation:
                def invoke_b(self, **_kwargs):
                    raise AssertionError("Invocation B must not run without the confirmed performance artifact")

            class Context:
                stage = "compile_seedance20_prompt"
                profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
                artifacts = (
                    {"kind": "segment_plan", "sha256": plan_sha},
                    {"kind": "performance_audio_source_contract", "sha256": "a" * 64},
                    {"kind": "audio_lyrics_beat_contract", "sha256": "b" * 64},
                )

                @contextmanager
                def materialize_artifact(self, kind, **_kwargs):
                    assert kind == "segment_plan"
                    yield type("Media", (), {"path": plan_path})()

            with self.assertRaisesRegex(ReplicationError, "approved performance line contract"):
                HighFidelityStageAdapter(Invocation()).run_stage(
                    context=Context(),
                    handler=lambda **_: {
                        "invocation_b_request": {
                            "segment_id": "S01",
                            "provider_payload": _provider_payload("Prompt for S01"),
                            "seedance_input_contract": {"contract": "S01"},
                        }
                    },
                )

    def test_invocation_b_rejects_a_performance_artifact_with_a_changed_confirmed_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {"segments": [{"segment_id": "S01", "start_ms": 0, "end_ms": 4_000, "duration_ms": 4_000, "cut_ids": ["C01"]}]}
            approved_sha = "c" * 64
            published_timeline_sha = "d" * 64
            sidecar_timeline_sha = "e" * 64
            line = {**_approved_lines()[0], "source_content_timeline_sha256": sidecar_timeline_sha}
            sidecar = {
                "contract": "approved-script-lines/v1",
                "revision": 1,
                "script_sha256": approved_sha,
                "source_content_timeline_sha256": sidecar_timeline_sha,
                "line_contracts": [line],
                "line_contracts_sha256": hashlib.sha256(json.dumps([line], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            }
            performance_line = {
                **_lines()[0],
                "source_content_timeline_sha256": published_timeline_sha,
            }
            performance = {
                "contract": "performance-line/v1",
                "script_revision": 1,
                "script_sha256": approved_sha,
                "source_content_timeline_sha256": published_timeline_sha,
                "line_contracts_sha256": sidecar["line_contracts_sha256"],
                "cuts": [performance_line],
            }
            paths = {}
            artifacts = []
            for kind, value in (("segment_plan", plan), ("performance_line_contract", performance)):
                path = root / f"{kind}.json"
                raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                path.write_bytes(raw)
                sha = hashlib.sha256(raw).hexdigest()
                paths[kind] = path
                artifacts.append({"kind": kind, "sha256": sha})
            artifacts.extend(
                [
                    {"kind": "performance_audio_source_contract", "sha256": "a" * 64},
                    {"kind": "audio_lyrics_beat_contract", "sha256": "b" * 64},
                ]
            )

            class Invocation:
                def invoke_b(self, **_kwargs):
                    raise AssertionError("Invocation B must not run with a changed timeline")

            class Context:
                stage = "compile_seedance20_prompt"
                profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
                snapshot = type("Snapshot", (), {"current_script_revision": 1, "approved_script_sha256": approved_sha})()
                job_id = "timeline-gate"
                job_store = type("Store", (), {"get_script_approval": lambda _self, _job, _revision: sidecar})()

                def __init__(self):
                    self.artifacts = tuple(artifacts)

                @contextmanager
                def materialize_artifact(self, kind, **_kwargs):
                    yield type("Media", (), {"path": paths[kind]})()

            with self.assertRaisesRegex(ReplicationError, "timeline SHA"):
                HighFidelityStageAdapter(Invocation()).run_stage(
                    context=Context(),
                    handler=lambda **_: {
                        "invocation_b_request": {
                            "segment_id": "S01",
                            "prompt_request": {
                                "segment": {
                                    "segment_id": "S01",
                                    "duration_ms": 4_000,
                                    "cut_ids": ["C01"],
                                }
                            },
                            "provider_payload": _provider_payload("Prompt for S01"),
                            "seedance_input_contract": {"contract": "S01"},
                        }
                    },
                )

    def test_provider_binding_preserves_the_frozen_performance_contract_digest(self):
        performance_sha = "f" * 64
        timeline_sha = "e" * 64

        binding = HighFidelityStageAdapter._provider_binding(
            segment_id="S01",
            segment_plan_sha256="a" * 64,
            request={
                "provider_payload": _provider_payload("Prompt for S01"),
                "performance_line_contract_sha256": performance_sha,
                "source_content_timeline_sha256": timeline_sha,
            },
            result={
                "performance_line_contract_sha256": performance_sha,
                "source_content_timeline_sha256": timeline_sha,
            },
        )

        self.assertEqual(
            binding["performance_line_contract_sha256"],
            performance_sha,
        )
        self.assertEqual(binding["source_content_timeline_sha256"], timeline_sha)

    def test_invocation_b_requires_a_source_audio_provider_digest_and_timeline_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            timeline_sha = "c" * 64
            script_sha = "d" * 64
            approved_line = {**_approved_lines()[0], "source_content_timeline_sha256": timeline_sha}
            sidecar = {
                "contract": "approved-script-lines/v1",
                "revision": 1,
                "script_sha256": script_sha,
                "source_content_timeline_sha256": timeline_sha,
                "line_contracts": [approved_line],
                "line_contracts_sha256": hashlib.sha256(
                    json.dumps([approved_line], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            }
            performance = {
                "contract": "performance-line/v1",
                "script_revision": 1,
                "script_sha256": script_sha,
                "source_content_timeline_sha256": timeline_sha,
                "line_contracts_sha256": sidecar["line_contracts_sha256"],
                "cuts": [{**_lines()[0], "source_content_timeline_sha256": timeline_sha}],
            }
            plan = {"segments": [{"segment_id": "S01", "start_ms": 0, "end_ms": 4_000, "duration_ms": 4_000, "cut_ids": ["C01"]}]}
            paths = {}
            artifacts = []
            for kind, value in (("segment_plan", plan), ("performance_line_contract", performance)):
                path = root / f"{kind}.json"
                raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                path.write_bytes(raw)
                sha256 = hashlib.sha256(raw).hexdigest()
                paths[kind] = path
                artifacts.append({"kind": kind, "sha256": sha256})
            artifacts.extend(
                [
                    {"kind": "performance_audio_source_contract", "sha256": "a" * 64},
                    {"kind": "audio_lyrics_beat_contract", "sha256": "b" * 64},
                ]
            )

            class Invocation:
                received = None

                def invoke_b(self, *, context, **payload):
                    self.received = payload
                    prompt = "Prompt for S01"
                    return {
                        "status": "ready",
                        "segment_id": "S01",
                        "segment_plan_sha256": artifacts[0]["sha256"],
                        "compiled_prompt": prompt,
                        "compiled_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    }

            class Context:
                stage = "compile_seedance20_prompt"
                profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
                snapshot = type("Snapshot", (), {"current_script_revision": 1, "approved_script_sha256": script_sha})()
                job_id = "provider-digest-gate"
                job_store = type("Store", (), {"get_script_approval": lambda _self, _job, _revision: sidecar})()

                def __init__(self):
                    self.artifacts = tuple(artifacts)

                @contextmanager
                def materialize_artifact(self, kind, **_kwargs):
                    yield type("Media", (), {"path": paths[kind]})()

            invocation = Invocation()
            with self.assertRaisesRegex(ReplicationError, "performance line contract digest"):
                HighFidelityStageAdapter(invocation).run_stage(
                    context=Context(),
                    handler=lambda **_: {
                        "invocation_b_request": {
                            "segment_id": "S01",
                            "prompt_request": {"segment": {"segment_id": "S01", "duration_ms": 4_000, "cut_ids": ["C01"]}},
                            "provider_payload": _provider_payload("Prompt for S01", duration=4),
                            "seedance_input_contract": {"contract": "S01"},
                        }
                    },
                )
            self.assertEqual(
                invocation.received["performance_line_contract_sha256"],
                artifacts[1]["sha256"],
            )
            self.assertEqual(invocation.received["source_content_timeline_sha256"], timeline_sha)

    def test_invocation_b_injects_approved_performance_lines_without_provider_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {"segments": [{"segment_id": "S01", "start_ms": 0, "end_ms": 8_000, "duration_ms": 8_000, "cut_ids": ["C01"]}]}
            performance = {
                "contract": "performance-line/v1",
                "source_audio_sha256": "a" * 64,
                "cuts": [{
                    "cut_id": "C01", "source_time": {"start_ms": 0, "end_ms": 8_000}, "segment_time": {"start_ms": 0, "end_ms": 8_000},
                    "performance_mode": "singing", "exact_sung_text": "Carry forward.", "lyric_status": "verified", "beat_anchors_ms": [200], "no_beat_reason": None,
                    "lip_sync": {"face_visibility": "front visible", "articulation": "clear lyric mouth shapes", "end_state": "mouth closes"},
                    "action": {"start": "hands down", "beat_action": "raise palm", "end": "hands down"},
                    "expression": {"start": "calm", "peak": "bright", "end": "steady"},
                    "emotion": "release", "end_pose": "front-facing pose", "criticality": "H", "final_audio_carrier": "source_audio_global_window_postproduction",
                }],
            }
            paths = {}
            artifacts = []
            for kind, value in (("segment_plan", plan), ("performance_line_contract", performance)):
                path = root / f"{kind}.json"
                raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                path.write_bytes(raw)
                sha = hashlib.sha256(raw).hexdigest()
                paths[kind] = path
                artifacts.append({"kind": kind, "sha256": sha})

            class Invocation:
                def invoke_b(self, *, context, **payload):
                    context.observed = payload
                    prompt = "Carry forward."
                    return {"status": "ready", "segment_id": "S01", "segment_plan_sha256": artifacts[0]["sha256"], "compiled_prompt": prompt, "compiled_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}

            class Context:
                stage = "compile_seedance20_prompt"
                profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
                artifacts = ()

                @contextmanager
                def materialize_artifact(self, kind, **_kwargs):
                    yield type("Media", (), {"path": paths[kind]})()

            context = Context()
            context.artifacts = tuple(artifacts)
            HighFidelityStageAdapter(Invocation()).run_stage(
                context=context,
                handler=lambda **_: {"invocation_b_request": {"segment_id": "S01", "prompt_request": {"segment": {"segment_id": "S01", "duration_ms": 8_000, "cut_ids": ["C01"]}}, "provider_payload": _provider_payload("Carry forward."), "seedance_input_contract": {"contract": "S01"}}},
            )
            self.assertEqual(context.observed["prompt_request"]["performance_lines"], performance["cuts"])
            self.assertNotIn("reference_audios", context.observed)

    def test_invocation_b_fans_out_two_frozen_segments_inside_one_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
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
                        "start_ms": 8_000,
                        "end_ms": 16_000,
                        "duration_ms": 8_000,
                        "cut_ids": ["C02"],
                    },
                ]
            }
            plan_path = root / "segment_plan.json"
            plan_path.write_text(
                json.dumps(
                    plan,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            calls = []

            class Invocation:
                def invoke_b(self, *, context, **payload):
                    calls.append(dict(payload))
                    segment_id = payload["segment_id"]
                    compiled_prompt = f"Prompt for {segment_id}"
                    return {
                        "status": "ready",
                        "segment_id": segment_id,
                        "segment_plan_sha256": plan_sha,
                        "compiled_prompt": compiled_prompt,
                        "compiled_prompt_sha256": hashlib.sha256(
                            compiled_prompt.encode("utf-8")
                        ).hexdigest(),
                    }

            class Context:
                stage = "compile_seedance20_prompt"
                profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
                artifacts = ({"kind": "segment_plan", "sha256": plan_sha},)

                @contextmanager
                def materialize_artifact(self, kind, **_kwargs):
                    self.materialized_kind = kind
                    yield type("Media", (), {"path": plan_path})()

            output = HighFidelityStageAdapter(Invocation()).run_stage(
                context=Context(),
                handler=lambda **_: {
                    "invocation_b_requests": [
                        {
                            "segment_id": "S01",
                            "request_token": "first",
                            "provider_payload": _provider_payload("Prompt for S01"),
                            "seedance_input_contract": {"contract": "S01"},
                        },
                        {
                            "segment_id": "S02",
                            "request_token": "second",
                            "provider_payload": _provider_payload("Prompt for S02"),
                            "seedance_input_contract": {"contract": "S02"},
                        },
                    ]
                },
            )

            self.assertEqual([call["segment_id"] for call in calls], ["S01", "S02"])
            self.assertTrue(all(call["segment_plan"] == plan for call in calls))
            self.assertEqual(
                [item["segment_id"] for item in output["invocation_b_segments"]],
                ["S01", "S02"],
            )
            self.assertTrue(
                all(
                    item["segment_plan_sha256"] == plan_sha
                    for item in output["invocation_b_segments"]
                )
            )
            self.assertEqual(
                [item["segment_id"] for item in output["provider_requests"]],
                ["S01", "S02"],
            )
            self.assertEqual(
                output["provider_requests"],
                [
                    {
                        "segment_id": "S01",
                        "segment_plan_sha256": plan_sha,
                        "provider_payload": _provider_payload("Prompt for S01"),
                        "request_sha256": _request_sha(_provider_payload("Prompt for S01")),
                    },
                    {
                        "segment_id": "S02",
                        "segment_plan_sha256": plan_sha,
                        "provider_payload": _provider_payload("Prompt for S02"),
                        "request_sha256": _request_sha(_provider_payload("Prompt for S02")),
                    },
                ],
            )
            self.assertEqual(
                output["seedance_input_contract"]["segments"],
                [
                    {
                        **output["provider_requests"][0],
                        "input_contract": {"contract": "S01"},
                    },
                    {
                        **output["provider_requests"][1],
                        "input_contract": {"contract": "S02"},
                    },
                ],
            )
            self.assertNotIn("invocation_b", output)

    def test_active_invocation_b_rejects_argument_plan_without_frozen_artifact(self):
        plan = {
            "segments": [{
                "segment_id": "S01",
                "start_ms": 0,
                "end_ms": 8000,
                "duration_ms": 8000,
                "cut_ids": ["C01"],
            }]
        }

        class Invocation:
            def invoke_b(self, **_kwargs):
                raise AssertionError("Invocation B must not run without the frozen artifact")

        context = type(
            "Context",
            (),
            {
                "stage": "compile_seedance20_prompt",
                "profile_snapshot": {"profile": "high_fidelity_hybrid_v1"},
                "artifacts": (),
            },
        )()

        with self.assertRaisesRegex(
            Exception,
            "frozen Stage 7 segment plan artifact",
        ):
            HighFidelityStageAdapter(Invocation()).run_stage(
                context=context,
                handler=lambda **_: {
                    "invocation_b_request": {
                        "segment_id": "S01",
                        "segment_plan": plan,
                        "provider_payload": _provider_payload("Prompt for S01"),
                    }
                },
            )

    def test_production_compile_publishes_one_aggregate_input_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "segments": [{
                    "segment_id": "S01",
                    "start_ms": 0,
                    "end_ms": 8000,
                    "duration_ms": 8000,
                    "cut_ids": ["C01"],
                }]
            }
            plan_path = root / "segment_plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            payload = _provider_payload("Prompt for S01")
            published_bytes = {}

            class Invocation:
                def invoke_b(self, *, context, **kwargs):
                    return {
                        "status": "ready",
                        "segment_id": "S01",
                        "segment_plan_sha256": plan_sha,
                        "compiled_prompt": "Prompt for S01",
                        "compiled_prompt_sha256": hashlib.sha256(
                            b"Prompt for S01"
                        ).hexdigest(),
                    }

            class Context:
                stage = "compile_seedance20_prompt"
                allow_local_paths = False
                profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
                artifacts = ({"kind": "segment_plan", "sha256": plan_sha},)

                @property
                def execution_identity(self):
                    return {"profile_digest": "a" * 64}

                @contextmanager
                def materialize_artifact(self, _kind, **_kwargs):
                    yield type("Media", (), {"path": plan_path})()

                def publish_artifact(self, *, kind, stream, expected_sha256, **_kwargs):
                    raw = stream.read()
                    published_bytes[kind] = raw
                    if hashlib.sha256(raw).hexdigest() != expected_sha256:
                        raise AssertionError("published aggregate bytes changed")
                    return {
                        "kind": kind,
                        "sha256": expected_sha256,
                        "uri": f"s3://private/{kind}.json",
                        "metadata": {"artifact_store_verified": True},
                    }

            output = HighFidelityStageAdapter(Invocation()).run_stage(
                context=Context(),
                handler=lambda **_: {
                    "invocation_b_request": {
                        "segment_id": "S01",
                        "provider_payload": payload,
                        "seedance_input_contract": {"contract": "S01"},
                    }
                },
            )

        self.assertIn("seedance_input_contract", published_bytes)
        published = json.loads(published_bytes["seedance_input_contract"].decode("utf-8"))
        self.assertEqual(published["segments"][0]["segment_id"], "S01")
        self.assertEqual(
            output["published_artifacts"][0]["sha256"],
            hashlib.sha256(published_bytes["seedance_input_contract"]).hexdigest(),
        )

    def test_audit_stage_aggregates_two_segment_audits_without_changing_plan_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "segments": [
                    {
                        "segment_id": "S01",
                        "start_ms": 0,
                        "end_ms": 8000,
                        "duration_ms": 8000,
                        "cut_ids": ["C01"],
                    },
                    {
                        "segment_id": "S02",
                        "start_ms": 8000,
                        "end_ms": 16000,
                        "duration_ms": 8000,
                        "cut_ids": ["C02"],
                    },
                ]
            }
            plan_path = root / "segment_plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()

            class Context:
                stage = "audit_seedance_request"
                profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
                artifacts = ({"kind": "segment_plan", "sha256": plan_sha},)

                @contextmanager
                def materialize_artifact(self, _kind, **_kwargs):
                    yield type("Media", (), {"path": plan_path})()

            rows = [
                {
                    "segment_id": segment_id,
                    "segment_plan_sha256": plan_sha,
                    "provider_payload": _provider_payload(f"Prompt for {segment_id}"),
                    "request_sha256": _request_sha(
                        _provider_payload(f"Prompt for {segment_id}")
                    ),
                    "audit": {"auditor": "seedance-20", "status": "passed"},
                }
                for segment_id in ("S01", "S02")
            ]

            output = HighFidelityStageAdapter(object()).run_stage(
                context=Context(),
                handler=lambda **_: {"seedance_request_audits": rows},
            )

        self.assertEqual(
            output["seedance_request_audit"]["segments"],
            [
                {
                    "segment_id": row["segment_id"],
                    "segment_plan_sha256": plan_sha,
                    "provider_payload": row["provider_payload"],
                    "request_sha256": row["request_sha256"],
                    "audit": row["audit"],
                }
                for row in rows
            ],
        )
        self.assertEqual(output["provider_requests"], [
            {
                "segment_id": row["segment_id"],
                "segment_plan_sha256": plan_sha,
                "provider_payload": row["provider_payload"],
                "request_sha256": row["request_sha256"],
            }
            for row in rows
        ])

    def test_stage_adapter_binds_a_and_b_inside_existing_stage_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            plan = {
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
            plan_path = root / "segment_plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()

            class Context:
                stage = "build_script"
                profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
                artifacts = ({"kind": "segment_plan", "sha256": plan_sha},)

                @contextmanager
                def materialize_artifact(self, _kind, **_kwargs):
                    yield type("Media", (), {"path": plan_path})()

            adapter = HighFidelityStageAdapter(SeedanceInvocationAdapter(skill_file=skill))
            context = Context()
            output = adapter.run_stage(
                context=context,
                handler=lambda **_: {
                    "invocation_a_request": {
                        "route": "route_2",
                        "candidate_regions": [_candidate()],
                        "line_contracts": [],
                        "factor_coverage": _factor_coverage(),
                        "input_digests": {"source": "a" * 64},
                    }
                },
            )
            self.assertEqual(output["invocation_a"]["profile"], "seedance20_prescript_v1")
            context.stage = "compile_seedance20_prompt"
            output = adapter.run_stage(
                context=context,
                handler=lambda **_: {
                    "invocation_b_request": {
                        "prescript_artifact": output["invocation_a"],
                        "input_digests": {"source": "a" * 64},
                        "compiled_prompt": "Cut 1, 00.00-08.00s. No dialogue. Open the package.",
                        "final_cut_ids": ["C01"],
                        "segment_plan": plan,
                        "provider_payload": _provider_payload(
                            "Cut 1, 00.00-08.00s. No dialogue. Open the package."
                        ),
                        "seedance_input_contract": {"contract": "S01"},
                    }
                },
            )
            self.assertEqual(output["invocation_b"]["status"], "ready")

    def test_invocation_b_loads_frozen_segment_plan_artifact_when_handler_omits_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            plan = {
                "segments": [{
                    "segment_id": "S01",
                    "start_ms": 0,
                    "end_ms": 8000,
                    "duration_ms": 8000,
                    "cut_ids": ["C01"],
                }]
            }
            plan_path = root / "segment_plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()

            class Context:
                stage = "build_script"
                profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
                artifacts = ({"kind": "segment_plan", "sha256": plan_sha},)

                @contextmanager
                def materialize_artifact(self, kind, **_kwargs):
                    self.assert_kind = kind
                    yield type("Media", (), {"path": plan_path})()

            context = Context()
            adapter = HighFidelityStageAdapter(SeedanceInvocationAdapter(skill_file=skill))
            first = adapter.run_stage(
                context=context,
                handler=lambda **_: {
                    "invocation_a_request": {
                        "route": "route_2",
                        "candidate_regions": [_candidate()],
                        "line_contracts": [],
                        "factor_coverage": _factor_coverage(),
                        "input_digests": {"source": "a" * 64},
                    }
                },
            )
            context.stage = "compile_seedance20_prompt"

            result = adapter.run_stage(
                context=context,
                handler=lambda **_: {
                    "invocation_b_request": {
                        "prescript_artifact": first["invocation_a"],
                        "input_digests": {"source": "a" * 64},
                        "compiled_prompt": "Cut 1, 00.00-08.00s. No dialogue. Open the package.",
                        "final_cut_ids": ["C01"],
                        "provider_payload": _provider_payload(
                            "Cut 1, 00.00-08.00s. No dialogue. Open the package."
                        ),
                        "seedance_input_contract": {"contract": "S01"},
                    }
                },
            )

            self.assertEqual(result["invocation_b"]["status"], "ready")
            self.assertEqual(context.assert_kind, "segment_plan")
            self.assertEqual(result["seedance_input_contract"]["contract"], "S01")
            self.assertEqual(result["seedance_input_contract"]["segment_id"], "S01")
            self.assertEqual(
                result["seedance_input_contract"]["request_sha256"],
                result["provider_request"]["request_sha256"],
            )

    def test_legacy_context_skips_internal_invocation_without_adding_a_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            adapter = HighFidelityStageAdapter(SeedanceInvocationAdapter(skill_file=skill))
            context = type("Context", (), {"stage": "build_script", "profile_snapshot": None})()
            output = adapter.run_stage(
                context=context,
                handler=lambda **_: {
                    "invocation_a_request": {
                        "route": "route_2",
                        "candidate_regions": [_candidate()],
                        "line_contracts": [],
                        "factor_coverage": [],
                        "input_digests": {"source": "a" * 64},
                    }
                },
            )
            self.assertEqual(output["invocation_a"]["status"], "skipped")

    def test_legacy_context_preserves_existing_stage_handler_and_marks_invocation_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            adapter = HighFidelityStageAdapter(SeedanceInvocationAdapter(skill_file=skill))
            context = type("Context", (), {"stage": "build_script", "profile_snapshot": None})()
            called = False

            def handler(**_):
                nonlocal called
                called = True
                return {"invocation_a_request": {}, "legacy_stage_output": "preserved"}

            output = adapter.run_stage(context=context, handler=handler)
            self.assertEqual(output["invocation_a"]["status"], "skipped")
            self.assertTrue(called)
            self.assertEqual(output["legacy_stage_output"], "preserved")


if __name__ == "__main__":
    unittest.main()
