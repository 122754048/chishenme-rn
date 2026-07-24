from __future__ import annotations

import pytest

from server.source_content_timeline import (
    SourceContentTimelineError,
    build_source_content_timeline,
)
from server.orchestrator import HIGH_FIDELITY_STAGE_ARTIFACTS


SOURCE_SHA = "a" * 64
AUDIO_SHA = "b" * 64
TRACK_A_SHA = "c" * 64
TRACK_B_SHA = "d" * 64
TRACK_C_SHA = "e" * 64


def _analysis(*, tracks: list[dict] | None = None) -> dict:
    return {
        "source_cuts": [
            {
                "cut_id": "C01",
                "start_us": 0,
                "end_us": 1_000_000,
                "scene": "kitchen",
                "action": "holds product",
                "camera": "medium",
            },
            {
                "cut_id": "C02",
                "start_us": 1_000_000,
                "end_us": 2_000_000,
                "scene": "kitchen",
                "action": "points at product",
                "camera": "close up",
            },
        ],
        "ocr_intervals": [
            {
                "text_id": "T01",
                "kind": "subtitle",
                "text": "Before breakfast",
                "start_ms": 100,
                "end_ms": 750,
                "evidence_sha256": "f" * 64,
                "confidence": 0.98,
            }
        ],
        "visible_person_tracks": tracks or [],
    }


def _audio() -> dict:
    return {
        "source_duration_ms": 2000,
        "source_audio_sha256": AUDIO_SHA,
        "language": "en",
        "segments": [
            {
                "segment_id": "A001",
                "start_ms": 0,
                "end_ms": 850,
                "text": "I use this every day.",
                "kind": "speech",
                "confidence": 0.95,
            },
            {
                "segment_id": "A002",
                "start_ms": 1050,
                "end_ms": 1850,
                "text": "It is so simple.",
                "kind": "speech",
                "confidence": 0.91,
            },
        ],
        "audio_events": [
            {
                "event_id": "M01",
                "kind": "music",
                "start_ms": 0,
                "end_ms": 2000,
                "evidence_sha256": "1" * 64,
            }
        ],
        "meaningful_silence": [
            {
                "event_id": "S01",
                "kind": "silence",
                "start_ms": 850,
                "end_ms": 1050,
                "evidence_sha256": "2" * 64,
            }
        ],
    }


def test_builds_one_reusable_timeline_with_text_audio_music_and_confirmed_speaker() -> None:
    timeline = build_source_content_timeline(
        source_video_sha256=SOURCE_SHA,
        source_dynamics_analysis=_analysis(
            tracks=[
                {
                    "speaker_id": "CHARACTER_A",
                    "role": "on_camera",
                    "visibility": "on_camera",
                    "start_ms": 0,
                    "end_ms": 900,
                    "mouth_activity_confidence": 0.96,
                    "evidence_sha256": TRACK_A_SHA,
                },
                {
                    "speaker_id": "CHARACTER_B",
                    "role": "on_camera",
                    "visibility": "on_camera",
                    "start_ms": 1000,
                    "end_ms": 1900,
                    "mouth_activity_confidence": 0.93,
                    "evidence_sha256": TRACK_B_SHA,
                },
                {
                    "speaker_id": "CHARACTER_C",
                    "role": "on_camera",
                    "visibility": "on_camera",
                    "start_ms": 1000,
                    "end_ms": 1900,
                    "mouth_activity_confidence": 0.92,
                    "evidence_sha256": TRACK_C_SHA,
                },
            ]
        ),
        audio_contract=_audio(),
    )

    assert timeline["contract"] == "source-content-timeline/v1"
    assert timeline["analysis_passes"] == {"dynamics": 1, "asr": 1, "ocr": 1, "speaker_assignment": 1}
    assert timeline["reanalysis_forbidden"] is True
    assert timeline["visible_text"][0]["cut_ids"] == ["C01"]
    assert timeline["audio_lines"][0]["speaker_assignment"] == {
        "status": "CONFIRMED",
        "speaker_id": "CHARACTER_A",
        "role": "on_camera",
        "visibility": "on_camera",
        "confidence": 0.96,
        "evidence_sha256": TRACK_A_SHA,
    }
    pending = timeline["audio_lines"][1]["speaker_assignment"]
    assert pending["status"] == "PENDING_ASSIGNMENT"
    assert pending["candidate_speaker_ids"] == ["CHARACTER_B", "CHARACTER_C"]
    assert {event["event_id"] for event in timeline["music_events"]} == {"M01", "S01"}
    assert len(timeline["contract_sha256"]) == 64


def test_leaves_unproven_source_speaker_pending_for_existing_script_confirmation() -> None:
    timeline = build_source_content_timeline(
        source_video_sha256=SOURCE_SHA,
        source_dynamics_analysis=_analysis(),
        audio_contract=_audio(),
    )

    assignment = timeline["audio_lines"][0]["speaker_assignment"]
    assert assignment["status"] == "PENDING_ASSIGNMENT"
    assert assignment["reason"] == "no_single_visible_lip_sync_candidate"


def test_rejects_visible_speaker_without_bound_evidence() -> None:
    with pytest.raises(SourceContentTimelineError, match="evidence_sha256"):
        build_source_content_timeline(
            source_video_sha256=SOURCE_SHA,
            source_dynamics_analysis=_analysis(
                tracks=[
                    {
                        "speaker_id": "CHARACTER_A",
                        "role": "on_camera",
                        "visibility": "on_camera",
                        "start_ms": 0,
                        "end_ms": 900,
                        "mouth_activity_confidence": 0.96,
                    }
                ]
            ),
            audio_contract=_audio(),
        )


def test_active_dynamics_artifact_contract_requires_the_reusable_source_content_timeline() -> None:
    assert [item["kind"] for item in HIGH_FIDELITY_STAGE_ARTIFACTS["analyze_dynamics"]] == [
        "performance_audio_source_contract",
        "audio_lyrics_beat_contract",
        "source_content_timeline",
    ]
