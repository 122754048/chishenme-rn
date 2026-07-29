#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PRESENCE = {"identifiable", "partial_or_hands", "transition_residue", "screen_pixels_only", "none", "uncertain"}
EVENT_KINDS = {"voiceover", "dialogue", "subtitle", "sfx", "music", "ambience", "silence"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(value: dict, probe: dict | None = None) -> None:
    require(value.get("contract") == "reference-video-dynamics", "invalid contract")
    require(value.get("contract_version") == 1, "unsupported contract_version")
    duration = value.get("reference_duration_us")
    require(isinstance(duration, int) and duration > 0, "reference_duration_us must be positive")
    if probe is not None:
        require(probe.get("contract") == "reference-video-probe", "invalid probe contract")
        require(duration == probe.get("duration_us"), "analysis duration does not match probe")
        for field in ("source_width", "source_height", "fps_num", "fps_den"):
            require(value.get(field) == probe.get(field), f"{field} does not match probe")
    require(
        "analysis_provenance" not in value,
        "external analyzer provenance is not allowed in the GPT keyframe production flow",
    )
    cuts = value.get("source_cuts")
    require(isinstance(cuts, list) and cuts, "source_cuts must be non-empty")
    require(value.get("source_cut_count") == len(cuts), "source_cut_count mismatch")
    expected_start = 0
    for number, cut in enumerate(cuts, start=1):
        require(isinstance(cut, dict), f"Cut {number} must be an object")
        require(cut.get("cut") == number, f"Cut {number} numbering mismatch")
        require(cut.get("start_us") == expected_start, f"Cut {number} creates a gap or overlap")
        end = cut.get("end_us")
        require(isinstance(end, int) and end > expected_start and end <= duration, f"Cut {number} end_us is invalid")
        require(cut.get("subject_presence") in PRESENCE, f"Cut {number} subject_presence is invalid")
        require(isinstance(cut.get("content_roles"), list) and cut["content_roles"], f"Cut {number} content_roles is empty")
        for field in ("scene", "action", "camera", "transition", "end_state"):
            require(isinstance(cut.get(field), str) and cut[field].strip(), f"Cut {number} {field} is empty")
        require(cut.get("certainty") in {"certain", "uncertain"}, f"Cut {number} certainty is invalid")
        expected_start = end
    require(expected_start == duration, "source_cuts do not cover the exact duration")
    events = value.get("source_events")
    require(isinstance(events, list) and events, "source_events must be non-empty")
    for number, event in enumerate(events, start=1):
        require(event.get("event") == number, f"event {number} numbering mismatch")
        require(event.get("kind") in EVENT_KINDS, f"event {number} kind is invalid")
        start, end = event.get("start_us"), event.get("end_us")
        require(isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= duration, f"event {number} range is invalid")
        first, last = event.get("source_cut_start"), event.get("source_cut_end")
        require(isinstance(first, int) and isinstance(last, int) and 1 <= first <= last <= len(cuts), f"event {number} Cut range is invalid")
        require(isinstance(event.get("text"), str), f"event {number} text is invalid")
        require(
            event.get("certainty") in {"certain", "uncertain", "inaudible", "not_applicable"},
            f"event {number} certainty is invalid",
        )
    extensions = value.get("extensions")
    if isinstance(extensions, dict) and "high_fidelity_hybrid_v1" in extensions:
        try:
            from validate_high_fidelity_extension import validate_high_fidelity_extension
        except ModuleNotFoundError:
            import importlib.util

            extension_path = Path(__file__).with_name("validate_high_fidelity_extension.py")
            spec = importlib.util.spec_from_file_location("validate_high_fidelity_extension", extension_path)
            if spec is None or spec.loader is None:
                raise ValueError("high-fidelity extension validator is unavailable")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            validate_high_fidelity_extension = module.validate_high_fidelity_extension
        validate_high_fidelity_extension(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a reference-video dynamics contract.")
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--probe", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.json_file.read_text(encoding="utf-8"))
        probe = json.loads(args.probe.read_text(encoding="utf-8")) if args.probe else None
        validate(value, probe)
        print("VALID")
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
