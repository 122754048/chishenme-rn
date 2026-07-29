from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

import media_quality  # noqa: E402
from concat_videos import MediaInfo  # noqa: E402


class MediaQualityActiveWindowTest(unittest.TestCase):
    def test_no_black_keeps_complete_duration(self):
        window = media_quality.resolve_active_window(
            duration=4.0,
            fps=25.0,
            black_intervals=(),
        )
        self.assertEqual(window.active_start, 0.0)
        self.assertEqual(window.active_end, 4.0)
        self.assertEqual(window.active_duration, 4.0)

    def test_leading_and_trailing_black_are_trimmed_but_internal_black_is_preserved(self):
        intervals = (
            media_quality.BlackInterval(0.0, 0.4),
            media_quality.BlackInterval(1.5, 1.8),
            media_quality.BlackInterval(3.0, 4.0),
        )
        window = media_quality.resolve_active_window(
            duration=4.0,
            fps=25.0,
            black_intervals=intervals,
        )
        self.assertEqual(window.active_start, 0.4)
        self.assertEqual(window.active_end, 3.0)
        self.assertEqual(window.active_duration, 2.6)
        self.assertEqual(window.leading_black_duration, 0.4)
        self.assertEqual(window.trailing_black_duration, 1.0)
        self.assertEqual(window.internal_black_intervals, (intervals[1],))

    def test_all_black_media_is_rejected(self):
        with self.assertRaisesRegex(media_quality.MediaQualityError, "NO_ACTIVE_VIDEO_CONTENT"):
            media_quality.resolve_active_window(
                duration=4.0,
                fps=25.0,
                black_intervals=(media_quality.BlackInterval(0.0, 4.0),),
            )

    def test_blackdetect_output_is_parsed_deterministically(self):
        stderr = "\n".join(
            (
                "[blackdetect @ 000] black_start:0 black_end:0.4 black_duration:0.4",
                "[blackdetect @ 000] black_start:3.0 black_end:4.0 black_duration:1.0",
            )
        )
        self.assertEqual(
            media_quality.parse_blackdetect(stderr),
            (
                media_quality.BlackInterval(0.0, 0.4),
                media_quality.BlackInterval(3.0, 4.0),
            ),
        )

    def test_fragmented_edge_black_intervals_are_coalesced(self):
        window = media_quality.resolve_active_window(
            duration=4.0,
            fps=30.0,
            black_intervals=(
                media_quality.BlackInterval(0.0, 0.1),
                media_quality.BlackInterval(0.1001, 0.2),
                media_quality.BlackInterval(3.9, 4.0),
            ),
        )
        self.assertAlmostEqual(window.active_start, 0.2, places=4)
        self.assertEqual(window.internal_black_intervals, ())

    def test_detector_uses_one_low_resolution_non_semantic_ffmpeg_scan(self):
        calls: list[list[str]] = []

        def run(command: list[str]):
            calls.append(command)
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stderr": "[blackdetect @ 000] black_start:2.1 black_end:4.0 black_duration:1.9",
                },
            )()

        window = media_quality.detect_active_window(
            Path("tail.mp4"),
            duration=4.0,
            fps=30.0,
            run=run,
        )
        self.assertEqual(len(calls), 1)
        command = " ".join(calls[0]).lower()
        self.assertIn("blackdetect", command)
        self.assertIn("scale=160", command)
        self.assertIn("setpts=pts-startpts", command)
        self.assertIn("pic_th=1.0", command)
        self.assertIn("-an", calls[0])
        self.assertNotIn("ocr", command)
        self.assertEqual(window.active_end, 2.1)


class FinalMediaQualityTest(unittest.TestCase):
    def _info(
        self,
        *,
        video_duration: float = 4.0,
        audio_duration: float = 4.0,
    ) -> MediaInfo:
        return MediaInfo(
            path=Path("final.mp4"),
            has_video=True,
            has_audio=True,
            duration=max(video_duration, audio_duration),
            frame_rate="30/1",
            video_duration=video_duration,
            audio_duration=audio_duration,
        )

    def test_clean_final_media_passes(self):
        result = media_quality.validate_final_media(
            Path("final.mp4"),
            media_info=self._info(),
            fps=30.0,
            run=lambda _: type("Result", (), {"returncode": 0, "stderr": ""})(),
        )
        self.assertEqual(result["status"], "passed")

    def test_internal_black_at_splice_boundary_blocks_delivery(self):
        stderr = "[blackdetect @ 0] black_start:1.0 black_end:1.2 black_duration:0.2"
        with self.assertRaisesRegex(
            media_quality.MediaQualityError,
            "SPLICE_BOUNDARY_BLACK_DETECTED",
        ):
            media_quality.validate_final_media(
                Path("final.mp4"),
                media_info=self._info(),
                fps=30.0,
                splice_windows=((1.0, 1.0),),
                run=lambda _: type(
                    "Result", (), {"returncode": 0, "stderr": stderr}
                )(),
            )

    def test_internal_black_away_from_splice_boundary_is_reported_but_allowed(self):
        stderr = "[blackdetect @ 0] black_start:2.0 black_end:2.2 black_duration:0.2"
        result = media_quality.validate_final_media(
            Path("final.mp4"),
            media_info=self._info(),
            fps=30.0,
            splice_windows=((1.0, 1.0),),
            run=lambda _: type("Result", (), {"returncode": 0, "stderr": stderr})(),
        )
        self.assertEqual(
            result["internal_black_intervals"],
            [{"start": 2.0, "end": 2.2}],
        )
        self.assertEqual(result["splice_windows_checked"], [[1.0, 1.0]])

    def test_trailing_black_blocks_delivery(self):
        stderr = "[blackdetect @ 0] black_start:3.5 black_end:4.0 black_duration:0.5"
        with self.assertRaisesRegex(media_quality.MediaQualityError, "TRAILING_BLACK_DETECTED"):
            media_quality.validate_final_media(
                Path("final.mp4"),
                media_info=self._info(),
                fps=30.0,
                run=lambda _: type("Result", (), {"returncode": 0, "stderr": stderr})(),
            )

    def test_single_edge_black_frame_blocks_delivery(self):
        stderr = "[blackdetect @ 0] black_start:0 black_end:0.033333 black_duration:0.033333"
        with self.assertRaisesRegex(media_quality.MediaQualityError, "LEADING_BLACK_DETECTED"):
            media_quality.validate_final_media(
                Path("final.mp4"),
                media_info=self._info(),
                fps=30.0,
                run=lambda _: type("Result", (), {"returncode": 0, "stderr": stderr})(),
            )

    def test_video_ending_before_audio_blocks_delivery(self):
        with self.assertRaisesRegex(media_quality.MediaQualityError, "VIDEO_ENDS_BEFORE_AUDIO"):
            media_quality.validate_final_media(
                Path("final.mp4"),
                media_info=self._info(video_duration=4.0, audio_duration=4.4),
                fps=30.0,
                run=lambda _: type("Result", (), {"returncode": 0, "stderr": ""})(),
            )

    def test_audio_ending_before_video_blocks_av_drift(self):
        with self.assertRaisesRegex(media_quality.MediaQualityError, "AUDIO_VIDEO_DURATION_DRIFT"):
            media_quality.validate_final_media(
                Path("final.mp4"),
                media_info=self._info(video_duration=4.4, audio_duration=4.0),
                fps=30.0,
                run=lambda _: type("Result", (), {"returncode": 0, "stderr": ""})(),
            )

    def test_freezedetect_output_is_parsed_and_boundary_freeze_blocks_delivery(self):
        stderr = "[freezedetect @ 0] freeze_start:1.000\n[freezedetect @ 0] freeze_end:1.800 freeze_duration:0.800"
        self.assertEqual(
            media_quality.parse_freezedetect(stderr),
            (media_quality.FreezeInterval(1.0, 1.8),),
        )
        result = media_quality.validate_final_media(
            Path("final.mp4"),
            media_info=self._info(),
            fps=30.0,
            splice_windows=((1.0, 1.0),),
            run=lambda command: type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stderr": stderr if "freezedetect" in " ".join(command) else "",
                },
            )(),
        )
        self.assertEqual(
            result["freeze_intervals"],
            [{"start": 1.0, "end": 1.8}],
        )

    def test_trailing_freeze_blocks_delivery_without_padding(self):
        stderr = "[freezedetect @ 0] freeze_start:2.200\n[freezedetect @ 0] freeze_end:4.000 freeze_duration:1.800"
        result = media_quality.validate_final_media(
            Path("final.mp4"),
            media_info=self._info(),
            fps=30.0,
            run=lambda command: type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stderr": stderr if "freezedetect" in " ".join(command) else "",
                },
            )(),
        )
        self.assertEqual(
            result["freeze_intervals"],
            [{"start": 2.2, "end": 4.0}],
        )


if __name__ == "__main__":
    unittest.main()
