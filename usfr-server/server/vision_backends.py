"""Evidence-bound OCR and VLM HTTP adapters for production workers.

The public workflow remains provider-neutral.  These adapters define a small
sidecar contract that can wrap a locally deployed model (for example
PP-OCRv5/Qwen-VL) or a private remote service.  A worker sends media bytes,
never a workstation or lease-local path, and accepts a response only when it
echoes the exact request, input bytes, sampled frames, and pinned model SHA.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping, Sequence
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest
import unicodedata

from PIL import Image

from .errors import ReplicationError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


_HF_EXTENSION_KEYS = {
    "schema_version",
    "analysis_pass_count",
    "semantic_cuts",
    "route_excluded_intervals",
}
_HF_SEMANTIC_CUT_KEYS = {
    "cut",
    "scene_topology",
    "framing_migration",
    "lighting",
    "performance",
    "object_action",
    "speech_audio",
    "evidence",
    "observed_inferred_planned",
    "confidence",
    "uncertainty",
    "criticality",
    "blocker_threshold",
}
_HF_ROUTE_EXCLUDED_KEYS = {
    "cut",
    "region_type",
    "start_us",
    "end_us",
    "transition_shell",
    "technical_stream",
}
_HF_SCENE_KEYS = {
    "entities",
    "spatial_relations",
    "occlusion_order",
    "table_line_y",
    "horizon_y",
    "negative_space",
}
_HF_ENTITY_KEYS = {
    "entity_id",
    "layer",
    "bbox",
    "z_order",
    "relation_to_camera",
}
_HF_FRAMING_KEYS = {"strategy", "anchors", "topology_constraint"}
_HF_ANCHOR_KEYS = {"anchor_id", "bbox"}
_HF_LIGHTING_KEYS = {
    "key_origin",
    "key_vector",
    "shadow_vector",
    "hardness",
    "contrast_ratio",
    "color_temperature_k",
}
_HF_PERFORMANCE_KEYS = {
    "applicability",
    "not_applicable_reason",
    "posture",
    "gaze_phases",
    "expression_phases",
    "gesture_phases",
    "objective",
    "visible_tactic",
    "emotional_turn",
    "microphone_relation",
}
_HF_PHASE_KEYS = {"start_us", "end_us", "target", "state", "hand", "path", "end_state"}
_HF_ACTION_KEYS = {
    "state_sequence",
    "completed_end_state",
    "hand_ownership",
    "contact_points",
    "movement_trajectory",
    "caused_audio_event_ids",
}
_HF_ACTION_STATE_KEYS = {"phase", "start_us", "end_us", "state"}
_HF_SPEECH_KEYS = {"exact_asr_event_ids", "audio_event_mappings", "meaningful_silence_ranges"}
_HF_AUDIO_MAPPING_KEYS = {"event_id", "role", "synced_factor_id", "evidence"}
_HF_RANGE_KEYS = {"start_us", "end_us"}
_HF_EVIDENCE_KEYS = {
    "evidence_id",
    "kind",
    "start_us",
    "end_us",
    "frame",
    "frame_sha256",
    "timestamp_us",
    "method",
    "observed_inferred_planned",
    "confidence",
}
_HF_TRANSITION_KEYS = {
    "kind",
    "type",
    "duration_ms",
    "duration_frames",
    "duration_seconds",
    "start_frame",
    "end_frame",
    "easing",
    "audio",
    "z_order",
}
_HF_STREAM_KEYS = {
    "width",
    "height",
    "fps_num",
    "fps_den",
    "codec",
    "pixel_format",
}
_OVERLAY_CONTRACT_KEYS = {
    "contract",
    "contract_version",
    "reference_duration_us",
    "source_width",
    "source_height",
    "coordinate_space",
    "target_mapping",
    "attachment",
    "time_range_semantics",
    "cuts",
    "notes",
}
_OVERLAY_CUT_KEYS = {"cut", "start_us", "end_us", "source_overlays"}
_OVERLAY_KEYS = {
    "overlay_id",
    "kind",
    "start_us",
    "end_us",
    "start_rect",
    "end_rect",
    "start_rotation_deg",
    "end_rotation_deg",
    "start_opacity",
    "end_opacity",
    "motion_phase",
    "motion_path",
    "layer_relation",
    "z_index",
    "interpolation",
    "keyframes",
    "observed_text",
}
_OVERLAY_KEYFRAME_KEYS = {"time_us", "bbox", "rotation_deg", "opacity"}
_OVERLAY_RECT_KEYS = {"x", "y", "width", "height"}


class VisionBackendUnavailable(ReplicationError):
    """A pinned OCR/VLM backend failed or returned unbound evidence."""

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None, retryable: bool = True) -> None:
        super().__init__(
            "VISION_BACKEND_UNAVAILABLE",
            message,
            category="capability",
            retryable=retryable,
            user_action_required=False,
            details=dict(details or {}),
            http_status=503,
        )


def _require_sha(value: Any, field: str) -> str:
    text = str(value or "")
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return text


def _canonical_json(value: Mapping[str, Any] | Sequence[Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value))


def _qc_dimensions_digest(value: Mapping[str, Any]) -> str:
    """Match the packaged weighted-QC dimensions digest exactly."""

    projected: dict[str, Any] = {}
    for name in sorted(value):
        item = value[name]
        if isinstance(item, Mapping):
            row = {key: child for key, child in item.items() if key != "weight"}
            if "score" in row:
                row["score"] = float(row["score"])
            projected[name] = row
        else:
            projected[name] = item
    return _canonical_sha256(projected)


def _qc_factor_scores_digest(value: Mapping[str, Any]) -> str:
    """Match the packaged weighted-QC factor digest exactly."""

    projected: dict[str, Any] = {}
    for factor_id, item in value.items():
        if isinstance(item, Mapping):
            row = dict(item)
            if "score" in row:
                row["score"] = float(row["score"])
            projected[factor_id] = row
        else:
            projected[factor_id] = item
    return _canonical_sha256(projected)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bound_frame_times_for_records(
    records: Any,
    frame_timestamps: Mapping[str, Sequence[int]],
) -> list[int]:
    """Resolve evidence frame digests to their decoded sample timestamps."""

    if not isinstance(records, list):
        return []
    timestamps: list[int] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        digest = str(record.get("frame_sha256") or "")
        explicit_timestamp = record.get("timestamp_us")
        if explicit_timestamp is not None:
            try:
                timestamp = int(explicit_timestamp)
            except (TypeError, ValueError):
                continue
            if timestamp in frame_timestamps.get(digest, ()):
                timestamps.append(timestamp)
            continue
        for timestamp in frame_timestamps.get(digest, ()):
            try:
                timestamps.append(int(timestamp))
            except (TypeError, ValueError):
                continue
    return timestamps


def _validate_cut_local_frame_records(
    records: Any,
    frame_timestamps: Mapping[str, Sequence[int]],
    *,
    start_us: int,
    end_us: int,
    label: str,
) -> None:
    """Require every evidence reference to be local to one decoded Cut.

    A digest may identify identical pixels at several timestamps.  A bare
    digest is therefore accepted only when *all* of its decoded occurrences
    lie inside the Cut; an explicit ``timestamp_us`` must identify one sampled
    occurrence and also lie inside the Cut.  This is deliberately per-record so
    one valid reference cannot mask a second foreign reference.
    """

    if not isinstance(records, list):
        raise VisionBackendUnavailable(
            f"{label} evidence records must be an array",
            retryable=False,
        )
    for index, record in enumerate(records, start=1):
        if not isinstance(record, Mapping):
            raise VisionBackendUnavailable(
                f"{label} evidence record {index} is invalid",
                retryable=False,
            )
        digest = str(record.get("frame_sha256") or "")
        occurrences = [int(value) for value in frame_timestamps.get(digest, ())]
        if not occurrences:
            raise VisionBackendUnavailable(
                f"{label} evidence record {index} does not reference a sampled frame",
                retryable=False,
            )
        explicit_timestamp = record.get("timestamp_us")
        if explicit_timestamp is not None:
            try:
                timestamp = int(explicit_timestamp)
            except (TypeError, ValueError) as exc:
                raise VisionBackendUnavailable(
                    f"{label} evidence record {index} timestamp_us is invalid",
                    retryable=False,
                ) from exc
            if timestamp not in occurrences:
                raise VisionBackendUnavailable(
                    f"{label} evidence record {index} timestamp_us is not one of the sampled frames",
                    retryable=False,
                )
            if not start_us <= timestamp < end_us:
                raise VisionBackendUnavailable(
                    f"{label} evidence record {index} timestamp_us is outside its Cut timing",
                    retryable=False,
                )
            continue
        if any(not start_us <= timestamp < end_us for timestamp in occurrences):
            raise VisionBackendUnavailable(
                f"{label} evidence record {index} is a bare digest with ambiguous or foreign Cut timing; timestamp_us is required",
                retryable=False,
            )


def _safe_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise VisionBackendUnavailable(f"{field} must be non-empty", retryable=False)
    if "\ufffd" in text or any(unicodedata.category(char) in {"Cc", "Cs"} for char in text):
        raise VisionBackendUnavailable(f"{field} contains replacement, control, or surrogate characters", retryable=False)
    return text


def _active_high_fidelity_context(context: Any | None) -> bool:
    profile = getattr(context, "profile_snapshot", None)
    if not isinstance(profile, Mapping) or profile.get("profile") != "high_fidelity_hybrid_v1":
        return False
    return str(profile.get("activation_mode") or "active").strip().casefold() in {
        "active",
        "production",
        "default",
    }


def _load_hf_extension_validator() -> Any:
    path = (
        Path(__file__).resolve().parents[1]
        / "bundled-skills"
        / "analyze-reference-video-dynamics"
        / "scripts"
        / "validate_high_fidelity_extension.py"
    )
    spec = importlib.util.spec_from_file_location("usfr_vlm_hf_extension_validator", path)
    if spec is None or spec.loader is None:
        raise VisionBackendUnavailable(
            "packaged high-fidelity dynamics extension validator is unavailable",
            retryable=False,
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise VisionBackendUnavailable(
            "packaged high-fidelity dynamics extension validator failed to load",
            details={"reason": str(exc)},
            retryable=False,
        ) from exc
    return module


def _load_adaptive_evidence_plan_validator() -> Any:
    path = (
        Path(__file__).resolve().parents[1]
        / "bundled-skills"
        / "analyze-reference-video-dynamics"
        / "scripts"
        / "adaptive_evidence_plan.py"
    )
    spec = importlib.util.spec_from_file_location("usfr_vlm_adaptive_evidence_plan", path)
    if spec is None or spec.loader is None:
        raise VisionBackendUnavailable(
            "packaged adaptive evidence-plan validator is unavailable",
            retryable=False,
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise VisionBackendUnavailable(
            "packaged adaptive evidence-plan validator failed to load",
            details={"reason": str(exc)},
            retryable=False,
        ) from exc
    return module


def _validated_adaptive_evidence_plan(
    value: Any,
    *,
    source_sha256: str,
    duration_us: int,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise VisionBackendUnavailable("VLM evidence_plan must be an object", retryable=False)
    normalized = json.loads(_canonical_json(value).decode("utf-8"))
    module = _load_adaptive_evidence_plan_validator()
    try:
        module.validate_evidence_plan(normalized)
    except Exception as exc:
        raise VisionBackendUnavailable(
            "VLM evidence_plan failed the packaged validator",
            details={"reason": str(exc)},
            retryable=False,
        ) from exc
    source = normalized.get("source")
    if not isinstance(source, Mapping) or str(source.get("sha256") or "") != source_sha256:
        raise VisionBackendUnavailable(
            "VLM evidence_plan is not bound to the exact source video",
            retryable=False,
        )
    if int(source.get("duration_us") or 0) != duration_us:
        raise VisionBackendUnavailable(
            "VLM evidence_plan duration does not match the exact source duration",
            retryable=False,
        )
    return normalized


def _load_overlay_contract_validator() -> Any:
    path = (
        Path(__file__).resolve().parents[1]
        / "bundled-skills"
        / "replicate-source-ui-overlays"
        / "scripts"
        / "validate_overlay_contract.py"
    )
    spec = importlib.util.spec_from_file_location("usfr_vlm_overlay_contract_validator", path)
    if spec is None or spec.loader is None:
        raise VisionBackendUnavailable(
            "packaged source overlay contract validator is unavailable",
            retryable=False,
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise VisionBackendUnavailable(
            "packaged source overlay contract validator failed to load",
            details={"reason": str(exc)},
            retryable=False,
        ) from exc
    return module


def _require_allowed_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise VisionBackendUnavailable(
            f"{label} contains unsupported fields: {unknown}",
            retryable=False,
        )


def _validate_hf_extension_shape(extension: Any) -> dict[str, Any]:
    """Validate the full HF sidecar shape using explicit field allowlists."""

    if not isinstance(extension, Mapping):
        raise VisionBackendUnavailable(
            "active high-fidelity VLM response extension must be an object",
            retryable=False,
        )
    extension = dict(extension)
    _require_allowed_keys(extension, _HF_EXTENSION_KEYS, "high-fidelity extension")

    def mapping(value: Any, allowed: set[str], label: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise VisionBackendUnavailable(f"{label} must be an object", retryable=False)
        result = dict(value)
        _require_allowed_keys(result, allowed, label)
        return result

    def evidence(value: Any, label: str) -> None:
        item = mapping(value, _HF_EVIDENCE_KEYS, label)
        # ``frame_sha256`` is optional for legacy local semantic fixtures, but
        # when a sidecar supplies it it must be an exact lowercase digest.
        if item.get("frame_sha256") is not None:
            _require_sha(item.get("frame_sha256"), f"{label}.frame_sha256")
        if item.get("timestamp_us") is not None:
            timestamp = item.get("timestamp_us")
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
                raise VisionBackendUnavailable(
                    f"{label}.timestamp_us must be a non-negative integer",
                    retryable=False,
                )

    semantic_cuts = extension.get("semantic_cuts")
    if not isinstance(semantic_cuts, list):
        raise VisionBackendUnavailable("high-fidelity extension semantic_cuts must be an array", retryable=False)
    for index, raw_cut in enumerate(semantic_cuts, start=1):
        cut = mapping(raw_cut, _HF_SEMANTIC_CUT_KEYS, f"semantic_cuts[{index}]")
        topology = mapping(cut.get("scene_topology"), _HF_SCENE_KEYS, f"semantic_cuts[{index}].scene_topology")
        entities = topology.get("entities")
        if not isinstance(entities, list):
            raise VisionBackendUnavailable("scene_topology.entities must be an array", retryable=False)
        for entity_index, entity in enumerate(entities, start=1):
            mapping(entity, _HF_ENTITY_KEYS, f"semantic_cuts[{index}].scene_topology.entities[{entity_index}]")
        framing = mapping(cut.get("framing_migration"), _HF_FRAMING_KEYS, f"semantic_cuts[{index}].framing_migration")
        anchors = framing.get("anchors")
        if not isinstance(anchors, list):
            raise VisionBackendUnavailable("framing_migration.anchors must be an array", retryable=False)
        for anchor_index, anchor in enumerate(anchors, start=1):
            mapping(anchor, _HF_ANCHOR_KEYS, f"semantic_cuts[{index}].framing_migration.anchors[{anchor_index}]")
        mapping(cut.get("lighting"), _HF_LIGHTING_KEYS, f"semantic_cuts[{index}].lighting")
        performance = mapping(cut.get("performance"), _HF_PERFORMANCE_KEYS, f"semantic_cuts[{index}].performance")
        for phase_name in ("gaze_phases", "expression_phases", "gesture_phases"):
            phases = performance.get(phase_name)
            if phases is not None:
                if not isinstance(phases, list):
                    raise VisionBackendUnavailable(f"performance.{phase_name} must be an array", retryable=False)
                for phase_index, phase in enumerate(phases, start=1):
                    mapping(phase, _HF_PHASE_KEYS, f"semantic_cuts[{index}].performance.{phase_name}[{phase_index}]")
        action = mapping(cut.get("object_action"), _HF_ACTION_KEYS, f"semantic_cuts[{index}].object_action")
        states = action.get("state_sequence")
        if not isinstance(states, list):
            raise VisionBackendUnavailable("object_action.state_sequence must be an array", retryable=False)
        for state_index, state in enumerate(states, start=1):
            mapping(state, _HF_ACTION_STATE_KEYS, f"semantic_cuts[{index}].object_action.state_sequence[{state_index}]")
        speech = mapping(cut.get("speech_audio"), _HF_SPEECH_KEYS, f"semantic_cuts[{index}].speech_audio")
        mappings = speech.get("audio_event_mappings")
        if not isinstance(mappings, list):
            raise VisionBackendUnavailable("speech_audio.audio_event_mappings must be an array", retryable=False)
        for mapping_index, audio_mapping in enumerate(mappings, start=1):
            item = mapping(audio_mapping, _HF_AUDIO_MAPPING_KEYS, f"semantic_cuts[{index}].speech_audio.audio_event_mappings[{mapping_index}]")
            records = item.get("evidence")
            if not isinstance(records, list):
                raise VisionBackendUnavailable("audio event mapping evidence must be an array", retryable=False)
            for evidence_index, record in enumerate(records, start=1):
                evidence(record, f"semantic_cuts[{index}].speech_audio.audio_event_mappings[{mapping_index}].evidence[{evidence_index}]")
        silence = speech.get("meaningful_silence_ranges")
        if not isinstance(silence, list):
            raise VisionBackendUnavailable("speech_audio.meaningful_silence_ranges must be an array", retryable=False)
        for silence_index, item in enumerate(silence, start=1):
            mapping(item, _HF_RANGE_KEYS, f"semantic_cuts[{index}].speech_audio.meaningful_silence_ranges[{silence_index}]")
        records = cut.get("evidence")
        if not isinstance(records, list) or not records:
            raise VisionBackendUnavailable("each semantic Cut requires evidence", retryable=False)
        for evidence_index, record in enumerate(records, start=1):
            evidence(record, f"semantic_cuts[{index}].evidence[{evidence_index}]")

    excluded = extension.get("route_excluded_intervals")
    if not isinstance(excluded, list):
        raise VisionBackendUnavailable("high-fidelity extension route_excluded_intervals must be an array", retryable=False)
    for index, raw_interval in enumerate(excluded, start=1):
        interval = mapping(raw_interval, _HF_ROUTE_EXCLUDED_KEYS, f"route_excluded_intervals[{index}]")
        mapping(interval.get("transition_shell"), _HF_TRANSITION_KEYS, f"route_excluded_intervals[{index}].transition_shell")
        mapping(interval.get("technical_stream"), _HF_STREAM_KEYS, f"route_excluded_intervals[{index}].technical_stream")
    return extension


def _validate_hf_extension_response(
    extension: Any,
    *,
    source_cuts: Sequence[Mapping[str, Any]],
    source_events: Sequence[Mapping[str, Any]],
    frame_sha256s: Sequence[str],
    frame_timestamps: Mapping[str, Sequence[int]] | None = None,
) -> dict[str, Any]:
    normalized = _validate_hf_extension_shape(extension)
    validator = _load_hf_extension_validator()
    try:
        validator.validate_high_fidelity_extension(
            {
                "source_cuts": list(source_cuts),
                "source_events": list(source_events),
                "extensions": {"high_fidelity_hybrid_v1": normalized},
            }
        )
    except Exception as exc:
        raise VisionBackendUnavailable(
            "active high-fidelity VLM extension failed the packaged validator",
            details={"reason": str(exc)},
            retryable=False,
        ) from exc

    frame_set = set(frame_sha256s)
    referenced: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key == "frame_sha256" and isinstance(child, str):
                    referenced.add(child)
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(normalized)
    if referenced and not referenced.issubset(frame_set):
        raise VisionBackendUnavailable(
            "active high-fidelity extension references an unsent evidence frame",
            retryable=False,
        )
    semantic_cuts = normalized.get("semantic_cuts") or []
    source_by_number = {
        int(item.get("cut") or index): item
        for index, item in enumerate(source_cuts, start=1)
        if isinstance(item, Mapping)
    }

    def _bound_frame_times(value: Any) -> list[int]:
        """Return decoded sample times referenced by an evidence array."""

        if not isinstance(value, list) or frame_timestamps is None:
            return []
        result: list[int] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            digest = str(item.get("frame_sha256") or "")
            explicit_timestamp = item.get("timestamp_us")
            if explicit_timestamp is not None:
                try:
                    timestamp = int(explicit_timestamp)
                except (TypeError, ValueError):
                    continue
                if timestamp in frame_timestamps.get(digest, ()):
                    result.append(timestamp)
                continue
            for timestamp in frame_timestamps.get(digest, ()):
                try:
                    result.append(int(timestamp))
                except (TypeError, ValueError):
                    continue
        return result

    for index, semantic_cut in enumerate(semantic_cuts, start=1):
        cut_refs: set[str] = set()
        collect(semantic_cut.get("evidence") if isinstance(semantic_cut, Mapping) else None)
        if isinstance(semantic_cut, Mapping):
            for record in semantic_cut.get("evidence") or []:
                if isinstance(record, Mapping) and isinstance(record.get("frame_sha256"), str):
                    cut_refs.add(record["frame_sha256"])
        if not cut_refs:
            raise VisionBackendUnavailable(
                f"active high-fidelity semantic Cut {index} has no frame digest binding",
                retryable=False,
            )
        if not cut_refs.intersection(frame_set):
            raise VisionBackendUnavailable(
                f"active high-fidelity semantic Cut {index} frame digest binding does not match sampled frames",
                retryable=False,
            )
        if frame_timestamps is not None:
            try:
                cut_number = int(semantic_cut.get("cut"))
            except (TypeError, ValueError) as exc:
                raise VisionBackendUnavailable(
                    f"active high-fidelity semantic Cut {index} has an invalid Cut number",
                    retryable=False,
                ) from exc
            source_cut = source_by_number.get(cut_number)
            if not isinstance(source_cut, Mapping):
                raise VisionBackendUnavailable(
                    f"active high-fidelity semantic Cut {index} has no source timing",
                    retryable=False,
                )
            try:
                cut_start = int(source_cut.get("start_us"))
                cut_end = int(source_cut.get("end_us"))
            except (TypeError, ValueError) as exc:
                raise VisionBackendUnavailable(
                    f"active high-fidelity semantic Cut {index} has invalid source timing",
                    retryable=False,
                ) from exc
            semantic_evidence = semantic_cut.get("evidence") if isinstance(semantic_cut, Mapping) else None
            _validate_cut_local_frame_records(
                semantic_evidence,
                frame_timestamps,
                start_us=cut_start,
                end_us=cut_end,
                label=f"active high-fidelity semantic Cut {index}",
            )
            evidence_times = _bound_frame_times(semantic_evidence)
            if not any(cut_start <= timestamp < cut_end for timestamp in evidence_times):
                raise VisionBackendUnavailable(
                    f"active high-fidelity semantic Cut {index} evidence is not bound to a decoded sampled frame inside its Cut timing",
                    retryable=False,
                )
    if not frame_set:
        raise VisionBackendUnavailable("active high-fidelity VLM response has no sampled frame digests", retryable=False)
    return normalized


def _validate_source_overlay_contract(
    contract: Any,
    *,
    duration_us: int,
) -> dict[str, Any]:
    """Validate an optional sidecar overlay contract without inferring overlays."""

    if not isinstance(contract, Mapping):
        raise VisionBackendUnavailable(
            "source_overlay_contract must be an object when supplied",
            retryable=False,
        )
    normalized = dict(contract)
    _require_allowed_keys(normalized, _OVERLAY_CONTRACT_KEYS, "source_overlay_contract")

    def mapping(value: Any, allowed: set[str], label: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise VisionBackendUnavailable(f"{label} must be an object", retryable=False)
        result = dict(value)
        _require_allowed_keys(result, allowed, label)
        return result

    cuts = normalized.get("cuts")
    if not isinstance(cuts, list):
        raise VisionBackendUnavailable("source_overlay_contract.cuts must be an array", retryable=False)
    for cut_index, raw_cut in enumerate(cuts, start=1):
        cut = mapping(raw_cut, _OVERLAY_CUT_KEYS, f"source_overlay_contract.cuts[{cut_index}]")
        overlays = cut.get("source_overlays")
        if not isinstance(overlays, list):
            raise VisionBackendUnavailable(
                f"source_overlay_contract.cuts[{cut_index}].source_overlays must be an array",
                retryable=False,
            )
        for overlay_index, raw_overlay in enumerate(overlays, start=1):
            overlay = mapping(
                raw_overlay,
                _OVERLAY_KEYS,
                f"source_overlay_contract.cuts[{cut_index}].source_overlays[{overlay_index}]",
            )
            for field in ("start_rect", "end_rect"):
                rect = mapping(
                    overlay.get(field),
                    _OVERLAY_RECT_KEYS,
                    f"source_overlay_contract.cuts[{cut_index}].source_overlays[{overlay_index}].{field}",
                )
                if any(key not in rect for key in _OVERLAY_RECT_KEYS):
                    raise VisionBackendUnavailable(
                        f"source_overlay_contract overlay {field} must contain x/y/width/height",
                        retryable=False,
                    )
            keyframes = overlay.get("keyframes")
            if not isinstance(keyframes, list):
                raise VisionBackendUnavailable(
                    f"source_overlay_contract.cuts[{cut_index}].source_overlays[{overlay_index}].keyframes must be an array",
                    retryable=False,
                )
            for keyframe_index, raw_keyframe in enumerate(keyframes, start=1):
                keyframe = mapping(
                    raw_keyframe,
                    _OVERLAY_KEYFRAME_KEYS,
                    f"source_overlay_contract.cuts[{cut_index}].source_overlays[{overlay_index}].keyframes[{keyframe_index}]",
                )
                mapping(
                    keyframe.get("bbox"),
                    _OVERLAY_RECT_KEYS,
                    f"source_overlay_contract.cuts[{cut_index}].source_overlays[{overlay_index}].keyframes[{keyframe_index}].bbox",
                )

    if normalized.get("reference_duration_us") != duration_us:
        raise VisionBackendUnavailable(
            "source_overlay_contract reference duration does not match the exact source duration",
            retryable=False,
        )
    # The overlay contract's visible-frame dimensions can legitimately differ
    # from raw container metadata when rotation correction or a crop is part of
    # the source contract.  Bind the contract to the exact source duration and
    # media/frame digests above, while only requiring sane optional dimensions.
    for field in ("source_width", "source_height"):
        value = normalized.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
            raise VisionBackendUnavailable(
                f"source_overlay_contract {field} must be a positive integer when supplied",
                retryable=False,
            )
    validator = _load_overlay_contract_validator()
    try:
        validator.validate(normalized)
    except Exception as exc:
        raise VisionBackendUnavailable(
            "source overlay contract failed the packaged validator",
            details={"reason": str(exc)},
            retryable=False,
        ) from exc
    return normalized


class _EvidenceBoundHttpBackend:
    schema_version = ""
    implementation = ""
    adapter_version = "1.0.0"

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        model_sha256: str,
        api_token: str | None = None,
        api_token_env: str | None = None,
        timeout_seconds: float = 120.0,
        max_response_bytes: int = 8 * 1024 * 1024,
        production: bool = True,
    ) -> None:
        parsed = urlparse.urlparse(str(endpoint or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("vision backend endpoint must be an HTTP(S) service URL")
        if parsed.username or parsed.password:
            raise ValueError("vision backend endpoint must not contain credentials")
        if production and parsed.scheme != "https":
            raise ValueError("production vision backend endpoint must use HTTPS")
        if not str(model_id or "").strip():
            raise ValueError("vision backend model_id is required")
        if not math.isfinite(float(timeout_seconds)) or not 0 < float(timeout_seconds) <= 600:
            raise ValueError("vision backend timeout_seconds must be in (0, 600]")
        if int(max_response_bytes) <= 0:
            raise ValueError("vision backend max_response_bytes must be positive")
        self.endpoint = str(endpoint)
        self.model_id = str(model_id).strip()
        self.model_sha256 = _require_sha(model_sha256, "model_sha256")
        self.api_token = api_token
        self.api_token_env = api_token_env
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)
        self.production = bool(production)

    def capability_identity(self) -> Mapping[str, Any]:
        return {
            "implementation": self.implementation,
            "version": self.adapter_version,
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
            "evidence_binding": self.schema_version,
            "transport": "https-json" if self.endpoint.startswith("https://") else "http-json-test-only",
        }

    def _post(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], str, str]:
        core = dict(payload)
        request_sha256 = _sha256_bytes(_canonical_json(core))
        body = _canonical_json({**core, "request_sha256": request_sha256})
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "usfr-evidence-bound-vision/1.0",
        }
        token = self.api_token or (os.getenv(self.api_token_env) if self.api_token_env else None)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urlrequest.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_response_bytes + 1)
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise VisionBackendUnavailable(
                "vision backend request failed",
                details={"host": urlparse.urlparse(self.endpoint).hostname or ""},
            ) from exc
        if len(raw) > self.max_response_bytes:
            raise VisionBackendUnavailable("vision backend response exceeded the configured byte limit", retryable=False)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisionBackendUnavailable("vision backend returned malformed JSON") from exc
        if not isinstance(value, Mapping):
            raise VisionBackendUnavailable("vision backend response must be a JSON object", retryable=False)
        result = dict(value)
        if result.get("schema_version") != self.schema_version:
            raise VisionBackendUnavailable("vision backend response schema does not match", retryable=False)
        if result.get("request_sha256") != request_sha256:
            raise VisionBackendUnavailable("vision backend response is not bound to the exact request SHA", retryable=False)
        model = result.get("model")
        if not isinstance(model, Mapping):
            raise VisionBackendUnavailable("vision backend response has no model identity", retryable=False)
        if str(model.get("id") or "") != self.model_id or str(model.get("sha256") or "") != self.model_sha256:
            raise VisionBackendUnavailable("vision backend response model identity does not match the pinned model", retryable=False)
        return result, request_sha256, _sha256_bytes(raw)


class EvidenceBoundHttpOcrBackend(_EvidenceBoundHttpBackend):
    """Call a private OCR service and validate text boxes against input bytes."""

    schema_version = "usfr-ocr-evidence/v1"
    implementation = "server.vision_backends:EvidenceBoundHttpOcrBackend"

    @classmethod
    def from_environment(cls, *, production: bool = True) -> "EvidenceBoundHttpOcrBackend":
        return cls(
            endpoint=os.environ["USFR_OCR_ENDPOINT"],
            model_id=os.environ["USFR_OCR_MODEL_ID"],
            model_sha256=os.environ["USFR_OCR_MODEL_SHA256"],
            api_token_env="USFR_OCR_API_TOKEN",
            production=production,
        )

    def recognize(self, path: Path) -> Mapping[str, Any]:
        source = Path(path)
        try:
            data = source.read_bytes()
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                image_format = str(image.format or "").lower()
        except (OSError, ValueError) as exc:
            raise VisionBackendUnavailable("OCR input is not a readable image", retryable=False) from exc
        if not data or width <= 0 or height <= 0:
            raise VisionBackendUnavailable("OCR input image has no usable pixels", retryable=False)
        input_sha256 = _sha256_bytes(data)
        response, request_sha256, response_sha256 = self._post(
            {
                "schema_version": self.schema_version,
                "input_sha256": input_sha256,
                "content_type": f"image/{image_format or 'png'}",
                "width": width,
                "height": height,
                "image_base64": base64.b64encode(data).decode("ascii"),
                "expected_model": {"id": self.model_id, "sha256": self.model_sha256},
            }
        )
        if response.get("input_sha256") != input_sha256:
            raise VisionBackendUnavailable("OCR response input SHA does not match the rendered image", retryable=False)
        records_value = response.get("records")
        if not isinstance(records_value, list):
            raise VisionBackendUnavailable("OCR response records must be an array", retryable=False)
        records: list[dict[str, Any]] = []
        for index, item in enumerate(records_value):
            if not isinstance(item, Mapping):
                raise VisionBackendUnavailable("OCR record must be an object", details={"record": index}, retryable=False)
            text = _safe_text(item.get("text"), f"OCR record {index} text")
            bbox = item.get("bbox")
            if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes, bytearray)) or len(bbox) != 4:
                raise VisionBackendUnavailable("OCR record bbox must contain four coordinates", details={"record": index}, retryable=False)
            try:
                x1, y1, x2, y2 = [float(value) for value in bbox]
                confidence = float(item.get("confidence"))
            except (TypeError, ValueError) as exc:
                raise VisionBackendUnavailable("OCR record bbox/confidence must be numeric", details={"record": index}, retryable=False) from exc
            if not all(math.isfinite(value) for value in (x1, y1, x2, y2, confidence)):
                raise VisionBackendUnavailable("OCR record contains non-finite geometry", details={"record": index}, retryable=False)
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise VisionBackendUnavailable("OCR record bbox lies outside the exact input image", details={"record": index}, retryable=False)
            if not 0 <= confidence <= 1:
                raise VisionBackendUnavailable("OCR record confidence must be in [0, 1]", details={"record": index}, retryable=False)
            records.append({"text": text, "bbox": [x1, y1, x2, y2], "confidence": confidence})
        records_sha256 = _sha256_bytes(_canonical_json(records))
        return {
            "records": records,
            "evidence": {
                "schema_version": self.schema_version,
                "request_sha256": request_sha256,
                "response_sha256": response_sha256,
                "input_sha256": input_sha256,
                "records_sha256": records_sha256,
                "model_id": self.model_id,
                "model_sha256": self.model_sha256,
            },
        }

    def __call__(self, path: Path) -> Mapping[str, Any]:
        return self.recognize(path)


class EvidenceBoundHttpUiRenderer(_EvidenceBoundHttpBackend):
    """Render a target UI through a private, evidence-bound video sidecar.

    The canonical worker owns the route, truth card, and render contract.  The
    sidecar only performs deterministic media construction and returns encoded
    MP4 bytes plus a state sequence.  No local path is placed on the wire and
    the response is accepted only when request/source/model/video digests and
    the exact target contracts are bound together.  Independent OCR/layout
    verification remains in :class:`DeterministicUiRenderer`.
    """

    schema_version = "usfr-ui-render-evidence/v1"
    implementation = "server.vision_backends:EvidenceBoundHttpUiRenderer"
    adapter_version = "1.0.0"

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        model_sha256: str,
        api_token: str | None = None,
        api_token_env: str | None = None,
        timeout_seconds: float = 180.0,
        max_response_bytes: int = 128 * 1024 * 1024,
        production: bool = True,
        ffprobe_bin: str | None = None,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            model_id=model_id,
            model_sha256=model_sha256,
            api_token=api_token,
            api_token_env=api_token_env,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            production=production,
        )
        self.ffprobe_bin = ffprobe_bin

    @classmethod
    def from_environment(cls, *, production: bool = True) -> "EvidenceBoundHttpUiRenderer":
        return cls(
            endpoint=os.environ["USFR_UI_RENDER_ENDPOINT"],
            model_id=os.environ["USFR_UI_RENDER_MODEL_ID"],
            model_sha256=os.environ["USFR_UI_RENDER_MODEL_SHA256"],
            api_token_env="USFR_UI_RENDER_API_TOKEN",
            production=production,
        )

    def capability_identity(self) -> Mapping[str, Any]:
        identity = dict(super().capability_identity())
        identity["implementation"] = self.implementation
        identity["sha256"] = _sha256_bytes(
            self._canonical(
                {
                    "implementation": self.implementation,
                    "version": self.adapter_version,
                    "model_id": self.model_id,
                    "model_sha256": self.model_sha256,
                }
            )
        )
        return identity

    @staticmethod
    def _canonical(value: Any) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _contracts_from_context(context: Any) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
        """Find target-owned contracts without consulting renderer output."""

        candidates: list[Mapping[str, Any]] = []
        for item in getattr(context, "input_slots", ()) or ():
            if not isinstance(item, Mapping) or str(item.get("slot_id") or "") != "ui_screenshot":
                continue
            metadata = item.get("metadata")
            if isinstance(metadata, Mapping):
                candidates.append(metadata)
            elif isinstance(metadata, Sequence) and not isinstance(metadata, (str, bytes, bytearray)):
                candidates.extend(record for record in metadata if isinstance(record, Mapping))
        for item in getattr(context, "artifacts", ()) or ():
            if not isinstance(item, Mapping) or str(item.get("kind") or "") != "app_store_screenshot":
                continue
            metadata = item.get("metadata")
            if isinstance(metadata, Mapping):
                candidates.append(metadata)
        for item in candidates:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else item
            truth = metadata.get("ui_truth_card") if isinstance(metadata, Mapping) else None
            contract = metadata.get("ui_render_contract") if isinstance(metadata, Mapping) else None
            if isinstance(truth, Mapping) and isinstance(contract, Mapping):
                return truth, contract
        return None, None

    def _probe_video(self, path: Path) -> Mapping[str, Any]:
        executable = self.ffprobe_bin or shutil.which("ffprobe")
        if not executable:
            raise VisionBackendUnavailable("ffprobe is required to validate rendered UI video", retryable=False)
        command = [
            str(executable), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VisionBackendUnavailable("rendered UI video probe failed", retryable=False) from exc
        if result.returncode != 0:
            raise VisionBackendUnavailable("rendered UI video is not decodable", retryable=False)
        try:
            value = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisionBackendUnavailable("rendered UI video probe returned malformed JSON", retryable=False) from exc
        streams = value.get("streams") if isinstance(value, Mapping) else None
        if not isinstance(streams, list) or not any(isinstance(item, Mapping) and item.get("codec_type") == "video" for item in streams):
            raise VisionBackendUnavailable("rendered UI sidecar returned no video stream", retryable=False)
        video_stream = next(item for item in streams if isinstance(item, Mapping) and item.get("codec_type") == "video")
        try:
            duration = float(video_stream.get("duration") or (value.get("format") or {}).get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if not math.isfinite(duration) or duration <= 0:
            raise VisionBackendUnavailable("rendered UI sidecar returned a zero-duration video", retryable=False)
        return value

    def check_ready(self) -> bool:
        """Probe the renderer sidecar without sending user media."""

        parsed = urlparse.urlparse(self.endpoint)
        health = urlparse.urlunparse((parsed.scheme, parsed.netloc, "/readyz", "", "", ""))
        headers = {"Accept": "application/json"}
        token = self.api_token or (os.getenv(self.api_token_env) if self.api_token_env else None)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urlrequest.Request(health, headers=headers, method="GET")
        try:
            with urlrequest.urlopen(request, timeout=min(self.timeout_seconds, 10.0)) as response:
                return 200 <= int(getattr(response, "status", 200)) < 300
        except (urlerror.URLError, TimeoutError, OSError):
            return False

    def __call__(
        self,
        source: Path,
        output: Path,
        context: Any | None = None,
        *,
        truth: Mapping[str, Any] | None = None,
        render_contract: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        source_path = Path(source)
        output_path = Path(output)
        try:
            source_bytes = source_path.read_bytes()
        except OSError as exc:
            raise VisionBackendUnavailable("UI renderer source cannot be read", retryable=False) from exc
        if not source_bytes:
            raise VisionBackendUnavailable("UI renderer source is empty", retryable=False)
        if truth is None or render_contract is None:
            context_truth, context_contract = self._contracts_from_context(context)
            truth = truth or context_truth
            render_contract = render_contract or context_contract
        if not isinstance(truth, Mapping) or not isinstance(render_contract, Mapping):
            raise VisionBackendUnavailable("UI renderer requires ui_truth_card and ui_render_contract", retryable=False)
        source_sha256 = _sha256_bytes(source_bytes)
        source_content_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        if not source_content_type.startswith("image/"):
            source_content_type = "image/png"
        response, request_sha256, response_sha256 = self._post(
            {
                "schema_version": self.schema_version,
                "source_sha256": source_sha256,
                "source_content_type": source_content_type,
                "source_base64": base64.b64encode(source_bytes).decode("ascii"),
                "ui_truth_card": dict(truth),
                "ui_render_contract": dict(render_contract),
                "expected_model": {"id": self.model_id, "sha256": self.model_sha256},
            }
        )
        if str(response.get("source_sha256") or "") != source_sha256:
            raise VisionBackendUnavailable("UI renderer response source SHA does not match input", retryable=False)
        if response.get("ui_truth_card") != dict(truth) or response.get("ui_render_contract") != dict(render_contract):
            raise VisionBackendUnavailable("UI renderer response contracts do not match target truth", retryable=False)
        encoded = response.get("video_base64")
        if not isinstance(encoded, str) or not encoded:
            raise VisionBackendUnavailable("UI renderer response must contain video_base64", retryable=False)
        try:
            video_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise VisionBackendUnavailable("UI renderer response video_base64 is invalid", retryable=False) from exc
        video_sha256 = _sha256_bytes(video_bytes)
        if str(response.get("video_sha256") or "") != video_sha256:
            raise VisionBackendUnavailable("UI renderer response video SHA does not match bytes", retryable=False)
        states = response.get("state_sequence")
        expected_states = render_contract.get("state_sequence")
        if (
            not isinstance(states, list)
            or any(not isinstance(item, str) or not item for item in states)
            or len(set(states)) != len(states)
        ):
            raise VisionBackendUnavailable("UI renderer response state_sequence must be an array", retryable=False)
        if not isinstance(expected_states, list) or states != [str(item) for item in expected_states]:
            raise VisionBackendUnavailable("UI renderer response state_sequence does not match target contract", retryable=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        try:
            temporary.write_bytes(video_bytes)
            self._probe_video(temporary)
            temporary.replace(output_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return {
            "video_path": str(output_path),
            "ui_truth_card": dict(truth),
            "ui_render_contract": dict(render_contract),
            "state_sequence": list(states),
            "backend_evidence": {
                "schema_version": self.schema_version,
                "request_sha256": request_sha256,
                "response_sha256": response_sha256,
                "source_sha256": source_sha256,
                "video_sha256": video_sha256,
                "model_id": self.model_id,
                "model_sha256": self.model_sha256,
            },
        }


class EvidenceBoundHttpSemanticQcEvaluator(_EvidenceBoundHttpBackend):
    """Call a private semantic-QC service with exact final-media bytes.

    This adapter is intentionally a transport/evidence boundary, not a local
    comparator.  The deployment-owned service supplies dimensions and factor
    observations; this class verifies that they are bound to the exact media,
    request, model, and weighted-QC receipt expected by ``FfmpegQcEngine``.
    Worker paths are never serialized on the wire.
    """

    schema_version = "usfr-qc-evaluator/v1"
    implementation = "server.vision_backends:EvidenceBoundHttpSemanticQcEvaluator"
    adapter_version = "1.0.0"

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        model_sha256: str,
        api_token: str | None = None,
        api_token_env: str | None = None,
        timeout_seconds: float = 240.0,
        max_response_bytes: int = 32 * 1024 * 1024,
        max_media_bytes: int = 256 * 1024 * 1024,
        production: bool = True,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            model_id=model_id,
            model_sha256=model_sha256,
            api_token=api_token,
            api_token_env=api_token_env,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            production=production,
        )
        if int(max_media_bytes) <= 0:
            raise ValueError("semantic QC max_media_bytes must be positive")
        self.max_media_bytes = int(max_media_bytes)

    @classmethod
    def from_environment(cls, *, production: bool = True) -> "EvidenceBoundHttpSemanticQcEvaluator":
        return cls(
            endpoint=os.environ["USFR_QC_EVALUATOR_ENDPOINT"],
            model_id=os.environ["USFR_QC_EVALUATOR_MODEL_ID"],
            model_sha256=os.environ["USFR_QC_EVALUATOR_MODEL_SHA256"],
            api_token_env="USFR_QC_EVALUATOR_API_TOKEN",
            production=production,
        )

    @staticmethod
    def _request_payload(
        *,
        final_output_sha256: str,
        current_run_source_sha256s: Sequence[str],
        input_artifacts: Sequence[Mapping[str, Any]],
        source_audio_performance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": "high-fidelity-qc-evaluator-request/v1",
            "final_output_sha256": final_output_sha256,
            "current_run_source_sha256s": sorted(set(current_run_source_sha256s)),
            "input_artifact_sha256s": sorted(
                str(item.get("sha256") or "").lower()
                for item in input_artifacts
                if isinstance(item, Mapping)
                and _SHA256.fullmatch(str(item.get("sha256") or "").lower())
            ),
        }
        if source_audio_performance is not None:
            payload["source_audio_performance"] = (
                EvidenceBoundHttpSemanticQcEvaluator._source_audio_performance_projection(
                    source_audio_performance
                )
            )
        return payload

    @staticmethod
    def _source_audio_performance_projection(value: Mapping[str, Any]) -> dict[str, Any]:
        """Validate the path-free source-performance QC request projection."""

        if not isinstance(value, Mapping):
            raise VisionBackendUnavailable(
                "semantic QC source_audio_performance must be an object",
                retryable=False,
            )
        required_digests = (
            "performance_line_contract_sha256",
            "final_output_sha256",
            "source_media_sha256",
            "source_audio_sha256",
            "remux_request_sha256",
        )
        normalized: dict[str, Any] = {}
        for field in required_digests:
            normalized[field] = _require_sha(
                value.get(field),
                f"semantic QC source_audio_performance {field}",
            )
        raw_regions = value.get("regions")
        if not isinstance(raw_regions, list):
            raise VisionBackendUnavailable(
                "semantic QC source_audio_performance regions must be an array",
                retryable=False,
            )
        regions: list[dict[str, Any]] = []
        seen_region_ids: set[str] = set()
        for index, raw_region in enumerate(raw_regions):
            if not isinstance(raw_region, Mapping):
                raise VisionBackendUnavailable(
                    f"semantic QC source_audio_performance region {index} must be an object",
                    retryable=False,
                )
            region_id = str(raw_region.get("region_id") or "").strip()
            mode = str(raw_region.get("audio_mode") or "").strip()
            if not region_id or region_id in seen_region_ids:
                raise VisionBackendUnavailable(
                    "semantic QC source_audio_performance regions require unique IDs",
                    retryable=False,
                )
            seen_region_ids.add(region_id)

            def bound(field: str) -> int:
                value = raw_region.get(field)
                if isinstance(value, bool):
                    raise VisionBackendUnavailable(
                        f"semantic QC source_audio_performance region {region_id} {field} is invalid",
                        retryable=False,
                    )
                try:
                    result = int(value)
                except (TypeError, ValueError) as exc:
                    raise VisionBackendUnavailable(
                        f"semantic QC source_audio_performance region {region_id} requires {field}",
                        retryable=False,
                    ) from exc
                if result < 0:
                    raise VisionBackendUnavailable(
                        f"semantic QC source_audio_performance region {region_id} {field} must be non-negative",
                        retryable=False,
                    )
                return result

            output_start_us = bound("output_start_us")
            output_end_us = bound("output_end_us")
            if output_end_us <= output_start_us:
                raise VisionBackendUnavailable(
                    f"semantic QC source_audio_performance region {region_id} output window is invalid",
                    retryable=False,
                )
            projected: dict[str, Any] = {
                "region_id": region_id,
                "audio_mode": mode,
                "output_start_us": output_start_us,
                "output_end_us": output_end_us,
            }
            if mode == "source_master":
                source_start_us = bound("source_start_us")
                source_end_us = bound("source_end_us")
                if source_end_us <= source_start_us or (
                    source_end_us - source_start_us != output_end_us - output_start_us
                ):
                    raise VisionBackendUnavailable(
                        f"semantic QC source_audio_performance region {region_id} source window is invalid",
                        retryable=False,
                    )
                projected.update(
                    {
                        "source_start_us": source_start_us,
                        "source_end_us": source_end_us,
                    }
                )
            elif mode == "opaque_audio_keep":
                projected["opaque_media_sha256"] = _require_sha(
                    raw_region.get("opaque_media_sha256"),
                    f"semantic QC source_audio_performance opaque region {region_id} opaque_media_sha256",
                )
            else:
                raise VisionBackendUnavailable(
                    f"semantic QC source_audio_performance region {region_id} has unsupported audio mode",
                    retryable=False,
                )
            regions.append(projected)
        normalized["regions"] = regions
        return normalized

    @staticmethod
    def _source_evidence(context: Any | None) -> list[dict[str, Any]]:
        """Serialize optional sampled evidence bytes, never a worker path."""

        raw = getattr(context, "semantic_qc_evidence", ()) if context is not None else ()
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            return []
        result: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping):
                raise VisionBackendUnavailable(
                    f"semantic QC evidence {index} is not an object",
                    retryable=False,
                )
            digest = _require_sha(item.get("artifact_sha256"), f"semantic QC evidence {index} artifact_sha256")
            data = item.get("bytes")
            if not isinstance(data, (bytes, bytearray)) or not data:
                raise VisionBackendUnavailable(
                    f"semantic QC evidence {index} must contain non-empty bytes",
                    retryable=False,
                )
            data_bytes = bytes(data)
            if _sha256_bytes(data_bytes) != digest:
                raise VisionBackendUnavailable(
                    f"semantic QC evidence {index} bytes do not match artifact_sha256",
                    retryable=False,
                )
            result.append(
                {
                    "artifact_sha256": digest,
                    "content_type": str(item.get("content_type") or "application/octet-stream"),
                    "start_ms": item.get("start_ms"),
                    "end_ms": item.get("end_ms"),
                    "bytes_base64": base64.b64encode(data_bytes).decode("ascii"),
                }
            )
        return result

    def _validate_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        request_sha256: str,
        response_payload: Mapping[str, Any],
        final_output_sha256: str,
        current_run_source_sha256s: Sequence[str],
        dimensions: Mapping[str, Any],
        factor_scores: Mapping[str, Any],
    ) -> dict[str, Any]:
        if receipt.get("schema_version") != "high-fidelity-qc-evaluator-receipt/v1":
            raise VisionBackendUnavailable("semantic QC evaluator receipt schema is unsupported", retryable=False)
        if receipt.get("provenance") != "independent_evaluator":
            raise VisionBackendUnavailable("semantic QC evaluator receipt provenance is invalid", retryable=False)
        identity = self.capability_identity()
        for field in ("implementation", "version", "model_id", "model_sha256"):
            if str(receipt.get(field) or "") != str(identity.get(field) or ""):
                raise VisionBackendUnavailable(
                    f"semantic QC evaluator receipt {field} does not match the pinned evaluator",
                    retryable=False,
                )
        for field in (
            "model_sha256",
            "request_sha256",
            "response_sha256",
            "dimensions_sha256",
            "factor_scores_sha256",
            "final_output_sha256",
        ):
            _require_sha(receipt.get(field), f"semantic QC evaluator receipt {field}")
        sources = receipt.get("current_run_source_sha256s")
        expected_sources = sorted(set(current_run_source_sha256s))
        if not isinstance(sources, list) or sources != expected_sources:
            raise VisionBackendUnavailable(
                "semantic QC evaluator receipt source set does not match the current Run",
                retryable=False,
            )
        if str(receipt.get("request_sha256")) != request_sha256:
            raise VisionBackendUnavailable(
                "semantic QC evaluator receipt request SHA does not match the canonical request",
                retryable=False,
            )
        if str(receipt.get("response_sha256")) != _canonical_sha256(response_payload):
            raise VisionBackendUnavailable(
                "semantic QC evaluator receipt response SHA does not match the QC evidence",
                retryable=False,
            )
        if str(receipt.get("final_output_sha256")) != final_output_sha256:
            raise VisionBackendUnavailable(
                "semantic QC evaluator receipt final output SHA does not match the media bytes",
                retryable=False,
            )
        if str(receipt.get("dimensions_sha256")) != _qc_dimensions_digest(dimensions):
            raise VisionBackendUnavailable(
                "semantic QC evaluator receipt dimensions digest does not match the QC evidence",
                retryable=False,
            )
        if str(receipt.get("factor_scores_sha256")) != _qc_factor_scores_digest(factor_scores):
            raise VisionBackendUnavailable(
                "semantic QC evaluator receipt factor-scores digest does not match the QC evidence",
                retryable=False,
            )
        return dict(receipt)

    def evaluate(
        self,
        *,
        path: Path,
        context: Any | None = None,
        input_artifacts: Sequence[Mapping[str, Any]] = (),
        final_output_sha256: str,
        current_run_source_sha256s: Sequence[str],
        source_audio_performance: Mapping[str, Any] | None = None,
        request_payload: Mapping[str, Any] | None = None,
        request_sha256: str | None = None,
    ) -> Mapping[str, Any]:
        media_path = Path(path)
        try:
            media_bytes = media_path.read_bytes()
        except OSError as exc:
            raise VisionBackendUnavailable("semantic QC final media cannot be read", retryable=False) from exc
        if not media_bytes:
            raise VisionBackendUnavailable("semantic QC final media is empty", retryable=False)
        if len(media_bytes) > self.max_media_bytes:
            raise VisionBackendUnavailable("semantic QC final media exceeds the configured byte limit", retryable=False)
        media_sha256 = _sha256_bytes(media_bytes)
        final_output_sha256 = _require_sha(final_output_sha256, "final_output_sha256")
        if media_sha256 != final_output_sha256:
            raise VisionBackendUnavailable(
                "semantic QC final media SHA does not match final_output_sha256",
                retryable=False,
            )
        source_digests = [_require_sha(item, "current_run_source_sha256") for item in current_run_source_sha256s]
        if not source_digests or len(set(source_digests)) != len(source_digests):
            raise VisionBackendUnavailable(
                "semantic QC current Run source SHA set must be non-empty and unique",
                retryable=False,
            )
        source_digests = sorted(source_digests)
        artifacts = [item for item in input_artifacts if isinstance(item, Mapping)]
        normalized_source_audio_performance = (
            self._source_audio_performance_projection(source_audio_performance)
            if source_audio_performance is not None
            else None
        )
        if normalized_source_audio_performance is not None:
            if normalized_source_audio_performance["final_output_sha256"] != final_output_sha256:
                raise VisionBackendUnavailable(
                    "semantic QC source_audio_performance final output SHA does not match actual media",
                    retryable=False,
                )
            if normalized_source_audio_performance["source_media_sha256"] not in source_digests:
                raise VisionBackendUnavailable(
                    "semantic QC source_audio_performance source media SHA is not in the current Run",
                    retryable=False,
                )
        expected_request = self._request_payload(
            final_output_sha256=final_output_sha256,
            current_run_source_sha256s=source_digests,
            input_artifacts=artifacts,
            source_audio_performance=normalized_source_audio_performance,
        )
        if request_payload is not None:
            if not isinstance(request_payload, Mapping):
                raise VisionBackendUnavailable(
                    "semantic QC request payload must be an object",
                    retryable=False,
                )
            supplied_request = dict(request_payload)
            if supplied_request.get("final_output_sha256") != expected_request["final_output_sha256"]:
                raise VisionBackendUnavailable(
                    "semantic QC request payload final_output_sha256 does not match actual media",
                    retryable=False,
                )
            if supplied_request.get("current_run_source_sha256s") != expected_request["current_run_source_sha256s"]:
                raise VisionBackendUnavailable(
                    "semantic QC request payload current_run_source_sha256s does not match the current Run",
                    retryable=False,
                )
            if supplied_request.get("input_artifact_sha256s") != expected_request["input_artifact_sha256s"]:
                raise VisionBackendUnavailable(
                    "semantic QC request payload input_artifact_sha256s does not match input artifacts",
                    retryable=False,
                )
            if supplied_request != expected_request:
                raise VisionBackendUnavailable(
                    "semantic QC request payload does not match the canonical request",
                    retryable=False,
                )
            canonical_request = supplied_request
        else:
            canonical_request = expected_request
        expected_request_sha256 = _canonical_sha256(canonical_request)
        if request_sha256 is not None and str(request_sha256) != expected_request_sha256:
            raise VisionBackendUnavailable(
                "semantic QC request SHA does not match the canonical request",
                retryable=False,
            )
        source_evidence = self._source_evidence(context)
        response, transport_request_sha256, transport_response_sha256 = self._post(
            {
                "schema_version": self.schema_version,
                "evaluator_request": canonical_request,
                "evaluator_request_sha256": expected_request_sha256,
                "media_sha256": media_sha256,
                "media_content_type": "video/mp4",
                "media_base64": base64.b64encode(media_bytes).decode("ascii"),
                "source_evidence": source_evidence,
                "expected_model": {"id": self.model_id, "sha256": self.model_sha256},
            }
        )
        if str(response.get("evaluator_request_sha256") or "") != expected_request_sha256:
            raise VisionBackendUnavailable(
                "semantic QC response is not bound to the canonical evaluator request",
                retryable=False,
            )
        if str(response.get("media_sha256") or "") != media_sha256:
            raise VisionBackendUnavailable("semantic QC response media SHA does not match the media bytes", retryable=False)
        qc_input = response.get("qc_input")
        if not isinstance(qc_input, Mapping):
            raise VisionBackendUnavailable("semantic QC response qc_input must be an object", retryable=False)
        qc_input = dict(qc_input)
        dimensions = qc_input.get("dimensions")
        factor_scores = qc_input.get("factor_scores")
        if not isinstance(dimensions, Mapping) or not isinstance(factor_scores, Mapping) or not factor_scores:
            raise VisionBackendUnavailable(
                "semantic QC response requires dimensions and non-empty factor_scores",
                retryable=False,
            )
        if not isinstance(qc_input.get("hard_failures"), list):
            raise VisionBackendUnavailable("semantic QC response hard_failures must be an array", retryable=False)
        receipt = qc_input.get("evaluator_receipt")
        if not isinstance(receipt, Mapping):
            raise VisionBackendUnavailable("semantic QC response requires an evaluator receipt", retryable=False)
        response_payload = {key: value for key, value in qc_input.items() if key != "evaluator_receipt"}
        normalized_receipt = self._validate_receipt(
            receipt,
            request_sha256=expected_request_sha256,
            response_payload=response_payload,
            final_output_sha256=final_output_sha256,
            current_run_source_sha256s=source_digests,
            dimensions=dimensions,
            factor_scores=factor_scores,
        )
        qc_input["evaluator_receipt"] = normalized_receipt
        return {
            "qc_input": qc_input,
            "backend_evidence": {
                "schema_version": self.schema_version,
                "transport_request_sha256": transport_request_sha256,
                "transport_response_sha256": transport_response_sha256,
                "evaluator_request_sha256": expected_request_sha256,
                "media_sha256": media_sha256,
                "model_id": self.model_id,
                "model_sha256": self.model_sha256,
                "source_evidence_count": len(source_evidence),
            },
        }

    __call__ = evaluate


class EvidenceBoundHttpVlmBackend(_EvidenceBoundHttpBackend):
    """Extract bounded evidence frames and call a private semantic VLM."""

    schema_version = "usfr-vlm-evidence/v1"
    implementation = "server.vision_backends:EvidenceBoundHttpVlmBackend"

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        model_sha256: str,
        api_token: str | None = None,
        api_token_env: str | None = None,
        timeout_seconds: float = 180.0,
        max_response_bytes: int = 8 * 1024 * 1024,
        production: bool = True,
        ffmpeg_bin: str | None = None,
        max_frames: int = 24,
        max_frame_width: int = 768,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            model_id=model_id,
            model_sha256=model_sha256,
            api_token=api_token,
            api_token_env=api_token_env,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            production=production,
        )
        if not 1 <= int(max_frames) <= 96:
            raise ValueError("max_frames must be in [1, 96]")
        if not 128 <= int(max_frame_width) <= 2048:
            raise ValueError("max_frame_width must be in [128, 2048]")
        self.ffmpeg_bin = ffmpeg_bin
        self.max_frames = int(max_frames)
        self.max_frame_width = int(max_frame_width)

    @classmethod
    def from_environment(cls, *, production: bool = True) -> "EvidenceBoundHttpVlmBackend":
        return cls(
            endpoint=os.environ["USFR_VLM_ENDPOINT"],
            model_id=os.environ["USFR_VLM_MODEL_ID"],
            model_sha256=os.environ["USFR_VLM_MODEL_SHA256"],
            api_token_env="USFR_VLM_API_TOKEN",
            production=production,
        )

    def _timestamps(self, *, duration_us: int, fps: float, cuts: Sequence[Mapping[str, Any]]) -> list[int]:
        frame_step_us = max(1_000, int(round(1_000_000 / fps))) if fps > 0 else 33_333
        last_decodable_us = max(0, duration_us - frame_step_us)
        candidates = {0, last_decodable_us}
        for item in cuts:
            try:
                start = max(0, int(item.get("start_us") or 0))
                end = min(duration_us, int(item.get("end_us") or duration_us))
            except (TypeError, ValueError):
                continue
            if end > start:
                candidates.add(start)
                candidates.add(min(last_decodable_us, start + (end - start) // 2))
                candidates.add(max(start, min(last_decodable_us, end - frame_step_us)))
        ordered = sorted(max(0, min(last_decodable_us, value)) for value in candidates)
        ordered = list(dict.fromkeys(ordered))
        if len(ordered) <= self.max_frames:
            return ordered
        positions = [round(index * (len(ordered) - 1) / (self.max_frames - 1)) for index in range(self.max_frames)] if self.max_frames > 1 else [len(ordered) // 2]
        return [ordered[index] for index in dict.fromkeys(positions)]

    def _frame(self, path: Path, timestamp_us: int) -> bytes:
        executable = self.ffmpeg_bin or shutil.which("ffmpeg")
        if not executable:
            raise VisionBackendUnavailable("ffmpeg is required to extract VLM evidence frames")
        command = [
            str(executable),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp_us / 1_000_000:.6f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={self.max_frame_width}:-2:force_original_aspect_ratio=decrease",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
        try:
            result = subprocess.run(command, check=False, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VisionBackendUnavailable("VLM evidence frame extraction failed") from exc
        if result.returncode != 0 or not result.stdout:
            raise VisionBackendUnavailable("VLM evidence frame extraction produced no image")
        return bytes(result.stdout)

    def analyze(
        self,
        *,
        path: Path,
        probe: Mapping[str, Any],
        cuts: Sequence[Mapping[str, Any]],
        evidence_plan: Mapping[str, Any] | None = None,
        analysis_scope: Mapping[str, Any] | None = None,
        context: Any | None = None,
    ) -> Mapping[str, Any]:
        active_profile = _active_high_fidelity_context(context)
        source = Path(path)
        try:
            source_sha256 = _sha256_file(source)
        except OSError as exc:
            raise VisionBackendUnavailable("VLM source video cannot be read") from exc
        try:
            duration_us = int(probe.get("duration_us"))
        except (TypeError, ValueError) as exc:
            raise VisionBackendUnavailable("VLM probe has no valid duration", retryable=False) from exc
        if duration_us <= 0:
            raise VisionBackendUnavailable("VLM probe duration must be positive", retryable=False)
        validated_evidence_plan = None
        if evidence_plan is not None:
            validated_evidence_plan = _validated_adaptive_evidence_plan(
                evidence_plan,
                source_sha256=source_sha256,
                duration_us=duration_us,
            )
        frames: list[dict[str, Any]] = []
        try:
            fps = float(probe.get("fps") or 0)
        except (TypeError, ValueError):
            fps = 0.0
        timestamps = self._timestamps(duration_us=duration_us, fps=fps, cuts=cuts)
        if active_profile:
            uncovered = []
            for index, item in enumerate(cuts, start=1):
                try:
                    start_us = int(item.get("start_us") or 0)
                    end_us = int(item.get("end_us") or duration_us)
                except (TypeError, ValueError):
                    uncovered.append(index)
                    continue
                if not any(start_us <= timestamp < end_us for timestamp in timestamps):
                    uncovered.append(index)
            if uncovered:
                raise VisionBackendUnavailable(
                    "active high-fidelity VLM frame coverage is insufficient for source Cut(s)",
                    details={"uncovered_cuts": uncovered, "sample_count": len(timestamps)},
                    retryable=False,
                )
        for timestamp_us in timestamps:
            data = self._frame(source, timestamp_us)
            frames.append(
                {
                    "timestamp_us": timestamp_us,
                    "sha256": _sha256_bytes(data),
                    "content_type": "image/jpeg",
                    "image_base64": base64.b64encode(data).decode("ascii"),
                }
            )
        if not frames:
            raise VisionBackendUnavailable("VLM analysis has no evidence frames")
        decoder_cuts = []
        for index, item in enumerate(cuts, start=1):
            decoder_cuts.append(
                {
                    "cut": int(item.get("cut") or index),
                    "start_us": int(item.get("start_us") or 0),
                    "end_us": int(item.get("end_us") or 0),
                }
            )
        route_policy: dict[str, Any] | None = None
        context_routes = getattr(context, "routes", None) if context is not None else None
        if isinstance(context_routes, Mapping):
            route_policy = {
                "ui_route": str(context_routes.get("ui") or "source_ui_keep"),
                "tail_route": str(context_routes.get("tail") or "omit_source_end_card"),
                "opaque_content_policy": "do_not_semantically_inspect_or_regenerate",
                "source_preserve_policy": "retain_source_pixels_and_timing",
            }
        request_payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "source_sha256": source_sha256,
            "source": {
                "duration_us": duration_us,
                "width": int(probe.get("width") or 0),
                "height": int(probe.get("height") or 0),
                "fps": float(probe.get("fps") or 0),
            },
            "decoder_cuts": decoder_cuts,
            "frames": frames,
            "expected_model": {"id": self.model_id, "sha256": self.model_sha256},
        }
        if route_policy is not None:
            request_payload["route_policy"] = route_policy
        if validated_evidence_plan is not None:
            request_payload["evidence_plan"] = validated_evidence_plan
        if analysis_scope is not None:
            request_payload["analysis_scope"] = dict(analysis_scope)
        response, request_sha256, response_sha256 = self._post(
            request_payload
        )
        if response.get("source_sha256") != source_sha256:
            raise VisionBackendUnavailable("VLM response source SHA does not match the exact source video", retryable=False)
        frame_sha256s = [item["sha256"] for item in frames]
        if response.get("frame_sha256s") != frame_sha256s:
            raise VisionBackendUnavailable("VLM response is not bound to the exact sampled frames", retryable=False)
        frame_timestamps: dict[str, list[int]] = {}
        for frame in frames:
            frame_timestamps.setdefault(str(frame["sha256"]), []).append(int(frame["timestamp_us"]))
        source_cuts_value = response.get("source_cuts")
        if not isinstance(source_cuts_value, list) or not source_cuts_value:
            raise VisionBackendUnavailable("VLM response source_cuts must be a non-empty array", retryable=False)
        source_cuts: list[dict[str, Any]] = []
        cursor = 0
        for index, item in enumerate(source_cuts_value, start=1):
            if not isinstance(item, Mapping):
                raise VisionBackendUnavailable("VLM source cut must be an object", details={"cut": index}, retryable=False)
            try:
                start_us = int(item.get("start_us"))
                end_us = int(item.get("end_us"))
            except (TypeError, ValueError) as exc:
                raise VisionBackendUnavailable("VLM source cut timing must be integer microseconds", details={"cut": index}, retryable=False) from exc
            if start_us != cursor or end_us <= start_us or end_us > duration_us:
                raise VisionBackendUnavailable("VLM source cuts must be contiguous from frame zero", details={"cut": index}, retryable=False)
            refs = item.get("evidence_refs")
            referenced = {
                str(ref.get("frame_sha256") or "")
                for ref in refs
                if isinstance(refs, list) and isinstance(ref, Mapping)
            } if isinstance(refs, list) else set()
            if not referenced.intersection(frame_sha256s):
                raise VisionBackendUnavailable("VLM source cut has no reference to a sampled evidence frame", details={"cut": index}, retryable=False)
            clean_refs: list[dict[str, Any]] = []
            for ref in refs if isinstance(refs, list) else []:
                if not isinstance(ref, Mapping):
                    continue
                digest = str(ref.get("frame_sha256") or "")
                if digest not in frame_timestamps:
                    continue
                clean_ref: dict[str, Any] = {"kind": "frame", "frame_sha256": digest}
                if ref.get("timestamp_us") is not None:
                    try:
                        timestamp_us = int(ref.get("timestamp_us"))
                    except (TypeError, ValueError) as exc:
                        raise VisionBackendUnavailable(
                            "VLM source cut evidence timestamp is invalid",
                            details={"cut": index},
                            retryable=False,
                        ) from exc
                    if timestamp_us not in frame_timestamps[digest]:
                        raise VisionBackendUnavailable(
                            "VLM source cut evidence timestamp is not one of the sampled frames",
                            details={"cut": index},
                            retryable=False,
                        )
                    clean_ref["timestamp_us"] = timestamp_us
                clean_refs.append(clean_ref)
            record: dict[str, Any] = {
                "cut": index,
                "start_us": start_us,
                "end_us": end_us,
                "evidence_refs": clean_refs,
            }
            # Read semantic fields from the response only after constructing a
            # whitelist record; arbitrary response keys (especially paths)
            # never enter a durable dynamics artifact.
            for field in ("scene", "action", "camera", "transition", "end_state", "certainty"):
                record[field] = _safe_text(item.get(field), f"VLM source cut {index} {field}")
            if item.get("subject_presence") is not None:
                record["subject_presence"] = _safe_text(item.get("subject_presence"), f"VLM source cut {index} subject_presence")
            roles = item.get("content_roles")
            if isinstance(roles, list):
                record["content_roles"] = [
                    _safe_text(value, f"VLM source cut {index} content role")
                    for value in roles
                ]
            source_cuts.append(record)
            cursor = end_us
        if cursor != duration_us:
            raise VisionBackendUnavailable("VLM source cuts do not cover the exact decoded end", retryable=False)
        if active_profile:
            for index, record in enumerate(source_cuts, start=1):
                referenced_times = _bound_frame_times_for_records(
                    record.get("evidence_refs"), frame_timestamps
                )
                evidence_refs = record.get("evidence_refs")
                _validate_cut_local_frame_records(
                    evidence_refs,
                    frame_timestamps,
                    start_us=record["start_us"],
                    end_us=record["end_us"],
                    label=f"active high-fidelity source Cut {index}",
                )
                if not any(record["start_us"] <= timestamp < record["end_us"] for timestamp in referenced_times):
                    raise VisionBackendUnavailable(
                        f"active high-fidelity source Cut {index} evidence is not bound to a decoded sampled frame inside its Cut timing",
                        retryable=False,
                    )
        source_events = response.get("source_events")
        if not isinstance(source_events, list):
            raise VisionBackendUnavailable("VLM response source_events must be an array", retryable=False)
        clean_events: list[dict[str, Any]] = []
        for index, item in enumerate(source_events, start=1):
            if not isinstance(item, Mapping):
                continue
            event: dict[str, Any] = {}
            for field in ("event", "source_cut_start", "source_cut_end", "start_us", "end_us"):
                if item.get(field) is not None:
                    try:
                        event[field] = int(item.get(field))
                    except (TypeError, ValueError) as exc:
                        raise VisionBackendUnavailable("VLM source event has invalid integer timing", details={"event": index}, retryable=False) from exc
            for field in ("kind", "text", "certainty"):
                if item.get(field) is not None:
                    event[field] = _safe_text(item.get(field), f"VLM source event {index} {field}")
            refs = item.get("evidence_refs")
            if isinstance(refs, list):
                allowed = {
                    str(ref.get("frame_sha256") or "")
                    for ref in refs
                    if isinstance(ref, Mapping)
                }.intersection(frame_sha256s)
                event["evidence_refs"] = [
                    {"kind": "frame", "frame_sha256": value}
                    for value in frame_sha256s
                    if value in allowed
                ]
            event.setdefault("event", index)
            clean_events.append(event)

        extension: dict[str, Any] | None = None
        if active_profile:
            raw_extensions = response.get("extensions")
            if not isinstance(raw_extensions, Mapping) or "high_fidelity_hybrid_v1" not in raw_extensions:
                raise VisionBackendUnavailable(
                    "active high-fidelity VLM response requires extensions.high_fidelity_hybrid_v1",
                    retryable=False,
                )
            extension = _validate_hf_extension_response(
                raw_extensions.get("high_fidelity_hybrid_v1"),
                source_cuts=source_cuts,
                source_events=clean_events,
                frame_sha256s=frame_sha256s,
                frame_timestamps=frame_timestamps,
            )

        overlay_contract: dict[str, Any] | None = None
        if "source_overlay_contract" in response:
            overlay_contract = _validate_source_overlay_contract(
                response.get("source_overlay_contract"),
                duration_us=duration_us,
            )

        result: dict[str, Any] = {
            "source_cuts": source_cuts,
            "source_events": clean_events,
            "backend_evidence": {
                "schema_version": self.schema_version,
                "request_sha256": request_sha256,
                "response_sha256": response_sha256,
                "source_sha256": source_sha256,
                "frame_sha256s": frame_sha256s,
                "model_id": self.model_id,
                "model_sha256": self.model_sha256,
            },
        }
        if validated_evidence_plan is not None:
            result["backend_evidence"]["evidence_plan_sha256"] = validated_evidence_plan["plan_sha256"]
        if extension is not None:
            result["extensions"] = {"high_fidelity_hybrid_v1": extension}
        if overlay_contract is not None:
            result["source_overlay_contract"] = overlay_contract
            result["backend_evidence"]["source_overlay_contract_sha256"] = _sha256_bytes(
                _canonical_json(overlay_contract)
            )
        return result

    def __call__(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
        if kwargs:
            return self.analyze(**kwargs)
        if len(args) < 3:
            raise TypeError("VLM backend requires path, probe, and cuts")
        return self.analyze(path=args[0], probe=args[1], cuts=args[2])


__all__ = [
    "VisionBackendUnavailable",
    "EvidenceBoundHttpOcrBackend",
    "EvidenceBoundHttpSemanticQcEvaluator",
    "EvidenceBoundHttpUiRenderer",
    "EvidenceBoundHttpVlmBackend",
]
