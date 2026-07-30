"""Canonical user-confirmed locks for visible source text observations."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DISPOSITIONS = frozenset({"keep", "replace", "remove"})
_GENERATION_SURFACE_KINDS = frozenset(
    {
        "scene_surface_text",
        "diegetic_surface_text",
        "prop_text",
        "paper_text",
        "paper_sign_text",
        "packaging_text",
        "product_label_text",
        "wardrobe_text",
        "physical_sign_text",
        "device_body_text",
    }
)
_DETERMINISTIC_OVERLAY_KINDS = frozenset(
    {
        "subtitle",
        "caption",
        "overlay_text",
        "headline",
        "cta",
        "wordmark",
        "lower_third",
        "sticker_text",
    }
)
_DETERMINISTIC_UI_KINDS = frozenset({"ui_text", "screen_ui_text", "app_ui_text"})
_LOCK_FIELDS = frozenset(
    {
        "text_id",
        "cut_ids",
        "start_ms",
        "end_ms",
        "kind",
        "source_evidence_sha256",
        "approved_text",
        "disposition",
        "placement",
    }
)


class VisibleTextContractError(ValueError):
    """Raised when user-confirmed visible text is not source-bound."""


def _canonical_json(value: Any, *, field: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise VisibleTextContractError(f"{field} must be canonical JSON") from exc


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisibleTextContractError(f"{field} must be a non-empty string")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise VisibleTextContractError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _ms(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VisibleTextContractError(f"{field} must be a non-negative integer millisecond")
    return value


def _canonical_lock(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise VisibleTextContractError("visible text lock must be an object")
    fields = set(value)
    missing = sorted(_LOCK_FIELDS - fields)
    unknown = sorted(fields - _LOCK_FIELDS)
    if missing or unknown:
        raise VisibleTextContractError(
            f"visible text lock has an invalid shape: missing={missing}, unknown={unknown}"
        )
    cut_ids = value.get("cut_ids")
    if not isinstance(cut_ids, Sequence) or isinstance(cut_ids, (str, bytes, bytearray)):
        raise VisibleTextContractError("visible text lock cut_ids must be an array")
    canonical_cut_ids = [_text(item, field="visible text lock cut_ids item") for item in cut_ids]
    if not canonical_cut_ids or len(set(canonical_cut_ids)) != len(canonical_cut_ids):
        raise VisibleTextContractError("visible text lock cut_ids must be non-empty and unique")
    start_ms = _ms(value.get("start_ms"), field="visible text lock start_ms")
    end_ms = _ms(value.get("end_ms"), field="visible text lock end_ms")
    if end_ms <= start_ms:
        raise VisibleTextContractError("visible text lock end_ms must be after start_ms")
    disposition = value.get("disposition")
    if disposition not in _DISPOSITIONS:
        raise VisibleTextContractError("visible text lock disposition must be keep, replace, or remove")
    approved_text = value.get("approved_text")
    if not isinstance(approved_text, str):
        raise VisibleTextContractError("visible text lock approved_text must be a string")
    if disposition == "remove":
        if approved_text != "":
            raise VisibleTextContractError("remove visible text lock requires empty approved_text")
    elif not approved_text.strip():
        raise VisibleTextContractError(f"{disposition} visible text lock requires non-empty approved_text")
    placement = value.get("placement")
    if not isinstance(placement, Mapping):
        raise VisibleTextContractError("visible text lock placement must be an object")
    return {
        "text_id": _text(value.get("text_id"), field="visible text lock text_id"),
        "cut_ids": canonical_cut_ids,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "kind": _text(value.get("kind"), field="visible text lock kind"),
        "source_evidence_sha256": _sha256(
            value.get("source_evidence_sha256"), field="visible text lock source_evidence_sha256"
        ),
        "approved_text": approved_text,
        "disposition": disposition,
        "placement": _canonical_json(dict(placement), field="visible text lock placement"),
    }


def canonicalize_visible_text_locks(locks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate only the lock syntax needed at the approval API boundary."""

    if not isinstance(locks, Sequence) or isinstance(locks, (str, bytes, bytearray)):
        raise VisibleTextContractError("visible_text_locks must be an array")
    canonical = [_canonical_lock(item) for item in locks]
    text_ids = [item["text_id"] for item in canonical]
    if len(set(text_ids)) != len(text_ids):
        raise VisibleTextContractError("visible text locks must not duplicate text_id")
    return sorted(canonical, key=lambda item: (item["start_ms"], item["end_ms"], item["text_id"]))


def visible_text_locks_sha256(locks: Sequence[Mapping[str, Any]]) -> str:
    canonical = canonicalize_visible_text_locks(locks)
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def visible_text_render_route(lock: Mapping[str, Any]) -> str:
    """Choose the render lane from the text's physical carrier."""

    canonical = _canonical_lock(lock)
    kind = canonical["kind"].strip().casefold().replace("-", "_").replace(" ", "_")
    if kind in _GENERATION_SURFACE_KINDS:
        placement = canonical["placement"]
        required = ("carrier_id", "surface_relation", "motion_behavior")
        missing = [field for field in required if not str(placement.get(field) or "").strip()]
        if missing:
            raise VisibleTextContractError(
                f"scene-surface visible text placement is missing carrier fields: {missing}"
            )
        return "generation_surface"
    if kind in _DETERMINISTIC_OVERLAY_KINDS:
        return "deterministic_overlay"
    if kind in _DETERMINISTIC_UI_KINDS:
        return "deterministic_ui"
    raise VisibleTextContractError(
        "visible text kind has no carrier-aware render route; classify it as scene-surface, overlay, or UI text"
    )


def split_visible_text_locks_by_render_route(
    locks: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    routed = {
        "generation_surface": [],
        "deterministic_overlay": [],
        "deterministic_ui": [],
    }
    for lock in canonicalize_visible_text_locks(locks):
        routed[visible_text_render_route(lock)].append(lock)
    return routed


def _source_row(value: Mapping[str, Any]) -> dict[str, Any]:
    placement = value.get("placement", {})
    if not isinstance(placement, Mapping):
        raise VisibleTextContractError("timeline visible_text placement must be an object")
    return {
        "text_id": _text(value.get("text_id"), field="timeline visible_text text_id"),
        "cut_ids": [_text(item, field="timeline visible_text cut_ids item") for item in value.get("cut_ids", [])],
        "start_ms": _ms(value.get("start_ms"), field="timeline visible_text start_ms"),
        "end_ms": _ms(value.get("end_ms"), field="timeline visible_text end_ms"),
        "kind": _text(value.get("kind"), field="timeline visible_text kind"),
        "source_evidence_sha256": _sha256(
            value.get("source_evidence_sha256", value.get("evidence_sha256")),
            field="timeline visible_text source evidence",
        ),
        "text": _text(value.get("text"), field="timeline visible_text text"),
        "placement": _canonical_json(dict(placement), field="timeline visible_text placement"),
    }


def validate_visible_text_locks(
    locks: Sequence[Mapping[str, Any]], *, timeline: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Bind every lock to one exact frozen visible-text observation."""

    if not isinstance(timeline, Mapping):
        raise VisibleTextContractError("timeline is required")
    visible_text = timeline.get("visible_text")
    if not isinstance(visible_text, Sequence) or isinstance(visible_text, (str, bytes, bytearray)):
        raise VisibleTextContractError("timeline visible_text must be an array")
    source_rows = [_source_row(item) for item in visible_text if isinstance(item, Mapping)]
    if len(source_rows) != len(visible_text):
        raise VisibleTextContractError("timeline visible_text rows must be objects")
    source_by_id = {item["text_id"]: item for item in source_rows}
    if len(source_by_id) != len(source_rows):
        raise VisibleTextContractError("timeline visible_text rows must have unique text_id")
    canonical = canonicalize_visible_text_locks(locks)
    if len(canonical) != len(source_rows):
        raise VisibleTextContractError("visible text locks must cover every frozen source evidence row")
    for lock in canonical:
        source = source_by_id.get(lock["text_id"])
        if source is None:
            raise VisibleTextContractError("visible text lock does not match frozen source evidence")
        for field in ("cut_ids", "start_ms", "end_ms", "kind", "source_evidence_sha256", "placement"):
            if lock[field] != source[field]:
                raise VisibleTextContractError("visible text lock does not match frozen source evidence")
        if lock["disposition"] == "keep" and lock["approved_text"] != source["text"]:
            raise VisibleTextContractError("keep visible text lock approved_text must exactly match source text")
    return canonical


__all__ = [
    "VisibleTextContractError",
    "canonicalize_visible_text_locks",
    "validate_visible_text_locks",
    "visible_text_locks_sha256",
    "visible_text_render_route",
    "split_visible_text_locks_by_render_route",
]
