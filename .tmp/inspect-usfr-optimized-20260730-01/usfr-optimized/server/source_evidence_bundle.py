"""One immutable source-evidence authority reused by all downstream stages."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import ReplicationError


SOURCE_EVIDENCE_BUNDLE_CONTRACT = "usfr-source-evidence-bundle/v1"
_UNSAFE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "chain_of_thought",
        "file_path",
        "local_path",
        "path",
        "raw_prompt",
        "reasoning",
        "secret",
        "token",
        "work_dir",
    }
)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Path):
        raise ReplicationError("CONTRACT_INVALID", "source evidence cannot contain a local path")
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if str(key).casefold() not in _UNSAFE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    raise ReplicationError("CONTRACT_INVALID", "source evidence contains an unsupported value")


class AnalysisInvocationLedger:
    """In-memory guard used by one lease to prevent duplicate full-source work."""

    def __init__(self) -> None:
        self._records: list[dict[str, str]] = []

    def record(self, tool_name: str, *, scope: str, region_id: str | None = None) -> None:
        tool = str(tool_name).strip()
        normalized_scope = str(scope).strip()
        if not tool or not normalized_scope:
            raise ReplicationError("CONTRACT_INVALID", "analysis invocation is incomplete")
        if normalized_scope == "full_source" and any(
            item["scope"] == "full_source" for item in self._records
        ):
            raise ReplicationError(
                "DUPLICATE_SOURCE_ANALYSIS",
                "full source analysis already completed",
                category="analysis",
                http_status=409,
            )
        if normalized_scope != "full_source" and not str(region_id or "").strip():
            raise ReplicationError(
                "CONTRACT_INVALID",
                "supplemental analysis requires a routed region",
                category="analysis",
                http_status=422,
            )
        self._records.append(
            {"tool": tool, "scope": normalized_scope, "region_id": str(region_id or "").strip()}
        )

    def snapshot(self) -> tuple[Mapping[str, str], ...]:
        return tuple(dict(item) for item in self._records)


def build_source_evidence_bundle(
    *,
    probe: Mapping[str, Any],
    timeline: Mapping[str, Any],
    execution_scope: Mapping[str, Any],
    semantic_evidence: Mapping[str, Any] | None,
    audio_evidence: Mapping[str, Any] | None,
    ui_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Freeze the only normal source evidence read by later workflow stages."""

    if not isinstance(probe, Mapping) or not isinstance(timeline, Mapping) or not isinstance(execution_scope, Mapping):
        raise ReplicationError("CONTRACT_INVALID", "source evidence bundle inputs are invalid")
    scope_sha256 = str(execution_scope.get("scope_sha256") or "").strip().lower()
    if len(scope_sha256) != 64 or any(char not in "0123456789abcdef" for char in scope_sha256):
        raise ReplicationError("CONTRACT_INVALID", "source evidence scope digest is invalid")
    bundle: dict[str, Any] = {
        "contract": SOURCE_EVIDENCE_BUNDLE_CONTRACT,
        "probe": _safe_value(probe),
        "timeline": _safe_value(timeline),
        "execution_scope": _safe_value(execution_scope),
        "execution_scope_sha256": scope_sha256,
        "semantic_evidence": _safe_value(semantic_evidence or {}),
        "audio_evidence": _safe_value(audio_evidence or {}),
        "ui_evidence": _safe_value(ui_evidence or {}),
        "analysis_policy": {
            "maximum_full_source_semantic_calls": 1,
            "supplemental_scope": "one_region_one_unresolved_factor_only",
        },
    }
    bundle["bundle_sha256"] = hashlib.sha256(_canonical(bundle)).hexdigest()
    return bundle


def validate_source_evidence_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("contract") != SOURCE_EVIDENCE_BUNDLE_CONTRACT:
        raise ReplicationError("CONTRACT_INVALID", "source evidence bundle contract is invalid")
    body = dict(value)
    claimed = str(body.pop("bundle_sha256", "")).lower()
    if claimed != hashlib.sha256(_canonical(body)).hexdigest():
        raise ReplicationError("CONTRACT_INVALID", "source evidence bundle digest mismatch")
    if body.get("execution_scope_sha256") != (body.get("execution_scope") or {}).get("scope_sha256"):
        raise ReplicationError("CONTRACT_INVALID", "source evidence execution scope mismatch")
    return dict(value)


__all__ = [
    "AnalysisInvocationLedger",
    "SOURCE_EVIDENCE_BUNDLE_CONTRACT",
    "build_source_evidence_bundle",
    "validate_source_evidence_bundle",
]
