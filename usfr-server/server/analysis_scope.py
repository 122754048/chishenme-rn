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

    language_only = bool(admission.get("language_only"))
    has_product = _present(slots, "new_product_image") or routes.get("product") == "replace_from_slot"
    has_model = _present(slots, "new_model_image") or routes.get("character") == "replace_from_slot"
    generated_ui = (
        _present(slots, "ui_screenshot")
        or _present(slots, "app_store_url")
        or routes.get("ui") == "generated_ui_demo"
    )
    opaque_ui = _present(slots, "ui_operation_video") or routes.get("ui") == "opaque_ui_demo"
    opaque_tail = _present(slots, "tail_video") or routes.get("tail") == "opaque_app_tail_card"
    background_music = isinstance(extensions.get("background_music"), Mapping)

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

    if generated_ui:
        app_store = (
            _decision("deferred", "await_generated_ui_region")
            if _present(slots, "app_store_url")
            else _decision("skipped", "no_app_store_url")
        )
        target_ui_ocr = _decision("deferred", "await_generated_ui_region")
        ui_rebuild = _decision("deferred", "await_generated_ui_region")
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
            },
            "storyboard": {
                "status": "required",
                "user_editable": True,
                "reason": "generated_regions_require_confirmed_storyboards_before_provider_submission",
            },
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
    tools = {
        "source_probe": _decision("required", "verified_duration_fps_and_canvas_are_always_required"),
        "structural_timeline": _decision("required", "source_intervals_and_transition_boundaries_are_always_required"),
        "semantic_vlm": _decision(semantic_pass["status"], semantic_pass.get("reason", "targeted_factors_only")),
        "source_asr": source_asr,
        "source_ocr": _decision(
            "deferred" if generated_ui else "skipped",
            "only_if_stage4_declares_a_semantic_overlay" if generated_ui else "source_ui_is_not_a_replacement_target",
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
        "escalation_policy": {
            "unknown_or_conflicting_source_region": "require_minimum_relevant_evidence_before_route",
            "deferred_tool": "start_only_when_stage4_proves_the_region_consumes_it",
            "quality_rule": "never_skip_selected_route_evidence_or_final_qc",
        },
    }
    scope["scope_sha256"] = hashlib.sha256(_canonical(scope)).hexdigest()
    return scope


__all__ = ["ANALYSIS_SCOPE_CONTRACT", "build_analysis_scope"]
