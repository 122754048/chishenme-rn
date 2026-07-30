from __future__ import annotations

import pytest

from server.runninghub_final_lip_sync import (
    FINAL_LIP_SYNC_WORKFLOW_ID,
    build_final_lip_sync_provider_request,
)


def test_builds_the_one_pinned_runninghub_request_for_localized_spoken_lip_sync() -> None:
    request = build_final_lip_sync_provider_request(
        audio_input="https://media.example/localized-speech.wav",
        video_input="https://media.example/generated-speaker.mp4",
        audio_kind="spoken_language_localization",
    )

    assert request == {
        "workflow_id": FINAL_LIP_SYNC_WORKFLOW_ID,
        "payload": {
            "nodeInfoList": [
                {
                    "nodeId": "3",
                    "fieldName": "audio",
                    "fieldValue": "https://media.example/localized-speech.wav",
                    "description": "audio",
                },
                {
                    "nodeId": "6",
                    "fieldName": "video",
                    "fieldValue": "https://media.example/generated-speaker.mp4",
                    "description": "video",
                },
            ],
            "instanceType": "default",
            "usePersonalQueue": False,
        },
    }


def test_final_speech_lip_sync_rejects_song_audio() -> None:
    with pytest.raises(ValueError, match="SPEECH_ONLY"):
        build_final_lip_sync_provider_request(
            audio_input="https://media.example/song.mp3",
            video_input="https://media.example/generated-person.mp4",
            audio_kind="song",
        )


@pytest.mark.parametrize("audio_input,video_input", [("", "video.mp4"), ("audio.wav", "")])
def test_rejects_a_lip_sync_request_with_a_missing_uploaded_media_input(audio_input: str, video_input: str) -> None:
    with pytest.raises(ValueError, match="RUNNINGHUB_FINAL_LIP_SYNC_MEDIA_REQUIRED"):
        build_final_lip_sync_provider_request(
            audio_input=audio_input, video_input=video_input, audio_kind="spoken_language_localization"
        )
