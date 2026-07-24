from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
import hmac
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping
import math
import unicodedata

try:  # package-relative import is mandatory for the production bundle loader
    from .concat_videos import (
        ConcatError,
        TransitionBoundary,
        concat_segments,
        probe_media,
        render_transition_segments,
    )
except ImportError:  # CLI/test harness compatibility when run as a script
    from concat_videos import (
        ConcatError,
        TransitionBoundary,
        concat_segments,
        probe_media,
        render_transition_segments,
    )
try:
    from .media_quality import (
        ActiveWindow,
        MediaQualityError,
        detect_active_window,
        validate_final_media,
    )
except ImportError:  # CLI/test harness compatibility when run as a script
    from media_quality import (
        ActiveWindow,
        MediaQualityError,
        detect_active_window,
        validate_final_media,
    )
try:
    from validate_overlay_contract import validate as validate_source_overlay_contract
except ModuleNotFoundError:  # bundled sibling skill when run from a test harness
    _overlay_validator_dir = (
        Path(__file__).resolve().parents[2]
        / "replicate-source-ui-overlays"
        / "scripts"
    )
    if str(_overlay_validator_dir) not in sys.path:
        sys.path.insert(0, str(_overlay_validator_dir))
    from validate_overlay_contract import validate as validate_source_overlay_contract


CANONICAL_REGION_TYPES = {
    "generated",
    "opaque_ui_demo",
    "generated_ui_demo",
    "excluded_app_end_card",
}
LEGACY_KIND_MAP = {
    "generated": "generated",
    "ui_demo": "opaque_ui_demo",
    "logo_download_animation": "excluded_app_end_card",
}
ALLOWED_KINDS = CANONICAL_REGION_TYPES
REPLACEMENT_KINDS = {"opaque_ui_demo", "excluded_app_end_card"}
SUPPORTED_OPAQUE_AUDIO_POLICIES = {
    "opaque_audio_keep",
    "evidence_bound_mix",
    "silence_allowed",
}
NATURAL_MEDIA_DURATION_POLICY = "natural_media_duration"
SUPPORTED_TRANSITION_TYPES = {
    "hard_cut",
    "push",
    "push_left",
    "push_right",
    "push_up",
    "push_down",
    "slide",
    "slide_left",
    "slide_right",
    "slide_up",
    "slide_down",
    "zoom",
    "zoom_in",
    "zoom_out",
    "zoom_back",
    "wipe",
    "wipe_left",
    "wipe_right",
    "wipe_up",
    "wipe_down",
    "dissolve",
    "fade",
    "preview_expand",
    "reveal_expand",
    "match_expand",
    "radial_zoom_blur",
}
GENERATED_UI_QC_CHECKS = (
    "ocr_passed",
    "approved_copy_passed",
    "page_state_passed",
    "layout_passed",
)
ALLOWED_MEDIA_ORIGINS = {"user_upload", "source_interval", "generated_media"}
TAIL_CARD_NORMALIZATION_OPERATIONS = (
    "scale",
    "spatial_crop",
    "frame_rate",
    "boundary_black_trim",
    "video_pts_reset",
    "video_codec",
    "pixel_format",
    "audio_boundary_trim",
    "audio_pts_reset",
    "audio_codec",
    "sample_rate",
    "channel_layout",
    "container",
)
OPAQUE_UI_NORMALIZATION_OPERATIONS = (
    "scale",
    "spatial_crop",
    "frame_rate",
    "boundary_black_trim",
    "video_pts_reset",
    "video_codec",
    "pixel_format",
    "audio_boundary_trim",
    "audio_pts_reset",
    "audio_codec",
    "sample_rate",
    "channel_layout",
    "container",
)


class TimelineSpliceError(RuntimeError):
    pass


@dataclass(frozen=True)
class TimelineRegion:
    kind: str
    source_start: float
    source_end: float
    media_path: Path | None
    region_id: str | None = None
    legacy_kind: str | None = None
    source_start_us: int = 0
    source_end_us: int = 0
    duration_policy: str | None = None
    transition_shell: dict[str, Any] | None = None
    transition_shell_applied: bool | dict[str, Any] | None = None
    ui_truth_card: dict[str, Any] | None = None
    ui_render_contract: dict[str, Any] | None = None
    ui_qc_report: dict[str, Any] | None = None
    ui_qc_report_sha256: str | None = None
    ui_truth_card_sha256: str | None = None
    ui_render_contract_sha256: str | None = None
    media_sha256: str | None = None
    provider_carrier_receipts: tuple[dict[str, Any], ...] = ()
    carrier_receipts: tuple[dict[str, Any], ...] = ()
    media_origin: str = "generated_media"
    assembly_policy: str | None = None
    audio_policy: str = "source_audio_keep"
    tail_append: bool = False
    planned_transition: bool = False

    @property
    def duration(self) -> float:
        return self.source_end - self.source_start


@dataclass(frozen=True)
class TimelineContract:
    source_duration: float
    regions: tuple[TimelineRegion, ...]
    target_width: int | None = None
    target_height: int | None = None
    target_fps: int = 24
    source_fps: float = 24.0
    source_duration_us: int = 0
    source_overlay_contract_sha256: str | None = None
    overlay_render_mapping_sha256: str | None = None


def load_contract(path: Path) -> TimelineContract:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TimelineSpliceError("timeline contract must be a JSON object")

    target = data.get("target") or {}
    if not isinstance(target, dict):
        raise TimelineSpliceError("target must be an object")
    width = int(target["width"]) if target.get("width") else None
    height = int(target["height"]) if target.get("height") else None
    fps = int(target.get("fps") or 24)
    if (width is not None and width <= 0) or (height is not None and height <= 0):
        raise TimelineSpliceError("target dimensions must be positive")
    if fps <= 0:
        raise TimelineSpliceError("target fps must be positive")

    raw_regions_candidate = data.get("regions")
    uses_microseconds = data.get("source_duration_us") is not None or (
        isinstance(raw_regions_candidate, list)
        and any(
            isinstance(item, dict)
            and ("source_start_us" in item or "source_end_us" in item)
            for item in raw_regions_candidate
        )
    )
    if uses_microseconds and data.get("source_fps") is None:
        raise TimelineSpliceError(
            "source_fps is required for a microsecond timeline contract"
        )
    source_fps = _parse_fps(data.get("source_fps"), fallback=float(fps))
    source_duration_us_raw = data.get("source_duration_us")
    if source_duration_us_raw is not None:
        source_duration_us = _positive_int(
            source_duration_us_raw, "source_duration_us"
        )
        source_duration = source_duration_us / 1_000_000
    else:
        source_duration = float(data.get("source_duration") or 0)
        if source_duration <= 0:
            raise TimelineSpliceError("source_duration must be positive")
        source_duration_us = round(source_duration * 1_000_000)

    raw_regions = data.get("regions")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise TimelineSpliceError("timeline contract requires regions")

    _promote_region_overlay_contracts(data, raw_regions)

    base_dir = path.parent
    source_overlay_contract: dict[str, Any] | None = None
    source_overlay_contract_sha256: str | None = None
    if data.get("source_overlay_contract") is not None:
        source_overlay_contract, source_overlay_contract_sha256 = _load_contract_mapping(
            data.get("source_overlay_contract"),
            base_dir,
            "source_overlay_contract",
        )
        try:
            validate_source_overlay_contract(source_overlay_contract)
        except (TypeError, ValueError, KeyError) as exc:
            raise TimelineSpliceError(
                f"source_overlay_contract is invalid: {exc}"
            ) from exc
    shell_lookup = _transition_shell_lookup(data.get("transition_shells"))
    regions: list[TimelineRegion] = []
    for index, item in enumerate(raw_regions, start=1):
        if not isinstance(item, dict):
            raise TimelineSpliceError(f"region {index} must be an object")
        kind, legacy_kind = _parse_region_type(item, index)
        source_start, source_end, source_start_us, source_end_us = _parse_region_time(
            item, index
        )
        if source_end <= source_start:
            raise TimelineSpliceError(f"region {index} has invalid time range")

        media_path = _resolve_optional_path(base_dir, item.get("media_path"))
        media_origin = str(item.get("media_origin") or (
            "user_upload"
            if kind in REPLACEMENT_KINDS
            else "generated_media"
        ))
        if media_origin not in ALLOWED_MEDIA_ORIGINS:
            raise TimelineSpliceError(
                f"region {index} has unsupported media_origin: {media_origin}"
            )
        assembly_policy = (
            str(item.get("assembly_policy"))
            if item.get("assembly_policy")
            else None
        )
        duration_policy = (
            str(item.get("duration_policy"))
            if item.get("duration_policy")
            else None
        )
        if (
            kind in {"generated", "generated_ui_demo"}
            and media_origin == "generated_media"
        ):
            if duration_policy is None:
                duration_policy = NATURAL_MEDIA_DURATION_POLICY
            elif duration_policy != NATURAL_MEDIA_DURATION_POLICY:
                raise TimelineSpliceError(
                    f"{kind} region {index} requires natural_media_duration"
                )
        if kind in REPLACEMENT_KINDS and media_origin != "source_interval":
            audio_policy = str(item.get("audio_policy") or "opaque_audio_keep").strip().lower()
            if audio_policy not in SUPPORTED_OPAQUE_AUDIO_POLICIES:
                raise TimelineSpliceError(
                    "AUDIO_POLICY_CAPABILITY_REQUIRED: opaque replacement audio policy "
                    f"{audio_policy!r} requires a dedicated audio compositor"
                )
        else:
            audio_policy = str(item.get("audio_policy") or "source_audio_keep").strip().lower()
        if media_origin == "source_interval":
            forbidden_bindings = sorted(
                key
                for key in (
                    "slot_id",
                    "input_slot_id",
                    "media_slot_id",
                    "media_artifact_id",
                    "artifact_id",
                    "media_artifact_sha256",
                    "artifact_sha256",
                    "media_artifact_bindings",
                    "provider_carrier_receipts",
                    "carrier_receipts",
                    "segment_id",
                    "segment_plan_sha256",
                )
                if key in item and item.get(key) is not None
            )
            if forbidden_bindings:
                raise TimelineSpliceError(
                    "source/omitted route contains forbidden media binding fields: "
                    + ", ".join(forbidden_bindings)
                )
            omitted_source_tail = (
                kind == "excluded_app_end_card"
                and media_path is None
                and str(assembly_policy or "").strip().lower()
                in {"omit_source_end_card", "omit_source_tail", "omit"}
            )
            if media_path is None and not omitted_source_tail:
                raise TimelineSpliceError(
                    f"source_interval region {index} requires media_path"
                )
            if not omitted_source_tail and assembly_policy != "splice_source_interval":
                raise TimelineSpliceError(
                    f"source_interval region {index} requires "
                    "assembly_policy=splice_source_interval"
                )
        if kind in {"generated", "opaque_ui_demo", "generated_ui_demo"} and media_path is None:
            raise TimelineSpliceError(f"{kind} region {index} requires media_path")

        transition_shell = _resolve_transition_shell(item, shell_lookup, index)
        transition_applied = item.get("transition_shell_applied")
        if kind == "excluded_app_end_card" and media_path is not None:
            _require_transition_phase(
                transition_shell,
                "entry",
                index,
                transition_applied,
            )
        if kind == "opaque_ui_demo":
            if index > 1:
                _require_transition_phase(
                    transition_shell,
                    "entry",
                    index,
                    transition_applied,
                )
            if index < len(raw_regions):
                _require_transition_phase(
                    transition_shell,
                    "exit",
                    index,
                    transition_applied,
                )

        ui_truth_card = None
        ui_truth_card_sha256 = None
        ui_render_contract = None
        ui_render_contract_sha256 = None
        ui_qc_report = None
        ui_qc_report_sha256 = None
        media_sha256 = None
        if kind == "generated_ui_demo":
            ui_truth_card, ui_truth_card_sha256 = _load_json_mapping(
                item.get("ui_truth_card"), base_dir, "ui_truth_card", index
            )
            ui_render_contract, ui_render_contract_sha256 = _load_json_mapping(
                item.get("ui_render_contract"),
                base_dir,
                "ui_render_contract",
                index,
            )
            ui_qc_report, ui_qc_report_sha256 = _load_json_mapping(
                item.get("ui_qc_report"), base_dir, "ui_qc_report", index
            )
            assert media_path is not None
            media_sha256 = _validate_generated_ui_qc(
                media_path,
                ui_qc_report,
                index,
                ui_truth_card=ui_truth_card,
                ui_truth_card_sha256=ui_truth_card_sha256,
                ui_render_contract_sha256=ui_render_contract_sha256,
                ui_render_contract=ui_render_contract,
            )

        provider_carrier_receipts = _parse_provider_carrier_receipts(item, index)
        if provider_carrier_receipts and (
            kind != "generated" or media_origin != "generated_media"
        ):
            raise TimelineSpliceError(
                f"region {index} provider carrier receipts require generated/generated_media"
            )

        regions.append(
            TimelineRegion(
                kind=kind,
                source_start=source_start,
                source_end=source_end,
                media_path=media_path,
                region_id=str(item.get("region_id")) if item.get("region_id") else None,
                legacy_kind=legacy_kind,
                source_start_us=source_start_us,
                source_end_us=source_end_us,
                duration_policy=str(item.get("duration_policy"))
                if item.get("duration_policy")
                else duration_policy,
                transition_shell=transition_shell,
                transition_shell_applied=transition_applied,
                ui_truth_card=ui_truth_card,
                ui_render_contract=ui_render_contract,
                ui_qc_report=ui_qc_report,
                ui_qc_report_sha256=ui_qc_report_sha256,
                ui_truth_card_sha256=ui_truth_card_sha256,
                ui_render_contract_sha256=ui_render_contract_sha256,
                media_sha256=media_sha256,
                provider_carrier_receipts=provider_carrier_receipts,
                carrier_receipts=_parse_carrier_receipts(item, index),
                media_origin=media_origin,
                assembly_policy=assembly_policy,
                audio_policy=audio_policy,
                tail_append=item.get("tail_append") is True,
                planned_transition=item.get("planned_transition") is True,
            )
        )

    _validate_coverage(
        regions,
        source_duration,
        tolerance=max(1.0 / source_fps, 1e-6),
    )
    for region_index, region in enumerate(regions):
        if region.kind == "excluded_app_end_card" and (
            region.media_path is None or _omits_source_tail(region)
        ) and region_index != len(regions) - 1:
            raise TimelineSpliceError(
                "excluded_app_end_card without replacement media must be terminal"
            )
    # A generated UI interval is still an interval in the source interaction
    # graph.  When it has a neighbour, both boundary shells are required so
    # the deterministic compositor can reproduce the source handoff.  A
    # single-region generated UI contract has no external boundary and remains
    # valid without a shell.
    for region_index, region in enumerate(regions):
        if region.kind != "generated_ui_demo":
            continue
        if region_index > 0:
            _require_transition_phase(
                region.transition_shell,
                "entry",
                region_index + 1,
                region.transition_shell_applied,
            )
        if region_index + 1 < len(regions):
            _require_transition_phase(
                region.transition_shell,
                "exit",
                region_index + 1,
                region.transition_shell_applied,
            )
    overlay_render_mapping_sha256: str | None = None
    if source_overlay_contract is not None:
        overlay_render_mapping = None
        if data.get("overlay_render_mapping") is not None:
            overlay_render_mapping, overlay_render_mapping_sha256 = _load_contract_mapping(
                data.get("overlay_render_mapping"),
                base_dir,
                "overlay_render_mapping",
            )
        _validate_generated_overlay_mapping(
            regions,
            source_overlay_contract,
            overlay_render_mapping,
            source_overlay_contract_sha256=source_overlay_contract_sha256,
        )
        _validate_overlay_render_receipts_contract(
            data,
            regions,
            source_overlay_contract,
            overlay_render_mapping,
            source_overlay_contract_sha256=source_overlay_contract_sha256,
            overlay_render_mapping_sha256=overlay_render_mapping_sha256,
        )
    elif data.get("overlay_render_receipts_required") is True:
        raise TimelineSpliceError(
            "OVERLAY_RENDER_RECEIPT_REQUIRED: active semantic overlay assembly requires source_overlay_contract"
        )
    return TimelineContract(
        source_duration=source_duration,
        source_duration_us=source_duration_us,
        source_fps=source_fps,
        regions=tuple(regions),
        target_width=width,
        target_height=height,
        target_fps=fps,
        source_overlay_contract_sha256=source_overlay_contract_sha256,
        overlay_render_mapping_sha256=overlay_render_mapping_sha256,
    )


def _parse_region_type(item: dict[str, Any], index: int) -> tuple[str, str | None]:
    if item.get("region_type") is not None:
        if item.get("kind") is not None:
            raise TimelineSpliceError(
                f"region {index} must not mix region_type with legacy kind"
            )
        kind = str(item.get("region_type") or "")
        if kind not in CANONICAL_REGION_TYPES:
            raise TimelineSpliceError(
                f"region {index} has unsupported region_type: {kind}"
            )
        return kind, None

    legacy_kind = str(item.get("kind") or "")
    if legacy_kind not in LEGACY_KIND_MAP:
        raise TimelineSpliceError(
            f"region {index} has unsupported legacy kind: {legacy_kind}"
        )
    return LEGACY_KIND_MAP[legacy_kind], legacy_kind


def _parse_region_time(
    item: dict[str, Any], index: int
) -> tuple[float, float, int, int]:
    has_us = "source_start_us" in item or "source_end_us" in item
    if has_us:
        if "source_start_us" not in item or "source_end_us" not in item:
            raise TimelineSpliceError(
                f"region {index} requires both source_start_us and source_end_us"
            )
        start_us = _nonnegative_int(item["source_start_us"], "source_start_us")
        end_us = _nonnegative_int(item["source_end_us"], "source_end_us")
        return start_us / 1_000_000, end_us / 1_000_000, start_us, end_us

    try:
        start = float(item.get("source_start"))
        end = float(item.get("source_end"))
    except (TypeError, ValueError) as exc:
        raise TimelineSpliceError(
            f"region {index} requires numeric source_start/source_end"
        ) from exc
    return start, end, round(start * 1_000_000), round(end * 1_000_000)


def _parse_provider_carrier_receipts(
    item: Mapping[str, Any],
    index: int,
) -> tuple[dict[str, Any], ...]:
    raw = item.get("provider_carrier_receipts")
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise TimelineSpliceError(
            f"region {index} provider_carrier_receipts must be a non-empty array"
        )
    receipts: list[dict[str, Any]] = []
    segment_ids: set[str] = set()
    artifact_ids: set[str] = set()
    for receipt in raw:
        if not isinstance(receipt, Mapping):
            raise TimelineSpliceError(
                f"region {index} provider carrier receipt must be an object"
            )
        normalized = dict(receipt)
        segment_id = str(normalized.get("segment_id") or "").strip()
        artifact_id = str(normalized.get("artifact_id") or "").strip()
        if (
            normalized.get("kind") != "provider_video"
            or not segment_id
            or segment_id in segment_ids
            or not artifact_id
            or artifact_id in artifact_ids
        ):
            raise TimelineSpliceError(
                f"region {index} provider carrier receipt identity is invalid"
            )
        for field in (
            "artifact_sha256",
            "segment_plan_sha256",
            "carrier_sha256",
        ):
            digest = str(normalized.get(field) or "").lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise TimelineSpliceError(
                    f"region {index} provider carrier receipt {field} is invalid"
                )
            normalized[field] = digest
        segment_sha = str(normalized.get("segment_sha256") or normalized["artifact_sha256"]).lower()
        if re.fullmatch(r"[0-9a-f]{64}", segment_sha) is None or segment_sha != normalized["artifact_sha256"]:
            raise TimelineSpliceError(
                f"region {index} provider carrier receipt segment SHA does not match artifact SHA"
            )
        normalized["segment_sha256"] = segment_sha
        combined_sha = str(normalized.get("combined_carrier_sha256") or normalized["carrier_sha256"]).lower()
        if re.fullmatch(r"[0-9a-f]{64}", combined_sha) is None or combined_sha != normalized["carrier_sha256"]:
            raise TimelineSpliceError(
                f"region {index} provider carrier receipt combined carrier SHA is invalid"
            )
        normalized["combined_carrier_sha256"] = combined_sha
        normalized["segment_id"] = segment_id
        normalized["artifact_id"] = artifact_id
        segment_ids.add(segment_id)
        artifact_ids.add(artifact_id)
        receipts.append(normalized)
    return tuple(receipts)


def _parse_carrier_receipts(
    item: Mapping[str, Any],
    index: int,
) -> tuple[dict[str, Any], ...]:
    raw = item.get("carrier_receipts")
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise TimelineSpliceError(
            f"region {index} carrier_receipts must be a non-empty array"
        )
    result: list[dict[str, Any]] = []
    seen_regions: set[str] = set()
    for receipt in raw:
        if not isinstance(receipt, Mapping):
            raise TimelineSpliceError(f"region {index} carrier receipt must be an object")
        normalized = dict(receipt)
        receipt_region = str(normalized.get("region_id") or "").strip()
        media_sha = str(normalized.get("media_sha256") or "").lower()
        carrier_sha = str(normalized.get("carrier_sha256") or "").lower()
        if (
            not receipt_region
            or receipt_region in seen_regions
            or re.fullmatch(r"[0-9a-f]{64}", media_sha) is None
            or re.fullmatch(r"[0-9a-f]{64}", carrier_sha) is None
            or media_sha != carrier_sha
        ):
            raise TimelineSpliceError(
                f"region {index} carrier receipt identity or SHA is invalid"
            )
        normalized["region_id"] = receipt_region
        normalized["media_sha256"] = media_sha
        normalized["carrier_sha256"] = carrier_sha
        seen_regions.add(receipt_region)
        result.append(normalized)
    return tuple(result)


def _validate_coverage(
    regions: list[TimelineRegion],
    source_duration: float,
    *,
    tolerance: float = 0.01,
) -> None:
    expected_start = 0.0
    for index, region in enumerate(regions, start=1):
        if abs(region.source_start - expected_start) > tolerance:
            raise TimelineSpliceError(
                f"region {index} does not continuously cover the source timeline"
            )
        expected_start = region.source_end
    if abs(expected_start - source_duration) > tolerance:
        raise TimelineSpliceError("regions do not end at source_duration")


def _omits_source_tail(region: TimelineRegion) -> bool:
    return (
        region.kind == "excluded_app_end_card"
        and region.media_origin == "source_interval"
    )


def _video_duration(info: Any) -> float:
    duration = float(getattr(info, "video_duration", 0.0) or 0.0)
    return duration if duration > 0 else float(getattr(info, "duration", 0.0) or 0.0)


def _replacement_fps(info: Any, *, fallback: float) -> float:
    """Return the decoded replacement-media FPS used for edge-frame audits."""

    raw = getattr(info, "frame_rate", "")
    if isinstance(raw, str) and "/" in raw:
        numerator, denominator = raw.split("/", 1)
        try:
            value = float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            value = 0.0
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
    return value if value > 0 else fallback


def _validate_aspect_ratio(
    region: TimelineRegion,
    info: Any,
    *,
    target_width: int,
    target_height: int,
) -> dict[str, Any]:
    if region.media_origin == "source_interval" or region.kind not in {
        "opaque_ui_demo",
        "excluded_app_end_card",
        "generated_ui_demo",
    }:
        return {
            "mode": "fit_pad",
            "crop_fraction": 0.0,
            "anchor": [0.5, 0.5],
        }
    width = int(
        getattr(info, "display_width", 0) or getattr(info, "width", 0) or 0
    )
    height = int(
        getattr(info, "display_height", 0) or getattr(info, "height", 0) or 0
    )
    if width <= 0 or height <= 0:
        raise TimelineSpliceError("OPAQUE_MEDIA_DIMENSIONS_REQUIRED")
    source_ratio = width / height
    target_ratio = target_width / target_height
    relative_error = abs(source_ratio - target_ratio) / target_ratio
    if region.kind == "generated_ui_demo":
        if relative_error > 0.01:
            raise TimelineSpliceError(
                f"GENERATED_UI_ASPECT_RATIO_MISMATCH: {width}x{height} cannot be "
                f"normalized to {target_width}x{target_height} without changing "
                "the validated UI layout"
            )
        return {
            "mode": "fit_pad",
            "crop_fraction": 0.0,
            "anchor": [0.5, 0.5],
            "input_display_dimensions": [width, height],
        }

    crop_fraction = (
        1.0 - target_ratio / source_ratio
        if source_ratio > target_ratio
        else 1.0 - source_ratio / target_ratio
    )
    crop_fraction = max(0.0, crop_fraction)
    if crop_fraction > 0.12:
        raise TimelineSpliceError(
            f"OPAQUE_ASPECT_RATIO_MISMATCH: {width}x{height} requires "
            f"{crop_fraction:.1%} cover crop to reach "
            f"{target_width}x{target_height}, exceeding the 12% safe limit"
        )
    return {
        "mode": "cover_crop",
        "crop_fraction": round(crop_fraction, 6),
        "anchor": [0.5, 0.5],
        "input_display_dimensions": [width, height],
    }


def _splice_windows(
    placements: list[dict[str, Any]],
) -> tuple[tuple[float, float], ...]:
    windows: list[tuple[float, float]] = []
    for left, right in zip(placements, placements[1:]):
        left_end = float(left["output_end"])
        right_start = float(right["output_start"])
        windows.append((min(left_end, right_start), max(left_end, right_start)))
    return tuple(windows)


def splice_timeline(
    contract: TimelineContract,
    output_path: Path,
    manifest_path: Path,
    *,
    expect_audio: bool = True,
    replacement_duration_tolerance: float = 0.25,
    strict_output_receipts: bool = False,
) -> Path:
    # Retained only for CLI/API compatibility with legacy callers. Supplied UI
    # now preserves its active-content duration, so no duration-match tolerance
    # is applied and no final-frame/audio padding is generated.
    _ = replacement_duration_tolerance
    included = [
        region
        for region in contract.regions
        if region.media_path is not None and not _omits_source_tail(region)
    ]
    if not included:
        raise TimelineSpliceError("timeline has no included media")

    media_by_path: dict[Path, Any] = {}
    active_windows: dict[Path, ActiveWindow] = {}
    for region in included:
        assert region.media_path is not None
        try:
            info = probe_media(region.media_path)
        except ConcatError as exc:
            raise TimelineSpliceError(str(exc)) from exc
        if expect_audio and not info.has_audio and region.audio_policy != "silence_allowed":
            raise TimelineSpliceError(
                f"expected audio stream is missing: {region.media_path}"
            )
        if info.duration <= 0:
            raise TimelineSpliceError(
                f"media duration must be positive: {region.media_path}"
            )
        requires_media_hash = bool(
            strict_output_receipts
            or region.media_sha256
            or region.provider_carrier_receipts
            or region.carrier_receipts
        )
        actual_media_sha = (
            _sha256_file(region.media_path) if requires_media_hash else None
        )
        if region.media_sha256 and actual_media_sha is not None and not hmac.compare_digest(
            actual_media_sha, str(region.media_sha256).lower()
        ):
            raise TimelineSpliceError(
                f"{region.kind} media SHA-256 does not match declared bytes"
            )
        if strict_output_receipts and region.media_origin != "source_interval":
            if region.provider_carrier_receipts:
                receipts = region.provider_carrier_receipts
            else:
                receipts = region.carrier_receipts
            if not receipts:
                raise TimelineSpliceError(
                    f"{region.kind} non-source placement requires an output-bound carrier receipt"
                )
            if region.carrier_receipts:
                for receipt in region.carrier_receipts:
                    if receipt.get("region_id") != region.region_id:
                        raise TimelineSpliceError(
                            "carrier receipt does not match its timeline region"
                        )
                    if receipt.get("media_sha256") != actual_media_sha or receipt.get("carrier_sha256") != actual_media_sha:
                        raise TimelineSpliceError(
                            "carrier receipt does not bind the materialized media bytes"
                        )
        input_video_duration = _video_duration(info)
        if (
            region.kind in {"excluded_app_end_card", "opaque_ui_demo"}
            and region.media_origin != "source_interval"
        ):
            try:
                active_windows[region.media_path] = detect_active_window(
                    region.media_path,
                    duration=input_video_duration,
                    fps=_replacement_fps(info, fallback=float(contract.target_fps)),
                )
            except MediaQualityError as exc:
                raise TimelineSpliceError(str(exc)) from exc
        if (
            region.media_origin == "source_interval"
            and abs(input_video_duration - region.duration)
            > max(2.0 / contract.target_fps, 0.05)
        ):
            raise TimelineSpliceError(
                "SOURCE_INTERVAL_DURATION_MISMATCH: "
                f"decoded slice {input_video_duration:.3f}s does not match "
                f"declared interval {region.duration:.3f}s"
            )
        if region.kind == "generated_ui_demo":
            assert region.ui_qc_report is not None
            actual_sha = _validate_generated_ui_qc(
                region.media_path,
                region.ui_qc_report,
                0,
                ui_truth_card=region.ui_truth_card,
                ui_truth_card_sha256=region.ui_truth_card_sha256,
                ui_render_contract_sha256=region.ui_render_contract_sha256,
                ui_render_contract=region.ui_render_contract,
            )
            if region.media_sha256 and not hmac.compare_digest(
                actual_sha, region.media_sha256
            ):
                raise TimelineSpliceError(
                    "generated_ui_demo media changed after timeline contract validation"
                )
        media_by_path[region.media_path] = info

    first_info = media_by_path[included[0].media_path]
    width = contract.target_width or first_info.display_width or first_info.width
    height = contract.target_height or first_info.display_height or first_info.height
    spatial_plans: dict[int, dict[str, Any]] = {}
    for region in included:
        assert region.media_path is not None
        spatial_plans[id(region)] = _validate_aspect_ratio(
            region,
            media_by_path[region.media_path],
            target_width=width,
            target_height=height,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    placements: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    output_cursor = 0.0
    included_boundaries = [
        _boundary_between(left, right, fps=contract.source_fps)
        for left, right in zip(included, included[1:])
    ]
    effective_input_durations: list[float] = []
    for region in included:
        assert region.media_path is not None
        info = media_by_path[region.media_path]
        if (
            region.kind in {"excluded_app_end_card", "opaque_ui_demo"}
            and region.media_origin != "source_interval"
        ):
            effective_input_durations.append(
                active_windows[region.media_path].active_duration
            )
        elif (
            region.duration_policy == NATURAL_MEDIA_DURATION_POLICY
            or region.media_origin == "source_interval"
        ):
            effective_input_durations.append(_video_duration(info))
        else:
            effective_input_durations.append(region.duration)
    boundaries = [
        _fit_boundary_to_active_frames(
            boundary,
            left_active_frames=max(
                1,
                int(effective_input_durations[index] * contract.target_fps + 1e-6),
            ),
            right_active_frames=max(
                1,
                int(
                    effective_input_durations[index + 1]
                    * contract.target_fps
                    + 1e-6
                ),
            ),
            fps=float(contract.target_fps),
        )
        for index, boundary in enumerate(included_boundaries)
    ]
    uses_transition_renderer = any(
        boundary.type != "hard_cut" or bool(boundary.source_shell_sha256)
        for boundary in boundaries
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        normalized: list[Path] = []
        normalized_durations: list[float] = []
        prepared_regions: list[TimelineRegion] = []
        included_index = 0
        for index, region in enumerate(contract.regions, start=1):
            if region.media_path is None or _omits_source_tail(region):
                if region.kind != "excluded_app_end_card":
                    raise TimelineSpliceError(
                        f"only excluded_app_end_card may be omitted: region {index}"
                    )
                omitted.append(
                    {
                        "region_id": region.region_id,
                        "region_type": region.kind,
                        "source_start": region.source_start,
                        "source_end": region.source_end,
                        "source_duration": region.duration,
                        "source_start_us": region.source_start_us,
                        "source_end_us": region.source_end_us,
                        "output_start": round(output_cursor, 6),
                        "output_end": round(output_cursor, 6),
                        "reason": "tail_video_absent",
                    }
                )
                continue

            info = media_by_path[region.media_path]
            normalized_path = tmp_path / f"region-{index:03d}.mp4"
            boundary_before = (
                boundaries[included_index - 1]
                if included_index > 0
                else None
            )
            boundary_after = (
                boundaries[included_index]
                if included_index < len(boundaries)
                else None
            )
            fade_in = (
                _hard_cut_audio_fade(
                    boundary_before,
                    included[included_index - 1] if included_index > 0 else None,
                    region,
                )
                if not uses_transition_renderer
                else 0.0
            )
            fade_out = (
                _hard_cut_audio_fade(
                    boundary_after,
                    region,
                    included[included_index + 1]
                    if included_index + 1 < len(included)
                    else None,
                )
                if not uses_transition_renderer
                else 0.0
            )
            operations = _normalize_region(
                region,
                _video_duration(info),
                normalized_path,
                width=width,
                height=height,
                fps=contract.target_fps,
                include_audio=expect_audio,
                active_window=active_windows.get(region.media_path),
                input_has_audio=info.has_audio,
                input_video_start=float(getattr(info, "video_start_time", 0.0) or 0.0),
                input_audio_start=float(getattr(info, "audio_start_time", 0.0) or 0.0),
                audio_fade_in=fade_in,
                audio_fade_out=fade_out,
                spatial_plan=spatial_plans[id(region)],
            )
            try:
                normalized_info = probe_media(normalized_path)
            except ConcatError as exc:
                raise TimelineSpliceError(str(exc)) from exc
            if expect_audio and not normalized_info.has_audio:
                raise TimelineSpliceError(
                    f"normalized media is missing audio: {normalized_path}"
                )
            normalized_tolerance = max(2.0 / contract.target_fps, 0.05)
            normalized_video_duration = _video_duration(normalized_info)
            natural_media_duration = (
                region.duration_policy == NATURAL_MEDIA_DURATION_POLICY
            )
            if (
                region.kind not in {"excluded_app_end_card", "opaque_ui_demo"}
                and region.media_origin != "source_interval"
                and not natural_media_duration
                and abs(normalized_video_duration - region.duration)
                > normalized_tolerance
            ):
                raise TimelineSpliceError(
                    f"normalized {region.kind} duration {normalized_video_duration:.3f}s "
                    f"does not match planned {region.duration:.3f}s"
                )
            effective_duration = (
                normalized_video_duration
                if region.kind in {"excluded_app_end_card", "opaque_ui_demo"}
                or region.media_origin == "source_interval"
                or natural_media_duration
                else region.duration
            )
            overlap_before = 0.0
            if prepared_regions:
                boundary = boundary_before
                assert boundary is not None
                if boundary.type != "hard_cut":
                    overlap_before = boundary.duration
            output_start = output_cursor - overlap_before
            output_end = output_start + effective_duration
            normalized.append(normalized_path)
            normalized_durations.append(effective_duration)
            prepared_regions.append(region)
            placement: dict[str, Any] = {
                "region_id": region.region_id,
                "region_type": region.kind,
                "legacy_kind": region.legacy_kind,
                "source_start": region.source_start,
                "source_end": region.source_end,
                "source_duration": region.duration,
                "source_start_us": region.source_start_us,
                "source_end_us": region.source_end_us,
                "media_path": str(region.media_path),
                "media_origin": region.media_origin,
                "assembly_policy": region.assembly_policy,
                "actual_media_duration": round(info.duration, 6),
                "actual_video_duration": round(_video_duration(info), 6),
                "actual_audio_duration": round(float(info.audio_duration or 0.0), 6),
                "input_video_start_time": round(float(info.video_start_time or 0.0), 6),
                "input_audio_start_time": round(float(info.audio_start_time or 0.0), 6),
                "input_relative_av_start_offset": round(
                    float(info.audio_start_time or 0.0)
                    - float(info.video_start_time or 0.0),
                    6,
                ),
                "normalized_residual_av_start_offset": round(
                    max(
                        0.0,
                        float(info.audio_start_time or 0.0)
                        - float(info.video_start_time or 0.0)
                        - (
                            float(active_windows[region.media_path].active_start)
                            if region.media_path in active_windows
                            and region.kind in {"opaque_ui_demo", "excluded_app_end_card"}
                            and region.media_origin != "source_interval"
                            else 0.0
                        ),
                    ),
                    6,
                ),
                "audio_policy": region.audio_policy,
                "encoded_dimensions": [info.width, info.height],
                "display_rotation_deg": int(info.rotation_deg or 0),
                "display_dimensions": [
                    int(info.display_width or info.width),
                    int(info.display_height or info.height),
                ],
                "spatial_normalization": spatial_plans[id(region)],
                "effective_media_duration": round(effective_duration, 6),
                "normalized_media_duration": round(normalized_video_duration, 6),
                "normalized_container_duration": round(normalized_info.duration, 6),
                "output_start": round(output_start, 6),
                "output_end": round(output_end, 6),
                "output_duration": round(effective_duration, 6),
                "duration_policy": (
                    "trim_to_active_content"
                    if region.kind in {"excluded_app_end_card", "opaque_ui_demo"}
                    else region.duration_policy or "match_source_interval"
                ),
                "retimed": region.media_origin != "source_interval"
                and region.kind in {"generated", "generated_ui_demo"}
                and not natural_media_duration
                and abs(info.duration - region.duration) > 0.01,
                "allowed_normalization_operations": list(operations),
                "semantic_analysis_performed": False
                if region.kind in REPLACEMENT_KINDS
                else None,
                "transition_shell": region.transition_shell,
                "transition_shell_applied": _transition_application_manifest(region),
                "tail_append": region.tail_append,
                "planned_transition": region.planned_transition,
            }
            if region.provider_carrier_receipts:
                placement["provider_carrier_receipts"] = [
                    dict(receipt) for receipt in region.provider_carrier_receipts
                ]
            if region.carrier_receipts:
                placement["carrier_receipts"] = [
                    dict(receipt) for receipt in region.carrier_receipts
                ]
            if region.kind == "excluded_app_end_card":
                placement["tail_media_audit"] = active_windows[region.media_path].as_dict()
                placement["final_interval_authority"] = "tail_video"
            if region.kind == "opaque_ui_demo" and region.media_origin != "source_interval":
                placement["ui_media_audit"] = active_windows[
                    region.media_path
                ].as_dict()
                placement["source_to_output_duration_delta"] = round(
                    effective_duration - region.duration, 6
                )
            if natural_media_duration:
                placement["source_to_output_duration_delta"] = round(
                    effective_duration - region.duration,
                    6,
                )
                placement["final_interval_authority"] = "provider_video_stream"
            if region.kind == "generated_ui_demo":
                placement["ui_qc"] = {
                    "status": "passed",
                    "media_sha256": region.media_sha256,
                    "report_sha256": region.ui_qc_report_sha256,
                    "ui_truth_card_sha256": region.ui_truth_card_sha256,
                    "ui_render_contract_sha256": region.ui_render_contract_sha256,
                    "truth_basis": region.ui_qc_report.get("truth_basis"),
                    "truth_source_sha256": region.ui_qc_report.get("truth_source_sha256"),
                    "ocr_match_percent": 100,
                    "layout_match_percent": 100,
                    "ocr_evidence_count": len(
                        region.ui_qc_report.get("ocr_evidence", [])
                    ),
                    "layout_evidence_count": len(
                        region.ui_qc_report.get("layout_evidence", [])
                    ),
                    "state_count": len(
                        region.ui_truth_card.get("states", [])
                        if isinstance(region.ui_truth_card, dict)
                        else []
                    ),
                    "state_evidence_count": len(
                        region.ui_qc_report.get("state_evidence", [])
                    ),
                    "animation_intervals_checked": int(
                        region.ui_qc_report.get("animation_intervals_checked", 0) or 0
                    ),
                    "animation_qc_required": region.ui_qc_report.get(
                        "animation_qc_required"
                    ),
                    "animation_ocr_match_percent": region.ui_qc_report.get(
                        "animation_ocr_match_percent"
                    ),
                    "animation_layout_match_percent": region.ui_qc_report.get(
                        "animation_layout_match_percent"
                    ),
                    "frame_sha256_algorithm": (
                        _UI_FRAME_SHA_ALGORITHM
                        if isinstance(region.ui_truth_card, dict)
                        and "states" in region.ui_truth_card
                        else None
                    ),
                    **{
                        key: True
                        for key in GENERATED_UI_QC_CHECKS
                    },
                }
            placements.append(placement)
            output_cursor = output_end
            included_index += 1

        try:
            transition_receipts: list[dict[str, object]] = []
            if any(boundary.type != "hard_cut" for boundary in boundaries):
                _, rendered_duration, transition_receipts = render_transition_segments(
                    normalized,
                    normalized_durations,
                    boundaries,
                    output_path,
                    expect_audio=expect_audio,
                )
                tolerance = max(2.0 / contract.target_fps, 0.05)
                if abs(rendered_duration - output_cursor) > tolerance:
                    raise TimelineSpliceError(
                        "transition compositor duration differs from timeline mapping"
                    )
                _apply_transition_receipts(
                    placements,
                    prepared_regions,
                    transition_receipts,
                    fps=contract.source_fps,
                )
            else:
                concat_segments(normalized, output_path, expect_audio=expect_audio)
            final_info = probe_media(output_path)
        except ConcatError as exc:
            raise TimelineSpliceError(str(exc)) from exc

    final_duration_tolerance = max(2.0 / contract.target_fps, 0.05)
    final_video_duration = _video_duration(final_info)
    if abs(final_video_duration - output_cursor) > final_duration_tolerance:
        raise TimelineSpliceError(
            f"final duration {final_video_duration:.3f}s differs from planned "
            f"duration {output_cursor:.3f}s"
        )
    final_output_sha256: str | None = None
    if output_path.is_file():
        final_output_sha256 = _sha256_file(output_path)
        for receipt in transition_receipts:
            declared_output_sha256 = str(
                receipt.get("final_output_sha256") or ""
            ).lower()
            if strict_output_receipts and not re.fullmatch(
                r"[0-9a-f]{64}", declared_output_sha256
            ):
                raise TimelineSpliceError(
                    "transition receipt is missing a producer-bound final output SHA-256"
                )
            if declared_output_sha256 and declared_output_sha256 != final_output_sha256:
                raise TimelineSpliceError(
                    "TRANSITION_OUTPUT_SHA256_MISMATCH: transition receipt "
                    "does not bind the current final media bytes"
                )
            if not declared_output_sha256:
                receipt["final_output_sha256"] = final_output_sha256
        for placement in placements:
            all_receipts: list[dict[str, Any]] = []
            for field in ("provider_carrier_receipts", "carrier_receipts"):
                raw_receipts = placement.get(field)
                if isinstance(raw_receipts, list):
                    all_receipts.extend(
                        receipt for receipt in raw_receipts if isinstance(receipt, dict)
                    )
            for receipt in all_receipts:
                if not isinstance(receipt, dict):
                    continue
                declared_output_sha256 = str(
                    receipt.get("final_output_sha256") or ""
                ).lower()
                if (
                    declared_output_sha256
                    and declared_output_sha256 != final_output_sha256
                ):
                    raise TimelineSpliceError(
                        "PROVIDER_CARRIER_OUTPUT_SHA256_MISMATCH: provider carrier "
                        "receipt does not bind the current final media bytes"
                    )
                receipt["final_output_sha256"] = final_output_sha256
    if output_path.is_file():
        try:
            final_media_qc = validate_final_media(
                output_path,
                media_info=final_info,
                fps=float(contract.target_fps),
                splice_windows=_splice_windows(placements),
            )
        except MediaQualityError as exc:
            raise TimelineSpliceError(str(exc)) from exc
    else:
        final_media_qc = {
            "status": "not_run_in_mocked_assembly",
            "reason": "output artifact is not present on the local staging filesystem",
        }
    manifest = {
        "contract": "universal-timeline-regions",
        "contract_version": 2,
        "source_duration": contract.source_duration,
        "source_duration_us": contract.source_duration_us,
        "planned_output_duration": round(output_cursor, 6),
        "actual_output_duration": round(final_video_duration, 6),
        "actual_container_duration": round(final_info.duration, 6),
        "final_output_sha256": final_output_sha256,
        "output_path": str(output_path),
        "target": {"width": width, "height": height, "fps": contract.target_fps},
        "placements": placements,
        "omitted_intervals": omitted,
        "transition_renders": transition_receipts,
        "final_media_qc": final_media_qc,
        "rules": {
            "opaque_semantic_analysis": False,
            "opaque_generation": False,
            "missing_tail_card_behavior": "omit_source_tail",
            "missing_opaque_ui_behavior": "block",
            "source_interval_behavior": "preserve",
            "tail_card_duration_policy": "trim_to_active_content",
            "tail_card_content_retime": False,
            "tail_card_black_filler": False,
            "opaque_ui_time_stretch": False,
            "opaque_ui_duration_policy": "trim_to_active_content",
            "opaque_ui_final_frame_padding": False,
            "generated_ui_qc_required": True,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output_path


def _normalize_region(
    region: TimelineRegion,
    input_duration: float,
    output_path: Path,
    *,
    width: int,
    height: int,
    fps: int,
    include_audio: bool,
    active_window: ActiveWindow | None = None,
    input_has_audio: bool = True,
    input_video_start: float = 0.0,
    input_audio_start: float = 0.0,
    audio_fade_in: float = 0.0,
    audio_fade_out: float = 0.0,
    spatial_plan: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    assert region.media_path is not None
    spatial_plan = spatial_plan or {"mode": "fit_pad", "anchor": [0.5, 0.5]}
    if spatial_plan.get("mode") == "cover_crop":
        anchor = spatial_plan.get("anchor") or [0.5, 0.5]
        try:
            anchor_x, anchor_y = float(anchor[0]), float(anchor[1])
        except (IndexError, TypeError, ValueError) as exc:
            raise TimelineSpliceError("invalid opaque crop anchor") from exc
        if not 0 <= anchor_x <= 1 or not 0 <= anchor_y <= 1:
            raise TimelineSpliceError("opaque crop anchor must be within [0,1]")
        scale = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:(iw-ow)*{anchor_x:.6f}:"
            f"(ih-oh)*{anchor_y:.6f},fps={fps},setsar=1"
        )
    else:
        scale = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1"
        )
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(region.media_path),
    ]
    inject_silence = bool(
        include_audio
        and not input_has_audio
        and region.audio_policy == "silence_allowed"
    )
    if include_audio and not input_has_audio and not inject_silence:
        raise TimelineSpliceError(
            "AUDIO_POLICY_CAPABILITY_REQUIRED: replacement media has no audio "
            "and does not declare audio_policy=silence_allowed"
        )
    if inject_silence:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )

    if region.media_origin == "source_interval":
        video_filter = f"{scale},setpts=PTS-STARTPTS"
        audio_filter = (
            f"aresample=48000,atrim=start=0:end={input_duration:.6f},"
            "asetpts=PTS-STARTPTS"
        )
        operations = (
            "scale",
            "spatial_pad",
            "frame_rate",
            "video_pts_reset",
            "video_codec",
            "pixel_format",
            "audio_codec",
            "sample_rate",
            "channel_layout",
            "audio_boundary_trim",
            "audio_pts_reset",
            "container",
        )
        normalized_duration = input_duration
    elif region.kind == "excluded_app_end_card":
        if active_window is None:
            raise TimelineSpliceError("tail media requires active-content audit")
        video_filter = (
            f"{scale},trim=start={active_window.active_start:.6f}:"
            f"end={active_window.active_end:.6f},setpts=PTS-STARTPTS"
        )
        audio_filter = (
            f"atrim=start={active_window.active_start:.6f}:"
            f"end={active_window.active_end:.6f},asetpts=PTS-STARTPTS"
        )
        operations = TAIL_CARD_NORMALIZATION_OPERATIONS
        if inject_silence:
            audio_filter = (
                f"atrim=duration={active_window.active_duration:.6f},"
                "asetpts=PTS-STARTPTS"
            )
            operations = (*operations, "audio_silence_injected")
        normalized_duration = active_window.active_duration
    elif region.kind == "opaque_ui_demo":
        if active_window is None:
            raise TimelineSpliceError("opaque UI media requires active-content audit")
        temporal_video = (
            f"trim=start={active_window.active_start:.6f}:"
            f"end={active_window.active_end:.6f},setpts=PTS-STARTPTS"
        )
        temporal_audio = (
            f"atrim=start={active_window.active_start:.6f}:"
            f"end={active_window.active_end:.6f},asetpts=PTS-STARTPTS"
        )
        operations = OPAQUE_UI_NORMALIZATION_OPERATIONS
        video_filter = f"{scale},{temporal_video}"
        audio_filter = (
            f"atrim=duration={active_window.active_duration:.6f},"
            "asetpts=PTS-STARTPTS"
            if inject_silence
            else temporal_audio
        )
        if inject_silence:
            operations = (*operations, "audio_silence_injected")
        normalized_duration = active_window.active_duration
    elif region.duration_policy == NATURAL_MEDIA_DURATION_POLICY:
        video_filter = f"{scale},setpts=PTS-STARTPTS"
        audio_filter = (
            f"aresample=48000,atrim=start=0:end={input_duration:.6f},"
            "asetpts=PTS-STARTPTS"
        )
        operations = (
            "scale",
            "spatial_pad",
            "frame_rate",
            "video_pts_reset",
            "video_codec",
            "pixel_format",
            "audio_codec",
            "sample_rate",
            "channel_layout",
            "audio_boundary_trim",
            "audio_pts_reset",
            "container",
        )
        normalized_duration = input_duration
    else:
        video_factor = region.duration / input_duration
        video_filter = f"{scale},setpts={video_factor:.12f}*PTS"
        audio_filter = _atempo_filter(input_duration / region.duration)
        operations = (
            "scale",
            "spatial_pad",
            "frame_rate",
            "generated_retime",
            "video_codec",
            "audio_codec",
            "container",
        )
        normalized_duration = region.duration

    # Resetting video and audio independently can silently move a delayed
    # microphone track ahead of the picture. Preserve a positive source
    # offset with an explicit audio delay; an audio track that starts before
    # video cannot be represented safely by this one-input normalizer and
    # fails closed instead of being silently re-timed.
    relative_av_start = float(input_audio_start) - float(input_video_start)
    trim_origin = 0.0
    if (
        active_window is not None
        and region.kind in {"opaque_ui_demo", "excluded_app_end_card"}
        and region.media_origin != "source_interval"
    ):
        trim_origin = max(0.0, float(active_window.active_start))
    residual_av_start = (
        max(0.0, relative_av_start - trim_origin)
        if trim_origin > 0
        else relative_av_start
    )
    # Codec/container timestamp jitter commonly sits below two frames; retain
    # larger offsets as real A/V alignment evidence instead of shifting them
    # away during normalization.
    offset_tolerance = max(2.0 / max(float(fps), 1.0), 0.05)
    if include_audio and input_has_audio and abs(residual_av_start) > offset_tolerance:
        if residual_av_start < 0:
            raise TimelineSpliceError(
                "AUDIO_VIDEO_START_OFFSET_UNSUPPORTED: audio starts before video"
            )
        audio_filter = (
            f"{audio_filter},adelay={residual_av_start * 1000.0:.3f}:all=1"
            if audio_filter
            else f"adelay={residual_av_start * 1000.0:.3f}:all=1"
        )
        operations = (*operations, "audio_start_offset_preserved")

    if include_audio and (audio_fade_in > 0 or audio_fade_out > 0):
        fade_filters: list[str] = []
        if audio_fade_in > 0:
            fade_filters.append(
                f"afade=t=in:st=0:d={audio_fade_in:.6f}"
            )
        if audio_fade_out > 0:
            fade_start = max(0.0, normalized_duration - audio_fade_out)
            fade_filters.append(
                f"afade=t=out:st={fade_start:.6f}:d={audio_fade_out:.6f}"
            )
        audio_filter = ",".join(
            [part for part in (audio_filter, *fade_filters) if part]
        )
        operations = tuple((*operations, "audio_boundary_fade"))

    command.extend(
        [
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    command.extend(["-map", "0:v:0"])
    if include_audio:
        command.extend(["-map", "1:a:0" if inject_silence else "0:a:0"])
    if (
        region.kind in {"generated", "generated_ui_demo"}
        and region.duration_policy != NATURAL_MEDIA_DURATION_POLICY
    ) or region.media_origin == "source_interval":
        command.extend(["-t", f"{region.duration:.6f}"])
    elif inject_silence:
        command.extend(["-t", f"{normalized_duration:.6f}"])
    if include_audio:
        if audio_filter:
            command.extend(["-af", audio_filter])
        command.extend(["-c:a", "aac", "-ar", "48000", "-ac", "2"])
    else:
        command.append("-an")
    command.append(str(output_path))
    result = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise TimelineSpliceError(
            f"ffmpeg failed for {region.media_path}: {result.stderr.strip()}"
        )
    return tuple(operations)


def _atempo_filter(speed: float) -> str:
    if speed <= 0:
        raise TimelineSpliceError("audio speed must be positive")
    factors: list[float] = []
    while speed > 2.0:
        factors.append(2.0)
        speed /= 2.0
    while speed < 0.5:
        factors.append(0.5)
        speed /= 0.5
    factors.append(speed)
    return ",".join(f"atempo={factor:.12f}" for factor in factors)


def _boundary_between(
    left: TimelineRegion,
    right: TimelineRegion,
    *,
    fps: float,
) -> TransitionBoundary:
    left_spec = None if not left.transition_shell else left.transition_shell.get("exit")
    right_spec = None if not right.transition_shell else right.transition_shell.get("entry")
    if left_spec and right_spec and left_spec != right_spec:
        raise TimelineSpliceError("conflicting transition shells at region boundary")
    spec = right_spec or left_spec
    if spec is None:
        return TransitionBoundary(type="hard_cut", duration=0.0)
    if isinstance(spec, str):
        transition_type = spec
        values: dict[str, Any] = {"type": spec}
    elif isinstance(spec, dict):
        transition_type = str(spec.get("type") or "")
        values = dict(spec)
    else:
        raise TimelineSpliceError("transition shell phase must be an object")
    if transition_type not in SUPPORTED_TRANSITION_TYPES:
        raise TimelineSpliceError(
            f"unsupported transition shell type: {transition_type}"
        )
    unsupported_fields = sorted(
        set(values)
        & {
            "mask",
            "mask_keyframes",
            "opacity_keyframes",
            "geometry_keyframes",
            "trajectory_keyframes",
            "clip_path",
            "custom_expression",
        }
    )
    easing = str(values.get("easing") or "linear").strip().lower()
    if easing not in {"linear", "none"}:
        unsupported_fields.append("easing")
    if unsupported_fields:
        raise TimelineSpliceError(
            "TRANSITION_BACKEND_CAPABILITY_REQUIRED: FFmpeg xfade cannot "
            "faithfully consume " + ", ".join(sorted(set(unsupported_fields)))
        )
    left_audio = None if not left.transition_shell else left.transition_shell.get("audio")
    right_audio = None if not right.transition_shell else right.transition_shell.get("audio")
    if left_audio and right_audio and left_audio != right_audio:
        raise TimelineSpliceError("conflicting transition audio shells at region boundary")
    audio_spec = right_audio or left_audio
    audio_policy, audio_fade_duration = _transition_audio_policy(audio_spec)
    left_z = None if not left.transition_shell else left.transition_shell.get("z_order")
    right_z = None if not right.transition_shell else right.transition_shell.get("z_order")
    if left_z and right_z and left_z != right_z:
        raise TimelineSpliceError("conflicting transition z-order shells at region boundary")
    source_shell = {
        "visual": values,
        "audio": audio_spec,
        "z_order": right_z or left_z,
    }
    source_shell_sha256 = hashlib.sha256(
        json.dumps(
            source_shell,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    duration = (
        0.0
        if transition_type == "hard_cut"
        else _transition_duration(values, fps=fps)
    )
    return TransitionBoundary(
        type=transition_type,
        duration=duration,
        source_shell_sha256=source_shell_sha256,
        audio_policy=audio_policy,
        audio_fade_duration=audio_fade_duration,
        requested_frames=(
            int(values["duration_frames"])
            if values.get("duration_frames") is not None
            else None
        ),
    )


def _fit_boundary_to_active_frames(
    boundary: TransitionBoundary,
    *,
    left_active_frames: int,
    right_active_frames: int,
    fps: float,
) -> TransitionBoundary:
    if boundary.type == "hard_cut":
        return boundary
    requested = max(1, round(boundary.duration * fps))
    available = min(
        max(left_active_frames - 1, 0),
        max(right_active_frames - 1, 0),
    )
    if available < 1:
        raise TimelineSpliceError(
            "transition shell has no real active-frame overlap"
        )
    if boundary.duration <= available / fps + 1e-9:
        return replace(
            boundary,
            requested_duration=boundary.duration,
            duration_adjusted=False,
        )
    duration_frames = min(requested, available)
    duration = duration_frames / fps
    return replace(
        boundary,
        duration=duration,
        requested_duration=boundary.duration,
        duration_adjusted=duration_frames != requested,
    )


def _transition_audio_policy(raw: Any) -> tuple[str, float]:
    if raw is None:
        return "source_equivalent", 0.03
    if isinstance(raw, str):
        policy = raw
        fade_duration = 0.03
    elif isinstance(raw, dict):
        policy = str(raw.get("policy") or raw.get("boundary") or "source_equivalent")
        try:
            fade_duration = float(raw.get("fade_seconds", 0.03))
        except (TypeError, ValueError) as exc:
            raise TimelineSpliceError(
                "transition audio fade_seconds must be numeric"
            ) from exc
    else:
        raise TimelineSpliceError("transition audio shell must be an object or string")
    normalized = policy.strip().lower().replace("-", "_")
    aliases = {
        "source_equivalent": "source_equivalent",
        "crossfade": "crossfade",
        "anti_pop_fade": "anti_pop_fade",
        "preserve": "preserve",
        "hard_cut_preserve": "hard_cut_preserve",
    }
    if normalized not in aliases:
        raise TimelineSpliceError(f"unsupported transition audio policy: {policy}")
    if fade_duration <= 0 or fade_duration > 0.25:
        raise TimelineSpliceError(
            "transition audio fade_seconds must be within (0, 0.25]"
        )
    return aliases[normalized], fade_duration


def _hard_cut_audio_fade(
    boundary: TransitionBoundary | None,
    left: TimelineRegion | None = None,
    right: TimelineRegion | None = None,
) -> float:
    if boundary is None or boundary.type != "hard_cut":
        return 0.0
    if (
        left is not None
        and right is not None
        and left.media_origin == "source_interval"
        and right.media_origin == "source_interval"
    ):
        return 0.0
    if boundary.audio_policy in {"preserve", "hard_cut_preserve"}:
        return 0.0
    return boundary.audio_fade_duration


def _transition_duration(spec: dict[str, Any], *, fps: float) -> float:
    raw_seconds = spec.get("duration_seconds")
    if raw_seconds is not None:
        duration = float(raw_seconds)
    elif spec.get("duration_frames") is not None:
        duration = float(spec["duration_frames"]) / fps
    elif spec.get("start_frame") is not None and spec.get("end_frame") is not None:
        duration = abs(float(spec["end_frame"]) - float(spec["start_frame"])) / fps
    else:
        duration = 0.2
    if duration <= 0:
        raise TimelineSpliceError("non-hard transition duration must be positive")
    return duration


def _apply_transition_receipts(
    placements: list[dict[str, Any]],
    regions: list[TimelineRegion],
    receipts: list[dict[str, object]],
    *,
    fps: float = 30.0,
) -> None:
    seen_boundaries: set[int] = set()
    for receipt in receipts:
        try:
            boundary_index = int(receipt["boundary_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TimelineSpliceError(
                "TRANSITION_RECEIPT_BOUNDARY_INVALID"
            ) from exc
        if boundary_index < 0 or boundary_index + 1 >= len(regions):
            raise TimelineSpliceError("TRANSITION_RECEIPT_BOUNDARY_INVALID")
        if boundary_index in seen_boundaries:
            raise TimelineSpliceError("TRANSITION_RECEIPT_BOUNDARY_DUPLICATE")
        seen_boundaries.add(boundary_index)
        left = regions[boundary_index]
        right = regions[boundary_index + 1]

        # A transition flag is not evidence that the source shell was
        # actually used.  Recompute the canonical shell digest at assembly
        # time and require the compositor receipt to bind the exact bytes.
        # This catches stale/mis-associated UI or tail joins before delivery.
        expected_boundary = _boundary_between(left, right, fps=fps)
        expected_shell_sha = expected_boundary.source_shell_sha256
        # A shell-less hard cut is the default boundary, not a source-shell
        # transition.  The compositor emits a non-rendered receipt for it in
        # a mixed transition graph, but there are no source-shell bytes to
        # hash or bind.  Any real transition (and any hard cut that carries
        # an explicit shell, such as an audio policy) must still bind the
        # exact source-shell digest.
        if expected_boundary.type == "hard_cut" and not expected_shell_sha:
            # Keep the persisted manifest honest: this receipt proves the
            # output-clock cut, not application of a source shell.
            receipt.pop("source_shell_sha256", None)
        else:
            actual_shell_sha = str(receipt.get("source_shell_sha256") or "")
            if not actual_shell_sha or not hmac.compare_digest(
                actual_shell_sha, expected_shell_sha
            ):
                raise TimelineSpliceError(
                    "TRANSITION_RECEIPT_SOURCE_SHELL_MISMATCH"
                )

        rendered = receipt.get("rendered") is True
        if expected_boundary.type != "hard_cut" and not rendered:
            raise TimelineSpliceError("TRANSITION_RECEIPT_NOT_RENDERED")
        if not rendered:
            # Hard cuts are represented by a non-rendered receipt; explicit
            # source-shell cuts carry the digest above, while ordinary cuts
            # intentionally carry no source-shell field.
            continue
        receipt["owner"] = "source_compositor"
        left_exit = None if not left.transition_shell else left.transition_shell.get("exit")
        right_entry = None if not right.transition_shell else right.transition_shell.get("entry")
        if left_exit:
            applied = placements[boundary_index].setdefault(
                "transition_shell_applied", {}
            )
            if isinstance(applied, dict):
                applied["exit"] = True
        if right_entry:
            applied = placements[boundary_index + 1].setdefault(
                "transition_shell_applied", {}
            )
            if isinstance(applied, dict):
                applied["entry"] = True
    for boundary_index, (left, right) in enumerate(zip(regions, regions[1:])):
        boundary = _boundary_between(left, right, fps=fps)
        if (
            boundary.type != "hard_cut" or boundary.source_shell_sha256
        ) and boundary_index not in seen_boundaries:
            raise TimelineSpliceError(
                "TRANSITION_RECEIPT_MISSING: declared source transition shell has no receipt"
            )


def _parse_fps(raw: Any, *, fallback: float) -> float:
    if raw is None:
        return fallback
    if isinstance(raw, dict):
        try:
            numerator = float(raw.get("num"))
            denominator = float(raw.get("den") or 1)
        except (TypeError, ValueError) as exc:
            raise TimelineSpliceError("source_fps must be numeric") from exc
        if numerator <= 0 or denominator <= 0:
            raise TimelineSpliceError("source_fps must be positive")
        return numerator / denominator
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise TimelineSpliceError("source_fps must be numeric") from exc
    if value <= 0:
        raise TimelineSpliceError("source_fps must be positive")
    return value


def _positive_int(value: Any, field: str) -> int:
    parsed = _nonnegative_int(value, field)
    if parsed <= 0:
        raise TimelineSpliceError(f"{field} must be positive")
    return parsed


def _nonnegative_int(value: Any, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TimelineSpliceError(f"{field} must be an integer") from exc
    if parsed < 0:
        raise TimelineSpliceError(f"{field} must be non-negative")
    return parsed


def _resolve_optional_path(base_dir: Path, raw_path: Any) -> Path | None:
    if raw_path in (None, ""):
        return None
    path = Path(str(raw_path))
    return path if path.is_absolute() else base_dir / path


def _transition_shell_lookup(raw: Any) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise TimelineSpliceError("transition_shells must be a list")
    lookup: dict[str, dict[str, Any]] = {}
    for index, shell in enumerate(raw, start=1):
        if not isinstance(shell, dict) or not shell.get("shell_id"):
            raise TimelineSpliceError(
                f"transition_shells entry {index} requires shell_id"
            )
        shell_id = str(shell["shell_id"])
        if shell_id in lookup:
            raise TimelineSpliceError(f"duplicate transition_shell ID: {shell_id}")
        lookup[shell_id] = dict(shell)
    return lookup


def _resolve_transition_shell(
    item: dict[str, Any],
    lookup: dict[str, dict[str, Any]],
    index: int,
) -> dict[str, Any] | None:
    raw = item.get("transition_shell")
    if raw is None:
        shell: dict[str, Any] = {}
    elif isinstance(raw, dict):
        shell = dict(raw)
    else:
        raise TimelineSpliceError(
            f"region {index} transition_shell must be an object"
        )

    if "entry" not in shell and "in" in shell:
        shell["entry"] = shell["in"]
    if "exit" not in shell and "out" in shell:
        shell["exit"] = shell["out"]

    for field, phase in (("transition_in", "entry"), ("transition_out", "exit")):
        shell_id = item.get(field)
        if shell_id is not None:
            resolved = lookup.get(str(shell_id))
            if resolved is None:
                raise TimelineSpliceError(
                    f"region {index} references unknown {field}: {shell_id}"
                )
            if phase in shell and shell[phase] != resolved:
                raise TimelineSpliceError(
                    f"region {index} has conflicting inline and referenced {phase} transition_shell"
                )
            shell.setdefault(phase, resolved)
    return shell or None


def _require_transition_phase(
    shell: dict[str, Any] | None,
    phase: str,
    index: int,
    applied: Any,
) -> None:
    spec = None if shell is None else shell.get(phase)
    if spec is None:
        raise TimelineSpliceError(
            f"region {index} transition_shell {phase} is required"
        )
    if isinstance(spec, str):
        spec = {"type": spec}
        assert shell is not None
        shell[phase] = spec
    if not isinstance(spec, dict):
        raise TimelineSpliceError(
            f"region {index} transition_shell {phase} must be an object"
        )
    transition_type = str(spec.get("type") or "")
    if transition_type not in SUPPORTED_TRANSITION_TYPES:
        raise TimelineSpliceError(
            f"region {index} has unsupported transition_shell type: {transition_type}"
        )
    # Non-hard transitions are rendered by the canonical compositor. Input
    # manifests may describe the source shell, but they cannot self-assert that
    # pixels were already rendered.


def _phase_applied(applied: Any, phase: str, spec: dict[str, Any]) -> bool:
    if isinstance(applied, bool):
        return applied
    if isinstance(applied, dict):
        aliases = (phase, "in" if phase == "entry" else "out")
        return any(applied.get(alias) is True for alias in aliases)
    return spec.get("applied") is True


def _transition_application_manifest(region: TimelineRegion) -> dict[str, bool] | None:
    if not region.transition_shell:
        return None
    result: dict[str, bool] = {}
    for phase in ("entry", "exit"):
        spec = region.transition_shell.get(phase)
        if isinstance(spec, dict):
            result[phase] = str(spec.get("type") or "") == "hard_cut"
    return result or None


def _load_contract_mapping(
    value: Any,
    base_dir: Path,
    field: str,
) -> tuple[dict[str, Any], str]:
    """Load a top-level immutable JSON contract and bind its bytes."""

    if value is None:
        raise TimelineSpliceError(f"{field} is required")
    if isinstance(value, dict):
        if not value:
            raise TimelineSpliceError(f"{field} must be non-empty")
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return dict(value), hashlib.sha256(raw).hexdigest()
    evidence_path = _resolve_optional_path(base_dir, value)
    if evidence_path is None or not evidence_path.is_file():
        raise TimelineSpliceError(f"{field} requires readable JSON")
    raw = evidence_path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TimelineSpliceError(f"{field} is invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise TimelineSpliceError(f"{field} must be a non-empty JSON object")
    return parsed, hashlib.sha256(raw).hexdigest()


def _promote_region_overlay_contracts(
    data: dict[str, Any],
    raw_regions: list[Any],
) -> None:
    """Rehydrate contracts compacted into durable per-region metadata.

    Production persistence stores timeline rows individually.  The Stage-4
    bridge places the immutable source contract on the first carrier row so a
    later worker can export ``analysis/timeline_regions.json`` without losing
    overlay evidence.  Top-level declarations remain authoritative when
    present; embedded rows are only a lossless fallback and must agree.
    """

    embedded_contracts: list[dict[str, Any]] = []
    embedded_mappings: list[dict[str, Any]] = []
    for item in raw_regions:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else item
        contract = metadata.get("source_overlay_contract")
        if isinstance(contract, dict):
            expected = str(metadata.get("source_overlay_contract_sha256") or "").lower()
            actual = _canonical_sha256(contract)
            if expected and expected != actual:
                raise TimelineSpliceError(
                    "OVERLAY_CONTRACT_INVALID: embedded source_overlay_contract SHA does not match"
                )
            embedded_contracts.append(contract)
        mapping = metadata.get("overlay_render_mapping")
        if isinstance(mapping, dict):
            embedded_mappings.append(mapping)

    if data.get("source_overlay_contract") is None and embedded_contracts:
        first = embedded_contracts[0]
        first_digest = _canonical_sha256(first)
        if any(_canonical_sha256(item) != first_digest for item in embedded_contracts[1:]):
            raise TimelineSpliceError(
                "OVERLAY_CONTRACT_MISMATCH: embedded source_overlay_contract rows disagree"
            )
        data["source_overlay_contract"] = first
    elif data.get("source_overlay_contract") is not None and embedded_contracts:
        top_digest = _canonical_sha256(data["source_overlay_contract"])
        if any(_canonical_sha256(item) != top_digest for item in embedded_contracts):
            raise TimelineSpliceError(
                "OVERLAY_CONTRACT_MISMATCH: top-level and embedded source_overlay_contract disagree"
            )

    if data.get("overlay_render_mapping") is None and embedded_mappings:
        first = embedded_mappings[0]
        first_digest = _canonical_sha256(first)
        if any(_canonical_sha256(item) != first_digest for item in embedded_mappings[1:]):
            raise TimelineSpliceError(
                "OVERLAY_RENDER_MAPPING_INVALID: embedded overlay_render_mapping rows disagree"
            )
        data["overlay_render_mapping"] = first
    elif data.get("overlay_render_mapping") is not None and embedded_mappings:
        top_digest = _canonical_sha256(data["overlay_render_mapping"])
        if any(_canonical_sha256(item) != top_digest for item in embedded_mappings):
            raise TimelineSpliceError(
                "OVERLAY_RENDER_MAPPING_INVALID: top-level and embedded overlay_render_mapping disagree"
            )


def _validate_generated_overlay_mapping(
    regions: list[TimelineRegion],
    source_overlay_contract: dict[str, Any],
    mapping: dict[str, Any] | None,
    *,
    source_overlay_contract_sha256: str | None,
) -> None:
    """Block generated output when declared semantic overlays have no carrier.

    The source overlay contract describes source pixels and geometry only.  A
    separate target mapping is required before a generated region can be
    published; this prevents Seedance text/logo omission from silently passing
    through an otherwise valid media splice.
    """

    required_by_region: dict[str, set[str]] = {}
    for cut in source_overlay_contract.get("cuts", []):
        if not isinstance(cut, dict):
            continue
        try:
            cut_start = int(cut.get("start_us"))
            cut_end = int(cut.get("end_us"))
        except (TypeError, ValueError):
            continue
        for overlay in cut.get("source_overlays", []):
            if not isinstance(overlay, dict):
                continue
            overlay_id = str(overlay.get("overlay_id") or "").strip()
            if not overlay_id:
                continue
            for region in regions:
                if region.kind not in {"generated", "generated_ui_demo"}:
                    continue
                if region.source_end_us <= cut_start or region.source_start_us >= cut_end:
                    continue
                region_id = str(region.region_id or "").strip()
                if not region_id:
                    raise TimelineSpliceError(
                        "OVERLAY_RENDER_MAPPING_REQUIRED: generated region with "
                        "semantic overlays requires region_id"
                    )
                required_by_region.setdefault(region_id, set()).add(overlay_id)

    if not required_by_region:
        return
    if mapping is None:
        raise TimelineSpliceError(
            "OVERLAY_RENDER_MAPPING_REQUIRED: source_overlay_contract declares "
            "semantic overlays in a generated region but overlay_render_mapping "
            "is missing"
        )
    if mapping.get("contract") != "target-overlay-render-mapping":
        raise TimelineSpliceError(
            "OVERLAY_RENDER_MAPPING_INVALID: unsupported overlay_render_mapping contract"
        )
    if mapping.get("contract_version") != 1:
        raise TimelineSpliceError(
            "OVERLAY_RENDER_MAPPING_INVALID: unsupported overlay_render_mapping version"
        )
    if not source_overlay_contract_sha256 or str(
        mapping.get("source_overlay_contract_sha256") or ""
    ).lower() != source_overlay_contract_sha256.lower():
        raise TimelineSpliceError(
            "OVERLAY_RENDER_MAPPING_INVALID: source_overlay_contract_sha256 does not match"
        )
    rows = mapping.get("regions")
    if not isinstance(rows, list):
        raise TimelineSpliceError(
            "OVERLAY_RENDER_MAPPING_INVALID: regions must be an array"
        )
    rows_by_region: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TimelineSpliceError(
                "OVERLAY_RENDER_MAPPING_INVALID: region row must be an object"
            )
        region_id = str(row.get("region_id") or "").strip()
        if not region_id or region_id in rows_by_region:
            raise TimelineSpliceError(
                "OVERLAY_RENDER_MAPPING_INVALID: region_id must be unique and non-empty"
            )
        rows_by_region[region_id] = row

    for region_id, required_ids in required_by_region.items():
        row = rows_by_region.get(region_id)
        if row is None:
            raise TimelineSpliceError(
                f"OVERLAY_RENDER_MAPPING_REQUIRED: region {region_id} has no mapping row"
            )
        entries = row.get("overlays")
        if not isinstance(entries, list):
            raise TimelineSpliceError(
                f"OVERLAY_RENDER_MAPPING_INVALID: region {region_id} overlays must be an array"
            )
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise TimelineSpliceError(
                    f"OVERLAY_RENDER_MAPPING_INVALID: region {region_id} overlay row must be an object"
                )
            overlay_id = str(entry.get("overlay_id") or "").strip()
            if not overlay_id or overlay_id in seen:
                raise TimelineSpliceError(
                    f"OVERLAY_RENDER_MAPPING_INVALID: region {region_id} overlay IDs must be unique"
                )
            seen.add(overlay_id)
            if overlay_id not in required_ids:
                raise TimelineSpliceError(
                    f"OVERLAY_RENDER_MAPPING_INVALID: region {region_id} maps undeclared overlay {overlay_id}"
                )
            if entry.get("validated") is not True:
                raise TimelineSpliceError(
                    f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} is not validated"
                )
            render_mode = str(entry.get("render_mode") or "").strip().lower()
            if render_mode not in {"deterministic_text", "deterministic_asset"}:
                raise TimelineSpliceError(
                    f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} has no deterministic render mode"
                )
            payload_sha = str(entry.get("payload_sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", payload_sha):
                raise TimelineSpliceError(
                    f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} payload SHA is invalid"
                )
            if isinstance(entry.get("payload"), dict) and _canonical_sha256(entry["payload"]) != payload_sha:
                raise TimelineSpliceError(
                    f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} payload SHA does not match payload bytes"
                )
            if render_mode == "deterministic_text":
                text_payload = entry.get("text")
                if not str(text_payload or "").strip() and isinstance(entry.get("payload"), dict):
                    text_payload = entry["payload"].get("text")
                if not str(text_payload or "").strip():
                    raise TimelineSpliceError(
                        f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} text payload is empty"
                    )
            elif not re.fullmatch(
                r"[0-9a-f]{64}", str(entry.get("asset_sha256") or "").lower()
            ):
                payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
                if not re.fullmatch(
                    r"[0-9a-f]{64}", str(payload.get("asset_sha256") or "").lower()
                ):
                    raise TimelineSpliceError(
                        f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} asset SHA is invalid"
                    )
        missing = sorted(required_ids - seen)
        if missing:
            raise TimelineSpliceError(
                f"OVERLAY_RENDER_MAPPING_REQUIRED: region {region_id} is missing "
                + ", ".join(missing)
            )


def _validate_overlay_render_receipts_contract(
    data: Mapping[str, Any],
    regions: list[TimelineRegion],
    source_overlay_contract: dict[str, Any] | None,
    mapping: dict[str, Any] | None,
    *,
    source_overlay_contract_sha256: str | None,
    overlay_render_mapping_sha256: str | None,
) -> None:
    """Require output-bound receipts when active timeline assembly opts in."""

    if data.get("overlay_render_receipts_required") is not True:
        return
    if not isinstance(source_overlay_contract, dict) or not isinstance(mapping, dict):
        raise TimelineSpliceError(
            "OVERLAY_RENDER_RECEIPT_REQUIRED: active semantic overlay assembly requires source contract and mapping"
        )
    receipts = data.get("overlay_render_receipts")
    if not isinstance(receipts, list):
        raise TimelineSpliceError(
            "OVERLAY_RENDER_RECEIPT_REQUIRED: overlay_render_receipts must be an array"
        )
    required: dict[tuple[str, str], str] = {}
    for cut in source_overlay_contract.get("cuts", []):
        if not isinstance(cut, dict):
            continue
        try:
            cut_start = int(cut.get("start_us"))
            cut_end = int(cut.get("end_us"))
        except (TypeError, ValueError):
            continue
        for overlay in cut.get("source_overlays", []):
            if not isinstance(overlay, dict):
                continue
            overlay_id = str(overlay.get("overlay_id") or "").strip()
            if not overlay_id:
                continue
            for region in regions:
                if region.kind not in {"generated", "generated_ui_demo"}:
                    continue
                if region.source_end_us <= cut_start or region.source_start_us >= cut_end:
                    continue
                region_id = str(region.region_id or "").strip()
                row = next(
                    (
                        item
                        for item in mapping.get("regions", [])
                        if isinstance(item, dict) and str(item.get("region_id") or "").strip() == region_id
                    ),
                    None,
                )
                if not isinstance(row, dict):
                    continue
                entry = next(
                    (
                        item
                        for item in row.get("overlays", [])
                        if isinstance(item, dict) and str(item.get("overlay_id") or "").strip() == overlay_id
                    ),
                    None,
                )
                if isinstance(entry, dict):
                    required[(region_id, overlay_id)] = str(entry.get("payload_sha256") or "").lower()
    seen: set[tuple[str, str]] = set()
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        key = (str(receipt.get("region_id") or "").strip(), str(receipt.get("overlay_id") or "").strip())
        if key not in required:
            continue
        if str(receipt.get("source_overlay_contract_sha256") or "").lower() != str(source_overlay_contract_sha256 or "").lower():
            continue
        if overlay_render_mapping_sha256 and str(receipt.get("overlay_render_mapping_sha256") or "").lower() != overlay_render_mapping_sha256.lower():
            continue
        if str(receipt.get("payload_sha256") or "").lower() != required[key]:
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("output_sha256") or "").lower()):
            continue
        if not isinstance(receipt.get("frame_windows"), list) or not receipt.get("frame_windows"):
            continue
        seen.add(key)
    missing = sorted(set(required) - seen)
    if missing:
        raise TimelineSpliceError(
            "OVERLAY_RENDER_RECEIPT_REQUIRED: missing output-bound overlay receipts "
            + str(missing)
        )


def _load_json_mapping(
    value: Any,
    base_dir: Path,
    field: str,
    index: int,
) -> tuple[dict[str, Any], str]:
    if value is None:
        raise TimelineSpliceError(
            f"generated_ui_demo region {index} requires {field}"
        )
    if isinstance(value, dict):
        if not value:
            raise TimelineSpliceError(
                f"generated_ui_demo region {index} requires non-empty {field}"
            )
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return dict(value), hashlib.sha256(raw).hexdigest()
    evidence_path = _resolve_optional_path(base_dir, value)
    if evidence_path is None or not evidence_path.is_file():
        raise TimelineSpliceError(
            f"generated_ui_demo region {index} requires readable {field}"
        )
    raw = evidence_path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TimelineSpliceError(
            f"generated_ui_demo region {index} has invalid {field}: {exc}"
        ) from exc
    if not isinstance(parsed, dict) or not parsed:
        raise TimelineSpliceError(
            f"generated_ui_demo region {index} requires non-empty {field}"
        )
    return parsed, hashlib.sha256(raw).hexdigest()


_UI_FRAME_SHA_ALGORITHM = "ffmpeg-rawvideo-rgb24-v1"
_UI_FRAME_SHA_CACHE: dict[tuple[str, int, int, int], str] = {}


def _canonical_sha256(value: Any) -> str:
    """Return the stable digest used by UI truth/evidence bindings."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _decode_frame_sha256(media_path: Path, frame_ms: int) -> str:
    """Hash the actual decoded RGB24 frame at ``frame_ms``.

    A container SHA only proves that the uploaded bytes were not changed; it
    cannot prove that a QC row refers to the pixels at the claimed time.  The
    worker therefore performs the same deterministic FFmpeg projection used
    by the evidence producer and binds the row to these decoded bytes.
    """

    if not media_path.is_file():
        raise TimelineSpliceError("generated_ui_demo media file is required for frame evidence")
    stat = media_path.stat()
    cache_key = (str(media_path.resolve()), int(stat.st_size), int(stat.st_mtime_ns), int(frame_ms))
    cached = _UI_FRAME_SHA_CACHE.get(cache_key)
    if cached is not None:
        return cached
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(media_path),
            "-ss",
            f"{frame_ms / 1000.0:.6f}",
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-400:]
        raise TimelineSpliceError(
            f"generated_ui_demo decoded frame evidence unavailable at {frame_ms}ms"
            + (f": {detail}" if detail else "")
        )
    digest = hashlib.sha256(result.stdout).hexdigest()
    if len(_UI_FRAME_SHA_CACHE) >= 4096:
        _UI_FRAME_SHA_CACHE.clear()
    _UI_FRAME_SHA_CACHE[cache_key] = digest
    return digest


def _normalise_ui_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200b", "").split()).casefold()


def _ui_layout_projection(
    records: Any,
    *,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    result: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        projected: dict[str, Any] = {}
        if "element_id" in item:
            projected["element_id"] = str(item.get("element_id") or "")
        if "text" in item:
            projected["text"] = str(item.get("text") or "")
        bbox = item.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                projected["bbox"] = [
                    round(float(bbox[0]) * scale_x, 6),
                    round(float(bbox[1]) * scale_y, 6),
                    round(float(bbox[2]) * scale_x, 6),
                    round(float(bbox[3]) * scale_y, 6),
                ]
            except (TypeError, ValueError):
                projected["bbox"] = list(bbox)
        result.append(projected)
    return result


def _ui_viewport(render_contract: dict[str, Any] | None) -> tuple[float, float] | None:
    if not isinstance(render_contract, dict):
        return None
    raw = render_contract.get("viewport")
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    try:
        width, height = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        raise TimelineSpliceError("generated_ui_demo ui_render_contract viewport must be numeric")
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise TimelineSpliceError("generated_ui_demo ui_render_contract viewport must be positive")
    return width, height


def _ui_rendered_viewport(
    render_contract: dict[str, Any] | None,
    *,
    media_info: Any | None,
) -> tuple[float, float]:
    """Return the pixel coordinate space used by OCR/layout receipts."""

    raw = None if not isinstance(render_contract, dict) else render_contract.get("rendered_viewport")
    if raw is None:
        width = float(
            getattr(media_info, "display_width", 0)
            or getattr(media_info, "width", 0)
            or 0
        )
        height = float(
            getattr(media_info, "display_height", 0)
            or getattr(media_info, "height", 0)
            or 0
        )
        raw = [width, height]
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise TimelineSpliceError(
            "generated_ui_demo ui_render_contract.rendered_viewport must contain two values"
        )
    try:
        width, height = float(raw[0]), float(raw[1])
    except (TypeError, ValueError) as exc:
        raise TimelineSpliceError(
            "generated_ui_demo ui_render_contract.rendered_viewport must be numeric"
        ) from exc
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise TimelineSpliceError(
            "generated_ui_demo ui_render_contract.rendered_viewport must be positive"
        )
    media_width = float(
        getattr(media_info, "display_width", 0)
        or getattr(media_info, "width", 0)
        or 0
    )
    media_height = float(
        getattr(media_info, "display_height", 0)
        or getattr(media_info, "height", 0)
        or 0
    )
    if media_width > 0 and media_height > 0:
        if abs(width - media_width) > 1.0 or abs(height - media_height) > 1.0:
            raise TimelineSpliceError(
                "generated_ui_demo rendered_viewport does not match decoded UI video dimensions"
            )
    return width, height


def _validate_ui_text_literal(value: Any, field: str) -> None:
    text = str(value)
    if "\ufffd" in text or any(unicodedata.category(char) in {"Cc", "Cs"} for char in text):
        raise TimelineSpliceError(f"{field} contains replacement/control text")


def _validate_ui_layout_item(
    item: dict[str, Any],
    field: str,
    *,
    viewport: tuple[float, float] | None,
) -> None:
    bbox = item.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise TimelineSpliceError(f"{field}.bbox must contain four coordinates")
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox]
    except (TypeError, ValueError) as exc:
        raise TimelineSpliceError(f"{field}.bbox must be numeric") from exc
    if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
        raise TimelineSpliceError(f"{field}.bbox contains non-finite geometry")
    if not (x1 < x2 and y1 < y2):
        raise TimelineSpliceError(f"{field}.bbox must have positive area")
    if viewport is not None:
        width, height = viewport
        if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
            raise TimelineSpliceError(f"{field}.bbox lies outside the UI viewport")
    if "text" in item:
        if not isinstance(item.get("text"), str):
            raise TimelineSpliceError(f"{field}.text must be a string")
        _validate_ui_text_literal(item.get("text"), f"{field}.text")


def _require_bound_ocr_receipt(receipt: dict[str, Any], *, prefix: str) -> None:
    """Reject state rows that only self-report records and a percentage.

    A production OCR receipt must identify the exact request/response and the
    pinned model.  The actual backend call remains deployment-owned; this
    boundary prevents a status-only or anonymous sidecar from entering the
    timeline contract.
    """
    for field in ("request_sha256", "response_sha256", "model_sha256"):
        value = str(receipt.get(field) or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise TimelineSpliceError(f"{prefix} OCR evidence requires bound {field}")
    model_id = str(receipt.get("model_id") or "").strip()
    if not model_id:
        raise TimelineSpliceError(f"{prefix} OCR evidence requires bound model_id")
    schema = receipt.get("schema_version")
    if schema is not None and schema != "usfr-ocr-evidence/v1":
        raise TimelineSpliceError(f"{prefix} OCR evidence schema is unsupported")


def _validate_ui_navigation(
    render_contract: dict[str, Any] | None,
    *,
    state_by_id: dict[str, dict[str, Any]],
    ordered_state_ids: list[str],
    prefix: str,
) -> None:
    if not isinstance(render_contract, dict) or render_contract.get("navigation") is None:
        return
    navigation = render_contract.get("navigation")
    if not isinstance(navigation, list):
        raise TimelineSpliceError(f"{prefix} ui_render_contract.navigation must be an array")
    frame_by_id = {state_id: int(state["frame_ms"]) for state_id, state in state_by_id.items()}
    interactive_roles = {"button", "link", "tab", "input", "control", "cta", "switch", "checkbox"}
    for nav_index, item in enumerate(navigation, start=1):
        if not isinstance(item, dict):
            raise TimelineSpliceError(f"{prefix} navigation[{nav_index}] must be an object")
        from_state = str(item.get("from_state") or "")
        to_state = str(item.get("to_state") or "")
        control_id = str(item.get("control_id") or "")
        action = str(item.get("action") or "").strip().lower()
        if from_state not in state_by_id or to_state not in state_by_id:
            raise TimelineSpliceError(f"{prefix} navigation references an unknown state")
        if not control_id or not action:
            raise TimelineSpliceError(f"{prefix} navigation requires action and control_id")
        at_ms = item.get("at_ms")
        if isinstance(at_ms, bool) or not isinstance(at_ms, int):
            raise TimelineSpliceError(f"{prefix} navigation[{nav_index}].at_ms must be an integer")
        if not min(frame_by_id[from_state], frame_by_id[to_state]) <= at_ms <= max(
            frame_by_id[from_state], frame_by_id[to_state]
        ):
            raise TimelineSpliceError(f"{prefix} navigation[{nav_index}] occurs outside its state window")
        controls = state_by_id[from_state].get("expected_layout", [])
        control = next(
            (item for item in controls if isinstance(item, dict) and str(item.get("element_id") or "") == control_id),
            None,
        )
        if control is None:
            raise TimelineSpliceError(
                f"{prefix} navigation[{nav_index}] control is missing from source state layout"
            )
        role = str(control.get("role") or control.get("type") or "").strip().lower()
        if role not in interactive_roles:
            raise TimelineSpliceError(
                f"{prefix} navigation[{nav_index}] control is not interactive"
            )


def _validate_generated_ui_state_evidence(
    media_path: Path,
    report: dict[str, Any],
    truth: dict[str, Any],
    index: int,
    *,
    ui_render_contract: dict[str, Any] | None = None,
) -> None:
    """Validate multi-state UI evidence against target truth and real pixels.

    This is intentionally additive.  Legacy single-state reports remain
    accepted when no ``states`` array is present; once a truth card declares
    state sequence evidence, every state must have exactly one frame-bound OCR
    and layout receipt and the claimed frame hash must match decoded media.
    """

    prefix = f"generated_ui_demo region {index}"
    algorithm = report.get("frame_sha256_algorithm")
    if algorithm is not None and algorithm != _UI_FRAME_SHA_ALGORITHM:
        raise TimelineSpliceError(
            f"{prefix} ui_qc_report frame_sha256_algorithm is unsupported"
        )
    states = truth.get("states")
    if not isinstance(states, list) or not states:
        raise TimelineSpliceError(f"{prefix} ui_truth_card.states must be a non-empty array")
    state_by_id: dict[str, dict[str, Any]] = {}
    ordered_state_ids: list[str] = []
    previous_frame_ms: int | None = None
    media_info: Any | None = None
    try:
        media_info = probe_media(media_path)
        media_duration_ms = int(round(_video_duration(media_info) * 1000.0))
    except (ConcatError, OSError, ValueError):
        media_duration_ms = None
    viewport = _ui_viewport(ui_render_contract)
    if viewport is None:
        raise TimelineSpliceError(
            f"{prefix} ui_render_contract.viewport is required for multi-state layout validation"
        )
    rendered_viewport = _ui_rendered_viewport(
        ui_render_contract,
        media_info=media_info,
    )
    if media_info is not None:
        media_width = float(
            getattr(media_info, "display_width", 0)
            or getattr(media_info, "width", 0)
            or 0
        )
        media_height = float(
            getattr(media_info, "display_height", 0)
            or getattr(media_info, "height", 0)
            or 0
        )
        if media_width > 0 and media_height > 0:
            viewport_ratio = viewport[0] / viewport[1]
            media_ratio = media_width / media_height
            if abs(viewport_ratio - media_ratio) / media_ratio > 0.01:
                raise TimelineSpliceError(
                    f"{prefix} ui_render_contract viewport aspect does not match decoded UI video"
                )
    for state_index, state in enumerate(states, start=1):
        if not isinstance(state, dict):
            raise TimelineSpliceError(f"{prefix} ui_truth_card.states[{state_index}] must be an object")
        state_id = str(state.get("state_id") or "")
        if not state_id or state_id in state_by_id:
            raise TimelineSpliceError(f"{prefix} ui_truth_card.states has duplicate/empty state_id")
        frame_ms = state.get("frame_ms")
        if isinstance(frame_ms, bool) or not isinstance(frame_ms, int) or frame_ms < 0:
            raise TimelineSpliceError(f"{prefix} ui_truth_card.states[{state_index}] frame_ms is invalid")
        if previous_frame_ms is not None and frame_ms <= previous_frame_ms:
            raise TimelineSpliceError(
                f"{prefix} ui_truth_card.states frame_ms values must be strictly increasing"
            )
        if media_duration_ms is not None and frame_ms >= media_duration_ms:
            raise TimelineSpliceError(
                f"{prefix} ui_truth_card.states[{state_index}] frame_ms is outside the UI media duration"
            )
        previous_frame_ms = frame_ms
        expected_text = state.get("expected_text", [])
        expected_layout = state.get("expected_layout", [])
        if not isinstance(expected_text, list) or any(not isinstance(item, str) for item in expected_text):
            raise TimelineSpliceError(f"{prefix} ui_truth_card.states[{state_index}] expected_text must be a string array")
        if not isinstance(expected_layout, list) or any(not isinstance(item, dict) for item in expected_layout):
            raise TimelineSpliceError(f"{prefix} ui_truth_card.states[{state_index}] expected_layout must be an object array")
        for text_index, text_value in enumerate(expected_text, start=1):
            _validate_ui_text_literal(
                text_value,
                f"{prefix} ui_truth_card.states[{state_index}].expected_text[{text_index}]",
            )
        for layout_index, layout_item in enumerate(expected_layout, start=1):
            _validate_ui_layout_item(
                layout_item,
                f"{prefix} ui_truth_card.states[{state_index}].expected_layout[{layout_index}]",
                viewport=viewport,
            )
        element_ids = [
            str(item.get("element_id") or "")
            for item in expected_layout
            if str(item.get("element_id") or "")
        ]
        if len(element_ids) != len(set(element_ids)):
            raise TimelineSpliceError(
                f"{prefix} ui_truth_card.states[{state_index}] has duplicate element_id values"
            )
        layout_text = [
            _normalise_ui_text(item.get("text"))
            for item in expected_layout
            if _normalise_ui_text(item.get("text"))
        ]
        expected_text_normalised = [
            _normalise_ui_text(text)
            for text in expected_text
            if _normalise_ui_text(text)
        ]
        if layout_text != expected_text_normalised:
            raise TimelineSpliceError(
                f"{prefix} ui_truth_card.states[{state_index}] layout text order does not match expected_text"
            )
        ordered_state_ids.append(state_id)
        state_by_id[state_id] = state

    if not isinstance(ui_render_contract, dict):
        raise TimelineSpliceError(
            f"{prefix} ui_render_contract is required for a multi-state UI"
        )
    raw_sequence = ui_render_contract.get("state_sequence")
    if not isinstance(raw_sequence, list) or any(
        not isinstance(item, str) or not item for item in raw_sequence
    ):
        raise TimelineSpliceError(
            f"{prefix} ui_render_contract.state_sequence must be a non-empty string array"
        )
    if [str(item) for item in raw_sequence] != ordered_state_ids:
        raise TimelineSpliceError(
            f"{prefix} ui_render_contract state_sequence does not match truth state order"
        )
    approved_copy = truth.get("approved_copy")
    if isinstance(approved_copy, list):
        expected_copy = {
            _normalise_ui_text(text)
            for state in states
            for text in state.get("expected_text", [])
            if _normalise_ui_text(text)
        }
        approved_copy_set = {
            _normalise_ui_text(text)
            for text in approved_copy
            if _normalise_ui_text(text)
        }
        if expected_copy != approved_copy_set:
            raise TimelineSpliceError(
                f"{prefix} approved_copy does not cover the exact visible state text set"
            )

    evidence = report.get("state_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise TimelineSpliceError(f"{prefix} ui_qc_report state evidence requires one row per state_id")
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for evidence_index, row in enumerate(evidence, start=1):
        if not isinstance(row, dict):
            raise TimelineSpliceError(f"{prefix} ui_qc_report state evidence[{evidence_index}] must be an object")
        state_id = str(row.get("state_id") or "")
        if not state_id or state_id in evidence_by_id:
            raise TimelineSpliceError(f"{prefix} ui_qc_report state evidence has duplicate/empty state_id")
        evidence_by_id[state_id] = row
    if set(evidence_by_id) != set(state_by_id):
        raise TimelineSpliceError(
            f"{prefix} state evidence state_id set does not match ui_truth_card.states"
        )
    if [str(row.get("state_id") or "") for row in evidence] != ordered_state_ids:
        raise TimelineSpliceError(
            f"{prefix} state evidence order does not match ui_truth_card.states"
        )

    for state_id, state in state_by_id.items():
        row = evidence_by_id[state_id]
        frame_ms = state["frame_ms"]
        if row.get("frame_ms") != frame_ms:
            raise TimelineSpliceError(
                f"{prefix} state evidence {state_id} frame_ms does not match ui_truth_card"
            )
        frame_sha = str(row.get("frame_sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", frame_sha):
            raise TimelineSpliceError(
                f"{prefix} state evidence {state_id} frame_sha256 must be lowercase SHA-256"
            )
        actual_frame_sha = _decode_frame_sha256(media_path, frame_ms)
        if not hmac.compare_digest(actual_frame_sha, frame_sha):
            raise TimelineSpliceError(
                f"{prefix} state evidence {state_id} decoded frame SHA-256 does not match media"
            )
        truth_digest = str(row.get("truth_state_sha256") or "").lower()
        if not hmac.compare_digest(truth_digest, _canonical_sha256(state)):
            raise TimelineSpliceError(
                f"{prefix} state evidence {state_id} truth state digest does not match ui_truth_card"
            )
        for evidence_kind in ("ocr_evidence", "layout_evidence"):
            receipt = row.get(evidence_kind)
            if not isinstance(receipt, dict):
                raise TimelineSpliceError(
                    f"{prefix} state evidence {state_id} requires {evidence_kind}"
                )
            input_sha = str(receipt.get("input_sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", input_sha):
                raise TimelineSpliceError(
                    f"{prefix} state evidence {state_id} {evidence_kind} input SHA must be lowercase SHA-256"
                )
            # OCR/VLM services commonly receive an encoded PNG/JPEG extracted
            # from the video frame, while the timeline truth binds the raw
            # decoded RGB24 pixels.  In that deployment contract both hashes
            # are required: ``decoded_frame_sha256`` proves the frame, and
            # ``input_sha256`` proves the exact bytes sent to the backend.
            # Legacy/test receipts without the second field retain the strict
            # raw-frame binding for compatibility.
            decoded_input_sha = receipt.get("decoded_frame_sha256")
            if decoded_input_sha is None:
                if not hmac.compare_digest(input_sha, actual_frame_sha):
                    raise TimelineSpliceError(
                        f"{prefix} state evidence {state_id} {evidence_kind} input SHA does not match decoded frame"
                    )
            else:
                decoded_input_sha = str(decoded_input_sha).lower()
                if not re.fullmatch(r"[0-9a-f]{64}", decoded_input_sha) or not hmac.compare_digest(
                    decoded_input_sha, actual_frame_sha
                ):
                    raise TimelineSpliceError(
                        f"{prefix} state evidence {state_id} {evidence_kind} decoded frame SHA does not match media"
                    )
            records = receipt.get("records")
            if not isinstance(records, list):
                raise TimelineSpliceError(
                    f"{prefix} state evidence {state_id} {evidence_kind}.records must be an array"
                )
            records_digest = str(receipt.get("records_sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", records_digest) or not hmac.compare_digest(
                records_digest, _canonical_sha256(records)
            ):
                raise TimelineSpliceError(
                    f"{prefix} state evidence {state_id} {evidence_kind} records SHA does not match"
                )
            if row.get("%s_match_percent" % evidence_kind.split("_", 1)[0]) != 100:
                raise TimelineSpliceError(
                    f"{prefix} state evidence {state_id} {evidence_kind} match must be 100"
                )
            if evidence_kind == "ocr_evidence":
                _require_bound_ocr_receipt(
                    receipt,
                    prefix=f"{prefix} state evidence {state_id}",
                )
        expected_text = [_normalise_ui_text(item) for item in state.get("expected_text", [])]
        observed_text = [
            _normalise_ui_text(item.get("text"))
            for item in row["ocr_evidence"]["records"]
            if isinstance(item, dict) and _normalise_ui_text(item.get("text"))
        ]
        if observed_text != expected_text:
            raise TimelineSpliceError(
                f"{prefix} state evidence {state_id} OCR records do not match ui_truth_card"
            )
        expected_layout = _ui_layout_projection(state.get("expected_layout", []))
        observed_layout = _ui_layout_projection(
            row["layout_evidence"]["records"],
            scale_x=viewport[0] / rendered_viewport[0],
            scale_y=viewport[1] / rendered_viewport[1],
        )
        if expected_layout != observed_layout:
            raise TimelineSpliceError(
                f"{prefix} state evidence {state_id} layout records do not match ui_truth_card"
            )

    _validate_ui_navigation(
        ui_render_contract,
        state_by_id=state_by_id,
        ordered_state_ids=ordered_state_ids,
        prefix=prefix,
    )

    # A state-frame receipt proves only the exact declared snapshots.  Active
    # generated-UI reports additionally carry independent OCR/layout receipts
    # for interpolation frames so a renderer cannot hide a replacement glyph
    # or an out-of-viewport geometry excursion between states.
    if report.get("animation_qc_required") is True:
        animation_intervals = report.get("animation_interval_evidence")
        if not isinstance(animation_intervals, list):
            raise TimelineSpliceError(
                f"{prefix} ui_qc_report animation interval evidence is required"
            )
        expected_text = {
            _normalise_ui_text(text)
            for state in states
            for text in state.get("expected_text", [])
            if _normalise_ui_text(text)
        }
        media_width = float(getattr(media_info, "display_width", 0) or getattr(media_info, "width", 0) or 0)
        media_height = float(getattr(media_info, "display_height", 0) or getattr(media_info, "height", 0) or 0)
        if media_width <= 0 or media_height <= 0:
            raise TimelineSpliceError(f"{prefix} animation QC cannot determine rendered viewport")
        for interval_index, interval in enumerate(animation_intervals, start=1):
            if not isinstance(interval, dict):
                raise TimelineSpliceError(
                    f"{prefix} animation interval evidence[{interval_index}] must be an object"
                )
            start_ms = interval.get("start_ms")
            end_ms = interval.get("end_ms")
            if (
                isinstance(start_ms, bool)
                or isinstance(end_ms, bool)
                or not isinstance(start_ms, int)
                or not isinstance(end_ms, int)
                or start_ms < 0
                or end_ms <= start_ms
            ):
                raise TimelineSpliceError(
                    f"{prefix} animation interval evidence[{interval_index}] timing is invalid"
                )
            samples = interval.get("samples")
            if not isinstance(samples, list) or not samples:
                raise TimelineSpliceError(
                    f"{prefix} animation interval evidence[{interval_index}] requires samples"
                )
            for sample_index, sample in enumerate(samples, start=1):
                if not isinstance(sample, dict):
                    raise TimelineSpliceError(
                        f"{prefix} animation sample[{interval_index}:{sample_index}] must be an object"
                    )
                frame_ms = sample.get("frame_ms")
                if (
                    isinstance(frame_ms, bool)
                    or not isinstance(frame_ms, int)
                    or frame_ms <= start_ms
                    or frame_ms >= end_ms
                ):
                    raise TimelineSpliceError(
                        f"{prefix} animation sample[{interval_index}:{sample_index}] frame_ms is outside interval"
                    )
                frame_sha = str(sample.get("decoded_frame_sha256") or sample.get("frame_sha256") or "").lower()
                if not re.fullmatch(r"[0-9a-f]{64}", frame_sha):
                    raise TimelineSpliceError(
                        f"{prefix} animation sample[{interval_index}:{sample_index}] frame SHA must be lowercase SHA-256"
                    )
                actual_frame_sha = _decode_frame_sha256(media_path, frame_ms)
                if not hmac.compare_digest(actual_frame_sha, frame_sha):
                    raise TimelineSpliceError(
                        f"{prefix} animation sample[{interval_index}:{sample_index}] decoded frame SHA does not match media"
                    )
                if sample.get("ocr_match_percent") != 100 or sample.get("layout_match_percent") != 100:
                    raise TimelineSpliceError(
                        f"{prefix} animation sample[{interval_index}:{sample_index}] OCR/layout match must be 100"
                    )
                for evidence_kind in ("ocr_evidence", "layout_evidence"):
                    receipt = sample.get(evidence_kind)
                    if not isinstance(receipt, dict):
                        raise TimelineSpliceError(
                            f"{prefix} animation sample[{interval_index}:{sample_index}] requires {evidence_kind}"
                        )
                    input_sha = str(receipt.get("input_sha256") or "").lower()
                    if not re.fullmatch(r"[0-9a-f]{64}", input_sha):
                        raise TimelineSpliceError(
                            f"{prefix} animation sample[{interval_index}:{sample_index}] {evidence_kind} input SHA is invalid"
                        )
                    decoded_sha = str(receipt.get("decoded_frame_sha256") or frame_sha).lower()
                    if not re.fullmatch(r"[0-9a-f]{64}", decoded_sha) or not hmac.compare_digest(decoded_sha, frame_sha):
                        raise TimelineSpliceError(
                            f"{prefix} animation sample[{interval_index}:{sample_index}] {evidence_kind} decoded frame SHA does not match media"
                        )
                    records = receipt.get("records")
                    records_sha = str(receipt.get("records_sha256") or "").lower()
                    if not isinstance(records, list) or not re.fullmatch(r"[0-9a-f]{64}", records_sha) or not hmac.compare_digest(records_sha, _canonical_sha256(records)):
                        raise TimelineSpliceError(
                            f"{prefix} animation sample[{interval_index}:{sample_index}] {evidence_kind} records SHA does not match"
                        )
                    if evidence_kind == "ocr_evidence":
                        _require_bound_ocr_receipt(
                            receipt,
                            prefix=f"{prefix} animation sample[{interval_index}:{sample_index}]",
                        )
                        observed_text: list[str] = []
                        for record in records:
                            if not isinstance(record, dict):
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] OCR record is malformed"
                                )
                            text = str(record.get("text") or "").strip()
                            if not text or any(char in text for char in ("\ufffd", "\u25a1")):
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] contains garbled/replacement text"
                                )
                            normalized = _normalise_ui_text(text)
                            if expected_text and normalized not in expected_text:
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] OCR text is outside target truth"
                                )
                            observed_text.append(normalized)
                            bbox = record.get("bbox")
                            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] OCR record lacks layout bounds"
                                )
                            try:
                                x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
                            except (TypeError, ValueError):
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] OCR layout bounds are invalid"
                                )
                            if not (0 <= x1 < x2 <= media_width and 0 <= y1 < y2 <= media_height):
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] layout leaves rendered viewport"
                                )
                        if expected_text and not observed_text:
                            raise TimelineSpliceError(
                                f"{prefix} animation sample[{interval_index}:{sample_index}] has no readable OCR text"
                            )
                    else:
                        # Layout receipts are independently hashed and must
                        # describe the same readable, in-viewport elements;
                        # accepting only an OCR receipt would leave a second
                        # self-reported geometry channel.
                        for record in records:
                            if not isinstance(record, dict):
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] layout record is malformed"
                                )
                            text = str(record.get("text") or "").strip()
                            if not text or any(char in text for char in ("\ufffd", "\u25a1")):
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] layout contains garbled/replacement text"
                                )
                            if expected_text and _normalise_ui_text(text) not in expected_text:
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] layout text is outside target truth"
                                )
                            bbox = record.get("bbox")
                            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] layout record lacks bounds"
                                )
                            try:
                                x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
                            except (TypeError, ValueError):
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] layout bounds are invalid"
                                )
                            if not (0 <= x1 < x2 <= media_width and 0 <= y1 < y2 <= media_height):
                                raise TimelineSpliceError(
                                    f"{prefix} animation sample[{interval_index}:{sample_index}] layout leaves rendered viewport"
                                )
        if report.get("animation_ocr_match_percent") != 100 or report.get("animation_layout_match_percent") != 100:
            raise TimelineSpliceError(f"{prefix} animation OCR/layout aggregate must be 100")


def _validate_generated_ui_qc(
    media_path: Path,
    report: dict[str, Any],
    index: int,
    *,
    ui_truth_card: dict[str, Any] | None,
    ui_truth_card_sha256: str | None,
    ui_render_contract_sha256: str | None,
    ui_render_contract: dict[str, Any] | None = None,
) -> str:
    prefix = (
        f"generated_ui_demo region {index}"
        if index > 0
        else "generated_ui_demo region"
    )
    if "passed" not in report and "status" not in report:
        raise TimelineSpliceError(f"{prefix} ui_qc_report requires a passed status")
    if "passed" in report and report.get("passed") is not True:
        raise TimelineSpliceError(f"{prefix} ui_qc_report passed must be true")
    if "status" in report and str(report.get("status") or "").lower() not in {
        "pass",
        "passed",
    }:
        raise TimelineSpliceError(f"{prefix} ui_qc_report status must be passed")
    for check in GENERATED_UI_QC_CHECKS:
        if report.get(check) is not True:
            raise TimelineSpliceError(f"{prefix} ui_qc_report {check} must be true")
    for field, expected_digest in (
        ("ui_truth_card_sha256", ui_truth_card_sha256),
        ("ui_render_contract_sha256", ui_render_contract_sha256),
    ):
        actual_digest = str(report.get(field) or "").lower()
        if (
            expected_digest is None
            or not re.fullmatch(r"[0-9a-f]{64}", actual_digest)
            or not hmac.compare_digest(actual_digest, expected_digest)
        ):
            raise TimelineSpliceError(
                f"{prefix} ui_qc_report {field} does not match validated evidence"
            )
    if report.get("animation_qc_required") is True:
        truth_basis = str(report.get("truth_basis") or "").strip().lower()
        if truth_basis not in {
            "target-owned-upload",
            "user-ui-screenshot",
            "parsed-app-store-evidence",
            "official-app-evidence",
        }:
            raise TimelineSpliceError(
                f"{prefix} ui_qc_report truth_basis must identify screenshot/App evidence"
            )
        truth_source_sha = str(report.get("truth_source_sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", truth_source_sha):
            raise TimelineSpliceError(
                f"{prefix} ui_qc_report truth_source_sha256 must be lowercase SHA-256"
            )
    for field in ("ocr_match_percent", "layout_match_percent"):
        value = report.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 100.0:
            raise TimelineSpliceError(f"{prefix} ui_qc_report {field} must be 100")
    approved_copy = None if ui_truth_card is None else ui_truth_card.get("approved_copy")
    if not isinstance(approved_copy, list) or any(
        not isinstance(item, str) for item in approved_copy
    ):
        raise TimelineSpliceError(
            f"{prefix} ui_truth_card approved_copy must be a string array"
        )
    for copy_index, copy_value in enumerate(approved_copy or [], start=1):
        _validate_ui_text_literal(
            copy_value,
            f"{prefix} ui_truth_card.approved_copy[{copy_index}]",
        )
    if report.get("approved_copy_observed") != approved_copy:
        raise TimelineSpliceError(
            f"{prefix} ui_qc_report approved_copy_observed does not match target truth"
        )
    # High-fidelity generated UI may declare a target state sequence.  In
    # that mode summary percentages and container hashes are insufficient: the
    # state rows must bind to decoded pixels and to the exact truth state.
    if isinstance(ui_truth_card, dict) and "states" in ui_truth_card:
        _validate_generated_ui_state_evidence(
            media_path,
            report,
            ui_truth_card,
            index,
            ui_render_contract=ui_render_contract,
        )
        state_rows = report.get("state_evidence")
        if isinstance(state_rows, list):
            expected_frame_rows = [
                {
                    "frame_ms": row.get("frame_ms"),
                    "sha256": str(row.get("frame_sha256") or "").lower(),
                }
                for row in state_rows
                if isinstance(row, dict)
            ]
            for field in ("ocr_evidence", "layout_evidence"):
                if report.get(field) != expected_frame_rows:
                    raise TimelineSpliceError(
                        f"{prefix} ui_qc_report {field} must be the exact projection of state evidence"
                    )
    for field in ("ocr_evidence", "layout_evidence"):
        evidence = report.get(field)
        if not isinstance(evidence, list) or not evidence:
            raise TimelineSpliceError(
                f"{prefix} ui_qc_report {field} requires frame evidence"
            )
        for evidence_index, item in enumerate(evidence, start=1):
            if not isinstance(item, dict):
                raise TimelineSpliceError(
                    f"{prefix} ui_qc_report {field}[{evidence_index}] must be an object"
                )
            frame_ms = item.get("frame_ms")
            sha256 = str(item.get("sha256") or "").lower()
            if (
                isinstance(frame_ms, bool)
                or not isinstance(frame_ms, int)
                or frame_ms < 0
                or not re.fullmatch(r"[0-9a-f]{64}", sha256)
            ):
                raise TimelineSpliceError(
                    f"{prefix} ui_qc_report {field}[{evidence_index}] is invalid"
                )
    expected = str(report.get("media_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise TimelineSpliceError(
            f"{prefix} ui_qc_report media_sha256 must be lowercase SHA-256"
        )
    if not media_path.is_file():
        raise TimelineSpliceError(f"{prefix} media file is required for UI QC")
    actual = _sha256_file(media_path)
    if not hmac.compare_digest(actual, expected):
        raise TimelineSpliceError(
            f"{prefix} media SHA-256 does not match ui_qc_report"
        )
    return actual


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Splice generated regions, supplied opaque UI, and optional App "
            "tail-card media under the canonical timeline-region contract."
        )
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--no-audio-expected", action="store_true")
    parser.add_argument("--replacement-duration-tolerance", type=float, default=0.25)
    args = parser.parse_args()

    contract = load_contract(args.contract)
    splice_timeline(
        contract,
        args.output,
        args.manifest,
        expect_audio=not args.no_audio_expected,
        replacement_duration_tolerance=args.replacement_duration_tolerance,
    )
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
