"""One immutable, reusable source-evidence projection for a USFR run."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .errors import ReplicationError


SOURCE_EVIDENCE_BUNDLE_CONTRACT = "usfr-source-evidence-bundle/v1"


def canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class AnalysisInvocationLedger:
    """Reject repeated full-source semantic passes within one run."""

    records: list[dict[str, str]] = field(default_factory=list)

    def record(self, tool_name: str, *, scope: str, region_id: str | None = None) -> dict[str, str]:
        tool = str(tool_name or "").strip()
        normalized_scope = str(scope or "").strip()
        if not tool or not normalized_scope:
            raise ReplicationError("CONTRACT_INVALID", "analysis invocation requires tool and scope")
        if normalized_scope == "full_source" and any(
            item.get("tool") == tool and item.get("scope") == "full_source" for item in self.records
        ):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "full source analysis already completed",
                details={"tool": tool},
            )
        receipt = {"tool": tool, "scope": normalized_scope}
        if region_id is not None:
            receipt["region_id"] = str(region_id)
        self.records.append(receipt)
        return dict(receipt)


def build_source_evidence_bundle(
    *,
    probe: Mapping[str, Any],
    timeline: Mapping[str, Any],
    execution_scope: Mapping[str, Any],
    semantic_evidence: Mapping[str, Any] | None = None,
    audio_evidence: Mapping[str, Any] | None = None,
    ui_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only source evidence object consumed after route freezing."""

    if not isinstance(probe, Mapping) or not isinstance(timeline, Mapping):
        raise ReplicationError("CONTRACT_INVALID", "source evidence bundle requires probe and timeline objects")
    if not isinstance(execution_scope, Mapping) or not str(execution_scope.get("scope_sha256") or ""):
        raise ReplicationError("CONTRACT_INVALID", "source evidence bundle requires execution scope digest")
    bundle: dict[str, Any] = {
        "contract": SOURCE_EVIDENCE_BUNDLE_CONTRACT,
        "probe": json.loads(json.dumps(dict(probe), ensure_ascii=False, sort_keys=True)),
        "timeline": json.loads(json.dumps(dict(timeline), ensure_ascii=False, sort_keys=True)),
        "execution_scope_sha256": str(execution_scope["scope_sha256"]),
        "semantic_evidence": json.loads(json.dumps(dict(semantic_evidence or {}), ensure_ascii=False, sort_keys=True)),
        "audio_evidence": json.loads(json.dumps(dict(audio_evidence or {}), ensure_ascii=False, sort_keys=True)),
        "ui_evidence": json.loads(json.dumps(dict(ui_evidence or {}), ensure_ascii=False, sort_keys=True)),
    }
    digest = canonical_sha256(bundle)
    bundle["bundle_sha256"] = digest
    bundle["source_evidence_bundle_sha256"] = digest
    return bundle


def validate_source_evidence_bundle(bundle: Mapping[str, Any]) -> None:
    if bundle.get("contract") != SOURCE_EVIDENCE_BUNDLE_CONTRACT:
        raise ReplicationError("CONTRACT_INVALID", "source evidence bundle contract is invalid")
    declared = str(bundle.get("bundle_sha256") or "").lower()
    if len(declared) != 64 or declared != canonical_sha256({key: value for key, value in bundle.items() if key not in {"bundle_sha256", "source_evidence_bundle_sha256"}}):
        raise ReplicationError("CONTRACT_INVALID", "source evidence bundle digest mismatch")
    if str(bundle.get("source_evidence_bundle_sha256") or "") != declared:
        raise ReplicationError("CONTRACT_INVALID", "source evidence bundle alias digest mismatch")


__all__ = [
    "AnalysisInvocationLedger",
    "SOURCE_EVIDENCE_BUNDLE_CONTRACT",
    "build_source_evidence_bundle",
    "canonical_sha256",
    "validate_source_evidence_bundle",
]
