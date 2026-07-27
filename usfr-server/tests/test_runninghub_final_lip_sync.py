from __future__ import annotations

import pytest

from server.runninghub_final_lip_sync import (
    FINAL_LIP_SYNC_WORKFLOW_ID,
    build_final_lip_sync_provider_request,
)


def test_builds_the_one_pinned_runninghub_request_for_language_and_singing_lip_sync() -> None:
    request = build_final_lip_sync_provider_request(
        audio_input="https://media.example/song-window.wav",
        video_input="https://media.example/generated-singer.mp4",
    )

    assert request == {
        "workflow_id": FINAL_LIP_SYNC_WORKFLOW_ID,
        "payload": {
            "nodeInfoList": [
                {
                    "nodeId": "3",
                    "fieldName": "audio",
                    "fieldValue": "https://media.example/song-window.wav",
                    "description": "audio",
                },
                {
                    "nodeId": "6",
                    "fieldName": "video",
                    "fieldValue": "https://media.example/generated-singer.mp4",
                    "description": "video",
                },
            ],
            "instanceType": "default",
            "usePersonalQueue": False,
        },
    }


@pytest.mark.parametrize("audio_input,video_input", [("", "video.mp4"), ("audio.wav", "")])
def test_rejects_a_lip_sync_request_with_a_missing_uploaded_media_input(audio_input: str, video_input: str) -> None:
    with pytest.raises(ValueError, match="RUNNINGHUB_FINAL_LIP_SYNC_MEDIA_REQUIRED"):
        build_final_lip_sync_provider_request(audio_input=audio_input, video_input=video_input)
