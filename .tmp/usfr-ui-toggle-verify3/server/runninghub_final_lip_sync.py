"""Canonical request builder for the final RunningHub audio-driven lip-sync.

Language localization and verified singing use the same workflow.  Upstream
stages decide whether a region is eligible; this module only freezes the exact
provider request and never performs a media upload or a paid submission.
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
) -> dict[str, Any]:
    """Build the only permitted final lip-sync request shape.

    Node 3 consumes the exact target-language or song-audio window, and node 6
    consumes the matching generated person-video window.  The output MP4 keeps
    the workflow's embedded audio; callers must not remux a different track.
    """

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
