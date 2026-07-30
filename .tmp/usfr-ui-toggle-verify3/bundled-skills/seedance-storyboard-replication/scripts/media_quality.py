from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterable


class MediaQualityError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class BlackInterval:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True, order=True)
class FreezeInterval:
    """A decoded interval whose frames remain materially unchanged."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class ActiveWindow:
    raw_duration: float
    active_start: float
    active_end: float
    leading_black_duration: float
    trailing_black_duration: float
    black_intervals: tuple[BlackInterval, ...]
    internal_black_intervals: tuple[BlackInterval, ...]

    @property
    def active_duration(self) -> float:
        return max(0.0, self.active_end - self.active_start)

    def as_dict(self) -> dict[str, object]:
        return {
            "raw_duration": round(self.raw_duration, 6),
            "active_start": round(self.active_start, 6),
            "active_end": round(self.active_end, 6),
            "active_duration": round(self.active_duration, 6),
            "leading_black_duration": round(self.leading_black_duration, 6),
            "trailing_black_duration": round(self.trailing_black_duration, 6),
            "black_intervals": [
                {"start": round(item.start, 6), "end": round(item.end, 6)}
                for item in self.black_intervals
            ],
            "internal_black_intervals": [
                {"start": round(item.start, 6), "end": round(item.end, 6)}
                for item in self.internal_black_intervals
            ],
        }


_BLACK_RE = re.compile(
    r"black_start:(?P<start>-?\d+(?:\.\d+)?)\s+"
    r"black_end:(?P<end>-?\d+(?:\.\d+)?)\s+"
    r"black_duration:(?P<duration>-?\d+(?:\.\d+)?)"
)

_FREEZE_START_RE = re.compile(r"freeze_start\s*:\s*(?P<start>-?\d+(?:\.\d+)?)")
_FREEZE_END_RE = re.compile(
    r"freeze_end\s*:\s*(?P<end>-?\d+(?:\.\d+)?)"
    r"(?:\s+freeze_duration\s*:\s*(?P<duration>-?\d+(?:\.\d+)?))?"
)


def parse_blackdetect(stderr: str) -> tuple[BlackInterval, ...]:
    intervals: list[BlackInterval] = []
    for match in _BLACK_RE.finditer(stderr or ""):
        start = max(0.0, float(match.group("start")))
        end = max(start, float(match.group("end")))
        intervals.append(BlackInterval(start, end))
    return tuple(sorted(intervals))


def parse_freezedetect(
    stderr: str,
    *,
    duration: float | None = None,
) -> tuple[FreezeInterval, ...]:
    """Parse FFmpeg ``freezedetect`` start/end records deterministically."""

    pending_start: float | None = None
    intervals: list[FreezeInterval] = []
    for line in (stderr or "").splitlines():
        start_match = _FREEZE_START_RE.search(line)
        if start_match is not None:
            pending_start = max(0.0, float(start_match.group("start")))
            continue
        end_match = _FREEZE_END_RE.search(line)
        if end_match is None or pending_start is None:
            continue
        end = max(pending_start, float(end_match.group("end")))
        intervals.append(FreezeInterval(pending_start, end))
        pending_start = None
    if pending_start is not None and duration is not None and duration > pending_start:
        intervals.append(FreezeInterval(pending_start, float(duration)))
    return tuple(sorted(intervals))


def resolve_active_window(
    *,
    duration: float,
    fps: float,
    black_intervals: Iterable[BlackInterval],
) -> ActiveWindow:
    if duration <= 0:
        raise MediaQualityError("INVALID_MEDIA_DURATION")
    if fps <= 0:
        raise MediaQualityError("INVALID_MEDIA_FPS")

    edge_tolerance = max(1.5 / fps, 0.02)
    intervals = _coalesce_intervals(black_intervals, tolerance=edge_tolerance)
    active_start = 0.0
    active_end = duration
    leading: BlackInterval | None = None
    trailing: BlackInterval | None = None

    for interval in intervals:
        if interval.start <= edge_tolerance and interval.end > active_start:
            active_start = min(duration, interval.end)
            leading = interval
        else:
            break

    for interval in reversed(intervals):
        if interval.end >= duration - edge_tolerance and interval.start < active_end:
            active_end = max(0.0, interval.start)
            trailing = interval
        else:
            break

    minimum_active = max(2.0 / fps, 0.05)
    if active_end - active_start <= minimum_active:
        raise MediaQualityError("NO_ACTIVE_VIDEO_CONTENT")

    internal = tuple(
        interval
        for interval in intervals
        if interval is not leading
        and interval is not trailing
        and interval.start >= active_start - edge_tolerance
        and interval.end <= active_end + edge_tolerance
    )
    return ActiveWindow(
        raw_duration=duration,
        active_start=active_start,
        active_end=active_end,
        leading_black_duration=active_start,
        trailing_black_duration=max(0.0, duration - active_end),
        black_intervals=intervals,
        internal_black_intervals=internal,
    )


def _coalesce_intervals(
    intervals: Iterable[BlackInterval],
    *,
    tolerance: float,
) -> tuple[BlackInterval, ...]:
    """Merge codec-fragmented black intervals before edge classification."""

    merged: list[BlackInterval] = []
    for interval in sorted(intervals):
        if not merged or interval.start - merged[-1].end > tolerance:
            merged.append(interval)
            continue
        merged[-1] = BlackInterval(
            merged[-1].start,
            max(merged[-1].end, interval.end),
        )
    return tuple(merged)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def detect_active_window(
    path: Path,
    *,
    duration: float,
    fps: float,
    run: Callable[[list[str]], object] = _run,
) -> ActiveWindow:
    intervals = detect_black_intervals(
        path,
        fps=fps,
        # Edge padding is removed before an opaque splice.  A one-frame
        # black flash is visible at 30fps and must not survive normalization;
        # internal dark/black intervals are still preserved by
        # ``resolve_active_window``.  Use a half-frame detector threshold so
        # codec rounding cannot hide a single full-black edge frame.
        minimum_black_frames=0.5,
        run=run,
    )
    return resolve_active_window(
        duration=duration,
        fps=fps,
        black_intervals=intervals,
    )


def detect_black_intervals(
    path: Path,
    *,
    fps: float,
    minimum_black_frames: float,
    run: Callable[[list[str]], object] = _run,
) -> tuple[BlackInterval, ...]:
    if fps <= 0:
        raise MediaQualityError("INVALID_MEDIA_FPS")
    if minimum_black_frames <= 0:
        raise MediaQualityError("INVALID_BLACK_SCAN_FRAME_THRESHOLD")
    minimum_black = max(minimum_black_frames / fps, 0.001)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-vf",
        (
            "scale=160:-2,"
            "setpts=PTS-STARTPTS,"
            # ``pic_th=0.99`` treats a sparse, legitimate logo on a black
            # end-card as padding after the low-resolution probe.  Edge
            # trimming is allowed to remove only a genuinely full-black
            # frame; keep any non-black pixel so small logos and download
            # marks remain active content.
            f"blackdetect=d={minimum_black:.6f}:pix_th=0.1:pic_th=1.0"
        ),
        "-an",
        "-f",
        "null",
        "-",
    ]
    result = run(command)
    if int(getattr(result, "returncode", 1)) != 0:
        stderr = str(getattr(result, "stderr", "")).strip()
        raise MediaQualityError(f"BLACKDETECT_FAILED: {stderr}")
    return parse_blackdetect(str(getattr(result, "stderr", "")))


def detect_freeze_intervals(
    path: Path,
    *,
    fps: float,
    duration: float | None = None,
    minimum_freeze_seconds: float = 0.5,
    run: Callable[[list[str]], object] = _run,
) -> tuple[FreezeInterval, ...]:
    """Detect material frame freezes without inspecting content semantics."""

    if fps <= 0:
        raise MediaQualityError("INVALID_MEDIA_FPS")
    if minimum_freeze_seconds <= 0:
        raise MediaQualityError("INVALID_FREEZE_DURATION")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-vf",
        (
            "scale=160:-2,setpts=PTS-STARTPTS,"
            f"freezedetect=n=-60dB:d={minimum_freeze_seconds:.6f}"
        ),
        "-an",
        "-f",
        "null",
        "-",
    ]
    result = run(command)
    if int(getattr(result, "returncode", 1)) != 0:
        stderr = str(getattr(result, "stderr", "")).strip()
        raise MediaQualityError(f"FREEZEDETECT_FAILED: {stderr}")
    return parse_freezedetect(
        str(getattr(result, "stderr", "")),
        duration=duration,
    )


def validate_final_media(
    path: Path,
    *,
    media_info: object,
    fps: float,
    splice_windows: Iterable[tuple[float, float]] = (),
    run: Callable[[list[str]], object] = _run,
) -> dict[str, object]:
    duration = float(getattr(media_info, "duration", 0.0) or 0.0)
    video_duration = float(
        getattr(media_info, "video_duration", 0.0) or duration
    )
    audio_duration = float(
        getattr(media_info, "audio_duration", 0.0) or duration
    )
    tolerance = max(2.0 / fps, 0.05)
    if bool(getattr(media_info, "has_audio", False)):
        if audio_duration - video_duration > tolerance:
            raise MediaQualityError("VIDEO_ENDS_BEFORE_AUDIO")
        if video_duration - audio_duration > tolerance:
            raise MediaQualityError("AUDIO_VIDEO_DURATION_DRIFT")

    # Delivery QC is stricter than active-content trimming. One full black
    # frame at a splice is a visible flash, so scan at a one-frame threshold
    # even though edge trimming intentionally ignores shorter dark transients.
    strict_intervals = detect_black_intervals(
        path,
        fps=fps,
        minimum_black_frames=0.5,
        run=run,
    )
    window = resolve_active_window(
        duration=video_duration,
        fps=fps,
        black_intervals=strict_intervals,
    )
    edge_black_threshold = max(0.5 / fps, 0.001)
    if window.leading_black_duration >= edge_black_threshold:
        raise MediaQualityError("LEADING_BLACK_DETECTED")
    if window.trailing_black_duration >= edge_black_threshold:
        raise MediaQualityError("TRAILING_BLACK_DETECTED")
    normalized_splice_windows: list[tuple[float, float]] = []
    for index, raw in enumerate(splice_windows, start=1):
        try:
            start, end = float(raw[0]), float(raw[1])
        except (IndexError, TypeError, ValueError) as exc:
            raise MediaQualityError(
                f"INVALID_SPLICE_WINDOW_{index}"
            ) from exc
        if start < 0 or end < start or end > video_duration + tolerance:
            raise MediaQualityError(f"INVALID_SPLICE_WINDOW_{index}")
        normalized_splice_windows.append((start, end))

    for interval in window.internal_black_intervals:
        for start, end in normalized_splice_windows:
            if interval.end >= start - tolerance and interval.start <= end + tolerance:
                raise MediaQualityError("SPLICE_BOUNDARY_BLACK_DETECTED")
    freeze_intervals = detect_freeze_intervals(
        path,
        fps=fps,
        duration=video_duration,
        minimum_freeze_seconds=max(0.5, 2.0 / fps),
        run=run,
    )
    # Freeze intervals are diagnostic at this low-level carrier boundary.
    # The server QC engine applies the hard gate only when a compositor
    # manifest proves a generated/opaque carrier could have introduced the
    # freeze; an uploaded static tail or an intentional source hold is valid
    # content and must remain lineage-authorized.
    return {
        "status": "passed",
        "video_duration": round(video_duration, 6),
        "audio_duration": round(audio_duration, 6),
        "av_duration_delta": round(abs(video_duration - audio_duration), 6),
        "leading_black_duration": round(window.leading_black_duration, 6),
        "trailing_black_duration": round(window.trailing_black_duration, 6),
        "internal_black_intervals": [
            {"start": round(item.start, 6), "end": round(item.end, 6)}
            for item in window.internal_black_intervals
        ],
        "freeze_intervals": [
            {"start": round(item.start, 6), "end": round(item.end, 6)}
            for item in freeze_intervals
        ],
        "splice_windows_checked": [
            [round(start, 6), round(end, 6)]
            for start, end in normalized_splice_windows
        ],
        "black_scan": "low_resolution_one_frame_blackdetect",
        "freeze_scan": "low_resolution_freezedetect",
    }
