"""Freeze the artifact scope before any paid USFR image or video generation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_ui_pixels import source_ui_model_partition


_CUT_ID_PATTERN = re.compile(r"\bC\d{2,}\b", re.IGNORECASE)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _content_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _integer(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _tail_omission_required(input_slots: Mapping[str, Any]) -> bool:
    slots = _mapping(input_slots.get("slots"), "input_slots.slots")
    tail = _mapping(slots.get("tail_video"), "input_slots.slots.tail_video")
    routes = _mapping(input_slots.get("routes"), "input_slots.routes")
    return tail.get("present") is False and routes.get("tail") == "omit_source_end_card"


def _normalise_regions(timeline_regions: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = timeline_regions.get("regions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("timeline_regions.regions must be a non-empty array")
    regions: list[dict[str, Any]] = []
    for index, value in enumerate(raw):
        region = dict(_mapping(value, f"timeline_regions.regions[{index}]"))
        region["start_ms"] = _integer(region.get("start_ms"), f"region[{index}].start_ms")
        region["end_ms"] = _integer(region.get("end_ms"), f"region[{index}].end_ms")
        if region["end_ms"] <= region["start_ms"]:
            raise ValueError(f"region[{index}] must have a positive duration")
        cut_ids = region.get("source_cut_ids")
        if not isinstance(cut_ids, list) or not cut_ids or any(not isinstance(item, str) or not item for item in cut_ids):
            raise ValueError(f"region[{index}].source_cut_ids must be a non-empty string array")
        regions.append(region)
    return regions


def _omission_contract(timeline_regions: Mapping[str, Any]) -> tuple[int, int, list[dict[str, Any]], list[str], list[str], list[str]]:
    source_end_ms = _integer(timeline_regions.get("source_end_ms"), "timeline_regions.source_end_ms")
    final_output_end_ms = _integer(timeline_regions.get("final_output_end_ms"), "timeline_regions.final_output_end_ms")
    regions = _normalise_regions(timeline_regions)
    excluded = [
        region for region in regions
        if region.get("assembly_policy") == "omit_source_end_card" or region.get("media_origin") == "excluded"
    ]
    if not excluded:
        raise ValueError("OMITTED_SOURCE_END_CARD_LEAK: missing-tail routing requires an excluded terminal region")
    excluded.sort(key=lambda region: (region["start_ms"], region["end_ms"]))
    if excluded[0]["start_ms"] != final_output_end_ms or excluded[-1]["end_ms"] != source_end_ms:
        raise ValueError("OMITTED_SOURCE_END_CARD_LEAK: final output boundary must equal the first excluded terminal region")
    if any(current["end_ms"] != following["start_ms"] for current, following in zip(excluded, excluded[1:])):
        raise ValueError("OMITTED_SOURCE_END_CARD_LEAK: excluded terminal regions must be contiguous")
    if any(
        region.get(field) is not False
        for region in excluded
        for field in ("include_in_script", "include_in_storyboard", "include_in_seedance")
    ):
        raise ValueError("OMITTED_SOURCE_END_CARD_LEAK: excluded terminal regions must be absent from all generation artifacts")
    allowed_cut_ids: list[str] = []
    excluded_cut_ids: list[str] = []
    prohibited_terms: list[str] = []
    for region in excluded:
        terms = region.get("prohibited_artifact_terms")
        if not isinstance(terms, list) or not terms or any(not isinstance(item, str) or not item.strip() for item in terms):
            raise ValueError("OMITTED_SOURCE_END_CARD_LEAK: every excluded terminal region must declare prohibited_artifact_terms")
        prohibited_terms.extend(item.strip().lower() for item in terms)
    for region in regions:
        if region not in excluded and region["end_ms"] > final_output_end_ms:
            raise ValueError("OMITTED_SOURCE_END_CARD_LEAK: non-excluded content extends beyond the final output boundary")
        destination = excluded_cut_ids if region in excluded else allowed_cut_ids
        destination.extend(region["source_cut_ids"])
    return source_end_ms, final_output_end_ms, regions, allowed_cut_ids, excluded_cut_ids, prohibited_terms


def _validate_segment_plan(segment_plan: Mapping[str, Any], *, final_output_end_ms: int, allowed_cut_ids: list[str], excluded_cut_ids: list[str]) -> None:
    raw_segments = segment_plan.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("segment_plan.segments must be a non-empty array")
    allowed = set(allowed_cut_ids)
    excluded = set(excluded_cut_ids)
    for index, value in enumerate(raw_segments):
        segment = _mapping(value, f"segment_plan.segments[{index}]")
        end_ms = _integer(segment.get("end_ms"), f"segment[{index}].end_ms")
        cut_ids = segment.get("cut_ids")
        if not isinstance(cut_ids, list) or any(not isinstance(item, str) for item in cut_ids):
            raise ValueError(f"segment[{index}].cut_ids must be a string array")
        leaked = sorted(set(cut_ids) & excluded)
        if end_ms > final_output_end_ms or leaked or not set(cut_ids).issubset(allowed):
            raise ValueError("OMITTED_SOURCE_END_CARD_LEAK: segment plan reaches an excluded source-tail interval")


def _validate_text_artifacts(text_artifacts: Mapping[str, str], *, excluded_cut_ids: list[str], prohibited_terms: list[str]) -> dict[str, str]:
    if not text_artifacts:
        raise ValueError("text_artifacts must not be empty")
    excluded = {item.upper() for item in excluded_cut_ids}
    hashes: dict[str, str] = {}
    for name, text in text_artifacts.items():
        if not isinstance(name, str) or not name or not isinstance(text, str) or not text.strip():
            raise ValueError("text_artifacts must contain non-empty names and text")
        mentioned = {item.upper() for item in _CUT_ID_PATTERN.findall(text)}
        forbidden_cuts = sorted(mentioned & excluded)
        lower_text = text.lower()
        forbidden_terms = [term for term in prohibited_terms if term in lower_text]
        if forbidden_cuts or forbidden_terms:
            details = ", ".join(forbidden_cuts + forbidden_terms)
            raise ValueError(f"OMITTED_SOURCE_END_CARD_LEAK: {name} contains excluded tail content ({details})")
        hashes[name] = _content_sha256(text)
    return hashes


def build_scope_receipt(
    *,
    input_slots: Mapping[str, Any],
    timeline_regions: Mapping[str, Any],
    segment_plan: Mapping[str, Any],
    text_artifacts: Mapping[str, str],
) -> dict[str, Any]:
    """Return a content-addressed scope receipt or fail before Provider admission."""
    input_slots = _mapping(input_slots, "input_slots")
    timeline_regions = _mapping(timeline_regions, "timeline_regions")
    segment_plan = _mapping(segment_plan, "segment_plan")
    if not _tail_omission_required(input_slots):
        return {
            "schema_version": "usfr-timeline-scope-receipt/v1",
            "status": "not_applicable",
            "reason": "missing-tail omission route is not active",
        }
    source_end_ms, final_output_end_ms, regions, allowed_cut_ids, excluded_cut_ids, prohibited_terms = _omission_contract(timeline_regions)
    ui_partition = source_ui_model_partition(regions)
    _validate_segment_plan(
        segment_plan,
        final_output_end_ms=final_output_end_ms,
        allowed_cut_ids=allowed_cut_ids,
        excluded_cut_ids=excluded_cut_ids,
    )
    text_artifact_sha256 = _validate_text_artifacts(
        text_artifacts,
        excluded_cut_ids=excluded_cut_ids,
        prohibited_terms=prohibited_terms,
    )
    receipt: dict[str, Any] = {
        "schema_version": "usfr-timeline-scope-receipt/v1",
        "status": "passed",
        "route": "omit_source_end_card",
        "source_end_ms": source_end_ms,
        "final_output_end_ms": final_output_end_ms,
        "allowed_cut_ids": allowed_cut_ids,
        "excluded_cut_ids": excluded_cut_ids,
        **ui_partition,
        "input_slots_sha256": _canonical_sha256(input_slots),
        "timeline_regions_sha256": _canonical_sha256(timeline_regions),
        "segment_plan_sha256": _canonical_sha256(segment_plan),
        "text_artifact_sha256": text_artifact_sha256,
    }
    receipt["scope_sha256"] = _canonical_sha256(receipt)
    return receipt


def validate_scope_receipt_for_text(receipt: Mapping[str, Any], text: str) -> None:
    """Admit only the exact preflighted text to a paid image or video adapter."""
    receipt = _mapping(receipt, "timeline scope receipt")
    status = receipt.get("status")
    if status == "not_applicable":
        return
    if status != "passed":
        raise ValueError("TIMELINE_SCOPE_RECEIPT_INVALID: receipt did not pass preflight")
    expected = receipt.get("scope_sha256")
    actual = _canonical_sha256({key: value for key, value in receipt.items() if key != "scope_sha256"})
    if not isinstance(expected, str) or expected != actual:
        raise ValueError("TIMELINE_SCOPE_RECEIPT_INVALID: receipt digest mismatch")
    text_hashes = receipt.get("text_artifact_sha256")
    if not isinstance(text_hashes, Mapping) or _content_sha256(text) not in text_hashes.values():
        raise ValueError("OMITTED_SOURCE_END_CARD_LEAK: text was not frozen in the timeline scope receipt")


def _read_json(path: Path) -> Mapping[str, Any]:
    return _mapping(json.loads(path.read_text(encoding="utf-8-sig")), str(path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze and validate a USFR pre-generation timeline scope.")
    parser.add_argument("--input-slots", type=Path, required=True)
    parser.add_argument("--timeline-regions", type=Path, required=True)
    parser.add_argument("--segment-plan", type=Path, required=True)
    parser.add_argument("--text-artifact", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    artifacts = {path.name: path.read_text(encoding="utf-8-sig") for path in args.text_artifact}
    receipt = build_scope_receipt(
        input_slots=_read_json(args.input_slots),
        timeline_regions=_read_json(args.timeline_regions),
        segment_plan=_read_json(args.segment_plan),
        text_artifacts=artifacts,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
