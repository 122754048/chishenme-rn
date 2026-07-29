from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


class ControlKeyframeContractError(ValueError):
    pass


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_cut_ids(source_dynamics: Mapping[str, Any]) -> list[str]:
    raw_cuts = source_dynamics.get("source_cuts")
    if not isinstance(raw_cuts, list) or not raw_cuts:
        raise ControlKeyframeContractError("source_dynamics.source_cuts must be a non-empty array")

    cut_ids: list[str] = []
    for index, cut in enumerate(raw_cuts, start=1):
        if not isinstance(cut, Mapping):
            raise ControlKeyframeContractError(f"source cut {index} must be an object")
        cut_id = cut.get("cut_id")
        if not isinstance(cut_id, str) or not cut_id:
            number = cut.get("cut")
            if not isinstance(number, int) or number < 1:
                raise ControlKeyframeContractError(f"source cut {index} must provide cut_id or positive cut")
            cut_id = f"C{number:02d}"
        cut_ids.append(cut_id)

    if len(set(cut_ids)) != len(cut_ids):
        raise ControlKeyframeContractError("source Cut IDs must be unique")
    return cut_ids


def build_control_keyframe_manifest(
    source_dynamics: Mapping[str, Any],
    *,
    source_video_sha256: str | None = None,
    source_keyframes: list[Mapping[str, Any]] | None = None,
    source_keyframe_sheet_sha256: str | None = None,
    replacement_control_sheet_sha256: str | None = None,
    replacement_target_sha256s: list[str] | None = None,
) -> dict[str, Any]:
    cut_ids = source_cut_ids(source_dynamics)
    manifest: dict[str, Any] = {
        "schema_version": "usfr-control-keyframes/v2",
        "source_cut_ids": cut_ids,
        "panel_count": len(cut_ids),
        "fixed_panel_count": None,
        "panels": [
            {"panel_index": index, "cut_id": cut_id}
            for index, cut_id in enumerate(cut_ids, start=1)
        ],
    }
    lineage_values = (
        source_video_sha256,
        source_keyframes,
        source_keyframe_sheet_sha256,
        replacement_control_sheet_sha256,
        replacement_target_sha256s,
    )
    if any(value is not None for value in lineage_values):
        manifest["source_keyframe_lineage"] = {
            "source_video_sha256": source_video_sha256,
            "source_keyframes": [dict(item) for item in source_keyframes or []],
            "source_keyframe_sheet_sha256": source_keyframe_sheet_sha256,
            "replacement_control_sheet_sha256": replacement_control_sheet_sha256,
            "replacement_target_sha256s": list(replacement_target_sha256s or []),
            "seedance_video_reference_required": True,
        }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    return manifest


def _sha256(value: Any, label: str) -> str:
    normalized = str(value or "").lower()
    if _SHA256.fullmatch(normalized) is None:
        raise ControlKeyframeContractError(f"{label} must be a lowercase SHA-256")
    return normalized


def _source_cut_bounds(source_dynamics: Mapping[str, Any]) -> dict[str, tuple[int, int]]:
    cut_ids = source_cut_ids(source_dynamics)
    bounds: dict[str, tuple[int, int]] = {}
    for cut_id, cut in zip(cut_ids, source_dynamics["source_cuts"], strict=True):
        if not isinstance(cut, Mapping):
            raise ControlKeyframeContractError("source Cut must be an object")
        start = cut.get("start_us")
        end = cut.get("end_us")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            raise ControlKeyframeContractError(f"source Cut {cut_id} requires valid microsecond bounds")
        bounds[cut_id] = (start, end)
    return bounds


def _validate_source_keyframe_lineage(
    source_dynamics: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    lineage = manifest.get("source_keyframe_lineage")
    if not isinstance(lineage, Mapping):
        raise ControlKeyframeContractError("source keyframe lineage is required before replacement control generation")
    source_video_sha256 = _sha256(lineage.get("source_video_sha256"), "source keyframe lineage source_video_sha256")
    source_sheet_sha256 = _sha256(lineage.get("source_keyframe_sheet_sha256"), "source keyframe lineage source_keyframe_sheet_sha256")
    replacement_sheet_sha256 = _sha256(lineage.get("replacement_control_sheet_sha256"), "source keyframe lineage replacement_control_sheet_sha256")
    targets = lineage.get("replacement_target_sha256s")
    if not isinstance(targets, list):
        raise ControlKeyframeContractError("source keyframe lineage replacement targets must be an array")
    target_sha256s = [_sha256(value, "replacement target sha256") for value in targets]
    if lineage.get("seedance_video_reference_required") is not True:
        raise ControlKeyframeContractError("source keyframe lineage must require the original video reference for Seedance")

    bounds = _source_cut_bounds(source_dynamics)
    keyframes = lineage.get("source_keyframes")
    if not isinstance(keyframes, list) or len(keyframes) != len(bounds):
        raise ControlKeyframeContractError("source keyframe lineage must contain exactly one source keyframe per Cut")
    for cut_id, keyframe in zip(bounds, keyframes, strict=True):
        if not isinstance(keyframe, Mapping) or keyframe.get("cut_id") != cut_id:
            raise ControlKeyframeContractError("source keyframes must follow source Cut order")
        timestamp = keyframe.get("timestamp_us")
        start, end = bounds[cut_id]
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or not start <= timestamp < end:
            raise ControlKeyframeContractError(f"source keyframe for {cut_id} must fall inside its source Cut")
        _sha256(keyframe.get("sha256"), f"source keyframe {cut_id} sha256")
    return {
        "source_video_sha256": source_video_sha256,
        "source_keyframe_sheet_sha256": source_sheet_sha256,
        "replacement_control_sheet_sha256": replacement_sheet_sha256,
        "replacement_target_sha256s": target_sha256s,
    }


def validate_control_keyframe_manifest(
    source_dynamics: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    expected_cut_ids = source_cut_ids(source_dynamics)
    if manifest.get("fixed_panel_count") is not None:
        raise ControlKeyframeContractError("fixed panel count is forbidden")

    panels = manifest.get("panels")
    if not isinstance(panels, list):
        raise ControlKeyframeContractError("control keyframe manifest requires panels")

    panel_cut_ids: list[str] = []
    for index, panel in enumerate(panels, start=1):
        if not isinstance(panel, Mapping) or not isinstance(panel.get("cut_id"), str):
            raise ControlKeyframeContractError(f"control panel {index} requires cut_id")
        if panel.get("panel_index") != index:
            raise ControlKeyframeContractError("control panel indexes must be contiguous and ordered")
        panel_cut_ids.append(str(panel["cut_id"]))

    if manifest.get("panel_count") != len(expected_cut_ids) or panel_cut_ids != expected_cut_ids:
        raise ControlKeyframeContractError(
            "control keyframe panels must match source Cuts exactly in count and order"
        )

    lineage = _validate_source_keyframe_lineage(source_dynamics, manifest)

    return {
        "schema_version": "usfr-control-keyframes-validation/v1",
        "status": "passed",
        "source_cut_ids": expected_cut_ids,
        "panel_count": len(expected_cut_ids),
        "manifest_sha256": _canonical_sha256(dict(manifest)),
        **lineage,
        "required_director_board_reference_sha256": lineage["replacement_control_sheet_sha256"],
        "required_seedance_video_reference_sha256": lineage["source_video_sha256"],
        # The sheets establish how the director board was made. They are not
        # final Seedance references: the source video supplies motion/context
        # and the approved director board is the sole visual control at @Image1.
        "final_seedance_reference_contract": {
            "source_video_required": True,
            "director_board_required_at_image_slot": 1,
            "internal_artifacts_forbidden": [
                "source_keyframe_sheet",
                "replacement_control_sheet",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate one control-keyframe panel for every source Cut."
    )
    parser.add_argument("--source-dynamics", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_dynamics = json.loads(args.source_dynamics.read_text(encoding="utf-8-sig"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    receipt = validate_control_keyframe_manifest(source_dynamics, manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
