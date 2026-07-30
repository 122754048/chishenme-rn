from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from .errors import ReplicationError


def probe_source(path: str | Path, *, max_duration_seconds: float = 30.0, timeout_seconds: float = 30.0) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ReplicationError("INPUT_SOURCE_REQUIRED", "source video does not exist", category="input", user_action_required=True, http_status=400)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    command = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(source),
    ]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReplicationError("INPUT_SOURCE_INVALID", "source video probe failed", category="input", retryable=True, details={"path": str(source)}, http_status=422) from exc
    if completed.returncode != 0:
        raise ReplicationError("INPUT_SOURCE_INVALID", "source video is not decodable", category="input", user_action_required=True, details={"stderr": completed.stderr[-1000:]}, http_status=422)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReplicationError("INPUT_SOURCE_INVALID", "ffprobe returned invalid JSON", category="input", http_status=422) from exc
    format_info = payload.get("format") if isinstance(payload, dict) else {}
    try:
        duration = float(format_info.get("duration"))
    except (TypeError, ValueError) as exc:
        raise ReplicationError("INPUT_SOURCE_INVALID", "source duration is missing", category="input", http_status=422) from exc
    if duration > max_duration_seconds:
        raise ReplicationError(
            "INPUT_SOURCE_TOO_LONG",
            "source_video must be at most 30 seconds",
            category="input",
            user_action_required=True,
            details={"duration_seconds": duration, "maximum_seconds": max_duration_seconds},
            http_status=422,
        )
    streams = payload.get("streams") if isinstance(payload, dict) else []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not video:
        raise ReplicationError("INPUT_SOURCE_INVALID", "source video has no video stream", category="input", user_action_required=True, http_status=422)
    return {
        "path": str(source),
        "sha256": digest.hexdigest(),
        "duration_seconds": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("r_frame_rate"),
        "has_audio": any(item.get("codec_type") == "audio" for item in streams),
        "format": format_info.get("format_name"),
    }
