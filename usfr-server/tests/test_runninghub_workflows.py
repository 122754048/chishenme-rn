from __future__ import annotations

from pathlib import Path

import pytest


def test_song_lip_sync_runs_two_generated_person_segments_and_returns_sha_bound_downloads(tmp_path: Path) -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient

    audio = tmp_path / "song.mp3"
    first = tmp_path / "S01.mp4"
    second = tmp_path / "S02.mp4"
    audio.write_bytes(b"song-bytes")
    first.write_bytes(b"first-video")
    second.write_bytes(b"second-video")
    submitted: list[dict[str, object]] = []

    def request_json(**kwargs):
        payload = kwargs["payload"]
        if "/run/ai-app/" in str(kwargs["url"]):
            submitted.append(dict(payload))
            video = next(item["fieldValue"] for item in payload["nodeInfoList"] if item["nodeId"] == "228")
            return {"taskId": "task-01" if video.endswith("S01.mp4") else "task-02", "status": "RUNNING"}
        task_id = payload["taskId"]
        return {"taskId": task_id, "status": "SUCCESS", "results": [{"outputType": "mp4", "url": f"https://result.example/{task_id}.mp4"}]}

    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        request_json=request_json,
        upload_file=lambda path: f"https://media.example/{path.name}",
        download_file=lambda url: b"\x00\x00\x00\x18ftypmp42" + url.encode("ascii"),
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
    )

    result = client.run_song_lip_sync_segments(
        uploaded_audio_kind="song",
        audio_path=audio,
        segments=[
            {"segment_id": "S01", "segment_type": "generated_person", "video_path": first, "song_start": "1:30", "song_end": "1:35"},
            {"segment_id": "S02", "segment_type": "generated_person", "video_path": second, "song_start": "1:35", "song_end": "1:40"},
        ],
    )

    assert len(submitted) == 2
    assert {row["segment_id"] for row in result["segments"]} == {"S01", "S02"}
    assert all(row["video_bytes"].startswith(b"\x00\x00\x00\x18ftyp") for row in result["segments"])
    assert all(row["receipt"]["workflow_id"] == "2082759080288296961" for row in result["segments"])


def test_song_lip_sync_rejects_an_opaque_ui_segment_before_uploading_any_media(tmp_path: Path) -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient, RunningHubWorkflowError

    audio = tmp_path / "song.mp3"
    ui = tmp_path / "ui.mp4"
    audio.write_bytes(b"song-bytes")
    ui.write_bytes(b"ui-video")
    uploads: list[Path] = []
    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        upload_file=lambda path: uploads.append(Path(path)) or "https://media.example/file",
    )

    with pytest.raises(RunningHubWorkflowError, match="SEGMENT_INELIGIBLE"):
        client.run_song_lip_sync_segments(
            uploaded_audio_kind="song",
            audio_path=audio,
            segments=[{"segment_id": "UI01", "segment_type": "opaque_ui_demo", "video_path": ui, "song_start": "1:30", "song_end": "1:35"}],
        )

    assert uploads == []


def test_whisper_workflow_uploads_the_current_audio_to_the_configured_node_and_parses_timestamped_txt(tmp_path: Path) -> None:
    from server.runninghub_workflows import RunningHubWorkflowClient

    requests: list[dict[str, object]] = []

    def request_json(**kwargs):
        requests.append(kwargs)
        if "/run/workflow/" in str(kwargs["url"]):
            return {"taskId": "whisper-task", "status": "RUNNING"}
        return {
            "taskId": "whisper-task",
            "status": "SUCCESS",
            "results": [
                {
                    "outputType": "txt",
                    "text": """00:00:00,000 --> 00:00:01,250
Hello world

00:00:01,250 --> 00:00:02,000
Second line""",
                }
            ],
        }

    audio = tmp_path / "source.wav"
    audio.write_bytes(b"RIFF-test")
    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        request_json=request_json,
        upload_file=lambda path: "https://media.example.test/current-source.wav",
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
    )

    result = client.run_whisper(
        audio_path=audio,
        workflow_id="2081636941417758721",
        input_node_id="12",
        input_field="audio",
    )

    assert result["task_id"] == "whisper-task"
    assert result["uploaded_audio_url"] == "https://media.example.test/current-source.wav"
    assert result["segments"] == [
        {"start": 0.0, "end": 1.25, "text": "Hello world"},
        {"start": 1.25, "end": 2.0, "text": "Second line"},
    ]
    submit = requests[0]
    assert submit["url"] == "https://runninghub.example.test/openapi/v2/run/workflow/2081636941417758721"
    assert submit["payload"] == {
        "addMetadata": True,
        "nodeInfoList": [
            {"nodeId": "12", "fieldName": "audio", "fieldValue": "https://media.example.test/current-source.wav"}
        ],
        "instanceType": "default",
        "usePersonalQueue": "false",
    }


def test_whisper_workflow_rejects_a_success_response_without_a_txt_result(tmp_path: Path) -> None:
    import pytest

    from server.runninghub_workflows import RunningHubWorkflowClient, RunningHubWorkflowError

    audio = tmp_path / "source.wav"
    audio.write_bytes(b"RIFF-test")
    replies = iter((
        {"taskId": "whisper-task", "status": "RUNNING"},
        {"taskId": "whisper-task", "status": "SUCCESS", "results": [{"outputType": "json", "url": "https://example.test/x"}]},
    ))
    client = RunningHubWorkflowClient(
        api_key="runninghub-test-key",
        base_url="https://runninghub.example.test",
        request_json=lambda **_kwargs: next(replies),
        upload_file=lambda _path: "https://media.example.test/current-source.wav",
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
    )

    with pytest.raises(RunningHubWorkflowError, match="TXT"):
        client.run_whisper(audio_path=audio, workflow_id="workflow-1", input_node_id="12", input_field="audio")
