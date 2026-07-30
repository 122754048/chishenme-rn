from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .analysis_scope import build_analysis_scope
from .errors import ReplicationError


HIGH_FIDELITY_PROFILE = "high_fidelity_hybrid_v1"
SEMANTIC_STAGE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"id": 1, "name": "intake_bind"},
    {"id": 2, "name": "target_truth"},
    {"id": 3, "name": "dynamics"},
    {"id": 4, "name": "region_overlay_route"},
    {"id": 5, "name": "intent"},
    {"id": 6, "name": "script"},
    {"id": 7, "name": "region_duration"},
    {"id": 8, "name": "storyboard"},
    {"id": 9, "name": "prompt_audit"},
    {"id": 10, "name": "provider"},
    {"id": 11, "name": "assembly"},
    {"id": 12, "name": "qc_delivery"},
)
_SEMANTIC_STAGE_IDS = {
    item["name"]: int(item["id"])
    for item in SEMANTIC_STAGE_DEFINITIONS
}
_OPERATIONAL_STAGE_SEMANTICS: dict[str, tuple[str, ...]] = {
    "bind_inputs": ("intake_bind",),
    "probe_source": ("intake_bind",),
    "parse_app_store_evidence": ("target_truth",),
    "resolve_ui_evidence": ("target_truth",),
    "analyze_dynamics": ("dynamics",),
    "route_regions": ("region_overlay_route",),
    # Intent and script remain co-located in build_script.  Region duration is
    # frozen only after script approval, inside generate_storyboards, without
    # adding a RunState stage or changing the queue/approval contract.
    "build_script": ("intent", "script"),
    "await_script_approval": ("script",),
    "generate_storyboards": ("storyboard",),
    "await_storyboard_approval": ("storyboard",),
    "compile_seedance20_prompt": ("prompt_audit",),
    "audit_seedance_request": ("prompt_audit",),
    "submit_provider_video": ("provider",),
    "wait_provider_video": ("provider",),
    "splice_timeline": ("assembly",),
    "run_qc": ("qc_delivery",),
}
_INTERNAL_STEP_SEMANTICS: dict[str, str] = {
    "source_audio_authorization": "intake_bind",
    "audio_lyrics_beat": "dynamics",
    "performance_line_contract": "script",
    "performance_timeline_contract": "region_duration",
    "performance_storyboard": "storyboard",
    "performance_prompt_audit": "prompt_audit",
    "source_audio_refill": "assembly",
    "source_audio_performance_qc": "qc_delivery",
    "source_intent_graph": "intent",
    "target_value_graph": "intent",
    "claim_atoms": "intent",
    "affordance_map": "intent",
    "layer_ledger": "intent",
    "seedance_invocation_a": "script",
    "exact_line_contract": "script",
    "duration_planner": "region_duration",
    "segment_plan": "region_duration",
    "segment_local_rebind": "region_duration",
    "seedance_invocation_b": "prompt_audit",
    "seedance20_skill_snapshot_check": "prompt_audit",
    "exact_line_parity": "prompt_audit",
    "high_fidelity_factor_audit": "prompt_audit",
    "hybrid_compositor": "assembly",
    "timeline_splice": "assembly",
    "technical_qc": "qc_delivery",
    "technical_timeline_qc": "qc_delivery",
    "opaque_media_qc": "qc_delivery",
    "high_fidelity_qc_extension": "qc_delivery",
    "voiceover_alignment": "qc_delivery",
}

_TARGET_TRUTH_BINDING_SLOTS = (
    "new_product_image",
    "new_model_image",
    "ui_screenshot",
)


def _slot_present(value: Any) -> bool:
    """Read the fixed-slot presence bit without re-identifying its role."""

    if isinstance(value, Mapping):
        return bool(value.get("present"))
    return bool(value)


def build_semantic_stage_mapping(
    stages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Project operational entries onto the frozen twelve semantic stages.

    The public workflow intentionally has more operational entries than
    semantic stages: evidence resolution, approvals, provider submit/poll,
    and internal high-fidelity work are all represented as durable worker
    operations.  This read-only projection makes that relationship explicit
    for deployment audits without adding a RunState stage, approval, route, or
    Provider task.
    """

    operational: list[dict[str, Any]] = []
    unknown: list[str] = []
    observed: set[str] = set()
    stage_positions: dict[str, list[int]] = {}
    for index, raw_stage in enumerate(stages):
        if not isinstance(raw_stage, Mapping):
            unknown.append(f"<non-object:{index}>")
            continue
        name = str(raw_stage.get("name") or "").strip()
        semantic_names = _OPERATIONAL_STAGE_SEMANTICS.get(name)
        if semantic_names is None:
            unknown.append(name or f"<unnamed:{index}>")
            semantic_names = ()
        normalized_names = list(semantic_names)
        if name == "bind_inputs" and raw_stage.get("target_truth_bound") is True:
            normalized_names.append("target_truth")
            normalized_names = list(dict.fromkeys(normalized_names))
        observed.update(normalized_names)
        for semantic_name in normalized_names:
            stage_positions.setdefault(semantic_name, []).append(index)
        internal_names: list[str] = []
        for raw_step in raw_stage.get("internal_steps", ()) or ():
            step = str(raw_step or "").strip()
            semantic_name = _INTERNAL_STEP_SEMANTICS.get(step)
            if semantic_name is None:
                if step:
                    unknown.append(f"{name}.internal_steps:{step}")
                continue
            internal_names.append(semantic_name)
            observed.add(semantic_name)
        operational.append(
            {
                "index": index,
                "name": name,
                "semantic_stage_ids": [
                    _SEMANTIC_STAGE_IDS[item] for item in normalized_names
                ],
                "semantic_stage_names": normalized_names,
                "internal_semantic_stage_names": sorted(set(internal_names)),
            }
        )

    # A target-truth lookup can be intentionally deferred until route_regions
    # proves that a generated UI carrier will consume it.  A semantic stage is
    # deferred when a later canonical stage appears operationally first; report
    # the deferred stage itself, not the stage that happened to run before it.
    deferred: list[int] = []
    first_positions = {
        name: min(positions) for name, positions in stage_positions.items()
    }
    for name, stage_id in _SEMANTIC_STAGE_IDS.items():
        position = first_positions.get(name)
        if position is None:
            continue
        if any(
            later_position < position
            for later_name, later_position in first_positions.items()
            if _SEMANTIC_STAGE_IDS[later_name] > stage_id
        ):
            deferred.append(stage_id)

    approval_count = sum(
        1
        for item in stages
        if isinstance(item, Mapping) and item.get("kind") == "approval"
    )
    # The review route is authoritative for user approval semantics.  Route 1
    # reuses an already approved script (storyboard approval remains), while
    # local-only has no review gates.  Keep the structural fallback for legacy
    # plans that do not carry route metadata.
    route_values = {
        str(item.get("review_route") or item.get("route") or "")
        for item in stages
        if isinstance(item, Mapping)
    }
    route = next((item for item in route_values if item in {"route_1", "route_2", "local_only"}), None)
    if route == "route_1":
        approval_count = 1
    elif route == "local_only":
        approval_count = 0
    provider_stage_entry_count = sum(
        1
        for item in stages
        if isinstance(item, Mapping) and item.get("provider") is True
        and item.get("kind") in {"provider_create", "provider_poll"}
    )
    return {
        "semantic_stage_count": len(SEMANTIC_STAGE_DEFINITIONS),
        "semantic_stage_names": [item["name"] for item in SEMANTIC_STAGE_DEFINITIONS],
        "semantic_stage_ids": [item["id"] for item in SEMANTIC_STAGE_DEFINITIONS],
        "observed_semantic_stage_ids": sorted(
            _SEMANTIC_STAGE_IDS[item] for item in observed
        ),
        "operational_stage_count": len(operational),
        "operational_stages": operational,
        "unknown_operational_stages": sorted(set(unknown)),
        "deferred_semantic_stage_ids": sorted(set(deferred)),
        "user_approval_count": approval_count,
        "provider_stage_entry_count": provider_stage_entry_count,
        "max_provider_tasks": 2,
    }


HIGH_FIDELITY_REQUIRED_METADATA = [
    "producer_stage",
    "parent_digests",
    "profile_digest",
    "content_type",
    "size_bytes",
]
HIGH_FIDELITY_STAGE_ARTIFACTS: dict[str, tuple[dict[str, str], ...]] = {
    "analyze_dynamics": (
        {"kind": "performance_audio_source_contract", "logical_path": "analysis/performance_audio_source_contract.json"},
        {"kind": "audio_lyrics_beat_contract", "logical_path": "analysis/audio_lyrics_beat_contract.json"},
        {"kind": "source_content_timeline", "logical_path": "analysis/source_content_timeline.json"},
    ),
    "build_script": (
        {"kind": "high_fidelity_analysis", "logical_path": "analysis/high_fidelity_analysis.json"},
        {"kind": "seedance20_prescript_v1", "logical_path": "analysis/seedance20_prescript_v1.json"},
        {"kind": "exact_line_contract", "logical_path": "analysis/exact_line_contract.json"},
        {"kind": "performance_line_contract", "logical_path": "analysis/performance_line_contract.json"},
    ),
    "generate_storyboards": (
        {"kind": "segment_plan", "logical_path": "analysis/segment_plan.json"},
        {"kind": "performance_timeline_contract", "logical_path": "analysis/performance_timeline_contract.json"},
    ),
    "compile_seedance20_prompt": (
        {"kind": "seedance_input_contract", "logical_path": "seedance/seedance_input_contract.json"},
    ),
    "audit_seedance_request": (
        {"kind": "seedance_request_audit", "logical_path": "seedance/seedance_request_audit.json"},
    ),
    "splice_timeline": (
        {"kind": "assembled_video", "logical_path": "final/assembled_video.mp4"},
        {"kind": "hybrid_composite_manifest", "logical_path": "final/hybrid_composite_manifest.json"},
        {"kind": "audio_splice_policy", "logical_path": "final/audio_splice_policy.json"},
    ),
    "run_qc": (
        {"kind": "qc_report", "logical_path": "final/qc_report.json"},
        {"kind": "high_fidelity_qc_extension", "logical_path": "final/high_fidelity_qc_extension.json"},
    ),
}
HIGH_FIDELITY_PROMPT_INTEGRITY_ARTIFACTS = tuple(
    artifact
    for stage in ("analyze_dynamics", "build_script", "compile_seedance20_prompt", "audit_seedance_request")
    for artifact in HIGH_FIDELITY_STAGE_ARTIFACTS[stage]
)


def _artifact_contract(stage: str) -> dict[str, Any]:
    return {
        "profile": HIGH_FIDELITY_PROFILE,
        "required_artifacts": [dict(item) for item in HIGH_FIDELITY_STAGE_ARTIFACTS[stage]],
        "required_metadata": list(HIGH_FIDELITY_REQUIRED_METADATA),
    }


def _timeline_region_items(
    timeline_regions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    raw: Any = timeline_regions.get("regions") if isinstance(timeline_regions, Mapping) else timeline_regions
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise ValueError("timeline_regions must be a region sequence or an object with a regions sequence")
    result: list[Mapping[str, Any]] = []
    for index, region in enumerate(raw):
        if not isinstance(region, Mapping):
            raise ValueError(f"timeline_regions[{index}] must be an object")
        result.append(region)
    return result


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _overlay_contract_from_analysis(value: Any) -> Mapping[str, Any] | None:
    """Read the immutable overlay contract from one dynamics-pass envelope."""

    if not isinstance(value, Mapping):
        return None
    direct = value.get("source_overlay_contract")
    if isinstance(direct, Mapping):
        return direct
    nested = value.get("source_dynamics_analysis")
    if isinstance(nested, Mapping):
        direct = nested.get("source_overlay_contract")
        if isinstance(direct, Mapping):
            return direct
    return None


def _overlay_mapping_from_timeline(value: Mapping[str, Any]) -> Mapping[str, Any] | None:
    mapping = value.get("overlay_render_mapping")
    return mapping if isinstance(mapping, Mapping) else None


def _region_microseconds(region: Mapping[str, Any]) -> tuple[int, int] | None:
    try:
        if region.get("source_start_us") is not None or region.get("source_end_us") is not None:
            start = int(region.get("source_start_us"))
            end = int(region.get("source_end_us"))
        else:
            start = round(float(region.get("source_start") or region.get("start") or 0.0) * 1_000_000)
            end = round(float(region.get("source_end") or region.get("end") or 0.0) * 1_000_000)
    except (TypeError, ValueError):
        return None
    return start, end


def _generated_ui_source_interval_contract(region: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project one routed generated-UI interval into its frozen source contract.

    Stage 4 already owns the source region boundaries and transition shell.  The
    optional Remotion adapter must consume those facts rather than infer them
    after target UI truth is resolved in the next stage.  Return ``None`` when
    the route has not frozen every required source fact so callers retain the
    deterministic fallback instead of inventing a contract.
    """

    kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
    if kind not in {"generated_ui_demo", "generated_ui"}:
        return None
    region_id = str(region.get("region_id") or "").strip()
    interval = _region_microseconds(region)
    viewport = region.get("display_viewport")
    transition_shell = region.get("transition_shell")
    try:
        rotation = int(region.get("rotation_degrees"))
        crop = float(region.get("safe_cover_crop_percent"))
        width, height = int(viewport[0]), int(viewport[1])
    except (IndexError, TypeError, ValueError):
        return None
    if (
        not region_id
        or interval is None
        or interval[0] < 0
        or interval[1] <= interval[0]
        or interval[0] % 1000 != 0
        or interval[1] % 1000 != 0
        or width <= 0
        or height <= 0
        or rotation not in {0, 90, 180, 270}
        or not 0 <= crop <= 12
        or not isinstance(transition_shell, Mapping)
        or not transition_shell
    ):
        return None
    start_ms, end_ms = interval[0] // 1000, interval[1] // 1000
    normalized_crop: int | float = int(crop) if crop.is_integer() else crop
    return {
        "schema_version": "source-ui-interval/v1",
        "region_id": region_id,
        "source_start_ms": start_ms,
        "source_end_ms": end_ms,
        "output_duration_ms": end_ms - start_ms,
        "display_viewport": [width, height],
        "rotation_degrees": rotation,
        "safe_cover_crop_percent": normalized_crop,
        "transition_shell": json.loads(json.dumps(transition_shell, ensure_ascii=False, sort_keys=True)),
    }


def _bind_generated_ui_source_interval_contracts(
    regions: Sequence[dict[str, Any]],
) -> None:
    for region in regions:
        existing = region.get("source_interval_contract")
        canonical_contract = _generated_ui_source_interval_contract(region)
        if isinstance(existing, Mapping) and canonical_contract is not None:
            normalized_existing = json.loads(json.dumps(existing, ensure_ascii=False, sort_keys=True))
            if _canonical_sha256(normalized_existing) != _canonical_sha256(canonical_contract):
                raise ReplicationError(
                    "SOURCE_UI_INTERVAL_CONTRACT_MISMATCH",
                    "SOURCE_UI_INTERVAL_CONTRACT_MISMATCH: supplied source_interval_contract differs from routed source facts",
                    category="timeline",
                    user_action_required=True,
                    details={"region_id": canonical_contract["region_id"]},
                )
            contract = canonical_contract
        elif isinstance(existing, Mapping):
            contract = json.loads(json.dumps(existing, ensure_ascii=False, sort_keys=True))
        else:
            contract = canonical_contract
        if contract is not None:
            region["source_interval_contract"] = contract
            region["source_interval_contract_sha256"] = _canonical_sha256(contract)


def _timeline_has_generated_overlay_overlap(
    regions: Sequence[Mapping[str, Any]],
    source_overlay_contract: Mapping[str, Any],
) -> bool:
    overlays_by_interval: list[tuple[int, int]] = []
    for cut in source_overlay_contract.get("cuts", []):
        if not isinstance(cut, Mapping):
            continue
        try:
            cut_start = int(cut.get("start_us"))
            cut_end = int(cut.get("end_us"))
        except (TypeError, ValueError):
            continue
        if cut_end <= cut_start:
            continue
        if any(isinstance(item, Mapping) for item in (cut.get("source_overlays") or [])):
            overlays_by_interval.append((cut_start, cut_end))
    if not overlays_by_interval:
        return False
    for region in regions:
        kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
        if kind not in {"generated", "generated_ui", "generated_ui_demo"}:
            continue
        interval = _region_microseconds(region)
        if interval is None:
            continue
        start, end = interval
        if any(end > overlay_start and start < overlay_end for overlay_start, overlay_end in overlays_by_interval):
            return True
    return False


def _validate_source_overlay_contract_shape(value: Mapping[str, Any]) -> None:
    if value.get("contract") != "source-ui-overlay-motion" or value.get("contract_version") != 1:
        raise ReplicationError(
            "OVERLAY_CONTRACT_INVALID",
            "OVERLAY_CONTRACT_INVALID: unsupported source_overlay_contract",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    try:
        duration = int(value.get("reference_duration_us"))
    except (TypeError, ValueError) as exc:
        raise ReplicationError(
            "OVERLAY_CONTRACT_INVALID",
            "OVERLAY_CONTRACT_INVALID: reference_duration_us must be positive",
            category="timeline",
            user_action_required=True,
            http_status=422,
        ) from exc
    cuts = value.get("cuts")
    if duration <= 0 or not isinstance(cuts, list) or not cuts:
        raise ReplicationError(
            "OVERLAY_CONTRACT_INVALID",
            "OVERLAY_CONTRACT_INVALID: source overlay cuts are required",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    cursor = 0
    for index, cut in enumerate(cuts, start=1):
        if not isinstance(cut, Mapping):
            raise ReplicationError("OVERLAY_CONTRACT_INVALID", f"OVERLAY_CONTRACT_INVALID: Cut {index} is not an object", category="timeline", user_action_required=True, http_status=422)
        try:
            start = int(cut.get("start_us"))
            end = int(cut.get("end_us"))
        except (TypeError, ValueError) as exc:
            raise ReplicationError("OVERLAY_CONTRACT_INVALID", f"OVERLAY_CONTRACT_INVALID: Cut {index} timing is invalid", category="timeline", user_action_required=True, http_status=422) from exc
        if start != cursor or end <= start or end > duration or not isinstance(cut.get("source_overlays"), list):
            raise ReplicationError("OVERLAY_CONTRACT_INVALID", f"OVERLAY_CONTRACT_INVALID: Cut {index} is not contiguous or lacks source_overlays", category="timeline", user_action_required=True, http_status=422)
        cursor = end
    if cursor != duration:
        raise ReplicationError("OVERLAY_CONTRACT_INVALID", "OVERLAY_CONTRACT_INVALID: source overlay cuts do not cover the reference duration", category="timeline", user_action_required=True, http_status=422)


def bind_source_overlay_contract_to_timeline(
    timeline_regions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    dynamics_output: Mapping[str, Any] | None,
    *,
    enforce_generated_mapping: bool = False,
    target_overlay_replacements: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind one validated source overlay contract to the Stage-4 timeline.

    ``route_regions`` is the only stage that decides which source intervals
    are generated, opaque, or source-preserved.  This bridge carries the
    immutable contract produced by the single dynamics pass into that same
    timeline envelope and into the first durable region row.  It deliberately
    never edits geometry, timing, keyframes, or source overlay contents.
    """

    if isinstance(timeline_regions, Mapping):
        result = dict(timeline_regions)
        raw_regions = result.get("regions")
        if raw_regions is None and isinstance(result.get("timeline_regions"), (list, tuple)):
            raw_regions = result.get("timeline_regions")
    else:
        result = {}
        raw_regions = timeline_regions
    if not isinstance(raw_regions, Sequence) or isinstance(raw_regions, (str, bytes, bytearray)):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "timeline_regions must contain a region array",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    regions = [dict(item) for item in raw_regions if isinstance(item, Mapping)]
    if len(regions) != len(raw_regions):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "timeline_regions entries must be objects",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )

    incoming = _overlay_contract_from_analysis(dynamics_output)
    existing = result.get("source_overlay_contract")
    if existing is not None and not isinstance(existing, Mapping):
        raise ReplicationError(
            "OVERLAY_CONTRACT_INVALID",
            "timeline source_overlay_contract must be an object",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    if incoming is not None and existing is not None and _canonical_sha256(existing) != _canonical_sha256(incoming):
        raise ReplicationError(
            "OVERLAY_CONTRACT_MISMATCH",
            "OVERLAY_CONTRACT_MISMATCH: route_regions attempted to replace the immutable source_overlay_contract",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    contract = incoming or existing
    mapping = _overlay_mapping_from_timeline(result)
    if contract is not None:
        _validate_source_overlay_contract_shape(contract)
    if (
        mapping is None
        and enforce_generated_mapping
        and isinstance(contract, Mapping)
        and target_overlay_replacements is not None
    ):
        from .overlay_mapping import build_overlay_render_mapping

        mapping = build_overlay_render_mapping(
            contract,
            regions,
            replacements=target_overlay_replacements,
        )
    if enforce_generated_mapping and contract is not None and _timeline_has_generated_overlay_overlap(regions, contract):
        if mapping is None:
            raise ReplicationError(
                "OVERLAY_RENDER_MAPPING_REQUIRED",
                "OVERLAY_RENDER_MAPPING_REQUIRED: source_overlay_contract declares semantic overlays in a generated region but overlay_render_mapping is missing",
                category="timeline",
                user_action_required=True,
                http_status=422,
            )

    if contract is not None:
        contract_copy = json.loads(json.dumps(contract, ensure_ascii=False, sort_keys=True))
        contract_sha = _canonical_sha256(contract_copy)
        result["source_overlay_contract"] = contract_copy
        result["source_overlay_contract_sha256"] = contract_sha
        if mapping is not None:
            mapping_copy = json.loads(json.dumps(mapping, ensure_ascii=False, sort_keys=True))
            result["overlay_render_mapping"] = mapping_copy
            result["overlay_render_mapping_sha256"] = _canonical_sha256(mapping_copy)
        if enforce_generated_mapping and _timeline_has_generated_overlay_overlap(regions, contract):
            result["overlay_render_receipts_required"] = True
        for index, region in enumerate(regions):
            region["source_overlay_contract_sha256"] = contract_sha
            if mapping is not None:
                region["overlay_render_mapping_sha256"] = result["overlay_render_mapping_sha256"]
            # The first region is the durable carrier when the database stores
            # only per-region metadata.  Repeated digest fields on every row
            # make tampering or partial deletion detectable downstream.
            if index == 0:
                region["source_overlay_contract"] = contract_copy
                if mapping is not None:
                    region["overlay_render_mapping"] = result["overlay_render_mapping"]
    _bind_generated_ui_source_interval_contracts(regions)
    result["regions"] = regions
    result.pop("timeline_regions", None)
    if not str(result.get("timeline_regions_sha256") or ""):
        result["timeline_regions_sha256"] = _canonical_sha256(result)
    return result


def timeline_regions_require_generation(
    timeline_regions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> bool:
    """Return whether validated Stage-4 carriers require generated media.

    Slot routes are only a pre-analysis prediction.  Once timeline regions
    exist, their actual media carrier and assembly policy are authoritative.
    Composite, source-origin, and opaque/user-upload carriers stay local.
    """
    for region in _timeline_region_items(timeline_regions):
        media_origin = str(region.get("media_origin") or "").strip().lower()
        assembly_policy = str(region.get("assembly_policy") or "").strip().lower()
        if media_origin in {"generated", "generated_media"}:
            return True
        if assembly_policy == "generate_region" or assembly_policy.startswith("generate_"):
            return True
    return False


def timeline_regions_require_seedance_generation(
    timeline_regions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> bool:
    """Return whether Stage-4 carriers require ordinary Seedance generation.

    Generated UI is real generated media, but it belongs to the deterministic
    UI renderer/timeline lane.  It must never trigger script, storyboard,
    Image Gen, Invocation A/B, CreateAsset, or CreateVideo work.
    """

    for region in _timeline_region_items(timeline_regions):
        kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
        media_origin = str(region.get("media_origin") or "").strip().lower()
        assembly_policy = str(region.get("assembly_policy") or "").strip().lower()
        if (
            kind in {"generated_ui", "generated_ui_demo"}
            or media_origin in {"generated_ui", "generated_ui_media"}
            or assembly_policy in {"generate_ui", "render_generated_ui"}
        ):
            continue
        if media_origin in {"generated", "generated_media"}:
            return True
        if assembly_policy == "generate_region" or assembly_policy.startswith("generate_"):
            return True
    return False


def _timeline_regions_require_generated_ui(
    timeline_regions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> bool:
    for region in _timeline_region_items(timeline_regions):
        kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
        media_origin = str(region.get("media_origin") or "").strip().lower()
        assembly_policy = str(region.get("assembly_policy") or "").strip().lower()
        if (
            kind in {"generated_ui", "generated_ui_demo"}
            or media_origin in {"generated_ui", "generated_ui_media"}
            or assembly_policy in {"generate_ui", "render_generated_ui"}
        ):
            return True
    return False


def validate_timeline_region_persistence(
    artifact: Mapping[str, Any] | None,
    regions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    active: bool = False,
) -> None:
    """Fail closed when the Stage-4 artifact and indexed rows disagree."""

    if not isinstance(artifact, Mapping):
        return
    metadata = artifact.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    required_fields = ("region_count", "generation_required", "timeline_regions_sha256")
    if active and any(field not in metadata for field in required_fields):
        raise ReplicationError(
            "TIMELINE_REGION_PERSISTENCE_MISMATCH",
            "TIMELINE_REGION_PERSISTENCE_MISMATCH: timeline_regions artifact metadata is incomplete for active production",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    raw = regions.get("regions") if isinstance(regions, Mapping) else regions
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise ReplicationError(
            "TIMELINE_REGION_PERSISTENCE_MISMATCH",
            "TIMELINE_REGION_PERSISTENCE_MISMATCH: timeline region rows are not an array",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    if "region_count" in metadata:
        try:
            expected_count = int(metadata.get("region_count"))
        except (TypeError, ValueError):
            expected_count = -1
        if expected_count != len(raw):
            raise ReplicationError(
                "TIMELINE_REGION_PERSISTENCE_MISMATCH",
                "TIMELINE_REGION_PERSISTENCE_MISMATCH: timeline_regions artifact region_count does not match indexed rows",
                category="timeline",
                user_action_required=True,
                http_status=422,
                details={"expected": expected_count, "actual": len(raw)},
            )
    if "generation_required" in metadata:
        actual_generation = timeline_regions_require_generation(raw)
        if bool(metadata.get("generation_required")) != actual_generation:
            raise ReplicationError(
                "TIMELINE_REGION_PERSISTENCE_MISMATCH",
                "TIMELINE_REGION_PERSISTENCE_MISMATCH: timeline_regions artifact generation_required does not match indexed rows",
                category="timeline",
                user_action_required=True,
                http_status=422,
            )
    artifact_sha = str(artifact.get("sha256") or metadata.get("timeline_regions_sha256") or "").lower()
    declared_sha = str(metadata.get("timeline_regions_sha256") or "").lower()
    if artifact_sha and declared_sha and artifact_sha != declared_sha:
        raise ReplicationError(
            "TIMELINE_REGION_PERSISTENCE_MISMATCH",
            "TIMELINE_REGION_PERSISTENCE_MISMATCH: timeline_regions artifact SHA and metadata SHA differ",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    for index, row in enumerate(raw):
        if not isinstance(row, Mapping):
            raise ReplicationError(
                "TIMELINE_REGION_PERSISTENCE_MISMATCH",
                f"TIMELINE_REGION_PERSISTENCE_MISMATCH: timeline region row {index} is not an object",
                category="timeline",
                user_action_required=True,
                http_status=422,
            )
        row_meta = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else row
        row_sha = str(row_meta.get("timeline_regions_sha256") or "").lower()
        if declared_sha and row_sha and row_sha != declared_sha:
            raise ReplicationError(
                "TIMELINE_REGION_PERSISTENCE_MISMATCH",
                f"TIMELINE_REGION_PERSISTENCE_MISMATCH: timeline region row {index} has a different timeline SHA",
                category="timeline",
                user_action_required=True,
                http_status=422,
            )


def stage_dedupe_key(
    run_id: str,
    stage: str,
    input_digest: str,
    workflow_version: str,
    *,
    profile_digest: str | None = None,
    capability_manifest_digest: str | None = None,
) -> str:
    value = f"{run_id}:{stage}:{input_digest}:{workflow_version}"
    if profile_digest:
        value += f":{profile_digest}"
    if capability_manifest_digest:
        value += f":{capability_manifest_digest}"
    value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def build_stage_plan(
    manifest: Mapping[str, Any],
    *,
    workflow_version: str = "server-v1",
    timeline_regions: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    review_route: str | None = None,
) -> list[dict[str, Any]]:
    analysis_scope = build_analysis_scope(manifest)
    routes = dict(manifest.get("routes") or {})
    slots = dict(manifest.get("slots") or {})
    extensions = dict(manifest.get("extensions") or {})
    profile = (extensions.get("high_fidelity_profile") or {})
    profile_active = profile.get("profile") == HIGH_FIDELITY_PROFILE
    # A historical route_1 marker is accepted only for compatibility.  It is
    # normalized to route_2 because every generated-media run must let the
    # user edit and confirm both its script and storyboard.
    execution_route = extensions.get("execution_route") or manifest.get("execution_route")
    selected_review_route = review_route or extensions.get("review_route") or manifest.get("review_route") or execution_route
    if selected_review_route in {"route_1", "local_only"}:
        selected_review_route = "route_2"
    stages: list[dict[str, Any]] = [
        {"name": "bind_inputs", "kind": "deterministic", "provider": False, "analysis_scope": analysis_scope},
        {"name": "probe_source", "kind": "deterministic", "provider": False, "analysis_scope": analysis_scope},
        {"name": "analyze_dynamics", "kind": "analysis", "provider": False, "analysis_scope": analysis_scope},
        {"name": "route_regions", "kind": "deterministic", "provider": False, "analysis_scope": analysis_scope},
    ]
    target_truth_slots = [
        slot_name
        for slot_name in _TARGET_TRUTH_BINDING_SLOTS
        if _slot_present(slots.get(slot_name))
    ]
    if target_truth_slots:
        # Fixed-slot binding is the target-truth boundary for image evidence;
        # App Store URL evidence remains intentionally deferred until routing
        # proves that a generated UI carrier will consume it.
        stages[0]["target_truth_bound"] = True
        stages[0]["target_truth_slots"] = target_truth_slots
    if timeline_regions is not None:
        seedance_generation_required = timeline_regions_require_seedance_generation(timeline_regions)
        generated_ui_required = _timeline_regions_require_generated_ui(timeline_regions)
    else:
        seedance_generation_required = (
            routes.get("product") == "replace_from_slot"
            or routes.get("character") == "replace_from_slot"
            or manifest.get("output_language") is not None
        )
        generated_ui_required = routes.get("ui") == "generated_ui_demo"
    # App Store evidence is only needed for an actual generated UI carrier.
    # It must be resolved before the deterministic UI renderer consumes it.
    # A validated Stage-4 timeline overrides the earlier slot prediction.
    if generated_ui_required and _slot_present(slots.get("app_store_url")):
        stages.append({"name": "parse_app_store_evidence", "kind": "evidence", "provider": True})
    if generated_ui_required:
        stages.append({"name": "resolve_ui_evidence", "kind": "evidence", "provider": False})
    language_only = bool(manifest.get("admission", {}).get("language_only"))
    if language_only:
        build_script = {"name": "build_script", "kind": "contract", "provider": False, "language_only": True}
        compile_prompt = {"name": "compile_seedance20_prompt", "kind": "audit", "provider": False, "language_only": True}
        audit_request = {"name": "audit_seedance_request", "kind": "audit", "provider": False, "language_only": True}
        storyboard_stage: dict[str, Any] = {
            "name": "generate_storyboards",
            "kind": "image2",
            "provider": True,
            "language_only": True,
        }
        if profile_active:
            build_script["internal_steps"] = [
                "source_intent_graph",
                "target_value_graph",
                "claim_atoms",
                "affordance_map",
                "layer_ledger",
                "seedance_invocation_a",
                "exact_line_contract",
            ]
            compile_prompt["internal_steps"] = ["seedance_invocation_b", "seedance20_skill_snapshot_check"]
            audit_request["internal_steps"] = ["exact_line_parity", "high_fidelity_factor_audit"]
            build_script["artifact_contract"] = _artifact_contract("build_script")
            compile_prompt["artifact_contract"] = _artifact_contract("compile_seedance20_prompt")
            audit_request["artifact_contract"] = _artifact_contract("audit_seedance_request")
            storyboard_stage["internal_steps"] = [
                "duration_planner",
                "segment_plan",
                "segment_local_rebind",
            ]
            storyboard_stage["artifact_contract"] = _artifact_contract("generate_storyboards")
        stages.extend(
            [
                build_script,
                {"name": "await_script_approval", "kind": "approval", "provider": False, "language_only": True},
                storyboard_stage,
                {"name": "await_storyboard_approval", "kind": "approval", "provider": False, "language_only": True},
                compile_prompt,
                audit_request,
                {"name": "submit_provider_video", "kind": "provider_create", "provider": True, "language_only": True},
                {"name": "wait_provider_video", "kind": "provider_poll", "provider": True, "language_only": True},
                {"name": "splice_timeline", "kind": "assembly", "provider": False, "language_only": True,
                 **({"internal_steps": ["hybrid_compositor", "timeline_splice"], "artifact_contract": _artifact_contract("splice_timeline")} if profile_active else {})},
                {"name": "run_qc", "kind": "qc", "provider": False, "language_only": True,
                 **({"internal_steps": ["technical_qc", "high_fidelity_qc_extension", "voiceover_alignment"], "artifact_contract": _artifact_contract("run_qc")} if profile_active else {})},
            ]
        )
        storyboard_stage["provider"] = False
        storyboard_stage["mode"] = "source_or_opaque_review"
        return [dict(stage, workflow_version=workflow_version, review_route="route_2") for stage in stages]
    if not seedance_generation_required:
        stages.extend(
            [
                {"name": "build_script", "kind": "contract", "provider": False},
                {"name": "await_script_approval", "kind": "approval", "provider": False},
                {
                    "name": "generate_storyboards",
                    "kind": "deterministic_review",
                    "provider": False,
                    "mode": "source_or_opaque_review",
                },
                {"name": "await_storyboard_approval", "kind": "approval", "provider": False},
                {"name": "splice_timeline", "kind": "assembly", "provider": False},
                {"name": "run_qc", "kind": "qc", "provider": False},
            ]
        )
        if profile_active:
            stages[-2]["profile_skips"] = [
                "deep_commercial_intent",
                "target_value_graph",
                "exact_line_contract",
                "seedance_invocation_a",
                "seedance_invocation_b",
            ]
            stages[-2]["internal_steps"] = ["technical_timeline_qc", "opaque_media_qc"]
        return [dict(stage, workflow_version=workflow_version, **({"review_route": selected_review_route} if selected_review_route else {})) for stage in stages]
    build_script = {"name": "build_script", "kind": "contract", "provider": False}
    compile_prompt = {"name": "compile_seedance20_prompt", "kind": "audit", "provider": False}
    audit_request = {"name": "audit_seedance_request", "kind": "audit", "provider": False}
    if profile_active:
        build_script["internal_steps"] = [
            "source_intent_graph",
            "target_value_graph",
            "claim_atoms",
            "affordance_map",
            "layer_ledger",
            "seedance_invocation_a",
            "exact_line_contract",
        ]
        compile_prompt["internal_steps"] = ["seedance_invocation_b", "seedance20_skill_snapshot_check"]
        audit_request["internal_steps"] = ["exact_line_parity", "high_fidelity_factor_audit"]
        build_script["artifact_contract"] = _artifact_contract("build_script")
        compile_prompt["artifact_contract"] = _artifact_contract("compile_seedance20_prompt")
        audit_request["artifact_contract"] = _artifact_contract("audit_seedance_request")
    approval_and_storyboard = [
        build_script,
        {"name": "await_script_approval", "kind": "approval", "provider": False},
    ]
    storyboard_stage: dict[str, Any] = {
        "name": "generate_storyboards",
        "kind": "image2",
        "provider": True,
    }
    if profile_active:
        storyboard_stage["internal_steps"] = [
            "duration_planner",
            "segment_plan",
            "segment_local_rebind",
        ]
        storyboard_stage["artifact_contract"] = _artifact_contract(
            "generate_storyboards"
        )
    approval_and_storyboard.extend(
        [
            storyboard_stage,
            {"name": "await_storyboard_approval", "kind": "approval", "provider": False},
            compile_prompt,
            audit_request,
            {"name": "submit_provider_video", "kind": "provider_create", "provider": True},
            {"name": "wait_provider_video", "kind": "provider_poll", "provider": True},
            {"name": "splice_timeline", "kind": "assembly", "provider": False,
             **({"internal_steps": ["hybrid_compositor", "timeline_splice"], "artifact_contract": _artifact_contract("splice_timeline")} if profile_active else {})},
            {"name": "run_qc", "kind": "qc", "provider": False,
             **({"internal_steps": ["technical_qc", "high_fidelity_qc_extension", "voiceover_alignment"], "artifact_contract": _artifact_contract("run_qc")} if profile_active else {})},
        ]
    )
    stages.extend(approval_and_storyboard)
    return [dict(stage, workflow_version=workflow_version, **({"review_route": selected_review_route} if selected_review_route else {})) for stage in stages]
