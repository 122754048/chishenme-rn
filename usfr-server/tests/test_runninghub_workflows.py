from __future__ import annotations

from pathlib import Path

import pytest


def test_speech_whisper_uploads_the_source_video_to_the_ai_app_video_node(tmp_path: Path) -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient

    requests: list[dict[str, object]] = []

    def request_json(**kwargs):
        requests.append(kwargs)
        if "/run/ai-app/" in str(kwargs["url"]):
            return {"taskId": "speech-task", "status": "RUNNING"}
        return {
            "taskId": "speech-task",
            "status": "SUCCESS",
            "results": [{
                "outputType": "txt",
                "text": "00:00:00,000 --> 00:00:01,250\nHello world",
            }],
        }

    video = tmp_path / "source.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42source")
    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        request_json=request_json,
        upload_file=lambda path: "https://media.example.test/current-source.mp4",
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
    )

    result = client.run_speech_whisper(
        video_path=video,
        workflow_id="2080170949061038081",
        input_node_id="1",
        input_field="video",
    )

    assert result["segments"] == [{"start": 0.0, "end": 1.25, "text": "Hello world"}]
    assert result["uploaded_video_url"] == "https://media.example.test/current-source.mp4"
    assert requests[0]["url"] == "https://runninghub.example.test/openapi/v2/run/ai-app/2080170949061038081"
    assert requests[0]["payload"]["nodeInfoList"] == [{
        "nodeId": "1",
        "fieldName": "video",
        "fieldValue": "https://media.example.test/current-source.mp4",
    }]


def test_whisper_workflow_rejects_a_success_response_without_a_txt_result(tmp_path: Path) -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient, RunningHubWorkflowError

    video = tmp_path / "source.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42source")
    replies = iter((
        {"taskId": "whisper-task", "status": "RUNNING"},
        {"taskId": "whisper-task", "status": "SUCCESS", "results": [{"outputType": "json", "url": "https://example.test/x"}]},
    ))
    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        request_json=lambda **_kwargs: next(replies),
        upload_file=lambda _path: "https://media.example.test/current-source.mp4",
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
    )

    with pytest.raises(RunningHubWorkflowError, match="TXT"):
        client.run_speech_whisper(video_path=video, workflow_id="workflow-1", input_node_id="1", input_field="video")


def test_whisper_workflow_downloads_txt_when_result_text_is_returned_as_a_url(tmp_path: Path) -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient

    video = tmp_path / "source.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42source")
    replies = iter((
        {"taskId": "whisper-task", "status": "RUNNING"},
        {"taskId": "whisper-task", "status": "SUCCESS", "results": [{
            "outputType": "txt", "text": None, "url": "https://media.example.test/lyrics.txt",
        }]},
    ))
    downloads: list[str] = []

    def download_file(*, url: str, **_kwargs) -> bytes:
        downloads.append(url)
        return "00:00:00,000 --> 00:00:01,000\n歌词内容".encode("utf-8")

    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        request_json=lambda **_kwargs: next(replies),
        upload_file=lambda _path: "https://media.example.test/source.mp4",
        download_file=download_file,
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
    )

    result = client.run_speech_whisper(
        video_path=video, workflow_id="workflow-1", input_node_id="1", input_field="video"
    )

    assert downloads == ["https://media.example.test/lyrics.txt"]
    assert result["segments"] == [{"start": 0.0, "end": 1.0, "text": "歌词内容"}]


def test_whisper_workflow_accepts_plain_txt_when_extracting_uploaded_song_lyrics(tmp_path: Path) -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient

    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF-test")
    replies = iter((
        {"taskId": "whisper-task", "status": "RUNNING"},
        {"taskId": "whisper-task", "status": "SUCCESS", "results": [{
            "outputType": "txt",
            "text": "几年后的原谅\n为一张脸去养一身伤\n别讲想念我",
        }]},
    ))
    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        request_json=lambda **_kwargs: next(replies),
        upload_file=lambda _path: "https://media.example.test/song.wav",
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
    )

    result = client.run_whisper(
        audio_path=audio,
        workflow_id="workflow-1",
        input_node_id="12",
        input_field="audio",
        require_timestamps=False,
    )

    assert result["segments"] == [
        {"text": "几年后的原谅"},
        {"text": "为一张脸去养一身伤"},
        {"text": "别讲想念我"},
    ]



def test_tts_binds_the_original_voiceover_reference_audio_when_provided() -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient

    requests: list[dict[str, object]] = []

    def request_json(**kwargs):
        requests.append(kwargs)
        if "/run/workflow/" in str(kwargs["url"]):
            return {"taskId": "tts-task", "status": "RUNNING"}
        return {
            "taskId": "tts-task",
            "status": "SUCCESS",
            "results": [{"outputType": "wav", "url": "https://media.example.test/voiceover.wav"}],
        }

    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        request_json=request_json,
        download_file=lambda **_kwargs: b"RIFF-voiceover",
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
        tts_config={
            "workflow_id": "tts-workflow",
            "text_node_id": "1",
            "text_field": "text",
            "language_node_id": "2",
            "language_field": "language",
            "speaker_node_id": "3",
            "speaker_field": "speaker",
            "timing_node_id": "4",
            "timing_field": "timing",
            "reference_audio_node_id": "5",
            "reference_audio_field": "audio",
        },
    )

    client.run_tts(
        "新しいナレーション",
        "ja",
        {"start_ms": 0, "end_ms": 1000},
        speaker="VOICEOVER",
        voice_reference_url="https://media.example.test/source-voiceover.wav",
    )

    node_values = {
        (item["nodeId"], item["fieldName"]): item["fieldValue"]
        for item in requests[0]["payload"]["nodeInfoList"]
    }
    assert node_values[("5", "audio")] == "https://media.example.test/source-voiceover.wav"


def test_voice_clone_two_input_tts_submits_reference_audio_and_approved_plain_text_only() -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient

    requests: list[dict[str, object]] = []

    def request_json(**kwargs):
        requests.append(kwargs)
        if "/run/ai-app/" in str(kwargs["url"]):
            return {"taskId": "tts-task", "status": "RUNNING"}
        return {
            "taskId": "tts-task",
            "status": "SUCCESS",
            "results": [{"outputType": "wav", "url": "https://media.example.test/voiceover.wav"}],
        }

    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        request_json=request_json,
        download_file=lambda **_kwargs: b"RIFF-voiceover",
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
        tts_config={
            "mode": "voice_clone_two_input",
            "workflow_id": "2080177717619118082",
            "reference_audio_node_id": "4",
            "reference_audio_field": "audio",
            "text_node_id": "11",
            "text_field": "prompt",
        },
    )

    client.run_tts(
        "Approved voiceover line.",
        "en-US",
        {"start_ms": 1000, "end_ms": 2800},
        speaker="NARRATOR_A",
        voice_reference_url="https://media.example.test/reference.wav",
    )

    submit = next(item for item in requests if "/run/ai-app/" in str(item["url"]))
    assert str(submit["url"]).endswith("/openapi/v2/run/ai-app/2080177717619118082")
    assert submit["payload"]["nodeInfoList"] == [
        {
            "nodeId": "4",
            "fieldName": "audio",
            "fieldValue": "https://media.example.test/reference.wav",
        },
        {
            "nodeId": "11",
            "fieldName": "prompt",
            "fieldValue": "Approved voiceover line.",
        },
    ]

def test_tts_rejects_voice_reference_without_a_configured_reference_node() -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient, RunningHubWorkflowError

    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        tts_config={
            "workflow_id": "tts-workflow",
            "text_node_id": "1",
            "text_field": "text",
            "language_node_id": "2",
            "language_field": "language",
            "speaker_node_id": "3",
            "speaker_field": "speaker",
            "timing_node_id": "4",
            "timing_field": "timing",
        },
    )

    with pytest.raises(RunningHubWorkflowError, match="reference audio configuration missing"):
        client.run_tts(
            "旁白",
            "zh-CN",
            {"start_ms": 0, "end_ms": 1000},
            speaker="VOICEOVER",
            voice_reference_url="https://media.example.test/source-voiceover.wav",
        )
