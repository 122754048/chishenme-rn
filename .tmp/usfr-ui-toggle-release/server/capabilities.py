"""Deployment capability manifest and fail-closed validator.

The canonical workflow deliberately keeps its twelve stages and two approval
gates.  This module does not add a stage; it makes the implementation boundary
explicit so a production worker cannot accept a hand-written high-fidelity
sidecar without the analyzers, renderers, compiler, compositor, QC, and
provider adapter that are able to produce and verify it.

The manifest describes injected server/container capabilities, not client
inputs and not local Skill paths.  Local/development and legacy runs bypass the
production gate for backwards compatibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any


PROFILE_NAME = "high_fidelity_hybrid_v1"
SCHEMA_VERSION = "stage-capabilities/v1"
REQUIRED_CAPABILITIES = (
    "dynamics_analyzer",
    "asr_transcriber",
    "ocr_ui_renderer",
    "seedance20_compiler",
    "compositor",
    "qc_engine",
    "provider_adapter",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("manifest_sha256", None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"stage capability {field} must be a non-empty string")
    return value.strip()


def _validate_implementation(value: Any, field: str) -> str:
    implementation = _non_empty(value, field)
    folded = implementation.casefold()
    # A deployment may use a module, container, registry, or private artifact
    # reference.  It must never point at a workstation or ~/.codex checkout.
    if (
        folded.startswith(("file://", "local:", "path:"))
        or "~/.codex" in folded
        or ".codex\\skills" in folded
        or ".codex/skills" in folded
        or (len(implementation) > 1 and implementation[1] == ":" and implementation[0].isalpha())
        or implementation.startswith(("/", "\\"))
    ):
        raise ValueError(f"stage capability {field} cannot use a local path")
    return implementation


def build_stage_capability_manifest(
    capabilities: Mapping[str, Mapping[str, Any]],
    *,
    profile: str = PROFILE_NAME,
) -> dict[str, Any]:
    """Build an immutable manifest from server-injected capability records."""

    if profile != PROFILE_NAME:
        raise ValueError(f"unsupported capability profile: {profile!r}")
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "profile": profile,
        "capabilities": {str(name): dict(value) for name, value in capabilities.items()},
    }
    manifest["manifest_sha256"] = _digest(manifest)
    validate_stage_capability_manifest(manifest, production=True, profile_active=True)
    return manifest


def validate_stage_capability_manifest(
    manifest: Mapping[str, Any] | None,
    *,
    production: bool,
    profile_active: bool,
) -> None:
    """Validate required runtime capabilities for an active production profile.

    ``None``/``{}`` intentionally remain valid for legacy or local execution.
    An active profile in a production worker must provide every required
    capability and an immutable digest.  This validator only checks the
    declared server boundary; it does not pretend to implement visual models.
    """

    if not production or not profile_active:
        return None
    if not isinstance(manifest, Mapping) or not manifest:
        raise ValueError("active production profile requires a stage capability manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("stage capability manifest schema version is stale")
    if manifest.get("profile") != PROFILE_NAME:
        raise ValueError("stage capability manifest profile is unsupported")
    digest = manifest.get("manifest_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError("stage capability manifest must carry a lowercase SHA-256 digest")
    if _digest(manifest) != digest:
        raise ValueError("stage capability manifest digest is stale or tampered")
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, Mapping):
        raise ValueError("stage capability manifest capabilities must be an object")
    missing = [name for name in REQUIRED_CAPABILITIES if name not in capabilities]
    if missing:
        raise ValueError(f"stage capability manifest missing required capabilities: {', '.join(missing)}")
    unknown = sorted(set(str(name) for name in capabilities) - set(REQUIRED_CAPABILITIES))
    if unknown:
        raise ValueError(f"stage capability manifest has unsupported capabilities: {', '.join(unknown)}")
    for name in REQUIRED_CAPABILITIES:
        record = capabilities.get(name)
        if not isinstance(record, Mapping):
            raise ValueError(f"stage capability {name} record must be an object")
        if record.get("declared") is not True:
            raise ValueError(f"stage capability {name} must be declared=true")
        _validate_implementation(record.get("implementation"), f"{name}.implementation")
        _non_empty(record.get("version"), f"{name}.version")
        sha = record.get("sha256")
        if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
            raise ValueError(f"stage capability {name}.sha256 must be lowercase SHA-256")
    return None


__all__ = [
    "PROFILE_NAME",
    "SCHEMA_VERSION",
    "REQUIRED_CAPABILITIES",
    "build_stage_capability_manifest",
    "validate_stage_capability_manifest",
]
