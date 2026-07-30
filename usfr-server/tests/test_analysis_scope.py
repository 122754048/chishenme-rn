from __future__ import annotations

import pytest

from server.analysis_scope import (
    build_analysis_scope,
    build_execution_scope,
    promote_deferred_tool,
    validate_tool_call,
)
from server.errors import ReplicationError
from server.orchestrator import build_stage_plan


def _manifest(*, slots=None, routes=None, admission=None, extensions=None, output_language=None):
    value = {
        "slots": {
            "source_video": {"present": True},
            "new_product_image": {"present": False},
            "new_model_image": {"present": False},
            "ui_screenshot": {"present": False},
            "app_store_url": {"present": False},
            "ui_operation_video": {"present": False},
            "tail_video": {"present": False},
            **(slots or {}),
        },
        "routes": {
            "product": "source_preserve",
            "character": "source_preserve",
            "ui": "source_ui_keep",
            "tail": "omit_source_end_card",
            **(routes or {}),
        },
        "admission": dict(admission or {}),
    }
    if extensions is not None:
        value["extensions"] = extensions
    if output_language is not None:
        value["output_language"] = output_language
    return value


def test_model_replacement_keeps_source_ui_when_auto_ui_rebuild_is_disabled() -> None:
    manifest = _manifest(
        slots={"new_model_image": {"present": True}},
        routes={"character": "replace_from_slot"},
    )

    scope = build_analysis_scope(manifest)

    assert scope["semantic_pass"]["status"] == "required"
    assert scope["semantic_pass"]["focus"] == [
        "source_timeline",
        "character_identity",
        "camera",
        "action",
        "continuity",
    ]
    assert scope["tools"]["source_ocr"]["status"] == "skipped"
    assert scope["tools"]["app_store_evidence"]["status"] == "skipped"
    assert scope["tools"]["ui_rebuild"] == {
        "status": "skipped",
        "reason": "no_generated_ui_route",
    }


def test_explicit_ui_target_evidence_stays_enabled_even_when_auto_switch_is_false() -> None:
    manifest = _manifest(
        slots={"ui_screenshot": {"present": True}},
        routes={"ui": "generated_ui_demo"},
        extensions={"ui_rebuild_enabled": False},
    )

    scope = build_analysis_scope(manifest)

    assert scope["tools"]["app_store_evidence"]["status"] == "skipped"
    assert scope["tools"]["target_ui_ocr"]["status"] == "deferred"
    assert scope["tools"]["ui_rebuild"]["status"] == "deferred"


def test_language_only_routes_audio_only_and_does_not_request_seedance_or_storyboard() -> None:
    manifest = _manifest(
        admission={"language_only": True},
        output_language="ja",
    )

    scope = build_analysis_scope(manifest)
    plan = build_stage_plan(manifest)

    assert scope["route_family"] == "language_only"
    assert scope["semantic_pass"]["status"] == "skipped"
    assert scope["tools"]["source_asr"]["status"] == "required"
    assert scope["tools"]["storyboard"]["status"] == "skipped"
    assert scope["tools"]["seedance_video"]["status"] == "skipped"
    assert next(stage for stage in plan if stage["name"] == "analyze_dynamics")["analysis_scope"] == scope


def test_app_ui_is_deferred_until_region_route_proves_a_generated_ui_carrier() -> None:
    manifest = _manifest(
        slots={
            "ui_screenshot": {"present": True},
            "app_store_url": {"present": True},
        },
        routes={"ui": "generated_ui_demo"},
    )

    scope = build_analysis_scope(manifest)

    assert scope["semantic_pass"]["focus"] == [
        "source_timeline",
        "ui_interval",
        "camera",
        "transition",
    ]
    assert scope["tools"]["app_store_evidence"] == {
        "status": "deferred",
        "reason": "await_generated_ui_region",
    }
    assert scope["tools"]["target_ui_ocr"] == {
        "status": "deferred",
        "reason": "await_generated_ui_region",
    }


def test_opaque_ui_and_tail_use_technical_routing_without_ocr_or_semantic_rewrite() -> None:
    manifest = _manifest(
        slots={
            "ui_operation_video": {"present": True},
            "tail_video": {"present": True},
        },
        routes={
            "ui": "opaque_ui_demo",
            "tail": "opaque_app_tail_card",
        },
    )

    scope = build_analysis_scope(manifest)

    assert scope["route_family"] == "technical_splice"
    assert scope["semantic_pass"] == {
        "status": "skipped",
        "reason": "opaque_media_has_no_semantic_rewrite",
        "focus": [],
    }
    assert scope["tools"]["source_ocr"]["status"] == "skipped"
    assert scope["tools"]["source_asr"]["status"] == "skipped"
    assert scope["tools"]["seedance_video"]["status"] == "skipped"


def test_uploaded_music_requires_its_own_alignment_but_defers_source_asr_until_a_lip_sync_region_needs_it() -> None:
    manifest = _manifest(
        extensions={"background_music": {"extension_id": "input_contract_v2.background_music"}},
    )

    scope = build_analysis_scope(manifest)

    assert scope["tools"]["uploaded_music_alignment"]["status"] == "required"
    assert scope["tools"]["source_asr"] == {
        "status": "deferred",
        "reason": "only_if_generated_region_intersects_speech_or_visible_singing",
    }
    assert scope["tools"]["app_store_evidence"]["status"] == "skipped"


def test_generated_composite_route_declares_the_two_editable_user_approval_gates() -> None:
    manifest = _manifest(
        slots={"new_model_image": {"present": True}},
        routes={"character": "replace_from_slot"},
        extensions={"background_music": {"extension_id": "input_contract_v2.background_music"}},
    )

    scope = build_analysis_scope(manifest)
    plan = build_stage_plan(manifest)

    assert scope["user_review"] == {
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
    assert [stage["name"] for stage in plan if stage["kind"] == "approval"] == [
        "await_script_approval",
        "await_storyboard_approval",
    ]


def test_generated_route_exposes_only_a_markdown_file_then_png_storyboard_images() -> None:
    manifest = _manifest(
        slots={"new_model_image": {"present": True}},
        routes={"character": "replace_from_slot"},
    )

    scope = build_analysis_scope(manifest)
    plan = build_stage_plan(manifest)

    assert scope["user_interaction"] == {
        "approval_gate_count": 2,
        "approval_sequence": ["script_document", "director_storyboard_images"],
        "intermediate_confirmation": "forbidden",
        "progress_updates": "non_blocking_no_reply_required",
    }
    approvals = [stage for stage in plan if stage["kind"] == "approval"]
    assert [stage["user_artifact"] for stage in approvals] == [
        scope["user_review"]["script"]["artifact"],
        scope["user_review"]["storyboard"]["artifact"],
    ]


def test_skipped_tool_cannot_be_called() -> None:
    scope = build_analysis_scope(
        _manifest(slots={"new_model_image": {"present": True}}, routes={"character": "replace_from_slot"})
    )

    with pytest.raises(ReplicationError, match="tool is outside execution scope"):
        validate_tool_call(scope, "ui_rebuild", "resolve_ui_evidence")


def test_deferred_tool_requires_a_stage4_promotion_receipt() -> None:
    scope = build_analysis_scope(
        _manifest(
            slots={"ui_screenshot": {"present": True}},
            routes={"ui": "generated_ui_demo"},
        )
    )

    with pytest.raises(ReplicationError, match="promotion receipt"):
        validate_tool_call(scope, "ui_rebuild", "resolve_ui_evidence")


def test_stage4_promotion_freezes_one_final_execution_scope() -> None:
    analysis_scope = build_analysis_scope(
        _manifest(
            slots={"ui_screenshot": {"present": True}},
            routes={"ui": "generated_ui_demo"},
        )
    )
    receipt = promote_deferred_tool(
        scope=analysis_scope,
        tool_name="ui_rebuild",
        region_ids=["R01"],
        reason="generated UI interval confirmed",
    )

    execution_scope = build_execution_scope(
        analysis_scope,
        promotion_receipts=[receipt],
        finalized=True,
    )

    assert execution_scope["tools"]["ui_rebuild"]["status"] == "required"
    assert execution_scope["tools"]["target_ui_ocr"]["status"] == "skipped"
    validate_tool_call(execution_scope, "ui_rebuild", "resolve_ui_evidence")
