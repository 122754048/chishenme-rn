#!/usr/bin/env python3
from __future__ import annotations

import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


def executable(name: str, *, required: bool = True) -> str | None:
    env_name = "FFPROBE_EXE" if name == "ffprobe" else "FFMPEG_EXE"
    configured = os.getenv(env_name, "").strip()
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which(name)
    if found:
        return found
    imageio_ffmpeg = os.getenv("IMAGEIO_FFMPEG_EXE", "").strip()
    if imageio_ffmpeg and Path(imageio_ffmpeg).is_file():
        sibling = Path(imageio_ffmpeg).with_name("ffprobe" + Path(imageio_ffmpeg).suffix)
        if name == "ffmpeg":
            return imageio_ffmpeg
        if sibling.is_file():
            return str(sibling)
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg

            bundled = imageio_ffmpeg.get_ffmpeg_exe()
            if bundled and Path(bundled).is_file():
                return bundled
        except ImportError:
            pass
    if required:
        raise SystemExit(f"{name} was not found; set {env_name}")
    return None


def run_json(command: list[str]) -> dict[str, Any]:
    process = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if process.returncode != 0:
        raise SystemExit(process.stderr.strip() or "media probe failed")
    return json.loads(process.stdout)


def ratio(value: str | None) -> tuple[int, int]:
    try:
        result = Fraction(str(value or "0/1"))
    except (ValueError, ZeroDivisionError):
        return 0, 1
    return result.numerator, result.denominator


def rotation(stream: dict[str, Any]) -> int:
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    if str(tags.get("rotate") or "").lstrip("-").isdigit():
        return int(tags["rotate"]) % 360
    for item in stream.get("side_data_list") or []:
        if isinstance(item, dict) and str(item.get("rotation") or "").lstrip("-").isdigit():
            return int(item["rotation"]) % 360
    return 0


def scene_candidates(video: Path, threshold: float) -> list[int]:
    ffmpeg = executable("ffmpeg")
    assert ffmpeg is not None
    filter_value = f"select='gt(scene,{threshold})',showinfo"
    process = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video), "-vf", filter_value, "-an", "-f", "null", "-"], check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    values = {int(round(float(match.group(1)) * 1_000_000)) for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", process.stderr)}
    return sorted(value for value in values if value > 0)


def probe_without_ffprobe(video: Path) -> dict[str, Any]:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise SystemExit("ffprobe is unavailable and imageio-ffmpeg is not installed") from exc
    frames = imageio_ffmpeg.read_frames(str(video), pix_fmt="rgb24")
    try:
        metadata = next(frames)
    finally:
        frames.close()
    size = metadata.get("size") or metadata.get("source_size") or (0, 0)
    fps = Fraction(str(metadata.get("fps") or 0)).limit_denominator(100_000)
    duration = float(metadata.get("duration") or 0)
    if duration <= 0 or not size or len(size) != 2:
        raise SystemExit("imageio-ffmpeg could not determine video duration or size")
    return {
        "duration_us": int(round(duration * 1_000_000)),
        "source_width": int(size[0]),
        "source_height": int(size[1]),
        "encoded_width": int(size[0]),
        "encoded_height": int(size[1]),
        "rotation_deg": 0,
        "fps_num": fps.numerator,
        "fps_den": fps.denominator,
        "frame_count": int(round(duration * float(fps))) if fps else None,
        "video_codec": metadata.get("codec"),
        "audio_streams": [],
        "warnings": ["ffprobe unavailable; audio-stream and rotation metadata require downstream ffmpeg inspection"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a reference video and optionally detect scene-cut candidates.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--detect-scenes", action="store_true")
    parser.add_argument("--scene-threshold", type=float, default=0.30)
    args = parser.parse_args()
    if not args.video.is_file():
        raise SystemExit("video file not found")
    ffprobe = executable("ffprobe", required=False)
    if ffprobe:
        data = run_json([ffprobe, "-v", "error", "-show_format", "-show_streams", "-show_chapters", "-of", "json", str(args.video)])
        streams = data.get("streams") if isinstance(data.get("streams"), list) else []
        video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
        if not isinstance(video_stream, dict):
            raise SystemExit("video stream not found")
        audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
        duration = video_stream.get("duration") or (data.get("format") or {}).get("duration")
        duration_us = int(round(float(duration) * 1_000_000))
        fps_num, fps_den = ratio(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
        rot = rotation(video_stream)
        raw_width, raw_height = int(video_stream.get("width") or 0), int(video_stream.get("height") or 0)
        width, height = (raw_height, raw_width) if rot in {90, 270} else (raw_width, raw_height)
        probed = {
            "duration_us": duration_us,
            "source_width": width,
            "source_height": height,
            "encoded_width": raw_width,
            "encoded_height": raw_height,
            "rotation_deg": rot,
            "fps_num": fps_num,
            "fps_den": fps_den,
            "frame_count": int(video_stream.get("nb_frames") or 0) or None,
            "video_codec": video_stream.get("codec_name"),
            "audio_streams": [{"codec": item.get("codec_name"), "sample_rate": int(item.get("sample_rate") or 0), "channels": int(item.get("channels") or 0)} for item in audio_streams],
            "warnings": [],
        }
    else:
        probed = probe_without_ffprobe(args.video)
        duration_us = probed["duration_us"]
    candidates = scene_candidates(args.video, args.scene_threshold) if args.detect_scenes else []
    output = {
        "contract": "reference-video-probe",
        "contract_version": 1,
        "file_name": args.video.name,
        **probed,
        "scene_cut_candidates_us": [value for value in candidates if value < duration_us],
        "candidate_policy": "hints_only; inspect complete video and split on action/camera/audio/overlay phase changes",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
