from __future__ import annotations

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


def test_routes_a_confirmed_on_camera_sung_line_to_one_uploaded_lyric_transcription() -> None:
    result = route_uploaded_audio(_timeline())

    assert result["mode"] == "pending_uploaded_lyrics"
    assert result["reason"] == "confirmed_source_music_video_performance"
    assert result["eligible_source_windows"] == [
        {
            "line_id": "A001",
            "speaker_id": "CHARACTER_A",
            "start_ms": 1000,
            "end_ms": 5000,
            "source_line_evidence_sha256": "b" * 64,
        }
    ]
    assert result["max_uploaded_lyric_transcriptions"] == 1


def test_routes_spoken_or_ambiguous_source_audio_to_background_music_without_lyrics() -> None:
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

    assert spoken["mode"] == "background_music_replacement"
    assert spoken["reason"] == "no_confirmed_on_camera_singing"
    assert ambiguous["mode"] == "background_music_replacement"
    assert ambiguous["reason"] == "no_confirmed_on_camera_singing"
