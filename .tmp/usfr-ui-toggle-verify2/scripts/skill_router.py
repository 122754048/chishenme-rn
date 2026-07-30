"""Deterministic skill selection for the high-fidelity replication profile.

This module is intentionally provider- and filesystem-neutral.  It turns the
already frozen source/target analysis factors into an ordered list of bundled
or injected skill dependencies.  It does not add a workflow stage, approval,
provider request, or public input field.  The returned paths are logical
POSIX package paths only; a worker resolves them from its immutable container
or artifact bundle at startup.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any


ROUTER_CONTRACT = "universal-fidelity-skill-routing/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")


class SkillRouteError(ValueError):
    """Raised when a route would be non-deterministic or non-deployable."""


_BUNDLED = {
    "analyze-reference-video-dynamics": (
        "bundled-skills/analyze-reference-video-dynamics",
        "one frame-zero-to-end source dynamics pass",
    ),
    "replicate-source-ui-overlays": (
        "bundled-skills/replicate-source-ui-overlays",
        "timed overlay geometry and layer contract",
    ),
    "parse-app-store-evidence": (
        "bundled-skills/parse-app-store-evidence",
        "official Apple/Google evidence bundle",
    ),
    "seedance-storyboard-replication": (
        "bundled-skills/seedance-storyboard-replication",
        "existing storyboard/provider/assembly adapter",
    ),
}

_INJECTED = {
    "seedance-20": ("seedance-20/SKILL.md", "mandatory final prompt compiler/auditor"),
    "seedance-characters": ("seedance-20/skills/seedance-characters/SKILL.md", "identity/performance/hand safety"),
    "seedance-camera": ("seedance-20/skills/seedance-camera/SKILL.md", "camera and framing contract"),
    "seedance-motion": ("seedance-20/skills/seedance-motion/SKILL.md", "physical action and endpoint contract"),
    "seedance-lighting": ("seedance-20/skills/seedance-lighting/SKILL.md", "motivated light and shadow contract"),
    "seedance-audio": ("seedance-20/skills/seedance-audio/SKILL.md", "dialogue, Foley, silence, and lip-sync contract"),
    "seedance-sequence": ("seedance-20/skills/seedance-sequence/SKILL.md", "multi-region continuity and handoff"),
    "seedance-style": ("seedance-20/skills/seedance-style/SKILL.md", "medium/style constraints when explicitly evidenced"),
    "seedance-vfx": ("seedance-20/skills/seedance-vfx/SKILL.md", "physical VFX constraints when explicitly evidenced"),
    "seedance-prompt": ("seedance-20/skills/seedance-prompt/SKILL.md", "production prompt compiler"),
    "seedance-antislop": ("seedance-20/skills/seedance-antislop/SKILL.md", "observable production-language cleanup"),
}

_SPECIALIST_ORDER = (
    ("performance", "seedance-characters"),
    ("characters", "seedance-characters"),
    ("camera", "seedance-camera"),
    ("motion", "seedance-motion"),
    ("lighting", "seedance-lighting"),
    ("audio", "seedance-audio"),
    ("style", "seedance-style"),
    ("vfx", "seedance-vfx"),
)


def _truthy(factors: Mapping[str, Any], *keys: str) -> bool:
    return any(factors.get(key) is True for key in keys)


def _validate_logical_prefix(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillRouteError("dependency_root must be a non-empty logical path")
    value = value.strip().replace("\\", "/").strip("/")
    if _ABSOLUTE.match(value) or any(part in {"", ".", ".."} for part in value.split("/")):
        raise SkillRouteError("dependency_root must be a relative POSIX package path")
    return value


def _descriptor(name: str, *, dependency_root: str) -> dict[str, Any]:
    if name in _BUNDLED:
        base, role = _BUNDLED[name]
        package_path = f"{base}/SKILL.md"
        source = "bundled"
    elif name in _INJECTED:
        relative, role = _INJECTED[name]
        package_path = f"{dependency_root}/{relative}"
        source = "injected"
    else:
        raise SkillRouteError(f"unknown skill dependency: {name}")
    return {
        "name": name,
        "source": source,
        "package_path": package_path,
        "role": role,
        "digest_required": True,
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_skill_route(
    *,
    generated_regions: int,
    factors: Mapping[str, Any] | None = None,
    overlay_required: bool = False,
    app_store_url_present: bool = False,
    dependency_root: str = "dependencies",
) -> dict[str, Any]:
    """Build a stable, deployable module route from frozen analysis factors."""

    if isinstance(generated_regions, bool) or not isinstance(generated_regions, int) or not 0 <= generated_regions <= 2:
        raise SkillRouteError("generated_regions must be an integer from 0 through 2")
    if not isinstance(overlay_required, bool) or not isinstance(app_store_url_present, bool):
        raise SkillRouteError("overlay_required and app_store_url_present must be boolean")
    factors = dict(factors or {})
    dependency_root = _validate_logical_prefix(dependency_root)

    modules: list[str] = ["analyze-reference-video-dynamics"]
    if overlay_required:
        modules.append("replicate-source-ui-overlays")
    # A local-only/opaque-only run has no generated UI carrier that can consume
    # App-store semantics.  Skipping the parser here preserves the design's
    # zero-generated-region fast path and avoids an unnecessary network/evidence
    # stage without changing the public route or slot contract.
    if app_store_url_present and generated_regions:
        modules.append("parse-app-store-evidence")

    provider_modules: list[str] = []
    if generated_regions:
        modules.append("seedance-storyboard-replication")
        provider_modules.append("seedance-storyboard-replication")
        # Keep this order identical to Invocation-B's prompt compiler so the
        # same factor set yields one stable A/B dependency route.
        modules.extend(("seedance-20", "seedance-prompt", "seedance-antislop"))
        seen_specialists: set[str] = set()
        for key, name in _SPECIALIST_ORDER:
            if _truthy(factors, key) and name not in seen_specialists:
                modules.append(name)
                seen_specialists.add(name)
        if generated_regions > 1 or _truthy(factors, "multi_shot", "sequence", "continuity"):
            modules.append("seedance-sequence")

    if len(modules) != len(set(modules)):
        raise SkillRouteError("skill route contains duplicate modules")
    dependencies = {name: _descriptor(name, dependency_root=dependency_root) for name in modules}
    payload = {
        "contract": ROUTER_CONTRACT,
        "analysis_pass_count": 1,
        "generated_regions": generated_regions,
        "modules": modules,
        "provider_modules": provider_modules,
        "dependency_snapshot": dependencies,
    }
    digest = hashlib.sha256(_canonical(payload)).hexdigest()
    if _SHA256.fullmatch(digest) is None:  # defensive; keeps the contract explicit
        raise SkillRouteError("skill route digest generation failed")
    return {**payload, "route_sha256": digest}


__all__ = ["ROUTER_CONTRACT", "SkillRouteError", "build_skill_route"]
