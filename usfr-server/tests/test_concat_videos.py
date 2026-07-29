from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from concat_videos import (  # noqa: E402
    ConcatError,
    MediaInfo,
    TransitionBoundary,
    _run,
    _run_ffmpeg_concat,
    _compatible_for_copy,
    build_transition_filter_graph,
    concat_segments,
    probe_media,
    render_transition_segments,
)


def compatible_info(path: str = "a.mp4") -> MediaInfo:
    return MediaInfo(
        path=Path(path),
        has_video=True,
        has_audio=True,
        duration=2.0,
        video_codec="h264",
        audio_codec="aac",
        width=180,
        height=320,
        frame_rate="30/1",
        video_time_base="1/90000",
        pixel_format="yuv420p",
        video_start_time=0.0,
        video_duration=2.0,
        audio_sample_rate=48000,
        audio_channel_layout="stereo",
        audio_time_base="1/48000",
        audio_start_time=0.0,
        audio_duration=2.0,
    )


class ConcatCompatibilityTest(unittest.TestCase):
    def test_ffmpeg_subprocess_uses_explicit_utf8_for_multilingual_metadata(self):
        with patch(
            "concat_videos.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""),
        ) as run:
            _run(["ffprobe", "素材.mp4"])

        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_probe_reports_display_dimensions_from_rotation_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            media_path = Path(tmp) / "rotated.mp4"
            media_path.write_bytes(b"probe-fixture")
            payload = {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 320,
                        "height": 180,
                        "avg_frame_rate": "30/1",
                        "time_base": "1/90000",
                        "pix_fmt": "yuv420p",
                        "duration": "1.0",
                        "side_data_list": [{"rotation": 90}],
                    },
                    {
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "48000",
                        "channel_layout": "stereo",
                        "time_base": "1/48000",
                        "duration": "1.0",
                    },
                ],
                "format": {"duration": "1.0"},
            }
            with patch(
                "concat_videos._run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(payload),
                    stderr="",
                ),
            ):
                info = probe_media(media_path)

        self.assertEqual((info.width, info.height), (320, 180))
        self.assertEqual(info.rotation_deg, 90)
        self.assertEqual((info.display_width, info.display_height), (180, 320))

    def test_probe_uses_video_duration_ts_instead_of_longer_container_audio(self):
        """AAC/container overhang must never become the visual endpoint."""

        with tempfile.TemporaryDirectory() as tmp:
            media_path = Path(tmp) / "audio-overhang.mp4"
            media_path.write_bytes(b"probe-fixture")
            payload = {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 180,
                        "height": 320,
                        "avg_frame_rate": "30/1",
                        "time_base": "1/90000",
                        "duration_ts": "90000",
                        "pix_fmt": "yuv420p",
                    },
                    {
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "48000",
                        "channel_layout": "stereo",
                        "time_base": "1/48000",
                        "duration": "1.5",
                    },
                ],
                "format": {"duration": "1.5"},
            }
            with patch(
                "concat_videos._run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(payload),
                    stderr="",
                ),
            ):
                info = probe_media(media_path)

        self.assertEqual(info.duration, 1.5)
        self.assertEqual(info.video_duration, 1.0)
        self.assertEqual(info.audio_duration, 1.5)

    def test_full_signature_allows_copy(self):
        first = compatible_info("a.mp4")
        second = replace(first, path=Path("b.mp4"))
        self.assertTrue(_compatible_for_copy([first, second]))

    def test_video_signature_mismatch_rejects_copy(self):
        first = compatible_info("a.mp4")
        for field, value in (
            ("frame_rate", "25/1"),
            ("video_time_base", "1/12800"),
            ("pixel_format", "yuv444p"),
            ("video_start_time", 0.2),
            ("sample_aspect_ratio", "40:41"),
        ):
            with self.subTest(field=field):
                self.assertFalse(
                    _compatible_for_copy(
                        [first, replace(first, path=Path("b.mp4"), **{field: value})]
                    )
                )

    def test_display_rotation_mismatch_rejects_stream_copy(self):
        first = replace(
            compatible_info("a.mp4"),
            width=320,
            height=180,
            rotation_deg=90,
            display_width=180,
            display_height=320,
        )
        second = replace(
            first,
            path=Path("b.mp4"),
            rotation_deg=0,
            display_width=320,
            display_height=180,
        )
        self.assertFalse(_compatible_for_copy([first, second]))

    def test_normalization_uses_display_dimensions_for_rotated_first_input(self):
        first = replace(
            compatible_info("a.mp4"),
            width=320,
            height=180,
            rotation_deg=90,
            display_width=180,
            display_height=320,
        )
        second = replace(first, path=Path("b.mp4"), video_codec="hevc")
        final = replace(
            first,
            path=Path("result.mp4"),
            duration=4.0,
            video_duration=4.0,
            audio_duration=4.0,
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "concat_videos.probe_media",
            side_effect=(first, second, final),
        ), patch(
            "concat_videos._normalize_segment",
            side_effect=lambda _input, output, **_kwargs: output,
        ) as normalize, patch(
            "concat_videos._run_ffmpeg_concat"
        ):
            concat_segments(
                [first.path, second.path],
                Path(tmp) / "result.mp4",
                expect_audio=True,
            )

        self.assertEqual(normalize.call_args_list[0].kwargs["width"], 180)
        self.assertEqual(normalize.call_args_list[0].kwargs["height"], 320)

    def test_concat_rebases_pts_and_audio_instead_of_stream_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            list_path = root / "concat.txt"
            list_path.write_text(
                f"file '{root / 'a.mp4'}'\nfile '{root / 'b.mp4'}'\n",
                encoding="utf-8",
            )
            with patch(
                "concat_videos._run",
                return_value=SimpleNamespace(returncode=0, stderr=""),
            ) as run:
                _run_ffmpeg_concat(list_path, root / "result.mp4", include_audio=True)
        command = " ".join(str(item) for item in run.call_args.args[0]).lower()
        self.assertIn("-filter_complex", command)
        self.assertIn("setpts=pts-startpts", command)
        self.assertIn("asetpts=pts-startpts", command)
        self.assertNotIn("-c copy", command)

    def test_audio_signature_or_av_duration_mismatch_rejects_copy(self):
        first = compatible_info("a.mp4")
        for field, value in (
            ("audio_sample_rate", 44100),
            ("audio_channel_layout", "mono"),
            ("audio_time_base", "1/44100"),
            ("audio_start_time", 0.1),
            ("audio_duration", 2.3),
        ):
            with self.subTest(field=field):
                self.assertFalse(
                    _compatible_for_copy(
                        [first, replace(first, path=Path("b.mp4"), **{field: value})]
                    )
                )

    def test_concat_rejects_per_segment_av_duration_drift_before_offsets_cancel(self):
        first = replace(
            compatible_info("a.mp4"),
            duration=1.2,
            video_duration=1.0,
            audio_duration=1.2,
        )
        second = replace(
            compatible_info("b.mp4"),
            duration=1.0,
            video_duration=1.0,
            audio_duration=0.8,
        )
        final = replace(
            compatible_info("result.mp4"),
            duration=2.0,
            video_duration=2.0,
            audio_duration=2.0,
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "concat_videos.probe_media",
            side_effect=(first, second, final),
        ), patch(
            "concat_videos._normalize_segment",
            side_effect=lambda _input, output, **_kwargs: output,
        ), patch("concat_videos._run_ffmpeg_concat"):
            with self.assertRaisesRegex(
                ConcatError,
                "SEGMENT_AUDIO_VIDEO_DURATION_MISMATCH",
            ):
                concat_segments(
                    [first.path, second.path],
                    Path(tmp) / "result.mp4",
                    expect_audio=True,
                )

    def test_concat_rejects_per_segment_av_start_drift_before_rebasing(self):
        first = replace(
            compatible_info("a.mp4"),
            duration=1.0,
            video_duration=1.0,
            audio_duration=1.0,
            audio_start_time=0.2,
        )
        second = replace(
            compatible_info("b.mp4"),
            duration=1.0,
            video_duration=1.0,
            audio_duration=1.0,
        )
        final = replace(
            compatible_info("result.mp4"),
            duration=2.0,
            video_duration=2.0,
            audio_duration=2.0,
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "concat_videos.probe_media",
            side_effect=(first, second, final),
        ), patch(
            "concat_videos._normalize_segment",
            side_effect=lambda _input, output, **_kwargs: output,
        ), patch("concat_videos._run_ffmpeg_concat"):
            with self.assertRaisesRegex(
                ConcatError,
                "SEGMENT_AUDIO_VIDEO_START_MISMATCH",
            ):
                concat_segments(
                    [first.path, second.path],
                    Path(tmp) / "result.mp4",
                    expect_audio=True,
                )

    def test_hard_cut_concat_rejects_short_audio_instead_of_truncating_picture(self):
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            self.skipTest("ffmpeg/ffprobe are unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            segments = []
            for index, (color, audio_duration) in enumerate(
                (("red", 0.6), ("blue", 1.0)),
                start=1,
            ):
                path = root / f"segment-{index}.mp4"
                result = _run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c={color}:s=180x320:r=30:d=1",
                        "-f",
                        "lavfi",
                        "-i",
                        f"sine=frequency={440 + index * 110}:sample_rate=48000:d={audio_duration}",
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        str(path),
                    ]
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                segments.append(path)

            with self.assertRaisesRegex(
                ConcatError,
                "SEGMENT_AUDIO_VIDEO_DURATION_MISMATCH",
            ):
                concat_segments(
                    segments,
                    root / "result.mp4",
                    expect_audio=True,
                )


class TransitionFilterGraphTest(unittest.TestCase):
    def test_short_audio_cannot_truncate_video_terminal_authority(self):
        """The compositor must retain the planned picture even when QC will reject short audio."""

        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            self.skipTest("ffmpeg/ffprobe are unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            segments = []
            for index, (color, audio_duration) in enumerate(
                (("red", 0.6), ("blue", 1.0)),
                start=1,
            ):
                path = root / f"segment-{index}.mp4"
                result = _run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c={color}:s=180x320:r=30:d=1",
                        "-f",
                        "lavfi",
                        "-i",
                        f"sine=frequency={440 + index * 110}:sample_rate=48000:d={audio_duration}",
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        str(path),
                    ]
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                segments.append(path)

            output = root / "result.mp4"
            _, planned_duration, _ = render_transition_segments(
                segments,
                [1.0, 1.0],
                [TransitionBoundary(type="dissolve", duration=0.2)],
                output,
                expect_audio=True,
            )
            info = probe_media(output)

        self.assertAlmostEqual(planned_duration, 1.8, places=2)
        self.assertAlmostEqual(info.video_duration, planned_duration, delta=0.04)
        self.assertLess(info.audio_duration, info.video_duration - 0.2)

    def test_audio_transition_render_uses_video_terminal_authority(self):
        with patch(
            "concat_videos._run",
            return_value=SimpleNamespace(returncode=0, stderr=""),
        ) as run:
            render_transition_segments(
                [Path("a.mp4"), Path("b.mp4")],
                [2.0, 2.0],
                [TransitionBoundary(type="dissolve", duration=0.2)],
                Path("result.mp4"),
                expect_audio=True,
            )

        command = run.call_args.args[0]
        self.assertNotIn("-shortest", command)
        self.assertIn("-t", command)
        self.assertEqual(command[command.index("-t") + 1], "3.800000")

    def test_dissolve_renders_video_and_audio_overlap(self):
        graph, duration, receipts = build_transition_filter_graph(
            durations=[2.0, 2.0],
            boundaries=[TransitionBoundary(type="dissolve", duration=0.2)],
            include_audio=True,
        )
        # FFmpeg's native xfade=dissolve can emit full-frame salt-and-pepper
        # noise for mixed mobile codecs.  The canonical compositor must use
        # the deterministic alpha-overlay implementation instead.
        self.assertNotIn("xfade=transition=dissolve", graph)
        self.assertIn("fade=t=in:st=0:d=0.200000:alpha=1", graph)
        self.assertIn("overlay=shortest=1:format=auto", graph)
        self.assertIn("concat=n=3:v=1:a=0", graph)
        self.assertIn("setsar=1", graph)
        self.assertIn("atrim=end=1.830000", graph)
        self.assertIn("acrossfade=d=0.030000", graph)
        self.assertEqual(duration, 3.8)
        self.assertTrue(receipts[0]["rendered"])

    def test_short_replacement_scales_overlap_without_retiming_or_duplicate_frames(self):
        graph, duration, receipts = build_transition_filter_graph(
            durations=[4 / 30, 3 / 30],
            boundaries=[
                TransitionBoundary(
                    type="dissolve",
                    duration=6 / 30,
                    source_shell_sha256="a" * 64,
                )
            ],
            include_audio=False,
            fps=30,
        )

        self.assertAlmostEqual(receipts[0]["duration"], 2 / 30, places=6)
        self.assertTrue(receipts[0]["duration_adjusted"])
        self.assertAlmostEqual(duration, 5 / 30, places=6)
        lowered = graph.lower()
        for forbidden in (
            "tpad",
            "apad",
            "loop=",
            "-stream_loop",
            "color=c=black",
            "clone",
            "stop_mode=clone",
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertNotRegex(lowered, r"setpts\s*=\s*(?:[0-9.]|[^,;]*\*)")

    def test_non_hard_transition_consumes_declared_audio_fade_window(self):
        graph, _, receipts = build_transition_filter_graph(
            durations=[2.0, 2.0],
            boundaries=[
                TransitionBoundary(
                    type="dissolve",
                    duration=0.2,
                    audio_fade_duration=0.05,
                )
            ],
            include_audio=True,
        )
        self.assertIn("acrossfade=d=0.050000", graph)
        self.assertNotIn("acrossfade=d=0.200000", graph)
        self.assertEqual(receipts[0]["audio_fade_duration"], 0.05)

    def test_non_hard_preserve_audio_drops_only_the_overlapped_left_tail(self):
        graph, duration, receipts = build_transition_filter_graph(
            durations=[2.0, 2.0],
            boundaries=[
                TransitionBoundary(
                    type="dissolve",
                    duration=0.2,
                    audio_policy="preserve",
                )
            ],
            include_audio=True,
        )
        self.assertIn("atrim=end=1.800000", graph)
        self.assertNotIn("acrossfade=", graph)
        self.assertEqual(duration, 3.8)
        self.assertEqual(receipts[0]["audio_transition"], "preserve")

    def test_push_wipe_slide_fade_and_zoom_have_deterministic_ffmpeg_mappings(self):
        expected = {
            "push_left": "slideleft",
            "wipe_right": "wiperight",
            "slide_up": "slideup",
            "fade": "fade",
            "zoom_in": "zoomin",
            "preview_expand": "zoomin",
        }
        for source_type, ffmpeg_type in expected.items():
            with self.subTest(source_type=source_type):
                graph, _, receipts = build_transition_filter_graph(
                    durations=[2.0, 2.0],
                    boundaries=[TransitionBoundary(type=source_type, duration=0.2)],
                    include_audio=False,
                )
                self.assertIn(f"transition={ffmpeg_type}", graph)
                self.assertEqual(receipts[0]["ffmpeg_transition"], ffmpeg_type)

    def test_radial_zoom_blur_does_not_claim_hblur_is_exact(self):
        with self.assertRaisesRegex(
            ConcatError,
            "TRANSITION_BACKEND_CAPABILITY_REQUIRED",
        ):
            build_transition_filter_graph(
                durations=[2.0, 2.0],
                boundaries=[
                    TransitionBoundary(
                        type="radial_zoom_blur",
                        duration=0.2,
                    )
                ],
                include_audio=False,
            )

    def test_zoom_out_and_zoom_back_do_not_silently_downgrade_to_fade(self):
        for source_type in ("zoom_out", "zoom_back"):
            with self.subTest(source_type=source_type), self.assertRaisesRegex(
                ConcatError,
                "TRANSITION_BACKEND_CAPABILITY_REQUIRED",
            ):
                build_transition_filter_graph(
                    durations=[2.0, 2.0],
                    boundaries=[
                        TransitionBoundary(
                            type=source_type,
                            duration=0.2,
                        )
                    ],
                    include_audio=False,
                )

    def test_hard_cut_does_not_reduce_duration(self):
        graph, duration, receipts = build_transition_filter_graph(
            durations=[2.0, 2.0],
            boundaries=[TransitionBoundary(type="hard_cut", duration=0.0)],
            include_audio=True,
        )
        self.assertIn("concat=n=2:v=1:a=0", graph)
        self.assertNotIn("xfade=", graph)
        self.assertIn("afade=t=out:st=1.970000:d=0.030000", graph)
        self.assertIn("afade=t=in:st=0:d=0.030000", graph)
        self.assertEqual(duration, 4.0)
        self.assertFalse(receipts[0]["rendered"])
        self.assertTrue(receipts[0]["audio_rendered"])
        self.assertEqual(receipts[0]["audio_transition"], "anti_pop_fade")
        self.assertEqual(receipts[0]["audio_fade_duration"], 0.03)

    def test_transition_receipt_binds_the_exact_source_shell_digest(self):
        _, _, receipts = build_transition_filter_graph(
            durations=[2.0, 2.0],
            boundaries=[
                TransitionBoundary(
                    type="dissolve",
                    duration=0.2,
                    source_shell_sha256="a" * 64,
                )
            ],
            include_audio=True,
        )
        self.assertEqual(receipts[0]["source_shell_sha256"], "a" * 64)

    def test_transition_renderer_mints_final_output_sha_before_returning_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "rendered.mp4"
            left = Path(tmp) / "left.mp4"
            right = Path(tmp) / "right.mp4"
            left.write_bytes(b"left")
            right.write_bytes(b"right")
            final_bytes = b"final-output"

            def run(command):
                output.write_bytes(final_bytes)
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch("concat_videos._run", side_effect=run):
                _, _, receipts = render_transition_segments(
                    [left, right],
                    [1.0, 1.0],
                    [TransitionBoundary(type="hard_cut", source_shell_sha256="a" * 64)],
                    output,
                    expect_audio=False,
                )

            self.assertEqual(
                receipts[0]["final_output_sha256"],
                hashlib.sha256(final_bytes).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
