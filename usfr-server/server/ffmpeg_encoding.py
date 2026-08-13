"""Central FFmpeg H.264 encoder selection for USFR runtime paths."""

from __future__ import annotations

import os


class FfmpegEncodingConfigurationError(ValueError):
    pass


def _threads_args() -> list[str]:
    raw = os.environ.get("USFR_FFMPEG_THREADS", "").strip()
    if not raw:
        return []
    try:
        value = int(raw)
    except ValueError as exc:
        raise FfmpegEncodingConfigurationError(
            "USFR_FFMPEG_THREADS must be an integer from 1 through 64"
        ) from exc
    if not 1 <= value <= 64:
        raise FfmpegEncodingConfigurationError(
            "USFR_FFMPEG_THREADS must be an integer from 1 through 64"
        )
    return ["-threads", str(value)]


def video_encoder_args() -> list[str]:
    encoder = os.environ.get("USFR_FFMPEG_ENCODER", "libx264").strip() or "libx264"
    if encoder == "libx264":
        return [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            *_threads_args(),
        ]
    if encoder == "h264_nvenc":
        return [
            "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr",
            "-cq", "19", "-b:v", "0", *_threads_args(),
        ]
    raise FfmpegEncodingConfigurationError(
        "USFR_FFMPEG_ENCODER must be libx264 or h264_nvenc"
    )


__all__ = [
    "FfmpegEncodingConfigurationError",
    "video_encoder_args",
]
