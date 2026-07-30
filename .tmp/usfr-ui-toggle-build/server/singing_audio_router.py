"""Constant-cost source-audio route selection for music performances.

The router consumes the existing frozen source-content timeline. It never
decodes source media, calls a model, or assigns a speaker itself. Source audio
is always retained by default; confirmed on-camera singing instead opens a
lyric-confirmation gate so the approved exact text can drive lip-sync.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .uploaded_audio_contract import validate_uploaded_audio_contract


_MIN_CONFIDENCE = 0.80


def uploaded_audio_tools(classification: Mapping[str, Any]) -> frozenset[str]:
    kind = str(classification.get("kind") or "").strip().casefold()
    if kind == "song":
        return frozenset({"lyrics", "singing_contract", "seedance_audio", "singing_lip_sync"})
    if kind == "non_song":
        return frozenset({"music_window_replace"})
    raise ValueError("uploaded audio must be frozen as song or non_song before script drafting")


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


def _source_music_windows(source_content_timeline: Mapping[str, Any]) -> list[dict[str, int | str]]:
    """Freeze validated source music event windows without normalizing them."""

    raw_events = source_content_timeline.get("music_events")
    if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes, bytearray)):
        return []

    windows: list[dict[str, int | str]] = []
    previous_end_ms = -1
    event_ids: set[str] = set()
    for event in raw_events:
        if not isinstance(event, Mapping) or str(event.get("kind") or "").strip().casefold() not in {"music", "bgm", "instrumental", "song"}:
            continue
        event_id = str(event.get("event_id") or "").strip()
        start_ms, end_ms = event.get("start_ms"), event.get("end_ms")
        if (
            not event_id
            or event_id in event_ids
            or not isinstance(start_ms, int)
            or isinstance(start_ms, bool)
            or not isinstance(end_ms, int)
            or isinstance(end_ms, bool)
            or start_ms < 0
            or end_ms <= start_ms
        ):
            raise ValueError("source music window is invalid")
        if start_ms < previous_end_ms:
            raise ValueError("source music windows overlap or are out of order")
        windows.append({"event_id": event_id, "start_ms": start_ms, "end_ms": end_ms})
        event_ids.add(event_id)
        previous_end_ms = end_ms
    return windows


def route_uploaded_audio(
    source_content_timeline: Mapping[str, Any],
    *,
    uploaded_audio_contract: Mapping[str, Any] | None = None,
    uploaded_audio_sha256: str | None = None,
) -> dict[str, object]:
    """Route source audio without treating a user upload as a song requirement.

    The public function name is retained for compatibility. A confirmed sung
    line is sourced from the frozen source-audio transcript and must be shown
    to the user for lyric confirmation before prompt compilation. Ambiguous or
    non-singing source audio keeps its original mix and never creates a guessed
    singer or lyric.
    """

    source_music_windows = _source_music_windows(source_content_timeline)
    replacement_timing = {
        "source_music_windows": source_music_windows,
        "replacement_timing_policy": "source_music_cut_in_out_exact",
    }
    raw_lines = source_content_timeline.get("audio_lines") if isinstance(source_content_timeline, Mapping) else None
    lines = raw_lines if isinstance(raw_lines, Sequence) and not isinstance(raw_lines, (str, bytes, bytearray)) else ()
    eligible = [window for line in lines if isinstance(line, Mapping) for window in [_eligible_window(line)] if window]
    if uploaded_audio_contract is not None:
        uploaded = validate_uploaded_audio_contract(
            uploaded_audio_contract,
            audio_sha256=str(uploaded_audio_sha256 or ""),
        )
        if uploaded["kind"] == "non_song":
            return {
                "contract": "source-audio-performance-route/v2",
                "mode": "uploaded_non_song_replace",
                "reason": "confirmed_uploaded_non_song_replacement",
                "audio_policy": "uploaded_audio_replace",
                "lyric_source": "not_required",
                "requires_user_lyric_confirmation": False,
                "eligible_source_windows": [],
                "performer_assignments": {},
                "uploaded_audio_classification": uploaded,
                **replacement_timing,
            }
        if not eligible:
            return {
                "contract": "source-audio-performance-route/v2",
                "mode": "blocked_uploaded_song_performer_assignment",
                "reason": "uploaded_song_requires_confirmed_on_camera_performer",
                "audio_policy": "uploaded_audio_replace",
                "lyric_source": "uploaded_audio_transcription",
                "requires_user_lyric_confirmation": True,
                "requires_confirmed_performer_assignment": True,
                "eligible_source_windows": [],
                "performer_assignments": {},
                "uploaded_lyrics": uploaded["lyrics"],
                "uploaded_audio_classification": uploaded,
                **replacement_timing,
            }
        return {
            "contract": "source-audio-performance-route/v2",
            "mode": "pending_uploaded_song_lyrics_confirmation",
            "reason": "confirmed_uploaded_song_requires_lyrics_and_performer_confirmation",
            "audio_policy": "uploaded_audio_replace",
            "lyric_source": "uploaded_audio_transcription",
            "requires_user_lyric_confirmation": True,
            "requires_confirmed_performer_assignment": True,
            "eligible_source_windows": eligible,
            "performer_assignments": {
                str(window["line_id"]): str(window["speaker_id"])
                for window in eligible
            },
            "uploaded_lyrics": uploaded["lyrics"],
            "uploaded_audio_classification": uploaded,
            **replacement_timing,
        }
    if eligible:
        return {
            "contract": "source-audio-performance-route/v2",
            "mode": "pending_source_lyrics_confirmation",
            "reason": "confirmed_source_music_video_performance",
            "audio_policy": "source_audio_keep",
            "lyric_source": "source_audio_transcription",
            "requires_user_lyric_confirmation": True,
            "eligible_source_windows": eligible,
            "performer_assignments": {
                str(window["line_id"]): str(window["speaker_id"])
                for window in eligible
            },
            "max_source_lyric_transcriptions": 1,
            **replacement_timing,
        }
    return {
        "contract": "source-audio-performance-route/v2",
        "mode": "source_audio_keep",
        "reason": "no_confirmed_on_camera_singing",
        "audio_policy": "source_audio_keep",
        "lyric_source": "not_required",
        "requires_user_lyric_confirmation": False,
        "eligible_source_windows": [],
        "performer_assignments": {},
        "max_source_lyric_transcriptions": 0,
        **replacement_timing,
    }


__all__ = ["route_uploaded_audio", "uploaded_audio_tools"]
