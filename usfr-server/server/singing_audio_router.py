"""Constant-cost route selection for an uploaded reference song.

The router consumes the existing frozen source-content timeline.  It never
decodes source media, calls a model, or assigns a speaker itself: uncertainty
therefore becomes a BGM replacement instead of an expensive or unsafe guess.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_MIN_CONFIDENCE = 0.80


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if 0.0 <= result <= 1.0 else None


def _eligible_window(line: Mapping[str, Any]) -> dict[str, object] | None:
    if str(line.get("content_type") or "").strip().casefold() != "sung":
        return None
    speaker = line.get("speaker_assignment")
    if not isinstance(speaker, Mapping):
        return None
    line_confidence = _number(line.get("confidence"))
    speaker_confidence = _number(speaker.get("confidence"))
    start_ms, end_ms = line.get("start_ms"), line.get("end_ms")
    if (
        speaker.get("status") != "CONFIRMED"
        or speaker.get("visibility") != "on_camera"
        or line_confidence is None
        or line_confidence < _MIN_CONFIDENCE
        or speaker_confidence is None
        or speaker_confidence < _MIN_CONFIDENCE
        or not isinstance(start_ms, int)
        or isinstance(start_ms, bool)
        or not isinstance(end_ms, int)
        or isinstance(end_ms, bool)
        or end_ms <= start_ms
    ):
        return None
    line_id = str(line.get("line_id") or "").strip()
    speaker_id = str(speaker.get("speaker_id") or "").strip()
    evidence_sha256 = str(speaker.get("evidence_sha256") or "").strip()
    if not line_id or not speaker_id or len(evidence_sha256) != 64:
        return None
    return {
        "line_id": line_id,
        "speaker_id": speaker_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "source_line_evidence_sha256": evidence_sha256,
    }


def route_uploaded_audio(source_content_timeline: Mapping[str, Any]) -> dict[str, object]:
    """Select the only admissible audio route from already-frozen evidence.

    ``pending_uploaded_lyrics`` permits one short uploaded-audio transcription
    later in the same job.  All non-MV or uncertain inputs retain the fast BGM
    path and create no lyric or lip-sync work.
    """

    raw_lines = source_content_timeline.get("audio_lines") if isinstance(source_content_timeline, Mapping) else None
    lines = raw_lines if isinstance(raw_lines, Sequence) and not isinstance(raw_lines, (str, bytes, bytearray)) else ()
    eligible = [window for line in lines if isinstance(line, Mapping) for window in [_eligible_window(line)] if window]
    if eligible:
        return {
            "contract": "uploaded-audio-route/v1",
            "mode": "pending_uploaded_lyrics",
            "reason": "confirmed_source_music_video_performance",
            "eligible_source_windows": eligible,
            "max_uploaded_lyric_transcriptions": 1,
        }
    return {
        "contract": "uploaded-audio-route/v1",
        "mode": "background_music_replacement",
        "reason": "no_confirmed_on_camera_singing",
        "eligible_source_windows": [],
        "max_uploaded_lyric_transcriptions": 0,
    }


__all__ = ["route_uploaded_audio"]
