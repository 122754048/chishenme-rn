from __future__ import annotations

from server.qc_escalation import build_qc_plan


def test_clean_technical_splice_uses_base_qc_only() -> None:
    plan = build_qc_plan(route="technical_splice", hard_failures=[], factor_scores={})
    assert plan["escalated_factors"] == []
    assert plan["prohibited_full_rerun"] is True
    assert "decode" in plan["base_checks"]


def test_low_lip_sync_escalates_only_audio_performance() -> None:
    plan = build_qc_plan(
        route="uploaded_music_mv",
        hard_failures=[],
        factor_scores={"lip_sync": 78, "timeline": 100},
    )
    assert plan["escalated_factors"] == ["lip_sync"]
