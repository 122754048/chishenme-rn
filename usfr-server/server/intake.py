from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import Any, Protocol

from .errors import ReplicationError


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_SAFE_OBJECT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$")
_MAX_OBJECT_BYTES = 512 * 1024 * 1024
_DURATION_TOLERANCE_SECONDS = 0.001
_MULTI_VALUE_SLOTS = {"new_product_image", "new_model_image", "ui_screenshot"}
_VIDEO_MIME = {"video/mp4", "video/quicktime", "video/webm", "video/x-m4v"}
_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/avif", "image/gif"}


class ObjectStoreProbe(Protocol):
    def head(self, object_key: str) -> Mapping[str, Any]: ...


def _values(value: object) -> list[object]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _object_ref(value: object) -> bool:
    return isinstance(value, Mapping) and (
        "object_key" in value
        or "object_uri" in value
        or "uri" in value
        or ("url" in value and "sha256" in value)
    )


def _validate_object_ref(value: Mapping[str, Any], *, slot_id: str, kind: str) -> tuple[str, str, dict[str, Any]]:
    allowed = {
        "object_key",
        "object_uri",
        "uri",
        "sha256",
        "size_bytes",
        "content_type",
        "duration_seconds",
        "etag",
        "status",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{slot_id}: unknown upload-completion field: {unknown[0]}")
    key = str(value.get("object_key") or value.get("object_uri") or value.get("uri") or "").strip()
    if not key or not _SAFE_OBJECT_KEY.fullmatch(key) or ".." in key.split("/"):
        raise ValueError(f"{slot_id}: object_key is invalid")
    digest = str(value.get("sha256") or "").lower()
    if not _SHA256.fullmatch(digest):
        raise ValueError(f"{slot_id}: upload-completion sha256 must be 64 lowercase hexadecimal characters")
    raw_size = value.get("size_bytes")
    if isinstance(raw_size, bool) or isinstance(raw_size, float) and not raw_size.is_integer():
        raise ValueError(f"{slot_id}: size_bytes must be an integer")
    try:
        size_bytes = int(raw_size)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{slot_id}: size_bytes is required") from exc
    if size_bytes < 0 or size_bytes > _MAX_OBJECT_BYTES:
        raise ValueError(f"{slot_id}: size_bytes is outside the allowed range")
    content_type = str(value.get("content_type") or "").lower().strip()
    allowed_mime = _VIDEO_MIME if kind == "video" else _IMAGE_MIME
    if content_type not in allowed_mime:
        raise ValueError(f"{slot_id}: content_type is not an allowed {kind} MIME type")
    duration = value.get("duration_seconds")
    if kind == "video" and duration is None:
        raise ValueError(f"{slot_id}: duration_seconds is required for video upload completion")
    if duration is not None:
        try:
            duration = float(duration)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{slot_id}: duration_seconds is invalid") from exc
        if not math.isfinite(duration) or duration < 0:
            raise ValueError(f"{slot_id}: duration_seconds cannot be negative")
        if slot_id == "source_video" and duration > 30.0:
            raise ValueError(f"{slot_id}: duration exceeds 30 seconds")
    status = value.get("status")
    if status is not None and str(status).lower() != "completed":
        raise ValueError(f"{slot_id}: upload completion status must be completed")
    metadata = {
        "object_key": key,
        "sha256": digest,
        "size_bytes": size_bytes,
        "content_type": content_type,
    }
    if duration is not None:
        metadata["duration_seconds"] = duration
    if value.get("etag") is not None:
        metadata["etag"] = str(value["etag"])
    if status is not None:
        metadata["status"] = "completed"
    return key, digest, metadata


def bind_uploaded_slots(
    slot_objects: Mapping[str, Any],
    *,
    object_store: ObjectStoreProbe | None = None,
    upload_scope: str | None = None,
    allow_language_only: bool = False,
) -> dict[str, Any]:
    """Validate server upload-completion objects using their fixed slot IDs."""

    # Keep the local CLI binder as the compatibility path. The server path
    # additionally accepts immutable object-store completion records, which do
    # not have a local filesystem path to hash.
    from scripts.bind_input_slots import SLOT_ORDER

    unknown = sorted(set(slot_objects) - set(SLOT_ORDER))
    if unknown:
        raise ReplicationError("INPUT_SLOT_INVALID", f"unknown input slot: {unknown[0]}", category="input", user_action_required=True, http_status=400)
    for slot_id, raw in slot_objects.items():
        values = _values(raw)
        if slot_id not in _MULTI_VALUE_SLOTS and len(values) > 1:
            raise ReplicationError("INPUT_SLOT_INVALID", f"{slot_id}: only one value is allowed", category="input", user_action_required=True, http_status=400)
    has_object_completion = any(_object_ref(item) for raw in slot_objects.values() for item in _values(raw))
    if has_object_completion and object_store is None:
        raise ReplicationError(
            "INPUT_SLOT_INVALID",
            "object-store upload completion requires a configured object store",
            category="input",
            user_action_required=True,
            http_status=400,
        )
    if has_object_completion and not upload_scope:
        raise ReplicationError(
            "INPUT_SLOT_INVALID",
            "object-store upload completion requires upload_scope",
            category="input",
            user_action_required=True,
            http_status=400,
        )
    if not has_object_completion:
        normalized: dict[str, Any] = {}
        for slot_id, value in slot_objects.items():
            if isinstance(value, Mapping):
                if "path" in value:
                    normalized[slot_id] = value["path"]
                elif "url" in value:
                    normalized[slot_id] = value["url"]
                else:
                    normalized[slot_id] = value
            else:
                normalized[slot_id] = value
        try:
            from scripts.bind_input_slots import validate_slots

            manifest = validate_slots(normalized)
        except ValueError as exc:
            message = str(exc)
            code = "MIN_ONE_OPTIONAL_INPUT_REQUIRED" if "MIN_ONE_OPTIONAL_INPUT_REQUIRED" in message else "INPUT_SLOT_INVALID"
            raise ReplicationError(
                code=code,
                message=message,
                category="input",
                user_action_required=True,
                http_status=422 if code.startswith("MIN_") else 400,
            ) from exc
        if not manifest["admission"]["can_proceed"] and allow_language_only:
            manifest["admission"].update(
                {
                    "minimum_optional_slots": 0,
                    "can_proceed": True,
                    "blocker_code": None,
                    "language_only": True,
                }
            )
        if manifest["admission"].get("language_only"):
            manifest["review_route"] = "local_only"
        if not manifest["admission"]["can_proceed"]:
            raise ReplicationError(
                code="MIN_ONE_OPTIONAL_INPUT_REQUIRED",
                message="source_video plus at least one optional slot is required before Next is enabled",
                category="input",
                user_action_required=True,
                http_status=422,
            )
        return manifest

    from scripts.bind_input_slots import OPTIONAL_SLOTS, SLOT_ORDER, _route_defaults, _SLOT_KIND, _SLOT_ROLE, _url_value, _file_value

    unknown = sorted(set(slot_objects) - set(SLOT_ORDER))
    if unknown:
        raise ReplicationError("INPUT_SLOT_INVALID", f"unknown input slot: {unknown[0]}", category="input", user_action_required=True, http_status=400)
    slots: dict[str, dict[str, Any]] = {}
    present: dict[str, bool] = {}
    try:
        for slot_id in SLOT_ORDER:
            raw = slot_objects.get(slot_id)
            values = _values(raw)
            supplied = bool(values)
            present[slot_id] = supplied
            normalized_values: list[str] = []
            hashes: list[str] = []
            metadata: list[dict[str, Any]] = []
            for item in values:
                kind = _SLOT_KIND[slot_id]
                if slot_id == "app_store_url":
                    if isinstance(item, Mapping):
                        allowed = {"url", "sha256"}
                        extra = sorted(set(item) - allowed)
                        if extra:
                            raise ValueError(f"{slot_id}: unknown upload-completion field: {extra[0]}")
                        declared_digest = item.get("sha256")
                        item = item.get("url")
                    else:
                        declared_digest = None
                    normalized, digest = _url_value(item, slot_id=slot_id)
                    if declared_digest is not None and str(declared_digest).lower() != digest:
                        raise ValueError(f"{slot_id}: declared sha256 does not match URL")
                    normalized_values.append(normalized)
                    hashes.append(digest)
                elif isinstance(item, Mapping):
                    normalized, digest, item_metadata = _validate_object_ref(item, slot_id=slot_id, kind=kind)
                    if object_store is not None and not upload_scope:
                        raise ValueError(f"{slot_id}: upload_scope is required for object-store completion")
                    allowed_prefix = f"uploads/{upload_scope}/" if upload_scope else ""
                    if upload_scope and not normalized.startswith(allowed_prefix):
                        raise ValueError(f"{slot_id}: object_key is outside the upload scope")
                    if object_store is not None:
                        try:
                            observed = object_store.head(normalized)
                        except Exception as exc:
                            raise ReplicationError(
                                "OBJECT_STORE_UNAVAILABLE",
                                "object-store metadata could not be verified",
                                category="storage",
                                retryable=True,
                                details={"object_key": normalized},
                                http_status=503,
                            ) from exc
                        if not isinstance(observed, Mapping):
                            observed = {
                                "object_key": getattr(observed, "object_key", None),
                                "sha256": getattr(observed, "sha256", None),
                                "size_bytes": getattr(observed, "size_bytes", None),
                                "content_type": getattr(observed, "content_type", None),
                                "status": "completed",
                            }
                        observed_key = str(observed.get("object_key") or observed.get("object_uri") or observed.get("uri") or "").strip()
                        if observed_key != normalized:
                            raise ReplicationError(
                                "ARTIFACT_METADATA_MISMATCH",
                                "object-store object key does not match upload completion",
                                category="artifact",
                                user_action_required=True,
                                details={"object_key": normalized, "observed_object_key": observed_key},
                                http_status=422,
                            )
                        if upload_scope and not observed_key.startswith(allowed_prefix):
                            raise ReplicationError(
                                "ARTIFACT_METADATA_MISMATCH",
                                "object-store object is outside the upload scope",
                                category="artifact",
                                user_action_required=True,
                                details={"object_key": observed_key, "upload_scope": upload_scope},
                                http_status=422,
                            )
                        if str(observed.get("sha256") or "").lower() != digest:
                            raise ReplicationError(
                                "ARTIFACT_HASH_MISMATCH",
                                "object-store bytes do not match upload completion SHA-256",
                                category="artifact",
                                user_action_required=True,
                                details={"object_key": normalized, "expected": digest, "actual": observed.get("sha256")},
                                http_status=422,
                            )
                        try:
                            observed_size = int(observed.get("size_bytes", -1))
                        except (TypeError, ValueError) as exc:
                            raise ValueError(f"{slot_id}: object-store size is invalid") from exc
                        if observed_size != int(item_metadata["size_bytes"]):
                            raise ValueError(f"{slot_id}: object-store size does not match upload completion")
                        if str(observed.get("content_type") or "").lower() != item_metadata["content_type"]:
                            raise ValueError(f"{slot_id}: object-store content type does not match upload completion")
                        if str(observed.get("status") or "completed").lower() != "completed":
                            raise ValueError(f"{slot_id}: object-store object is not completed")
                        if kind == "video":
                            declared_duration = float(item_metadata["duration_seconds"])
                            observed_duration_raw = observed.get("duration_seconds")
                            if observed_duration_raw is not None:
                                try:
                                    observed_duration = float(observed_duration_raw)
                                except (TypeError, ValueError) as exc:
                                    raise ValueError(f"{slot_id}: object-store duration is invalid") from exc
                            else:
                                observed_duration = declared_duration
                            if abs(observed_duration - declared_duration) > _DURATION_TOLERANCE_SECONDS:
                                raise ReplicationError(
                                    "ARTIFACT_METADATA_MISMATCH",
                                    "object-store duration does not match upload completion",
                                    category="artifact",
                                    user_action_required=True,
                                    details={
                                        "object_key": normalized,
                                        "expected_duration_seconds": declared_duration,
                                        "observed_duration_seconds": observed_duration,
                                    },
                                    http_status=422,
                                )
                            if slot_id == "source_video" and observed_duration > 30.0:
                                raise ReplicationError(
                                    "INPUT_SOURCE_TOO_LONG",
                                    "source_video must be at most 30 seconds",
                                    category="input",
                                    user_action_required=True,
                                    details={"duration_seconds": observed_duration, "maximum_seconds": 30.0},
                                    http_status=422,
                                )
                        item_metadata["store_verified"] = True
                    normalized_values.append(normalized)
                    hashes.append(digest)
                    metadata.append(item_metadata)
                else:
                    normalized, digest = _file_value(item, kind=kind, slot_id=slot_id)
                    normalized_values.append(normalized)
                    hashes.append(digest)
            slots[slot_id] = {
                "slot_id": slot_id,
                "role": _SLOT_ROLE[slot_id],
                "kind": _SLOT_KIND[slot_id],
                "present": supplied,
                "valid": True,
                "source": "supplied" if supplied else "absent",
                "values": normalized_values,
                "sha256": hashes,
                "metadata": metadata,
            }
    except ValueError as exc:
        raise ReplicationError("INPUT_SLOT_INVALID", str(exc), category="input", user_action_required=True, http_status=400) from exc
    optional_count = sum(present[slot_id] for slot_id in OPTIONAL_SLOTS)
    if not present.get("source_video"):
        raise ReplicationError("INPUT_SOURCE_REQUIRED", "source_video is required", category="input", user_action_required=True, http_status=400)
    if optional_count < 1 and not allow_language_only:
        raise ReplicationError("MIN_ONE_OPTIONAL_INPUT_REQUIRED", "source_video plus at least one optional slot is required before Next is enabled", category="input", user_action_required=True, http_status=422)
    language_only = bool(allow_language_only)
    return {
        "schema_version": "fixed-input-slots/v1",
        "slot_order": list(SLOT_ORDER),
        "admission": {
            "source_required": True,
            "source_present": True,
            "minimum_optional_slots": 0 if allow_language_only else 1,
            "optional_present_count": optional_count,
            "can_proceed": True,
            "blocker_code": None,
            "language_only": language_only,
        },
        "slots": slots,
        "routes": _route_defaults(present),
        "upload_scope": upload_scope,
        "review_route": "local_only" if language_only else None,
    }
