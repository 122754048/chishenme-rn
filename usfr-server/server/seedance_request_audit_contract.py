"""Pure validation for the active Seedance request-audit contract."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SeedanceRequestAuditValidationError(ValueError):
    """A v2 request audit is not bound to the current approved authority."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_audit_fingerprint(payload: Mapping[str, Any]) -> str:
    basis = dict(payload)
    basis.pop("stage_fingerprint", None)
    return hashlib.sha256(_canonical_bytes(basis)).hexdigest()


def _require_sha(value: Any, *, field: str) -> str:
    normalized = str(value or "").lower()
    if _SHA256.fullmatch(normalized) is None:
        raise SeedanceRequestAuditValidationError(f"{field} must be a SHA-256 digest")
    return normalized


def validate_v2_seedance_request_audit(
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any] | None,
    *,
    expected_script_sha256: str,
    expected_source_sha256: str,
    expected_segment_plan_sha256: str,
    expected_asset_manifest_sha256: str,
) -> Mapping[str, Any]:
    if payload.get("schema_version") != "seedance-request-audit/v2":
        raise SeedanceRequestAuditValidationError("v2 request audit schema is unsupported")
    if payload.get("edit_contract") != "video-edit-v2":
        raise SeedanceRequestAuditValidationError("v2 request audit edit contract is unsupported")
    expected_script = _require_sha(expected_script_sha256, field="current approved script")
    expected_source = _require_sha(expected_source_sha256, field="current source video")
    expected_plan = _require_sha(expected_segment_plan_sha256, field="current segment plan")
    expected_asset = _require_sha(expected_asset_manifest_sha256, field="current asset manifest")
    fingerprint = _require_sha(payload.get("stage_fingerprint"), field="stage_fingerprint")
    if fingerprint != canonical_audit_fingerprint(payload):
        raise SeedanceRequestAuditValidationError("v2 request audit stage fingerprint is stale")
    if not isinstance(metadata, Mapping):
        raise SeedanceRequestAuditValidationError("v2 request audit descriptor metadata is missing")
    if str(metadata.get("stage_fingerprint") or "").lower() != fingerprint:
        raise SeedanceRequestAuditValidationError("v2 request audit metadata fingerprint is stale")
    if str(metadata.get("approved_script_sha256") or "").lower() != expected_script:
        raise SeedanceRequestAuditValidationError("v2 request audit metadata script is stale")
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        raise SeedanceRequestAuditValidationError("v2 request audit segments are missing")
    seen_segment_ids: set[str] = set()
    for index, raw_segment in enumerate(segments):
        if not isinstance(raw_segment, Mapping):
            raise SeedanceRequestAuditValidationError(f"v2 request audit segment {index} is invalid")
        segment_id = str(raw_segment.get("segment_id") or "").strip()
        if not segment_id or segment_id in seen_segment_ids:
            raise SeedanceRequestAuditValidationError(f"v2 request audit segment {index} identity is invalid")
        if _require_sha(raw_segment.get("approved_script_sha256"), field=f"segment {index} script") != expected_script:
            raise SeedanceRequestAuditValidationError(f"v2 request audit segment {index} script is stale")
        if _require_sha(raw_segment.get("source_video_sha256"), field=f"segment {index} source") != expected_source:
            raise SeedanceRequestAuditValidationError(f"v2 request audit segment {index} source is stale")
        if _require_sha(raw_segment.get("segment_plan_sha256"), field=f"segment {index} plan") != expected_plan:
            raise SeedanceRequestAuditValidationError(f"v2 request audit segment {index} plan is stale")
        if _require_sha(raw_segment.get("asset_board_manifest_sha256"), field=f"segment {index} asset manifest") != expected_asset:
            raise SeedanceRequestAuditValidationError(f"v2 request audit segment {index} asset manifest is stale")
        seen_segment_ids.add(segment_id)
    return {
        "stage_fingerprint": fingerprint,
        "segment_ids": tuple(sorted(seen_segment_ids)),
    }
