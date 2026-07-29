"""Strictly scoped optional Remotion renderer selection for generated App UI.

This module deliberately contains no Video ShotCraft dependency, templates,
shot selection, BGM, or SFX behaviour.  It only decides whether an injected,
evidence-bound renderer may use the small whitelisted 2.5D UI lane for one
already-frozen generated-UI interval.  Every other case delegates directly to
the existing deterministic renderer.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Mapping, Sequence

from scripts.hybrid_compositor import choose_backend, remotion_activation_receipt_matches


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MOTION_ACTIONS = frozenset({"perspective", "parallax", "translate", "scale"})
_INTERVAL_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "region_id",
        "source_start_ms",
        "source_end_ms",
        "output_duration_ms",
        "display_viewport",
        "rotation_degrees",
        "safe_cover_crop_percent",
        "transition_shell",
    }
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identity(renderer: Any, *, label: str) -> dict[str, str]:
    identity = getattr(renderer, "capability_identity", None)
    if not callable(identity):
        raise ValueError(f"{label} requires capability_identity()")
    value = identity()
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} capability identity must be an object")
    result = {field: str(value.get(field) or "") for field in ("implementation", "version", "sha256")}
    if not result["implementation"] or not result["version"] or _SHA256.fullmatch(result["sha256"]) is None:
        raise ValueError(f"{label} capability identity must contain implementation, version, and SHA-256")
    return result


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _valid_interval_contract(value: Any, *, region_id: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(value, Mapping) or not _INTERVAL_REQUIRED_FIELDS.issubset(value):
        return None, "source_interval_contract_incomplete"
    contract = deepcopy(dict(value))
    if contract.get("schema_version") != "source-ui-interval/v1" or str(contract.get("region_id") or "") != region_id:
        return None, "source_interval_contract_mismatch"
    try:
        start_ms = int(contract["source_start_ms"])
        end_ms = int(contract["source_end_ms"])
        duration_ms = int(contract["output_duration_ms"])
        rotation = int(contract["rotation_degrees"])
        crop = float(contract["safe_cover_crop_percent"])
        viewport = contract["display_viewport"]
        width, height = int(viewport[0]), int(viewport[1])
    except (IndexError, TypeError, ValueError):
        return None, "source_interval_contract_invalid"
    if (
        start_ms < 0
        or end_ms <= start_ms
        or duration_ms <= 0
        or width <= 0
        or height <= 0
        or rotation not in {0, 90, 180, 270}
        or not 0 <= crop <= 12
        or not isinstance(contract.get("transition_shell"), Mapping)
        or not contract["transition_shell"]
    ):
        return None, "source_interval_contract_invalid"
    return contract, None


def _interval_contract_matches_region_facts(
    contract: Mapping[str, Any], region: Mapping[str, Any]
) -> bool:
    """Defend the renderer boundary against a forged Stage-4 interval contract."""

    try:
        if region.get("source_start_us") is not None or region.get("source_end_us") is not None:
            start_us = int(region.get("source_start_us"))
            end_us = int(region.get("source_end_us"))
            if start_us % 1000 != 0 or end_us % 1000 != 0:
                return False
            start_ms, end_ms = start_us // 1000, end_us // 1000
        else:
            start_ms = round(float(region.get("source_start") or region.get("start") or 0) * 1000)
            end_ms = round(float(region.get("source_end") or region.get("end") or 0) * 1000)
        viewport = region.get("display_viewport")
        source_viewport = [int(viewport[0]), int(viewport[1])]
        rotation = int(region.get("rotation_degrees"))
        crop = float(region.get("safe_cover_crop_percent"))
    except (IndexError, TypeError, ValueError):
        return False
    return (
        contract.get("source_start_ms") == start_ms
        and contract.get("source_end_ms") == end_ms
        and contract.get("output_duration_ms") == end_ms - start_ms
        and contract.get("display_viewport") == source_viewport
        and contract.get("rotation_degrees") == rotation
        and float(contract.get("safe_cover_crop_percent")) == crop
        and _canonical(contract.get("transition_shell")) == _canonical(region.get("transition_shell"))
    )


class ConditionalUiRenderBackend:
    """Select one UI renderer for one frozen target UI interval.

    The fallback renderer is mandatory.  The Remotion renderer is only called
    after the target evidence, UI truth/render contracts, source interval
    contract, adapter identity, and activation receipt all bind to one another.
    """

    implementation = "server.remotion_react_ui:ConditionalUiRenderBackend"
    version = "1.0.0"

    def __init__(
        self,
        *,
        fallback_renderer: Any,
        remotion_renderer: Any | None,
        capabilities: Mapping[str, Any] | None,
    ) -> None:
        if not callable(fallback_renderer):
            raise ValueError("fallback UI renderer must be callable")
        self.fallback_renderer = fallback_renderer
        self.remotion_renderer = remotion_renderer
        self._fallback_identity = _identity(fallback_renderer, label="fallback UI renderer")
        self._remotion_identity = (
            _identity(remotion_renderer, label="remotion_react_ui renderer")
            if remotion_renderer is not None
            else None
        )
        if capabilities is None:
            self.capabilities: dict[str, Any] = {}
        elif isinstance(capabilities, Mapping):
            self.capabilities = json.loads(_canonical(dict(capabilities)).decode("utf-8"))
        else:
            raise ValueError("UI backend capabilities must be an object")

    def capability_identity(self) -> Mapping[str, Any]:
        payload = {
            "implementation": self.implementation,
            "version": self.version,
            "fallback": self._fallback_identity,
            "remotion": self._remotion_identity,
        }
        return {
            "implementation": self.implementation,
            "version": self.version,
            "sha256": _sha256(payload),
        }

    def _matching_generated_ui_region(self, context: Any) -> Mapping[str, Any] | None:
        regions = [
            item
            for item in (getattr(context, "timeline_regions", ()) or ())
            if isinstance(item, Mapping)
            and str(item.get("region_type") or item.get("kind") or "").casefold()
            == "generated_ui_demo"
        ]
        return regions[0] if len(regions) == 1 else None

    def _decision(
        self,
        *,
        context: Any,
        truth: Mapping[str, Any],
        render_contract: Mapping[str, Any],
        target_ui_evidence_sha256: str,
    ) -> tuple[Any, dict[str, Any]]:
        region = self._matching_generated_ui_region(context)
        if region is None:
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "generated_ui_interval_not_unique",
            }
        region_id = str(region.get("region_id") or "")
        if not region_id:
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "generated_ui_region_id_missing",
            }
        interval, interval_error = _valid_interval_contract(
            region.get("source_interval_contract"), region_id=region_id
        )
        if interval_error is not None or interval is None:
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": interval_error or "source_interval_contract_invalid",
            }
        if not _interval_contract_matches_region_facts(interval, region):
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "source_interval_contract_source_facts_mismatch",
            }
        interval_sha256 = _sha256(interval)
        if region.get("source_interval_contract_sha256") != interval_sha256:
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "source_interval_contract_digest_mismatch",
            }
        if _SHA256.fullmatch(target_ui_evidence_sha256) is None:
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "target_ui_evidence_digest_invalid",
            }
        record = self.capabilities.get("remotion_react_ui")
        if self.remotion_renderer is None:
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "remotion_adapter_unavailable",
            }
        if not isinstance(record, Mapping):
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "remotion_capability_unconfigured",
            }
        if any(record.get(field) != self._remotion_identity[field] for field in ("implementation", "version", "sha256")):
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "remotion_adapter_identity_mismatch",
            }
        activation_sha256 = record.get("activation_report_sha256")
        requirements = {
            "route": "generated_ui_demo",
            "deterministic_ui_rebuild_allowed": region.get("deterministic_ui_rebuild_allowed") is True,
            "existing_renderer_equivalent": region.get("existing_renderer_equivalent"),
            "motion_actions": region.get("motion_actions"),
            "target_ui_evidence_sha256": target_ui_evidence_sha256,
            "ui_truth_card_sha256": _sha256(truth),
            "ui_render_contract_sha256": _sha256(render_contract),
            "source_interval_contract_sha256": interval_sha256,
            "benchmark_activation_report_sha256": activation_sha256,
            "remotion_adapter_identity": dict(self._remotion_identity),
        }
        if not remotion_activation_receipt_matches(
            requirements=requirements,
            capability_record=record,
        ):
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "remotion_activation_receipt_unverified",
            }
        if choose_backend(requirements, self.capabilities) != "remotion_react_ui":
            return self.fallback_renderer, {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "remotion_eligibility_conditions_not_met",
            }
        return self.remotion_renderer, {
            "backend": "remotion_react_ui",
            "enabled": True,
            "reason": "all_required_interval_evidence_and_activation_receipt_matched",
            "activation_report_sha256": activation_sha256,
            "source_interval_contract_sha256": interval_sha256,
        }

    def __call__(
        self,
        source: Path,
        output: Path,
        context: Any,
        *,
        truth: Mapping[str, Any],
        render_contract: Mapping[str, Any],
        target_ui_evidence_sha256: str | None = None,
    ) -> Mapping[str, Any]:
        evidence_sha256 = target_ui_evidence_sha256 or _file_sha256(Path(source))
        renderer, decision = self._decision(
            context=context,
            truth=truth,
            render_contract=render_contract,
            target_ui_evidence_sha256=evidence_sha256,
        )
        started_at = time.perf_counter()
        result = renderer(source, output, context, truth=truth, render_contract=render_contract)
        if not isinstance(result, Mapping):
            raise ValueError("selected UI renderer must return an object")
        response = dict(result)
        response["ui_renderer_decision"] = {
            **decision,
            "renderer_identity": dict(
                self._remotion_identity
                if decision["backend"] == "remotion_react_ui"
                else self._fallback_identity
            ),
            "duration_ms": int(round((time.perf_counter() - started_at) * 1000)),
        }
        return response


__all__ = ["ConditionalUiRenderBackend"]
