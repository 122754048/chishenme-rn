from __future__ import annotations

from pathlib import Path


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
