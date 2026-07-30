"""Frozen, frame-locked source UI interaction contracts.

The contract intentionally captures only a source UI interval's immutable
timing and deterministic render policy.  Motion extraction and rendering stay
behind the existing UI renderer boundary, so ordinary video regions do not
gain analysis or provider work.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


class UiInteractionContractError(ValueError):
    """Raised when a routed UI interval cannot safely enter reconstruction."""


_UI_REGION_TYPES = frozenset({"generated_ui_demo", "generated_ui"})
_SUPPORTED_ACTIONS = ("drag", "scroll", "bounce", "scale", "rotate", "opacity", "tap")


def _frame_at(time_us: int, *, fps_num: int, fps_den: int) -> int:
    return (time_us * fps_num) // (1_000_000 * fps_den)


def _frame_end_exclusive(time_us: int, *, fps_num: int, fps_den: int) -> int:
    return (time_us * fps_num + (1_000_000 * fps_den) - 1) // (1_000_000 * fps_den)


def _language(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UiInteractionContractError(f"{label} must be a non-empty language tag")
    return value.strip()


def _ui_roi(region: Mapping[str, Any], *, viewport_width: int, viewport_height: int) -> dict[str, Any]:
    raw = region.get("ui_roi")
    if raw is None:
        x, y, width, height = 0, 0, viewport_width, viewport_height
    elif isinstance(raw, Mapping):
        try:
            x = int(raw["x"])
            y = int(raw["y"])
            width = int(raw["width"])
            height = int(raw["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UiInteractionContractError("UI ROI is invalid") from exc
    elif isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            x, y, width, height = (int(value) for value in raw)
        except (TypeError, ValueError) as exc:
            raise UiInteractionContractError("UI ROI is invalid") from exc
    else:
        raise UiInteractionContractError("UI ROI is invalid")
    if (
        x < 0
        or y < 0
        or width <= 0
        or height <= 0
        or x + width > viewport_width
        or y + height > viewport_height
    ):
        raise UiInteractionContractError("UI ROI lies outside the display viewport")
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "coordinate_space": "display_pixels",
    }


def build_source_ui_interaction_contract(
    region: Mapping[str, Any],
    *,
    fps_num: int,
    fps_den: int,
    source_language: str,
    output_language: str | None,
) -> dict[str, Any]:
    """Return the immutable interaction facts for one deterministic UI lane.

    UI controls are rendered from source-frame-locked tracks.  This function
    does not inspect media: it prevents accidental full-video analysis by
    accepting only the already-routed UI interval and source timing metadata.
    """

    if not isinstance(region, Mapping):
        raise UiInteractionContractError("UI region must be an object")
    kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
    if kind not in _UI_REGION_TYPES:
        raise UiInteractionContractError("source UI interaction contract requires generated_ui_demo")
    region_id = str(region.get("region_id") or "").strip()
    if not region_id:
        raise UiInteractionContractError("UI region requires region_id")
    try:
        start_us = int(region["source_start_us"])
        end_us = int(region["source_end_us"])
        width, height = (int(value) for value in region["display_viewport"])
        fps_num = int(fps_num)
        fps_den = int(fps_den)
    except (KeyError, TypeError, ValueError) as exc:
        raise UiInteractionContractError("UI region timing, viewport, and source FPS are required") from exc
    if start_us < 0 or end_us <= start_us or width <= 0 or height <= 0 or fps_num <= 0 or fps_den <= 0:
        raise UiInteractionContractError("UI region timing, viewport, or source FPS is invalid")

    source = _language(source_language, label="source_language")
    localized = output_language.strip() if isinstance(output_language, str) and output_language.strip() else None
    target = localized or source
    start_frame = _frame_at(start_us, fps_num=fps_num, fps_den=fps_den)
    end_frame = _frame_end_exclusive(end_us, fps_num=fps_num, fps_den=fps_den)
    if end_frame <= start_frame:
        raise UiInteractionContractError("UI interval has no source frames")

    return {
        "schema_version": "source-ui-interaction/v1",
        "region_id": region_id,
        "source_window_us": {"start": start_us, "end_exclusive": end_us},
        "frame_window": {"start": start_frame, "end_exclusive": end_frame},
        "source_fps": {"num": fps_num, "den": fps_den},
        "display_viewport": [width, height],
        "ui_roi": _ui_roi(region, viewport_width=width, viewport_height=height),
        "language": {
            "source": source,
            "target": target,
            "mode": "localized" if localized else "preserve_source",
        },
        "text_encoding": {"encoding": "utf-8", "replacement_glyphs_forbidden": True},
        "motion": {
            "capture_scope": "ui_roi_only",
            "track_policy": "source_frame_locked",
            "supported_actions": list(_SUPPORTED_ACTIONS),
        },
        "validation": {
            "mode": "basic_anchor_only",
            "automatic_retry": False,
            "anchor_frames": [start_frame, end_frame - 1],
        },
    }


def validate_source_ui_interaction_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a stored interaction contract before it reaches a renderer."""

    if not isinstance(value, Mapping):
        raise UiInteractionContractError("source UI interaction contract must be an object")
    normalized = json.loads(json.dumps(dict(value), ensure_ascii=False, sort_keys=True))
    if normalized.get("schema_version") != "source-ui-interaction/v1":
        raise UiInteractionContractError("source UI interaction contract schema is unsupported")
    if not isinstance(normalized.get("region_id"), str) or not normalized["region_id"].strip():
        raise UiInteractionContractError("source UI interaction contract requires region_id")
    try:
        start_us = int(normalized["source_window_us"]["start"])
        end_us = int(normalized["source_window_us"]["end_exclusive"])
        start_frame = int(normalized["frame_window"]["start"])
        end_frame = int(normalized["frame_window"]["end_exclusive"])
        width, height = (int(item) for item in normalized["display_viewport"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UiInteractionContractError("source UI interaction timing or viewport is invalid") from exc
    if start_us < 0 or end_us <= start_us or start_frame < 0 or end_frame <= start_frame or width <= 0 or height <= 0:
        raise UiInteractionContractError("source UI interaction window is invalid")
    source_fps = normalized.get("source_fps")
    if source_fps is not None:
        try:
            fps_num = int(source_fps["num"])
            fps_den = int(source_fps["den"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UiInteractionContractError("source UI interaction FPS is invalid") from exc
        if fps_num <= 0 or fps_den <= 0:
            raise UiInteractionContractError("source UI interaction FPS is invalid")
    roi = normalized.get("ui_roi")
    if roi is not None:
        if not isinstance(roi, Mapping) or roi.get("coordinate_space") != "display_pixels":
            raise UiInteractionContractError("source UI interaction ROI is invalid")
        try:
            roi_x = int(roi["x"])
            roi_y = int(roi["y"])
            roi_width = int(roi["width"])
            roi_height = int(roi["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UiInteractionContractError("source UI interaction ROI is invalid") from exc
        if (
            roi_x < 0
            or roi_y < 0
            or roi_width <= 0
            or roi_height <= 0
            or roi_x + roi_width > width
            or roi_y + roi_height > height
        ):
            raise UiInteractionContractError("source UI interaction ROI lies outside the display viewport")
    language = normalized.get("language")
    if not isinstance(language, Mapping):
        raise UiInteractionContractError("source UI interaction language is required")
    source_language = _language(language.get("source"), label="source language")
    target_language = _language(language.get("target"), label="target language")
    mode = language.get("mode")
    if mode not in {"preserve_source", "localized"} or (mode == "preserve_source" and source_language != target_language):
        raise UiInteractionContractError("source UI interaction language mode is invalid")
    encoding = normalized.get("text_encoding")
    if encoding != {"encoding": "utf-8", "replacement_glyphs_forbidden": True}:
        raise UiInteractionContractError("source UI interaction must require UTF-8 text without replacement glyphs")
    motion = normalized.get("motion")
    if not isinstance(motion, Mapping) or motion.get("capture_scope") != "ui_roi_only" or motion.get("track_policy") != "source_frame_locked":
        raise UiInteractionContractError("source UI interaction must use frame-locked UI-only motion capture")
    if list(motion.get("supported_actions") or []) != list(_SUPPORTED_ACTIONS):
        raise UiInteractionContractError("source UI interaction supported action set is invalid")
    validation = normalized.get("validation")
    if not isinstance(validation, Mapping) or validation.get("mode") != "basic_anchor_only" or validation.get("automatic_retry") is not False:
        raise UiInteractionContractError("source UI interaction validation policy is invalid")
    if validation.get("anchor_frames") != [start_frame, end_frame - 1]:
        raise UiInteractionContractError("source UI interaction anchor frames are invalid")
    return normalized


__all__ = [
    "UiInteractionContractError",
    "build_source_ui_interaction_contract",
    "validate_source_ui_interaction_contract",
]
