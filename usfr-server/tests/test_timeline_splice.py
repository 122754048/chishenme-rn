from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

import timeline_splice  # noqa: E402
from concat_videos import MediaInfo  # noqa: E402
from media_quality import ActiveWindow, BlackInterval, MediaQualityError  # noqa: E402


def write_contract(path: Path, regions: list[dict], source_duration: float = 10.0) -> None:
    path.write_text(
        json.dumps(
            {
                "source_duration": source_duration,
                "target": {"width": 180, "height": 320, "fps": 24},
                "regions": regions,
            }
        ),
        encoding="utf-8",
    )


def info(path: Path, duration: float) -> MediaInfo:
    return MediaInfo(
        path=path,
        has_video=True,
        has_audio=True,
        duration=duration,
        video_codec="h264",
        audio_codec="aac",
        width=180,
        height=320,
    )


def mapping_sha256(value: dict) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TimelineSpliceBehaviorTest(unittest.TestCase):
    def test_non_hard_source_transition_cannot_downgrade_to_hard_cut(self):
        left = timeline_splice.TimelineRegion(
            kind="generated",
            source_start=0.0,
            source_end=1 / 30,
            media_path=Path("left.mp4"),
            transition_shell={
                "exit": {"type": "dissolve", "duration_frames": 6}
            },
        )
        right = timeline_splice.TimelineRegion(
            kind="opaque_ui_demo",
            source_start=1 / 30,
            source_end=11 / 30,
            media_path=Path("right.mp4"),
            transition_shell={
                "entry": {"type": "dissolve", "duration_frames": 6}
            },
        )

        boundary = timeline_splice._boundary_between(left, right, fps=30)
        self.assertEqual(boundary.type, "dissolve")
        with self.assertRaisesRegex(
            timeline_splice.TimelineSpliceError,
            "no real active-frame overlap",
        ):
            timeline_splice._fit_boundary_to_active_frames(
                boundary,
                left_active_frames=1,
                right_active_frames=10,
                fps=30,
            )
        ffmpeg_plan = json.dumps(boundary.__dict__, sort_keys=True).lower()
        for forbidden in (
            "tpad",
            "apad",
            "loop=",
            "color=c=black",
            "duplicate",
            "clone",
        ):
            self.assertNotIn(forbidden, ffmpeg_plan)

    def test_rich_transition_fields_fail_closed_instead_of_silent_downgrade(self):
        left = timeline_splice.TimelineRegion(
            kind="generated",
            source_start=0.0,
            source_end=1.0,
            media_path=Path("left.mp4"),
            transition_shell={
                "exit": {
                    "type": "dissolve",
                    "duration_seconds": 0.2,
                    "easing": "ease_in_out_cubic",
                    "mask_keyframes": [{"time": 0.0}, {"time": 0.2}],
                }
            },
        )
        right = timeline_splice.TimelineRegion(
            kind="opaque_ui_demo",
            source_start=1.0,
            source_end=2.0,
            media_path=Path("right.mp4"),
            transition_shell={
                "entry": {
                    "type": "dissolve",
                    "duration_seconds": 0.2,
                    "easing": "ease_in_out_cubic",
                    "mask_keyframes": [{"time": 0.0}, {"time": 0.2}],
                }
            },
        )
        with self.assertRaisesRegex(
            timeline_splice.TimelineSpliceError,
            "TRANSITION_BACKEND_CAPABILITY_REQUIRED",
        ):
            timeline_splice._boundary_between(left, right, fps=30)

    def test_opaque_aspect_uses_display_dimensions_after_rotation(self):
        region = timeline_splice.TimelineRegion(
            kind="opaque_ui_demo",
            source_start=0.0,
            source_end=1.0,
            media_path=Path("rotated.mp4"),
            media_origin="user_upload",
        )
        info = SimpleNamespace(
            width=320,
            height=180,
            display_width=180,
            display_height=320,
            rotation_deg=90,
        )
        timeline_splice._validate_aspect_ratio(
            region,
            info,
            target_width=180,
            target_height=320,
        )

    def test_non_hard_ui_boundaries_use_real_compositor_and_overlap_accounting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "generated",
                        "source_start": 0,
                        "source_end": 2,
                        "media_path": "a.mp4",
                    },
                    {
                        "region_type": "opaque_ui_demo",
                        "source_start": 2,
                        "source_end": 4,
                        "media_path": "ui.mp4",
                        "transition_shell": {
                            "entry": {"type": "dissolve", "duration_frames": 6},
                            "exit": {"type": "push_left", "duration_frames": 3},
                        },
                        "transition_shell_applied": False,
                    },
                    {
                        "region_type": "generated",
                        "source_start": 4,
                        "source_end": 6,
                        "media_path": "b.mp4",
                    },
                ],
                source_duration=6,
            )
            contract = timeline_splice.load_contract(contract_path)

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved == output_path:
                    return info(resolved, 5.625)
                if resolved.name.startswith("region-"):
                    return info(resolved, 2.0)
                if resolved.name in {"a.mp4", "ui.mp4", "b.mp4"}:
                    return info(resolved, 2.0)
                raise AssertionError(f"unexpected probe: {resolved}")

            receipts = [
                {
                    "boundary_index": 0,
                    "source_type": "dissolve",
                    "ffmpeg_transition": "dissolve",
                    "duration": 0.25,
                    "offset": 1.75,
                    "rendered": True,
                    "render_hash": "a" * 64,
                    "source_shell_sha256": timeline_splice._boundary_between(
                        contract.regions[0], contract.regions[1], fps=contract.target_fps
                    ).source_shell_sha256,
                },
                {
                    "boundary_index": 1,
                    "source_type": "push_left",
                    "ffmpeg_transition": "slideleft",
                    "duration": 0.125,
                    "offset": 3.625,
                    "rendered": True,
                    "render_hash": "b" * 64,
                    "source_shell_sha256": timeline_splice._boundary_between(
                        contract.regions[1], contract.regions[2], fps=contract.target_fps
                    ).source_shell_sha256,
                },
            ]
            with patch.object(
                timeline_splice, "probe_media", side_effect=probe
            ), patch.object(
                timeline_splice,
                "render_transition_segments",
                return_value=(output_path, 5.625, receipts),
            ) as render, patch.object(
                timeline_splice, "concat_segments"
            ) as concat, patch.object(
                timeline_splice.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 0, "stderr": ""})(),
            ):
                timeline_splice.splice_timeline(contract, output_path, manifest_path)

            concat.assert_not_called()
            boundaries = render.call_args.args[2]
            self.assertEqual([item.type for item in boundaries], ["dissolve", "push_left"])
            self.assertEqual([item.duration for item in boundaries], [0.25, 0.125])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["planned_output_duration"], 5.625)
            self.assertEqual(manifest["placements"][1]["output_start"], 1.75)
            self.assertEqual(manifest["placements"][2]["output_end"], 5.625)
            self.assertTrue(manifest["placements"][1]["transition_shell_applied"]["entry"])
            self.assertTrue(manifest["placements"][1]["transition_shell_applied"]["exit"])
            self.assertEqual(len(manifest["transition_renders"]), 2)

    def test_mixed_dissolve_and_shellless_hard_cut_receipts_are_accepted(self):
        """A hard cut without a source shell has no shell digest to bind."""
        regions = [
            timeline_splice.TimelineRegion(
                kind="generated",
                source_start=0.0,
                source_end=1.0,
                media_path=Path("left.mp4"),
                transition_shell={
                    "exit": {"type": "dissolve", "duration_seconds": 0.2}
                },
            ),
            timeline_splice.TimelineRegion(
                kind="generated",
                source_start=1.0,
                source_end=2.0,
                media_path=Path("middle.mp4"),
                transition_shell={
                    "entry": {"type": "dissolve", "duration_seconds": 0.2}
                },
            ),
            timeline_splice.TimelineRegion(
                kind="generated",
                source_start=2.0,
                source_end=3.0,
                media_path=Path("right.mp4"),
            ),
        ]
        dissolve = timeline_splice._boundary_between(
            regions[0], regions[1], fps=30.0
        )
        self.assertEqual(
            timeline_splice._boundary_between(regions[1], regions[2], fps=30.0).type,
            "hard_cut",
        )
        placements = [
            {"transition_shell_applied": {}},
            {"transition_shell_applied": {}},
            {"transition_shell_applied": {}},
        ]
        receipts = [
            {
                "boundary_index": 0,
                "rendered": True,
                "source_shell_sha256": dissolve.source_shell_sha256,
            },
            {
                "boundary_index": 1,
                "rendered": False,
                "source_shell_sha256": "",
            },
        ]

        timeline_splice._apply_transition_receipts(
            placements,
            regions,
            receipts,
            fps=30.0,
        )

        self.assertTrue(placements[0]["transition_shell_applied"]["exit"])
        self.assertTrue(placements[1]["transition_shell_applied"]["entry"])
        self.assertNotIn("source_shell_sha256", receipts[1])

    def test_explicit_hard_cut_shell_still_requires_source_shell_digest(self):
        left = timeline_splice.TimelineRegion(
            kind="generated",
            source_start=0.0,
            source_end=1.0,
            media_path=Path("left.mp4"),
            transition_shell={"exit": {"type": "hard_cut"}},
        )
        right = timeline_splice.TimelineRegion(
            kind="generated",
            source_start=1.0,
            source_end=2.0,
            media_path=Path("right.mp4"),
            transition_shell={"entry": {"type": "hard_cut"}},
        )
        boundary = timeline_splice._boundary_between(left, right, fps=30.0)
        self.assertEqual(boundary.type, "hard_cut")
        self.assertTrue(boundary.source_shell_sha256)
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
                        "rendered": False,
                        "source_shell_sha256": "",
                    }
                ],
                fps=30.0,
            )

    def test_transition_receipt_bound_to_stale_output_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "generated",
                        "source_start": 0,
                        "source_end": 2,
                        "media_path": "a.mp4",
                        "transition_shell": {
                            "exit": {"type": "dissolve", "duration_seconds": 0.25}
                        },
                    },
                    {
                        "region_type": "generated",
                        "source_start": 2,
                        "source_end": 4,
                        "media_path": "b.mp4",
                        "transition_shell": {
                            "entry": {"type": "dissolve", "duration_seconds": 0.25}
                        },
                    },
                ],
                source_duration=4,
            )
            contract = timeline_splice.load_contract(contract_path)

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved == output_path:
                    return info(resolved, 3.75)
                return info(resolved, 2.0)

            boundary = timeline_splice._boundary_between(
                contract.regions[0], contract.regions[1], fps=contract.source_fps
            )

            def render(*_args, **_kwargs):
                output_path.write_bytes(b"fresh-rendered-output")
                return (
                    output_path,
                    3.75,
                    [
                        {
                            "boundary_index": 0,
                            "source_type": "dissolve",
                            "ffmpeg_transition": "dissolve",
                            "duration": 0.25,
                            "offset": 1.75,
                            "rendered": True,
                            "render_hash": "a" * 64,
                            "source_shell_sha256": boundary.source_shell_sha256,
                            "final_output_sha256": "0" * 64,
                        }
                    ],
                )

            with patch.object(
                timeline_splice, "probe_media", side_effect=probe
            ), patch.object(
                timeline_splice, "render_transition_segments", side_effect=render
            ), patch.object(
                timeline_splice, "validate_final_media", return_value={"status": "passed"}
            ), patch.object(
                timeline_splice.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 0, "stderr": ""})(),
            ):
                with self.assertRaisesRegex(
                    timeline_splice.TimelineSpliceError,
                    "TRANSITION_OUTPUT_SHA256_MISMATCH",
                ):
                    timeline_splice.splice_timeline(
                        contract, output_path, manifest_path
                    )

    def test_duration_frames_use_source_fps_when_target_fps_differs(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        left = timeline_splice.TimelineRegion(
            kind="generated",
            source_start=0.0,
            source_end=2.0,
            media_path=Path("left.mp4"),
            transition_shell={"exit": {"type": "dissolve", "duration_frames": 6}},
        )
        right = timeline_splice.TimelineRegion(
            kind="generated",
            source_start=2.0,
            source_end=4.0,
            media_path=Path("right.mp4"),
            transition_shell={"entry": {"type": "dissolve", "duration_frames": 6}},
        )
        contract = timeline_splice.TimelineContract(
            source_duration=4.0,
            source_duration_us=4_000_000,
            source_fps=60.0,
            regions=(left, right),
            target_width=180,
            target_height=320,
            target_fps=30,
        )
        output_path = root / "result.mp4"
        captured: dict[str, object] = {}

        def fake_probe(path: Path) -> MediaInfo:
            if Path(path) == output_path:
                return info(Path(path), 3.9)
            return info(Path(path), 2.0)

        def fake_render(
            _segments: list[Path],
            durations: list[float],
            boundaries: list[object],
            _output: Path,
            *,
            expect_audio: bool,
        ) -> tuple[Path, float, list[dict[str, object]]]:
            captured["boundaries"] = boundaries
            expected = timeline_splice._boundary_between(left, right, fps=60.0)
            return (
                output_path,
                sum(durations) - expected.duration,
                [
                    {
                        "boundary_index": 0,
                        "rendered": True,
                        "source_shell_sha256": expected.source_shell_sha256,
                    }
                ],
            )

        with patch.object(timeline_splice, "probe_media", side_effect=fake_probe), patch.object(
            timeline_splice, "_normalize_region", return_value=()
        ), patch.object(
            timeline_splice, "render_transition_segments", side_effect=fake_render
        ), patch.object(
            timeline_splice, "validate_final_media", return_value={"status": "passed"}
        ):
            timeline_splice.splice_timeline(
                contract,
                output_path,
                root / "manifest.json",
            )

        boundaries = captured["boundaries"]
        self.assertEqual(len(boundaries), 1)
        self.assertAlmostEqual(boundaries[0].duration, 6.0 / 60.0)

    def test_source_interval_is_preserved_without_temporal_retime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            source_ui = root / "source-ui.mp4"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "opaque_ui_demo",
                        "source_start": 0,
                        "source_end": 2,
                        "media_path": str(source_ui),
                        "media_origin": "source_interval",
                        "assembly_policy": "splice_source_interval",
                        "transition_shell": {
                            "entry": {"type": "hard_cut"},
                            "exit": {"type": "hard_cut"},
                        },
                    }
                ],
                source_duration=2,
            )
            contract = timeline_splice.load_contract(contract_path)

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved == source_ui:
                    return info(resolved, 2.0)
                if resolved == output_path or resolved.name == "region-001.mp4":
                    return info(resolved, 2.0)
                raise AssertionError(f"unexpected probe: {resolved}")

            with patch.object(timeline_splice, "probe_media", side_effect=probe), patch.object(
                timeline_splice, "concat_segments"
            ), patch.object(
                timeline_splice.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 0, "stderr": ""})(),
            ) as run:
                timeline_splice.splice_timeline(contract, output_path, manifest_path)

            command = " ".join(run.call_args.args[0]).lower()
            for forbidden in ("tpad", "apad", "atempo"):
                self.assertNotIn(forbidden, command)
            self.assertIn("setpts=pts-startpts", command)
            self.assertIn("atrim=", command)
            self.assertIn("-t", command)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            placement = manifest["placements"][0]
            self.assertEqual(placement["media_origin"], "source_interval")
            self.assertEqual(
                placement["assembly_policy"], "splice_source_interval"
            )
            self.assertEqual(manifest["rules"]["source_interval_behavior"], "preserve")

    def test_source_interval_rebases_video_and_audio_pts_at_slice_boundary(self):
        region = timeline_splice.TimelineRegion(
            kind="generated",
            source_start=0.0,
            source_end=1.0,
            media_path=Path("slice.mp4"),
            media_origin="source_interval",
            assembly_policy="splice_source_interval",
        )
        with patch.object(
            timeline_splice.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stderr=""),
        ) as run:
            timeline_splice._normalize_region(
                region,
                1.0,
                Path("normalized.mp4"),
                width=180,
                height=320,
                fps=30,
                include_audio=True,
            )
        command = " ".join(str(item) for item in run.call_args.args[0]).lower()
        self.assertIn("setpts=pts-startpts", command)
        self.assertIn("asetpts=pts-startpts", command)
        self.assertIn("-t 1.000000", command)

    def test_normalization_uses_high_fidelity_intermediate_video_encode(self):
        region = timeline_splice.TimelineRegion(
            kind="generated",
            source_start=0.0,
            source_end=1.0,
            media_path=Path("generated.mp4"),
            media_origin="generated_media",
        )
        with patch.object(
            timeline_splice.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stderr=""),
        ) as run:
            timeline_splice._normalize_region(
                region,
                1.0,
                Path("normalized.mp4"),
                width=180,
                height=320,
                fps=30,
                include_audio=False,
            )
        command = " ".join(str(item) for item in run.call_args.args[0]).lower()
        self.assertIn("-crf 18", command)
        self.assertIn("-preset veryfast", command)

    def test_normalization_preserves_positive_input_av_start_offset(self):
        region = timeline_splice.TimelineRegion(
            kind="opaque_ui_demo",
            source_start=0.0,
            source_end=1.0,
            media_path=Path("ui.mp4"),
            media_origin="user_upload",
            audio_policy="opaque_audio_keep",
        )
        active = ActiveWindow(
            raw_duration=1.0,
            active_start=0.0,
            active_end=1.0,
            leading_black_duration=0.0,
            trailing_black_duration=0.0,
            black_intervals=(),
            internal_black_intervals=(),
        )
        with patch.object(
            timeline_splice.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stderr=""),
        ) as run:
            timeline_splice._normalize_region(
                region,
                1.0,
                Path("normalized.mp4"),
                width=180,
                height=320,
                fps=30,
                include_audio=True,
                active_window=active,
                input_has_audio=True,
                input_video_start=0.0,
                input_audio_start=0.18,
            )
        command = " ".join(str(item) for item in run.call_args.args[0]).lower()
        self.assertIn("adelay=180.000:all=1", command)

    def test_opaque_trim_recomputes_residual_av_start_offset(self):
        region = timeline_splice.TimelineRegion(
            kind="opaque_ui_demo",
            source_start=0.0,
            source_end=1.0,
            media_path=Path("ui.mp4"),
            media_origin="user_upload",
            audio_policy="opaque_audio_keep",
        )
        active = ActiveWindow(
            raw_duration=1.0,
            active_start=0.3,
            active_end=1.0,
            leading_black_duration=0.3,
            trailing_black_duration=0.0,
            black_intervals=(),
            internal_black_intervals=(),
        )
        with patch.object(
            timeline_splice.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stderr=""),
        ) as run:
            timeline_splice._normalize_region(
                region,
                1.0,
                Path("normalized.mp4"),
                width=180,
                height=320,
                fps=30,
                include_audio=True,
                active_window=active,
                input_has_audio=True,
                input_video_start=0.0,
                input_audio_start=0.18,
            )
        command = " ".join(str(item) for item in run.call_args.args[0]).lower()
        self.assertNotIn("adelay=180.000", command)
        self.assertNotIn("adelay=", command)

    def test_opaque_silence_allowed_policy_injects_a_real_audio_stream(self):
        region = timeline_splice.TimelineRegion(
            kind="opaque_ui_demo",
            source_start=0.0,
            source_end=1.0,
            media_path=Path("ui.mp4"),
            media_origin="user_upload",
            audio_policy="silence_allowed",
        )
        active = ActiveWindow(
            raw_duration=1.0,
            active_start=0.0,
            active_end=1.0,
            leading_black_duration=0.0,
            trailing_black_duration=0.0,
            black_intervals=(),
            internal_black_intervals=(),
        )
        with patch.object(
            timeline_splice.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stderr=""),
        ) as run:
            timeline_splice._normalize_region(
                region,
                1.0,
                Path("normalized.mp4"),
                width=180,
                height=320,
                fps=30,
                include_audio=True,
                active_window=active,
                input_has_audio=False,
            )
        command = " ".join(str(item) for item in run.call_args.args[0]).lower()
        self.assertIn("anullsrc", command)
        self.assertIn("-map 1:a:0", command)

    def test_opaque_source_voiceover_policy_requires_dedicated_audio_compositor(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract_path = Path(tmp) / "timeline.json"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "opaque_ui_demo",
                        "source_start": 0,
                        "source_end": 1,
                        "media_path": "ui.mp4",
                        "audio_policy": "source_voiceover_keep",
                    }
                ],
                source_duration=1,
            )
            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "AUDIO_POLICY_CAPABILITY_REQUIRED",
            ):
                timeline_splice.load_contract(contract_path)

    def test_source_tail_interval_is_omitted_when_tail_slot_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            source_tail = root / "source-tail.mp4"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "excluded_app_end_card",
                        "source_start": 0,
                        "source_end": 2,
                        "media_path": str(source_tail),
                        "media_origin": "source_interval",
                        "assembly_policy": "splice_source_interval",
                        "transition_shell": {"entry": {"type": "hard_cut"}},
                    }
                ],
                source_duration=2,
            )
            contract = timeline_splice.load_contract(contract_path)

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved == output_path:
                    return info(resolved, 0.0)
                raise AssertionError(f"unexpected probe: {resolved}")

            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "timeline has no included media",
            ):
                timeline_splice.splice_timeline(contract, output_path, manifest_path)

    def test_missing_terminal_tail_contributes_zero_duration_without_filler(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            source_tail = root / "source-tail.mp4"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "generated",
                        "source_start": 0,
                        "source_end": 8,
                        "media_path": "main.mp4",
                    },
                    {
                        "region_type": "excluded_app_end_card",
                        "source_start": 8,
                        "source_end": 10,
                        "media_path": str(source_tail),
                        "media_origin": "source_interval",
                        "assembly_policy": "splice_source_interval",
                        "transition_shell": {"entry": {"type": "hard_cut"}},
                    },
                ],
            )
            contract = timeline_splice.load_contract(contract_path)

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved == root / "main.mp4" or resolved.name == "region-001.mp4":
                    return info(resolved, 8.0)
                if resolved == output_path:
                    return info(resolved, 8.0)
                raise AssertionError(f"unexpected probe: {resolved}")

            with patch.object(
                timeline_splice, "probe_media", side_effect=probe
            ), patch.object(timeline_splice, "concat_segments"), patch.object(
                timeline_splice.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 0, "stderr": ""})(),
            ):
                timeline_splice.splice_timeline(contract, output_path, manifest_path)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["planned_output_duration"], 8.0)
            self.assertEqual(len(manifest["placements"]), 1)
            self.assertEqual(manifest["omitted_intervals"][0]["reason"], "tail_video_absent")
            self.assertEqual(manifest["rules"]["missing_tail_card_behavior"], "omit_source_tail")

    def test_missing_tail_card_must_be_terminal(self):
        """Omitting a non-terminal tail cannot silently bridge later media."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            write_contract(
                contract_path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 1, "media_path": "a.mp4"},
                    {
                        "region_type": "excluded_app_end_card",
                        "source_start": 1,
                        "source_end": 2,
                        "media_path": None,
                    },
                    {"region_type": "generated", "source_start": 2, "source_end": 3, "media_path": "b.mp4"},
                ],
                source_duration=3,
            )
            with self.assertRaisesRegex(
                timeline_splice.TimelineSpliceError,
                "terminal",
            ):
                timeline_splice.load_contract(contract_path)

    def test_supplied_end_card_trims_black_edges_and_ends_at_active_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            tail = root / "tail.mp4"
            write_contract(
                contract_path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 8, "media_path": "main.mp4"},
                    {
                        "region_type": "excluded_app_end_card",
                        "source_start": 8,
                        "source_end": 10,
                        "media_path": str(tail),
                        "transition_shell": {"entry": {"type": "hard_cut"}},
                    },
                ],
            )
            contract = timeline_splice.load_contract(contract_path)
            output_info = info(output_path, 9.9)
            probes = {
                root / "main.mp4": info(root / "main.mp4", 8.0),
                tail: info(tail, 4.713),
            }

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved in probes:
                    return probes[resolved]
                if resolved == output_path:
                    return output_info
                if resolved.name == "region-001.mp4":
                    return info(resolved, 8.0)
                if resolved.name == "region-002.mp4":
                    return info(resolved, 1.9)
                raise AssertionError(f"unexpected probe: {resolved}")

            with patch.object(timeline_splice, "probe_media", side_effect=probe), patch.object(
                timeline_splice, "concat_segments"
            ), patch.object(
                timeline_splice,
                "detect_active_window",
                return_value=ActiveWindow(
                    raw_duration=4.713,
                    active_start=0.2,
                    active_end=2.1,
                    leading_black_duration=0.2,
                    trailing_black_duration=2.613,
                    black_intervals=(
                        BlackInterval(0.0, 0.2),
                        BlackInterval(2.1, 4.713),
                    ),
                    internal_black_intervals=(),
                ),
            ), patch.object(
                timeline_splice.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 0, "stderr": ""})(),
            ) as run:
                timeline_splice.splice_timeline(contract, output_path, manifest_path)

            tail_command = next(
                call.args[0]
                for call in run.call_args_list
                if str(tail) in call.args[0]
            )
            joined = " ".join(tail_command).lower()
            self.assertIn("trim=start=0.200000:end=2.100000", joined)
            self.assertIn("setpts=pts-startpts", joined)
            self.assertIn("atrim=start=0.200000:end=2.100000", joined)
            self.assertIn("asetpts=pts-startpts", joined)
            for forbidden in ("tpad", "apad", "atempo"):
                self.assertNotIn(forbidden, joined)
            self.assertNotIn("-t", tail_command)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            tail_placement = manifest["placements"][1]
            self.assertEqual(tail_placement["region_type"], "excluded_app_end_card")
            self.assertEqual(tail_placement["actual_media_duration"], 4.713)
            self.assertEqual(tail_placement["effective_media_duration"], 1.9)
            self.assertEqual(tail_placement["normalized_media_duration"], 1.9)
            self.assertEqual(tail_placement["duration_policy"], "trim_to_active_content")
            self.assertEqual(tail_placement["tail_media_audit"]["active_end"], 2.1)
            self.assertEqual(manifest["planned_output_duration"], 9.9)
            self.assertEqual(manifest["actual_output_duration"], 9.9)
            self.assertIn("boundary_black_trim", tail_placement["allowed_normalization_operations"])

    def test_all_black_supplied_tail_blocks_before_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            tail = root / "tail.mp4"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "generated",
                        "source_start": 0,
                        "source_end": 8,
                        "media_path": "main.mp4",
                    },
                    {
                        "region_type": "excluded_app_end_card",
                        "source_start": 8,
                        "source_end": 10,
                        "media_path": str(tail),
                        "transition_shell": {"entry": {"type": "hard_cut"}},
                    },
                ],
            )
            contract = timeline_splice.load_contract(contract_path)

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved == root / "main.mp4":
                    return info(resolved, 8.0)
                if resolved == tail:
                    return info(resolved, 4.0)
                raise AssertionError(f"unexpected probe: {resolved}")

            with patch.object(
                timeline_splice, "probe_media", side_effect=probe
            ), patch.object(
                timeline_splice,
                "detect_active_window",
                side_effect=MediaQualityError("NO_ACTIVE_VIDEO_CONTENT"),
            ):
                with self.assertRaisesRegex(
                    timeline_splice.TimelineSpliceError,
                    "NO_ACTIVE_VIDEO_CONTENT",
                ):
                    timeline_splice.splice_timeline(
                        contract,
                        root / "result.mp4",
                        root / "manifest.json",
                    )

    def test_legacy_missing_end_card_manifest_remains_backward_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            write_contract(
                contract_path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 8, "media_path": "main.mp4"},
                    {
                        "region_type": "excluded_app_end_card",
                        "source_start": 8,
                        "source_end": 10,
                        "media_path": None,
                    },
                ],
            )
            contract = timeline_splice.load_contract(contract_path)
            output_info = info(output_path, 8.0)

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved == root / "main.mp4" or resolved.name == "region-001.mp4":
                    return info(resolved, 8.0)
                if resolved == output_path:
                    return output_info
                raise AssertionError(f"unexpected probe: {resolved}")

            with patch.object(
                timeline_splice,
                "probe_media",
                side_effect=probe,
            ), patch.object(timeline_splice, "concat_segments"), patch.object(
                timeline_splice.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 0, "stderr": ""})(),
            ):
                timeline_splice.splice_timeline(contract, output_path, manifest_path)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["planned_output_duration"], 8.0)
            self.assertEqual(manifest["placements"][0]["output_end"], 8.0)
            self.assertEqual(manifest["omitted_intervals"][0]["region_type"], "excluded_app_end_card")
            self.assertEqual(manifest["omitted_intervals"][0]["output_start"], 8.0)
            self.assertEqual(manifest["omitted_intervals"][0]["output_end"], 8.0)

    def test_opaque_ui_preserves_active_duration_without_time_stretch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            ui = root / "ui.mp4"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "opaque_ui_demo",
                        "source_start": 0,
                        "source_end": 2,
                        "media_path": str(ui),
                        "transition_shell": {
                            "entry": {"type": "hard_cut"},
                            "exit": {"type": "hard_cut"},
                        },
                    }
                ],
                source_duration=2,
            )
            contract = timeline_splice.load_contract(contract_path)
            probes = {ui: info(ui, 2.1)}

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved in probes:
                    return probes[resolved]
                if resolved == output_path or resolved.name == "region-001.mp4":
                    return info(resolved, 2.1)
                raise AssertionError(f"unexpected probe: {resolved}")

            with patch.object(timeline_splice, "probe_media", side_effect=probe), patch.object(
                timeline_splice,
                "detect_active_window",
                return_value=timeline_splice.ActiveWindow(
                    raw_duration=2.1,
                    active_start=0.0,
                    active_end=2.1,
                    leading_black_duration=0.0,
                    trailing_black_duration=0.0,
                    black_intervals=(),
                    internal_black_intervals=(),
                ),
            ), patch.object(
                timeline_splice, "concat_segments"
            ), patch.object(
                timeline_splice.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 0, "stderr": ""})(),
            ) as run:
                timeline_splice.splice_timeline(contract, output_path, manifest_path)

            command = " ".join(run.call_args.args[0]).lower()
            self.assertIn("trim", command)
            self.assertNotIn("atempo", command)
            self.assertNotIn("tpad", command)
            self.assertNotIn("apad", command)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["planned_output_duration"], 2.1)
            self.assertEqual(
                manifest["placements"][0]["duration_policy"],
                "trim_to_active_content",
            )

    def test_opaque_ui_short_slice_shifts_timeline_without_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            ui = root / "ui.mp4"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "opaque_ui_demo",
                        "source_start": 0,
                        "source_end": 2,
                        "media_path": str(ui),
                        "transition_shell": {
                            "entry": {"type": "hard_cut"},
                            "exit": {"type": "dissolve", "duration_seconds": 0.08},
                        },
                    },
                    {
                        "region_type": "generated",
                        "source_start": 2,
                        "source_end": 3,
                        "media_path": "following.mp4",
                        "transition_shell": {
                            "entry": {"type": "dissolve", "duration_seconds": 0.08}
                        },
                    },
                ],
                source_duration=3,
            )
            contract = timeline_splice.load_contract(contract_path)

            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved == ui:
                    return info(resolved, 1.95)
                if resolved == root / "following.mp4":
                    return info(resolved, 1.0)
                if resolved.name == "region-001.mp4":
                    return info(resolved, 1.95)
                if resolved.name == "region-002.mp4":
                    return info(resolved, 1.0)
                if resolved == output_path:
                    return info(resolved, 2.87)
                raise AssertionError(f"unexpected probe: {resolved}")

            with patch.object(timeline_splice, "probe_media", side_effect=probe), patch.object(
                timeline_splice,
                "detect_active_window",
                return_value=timeline_splice.ActiveWindow(
                    raw_duration=1.95,
                    active_start=0.0,
                    active_end=1.95,
                    leading_black_duration=0.0,
                    trailing_black_duration=0.0,
                    black_intervals=(),
                    internal_black_intervals=(),
                ),
            ), patch.object(
                timeline_splice,
                "render_transition_segments",
                return_value=(
                    output_path,
                    2.87,
                    [
                        {
                            "boundary_index": 0,
                            "source_type": "dissolve",
                            "ffmpeg_transition": "dissolve",
                            "duration": 0.08,
                            "offset": 1.87,
                            "rendered": True,
                            "render_hash": "a" * 64,
                            "source_shell_sha256": timeline_splice._boundary_between(
                                contract.regions[0], contract.regions[1], fps=contract.target_fps
                            ).source_shell_sha256,
                        }
                    ],
                ),
            ), patch.object(
                timeline_splice.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 0, "stderr": ""})(),
            ) as run:
                timeline_splice.splice_timeline(contract, output_path, manifest_path)

            ui_command = next(
                call.args[0]
                for call in run.call_args_list
                if str(ui) in call.args[0]
            )
            command = " ".join(ui_command).lower()
            self.assertNotIn("tpad", command)
            self.assertNotIn("apad", command)
            self.assertNotIn("atempo", command)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["placements"][0]["output_duration"], 1.95)
            self.assertEqual(manifest["planned_output_duration"], 2.87)

    def test_generated_ui_manifest_records_qc_digest_and_media_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "generated-ui.mp4"
            media.write_bytes(b"generated-ui")
            media_sha = hashlib.sha256(media.read_bytes()).hexdigest()
            truth = {"approved_copy": ["Continue"]}
            render_contract = {"page_state": "checkout"}
            contract_path = root / "timeline.json"
            output_path = root / "result.mp4"
            manifest_path = root / "manifest.json"
            write_contract(
                contract_path,
                [
                    {
                        "region_type": "generated_ui_demo",
                        "source_start": 0,
                        "source_end": 2,
                        "media_path": str(media),
                        "ui_truth_card": truth,
                        "ui_render_contract": render_contract,
                        "ui_qc_report": {
                            "passed": True,
                            "ocr_passed": True,
                            "approved_copy_passed": True,
                            "page_state_passed": True,
                            "layout_passed": True,
                            "media_sha256": media_sha,
                            "ui_truth_card_sha256": mapping_sha256(truth),
                            "ui_render_contract_sha256": mapping_sha256(
                                render_contract
                            ),
                            "ocr_match_percent": 100,
                            "layout_match_percent": 100,
                            "approved_copy_observed": ["Continue"],
                            "ocr_evidence": [
                                {"frame_ms": 500, "sha256": "a" * 64}
                            ],
                            "layout_evidence": [
                                {"frame_ms": 500, "sha256": "b" * 64}
                            ],
                        },
                    }
                ],
                source_duration=2,
            )
            contract = timeline_splice.load_contract(contract_path)
            def probe(path: Path) -> MediaInfo:
                resolved = Path(path)
                if resolved == media or resolved == output_path or resolved.name == "region-001.mp4":
                    return info(resolved, 2.0)
                raise AssertionError(f"unexpected probe: {resolved}")

            with patch.object(
                timeline_splice,
                "probe_media",
                side_effect=probe,
            ), patch.object(timeline_splice, "concat_segments"), patch.object(
                timeline_splice.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 0, "stderr": ""})(),
            ):
                timeline_splice.splice_timeline(contract, output_path, manifest_path)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            placement = manifest["placements"][0]
            self.assertEqual(placement["region_type"], "generated_ui_demo")
            self.assertEqual(placement["ui_qc"]["media_sha256"], media_sha)
            self.assertTrue(placement["ui_qc"]["report_sha256"])
            self.assertEqual(
                placement["ui_qc"]["ui_truth_card_sha256"],
                mapping_sha256(truth),
            )
            self.assertEqual(placement["ui_qc"]["ocr_match_percent"], 100)


if __name__ == "__main__":
    unittest.main()
