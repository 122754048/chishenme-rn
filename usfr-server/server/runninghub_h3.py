"""One-attempt RunningHub MiniMax H3 video-edit provider boundary."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


H3_ENDPOINT = "/openapi/v2/minimax/hailuo-h3/multimodal-to-video"
H3_QUERY_ENDPOINT = "/openapi/v2/query"


class RunningHubH3Error(RuntimeError):
    pass


class RunningHubH3Client:
    def __init__(self, *, base_url: str,
                 post_json: Callable[[str, dict[str, object]], Mapping[str, Any]],
                 download: Callable[[str], bytes], sleep: Callable[[float], None] = time.sleep,
                 poll_interval_seconds: float = 5.0, timeout_seconds: float = 1800.0) -> None:
        parsed = urlparse(str(base_url).strip())
        if parsed.scheme != "https" or not parsed.hostname:
            raise RunningHubH3Error("H3_BASE_URL_INVALID")
        self.base_url = parsed.geturl().rstrip("/")
        self.post_json = post_json
        self.download = download
        self.sleep = sleep
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds

    def run(self, *, payload: Mapping[str, object], destination: Path) -> dict[str, object]:
        submitted = dict(self.post_json(self.base_url + H3_ENDPOINT, dict(payload)))
        task_id = str(submitted.get("taskId") or "").strip()
        if not task_id:
            raise RunningHubH3Error("H3_CREATE_AMBIGUOUS")
        response = submitted
        deadline = time.monotonic() + self.timeout_seconds
        while str(response.get("status") or "").upper() not in {"SUCCESS", "FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            if time.monotonic() >= deadline:
                raise RunningHubH3Error("H3_POLL_TIMEOUT")
            self.sleep(self.poll_interval_seconds)
            response = dict(self.post_json(self.base_url + H3_QUERY_ENDPOINT, {"taskId": task_id}))
        if str(response.get("status") or "").upper() != "SUCCESS":
            raise RunningHubH3Error("H3_PROVIDER_FAILED")
        videos = [
            row for row in (response.get("results") or [])
            if isinstance(row, Mapping)
            and str(row.get("outputType") or "").casefold() in {"mp4", "mov"}
            and str(row.get("url") or "").startswith("https://")
        ]
        if len(videos) != 1:
            raise RunningHubH3Error("H3_RESULT_COUNT_INVALID")
        data = self.download(str(videos[0]["url"]))
        if not data:
            raise RunningHubH3Error("H3_RESULT_EMPTY")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return {"task_id": task_id, "status": "SUCCESS", "result_path": str(destination),
                "provider_response": response}


__all__ = ["H3_ENDPOINT", "H3_QUERY_ENDPOINT", "RunningHubH3Client", "RunningHubH3Error"]
