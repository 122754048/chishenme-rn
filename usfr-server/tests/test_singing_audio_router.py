from __future__ import annotations

import pytest

from server.singing_audio_router import route_uploaded_audio


def _timeline(*, kind: str = "sung", speaker: dict | None = None) -> dict:
    return {
        "contract": "source-content-timeline/v1",
        "contract_sha256": "a" * 64,
        "audio_lines": [
            {
                "line_id": "A001",
                "content_type": kind,
                "text": "the source lyric",
                "start_ms": 1000,
                "end_ms": 5000,
                "confidence": 0.95,
                "speaker_assignment": speaker
                or {
                    "status": "CONFIRMED",
                    "speaker_id": "CHARACTER_A",
                    "visibility": "on_camera",
                    "confidence": 0.92,
                    "evidence_sha256": "b" * 64,
                },
            }
        ],
    }


def _uploaded_audio(*, kind: str, lyrics: list[dict] | None = None) -> dict:
    return {
        "contract": "uploaded-audio-classification/v1",
        "audio_sha256": "d" * 64,
        "kind": kind,
        "confidence": 0.97,
        "classification_evidence_sha256": "e" * 64,
        "lyrics": lyrics if lyrics is not None else [
            {"start_ms": 0, "end_ms": 4000, "text": "Meet me where the morning starts"}
        ],
    }


def test_routes_a_confirmed_on_camera_sung_line_to_source_lyric_confirmation() -> None:
    result = route_uploaded_audio(_timeline())

    assert result["contract"] == "source-audio-performance-route/v2"
    assert result["mode"] == "pending_source_lyrics_confirmation"
    assert result["reason"] == "confirmed_source_music_video_performance"
    assert result["audio_policy"] == "source_audio_keep"
    assert result["lyric_source"] == "source_audio_transcription"
    assert result["requires_user_lyric_confirmation"] is True
    assert result["eligible_source_windows"] == [
        {
            "line_id": "A001",
            "speaker_id": "CHARACTER_A",
            "start_ms": 1000,
            "end_ms": 5000,
            "source_line_evidence_sha256": "b" * 64,
        }
    ]
    assert result["max_source_lyric_transcriptions"] == 1


def test_keeps_source_audio_when_source_has_no_confirmed_on_camera_singer() -> None:
    spoken = route_uploaded_audio(_timeline(kind="spoken"))
    ambiguous = route_uploaded_audio(
        _timeline(
            speaker={
                "status": "PENDING_ASSIGNMENT",
                "reason": "multiple_visible_lip_sync_candidates",
                "candidate_speaker_ids": ["CHARACTER_A", "CHARACTER_B"],
            }
        )
    )

    assert spoken["mode"] == "source_audio_keep"
    assert spoken["reason"] == "no_confirmed_on_camera_singing"
    assert spoken["audio_policy"] == "source_audio_keep"
    assert spoken["requires_user_lyric_confirmation"] is False
    assert ambiguous["mode"] == "source_audio_keep"
    assert ambiguous["reason"] == "no_confirmed_on_camera_singing"
    assert ambiguous["audio_policy"] == "source_audio_keep"
    assert ambiguous["requires_user_lyric_confirmation"] is False


def test_preserves_distinct_singing_roles_for_each_confirmed_line() -> None:
    timeline = _timeline()
    timeline["audio_lines"].append(
        {
            "line_id": "A002",
            "content_type": "sung",
            "text": "the second singer lyric",
            "start_ms": 5000,
            "end_ms": 8000,
            "confidence": 0.97,
            "speaker_assignment": {
                "status": "CONFIRMED",
                "speaker_id": "CHARACTER_B",
                "visibility": "on_camera",
                "confidence": 0.94,
                "evidence_sha256": "c" * 64,
            },
        }
    )

    result = route_uploaded_audio(timeline)

    assert result["performer_assignments"] == {
        "A001": "CHARACTER_A",
        "A002": "CHARACTER_B",
    }


def test_freezes_original_music_cut_in_and_cut_out_windows_for_any_uploaded_audio() -> None:
    timeline = _timeline(kind="instrumental")
    timeline["music_events"] = [
        {"event_id": "M01", "kind": "music", "start_ms": 900, "end_ms": 3600},
        {"event_id": "M02", "kind": "music", "start_ms": 5200, "end_ms": 7400},
    ]

    result = route_uploaded_audio(timeline)

    assert result["source_music_windows"] == [
        {"event_id": "M01", "start_ms": 900, "end_ms": 3600},
        {"event_id": "M02", "start_ms": 5200, "end_ms": 7400},
    ]
    assert result["replacement_timing_policy"] == "source_music_cut_in_out_exact"


def test_rejects_ambiguous_or_invalid_source_music_windows() -> None:
    timeline = _timeline(kind="instrumental")
    timeline["music_events"] = [
        {"event_id": "M01", "kind": "music", "start_ms": 900, "end_ms": 3600},
        {"event_id": "M02", "kind": "music", "start_ms": 3200, "end_ms": 7400},
    ]

    with pytest.raises(ValueError, match="source music windows overlap"):
        route_uploaded_audio(timeline)


def test_treats_bgm_and_instrumental_events_as_source_music_windows() -> None:
    timeline = _timeline(kind="instrumental")
    timeline["music_events"] = [
        {"event_id": "M01", "kind": "bgm", "start_ms": 900, "end_ms": 3600},
        {"event_id": "M02", "kind": "instrumental", "start_ms": 5200, "end_ms": 7400},
    ]

    result = route_uploaded_audio(timeline)

    assert result["source_music_windows"] == [
        {"event_id": "M01", "start_ms": 900, "end_ms": 3600},
        {"event_id": "M02", "start_ms": 5200, "end_ms": 7400},
    ]


def test_routes_an_uploaded_non_song_to_window_bound_replacement_without_lip_sync() -> None:
    result = route_uploaded_audio(
        _timeline(),
        uploaded_audio_contract=_uploaded_audio(kind="non_song", lyrics=[]),
        uploaded_audio_sha256="d" * 64,
    )

    assert result["mode"] == "uploaded_non_song_replace"
    assert result["audio_policy"] == "uploaded_audio_replace"
    assert result["requires_user_lyric_confirmation"] is False
    assert result["eligible_source_windows"] == []
    assert result["performer_assignments"] == {}


def test_routes_an_uploaded_song_to_lyrics_and_performer_confirmation() -> None:
    result = route_uploaded_audio(
        _timeline(),
        uploaded_audio_contract=_uploaded_audio(kind="song"),
        uploaded_audio_sha256="d" * 64,
    )

    assert result["mode"] == "pending_uploaded_song_lyrics_confirmation"
    assert result["audio_policy"] == "uploaded_audio_replace"
    assert result["lyric_source"] == "uploaded_audio_transcription"
    assert result["requires_user_lyric_confirmation"] is True
    assert result["uploaded_lyrics"] == [
        {"start_ms": 0, "end_ms": 4000, "text": "Meet me where the morning starts"}
    ]
    assert result["performer_assignments"] == {"A001": "CHARACTER_A"}
