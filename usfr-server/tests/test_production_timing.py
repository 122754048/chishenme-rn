import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from production_timing import ProductionTiming  # noqa: E402


class FakeClock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ProductionTimingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "timing_log.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_approval_wait_is_excluded_from_active_processing(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        clock.advance(120)
        timing.pause_approval("script")
        clock.advance(600)
        timing.resume_approval("script")
        clock.advance(180)
        result = timing.finish()
        self.assertEqual(result["end_to_end_seconds"], 900)
        self.assertEqual(result["approval_wait_seconds"], 600)
        self.assertEqual(result["active_processing_seconds"], 300)

    def test_thirty_minutes_is_recorded_not_enforced(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        clock.advance(1900)
        result = timing.finish()
        self.assertEqual(result["active_processing_seconds"], 1900)
        self.assertFalse(result["target_met"])

    def test_provider_stage_is_counted_separately(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        timing.start_stage("runninghub", provider=True)
        clock.advance(12)
        timing.end_stage("runninghub")
        timing.start_stage("qc")
        clock.advance(8)
        timing.end_stage("qc")
        result = timing.finish()
        self.assertEqual(result["provider_seconds"], 12)
        self.assertEqual(result["active_processing_seconds"], 20)
        self.assertEqual(result["slowest_stage"], "runninghub")

    def test_invalid_nested_states_are_rejected(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        with self.assertRaises(RuntimeError):
            timing.finish()
        timing.start()
        timing.pause_approval("storyboard")
        with self.assertRaises(RuntimeError):
            timing.pause_approval("script")
        with self.assertRaises(RuntimeError):
            timing.start_stage("provider", provider=True)
        with self.assertRaises(RuntimeError):
            timing.resume_approval("script")
        timing.resume_approval("storyboard")
        timing.start_stage("provider", provider=True)
        with self.assertRaises(RuntimeError):
            timing.start_stage("nested")

    def test_existing_log_is_resumed_and_written_atomically(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        clock.advance(10)
        timing.pause_approval("script")
        clock.advance(5)
        timing.resume_approval("script")
        resumed = ProductionTiming(self.path, clock=clock)
        clock.advance(10)
        result = resumed.finish()
        self.assertEqual(result["end_to_end_seconds"], 25)
        self.assertEqual(result["approval_wait_seconds"], 5)
        with self.path.open(encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["finished_at"], 25)

    def write_log(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_existing_json_must_be_an_object(self):
        self.write_log([])
        with self.assertRaisesRegex(ValueError, "JSON object"):
            ProductionTiming(self.path, clock=FakeClock())

    def test_partial_log_with_inconsistent_stage_is_rejected(self):
        self.write_log({"started_at": 0, "stage_name": "runninghub_standard"})
        with self.assertRaisesRegex(ValueError, "stage_name and stage_started_at"):
            ProductionTiming(self.path, clock=FakeClock())

    def test_partial_log_with_inconsistent_approval_pause_is_rejected(self):
        self.write_log({"started_at": 0, "paused_gate": "script"})
        with self.assertRaisesRegex(ValueError, "paused_gate and paused_at"):
            ProductionTiming(self.path, clock=FakeClock())

    def test_negative_or_non_finite_accounting_is_rejected(self):
        for field, value in (
            ("provider_seconds", -1),
            ("approval_wait_seconds", float("nan")),
            ("active_processing_seconds", -1),
        ):
            with self.subTest(field=field):
                self.write_log({"started_at": 0, field: value})
                with self.assertRaisesRegex(ValueError, field):
                    ProductionTiming(self.path, clock=FakeClock())

    def test_persisted_target_cannot_override_measurement_target(self):
        self.write_log({"started_at": 0, "target_seconds": 1})
        clock = FakeClock()
        clock.advance(2)
        result = ProductionTiming(self.path, clock=clock).finish()
        self.assertEqual(result["target_seconds"], 1800)
        self.assertTrue(result["target_met"])

    def test_backward_clock_is_rejected_before_negative_duration(self):
        clock = FakeClock()
        clock.advance(10)
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        clock.value = 9
        with self.assertRaisesRegex(RuntimeError, "clock moved backwards"):
            timing.start_stage("qc")

    def test_resumed_log_rejects_clock_earlier_than_last_transition(self):
        clock = FakeClock()
        clock.advance(10)
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        clock.advance(5)
        timing.pause_approval("script")
        resumed_clock = FakeClock()
        resumed_clock.value = 14
        resumed = ProductionTiming(self.path, clock=resumed_clock)
        with self.assertRaisesRegex(RuntimeError, "clock moved backwards"):
            resumed.start()

    def test_finished_log_cannot_be_resumed_or_mutated(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        timing.finish()
        resumed = ProductionTiming(self.path, clock=clock)
        with self.assertRaisesRegex(RuntimeError, "already finished"):
            resumed.start()
        with self.assertRaisesRegex(RuntimeError, "already finished"):
            resumed.start_stage("qc")

    def test_skipped_internal_profile_work_is_recorded_without_active_time(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        timing.record_skipped("seedance_invocation_a", reason="local_only")
        timing.record_skipped("seedance_invocation_b", reason="opaque_only")
        clock.advance(3)
        result = timing.finish()
        self.assertEqual(result["active_processing_seconds"], 3)
        self.assertEqual(
            result["skipped_stages"],
            {
                "seedance_invocation_a": "local_only",
                "seedance_invocation_b": "opaque_only",
            },
        )

    def test_invocation_a_metrics_are_persisted_and_validated(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        timing.record_profile_metric(
            "seedance_invocation_a", duration_seconds=2.5, status="succeeded"
        )
        clock.advance(1)
        result = timing.finish()
        self.assertEqual(result["profile_metrics"]["seedance_invocation_a"]["p50_seconds"], 2.5)
        self.assertEqual(result["profile_metrics"]["seedance_invocation_a"]["samples"], [2.5])

    def test_invocation_a_metric_can_be_recorded_inside_existing_stage(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        timing.start_stage("build_script")
        clock.advance(2.5)
        timing.record_profile_metric(
            "seedance_invocation_a", duration_seconds=2.5, status="succeeded"
        )
        clock.advance(1.0)
        timing.end_stage("build_script")
        result = timing.finish()
        self.assertEqual(result["stage_seconds"]["build_script"], 3.5)
        self.assertEqual(
            result["profile_metrics"]["seedance_invocation_a"]["samples"],
            [2.5],
        )

    def test_invocation_a_hard_timeout_is_enforced_by_the_ledger(self):
        clock = FakeClock()
        timing = ProductionTiming(self.path, clock=clock)
        timing.start()
        with self.assertRaisesRegex(ValueError, "120"):
            timing.record_profile_metric(
                "seedance_invocation_a", duration_seconds=121, status="succeeded"
            )


if __name__ == "__main__":
    unittest.main()
