#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


EXTENSION_NAME = "high_fidelity_hybrid_v1"
ROUTE_EXCLUDED_TYPES = {
    "opaque_ui_demo",
    "source_ui_keep",
    "excluded_app_end_card",
    "omit_source_end_card",
}
FRAMING_STRATEGIES = {"crop", "reframe", "extend", "pad"}
PROVENANCE = {"observed", "inferred", "planned"}
CRITICALITIES = {"H", "M", "L"}
FORBIDDEN_LEAKAGE_KEYS = {
    "source_identity",
    "source_person_name",
    "source_character_name",
    "source_brand",
    "source_brand_name",
    "brand_name",
    "source_product_name",
    "product_name",
    "source_app_name",
    "app_name",
    "source_logo",
    "voiceprint",
}
SEMANTIC_CUT_KEYS = {
    "cut",
    "scene_topology",
    "framing_migration",
    "lighting",
    "performance",
    "object_action",
    "speech_audio",
    "evidence",
    "observed_inferred_planned",
    "confidence",
    "uncertainty",
    "criticality",
    "blocker_threshold",
}
ROUTE_EXCLUDED_KEYS = {
    "cut",
    "region_type",
    "start_us",
    "end_us",
    "transition_shell",
    "technical_stream",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _scan_for_leakage(value: Any, path: str = "extension") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.strip().lower().replace("-", "_")
            if normalized in FORBIDDEN_LEAKAGE_KEYS:
                raise ValueError(f"source identity leakage field is forbidden at {path}.{key}")
            _scan_for_leakage(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_leakage(child, f"{path}[{index}]")


def _scan_for_terms(value: Any, terms: tuple[str, ...], path: str = "extension") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _scan_for_terms(child, terms, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_terms(child, terms, f"{path}[{index}]")
    elif isinstance(value, str):
        folded = value.casefold()
        for term in terms:
            if term in folded:
                raise ValueError(f"forbidden source identity token found at {path}")


def _validate_bbox(value: Any, label: str) -> None:
    require(isinstance(value, list) and len(value) == 4, f"{label} normalized bbox must have four values")
    require(all(_is_number(item) and 0 <= item <= 1 for item in value), f"{label} normalized bbox values must be in [0,1]")
    x, y, width, height = value
    require(width > 0 and height > 0 and x + width <= 1 and y + height <= 1, f"{label} normalized bbox exceeds [0,1]")


def _validate_vector(value: Any, label: str) -> None:
    require(isinstance(value, list) and len(value) == 3, f"{label} must contain three components")
    require(all(_is_number(item) and -1 <= item <= 1 for item in value), f"{label} components must be in [-1,1]")


def _validate_evidence(value: Any, label: str, *, required: bool = True) -> None:
    require(isinstance(value, list), f"{label} must be an array")
    if required:
        require(bool(value), f"{label} must be non-empty")
    seen: set[str] = set()
    for index, item in enumerate(value, start=1):
        prefix = f"{label}[{index}]"
        require(isinstance(item, dict), f"{prefix} must be an object")
        evidence_id = item.get("evidence_id")
        require(_non_empty_string(evidence_id) and evidence_id not in seen, f"{prefix}.evidence_id is invalid or duplicated")
        seen.add(evidence_id)
        require(item.get("kind") in {"frame", "audio", "OCR", "ASR", "tracking", "waveform"}, f"{prefix}.kind is invalid")
        start = item.get("start_us")
        end = item.get("end_us")
        require(_is_integer(start) and _is_integer(end) and 0 <= start <= end, f"{prefix} range is invalid")
        frame = item.get("frame")
        require(frame is None or (_is_integer(frame) and frame >= 0), f"{prefix}.frame is invalid")
        require(_non_empty_string(item.get("method")), f"{prefix}.method is empty")
        require(item.get("observed_inferred_planned") in PROVENANCE, f"{prefix} provenance is invalid")
        confidence = item.get("confidence")
        require(_is_number(confidence) and 0 <= confidence <= 1, f"{prefix}.confidence is invalid")


def _validate_phase_ranges(phases: Any, label: str, cut_start: int, cut_end: int) -> None:
    require(isinstance(phases, list) and phases, f"{label} must be non-empty")
    last_end = cut_start
    for index, phase in enumerate(phases, start=1):
        prefix = f"{label}[{index}]"
        require(isinstance(phase, dict), f"{prefix} must be an object")
        start = phase.get("start_us")
        end = phase.get("end_us")
        require(
            _is_integer(start)
            and _is_integer(end)
            and cut_start <= start < end <= cut_end,
            f"{prefix} range is invalid",
        )
        require(start == last_end, f"{label} creates a gap or overlap")
        last_end = end
    require(last_end == cut_end, f"{label} does not cover the semantic Cut")


def _validate_scene_topology(value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    entities = value.get("entities")
    require(isinstance(entities, list) and entities, f"{label}.entities must be non-empty")
    entity_ids: set[str] = set()
    for index, entity in enumerate(entities, start=1):
        prefix = f"{label}.entities[{index}]"
        require(isinstance(entity, dict), f"{prefix} must be an object")
        entity_id = entity.get("entity_id")
        require(_non_empty_string(entity_id) and entity_id not in entity_ids, f"{prefix}.entity_id is invalid or duplicated")
        entity_ids.add(entity_id)
        require(entity.get("layer") in {"foreground", "midground", "background", "offscreen"}, f"{prefix}.layer is invalid")
        _validate_bbox(entity.get("bbox"), f"{prefix}.bbox")
        require(_is_integer(entity.get("z_order")), f"{prefix}.z_order must be an integer")
        require(_non_empty_string(entity.get("relation_to_camera")), f"{prefix}.relation_to_camera is empty")
    relations = value.get("spatial_relations")
    require(isinstance(relations, list) and all(_non_empty_string(item) for item in relations), f"{label}.spatial_relations is invalid")
    occlusion = value.get("occlusion_order")
    require(isinstance(occlusion, list) and all(_non_empty_string(item) for item in occlusion), f"{label}.occlusion_order is invalid")
    for key in ("table_line_y", "horizon_y"):
        coordinate = value.get(key)
        require(coordinate is None or (_is_number(coordinate) and 0 <= coordinate <= 1), f"{label}.{key} is invalid")
    _validate_bbox(value.get("negative_space"), f"{label}.negative_space")


def _validate_framing(value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    require(value.get("strategy") in FRAMING_STRATEGIES, f"{label}.strategy is invalid")
    anchors = value.get("anchors")
    require(isinstance(anchors, list) and anchors, f"{label}.anchors must be non-empty")
    seen: set[str] = set()
    for index, anchor in enumerate(anchors, start=1):
        prefix = f"{label}.anchors[{index}]"
        require(isinstance(anchor, dict), f"{prefix} must be an object")
        anchor_id = anchor.get("anchor_id")
        require(_non_empty_string(anchor_id) and anchor_id not in seen, f"{prefix}.anchor_id is invalid or duplicated")
        seen.add(anchor_id)
        _validate_bbox(anchor.get("bbox"), f"{prefix}.bbox")
    require(_non_empty_string(value.get("topology_constraint")), f"{label}.topology_constraint is empty")


def _validate_lighting(value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    require(_non_empty_string(value.get("key_origin")), f"{label}.key_origin is empty")
    _validate_vector(value.get("key_vector"), f"{label}.key_vector")
    _validate_vector(value.get("shadow_vector"), f"{label}.shadow_vector")
    require(value.get("hardness") in {"hard", "medium", "soft"}, f"{label}.hardness is invalid")
    contrast = value.get("contrast_ratio")
    temperature = value.get("color_temperature_k")
    require(_is_number(contrast) and contrast > 0, f"{label}.contrast_ratio is invalid")
    require(_is_integer(temperature) and 1000 <= temperature <= 20000, f"{label}.color_temperature_k is invalid")


def _validate_performance(value: Any, label: str, cut: dict) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    applicability = value.get("applicability")
    require(applicability in {"person_present", "not_applicable"}, f"{label}.applicability is invalid")
    if cut.get("subject_presence") == "identifiable":
        require(applicability == "person_present", f"{label} must describe the identifiable performer")
    if applicability == "not_applicable":
        require(_non_empty_string(value.get("not_applicable_reason")), f"{label}.not_applicable_reason is empty")
        return
    require(_non_empty_string(value.get("posture")), f"{label}.posture is empty")
    gaze = value.get("gaze_phases")
    expression = value.get("expression_phases")
    gesture = value.get("gesture_phases")
    _validate_phase_ranges(gaze, f"{label}.gaze_phases", cut["start_us"], cut["end_us"])
    _validate_phase_ranges(expression, f"{label}.expression_phases", cut["start_us"], cut["end_us"])
    _validate_phase_ranges(gesture, f"{label}.gesture_phases", cut["start_us"], cut["end_us"])
    for index, phase in enumerate(gaze, start=1):
        require(_non_empty_string(phase.get("target")), f"{label}.gaze_phases[{index}].target is empty")
    for index, phase in enumerate(expression, start=1):
        require(_non_empty_string(phase.get("state")), f"{label}.expression_phases[{index}].state is empty")
    for index, phase in enumerate(gesture, start=1):
        require(_non_empty_string(phase.get("hand")), f"{label}.gesture_phases[{index}].hand is empty")
        require(_non_empty_string(phase.get("path")), f"{label}.gesture_phases[{index}].path is empty")
        require(_non_empty_string(phase.get("end_state")), f"{label}.gesture_phases[{index}].end_state is empty")
    for field in ("objective", "visible_tactic", "emotional_turn", "microphone_relation"):
        require(_non_empty_string(value.get(field)), f"{label}.{field} is empty")


def _validate_object_action(value: Any, label: str, cut: dict) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    states = value.get("state_sequence")
    if not isinstance(states, list) or not states:
        raise ValueError(f"{label} requires a completed action endpoint")
    completed = value.get("completed_end_state")
    if states[-1].get("phase") != "completed" or not _non_empty_string(completed):
        raise ValueError(f"{label} requires a completed action endpoint")
    _validate_phase_ranges(states, f"{label}.state_sequence", cut["start_us"], cut["end_us"])
    for index, state in enumerate(states, start=1):
        require(_non_empty_string(state.get("phase")), f"{label}.state_sequence[{index}].phase is empty")
        require(_non_empty_string(state.get("state")), f"{label}.state_sequence[{index}].state is empty")
    require(states[-1].get("state") == completed, f"{label} completed action endpoint does not match final state")
    require(_non_empty_string(value.get("hand_ownership")), f"{label}.hand_ownership is empty")
    contacts = value.get("contact_points")
    require(isinstance(contacts, list) and all(_non_empty_string(item) for item in contacts), f"{label}.contact_points is invalid")
    require(_non_empty_string(value.get("movement_trajectory")), f"{label}.movement_trajectory is empty")
    caused = value.get("caused_audio_event_ids")
    require(isinstance(caused, list) and all(_is_integer(item) and item > 0 for item in caused), f"{label}.caused_audio_event_ids is invalid")


def _validate_speech_audio(value: Any, label: str, cut: dict, events: list[dict]) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    exact_ids = value.get("exact_asr_event_ids")
    mappings = value.get("audio_event_mappings")
    silence = value.get("meaningful_silence_ranges")
    require(isinstance(exact_ids, list) and all(_is_integer(item) and item > 0 for item in exact_ids), f"{label}.exact_asr_event_ids is invalid")
    require(isinstance(mappings, list), f"{label}.audio_event_mappings is invalid")
    require(isinstance(silence, list), f"{label}.meaningful_silence_ranges is invalid")
    for index, time_range in enumerate(silence, start=1):
        require(isinstance(time_range, dict), f"{label}.meaningful_silence_ranges[{index}] must be an object")
        start, end = time_range.get("start_us"), time_range.get("end_us")
        require(_is_integer(start) and _is_integer(end) and cut["start_us"] <= start < end <= cut["end_us"], f"{label}.meaningful_silence_ranges[{index}] is invalid")
    event_by_id = {event.get("event"): event for event in events}
    mapped_ids: set[int] = set()
    for index, mapping in enumerate(mappings, start=1):
        prefix = f"{label}.audio_event_mappings[{index}]"
        require(isinstance(mapping, dict), f"{prefix} must be an object")
        event_id = mapping.get("event_id")
        require(event_id in event_by_id and event_id not in mapped_ids, f"{prefix}.event_id is invalid or duplicated")
        mapped_ids.add(event_id)
        require(mapping.get("role") == event_by_id[event_id].get("kind"), f"{prefix}.role does not match source event")
        require(_non_empty_string(mapping.get("synced_factor_id")), f"{prefix}.synced_factor_id is empty")
        _validate_evidence(mapping.get("evidence"), f"{prefix}.evidence")
    required_event_ids = {
        event.get("event")
        for event in events
        if event.get("source_cut_start") <= cut["cut"] <= event.get("source_cut_end")
    }
    for event_id in sorted(required_event_ids - mapped_ids):
        raise ValueError(f"{label} audio event {event_id} is not mapped to a visual/proof factor")
    required_asr = {
        event.get("event")
        for event in events
        if event.get("kind") in {"voiceover", "dialogue"}
        and event.get("source_cut_start") <= cut["cut"] <= event.get("source_cut_end")
    }
    require(set(exact_ids) == required_asr, f"{label}.exact_asr_event_ids do not match spoken source events")


def _validate_semantic_cut(extension_cut: Any, source_cut: dict, events: list[dict], index: int) -> None:
    label = f"extensions.{EXTENSION_NAME}.semantic_cuts[{index}]"
    require(isinstance(extension_cut, dict), f"{label} must be an object")
    unknown = set(extension_cut) - SEMANTIC_CUT_KEYS
    require(not unknown, f"{label} has unsupported fields: {sorted(unknown)}")
    require(extension_cut.get("cut") == source_cut.get("cut"), f"{label}.cut mismatch")
    _validate_scene_topology(extension_cut.get("scene_topology"), f"{label}.scene_topology")
    require("framing_migration" in extension_cut, f"{label}.framing_migration is required")
    _validate_framing(extension_cut.get("framing_migration"), f"{label}.framing_migration")
    _validate_lighting(extension_cut.get("lighting"), f"{label}.lighting")
    _validate_performance(extension_cut.get("performance"), f"{label}.performance", source_cut)
    _validate_object_action(extension_cut.get("object_action"), f"{label}.object_action", source_cut)
    _validate_speech_audio(extension_cut.get("speech_audio"), f"{label}.speech_audio", source_cut, events)
    _validate_evidence(extension_cut.get("evidence"), f"{label}.evidence")
    require(extension_cut.get("observed_inferred_planned") in PROVENANCE, f"{label} provenance is invalid")
    confidence = extension_cut.get("confidence")
    threshold = extension_cut.get("blocker_threshold")
    require(_is_number(confidence) and 0 <= confidence <= 1, f"{label}.confidence is invalid")
    require(_is_number(threshold) and 0 <= threshold <= 1, f"{label}.blocker_threshold is invalid")
    criticality = extension_cut.get("criticality")
    require(criticality in CRITICALITIES, f"{label}.criticality is invalid")
    if criticality == "H" and confidence < threshold:
        raise ValueError(f"{label} high-criticality confidence is below blocker threshold")
    uncertainty = extension_cut.get("uncertainty")
    require(isinstance(uncertainty, list) and all(_non_empty_string(item) for item in uncertainty), f"{label}.uncertainty is invalid")


def _validate_route_excluded(value: Any, source_cut: dict, index: int) -> None:
    label = f"extensions.{EXTENSION_NAME}.route_excluded_intervals[{index}]"
    require(isinstance(value, dict), f"{label} must be an object")
    if set(value) - ROUTE_EXCLUDED_KEYS:
        raise ValueError(f"{label} may carry technical metadata only")
    require(value.get("cut") == source_cut.get("cut"), f"{label}.cut mismatch")
    require(value.get("region_type") in ROUTE_EXCLUDED_TYPES, f"{label}.region_type is invalid")
    require(value.get("start_us") == source_cut.get("start_us") and value.get("end_us") == source_cut.get("end_us"), f"{label} must preserve exact Cut boundaries")
    transition = value.get("transition_shell")
    require(isinstance(transition, dict) and _non_empty_string(transition.get("kind")), f"{label}.transition_shell is invalid")
    duration_ms = transition.get("duration_ms")
    require(_is_integer(duration_ms) and duration_ms >= 0, f"{label}.transition_shell.duration_ms is invalid")
    stream = value.get("technical_stream")
    require(isinstance(stream, dict), f"{label}.technical_stream is invalid")
    for key in ("width", "height", "fps_num", "fps_den"):
        require(_is_integer(stream.get(key)) and stream[key] > 0, f"{label}.technical_stream.{key} is invalid")


def validate_high_fidelity_extension(
    value: dict, *, forbidden_source_terms: list[str] | tuple[str, ...] | None = None
) -> None:
    require(isinstance(value, dict), "dynamics contract must be an object")
    extensions = value.get("extensions")
    if extensions is None or EXTENSION_NAME not in extensions:
        return
    require(isinstance(extensions, dict), "extensions must be an object")
    extension = extensions.get(EXTENSION_NAME)
    require(isinstance(extension, dict), f"extensions.{EXTENSION_NAME} must be an object")
    _scan_for_leakage(extension)
    terms = tuple(
        term.strip().casefold()
        for term in (forbidden_source_terms or ())
        if isinstance(term, str) and term.strip()
    )
    if terms:
        _scan_for_terms(extension, terms)
    require(extension.get("schema_version") == 1, "unsupported high-fidelity extension schema_version")
    require(extension.get("analysis_pass_count") == 1, "analysis_pass_count must be 1; reuse the single semantic pass")
    semantic_cuts = extension.get("semantic_cuts")
    excluded = extension.get("route_excluded_intervals")
    require(isinstance(semantic_cuts, list), "semantic_cuts must be an array")
    require(isinstance(excluded, list), "route_excluded_intervals must be an array")
    source_cuts = value.get("source_cuts")
    events = value.get("source_events")
    require(isinstance(source_cuts, list) and source_cuts, "source_cuts must be non-empty")
    require(isinstance(events, list), "source_events must be an array")
    source_by_number = {cut.get("cut"): cut for cut in source_cuts if isinstance(cut, dict)}
    covered: set[int] = set()
    for index, extension_cut in enumerate(semantic_cuts, start=1):
        cut_number = extension_cut.get("cut") if isinstance(extension_cut, dict) else None
        require(cut_number in source_by_number and cut_number not in covered, f"semantic Cut {cut_number} is invalid or duplicated")
        covered.add(cut_number)
        _validate_semantic_cut(extension_cut, source_by_number[cut_number], events, index)
    for index, excluded_cut in enumerate(excluded, start=1):
        cut_number = excluded_cut.get("cut") if isinstance(excluded_cut, dict) else None
        require(cut_number in source_by_number and cut_number not in covered, f"route-excluded Cut {cut_number} is invalid or duplicated")
        covered.add(cut_number)
        _validate_route_excluded(excluded_cut, source_by_number[cut_number], index)
    require(covered == set(source_by_number), "semantic and route-excluded records must cover every source Cut exactly once")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an optional high-fidelity dynamics extension.")
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--forbidden-source-term", action="append", default=[])
    args = parser.parse_args()
    try:
        value = json.loads(args.json_file.read_text(encoding="utf-8"))
        validate_high_fidelity_extension(
            value, forbidden_source_terms=args.forbidden_source_term
        )
        print("VALID")
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
