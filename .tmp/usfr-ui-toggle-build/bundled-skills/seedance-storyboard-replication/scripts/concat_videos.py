from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile


class ConcatError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    has_video: bool
    has_audio: bool
    duration: float
    video_codec: str = ""
    audio_codec: str = ""
    width: int = 0
    height: int = 0
    rotation_deg: int = 0
    display_width: int = 0
    display_height: int = 0
    frame_rate: str = ""
    video_time_base: str = ""
    pixel_format: str = ""
    sample_aspect_ratio: str = "1:1"
    video_start_time: float = 0.0
    video_duration: float = 0.0
    audio_sample_rate: int = 0
    audio_channel_layout: str = ""
    audio_time_base: str = ""
    audio_start_time: float = 0.0
    audio_duration: float = 0.0


@dataclass(frozen=True)
class TransitionBoundary:
    type: str
    duration: float = 0.0
    source_shell_sha256: str = ""
    audio_policy: str = "source_equivalent"
    audio_fade_duration: float = 0.03
    requested_duration: float | None = None
    duration_adjusted: bool = False
    requested_frames: int | None = None


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def probe_media(path: Path) -> MediaInfo:
    if not path.is_file():
        raise ConcatError(f"Media file not found: {path}")
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    if result.returncode != 0:
        raise ConcatError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if not video_streams:
        raise ConcatError(f"Media file has no video stream: {path}")
    video = video_streams[0]
    audio = audio_streams[0] if audio_streams else {}
    encoded_width = int(video.get("width") or 0)
    encoded_height = int(video.get("height") or 0)
    rotation_deg = _rotation_degrees(video)
    if rotation_deg in {90, 270}:
        display_width, display_height = encoded_height, encoded_width
    else:
        display_width, display_height = encoded_width, encoded_height
    format_duration = _float_value(data.get("format", {}).get("duration"))
    video_duration = _stream_duration_seconds(video)
    if video_duration <= 0:
        raise ConcatError(
            f"Video stream duration is unavailable: {path}"
        )
    audio_duration = _stream_duration_seconds(audio) if audio_streams else 0.0
    container_duration = format_duration if format_duration > 0 else video_duration
    return MediaInfo(
        path=path,
        has_video=True,
        has_audio=bool(audio_streams),
        duration=container_duration,
        video_codec=str(video.get("codec_name") or ""),
        audio_codec=str(audio.get("codec_name") or ""),
        width=encoded_width,
        height=encoded_height,
        rotation_deg=rotation_deg,
        display_width=display_width,
        display_height=display_height,
        frame_rate=str(video.get("avg_frame_rate") or video.get("r_frame_rate") or ""),
        video_time_base=str(video.get("time_base") or ""),
        pixel_format=str(video.get("pix_fmt") or ""),
        sample_aspect_ratio=str(video.get("sample_aspect_ratio") or "1:1"),
        video_start_time=_float_value(video.get("start_time")),
        video_duration=video_duration,
        audio_sample_rate=int(audio.get("sample_rate") or 0),
        audio_channel_layout=str(
            audio.get("channel_layout")
            or (f"channels:{audio.get('channels')}" if audio.get("channels") else "")
        ),
        audio_time_base=str(audio.get("time_base") or ""),
        audio_start_time=_float_value(audio.get("start_time")),
        audio_duration=audio_duration,
    )


def _float_value(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _stream_duration_seconds(stream: dict[str, object]) -> float:
    """Return a stream-owned duration without borrowing the container clock."""

    duration = _float_value(stream.get("duration"))
    if duration > 0:
        return duration
    duration_ts = _float_value(stream.get("duration_ts"))
    time_base = str(stream.get("time_base") or "")
    if duration_ts > 0 and "/" in time_base:
        numerator, denominator = time_base.split("/", 1)
        try:
            seconds = duration_ts * float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            seconds = 0.0
        if seconds > 0:
            return seconds
    frame_count = _float_value(stream.get("nb_frames"))
    frame_rate_raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    frame_rate = _fps_value(str(frame_rate_raw)) if frame_rate_raw else 0.0
    if frame_count > 0 and frame_rate > 0:
        return frame_count / frame_rate
    return 0.0


def _rotation_degrees(stream: dict[str, object]) -> int:
    tags = stream.get("tags")
    candidates: list[object] = []
    if isinstance(tags, dict):
        candidates.append(tags.get("rotate"))
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        candidates.extend(
            item.get("rotation")
            for item in side_data
            if isinstance(item, dict)
        )
    for value in candidates:
        try:
            return int(round(float(value))) % 360
        except (TypeError, ValueError):
            continue
    return 0


def concat_segments(
    segment_paths: list[Path],
    output_path: Path,
    *,
    expect_audio: bool = True,
) -> Path:
    if not segment_paths:
        raise ConcatError("At least one segment is required")
    media = [probe_media(Path(path)) for path in segment_paths]
    planned_video_duration = sum(info.video_duration for info in media)
    if expect_audio:
        missing_audio = [info.path for info in media if not info.has_audio]
        if missing_audio:
            raise ConcatError(f"Expected audio stream is missing: {missing_audio[0]}")
        for info in media:
            tolerance = max(2.0 / _fps_value(info.frame_rate), 0.05)
            if abs(info.video_duration - info.audio_duration) > tolerance:
                raise ConcatError(
                    "SEGMENT_AUDIO_VIDEO_DURATION_MISMATCH: "
                    f"{info.path} video/audio durations differ before concat"
                )
            if abs(info.video_start_time - info.audio_start_time) > tolerance:
                raise ConcatError(
                    "SEGMENT_AUDIO_VIDEO_START_MISMATCH: "
                    f"{info.path} video/audio start times differ before concat"
                )
    audio_presence = {info.has_audio for info in media}
    if len(audio_presence) > 1:
        mixed = [info.path for info in media if not info.has_audio][0]
        raise ConcatError(f"Mixed audio presence across segments; missing audio in {mixed}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if _compatible_for_copy(media):
            list_path = _write_concat_list(tmp_path / "concat-list.txt", [info.path for info in media])
            _run_ffmpeg_concat(
                list_path,
                output_path,
                include_audio=expect_audio,
                planned_video_duration=planned_video_duration,
            )
        else:
            normalized = [
                _normalize_segment(
                    info.path,
                    tmp_path / f"normalized-{index:03d}.mp4",
                    width=media[0].display_width or media[0].width,
                    height=media[0].display_height or media[0].height,
                    fps=_fps_value(media[0].frame_rate),
                    include_audio=media[0].has_audio,
                )
                for index, info in enumerate(media, start=1)
            ]
            list_path = _write_concat_list(tmp_path / "concat-list.txt", normalized)
            _run_ffmpeg_concat(
                list_path,
                output_path,
                include_audio=expect_audio,
                planned_video_duration=planned_video_duration,
            )

    final_info = probe_media(output_path)
    if expect_audio and not final_info.has_audio:
        raise ConcatError(f"Final output has no audio stream: {output_path}")
    tolerance = max(2.0 / _fps_value(final_info.frame_rate), 0.05)
    if abs(final_info.video_duration - planned_video_duration) > tolerance:
        raise ConcatError(
            "VIDEO_DURATION_DRIFT: final picture duration does not match the "
            "concatenated video-stream clock"
        )
    if expect_audio and abs(final_info.video_duration - final_info.audio_duration) > tolerance:
        raise ConcatError(
            "AUDIO_VIDEO_DURATION_DRIFT: final audio does not cover the "
            "concatenated video-stream clock"
        )
    return output_path


def _compatible_for_copy(media: list[MediaInfo]) -> bool:
    first = media[0]
    required_video = (
        first.video_codec,
        first.frame_rate,
        first.video_time_base,
        first.pixel_format,
        first.sample_aspect_ratio,
    )
    if any(not value for value in required_video):
        return False
    if first.has_audio and (
        not first.audio_codec
        or not first.audio_sample_rate
        or not first.audio_channel_layout
        or not first.audio_time_base
    ):
        return False

    def av_is_aligned(info: MediaInfo) -> bool:
        if abs(info.video_start_time) > 0.001:
            return False
        if info.has_audio and abs(info.audio_start_time) > 0.001:
            return False
        if info.has_audio and info.video_duration > 0 and info.audio_duration > 0:
            tolerance = max(2.0 / _fps_value(info.frame_rate), 0.05)
            if abs(info.video_duration - info.audio_duration) > tolerance:
                return False
        return True

    return all(
        info.video_codec == first.video_codec
        and info.audio_codec == first.audio_codec
        and info.width == first.width
        and info.height == first.height
        and info.rotation_deg == first.rotation_deg
        and info.display_width == first.display_width
        and info.display_height == first.display_height
        and info.has_audio == first.has_audio
        and info.frame_rate == first.frame_rate
        and info.video_time_base == first.video_time_base
        and info.pixel_format == first.pixel_format
        and info.sample_aspect_ratio == first.sample_aspect_ratio
        and info.audio_sample_rate == first.audio_sample_rate
        and info.audio_channel_layout == first.audio_channel_layout
        and info.audio_time_base == first.audio_time_base
        and av_is_aligned(info)
        for info in media
    )


def _fps_value(value: str) -> float:
    if not value:
        return 30.0
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            parsed = float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            return 30.0
        return parsed if parsed > 0 else 30.0
    try:
        parsed = float(value)
    except ValueError:
        return 30.0
    return parsed if parsed > 0 else 30.0


def _write_concat_list(path: Path, segments: list[Path]) -> Path:
    lines = [f"file {shlex.quote(str(segment))}" for segment in segments]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run_ffmpeg_concat(
    list_path: Path,
    output_path: Path,
    *,
    include_audio: bool = True,
    planned_video_duration: float | None = None,
) -> None:
    segments: list[Path] = []
    for line in list_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or not stripped.lower().startswith("file "):
            continue
        values = shlex.split(stripped, posix=True)
        if len(values) != 2:
            raise ConcatError("concat list contains an invalid file entry")
        segments.append(Path(values[1]))
    if not segments:
        raise ConcatError("concat list contains no media segments")

    filters: list[str] = []
    for index in range(len(segments)):
        filters.append(
            f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS,setsar=1[v{index}]"
        )
        if include_audio:
            filters.append(
                f"[{index}:a]aresample=48000,asetpts=PTS-STARTPTS[a{index}]"
            )
    video_inputs = "".join(f"[v{index}]" for index in range(len(segments)))
    filters.append(f"{video_inputs}concat=n={len(segments)}:v=1:a=0[vout]")
    if include_audio:
        audio_inputs = "".join(f"[a{index}]" for index in range(len(segments)))
        filters.append(f"{audio_inputs}concat=n={len(segments)}:v=0:a=1[aconcat]")
        if planned_video_duration is not None:
            if planned_video_duration <= 0:
                raise ConcatError("Planned video duration must be positive")
            filters.append(
                f"[aconcat]atrim=end={planned_video_duration:.6f},"
                "asetpts=PTS-STARTPTS[aout]"
            )
        else:
            filters.append("[aconcat]anull[aout]")

    command = ["ffmpeg", "-y", "-loglevel", "error"]
    for segment in segments:
        command.extend(["-i", str(segment)])
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if include_audio:
        command.extend(["-map", "[aout]", "-c:a", "aac", "-ar", "48000", "-ac", "2"])
    else:
        command.append("-an")
    if planned_video_duration is not None:
        command.extend(["-t", f"{planned_video_duration:.6f}"])
    command.extend(["-movflags", "+faststart", str(output_path)])
    result = _run(command)
    if result.returncode != 0:
        raise ConcatError(f"ffmpeg concat failed: {result.stderr.strip()}")


def _normalize_segment(
    input_path: Path,
    output_path: Path,
    *,
    width: int,
    height: int,
    fps: float,
    include_audio: bool,
) -> Path:
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps:.6f},setpts=PTS-STARTPTS,setsar=1"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-video_track_timescale",
        "90000",
    ]
    if include_audio:
        command.extend(
            [
                "-af",
                "aresample=48000,asetpts=PTS-STARTPTS",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
            ]
        )
    else:
        command.append("-an")
    command.append(str(output_path))
    result = _run(command)
    if result.returncode != 0:
        raise ConcatError(f"ffmpeg normalize failed for {input_path}: {result.stderr.strip()}")
    return output_path


_XFADE_TYPES = {
    "push": "slideleft",
    "push_left": "slideleft",
    "push_right": "slideright",
    "push_up": "slideup",
    "push_down": "slidedown",
    "slide": "slideleft",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "slide_up": "slideup",
    "slide_down": "slidedown",
    "wipe": "wipeleft",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "wipe_up": "wipeup",
    "wipe_down": "wipedown",
    "dissolve": "dissolve",
    "fade": "fade",
    "zoom": "zoomin",
    "zoom_in": "zoomin",
    "zoom_out": "fade",
    "zoom_back": "fade",
    # A source UI result preview that expands into the following full-frame
    # plate is materially closer to an expanding reveal than to a dissolve.
    # Keep these platform-neutral aliases so the dynamics/overlay contract can
    # drive the compositor without leaking FFmpeg vocabulary upstream.
    "preview_expand": "zoomin",
    "reveal_expand": "zoomin",
    "match_expand": "zoomin",
}

# ``hblur`` only smears pixels horizontally; it does not reproduce the
# source's radial zoom, focal expansion, or blur kernel.  Keep that source
# label accepted by the timeline contract, but do not let the default FFmpeg
# backend claim an approximate filter is an exact replica.  A deployment may
# add a dedicated renderer later; until then the route fails closed.
_NON_EXACT_TRANSITIONS = {
    "radial_zoom_blur",
    # FFmpeg xfade exposes a centred ``zoomin`` transition but no matching
    # zoom-out/back camera transform.  Mapping these source shells to a plain
    # fade changes the motion contract and must not be reported as fidelity.
    "zoom_out",
    "zoom_back",
}


def build_transition_filter_graph(
    *,
    durations: list[float],
    boundaries: list[TransitionBoundary],
    include_audio: bool,
    fps: float = 30.0,
) -> tuple[str, float, list[dict[str, object]]]:
    if not durations:
        raise ConcatError("At least one segment duration is required")
    if len(boundaries) != len(durations) - 1:
        raise ConcatError("Transition boundary count must equal segment count minus one")
    if any(duration <= 0 for duration in durations):
        raise ConcatError("Segment durations must be positive")
    if fps <= 0:
        raise ConcatError("fps must be positive")

    filters: list[str] = []
    for index in range(len(durations)):
        # Transition filters require identical sample aspect ratios. The
        # timeline normalizer already records the source SAR as provenance;
        # force the compositor inputs to square pixels as a final defensive
        # boundary so mixed mobile exports cannot break xfade/concat.
        filters.append(
            f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS,setsar=1[v{index}]"
        )
        if include_audio:
            filters.append(
                f"[{index}:a]aresample=48000,asetpts=PTS-STARTPTS[a{index}]"
            )

    current_video = "v0"
    current_audio = "a0" if include_audio else None
    current_duration = durations[0]
    receipts: list[dict[str, object]] = []
    for index, boundary in enumerate(boundaries, start=1):
        output_video = f"vc{index}"
        output_audio = f"ac{index}"
        if boundary.type == "hard_cut":
            filters.append(
                f"[{current_video}][v{index}]concat=n=2:v=1:a=0[{output_video}]"
            )
            if include_audio and current_audio is not None:
                if boundary.audio_policy in {"preserve", "hard_cut_preserve"}:
                    filters.append(
                        f"[{current_audio}][a{index}]concat=n=2:v=0:a=1[{output_audio}]"
                    )
                    audio_rendered = False
                    audio_transition = "preserve"
                    fade_duration = 0.0
                else:
                    fade_duration = min(
                        max(float(boundary.audio_fade_duration), 0.0),
                        current_duration / 2.0,
                        durations[index] / 2.0,
                    )
                    if fade_duration <= 0:
                        raise ConcatError("Hard-cut anti-pop fade duration must be positive")
                    left_audio = f"ahcl{index}"
                    right_audio = f"ahcr{index}"
                    fade_start = current_duration - fade_duration
                    filters.append(
                        f"[{current_audio}]afade=t=out:st={fade_start:.6f}:"
                        f"d={fade_duration:.6f}[{left_audio}]"
                    )
                    filters.append(
                        f"[a{index}]afade=t=in:st=0:d={fade_duration:.6f}"
                        f"[{right_audio}]"
                    )
                    filters.append(
                        f"[{left_audio}][{right_audio}]concat=n=2:v=0:a=1"
                        f"[{output_audio}]"
                    )
                    audio_rendered = True
                    audio_transition = "anti_pop_fade"
            else:
                audio_rendered = False
                audio_transition = "none"
                fade_duration = 0.0
            current_duration += durations[index]
            receipts.append(
                {
                    "boundary_index": index - 1,
                    "source_type": "hard_cut",
                    "ffmpeg_transition": "hard_cut",
                    "duration": 0.0,
                    "offset": round(current_duration - durations[index], 6),
                    "rendered": False,
                    "audio_rendered": audio_rendered,
                    "audio_transition": audio_transition,
                    "audio_fade_duration": round(fade_duration, 6),
                    "source_shell_sha256": boundary.source_shell_sha256,
                }
            )
        else:
            if boundary.type in _NON_EXACT_TRANSITIONS:
                raise ConcatError(
                    "TRANSITION_BACKEND_CAPABILITY_REQUIRED: "
                    f"FFmpeg backend has no exact renderer for {boundary.type}"
                )
            ffmpeg_type = _XFADE_TYPES.get(boundary.type)
            if ffmpeg_type is None:
                raise ConcatError(f"Unsupported transition type: {boundary.type}")
            requested_overlap = boundary.duration
            if boundary.requested_duration is not None:
                overlap = boundary.duration
                duration_adjusted = boundary.duration_adjusted
            else:
                requested_frames = max(1, round(requested_overlap * fps))
                left_active_frames = max(
                    1, int(durations[index - 1] * fps + 1e-6)
                )
                right_active_frames = max(
                    1, int(durations[index] * fps + 1e-6)
                )
                available_frames = min(
                    max(left_active_frames - 1, 0),
                    max(right_active_frames - 1, 0),
                )
                if requested_overlap > available_frames / fps + 1e-9:
                    fitted_frames = min(requested_frames, available_frames)
                    if fitted_frames < 1:
                        raise ConcatError(
                            "transition shell has no real active-frame overlap"
                        )
                    overlap = fitted_frames / fps
                    duration_adjusted = True
                else:
                    overlap = requested_overlap
                    duration_adjusted = False
            if overlap <= 0:
                raise ConcatError("Non-hard transition duration must be positive")
            if overlap >= min(current_duration, durations[index]):
                raise ConcatError("Transition duration exceeds adjacent media")
            offset = current_duration - overlap
            if boundary.type == "dissolve":
                # FFmpeg's native xfade=dissolve is not deterministic across
                # common mobile codecs: mixed H.264/HEVC inputs can produce a
                # full-frame salt-and-pepper burst during the overlap. Build
                # the same linear dissolve explicitly from trimmed frames,
                # an alpha-ramped incoming stream, and overlay. Every branch
                # resets PTS before concat so this remains valid when the
                # outgoing stream is itself the result of an earlier shell.
                left_head = f"dhead{index}"
                left_overlap = f"dleft{index}"
                right_overlap = f"dright{index}"
                right_tail = f"dtail{index}"
                blend = f"dblend{index}"
                filters.extend(
                    [
                        f"[{current_video}]split=2[dcurh{index}][dcuro{index}]",
                        f"[v{index}]split=2[dnxto{index}][dnxt{index}]",
                        f"[dcurh{index}]trim=end={offset:.6f},"
                        f"setpts=PTS-STARTPTS[{left_head}]",
                        f"[dcuro{index}]trim=start={offset:.6f}:"
                        f"end={current_duration:.6f},setpts=PTS-STARTPTS"
                        f"[{left_overlap}]",
                        f"[dnxto{index}]trim=end={overlap:.6f},"
                        f"setpts=PTS-STARTPTS,format=rgba,"
                        f"fade=t=in:st=0:d={overlap:.6f}:alpha=1"
                        f"[{right_overlap}]",
                        f"[{left_overlap}][{right_overlap}]overlay=shortest=1:"
                        f"format=auto[{blend}]",
                        f"[dnxt{index}]trim=start={overlap:.6f}:"
                        f"end={durations[index]:.6f},"
                        f"setpts=PTS-STARTPTS[{right_tail}]",
                        f"[{left_head}][{blend}][{right_tail}]concat=n=3:v=1:a=0"
                        f"[{output_video}]",
                    ]
                )
            else:
                filters.append(
                    f"[{current_video}][v{index}]xfade=transition={ffmpeg_type}:"
                    f"duration={overlap:.6f}:offset={offset:.6f}[{output_video}]"
                )
            if include_audio and current_audio is not None:
                if boundary.audio_policy in {"preserve", "hard_cut_preserve"}:
                    # Keep each source audio stream intact and remove only
                    # the portion of the outgoing clip hidden by the visual
                    # overlap.  This preserves the source boundary contract
                    # without introducing an unrequested crossfade.
                    preserved_left = f"apreserve{index}"
                    filters.append(
                        f"[{current_audio}]atrim=end={offset:.6f},asetpts=PTS-STARTPTS"
                        f"[{preserved_left}]"
                    )
                    filters.append(
                        f"[{preserved_left}][a{index}]concat=n=2:v=0:a=1"
                        f"[{output_audio}]"
                    )
                    audio_transition = "preserve"
                    audio_rendered = True
                    audio_fade_duration = 0.0
                else:
                    audio_fade_duration = min(
                        max(float(boundary.audio_fade_duration), 0.0),
                        overlap,
                    )
                    if audio_fade_duration <= 0:
                        raise ConcatError(
                            "Non-hard transition audio fade duration must be positive"
                        )
                    if float(boundary.audio_fade_duration) > overlap + 1e-9:
                        raise ConcatError(
                            "TRANSITION_AUDIO_FADE_EXCEEDS_VISUAL_OVERLAP"
                        )
                    audio_left = f"afadeleft{index}"
                    filters.append(
                        f"[{current_audio}]atrim=end={offset + audio_fade_duration:.6f},"
                        f"asetpts=PTS-STARTPTS[{audio_left}]"
                    )
                    filters.append(
                        f"[{audio_left}][a{index}]acrossfade=d={audio_fade_duration:.6f}:"
                        f"c1=tri:c2=tri[{output_audio}]"
                    )
                    audio_transition = "crossfade"
                    audio_rendered = True
            else:
                audio_transition = "none"
                audio_rendered = False
                audio_fade_duration = 0.0
            current_duration += durations[index] - overlap
            receipts.append(
                {
                    "boundary_index": index - 1,
                    "source_type": boundary.type,
                    "ffmpeg_transition": ffmpeg_type,
                    "duration": round(overlap, 6),
                    "requested_duration": round(
                        boundary.requested_duration
                        if boundary.requested_duration is not None
                        else requested_overlap,
                        6,
                    ),
                    "duration_adjusted": duration_adjusted,
                    "offset": round(offset, 6),
                    "rendered": True,
                    "audio_rendered": audio_rendered,
                    "audio_transition": audio_transition,
                    "audio_fade_duration": round(audio_fade_duration, 6),
                    "source_shell_sha256": boundary.source_shell_sha256,
                }
            )
        current_video = output_video
        if include_audio:
            current_audio = output_audio

    filters.append(f"[{current_video}]null[vout]")
    if include_audio and current_audio is not None:
        filters.append(
            f"[{current_audio}]atrim=end={current_duration:.6f},"
            "asetpts=PTS-STARTPTS[aout]"
        )
    graph = ";".join(filters)
    graph_hash = hashlib.sha256(graph.encode("utf-8")).hexdigest()
    for receipt in receipts:
        receipt["render_hash"] = graph_hash
    return graph, round(current_duration, 6), receipts


def render_transition_segments(
    segment_paths: list[Path],
    durations: list[float],
    boundaries: list[TransitionBoundary],
    output_path: Path,
    *,
    expect_audio: bool,
    fps: float = 30.0,
) -> tuple[Path, float, list[dict[str, object]]]:
    graph, planned_duration, receipts = build_transition_filter_graph(
        durations=durations,
        boundaries=boundaries,
        include_audio=expect_audio,
        fps=fps,
    )
    command = ["ffmpeg", "-y", "-loglevel", "error"]
    for path in segment_paths:
        command.extend(["-i", str(path)])
    command.extend(["-filter_complex", graph, "-map", "[vout]"])
    if expect_audio:
        command.extend(["-map", "[aout]"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if expect_audio:
        command.extend(["-c:a", "aac", "-ar", "48000", "-ac", "2"])
    else:
        command.append("-an")
    # The picture timeline is authoritative.  ``-shortest`` would instead
    # truncate valid video whenever an input audio stream ends early.  The
    # graph trims audio overhang above; this explicit output bound removes AAC
    # encoder padding without extending or synthesizing missing audio.
    command.extend(["-t", f"{planned_duration:.6f}"])
    command.extend(["-movflags", "+faststart", str(output_path)])
    result = _run(command)
    if result.returncode != 0:
        raise ConcatError(f"ffmpeg transition render failed: {result.stderr.strip()}")
    if output_path.is_file() and output_path.stat().st_size > 0:
        final_output_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
        for receipt in receipts:
            receipt["final_output_sha256"] = final_output_sha256
    return output_path, planned_duration, receipts


def main() -> int:
    parser = argparse.ArgumentParser(description="Concatenate Seedance video segments without dropping audio.")
    parser.add_argument("--segment", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-audio-expected", action="store_true")
    args = parser.parse_args()

    concat_segments(args.segment, args.output, expect_audio=not args.no_audio_expected)
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
