"""Deterministic conversion from source overlay evidence to render mapping.

The dynamics pass owns the source overlay contract.  This module only binds a
target-owned text or asset payload to the exact source overlay and generated
timeline region that it overlaps.  Geometry and timing are copied verbatim;
the builder never invents a source overlay or silently turns a brand mark into
text.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TEXT_KINDS = {
    "wordmark",
    "readable_wordmark",
    "subtitle",
    "selling_point",
    "selling_point_text",
    "cta",
    "cta_text",
}
_ASSET_KINDS = {"brand_mark", "logo", "graphic", "ui", "other"}
_TEXT_STYLE_KEYS = ("color", "font_size", "fontfile", "align", "bordercolor", "borderw")
_ASSET_STYLE_KEYS = ("fit", "opacity", "blend", "premultiplied")
_OUTPUT_LANGUAGES = {"en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"}
_MOJIBAKE_MARKERS = ("\ufffd", "Ã", "Â", "â€", "绔嬪嵆", "涓嬭浇")


class OverlayMappingError(ValueError):
    """The target replacement cannot be bound without changing source truth."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256(value: Any) -> str:
    return canonical_sha256(value)


def _as_us(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OverlayMappingError(f"{field} must be an integer microsecond timestamp")
    return value


def _source_index(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if contract.get("contract") != "source-ui-overlay-motion" or contract.get("contract_version") != 1:
        raise OverlayMappingError("source overlay contract must be source-ui-overlay-motion/v1")
    cuts = contract.get("cuts")
    if not isinstance(cuts, list) or not cuts:
        raise OverlayMappingError("source overlay contract cuts are required")
    result: dict[str, dict[str, Any]] = {}
    for cut_index, cut in enumerate(cuts, start=1):
        if not isinstance(cut, Mapping):
            raise OverlayMappingError(f"source overlay Cut {cut_index} must be an object")
        overlays = cut.get("source_overlays")
        if not isinstance(overlays, list):
            raise OverlayMappingError(f"source overlay Cut {cut_index} source_overlays must be an array")
        for overlay in overlays:
            if not isinstance(overlay, Mapping):
                raise OverlayMappingError("source overlay entry must be an object")
            overlay_id = str(overlay.get("overlay_id") or "").strip()
            if not overlay_id:
                raise OverlayMappingError("source overlay IDs must be non-empty")
            start = _as_us(overlay.get("start_us"), f"{overlay_id}.start_us")
            end = _as_us(overlay.get("end_us"), f"{overlay_id}.end_us")
            if end <= start:
                raise OverlayMappingError(f"{overlay_id} has an invalid source window")
            kind = str(overlay.get("kind") or "other").strip().lower()
            if kind not in _TEXT_KINDS | _ASSET_KINDS:
                raise OverlayMappingError(f"{overlay_id} has unsupported source overlay kind: {kind}")
            if kind == "brand_mark" and overlay.get("observed_text") not in (None, ""):
                raise OverlayMappingError("brand_mark observed_text must be null")
            candidate = deepcopy(dict(overlay))
            previous = result.get(overlay_id)
            if previous is None:
                result[overlay_id] = candidate
            else:
                # The overlay contract permits one logical ID to continue
                # across adjacent Cuts.  Consolidate those phase records for
                # the region-level mapping while retaining every keyframe.
                previous["start_us"] = min(int(previous["start_us"]), start)
                previous["end_us"] = max(int(previous["end_us"]), end)
                previous["end_rect"] = candidate.get("end_rect") or previous.get("end_rect")
                previous["end_rotation_deg"] = candidate.get("end_rotation_deg", previous.get("end_rotation_deg"))
                previous["end_opacity"] = candidate.get("end_opacity", previous.get("end_opacity"))
                old_keyframes = previous.get("keyframes") if isinstance(previous.get("keyframes"), list) else []
                new_keyframes = candidate.get("keyframes") if isinstance(candidate.get("keyframes"), list) else []
                previous["keyframes"] = sorted(
                    [*old_keyframes, *new_keyframes],
                    key=lambda item: int(item.get("time_us", 0)) if isinstance(item, Mapping) else 0,
                )
    return result


def _generated_regions(timeline_regions: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw = timeline_regions.get("regions") if isinstance(timeline_regions, Mapping) else timeline_regions
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise OverlayMappingError("timeline regions must be an array")
    result: list[dict[str, Any]] = []
    for index, region in enumerate(raw, start=1):
        if not isinstance(region, Mapping):
            raise OverlayMappingError(f"timeline region {index} must be an object")
        kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
        origin = str(region.get("media_origin") or "").strip().lower()
        policy = str(region.get("assembly_policy") or "").strip().lower()
        if kind not in {"generated", "generated_ui", "generated_ui_demo"} and origin not in {"generated", "generated_media"} and policy not in {"generate_region", "generate_ui"}:
            continue
        region_id = str(region.get("region_id") or "").strip()
        if not region_id:
            raise OverlayMappingError("generated timeline regions require region_id")
        start = region.get("source_start_us", region.get("start_us"))
        end = region.get("source_end_us", region.get("end_us"))
        start_us = _as_us(start, f"{region_id}.source_start_us")
        end_us = _as_us(end, f"{region_id}.source_end_us")
        if end_us <= start_us:
            raise OverlayMappingError(f"{region_id} has an invalid source window")
        result.append({**dict(region), "region_id": region_id, "source_start_us": start_us, "source_end_us": end_us})
    return result


def _replacement_payload(
    overlay: Mapping[str, Any],
    replacement: Mapping[str, Any] | None,
    *,
    output_language: str | None,
) -> tuple[str, dict[str, Any]]:
    overlay_id = str(overlay.get("overlay_id") or "")
    kind = str(overlay.get("kind") or "other").strip().lower()
    replacement = dict(replacement or {})
    requested_mode = str(replacement.get("render_mode") or "").strip().lower()
    text = replacement.get("text")
    if text is None and kind in _TEXT_KINDS:
        text = overlay.get("observed_text")
    if text is not None:
        if kind not in _TEXT_KINDS:
            raise OverlayMappingError(f"{overlay_id} source kind {kind} cannot be replaced with text")
        if (
            not isinstance(text, str)
            or not text.strip()
            or any(marker in text for marker in _MOJIBAKE_MARKERS)
        ):
            raise OverlayMappingError(f"{overlay_id} target text must be readable UTF-8 text")
        declared_language = replacement.get("language", replacement.get("output_language"))
        if declared_language is not None and declared_language != output_language:
            raise OverlayMappingError(
                f"{overlay_id} target text language differs from output_language"
            )
        payload: dict[str, Any] = {
            "text": text,
            "output_language": output_language,
        }
        if output_language is not None:
            font_sha = str(replacement.get("font_sha256") or "").lower()
            if _SHA256.fullmatch(font_sha) is None:
                raise OverlayMappingError(
                    f"{overlay_id}.font_sha256 must bind an immutable font asset"
                )
            raw_codepoints = replacement.get("supported_codepoints")
            if (
                not isinstance(raw_codepoints, Sequence)
                or isinstance(raw_codepoints, (str, bytes, bytearray))
            ):
                raise OverlayMappingError(
                    f"{overlay_id} requires deterministic glyph coverage"
                )
            try:
                codepoints = sorted({int(value) for value in raw_codepoints})
            except (TypeError, ValueError) as exc:
                raise OverlayMappingError(
                    f"{overlay_id} glyph coverage must contain Unicode codepoints"
                ) from exc
            missing = sorted(
                {ord(char) for char in text if not char.isspace()} - set(codepoints)
            )
            if missing:
                raise OverlayMappingError(
                    f"{overlay_id} immutable font has missing glyph coverage: {missing}"
                )
            payload.update(
                {
                    "font_sha256": font_sha,
                    "glyph_coverage_sha256": _sha256(codepoints),
                    "verification_required": True,
                }
            )
            for key in (
                "font_artifact_kind",
                "font_artifact_id",
                "font_path",
            ):
                if replacement.get(key) is not None:
                    payload[key] = replacement[key]
        for key in _TEXT_STYLE_KEYS:
            if key in replacement:
                payload[key] = replacement[key]
        return "deterministic_text", payload

    asset_sha = str(replacement.get("asset_sha256") or "").lower()
    if asset_sha:
        if kind not in _ASSET_KINDS:
            raise OverlayMappingError(f"{overlay_id} source kind {kind} cannot use an asset payload")
        if _SHA256.fullmatch(asset_sha) is None:
            raise OverlayMappingError(f"{overlay_id}.asset_sha256 must be a lowercase SHA-256")
        payload = {"asset_sha256": asset_sha}
        for key in ("artifact_kind", "artifact_id", "asset_path"):
            if replacement.get(key) is not None:
                payload[key] = replacement[key]
        for key in _ASSET_STYLE_KEYS:
            if key in replacement:
                payload[key] = replacement[key]
        if requested_mode not in {"", "deterministic_asset", "replacement_asset"}:
            raise OverlayMappingError(f"{overlay_id} has incompatible asset render mode")
        return "deterministic_asset", payload

    if requested_mode == "omit":
        raise OverlayMappingError(f"{overlay_id} cannot be omitted from an active semantic overlay mapping")
    raise OverlayMappingError(
        f"{overlay_id} requires target text or an immutable asset_sha256; refusing to invent overlay content"
    )


def build_overlay_render_mapping(
    source_overlay_contract: Mapping[str, Any],
    timeline_regions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    replacements: Mapping[str, Mapping[str, Any]] | None = None,
    allow_local_paths: bool = False,
    output_language: str | None = None,
) -> dict[str, Any]:
    """Build the canonical server mapping for generated regions.

    ``replacements`` is keyed by immutable ``overlay_id``.  Missing text
    replacements preserve the observed source text; missing brand/asset
    replacements block rather than inventing a logo or image.
    """

    if output_language is None and isinstance(timeline_regions, Mapping):
        candidate = timeline_regions.get("output_language")
        output_language = str(candidate) if candidate is not None else None
    if output_language is not None and output_language not in _OUTPUT_LANGUAGES:
        raise OverlayMappingError("output_language is unsupported")
    contract = deepcopy(dict(source_overlay_contract))
    source_index = _source_index(contract)
    regions = _generated_regions(timeline_regions)
    replacements = dict(replacements or {})
    rows: list[dict[str, Any]] = []
    mapped_keys: set[tuple[str, str]] = set()
    for region in regions:
        region_id = region["region_id"]
        region_start = region["source_start_us"]
        region_end = region["source_end_us"]
        entries: list[dict[str, Any]] = []
        for overlay_id, overlay in source_index.items():
            overlay_start = _as_us(overlay.get("start_us"), f"{overlay_id}.start_us")
            overlay_end = _as_us(overlay.get("end_us"), f"{overlay_id}.end_us")
            if overlay_end <= region_start or overlay_start >= region_end:
                continue
            key = (region_id, overlay_id)
            if key in mapped_keys:
                raise OverlayMappingError(f"duplicate overlay mapping: {region_id}/{overlay_id}")
            replacement = replacements.get(overlay_id)
            if isinstance(replacement, Mapping) and replacement.get("asset_path") is not None and not allow_local_paths:
                raise OverlayMappingError(
                    f"{overlay_id} asset_path is development-only; provide artifact_kind/artifact_id and asset_sha256"
                )
            mode, payload = _replacement_payload(
                overlay,
                replacement,
                output_language=output_language,
            )
            if mode == "deterministic_text":
                target_text = str(payload.get("text") or "").casefold()
                for prompt_field in (
                    "segment_prompt",
                    "seedance_prompt",
                    "prompt",
                    "generation_prompt",
                ):
                    prompt = region.get(prompt_field)
                    if (
                        target_text
                        and isinstance(prompt, str)
                        and target_text in prompt.casefold()
                    ):
                        raise OverlayMappingError(
                            f"{overlay_id} Seedance-readable-text leakage is forbidden"
                        )
            entry = deepcopy(dict(overlay))
            entry.update(
                {
                    "source_overlay_id": overlay_id,
                    "overlay_id": overlay_id,
                    "source_overlay": deepcopy(dict(overlay)),
                    "validated": True,
                    "render_mode": mode,
                    "payload": payload,
                    "payload_sha256": _sha256(payload),
                }
            )
            if mode == "deterministic_asset":
                entry["asset_sha256"] = payload["asset_sha256"]
            entries.append(entry)
            mapped_keys.add(key)
        if entries:
            rows.append({"region_id": region_id, "overlays": entries})
    if not rows:
        return {
            "contract": "target-overlay-render-mapping",
            "contract_version": 1,
            "source_overlay_contract_sha256": _sha256(contract),
            "output_language": output_language,
            "regions": [],
        }
    return {
        "contract": "target-overlay-render-mapping",
        "contract_version": 1,
        "source_overlay_contract_sha256": _sha256(contract),
        "output_language": output_language,
        "regions": rows,
    }


__all__ = ["OverlayMappingError", "build_overlay_render_mapping", "canonical_sha256"]
