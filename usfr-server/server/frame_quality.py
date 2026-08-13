"""Small deterministic frame-quality measurements shared by media stages."""

from __future__ import annotations

import io
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


class FrameQualityError(ValueError):
    """A frame could not be extracted or measured from bound media."""


def sharpness_ratio(source_image: Any, control_image: Any) -> float:
    """Return retained global and local edge detail for two images."""

    from PIL import ImageFilter, ImageStat

    def edge_image(image: Any) -> Any:
        grayscale = image.convert("L").resize((512, 512))
        return grayscale.filter(ImageFilter.FIND_EDGES)

    def edge_energy(image: Any) -> float:
        return float(ImageStat.Stat(image).mean[0])

    source_edges = edge_image(source_image)
    control_edges = edge_image(control_image)
    source_energy = edge_energy(source_edges.crop((8, 8, 504, 504)))
    if source_energy < 4.0:
        return 1.0
    ratios = [edge_energy(control_edges.crop((8, 8, 504, 504))) / source_energy]
    source_tile_floor = max(4.0, source_energy * 0.35)
    for top in range(0, 512, 128):
        for left in range(0, 512, 128):
            source_tile = source_edges.crop((left + 2, top + 2, left + 126, top + 126))
            control_tile = control_edges.crop((left + 2, top + 2, left + 126, top + 126))
            source_tile_energy = edge_energy(source_tile)
            if source_tile_energy >= source_tile_floor:
                ratios.append(edge_energy(control_tile) / source_tile_energy)
    return min(ratios)


def _decode_frame(
    path: Path,
    *,
    timestamp_ms: int,
    ffmpeg_bin: str | None,
    timeout_seconds: float,
) -> Any:
    from PIL import Image, UnidentifiedImageError

    executable = ffmpeg_bin or "ffmpeg"
    try:
        completed = subprocess.run(
            [
                executable,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-ss",
                f"{timestamp_ms / 1000.0:.6f}",
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrameQualityError("frame extraction failed") from exc
    if completed.returncode != 0 or not completed.stdout:
        raise FrameQualityError("frame extraction failed")
    try:
        image = Image.open(io.BytesIO(completed.stdout))
        image.load()
        return image.convert("RGB")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise FrameQualityError("decoded frame is invalid") from exc


def measure_video_sharpness(
    source_path: Path,
    final_path: Path,
    *,
    preservation_windows: Sequence[Mapping[str, Any]],
    ffmpeg_bin: str | None = None,
    timeout_seconds: float = 10.0,
    threshold: float = 0.60,
) -> dict[str, Any]:
    """Measure deterministic midpoint samples from approved preservation windows."""

    timestamps: list[int] = []
    seen_timestamps: set[int] = set()
    for index, window in enumerate(preservation_windows):
        if not isinstance(window, Mapping):
            raise FrameQualityError(f"preservation window {index} is invalid")
        try:
            start_ms = int(window["start_ms"])
            end_ms = int(window["end_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FrameQualityError(f"preservation window {index} is invalid") from exc
        if start_ms < 0 or end_ms <= start_ms:
            raise FrameQualityError(f"preservation window {index} is invalid")
        timestamp_ms = start_ms + (end_ms - start_ms) // 2
        if timestamp_ms not in seen_timestamps:
            timestamps.append(timestamp_ms)
            seen_timestamps.add(timestamp_ms)

    if len(timestamps) > 5:
        count = len(timestamps)
        selected_indices = [
            round((count - 1) * fraction)
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0)
        ]
        timestamps = [timestamps[index] for index in selected_indices]

    try:
        deadline = time.monotonic() + float(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise FrameQualityError("sharpness deadline is invalid") from exc

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise FrameQualityError("sharpness frame measurement deadline exhausted")
        return value

    sampled_frames: list[dict[str, Any]] = []
    for timestamp_ms in timestamps:
        source_image = _decode_frame(
            source_path,
            timestamp_ms=timestamp_ms,
            ffmpeg_bin=ffmpeg_bin,
            timeout_seconds=remaining(),
        )
        remaining()
        final_image = _decode_frame(
            final_path,
            timestamp_ms=timestamp_ms,
            ffmpeg_bin=ffmpeg_bin,
            timeout_seconds=remaining(),
        )
        remaining()
        sampled_frames.append(
            {
                "timestamp_ms": timestamp_ms,
                "ratio": sharpness_ratio(source_image, final_image),
            }
        )
    minimum_ratio = min(
        (float(frame["ratio"]) for frame in sampled_frames),
        default=1.0,
    )
    return {
        "threshold": threshold,
        "minimum_ratio": minimum_ratio,
        "sampled_frames": sampled_frames,
    }
