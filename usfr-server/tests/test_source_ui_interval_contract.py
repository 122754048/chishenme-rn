from __future__ import annotations

import hashlib
import json

import pytest

from server.errors import ReplicationError
from server.orchestrator import bind_source_overlay_contract_to_timeline


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_route_regions_freezes_a_complete_source_interval_contract_for_generated_ui() -> None:
    routed = bind_source_overlay_contract_to_timeline(
        {
            "regions": [
                {
                    "region_id": "ui-001",
                    "region_type": "generated_ui_demo",
                    "source_start_us": 1_000_000,
                    "source_end_us": 3_000_000,
                    "display_viewport": [1080, 1920],
                    "rotation_degrees": 0,
                    "safe_cover_crop_percent": 0,
                    "transition_shell": {"entry": {"type": "hard_cut"}, "exit": {"type": "hard_cut"}},
                }
            ]
        },
        dynamics_output=None,
    )

    interval = {
        "schema_version": "source-ui-interval/v1",
        "region_id": "ui-001",
        "source_start_ms": 1000,
        "source_end_ms": 3000,
        "output_duration_ms": 2000,
        "display_viewport": [1080, 1920],
        "rotation_degrees": 0,
        "safe_cover_crop_percent": 0,
        "transition_shell": {"entry": {"type": "hard_cut"}, "exit": {"type": "hard_cut"}},
    }
    region = routed["regions"][0]
    assert region["source_interval_contract"] == interval
    assert region["source_interval_contract_sha256"] == _sha256(interval)


def test_route_regions_rejects_a_prefilled_interval_contract_that_differs_from_source_facts() -> None:
    region = {
        "region_id": "ui-001",
        "region_type": "generated_ui_demo",
        "source_start_us": 1_000_000,
        "source_end_us": 3_000_000,
        "display_viewport": [1080, 1920],
        "rotation_degrees": 0,
        "safe_cover_crop_percent": 0,
        "transition_shell": {"entry": {"type": "hard_cut"}, "exit": {"type": "hard_cut"}},
        "source_interval_contract": {
            "schema_version": "source-ui-interval/v1",
            "region_id": "ui-001",
            "source_start_ms": 0,
            "source_end_ms": 10_000,
            "output_duration_ms": 10_000,
            "display_viewport": [1080, 1920],
            "rotation_degrees": 0,
            "safe_cover_crop_percent": 0,
            "transition_shell": {"entry": {"type": "hard_cut"}, "exit": {"type": "hard_cut"}},
        },
    }

    with pytest.raises(ReplicationError, match="SOURCE_UI_INTERVAL_CONTRACT_MISMATCH"):
        bind_source_overlay_contract_to_timeline({"regions": [region]}, dynamics_output=None)
