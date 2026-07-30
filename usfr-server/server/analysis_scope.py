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
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ReplicationError


ANALYSIS_SCOPE_CONTRACT = "usfr-analysis-scope/v1"
EXECUTION_SCOPE_CONTRACT = "usfr-execution-scope/v1"
TOOL_PROMOTION_CONTRACT = "usfr-tool-promotion/v1"


def _present(slots: Mapping[str, Any], name: str) -> bool:
    value = slots.get(name)
    if isinstance(value, Mapping):
        return value.get("present") is True
    return bool(value)


def _decision(status: str, reason: str) -> dict[str, str]:
    return {"status": status, "reason": reason}


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _without_digest(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {str(key): item for key, item in value.items() if key != field}


def _validate_scope_digest(scope: Mapping[str, Any]) -> None:
    declared = str(scope.get("scope_sha256") or "").lower()
    if len(declared) != 64 or declared != _digest(_without_digest(scope, "scope_sha256")):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "execution scope digest does not match its immutable contents",
            category="contract",
            http_status=422,
        )


def promote_deferred_tool(
    *,
    scope: Mapping[str, Any],
    tool_name: str,
    region_ids: Sequence[str],
    reason: str,
) -> dict[str, Any]:
    """Return the sole Stage-4 authority for starting one deferred tool."""

    if scope.get("contract") != ANALYSIS_SCOPE_CONTRACT:
        raise ReplicationError("CONTRACT_INVALID", "tool promotion requires the analysis scope")
    _validate_scope_digest(scope)
    tools = scope.get("tools")
    decision = tools.get(tool_name) if isinstance(tools, Mapping) else None
    if not isinstance(decision, Mapping) or decision.get("status") != "deferred":
        raise ReplicationError("CONTRACT_INVALID", "only a deferred tool can be promoted")
    normalized_regions = list(dict.fromkeys(str(item).strip() for item in region_ids if str(item).strip()))
    normalized_reason = str(reason or "").strip()
    if not normalized_regions:
        raise ReplicationError("CONTRACT_INVALID", "tool promotion requires a region")
    if not normalized_reason:
        raise ReplicationError("CONTRACT_INVALID", "tool promotion requires a reason")
    receipt: dict[str, Any] = {
        "contract": TOOL_PROMOTION_CONTRACT,
        "analysis_scope_sha256": str(scope["scope_sha256"]),
        "stage": "route_regions",
        "tool": str(tool_name),
        "region_ids": normalized_regions,
        "reason": normalized_reason,
    }
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


def _validate_promotion_receipt(
    receipt: Mapping[str, Any],
    *,
    analysis_scope_sha256: str,
    tool_name: str,
) -> None:
    if receipt.get("contract") != TOOL_PROMOTION_CONTRACT:
        raise ReplicationError("CONTRACT_INVALID", "deferred tool requires a valid promotion receipt")
    if receipt.get("analysis_scope_sha256") != analysis_scope_sha256:
        raise ReplicationError("CONTRACT_INVALID", "promotion receipt scope mismatch")
    if receipt.get("tool") != tool_name or receipt.get("stage") != "route_regions":
        raise ReplicationError("CONTRACT_INVALID", "promotion receipt tool or stage mismatch")
    region_ids = receipt.get("region_ids")
    if not isinstance(region_ids, Sequence) or isinstance(region_ids, (str, bytes, bytearray)) or not region_ids:
        raise ReplicationError("CONTRACT_INVALID", "promotion receipt requires routed regions")
    declared = str(receipt.get("receipt_sha256") or "").lower()
    if len(declared) != 64 or declared != _digest(_without_digest(receipt, "receipt_sha256")):
        raise ReplicationError("CONTRACT_INVALID", "promotion receipt digest mismatch")


def build_execution_scope(
    analysis_scope: Mapping[str, Any],
    *,
    promotion_receipts: Sequence[Mapping[str, Any]] = (),
    finalized: bool = False,
) -> dict[str, Any]:
    """Freeze the tool contract consumed by every downstream stage.

    Before Stage 4, deferred tools remain blocked. After Stage 4, every
    deferred tool is deterministically promoted to required or closed as
    skipped, so no later stage can decide to broaden the route by itself.
    """

    if analysis_scope.get("contract") != ANALYSIS_SCOPE_CONTRACT:
        raise ReplicationError("CONTRACT_INVALID", "execution scope requires the analysis scope")
    _validate_scope_digest(analysis_scope)
    receipts: dict[str, dict[str, Any]] = {}
    for raw in promotion_receipts:
        if not isinstance(raw, Mapping):
            raise ReplicationError("CONTRACT_INVALID", "tool promotion receipt must be an object")
        tool_name = str(raw.get("tool") or "")
        _validate_promotion_receipt(
            raw,
            analysis_scope_sha256=str(analysis_scope["scope_sha256"]),
            tool_name=tool_name,
        )
        if tool_name in receipts:
            raise ReplicationError("CONTRACT_INVALID", "a deferred tool may be promoted only once")
        receipts[tool_name] = dict(raw)

    source_tools = analysis_scope.get("tools")
    if not isinstance(source_tools, Mapping):
        raise ReplicationError("CONTRACT_INVALID", "analysis scope tools are missing")
    tools: dict[str, dict[str, Any]] = {}
    for name, raw_decision in source_tools.items():
        if not isinstance(raw_decision, Mapping):
            raise ReplicationError("CONTRACT_INVALID", "analysis scope tool decision is invalid")
        decision = dict(raw_decision)
        original_status = str(decision.get("status") or "")
        if original_status == "deferred" and str(name) in receipts:
            decision = {
                "status": "required",
                "reason": str(receipts[str(name)]["reason"]),
                "origin_status": "deferred",
                "promotion_receipt_sha256": str(receipts[str(name)]["receipt_sha256"]),
                "region_ids": list(receipts[str(name)]["region_ids"]),
            }
        elif original_status == "deferred" and finalized:
            decision = {
                "status": "skipped",
                "reason": f"stage4_not_promoted:{decision.get('reason') or 'not_required'}",
                "origin_status": "deferred",
            }
        tools[str(name)] = decision

    execution_scope: dict[str, Any] = {
        "contract": EXECUTION_SCOPE_CONTRACT,
        "analysis_scope_sha256": str(analysis_scope["scope_sha256"]),
        "route_family": analysis_scope.get("route_family"),
        "semantic_pass": analysis_scope.get("semantic_pass"),
        "tools": tools,
        "user_review": analysis_scope.get("user_review"),
        "user_interaction": analysis_scope.get("user_interaction"),
        "promotion_receipts": [receipts[name] for name in sorted(receipts)],
        "finalized": bool(finalized),
    }
    execution_scope["scope_sha256"] = _digest(execution_scope)
    return execution_scope


def validate_tool_call(
    scope: Mapping[str, Any],
    tool_name: str,
    stage: str,
    *,
    promotion_receipt: Mapping[str, Any] | None = None,
) -> None:
    """Fail closed before an expensive or paid tool is invoked."""

    if not isinstance(scope, Mapping):
        raise ReplicationError("CONTRACT_INVALID", "tool call requires an execution scope")
    if scope.get("contract") not in {ANALYSIS_SCOPE_CONTRACT, EXECUTION_SCOPE_CONTRACT}:
        raise ReplicationError("CONTRACT_INVALID", "tool call scope contract is invalid")
    _validate_scope_digest(scope)
    tools = scope.get("tools")
    decision = tools.get(tool_name) if isinstance(tools, Mapping) else None
    if not isinstance(decision, Mapping):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "tool is absent from execution scope",
            details={"tool": tool_name, "stage": stage},
        )
    status = decision.get("status")
    if status == "skipped":
        raise ReplicationError(
            "CONTRACT_INVALID",
            "tool is outside execution scope",
            details={"tool": tool_name, "stage": stage, "reason": decision.get("reason")},
        )
    if status == "deferred":
        if not isinstance(promotion_receipt, Mapping):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "deferred tool requires a promotion receipt",
                details={"tool": tool_name, "stage": stage},
            )
        analysis_scope_sha256 = (
            str(scope.get("analysis_scope_sha256") or "")
            if scope.get("contract") == EXECUTION_SCOPE_CONTRACT
            else str(scope.get("scope_sha256") or "")
        )
        _validate_promotion_receipt(
            promotion_receipt,
            analysis_scope_sha256=analysis_scope_sha256,
            tool_name=tool_name,
        )
    elif status != "required":
        raise ReplicationError("CONTRACT_INVALID", "tool execution status is invalid")


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
    # Explicit UI evidence remains active regardless of the automatic rebuild
    # switch. A source UI interval may be rebuilt without explicit target UI
    # evidence only when the caller opts in. The default is fail-closed so a
    # product/model/language change cannot silently redraw unrelated UI.
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
    if seedance_needed and not language_only and not technical_splice:
        user_review = {
            "script": {
                "status": "required",
                "user_editable": True,
                "reason": "generated_regions_require_a_confirmed_reverse_script",
                "artifact": {
                    "kind": "user_script_markdown",
                    "content_type": "text/markdown; charset=utf-8",
                    "presentation": "file",
                    "logical_name": "analysis/reverse_storyboard_script.md",
                    "inline_chat_substitute_forbidden": True,
                },
            },
            "storyboard": {
                "status": "required",
                "user_editable": True,
                "reason": "generated_regions_require_confirmed_storyboards_before_provider_submission",
                "artifact": {
                    "kind": "storyboard_image",
                    "content_type": "image/png",
                    "presentation": "image_set",
                    "logical_name_pattern": "storyboards/segment_XX_vN.png",
                    "approval_scope": "all_segments_together",
                    "text_only_substitute_forbidden": True,
                },
            },
        }
        user_interaction = {
            "approval_gate_count": 2,
            "approval_sequence": ["script_document", "director_storyboard_images"],
            "intermediate_confirmation": "forbidden",
            "progress_updates": "non_blocking_no_reply_required",
        }
    else:
        review_reason = (
            "language_only_cloud_lip_sync"
            if language_only
            else "technical_splice_has_no_semantic_generation"
            if technical_splice
            else "no_generated_regions"
        )
        user_review = {
            "script": {"status": "skipped", "user_editable": False, "reason": review_reason},
            "storyboard": {"status": "skipped", "user_editable": False, "reason": review_reason},
        }
        user_interaction = {
            "approval_gate_count": 0,
            "approval_sequence": [],
            "intermediate_confirmation": "forbidden",
            "progress_updates": "non_blocking_no_reply_required",
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
            "skipped" if language_only or technical_splice else ("deferred" if seedance_needed else "skipped"),
            "language_only_cloud_lip_sync" if language_only else "await_generated_regions" if seedance_needed else "no_generated_regions",
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
        "user_interaction": user_interaction,
        "escalation_policy": {
            "unknown_or_conflicting_source_region": "require_minimum_relevant_evidence_before_route",
            "deferred_tool": "start_only_when_stage4_proves_the_region_consumes_it",
            "quality_rule": "never_skip_selected_route_evidence_or_final_qc",
        },
    }
    scope["scope_sha256"] = _digest(scope)
    return scope


__all__ = [
    "ANALYSIS_SCOPE_CONTRACT",
    "EXECUTION_SCOPE_CONTRACT",
    "TOOL_PROMOTION_CONTRACT",
    "build_analysis_scope",
    "build_execution_scope",
    "promote_deferred_tool",
    "validate_tool_call",
]
