"""Pinned RunningHub AI App request for uploaded-song lip synchronization.

This workflow is intentionally separate from the general final lip-sync
workflow.  Callers must establish song eligibility and segment provenance
before building this paid request.
"""

from __future__ import annotations

import re
from typing import Any


SONG_LIP_SYNC_WORKFLOW_ID = "2082759080288296961"
_TIMECODE = re.compile(r"^(?P<minutes>\d+):(?P<seconds>[0-5]\d)$")


def _media_input(value: object) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError("RUNNINGHUB_SONG_LIP_SYNC_MEDIA_REQUIRED")
    return result


def _song_time(value: object, *, field: str) -> tuple[str, int]:
    text = str(value or "").strip()
    match = _TIMECODE.fullmatch(text)
    if match is None:
        raise ValueError(f"RUNNINGHUB_SONG_LIP_SYNC_{field}_INVALID")
    seconds = int(match.group("minutes")) * 60 + int(match.group("seconds"))
    return text, seconds


def build_song_lip_sync_provider_request(
    *,
    audio_input: object,
    video_input: object,
    song_start: object,
    song_end: object,
) -> dict[str, Any]:
    """Build the only permitted request shape for the supplied song workflow."""

    audio = _media_input(audio_input)
    video = _media_input(video_input)
    start, start_seconds = _song_time(song_start, field="START")
    end, end_seconds = _song_time(song_end, field="END")
    if end_seconds <= start_seconds:
        raise ValueError("RUNNINGHUB_SONG_LIP_SYNC_WINDOW_INVALID")
    return {
        "workflow_id": SONG_LIP_SYNC_WORKFLOW_ID,
        "payload": {
            "nodeInfoList": [
                {"nodeId": "325", "fieldName": "value", "fieldValue": start, "description": "value"},
                {"nodeId": "326", "fieldName": "value", "fieldValue": end, "description": "value"},
                {"nodeId": "228", "fieldName": "video", "fieldValue": video, "description": "video"},
                {"nodeId": "125", "fieldName": "audio", "fieldValue": audio, "description": "audio"},
            ],
            "instanceType": "default",
            "usePersonalQueue": "false",
        },
    }


__all__ = ["SONG_LIP_SYNC_WORKFLOW_ID", "build_song_lip_sync_provider_request"]
