"""Canonical server-owned contract for approved v2 edit mappings."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ReplicationError


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_REFERENCE_RE = re.compile(r"^@Image([1-9][0-9]*)$")
_ASSET_TYPES = {"model", "garment", "scene", "product", "app"}
_REPLACEMENT_EXECUTION_MODES = {"direct_binding", "adapt_action"}
_PERSON_WARDROBE_POLICIES = {
    "identity_and_wardrobe_from_reference",
    "identity_from_reference_preserve_source_wardrobe",
}
_PERSON_ASSET_PROFILE = "model-identity-v3-local-crop"
_PERSON_ASSET_COMPOSITIONS = {
    "close_portrait_square",
    "upper_body_square",
    "full_body_square",
}
_APPROVED_APP_SLOT = "app_evidence_bundle"
_ALLOWED_TEXT_TARGETS = {"title", "title-main", "subtitle", "caption", "physical-text", "app-label"}
_ALLOWED_TEXT_LAYERS = {"physical", "overlay", "watermark"}


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReplicationError("INVALID_INPUT", "value is not JSON serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonicalize_parts(
    raw_bindings: Sequence[Any],
    raw_rows: Sequence[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    binding_fields = {
        "source_slot", "source_index", "source_asset_sha256", "asset_type",
        "asset_tag", "replaces_tag", "source_artifact_id", "image_reference",
        "source_object_descriptor", "target_identity_descriptor", "replacement_scope", "preserve_scope",
        "binding_confidence", "identity_scope", "wardrobe_policy", "target_wardrobe_evidence",
        "source_wardrobe_descriptor", "person_asset_profile", "asset_mime_type", "asset_width",
        "asset_height", "identity_subject_count", "asset_layout", "asset_composition",
    }
    expected_slots = {
        "model": {"new_model_image"},
        "garment": {"new_model_image"},
        "scene": {"new_model_image"},
        "product": {"new_product_image"},
        "app": {_APPROVED_APP_SLOT},
    }
    provisional: list[dict[str, Any]] = []
    seen_source_keys: set[tuple[str, int]] = set()
    seen_asset_tags: set[str] = set()
    seen_model_replaces_tags: set[str] = set()
    for raw in raw_bindings:
        if not isinstance(raw, Mapping) or not set(raw).issubset(binding_fields):
            raise ReplicationError("INVALID_INPUT", "approved asset binding has an invalid shape")
        source_slot = str(raw.get("source_slot") or "").strip()
        source_index = raw.get("source_index")
        source_sha = str(raw.get("source_asset_sha256") or "").strip().lower()
        asset_type = str(raw.get("asset_type") or "").strip().casefold()
        asset_tag = str(raw.get("asset_tag") or "").strip()
        replaces_tag = str(raw.get("replaces_tag") or "").strip()
        source_artifact_id = str(raw.get("source_artifact_id") or "").strip()
        source_object_descriptor = str(raw.get("source_object_descriptor") or "").strip()
        target_identity_descriptor = str(raw.get("target_identity_descriptor") or "").strip()
        replacement_scope = str(raw.get("replacement_scope") or "").strip()
        preserve_scope = str(raw.get("preserve_scope") or "").strip()
        binding_confidence = raw.get("binding_confidence")
        identity_scope = str(raw.get("identity_scope") or "").strip()
        wardrobe_policy = str(raw.get("wardrobe_policy") or "").strip()
        target_wardrobe_evidence = str(raw.get("target_wardrobe_evidence") or "").strip()
        source_wardrobe_descriptor = str(raw.get("source_wardrobe_descriptor") or "").strip()
        person_asset_profile = str(raw.get("person_asset_profile") or "").strip()
        asset_mime_type = str(raw.get("asset_mime_type") or "").strip().casefold()
        asset_width = raw.get("asset_width")
        asset_height = raw.get("asset_height")
        identity_subject_count = raw.get("identity_subject_count")
        asset_layout = str(raw.get("asset_layout") or "").strip()
        asset_composition = str(raw.get("asset_composition") or "").strip()
        has_source_object_contract = any(
            field in raw
            for field in (
                "source_object_descriptor", "target_identity_descriptor", "replacement_scope", "preserve_scope",
                "binding_confidence", "identity_scope",
                "wardrobe_policy", "target_wardrobe_evidence", "source_wardrobe_descriptor",
                "person_asset_profile", "asset_mime_type", "asset_width", "asset_height",
                "identity_subject_count", "asset_layout", "asset_composition",
            )
        )
        provided_reference = raw.get("image_reference")
        if provided_reference is not None and _IMAGE_REFERENCE_RE.fullmatch(str(provided_reference).strip()) is None:
            raise ReplicationError("INVALID_INPUT", "asset binding image_reference is invalid")
        if (
            source_slot not in {slot for slots in expected_slots.values() for slot in slots}
            or isinstance(source_index, bool)
            or not isinstance(source_index, int)
            or source_index < 0
            or _SHA256_RE.fullmatch(source_sha) is None
            or asset_type not in _ASSET_TYPES
            or source_slot not in expected_slots[asset_type]
            or not asset_tag
            or not replaces_tag
            or (asset_type == "app" and not source_artifact_id)
            or (asset_type != "app" and source_artifact_id)
            or (
                has_source_object_contract
                and (
                    not source_object_descriptor
                    or not replacement_scope
                    or not preserve_scope
                    or isinstance(binding_confidence, bool)
                    or not isinstance(binding_confidence, (int, float))
                    or not 0.0 <= float(binding_confidence) <= 1.0
                    or (asset_type == "model" and identity_scope != "face_hair_skin")
                    or (asset_type != "model" and bool(identity_scope))
                )
            )
        ):
            raise ReplicationError("INVALID_INPUT", "approved asset binding source or identity is invalid")
        if has_source_object_contract and asset_type == "model":
            if (
                person_asset_profile != _PERSON_ASSET_PROFILE
                or asset_mime_type != "image/png"
                or isinstance(asset_width, bool)
                or asset_width != 1024
                or isinstance(asset_height, bool)
                or asset_height != 1024
                or isinstance(identity_subject_count, bool)
                or identity_subject_count != 1
                or asset_layout != "identity_dominant"
                or asset_composition not in _PERSON_ASSET_COMPOSITIONS
            ):
                raise ReplicationError("PERSON_ASSET_FORMAT_REQUIRED", "approved person asset format is invalid")
            if wardrobe_policy not in _PERSON_WARDROBE_POLICIES:
                raise ReplicationError("INVALID_INPUT", "approved asset binding source or identity is invalid")
            if wardrobe_policy == "identity_and_wardrobe_from_reference":
                if target_wardrobe_evidence != "visible" or not target_identity_descriptor or source_wardrobe_descriptor:
                    raise ReplicationError("INVALID_INPUT", "approved asset binding source or identity is invalid")
            else:
                folded_scope = replacement_scope.casefold()
                if target_wardrobe_evidence != "absent" or not source_wardrobe_descriptor:
                    raise ReplicationError("INVALID_INPUT", "approved asset binding source or identity is invalid")
                if "wardrobe" in folded_scope or "complete appearance" in folded_scope:
                    raise ReplicationError(
                        "INVALID_INPUT",
                        "person wardrobe policy conflicts with replacement scope",
                    )
        elif wardrobe_policy or target_wardrobe_evidence or source_wardrobe_descriptor:
            raise ReplicationError("INVALID_INPUT", "approved asset binding source or identity is invalid")
        source_key = (source_slot, source_index)
        if source_key in seen_source_keys:
            raise ReplicationError("INVALID_INPUT", "source asset is assigned to multiple identities")
        if asset_tag in seen_asset_tags:
            raise ReplicationError("INVALID_INPUT", "asset_tag is assigned to multiple assets")
        if asset_type == "model" and replaces_tag in seen_model_replaces_tags:
            raise ReplicationError("INVALID_INPUT", "model replaces_tag is assigned to multiple assets")
        seen_source_keys.add(source_key)
        seen_asset_tags.add(asset_tag)
        if asset_type == "model":
            seen_model_replaces_tags.add(replaces_tag)
        binding = {
            "source_slot": source_slot,
            "source_index": source_index,
            "source_asset_sha256": source_sha,
            "asset_type": asset_type,
            "asset_tag": asset_tag,
            "replaces_tag": replaces_tag,
        }
        if source_artifact_id:
            binding["source_artifact_id"] = source_artifact_id
        if has_source_object_contract:
            binding.update({
                "source_object_descriptor": source_object_descriptor,
                "replacement_scope": replacement_scope,
                "preserve_scope": preserve_scope,
                "binding_confidence": float(binding_confidence),
            })
            if target_identity_descriptor:
                binding["target_identity_descriptor"] = target_identity_descriptor
            if identity_scope:
                binding["identity_scope"] = identity_scope
            if wardrobe_policy:
                binding["wardrobe_policy"] = wardrobe_policy
            if target_wardrobe_evidence:
                binding["target_wardrobe_evidence"] = target_wardrobe_evidence
            if source_wardrobe_descriptor:
                binding["source_wardrobe_descriptor"] = source_wardrobe_descriptor
            if asset_type == "model":
                binding.update({
                    "person_asset_profile": person_asset_profile,
                    "asset_mime_type": asset_mime_type,
                    "asset_width": asset_width,
                    "asset_height": asset_height,
                    "identity_subject_count": identity_subject_count,
                    "asset_layout": asset_layout,
                    "asset_composition": asset_composition,
                })
        if provided_reference is not None:
            binding["_provided_image_reference"] = str(provided_reference).strip()
        provisional.append(binding)

    allowed_fields = {
        "change_id", "kind", "start_ms", "end_ms", "asset_tag", "instruction",
        "speaker", "text", "language", "text_target", "layer", "execution_mode",
    }
    normalized_rows: list[dict[str, Any]] = []
    seen_change_ids: set[str] = set()
    asset_tags = {str(row["asset_tag"]) for row in provisional}
    asset_type_by_tag = {
        str(row["asset_tag"]): str(row["asset_type"])
        for row in provisional
    }
    first_replacement_ms: dict[str, int] = {}
    for raw in raw_rows:
        if not isinstance(raw, Mapping) or not set(raw).issubset(allowed_fields):
            raise ReplicationError("INVALID_INPUT", "approved edit change row has an invalid shape")
        change_id = str(raw.get("change_id") or "").strip()
        kind = str(raw.get("kind") or "").strip().casefold()
        start_ms, end_ms = raw.get("start_ms"), raw.get("end_ms")
        if (
            not change_id
            or change_id in seen_change_ids
            or kind not in {"replacement", "dialogue", "text", "language"}
            or isinstance(start_ms, bool)
            or not isinstance(start_ms, int)
            or isinstance(end_ms, bool)
            or not isinstance(end_ms, int)
            or start_ms < 0
            or end_ms <= start_ms
        ):
            raise ReplicationError("INVALID_INPUT", "approved edit change row identity or window is invalid")
        row = {key: raw[key] for key in sorted(raw)}
        row.update({"change_id": change_id, "kind": kind, "start_ms": start_ms, "end_ms": end_ms})
        if kind == "replacement":
            asset_tag = str(row.get("asset_tag") or "").strip()
            instruction = str(row.get("instruction") or "").strip()
            if not instruction:
                raise ReplicationError("INVALID_INPUT", "replacement change row requires instruction")
            if asset_tag not in asset_tags:
                raise ReplicationError("INVALID_INPUT", "replacement change row references an unknown asset_tag")
            execution_mode_supplied = "execution_mode" in row
            execution_mode = str(row.get("execution_mode") or "direct_binding").strip().casefold()
            if execution_mode not in _REPLACEMENT_EXECUTION_MODES:
                raise ReplicationError("INVALID_INPUT", "replacement change row execution_mode is invalid")
            if execution_mode == "adapt_action" and asset_type_by_tag[asset_tag] not in {"product", "app"}:
                raise ReplicationError(
                    "INVALID_INPUT",
                    "replacement change row execution_mode is not valid for this asset type",
                )
            row["asset_tag"] = asset_tag
            if execution_mode_supplied:
                row["execution_mode"] = execution_mode
            first_replacement_ms[asset_tag] = min(start_ms, first_replacement_ms.get(asset_tag, start_ms))
        elif kind == "dialogue":
            if not str(row.get("speaker") or "").strip() or not str(row.get("text") or "").strip():
                raise ReplicationError("INVALID_INPUT", "dialogue change row requires speaker and text")
        elif kind == "text":
            text_target = str(row.get("text_target") or "").strip()
            layer = str(row.get("layer") or "").strip().casefold()
            if (
                not str(row.get("text") or "").strip()
                or text_target not in _ALLOWED_TEXT_TARGETS
                or layer not in _ALLOWED_TEXT_LAYERS
            ):
                raise ReplicationError("INVALID_INPUT", "text change row requires an approved text_target, layer, and text")
            row["text_target"] = text_target
            row["layer"] = layer
        elif kind == "language":
            if not str(row.get("language") or "").strip() or not str(row.get("text") or "").strip():
                raise ReplicationError("INVALID_INPUT", "language change row requires language and text")
        normalized_rows.append(row)
        seen_change_ids.add(change_id)
    normalized_rows.sort(key=lambda row: (row["start_ms"], row["end_ms"], row["change_id"]))

    def binding_key(binding: Mapping[str, Any]) -> tuple[Any, ...]:
        asset_type = str(binding["asset_type"])
        if asset_type == "model":
            return (0, str(binding["replaces_tag"]), str(binding["asset_tag"]), int(binding["source_index"]))
        if asset_type == "garment":
            return (1, str(binding["asset_tag"]), int(binding["source_index"]))
        if asset_type == "scene":
            return (2, str(binding["asset_tag"]), int(binding["source_index"]))
        if asset_type == "product":
            return (3, first_replacement_ms.get(str(binding["asset_tag"]), 2**63 - 1), str(binding["asset_tag"]))
        return (4, str(binding["asset_tag"]), int(binding["source_index"]))

    canonical_bindings = [dict(binding) for binding in sorted(provisional, key=binding_key)]
    for index, binding in enumerate(canonical_bindings, start=1):
        expected_reference = f"@Image{index}"
        if binding.pop("_provided_image_reference", expected_reference) != expected_reference:
            raise ReplicationError("INVALID_INPUT", "asset binding image_reference does not match canonical order")
        binding["image_reference"] = expected_reference
    return canonical_bindings, normalized_rows


def build_approved_edit_script(
    asset_bindings: Sequence[Mapping[str, Any]],
    change_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the server-owned canonical v1 edit contract from unnumbered rows."""

    if not isinstance(asset_bindings, Sequence) or isinstance(asset_bindings, (str, bytes, bytearray)):
        raise ReplicationError("INVALID_INPUT", "asset_bindings must be an array")
    if not isinstance(change_rows, Sequence) or isinstance(change_rows, (str, bytes, bytearray)):
        raise ReplicationError("INVALID_INPUT", "change_rows must be an array")
    canonical_bindings, normalized_rows = _canonicalize_parts(asset_bindings, change_rows)
    return {
        "contract": "approved-edit-script/v1",
        "asset_bindings": canonical_bindings,
        "asset_bindings_sha256": _digest(canonical_bindings),
        "change_rows": normalized_rows,
        "change_rows_sha256": _digest(normalized_rows),
    }


def canonicalize_approved_edit_script(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize the one v2 approved edit mapping."""

    if not isinstance(value, Mapping):
        raise ReplicationError("INVALID_INPUT", "approved_edit_script must be a mapping")
    required = {"contract", "asset_bindings", "asset_bindings_sha256", "change_rows", "change_rows_sha256"}
    if set(value) != required:
        raise ReplicationError(
            "INVALID_INPUT",
            "approved_edit_script has an invalid shape",
            details={"unknown": sorted(set(value) - required), "missing": sorted(required - set(value))},
        )
    if value.get("contract") != "approved-edit-script/v1":
        raise ReplicationError("INVALID_INPUT", "approved_edit_script.contract is invalid")
    raw_bindings = value.get("asset_bindings")
    raw_rows = value.get("change_rows")
    if not isinstance(raw_bindings, Sequence) or isinstance(raw_bindings, (str, bytes, bytearray)):
        raise ReplicationError("INVALID_INPUT", "approved_edit_script.asset_bindings must be an array")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes, bytearray)):
        raise ReplicationError("INVALID_INPUT", "approved_edit_script.change_rows must be an array")
    canonical = build_approved_edit_script(raw_bindings, raw_rows)
    if value.get("asset_bindings_sha256") != canonical["asset_bindings_sha256"]:
        raise ReplicationError("INVALID_INPUT", "approved_edit_script.asset_bindings_sha256 is stale")
    if value.get("change_rows_sha256") != canonical["change_rows_sha256"]:
        raise ReplicationError("INVALID_INPUT", "approved_edit_script.change_rows_sha256 is stale")
    return canonical


__all__ = ["build_approved_edit_script", "canonicalize_approved_edit_script"]
