from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from server.remotion_react_ui import ConditionalUiRenderBackend


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class _Renderer:
    def __init__(self, name: str, digest: str) -> None:
        self.name = name
        self.digest = digest
        self.calls: list[str] = []

    def capability_identity(self):
        return {
            "implementation": f"tests:{self.name}",
            "version": "1",
            "sha256": self.digest,
        }

    def __call__(self, source, output, context, *, truth, render_contract):
        del source, output, context, truth, render_contract
        self.calls.append(self.name)
        return {"video_path": "ephemeral.mp4"}


def _eligible_context(*, source_interval_contract: dict | None = None):
    interval = source_interval_contract or {
        "schema_version": "source-ui-interval/v1",
        "region_id": "ui-1",
        "source_start_ms": 1000,
        "source_end_ms": 3000,
        "output_duration_ms": 2000,
        "display_viewport": [1080, 1920],
        "rotation_degrees": 0,
        "safe_cover_crop_percent": 0,
        "transition_shell": {"entry": "cut", "exit": "cut"},
    }
    return SimpleNamespace(
        timeline_regions=(
            {
                "region_id": "ui-1",
                "region_type": "generated_ui_demo",
                "source_start_us": 1_000_000,
                "source_end_us": 3_000_000,
                "display_viewport": [1080, 1920],
                "rotation_degrees": 0,
                "safe_cover_crop_percent": 0,
                "transition_shell": {"entry": "cut", "exit": "cut"},
                "deterministic_ui_rebuild_allowed": True,
                "existing_renderer_equivalent": False,
                "motion_actions": ["parallax", "scale"],
                "source_interval_contract": interval,
                "source_interval_contract_sha256": _sha(interval),
            },
        )
    )


def _activation_receipt(
    *,
    identity: dict[str, str],
    interval: dict,
    truth: dict,
    render_contract: dict,
    target_ui_evidence_sha256: str,
) -> tuple[str, dict]:
    bindings = {
        "source_interval_contract_sha256": _sha(interval),
        "target_ui_evidence_sha256": target_ui_evidence_sha256,
        "ui_truth_card_sha256": _sha(truth),
        "ui_render_contract_sha256": _sha(render_contract),
    }
    side = {
        **bindings,
        "ocr_match_percent": 100,
        "layout_match_percent": 100,
        "black_frame_count": 0,
        "timing_contract_matched": True,
        "active_seconds": 1.0,
    }
    report = {
        "schema_version": "usfr-backend-benchmark/v1",
        "candidate": "remotion_react_ui",
        "domain": "programmable_overlays",
        "adapter_identity": identity,
        "cases": [{"case_id": "ui-1", "candidate_case_id": "ui-1", "baseline": side, "candidate": side}],
    }
    report_sha256 = _sha(report)
    receipt = {
        "schema_version": "remotion-ui-activation-receipt/v1",
        "adapter_identity": identity,
        "benchmark_report": report,
        "benchmark_decision": {
            "schema_version": "usfr-backend-decision/v1",
            "candidate": "remotion_react_ui",
            "domain": "programmable_overlays",
            "report_sha256": report_sha256,
            "eligible": True,
            "no_hard_regressions": True,
        },
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return report_sha256, receipt


def _capabilities(*, renderer: _Renderer, context, truth: dict, render_contract: dict) -> dict:
    interval = context.timeline_regions[0]["source_interval_contract"]
    activation_sha256, receipt = _activation_receipt(
        identity=renderer.capability_identity(),
        interval=interval,
        truth=truth,
        render_contract=render_contract,
        target_ui_evidence_sha256="e" * 64,
    )
    return {
        "remotion_react_ui": {
            "status": "enabled",
            "domain": "programmable_overlays",
            "activation_report_sha256": activation_sha256,
            "activation_receipt": receipt,
            **renderer.capability_identity(),
        }
    }


def test_uses_remotion_only_with_complete_current_interval_and_matching_adapter() -> None:
    fallback = _Renderer("ffmpeg", "f" * 64)
    remotion = _Renderer("remotion", "d" * 64)
    context = _eligible_context()
    truth = {"states": [{"state_id": "home"}]}
    render_contract = {"route": "generated_ui_demo", "state_sequence": ["home"]}
    capabilities = _capabilities(
        renderer=remotion,
        context=context,
        truth=truth,
        render_contract=render_contract,
    )
    activation_sha = capabilities["remotion_react_ui"]["activation_report_sha256"]
    backend = ConditionalUiRenderBackend(
        fallback_renderer=fallback,
        remotion_renderer=remotion,
        capabilities=capabilities,
    )

    result = backend(
        Path("ui.png"),
        Path("ui.mp4"),
        context,
        truth=truth,
        render_contract=render_contract,
        target_ui_evidence_sha256="e" * 64,
    )

    assert remotion.calls == ["remotion"]
    assert fallback.calls == []
    assert result["ui_renderer_decision"] | {
        "backend": "remotion_react_ui",
        "enabled": True,
        "reason": "all_required_interval_evidence_and_activation_receipt_matched",
        "activation_report_sha256": activation_sha,
        "source_interval_contract_sha256": _sha(_eligible_context().timeline_regions[0]["source_interval_contract"]),
    } == result["ui_renderer_decision"]
    assert result["ui_renderer_decision"]["renderer_identity"] == remotion.capability_identity()
    assert result["ui_renderer_decision"]["duration_ms"] >= 0


def test_falls_back_when_activation_receipt_does_not_bind_the_installed_adapter() -> None:
    fallback = _Renderer("ffmpeg", "f" * 64)
    remotion = _Renderer("remotion", "d" * 64)
    backend = ConditionalUiRenderBackend(
        fallback_renderer=fallback,
        remotion_renderer=remotion,
        capabilities={
            "remotion_react_ui": {
                "status": "enabled",
                "domain": "programmable_overlays",
                "activation_report_sha256": "a" * 64,
                "implementation": "tests:remotion",
                "version": "1",
                "sha256": "e" * 64,
            }
        },
    )

    result = backend(
        Path("ui.png"),
        Path("ui.mp4"),
        _eligible_context(),
        truth={"states": [{"state_id": "home"}]},
        render_contract={"route": "generated_ui_demo", "state_sequence": ["home"]},
        target_ui_evidence_sha256="e" * 64,
    )

    assert fallback.calls == ["ffmpeg"]
    assert remotion.calls == []
    assert result["ui_renderer_decision"]["backend"] == "ffmpeg"
    assert result["ui_renderer_decision"]["reason"] == "remotion_adapter_identity_mismatch"


def test_falls_back_when_the_source_interval_contract_is_not_complete() -> None:
    fallback = _Renderer("ffmpeg", "f" * 64)
    remotion = _Renderer("remotion", "d" * 64)
    backend = ConditionalUiRenderBackend(
        fallback_renderer=fallback,
        remotion_renderer=remotion,
        capabilities={
            "remotion_react_ui": {
                "status": "enabled",
                "domain": "programmable_overlays",
                "activation_report_sha256": "a" * 64,
                **remotion.capability_identity(),
            }
        },
    )
    incomplete = dict(_eligible_context().timeline_regions[0]["source_interval_contract"])
    incomplete.pop("transition_shell")

    result = backend(
        Path("ui.png"),
        Path("ui.mp4"),
        _eligible_context(source_interval_contract=incomplete),
        truth={"states": [{"state_id": "home"}]},
        render_contract={"route": "generated_ui_demo", "state_sequence": ["home"]},
        target_ui_evidence_sha256="e" * 64,
    )

    assert fallback.calls == ["ffmpeg"]
    assert remotion.calls == []
    assert result["ui_renderer_decision"]["reason"] == "source_interval_contract_incomplete"


def test_falls_back_when_the_activation_digest_has_no_same_case_benchmark_receipt() -> None:
    fallback = _Renderer("ffmpeg", "f" * 64)
    remotion = _Renderer("remotion", "d" * 64)
    backend = ConditionalUiRenderBackend(
        fallback_renderer=fallback,
        remotion_renderer=remotion,
        capabilities={
            "remotion_react_ui": {
                "status": "enabled",
                "domain": "programmable_overlays",
                "activation_report_sha256": "a" * 64,
                **remotion.capability_identity(),
            }
        },
    )

    result = backend(
        Path("ui.png"),
        Path("ui.mp4"),
        _eligible_context(),
        truth={"states": [{"state_id": "home"}]},
        render_contract={"route": "generated_ui_demo", "state_sequence": ["home"]},
        target_ui_evidence_sha256="e" * 64,
    )

    assert fallback.calls == ["ffmpeg"]
    assert remotion.calls == []
    assert result["ui_renderer_decision"]["reason"] == "remotion_activation_receipt_unverified"


def test_falls_back_when_the_activation_receipt_binds_a_different_source_interval() -> None:
    fallback = _Renderer("ffmpeg", "f" * 64)
    remotion = _Renderer("remotion", "d" * 64)
    context = _eligible_context()
    truth = {"states": [{"state_id": "home"}]}
    render_contract = {"route": "generated_ui_demo", "state_sequence": ["home"]}
    capabilities = _capabilities(
        renderer=remotion,
        context=context,
        truth=truth,
        render_contract=render_contract,
    )
    receipt = capabilities["remotion_react_ui"]["activation_receipt"]
    report = receipt["benchmark_report"]
    for side in (report["cases"][0]["baseline"], report["cases"][0]["candidate"]):
        side["source_interval_contract_sha256"] = "0" * 64
    report_sha256 = _sha(report)
    receipt["benchmark_decision"]["report_sha256"] = report_sha256
    receipt["receipt_sha256"] = _sha({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    capabilities["remotion_react_ui"]["activation_report_sha256"] = report_sha256
    backend = ConditionalUiRenderBackend(
        fallback_renderer=fallback,
        remotion_renderer=remotion,
        capabilities=capabilities,
    )

    result = backend(
        Path("ui.png"),
        Path("ui.mp4"),
        context,
        truth=truth,
        render_contract=render_contract,
        target_ui_evidence_sha256="e" * 64,
    )

    assert fallback.calls == ["ffmpeg"]
    assert remotion.calls == []
    assert result["ui_renderer_decision"]["reason"] == "remotion_activation_receipt_unverified"


def test_falls_back_when_the_interval_contract_differs_from_the_region_source_facts() -> None:
    fallback = _Renderer("ffmpeg", "f" * 64)
    remotion = _Renderer("remotion", "d" * 64)
    interval = dict(_eligible_context().timeline_regions[0]["source_interval_contract"])
    interval["source_start_ms"] = 0
    interval["source_end_ms"] = 10_000
    interval["output_duration_ms"] = 10_000
    context = _eligible_context(source_interval_contract=interval)
    truth = {"states": [{"state_id": "home"}]}
    render_contract = {"route": "generated_ui_demo", "state_sequence": ["home"]}
    backend = ConditionalUiRenderBackend(
        fallback_renderer=fallback,
        remotion_renderer=remotion,
        capabilities=_capabilities(
            renderer=remotion,
            context=context,
            truth=truth,
            render_contract=render_contract,
        ),
    )

    result = backend(
        Path("ui.png"),
        Path("ui.mp4"),
        context,
        truth=truth,
        render_contract=render_contract,
        target_ui_evidence_sha256="e" * 64,
    )

    assert fallback.calls == ["ffmpeg"]
    assert remotion.calls == []
    assert result["ui_renderer_decision"]["reason"] == "source_interval_contract_source_facts_mismatch"


def test_falls_back_for_legacy_generated_ui_route_even_when_all_other_evidence_matches() -> None:
    fallback = _Renderer("ffmpeg", "f" * 64)
    remotion = _Renderer("remotion", "d" * 64)
    backend = ConditionalUiRenderBackend(
        fallback_renderer=fallback,
        remotion_renderer=remotion,
        capabilities={
            "remotion_react_ui": {
                "status": "enabled",
                "domain": "programmable_overlays",
                "activation_report_sha256": "a" * 64,
                **remotion.capability_identity(),
            }
        },
    )
    context = _eligible_context()
    context.timeline_regions[0]["region_type"] = "generated_ui"

    result = backend(
        Path("ui.png"),
        Path("ui.mp4"),
        context,
        truth={"states": [{"state_id": "home"}]},
        render_contract={"route": "generated_ui_demo", "state_sequence": ["home"]},
        target_ui_evidence_sha256="e" * 64,
    )

    assert fallback.calls == ["ffmpeg"]
    assert remotion.calls == []
    assert result["ui_renderer_decision"]["reason"] == "generated_ui_interval_not_unique"
