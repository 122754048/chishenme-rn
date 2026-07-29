from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

import timeline_splice  # noqa: E402


FFMPEG_AVAILABLE = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run_ffmpeg(*args: str) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


def _clip(
    path: Path,
    *,
    video_source: str,
    duration: float,
    frequency: int = 440,
) -> Path:
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        video_source,
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    )
    return path


def _write_contract(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _raw_frame_sha256(path: Path, frame_ms: int) -> str:
    """Hash the decoded RGB24 frame at a deterministic timestamp.

    The production validator uses the same FFmpeg raw-frame projection.  A
    container/file hash is not sufficient here because a generated UI video
    can be re-muxed without changing any visible pixels.
    """

    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ss",
            f"{frame_ms / 1000.0:.6f}",
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
    return hashlib.sha256(result.stdout).hexdigest()


def _state_digest(state: dict) -> str:
    return hashlib.sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _records_digest(records: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _state_row(media: Path, state: dict) -> dict:
    """Build a fully self-consistent state row for contract tests."""
    frame_sha = _raw_frame_sha256(media, int(state["frame_ms"]))
    ocr_records = [
        {
            "text": state["expected_text"][0],
            "bbox": state["expected_layout"][0]["bbox"],
        }
    ]
    layout_records = list(state["expected_layout"])
    return {
        "state_id": state["state_id"],
        "frame_ms": state["frame_ms"],
        "frame_sha256": frame_sha,
        "truth_state_sha256": _state_digest(state),
        "ocr_match_percent": 100,
        "layout_match_percent": 100,
        "ocr_evidence": {
            "input_sha256": frame_sha,
            "records": ocr_records,
            "records_sha256": _records_digest(ocr_records),
            "request_sha256": "1" * 64,
            "response_sha256": "2" * 64,
            "model_id": "ocr-test",
            "model_sha256": "3" * 64,
        },
        "layout_evidence": {
            "input_sha256": frame_sha,
            "records": layout_records,
            "records_sha256": _records_digest(layout_records),
            "renderer_sha256": "4" * 64,
        },
    }


def _multistate_contract_payload(media: Path, states: list[dict], *, render: dict | None = None) -> dict:
    truth = {"approved_copy": [text for state in states for text in state["expected_text"]], "states": states}
    rows = [_state_row(media, state) for state in states]
    render_contract = render or {
        "state_sequence": [state["state_id"] for state in states],
        "viewport": [180, 320],
    }
    media_sha = hashlib.sha256(media.read_bytes()).hexdigest()
    report = {
        "passed": True,
        "ocr_passed": True,
        "approved_copy_passed": True,
        "page_state_passed": True,
        "layout_passed": True,
        "media_sha256": media_sha,
        "ui_truth_card_sha256": _state_digest(truth),
        "ui_render_contract_sha256": _state_digest(render_contract),
        "ocr_match_percent": 100,
        "layout_match_percent": 100,
        "approved_copy_observed": truth["approved_copy"],
        "ocr_evidence": [
            {"frame_ms": row["frame_ms"], "sha256": row["frame_sha256"]}
            for row in rows
        ],
        "layout_evidence": [
            {"frame_ms": row["frame_ms"], "sha256": row["frame_sha256"]}
            for row in rows
        ],
        "state_evidence": rows,
    }
    return {
        "source_duration": 2.0,
        "target": {"width": 180, "height": 320, "fps": 30},
        "regions": [
            {
                "region_type": "generated_ui_demo",
                "source_start": 0.0,
                "source_end": 2.0,
                "media_path": str(media),
                "ui_truth_card": truth,
                "ui_render_contract": render_contract,
                "ui_qc_report": report,
            }
        ],
    }


@unittest.skipUnless(FFMPEG_AVAILABLE, "FFmpeg and FFprobe are required")
class TimelineSpliceRealMediaTest(unittest.TestCase):
    def test_transition_receipt_must_bind_exact_source_shell_digest(self):
        left = timeline_splice.TimelineRegion(
            kind="generated",
            source_start=0.0,
            source_end=1.0,
            media_path=Path("left.mp4"),
            transition_shell={
                "exit": {"type": "dissolve", "duration_seconds": 0.2}
            },
        )
        right = timeline_splice.TimelineRegion(
            kind="opaque_ui_demo",
            source_start=1.0,
            source_end=2.0,
            media_path=Path("right.mp4"),
            transition_shell={
                "entry": {"type": "dissolve", "duration_seconds": 0.2},
                "exit": {"type": "hard_cut"},
            },
        )
        with self.assertRaisesRegex(
            timeline_splice.TimelineSpliceError,
            "TRANSITION_RECEIPT_SOURCE_SHELL_MISMATCH",
        ):
            timeline_splice._apply_transition_receipts(
                [
                    {"transition_shell_applied": {}},
                    {"transition_shell_applied": {}},
                ],
                [left, right],
                [
                    {
                        "boundary_index": 0,
                        "rendered": True,
                        "source_shell_sha256": "0" * 64,
                    }
                ],
            )

    def test_one_frame_edge_black_is_trimmed_before_opaque_splice(self):
        """A single encoder frame of edge padding must not become a visible flash."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "one-frame-edge-black.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=180x320:r=30:d=0.033333",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=180x320:r=30:d=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=550:sample_rate=48000:duration=1.066666",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map",
                "[v]",
                "-map",
                "2:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(media),
            )
            info = timeline_splice.probe_media(media)
            active = timeline_splice.detect_active_window(
                media,
                duration=timeline_splice._video_duration(info),
                fps=30.0,
            )
            self.assertGreaterEqual(active.active_start, 1.0 / 30.0 - 0.01)

    def test_sparse_logo_on_black_is_not_misclassified_as_all_black(self):
        """A real black-background card with a small logo must remain active."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "sparse-logo-card.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=1080x1920:r=30:d=3",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-vf",
                "drawbox=x=(iw-20)/2:y=(ih-20)/2:w=20:h=20:color=white:t=fill:enable='between(t,1,2)'",
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-t",
                "3",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(media),
            )
            info = timeline_splice.probe_media(media)
            active = timeline_splice.detect_active_window(
                media,
                duration=timeline_splice._video_duration(info),
                fps=30.0,
            )
            self.assertAlmostEqual(active.active_start, 1.0, delta=0.05)
            self.assertAlmostEqual(active.active_end, 2.0, delta=0.05)

    def test_opaque_active_window_uses_replacement_fps_when_target_fps_differs(self):
        """A 60-fps replacement's one-frame edge black is measured at 60 fps, not target fps."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ui = root / "ui-60fps.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=180x320:r=60:d=0.016667",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=180x320:r=60:d=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=550:sample_rate=48000:duration=1.016667",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map",
                "[v]",
                "-map",
                "2:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(ui),
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 1.016667,
                    "target": {"width": 180, "height": 320, "fps": 24},
                    "regions": [
                        {
                            "region_type": "opaque_ui_demo",
                            "source_start": 0.0,
                            "source_end": 1.016667,
                            "media_path": str(ui),
                        }
                    ],
                },
            )
            manifest_path = root / "manifest.json"
            timeline_splice.splice_timeline(
                timeline_splice.load_contract(contract_path),
                root / "result.mp4",
                manifest_path,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            audit = manifest["placements"][0]["ui_media_audit"]
            self.assertGreaterEqual(audit["active_start"], 1.0 / 60.0 - 0.005)
            self.assertAlmostEqual(audit["active_duration"], 1.0, places=2)

    def test_rotated_mobile_upload_uses_display_dimensions_without_black_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = _clip(
                root / "encoded-landscape.mp4",
                video_source="testsrc2=s=320x180:r=30:d=1",
                duration=1,
            )
            rotated = root / "display-portrait.mp4"
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-display_rotation:v:0",
                    "90",
                    "-i",
                    str(raw),
                    "-c",
                    "copy",
                    str(rotated),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest("FFmpeg build cannot write display rotation metadata")
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 1.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "opaque_ui_demo",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(rotated),
                            "transition_shell": {
                                "entry": {"type": "hard_cut"},
                                "exit": {"type": "hard_cut"},
                            },
                        }
                    ],
                },
            )
            manifest_path = root / "manifest.json"
            timeline_splice.splice_timeline(
                timeline_splice.load_contract(contract_path),
                root / "result.mp4",
                manifest_path,
            )
            placement = json.loads(manifest_path.read_text(encoding="utf-8"))[
                "placements"
            ][0]
            self.assertEqual(placement["encoded_dimensions"], [320, 180])
            self.assertEqual(placement["display_rotation_deg"], 90)
            self.assertEqual(placement["display_dimensions"], [180, 320])

    def test_real_ui_entry_and_exit_transitions_render_and_pass_boundary_qc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = _clip(
                root / "before.mp4",
                video_source="color=c=red:s=180x320:r=30:d=1",
                duration=1,
                frequency=440,
            )
            ui = _clip(
                root / "ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=1",
                duration=1,
                frequency=550,
            )
            after = _clip(
                root / "after.mp4",
                video_source="color=c=blue:s=180x320:r=30:d=1",
                duration=1,
                frequency=660,
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 3.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(before),
                            "transition_shell": {
                                "exit": {"type": "dissolve", "duration_seconds": 0.2}
                            },
                        },
                        {
                            "region_type": "opaque_ui_demo",
                            "source_start": 1.0,
                            "source_end": 2.0,
                            "media_path": str(ui),
                            "transition_shell": {
                                "entry": {"type": "dissolve", "duration_seconds": 0.2},
                                "exit": {"type": "push_left", "duration_seconds": 0.2},
                            },
                        },
                        {
                            "region_type": "generated",
                            "source_start": 2.0,
                            "source_end": 3.0,
                            "media_path": str(after),
                            "transition_shell": {
                                "entry": {"type": "push_left", "duration_seconds": 0.2}
                            },
                        },
                    ],
                },
            )
            output = root / "result.mp4"
            manifest_path = root / "manifest.json"
            timeline_splice.splice_timeline(
                timeline_splice.load_contract(contract_path), output, manifest_path
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["final_media_qc"]["status"], "passed")
            self.assertEqual(len(manifest["transition_renders"]), 2)
            self.assertTrue(
                manifest["placements"][1]["transition_shell_applied"]["entry"]
            )
            self.assertTrue(
                manifest["placements"][1]["transition_shell_applied"]["exit"]
            )
            self.assertEqual(
                manifest["final_media_qc"]["splice_windows_checked"],
                [[0.8, 1.0], [1.6, 1.8]],
            )

    def test_opaque_mobile_ratio_normalization_sets_square_sar_before_transition(self):
        """Common 480x854 uploads must compose with a 9:16 target without SAR errors."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = _clip(
                root / "before.mp4",
                video_source="color=c=red:s=720x1280:r=30:d=1",
                duration=1,
                frequency=440,
            )
            # 480x854 is a frequent mobile export. Its 240:427 display ratio is
            # near, but not equal to, 9:16; scale/pad can otherwise leave the
            # normalized stream with a non-square SAR.
            ui = root / "ui-480x854.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "testsrc2=s=480x854:r=30:d=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=550:sample_rate=48000:duration=1",
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(ui),
            )
            after = _clip(
                root / "after.mp4",
                video_source="color=c=blue:s=720x1280:r=30:d=1",
                duration=1,
                frequency=660,
            )
            tail = root / "tail-480x854.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=480x854:r=30:d=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=770:sample_rate=48000:duration=1",
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(tail),
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 4.0,
                    "target": {"width": 720, "height": 1280, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(before),
                            "transition_shell": {
                                "exit": {"type": "dissolve", "duration_seconds": 0.2}
                            },
                        },
                        {
                            "region_type": "opaque_ui_demo",
                            "source_start": 1.0,
                            "source_end": 2.0,
                            "media_path": str(ui),
                            "transition_shell": {
                                "entry": {"type": "dissolve", "duration_seconds": 0.2},
                                "exit": {"type": "push_left", "duration_seconds": 0.2},
                            },
                        },
                        {
                            "region_type": "generated",
                            "source_start": 2.0,
                            "source_end": 3.0,
                            "media_path": str(after),
                            "transition_shell": {
                                "entry": {"type": "push_left", "duration_seconds": 0.2}
                            },
                        },
                        {
                            "region_type": "excluded_app_end_card",
                            "source_start": 3.0,
                            "source_end": 4.0,
                            "media_path": str(tail),
                            "transition_shell": {
                                "entry": {"type": "hard_cut"}
                            },
                        },
                    ],
                },
            )
            output = root / "result.mp4"
            manifest_path = root / "manifest.json"
            timeline_splice.splice_timeline(
                timeline_splice.load_contract(contract_path), output, manifest_path
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["final_media_qc"]["status"], "passed")
            ui_placement = manifest["placements"][1]
            self.assertEqual(ui_placement["display_dimensions"], [480, 854])
            self.assertEqual(ui_placement["normalized_media_duration"], 1.0)

    def test_full_frame_black_at_a_real_splice_boundary_blocks_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.mp4"
            right = root / "right.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=180x320:r=30:d=0.8",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=180x320:r=30:d=0.2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=1",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map",
                "[v]",
                "-map",
                "2:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(left),
            )
            _clip(
                right,
                video_source="color=c=blue:s=180x320:r=30:d=1",
                duration=1,
                frequency=660,
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 2.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(left),
                        },
                        {
                            "region_type": "generated",
                            "source_start": 1.0,
                            "source_end": 2.0,
                            "media_path": str(right),
                        },
                    ],
                },
            )
            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "SPLICE_BOUNDARY_BLACK_DETECTED",
            ):
                timeline_splice.splice_timeline(
                    timeline_splice.load_contract(contract_path),
                    root / "result.mp4",
                    root / "manifest.json",
                )

    def test_single_frame_black_flash_at_splice_boundary_blocks_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.mp4"
            right = root / "right.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=180x320:r=30:d=0.966667",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=180x320:r=30:d=0.033333",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=1",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map",
                "[v]",
                "-map",
                "2:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(left),
            )
            _clip(
                right,
                video_source="color=c=blue:s=180x320:r=30:d=1",
                duration=1,
                frequency=660,
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 2.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(left),
                        },
                        {
                            "region_type": "generated",
                            "source_start": 1.0,
                            "source_end": 2.0,
                            "media_path": str(right),
                        },
                    ],
                },
            )
            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "SPLICE_BOUNDARY_BLACK_DETECTED",
            ):
                timeline_splice.splice_timeline(
                    timeline_splice.load_contract(contract_path),
                    root / "result.mp4",
                    root / "manifest.json",
                )

    def test_supplied_ui_uses_active_duration_and_shifts_following_regions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = _clip(
                root / "before.mp4",
                video_source="color=c=red:s=180x320:r=30:d=1",
                duration=1,
                frequency=440,
            )
            ui = root / "ui.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "testsrc2=s=180x320:r=30:d=1.4",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=180x320:r=30:d=0.3",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=550:sample_rate=48000:duration=1.7",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map",
                "[v]",
                "-map",
                "2:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(ui),
            )
            after = _clip(
                root / "after.mp4",
                video_source="color=c=blue:s=180x320:r=30:d=1",
                duration=1,
                frequency=660,
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 3.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(before),
                        },
                        {
                            "region_type": "opaque_ui_demo",
                            "source_start": 1.0,
                            "source_end": 2.0,
                            "media_path": str(ui),
                            "transition_shell": {
                                "entry": {"type": "hard_cut"},
                                "exit": {"type": "hard_cut"},
                            },
                        },
                        {
                            "region_type": "generated",
                            "source_start": 2.0,
                            "source_end": 3.0,
                            "media_path": str(after),
                        },
                    ],
                },
            )
            output = root / "result.mp4"
            manifest_path = root / "manifest.json"
            timeline_splice.splice_timeline(
                timeline_splice.load_contract(contract_path), output, manifest_path
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            ui_placement = manifest["placements"][1]
            after_placement = manifest["placements"][2]
            self.assertAlmostEqual(ui_placement["effective_media_duration"], 1.4, places=2)
            self.assertAlmostEqual(after_placement["output_start"], 2.4, places=2)
            self.assertAlmostEqual(manifest["planned_output_duration"], 3.4, places=2)
            self.assertEqual(ui_placement["duration_policy"], "trim_to_active_content")
            self.assertIn("boundary_black_trim", ui_placement["allowed_normalization_operations"])
            self.assertNotIn("final_frame_padding", ui_placement["allowed_normalization_operations"])
            self.assertNotIn("audio_padding", ui_placement["allowed_normalization_operations"])

    def test_source_interval_media_duration_mismatch_blocks_contract_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_slice = _clip(
                root / "source-slice.mp4",
                video_source="testsrc2=s=180x320:r=30:d=1.3",
                duration=1.3,
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 1.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(source_slice),
                            "media_origin": "source_interval",
                            "assembly_policy": "splice_source_interval",
                        }
                    ],
                },
            )
            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "SOURCE_INTERVAL_DURATION_MISMATCH",
            ):
                timeline_splice.splice_timeline(
                    timeline_splice.load_contract(contract_path),
                    root / "result.mp4",
                    root / "manifest.json",
                )

    def test_opaque_aspect_mismatch_blocks_before_black_letterbox_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ui = _clip(
                root / "ui-wide.mp4",
                video_source="testsrc2=s=320x180:r=30:d=2",
                duration=2,
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 2.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "opaque_ui_demo",
                            "source_start": 0.0,
                            "source_end": 2.0,
                            "media_path": str(ui),
                            "transition_shell": {
                                "entry": {"type": "hard_cut"},
                                "exit": {"type": "hard_cut"},
                            },
                        }
                    ],
                },
            )
            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "OPAQUE_ASPECT_RATIO_MISMATCH",
            ):
                timeline_splice.splice_timeline(
                    timeline_splice.load_contract(contract_path),
                    root / "result.mp4",
                    root / "manifest.json",
                )

    def test_safe_opaque_cover_crop_is_used_instead_of_black_letterbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ui = _clip(
                root / "ui-near-portrait.mp4",
                video_source="testsrc2=s=190x320:r=30:d=1",
                duration=1,
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 1.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "opaque_ui_demo",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(ui),
                            "transition_shell": {
                                "entry": {"type": "hard_cut"},
                                "exit": {"type": "hard_cut"},
                            },
                        }
                    ],
                },
            )
            manifest_path = root / "manifest.json"
            timeline_splice.splice_timeline(
                timeline_splice.load_contract(contract_path),
                root / "result.mp4",
                manifest_path,
            )
            placement = json.loads(manifest_path.read_text(encoding="utf-8"))[
                "placements"
            ][0]
            self.assertEqual(placement["spatial_normalization"]["mode"], "cover_crop")
            self.assertLess(placement["spatial_normalization"]["crop_fraction"], 0.06)
            self.assertIn("spatial_crop", placement["allowed_normalization_operations"])
            self.assertNotIn("spatial_pad", placement["allowed_normalization_operations"])

    def test_short_ui_shifts_timeline_without_visible_freeze_or_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ui = _clip(
                root / "ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=1.8",
                duration=1.8,
            )
            following = _clip(
                root / "following.mp4",
                video_source="color=c=blue:s=180x320:r=30:d=1",
                duration=1,
                frequency=660,
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 3.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "opaque_ui_demo",
                            "source_start": 0.0,
                            "source_end": 2.0,
                            "media_path": str(ui),
                            "transition_shell": {
                                "entry": {"type": "hard_cut"},
                                "exit": {"type": "hard_cut"},
                            },
                        },
                        {
                            "region_type": "generated",
                            "source_start": 2.0,
                            "source_end": 3.0,
                            "media_path": str(following),
                        },
                    ],
                },
            )
            manifest_path = root / "manifest.json"
            timeline_splice.splice_timeline(
                timeline_splice.load_contract(contract_path),
                root / "result.mp4",
                manifest_path,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            ui_placement = manifest["placements"][0]
            following_placement = manifest["placements"][1]
            self.assertAlmostEqual(ui_placement["output_duration"], 1.8, places=2)
            self.assertAlmostEqual(following_placement["output_start"], 1.8, places=2)
            self.assertNotIn("final_frame_padding", ui_placement["allowed_normalization_operations"])
            self.assertNotIn("audio_padding", ui_placement["allowed_normalization_operations"])

    def test_tail_active_trim_and_real_transition_end_without_terminal_black(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = _clip(
                root / "main.mp4",
                video_source="color=c=red:s=180x320:r=30:d=1",
                duration=1,
            )
            tail = root / "tail.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=180x320:r=30:d=0.2",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=180x320:r=30:d=1",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=180x320:r=30:d=0.3",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=550:sample_rate=48000:duration=1.5",
                "-filter_complex",
                "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map",
                "[v]",
                "-map",
                "3:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(tail),
            )
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 2.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(main),
                            "transition_shell": {
                                "exit": {"type": "dissolve", "duration_seconds": 0.2}
                            },
                        },
                        {
                            "region_type": "excluded_app_end_card",
                            "source_start": 1.0,
                            "source_end": 2.0,
                            "media_path": str(tail),
                            "transition_shell": {
                                "entry": {"type": "dissolve", "duration_seconds": 0.2}
                            },
                        },
                    ],
                },
            )
            output = root / "result.mp4"
            manifest_path = root / "manifest.json"
            timeline_splice.splice_timeline(
                timeline_splice.load_contract(contract_path), output, manifest_path
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["final_media_qc"]["status"], "passed")
            self.assertEqual(
                manifest["placements"][-1]["duration_policy"],
                "trim_to_active_content",
            )
            self.assertTrue(
                manifest["placements"][-1]["transition_shell_applied"]["entry"]
            )
            self.assertLessEqual(
                manifest["final_media_qc"]["trailing_black_duration"], 2 / 30
            )

    def test_generated_ui_report_must_bind_truth_layout_and_ocr_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            media_sha = hashlib.sha256(media.read_bytes()).hexdigest()
            truth = {"approved_copy": ["Continue"]}
            render = {"page_state": "checkout", "viewport": [180, 320]}
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 2.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated_ui_demo",
                            "source_start": 0.0,
                            "source_end": 2.0,
                            "media_path": str(media),
                            "ui_truth_card": truth,
                            "ui_render_contract": render,
                            "ui_qc_report": {
                                "passed": True,
                                "ocr_passed": True,
                                "approved_copy_passed": True,
                                "page_state_passed": True,
                                "layout_passed": True,
                                "media_sha256": media_sha,
                                "ui_truth_card_sha256": "0" * 64,
                                "ui_render_contract_sha256": "1" * 64,
                                "ocr_match_percent": 100,
                                "layout_match_percent": 100,
                                "approved_copy_observed": ["Continue"],
                                "ocr_evidence": [{"frame_ms": 500, "sha256": "2" * 64}],
                                "layout_evidence": [{"frame_ms": 500, "sha256": "3" * 64}],
                            },
                        }
                    ],
                },
            )
            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "ui_truth_card_sha256",
            ):
                timeline_splice.load_contract(contract_path)

    def test_generated_ui_multistate_report_rejects_fabricated_decoded_frame_sha(self):
        """A state row must bind to pixels decoded from the actual UI video."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "generated-ui-states.mp4"
            _run_ffmpeg(
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=180x320:r=30:d=1",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=180x320:r=30:d=1",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map",
                "[v]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(media),
            )
            states = [
                {
                    "state_id": "home",
                    "frame_ms": 500,
                    "expected_text": ["Home"],
                    "expected_layout": [
                        {"text": "Home", "bbox": [10, 10, 80, 40]}
                    ],
                },
                {
                    "state_id": "result",
                    "frame_ms": 1500,
                    "expected_text": ["Done"],
                    "expected_layout": [
                        {"text": "Done", "bbox": [10, 10, 80, 40]}
                    ],
                },
            ]
            truth = {"approved_copy": ["Home", "Done"], "states": states}
            render = {"state_sequence": ["home", "result"], "viewport": [180, 320]}
            state_evidence = []
            for state in states:
                frame_sha = _raw_frame_sha256(media, state["frame_ms"])
                ocr_records = [
                    {"text": state["expected_text"][0], "bbox": state["expected_layout"][0]["bbox"]}
                ]
                layout_records = list(state["expected_layout"])
                state_evidence.append(
                    {
                        "state_id": state["state_id"],
                        "frame_ms": state["frame_ms"],
                        "frame_sha256": frame_sha,
                        "truth_state_sha256": _state_digest(state),
                        "ocr_match_percent": 100,
                        "layout_match_percent": 100,
                        "ocr_evidence": {
                            "input_sha256": frame_sha,
                            "records": ocr_records,
                            "records_sha256": _records_digest(ocr_records),
                            "request_sha256": "1" * 64,
                            "response_sha256": "2" * 64,
                            "model_id": "ocr-test",
                            "model_sha256": "3" * 64,
                        },
                        "layout_evidence": {
                            "input_sha256": frame_sha,
                            "records": layout_records,
                            "records_sha256": _records_digest(layout_records),
                            "renderer_sha256": "4" * 64,
                        },
                    }
                )
            # Tamper only the decoded-pixel binding.  The media/container SHA
            # remains correct, so a file-hash-only validator would incorrectly
            # accept this report.
            state_evidence[1]["frame_sha256"] = "f" * 64
            state_evidence[1]["ocr_evidence"]["input_sha256"] = "f" * 64
            state_evidence[1]["layout_evidence"]["input_sha256"] = "f" * 64
            media_sha = hashlib.sha256(media.read_bytes()).hexdigest()
            report = {
                "passed": True,
                "ocr_passed": True,
                "approved_copy_passed": True,
                "page_state_passed": True,
                "layout_passed": True,
                "media_sha256": media_sha,
                "ui_truth_card_sha256": _state_digest(truth),
                "ui_render_contract_sha256": _state_digest(render),
                "ocr_match_percent": 100,
                "layout_match_percent": 100,
                "approved_copy_observed": truth["approved_copy"],
                "ocr_evidence": [
                    {"frame_ms": item["frame_ms"], "sha256": item["frame_sha256"]}
                    for item in state_evidence
                ],
                "layout_evidence": [
                    {"frame_ms": item["frame_ms"], "sha256": item["frame_sha256"]}
                    for item in state_evidence
                ],
                "state_evidence": state_evidence,
            }
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 2.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated_ui_demo",
                            "source_start": 0.0,
                            "source_end": 2.0,
                            "media_path": str(media),
                            "ui_truth_card": truth,
                            "ui_render_contract": render,
                            "ui_qc_report": report,
                        }
                    ],
                },
            )
            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "decoded frame SHA-256",
            ):
                timeline_splice.load_contract(contract_path)

    def test_generated_ui_multistate_report_requires_one_to_one_truth_state_binding(self):
        """Missing/duplicate state evidence must block before media assembly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            states = [
                {
                    "state_id": "home",
                    "frame_ms": 500,
                    "expected_text": ["Home"],
                    "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
                },
                {
                    "state_id": "result",
                    "frame_ms": 1500,
                    "expected_text": ["Done"],
                    "expected_layout": [{"text": "Done", "bbox": [10, 10, 80, 40]}],
                },
            ]
            truth = {"approved_copy": ["Home", "Done"], "states": states}
            render = {"state_sequence": ["home", "result"], "viewport": [180, 320]}
            # Deliberately provide only one evidence row and bind it to the
            # wrong truth state.  This should fail even if all summary flags
            # and the container SHA are self-consistent.
            state = states[0]
            frame_sha = _raw_frame_sha256(media, state["frame_ms"])
            ocr_records = [{"text": "Home", "bbox": [10, 10, 80, 40]}]
            layout_records = list(state["expected_layout"])
            row = {
                "state_id": "wrong-state",
                "frame_ms": state["frame_ms"],
                "frame_sha256": frame_sha,
                "truth_state_sha256": _state_digest(state),
                "ocr_match_percent": 100,
                "layout_match_percent": 100,
                "ocr_evidence": {
                    "input_sha256": frame_sha,
                    "records": ocr_records,
                    "records_sha256": _records_digest(ocr_records),
                    "request_sha256": "1" * 64,
                    "response_sha256": "2" * 64,
                    "model_id": "ocr-test",
                    "model_sha256": "3" * 64,
                },
                "layout_evidence": {
                    "input_sha256": frame_sha,
                    "records": layout_records,
                    "records_sha256": _records_digest(layout_records),
                    "renderer_sha256": "4" * 64,
                },
            }
            media_sha = hashlib.sha256(media.read_bytes()).hexdigest()
            report = {
                "passed": True,
                "ocr_passed": True,
                "approved_copy_passed": True,
                "page_state_passed": True,
                "layout_passed": True,
                "media_sha256": media_sha,
                "ui_truth_card_sha256": _state_digest(truth),
                "ui_render_contract_sha256": _state_digest(render),
                "ocr_match_percent": 100,
                "layout_match_percent": 100,
                "approved_copy_observed": truth["approved_copy"],
                "ocr_evidence": [{"frame_ms": 500, "sha256": frame_sha}],
                "layout_evidence": [{"frame_ms": 500, "sha256": frame_sha}],
                "state_evidence": [row],
            }
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 2.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated_ui_demo",
                            "source_start": 0.0,
                            "source_end": 2.0,
                            "media_path": str(media),
                            "ui_truth_card": truth,
                            "ui_render_contract": render,
                            "ui_qc_report": report,
                        }
                    ],
                },
            )
            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "state evidence.*state_id",
            ):
                timeline_splice.load_contract(contract_path)

    def test_generated_ui_multistate_report_with_bound_frame_and_records_passes(self):
        """A complete state receipt is accepted and remains available to splice."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="color=c=green:s=180x320:r=30:d=1",
                duration=1,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
            }
            truth = {"approved_copy": ["Home"], "states": [state]}
            render = {"state_sequence": ["home"], "viewport": [180, 320]}
            frame_sha = _raw_frame_sha256(media, state["frame_ms"])
            ocr_records = [{"text": "Home", "bbox": [10, 10, 80, 40]}]
            layout_records = list(state["expected_layout"])
            row = {
                "state_id": "home",
                "frame_ms": 500,
                "frame_sha256": frame_sha,
                "truth_state_sha256": _state_digest(state),
                "ocr_match_percent": 100,
                "layout_match_percent": 100,
                "ocr_evidence": {
                    "input_sha256": frame_sha,
                    "records": ocr_records,
                    "records_sha256": _records_digest(ocr_records),
                    "request_sha256": "1" * 64,
                    "response_sha256": "2" * 64,
                    "model_id": "ocr-test",
                    "model_sha256": "3" * 64,
                },
                "layout_evidence": {
                    "input_sha256": frame_sha,
                    "records": layout_records,
                    "records_sha256": _records_digest(layout_records),
                },
            }
            media_sha = hashlib.sha256(media.read_bytes()).hexdigest()
            contract_path = _write_contract(
                root / "timeline.json",
                {
                    "source_duration": 1.0,
                    "target": {"width": 180, "height": 320, "fps": 30},
                    "regions": [
                        {
                            "region_type": "generated_ui_demo",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "media_path": str(media),
                            "ui_truth_card": truth,
                            "ui_render_contract": render,
                            "ui_qc_report": {
                                "passed": True,
                                "ocr_passed": True,
                                "approved_copy_passed": True,
                                "page_state_passed": True,
                                "layout_passed": True,
                                "media_sha256": media_sha,
                                "ui_truth_card_sha256": _state_digest(truth),
                                "ui_render_contract_sha256": _state_digest(render),
                                "ocr_match_percent": 100,
                                "layout_match_percent": 100,
                                "approved_copy_observed": ["Home"],
                                "ocr_evidence": [{"frame_ms": 500, "sha256": frame_sha}],
                                "layout_evidence": [{"frame_ms": 500, "sha256": frame_sha}],
                                "state_evidence": [row],
                            },
                        }
                    ],
                },
            )
            contract = timeline_splice.load_contract(contract_path)
            self.assertEqual(contract.regions[0].ui_truth_card["states"][0]["state_id"], "home")

    def test_generated_ui_multistate_normalizes_logical_layout_to_rendered_viewport(self):
        """A 2x rendered UI must compare OCR boxes in the declared coordinate space."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui-2x.mp4",
                video_source="color=c=green:s=360x640:r=30:d=1",
                duration=1,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"element_id": "title", "text": "Home", "bbox": [10, 10, 80, 40]}],
            }
            truth = {"approved_copy": ["Home"], "states": [state]}
            render = {
                "state_sequence": ["home"],
                "viewport": [180, 320],
                "rendered_viewport": [360, 640],
            }
            frame_sha = _raw_frame_sha256(media, state["frame_ms"])
            ocr_records = [{"text": "Home", "bbox": [20, 20, 160, 80]}]
            layout_records = [{"element_id": "title", "text": "Home", "bbox": [20, 20, 160, 80]}]
            row = {
                "state_id": "home",
                "frame_ms": 500,
                "frame_sha256": frame_sha,
                "truth_state_sha256": _state_digest(state),
                "ocr_match_percent": 100,
                "layout_match_percent": 100,
                "ocr_evidence": {
                    "input_sha256": frame_sha,
                    "records": ocr_records,
                    "records_sha256": _records_digest(ocr_records),
                    "request_sha256": "1" * 64,
                    "response_sha256": "2" * 64,
                    "model_id": "ocr-test",
                    "model_sha256": "3" * 64,
                },
                "layout_evidence": {
                    "input_sha256": frame_sha,
                    "records": layout_records,
                    "records_sha256": _records_digest(layout_records),
                },
            }
            media_sha = hashlib.sha256(media.read_bytes()).hexdigest()
            payload = {
                "source_duration": 1.0,
                "target": {"width": 360, "height": 640, "fps": 30},
                "regions": [
                    {
                        "region_type": "generated_ui_demo",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "media_path": str(media),
                        "ui_truth_card": truth,
                        "ui_render_contract": render,
                        "ui_qc_report": {
                            "passed": True,
                            "ocr_passed": True,
                            "approved_copy_passed": True,
                            "page_state_passed": True,
                            "layout_passed": True,
                            "media_sha256": media_sha,
                            "ui_truth_card_sha256": _state_digest(truth),
                            "ui_render_contract_sha256": _state_digest(render),
                            "ocr_match_percent": 100,
                            "layout_match_percent": 100,
                            "approved_copy_observed": ["Home"],
                            "ocr_evidence": [{"frame_ms": 500, "sha256": frame_sha}],
                            "layout_evidence": [{"frame_ms": 500, "sha256": frame_sha}],
                            "state_evidence": [row],
                        },
                    }
                ],
            }
            contract = timeline_splice.load_contract(_write_contract(root / "timeline-2x.json", payload))
            self.assertEqual(contract.regions[0].kind, "generated_ui_demo")

    def test_generated_ui_rejects_render_contract_state_sequence_mismatch(self):
        """A sidecar cannot claim a different page order than the render contract."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            states = [
                {
                    "state_id": "home",
                    "frame_ms": 500,
                    "expected_text": ["Home"],
                    "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
                },
                {
                    "state_id": "result",
                    "frame_ms": 1500,
                    "expected_text": ["Done"],
                    "expected_layout": [{"text": "Done", "bbox": [10, 10, 80, 40]}],
                },
            ]
            payload = _multistate_contract_payload(
                media,
                states,
                render={"state_sequence": ["home", "settings"], "viewport": [180, 320]},
            )
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "state_sequence"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_multistate_requires_render_viewport(self):
        """Layout percentages are meaningless without an explicit target viewport."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
            }
            payload = _multistate_contract_payload(
                media,
                [state],
                render={"state_sequence": ["home"]},
            )
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "viewport"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_viewport_aspect_must_match_decoded_video(self):
        """A landscape layout contract cannot certify portrait UI pixels."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
            }
            payload = _multistate_contract_payload(
                media,
                [state],
                render={"state_sequence": ["home"], "viewport": [320, 180]},
            )
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "viewport.*aspect"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_rejects_navigation_to_state_without_source_button(self):
        """Every recorded navigation must be backed by a visible source control."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            states = [
                {
                    "state_id": "home",
                    "frame_ms": 500,
                    "expected_text": ["Home"],
                    "expected_layout": [{"element_id": "title", "role": "label", "text": "Home", "bbox": [10, 10, 80, 40]}],
                },
                {
                    "state_id": "result",
                    "frame_ms": 1500,
                    "expected_text": ["Done"],
                    "expected_layout": [{"element_id": "result", "role": "label", "text": "Done", "bbox": [10, 10, 80, 40]}],
                },
            ]
            payload = _multistate_contract_payload(
                media,
                states,
                render={
                    "state_sequence": ["home", "result"],
                    "viewport": [180, 320],
                    "navigation": [
                        {"from_state": "home", "to_state": "result", "control_id": "next", "action": "tap", "at_ms": 900}
                    ],
                },
            )
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "navigation.*control"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_rejects_invalid_layout_geometry(self):
        """A matching sidecar must not authorize a box outside the target viewport."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"text": "Home", "bbox": [170, 310, 190, 330]}],
            }
            payload = _multistate_contract_payload(media, [state], render={"state_sequence": ["home"], "viewport": [180, 320]})
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "bbox|geometry|viewport"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_rejects_top_level_frame_evidence_not_bound_to_state_rows(self):
        """Summary frame rows must be the exact projection of per-state receipts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            states = [
                {
                    "state_id": "home",
                    "frame_ms": 500,
                    "expected_text": ["Home"],
                    "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
                },
                {
                    "state_id": "result",
                    "frame_ms": 1500,
                    "expected_text": ["Done"],
                    "expected_layout": [{"text": "Done", "bbox": [10, 10, 80, 40]}],
                },
            ]
            payload = _multistate_contract_payload(media, states)
            payload["regions"][0]["ui_qc_report"]["ocr_evidence"] = payload["regions"][0]["ui_qc_report"]["ocr_evidence"][:1]
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "top-level|frame evidence|state"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_rejects_unbound_ocr_receipt_in_multistate_state(self):
        """State receipts must identify the OCR request/model, not just records and hashes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
            }
            payload = _multistate_contract_payload(media, [state])
            for field in ("request_sha256", "response_sha256", "model_id", "model_sha256"):
                payload["regions"][0]["ui_qc_report"]["state_evidence"][0]["ocr_evidence"].pop(field, None)
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "OCR.*evidence|model|request"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_rejects_approved_copy_not_present_in_any_state(self):
        """A script-side copy claim cannot hide text absent from rendered states."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
            }
            payload = _multistate_contract_payload(media, [state])
            truth = payload["regions"][0]["ui_truth_card"]
            truth["approved_copy"] = ["Home", "Hidden"]
            report = payload["regions"][0]["ui_qc_report"]
            report["approved_copy_observed"] = ["Home", "Hidden"]
            report["ui_truth_card_sha256"] = _state_digest(truth)
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "approved_copy"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_accepts_encoded_ocr_input_with_decoded_frame_binding(self):
        """OCR may hash encoded PNG/JPEG bytes while the row still binds raw pixels."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
            }
            payload = _multistate_contract_payload(media, [state])
            row = payload["regions"][0]["ui_qc_report"]["state_evidence"][0]
            raw_frame_sha = row["frame_sha256"]
            for kind in ("ocr_evidence", "layout_evidence"):
                receipt = row[kind]
                receipt["decoded_frame_sha256"] = raw_frame_sha
                receipt["input_sha256"] = "9" * 64
            loaded = timeline_splice.load_contract(
                _write_contract(root / "timeline.json", payload)
            )
            self.assertEqual(loaded.regions[0].kind, "generated_ui_demo")

    def test_generated_ui_rejects_replacement_characters_in_truth_text(self):
        """Replacement/control glyphs are a hard no-乱码 gate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = _clip(
                root / "generated-ui.mp4",
                video_source="testsrc2=s=180x320:r=30:d=2",
                duration=2,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Ho\ufffdme"],
                "expected_layout": [{"text": "Ho\ufffdme", "bbox": [10, 10, 80, 40]}],
            }
            payload = _multistate_contract_payload(media, [state])
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "replacement|control|text"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_inside_timeline_requires_both_source_transition_shells(self):
        """An interior generated UI interval cannot silently hard-cut at either edge."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = _clip(
                root / "left.mp4",
                video_source="color=c=red:s=180x320:r=30:d=1",
                duration=1,
            )
            ui = _clip(
                root / "ui.mp4",
                video_source="color=c=green:s=180x320:r=30:d=1",
                duration=1,
            )
            right = _clip(
                root / "right.mp4",
                video_source="color=c=blue:s=180x320:r=30:d=1",
                duration=1,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
            }
            payload = _multistate_contract_payload(ui, [state], render={"state_sequence": ["home"], "viewport": [180, 320]})
            ui_region = payload["regions"][0]
            ui_region["source_start"] = 1.0
            ui_region["source_end"] = 2.0
            payload["source_duration"] = 3.0
            payload["regions"] = [
                {"region_type": "generated", "source_start": 0.0, "source_end": 1.0, "media_path": str(left)},
                ui_region,
                {"region_type": "generated", "source_start": 2.0, "source_end": 3.0, "media_path": str(right)},
            ]
            with self.assertRaisesRegex(timeline_splice.TimelineSpliceError, "transition_shell entry"):
                timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))

    def test_generated_ui_source_transition_shells_render_without_black_splice(self):
        """Both UI boundaries are compositor-rendered and pass the black-frame gate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = _clip(
                root / "left.mp4",
                video_source="color=c=red:s=180x320:r=30:d=1",
                duration=1,
            )
            ui = _clip(
                root / "ui.mp4",
                video_source="color=c=green:s=180x320:r=30:d=1",
                duration=1,
            )
            right = _clip(
                root / "right.mp4",
                video_source="color=c=blue:s=180x320:r=30:d=1",
                duration=1,
            )
            state = {
                "state_id": "home",
                "frame_ms": 500,
                "expected_text": ["Home"],
                "expected_layout": [{"text": "Home", "bbox": [10, 10, 80, 40]}],
            }
            payload = _multistate_contract_payload(ui, [state], render={"state_sequence": ["home"], "viewport": [180, 320]})
            ui_region = payload["regions"][0]
            ui_region.update(
                {
                    "source_start": 1.0,
                    "source_end": 2.0,
                    "transition_shell": {
                        "entry": {"type": "dissolve", "duration_seconds": 0.2},
                        "exit": {"type": "dissolve", "duration_seconds": 0.2},
                    },
                }
            )
            payload["source_duration"] = 3.0
            payload["regions"] = [
                {"region_type": "generated", "source_start": 0.0, "source_end": 1.0, "media_path": str(left)},
                ui_region,
                {"region_type": "generated", "source_start": 2.0, "source_end": 3.0, "media_path": str(right)},
            ]
            contract = timeline_splice.load_contract(_write_contract(root / "timeline.json", payload))
            output = root / "result.mp4"
            manifest_path = root / "manifest.json"
            timeline_splice.splice_timeline(contract, output, manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            ui_placement = manifest["placements"][1]
            self.assertTrue(ui_placement["transition_shell_applied"]["entry"])
            self.assertTrue(ui_placement["transition_shell_applied"]["exit"])
            self.assertEqual(len(manifest["transition_renders"]), 2)
            self.assertEqual(manifest["final_media_qc"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
