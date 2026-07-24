"""Deterministic source/target contract projection for Invocation A.

The public workflow already has a ``build_script`` stage.  This module is the
server-owned bridge used by that stage when a deployment handler returns only
the canonical analysis/route evidence.  It does not add a RunState stage or a
provider call; it materializes the immutable analysis artifact, projects its
validated factors, and emits the existing ``invocation_a_request`` shape.

The projection is intentionally conservative.  It never invents a claim,
source identity, UI state, voice line, or product fact.  If the evidence does
not support a generated candidate (or cannot fit the fixed 4--15 second
Seedance segment contract), it fails closed so the caller can keep the source
interval or request an operator correction.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .review_workflow import validate_target_selling_point

from .errors import ReplicationError
from .high_fidelity_envelope import (
    is_analysis_envelope,
    validate_analysis_envelope,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROUTE_GENERATED = {"generated", "generated_media"}
_SEMANTIC_GENERATED_REGION_TYPES = {"generated", "generated_video"}
_SEMANTIC_GENERATION_POLICIES = {"generate_region", "generate_video"}
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_MIN_SEGMENT_MS = 4_000
_MAX_SEGMENT_MS = 15_000
_MAX_RETIME_SOURCE_MS = 17_000
_MAX_SOURCE_MS = 30_000


def _route_value(value: Any) -> str:
    """Canonicalize route markers without changing ordinary semantic text.

    Timeline producers have historically emitted snake_case, kebab-case, and
    camelCase spellings for the same route-only lane.  Projection must make
    the decision on the marker itself (not on an arbitrary substring), while
    leaving ordinary generated regions untouched.
    """

    text = str(value or "").strip()
    text = _CAMEL_BOUNDARY.sub("_", text)
    text = re.sub(r"[-\s]+", "_", text)
    return text.lower()


def _sha_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def _slot_sha(slot: Mapping[str, Any]) -> str | None:
    values = slot.get("sha256")
    if isinstance(values, str):
        values = [values]
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
        for value in values:
            text = str(value or "").lower()
            if _SHA256.fullmatch(text):
                return text
    metadata = slot.get("metadata")
    if isinstance(metadata, Sequence) and not isinstance(metadata, (str, bytes, bytearray)):
        for item in metadata:
            if isinstance(item, Mapping):
                text = str(item.get("sha256") or "").lower()
                if _SHA256.fullmatch(text):
                    return text
    return None


def _slot_digests(context: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    slots = getattr(context, "input_slots", ()) or ()
    if isinstance(slots, Mapping):
        slots = slots.values()
    for slot in slots:
        if not isinstance(slot, Mapping) or not slot.get("present"):
            continue
        slot_id = str(slot.get("slot_id") or "").strip()
        if not slot_id:
            continue
        digest = _slot_sha(slot)
        if digest is None:
            values = slot.get("values")
            if isinstance(values, str):
                values = [values]
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)) and values:
                digest = _sha_json(str(values[0]))
        if digest:
            result[slot_id] = digest
    # ``input_artifacts`` is the immutable descriptor view exposed by the
    # worker context and is useful when a repository stores hashes there.
    for item in getattr(context, "input_artifacts", ()) or ():
        if not isinstance(item, Mapping):
            continue
        slot_id = str(item.get("slot_id") or "").strip()
        digest = str(item.get("sha256") or "").lower()
        if slot_id and _SHA256.fullmatch(digest) and slot_id not in result:
            result[slot_id] = digest
    if "source_video" not in result:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "high-fidelity Invocation A requires an immutable source_video digest",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    return dict(sorted(result.items()))


def _active_production_profile(context: Any) -> bool:
    """Return whether immutable evidence binding is mandatory for this run.

    Development contexts in the test/authoring surface often omit the worker's
    ``allow_local_paths`` flag.  Production ``WorkerStageContext`` sets it to
    ``False`` and freezes the profile activation mode, so the gate is narrow:
    it applies only to an active high-fidelity production run and never
    changes Shadow/legacy compatibility behavior.
    """

    profile = getattr(context, "profile_snapshot", None)
    if not isinstance(profile, Mapping) or profile.get("profile") != "high_fidelity_hybrid_v1":
        return False
    mode = str(profile.get("activation_mode") or "active").strip().lower()
    return mode not in {"shadow", "legacy", "disabled"} and getattr(context, "allow_local_paths", True) is False


def _trusted_evidence_digests(context: Any) -> set[str]:
    """Collect hashes already authorized by the run's immutable boundaries."""

    trusted: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").lower()
        if _SHA256.fullmatch(text):
            trusted.add(text)

    for slot in getattr(context, "input_slots", ()) or ():
        if not isinstance(slot, Mapping) or not slot.get("present"):
            continue
        values = slot.get("sha256")
        if isinstance(values, str):
            values = [values]
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            for value in values:
                add(value)
        metadata = slot.get("metadata")
        if isinstance(metadata, Sequence) and not isinstance(metadata, (str, bytes, bytearray)):
            for item in metadata:
                if isinstance(item, Mapping):
                    add(item.get("sha256"))

    artifacts = getattr(context, "artifacts", ()) or ()
    if isinstance(artifacts, Mapping):
        artifacts = artifacts.values()
    for artifact in artifacts:
        if isinstance(artifact, Mapping):
            add(artifact.get("sha256"))
            metadata = artifact.get("metadata")
            if isinstance(metadata, Mapping):
                add(metadata.get("sha256"))

    return trusted


def _iter_evidence_records(value: Any):
    """Yield nested high-fidelity evidence records without trusting IDs alone."""

    if isinstance(value, Mapping):
        if "evidence_id" in value:
            yield value
        for child in value.values():
            yield from _iter_evidence_records(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _iter_evidence_records(child)


def _validate_production_evidence_bindings(context: Any, analysis: Mapping[str, Any]) -> None:
    """Require every persisted analysis evidence record to bind real bytes.

    The schema historically required an object key but allowed a caller to
    invent that key without a byte digest.  In production this would let a
    fabricated source/target claim pass the structural analysis validator and
    reach Invocation A.  The fixed input slots and already-published upstream
    artifacts are the only trusted digest set at this boundary.
    """

    if not _active_production_profile(context):
        return
    trusted = _trusted_evidence_digests(context)
    if not trusted:
        raise ReplicationError(
            "EVIDENCE_DIGEST_UNBOUND",
            "EVIDENCE_DIGEST_UNBOUND: production high-fidelity analysis has no trusted source/target artifact digests",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    seen: set[int] = set()
    for record in _iter_evidence_records(analysis):
        marker = id(record)
        if marker in seen:
            continue
        seen.add(marker)
        digest = str(record.get("artifact_sha256") or "").lower()
        if _SHA256.fullmatch(digest) is None or digest not in trusted:
            raise ReplicationError(
                "EVIDENCE_DIGEST_UNBOUND",
                "EVIDENCE_DIGEST_UNBOUND: every production source/target evidence record must bind a trusted artifact SHA-256",
                category="contract",
                user_action_required=True,
                details={"evidence_id": str(record.get("evidence_id") or "")},
                http_status=422,
            )


def _validate_envelope_parent_digests(
    context: Any,
    envelope: Mapping[str, Any] | None,
) -> None:
    """Reject an envelope whose declared parents are stale or foreign.

    The envelope component hashes prove internal consistency.  Parent hashes
    additionally prove that the joined analysis belongs to this run's frozen
    uploads/published artifacts rather than another otherwise-valid run.
    Local authoring remains compatible when no parents were declared; active
    production requires at least one current parent binding.
    """

    if envelope is None:
        return
    parents = envelope.get("parent_digests")
    if parents is None:
        if _active_production_profile(context):
            raise ReplicationError(
                "EVIDENCE_DIGEST_UNBOUND",
                "canonical high-fidelity analysis envelope requires current-run parent digests",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        return
    if not isinstance(parents, Mapping) or not parents:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "canonical high-fidelity analysis envelope parent_digests must be non-empty",
            category="contract",
            user_action_required=True,
            http_status=422,
        )

    named: dict[str, str] = {}
    trusted = _trusted_evidence_digests(context)

    def register(name: Any, digest: Any) -> None:
        key = str(name or "").strip()
        value = str(digest or "").lower()
        if key and _SHA256.fullmatch(value):
            named.setdefault(key, value)
            trusted.add(value)

    for slot in getattr(context, "input_slots", ()) or ():
        if isinstance(slot, Mapping) and slot.get("present"):
            register(slot.get("slot_id"), _slot_sha(slot))
    artifacts = getattr(context, "artifacts", ()) or ()
    if isinstance(artifacts, Mapping):
        artifacts = artifacts.values()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        digest = artifact.get("sha256")
        metadata = artifact.get("metadata")
        if digest is None and isinstance(metadata, Mapping):
            digest = metadata.get("sha256")
        for key in (artifact.get("kind"), artifact.get("artifact_id"), artifact.get("slot_id")):
            register(key, digest)
    for artifact in getattr(context, "input_artifacts", ()) or ():
        if isinstance(artifact, Mapping):
            for key in (artifact.get("kind"), artifact.get("artifact_id"), artifact.get("slot_id")):
                register(key, artifact.get("sha256"))

    mismatches: list[str] = []
    for name, digest in parents.items():
        normalized = str(digest or "").lower()
        expected = named.get(str(name))
        if expected is not None:
            if normalized != expected:
                mismatches.append(str(name))
        elif normalized not in trusted:
            mismatches.append(str(name))
    if mismatches:
        raise ReplicationError(
            "EVIDENCE_DIGEST_UNBOUND",
            "canonical high-fidelity analysis envelope parent digest differs from current run evidence",
            category="contract",
            user_action_required=True,
            details={"mismatched_parent_digests": sorted(mismatches)},
            http_status=422,
        )


def _execution_route(context: Any, base: Mapping[str, Any]) -> str:
    route = str(base.get("route") or getattr(context, "execution_route", None) or "route_2")
    if route not in {"route_1", "route_2"}:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "build_script execution route must be route_1 or route_2",
            category="contract",
            user_action_required=True,
            details={"route": route},
            http_status=422,
        )
    return route


def _load_analysis_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "scripts" / "high_fidelity_analysis.py"
    spec = importlib.util.spec_from_file_location("usfr_high_fidelity_analysis_projection", path)
    if spec is None or spec.loader is None:
        raise ReplicationError("CONTRACT_INVALID", "packaged high-fidelity analysis module is unavailable", category="contract", http_status=422)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ReplicationError("CONTRACT_INVALID", "packaged high-fidelity analysis module failed to load", category="contract", details={"reason": str(exc)}, http_status=422) from exc
    return module


def _inline_artifact_payload(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for container in (item, item.get("metadata")):
        if not isinstance(container, Mapping):
            continue
        for key in ("inline_json", "payload", "content", "json"):
            value = container.get(key)
            if isinstance(value, Mapping):
                return value
            if isinstance(value, (bytes, bytearray)):
                try:
                    parsed = json.loads(bytes(value).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(parsed, Mapping):
                    return parsed
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, Mapping):
                    return parsed
    return None


def _read_analysis(context: Any, request: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    """Read the immutable semantic contract or canonical analysis envelope.

    A raw ``source_dynamics_analysis`` object is intentionally never returned
    as the semantic high-fidelity contract.  The two contracts have different
    schemas and must be joined by ``high_fidelity-analysis-envelope`` first.
    """

    def select(value: Any, *, source: str) -> Mapping[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        if is_analysis_envelope(value):
            try:
                return validate_analysis_envelope(value)
            except ValueError as exc:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "canonical high-fidelity analysis envelope is invalid",
                    category="contract",
                    user_action_required=True,
                    details={"source": source, "reason": str(exc)},
                    http_status=422,
                ) from exc
        if value.get("contract") == "reference-video-dynamics":
            raise ReplicationError(
                "CONTRACT_INVALID",
                "canonical high-fidelity analysis envelope is required; raw source_dynamics_analysis cannot drive Invocation A",
                category="contract",
                user_action_required=True,
                details={"source": source},
                http_status=422,
            )
        return dict(value)

    if isinstance(request, Mapping):
        for key in ("analysis_envelope", "high_fidelity_analysis", "analysis_contract", "analysis"):
            selected = select(request.get(key), source=f"request.{key}")
            if selected is not None:
                return selected
    for attr in ("high_fidelity_analysis", "analysis_contract", "analysis"):
        selected = select(getattr(context, attr, None), source=f"context.{attr}")
        if selected is not None:
            return selected
    artifacts = getattr(context, "artifacts", ()) or ()
    if isinstance(artifacts, Mapping):
        artifacts = artifacts.values()
    descriptor = next(
        (
            item
            for item in artifacts
            if isinstance(item, Mapping)
            and str(item.get("kind") or "") in {
                "high_fidelity_analysis",
                "high-fidelity-analysis",
                "high_fidelity_analysis_envelope",
                "high-fidelity-analysis-envelope",
            }
        ),
        None,
    )
    if isinstance(descriptor, Mapping):
        inline = _inline_artifact_payload(descriptor)
        if inline is not None:
            selected = select(inline, source="artifact")
            if selected is not None:
                return selected
    # The canonical worker carries the completed dynamics/ASR output in the
    # read-only stage-output cache for downstream existing stages. Prefer that
    # durable result before asking a deployment to materialize a separately
    # named high_fidelity_analysis artifact; this avoids a second analysis pass
    # while preserving the existing artifact path as the preferred authority.
    stage_outputs = getattr(context, "stage_outputs", {})
    if isinstance(stage_outputs, Mapping):
        prior = stage_outputs.get("analyze_dynamics")
        if isinstance(prior, Mapping):
            for key in ("analysis_envelope", "high_fidelity_analysis"):
                selected = select(prior.get(key), source=f"stage_outputs.analyze_dynamics.{key}")
                if selected is not None:
                    return selected
            if isinstance(prior.get("source_dynamics_analysis"), Mapping):
                # Do not silently reinterpret the dynamics sidecar as the
                # high-fidelity intent/claim/layer contract.
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "canonical high-fidelity analysis envelope is required; analyze_dynamics returned only source dynamics and audio contracts",
                    category="contract",
                    user_action_required=True,
                    details={"source": "stage_outputs.analyze_dynamics"},
                    http_status=422,
                )
    materialize = getattr(context, "materialize_artifact", None)
    if callable(materialize):
        try:
            with materialize("high_fidelity_analysis") as media:
                raw = Path(media.path).read_bytes()
            parsed = json.loads(raw.decode("utf-8"))
            selected = select(parsed, source="materialized_artifact")
            if selected is not None:
                return selected
        except Exception as exc:
            raise ReplicationError(
                "ARTIFACT_NOT_FOUND",
                "high-fidelity analysis artifact cannot be materialized",
                category="artifact",
                retryable=True,
                details={"reason": str(exc)},
                http_status=503,
            ) from exc
    raise ReplicationError(
        "CONTRACT_INVALID",
        "build_script requires the immutable high_fidelity_analysis artifact",
        category="contract",
        user_action_required=True,
        http_status=422,
    )


def _regions(context: Any, analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = getattr(context, "timeline_regions", ()) or analysis.get("timeline_regions") or ()
    if isinstance(raw, Mapping):
        raw = raw.get("regions") or []
    excluded_region_types = {
        "ui_demo",
        "opaque_ui_demo",
        "tail_card",
        "opaque_tail",
        "opaque_app_tail_card",
        "excluded_app_end_card",
        "omit_source_end_card",
        "generated_ui_demo",
        "generated_ui",
        "source_interval",
        "source_ui_keep",
        "source_tail_keep",
    }
    excluded_policies = {
        "splice_opaque_interval",
        "splice_source_interval",
        "append_opaque_tail",
        "omit_interval",
        "generate_ui",
        "generated_ui_demo",
        "render_generated_ui",
        "composite_generated_ui",
        "deterministic_ui_render",
    }
    candidates = [
        dict(item)
        for item in raw
        if isinstance(item, Mapping)
        and _route_value(item.get("region_type")) not in excluded_region_types
        and _route_value(item.get("assembly_policy")) not in excluded_policies
        and _route_value(item.get("region_type")) in _SEMANTIC_GENERATED_REGION_TYPES
        and _route_value(item.get("media_origin")) in _ROUTE_GENERATED
        and _route_value(item.get("assembly_policy")) in _SEMANTIC_GENERATION_POLICIES
    ]
    if not candidates:
        return []
    source_cuts = [item for item in (analysis.get("source_cuts") or []) if isinstance(item, Mapping)]
    for index, region in enumerate(candidates, start=1):
        cut_ids = region.get("cut_ids")
        if not isinstance(cut_ids, list) or not cut_ids:
            start = _as_int(region.get("source_start_us", region.get("start_us", 0)), f"timeline_regions[{index}].start_us")
            end = _as_int(region.get("source_end_us", region.get("end_us", 0)), f"timeline_regions[{index}].end_us")
            cut_ids = [
                f"C{int(cut.get('cut')):02d}"
                for cut in source_cuts
                if _as_int(cut.get("start_us", 0), "source cut start") >= start
                and _as_int(cut.get("end_us", 0), "source cut end") <= end
            ]
        region["cut_ids"] = [str(item) for item in cut_ids]
        if not region["cut_ids"]:
            raise ReplicationError("CONTRACT_INVALID", "generated timeline region has no source Cut IDs", category="contract", user_action_required=True, http_status=422)
    if len(candidates) > 2:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "more than two disjoint generated regions cannot fit the fixed Invocation A capacity",
            category="contract",
            user_action_required=True,
            details={"generated_region_count": len(candidates)},
            http_status=422,
        )
    return candidates


def _cut_by_id(analysis: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in analysis.get("source_cuts") or []:
        if not isinstance(item, Mapping):
            continue
        cut_id = item.get("cut_id")
        if isinstance(cut_id, str) and cut_id.strip():
            result[cut_id.strip()] = item
            continue
        if item.get("cut") is not None:
            result[f"C{int(item.get('cut')):02d}"] = item
    return result


def _analysis_parts(value: Mapping[str, Any]) -> tuple[
    Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, Mapping[str, Any] | None
]:
    """Return semantic analysis, dynamics, audio, and optional envelope."""

    if is_analysis_envelope(value):
        envelope = validate_analysis_envelope(value)
        return (
            envelope["high_fidelity_analysis"],
            envelope["source_dynamics_analysis"],
            envelope.get("audio_contract"),
            envelope,
        )
    audio = value.get("audio_contract") if isinstance(value.get("audio_contract"), Mapping) else None
    dynamics = value if isinstance(value.get("source_cuts"), list) else {}
    return value, dynamics, audio, None


def _extension_cuts(analysis: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    extension = (analysis.get("extensions") or {}).get("high_fidelity_hybrid_v1") if isinstance(analysis.get("extensions"), Mapping) else None
    if not isinstance(extension, Mapping):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for item in extension.get("semantic_cuts") or []:
        if not isinstance(item, Mapping):
            continue
        cut_id = item.get("cut_id")
        if isinstance(cut_id, str) and cut_id.strip():
            result[cut_id.strip()] = item
        elif item.get("cut") is not None:
            result[f"C{int(item.get('cut')):02d}"] = item
    return result


def _region_bounds(
    region: Mapping[str, Any],
    cuts: Sequence[str],
    by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[int, int]:
    start = region.get("source_start_us", region.get("start_us"))
    end = region.get("source_end_us", region.get("end_us"))
    if start is None or end is None:
        missing = [cut for cut in cuts if cut not in by_id]
        if missing:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "generated region references source Cuts absent from canonical dynamics",
                category="contract",
                user_action_required=True,
                details={"missing_cut_ids": missing},
                http_status=422,
            )
        start = min(_as_int(by_id[cut].get("start_us"), f"{cut}.start_us") for cut in cuts)
        end = max(_as_int(by_id[cut].get("end_us"), f"{cut}.end_us") for cut in cuts)
    start = _as_int(start, "region.start_us")
    end = _as_int(end, "region.end_us")
    if end <= start:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "generated region has invalid source bounds",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    return start, end


def _source_duration_ms(
    region: Mapping[str, Any],
    cuts: Sequence[str],
    by_id: Mapping[str, Mapping[str, Any]],
) -> int:
    start, end = _region_bounds(region, cuts, by_id)
    value = int(round((_as_int(end, "region.end_us") - _as_int(start, "region.start_us")) / 1000))
    if not _MIN_SEGMENT_MS <= value <= _MAX_SOURCE_MS:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "generated region duration must remain within the admitted 4--30 second source contract",
            category="contract",
            user_action_required=True,
            details={"duration_ms": value, "cut_ids": list(cuts)},
            http_status=422,
        )
    return value


def _record_value(value: Mapping[str, Any], key: str) -> Any:
    if key in value:
        return value.get(key)
    metadata = value.get("metadata")
    if isinstance(metadata, Mapping):
        return metadata.get(key)
    return None


def _explicit_output_bounds_ms(
    value: Mapping[str, Any],
    *,
    label: str,
) -> tuple[int, int] | None:
    start = _record_value(value, "output_start_ms")
    end = _record_value(value, "output_end_ms")
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"{label} must contain both output_start_ms and output_end_ms",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    start_ms = _as_int(start, f"{label}.output_start_ms")
    end_ms = _as_int(end, f"{label}.output_end_ms")
    if start_ms < 0 or end_ms <= start_ms:
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"{label} output timing is invalid",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    return start_ms, end_ms


def _map_source_ms(
    value_ms: int,
    *,
    source_start_ms: int,
    output_start_ms: int,
    scale: float,
) -> int:
    return output_start_ms + int(round((int(value_ms) - source_start_ms) * scale))


def _cut_output_bounds(
    *,
    cut_ids: Sequence[str],
    by_id: Mapping[str, Mapping[str, Any]],
    source_start_ms: int,
    source_end_ms: int,
    output_start_ms: int,
    output_end_ms: int,
    scale: float,
    require_explicit: bool,
) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    previous_end = output_start_ms
    for cut_id in cut_ids:
        cut = by_id.get(cut_id)
        if not isinstance(cut, Mapping) and len(cut_ids) == 1:
            # Compatibility for older validated high-fidelity artifacts that
            # carried one explicit generated region but no detached dynamics
            # Cut table.  Multi-Cut timing still requires canonical dynamics.
            cut = {
                "start_us": source_start_ms * 1000,
                "end_us": source_end_ms * 1000,
            }
        if not isinstance(cut, Mapping):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "generated region references source Cuts absent from canonical dynamics",
                category="contract",
                user_action_required=True,
                details={"missing_cut_ids": [cut_id]},
                http_status=422,
            )
        source_start_us = _as_int(cut.get("start_us"), f"{cut_id}.start_us")
        source_end_us = _as_int(cut.get("end_us"), f"{cut_id}.end_us")
        source_cut_start_ms = int(round(source_start_us / 1000))
        source_cut_end_ms = int(round(source_end_us / 1000))
        explicit = _explicit_output_bounds_ms(cut, label=f"Cut {cut_id}")
        mapped = (
            _map_source_ms(
                source_cut_start_ms,
                source_start_ms=source_start_ms,
                output_start_ms=output_start_ms,
                scale=scale,
            ),
            _map_source_ms(
                source_cut_end_ms,
                source_start_ms=source_start_ms,
                output_start_ms=output_start_ms,
                scale=scale,
            ),
        )
        if require_explicit and explicit is None:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "Route 1 requires approved output timing for every retimed Cut",
                category="contract",
                user_action_required=True,
                details={"cut_id": cut_id},
                http_status=422,
            )
        if explicit is not None:
            if scale != 1.0 and explicit != mapped:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "explicit Cut output timing differs from the approved retime projection",
                    category="contract",
                    user_action_required=True,
                    details={"cut_id": cut_id, "expected": mapped, "actual": explicit},
                    http_status=422,
                )
            bounds = explicit
        else:
            bounds = mapped
        if bounds[0] != previous_end or bounds[1] <= bounds[0]:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "projected Cut output timing must be continuous and ordered",
                category="contract",
                user_action_required=True,
                details={"cut_id": cut_id, "bounds": bounds},
                http_status=422,
            )
        result[cut_id] = bounds
        previous_end = bounds[1]
    if previous_end != output_end_ms:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "projected Cut output timing does not cover the generated region",
            category="contract",
            user_action_required=True,
            details={
                "expected_end_ms": output_end_ms,
                "actual_end_ms": previous_end,
            },
            http_status=422,
        )
    if source_end_ms <= source_start_ms:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "generated region source timing is invalid",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    return result


def _route1_output_timing_payload(
    *,
    regions: Sequence[Mapping[str, Any]],
    timing_plans: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
    extensions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    retimed_source_ids = {
        str(plan.get("source_region_id") or "")
        for plan in timing_plans
        if plan.get("require_explicit_action_timing") is True
    }
    region_rows: list[dict[str, Any]] = []
    cut_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    seen_cuts: set[str] = set()
    for region in regions:
        region_id = str(region.get("region_id") or "")
        if region_id not in retimed_source_ids:
            continue
        region_bounds = _explicit_output_bounds_ms(region, label=f"region {region_id}")
        if region_bounds is None:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "Route 1 approved output timing is missing its generated-region bounds",
                category="contract",
                user_action_required=True,
                details={"region_id": region_id},
                http_status=422,
            )
        cut_ids = [str(item) for item in region.get("cut_ids") or []]
        region_rows.append(
            {
                "region_id": region_id,
                "output_start_ms": region_bounds[0],
                "output_end_ms": region_bounds[1],
                "cut_ids": cut_ids,
            }
        )
        for cut_id in cut_ids:
            if cut_id in seen_cuts:
                continue
            cut = by_id.get(cut_id)
            if not isinstance(cut, Mapping):
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "Route 1 approved output timing references an unknown Cut",
                    category="contract",
                    user_action_required=True,
                    details={"cut_id": cut_id},
                    http_status=422,
                )
            cut_bounds = _explicit_output_bounds_ms(cut, label=f"Cut {cut_id}")
            if cut_bounds is None:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "Route 1 approved output timing is missing Cut bounds",
                    category="contract",
                    user_action_required=True,
                    details={"cut_id": cut_id},
                    http_status=422,
                )
            cut_rows.append(
                {
                    "cut_id": cut_id,
                    "output_start_ms": cut_bounds[0],
                    "output_end_ms": cut_bounds[1],
                }
            )
            seen_cuts.add(cut_id)
            extension = extensions.get(cut_id)
            action = extension.get("object_action") if isinstance(extension, Mapping) else None
            if not isinstance(action, Mapping):
                continue
            for state in action.get("state_sequence") or []:
                if not isinstance(state, Mapping):
                    continue
                state_bounds = _explicit_output_bounds_ms(
                    state,
                    label=f"{cut_id} action state",
                )
                if state_bounds is None:
                    raise ReplicationError(
                        "CONTRACT_INVALID",
                        "Route 1 approved output timing is missing action-state bounds",
                        category="contract",
                        user_action_required=True,
                        details={"cut_id": cut_id, "phase": state.get("phase")},
                        http_status=422,
                    )
                action_rows.append(
                    {
                        "cut_id": cut_id,
                        "phase": state.get("phase"),
                        "output_start_ms": state_bounds[0],
                        "output_end_ms": state_bounds[1],
                    }
                )
    return {
        "regions": region_rows,
        "cuts": cut_rows,
        "action_states": action_rows,
    }


def _validate_route1_timing_authority(
    value: Any,
    *,
    regions: Sequence[Mapping[str, Any]],
    timing_plans: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
    extensions: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    if not isinstance(value, Mapping) or value.get("kind") != "approved_script":
        raise ReplicationError(
            "CONTRACT_INVALID",
            "Route 1 retime requires approved script timing authority",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    script_sha256 = str(value.get("script_sha256") or "")
    output_timing_sha256 = str(value.get("output_timing_sha256") or "")
    if not _SHA256.fullmatch(script_sha256) or not _SHA256.fullmatch(output_timing_sha256):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "Route 1 approved script timing authority requires lowercase SHA-256 digests",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    timing_payload = _route1_output_timing_payload(
        regions=regions,
        timing_plans=timing_plans,
        by_id=by_id,
        extensions=extensions,
    )
    expected_timing_sha256 = _sha_json(timing_payload)
    if output_timing_sha256 != expected_timing_sha256:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "Route 1 approved script output timing digest differs from the projected timing",
            category="contract",
            user_action_required=True,
            details={
                "expected_output_timing_sha256": expected_timing_sha256,
                "actual_output_timing_sha256": output_timing_sha256,
            },
            http_status=422,
        )
    return {
        "kind": "approved_script",
        "script_sha256": script_sha256,
        "output_timing_sha256": output_timing_sha256,
    }


def _region_candidate_plans(
    *,
    region: Mapping[str, Any],
    cut_ids: Sequence[str],
    by_id: Mapping[str, Mapping[str, Any]],
    route: str,
    proposed_split_boundary_ms: Any,
) -> tuple[list[dict[str, Any]], int | None]:
    source_start_us, source_end_us = _region_bounds(region, cut_ids, by_id)
    source_start_ms = int(round(source_start_us / 1000))
    source_end_ms = int(round(source_end_us / 1000))
    source_duration_ms = _source_duration_ms(region, cut_ids, by_id)
    explicit_region = _explicit_output_bounds_ms(region, label="generated region")
    output_start_ms = explicit_region[0] if explicit_region is not None else source_start_ms
    require_explicit_retime = route == "route_1" and (
        _MAX_SEGMENT_MS < source_duration_ms <= _MAX_RETIME_SOURCE_MS
    )

    if _MAX_SEGMENT_MS < source_duration_ms <= _MAX_RETIME_SOURCE_MS:
        if require_explicit_retime and explicit_region is None:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "Route 1 cannot silently retime a 15--17 second region; approved output timing is required",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        output_end_ms = (
            explicit_region[1]
            if explicit_region is not None
            else output_start_ms + _MAX_SEGMENT_MS
        )
        if output_end_ms - output_start_ms != _MAX_SEGMENT_MS:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "15--17 second generated regions must freeze one approved 15-second output segment",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        scale = _MAX_SEGMENT_MS / source_duration_ms
    else:
        output_end_ms = explicit_region[1] if explicit_region is not None else source_end_ms
        if output_end_ms - output_start_ms != source_duration_ms:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "generated regions outside the 15--17 second retime window cannot change playback duration",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        scale = 1.0

    cut_bounds = _cut_output_bounds(
        cut_ids=cut_ids,
        by_id=by_id,
        source_start_ms=source_start_ms,
        source_end_ms=source_end_ms,
        output_start_ms=output_start_ms,
        output_end_ms=output_end_ms,
        scale=scale,
        require_explicit=require_explicit_retime,
    )
    source_region_id = str(region.get("region_id") or f"CR-{cut_ids[0]}")

    if source_duration_ms <= _MAX_RETIME_SOURCE_MS:
        if proposed_split_boundary_ms is not None:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "proposed_split_boundary_ms is not applicable to a region of 17 seconds or less",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        return [
            {
                "candidate_region_id": source_region_id,
                "source_region_id": source_region_id,
                "cut_ids": list(cut_ids),
                "source_start_us": source_start_us,
                "source_end_us": source_end_us,
                "output_start_ms": output_start_ms,
                "output_end_ms": output_end_ms,
                "retime_scale": scale,
                "cut_output_bounds": cut_bounds,
                "require_explicit_action_timing": require_explicit_retime,
            }
        ], None

    if proposed_split_boundary_ms is None:
        label = (
            "approved_split_boundary_ms"
            if route == "route_1"
            else "proposed_split_boundary_ms"
        )
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"{label} is required for a generated region longer than 17 seconds",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    if isinstance(proposed_split_boundary_ms, bool) or not isinstance(
        proposed_split_boundary_ms,
        int,
    ):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "proposed_split_boundary_ms must be an integer number of milliseconds",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    boundary_ms = proposed_split_boundary_ms
    boundary_index = None
    for index, (left_id, right_id) in enumerate(zip(cut_ids, cut_ids[1:])):
        if cut_bounds[left_id][1] == boundary_ms == cut_bounds[right_id][0]:
            boundary_index = index
            break
    if boundary_index is None:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "proposed_split_boundary_ms must match an exact Cut boundary",
            category="contract",
            user_action_required=True,
            details={"proposed_split_boundary_ms": boundary_ms},
            http_status=422,
        )
    grouped_cut_ids = [
        list(cut_ids[: boundary_index + 1]),
        list(cut_ids[boundary_index + 1 :]),
    ]
    plans: list[dict[str, Any]] = []
    for index, group in enumerate(grouped_cut_ids, start=1):
        start_ms = cut_bounds[group[0]][0]
        end_ms = cut_bounds[group[-1]][1]
        duration_ms = end_ms - start_ms
        if not _MIN_SEGMENT_MS <= duration_ms <= _MAX_SEGMENT_MS:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "proposed split creates a generated segment outside 4--15 seconds",
                category="contract",
                user_action_required=True,
                details={"segment_index": index, "duration_ms": duration_ms},
                http_status=422,
            )
        plans.append(
            {
                "candidate_region_id": f"{source_region_id}-P{index:02d}",
                "source_region_id": source_region_id,
                "cut_ids": group,
                "source_start_us": _as_int(by_id[group[0]].get("start_us"), f"{group[0]}.start_us"),
                "source_end_us": _as_int(by_id[group[-1]].get("end_us"), f"{group[-1]}.end_us"),
                "output_start_ms": start_ms,
                "output_end_ms": end_ms,
                "retime_scale": 1.0,
                "cut_output_bounds": {cut_id: cut_bounds[cut_id] for cut_id in group},
                "require_explicit_action_timing": False,
            }
        )
    return plans, boundary_ms


def _text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _phase_summary(value: Any, fallback: str) -> str:
    if not isinstance(value, Mapping):
        return fallback
    parts: list[str] = []
    for key in ("posture", "objective", "visible_tactic", "emotional_turn", "microphone_relation"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            parts.append(f"{key}={item.strip()}")
    for key in ("gaze_phases", "expression_phases", "gesture_phases"):
        phases = value.get(key)
        if isinstance(phases, list) and phases:
            rows = []
            for phase in phases:
                if not isinstance(phase, Mapping):
                    continue
                state = phase.get("target") or phase.get("state") or phase.get("path")
                if state:
                    rows.append(str(state))
            if rows:
                parts.append(f"{key}=" + " -> ".join(rows))
    return "; ".join(parts) or fallback


def _action_summary(value: Any, fallback: str) -> str:
    if not isinstance(value, Mapping):
        return fallback
    states = value.get("state_sequence")
    if isinstance(states, list):
        labels = [str(item.get("state")) for item in states if isinstance(item, Mapping) and item.get("state")]
        if labels:
            return " -> ".join(labels)
    return _text(value.get("movement_trajectory"), fallback)


def _audio_summary(
    audio: Mapping[str, Any] | None,
    *,
    start_us: int,
    end_us: int,
    speech: Mapping[str, Any] | None = None,
) -> tuple[str, list[str], list[str]]:
    if not isinstance(audio, Mapping):
        return "preserve source ambience and meaningful silence", [], []
    start_ms = start_us // 1000
    end_ms = max(start_ms + 1, int(round(end_us / 1000)))
    foley: list[str] = []
    music = False
    for index, event in enumerate(audio.get("audio_events") or [], start=1):
        if not isinstance(event, Mapping):
            continue
        try:
            ev_start = int(event.get("start_ms", 0))
            ev_end = int(event.get("end_ms", 0))
        except (TypeError, ValueError):
            continue
        if ev_end <= start_ms or ev_start >= end_ms:
            continue
        kind = str(event.get("kind") or "").lower()
        event_id = str(event.get("event_id") or f"AUDIO-{index:03d}")
        if kind in {"foley", "sfx", "sound_effect"}:
            foley.append(event_id)
        if kind == "music":
            music = True
    silence_ids: list[str] = []
    silence_values = audio.get("meaningful_silence", audio.get("silence_windows")) or []
    for index, window in enumerate(silence_values, start=1):
        if not isinstance(window, Mapping):
            continue
        try:
            win_start = int(window.get("start_ms", 0))
            win_end = int(window.get("end_ms", 0))
        except (TypeError, ValueError):
            continue
        if win_end > start_ms and win_start < end_ms:
            silence_ids.append(str(window.get("id") or f"SILENCE-{index:03d}"))
    speech_ids = []
    if isinstance(speech, Mapping):
        speech_ids = [str(item) for item in (speech.get("exact_asr_event_ids") or [])]
    summary = "preserve source ambience, room tone, and meaningful silence"
    if music:
        summary += "; preserve source music bed"
    if speech_ids:
        summary += "; preserve exact speech timing for ASR events " + ", ".join(speech_ids)
    if foley:
        summary += "; Foley events " + ", ".join(foley)
    return summary, foley, silence_ids


def _region_has_speech(
    region: Mapping[str, Any],
    audio: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(audio, Mapping):
        return False
    try:
        region_start_ms = int(
            region.get("source_start_us", region.get("start_us", 0))
        ) // 1000
        region_end_ms = int(
            region.get("source_end_us", region.get("end_us", 0))
        ) // 1000
    except (TypeError, ValueError):
        return False
    segments = audio.get("segments")
    if not isinstance(segments, Sequence) or isinstance(
        segments, (str, bytes, bytearray)
    ):
        return False
    for segment in segments:
        if not isinstance(segment, Mapping):
            continue
        try:
            start_ms = int(segment.get("start_ms"))
            end_ms = int(segment.get("end_ms"))
        except (TypeError, ValueError):
            continue
        if max(region_start_ms, start_ms) < min(region_end_ms, end_ms):
            return True
    return False


def _shot_budget(
    cuts: Sequence[str],
    by_id: Mapping[str, Mapping[str, Any]],
    duration_ms: int,
    *,
    region_start_us: int | None = None,
    output_start_ms: int | None = None,
    cut_output_bounds: Mapping[str, tuple[int, int]] | None = None,
    extensions: Mapping[str, Mapping[str, Any]] | None = None,
    analysis: Mapping[str, Any] | None = None,
    audio: Mapping[str, Any] | None = None,
    factors_by_cut: Mapping[str, Sequence[str]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    extensions = extensions or {}
    factors_by_cut = factors_by_cut or {}
    cut_output_bounds = cut_output_bounds or {}
    region_start_us = int(region_start_us or 0)
    output_start_ms = int(output_start_ms or 0)
    for index, cut_id in enumerate(cuts, start=1):
        if cut_id not in by_id and by_id:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "generated shot references a source Cut absent from canonical dynamics",
                category="contract",
                user_action_required=True,
                details={"cut_id": cut_id},
                http_status=422,
            )
        cut = by_id.get(cut_id, {})
        start = _as_int(cut.get("start_us", 0), f"{cut_id}.start_us")
        end = _as_int(cut.get("end_us", 0), f"{cut_id}.end_us")
        ext = extensions.get(cut_id, {})
        if not isinstance(ext, Mapping):
            ext = {}
        performance = ext.get("performance") if isinstance(ext.get("performance"), Mapping) else None
        action = ext.get("object_action") if isinstance(ext.get("object_action"), Mapping) else None
        speech = ext.get("speech_audio") if isinstance(ext.get("speech_audio"), Mapping) else None
        audio_text, _foley, _silence = _audio_summary(audio, start_us=start, end_us=end, speech=speech)
        scene = _text(cut.get("scene"), "preserve the evidenced source scene topology")
        camera = _text(cut.get("camera"), "preserve the evidenced source framing and camera path")
        lighting = _text(
            "; ".join(
                str(ext.get("lighting", {}).get(key))
                for key in ("key_origin", "hardness", "color_temperature_k")
                if isinstance(ext.get("lighting"), Mapping) and ext.get("lighting", {}).get(key) is not None
            ),
            "preserve the evidenced source lighting and shadow direction",
        )
        performance_text = _phase_summary(performance, "preserve the evidenced gaze, expression, posture, and gesture timing")
        action_text = _text(cut.get("action"), _action_summary(action, "preserve the evidenced action phases"))
        product_truth = "target feature → mechanism → benefit"
        commercial_proof = "target proof → CTA"
        if analysis:
            target_nodes = analysis.get("target_value_graph", {}).get("nodes", []) if isinstance(analysis.get("target_value_graph"), Mapping) else []
            for node in target_nodes:
                if isinstance(node, Mapping) and node.get("feature"):
                    try:
                        chain = validate_target_selling_point(
                            {
                                "feature": node.get("feature"),
                                "mechanism": node.get("mechanism") or node.get("how"),
                                "benefit": node.get("benefit") or node.get("value"),
                                "proof": (node.get("proof") or [{}])[0] if isinstance(node.get("proof"), Sequence) else node.get("proof"),
                                "cta": node.get("cta") or "try it now",
                            },
                            known_evidence_ids={str(item.get("evidence_id")) for item in node.get("evidence") or [] if isinstance(item, Mapping) and item.get("evidence_id")},
                        )
                    except Exception:
                        chain = None
                    if chain:
                        product_truth = f"{chain['feature']} → {chain['mechanism']} → {chain['benefit']}"
                        commercial_proof = f"{chain['proof'].get('evidence_id')} → {chain['cta']}"
                    break
        projected_bounds = cut_output_bounds.get(cut_id)
        if projected_bounds is not None:
            global_start_ms, global_end_ms = projected_bounds
            local_start_ms = global_start_ms - output_start_ms
            local_end_ms = global_end_ms - output_start_ms
        else:
            global_start_ms = None
            global_end_ms = None
            local_start_ms = max(0, int(round((start - region_start_us) / 1000)))
            local_end_ms = max(1, int(round((end - region_start_us) / 1000)))
        row = {
                "shot_id": f"SHOT-{index:02d}",
                "cut_id": cut_id,
                "start_ms": local_start_ms,
                "end_ms": local_end_ms,
                "duration_ms": max(1, local_end_ms - local_start_ms),
                "primary_action": str(cut.get("action") or "preserve the observed action phase"),
                "endpoint": str(cut.get("end_state") or "preserve the observed end state"),
                "scene": scene,
                "camera": camera,
                "lighting": lighting,
                "performance": performance_text,
                "action": action_text,
                "product_or_ui_truth": product_truth,
                "commercial_proof": commercial_proof,
                "transition": _text(cut.get("transition"), "preserve the source transition boundary"),
                "continuity": "preserve continuity from the preceding Cut and into the completed endpoint",
                "audio": audio_text,
                "factor_ids": list(factors_by_cut.get(cut_id) or []),
            }
        if global_start_ms is not None and global_end_ms is not None:
            row["output_global_start_ms"] = global_start_ms
            row["output_global_end_ms"] = global_end_ms
        rows.append(row)
    if not rows:
        raise ValueError("generated candidate has no shot cuts")
    # Derive durations from the already-rounded contiguous boundaries.  Only
    # the final endpoint is adjusted for a sub-millisecond source remainder;
    # no shot receives a synthetic 1 ms placeholder when canonical Cut timing
    # is available.
    for index, row in enumerate(rows):
        row["duration_ms"] = max(1, int(row["end_ms"]) - int(row["start_ms"]))
    delta = duration_ms - sum(int(item["duration_ms"]) for item in rows)
    rows[-1]["end_ms"] = int(rows[-1]["end_ms"]) + delta
    rows[-1]["duration_ms"] = int(rows[-1]["end_ms"]) - int(rows[-1]["start_ms"])
    if "output_global_end_ms" in rows[-1]:
        rows[-1]["output_global_end_ms"] = int(rows[-1]["output_global_end_ms"]) + delta
    if sum(int(item["duration_ms"]) for item in rows) != duration_ms:
        raise ValueError("shot budget does not cover candidate duration")
    return rows


def _required_factors(analysis: Mapping[str, Any], cut_ids: Sequence[str]) -> tuple[list[dict[str, Any]], list[str]]:
    cut_set = set(cut_ids)
    factors: list[dict[str, Any]] = []
    economized: list[str] = []
    for cut in analysis.get("layer_ledger") or []:
        if not isinstance(cut, Mapping) or str(cut.get("cut_id") or "") not in cut_set:
            continue
        for layer in cut.get("layers") or []:
            if not isinstance(layer, Mapping):
                continue
            factor_id = str(layer.get("factor_id") or "")
            if not factor_id:
                continue
            if str(layer.get("criticality") or "") == "H":
                route = str(layer.get("route") or "")
                upstream_carrier = str(layer.get("carrier") or "")
                if route == "OPAQUE_SPLICE" or upstream_carrier in {"opaque_media", "route_excluded"}:
                    carrier = "route_excluded"
                elif upstream_carrier == "seedance_generation":
                    carrier = "prompt"
                elif upstream_carrier in {"deterministic_composite", "audio_mix", "source_interval"}:
                    carrier = "postproduction"
                else:
                    carrier = "postproduction" if route in {"KEEP", "COMPOSITE", "REMOVE"} else "prompt"
                factors.append(
                    {
                        "factor_id": factor_id,
                        "cut_id": str(cut.get("cut_id") or ""),
                        "layer_id": str(layer.get("layer_id") or ""),
                        "source_pointer": f"/layer_ledger/{cut.get('cut_id')}/{layer.get('layer_id')}/{factor_id}",
                        "contract_pointer": str(
                            layer.get("contract_pointer")
                            or f"/layer_ledger/{cut.get('cut_id')}/{layer.get('layer_id')}/{factor_id}"
                        ),
                        "carrier": carrier,
                        "criticality": "H",
                    }
                )
            else:
                economized.append(factor_id)
    if not factors:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "generated region has no evidenced high-criticality factor to carry into Invocation A",
            category="contract",
            user_action_required=True,
            details={"cut_ids": list(cut_ids)},
            http_status=422,
        )
    return factors, sorted(set(economized))


def _candidate(
    *,
    region: Mapping[str, Any],
    timing_plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
    dynamics: Mapping[str, Any] | None = None,
    audio: Mapping[str, Any] | None = None,
    slots: Mapping[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cut_ids = [str(item) for item in timing_plan["cut_ids"]]
    dynamics = dynamics or {}
    by_id = _cut_by_id(dynamics if dynamics.get("source_cuts") else analysis)
    extensions = _extension_cuts(dynamics if dynamics.get("extensions") else analysis)
    output_start_ms = _as_int(timing_plan.get("output_start_ms"), "timing_plan.output_start_ms")
    output_end_ms = _as_int(timing_plan.get("output_end_ms"), "timing_plan.output_end_ms")
    duration_ms = output_end_ms - output_start_ms
    if not _MIN_SEGMENT_MS <= duration_ms <= _MAX_SEGMENT_MS:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "provisional generated candidate duration must remain within 4--15 seconds",
            category="contract",
            user_action_required=True,
            details={"duration_ms": duration_ms, "cut_ids": cut_ids},
            http_status=422,
        )
    source_start_us = _as_int(timing_plan.get("source_start_us"), "timing_plan.source_start_us")
    source_end_us = _as_int(timing_plan.get("source_end_us"), "timing_plan.source_end_us")
    retime_scale = float(timing_plan.get("retime_scale", 1.0))
    cut_output_bounds = timing_plan.get("cut_output_bounds")
    if not isinstance(cut_output_bounds, Mapping):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "candidate timing projection is missing Cut output bounds",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    factors, economized = _required_factors(analysis, cut_ids)
    factor_ids = [item["factor_id"] for item in factors]
    layer_names = {
        str(item.get("layer_id") or "").lower()
        for item in factors
    }
    if layer_names.intersection({"performance", "action", "gesture", "camera", "motion", "speech", "audio"}):
        primary = "motion"
        secondary = "identity" if layer_names.intersection({"character", "performer", "identity"}) else "scene"
    elif layer_names.intersection({"character", "performer", "identity"}):
        primary = "identity"
        secondary = "scene"
    else:
        primary = "scene"
        secondary = "identity"
    region_start_us = source_start_us
    factors_by_cut: dict[str, list[str]] = {}
    for factor in factors:
        factor_cut = str(factor.get("cut_id") or "")
        factors_by_cut.setdefault(factor_cut, []).append(str(factor["factor_id"]))
    shots = _shot_budget(
        cut_ids,
        by_id,
        duration_ms,
        region_start_us=region_start_us,
        output_start_ms=output_start_ms,
        cut_output_bounds=cut_output_bounds,
        extensions=extensions,
        analysis=analysis,
        audio=audio,
        factors_by_cut=factors_by_cut,
    )
    state_requirements: list[dict[str, Any]] = []
    performance: dict[str, str] = {"preserve_source": "exact observed gaze, posture, expression, and gesture timing"}
    for cut_id in cut_ids:
        cut = by_id.get(cut_id, {})
        ext = extensions.get(cut_id, {})
        action = ext.get("object_action") if isinstance(ext, Mapping) else None
        if isinstance(action, Mapping):
            for state in action.get("state_sequence") or []:
                if isinstance(state, Mapping):
                    explicit_state = _explicit_output_bounds_ms(
                        state,
                        label=f"{cut_id} action state",
                    )
                    if explicit_state is None and timing_plan.get("require_explicit_action_timing"):
                        raise ReplicationError(
                            "CONTRACT_INVALID",
                            "Route 1 requires approved output timing for every retimed action endpoint",
                            category="contract",
                            user_action_required=True,
                            details={"cut_id": cut_id, "phase": state.get("phase")},
                            http_status=422,
                        )
                    if explicit_state is not None:
                        state_global_start, state_global_end = explicit_state
                    else:
                        state_source_start_us = _as_int(
                            state.get("start_us", cut.get("start_us", source_start_us)),
                            "state.start_us",
                        )
                        state_source_end_us = _as_int(
                            state.get("end_us", cut.get("end_us", source_end_us)),
                            "state.end_us",
                        )
                        state_global_start = _map_source_ms(
                            int(round(state_source_start_us / 1000)),
                            source_start_ms=int(round(source_start_us / 1000)),
                            output_start_ms=output_start_ms,
                            scale=retime_scale,
                        )
                        state_global_end = _map_source_ms(
                            int(round(state_source_end_us / 1000)),
                            source_start_ms=int(round(source_start_us / 1000)),
                            output_start_ms=output_start_ms,
                            scale=retime_scale,
                        )
                    if (
                        state_global_start < output_start_ms
                        or state_global_end > output_end_ms
                        or state_global_end <= state_global_start
                    ):
                        raise ReplicationError(
                            "CONTRACT_INVALID",
                            "action state timing crosses its provisional candidate",
                            category="contract",
                            user_action_required=True,
                            details={"cut_id": cut_id, "phase": state.get("phase")},
                            http_status=422,
                        )
                    state_requirements.append(
                        {
                            "cut_id": cut_id,
                            "phase": str(state.get("phase") or "observed"),
                            "state": str(state.get("state") or "preserve observed state"),
                            "start_ms": state_global_start - output_start_ms,
                            "end_ms": state_global_end - output_start_ms,
                            "output_global_start_ms": state_global_start,
                            "output_global_end_ms": state_global_end,
                            "required": True,
                        }
                    )
        perf = ext.get("performance") if isinstance(ext, Mapping) else None
        if isinstance(perf, Mapping):
            performance["posture"] = str(perf.get("posture") or performance.get("posture") or "preserve observed posture")
            performance["objective"] = str(perf.get("objective") or "preserve observed objective")
    if not state_requirements:
        cut = by_id.get(cut_ids[-1], {})
        state_requirements = [
            {
                "cut_id": cut_ids[-1],
                "phase": "completed",
                "state": str(cut.get("end_state") or "preserve observed completed end state"),
                "start_ms": max(0, duration_ms - 1),
                "end_ms": duration_ms,
                "required": True,
            }
        ]
    if not any(item["phase"] == "completed" for item in state_requirements):
        state_requirements.append(
            {
                "cut_id": cut_ids[-1],
                "phase": "completed",
                "state": state_requirements[-1]["state"],
                "start_ms": max(0, duration_ms - 1),
                "end_ms": duration_ms,
                "required": True,
            }
        )
    roles: list[dict[str, Any]] = []
    role_names = {
        "new_model_image": "target character lock",
        "new_product_image": "target product lock",
        "ui_screenshot": "target UI truth",
        "app_store_url": "official App evidence",
    }
    for slot_id, role in role_names.items():
        if slot_id in slots and len(roles) < 4:
            roles.append({"slot": len(roles) + 1, "role": role})
    audio_text, foley_ids, silence_ids = _audio_summary(
        audio,
        start_us=source_start_us,
        end_us=source_end_us,
    )
    canonical_segment = {
        "segment_id": None,
        "start_ms": output_start_ms,
        "end_ms": output_end_ms,
        "duration_ms": duration_ms,
        "cut_ids": list(cut_ids),
        "shots": deepcopy(shots),
        "required_factor_ids": list(factor_ids),
        "reference_roles": deepcopy(roles),
    }
    prompt_carriers = [
        {"factor_id": item["factor_id"], "carrier": item["carrier"]}
        for item in factors
        if item["carrier"] in {"prompt", "reference", "payload"}
    ]
    postproduction_carriers = [
        {"factor_id": item["factor_id"], "carrier": item["carrier"]}
        for item in factors
        if item["carrier"] in {"postproduction", "route_excluded"}
    ]
    candidate = {
        "candidate_region_id": str(timing_plan.get("candidate_region_id")),
        "source_region_id": str(timing_plan.get("source_region_id")),
        "cut_ids": cut_ids,
        "required_factor_ids": factor_ids,
        "allowed_split_cut_ids": [],
        "forbidden_split_cut_ids": list(cut_ids),
        "duration_ms": duration_ms,
        "output_global_start_ms": output_start_ms,
        "output_global_end_ms": output_end_ms,
        "retime_scale": retime_scale,
        "primary_fidelity_spend": primary,
        "secondary_fidelity_spend": secondary,
        "economized_factors": economized,
        "mode": "fixed_b_image_reference",
        "single_take_or_multishot": "single_take" if len(cut_ids) == 1 else "multishot",
        "shot_budget": shots,
        "canonical_segment": canonical_segment,
        "reference_role_plan": roles,
        "background_strategy": "COMPOSITE" if any(slot in slots for slot in ("new_product_image", "new_model_image")) else "KEEP",
        "performance_strategy": performance,
        "action_state_requirements": state_requirements,
        "audio_strategy": {
            "music_policy": "preserve_source" if audio and any(str(item.get("kind") or "").lower() == "music" for item in audio.get("audio_events") or [] if isinstance(item, Mapping)) else "none",
            "ambience": audio_text,
            "foley_event_ids": foley_ids,
            "silence_window_ids": silence_ids,
        },
        "voiceover_timing_plan": [],
        "prompt_carrier_plan": prompt_carriers,
        "postproduction_carrier_plan": postproduction_carriers,
        "hard_blockers": [],
        "warnings": [],
    }
    return candidate, factors


def _project_interval_ms(
    value: dict[str, Any],
    *,
    label: str,
    timing_plan: Mapping[str, Any],
    route: str,
) -> None:
    start_ms = _as_int(value.get("start_ms"), f"{label}.start_ms")
    end_ms = _as_int(value.get("end_ms"), f"{label}.end_ms")
    if end_ms <= start_ms:
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"{label} timing is invalid",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    source_start_ms = int(round(_as_int(timing_plan.get("source_start_us"), "timing_plan.source_start_us") / 1000))
    source_end_ms = int(round(_as_int(timing_plan.get("source_end_us"), "timing_plan.source_end_us") / 1000))
    output_start_ms = _as_int(timing_plan.get("output_start_ms"), "timing_plan.output_start_ms")
    output_end_ms = _as_int(timing_plan.get("output_end_ms"), "timing_plan.output_end_ms")
    scale = float(timing_plan.get("retime_scale", 1.0))
    should_map = route == "route_2" and (
        scale != 1.0 or output_start_ms != source_start_ms
    )
    if should_map:
        if start_ms < source_start_ms or end_ms > source_end_ms:
            raise ReplicationError(
                "CONTRACT_INVALID",
                f"{label} falls outside the source candidate before retime",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        start_ms = _map_source_ms(
            start_ms,
            source_start_ms=source_start_ms,
            output_start_ms=output_start_ms,
            scale=scale,
        )
        end_ms = _map_source_ms(
            end_ms,
            source_start_ms=source_start_ms,
            output_start_ms=output_start_ms,
            scale=scale,
        )
    if start_ms < output_start_ms or end_ms > output_end_ms or end_ms <= start_ms:
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"{label} crosses or falls outside its provisional candidate",
            category="contract",
            user_action_required=True,
            details={
                "candidate_region_id": timing_plan.get("candidate_region_id"),
                "start_ms": start_ms,
                "end_ms": end_ms,
            },
            http_status=422,
        )
    value["start_ms"] = start_ms
    value["end_ms"] = end_ms


def _project_line_contracts(
    lines: Sequence[Mapping[str, Any]],
    *,
    timing_plans: Sequence[Mapping[str, Any]],
    candidates: Sequence[dict[str, Any]],
    route: str,
) -> list[dict[str, Any]]:
    candidate_by_id = {
        str(candidate["candidate_region_id"]): candidate
        for candidate in candidates
    }
    projected: list[dict[str, Any]] = []
    for raw in lines:
        if not isinstance(raw, Mapping):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "line_contracts must contain objects",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        line = deepcopy(dict(raw))
        timing = line.get("time")
        if not isinstance(timing, Mapping):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "line contract is missing its output-global time object",
                category="contract",
                user_action_required=True,
                details={"line_id": line.get("line_id")},
                http_status=422,
            )
        line_cut_ids = timing.get("cut_ids")
        if not isinstance(line_cut_ids, Sequence) or isinstance(
            line_cut_ids,
            (str, bytes, bytearray),
        ):
            line_cut_ids = [line.get("cut_id")]
        line_cut_set = {str(item) for item in line_cut_ids if item is not None}
        overlapping = [
            plan
            for plan in timing_plans
            if line_cut_set.intersection(str(item) for item in plan.get("cut_ids") or [])
        ]
        if not overlapping:
            # Source-origin and opaque-region dialogue is not part of the
            # Seedance candidate contract.
            continue
        matches = [
            plan
            for plan in overlapping
            if line_cut_set <= {str(item) for item in plan.get("cut_ids") or []}
        ]
        if len(matches) != 1:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "line contract crosses the proposed generated segment boundary",
                category="contract",
                user_action_required=True,
                details={"line_id": line.get("line_id")},
                http_status=422,
            )
        plan = matches[0]
        candidate_id = str(plan.get("candidate_region_id"))
        line["candidate_region_id"] = candidate_id
        line["segment_id"] = None
        line["time"] = dict(timing)
        _project_interval_ms(
            line["time"],
            label=f"line {line.get('line_id') or '<unknown>'}",
            timing_plan=plan,
            route=route,
        )
        line["time"]["duration_ms"] = (
            line["time"]["end_ms"] - line["time"]["start_ms"]
        )
        line["time"]["duration_is_derived"] = True
        line["time"]["time_base"] = "output_global_ms"
        line["time"]["segment_start_ms"] = None
        line["time"]["segment_end_ms"] = None
        for collection in ("proof_events", "foley_events", "silence_windows"):
            values = line.get(collection)
            if not isinstance(values, list):
                continue
            for index, raw_event in enumerate(values, start=1):
                if not isinstance(raw_event, Mapping):
                    raise ReplicationError(
                        "CONTRACT_INVALID",
                        f"{collection}[{index}] must be an object",
                        category="contract",
                        user_action_required=True,
                        http_status=422,
                    )
                event = dict(raw_event)
                _project_interval_ms(
                    event,
                    label=f"{collection}[{index}]",
                    timing_plan=plan,
                    route=route,
                )
                for key in (
                    "output_global_start_ms",
                    "output_global_end_ms",
                    "segment_start_ms",
                    "segment_end_ms",
                    "time_base",
                ):
                    event.pop(key, None)
                values[index - 1] = event
        music = line.get("music_policy")
        if isinstance(music, Mapping) and isinstance(music.get("windows"), list):
            line["music_policy"] = dict(music)
            for index, raw_window in enumerate(line["music_policy"]["windows"], start=1):
                if not isinstance(raw_window, Mapping):
                    raise ReplicationError(
                        "CONTRACT_INVALID",
                        f"music_policy.windows[{index}] must be an object",
                        category="contract",
                        user_action_required=True,
                        http_status=422,
                    )
                window = dict(raw_window)
                _project_interval_ms(
                    window,
                    label=f"music_policy.windows[{index}]",
                    timing_plan=plan,
                    route=route,
                )
                line["music_policy"]["windows"][index - 1] = window

        candidate = candidate_by_id[candidate_id]
        candidate["voiceover_timing_plan"].append(
            {"line_id": str(line.get("line_id")), "carrier": "prompt"}
        )
        candidate["audio_strategy"]["foley_event_ids"] = sorted(
            set(candidate["audio_strategy"]["foley_event_ids"])
            | {
                str(event.get("id"))
                for event in line.get("foley_events") or []
                if isinstance(event, Mapping) and event.get("id")
            }
        )
        candidate["audio_strategy"]["silence_window_ids"] = sorted(
            set(candidate["audio_strategy"]["silence_window_ids"])
            | {
                str(event.get("id"))
                for event in line.get("silence_windows") or []
                if isinstance(event, Mapping) and event.get("id")
            }
        )
        projected.append(line)
    return projected


def build_invocation_a_request(context: Any, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return an existing or deterministically projected Invocation-A request."""

    base = deepcopy(dict(request or {}))
    existing = base.get("invocation_a_request")
    if isinstance(existing, Mapping):
        if _active_production_profile(context):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "active production cannot bypass the canonical Invocation A projection",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        return dict(existing)
    loaded_analysis = _read_analysis(context, base)
    semantic_analysis, dynamics, audio, envelope = _analysis_parts(loaded_analysis)
    _validate_envelope_parent_digests(context, envelope)
    _validate_production_evidence_bindings(context, loaded_analysis)
    module = _load_analysis_module()
    try:
        module.validate_analysis(dict(semantic_analysis))
        projection = module.build_projection(dict(semantic_analysis))
    except Exception as exc:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "high-fidelity analysis cannot be projected into Invocation A",
            category="contract",
            user_action_required=True,
            details={"reason": str(exc)},
            http_status=422,
        ) from exc
    region_authority: Mapping[str, Any] = dynamics if dynamics else semantic_analysis
    if envelope is not None and not getattr(context, "timeline_regions", None):
        region_authority = {**dict(region_authority), "timeline_regions": envelope.get("timeline_regions")}
    regions = _regions(context, region_authority)
    projection_sha256 = str(envelope.get("projection_sha256")) if envelope is not None else None
    digests = _slot_digests(context)
    if projection_sha256 is not None:
        digests["analysis_envelope"] = projection_sha256
    route = _execution_route(context, base)
    if not regions:
        result = {
            "route": route,
            "candidate_regions": [],
            "line_contracts": [],
            "factor_coverage": [],
            "input_digests": digests,
        }
        if projection_sha256 is not None:
            result["projection_sha256"] = projection_sha256
            result["canonical_segments"] = []
        return result
    line_contracts = base.get("line_contracts")
    if not isinstance(line_contracts, list):
        exact_line_contract = base.get("exact_line_contract")
        if isinstance(exact_line_contract, Mapping) and isinstance(
            exact_line_contract.get("lines"), list
        ):
            line_contracts = exact_line_contract["lines"]
        elif isinstance(exact_line_contract, list):
            line_contracts = exact_line_contract
        else:
            line_contracts = []
    spoken_region_ids = [
        str(region.get("region_id") or f"region-{index}")
        for index, region in enumerate(regions, start=1)
        if _region_has_speech(region, audio)
    ]
    if spoken_region_ids and not line_contracts:
        raise ReplicationError(
            "EXACT_LINE_CONTRACT_REQUIRED",
            "EXACT_LINE_CONTRACT_REQUIRED: generated speech regions require "
            "approved exact line contracts before Invocation A",
            category="contract",
            user_action_required=True,
            details={"region_ids": spoken_region_ids},
            http_status=422,
        )
    by_id = _cut_by_id(dynamics if dynamics.get("source_cuts") else semantic_analysis)
    long_region_indexes = [
        index
        for index, region in enumerate(regions)
        if _source_duration_ms(
            region,
            [str(item) for item in region["cut_ids"]],
            by_id,
        )
        > _MAX_RETIME_SOURCE_MS
    ]
    split_value = None
    if route == "route_1":
        for key in ("approved_split_boundary_ms", "split_boundary_ms"):
            if base.get(key) is not None:
                split_value = base.get(key)
                break
    else:
        split_value = base.get("proposed_split_boundary_ms")
    if split_value is not None and len(long_region_indexes) != 1:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "proposed_split_boundary_ms is applicable only to one generated region longer than 17 seconds",
            category="contract",
            user_action_required=True,
            http_status=422,
        )

    candidates: list[dict[str, Any]] = []
    timing_plans: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    approved_boundary: int | None = None
    timing_authority: dict[str, str] | None = None
    for index, region in enumerate(regions):
        cut_ids = [str(item) for item in region["cut_ids"]]
        plans, boundary = _region_candidate_plans(
            region=region,
            cut_ids=cut_ids,
            by_id=by_id,
            route=route,
            proposed_split_boundary_ms=(
                split_value if index in long_region_indexes else None
            ),
        )
        if boundary is not None:
            approved_boundary = boundary
        for plan in plans:
            candidate, region_factors = _candidate(
                region=region,
                timing_plan=plan,
                analysis=semantic_analysis,
                dynamics=dynamics,
                audio=audio,
                slots=digests,
            )
            timing_plans.append(dict(plan))
            candidates.append(candidate)
            coverage.extend(
                {
                    **{
                        key: item[key]
                        for key in (
                            "factor_id",
                            "source_pointer",
                            "contract_pointer",
                            "carrier",
                            "criticality",
                        )
                    },
                    "candidate_region_id": candidate["candidate_region_id"],
                }
                for item in region_factors
            )
    if len(candidates) > 2:
        raise ReplicationError(
            "CONTRACT_INVALID",
            "Invocation A cannot plan more than two provisional generated candidates",
            category="contract",
            user_action_required=True,
            details={"candidate_count": len(candidates)},
            http_status=422,
        )
    if route == "route_1" and any(
        plan.get("require_explicit_action_timing") is True for plan in timing_plans
    ):
        timing_authority = _validate_route1_timing_authority(
            base.get("timing_authority"),
            regions=regions,
            timing_plans=timing_plans,
            by_id=by_id,
            extensions=_extension_cuts(dynamics),
        )
        digests["approved_script"] = timing_authority["script_sha256"]
        digests["approved_output_timing"] = timing_authority["output_timing_sha256"]
    line_contracts = _project_line_contracts(
        line_contracts,
        timing_plans=timing_plans,
        candidates=candidates,
        route=route,
    )
    authoritative_factor_ids = set(projection.get("required_factor_ids") or [])
    projected_factor_ids = {str(item["factor_id"]) for item in coverage}
    if not projected_factor_ids.issubset(authoritative_factor_ids):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "Invocation A factor coverage differs from the validated high-fidelity projection",
            category="contract",
            user_action_required=True,
            details={"unexpected_factor_ids": sorted(projected_factor_ids - authoritative_factor_ids)},
            http_status=422,
        )
    result = {
        "route": route,
        "candidate_regions": candidates,
        "line_contracts": line_contracts,
        "factor_coverage": coverage,
        "input_digests": digests,
    }
    if timing_authority is not None:
        result["timing_authority"] = timing_authority
    if approved_boundary is not None:
        result["proposed_split_boundary_ms"] = approved_boundary
    if projection_sha256 is not None:
        result["projection_sha256"] = projection_sha256
        result["canonical_segments"] = [
            deepcopy(candidate["canonical_segment"])
            for candidate in candidates
        ]
    return result


__all__ = ["build_invocation_a_request"]
