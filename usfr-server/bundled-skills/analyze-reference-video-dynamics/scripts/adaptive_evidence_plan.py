#!/usr/bin/env python3
"""Build the single-pass adaptive evidence request for source dynamics.

The video model/agent still performs the semantic observation.  This module
only creates and validates the deterministic evidence envelope that the worker
must provide to that pass.  Keeping the envelope deterministic makes the
analysis server-safe, cacheable, and independent of a workstation path.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


CONTRACT = "high-fidelity-evidence-plan"
CONTRACT_VERSION = 1
PROFILE = "high_fidelity_hybrid_v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")
_OPAQUE_TYPES = {
    "opaque_ui_demo",
    "source_ui_keep",
    "excluded_app_end_card",
    "omit_source_end_card",
}
_OPAQUE_KEYS = {
    "cut",
    "region_type",
    "start_us",
    "end_us",
    "transition_shell",
    "technical_stream",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_sha(value: Any, label: str) -> None:
    _require(isinstance(value, str) and _SHA256.fullmatch(value) is not None, f"{label} must be lowercase SHA-256")


def _probe_fields(probe: Mapping[str, Any]) -> tuple[int, int, int, int]:
    _require(probe.get("contract") == "reference-video-probe", "invalid probe contract")
    _require(probe.get("contract_version") == 1, "unsupported probe contract_version")
    duration = probe.get("duration_us")
    width, height = probe.get("source_width"), probe.get("source_height")
    fps_num, fps_den = probe.get("fps_num"), probe.get("fps_den")
    _require(_is_int(duration) and duration > 0, "probe duration_us must be positive")
    _require(_is_int(width) and width > 0 and _is_int(height) and height > 0, "probe dimensions are invalid")
    _require(_is_int(fps_num) and fps_num > 0 and _is_int(fps_den) and fps_den > 0, "probe fps is invalid")
    return duration, width, height, fps_num, fps_den


def _candidate_times(probe: Mapping[str, Any], duration: int) -> list[int]:
    values = probe.get("scene_cut_candidates_us") or []
    _require(isinstance(values, list), "scene_cut_candidates_us must be an array")
    candidates = sorted({int(value) for value in values if _is_int(value) and 0 < value < duration})
    # Scene detection is only a hint.  Add the exact ends and interval
    # midpoints so a video with no detected edit still receives motion
    # evidence across the whole duration.
    anchors = [0, *candidates, duration]
    if len(anchors) == 2:
        anchors.insert(1, duration // 2)
    else:
        anchors.extend((left + (right - left) // 2 for left, right in zip(anchors, anchors[1:])))
    return sorted(set(value for value in anchors if 0 <= value <= duration))


def _boundary_neighborhoods(times: Sequence[int], duration: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, time_us in enumerate(times, start=1):
        window = min(250_000, max(1_000, duration // 20))
        result.append({
            "boundary_id": f"B{index:03d}",
            "time_us": time_us,
            "window_start_us": max(0, time_us - window),
            "window_end_us": min(duration, time_us + window),
            "method": "decoder_boundary_frames",
            "reason": "edit/action/camera/audio/overlay phase candidate; reconcile in the single semantic pass",
        })
    return result


def _validate_opaque_intervals(value: Any, duration: int) -> None:
    _require(isinstance(value, list), "opaque_intervals must be an array")
    last_end = -1
    for index, item in enumerate(value, start=1):
        label = f"opaque_intervals[{index}]"
        _require(isinstance(item, Mapping), f"{label} must be an object")
        _require(set(item).issubset(_OPAQUE_KEYS), f"{label} must carry technical metadata only")
        _require(item.get("region_type") in _OPAQUE_TYPES, f"{label}.region_type is invalid")
        start, end = item.get("start_us"), item.get("end_us")
        _require(_is_int(start) and _is_int(end) and 0 <= start < end <= duration, f"{label} range is invalid")
        _require(start >= last_end, f"{label} overlaps a previous opaque interval")
        last_end = end
        transition = item.get("transition_shell")
        _require(isinstance(transition, Mapping) and isinstance(transition.get("kind"), str) and transition["kind"].strip(), f"{label}.transition_shell is invalid")
        stream = item.get("technical_stream")
        _require(isinstance(stream, Mapping), f"{label}.technical_stream is invalid")
        for field in ("width", "height", "fps_num", "fps_den"):
            _require(_is_int(stream.get(field)) and stream[field] > 0, f"{label}.technical_stream.{field} is invalid")


def build_evidence_plan(
    probe: Mapping[str, Any],
    *,
    source_sha256: str,
    opaque_intervals: Sequence[Mapping[str, Any]] | None = None,
    audio_required: bool | None = None,
) -> dict[str, Any]:
    """Create a deterministic evidence plan for one source semantic pass."""

    _require(isinstance(probe, Mapping), "probe must be an object")
    duration, width, height, fps_num, fps_den = _probe_fields(probe)
    _validate_sha(source_sha256, "source_sha256")
    opaque = [deepcopy(dict(item)) for item in (opaque_intervals or [])]
    _validate_opaque_intervals(opaque, duration)
    has_audio = bool(probe.get("audio_streams"))
    if audio_required is None:
        audio_required = has_audio
    _require(isinstance(audio_required, bool), "audio_required must be boolean")
    times = _candidate_times(probe, duration)
    keyframes = [
        {
            "keyframe_id": f"K{index:03d}",
            "time_us": time_us,
            "reason": "adaptive motion/action/camera/hold verification",
            "decoder_anchor": True,
        }
        for index, time_us in enumerate(times, start=1)
    ]
    plan: dict[str, Any] = {
        "contract": CONTRACT,
        "contract_version": CONTRACT_VERSION,
        "profile": PROFILE,
        "analysis_pass_count": 1,
        "source": {
            "sha256": source_sha256,
            "duration_us": duration,
            "width": width,
            "height": height,
            "fps_num": fps_num,
            "fps_den": fps_den,
        },
        "coverage": {
            "start_us": 0,
            "end_us": duration,
            "complete_timeline_required": True,
        },
        "candidate_policy": "hints_only",
        "cached_evidence_required": True,
        "evidence": {
            "complete_timeline": {
                "start_us": 0,
                "end_us": duration,
                "method": "complete_timeline_contact_sheet",
                "required": True,
            },
            "boundary_neighborhoods": _boundary_neighborhoods(times, duration),
            "adaptive_keyframes": keyframes,
            "detail_crops": {
                "required_when": ["product", "hand", "face", "UI", "subtitle", "overlay", "small_text"],
                "method": "full_resolution_frame_or_crop",
                "source_only": True,
            },
            "audio": {
                "required": audio_required,
                "transcription_required": audio_required,
                "method": "separate_audio_transcription_and_waveform",
                "reconcile_with_visual": True,
            },
        },
        "opaque_intervals": opaque,
    }
    plan["plan_sha256"] = _sha(plan)
    return plan


def _scan_paths(value: Any, path: str = "plan") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _scan_paths(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_paths(child, f"{path}[{index}]")
    elif isinstance(value, str) and (_ABSOLUTE.match(value) or value.startswith(("file://", "local://"))):
        raise ValueError(f"artifact paths must be object-store relative or omitted: {path}")


def validate_evidence_plan(value: Mapping[str, Any]) -> None:
    _require(isinstance(value, Mapping), "evidence plan must be an object")
    _require(value.get("contract") == CONTRACT, "invalid evidence plan contract")
    _require(value.get("contract_version") == CONTRACT_VERSION, "unsupported evidence plan version")
    _require(value.get("profile") == PROFILE, "evidence plan profile is invalid")
    _require(value.get("analysis_pass_count") == 1, "analysis_pass_count must be 1")
    source = value.get("source")
    _require(isinstance(source, Mapping), "source metadata is required")
    duration = source.get("duration_us")
    _require(_is_int(duration) and duration > 0, "source duration is invalid")
    _validate_sha(source.get("sha256"), "source.sha256")
    coverage = value.get("coverage")
    _require(isinstance(coverage, Mapping) and coverage.get("start_us") == 0 and coverage.get("end_us") == duration, "coverage must span exact source duration")
    _require(coverage.get("complete_timeline_required") is True, "complete timeline evidence is required")
    _require(value.get("candidate_policy") == "hints_only", "candidate_policy must be hints_only")
    evidence = value.get("evidence")
    _require(isinstance(evidence, Mapping), "evidence is required")
    complete = evidence.get("complete_timeline")
    _require(isinstance(complete, Mapping) and complete.get("start_us") == 0 and complete.get("end_us") == duration, "complete timeline must cover exact duration")
    _require(complete.get("method") == "complete_timeline_contact_sheet", "complete timeline method is invalid")
    boundaries = evidence.get("boundary_neighborhoods")
    _require(isinstance(boundaries, list) and boundaries, "boundary neighborhoods are required")
    for index, item in enumerate(boundaries, start=1):
        _require(isinstance(item, Mapping), f"boundary_neighborhoods[{index}] must be an object")
        for field in ("time_us", "window_start_us", "window_end_us"):
            _require(_is_int(item.get(field)) and 0 <= item[field] <= duration, f"boundary_neighborhoods[{index}].{field} is invalid")
        _require(item["window_start_us"] <= item["time_us"] <= item["window_end_us"], f"boundary_neighborhoods[{index}] window is invalid")
    keyframes = evidence.get("adaptive_keyframes")
    _require(isinstance(keyframes, list) and len(keyframes) >= 2, "adaptive keyframes must cover start and end")
    times = [item.get("time_us") for item in keyframes if isinstance(item, Mapping)]
    _require(times == sorted(set(times)), "adaptive keyframes must be sorted and unique")
    _require(times[0] == 0 and times[-1] == duration, "adaptive keyframes must include exact start and end")
    detail = evidence.get("detail_crops")
    _require(isinstance(detail, Mapping) and isinstance(detail.get("required_when"), list) and detail["required_when"], "detail crop policy is incomplete")
    audio = evidence.get("audio")
    _require(isinstance(audio, Mapping) and isinstance(audio.get("transcription_required"), bool), "audio evidence policy is invalid")
    _validate_opaque_intervals(value.get("opaque_intervals", []), duration)
    _scan_paths(value)
    expected = dict(value)
    expected.pop("plan_sha256", None)
    _validate_sha(value.get("plan_sha256"), "plan_sha256")
    _require(_sha(expected) == value.get("plan_sha256"), "evidence plan digest mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or validate a high-fidelity adaptive evidence plan.")
    parser.add_argument("probe", type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    try:
        value = json.loads(args.probe.read_text(encoding="utf-8-sig"))
        if args.validate:
            validate_evidence_plan(value)
        else:
            value = build_evidence_plan(value, source_sha256=args.source_sha256)
            if args.output is None:
                raise ValueError("--output is required when building a plan")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("VALID")
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_evidence_plan", "validate_evidence_plan"]
