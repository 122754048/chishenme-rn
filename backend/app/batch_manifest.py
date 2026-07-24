from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Mapping


FIXED_SLOT_IDS = (
    "source_video",
    "new_product_image",
    "new_model_image",
    "ui_screenshot",
    "app_store_url",
    "ui_operation_video",
    "tail_video",
)
SUPPORTED_EXTENSIONS = frozenset({"background_music"})


class BatchManifestError(ValueError):
    pass


@dataclass(frozen=True)
class BatchRow:
    row_id: str
    slots: dict[str, str | dict[str, object] | None]
    extensions: dict[str, str | dict[str, object] | None]
    output_language: str | None
    opaque_audio_policy: dict[str, str]


def parse_batch_manifest(rows: list[dict[str, object]]) -> list[BatchRow]:
    if not isinstance(rows, list):
        raise BatchManifestError("BATCH_MANIFEST_INVALID")
    parsed: list[BatchRow] = []
    seen: set[str] = set()
    for raw in rows:
        row = _parse_row(raw)
        if row.row_id in seen:
            raise BatchManifestError("BATCH_ROW_ID_DUPLICATE")
        seen.add(row.row_id)
        parsed.append(row)
    return parsed


def _parse_row(raw: dict[str, object]) -> BatchRow:
    if not isinstance(raw, dict):
        raise BatchManifestError("BATCH_ROW_INVALID")
    row_id = raw.get("row_id")
    if not isinstance(row_id, str) or not row_id.strip():
        raise BatchManifestError("BATCH_ROW_ID_REQUIRED")
    slots = raw.get("slots")
    if not isinstance(slots, dict):
        raise BatchManifestError("BATCH_SLOTS_INVALID")
    unknown_slots = set(slots) - set(FIXED_SLOT_IDS)
    if unknown_slots:
        raise BatchManifestError("BATCH_SLOT_UNSUPPORTED")
    source_video = slots.get("source_video")
    if not _has_reference(source_video):
        raise BatchManifestError("BATCH_SOURCE_VIDEO_REQUIRED")
    normalized_slots: dict[str, str | dict[str, object] | None] = {}
    for slot_id in FIXED_SLOT_IDS:
        value = slots.get(slot_id)
        if value is not None and not isinstance(value, (str, Mapping)):
            raise BatchManifestError("BATCH_SLOT_INVALID")
        normalized_slots[slot_id] = _normalize_reference(value)
    extensions = raw.get("extensions") or {}
    if not isinstance(extensions, dict):
        raise BatchManifestError("BATCH_EXTENSIONS_INVALID")
    if set(extensions) - SUPPORTED_EXTENSIONS:
        raise BatchManifestError("BATCH_EXTENSION_UNSUPPORTED")
    normalized_extensions: dict[str, str | dict[str, object] | None] = {}
    for extension_id in SUPPORTED_EXTENSIONS:
        value = extensions.get(extension_id)
        if value is not None and not isinstance(value, (str, Mapping)):
            raise BatchManifestError("BATCH_EXTENSION_INVALID")
        normalized_extensions[extension_id] = _normalize_reference(value)
    language = raw.get("output_language")
    if language is not None and not isinstance(language, str):
        raise BatchManifestError("BATCH_OUTPUT_LANGUAGE_INVALID")
    policies = raw.get("opaque_audio_policy") or {}
    if not isinstance(policies, dict) or any(not isinstance(value, str) for value in policies.values()):
        raise BatchManifestError("BATCH_AUDIO_POLICY_INVALID")
    return BatchRow(
        row_id=row_id.strip(),
        slots=normalized_slots,
        extensions=normalized_extensions,
        output_language=language.strip().lower() if isinstance(language, str) and language.strip() else None,
        opaque_audio_policy=dict(policies),
    )


def _normalize_reference(value: object) -> str | dict[str, object] | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    return None


def _has_reference(value: object) -> bool:
    return bool(value.strip()) if isinstance(value, str) else isinstance(value, Mapping) and bool(value)
