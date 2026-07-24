from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))
from timeline_splice import TimelineSpliceError, load_contract  # noqa: E402


def write_contract(
    path: Path,
    regions: list[dict],
    *,
    source_duration: float = 10.0,
    source_fps: float | None = None,
    extra: dict | None = None,
) -> None:
    payload = {
        "source_duration": source_duration,
        "target": {"width": 720, "height": 1280, "fps": 24},
        "regions": regions,
    }
    if source_fps is not None:
        payload["source_fps"] = source_fps
    if extra:
        payload.update(extra)
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def mapping_sha256(value: dict) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def generated_ui_qc(
    *,
    media_sha256: str,
    truth: dict,
    render: dict,
    **overrides,
) -> dict:
    report = {
        "passed": True,
        "ocr_passed": True,
        "approved_copy_passed": True,
        "page_state_passed": True,
        "layout_passed": True,
        "media_sha256": media_sha256,
        "ui_truth_card_sha256": mapping_sha256(truth),
        "ui_render_contract_sha256": mapping_sha256(render),
        "ocr_match_percent": 100,
        "layout_match_percent": 100,
        "approved_copy_observed": truth["approved_copy"],
        "ocr_evidence": [{"frame_ms": 500, "sha256": "a" * 64}],
        "layout_evidence": [{"frame_ms": 500, "sha256": "b" * 64}],
    }
    report.update(overrides)
    return report


class TimelineRegionContractTest(unittest.TestCase):
    @staticmethod
    def _source_overlay_contract() -> dict:
        overlay = {
            "contract": "source-ui-overlay-motion",
            "contract_version": 1,
            "reference_duration_us": 10_000_000,
            "source_width": 720,
            "source_height": 1280,
            "coordinate_space": "rotation_corrected_source_visible_frame_normalized",
            "target_mapping": "source_normalized_composition_to_target_frame",
            "attachment": "screen_space",
            "time_range_semantics": "start_inclusive_end_exclusive",
            "cuts": [
                {
                    "cut": 1,
                    "start_us": 0,
                    "end_us": 5_000_000,
                    "source_overlays": [
                        {
                            "overlay_id": "headline_hook",
                            "kind": "cta_text",
                            "start_us": 0,
                            "end_us": 5_000_000,
                            "start_rect": {"x": 0.05, "y": 0.02, "width": 0.9, "height": 0.08},
                            "end_rect": {"x": 0.05, "y": 0.02, "width": 0.9, "height": 0.08},
                            "start_rotation_deg": 0,
                            "end_rotation_deg": 0,
                            "start_opacity": 1,
                            "end_opacity": 1,
                            "motion_phase": "static",
                            "motion_path": "screen-space hold",
                            "z_index": 20,
                            "layer_relation": "above generated subject",
                            "interpolation": "hold",
                            "observed_text": "Source hook",
                            "keyframes": [
                                {
                                    "time_us": 0,
                                    "bbox": {"x": 0.05, "y": 0.02, "width": 0.9, "height": 0.08},
                                    "rotation_deg": 0,
                                    "opacity": 1,
                                },
                                {
                                    "time_us": 5_000_000,
                                    "bbox": {"x": 0.05, "y": 0.02, "width": 0.9, "height": 0.08},
                                    "rotation_deg": 0,
                                    "opacity": 1,
                                },
                            ],
                        }
                    ],
                },
                {
                    "cut": 2,
                    "start_us": 5_000_000,
                    "end_us": 10_000_000,
                    "source_overlays": [],
                },
            ],
        }
        return overlay

    def test_generated_region_with_declared_overlay_requires_render_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_id": "gen-a", "region_type": "generated", "source_start": 0, "source_end": 5, "media_path": "a.mp4"},
                    {"region_id": "gen-b", "region_type": "generated", "source_start": 5, "source_end": 10, "media_path": "b.mp4"},
                ],
                extra={"source_overlay_contract": self._source_overlay_contract()},
            )
            with self.assertRaisesRegex(
                TimelineSpliceError,
                "OVERLAY_RENDER_MAPPING_REQUIRED",
            ):
                load_contract(path)

    def test_generated_overlay_mapping_must_bind_contract_and_cover_overlay_ids(self):
        overlay = self._source_overlay_contract()
        overlay_sha = mapping_sha256(overlay)
        mapping = {
            "contract": "target-overlay-render-mapping",
            "contract_version": 1,
            "source_overlay_contract_sha256": overlay_sha,
            "regions": [
                {
                    "region_id": "gen-a",
                    "overlays": [
                        {
                            "overlay_id": "headline_hook",
                            "validated": True,
                            "render_mode": "deterministic_text",
                            "text": "Target hook",
                            "payload_sha256": "a" * 64,
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_id": "gen-a", "region_type": "generated", "source_start": 0, "source_end": 5, "media_path": "a.mp4"},
                    {"region_id": "gen-b", "region_type": "generated", "source_start": 5, "source_end": 10, "media_path": "b.mp4"},
                ],
                extra={
                    "source_overlay_contract": overlay,
                    "overlay_render_mapping": mapping,
                },
            )
            contract = load_contract(path)
        self.assertEqual(contract.source_overlay_contract_sha256, overlay_sha)
        self.assertEqual(contract.overlay_render_mapping_sha256, mapping_sha256(mapping))

    def test_region_carrier_rehydrates_overlay_contract_when_top_level_was_compacted(self):
        overlay = self._source_overlay_contract()
        overlay_sha = mapping_sha256(overlay)
        mapping = {
            "contract": "target-overlay-render-mapping",
            "contract_version": 1,
            "source_overlay_contract_sha256": overlay_sha,
            "regions": [
                {
                    "region_id": "gen-a",
                    "overlays": [
                        {
                            "overlay_id": "headline_hook",
                            "validated": True,
                            "render_mode": "deterministic_text",
                            "text": "Target hook",
                            "payload_sha256": "a" * 64,
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_id": "gen-a",
                        "region_type": "generated",
                        "source_start": 0,
                        "source_end": 5,
                        "media_path": "a.mp4",
                        "source_overlay_contract": overlay,
                        "source_overlay_contract_sha256": overlay_sha,
                        "overlay_render_mapping": mapping,
                    },
                    {"region_id": "gen-b", "region_type": "generated", "source_start": 5, "source_end": 10, "media_path": "b.mp4"},
                ],
            )
            contract = load_contract(path)
        self.assertEqual(contract.source_overlay_contract_sha256, overlay_sha)
        self.assertEqual(contract.overlay_render_mapping_sha256, mapping_sha256(mapping))

    def test_active_overlay_contract_requires_render_receipts(self):
        overlay = self._source_overlay_contract()
        overlay_sha = mapping_sha256(overlay)
        mapping = {
            "contract": "target-overlay-render-mapping",
            "contract_version": 1,
            "source_overlay_contract_sha256": overlay_sha,
            "regions": [{
                "region_id": "gen-a",
                "overlays": [{
                    "overlay_id": "headline_hook",
                    "validated": True,
                    "render_mode": "deterministic_text",
                    "text": "Target hook",
                    "payload_sha256": "a" * 64,
                }],
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_id": "gen-a", "region_type": "generated", "source_start": 0, "source_end": 5, "media_path": "a.mp4"},
                    {"region_id": "gen-b", "region_type": "generated", "source_start": 5, "source_end": 10, "media_path": "b.mp4"},
                ],
                extra={
                    "source_overlay_contract": overlay,
                    "overlay_render_mapping": mapping,
                    "overlay_render_receipts_required": True,
                },
            )
            with self.assertRaisesRegex(TimelineSpliceError, "OVERLAY_RENDER_RECEIPT_REQUIRED"):
                load_contract(path)

    def test_source_origin_ui_interval_is_valid_and_requires_splice_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_type": "opaque_ui_demo",
                        "source_start": 0,
                        "source_end": 10,
                        "media_path": "source-ui.mp4",
                        "media_origin": "source_interval",
                        "assembly_policy": "splice_source_interval",
                        "transition_shell": {
                            "entry": {"type": "hard_cut"},
                            "exit": {"type": "hard_cut"},
                        },
                    }
                ],
            )
            contract = load_contract(path)
        self.assertEqual(contract.regions[0].media_origin, "source_interval")
        self.assertEqual(
            contract.regions[0].assembly_policy,
            "splice_source_interval",
        )

    def test_source_origin_requires_explicit_media_path_and_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_type": "opaque_ui_demo",
                        "source_start": 0,
                        "source_end": 10,
                        "media_path": "source-ui.mp4",
                        "media_origin": "source_interval",
                        "transition_shell": {
                            "entry": {"type": "hard_cut"},
                            "exit": {"type": "hard_cut"},
                        },
                    }
                ],
            )
            with self.assertRaisesRegex(
                TimelineSpliceError, "assembly_policy=splice_source_interval"
            ):
                load_contract(path)

    def test_missing_opaque_ui_video_blocks_instead_of_omitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 4, "media_path": "a.mp4"},
                    {"region_type": "opaque_ui_demo", "source_start": 4, "source_end": 7, "media_path": None},
                    {"region_type": "generated", "source_start": 7, "source_end": 10, "media_path": "b.mp4"},
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "opaque_ui_demo.*requires"):
                load_contract(path)

    def test_legacy_missing_app_end_card_manifest_is_still_loadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 8, "media_path": "a.mp4"},
                    {"region_type": "excluded_app_end_card", "source_start": 8, "source_end": 10, "media_path": None},
                ],
            )
            contract = load_contract(path)
        self.assertEqual(contract.regions[-1].kind, "excluded_app_end_card")
        self.assertIsNone(contract.regions[-1].media_path)

    def test_generated_ui_requires_rendered_or_generated_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 4, "media_path": "a.mp4"},
                    {"region_type": "generated_ui_demo", "source_start": 4, "source_end": 10, "media_path": None},
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "generated_ui_demo.*requires"):
                load_contract(path)

    def test_non_hard_entry_transition_is_owned_by_the_canonical_compositor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 8, "media_path": "a.mp4"},
                    {
                        "region_type": "excluded_app_end_card",
                        "source_start": 8,
                        "source_end": 10,
                        "media_path": "tail.mp4",
                        "transition_shell": {"in": {"type": "push_left", "duration_frames": 6}},
                        "transition_shell_applied": False,
                    },
                ],
            )
            contract = load_contract(path)

        self.assertEqual(
            contract.regions[-1].transition_shell["entry"]["type"],
            "push_left",
        )
        self.assertFalse(contract.regions[-1].transition_shell_applied)

    def test_supplied_end_card_requires_explicit_entry_transition_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 8, "media_path": "a.mp4"},
                    {
                        "region_type": "excluded_app_end_card",
                        "source_start": 8,
                        "source_end": 10,
                        "media_path": "tail.mp4",
                    },
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "transition_shell.*entry.*required"):
                load_contract(path)

    def test_opaque_ui_requires_explicit_entry_and_exit_shells(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 4, "media_path": "a.mp4"},
                    {
                        "region_type": "opaque_ui_demo",
                        "source_start": 4,
                        "source_end": 7,
                        "media_path": "ui.mp4",
                        "transition_shell": {"entry": {"type": "hard_cut"}},
                    },
                    {"region_type": "generated", "source_start": 7, "source_end": 10, "media_path": "b.mp4"},
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "transition_shell.*exit.*required"):
                load_contract(path)

    def test_opaque_ui_only_region_requires_no_external_exit_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_type": "opaque_ui_demo",
                        "source_start": 0,
                        "source_end": 10,
                        "media_path": "ui.mp4",
                        "transition_shell": {"entry": {"type": "hard_cut"}},
                    }
                ],
            )
            contract = load_contract(path)
        self.assertEqual(contract.regions[0].kind, "opaque_ui_demo")

    def test_legacy_region_kinds_migrate_to_canonical_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"kind": "generated", "source_start": 0, "source_end": 4, "media_path": "a.mp4"},
                    {
                        "kind": "ui_demo",
                        "source_start": 4,
                        "source_end": 7,
                        "media_path": "ui.mp4",
                        "transition_shell": {
                            "entry": {"type": "hard_cut"},
                            "exit": {"type": "hard_cut"},
                        },
                    },
                    {
                        "kind": "logo_download_animation",
                        "source_start": 7,
                        "source_end": 10,
                        "media_path": "tail.mp4",
                        "transition_shell": {"entry": {"type": "hard_cut"}},
                    },
                ],
            )
            contract = load_contract(path)

        self.assertEqual(
            [region.kind for region in contract.regions],
            ["generated", "opaque_ui_demo", "excluded_app_end_card"],
        )
        self.assertEqual(
            [region.legacy_kind for region in contract.regions],
            ["generated", "ui_demo", "logo_download_animation"],
        )

    def test_legacy_ui_without_media_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"kind": "generated", "source_start": 0, "source_end": 4, "media_path": "a.mp4"},
                    {"kind": "ui_demo", "source_start": 4, "source_end": 10, "media_path": None},
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "opaque_ui_demo.*requires"):
                load_contract(path)

    def test_canonical_route_name_is_not_accepted_through_legacy_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "kind": "opaque_ui_demo",
                        "source_start": 0,
                        "source_end": 10,
                        "media_path": "ui.mp4",
                    }
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "unsupported legacy kind"):
                load_contract(path)

    def test_canonical_and_legacy_region_fields_cannot_be_mixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_type": "excluded_app_end_card",
                        "kind": "ui_demo",
                        "source_start": 0,
                        "source_end": 10,
                        "media_path": None,
                    }
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "must not mix.*region_type.*kind"):
                load_contract(path)

    def test_generated_ui_requires_truth_render_and_qc_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "ui.mp4"
            media.write_bytes(b"rendered-ui")
            media_sha256 = hashlib.sha256(media.read_bytes()).hexdigest()
            truth = {"approved_copy": ["Continue"]}
            render = {"page_state": "checkout"}
            evidence = {
                "ui_truth_card": truth,
                "ui_render_contract": render,
                "ui_qc_report": generated_ui_qc(
                    media_sha256=media_sha256,
                    truth=truth,
                    render=render,
                ),
            }
            for missing_field in evidence:
                with self.subTest(missing_field=missing_field):
                    path = root / f"timeline-{missing_field}.json"
                    region = {
                        "region_type": "generated_ui_demo",
                        "source_start": 0,
                        "source_end": 10,
                        "media_path": str(media),
                        **{key: value for key, value in evidence.items() if key != missing_field},
                    }
                    write_contract(path, [region])
                    with self.assertRaisesRegex(TimelineSpliceError, missing_field):
                        load_contract(path)

    def test_generated_ui_failed_qc_check_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "ui.mp4"
            media.write_bytes(b"rendered-ui")
            media_sha256 = hashlib.sha256(media.read_bytes()).hexdigest()
            truth = {"approved_copy": ["Continue"]}
            render = {"page_state": "checkout"}
            for failed_check in (
                "ocr_passed",
                "approved_copy_passed",
                "page_state_passed",
                "layout_passed",
            ):
                with self.subTest(failed_check=failed_check):
                    qc = generated_ui_qc(
                        media_sha256=media_sha256,
                        truth=truth,
                        render=render,
                    )
                    qc[failed_check] = False
                    path = root / f"timeline-{failed_check}.json"
                    write_contract(
                        path,
                        [
                            {
                                "region_type": "generated_ui_demo",
                                "source_start": 0,
                                "source_end": 10,
                                "media_path": str(media),
                                "ui_truth_card": truth,
                                "ui_render_contract": render,
                                "ui_qc_report": qc,
                            }
                        ],
                    )
                    with self.assertRaisesRegex(TimelineSpliceError, failed_check):
                        load_contract(path)

    def test_generated_ui_rejects_contradictory_qc_summary_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "ui.mp4"
            media.write_bytes(b"rendered-ui")
            truth = {"approved_copy": ["Continue"]}
            render = {"page_state": "checkout"}
            path = root / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_type": "generated_ui_demo",
                        "source_start": 0,
                        "source_end": 10,
                        "media_path": str(media),
                        "ui_truth_card": truth,
                        "ui_render_contract": render,
                        "ui_qc_report": generated_ui_qc(
                            media_sha256=hashlib.sha256(media.read_bytes()).hexdigest(),
                            truth=truth,
                            render=render,
                            passed=False,
                            status="passed",
                        ),
                    }
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "ui_qc_report passed must be true"):
                load_contract(path)

    def test_generated_ui_media_hash_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "ui.mp4"
            media.write_bytes(b"rendered-ui")
            truth = {"approved_copy": ["Continue"]}
            render = {"page_state": "checkout"}
            path = root / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_type": "generated_ui_demo",
                        "source_start": 0,
                        "source_end": 10,
                        "media_path": str(media),
                        "ui_truth_card": truth,
                        "ui_render_contract": render,
                        "ui_qc_report": generated_ui_qc(
                            media_sha256="0" * 64,
                            truth=truth,
                            render=render,
                        ),
                    }
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "media SHA-256.*does not match"):
                load_contract(path)

    def test_microsecond_fields_are_authoritative_and_frame_tolerance_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_type": "generated",
                        "source_start_us": 0,
                        "source_end_us": 4_000_000,
                        "media_path": "a.mp4",
                    },
                    {
                        "region_type": "generated",
                        "source_start_us": 4_020_000,
                        "source_end_us": 10_000_000,
                        "media_path": "b.mp4",
                    },
                ],
                source_fps=30,
                extra={"source_duration_us": 10_000_000},
            )
            contract = load_contract(path)

        self.assertEqual(contract.source_duration, 10.0)
        self.assertEqual(contract.regions[0].source_end_us, 4_000_000)
        self.assertEqual(contract.regions[1].source_start, 4.02)

    def test_microsecond_contract_requires_source_fps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_type": "generated",
                        "source_start_us": 0,
                        "source_end_us": 10_000_000,
                        "media_path": "a.mp4",
                    }
                ],
                extra={"source_duration_us": 10_000_000},
            )
            with self.assertRaisesRegex(TimelineSpliceError, "source_fps.*required"):
                load_contract(path)

    def test_unsupported_transition_type_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {
                        "region_type": "excluded_app_end_card",
                        "source_start": 0,
                        "source_end": 10,
                        "media_path": "tail.mp4",
                        "transition_shell": {"entry": {"type": "spin_cube"}},
                    }
                ],
            )
            with self.assertRaisesRegex(TimelineSpliceError, "unsupported transition_shell type"):
                load_contract(path)

    def test_coverage_gap_larger_than_one_source_frame_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.json"
            write_contract(
                path,
                [
                    {"region_type": "generated", "source_start": 0, "source_end": 4, "media_path": "a.mp4"},
                    {"region_type": "generated", "source_start": 4.04, "source_end": 10, "media_path": "b.mp4"},
                ],
                source_fps=30,
            )
            with self.assertRaisesRegex(TimelineSpliceError, "continuously cover"):
                load_contract(path)


if __name__ == "__main__":
    unittest.main()
