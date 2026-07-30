"""Bundled complete timeline renderer for the server compositor boundary.

The public workflow keeps the existing ``splice_timeline`` stage.  This
adapter makes the bundled FFmpeg implementation usable as the injected
complete renderer for that stage: it resolves lease-local source slices and
immutable generated/opaque media, runs the canonical timeline contract, and
redacts ephemeral paths from the returned manifest.
"""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import types
from typing import Any

from collections.abc import Mapping

from .audio_mixer import (
    AudioMixerError,
    EvidenceBoundAudioMixer,
    SourceAudioPerformanceAssembler,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_SOURCE_KEEP_REGION_TYPES = {
    "source_ui_keep",
    "source_interval",
    "source_keep",
    "source_preserve",
}
_OPAQUE_UI_REGION_TYPES = {"opaque_ui_demo", "ui_demo", "opaque_ui_video"}
_GENERATED_UI_REGION_TYPES = {"generated_ui_demo", "generated_ui"}
_OPAQUE_TAIL_REGION_TYPES = {
    "excluded_app_end_card",
    "opaque_app_tail_card",
    "opaque_tail",
    "tail_card",
}
_OMITTED_TAIL_REGION_TYPES = {"omit_source_end_card"}

_MEDIA_BINDING_FIELDS = frozenset(
    {
        "slot_id",
        "input_slot_id",
        "media_slot_id",
        "media_artifact_id",
        "artifact_id",
        "media_artifact_sha256",
        "artifact_sha256",
        "media_artifact_kind",
        "artifact_kind",
        "media_artifact_bindings",
        "provider_carrier_receipts",
        "carrier_receipts",
        "segment_id",
        "segment_plan_sha256",
    }
)


class TimelineRendererError(RuntimeError):
    """Raised when a complete timeline cannot be rendered safely."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_SOURCE_AUDIO_CONTRACT_KINDS = (
    "performance_audio_source_contract",
    "performance_timeline_contract",
    "audio_splice_policy",
)


def _read_json_contract(path: Path, *, kind: str, sha256: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise TimelineRendererError(f"source-audio {kind} artifact is unavailable")
    if sha256 is not None and _sha256_file(path) != sha256:
        raise TimelineRendererError(f"source-audio {kind} artifact SHA-256 does not match")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise TimelineRendererError(f"source-audio {kind} artifact is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise TimelineRendererError(f"source-audio {kind} artifact must be an object")
    return dict(value)


def _source_audio_contracts(context: Any, *, stack: ExitStack) -> dict[str, dict[str, Any]] | None:
    """Load immutable source-audio contracts without exposing media to a provider."""

    candidates: list[Mapping[str, Any]] = []
    for name in ("source_audio_contracts", "performance_audio_contracts"):
        value = getattr(context, name, None)
        if isinstance(value, Mapping):
            candidates.append(value)
    stage_outputs = getattr(context, "stage_outputs", None)
    if isinstance(stage_outputs, Mapping):
        for value in stage_outputs.values():
            if not isinstance(value, Mapping):
                continue
            nested = value.get("source_audio_contracts")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    for candidate in candidates:
        if any(kind in candidate for kind in _SOURCE_AUDIO_CONTRACT_KINDS):
            if not all(isinstance(candidate.get(kind), Mapping) for kind in _SOURCE_AUDIO_CONTRACT_KINDS):
                raise TimelineRendererError("source-audio contract set is incomplete")
            return {kind: dict(candidate[kind]) for kind in _SOURCE_AUDIO_CONTRACT_KINDS}

    artifacts = [
        dict(item)
        for item in (getattr(context, "artifacts", ()) or ())
        if isinstance(item, Mapping) and str(item.get("kind") or "") in _SOURCE_AUDIO_CONTRACT_KINDS
    ]
    if not artifacts:
        if getattr(context, "source_audio_mode", None) == "source_audio_replicate_v1":
            raise TimelineRendererError("source-audio replication mode is missing its immutable contracts")
        return None
    by_kind = {
        kind: [item for item in artifacts if item.get("kind") == kind]
        for kind in _SOURCE_AUDIO_CONTRACT_KINDS
    }
    if any(len(rows) != 1 for rows in by_kind.values()):
        raise TimelineRendererError("source-audio replication requires exactly one immutable contract of each kind")
    materialize = getattr(context, "materialize_artifact", None)
    if not callable(materialize):
        raise TimelineRendererError("source-audio replication requires an immutable artifact materializer")
    result: dict[str, dict[str, Any]] = {}
    for kind in _SOURCE_AUDIO_CONTRACT_KINDS:
        artifact = by_kind[kind][0]
        sha256 = str(artifact.get("sha256") or "").lower()
        if not _SHA256.fullmatch(sha256):
            raise TimelineRendererError(f"source-audio {kind} artifact has an invalid SHA-256")
        kwargs: dict[str, Any] = {"sha256": sha256}
        if artifact.get("artifact_id"):
            kwargs["artifact_id"] = str(artifact["artifact_id"])
        try:
            value = materialize(kind, **kwargs)
            if hasattr(value, "__enter__"):
                value = stack.enter_context(value)
            path = _path_from_materialized(value)
        except TimelineRendererError:
            raise
        except Exception as exc:
            raise TimelineRendererError(f"could not materialize source-audio {kind} contract") from exc
        result[kind] = _read_json_contract(path, kind=kind, sha256=sha256)
    return result


def _source_audio_remux_regions(
    *,
    contract_regions: list[dict[str, Any]],
    timeline_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project source-global contract windows onto rendered visual regions."""

    if timeline_contract.get("contract") != "performance-timeline/v1":
        raise TimelineRendererError("source-audio performance timeline contract is invalid")
    performance_rows = timeline_contract.get("performance_windows")
    opaque_rows = timeline_contract.get("opaque_windows")
    if not isinstance(performance_rows, list) or not isinstance(opaque_rows, list):
        raise TimelineRendererError("source-audio performance timeline windows are invalid")

    def index_windows(rows: list[Any], *, mode: str) -> dict[str, Mapping[str, Any]]:
        indexed: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise TimelineRendererError("source-audio performance timeline window is invalid")
            region_id = str(row.get("region_id") or "").strip()
            if not region_id or region_id in indexed or row.get("audio_mode") != mode:
                raise TimelineRendererError("source-audio performance timeline window is invalid")
            indexed[region_id] = row
        return indexed

    performance = index_windows(performance_rows, mode="source_master")
    opaque = index_windows(opaque_rows, mode="opaque_audio_keep")
    remux_regions: list[dict[str, Any]] = []
    for region in contract_regions:
        policy = str(region.get("assembly_policy") or "").strip().lower()
        if policy in {"omit_source_end_card", "omit_source_tail", "omit"}:
            continue
        region_id = str(region.get("region_id") or "").strip()
        if not region_id:
            raise TimelineRendererError("source-audio timeline region ID is missing")
        start_us = int(region.get("source_start_us") or 0)
        end_us = int(region.get("source_end_us") or 0)
        if end_us <= start_us:
            raise TimelineRendererError("source-audio timeline region has invalid source bounds")
        if region_id in opaque:
            expected = opaque[region_id]
            if int(expected.get("source_start_ms")) * 1000 != start_us or int(expected.get("source_end_ms")) * 1000 != end_us:
                raise TimelineRendererError("opaque source-audio timeline window does not match the frozen region")
            remux_regions.append(
                {
                    "region_id": region_id,
                    "audio_mode": "opaque_audio_keep",
                    "media": region.get("media_path"),
                }
            )
            continue
        expected = performance.get(region_id)
        if expected is not None:
            if int(expected.get("source_start_ms")) * 1000 != start_us or int(expected.get("source_end_ms")) * 1000 != end_us:
                raise TimelineRendererError("source performance timeline window does not match the frozen region")
        remux_regions.append(
            {
                "region_id": region_id,
                "audio_mode": "source_master",
                "source_start_us": start_us,
                "source_end_us": end_us,
            }
        )
    if set(performance) - {str(item["region_id"]) for item in remux_regions}:
        raise TimelineRendererError("source performance timeline contract has an unrendered generated window")
    if set(opaque) - {str(item["region_id"]) for item in remux_regions}:
        raise TimelineRendererError("opaque source-audio timeline contract has an unrendered window")
    return remux_regions


def _rebind_visual_receipts_to_audio_remux(
    value: Any,
    *,
    visual_output_sha256: str,
    final_output_sha256: str,
) -> Any:
    if isinstance(value, dict):
        result = {
            key: _rebind_visual_receipts_to_audio_remux(
                item,
                visual_output_sha256=visual_output_sha256,
                final_output_sha256=final_output_sha256,
            )
            for key, item in value.items()
        }
        if str(result.get("final_output_sha256") or "").lower() == visual_output_sha256:
            result["visual_output_sha256"] = visual_output_sha256
            result["final_output_sha256"] = final_output_sha256
        return result
    if isinstance(value, list):
        return [
            _rebind_visual_receipts_to_audio_remux(
                item,
                visual_output_sha256=visual_output_sha256,
                final_output_sha256=final_output_sha256,
            )
            for item in value
        ]
    return value


def _fraction(value: Any, fallback: float) -> float:
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            result = float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            return fallback
        return result if result > 0 else fallback
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result if result > 0 else fallback


def _timeline_module():
    """Load the bundled timeline and its sibling dependencies by absolute path.

    The production compositor must not resolve ``concat_videos`` (or any other
    bundled sibling) through the process-wide bare-name import cache.  A
    private package gives the implementation a stable relative-import anchor,
    while the origin checks below make a preloaded or tampered module fail
    closed instead of silently changing the media backend.
    """

    root = Path(__file__).resolve().parents[1]
    scripts = root / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
    module_path = (scripts / "timeline_splice.py").resolve()
    if not scripts.is_dir() or not module_path.is_file():
        raise TimelineRendererError("bundled timeline splice implementation is unavailable")
    package_name = "_usfr_bundled_timeline_splice_pkg"
    module_name = f"{package_name}.timeline_splice"
    concat_name = f"{package_name}.concat_videos"
    media_quality_name = f"{package_name}.media_quality"
    existing = sys.modules.get(module_name)
    if existing is not None:
        existing_path = Path(str(getattr(existing, "__file__", ""))).resolve()
        if existing_path != module_path:
            raise TimelineRendererError(
                "bundled timeline splice implementation origin is invalid"
            )
        dependency = sys.modules.get(concat_name)
        concat_path = (scripts / "concat_videos.py").resolve()
        if dependency is None or Path(str(getattr(dependency, "__file__", ""))).resolve() != concat_path:
            raise TimelineRendererError(
                "bundled concat_videos dependency origin is invalid"
            )
        return existing
    concat_path = (scripts / "concat_videos.py").resolve()
    media_quality_path = (scripts / "media_quality.py").resolve()
    if not concat_path.is_file() or not media_quality_path.is_file():
        raise TimelineRendererError(
            "bundled timeline splice dependencies are unavailable"
        )
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [str(scripts)]
        package.__package__ = package_name
        sys.modules[package_name] = package
    else:
        package_path = tuple(str(item) for item in getattr(package, "__path__", ()))
        if package_path != (str(scripts),):
            raise TimelineRendererError(
                "bundled timeline package origin is invalid"
            )
    spec = importlib.util.spec_from_file_location(
        module_name,
        module_path,
        submodule_search_locations=None,
    )
    if spec is None or spec.loader is None:
        raise TimelineRendererError(
            "bundled timeline splice implementation is unavailable"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - import errors are deployment-specific
        if sys.modules.get(module_name) is module:
            sys.modules.pop(module_name, None)
        raise TimelineRendererError("bundled timeline splice implementation failed to load") from exc
    loaded_path = Path(str(getattr(module, "__file__", ""))).resolve()
    if loaded_path != module_path:
        sys.modules.pop(module_name, None)
        raise TimelineRendererError(
            "bundled timeline splice implementation origin is invalid"
        )
    loaded_concat = sys.modules.get(concat_name)
    if loaded_concat is None or Path(str(getattr(loaded_concat, "__file__", ""))).resolve() != concat_path:
        sys.modules.pop(module_name, None)
        raise TimelineRendererError(
            "bundled concat_videos dependency origin is invalid"
        )
    loaded_media_quality = sys.modules.get(media_quality_name)
    if loaded_media_quality is None or Path(str(getattr(loaded_media_quality, "__file__", ""))).resolve() != media_quality_path:
        sys.modules.pop(module_name, None)
        raise TimelineRendererError(
            "bundled media_quality dependency origin is invalid"
        )
    # Keep the historical private alias for callers that introspect it, but
    # never resolve the implementation through the bare ``timeline_splice``
    # name used by CLI/test harnesses.
    sys.modules["_usfr_bundled_timeline_splice"] = module
    return module


def _path_from_materialized(value: Any) -> Path:
    candidate = getattr(value, "path", value)
    path = Path(candidate).resolve()
    if not path.is_file():
        raise TimelineRendererError(f"materialized media does not exist: {path}")
    return path


def _frozen_segment_plan(
    *,
    plan_sha: str,
    context: Any,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    plan_sha = str(plan_sha or "").lower()
    if not _SHA256.fullmatch(plan_sha):
        raise TimelineRendererError(
            "timeline region requires its frozen segment_plan_sha256"
        )
    artifacts = [
        item
        for item in (getattr(context, "artifacts", ()) or ())
        if isinstance(item, Mapping)
        and item.get("kind") == "segment_plan"
        and str(item.get("sha256") or "").lower() == plan_sha
    ]
    if len(artifacts) != 1:
        raise TimelineRendererError(
            "timeline region requires exactly one matching frozen segment plan artifact"
        )
    metadata = artifacts[0].get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    canonical_json = metadata.get("canonical_json")
    if not isinstance(canonical_json, str):
        raise TimelineRendererError(
            "frozen segment plan artifact is missing canonical JSON"
        )
    if hashlib.sha256(canonical_json.encode("utf-8")).hexdigest() != plan_sha:
        raise TimelineRendererError(
            "frozen segment plan canonical JSON does not match its SHA-256"
        )
    try:
        plan = json.loads(canonical_json)
    except json.JSONDecodeError as exc:
        raise TimelineRendererError("frozen segment plan JSON is invalid") from exc
    segments = plan.get("segments") if isinstance(plan, Mapping) else None
    if (
        not isinstance(segments, list)
        or not 1 <= len(segments) <= 2
        or any(not isinstance(item, Mapping) for item in segments)
    ):
        raise TimelineRendererError(
            "frozen segment plan must contain one or two Segment objects"
        )
    result: list[tuple[str, tuple[str, ...]]] = []
    seen_segments: set[str] = set()
    seen_cuts: set[str] = set()
    for segment in segments:
        segment_id = str(segment.get("segment_id") or "").strip()
        raw_cuts = segment.get("cut_ids")
        if (
            not segment_id
            or segment_id in seen_segments
            or not isinstance(raw_cuts, list)
            or not raw_cuts
            or any(not isinstance(item, str) or not item.strip() for item in raw_cuts)
            or len(raw_cuts) != len(set(raw_cuts))
        ):
            raise TimelineRendererError("frozen segment plan has invalid Segment/Cut identities")
        cuts = tuple(str(item).strip() for item in raw_cuts)
        if seen_cuts.intersection(cuts):
            raise TimelineRendererError("frozen segment plan reuses a Cut identity")
        seen_segments.add(segment_id)
        seen_cuts.update(cuts)
        result.append((segment_id, cuts))
    return tuple(result)


def _frozen_binding_order(
    region: Mapping[str, Any],
    bindings: list[Mapping[str, Any]],
    *,
    context: Any,
) -> tuple[str, ...]:
    plan_sha = str(region.get("segment_plan_sha256") or "").lower()
    plan = _frozen_segment_plan(plan_sha=plan_sha, context=context)
    plan_ids = tuple(item[0] for item in plan)
    binding_ids = tuple(str(item.get("segment_id") or "") for item in bindings)
    if (
        any(not item for item in binding_ids)
        or len(binding_ids) != len(set(binding_ids))
        or binding_ids != tuple(item for item in plan_ids if item in set(binding_ids))
    ):
        raise TimelineRendererError(
            "timeline region bindings differ from the frozen segment plan order"
        )
    raw_region_cut_ids = region.get("cut_ids")
    if (
        not isinstance(raw_region_cut_ids, list)
        or not raw_region_cut_ids
        or any(not isinstance(item, str) or not item.strip() for item in raw_region_cut_ids)
        or len(raw_region_cut_ids) != len(set(raw_region_cut_ids))
    ):
        raise TimelineRendererError(
            "timeline region requires exact Cut membership"
        )
    region_cut_ids = [item.strip() for item in raw_region_cut_ids]
    segments_by_id = dict(plan)
    expected_cut_ids: list[str] = []
    for segment_id in binding_ids:
        segment = segments_by_id.get(segment_id)
        raw_segment_cut_ids = segment if segment is not None else None
        if not raw_segment_cut_ids:
            raise TimelineRendererError(
                "timeline region requires exact Cut membership"
            )
        expected_cut_ids.extend(raw_segment_cut_ids)
    if region_cut_ids != expected_cut_ids:
        raise TimelineRendererError(
            "timeline region bindings differ from frozen Segment Cut membership"
        )
    return plan_ids


def _reject_route_media_bindings(
    region: Mapping[str, Any],
    *,
    route_label: str,
    production: bool,
) -> None:
    if not production:
        return
    present = sorted(
        key for key in _MEDIA_BINDING_FIELDS if key in region and region.get(key) is not None
    )
    if present:
        raise TimelineRendererError(
            f"{route_label} route contains forbidden media binding fields: {', '.join(present)}"
        )


def _timeline_segment_bindings(
    regions: list[Mapping[str, Any]],
    *,
    context: Any,
    production: bool,
) -> dict[str, tuple[str, ...]]:
    """Validate the global frozen Segment/Cut closure for production timelines."""

    generated_regions = [
        region
        for region in regions
        if str(region.get("region_type") or region.get("kind") or "").strip().lower()
        == "generated"
        and str(region.get("media_origin") or "generated_media").strip().lower()
        == "generated_media"
    ]
    if not production:
        return {}
    if not generated_regions:
        return {}
    plan_shas = {
        str(region.get("segment_plan_sha256") or "").lower()
        for region in generated_regions
    }
    if len(plan_shas) != 1 or not next(iter(plan_shas), ""):
        raise TimelineRendererError(
            "production generated regions require one shared frozen segment plan"
        )
    plan_sha = next(iter(plan_shas))
    plan = _frozen_segment_plan(plan_sha=plan_sha, context=context)
    expected_ids = tuple(item[0] for item in plan)
    expected_cuts = tuple(cut for _segment, cuts in plan for cut in cuts)
    observed_ids: list[str] = []
    observed_cuts: list[str] = []
    for region in regions:
        kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
        origin = str(region.get("media_origin") or "generated_media").strip().lower()
        if kind != "generated" or origin != "generated_media":
            continue
        raw = region.get("media_artifact_bindings")
        if not isinstance(raw, list) or not raw:
            raise TimelineRendererError(
                "production ordinary generated regions require plural provider bindings"
            )
        if any(key in region and region.get(key) is not None for key in ("media_artifact_id", "artifact_id", "media_artifact_sha256", "artifact_sha256")):
            raise TimelineRendererError(
                "production ordinary generated regions cannot bypass plural provider bindings"
            )
        typed = [item for item in raw if isinstance(item, Mapping)]
        if len(typed) != len(raw):
            raise TimelineRendererError("production provider segment bindings must be objects")
        _frozen_binding_order(region, typed, context=context)
        observed_ids.extend(str(item.get("segment_id") or "").strip() for item in typed)
        raw_cuts = region.get("cut_ids")
        if not isinstance(raw_cuts, list):
            raise TimelineRendererError("production generated region requires exact Cut membership")
        observed_cuts.extend(str(item).strip() for item in raw_cuts)
    if tuple(observed_ids) != expected_ids:
        raise TimelineRendererError(
            "production provider Segment coverage/order differs from the frozen plan"
        )
    if tuple(observed_cuts) != expected_cuts:
        raise TimelineRendererError(
            "production provider Cut coverage/order differs from the frozen plan"
        )
    return {segment_id: cuts for segment_id, cuts in plan}


def _region_times(region: Mapping[str, Any]) -> tuple[int, int, float, float]:
    try:
        start_us = int(region.get("source_start_us"))
        end_us = int(region.get("source_end_us"))
    except (TypeError, ValueError):
        try:
            start = float(region.get("source_start") or region.get("start") or 0.0)
            end = float(region.get("source_end") or region.get("end") or 0.0)
        except (TypeError, ValueError) as exc:
            raise TimelineRendererError("timeline region time is invalid") from exc
        start_us = round(start * 1_000_000)
        end_us = round(end * 1_000_000)
    if start_us < 0 or end_us <= start_us:
        raise TimelineRendererError("timeline region must have a positive time range")
    return start_us, end_us, start_us / 1_000_000.0, end_us / 1_000_000.0


def _transition_phase(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"type": value}
    if not isinstance(value, Mapping):
        raise TimelineRendererError("transition shell phase must be an object")
    result = dict(value)
    if not result.get("type") and result.get("kind"):
        result["type"] = str(result["kind"])
    if result.get("duration_seconds") is None and result.get("duration_ms") is not None:
        try:
            duration_ms = float(result["duration_ms"])
        except (TypeError, ValueError) as exc:
            raise TimelineRendererError("transition shell duration_ms is invalid") from exc
        if duration_ms < 0:
            raise TimelineRendererError("transition shell duration_ms is invalid")
        result["duration_seconds"] = duration_ms / 1000.0
    result.pop("kind", None)
    result.pop("duration_ms", None)
    return result


def fit_transition_shell(
    *,
    shell: Mapping[str, Any],
    left_active_frames: int,
    right_active_frames: int,
) -> dict[str, Any]:
    requested = int(shell.get("duration_frames") or 0)
    available = min(
        max(left_active_frames - 1, 0),
        max(right_active_frames - 1, 0),
    )
    duration = min(requested, available)
    if requested > 0 and duration < 1:
        raise TimelineRendererError(
            "transition shell has no real active-frame overlap"
        )
    result = dict(shell)
    result["duration_frames"] = duration
    result["duration_adjusted"] = duration != requested
    return result


def _transition_shell(
    value: Any,
    *,
    index: int,
    region_count: int,
    expand_flat: bool,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TimelineRendererError("transition_shell must be an object")
    raw = dict(value)
    entry = raw.get("entry", raw.get("in"))
    exit_spec = raw.get("exit", raw.get("out"))
    shared = {
        key: raw[key]
        for key in ("audio", "z_order", "planned_transition")
        if key in raw
    }
    if entry is not None or exit_spec is not None:
        result: dict[str, Any] = dict(shared)
        if entry is not None:
            result["entry"] = _transition_phase(entry)
        if exit_spec is not None:
            result["exit"] = _transition_phase(exit_spec)
        return result or None
    if not expand_flat:
        return dict(raw)
    phase = _transition_phase(
        {
            key: item
            for key, item in raw.items()
            if key not in {"audio", "z_order", "planned_transition"}
        }
    )
    result = dict(shared)
    if index > 0:
        result["entry"] = dict(phase)
    if index + 1 < region_count:
        result["exit"] = dict(phase)
    return result or None


def _normalize_region_route(
    region: Mapping[str, Any],
    *,
    index: int,
    region_count: int,
) -> tuple[str, str, str, dict[str, Any] | None]:
    semantic_kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
    if not semantic_kind:
        raise TimelineRendererError(f"timeline region {index + 1} has no region_type")
    media_origin = str(region.get("media_origin") or "generated_media").strip().lower()
    assembly_policy = str(region.get("assembly_policy") or "").strip().lower()

    if semantic_kind in _SOURCE_KEEP_REGION_TYPES:
        kind = "generated"
        media_origin = "source_interval"
        assembly_policy = "splice_source_interval"
    elif semantic_kind in _OPAQUE_UI_REGION_TYPES:
        kind = "opaque_ui_demo"
        assembly_policy = assembly_policy or "splice_opaque_media"
    elif semantic_kind in _GENERATED_UI_REGION_TYPES:
        kind = "generated_ui_demo"
        media_origin = "generated_media"
        assembly_policy = assembly_policy or "generate_ui"
    elif semantic_kind in _OPAQUE_TAIL_REGION_TYPES:
        kind = "excluded_app_end_card"
        assembly_policy = assembly_policy or "splice_opaque_media"
    elif semantic_kind in _OMITTED_TAIL_REGION_TYPES:
        kind = "excluded_app_end_card"
        media_origin = "source_interval"
        assembly_policy = "omit_source_end_card"
    elif semantic_kind == "generated":
        kind = "generated"
        assembly_policy = assembly_policy or (
            "splice_source_interval" if media_origin == "source_interval" else "generate_region"
        )
    else:
        raise TimelineRendererError(
            f"timeline region {index + 1} has unsupported semantic route: {semantic_kind}"
        )

    flat_transition_route = semantic_kind in (
        _SOURCE_KEEP_REGION_TYPES
        | _OPAQUE_UI_REGION_TYPES
        | _GENERATED_UI_REGION_TYPES
        | _OPAQUE_TAIL_REGION_TYPES
    )
    transition_value = region.get("transition_shell")
    tail_append = (
        semantic_kind in _OPAQUE_TAIL_REGION_TYPES
        and media_origin != "source_interval"
        and region.get("source_tail_detected") is False
    )
    if tail_append:
        assembly_policy = "tail_append"
        if transition_value is None:
            transition_value = region.get("planned_transition_shell")
            if transition_value is None:
                raise TimelineRendererError(
                    "tail append without a source terminal shell requires a planned transition"
                )
            if isinstance(transition_value, Mapping):
                transition_value = {
                    **dict(transition_value),
                    "planned_transition": True,
                }
    transition = _transition_shell(
        transition_value,
        index=index,
        region_count=region_count,
        expand_flat=flat_transition_route,
    )
    return kind, media_origin, assembly_policy, transition


def _extract_source_interval(
    source: Path,
    destination: Path,
    *,
    start: float,
    duration: float,
    expect_audio: bool,
) -> Path:
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-ss",
        f"{start:.6f}",
        "-t",
        f"{duration:.6f}",
        "-map",
        "0:v:0",
    ]
    if expect_audio:
        command.extend(["-map", "0:a:0?"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-reset_timestamps",
            "1",
        ]
    )
    if expect_audio:
        command.extend(["-c:a", "aac", "-ar", "48000", "-ac", "2"])
    else:
        command.append("-an")
    command.extend(["-avoid_negative_ts", "make_zero", str(destination)])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise TimelineRendererError(
            f"source interval extraction failed: {result.stderr.strip()}"
        )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise TimelineRendererError("source interval extraction produced no media")
    return destination


def _prepare_opaque_ui_source_audio(
    *,
    source: Path,
    opaque: Path,
    output: Path,
    source_start: float,
    source_duration: float,
    active_start: float,
    active_duration: float,
) -> Path:
    """Use UI pixels only while keeping the source interval's master audio."""

    if source_duration <= 0 or active_duration <= 0:
        raise TimelineRendererError("opaque UI duration must be positive")
    speed_ratio = source_duration / active_duration
    if speed_ratio < 0.8 or speed_ratio > 1.2:
        raise TimelineRendererError(
            "UI_DURATION_FIT_UNSUPPORTED: active UI operation requires more than 20% speed adjustment"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{active_start:.6f}",
        "-t",
        f"{active_duration:.6f}",
        "-i",
        str(opaque),
        "-ss",
        f"{source_start:.6f}",
        "-t",
        f"{source_duration:.6f}",
        "-i",
        str(source),
        "-filter_complex",
        (
            f"[0:v]setpts={speed_ratio:.12f}*(PTS-STARTPTS),"
            f"trim=duration={source_duration:.6f}[v];"
            f"[1:a]aresample=48000,atrim=start=0:end={source_duration:.6f},"
            "asetpts=PTS-STARTPTS[a]"
        ),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        raise TimelineRendererError(
            "opaque UI could not be retimed with source audio: "
            + (completed.stderr.strip() or "ffmpeg produced no output")
        )
    return output


def _logical_media_label(region: Mapping[str, Any], *, source: bool = False) -> str:
    if source:
        start_us, end_us, _, _ = _region_times(region)
        return f"source_interval:{start_us}-{end_us}"
    artifact_sha = str(
        region.get("media_artifact_sha256")
        or region.get("artifact_sha256")
        or region.get("media_sha256")
        or ""
    ).lower()
    if _SHA256.fullmatch(artifact_sha):
        return f"artifact:{artifact_sha}"
    slot_id = str(
        region.get("slot_id")
        or region.get("input_slot_id")
        or region.get("media_slot_id")
        or ""
    ).strip()
    if slot_id:
        return f"slot:{slot_id}"
    return "lease_ephemeral_media"


def _declared_media_identity(
    region: Mapping[str, Any],
    *,
    context: Any,
) -> tuple[str | None, str | None, str | None]:
    """Return (slot_id, artifact_id, declared_sha) for a non-source carrier."""

    slot_id = next(
        (
            str(region.get(key)).strip()
            for key in ("slot_id", "input_slot_id", "media_slot_id")
            if str(region.get(key) or "").strip()
        ),
        None,
    )
    artifact_id = next(
        (
            str(region.get(key)).strip()
            for key in ("media_artifact_id", "artifact_id")
            if str(region.get(key) or "").strip()
        ),
        None,
    )
    declared = next(
        (
            str(region.get(key) or "").lower()
            for key in ("media_sha256", "media_artifact_sha256", "artifact_sha256")
            if _SHA256.fullmatch(str(region.get(key) or "").lower())
        ),
        None,
    )
    if declared is None and isinstance(region.get("ui_qc_report"), Mapping):
        candidate = str(region["ui_qc_report"].get("media_sha256") or "").lower()
        if _SHA256.fullmatch(candidate):
            declared = candidate
    if declared is None and slot_id:
        for item in getattr(context, "input_slots", ()) or ():
            if not isinstance(item, Mapping) or str(item.get("slot_id") or "") != slot_id:
                continue
            raw_sha = item.get("sha256")
            values = raw_sha if isinstance(raw_sha, (list, tuple)) else (raw_sha,)
            valid = [str(value).lower() for value in values if _SHA256.fullmatch(str(value or "").lower())]
            if len(valid) == 1:
                declared = valid[0]
                break
    if declared is None and artifact_id:
        for item in getattr(context, "artifacts", ()) or ():
            if isinstance(item, Mapping) and str(item.get("artifact_id") or "") == artifact_id:
                candidate = str(item.get("sha256") or "").lower()
                if _SHA256.fullmatch(candidate):
                    declared = candidate
                    break
    return slot_id, artifact_id, declared


def _redact_manifest(value: Any, *, path_labels: Mapping[str, str], output_path: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                _redact_manifest(item, path_labels=path_labels, output_path=output_path)
                if key not in {"media_path", "output_path"}
                else (
                    "assembled_video"
                    if key == "output_path"
                    else path_labels.get(str(item), "lease_ephemeral_media")
                )
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_manifest(item, path_labels=path_labels, output_path=output_path)
            for item in value
        ]
    if isinstance(value, str):
        resolved = str(Path(value).resolve()) if value else value
        if resolved == str(output_path.resolve()):
            return "assembled_video"
        return path_labels.get(resolved, value)
    return value


class BundledTimelineRenderer:
    """Execute the bundled FFmpeg timeline splice as a complete renderer.

    ``FfmpegCompositor`` remains the layer/publication boundary.  This class
    only renders the timeline and returns a sanitized manifest plus transition
    receipts; it never publishes an object-store artifact itself.
    """

    capability_kind = "timeline_renderer"
    supports_evidence_bound_mix = True

    def __init__(
        self,
        *,
        production: bool = False,
        implementation: str = "server.timeline_renderer:BundledTimelineRenderer",
        version: str = "1.1.0",
        sha256: str | None = None,
        audio_mixer: EvidenceBoundAudioMixer | None = None,
    ) -> None:
        self.production = bool(production)
        self.implementation = implementation
        self.version = version
        digest = str(sha256 or "").lower()
        if self.production and not _SHA256.fullmatch(digest):
            raise ValueError("production timeline renderer requires an explicit SHA-256")
        base_sha256 = digest or hashlib.sha256(
            f"{implementation}:{version}".encode("utf-8")
        ).hexdigest()
        self.audio_mixer = audio_mixer or EvidenceBoundAudioMixer(
            production=self.production,
            sha256=(
                _sha256_file(Path(__file__).resolve().with_name("audio_mixer.py"))
                if self.production
                else None
            ),
        )
        if not bool(getattr(self.audio_mixer, "supports_evidence_bound_mix", False)):
            raise ValueError("timeline renderer audio mixer lacks evidence-bound support")
        mixer_identity = self.audio_mixer.capability_identity()
        self.sha256 = hashlib.sha256(
            json.dumps(
                {
                    "base_renderer_sha256": base_sha256,
                    "audio_mixer": mixer_identity,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def capability_identity(self) -> dict[str, Any]:
        return {
            "capability_kind": self.capability_kind,
            "implementation": self.implementation,
            "version": self.version,
            "sha256": self.sha256,
            "audio_mixer": self.audio_mixer.capability_identity(),
            "supports_evidence_bound_mix": True,
        }

    def _materialize_region(
        self,
        region: Mapping[str, Any],
        *,
        context: Any,
        stack: ExitStack,
        stage_dir: Path | None = None,
        timeline_module: Any | None = None,
        expect_audio: bool | None = None,
    ) -> Path:
        local_path = region.get("media_path")
        allow_local = bool(getattr(context, "allow_local_paths", False))
        if self.production and allow_local:
            raise TimelineRendererError(
                "production timeline renderer cannot use local media paths"
            )
        region_type = str(region.get("region_type") or region.get("kind") or "").strip().lower()
        media_origin = str(region.get("media_origin") or "generated_media").strip().lower()
        if self.production and region_type == "generated" and media_origin == "generated_media":
            raw_bindings = region.get("media_artifact_bindings")
            if not isinstance(raw_bindings, list) or not raw_bindings:
                raise TimelineRendererError(
                    "production ordinary generated regions require plural provider bindings"
                )
        raw_bindings = region.get("media_artifact_bindings")
        if raw_bindings is not None:
            if not isinstance(raw_bindings, list) or not 1 <= len(raw_bindings) <= 2:
                raise TimelineRendererError(
                    "timeline region media_artifact_bindings must contain one or two entries"
                )
            materialize_artifact = getattr(context, "materialize_artifact", None)
            if not callable(materialize_artifact):
                raise TimelineRendererError(
                    "timeline region requires an artifact materializer for bound segments"
                )
            typed_bindings = [
                item for item in raw_bindings if isinstance(item, Mapping)
            ]
            if len(typed_bindings) != len(raw_bindings):
                raise TimelineRendererError(
                    "timeline region segment binding must be an object"
                )
            _frozen_binding_order(region, typed_bindings, context=context)
            region_plan_sha = str(region.get("segment_plan_sha256") or "").lower()
            segment_ids: set[str] = set()
            artifact_ids: set[str] = set()
            plan_shas: set[str] = set()
            paths: list[Path] = []
            for binding in typed_bindings:
                segment_id = str(binding.get("segment_id") or "").strip()
                plan_sha = str(binding.get("segment_plan_sha256") or "").lower()
                artifact_id = str(binding.get("artifact_id") or "").strip()
                artifact_sha = str(binding.get("sha256") or "").lower()
                kind = str(binding.get("kind") or "")
                if (
                    not segment_id
                    or segment_id in segment_ids
                    or kind != "provider_video"
                    or not artifact_id
                    or artifact_id in artifact_ids
                    or not _SHA256.fullmatch(artifact_sha)
                    or not _SHA256.fullmatch(plan_sha)
                ):
                    raise TimelineRendererError(
                        "timeline region has an invalid exact provider segment binding"
                )
                segment_ids.add(segment_id)
                artifact_ids.add(artifact_id)
                plan_shas.add(plan_sha)
                try:
                    value = materialize_artifact(
                        kind,
                        artifact_id=artifact_id,
                        sha256=artifact_sha,
                    )
                    if hasattr(value, "__enter__"):
                        value = stack.enter_context(value)
                    materialized_sha = _sha256_file(_path_from_materialized(value))
                    if materialized_sha != artifact_sha:
                        raise TimelineRendererError(
                            f"provider segment {segment_id} materialized with a different SHA-256"
                        )
                    paths.append(_path_from_materialized(value))
                except TimelineRendererError:
                    raise
                except Exception as exc:
                    raise TimelineRendererError(
                        f"could not materialize provider segment {segment_id}"
                    ) from exc
            if len(plan_shas) != 1 or (region_plan_sha and region_plan_sha not in plan_shas):
                raise TimelineRendererError(
                    "timeline region provider segments do not share its frozen segment plan"
                )
            if len(paths) == 1:
                return paths[0]

            if stage_dir is None:
                work_dir = Path(getattr(context, "work_dir", Path.cwd())).resolve()
                work_dir.mkdir(parents=True, exist_ok=True)
                stage_dir = Path(
                    tempfile.mkdtemp(prefix="timeline-segments-", dir=str(work_dir))
                )
                stack.callback(
                    lambda: __import__("shutil").rmtree(stage_dir, ignore_errors=True)
                )
            else:
                stage_dir = Path(stage_dir).resolve()
                stage_dir.mkdir(parents=True, exist_ok=True)
            region_token = re.sub(
                r"[^A-Za-z0-9_.-]+",
                "-",
                str(region.get("region_id") or "generated-region"),
            ).strip("-.") or "generated-region"
            binding_digest = hashlib.sha256(
                "\n".join(
                    f"{item.get('segment_id')}:{item.get('artifact_id')}:{item.get('sha256')}"
                    for item in typed_bindings
                ).encode("utf-8")
            ).hexdigest()[:12]
            combined = stage_dir / f"{region_token}-{binding_digest}-provider-segments.mp4"
            module = timeline_module or _timeline_module()
            try:
                module.concat_segments(
                    paths,
                    combined,
                    expect_audio=(
                        bool(getattr(context, "expect_audio", True))
                        if expect_audio is None
                        else bool(expect_audio)
                    ),
                )
            except Exception as exc:
                raise TimelineRendererError(
                    "could not concatenate exact provider segments for timeline region"
                ) from exc
            combined_path = _path_from_materialized(combined)
            return combined_path
        if local_path is not None and allow_local:
            return _path_from_materialized(local_path)

        slot_id = str(
            region.get("slot_id")
            or region.get("input_slot_id")
            or region.get("media_slot_id")
            or ""
        ).strip()
        materialize_slot = getattr(context, "materialize_slot", None)
        if slot_id and callable(materialize_slot):
            try:
                value = materialize_slot(slot_id)
                if hasattr(value, "__enter__"):
                    value = stack.enter_context(value)
                return _path_from_materialized(value)
            except Exception as exc:
                raise TimelineRendererError(
                    f"could not materialize timeline slot {slot_id}"
                ) from exc

        materialize_artifact = getattr(context, "materialize_artifact", None)
        if callable(materialize_artifact):
            artifact_id = region.get("media_artifact_id") or region.get("artifact_id")
            artifact_sha = region.get("media_artifact_sha256") or region.get("artifact_sha256")
            default_kind = (
                "provider_video"
                if region_type == "generated"
                else "generated_ui_video"
                if region_type in _GENERATED_UI_REGION_TYPES
                else "generated_media"
            )
            kind = str(
                region.get("media_artifact_kind")
                or region.get("artifact_kind")
                or default_kind
            )
            if not artifact_id and not artifact_sha:
                available = [
                    item
                    for item in (getattr(context, "artifacts", ()) or ())
                    if isinstance(item, Mapping)
                    and str(item.get("kind") or "") == kind
                ]
                region_tokens = {
                    str(region.get(key) or "").strip()
                    for key in ("region_id", "segment_id", "candidate_region_id")
                    if str(region.get(key) or "").strip()
                }
                matched: list[Mapping[str, Any]] = []
                if region_tokens:
                    for item in available:
                        metadata = item.get("metadata")
                        metadata = metadata if isinstance(metadata, Mapping) else {}
                        artifact_tokens = {
                            str(container.get(key) or "").strip()
                            for container in (item, metadata)
                            for key in (
                                "region_id",
                                "segment_id",
                                "candidate_region_id",
                            )
                            if str(container.get(key) or "").strip()
                        }
                        if region_tokens & artifact_tokens:
                            matched.append(item)
                selected = matched if matched else available
                if len(selected) == 1:
                    artifact_id = selected[0].get("artifact_id")
                    artifact_sha = selected[0].get("sha256")
                elif len(selected) > 1:
                    raise TimelineRendererError(
                        f"timeline region has ambiguous {kind} artifact binding"
                    )
            kwargs: dict[str, Any] = {"kind": kind}
            if artifact_id:
                kwargs["artifact_id"] = str(artifact_id)
            if artifact_sha:
                kwargs["sha256"] = str(artifact_sha).lower()
            try:
                value = materialize_artifact(**kwargs)
                if hasattr(value, "__enter__"):
                    value = stack.enter_context(value)
                return _path_from_materialized(value)
            except Exception as exc:
                raise TimelineRendererError(
                    f"could not materialize timeline artifact {kind}"
                ) from exc
        raise TimelineRendererError(
            "timeline region requires a verified slot/artifact materializer"
        )

    def _materialize_prebound_mixed_region(
        self,
        receipt: Mapping[str, Any],
        *,
        context: Any,
        stack: ExitStack,
    ) -> Path:
        mixed_sha256 = str(receipt.get("mixed_region_sha256") or "").lower()
        if not _SHA256.fullmatch(mixed_sha256):
            raise TimelineRendererError(
                "pre-bound audio mixer receipt has no current mixed-region binding"
            )
        matches = [
            dict(item)
            for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping)
            and str(item.get("sha256") or "").lower() == mixed_sha256
        ]
        if len(matches) != 1:
            raise TimelineRendererError(
                "pre-bound audio mix requires exactly one current mixed-region artifact"
            )
        artifact = matches[0]
        kind = str(artifact.get("kind") or "").strip()
        artifact_id = str(artifact.get("artifact_id") or "").strip()
        materialize_artifact = getattr(context, "materialize_artifact", None)
        if not kind or not callable(materialize_artifact):
            raise TimelineRendererError(
                "pre-bound audio mix requires a current artifact materializer"
            )
        kwargs: dict[str, Any] = {"sha256": mixed_sha256}
        if artifact_id:
            kwargs["artifact_id"] = artifact_id
        try:
            value = materialize_artifact(kind, **kwargs)
            if hasattr(value, "__enter__"):
                value = stack.enter_context(value)
            path = _path_from_materialized(value)
        except TimelineRendererError:
            raise
        except Exception as exc:
            raise TimelineRendererError(
                "could not materialize the pre-bound mixed-region artifact"
            ) from exc
        if _sha256_file(path) != mixed_sha256:
            raise TimelineRendererError(
                "pre-bound mixed-region artifact SHA-256 does not match current bytes"
            )
        return path

    def render(self, source: Path, output: Path, context: Any) -> Mapping[str, Any]:
        source = Path(source).resolve()
        output = Path(output).resolve()
        if not source.is_file():
            raise TimelineRendererError("timeline source media is unavailable")
        work_dir = Path(getattr(context, "work_dir", output.parent)).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        timeline_manifest_path = output.with_name(f"{output.stem}.timeline.json")
        raw_regions = [
            dict(item)
            for item in (getattr(context, "timeline_regions", ()) or ())
            if isinstance(item, Mapping)
        ]
        if not raw_regions:
            raise TimelineRendererError("timeline renderer requires timeline regions")

        module = _timeline_module()
        with ExitStack() as stack:
            stage_dir = Path(tempfile.mkdtemp(prefix="timeline-render-", dir=str(work_dir)))
            stack.callback(lambda: __import__("shutil").rmtree(stage_dir, ignore_errors=True))
            source_audio_contracts = _source_audio_contracts(context, stack=stack)
            source_info = module.probe_media(source)
            source_fps = _fraction(source_info.frame_rate, 30.0)
            expect_audio = bool(getattr(context, "expect_audio", source_info.has_audio))
            path_labels: dict[str, str] = {}
            contract_regions: list[dict[str, Any]] = []
            audio_mixer_receipts: list[dict[str, Any]] = []
            audio_mixer_verification_media: list[dict[str, Any]] = []
            audio_route_guard = getattr(context, "audio_route_guard", None)
            guarded_audio_regions = {
                str(item.get("region_id") or ""): dict(item)
                for item in (
                    audio_route_guard.get("regions", [])
                    if isinstance(audio_route_guard, Mapping)
                    else []
                )
                if isinstance(item, Mapping)
            }
            flattened_regions: list[dict[str, Any]] = []
            for raw in raw_regions:
                metadata = raw.get("metadata")
                flattened_regions.append(
                    {**dict(metadata), **dict(raw)}
                    if isinstance(metadata, Mapping)
                    else dict(raw)
                )
            if self.production:
                _timeline_segment_bindings(
                    flattened_regions,
                    context=context,
                    production=True,
                )
            for index, raw in enumerate(raw_regions, start=1):
                stored_metadata = raw.get("metadata")
                region = (
                    {**dict(stored_metadata), **dict(raw)}
                    if isinstance(stored_metadata, Mapping)
                    else dict(raw)
                )
                region.pop("metadata", None)
                start_us, end_us, start, end = _region_times(region)
                kind, media_origin, assembly_policy, transition_shell = _normalize_region_route(
                    region,
                    index=index - 1,
                    region_count=len(raw_regions),
                )
                if (
                    kind == "opaque_ui_demo"
                    and media_origin != "source_interval"
                    and region.get("source_interval_evidenced") is False
                    and region.get("approved_insertion_cut") is not True
                ):
                    raise TimelineRendererError(
                        "opaque UI without a source interval requires an approved insertion cut"
                    )
                if media_origin == "source_interval":
                    _reject_route_media_bindings(
                        region,
                        route_label="source/omitted",
                        production=self.production,
                    )
                    if self.production and "media_path" in region:
                        raise TimelineRendererError(
                            "source/omitted route contains forbidden media binding field: media_path"
                        )
                if (
                    self.production
                    and kind == "excluded_app_end_card"
                    and assembly_policy in {"omit_source_end_card", "omit_source_tail", "omit"}
                    and transition_shell is not None
                ):
                    raise TimelineRendererError(
                        "omitted source tail cannot declare a transition shell"
                    )
                if (
                    region.get("media_artifact_bindings") is not None
                    and (kind != "generated" or media_origin != "generated_media")
                ):
                    raise TimelineRendererError(
                        "provider bindings require generated/generated_media carrier"
                    )
                normalized = {
                    key: region[key]
                    for key in (
                        "region_id",
                        "duration_policy",
                        "transition_shell_applied",
                        "ui_truth_card",
                        "ui_render_contract",
                        "ui_qc_report",
                        "ui_qc_report_sha256",
                        "ui_truth_card_sha256",
                        "ui_render_contract_sha256",
                        "media_sha256",
                        "audio_policy",
                        "tail_append",
                        "planned_transition",
                    )
                    if key in region
                }
                provider_bindings = region.get("media_artifact_bindings")
                natural_generated = (
                    kind == "generated" and media_origin == "generated_media" and provider_bindings is not None
                )
                natural_ui = kind == "generated_ui_demo" and media_origin == "generated_media"
                if self.production and (natural_generated or natural_ui):
                    raw_policy = region.get("duration_policy")
                    if raw_policy not in {None, "natural_media_duration"}:
                        raise TimelineRendererError(
                            "production generated media requires natural_media_duration"
                        )
                    normalized["duration_policy"] = "natural_media_duration"
                if provider_bindings is not None:
                    normalized["duration_policy"] = "natural_media_duration"
                if transition_shell is not None:
                    normalized["transition_shell"] = transition_shell
                if (
                    kind == "excluded_app_end_card"
                    and media_origin != "source_interval"
                    and region.get("source_tail_detected") is False
                ):
                    normalized["tail_append"] = True
                    normalized["planned_transition"] = bool(
                        transition_shell
                        and transition_shell.get("planned_transition") is True
                    )
                if (
                    expect_audio
                    and media_origin == "source_interval"
                    and not source_info.has_audio
                    and "audio_policy" not in normalized
                ):
                    normalized["audio_policy"] = "silence_allowed"
                if "audio_policy" not in normalized:
                    if media_origin == "source_interval":
                        normalized["audio_policy"] = "source_audio_keep"
                    elif region.get("generate_audio") is True:
                        normalized["audio_policy"] = "generated_audio_contract"
                    elif kind in {"opaque_ui_demo", "excluded_app_end_card"}:
                        normalized["audio_policy"] = "opaque_audio_keep"
                    else:
                        normalized["audio_policy"] = "source_audio_keep"
                normalized.update(
                    {
                        "region_type": kind,
                        "source_start_us": start_us,
                        "source_end_us": end_us,
                        "media_origin": media_origin,
                        "assembly_policy": assembly_policy,
                    }
                )
                if kind == "excluded_app_end_card" and assembly_policy in {
                    "omit_source_end_card",
                    "omit_source_tail",
                    "omit",
                }:
                    # Missing tail media is an intentional omission route.
                    contract_regions.append(normalized)
                    continue
                if media_origin == "source_interval":
                    slice_path = stage_dir / f"source-{index:03d}.mp4"
                    _extract_source_interval(
                        source,
                        slice_path,
                        start=start,
                        duration=end - start,
                        expect_audio=expect_audio,
                    )
                    normalized["media_path"] = str(slice_path)
                    path_labels[str(slice_path.resolve())] = _logical_media_label(region, source=True)
                else:
                    media_path = self._materialize_region(
                        region,
                        context=context,
                        stack=stack,
                        stage_dir=stage_dir,
                        timeline_module=module,
                        expect_audio=expect_audio,
                    )
                    original_media_path = media_path
                    original_media_sha = _sha256_file(original_media_path)
                    normalized["media_path"] = str(original_media_path)
                    path_labels[str(original_media_path.resolve())] = _logical_media_label(region)
                    slot_id: str | None = None
                    artifact_id: str | None = None
                    declared_sha: str | None = None
                    if not isinstance(provider_bindings, list):
                        slot_id, artifact_id, declared_sha = _declared_media_identity(
                            region,
                            context=context,
                        )
                        if self.production and declared_sha is None:
                            raise TimelineRendererError(
                                "production non-source placement requires a trusted media SHA-256 declaration"
                            )
                        if declared_sha is not None and declared_sha != original_media_sha:
                            raise TimelineRendererError(
                                "non-source placement media SHA-256 does not match materialized bytes"
                            )
                    if kind == "opaque_ui_demo" and normalized["audio_policy"] == "source_audio_keep":
                        if not source_info.has_audio:
                            raise TimelineRendererError(
                                "source_audio_keep requires an audio stream in the source video"
                            )
                        try:
                            opaque_info = module.probe_media(original_media_path)
                            active_window = module.detect_active_window(
                                original_media_path,
                                duration=module._video_duration(opaque_info),
                                fps=module._replacement_fps(
                                    opaque_info,
                                    fallback=float(getattr(context, "target_fps", 30) or 30),
                                ),
                            )
                        except Exception as exc:
                            raise TimelineRendererError(
                                "opaque UI active-content analysis failed"
                            ) from exc
                        prepared_path = stage_dir / f"ui-source-audio-{index:03d}.mp4"
                        _prepare_opaque_ui_source_audio(
                            source=source,
                            opaque=original_media_path,
                            output=prepared_path,
                            source_start=start,
                            source_duration=end - start,
                            active_start=active_window.active_start,
                            active_duration=active_window.active_duration,
                        )
                        media_path = prepared_path
                        normalized["media_path"] = str(media_path)
                        path_labels[str(media_path.resolve())] = _logical_media_label(region)
                    guarded = guarded_audio_regions.get(
                        str(region.get("region_id") or "")
                    )
                    if (
                        normalized["audio_policy"] == "evidence_bound_mix"
                        and isinstance(guarded, Mapping)
                        and guarded.get("mixer_receipt_status")
                        == "verified_prebound_receipt"
                    ):
                        receipt = region.get("mixer_receipt")
                        if not isinstance(receipt, Mapping):
                            raise TimelineRendererError(
                                "pre-bound audio mixer receipt is missing"
                            )
                        if (
                            str(receipt.get("opaque_media_sha256") or "").lower()
                            != original_media_sha
                        ):
                            raise TimelineRendererError(
                                "pre-bound audio mixer receipt does not bind current opaque media"
                            )
                        verification_dir_value = getattr(
                            context,
                            "audio_mix_verification_dir",
                            None,
                        )
                        if verification_dir_value is None:
                            raise TimelineRendererError(
                                "evidence-bound mix requires compositor-owned verification storage"
                            )
                        verification_dir = Path(verification_dir_value).resolve()
                        verification_dir.mkdir(parents=True, exist_ok=True)
                        region_token = re.sub(
                            r"[^A-Za-z0-9_.-]+",
                            "-",
                            str(region.get("region_id") or f"region-{index}"),
                        ).strip("-.") or f"region-{index}"
                        verified_opaque_path = (
                            verification_dir
                            / f"{region_token}-{index:03d}-opaque.mp4"
                        )
                        mixed_path = (
                            verification_dir
                            / f"{region_token}-{index:03d}-mixed.mp4"
                        )
                        prebound_mixed_path = self._materialize_prebound_mixed_region(
                            receipt,
                            context=context,
                            stack=stack,
                        )
                        shutil.copyfile(original_media_path, verified_opaque_path)
                        shutil.copyfile(prebound_mixed_path, mixed_path)
                        audio_mixer_verification_media.append(
                            {
                                "region_id": str(
                                    region.get("region_id") or f"region-{index}"
                                ),
                                "opaque_media_path": verified_opaque_path,
                                "mixed_region_path": mixed_path,
                            }
                        )
                        media_path = mixed_path
                        normalized["media_path"] = str(media_path)
                        path_labels[str(media_path.resolve())] = _logical_media_label(
                            region
                        )
                    if (
                        normalized["audio_policy"] == "evidence_bound_mix"
                        and isinstance(guarded, Mapping)
                        and guarded.get("mixer_receipt_status")
                        == "pending_renderer_receipt"
                    ):
                        speech_windows = (
                            guarded.get("speech_windows")
                        )
                        if not isinstance(speech_windows, list) or not speech_windows:
                            raise TimelineRendererError(
                                "evidence-bound mix is missing frozen source speech windows"
                            )
                        try:
                            verification_dir_value = getattr(
                                context,
                                "audio_mix_verification_dir",
                                None,
                            )
                            if verification_dir_value is None:
                                raise TimelineRendererError(
                                    "evidence-bound mix requires compositor-owned verification storage"
                                )
                            verification_dir = Path(verification_dir_value).resolve()
                            verification_dir.mkdir(parents=True, exist_ok=True)
                            opaque_info = module.probe_media(original_media_path)
                            if not opaque_info.has_audio:
                                raise TimelineRendererError(
                                    "evidence-bound mix requires opaque target audio"
                                )
                            active_window = module.detect_active_window(
                                original_media_path,
                                duration=module._video_duration(opaque_info),
                                fps=module._replacement_fps(
                                    opaque_info,
                                    fallback=float(getattr(context, "target_fps", 30) or 30),
                                ),
                            )
                            region_token = re.sub(
                                r"[^A-Za-z0-9_.-]+",
                                "-",
                                str(region.get("region_id") or f"region-{index}"),
                            ).strip("-.") or f"region-{index}"
                            verified_opaque_path = (
                                verification_dir
                                / f"{region_token}-{index:03d}-opaque.mp4"
                            )
                            mixed_path = (
                                verification_dir
                                / f"{region_token}-{index:03d}-mixed.mp4"
                            )
                            shutil.copyfile(original_media_path, verified_opaque_path)
                            receipt = self.audio_mixer.mix_region(
                                source_media=source,
                                opaque_media=verified_opaque_path,
                                output_path=mixed_path,
                                region_id=str(region.get("region_id") or f"region-{index}"),
                                source_start_us=start_us,
                                source_end_us=end_us,
                                speech_windows=speech_windows,
                                mix_policy=(
                                    region.get("audio_mix_policy")
                                    if isinstance(region.get("audio_mix_policy"), Mapping)
                                    else None
                                ),
                                active_window=active_window,
                                source_media_sha256=str(
                                    getattr(context, "source_media_sha256", "") or ""
                                ),
                                opaque_media_sha256=declared_sha or original_media_sha,
                            )
                        except (AudioMixerError, TimelineRendererError):
                            raise
                        except Exception as exc:
                            raise TimelineRendererError(
                                "evidence-bound audio mixer failed"
                            ) from exc
                        audio_mixer_receipts.append(dict(receipt))
                        audio_mixer_verification_media.append(
                            {
                                "region_id": str(
                                    region.get("region_id") or f"region-{index}"
                                ),
                                "opaque_media_path": verified_opaque_path,
                                "mixed_region_path": mixed_path,
                            }
                        )
                        media_path = mixed_path
                        normalized["media_path"] = str(media_path)
                        path_labels[str(media_path.resolve())] = _logical_media_label(region)
                    actual_media_sha = _sha256_file(media_path)
                    if isinstance(provider_bindings, list):
                        binding_shas = [
                            str(binding.get("sha256") or "").lower()
                            for binding in provider_bindings
                            if isinstance(binding, Mapping)
                        ]
                        if any(not _SHA256.fullmatch(value) for value in binding_shas):
                            raise TimelineRendererError(
                                "provider segment binding has an invalid SHA-256"
                            )
                        carrier_sha256 = actual_media_sha
                        if len(binding_shas) == 1 and carrier_sha256 != binding_shas[0]:
                            raise TimelineRendererError(
                                "single provider segment carrier SHA-256 does not match its artifact"
                            )
                        carrier_sha256 = _sha256_file(media_path)
                        normalized["provider_carrier_receipts"] = [
                            {
                                "kind": "provider_video",
                                "segment_id": str(binding.get("segment_id")),
                                "artifact_id": str(binding.get("artifact_id")),
                                "artifact_sha256": str(binding.get("sha256")).lower(),
                                "segment_sha256": str(binding.get("sha256")).lower(),
                                "segment_plan_sha256": str(
                                    binding.get("segment_plan_sha256")
                                ).lower(),
                                "carrier_sha256": carrier_sha256,
                                "combined_carrier_sha256": carrier_sha256,
                            }
                            for binding in provider_bindings
                            if isinstance(binding, Mapping)
                        ]
                    else:
                        normalized["media_sha256"] = actual_media_sha
                        normalized["carrier_receipts"] = [
                            {
                                "kind": "timeline_media",
                                "region_id": str(region.get("region_id") or ""),
                                "media_origin": media_origin,
                                "slot_id": slot_id,
                                "artifact_id": artifact_id,
                                "media_sha256": actual_media_sha,
                                "carrier_sha256": actual_media_sha,
                            }
                        ]
                contract_regions.append(normalized)

            contract_path = stage_dir / "timeline-contract.json"
            target_width = getattr(context, "target_width", None) or source_info.display_width or source_info.width
            target_height = getattr(context, "target_height", None) or source_info.display_height or source_info.height
            target_fps = int(getattr(context, "target_fps", 0) or round(source_fps) or 30)
            contract = {
                "contract": "universal-timeline-regions",
                "contract_version": 1,
                "source_duration_us": round(source_info.video_duration * 1_000_000),
                "source_fps": source_fps,
                "target": {
                    "width": int(target_width),
                    "height": int(target_height),
                    "fps": target_fps,
                },
                "regions": contract_regions,
            }
            contract_path.write_text(
                json.dumps(contract, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            try:
                loaded = module.load_contract(contract_path)
                module.splice_timeline(
                    loaded,
                    output,
                    timeline_manifest_path,
                    expect_audio=expect_audio,
                    strict_output_receipts=self.production,
                )
            except Exception as exc:
                if isinstance(exc, TimelineRendererError):
                    raise
                raise TimelineRendererError(f"bundled timeline splice failed: {exc}") from exc
            if source_audio_contracts is not None:
                source_contract = source_audio_contracts[
                    "performance_audio_source_contract"
                ]
                timeline_contract = source_audio_contracts[
                    "performance_timeline_contract"
                ]
                splice_policy = source_audio_contracts["audio_splice_policy"]
                if (
                    source_contract.get("contract") != "performance-audio-source/v1"
                    or source_contract.get("mode") != "source_audio_replicate_v1"
                    or source_contract.get("authorization")
                    != {"status": "user_default_authorized", "scope": "current_run_only"}
                    or source_contract.get("provider_reference_audio") != "forbidden"
                ):
                    raise TimelineRendererError("source-audio performance source contract is invalid")
                source_audio_sha256 = str(
                    source_contract.get("source_audio_sha256") or ""
                ).lower()
                if not _SHA256.fullmatch(source_audio_sha256):
                    raise TimelineRendererError("source-audio performance source SHA-256 is invalid")
                if (
                    splice_policy.get("contract") != "audio-splice-policy/v1"
                    or str(splice_policy.get("source_audio_sha256") or "").lower()
                    != source_audio_sha256
                    or splice_policy.get("generated_audio")
                    != "mute_then_replace_with_exact_source_global_window"
                    or splice_policy.get("opaque_audio") != "keep_original_only"
                ):
                    raise TimelineRendererError("source-audio splice policy is invalid")
                forbidden_operations = splice_policy.get("forbidden_operations")
                if not isinstance(forbidden_operations, list) or not set(
                    SourceAudioPerformanceAssembler._FORBIDDEN_OPERATIONS
                ).issubset(set(forbidden_operations)):
                    raise TimelineRendererError("source-audio splice policy does not forbid time-warp operations")
                try:
                    manifest = json.loads(timeline_manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise TimelineRendererError(
                        "source-audio remux requires a valid rendered timeline manifest"
                    ) from exc
                visual_output_sha256 = _sha256_file(output)
                remux_regions = _source_audio_remux_regions(
                    contract_regions=contract_regions,
                    timeline_contract=timeline_contract,
                )
                try:
                    performance_receipt = SourceAudioPerformanceAssembler(
                        production=self.production
                    ).remux_rendered_timeline(
                        source_media=source,
                        rendered_video=output,
                        output_path=output,
                        source_media_sha256=str(
                            getattr(context, "source_media_sha256", "") or ""
                        )
                        or None,
                        source_audio_sha256=source_audio_sha256,
                        regions=remux_regions,
                        placements=list(manifest.get("placements") or []),
                        transition_receipts=list(manifest.get("transition_renders") or []),
                    )
                except AudioMixerError as exc:
                    raise TimelineRendererError(
                        f"source-audio performance remux failed: {exc}"
                    ) from exc
                final_output_sha256 = str(
                    performance_receipt["final_output_sha256"]
                ).lower()
                manifest = _rebind_visual_receipts_to_audio_remux(
                    manifest,
                    visual_output_sha256=visual_output_sha256,
                    final_output_sha256=final_output_sha256,
                )
                manifest["visual_output_sha256"] = visual_output_sha256
                manifest["source_audio_performance_receipt"] = performance_receipt
                manifest["final_output_sha256"] = final_output_sha256
                timeline_manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )

        if not output.is_file() or output.stat().st_size == 0:
            raise TimelineRendererError("complete timeline renderer produced no output")
        try:
            manifest = json.loads(timeline_manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TimelineRendererError("timeline renderer did not produce a valid manifest") from exc
        expected_verification_region_ids = {
            region_id
            for region_id, item in guarded_audio_regions.items()
            if item.get("audio_policy") == "evidence_bound_mix"
            and item.get("mixer_receipt_status")
            in {"pending_renderer_receipt", "verified_prebound_receipt"}
        }
        observed_verification_region_ids = {
            str(item.get("region_id") or "")
            for item in audio_mixer_verification_media
        }
        if observed_verification_region_ids != expected_verification_region_ids or len(
            audio_mixer_verification_media
        ) != len(expected_verification_region_ids):
            raise TimelineRendererError(
                "evidence-bound audio mixer verification media coverage is incomplete"
            )
        expected_mix_region_ids = {
            region_id
            for region_id, item in guarded_audio_regions.items()
            if item.get("audio_policy") == "evidence_bound_mix"
            and item.get("mixer_receipt_status") == "pending_renderer_receipt"
        }
        observed_mix_region_ids = {
            str(item.get("region_id") or "") for item in audio_mixer_receipts
        }
        if observed_mix_region_ids != expected_mix_region_ids or len(
            audio_mixer_receipts
        ) != len(expected_mix_region_ids):
            raise TimelineRendererError(
                "evidence-bound audio mixer receipt coverage is incomplete"
            )
        if audio_mixer_receipts:
            final_output_sha256 = _sha256_file(output)
            if str(manifest.get("final_output_sha256") or "").lower() != final_output_sha256:
                raise TimelineRendererError(
                    "timeline manifest does not bind the current mixed final output"
                )
            for receipt in audio_mixer_receipts:
                receipt["final_output_sha256"] = final_output_sha256
            manifest["audio_mixer_receipts"] = audio_mixer_receipts
        sanitized = _redact_manifest(
            manifest,
            path_labels=path_labels,
            output_path=output,
        )
        timeline_manifest_path.write_text(
            json.dumps(sanitized, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return {
            "output_path": output,
            "timeline_manifest_path": timeline_manifest_path,
            "timeline_manifest": sanitized,
            "audio_mixer_verification_media": audio_mixer_verification_media,
            "transition_render_receipts": list(sanitized.get("transition_renders") or []),
            "capability_identity": self.capability_identity(),
        }

    __call__ = render
