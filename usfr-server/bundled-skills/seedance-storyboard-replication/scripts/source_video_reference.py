from __future__ import annotations

"""Deterministically prepare a source-video segment for RunningHub videoUrls."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


MIN_REFERENCE_MS = 2_000
MAX_REFERENCE_MS = 15_000
_DURATION_TOLERANCE_MS = 100


class SourceVideoReferenceError(ValueError):
    pass


@dataclass(frozen=True)
class SourceVideoReference:
    path: Path
    source_video_sha256: str
    source_slice_sha256: str
    segment_id: str
    start_ms: int
    end_ms: int
    reused_source: bool


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SourceVideoReferenceError(f"{label} must be an integer number of milliseconds")
    return value


def _frozen_segment(
    segment_plan: Mapping[str, Any],
    segment_id: str,
) -> tuple[int, int]:
    segments = segment_plan.get("segments")
    if not isinstance(segments, list):
        raise SourceVideoReferenceError("the frozen segment_plan must contain segments")
    matches = [
        segment
        for segment in segments
        if isinstance(segment, Mapping) and segment.get("segment_id") == segment_id
    ]
    if len(matches) != 1:
        raise SourceVideoReferenceError("the requested segment_id must occur exactly once in the frozen segment_plan")
    segment = matches[0]
    start_ms = _require_integer(segment.get("start_ms"), "segment.start_ms")
    end_ms = _require_integer(segment.get("end_ms"), "segment.end_ms")
    if start_ms < 0 or end_ms <= start_ms:
        raise SourceVideoReferenceError("the frozen segment has an invalid reference window")
    duration_ms = end_ms - start_ms
    if not MIN_REFERENCE_MS <= duration_ms <= MAX_REFERENCE_MS:
        raise SourceVideoReferenceError("a RunningHub video reference must be 2-15 seconds")
    declared_duration = segment.get("duration_ms")
    if declared_duration is not None and _require_integer(declared_duration, "segment.duration_ms") != duration_ms:
        raise SourceVideoReferenceError("segment.duration_ms differs from its frozen start/end window")
    return start_ms, end_ms


def _probe_duration_ms(path: Path) -> int:
    executable = shutil.which("ffprobe")
    if executable is None:
        raise SourceVideoReferenceError("ffprobe is required to prepare a source video reference")
    result = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SourceVideoReferenceError(f"ffprobe could not read source video: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
        duration_seconds = float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SourceVideoReferenceError("ffprobe did not return a usable video duration") from error
    duration_ms = int(round(duration_seconds * 1_000))
    if duration_ms <= 0:
        raise SourceVideoReferenceError("source video duration must be positive")
    return duration_ms


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SourceVideoReferenceError(f"ffmpeg source reference slice failed: {result.stderr.strip()}")


def _write_receipt(path: Path, reference: SourceVideoReference) -> None:
    payload = {
        "schema_version": "usfr-source-video-reference/v1",
        "source_video_sha256": reference.source_video_sha256,
        "source_slice_sha256": reference.source_slice_sha256,
        "segment_id": reference.segment_id,
        "start_ms": reference.start_ms,
        "end_ms": reference.end_ms,
        "reused_source": reference.reused_source,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _matching_cached_reference(
    *,
    output_path: Path,
    receipt_path: Path,
    source_video_sha256: str,
    segment_id: str,
    start_ms: int,
    end_ms: int,
    probe_duration_ms: Callable[[Path], int],
) -> SourceVideoReference | None:
    if not output_path.is_file() or not receipt_path.is_file():
        return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(receipt, Mapping):
        return None
    expected = {
        "schema_version": "usfr-source-video-reference/v1",
        "source_video_sha256": source_video_sha256,
        "segment_id": segment_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "reused_source": False,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        return None
    slice_sha256 = _file_sha256(output_path)
    if receipt.get("source_slice_sha256") != slice_sha256:
        return None
    duration_ms = probe_duration_ms(output_path)
    if duration_ms > MAX_REFERENCE_MS or abs(duration_ms - (end_ms - start_ms)) > _DURATION_TOLERANCE_MS:
        return None
    return SourceVideoReference(
        path=output_path,
        source_video_sha256=source_video_sha256,
        source_slice_sha256=slice_sha256,
        segment_id=segment_id,
        start_ms=start_ms,
        end_ms=end_ms,
        reused_source=False,
    )


def materialize_source_video_reference(
    *,
    source_video: Path,
    segment_plan: Mapping[str, Any],
    segment_id: str,
    output_dir: Path,
    source_slot_id: str = "source_video",
    probe_duration_ms: Callable[[Path], int] = _probe_duration_ms,
    run_ffmpeg: Callable[[list[str]], None] = _run_ffmpeg,
) -> SourceVideoReference:
    """Return the exact frozen source window without creating any Provider task.

    Only the public ``source_video`` slot is admissible. Opaque UI and tail
    videos have their own assembly routes and cannot become a video reference.
    """

    if source_slot_id != "source_video":
        raise SourceVideoReferenceError("only source_video may be used as a video reference")
    source = Path(source_video)
    if not source.is_file():
        raise SourceVideoReferenceError(f"source video does not exist: {source}")
    normalized_segment_id = str(segment_id or "").strip()
    if not normalized_segment_id:
        raise SourceVideoReferenceError("segment_id is required")
    start_ms, end_ms = _frozen_segment(segment_plan, normalized_segment_id)
    source_duration_ms = probe_duration_ms(source)
    if end_ms > source_duration_ms + _DURATION_TOLERANCE_MS:
        raise SourceVideoReferenceError("the frozen reference window exceeds the source video duration")
    source_sha256 = _file_sha256(source)
    if start_ms == 0 and end_ms == source_duration_ms and source_duration_ms <= MAX_REFERENCE_MS:
        reference = SourceVideoReference(
            path=source,
            source_video_sha256=source_sha256,
            source_slice_sha256=source_sha256,
            segment_id=normalized_segment_id,
            start_ms=start_ms,
            end_ms=end_ms,
            reused_source=True,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_receipt(output_dir / f"source-reference-{normalized_segment_id}.json", reference)
        return reference

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"source-reference-{normalized_segment_id}.mp4"
    receipt_path = output_dir / f"source-reference-{normalized_segment_id}.json"
    cached = _matching_cached_reference(
        output_path=output_path,
        receipt_path=receipt_path,
        source_video_sha256=source_sha256,
        segment_id=normalized_segment_id,
        start_ms=start_ms,
        end_ms=end_ms,
        probe_duration_ms=probe_duration_ms,
    )
    if cached is not None:
        return cached
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise SourceVideoReferenceError("ffmpeg is required to prepare a source video reference")
    expected_duration_ms = end_ms - start_ms
    run_ffmpeg(
        [
            executable,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-ss",
            f"{start_ms / 1_000:.3f}",
            "-t",
            f"{expected_duration_ms / 1_000:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    if not output_path.is_file():
        raise SourceVideoReferenceError("ffmpeg did not create the source video reference")
    output_duration_ms = probe_duration_ms(output_path)
    if output_duration_ms > MAX_REFERENCE_MS:
        raise SourceVideoReferenceError("the generated source video reference exceeds 15 seconds")
    if abs(output_duration_ms - expected_duration_ms) > _DURATION_TOLERANCE_MS:
        raise SourceVideoReferenceError("the generated source video reference does not preserve the frozen timing window")
    reference = SourceVideoReference(
        path=output_path,
        source_video_sha256=source_sha256,
        source_slice_sha256=_file_sha256(output_path),
        segment_id=normalized_segment_id,
        start_ms=start_ms,
        end_ms=end_ms,
        reused_source=False,
    )
    _write_receipt(receipt_path, reference)
    return reference
