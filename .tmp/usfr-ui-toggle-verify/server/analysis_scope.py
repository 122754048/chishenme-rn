"""Deterministic, zero-provider analysis routing for one USFR run.

The fixed input manifest already declares the role of every uploaded asset.
This module turns that declared intent into the smallest safe analysis scope
*before* any VLM, ASR, OCR, App Store, storyboard, or provider operation can
start.  It never guesses source content: a later source-region uncertainty
must escalate to the relevant evidence rather than silently skipping it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .errors import ReplicationError


ANALYSIS_SCOPE_CONTRACT = "usfr-analysis-scope/v1"


def _present(slots: Mapping[str, Any], name: str) -> bool:
    value = slots.get(name)
    if isinstance(value, Mapping):
        return value.get("present") is True
    return bool(value)


def _decision(status: str, reason: str) -> dict[str, str]:
    return {"status": status, "reason": reason}


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_analysis_scope(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable analysis/tool scope declared by a fixed manifest.

    The result is intentionally conservative: ``deferred`` means the tool is
    not started now, but Stage 4 must promote it to ``required`` if its actual
    source region consumes the capability.  Only ``skipped`` is a hard
    no-call decision, and it is used solely for a route that cannot consume
    that tool's output.
    """

    if not isinstance(manifest, Mapping):
        raise ValueError("analysis scope requires a fixed input manifest")
    slots = manifest.get("slots")
    slots = dict(slots) if isinstance(slots, Mapping) else {}
    routes = manifest.get("routes")
    routes = dict(routes) if isinstance(routes, Mapping) else {}
    extensions = manifest.get("extensions")
    extensions = dict(extensions) if isinstance(extensions, Mapping) else {}
    admission = manifest.get("admission")
    admission = dict(admission) if isinstance(admission, Mapping) else {}
    output_language = str(manifest.get("output_language") or "").strip()

    language_only = bool(admission.get("language_only"))
    has_product = _present(slots, "new_product_image") or routes.get("product") == "replace_from_slot"
    has_model = _present(slots, "new_model_image") or routes.get("character") == "replace_from_slot"
    explicit_ui_target = _present(slots, "ui_screenshot") or _present(slots, "app_store_url")
    auto_ui_rebuild = extensions.get("ui_rebuild_enabled") is True
    generated_ui = routes.get("ui") == "generated_ui_demo" and (
        explicit_ui_target or auto_ui_rebuild
    )
    opaque_ui = _present(slots, "ui_operation_video") or routes.get("ui") == "opaque_ui_demo"
    opaque_tail = _present(slots, "tail_video") or routes.get("tail") == "opaque_app_tail_card"
    background_music = isinstance(extensions.get("background_music"), Mapping)
    ui_rebuild_candidate = not opaque_ui and generated_ui

    visual_replacement = has_product or has_model or generated_ui
    technical_splice = not language_only and not visual_replacement and not background_music and (opaque_ui or opaque_tail)

    if language_only:
        route_family = "language_only"
        semantic_pass = {
            "status": "skipped",
            "reason": "language_only_uses_timestamped_audio_localization",
            "focus": [],
        }
    elif technical_splice:
        route_family = "technical_splice"
        semantic_pass = {
            "status": "skipped",
            "reason": "opaque_media_has_no_semantic_rewrite",
            "focus": [],
        }
    else:
        route_family = "composite" if sum((has_product, has_model, generated_ui, background_music)) > 1 else "targeted_replication"
        focus = ["source_timeline"]
        if has_model:
            focus.append("character_identity")
        if has_product:
            focus.append("product_truth")
        if generated_ui:
            focus.append("ui_interval")
        if has_model or has_product:
            focus.extend(("camera", "action", "continuity"))
        elif generated_ui:
            focus.extend(("camera", "transition"))
        if background_music:
            focus.extend(item for item in ("performance", "audio_window") if item not in focus)
        semantic_pass = {"status": "required", "focus": focus}

    if language_only:
        source_asr = _decision("required", "localized_audio_contract_requires_timestamped_source_speech")
    elif background_music:
        source_asr = _decision("deferred", "only_if_generated_region_intersects_speech_or_visible_singing")
    elif has_product:
        source_asr = _decision("required", "replacement_script_requires_source_speech_evidence")
    elif visual_replacement:
        source_asr = _decision("deferred", "only_if_selected_generated_region_contains_audible_dialogue")
    else:
        source_asr = _decision("skipped", "no_audio_rewrite_or_generated_speech_route")

    if ui_rebuild_candidate:
        app_store = (
            _decision("deferred", "await_generated_ui_region")
            if _present(slots, "app_store_url")
            else _decision("skipped", "no_app_store_url")
        )
        target_ui_ocr = _decision("deferred", "await_generated_ui_region")
        ui_rebuild = _decision(
            "deferred",
            "await_generated_ui_region"
            if generated_ui
            else "await_source_ui_cut_for_product_or_model_rebuild",
        )
    else:
        app_store = _decision("skipped", "no_generated_ui_route")
        target_ui_ocr = _decision("skipped", "no_generated_ui_route")
        ui_rebuild = _decision("skipped", "no_generated_ui_route")

    seedance_needed = visual_replacement or background_music
    # Pre-routing may defer paid work, but it must never erase the two existing
    # editable review gates from a generated-media route.  The scope is shown
    # before Stage 4 and therefore tells the caller that reverse-script review
    # and storyboard review remain mandatory once generated regions are frozen.
    # `deferred` below applies only to tools; it is not permission to bypass a
    # user approval gate.
    user_review = {
        "script": {
            "status": "required",
            "user_editable": True,
            "reason": "every_admitted_run_requires_confirmed_editable_script",
        },
        "storyboard": {
            "status": "required",
            "user_editable": True,
            "reason": "every_admitted_run_requires_confirmed_storyboard",
        },
    }
    tools = {
        "source_probe": _decision("required", "verified_duration_fps_and_canvas_are_always_required"),
        "structural_timeline": _decision("required", "source_intervals_and_transition_boundaries_are_always_required"),
        "semantic_vlm": _decision(semantic_pass["status"], semantic_pass.get("reason", "targeted_factors_only")),
        "source_asr": source_asr,
        "source_ocr": _decision(
            "deferred" if ui_rebuild_candidate else "skipped",
            "only_if_route_regions_declares_generated_ui_demo"
            if ui_rebuild_candidate
            else "source_ui_is_not_a_replacement_target",
        ),
        "app_store_evidence": app_store,
        "target_ui_ocr": target_ui_ocr,
        "ui_rebuild": ui_rebuild,
        "uploaded_music_alignment": _decision(
            "required" if background_music else "skipped",
            "audio1_window_and_singing_contract" if background_music else "no_uploaded_music",
        ),
        "storyboard": _decision(
            "required" if language_only or technical_splice or not seedance_needed else "deferred",
            "source_or_opaque_review_board" if language_only or technical_splice or not seedance_needed else "await_generated_regions",
        ),
        "seedance_video": _decision(
            "skipped" if language_only or technical_splice else ("deferred" if seedance_needed else "skipped"),
            "language_only_cloud_lip_sync" if language_only else "await_audited_generated_regions" if seedance_needed else "no_generated_regions",
        ),
    }
    scope: dict[str, Any] = {
        "contract": ANALYSIS_SCOPE_CONTRACT,
        "route_family": route_family,
        "semantic_pass": semantic_pass,
        "tools": tools,
        "user_review": user_review,
        "escalation_policy": {
            "unknown_or_conflicting_source_region": "require_minimum_relevant_evidence_before_route",
            "deferred_tool": "start_only_when_stage4_proves_the_region_consumes_it",
            "quality_rule": "never_skip_selected_route_evidence_or_final_qc",
        },
    }
    scope["scope_sha256"] = hashlib.sha256(_canonical(scope)).hexdigest()
    return scope


def promote_deferred_tool(
    *,
    scope: Mapping[str, Any],
    tool_name: str,
    region_ids: tuple[str, ...] | list[str],
    reason: str,
) -> dict[str, Any]:
    """Bind a deferred tool to the exact routed regions that consume it."""

    decision = (scope.get("tools") or {}).get(tool_name)
    if not isinstance(decision, Mapping) or decision.get("status") != "deferred":
        raise ReplicationError(
            "CONTRACT_INVALID",
            "only a deferred tool can receive a promotion receipt",
            category="analysis",
            http_status=422,
        )
    normalized_regions = tuple(str(item).strip() for item in region_ids if str(item).strip())
    if not normalized_regions:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "tool promotion requires a region",
            category="analysis",
            http_status=422,
        )
    normalized_reason = str(reason).strip()
    if not normalized_reason:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "tool promotion requires a reason",
            category="analysis",
            http_status=422,
        )
    receipt: dict[str, Any] = {
        "contract": "usfr-tool-promotion/v1",
        "scope_sha256": str(scope.get("scope_sha256") or ""),
        "tool": tool_name,
        "region_ids": list(normalized_regions),
        "reason": normalized_reason,
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def validate_tool_call(
    scope: Mapping[str, Any],
    tool_name: str,
    stage: str,
    *,
    promotion_receipt: Mapping[str, Any] | None = None,
) -> None:
    """Fail closed when a stage tries to call a tool outside its frozen scope."""

    decision = (scope.get("tools") or {}).get(tool_name)
    if not isinstance(decision, Mapping):
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"tool is absent from execution scope: {tool_name}",
            category="analysis",
            http_status=422,
            details={"stage": stage, "tool": tool_name},
        )
    status = decision.get("status")
    if status == "skipped":
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"tool is outside execution scope: {tool_name}",
            category="analysis",
            http_status=422,
            details={"stage": stage, "tool": tool_name},
        )
    if status == "required":
        return
    if status != "deferred":
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"tool has an invalid execution-scope status: {tool_name}",
            category="analysis",
            http_status=422,
        )
    if not isinstance(promotion_receipt, Mapping):
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"deferred tool requires a promotion receipt: {tool_name}",
            category="analysis",
            http_status=422,
            details={"stage": stage, "tool": tool_name},
        )
    if promotion_receipt.get("scope_sha256") != scope.get("scope_sha256"):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "promotion receipt scope mismatch",
            category="analysis",
            http_status=422,
        )
    if promotion_receipt.get("tool") != tool_name:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "promotion receipt tool mismatch",
            category="analysis",
            http_status=422,
        )
    if promotion_receipt.get("contract") != "usfr-tool-promotion/v1":
        raise ReplicationError(
            "CONTRACT_INVALID",
            "promotion receipt contract is invalid",
            category="analysis",
            http_status=422,
        )
    receipt_body = dict(promotion_receipt)
    receipt_sha256 = receipt_body.pop("receipt_sha256", None)
    if receipt_sha256 != hashlib.sha256(_canonical(receipt_body)).hexdigest():
        raise ReplicationError(
            "CONTRACT_INVALID",
            "promotion receipt digest mismatch",
            category="analysis",
            http_status=422,
        )
    regions = promotion_receipt.get("region_ids")
    if not isinstance(regions, list) or not regions or any(not isinstance(item, str) or not item for item in regions):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "promotion receipt has no routed regions",
            category="analysis",
            http_status=422,
        )


def apply_tool_promotions(
    scope: Mapping[str, Any],
    promotion_receipts: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Freeze the Stage-4 execution scope without rerunning route reasoning."""

    if scope.get("contract") != ANALYSIS_SCOPE_CONTRACT:
        raise ReplicationError("CONTRACT_INVALID", "pre-route analysis scope contract is invalid")
    final_scope = json.loads(json.dumps(scope, ensure_ascii=False, sort_keys=True))
    pre_route_sha256 = str(final_scope.pop("scope_sha256", ""))
    normalized_receipts: list[dict[str, Any]] = []
    seen_tools: set[str] = set()
    for raw_receipt in promotion_receipts:
        if not isinstance(raw_receipt, Mapping):
            raise ReplicationError("CONTRACT_INVALID", "tool promotion receipt is invalid")
        receipt = dict(raw_receipt)
        tool_name = str(receipt.get("tool") or "").strip()
        if not tool_name or tool_name in seen_tools:
            raise ReplicationError("CONTRACT_INVALID", "tool promotion set contains a duplicate tool")
        validate_tool_call(scope, tool_name, "route_regions", promotion_receipt=receipt)
        decision = final_scope["tools"][tool_name]
        decision.update(
            {
                "status": "required",
                "promoted_from": "deferred",
                "promotion_receipt": receipt,
                "reason": str(receipt.get("reason") or decision.get("reason") or "routed_region_requires_tool"),
            }
        )
        normalized_receipts.append(receipt)
        seen_tools.add(tool_name)
    final_scope["contract"] = "usfr-execution-scope/v1"
    final_scope["pre_route_scope_sha256"] = pre_route_sha256
    final_scope["promotion_receipts"] = normalized_receipts
    final_scope["scope_sha256"] = hashlib.sha256(_canonical(final_scope)).hexdigest()
    return final_scope


def validate_execution_scope(
    value: Mapping[str, Any],
    *,
    pre_route_scope: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("contract") != "usfr-execution-scope/v1":
        raise ReplicationError("CONTRACT_INVALID", "execution scope contract is invalid")
    body = dict(value)
    claimed = str(body.pop("scope_sha256", ""))
    if claimed != hashlib.sha256(_canonical(body)).hexdigest():
        raise ReplicationError("CONTRACT_INVALID", "execution scope digest mismatch")
    if value.get("pre_route_scope_sha256") != pre_route_scope.get("scope_sha256"):
        raise ReplicationError("CONTRACT_INVALID", "execution scope pre-route digest mismatch")
    receipts = value.get("promotion_receipts")
    if not isinstance(receipts, list):
        raise ReplicationError("CONTRACT_INVALID", "execution scope promotion receipts are invalid")
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise ReplicationError("CONTRACT_INVALID", "execution scope promotion receipt is invalid")
        validate_tool_call(
            pre_route_scope,
            str(receipt.get("tool") or ""),
            "route_regions",
            promotion_receipt=receipt,
        )
    return dict(value)


__all__ = [
    "ANALYSIS_SCOPE_CONTRACT",
    "apply_tool_promotions",
    "build_analysis_scope",
    "promote_deferred_tool",
    "validate_execution_scope",
    "validate_tool_call",
]
