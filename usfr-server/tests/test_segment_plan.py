from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = (
    ROOT
    / "bundled-skills"
    / "seedance-storyboard-replication"
    / "scripts"
)
sys.path.insert(0, str(SCRIPT_ROOT))

import segment_plan  # noqa: E402


def _generated(
    region_id: str,
    start_ms: int,
    end_ms: int,
    cut_ids: list[str],
) -> dict:
    return {
        "region_id": region_id,
        "region_type": "generated",
        "media_origin": "generated_media",
        "assembly_policy": "generate_region",
        "start_ms": start_ms,
        "end_ms": end_ms,
        "cut_ids": cut_ids,
    }


def _excluded(
    region_id: str,
    region_type: str,
    start_ms: int,
    end_ms: int,
) -> dict:
    return {
        "region_id": region_id,
        "region_type": region_type,
        "media_origin": "generated_media",
        "assembly_policy": "generate_ui",
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def _cut(cut_id: str, start_ms: int, end_ms: int) -> dict:
    return {"cut_id": cut_id, "start_ms": start_ms, "end_ms": end_ms}


class StructuredSegmentPlannerTest(unittest.TestCase):
    def _plan(self, timeline_regions, cuts, **kwargs):
        planner = getattr(segment_plan, "plan_structured_segments", None)
        self.assertTrue(
            callable(planner),
            "segment_plan.py must expose plan_structured_segments",
        )
        return planner(timeline_regions, cuts, **kwargs)

    def test_returns_canonical_discontiguous_segments_and_excludes_local_routes(self):
        regions = [
            {
                "region_id": "source-before",
                "region_type": "source_interval",
                "media_origin": "source_interval",
                "assembly_policy": "splice_source_interval",
                "start_ms": 0,
                "end_ms": 2_000,
            },
            _generated("gen-a", 2_000, 8_000, ["C01", "C02"]),
            _excluded("generated-ui", "generated_ui_demo", 8_000, 12_000),
            _excluded("opaque-ui", "opaque_ui_demo", 12_000, 14_000),
            _generated("gen-b", 14_000, 20_000, ["C04"]),
            _excluded("tail", "excluded_app_end_card", 20_000, 23_000),
        ]
        cuts = [
            _cut("C00", 0, 2_000),
            _cut("C01", 2_000, 5_000),
            _cut("C02", 5_000, 8_000),
            _cut("C03", 8_000, 12_000),
            _cut("C04", 14_000, 20_000),
            _cut("C05", 20_000, 23_000),
        ]

        result = self._plan(regions, cuts)

        self.assertEqual(
            result,
            {
                "segments": [
                    {
                        "segment_id": "S01",
                        "start_ms": 2_000,
                        "end_ms": 8_000,
                        "duration_ms": 6_000,
                        "cut_ids": ["C01", "C02"],
                    },
                    {
                        "segment_id": "S02",
                        "start_ms": 14_000,
                        "end_ms": 20_000,
                        "duration_ms": 6_000,
                        "cut_ids": ["C04"],
                    },
                ]
            },
        )

    def test_long_region_requires_an_approved_split_boundary(self):
        regions = [_generated("gen-long", 0, 18_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 9_000), _cut("C02", 9_000, 18_000)]

        with self.assertRaisesRegex(
            segment_plan.PlanningError,
            "approved_split_boundary_ms",
        ):
            self._plan(regions, cuts)

    def test_approved_cut_boundary_splits_one_long_region(self):
        regions = [_generated("gen-long", 0, 18_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 9_000), _cut("C02", 9_000, 18_000)]

        result = self._plan(
            regions,
            cuts,
            approved_split_boundary_ms=9_000,
        )

        self.assertEqual(
            result,
            {
                "segments": [
                    {
                        "segment_id": "S01",
                        "start_ms": 0,
                        "end_ms": 9_000,
                        "duration_ms": 9_000,
                        "cut_ids": ["C01"],
                    },
                    {
                        "segment_id": "S02",
                        "start_ms": 9_000,
                        "end_ms": 18_000,
                        "duration_ms": 9_000,
                        "cut_ids": ["C02"],
                    },
                ]
            },
        )

    def test_sixteen_second_region_retimes_to_one_fifteen_second_segment(self):
        regions = [_generated("gen-retime", 0, 16_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 8_000), _cut("C02", 8_000, 16_000)]

        result = self._plan(regions, cuts)

        self.assertEqual(
            result,
            {
                "segments": [{
                    "segment_id": "S01",
                    "start_ms": 0,
                    "end_ms": 15_000,
                    "duration_ms": 15_000,
                    "cut_ids": ["C01", "C02"],
                }]
            },
        )

    def test_retime_requires_approved_output_time_mapping_for_all_timed_obligations(self):
        regions = [_generated("gen-retime", 0, 16_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 8_000), _cut("C02", 8_000, 16_000)]
        cases = {
            "line_contracts": [{
                "line_id": "L01",
                "cut_id": "C01",
                "time": {"start_ms": 1_000, "end_ms": 2_000},
            }],
            "proof_events": [{"id": "P01", "start_ms": 1_000, "end_ms": 2_000}],
            "foley_events": [{"id": "F01", "start_ms": 1_000, "end_ms": 2_000}],
            "silence_windows": [{"id": "Q01", "start_ms": 1_000, "end_ms": 2_000}],
            "action_endpoints": [{"id": "A01", "start_ms": 1_000, "end_ms": 2_000}],
        }

        for argument, value in cases.items():
            with self.subTest(argument=argument):
                with self.assertRaisesRegex(
                    segment_plan.PlanningError,
                    "retime changes approved timing",
                ):
                    self._plan(regions, cuts, **{argument: value})

    def test_explicit_output_timing_allows_approved_retimed_windows(self):
        region = _generated("gen-retime", 0, 16_000, ["C01", "C02"])
        region["source_start_ms"] = 0
        region["source_end_ms"] = 16_000
        region["output_start_ms"] = 0
        region["output_end_ms"] = 15_000
        cuts = [
            {
                **_cut("C01", 0, 8_000),
                "source_start_ms": 0,
                "source_end_ms": 8_000,
                "output_start_ms": 0,
                "output_end_ms": 7_500,
            },
            {
                **_cut("C02", 8_000, 16_000),
                "source_start_ms": 8_000,
                "source_end_ms": 16_000,
                "output_start_ms": 7_500,
                "output_end_ms": 15_000,
            },
        ]

        result = self._plan(
            [region],
            cuts,
            line_contracts=[{
                "line_id": "L01",
                "cut_id": "C01",
                "time": {"start_ms": 938, "end_ms": 1_875},
            }],
            action_endpoints=[{"id": "A01", "at_ms": 14_999}],
        )

        self.assertEqual(result["segments"][0]["duration_ms"], 15_000)

    def test_split_boundary_must_be_an_exact_cut_boundary(self):
        regions = [_generated("gen-long", 0, 18_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 9_000), _cut("C02", 9_000, 18_000)]

        with self.assertRaisesRegex(
            segment_plan.PlanningError,
            "approved Cut boundary",
        ):
            self._plan(
                regions,
                cuts,
                approved_split_boundary_ms=8_000,
            )

    def test_split_boundary_must_be_an_exact_integer_millisecond(self):
        regions = [_generated("gen-long", 0, 18_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 9_000), _cut("C02", 9_000, 18_000)]

        for invalid in (9_000.4, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    segment_plan.PlanningError,
                    "integer",
                ):
                    self._plan(
                        regions,
                        cuts,
                        approved_split_boundary_ms=invalid,
                    )

    def test_rejects_generated_duration_outside_four_to_fifteen_seconds(self):
        with self.assertRaisesRegex(segment_plan.PlanningError, "4-15"):
            self._plan(
                [_generated("too-short", 0, 3_999, ["C01"])],
                [_cut("C01", 0, 3_999)],
            )

    def test_rejects_more_than_two_planned_segments(self):
        regions = [
            _generated("gen-a", 0, 5_000, ["C01"]),
            _generated("gen-b", 6_000, 11_000, ["C02"]),
            _generated("gen-c", 12_000, 17_000, ["C03"]),
        ]
        cuts = [
            _cut("C01", 0, 5_000),
            _cut("C02", 6_000, 11_000),
            _cut("C03", 12_000, 17_000),
        ]

        with self.assertRaisesRegex(segment_plan.PlanningError, "at most two"):
            self._plan(regions, cuts)

    def test_rejects_duplicate_cut_coverage(self):
        regions = [
            _generated("gen-a", 0, 6_000, ["C01"]),
            _generated("gen-b", 6_000, 12_000, ["C01"]),
        ]
        cuts = [_cut("C01", 0, 6_000)]

        with self.assertRaisesRegex(
            segment_plan.PlanningError,
            "Cut coverage|continuously cover",
        ):
            self._plan(regions, cuts)

    def test_rejects_out_of_order_or_overlapping_generated_regions(self):
        regions = [
            _generated("gen-a", 6_000, 12_000, ["C02"]),
            _generated("gen-b", 0, 7_000, ["C01"]),
        ]
        cuts = [_cut("C01", 0, 7_000), _cut("C02", 6_000, 12_000)]

        with self.assertRaisesRegex(segment_plan.PlanningError, "ordered and non-overlapping"):
            self._plan(regions, cuts)

    def test_rejects_generated_region_with_incomplete_canonical_route_fields(self):
        malformed = _generated("gen-a", 0, 8_000, ["C01"])
        malformed.pop("assembly_policy")

        with self.assertRaisesRegex(segment_plan.PlanningError, "canonical ordinary generated"):
            self._plan([malformed], [_cut("C01", 0, 8_000)])

    def test_rejects_overlap_between_generated_and_excluded_regions(self):
        regions = [
            _generated("gen-a", 0, 8_000, ["C01"]),
            _excluded("generated-ui", "generated_ui_demo", 7_000, 12_000),
        ]

        with self.assertRaisesRegex(segment_plan.PlanningError, "timeline regions.*overlap"):
            self._plan(regions, [_cut("C01", 0, 8_000)])

    def test_rejects_cut_time_gaps_inside_generated_region(self):
        regions = [_generated("gen-a", 0, 8_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 3_000), _cut("C02", 5_000, 8_000)]

        with self.assertRaisesRegex(segment_plan.PlanningError, "continuously cover"):
            self._plan(regions, cuts)

    def test_line_contract_must_not_cross_a_segment_boundary(self):
        regions = [_generated("gen-long", 0, 18_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 9_000), _cut("C02", 9_000, 18_000)]
        lines = [
            {
                "line_id": "L01",
                "cut_id": "C01",
                "time": {"start_ms": 8_500, "end_ms": 9_500},
            }
        ]

        with self.assertRaisesRegex(segment_plan.PlanningError, "line.*crosses"):
            self._plan(
                regions,
                cuts,
                approved_split_boundary_ms=9_000,
                line_contracts=lines,
            )

    def test_nested_proof_foley_and_silence_windows_must_stay_with_the_line_segment(self):
        regions = [_generated("gen-long", 0, 18_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 9_000), _cut("C02", 9_000, 18_000)]

        for collection in ("proof_events", "foley_events", "silence_windows"):
            with self.subTest(collection=collection):
                lines = [
                    {
                        "line_id": "L01",
                        "cut_id": "C01",
                        "time": {"start_ms": 1_000, "end_ms": 2_000},
                        collection: [
                            {
                                "id": f"{collection}-1",
                                "start_ms": 8_500,
                                "end_ms": 9_500,
                            }
                        ],
                    }
                ]
                with self.assertRaisesRegex(
                    segment_plan.PlanningError,
                    collection,
                ):
                    self._plan(
                        regions,
                        cuts,
                        approved_split_boundary_ms=9_000,
                        line_contracts=lines,
                    )

    def test_top_level_proof_foley_and_silence_windows_must_not_cross_segments(self):
        regions = [
            _generated("gen-a", 0, 8_000, ["C01"]),
            _generated("gen-b", 10_000, 18_000, ["C02"]),
        ]
        cuts = [_cut("C01", 0, 8_000), _cut("C02", 10_000, 18_000)]
        crossing = [{"id": "event-1", "start_ms": 7_500, "end_ms": 10_500}]

        for argument in ("proof_events", "foley_events", "silence_windows"):
            with self.subTest(argument=argument):
                with self.assertRaisesRegex(segment_plan.PlanningError, argument):
                    self._plan(regions, cuts, **{argument: crossing})

    def test_action_endpoint_must_not_cross_a_segment_boundary(self):
        regions = [_generated("gen-long", 0, 18_000, ["C01", "C02"])]
        cuts = [_cut("C01", 0, 9_000), _cut("C02", 9_000, 18_000)]

        with self.assertRaisesRegex(segment_plan.PlanningError, "action_endpoints"):
            self._plan(
                regions,
                cuts,
                approved_split_boundary_ms=9_000,
                action_endpoints=[{
                    "id": "END-01",
                    "start_ms": 8_500,
                    "end_ms": 9_500,
                }],
            )

    def test_point_action_endpoint_must_fall_inside_one_segment(self):
        regions = [_generated("gen-a", 0, 8_000, ["C01"])]
        cuts = [_cut("C01", 0, 8_000)]

        result = self._plan(
            regions,
            cuts,
            action_endpoints=[{"id": "END-01", "at_ms": 7_999}],
        )
        self.assertEqual(len(result["segments"]), 1)

        with self.assertRaisesRegex(segment_plan.PlanningError, "action_endpoints"):
            self._plan(
                regions,
                cuts,
                action_endpoints=[{"id": "END-02", "at_ms": 8_000}],
            )

    def test_falsey_non_array_event_contract_is_rejected(self):
        regions = [_generated("gen-a", 0, 8_000, ["C01"])]
        cuts = [_cut("C01", 0, 8_000)]
        line = {
            "line_id": "L01",
            "cut_id": "C01",
            "time": {"start_ms": 1_000, "end_ms": 2_000},
            "proof_events": False,
        }

        with self.assertRaisesRegex(segment_plan.PlanningError, "proof_events must be an array"):
            self._plan(regions, cuts, line_contracts=[line])

    def test_valid_line_and_event_windows_are_accepted(self):
        regions = [
            _generated("gen-a", 0, 8_000, ["C01"]),
            _generated("gen-b", 10_000, 18_000, ["C02"]),
        ]
        cuts = [_cut("C01", 0, 8_000), _cut("C02", 10_000, 18_000)]
        lines = [
            {
                "line_id": "L01",
                "cut_id": "C01",
                "time": {"start_ms": 1_000, "end_ms": 2_000},
                "proof_events": [{"id": "P01", "start_ms": 2_000, "end_ms": 2_500}],
                "foley_events": [{"id": "F01", "start_ms": 3_000, "end_ms": 3_200}],
                "silence_windows": [{"id": "Q01", "start_ms": 4_000, "end_ms": 4_500}],
            },
            {
                "line_id": "L02",
                "cut_id": "C02",
                "time": {"start_ms": 11_000, "end_ms": 12_000},
            },
        ]

        result = self._plan(
            regions,
            cuts,
            line_contracts=lines,
            proof_events=[{"id": "P02", "start_ms": 12_000, "end_ms": 12_500}],
            foley_events=[{"id": "F02", "start_ms": 13_000, "end_ms": 13_100}],
            silence_windows=[{"id": "Q02", "start_ms": 14_000, "end_ms": 14_500}],
        )

        self.assertEqual(len(result["segments"]), 2)

    def test_all_non_seedance_regions_do_not_create_an_empty_plan(self):
        regions = [
            _excluded("generated-ui", "generated_ui_demo", 0, 5_000),
            _excluded("opaque-ui", "opaque_ui_demo", 5_000, 10_000),
            _excluded("tail", "excluded_app_end_card", 10_000, 13_000),
        ]

        with self.assertRaisesRegex(segment_plan.PlanningError, "ordinary generated"):
            self._plan(regions, [])

    def test_legacy_boundary_planner_remains_available(self):
        legacy = segment_plan.plan_segments([0.0, 8.0])

        self.assertEqual(legacy.to_dict()["segments"][0]["output_duration"], 8.0)

    def test_legacy_boundary_planner_keeps_retime_and_explicit_split_behavior(self):
        retimed = segment_plan.plan_segments([0.0, 8.0, 16.0])
        split = segment_plan.plan_segments([0.0, 9.0, 18.0], split_boundary=9.0)

        self.assertEqual(retimed.to_dict()["segments"][0]["output_duration"], 15.0)
        self.assertEqual(len(split.to_dict()["segments"]), 2)


if __name__ == "__main__":
    unittest.main()
