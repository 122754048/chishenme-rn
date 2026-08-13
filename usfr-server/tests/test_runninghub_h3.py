from __future__ import annotations

from pathlib import Path

import pytest

from server.runninghub_h3 import H3_ENDPOINT, RunningHubH3Client, RunningHubH3Error


def test_h3_client_submits_exact_endpoint_and_polls_one_mp4(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    responses = iter([
        {"taskId": "task-1", "status": "QUEUED"},
        {"taskId": "task-1", "status": "RUNNING"},
        {"taskId": "task-1", "status": "SUCCESS", "results": [
            {"outputType": "mp4", "url": "https://example.com/result.mp4"}
        ]},
    ])

    def post(url: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((url, payload))
        return next(responses)

    client = RunningHubH3Client(
        base_url="https://www.runninghub.ai", post_json=post,
        download=lambda url: b"video-bytes", sleep=lambda _: None,
    )
    payload = {"prompt": "使用视频1。", "imageUrls": [],
               "videoUrls": ["https://example.com/source.mp4"], "audioUrls": [],
               "resolution": "768P", "duration": "15", "ratio": "adaptive"}
    result = client.run(payload=payload, destination=tmp_path / "result.mp4")
    assert calls[0][0] == "https://www.runninghub.ai" + H3_ENDPOINT
    assert calls[1][0].endswith("/openapi/v2/query")
    assert result["task_id"] == "task-1"
    assert (tmp_path / "result.mp4").read_bytes() == b"video-bytes"


def test_h3_client_never_recreates_after_ambiguous_create(tmp_path: Path) -> None:
    attempts = 0

    def post(url: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        return {"status": "QUEUED"}

    client = RunningHubH3Client(
        base_url="https://www.runninghub.ai", post_json=post,
        download=lambda url: b"", sleep=lambda _: None,
    )
    with pytest.raises(RunningHubH3Error, match="H3_CREATE_AMBIGUOUS"):
        client.run(payload={}, destination=tmp_path / "result.mp4")
    assert attempts == 1


def test_h3_client_rejects_failed_or_multiple_results(tmp_path: Path) -> None:
    responses = iter([
        {"taskId": "task-2", "status": "QUEUED"},
        {"taskId": "task-2", "status": "SUCCESS", "results": [
            {"outputType": "mp4", "url": "https://example.com/a.mp4"},
            {"outputType": "mp4", "url": "https://example.com/b.mp4"},
        ]},
    ])
    client = RunningHubH3Client(
        base_url="https://www.runninghub.ai", post_json=lambda u, p: next(responses),
        download=lambda url: b"video", sleep=lambda _: None,
    )
    with pytest.raises(RunningHubH3Error, match="H3_RESULT_COUNT_INVALID"):
        client.run(payload={}, destination=tmp_path / "result.mp4")
