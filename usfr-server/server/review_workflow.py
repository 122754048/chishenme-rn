from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ReplicationError
from .review_models import RevisionKind, RevisionManifest, ReviewRoute

SCRIPT_INVALIDATIONS = ("storyboard", "segment_plan", "prompt_audit", "provider_plan", "assembly", "qc")
STORYBOARD_INVALIDATIONS = ("segment_plan", "prompt_audit", "provider_plan", "assembly", "qc")
_SCRIPT_FIELDS = {"cut_id", "start_ms", "end_ms", "scene", "action", "camera", "dialogue", "delivery", "audio_events", "selling_point", "proof", "visual", "evidence_ids", "route"}


SUPPORTED_OUTPUT_LANGUAGES = ("en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh")


def resolve_review_route(*, seedance_required: bool, approved_script: RevisionManifest | None, current_script_inputs_sha256: str, output_language: str | None = None, approved_output_language: str | None = None) -> ReviewRoute:
    if not seedance_required:
        return "local_only"
    if output_language is not None and output_language not in SUPPORTED_OUTPUT_LANGUAGES:
        raise ReplicationError("INVALID_INPUT", "output_language is unsupported")
    language_matches = approved_output_language is None or output_language is None or approved_output_language == output_language
    if approved_script is not None and approved_script.status == "APPROVED" and approved_script.inputs_sha256 == current_script_inputs_sha256 and language_matches:
        return "route_1"
    return "route_2"


def downstream_invalidations(kind: RevisionKind) -> tuple[str, ...]:
    if kind == "script":
        return SCRIPT_INVALIDATIONS
    if kind == "storyboard":
        return STORYBOARD_INVALIDATIONS
    raise ReplicationError("INVALID_INPUT", "kind must be script or storyboard")


def select_storyboard_regeneration(*, ordered_cut_ids: tuple[str, ...], requested_cut_ids: tuple[str, ...], continuity_affected_cut_ids: tuple[str, ...]) -> tuple[str, ...]:
    selected = set(requested_cut_ids) | set(continuity_affected_cut_ids)
    return tuple(cut_id for cut_id in ordered_cut_ids if cut_id in selected)


def validate_target_selling_point(value: Mapping[str, Any], *, known_evidence_ids: set[str] | Sequence[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplicationError("CONTRACT_INVALID", "selling_point must be a mapping")
    required = ("feature", "mechanism", "benefit", "proof", "cta")
    missing = [key for key in required if not str(value.get(key) or "").strip() and key != "proof"]
    if missing:
        raise ReplicationError("CONTRACT_INVALID", "selling point value chain is incomplete", details={"missing": missing})
    proof = value.get("proof")
    evidence_id = proof.get("evidence_id") if isinstance(proof, Mapping) else None
    if not isinstance(evidence_id, str) or evidence_id not in set(known_evidence_ids):
        raise ReplicationError("CONTRACT_INVALID", "selling point proof is not target-evidence backed")
    return {key: value[key] for key in required}


def validate_script_revision(cuts: Sequence[Mapping[str, Any]], *, known_evidence_ids: set[str] | Sequence[str] = (), route: str | None = None, output_language: str | None = None) -> tuple[dict[str, Any], ...]:
    if not isinstance(cuts, Sequence) or isinstance(cuts, (str, bytes, bytearray)) or not cuts:
        raise ReplicationError("CONTRACT_INVALID", "script revision must contain Cuts")
    evidence = set(known_evidence_ids)
    if output_language is not None and output_language not in SUPPORTED_OUTPUT_LANGUAGES:
        raise ReplicationError("INVALID_INPUT", "output_language is unsupported")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    previous_end: int | None = None
    for index, raw in enumerate(cuts):
        if not isinstance(raw, Mapping):
            raise ReplicationError("CONTRACT_INVALID", "Cut must be an object", details={"index": index})
        missing = sorted(_SCRIPT_FIELDS - set(raw))
        if missing:
            raise ReplicationError("CONTRACT_INVALID", "Cut is missing required fields", details={"index": index, "missing": missing})
        cut_id = raw.get("cut_id")
        if not isinstance(cut_id, str) or not cut_id or cut_id in seen:
            raise ReplicationError("CONTRACT_INVALID", "Cuts must have unique non-empty cut_id")
        seen.add(cut_id)
        try:
            start, end = int(raw["start_ms"]), int(raw["end_ms"])
        except (TypeError, ValueError) as exc:
            raise ReplicationError("CONTRACT_INVALID", "Cut timing must be integer milliseconds") from exc
        if start < 0 or end <= start or (previous_end is not None and start != previous_end):
            raise ReplicationError("CONTRACT_INVALID", "Cuts must be contiguous, non-overlapping, and ordered")
        selling = validate_target_selling_point(raw["selling_point"], known_evidence_ids=evidence)
        ids = raw.get("evidence_ids")
        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes, bytearray)) or any(item not in evidence for item in ids):
            raise ReplicationError("CONTRACT_INVALID", "Cut evidence_ids must reference known target evidence")
        cut_route = raw.get("route")
        if route is not None and cut_route != route:
            raise ReplicationError("CONTRACT_INVALID", "Cut route differs from revision route")
        if cut_route == "local_only" and (raw.get("ui_text") or raw.get("tail_text") or raw.get("ui") or raw.get("tail")):
            raise ReplicationError("CONTRACT_INVALID", "local-only route cannot contain UI or tail text")
        if output_language is not None:
            declared = raw.get("output_language") or raw.get("language")
            if declared is not None and declared != output_language:
                raise ReplicationError("CONTRACT_INVALID", "dialogue language differs from selected output_language")
        item = dict(raw)
        item["selling_point"] = selling
        normalized.append(item)
        previous_end = end
    return tuple(normalized)
