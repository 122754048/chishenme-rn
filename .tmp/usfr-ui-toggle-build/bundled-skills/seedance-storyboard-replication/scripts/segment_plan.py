from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any


class PlanningError(ValueError):
    pass


MIN_SEGMENT_MS = 4_000
MAX_SEGMENT_MS = 15_000
MAX_SEGMENTS = 2

_GENERATED_REGION_TYPES = {"generated"}
_GENERATED_MEDIA_ORIGINS = {"generated", "generated_media"}
_GENERATED_ASSEMBLY_POLICIES = {"generate_region"}
_NON_SEEDANCE_REGION_TYPES = {
    "excluded_app_end_card",
    "generated_ui",
    "generated_ui_demo",
    "omit_source_end_card",
    "opaque_app_tail_card",
    "opaque_ui_demo",
    "source_end_card_keep",
    "source_interval",
    "source_ui_keep",
}


@dataclass(frozen=True)
class Segment:
    source_start: float
    source_end: float
    output_duration: float

    @property
    def source_duration(self) -> float:
        return self.source_end - self.source_start

    def to_dict(self) -> dict[str, float]:
        return {
            "source_start": self.source_start,
            "source_end": self.source_end,
            "source_duration": self.source_duration,
            "segment_local_start": 0.0,
            "segment_local_end": self.output_duration,
            "output_duration": self.output_duration,
        }


@dataclass(frozen=True)
class SegmentPlan:
    total_source_duration: float
    retime_scale: float
    segments: tuple[Segment, ...]
    selected_split_boundary: float | None = None

    def to_dict(self) -> dict:
        return {
            "total_source_duration": self.total_source_duration,
            "retime_scale": self.retime_scale,
            "selected_split_boundary": self.selected_split_boundary,
            "segments": [segment.to_dict() for segment in self.segments],
        }


def _normalize_boundaries(boundaries: Sequence[float]) -> list[float]:
    if len(boundaries) < 2:
        raise PlanningError("At least two boundaries are required")
    normalized = [float(boundary) for boundary in boundaries]
    for left, right in zip(normalized, normalized[1:]):
        if right <= left:
            raise PlanningError("Cut boundaries must be strictly increasing")
    return normalized


def _one_segment(boundaries: list[float], output_duration: float, retime_scale: float) -> SegmentPlan:
    return SegmentPlan(
        total_source_duration=boundaries[-1] - boundaries[0],
        retime_scale=retime_scale,
        segments=(Segment(boundaries[0], boundaries[-1], output_duration),),
    )


def plan_segments(
    boundaries: Sequence[float],
    split_boundary: float | None = None,
) -> SegmentPlan:
    normalized = _normalize_boundaries(boundaries)
    total = normalized[-1] - normalized[0]
    if total > 30:
        raise PlanningError("Reference video duration must be at most 30 seconds")
    if total <= 15:
        return _one_segment(normalized, total, 1.0)
    if total <= 17:
        return _one_segment(normalized, 15, 15 / total)

    if split_boundary is None:
        raise PlanningError(
            "A story-selected split_boundary is required above 17 seconds; "
            "do not choose a boundary from duration balance alone"
        )
    selected = next(
        (
            boundary
            for boundary in normalized[1:-1]
            if abs(boundary - float(split_boundary)) <= 1e-6
        ),
        None,
    )
    if selected is None:
        raise PlanningError(
            "split_boundary must be an approved Cut boundary; revise the Cut at a "
            "natural internal action beat and ask the user to approve it"
        )
    points = [normalized[0], selected, normalized[-1]]
    durations = [right - left for left, right in zip(points, points[1:])]
    if not all(5 <= duration <= 15 for duration in durations):
        legal_start = max(normalized[0] + 5, normalized[-1] - 15)
        legal_end = min(normalized[0] + 15, normalized[-1] - 5)
        raise PlanningError(
            "story-selected split_boundary creates a segment outside 5-15 seconds; "
            f"choose an approved narrative boundary from {legal_start:g} to {legal_end:g} seconds"
        )
    return SegmentPlan(
        total_source_duration=total,
        retime_scale=1.0,
        selected_split_boundary=selected,
        segments=tuple(
            Segment(left, right, duration)
            for left, right, duration in zip(points, points[1:], durations)
        ),
    )


def _flatten_record(value: Mapping[str, Any]) -> dict[str, Any]:
    metadata = value.get("metadata")
    flattened = dict(metadata) if isinstance(metadata, Mapping) else {}
    flattened.update(dict(value))
    return flattened


def _milliseconds(value: Any, label: str, multiplier: float = 1.0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanningError(f"{label} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise PlanningError(f"{label} must be finite")
    result = int(round(numeric * multiplier))
    if result < 0:
        raise PlanningError(f"{label} cannot be negative")
    return result


def _integer_milliseconds(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanningError(f"{label} must be an integer number of milliseconds")
    if value < 0:
        raise PlanningError(f"{label} cannot be negative")
    return value


def _bounds_ms(value: Mapping[str, Any], label: str) -> tuple[int, int]:
    record = _flatten_record(value)
    candidates = (
        ("output_start_ms", "output_end_ms", 1.0),
        ("start_ms", "end_ms", 1.0),
        ("source_start_ms", "source_end_ms", 1.0),
        ("output_start_us", "output_end_us", 0.001),
        ("source_start_us", "source_end_us", 0.001),
        ("start_us", "end_us", 0.001),
        ("output_start", "output_end", 1_000.0),
        ("source_start", "source_end", 1_000.0),
        ("start", "end", 1_000.0),
    )
    for start_key, end_key, multiplier in candidates:
        if start_key not in record and end_key not in record:
            continue
        if start_key not in record or end_key not in record:
            raise PlanningError(f"{label} must contain both {start_key} and {end_key}")
        start_ms = _milliseconds(record[start_key], f"{label}.{start_key}", multiplier)
        end_ms = _milliseconds(record[end_key], f"{label}.{end_key}", multiplier)
        if end_ms <= start_ms:
            raise PlanningError(f"{label} end must be greater than start")
        return start_ms, end_ms
    raise PlanningError(f"{label} has no supported timing fields")


def _string_list(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise PlanningError(f"{label} must be a non-empty string array")
    result = [str(item).strip() for item in value]
    if len(result) != len(set(result)):
        raise PlanningError(f"Cut coverage in {label} contains duplicates")
    return result


def _normalise_cuts(cuts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(cuts, Sequence) or isinstance(cuts, (str, bytes, bytearray)):
        raise PlanningError("cuts must be an array")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous_end: int | None = None
    for index, raw in enumerate(cuts, start=1):
        if not isinstance(raw, Mapping):
            raise PlanningError(f"cuts[{index}] must be an object")
        item = _flatten_record(raw)
        cut_id = item.get("cut_id")
        if cut_id is None and isinstance(item.get("cut"), int):
            cut_id = f"C{int(item['cut']):02d}"
        if not isinstance(cut_id, str) or not cut_id.strip():
            raise PlanningError(f"cuts[{index}].cut_id is required")
        cut_id = cut_id.strip()
        if cut_id in seen:
            raise PlanningError(f"Cut coverage repeats {cut_id}")
        start_ms, end_ms = _bounds_ms(item, f"cuts[{index}]")
        if previous_end is not None and start_ms < previous_end:
            raise PlanningError("Cuts must be ordered and non-overlapping")
        seen.add(cut_id)
        previous_end = end_ms
        normalized.append(
            {"cut_id": cut_id, "start_ms": start_ms, "end_ms": end_ms}
        )
    return normalized


def _ordinary_generated_region(value: Mapping[str, Any]) -> bool:
    item = _flatten_record(value)
    kind = str(item.get("region_type") or item.get("kind") or "").strip().lower()
    origin = str(item.get("media_origin") or "").strip().lower()
    policy = str(item.get("assembly_policy") or "").strip().lower()
    return (
        kind in _GENERATED_REGION_TYPES
        and origin in _GENERATED_MEDIA_ORIGINS
        and policy in _GENERATED_ASSEMBLY_POLICIES
    )


def _validate_region_route(value: Mapping[str, Any], label: str) -> bool:
    item = _flatten_record(value)
    kind = str(item.get("region_type") or item.get("kind") or "").strip().lower()
    origin = str(item.get("media_origin") or "").strip().lower()
    policy = str(item.get("assembly_policy") or "").strip().lower()
    if kind in _NON_SEEDANCE_REGION_TYPES:
        return False
    generatedish = (
        kind in _GENERATED_REGION_TYPES
        or origin in _GENERATED_MEDIA_ORIGINS
        or policy in _GENERATED_ASSEMBLY_POLICIES
    )
    if generatedish and not _ordinary_generated_region(item):
        raise PlanningError(
            f"{label} declares generated media without the canonical ordinary generated route"
        )
    return _ordinary_generated_region(item)


def _region_cut_ids(
    region: Mapping[str, Any],
    normalized_cuts: Sequence[Mapping[str, Any]],
    *,
    label: str,
    used_cut_ids: set[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    start_ms, end_ms = _bounds_ms(region, label)
    overlapping = [
        dict(cut)
        for cut in normalized_cuts
        if int(cut["start_ms"]) < end_ms and int(cut["end_ms"]) > start_ms
    ]
    if any(
        int(cut["start_ms"]) < start_ms or int(cut["end_ms"]) > end_ms
        for cut in overlapping
    ):
        raise PlanningError(f"Cut coverage for {label} is not aligned to Cut boundaries")
    if (
        not overlapping
        or int(overlapping[0]["start_ms"]) != start_ms
        or int(overlapping[-1]["end_ms"]) != end_ms
        or any(
            int(left["end_ms"]) != int(right["start_ms"])
            for left, right in zip(overlapping, overlapping[1:])
        )
    ):
        raise PlanningError(f"Cuts must continuously cover {label} from start to end")
    derived_ids = [str(cut["cut_id"]) for cut in overlapping]
    raw_ids = _flatten_record(region).get("cut_ids")
    if raw_ids is None:
        cut_ids = derived_ids
    else:
        cut_ids = _string_list(raw_ids, f"{label}.cut_ids")
        duplicates = used_cut_ids.intersection(cut_ids)
        if duplicates:
            raise PlanningError(
                f"Cut coverage repeats Cut IDs across generated regions: {sorted(duplicates)}"
            )
        if cut_ids != derived_ids:
            raise PlanningError(
                f"Cut coverage for {label} must exactly match the generated interval"
            )
    if not cut_ids:
        raise PlanningError(f"Cut coverage for {label} is empty")
    duplicates = used_cut_ids.intersection(cut_ids)
    if duplicates:
        raise PlanningError(
            f"Cut coverage repeats Cut IDs across generated regions: {sorted(duplicates)}"
        )
    used_cut_ids.update(cut_ids)
    return cut_ids, overlapping


def _segment(
    segment_id: str,
    start_ms: int,
    end_ms: int,
    cut_ids: Sequence[str],
) -> dict[str, Any]:
    duration_ms = end_ms - start_ms
    if not MIN_SEGMENT_MS <= duration_ms <= MAX_SEGMENT_MS:
        raise PlanningError(
            f"generated segment duration must remain within 4-15 seconds: {duration_ms}ms"
        )
    return {
        "segment_id": segment_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": duration_ms,
        "cut_ids": list(cut_ids),
    }


def _containing_segment(
    start_ms: int,
    end_ms: int,
    segments: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    matches = [
        segment
        for segment in segments
        if start_ms >= int(segment["start_ms"])
        and end_ms <= int(segment["end_ms"])
    ]
    return matches[0] if len(matches) == 1 else None


def _validate_windows(
    windows: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    *,
    label: str,
    required_segment_id: str | None = None,
) -> None:
    if not isinstance(windows, Sequence) or isinstance(windows, (str, bytes, bytearray)):
        raise PlanningError(f"{label} must be an array")
    for index, raw in enumerate(windows, start=1):
        if not isinstance(raw, Mapping):
            raise PlanningError(f"{label}[{index}] must be an object")
        start_ms, end_ms = _bounds_ms(raw, f"{label}[{index}]")
        segment = _containing_segment(start_ms, end_ms, segments)
        if segment is None:
            raise PlanningError(f"{label}[{index}] crosses or falls outside a segment")
        if required_segment_id is not None and segment["segment_id"] != required_segment_id:
            raise PlanningError(f"{label}[{index}] is outside its line segment")


def _validate_action_endpoints(
    endpoints: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
) -> None:
    if not isinstance(endpoints, Sequence) or isinstance(
        endpoints, (str, bytes, bytearray)
    ):
        raise PlanningError("action_endpoints must be an array")
    for index, raw in enumerate(endpoints, start=1):
        if not isinstance(raw, Mapping):
            raise PlanningError(f"action_endpoints[{index}] must be an object")
        if "at_ms" in raw or "time_ms" in raw:
            key = "at_ms" if "at_ms" in raw else "time_ms"
            point = _integer_milliseconds(raw.get(key), f"action_endpoints[{index}].{key}")
            matches = [
                segment
                for segment in segments
                if int(segment["start_ms"]) <= point < int(segment["end_ms"])
            ]
            if len(matches) != 1:
                raise PlanningError(
                    f"action_endpoints[{index}] crosses or falls outside a segment"
                )
            segment = matches[0]
        else:
            start_ms, end_ms = _bounds_ms(raw, f"action_endpoints[{index}]")
            segment = _containing_segment(start_ms, end_ms, segments)
            if segment is None:
                raise PlanningError(
                    f"action_endpoints[{index}] crosses or falls outside a segment"
                )
        cut_id = raw.get("cut_id")
        if cut_id is not None and str(cut_id) not in segment["cut_ids"]:
            raise PlanningError(f"action_endpoints[{index}] Cut is outside its segment")


def _contains_timed_obligations(*values: Any) -> bool:
    return any(
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) > 0
        for value in values
    )


def _validate_line_contracts(
    line_contracts: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
) -> None:
    if not isinstance(line_contracts, Sequence) or isinstance(
        line_contracts, (str, bytes, bytearray)
    ):
        raise PlanningError("line_contracts must be an array")
    for index, raw in enumerate(line_contracts, start=1):
        if not isinstance(raw, Mapping):
            raise PlanningError(f"line_contracts[{index}] must be an object")
        line_id = str(raw.get("line_id") or index)
        timing = raw.get("time")
        if not isinstance(timing, Mapping):
            timing = raw
        start_ms, end_ms = _bounds_ms(timing, f"line {line_id}")
        segment = _containing_segment(start_ms, end_ms, segments)
        if segment is None:
            raise PlanningError(f"line {line_id} crosses or falls outside a segment")
        cut_id = raw.get("cut_id")
        if cut_id is not None and str(cut_id) not in segment["cut_ids"]:
            raise PlanningError(f"line {line_id} Cut is outside its segment")
        for collection in ("proof_events", "foley_events", "silence_windows"):
            events = raw[collection] if collection in raw else []
            _validate_windows(
                events,
                segments,
                label=collection,
                required_segment_id=str(segment["segment_id"]),
            )


def plan_structured_segments(
    timeline_regions: Sequence[Mapping[str, Any]],
    cuts: Sequence[Mapping[str, Any]],
    *,
    approved_split_boundary_ms: int | None = None,
    line_contracts: Sequence[Mapping[str, Any]] = (),
    proof_events: Sequence[Mapping[str, Any]] = (),
    foley_events: Sequence[Mapping[str, Any]] = (),
    silence_windows: Sequence[Mapping[str, Any]] = (),
    action_endpoints: Sequence[Mapping[str, Any]] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Plan canonical Stage-7 segments from ordinary generated regions only.

    The function is pure: it reads structured timeline/Cut contracts and
    returns only the canonical ``{"segments": [...]}`` payload. UI, opaque,
    source-origin, and tail routes are ignored and never consume a segment.
    """

    if not isinstance(timeline_regions, Sequence) or isinstance(
        timeline_regions, (str, bytes, bytearray)
    ):
        raise PlanningError("timeline_regions must be an array")
    normalized_cuts = _normalise_cuts(cuts)
    generated: list[dict[str, Any]] = []
    previous_timeline_end: int | None = None
    for index, raw in enumerate(timeline_regions, start=1):
        if not isinstance(raw, Mapping):
            raise PlanningError(f"timeline_regions[{index}] must be an object")
        item = _flatten_record(raw)
        label = f"timeline_regions[{index}]"
        start_ms, end_ms = _bounds_ms(item, label)
        if previous_timeline_end is not None and start_ms < previous_timeline_end:
            raise PlanningError("timeline regions must be ordered and must not overlap")
        previous_timeline_end = end_ms
        if _validate_region_route(item, label):
            generated.append(
                {
                    "record": item,
                    "label": label,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                }
            )
    if not generated:
        raise PlanningError("no ordinary generated regions require a Seedance segment")
    if len(generated) > MAX_SEGMENTS:
        raise PlanningError("the structured plan supports at most two generated segments")
    previous_end: int | None = None
    for item in generated:
        if previous_end is not None and int(item["start_ms"]) < previous_end:
            raise PlanningError("generated regions must be ordered and non-overlapping")
        previous_end = int(item["end_ms"])

    used_cut_ids: set[str] = set()
    for item in generated:
        cut_ids, region_cuts = _region_cut_ids(
            item["record"],
            normalized_cuts,
            label=str(item["label"]),
            used_cut_ids=used_cut_ids,
        )
        item["cut_ids"] = cut_ids
        item["cuts"] = region_cuts

    segments: list[dict[str, Any]] = []
    retime_applied = False
    split_regions = [
        item
        for item in generated
        if int(item["end_ms"]) - int(item["start_ms"]) > 17_000
    ]
    if split_regions:
        if len(generated) != 1:
            raise PlanningError("splitting a long region would exceed at most two segments")
        region = split_regions[0]
        if approved_split_boundary_ms is None:
            raise PlanningError(
                "approved_split_boundary_ms is required for a generated region longer than 15 seconds"
            )
        boundary_ms = _integer_milliseconds(
            approved_split_boundary_ms,
            "approved_split_boundary_ms",
        )
        region_cuts = list(region["cuts"])
        boundary_index: int | None = None
        for index, (left, right) in enumerate(zip(region_cuts, region_cuts[1:])):
            if (
                int(left["end_ms"]) == boundary_ms
                and int(right["start_ms"]) == boundary_ms
            ):
                boundary_index = index
                break
        if boundary_index is None:
            raise PlanningError(
                "approved_split_boundary_ms must be an approved Cut boundary"
            )
        left_ids = [str(cut["cut_id"]) for cut in region_cuts[: boundary_index + 1]]
        right_ids = [str(cut["cut_id"]) for cut in region_cuts[boundary_index + 1 :]]
        segments.append(
            _segment("S01", int(region["start_ms"]), boundary_ms, left_ids)
        )
        segments.append(
            _segment("S02", boundary_ms, int(region["end_ms"]), right_ids)
        )
    else:
        if approved_split_boundary_ms is not None:
            raise PlanningError(
                "approved_split_boundary_ms is not applicable when no region requires a split"
            )
        for index, region in enumerate(generated, start=1):
            start_ms = int(region["start_ms"])
            source_end_ms = int(region["end_ms"])
            source_duration_ms = source_end_ms - start_ms
            end_ms = (
                start_ms + MAX_SEGMENT_MS
                if MAX_SEGMENT_MS < source_duration_ms <= 17_000
                else source_end_ms
            )
            if end_ms != source_end_ms:
                retime_applied = True
            segments.append(
                _segment(
                    f"S{index:02d}",
                    start_ms,
                    end_ms,
                    region["cut_ids"],
                )
            )

    if not 1 <= len(segments) <= MAX_SEGMENTS:
        raise PlanningError("the structured plan must contain one or at most two segments")
    planned_cut_ids = [
        str(cut_id) for segment in segments for cut_id in segment["cut_ids"]
    ]
    if len(planned_cut_ids) != len(set(planned_cut_ids)) or set(planned_cut_ids) != used_cut_ids:
        raise PlanningError("Cut coverage must be unique and complete across segments")

    if retime_applied and _contains_timed_obligations(
        line_contracts,
        proof_events,
        foley_events,
        silence_windows,
        action_endpoints,
    ):
        raise PlanningError(
            "15-17 second retime changes approved timing; freeze explicit output-global "
            "retimed Cut and obligation windows before Stage 7"
        )

    _validate_line_contracts(line_contracts, segments)
    _validate_windows(proof_events, segments, label="proof_events")
    _validate_windows(foley_events, segments, label="foley_events")
    _validate_windows(silence_windows, segments, label="silence_windows")
    _validate_action_endpoints(action_endpoints, segments)
    return {"segments": segments}


def _load_boundaries(cuts_json: Path) -> list[float]:
    data = json.loads(cuts_json.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [float(value) for value in data]
    if isinstance(data, dict) and isinstance(data.get("boundaries"), list):
        return [float(value) for value in data["boundaries"]]
    if isinstance(data, dict) and isinstance(data.get("cuts"), list):
        cuts = data["cuts"]
        if not cuts:
            raise PlanningError("cuts must not be empty")
        boundaries = [float(cuts[0]["start"])]
        boundaries.extend(float(cut["end"]) for cut in cuts)
        return boundaries
    raise PlanningError("cuts JSON must be a boundary list or an object with boundaries/cuts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan 4-15 second Seedance segments from Cut boundaries.")
    parser.add_argument("--cuts-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split-boundary", type=float)
    args = parser.parse_args()

    plan = plan_segments(
        _load_boundaries(args.cuts_json),
        split_boundary=args.split_boundary,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
