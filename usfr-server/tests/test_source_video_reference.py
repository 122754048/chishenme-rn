from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from source_video_reference import (  # noqa: E402
    SourceVideoReferenceError,
    materialize_source_video_reference,
)


def _plan(*segments: dict[str, object]) -> dict[str, object]:
    return {"segments": list(segments)}


def _segment(segment_id: str, start_ms: int, end_ms: int) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": end_ms - start_ms,
        "cut_ids": [f"C{segment_id[-2:]}"],
    }


def test_reuses_complete_short_source_when_the_frozen_segment_matches_it(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"complete-short-source")
    commands: list[list[str]] = []

    result = materialize_source_video_reference(
        source_video=source,
        segment_plan=_plan(_segment("S01", 0, 8_000)),
        segment_id="S01",
        output_dir=tmp_path / "references",
        probe_duration_ms=lambda _: 8_000,
        run_ffmpeg=lambda command: commands.append(command),
    )

    assert result.path == source
    assert result.reused_source is True
    assert result.source_video_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.source_slice_sha256 == result.source_video_sha256
    assert commands == []


def test_materializes_each_long_source_segment_at_its_exact_frozen_window(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"thirty-second-source")
    commands: list[list[str]] = []

    def run_ffmpeg(command: list[str]) -> None:
        commands.append(command)
        Path(command[-1]).write_bytes(f"slice-{len(commands)}".encode("ascii"))

    plan = _plan(_segment("S01", 0, 15_000), _segment("S02", 15_000, 30_000))
    duration_by_path = {
        source: 30_000,
        tmp_path / "references" / "source-reference-S01.mp4": 15_000,
        tmp_path / "references" / "source-reference-S02.mp4": 15_000,
    }
    probe_duration_ms = lambda path: duration_by_path[Path(path)]

    first = materialize_source_video_reference(
        source_video=source,
        segment_plan=plan,
        segment_id="S01",
        output_dir=tmp_path / "references",
        probe_duration_ms=probe_duration_ms,
        run_ffmpeg=run_ffmpeg,
    )
    second = materialize_source_video_reference(
        source_video=source,
        segment_plan=plan,
        segment_id="S02",
        output_dir=tmp_path / "references",
        probe_duration_ms=probe_duration_ms,
        run_ffmpeg=run_ffmpeg,
    )

    assert [(item.segment_id, item.start_ms, item.end_ms) for item in (first, second)] == [
        ("S01", 0, 15_000),
        ("S02", 15_000, 30_000),
    ]
    assert [command[command.index("-ss") + 1] for command in commands] == ["0.000", "15.000"]
    assert [command[command.index("-t") + 1] for command in commands] == ["15.000", "15.000"]
    assert all(item.path.is_file() for item in (first, second))


def test_reuses_an_existing_matching_frozen_slice_without_running_ffmpeg_again(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"thirty-second-source")
    commands: list[list[str]] = []
    reference_path = tmp_path / "references" / "source-reference-S01.mp4"

    def run_ffmpeg(command: list[str]) -> None:
        commands.append(command)
        Path(command[-1]).write_bytes(b"frozen-slice")

    def probe_duration_ms(path: Path) -> int:
        return 30_000 if Path(path) == source else 8_000

    plan = _plan(_segment("S01", 0, 8_000))
    first = materialize_source_video_reference(
        source_video=source,
        segment_plan=plan,
        segment_id="S01",
        output_dir=tmp_path / "references",
        probe_duration_ms=probe_duration_ms,
        run_ffmpeg=run_ffmpeg,
    )
    second = materialize_source_video_reference(
        source_video=source,
        segment_plan=plan,
        segment_id="S01",
        output_dir=tmp_path / "references",
        probe_duration_ms=probe_duration_ms,
        run_ffmpeg=run_ffmpeg,
    )

    assert first.path == reference_path
    assert second == first
    assert len(commands) == 1


def test_rejects_video_reference_windows_over_fifteen_seconds_before_ffmpeg(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    commands: list[list[str]] = []

    with pytest.raises(SourceVideoReferenceError, match="2-15 seconds"):
        materialize_source_video_reference(
            source_video=source,
            segment_plan=_plan(_segment("S01", 0, 15_001)),
            segment_id="S01",
            output_dir=tmp_path / "references",
            probe_duration_ms=lambda _: 16_000,
            run_ffmpeg=lambda command: commands.append(command),
        )

    assert commands == []


def test_rejects_opaque_media_as_a_video_reference_source(tmp_path: Path) -> None:
    source = tmp_path / "ui-operation.mp4"
    source.write_bytes(b"opaque-ui")

    with pytest.raises(SourceVideoReferenceError, match="source_video"):
        materialize_source_video_reference(
            source_video=source,
            source_slot_id="ui_operation_video",
            segment_plan=_plan(_segment("S01", 0, 8_000)),
            segment_id="S01",
            output_dir=tmp_path / "references",
            probe_duration_ms=lambda _: 8_000,
        )
