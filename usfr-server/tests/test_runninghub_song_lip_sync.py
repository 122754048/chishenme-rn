from __future__ import annotations

from server.runninghub_song_lip_sync import (
    SONG_LIP_SYNC_WORKFLOW_ID,
    build_song_lip_sync_provider_request,
)


def test_builds_the_pinned_song_lip_sync_ai_app_request_with_the_exact_song_window() -> None:
    request = build_song_lip_sync_provider_request(
        audio_input="https://media.example/song.mp3",
        video_input="https://media.example/generated-person.mp4",
        song_start="1:30",
        song_end="1:45",
    )

    assert request == {
        "workflow_id": SONG_LIP_SYNC_WORKFLOW_ID,
        "payload": {
            "nodeInfoList": [
                {"nodeId": "325", "fieldName": "value", "fieldValue": "1:30", "description": "value"},
                {"nodeId": "326", "fieldName": "value", "fieldValue": "1:45", "description": "value"},
                {"nodeId": "228", "fieldName": "video", "fieldValue": "https://media.example/generated-person.mp4", "description": "video"},
                {"nodeId": "125", "fieldName": "audio", "fieldValue": "https://media.example/song.mp3", "description": "audio"},
            ],
            "instanceType": "default",
            "usePersonalQueue": "false",
        },
    }
