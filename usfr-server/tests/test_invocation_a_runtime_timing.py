from __future__ import annotations

import time
import unittest

from server.errors import ReplicationError
from server.high_fidelity_ports import HighFidelityStageAdapter


class _Invocation:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay

    def invoke_a(self, **_kwargs):
        if self.delay:
            time.sleep(self.delay)
        return {"status": "ready", "profile": "seedance20_prescript_v1"}


class _Context:
    stage = "build_script"
    profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}
    invocation_a_timeout_seconds = 0.02

    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, str]] = []

    def record_profile_metric(self, name: str, *, duration_seconds: float, status: str) -> None:
        self.metrics.append((name, duration_seconds, status))


class InvocationARuntimeTimingTest(unittest.TestCase):
    def test_success_records_invocation_a_metric(self) -> None:
        context = _Context()
        context.invocation_a_timeout_seconds = 1.0
        result = HighFidelityStageAdapter(_Invocation()).run_stage(
            context=context,
            handler=lambda **_: {"invocation_a_request": {"candidate_regions": []}},
        )
        self.assertEqual(result["invocation_a"]["status"], "ready")
        self.assertEqual(context.metrics[0][0], "seedance_invocation_a")
        self.assertEqual(context.metrics[0][2], "succeeded")

    def test_timeout_records_metric_and_blocks_stage(self) -> None:
        context = _Context()
        with self.assertRaisesRegex(ReplicationError, "120-second deadline"):
            HighFidelityStageAdapter(_Invocation(delay=0.1)).run_stage(
                context=context,
                handler=lambda **_: {"invocation_a_request": {"candidate_regions": []}},
            )
        self.assertEqual(context.metrics[0][0], "seedance_invocation_a")
        self.assertEqual(context.metrics[0][2], "timeout")

    def test_legacy_marks_invocation_a_skipped(self) -> None:
        context = _Context()
        context.profile_snapshot = None
        HighFidelityStageAdapter(_Invocation()).run_stage(
            context=context,
            handler=lambda **_: {"legacy": True},
        )
        self.assertEqual(context.metrics[0][0], "seedance_invocation_a")
        self.assertEqual(context.metrics[0][2], "skipped")

    def test_shadow_profile_skips_invocation_a_without_provider_work(self) -> None:
        context = _Context()
        context.profile_snapshot = {"profile": "high_fidelity_hybrid_v1", "activation_mode": "shadow"}
        HighFidelityStageAdapter(_Invocation(delay=0.1)).run_stage(
            context=context,
            handler=lambda **_: {"legacy": True},
        )
        self.assertEqual(context.metrics[0][2], "skipped")


if __name__ == "__main__":
    unittest.main()
