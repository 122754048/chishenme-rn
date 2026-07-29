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


def _analysis_with_source_event_subtitle() -> dict:
    return {
        "source_cuts": [
            {"cut_id": "C01", "start_us": 0, "end_us": 1_000_000},
            {"cut_id": "C02", "start_us": 1_000_000, "end_us": 2_000_000},
            {"cut_id": "C03", "start_us": 2_000_000, "end_us": 3_000_000},
        ],
        "source_events": [
            {
                "event": 2,
                "kind": "subtitle",
                "text": "Uninstall!",
                "start_us": 2_100_000,
                "end_us": 2_700_000,
                "evidence_sha256": "6" * 64,
            }
        ],
        "visible_person_tracks": [],
    }


def _overlay_with_observed_text() -> dict:
    return {
        "contract": "source-ui-overlay-motion",
        "cuts": [
            {
                "cut": 3,
                "start_us": 2_000_000,
                "end_us": 3_000_000,
                "source_overlays": [
                    {
                        "overlay_id": "uninstall_response_01",
                        "kind": "cta_text",
                        "start_us": 2_100_000,
                        "end_us": 2_700_000,
                        "start_rect": [0.1, 0.7, 0.8, 0.1],
                        "end_rect": [0.1, 0.7, 0.8, 0.1],
                        "observed_text": "Uninstall!",
                    }
                ],
            }
        ],
    }


def _visible_text_timeline() -> dict:
    return build_source_content_timeline(
        source_video_sha256=SOURCE_SHA,
        source_dynamics_analysis=_analysis(),
        audio_contract=_audio(),
    )


def _visible_text_lock(**changes: object) -> dict:
    lock = {
        "text_id": "T01",
        "cut_ids": ["C01"],
        "start_ms": 100,
        "end_ms": 750,
        "kind": "subtitle",
        "source_evidence_sha256": "f" * 64,
        "approved_text": "Before breakfast",
        "disposition": "keep",
        "placement": {},
    }
    lock.update(changes)
    return lock


def test_merges_source_event_and_overlay_text_into_cut_bound_visible_text() -> None:
    audio = _audio()
    audio["source_duration_ms"] = 3_000
    timeline = build_source_content_timeline(
        source_video_sha256=SOURCE_SHA,
        source_dynamics_analysis=_analysis_with_source_event_subtitle(),
        audio_contract=audio,
        source_overlay_contract=_overlay_with_observed_text(),
    )

    assert [(row["text_id"], row["text"], row["cut_ids"]) for row in timeline["visible_text"]] == [
        ("event:2", "Uninstall!", ["C03"]),
        ("overlay:uninstall_response_01", "Uninstall!", ["C03"]),
    ]


def test_preserves_zero_and_one_source_event_ids() -> None:
    timeline = build_source_content_timeline(
        source_video_sha256=SOURCE_SHA,
        source_dynamics_analysis={
            "source_cuts": [
                {"cut_id": "C01", "start_us": 0, "end_us": 1_000_000},
                {"cut_id": "C02", "start_us": 1_000_000, "end_us": 2_000_000},
            ],
            "source_events": [
                {
                    "event": 0,
                    "kind": "subtitle",
                    "text": "First subtitle",
                    "start_us": 100_000,
                    "end_us": 900_000,
                    "evidence_sha256": "7" * 64,
                },
                {
                    "event": 1,
                    "kind": "subtitle",
                    "text": "Second subtitle",
                    "start_us": 1_100_000,
                    "end_us": 1_900_000,
                    "evidence_sha256": "8" * 64,
                },
            ],
        },
        audio_contract=_audio(),
    )

    assert [row["text_id"] for row in timeline["visible_text"]] == ["event:0", "event:1"]


def test_visible_text_locks_reject_an_unapproved_or_foreign_source_row() -> None:
    from server.visible_text_contract import VisibleTextContractError, validate_visible_text_locks

    with pytest.raises(VisibleTextContractError, match="source evidence"):
        validate_visible_text_locks(
            [_visible_text_lock(text_id="foreign", source_evidence_sha256="0" * 64)],
            timeline=_visible_text_timeline(),
        )


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


def test_preserves_a_source_song_event_as_an_uploaded_replacement_timing_window() -> None:
    audio = _audio()
    audio["audio_events"] = [
        {
            "event_id": "SONG01",
            "kind": "song",
            "start_ms": 250,
            "end_ms": 1750,
            "evidence_sha256": "1" * 64,
        }
    ]

    timeline = build_source_content_timeline(
        source_video_sha256=SOURCE_SHA,
        source_dynamics_analysis=_analysis(),
        audio_contract=audio,
    )

    assert [event for event in timeline["music_events"] if event["kind"] == "song"] == [
        {
            "event_id": "SONG01",
            "kind": "song",
            "start_ms": 250,
            "end_ms": 1750,
            "cut_ids": ["C01", "C02"],
            "evidence_sha256": "1" * 64,
        }
    ]


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
