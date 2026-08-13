"""Deterministic audio-lane routing shared by prompt, TTS and lip-sync stages.

The semantic analysis happens elsewhere once.  This module only turns the
frozen content type, visibility and task mode into one permitted execution
route, so downstream stages cannot reinterpret the same line differently.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ROUTE_GENERATED_DIALOGUE = "approved_dialogue_in_generation_prompt"
ROUTE_H3_LANGUAGE_EDIT = "h3_language_edit"
ROUTE_H3_MV_EDIT = "h3_mv_song_edit"
ROUTE_VOICEOVER_TTS = "voiceover_tts_no_lipsync"
ROUTE_SONG_LIP_SYNC = "song_lipsync"
ROUTE_BACKGROUND_MUSIC = "background_music_only"
ROUTE_NO_SPEECH = "no_speech_processing"

_MODES = frozenset({"normal_replication", "language_only"})
_ON_CAMERA = frozenset({"on_camera", "visible", "on_screen"})
_VOICEOVER = frozenset({"voiceover", "off_camera", "off_screen", "narration"})


class AudioLaneRouteError(ValueError):
    """Raised before a paid provider request can use the wrong audio lane."""


def route_audio_line(
    *,
    content_type: object,
    visibility: object,
    operation_mode: object,
) -> dict[str, Any]:
    kind = str(content_type or "").strip().casefold()
    visible = str(visibility or "").strip().casefold()
    mode = str(operation_mode or "").strip().casefold()
    if mode not in _MODES:
        raise AudioLaneRouteError("AUDIO_LANE_OPERATION_MODE_INVALID")

    if kind in {"sung", "singing", "song_performance"}:
        if visible not in _ON_CAMERA:
            raise AudioLaneRouteError("SONG_PERFORMER_MUST_BE_ON_CAMERA")
        return {
            "source_kind": "song_performance",
            "replacement_route": ROUTE_H3_MV_EDIT,
            "provider_owner": "h3",
            "tts_required": False,
            "voice_reference_required": False,
            "external_lip_sync": False,
            "workflow_id": None,
        }

    if kind in {"spoken", "speech", "dialogue", "spoken_dialogue", "narration", "voiceover"}:
        if visible in _VOICEOVER:
            return {
                "source_kind": "voiceover",
                "replacement_route": ROUTE_VOICEOVER_TTS,
                "tts_required": True,
                "voice_reference_required": True,
                "external_lip_sync": False,
                "workflow_id": None,
            }
        if visible not in _ON_CAMERA:
            raise AudioLaneRouteError("SPOKEN_VISIBILITY_UNRESOLVED")
        if mode == "language_only":
            return {
                "source_kind": "spoken_dialogue",
                "replacement_route": ROUTE_H3_LANGUAGE_EDIT,
                "provider_owner": "h3",
                "tts_required": False,
                "voice_reference_required": False,
                "external_lip_sync": False,
                "workflow_id": None,
            }
        return {
            "source_kind": "spoken_dialogue",
            "replacement_route": ROUTE_GENERATED_DIALOGUE,
            "provider_owner": "seedance",
            "tts_required": False,
            "voice_reference_required": False,
            "external_lip_sync": False,
            "workflow_id": None,
        }

    if kind in {"music", "instrumental", "background_music", "bgm"}:
        return {
            "source_kind": "background_music",
            "replacement_route": ROUTE_BACKGROUND_MUSIC,
            "tts_required": False,
            "voice_reference_required": False,
            "external_lip_sync": False,
            "workflow_id": None,
        }
    if kind in {"inaudible", "silence", "ambience", "sfx", "ambience_sfx"}:
        return {
            "source_kind": "silence" if kind in {"inaudible", "silence"} else "ambience_sfx",
            "replacement_route": ROUTE_NO_SPEECH,
            "tts_required": False,
            "voice_reference_required": False,
            "external_lip_sync": False,
            "workflow_id": None,
        }
    raise AudioLaneRouteError("AUDIO_LANE_CONTENT_TYPE_INVALID")


def validate_lip_sync_workflow(*, route: Mapping[str, Any], workflow_id: object) -> None:
    replacement = str(route.get("replacement_route") or "")
    actual = str(workflow_id or "").strip()
    if replacement == ROUTE_VOICEOVER_TTS:
        raise AudioLaneRouteError("VOICEOVER_LIP_SYNC_FORBIDDEN")
    del actual
    raise AudioLaneRouteError("EXTERNAL_LIP_SYNC_FORBIDDEN")


__all__ = [
    "AudioLaneRouteError",
    "ROUTE_BACKGROUND_MUSIC",
    "ROUTE_GENERATED_DIALOGUE",
    "ROUTE_H3_LANGUAGE_EDIT",
    "ROUTE_H3_MV_EDIT",
    "ROUTE_NO_SPEECH",
    "ROUTE_SONG_LIP_SYNC",
    "ROUTE_VOICEOVER_TTS",
    "route_audio_line",
    "validate_lip_sync_workflow",
]
