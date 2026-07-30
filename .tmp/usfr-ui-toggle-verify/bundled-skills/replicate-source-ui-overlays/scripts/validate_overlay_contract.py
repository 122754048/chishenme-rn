#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


KINDS = {"brand_mark", "wordmark", "subtitle", "cta_text", "graphic", "ui", "other"}
PHASES = {"static", "enter", "translate", "scale", "rotate", "transform", "exit"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def rect(value: object, label: str) -> tuple[float, float, float, float]:
    require(isinstance(value, dict), f"{label} must be an object")
    values = tuple(value.get(key) for key in ("x", "y", "width", "height"))
    require(all(isinstance(item, (int, float)) for item in values), f"{label} must contain numeric x/y/width/height")
    x, y, width, height = (float(item) for item in values)
    require(0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1, f"{label} is outside normalized bounds")
    require(x + width <= 1.000001 and y + height <= 1.000001, f"{label} exceeds the visible frame")
    return x, y, width, height


def scalar(value: object, minimum: float, maximum: float, label: str) -> float:
    require(isinstance(value, (int, float)) and minimum <= float(value) <= maximum, f"{label} is invalid")
    return float(value)


def same_frame(left: dict, right: dict) -> bool:
    return left["bbox"] == right["bbox"] and float(left["rotation_deg"]) == float(right["rotation_deg"]) and float(left["opacity"]) == float(right["opacity"])


def validate_overlay(overlay: dict, cut: dict, label: str) -> None:
    require(isinstance(overlay.get("overlay_id"), str) and overlay["overlay_id"].strip(), f"{label} overlay_id is empty")
    kind = overlay.get("kind")
    require(kind in KINDS, f"{label} kind is invalid")
    require(overlay.get("start_us") == cut["start_us"] and overlay.get("end_us") == cut["end_us"], f"{label} must span the complete Cut")
    start_rect, end_rect = rect(overlay.get("start_rect"), f"{label}.start_rect"), rect(overlay.get("end_rect"), f"{label}.end_rect")
    start_rotation = scalar(overlay.get("start_rotation_deg"), -3600, 3600, f"{label}.start_rotation_deg")
    end_rotation = scalar(overlay.get("end_rotation_deg"), -3600, 3600, f"{label}.end_rotation_deg")
    start_opacity = scalar(overlay.get("start_opacity"), 0, 1, f"{label}.start_opacity")
    end_opacity = scalar(overlay.get("end_opacity"), 0, 1, f"{label}.end_opacity")
    phase, interpolation = overlay.get("motion_phase"), overlay.get("interpolation")
    require(phase in PHASES, f"{label} motion_phase is invalid")
    require(interpolation in {"hold", "linear"}, f"{label} interpolation is invalid")
    require(isinstance(overlay.get("motion_path"), str) and overlay["motion_path"].strip(), f"{label} motion_path is empty")
    require(isinstance(overlay.get("layer_relation"), str) and overlay["layer_relation"].strip(), f"{label} layer_relation is empty")
    require(isinstance(overlay.get("z_index"), int), f"{label} z_index must be an integer")
    require(kind != "brand_mark" or overlay.get("observed_text") in {None, ""}, f"{label} brand_mark cannot contain text")
    keyframes = overlay.get("keyframes")
    require(isinstance(keyframes, list) and len(keyframes) >= 2, f"{label} needs at least two keyframes")
    require(keyframes[0].get("time_us") == cut["start_us"] and keyframes[-1].get("time_us") == cut["end_us"], f"{label} keyframes must cover both Cut boundaries")
    previous = cut["start_us"] - 1
    normalized: list[dict] = []
    for index, keyframe in enumerate(keyframes):
        require(isinstance(keyframe, dict), f"{label} keyframe {index} must be an object")
        time_us = keyframe.get("time_us")
        require(isinstance(time_us, int) and previous < time_us <= cut["end_us"], f"{label} keyframe times must increase")
        bbox = rect(keyframe.get("bbox"), f"{label}.keyframes[{index}].bbox")
        rotation = scalar(keyframe.get("rotation_deg"), -3600, 3600, f"{label}.keyframes[{index}].rotation_deg")
        opacity = scalar(keyframe.get("opacity"), 0, 1, f"{label}.keyframes[{index}].opacity")
        normalized.append({"bbox": bbox, "rotation_deg": rotation, "opacity": opacity})
        previous = time_us
    require(normalized[0] == {"bbox": start_rect, "rotation_deg": start_rotation, "opacity": start_opacity}, f"{label} first keyframe does not equal the start state")
    require(normalized[-1] == {"bbox": end_rect, "rotation_deg": end_rotation, "opacity": end_opacity}, f"{label} last keyframe does not equal the end state")
    if phase == "static":
        require(interpolation == "hold" and all(same_frame(normalized[0], item) for item in normalized[1:]), f"{label} static phase must hold an identical state")
    if interpolation == "hold":
        require(all(same_frame(normalized[0], item) for item in normalized[1:]), f"{label} hold interpolation cannot change")
    if interpolation == "linear":
        series = [[item["bbox"][axis] for item in normalized] for axis in range(4)]
        series.extend([[item["rotation_deg"] for item in normalized], [item["opacity"] for item in normalized]])
        for values in series:
            signs = {1 if right > left else -1 for left, right in zip(values, values[1:]) if right != left}
            require(len(signs) <= 1, f"{label} reverses inside one linear motion phase; split the Cut")


def validate(value: dict) -> None:
    require(value.get("contract") == "source-ui-overlay-motion", "invalid contract")
    require(value.get("contract_version") == 1, "unsupported contract_version")
    require(value.get("coordinate_space") == "rotation_corrected_source_visible_frame_normalized", "invalid coordinate_space")
    require(value.get("target_mapping") == "source_normalized_composition_to_target_frame", "invalid target_mapping")
    require(value.get("attachment") == "screen_space", "overlays must use screen_space attachment")
    require(value.get("time_range_semantics") == "start_inclusive_end_exclusive", "invalid time semantics")
    duration = value.get("reference_duration_us")
    require(isinstance(duration, int) and duration > 0, "reference_duration_us must be positive")
    cuts = value.get("cuts")
    require(isinstance(cuts, list) and cuts, "cuts must be non-empty")
    expected_start, last_seen = 0, {}
    for number, cut in enumerate(cuts, start=1):
        require(isinstance(cut, dict) and cut.get("cut") == number, f"Cut {number} numbering mismatch")
        require(cut.get("start_us") == expected_start, f"Cut {number} creates a gap or overlap")
        end = cut.get("end_us")
        require(isinstance(end, int) and expected_start < end <= duration, f"Cut {number} range is invalid")
        overlays = cut.get("source_overlays")
        require(isinstance(overlays, list), f"Cut {number} source_overlays must be an array")
        ids = [item.get("overlay_id") for item in overlays if isinstance(item, dict)]
        require(len(ids) == len(overlays) and len(set(ids)) == len(ids), f"Cut {number} overlay IDs must be unique")
        for index, overlay in enumerate(overlays):
            label = f"Cut {number} overlay {index + 1}"
            validate_overlay(overlay, cut, label)
            overlay_id = overlay["overlay_id"]
            if overlay_id in last_seen:
                require(last_seen[overlay_id] == number - 1, f"{label} reuses an overlay_id after a visibility gap")
            last_seen[overlay_id] = number
        expected_start = end
    require(expected_start == duration, "cuts do not cover the exact duration")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a source UI/Logo overlay motion contract.")
    parser.add_argument("json_file", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.json_file.read_text(encoding="utf-8"))
        validate(value)
        print("VALID")
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
