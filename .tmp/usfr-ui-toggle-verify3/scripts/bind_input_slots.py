"""Bind the seven fixed replication input slots without content classification.

The slot position is authoritative. This module validates only the declared
slot's transport type, hashes supplied values, and freezes deterministic route
defaults for downstream stages.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import urlparse


SLOT_ORDER = (
    "source_video",
    "new_product_image",
    "new_model_image",
    "ui_screenshot",
    "app_store_url",
    "ui_operation_video",
    "tail_video",
)
OPTIONAL_SLOTS = SLOT_ORDER[1:]
MULTI_VALUE_SLOTS = {"new_product_image", "new_model_image", "ui_screenshot"}
SUPPORTED_OUTPUT_LANGUAGES = ("en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh")
UI_REBUILD_ENABLED_ENV = "USFR_UI_REBUILD_ENABLED"

_SLOT_ROLE = {
    "source_video": "source_video",
    "new_product_image": "target_product_truth",
    "new_model_image": "target_character_truth",
    "ui_screenshot": "target_ui_truth",
    "app_store_url": "app_store_evidence",
    "ui_operation_video": "opaque_ui_demo",
    "tail_video": "opaque_app_tail_card",
}
_SLOT_KIND = {
    "source_video": "video",
    "new_product_image": "image",
    "new_model_image": "image",
    "ui_screenshot": "image",
    "app_store_url": "url",
    "ui_operation_video": "video",
    "tail_video": "video",
}
_VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
_IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
_AUDIO_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
_AUDIO_CONTENT_TYPES = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
}
_APP_STORE_HOSTS = {"apps.apple.com", "itunes.apple.com", "play.google.com"}


class InputSlotError(ValueError):
    """Raised when a fixed input slot cannot be admitted."""


def _is_absent(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (bytes, bytearray)):
        return not value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value) == 0
    return False


def _values(value: object) -> list[object]:
    if _is_absent(value):
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_value(value: object, *, kind: str, slot_id: str) -> tuple[str, str]:
    path = Path(str(value)).expanduser()
    if not path.is_file():
        raise InputSlotError(f"{slot_id}: file not found: {path}")
    suffix = path.suffix.lower()
    allowed = _VIDEO_SUFFIXES if kind == "video" else _IMAGE_SUFFIXES
    if suffix not in allowed:
        label = "video" if kind == "video" else "image"
        raise InputSlotError(f"{slot_id}: expected an {label} file, got {path.name}")
    resolved = path.resolve()
    return str(resolved), _sha256_bytes(resolved.read_bytes())


def _audio_value(value: object) -> tuple[str, str, str]:
    path = Path(str(value)).expanduser()
    if not path.is_file():
        raise InputSlotError(f"background_music: file not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in _AUDIO_SUFFIXES:
        raise InputSlotError(f"background_music: expected an audio file, got {path.name}")
    resolved = path.resolve()
    return (
        str(resolved),
        _sha256_bytes(resolved.read_bytes()),
        _AUDIO_CONTENT_TYPES[suffix],
    )


def _url_value(value: object, *, slot_id: str) -> tuple[str, str]:
    url = str(value).strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _APP_STORE_HOSTS:
        raise InputSlotError(
            f"{slot_id}: expected an official HTTPS Apple App Store or Google Play URL"
        )
    return url, _sha256_bytes(url.encode("utf-8"))


def _normalize_ui_rebuild_enabled(value: object = None) -> bool:
    """Resolve the automatic UI-rebuild switch and fail closed on bad input."""

    if value is None:
        value = os.getenv(UI_REBUILD_ENABLED_ENV, "")
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raw = str(value).strip().casefold()
    if not raw:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise InputSlotError(
        f"{UI_REBUILD_ENABLED_ENV}: expected true/false (received {value!r})"
    )


def _route_defaults(
    present: Mapping[str, bool],
    *,
    ui_rebuild_enabled: bool = False,
    output_language: object = None,
) -> dict[str, str]:
    explicit_ui_target = present["ui_screenshot"] or present["app_store_url"]
    automatic_ui_target = ui_rebuild_enabled and (
        present["new_product_image"]
        or present["new_model_image"]
        or not _is_absent(output_language)
    )
    return {
        "product": (
            "replace_from_slot" if present["new_product_image"] else "source_preserve"
        ),
        "character": (
            "replace_from_slot" if present["new_model_image"] else "source_preserve"
        ),
        "ui": (
            "opaque_ui_demo"
            if present["ui_operation_video"]
            else "generated_ui_demo"
            if explicit_ui_target or automatic_ui_target
            else "source_ui_keep"
        ),
        "tail": (
            "opaque_app_tail_card" if present["tail_video"] else "omit_source_end_card"
        ),
    }


def _normalize_output_language(value: object) -> str | None:
    if _is_absent(value):
        return None
    language = str(value).strip().lower()
    if language not in SUPPORTED_OUTPUT_LANGUAGES:
        raise InputSlotError(
            "output_language: expected one of "
            + ", ".join(SUPPORTED_OUTPUT_LANGUAGES)
        )
    return language


def validate_slots(
    slot_values: Mapping[str, object],
    *,
    output_language: object = None,
    background_music: object = None,
    ui_rebuild_enabled: object = None,
) -> dict[str, Any]:
    """Validate fixed slots and return an admission report.

    Source-only input returns a valid report with a blocker so a UI can disable
    Next without treating the expected gate as an exception. Invalid or unknown
    slot values raise because they cannot produce a trustworthy manifest.
    """

    slot_values = dict(slot_values)
    if output_language is None and "output_language" in slot_values:
        output_language = slot_values.pop("output_language")
    if background_music is None and "background_music" in slot_values:
        background_music = slot_values.pop("background_music")
    unknown = sorted(set(slot_values) - set(SLOT_ORDER))
    if unknown:
        raise InputSlotError(f"unknown input slot: {unknown[0]}")
    normalized_output_language = _normalize_output_language(output_language)
    configured_ui_rebuild_enabled = _normalize_ui_rebuild_enabled(ui_rebuild_enabled)

    slots: dict[str, dict[str, Any]] = {}
    present: dict[str, bool] = {}
    for slot_id in SLOT_ORDER:
        raw = slot_values.get(slot_id)
        supplied = not _is_absent(raw)
        present[slot_id] = supplied
        entries: list[str] = []
        hashes: list[str] = []
        if supplied:
            values = _values(raw)
            if slot_id not in MULTI_VALUE_SLOTS and len(values) > 1:
                raise InputSlotError(f"{slot_id}: slot only accepts one value")
            kind = _SLOT_KIND[slot_id]
            for item in values:
                if kind == "url":
                    normalized, digest = _url_value(item, slot_id=slot_id)
                else:
                    normalized, digest = _file_value(item, kind=kind, slot_id=slot_id)
                entries.append(normalized)
                hashes.append(digest)
        slots[slot_id] = {
            "slot_id": slot_id,
            "role": _SLOT_ROLE[slot_id],
            "kind": _SLOT_KIND[slot_id],
            "present": supplied,
            "valid": True,
            "source": "supplied" if supplied else "absent",
            "values": entries,
            "sha256": hashes,
        }

    optional_count = sum(present[slot_id] for slot_id in OPTIONAL_SLOTS)
    source_present = present["source_video"]
    if not source_present:
        raise InputSlotError("source_video is required")
    music_extension = None
    if not _is_absent(background_music):
        music_path, music_sha256, music_content_type = _audio_value(background_music)
        music_extension = {
            "extension_id": "input_contract_v2.background_music",
            "source": "supplied",
            "values": [music_path],
            "sha256": [music_sha256],
            "content_type": music_content_type,
            "provider_route": "seedance_audio_reference",
        }
    language_only = (
        normalized_output_language is not None
        and optional_count == 0
        and music_extension is None
    )
    can_proceed = optional_count >= 1 or music_extension is not None or language_only
    manifest = {
        "schema_version": "fixed-input-slots/v1",
        "slot_order": list(SLOT_ORDER),
        "admission": {
            "source_required": True,
            "source_present": source_present,
            "minimum_optional_slots": 0 if language_only else 1,
            "optional_present_count": optional_count,
            "can_proceed": can_proceed,
            "language_only": language_only,
            "change_input_present": can_proceed,
            "enabled_extension_present": music_extension is not None,
            "blocker_code": None if can_proceed else "MIN_ONE_OPTIONAL_INPUT_REQUIRED",
        },
        "slots": slots,
        "routes": _route_defaults(
            present,
            ui_rebuild_enabled=configured_ui_rebuild_enabled,
            output_language=normalized_output_language,
        ),
    }
    manifest["routes"]["background_music"] = (
        "seedance_audio_reference" if music_extension is not None else "none"
    )
    manifest["extensions"] = {
        "ui_rebuild_enabled": configured_ui_rebuild_enabled,
    }
    if music_extension is not None:
        manifest["extensions"]["background_music"] = music_extension
    if normalized_output_language is not None:
        manifest["output_language"] = normalized_output_language
    return manifest


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def bind_slots(
    slot_values: Mapping[str, object],
    *,
    output_language: object = None,
    background_music: object = None,
    ui_rebuild_enabled: object = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Freeze a formal manifest, enforcing the source-plus-change gate."""

    manifest = validate_slots(
        slot_values,
        output_language=output_language,
        background_music=background_music,
        ui_rebuild_enabled=ui_rebuild_enabled,
    )
    if not manifest["admission"]["can_proceed"]:
        raise InputSlotError("MIN_ONE_OPTIONAL_INPUT_REQUIRED")
    if output_path is not None:
        _write_json_atomic(Path(output_path), manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bind fixed replication input slots without AI role classification."
    )
    parser.add_argument("--source-video", required=True, type=Path)
    parser.add_argument("--new-product-image", action="append", type=Path)
    parser.add_argument("--new-model-image", action="append", type=Path)
    parser.add_argument("--ui-screenshot", action="append", type=Path)
    parser.add_argument("--app-store-url")
    parser.add_argument("--ui-operation-video", type=Path)
    parser.add_argument("--tail-video", type=Path)
    parser.add_argument("--background-music", type=Path)
    parser.add_argument("--output-language", choices=SUPPORTED_OUTPUT_LANGUAGES)
    parser.add_argument("--ui-rebuild-enabled", action="store_true", default=None)
    parser.add_argument("--output", type=Path, default=Path("analysis/input_slots.json"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    values = {
        "source_video": args.source_video,
        "new_product_image": args.new_product_image,
        "new_model_image": args.new_model_image,
        "ui_screenshot": args.ui_screenshot,
        "app_store_url": args.app_store_url,
        "ui_operation_video": args.ui_operation_video,
        "tail_video": args.tail_video,
    }
    try:
        bind_slots(
            values,
            output_language=args.output_language,
            background_music=args.background_music,
            ui_rebuild_enabled=args.ui_rebuild_enabled,
            output_path=args.output,
        )
    except InputSlotError as exc:
        raise SystemExit(str(exc)) from exc
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
