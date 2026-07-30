"""Canonical request builder for final spoken-language lip-sync only.

This workflow is reserved for a localized spoken replacement after language
change.  Songs must use ``runninghub_song_lip_sync`` and are rejected here.
"""

from __future__ import annotations

from typing import Any


FINAL_LIP_SYNC_WORKFLOW_ID = "2080140197518823426"


def _media_input(value: object) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError("RUNNINGHUB_FINAL_LIP_SYNC_MEDIA_REQUIRED")
    return result


def build_final_lip_sync_provider_request(
    *,
    audio_input: object,
    video_input: object,
    audio_kind: object,
) -> dict[str, Any]:
    """Build the only permitted final spoken-language lip-sync request shape.

    Node 3 consumes the exact localized spoken-audio window, and node 6
    consumes the matching generated person-video window.  The output MP4 keeps
    the workflow's embedded speech; callers must not remux a different track.
    """

    if str(audio_kind or "").strip() != "spoken_language_localization":
        raise ValueError("RUNNINGHUB_FINAL_LIP_SYNC_SPEECH_ONLY")
    audio = _media_input(audio_input)
    video = _media_input(video_input)
    return {
        "workflow_id": FINAL_LIP_SYNC_WORKFLOW_ID,
        "payload": {
            "nodeInfoList": [
                {
                    "nodeId": "3",
                    "fieldName": "audio",
                    "fieldValue": audio,
                    "description": "audio",
                },
                {
                    "nodeId": "6",
                    "fieldName": "video",
                    "fieldValue": video,
                    "description": "video",
                },
            ],
            "instanceType": "default",
            "usePersonalQueue": False,
        },
    }


__all__ = ["FINAL_LIP_SYNC_WORKFLOW_ID", "build_final_lip_sync_provider_request"]
