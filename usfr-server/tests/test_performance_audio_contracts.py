from __future__ import annotations

import unittest
from unittest.mock import patch

from server.errors import ReplicationError
from server.capability_ports import CapabilityStagePort, validate_provider_callable_binding
from server.orchestrator import HIGH_FIDELITY_STAGE_ARTIFACTS, build_semantic_stage_mapping
from server.performance_audio_contracts import (
    build_audio_evidence_contracts,
    build_source_audio_contracts,
)


SOURCE_AUDIO_SHA = "a" * 64


def _regions():
    return (
        {
            "region_id": "G01",
            "region_type": "generated",
            "source_start_ms": 0,
            "source_end_ms": 4_000,
            "segment_id": "S01",
        },
        {
            "region_id": "U01",
            "region_type": "opaque_ui_demo",
            "source_start_ms": 4_000,
            "source_end_ms": 8_400,
        },
        {
            "region_id": "G02",
            "region_type": "generated",
            "source_start_ms": 8_400,
            "source_end_ms": 14_000,
            "segment_id": "S02",
        },
        {
            "region_id": "E01",
            "region_type": "tail_card",
            "source_start_ms": 14_000,
            "source_end_ms": 16_033,
        },
    )


def _audio_contract(*, confidence: float = 0.99):
    return {
        "audio_contract": {
            "audio_language": "en",
            "segments": [
                {
                    "segment_id": "A01",
                    "start_ms": 0,
                    "end_ms": 4_000,
                    "text": "I will meet you by the lake",
                    "confidence": confidence,
                    "kind": "singing",
                    "beat_anchors_ms": [200, 900, 1_800],
                    "emotion": "hopeful",
                },
                {
                    "segment_id": "A02",
                    "start_ms": 8_400,
                    "end_ms": 14_000,
                    "text": "and carry on the song",
                    "confidence": confidence,
                    "kind": "singing",
                    "beat_anchors_ms": [8_600, 9_300, 10_100],
                    "emotion": "release",
                },
            ],
        }
    }


def _lines():
    return (
        {
            "line_id": "A01",
            "cut_id": "C01",
            "source_content_timeline_sha256": "a" * 64,
            "content_type": "sung",
            "speaker_assignment": {
                "status": "CONFIRMED",
                "speaker_id": "CHARACTER_A",
                "role": "creator",
                "visibility": "on_camera",
                "confidence": 0.94,
                "evidence_sha256": "b" * 64,
            },
            "source_time": {"start_ms": 0, "end_ms": 4_000},
            "segment_time": {"start_ms": 0, "end_ms": 4_000},
            "performance_mode": "singing",
            "exact_sung_text": "I will meet you by the lake",
            "lyric_status": "verified",
            "beat_anchors_ms": [200, 900, 1_800],
            "lip_sync": {
                "face_visibility": "front visible",
                "articulation": "clear lyric mouth shapes",
                "end_state": "mouth closes at final syllable",
            },
            "action": {
                "start": "hands down",
                "beat_action": "raise right palm on second beat",
                "end": "hands down",
            },
            "expression": {
                "start": "restrained smile",
                "peak": "bright open expression",
                "end": "steady direct gaze",
            },
            "emotion": "hopeful",
            "end_pose": "front-facing stable pose",
            "criticality": "H",
        },
        {
            "line_id": "A02",
            "cut_id": "C02",
            "source_content_timeline_sha256": "a" * 64,
            "content_type": "sung",
            "speaker_assignment": {
                "status": "CONFIRMED",
                "speaker_id": "CHARACTER_A",
                "role": "creator",
                "visibility": "on_camera",
                "confidence": 0.94,
                "evidence_sha256": "b" * 64,
            },
            "source_time": {"start_ms": 8_400, "end_ms": 14_000},
            "segment_time": {"start_ms": 0, "end_ms": 5_600},
            "performance_mode": "singing",
            "exact_sung_text": "and carry on the song",
            "lyric_status": "verified",
            "beat_anchors_ms": [200, 900, 1_700],
            "lip_sync": {
                "face_visibility": "front visible",
                "articulation": "clear lyric mouth shapes",
                "end_state": "mouth closes at final syllable",
            },
            "action": {
                "start": "right hand near chest",
                "beat_action": "open palm outward",
                "end": "hand relaxed at side",
            },
            "expression": {
                "start": "restrained smile",
                "peak": "bright open expression",
                "end": "steady direct gaze",
            },
            "emotion": "release",
            "end_pose": "front-facing stable pose",
            "criticality": "H",
        },
    )


def _approved_lines():
    rows = []
    for performance in _lines():
        text = performance["exact_sung_text"]
        rows.append(
            {
                "line_id": performance["line_id"],
                "cut_id": performance["cut_id"],
                "source_content_timeline_sha256": "a" * 64,
                "content_type": "sung",
                "speaker_assignment": dict(performance["speaker_assignment"]),
                "speaker": {
                    "id": "CHARACTER_A",
                    "role": "creator",
                    "visibility": "on_camera",
                    "voice_policy": "generic rights-cleared target voice",
                },
                "language": {"bcp47": "en", "script": "Latn"},
                "time": {
                    "time_base": "output_global_ms",
                    "start_ms": performance["source_time"]["start_ms"],
                    "end_ms": performance["source_time"]["end_ms"],
                    "duration_ms": performance["source_time"]["end_ms"] - performance["source_time"]["start_ms"],
                    "duration_is_derived": True,
                    "cut_ids": [performance["cut_id"]],
                    "cross_cut_reason": None,
                    "planned_safe_margin_ms": 0,
                },
                "text": {"exact": text, "normalized": text.lower(), "pronunciation_notes": []},
                "delivery": {"tone": "natural", "pace": "steady", "emphasis": [], "volume": "natural", "breath": "controlled", "mic_distance": "close", "accent_or_locale": "en"},
                "lip_sync": {"priority": "high", "face_visibility": "front visible", "occlusion": "none", "head_motion_limit": "small", "articulation": "clear lyric mouth shapes", "allowed_tolerance_ms": 100, "speaker_face_ref": "CHARACTER_A"},
                "proof_events": [],
                "foley_events": [],
                "silence_windows": [],
                "music_policy": {"mode": "none", "windows": []},
                "claim_ids": [],
                "qc_contract": {"asr_profile": "en", "speaker_check": "role", "language_check": "en", "line_tolerance_ms": 100, "proof_sync_tolerance_ms": 100, "foley_sync_tolerance_ms": 100, "hard_fail_flags": ["word_change"]},
                "criticality": performance["criticality"],
            }
        )
    return tuple(rows)


class SourceAudioReplicateContractsTests(unittest.TestCase):
    def test_rejects_performance_line_with_altered_approved_speaker_before_invocation(self):
        altered = dict(_lines()[0])
        altered["speaker_assignment"] = {
            **altered["speaker_assignment"],
            "speaker_id": "CHARACTER_B",
        }

        with self.assertRaisesRegex(ReplicationError, "PERFORMANCE_LINE_BINDING_REQUIRED"):
            build_source_audio_contracts(
                source_audio_sha256=SOURCE_AUDIO_SHA,
                source_duration_ms=16_033,
                audio_contract=_audio_contract(),
                timeline_regions=_regions(),
                performance_lines=(altered, _lines()[1]),
                line_contracts=_approved_lines(),
                source_content_timeline_sha256="a" * 64,
            )

    def test_rejects_pending_speaker_assignment_before_invocation(self):
        pending = dict(_lines()[0])
        pending["speaker_assignment"] = {
            "status": "PENDING_ASSIGNMENT",
            "reason": "multiple_visible_lip_sync_candidates",
            "candidate_speaker_ids": ["CHARACTER_A", "CHARACTER_B"],
        }

        with self.assertRaisesRegex(ReplicationError, "PENDING_ASSIGNMENT"):
            build_source_audio_contracts(
                source_audio_sha256=SOURCE_AUDIO_SHA,
                source_duration_ms=16_033,
                audio_contract=_audio_contract(),
                timeline_regions=_regions(),
                performance_lines=(pending, _lines()[1]),
                line_contracts=_approved_lines(),
                source_content_timeline_sha256="a" * 64,
            )

    def test_rejects_unconfirmed_lyric_before_invocation(self):
        unconfirmed = dict(_lines()[0])
        unconfirmed["lyric_status"] = "PENDING_CONFIRMATION"

        with self.assertRaisesRegex(ReplicationError, "PERFORMANCE_LINE_CONTRACT_REQUIRED"):
            build_source_audio_contracts(
                source_audio_sha256=SOURCE_AUDIO_SHA,
                source_duration_ms=16_033,
                audio_contract=_audio_contract(),
                timeline_regions=_regions(),
                performance_lines=(unconfirmed, _lines()[1]),
                line_contracts=_approved_lines(),
                source_content_timeline_sha256="a" * 64,
            )

    def test_rejects_performance_lines_from_different_source_content_timelines(self):
        changed_timeline = dict(_lines()[1])
        changed_timeline["source_content_timeline_sha256"] = "c" * 64

        with self.assertRaisesRegex(ReplicationError, "source-content timeline"):
            build_source_audio_contracts(
                source_audio_sha256=SOURCE_AUDIO_SHA,
                source_duration_ms=16_033,
                audio_contract=_audio_contract(),
                timeline_regions=_regions(),
                performance_lines=(_lines()[0], changed_timeline),
                line_contracts=_approved_lines(),
                source_content_timeline_sha256="a" * 64,
            )

    def test_provider_callable_binding_keeps_validated_bound_method(self):
        class Provider:
            def create_video(self):
                return None

        provider = Provider()
        candidate = provider.create_video
        with patch(
            "server.capability_ports.validate_runtime_capability_ports",
            return_value={"provider_adapter": provider},
        ):
            self.assertIs(
                validate_provider_callable_binding(
                    {}, "create_video", candidate,
                    manifest={}, production=True, profile_active=True,
                ),
                candidate,
            )

    def test_existing_dynamics_stage_publishes_source_audio_sidecars(self):
        class Dynamics:
            def analyze(self, **_kwargs):
                return {"status": "ready", "source_video_sha256": "a" * 64, "source_dynamics_analysis": {"contract": "reference-video-dynamics", "source_cuts": [{"cut_id": "C01", "start_us": 0, "end_us": 16_033_000}]}}

        class Asr:
            def transcribe(self, **_kwargs):
                return {"status": "ready", "audio_contract": {"source_audio_sha256": SOURCE_AUDIO_SHA, "source_duration_ms": 16_033, "silence_windows": [], **_audio_contract()["audio_contract"]}}

        class Context:
            allow_local_paths = True

            def __init__(self):
                self.published = []

            def publish_bytes(self, **kwargs):
                self.published.append(kwargs)
                return {"kind": kwargs["kind"], "sha256": kwargs["expected_sha256"]}

        port = object.__new__(CapabilityStagePort)
        port.stage = "analyze_dynamics"
        port.capability_names = ("dynamics_analyzer", "asr_transcriber")
        port.profile_active = False
        port._ports = {"dynamics_analyzer": Dynamics(), "asr_transcriber": Asr()}
        context = Context()

        result = port.run(context=context, input_artifacts=[])

        self.assertEqual(result["source_audio_mode"], "source_audio_replicate_v1")
        self.assertEqual(
            [item["kind"] for item in context.published],
            ["performance_audio_source_contract", "audio_lyrics_beat_contract", "source_content_timeline"],
        )
        self.assertEqual(result["source_content_timeline"]["analysis_passes"]["asr"], 1)

    def test_stage_three_contracts_require_extracted_source_audio_digest(self):
        result = build_audio_evidence_contracts(
            source_audio_sha256=SOURCE_AUDIO_SHA,
            source_duration_ms=16_033,
            audio_contract=_audio_contract(),
        )
        self.assertEqual(
            result["performance_audio_source_contract"]["source_audio_sha256"],
            SOURCE_AUDIO_SHA,
        )
        self.assertEqual(
            result["audio_lyrics_beat_contract"]["segments"][1]["text"],
            "and carry on the song",
        )

    def test_registers_contracts_as_internal_existing_stage_artifacts(self):
        self.assertEqual(
            [item["kind"] for item in HIGH_FIDELITY_STAGE_ARTIFACTS["analyze_dynamics"]],
            ["performance_audio_source_contract", "audio_lyrics_beat_contract", "source_content_timeline"],
        )
        self.assertIn(
            "performance_line_contract",
            [item["kind"] for item in HIGH_FIDELITY_STAGE_ARTIFACTS["build_script"]],
        )
        self.assertIn(
            "performance_timeline_contract",
            [item["kind"] for item in HIGH_FIDELITY_STAGE_ARTIFACTS["generate_storyboards"]],
        )
        self.assertIn(
            "audio_splice_policy",
            [item["kind"] for item in HIGH_FIDELITY_STAGE_ARTIFACTS["splice_timeline"]],
        )
        mapped = build_semantic_stage_mapping(
            [{"name": "analyze_dynamics", "internal_steps": ["source_audio_authorization", "audio_lyrics_beat"]}]
        )
        self.assertEqual(mapped["semantic_stage_count"], 12)
        self.assertEqual(mapped["unknown_operational_stages"], [])

    def test_builds_authorized_global_windows_and_opaque_only_policy(self):
        result = build_source_audio_contracts(
            source_audio_sha256=SOURCE_AUDIO_SHA,
            source_duration_ms=16_033,
            audio_contract=_audio_contract(),
            timeline_regions=_regions(),
            performance_lines=_lines(),
            line_contracts=_approved_lines(),
            source_content_timeline_sha256="a" * 64,
        )

        source = result["performance_audio_source_contract"]
        self.assertEqual(source["mode"], "source_audio_replicate_v1")
        self.assertEqual(source["authorization"], {"status": "user_default_authorized", "scope": "current_run_only"})
        self.assertEqual(source["source_audio_sha256"], SOURCE_AUDIO_SHA)
        self.assertEqual(source["provider_reference_audio"], "forbidden")

        timeline = result["performance_timeline_contract"]
        self.assertEqual(timeline["performance_windows"][1]["region_id"], "G02")
        self.assertEqual(timeline["performance_windows"][1]["source_start_ms"], 8_400)
        self.assertEqual(timeline["opaque_windows"], [
            {"region_id": "U01", "source_start_ms": 4_000, "source_end_ms": 8_400, "audio_mode": "opaque_audio_keep"},
            {"region_id": "E01", "source_start_ms": 14_000, "source_end_ms": 16_033, "audio_mode": "opaque_audio_keep"},
        ])
        self.assertEqual(result["audio_splice_policy"]["forbidden_operations"], ["atempo", "loop", "stretch", "freeze", "black_padding", "audio_padding", "unsupported_mixing"])

    def test_rejects_missing_required_performance_field_before_invocation(self):
        incomplete = dict(_lines()[0])
        incomplete.pop("end_pose")
        with self.assertRaisesRegex(ReplicationError, "PERFORMANCE_LINE_CONTRACT_REQUIRED"):
            build_source_audio_contracts(
                source_audio_sha256=SOURCE_AUDIO_SHA,
                source_duration_ms=16_033,
                audio_contract=_audio_contract(),
                timeline_regions=_regions(),
                performance_lines=(incomplete, _lines()[1]),
                line_contracts=_approved_lines(),
                source_content_timeline_sha256="a" * 64,
            )

    def test_rejects_unresolved_low_confidence_critical_lyric(self):
        with self.assertRaisesRegex(ReplicationError, "AUDIO_LYRIC_EVIDENCE_REQUIRED"):
            build_source_audio_contracts(
                source_audio_sha256=SOURCE_AUDIO_SHA,
                source_duration_ms=16_033,
                audio_contract=_audio_contract(confidence=0.31),
                timeline_regions=_regions(),
                performance_lines=_lines(),
                line_contracts=_approved_lines(),
                source_content_timeline_sha256="a" * 64,
            )

    def test_rejects_verified_lyric_that_differs_from_source_audio_evidence(self):
        forged = dict(_lines()[1])
        forged["exact_sung_text"] = "invented lyric"
        with self.assertRaisesRegex(ReplicationError, "AUDIO_LYRIC_EVIDENCE_REQUIRED"):
            build_source_audio_contracts(
                source_audio_sha256=SOURCE_AUDIO_SHA,
                source_duration_ms=16_033,
                audio_contract=_audio_contract(),
                timeline_regions=_regions(),
                performance_lines=(_lines()[0], forged),
                line_contracts=_approved_lines(),
                source_content_timeline_sha256="a" * 64,
            )


if __name__ == "__main__":
    unittest.main()
