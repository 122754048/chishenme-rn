"""Invocation A: deterministic Seedance-20 executability sidecar.

Invocation A is an internal, non-provider pass.  It allocates fidelity and
checks that an approved source/target contract can fit the fixed-B route.  It
never creates assets or a paid video task and never becomes a public workflow
stage.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from line_contract import validate_line_contracts


PROFILE = "seedance20_prescript_v1"
SKILL_NAME = "seedance-20"
SCHEMA_VERSION = "seedance20-prescript/v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FIDELITY_SPENDS = {"identity", "motion", "scene"}
_BACKGROUND_STRATEGIES = {"KEEP", "COMPOSITE", "REPLACE"}
_LINE_CARRIERS = {"prompt", "postproduction"}
_FACTOR_CARRIERS = {"prompt", "reference", "payload", "postproduction", "route_excluded"}
_FACTOR_CRITICALITIES = {"H", "M", "L"}
_MUSIC_POLICIES = {"none", "preserve_source", "approved"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(path: Any) -> str:
    if hasattr(path, "read_bytes") and not isinstance(path, Path):
        return hashlib.sha256(bytes(path.read_bytes())).hexdigest()
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _skill_metadata(path: Any) -> tuple[str, str, str]:
    if hasattr(path, "read_text") and not isinstance(path, Path):
        raw = path.read_text(encoding="utf-8")
    else:
        raw = Path(path).read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*([^\n]+)\s*$", raw)
    if not match or match.group(1).strip() != SKILL_NAME:
        raise ValueError("seedance-20 skill snapshot has the wrong name")
    version_match = re.search(r"(?m)^\s*version:\s*([^\n]+)\s*$", raw)
    version = version_match.group(1).strip().strip('"\'') if version_match else "unknown"
    return match.group(1).strip(), version, _file_sha(path)


def _validate_digest(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _non_empty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must be an array of non-empty strings")
    return list(value)


def _integer_ms(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer number of milliseconds")
    return value


def _validate_projection_candidate_timing(candidate: Mapping[str, Any]) -> None:
    output_start = candidate.get("output_global_start_ms")
    output_end = candidate.get("output_global_end_ms")
    canonical = candidate.get("canonical_segment")
    if output_start is None and output_end is None and canonical is None:
        return
    if output_start is None or output_end is None:
        raise ValueError("projection-bound candidate requires complete output-global bounds")
    output_start = _integer_ms(output_start, "candidate.output_global_start_ms")
    output_end = _integer_ms(output_end, "candidate.output_global_end_ms")
    duration = _integer_ms(candidate.get("duration_ms"), "candidate.duration_ms")
    if output_start < 0 or output_end - output_start != duration:
        raise ValueError("candidate output-global bounds must match its duration")

    shots = candidate.get("shot_budget")
    if not isinstance(shots, list) or not shots:
        raise ValueError("projection-bound shot_budget must be non-empty")
    previous_local_end = 0
    previous_global_end = output_start
    observed_cut_ids: list[str] = []
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, Mapping):
            raise ValueError(f"shot_budget[{index}] must be an object")
        local_start = _integer_ms(shot.get("start_ms"), f"shot_budget[{index}].start_ms")
        local_end = _integer_ms(shot.get("end_ms"), f"shot_budget[{index}].end_ms")
        shot_duration = _integer_ms(
            shot.get("duration_ms"),
            f"shot_budget[{index}].duration_ms",
        )
        global_start = _integer_ms(
            shot.get("output_global_start_ms"),
            f"shot_budget[{index}].output_global_start_ms",
        )
        global_end = _integer_ms(
            shot.get("output_global_end_ms"),
            f"shot_budget[{index}].output_global_end_ms",
        )
        if (
            local_start != previous_local_end
            or local_end <= local_start
            or local_end > duration
            or shot_duration != local_end - local_start
            or global_start != output_start + local_start
            or global_end != output_start + local_end
            or global_start != previous_global_end
        ):
            raise ValueError(
                f"shot_budget[{index}] bounds must be contiguous and match the candidate clock"
            )
        cut_id = shot.get("cut_id")
        if not isinstance(cut_id, str) or not cut_id:
            raise ValueError(f"shot_budget[{index}].cut_id is required")
        observed_cut_ids.append(cut_id)
        previous_local_end = local_end
        previous_global_end = global_end
    if previous_local_end != duration or previous_global_end != output_end:
        raise ValueError("shot_budget bounds must exactly cover the candidate")
    if observed_cut_ids != list(candidate.get("cut_ids") or []):
        raise ValueError("shot_budget Cut order differs from candidate cut_ids")

    states = candidate.get("action_state_requirements")
    if not isinstance(states, list) or not states:
        raise ValueError("action_state_requirements must be non-empty")
    completed_ends: list[int] = []
    for index, state in enumerate(states, start=1):
        if not isinstance(state, Mapping):
            raise ValueError(f"action_state_requirements[{index}] must be an object")
        local_start = _integer_ms(
            state.get("start_ms"),
            f"action_state_requirements[{index}].start_ms",
        )
        local_end = _integer_ms(
            state.get("end_ms"),
            f"action_state_requirements[{index}].end_ms",
        )
        if local_start < 0 or local_end <= local_start or local_end > duration:
            raise ValueError(
                f"action_state_requirements[{index}] bounds must remain inside the candidate"
            )
        global_start = state.get("output_global_start_ms")
        global_end = state.get("output_global_end_ms")
        if global_start is not None or global_end is not None:
            if global_start is None or global_end is None:
                raise ValueError(
                    f"action_state_requirements[{index}] output-global bounds are incomplete"
                )
            if (
                _integer_ms(
                    global_start,
                    f"action_state_requirements[{index}].output_global_start_ms",
                )
                != output_start + local_start
                or _integer_ms(
                    global_end,
                    f"action_state_requirements[{index}].output_global_end_ms",
                )
                != output_start + local_end
            ):
                raise ValueError(
                    f"action_state_requirements[{index}] bounds differ from the candidate clock"
                )
        if state.get("phase") == "completed" and state.get("required") is True:
            completed_ends.append(local_end)
    if not completed_ends or max(completed_ends) != duration:
        raise ValueError("completed action endpoint must terminate at the candidate end")

    if not isinstance(canonical, Mapping):
        raise ValueError("projection-bound candidate requires canonical_segment")
    expected_canonical = {
        "start_ms": output_start,
        "end_ms": output_end,
        "duration_ms": duration,
        "cut_ids": list(candidate.get("cut_ids") or []),
        "shots": shots,
    }
    for field, expected in expected_canonical.items():
        if canonical.get(field) != expected:
            raise ValueError(f"canonical_segment.{field} differs from the candidate")
    if canonical.get("segment_id") is not None:
        raise ValueError("canonical_segment.segment_id must remain unbound before Stage 7")


def _validate_candidate(
    candidate: Mapping[str, Any],
    *,
    require_factor_coverage: bool = False,
) -> None:
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate region must be an object")
    region_id = candidate.get("candidate_region_id")
    if not isinstance(region_id, str) or not region_id:
        raise ValueError("candidate_region_id is required")
    cut_ids = candidate.get("cut_ids")
    if (
        not isinstance(cut_ids, list)
        or not cut_ids
        or any(not isinstance(item, str) or not item for item in cut_ids)
        or len(cut_ids) != len(set(cut_ids))
    ):
        raise ValueError("candidate region must contain contiguous cut_ids")
    required_factor_ids = candidate.get("required_factor_ids")
    if require_factor_coverage or required_factor_ids is not None:
        if (
            not isinstance(required_factor_ids, list)
            or not required_factor_ids
            or any(not isinstance(item, str) or not item.strip() for item in required_factor_ids)
            or len(required_factor_ids) != len(set(required_factor_ids))
        ):
            raise ValueError("candidate required_factor_ids must be a unique non-empty string array")
    duration = candidate.get("duration_ms")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 4000 or duration > 15000:
        raise ValueError("candidate duration must be between 4000 and 15000 milliseconds")
    output_start = candidate.get("output_global_start_ms")
    output_end = candidate.get("output_global_end_ms")
    if output_start is not None or output_end is not None:
        if (
            isinstance(output_start, bool)
            or not isinstance(output_start, int)
            or isinstance(output_end, bool)
            or not isinstance(output_end, int)
            or output_start < 0
            or output_end - output_start != duration
        ):
            raise ValueError("candidate output-global bounds must match its duration")
    retime_scale = candidate.get("retime_scale")
    if retime_scale is not None and (
        isinstance(retime_scale, bool)
        or not isinstance(retime_scale, (int, float))
        or float(retime_scale) <= 0
    ):
        raise ValueError("candidate retime_scale must be positive")
    if candidate.get("primary_fidelity_spend") not in _FIDELITY_SPENDS:
        raise ValueError("candidate must have exactly one primary fidelity spend")
    secondary = candidate.get("secondary_fidelity_spend")
    if secondary is not None and secondary not in _FIDELITY_SPENDS:
        raise ValueError("secondary_fidelity_spend is invalid")
    if secondary == candidate.get("primary_fidelity_spend"):
        raise ValueError("secondary_fidelity_spend must differ from the primary spend")
    if candidate.get("mode") != "fixed_b_image_reference":
        raise ValueError("candidate mode must remain fixed_b_image_reference")
    if candidate.get("single_take_or_multishot") not in {"single_take", "multishot"}:
        raise ValueError("single_take_or_multishot is invalid")

    for field in ("allowed_split_cut_ids", "forbidden_split_cut_ids", "economized_factors"):
        _string_list(candidate.get(field), field)
    allowed = set(candidate["allowed_split_cut_ids"])
    forbidden = set(candidate["forbidden_split_cut_ids"])
    if not allowed <= set(cut_ids) or not forbidden <= set(cut_ids) or allowed & forbidden:
        raise ValueError("allowed/forbidden split Cut IDs must be disjoint candidate Cuts")

    shots = candidate.get("shot_budget")
    if not isinstance(shots, list) or not shots:
        raise ValueError("shot_budget must be non-empty")
    shot_ids: set[str] = set()
    shot_duration = 0
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, Mapping):
            raise ValueError(f"shot_budget[{index}] must be an object")
        shot_id = _non_empty(shot.get("shot_id"), f"shot_budget[{index}].shot_id")
        if shot_id in shot_ids:
            raise ValueError(f"shot_budget repeats shot_id {shot_id}")
        shot_ids.add(shot_id)
        duration_ms = shot.get("duration_ms")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms <= 0:
            raise ValueError(f"shot_budget[{index}].duration_ms must be positive")
        shot_duration += duration_ms
        _non_empty(shot.get("primary_action"), f"shot_budget[{index}].primary_action")
        _non_empty(shot.get("endpoint"), f"shot_budget[{index}].endpoint")
    if shot_duration != duration:
        raise ValueError("shot_budget durations must exactly cover candidate duration")

    roles = candidate.get("reference_role_plan", [])
    if not isinstance(roles, list) or len(roles) > 4:
        raise ValueError("candidate cannot use more than four image roles")
    seen_roles: set[Any] = set()
    for role in roles:
        if not isinstance(role, Mapping):
            raise ValueError("reference role must be an object")
        slot = role.get("slot")
        if slot not in {1, 2, 3, 4}:
            raise ValueError("reference role slots must be in the fixed 1-4 range")
        if slot in seen_roles:
            raise ValueError("reference role slots must be unique")
        seen_roles.add(slot)
        _non_empty(role.get("role"), "reference role role")

    if candidate.get("background_strategy") not in _BACKGROUND_STRATEGIES:
        raise ValueError("background_strategy is invalid")
    if not isinstance(candidate.get("performance_strategy"), Mapping) or not candidate["performance_strategy"]:
        raise ValueError("performance_strategy must be a non-empty object")
    states = candidate.get("action_state_requirements")
    if not isinstance(states, list) or not states:
        raise ValueError("action_state_requirements must be non-empty")
    has_completed = False
    for index, state in enumerate(states, start=1):
        if not isinstance(state, Mapping):
            raise ValueError(f"action_state_requirements[{index}] must be an object")
        phase = _non_empty(state.get("phase"), f"action_state_requirements[{index}].phase")
        _non_empty(state.get("state"), f"action_state_requirements[{index}].state")
        if not isinstance(state.get("required"), bool):
            raise ValueError(f"action_state_requirements[{index}].required must be boolean")
        has_completed = has_completed or (phase == "completed" and state["required"] is True)
    if not has_completed:
        raise ValueError("action_state_requirements requires a completed endpoint")

    audio = candidate.get("audio_strategy")
    if not isinstance(audio, Mapping) or not audio:
        raise ValueError("audio_strategy must be a non-empty object")
    if audio.get("music_policy") not in _MUSIC_POLICIES:
        raise ValueError("audio_strategy.music_policy is invalid")
    _non_empty(audio.get("ambience"), "audio_strategy.ambience")
    _string_list(audio.get("foley_event_ids"), "audio_strategy.foley_event_ids")
    _string_list(audio.get("silence_window_ids"), "audio_strategy.silence_window_ids")

    voice_plan = candidate.get("voiceover_timing_plan")
    if not isinstance(voice_plan, list):
        raise ValueError("voiceover_timing_plan must be an array")
    planned_lines: set[str] = set()
    for index, item in enumerate(voice_plan, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"voiceover_timing_plan[{index}] must be an object")
        line_id = _non_empty(item.get("line_id"), f"voiceover_timing_plan[{index}].line_id")
        if line_id in planned_lines:
            raise ValueError(f"voiceover_timing_plan repeats line_id {line_id}")
        planned_lines.add(line_id)
        if item.get("carrier") not in _LINE_CARRIERS:
            raise ValueError(f"voiceover_timing_plan[{index}].carrier is invalid")

    for field in ("prompt_carrier_plan", "postproduction_carrier_plan", "hard_blockers", "warnings"):
        if not isinstance(candidate.get(field), list):
            raise ValueError(f"{field} must be an array")
    for key in ("opaque_ui_demo", "tail_video", "source_interval", "source_ui_keep", "transition_shell"):
        if key in candidate:
            raise ValueError(f"opaque/source route must remain outside Invocation A semantics: {key}")
    _validate_projection_candidate_timing(candidate)


def _validate_line_carriers(
    candidates: Sequence[Mapping[str, Any]],
    lines: Sequence[Mapping[str, Any]],
) -> None:
    candidates_by_id = {candidate["candidate_region_id"]: candidate for candidate in candidates}
    line_ids = {line["line_id"] for line in lines}
    planned_ids: set[str] = set()
    for candidate in candidates:
        region_id = candidate["candidate_region_id"]
        for item in candidate["voiceover_timing_plan"]:
            line_id = item["line_id"]
            if line_id in planned_ids:
                raise ValueError(f"line carrier is duplicated: {line_id}")
            planned_ids.add(line_id)
            if line_id not in line_ids:
                raise ValueError(f"line carrier references an unknown line: {line_id}")
            if item.get("carrier") not in _LINE_CARRIERS:
                raise ValueError(f"line carrier is invalid: {line_id}")
        for line in lines:
            if line.get("candidate_region_id") != region_id:
                continue
            if line["cut_id"] not in candidate["cut_ids"]:
                raise ValueError(f"line Cut is outside candidate region: {line['line_id']}")
    for line in lines:
        region_id = line.get("candidate_region_id")
        if region_id not in candidates_by_id:
            raise ValueError(f"line candidate_region_id is invalid: {line['line_id']}")
        if line["line_id"] not in planned_ids:
            raise ValueError(f"line carrier is required: {line['line_id']}")
        candidate = candidates_by_id[region_id]
        candidate_start = candidate.get("output_global_start_ms")
        candidate_end = candidate.get("output_global_end_ms")
        if candidate_start is None and candidate_end is None:
            continue
        candidate_start = _integer_ms(
            candidate_start,
            f"candidate {region_id}.output_global_start_ms",
        )
        candidate_end = _integer_ms(
            candidate_end,
            f"candidate {region_id}.output_global_end_ms",
        )
        time = line.get("time")
        if not isinstance(time, Mapping) or time.get("time_base") != "output_global_ms":
            raise ValueError(f"line {line['line_id']} must use the output-global candidate clock")

        def require_inside(value: Mapping[str, Any], label: str) -> None:
            start_ms = _integer_ms(value.get("start_ms"), f"{label}.start_ms")
            end_ms = _integer_ms(value.get("end_ms"), f"{label}.end_ms")
            if start_ms < candidate_start or end_ms > candidate_end or end_ms <= start_ms:
                raise ValueError(f"{label} falls outside its provisional candidate")

        require_inside(time, f"line {line['line_id']}")
        for collection in ("proof_events", "foley_events", "silence_windows"):
            for index, event in enumerate(line.get(collection) or [], start=1):
                require_inside(event, f"{collection}[{index}]")
        music = line.get("music_policy")
        if isinstance(music, Mapping):
            for index, window in enumerate(music.get("windows") or [], start=1):
                require_inside(window, f"music_policy.windows[{index}]")


def _validate_factor_coverage(
    candidates: Sequence[Mapping[str, Any]],
    value: Any,
    *,
    required: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("factor_coverage must be an array")
    if required and candidates and not value:
        raise ValueError("factor_coverage must be non-empty for generated candidates")
    candidates_by_id = {
        str(candidate["candidate_region_id"]): set(candidate.get("required_factor_ids") or [])
        for candidate in candidates
    }
    covered_by_region = {region_id: set() for region_id in candidates_by_id}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    allowed_fields = {
        "factor_id",
        "candidate_region_id",
        "source_pointer",
        "contract_pointer",
        "carrier",
        "criticality",
    }
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"factor_coverage[{index}] must be an object")
        unknown = set(raw) - allowed_fields
        if unknown:
            raise ValueError(f"factor_coverage[{index}] has unsupported fields: {sorted(unknown)}")
        factor_id = _non_empty(raw.get("factor_id"), f"factor_coverage[{index}].factor_id")
        if factor_id in seen:
            raise ValueError(f"factor_coverage repeats factor_id {factor_id}")
        seen.add(factor_id)
        region_id = _non_empty(
            raw.get("candidate_region_id"),
            f"factor_coverage[{index}].candidate_region_id",
        )
        if region_id not in candidates_by_id:
            raise ValueError(f"factor_coverage[{index}] references an unknown candidate region")
        if factor_id not in candidates_by_id[region_id]:
            raise ValueError(f"factor_coverage[{index}] factor does not belong to its candidate region")
        _non_empty(raw.get("source_pointer"), f"factor_coverage[{index}].source_pointer")
        _non_empty(raw.get("contract_pointer"), f"factor_coverage[{index}].contract_pointer")
        if raw.get("carrier") not in _FACTOR_CARRIERS:
            raise ValueError(f"factor_coverage[{index}].carrier is invalid")
        if raw.get("criticality") not in _FACTOR_CRITICALITIES:
            raise ValueError(f"factor_coverage[{index}].criticality is invalid")
        covered_by_region[region_id].add(factor_id)
        normalized.append(deepcopy(dict(raw)))
    for region_id, required in candidates_by_id.items():
        observed = covered_by_region[region_id]
        if required and observed != required:
            raise ValueError(
                "factor coverage differs from required factor set for "
                f"{region_id}; missing={sorted(required - observed)}, extra={sorted(observed - required)}"
            )
    return normalized


def _content_without_hash(value: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(value))
    compiler = dict(result.get("compiler") or {})
    compiler.pop("output_sha256", None)
    result["compiler"] = compiler
    return result


def _validate_proposed_split_boundary(
    candidates: Sequence[Mapping[str, Any]],
    value: Any,
) -> int | None:
    if value is None:
        if len(candidates) == 2:
            first_source = candidates[0].get("source_region_id")
            second_source = candidates[1].get("source_region_id")
            if first_source and first_source == second_source:
                raise ValueError(
                    "proposed_split_boundary_ms is required for two candidates from the same source region"
                )
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("proposed_split_boundary_ms must be an integer number of milliseconds")
    if len(candidates) != 2:
        raise ValueError("proposed_split_boundary_ms requires exactly two provisional candidates")
    first, second = candidates
    first_end = first.get("output_global_end_ms")
    second_start = second.get("output_global_start_ms")
    if first_end != value or second_start != value:
        raise ValueError("proposed_split_boundary_ms must match the provisional candidate boundary")
    first_source = first.get("source_region_id")
    second_source = second.get("source_region_id")
    if not first_source or first_source != second_source:
        raise ValueError("proposed split candidates must come from the same source region")
    return value


def build_prescript_artifact(
    *,
    route: str,
    candidate_regions: Sequence[Mapping[str, Any]],
    line_contracts: Sequence[Mapping[str, Any]],
    factor_coverage: Sequence[Mapping[str, Any]],
    skill_file: Any,
    input_digests: Mapping[str, str],
    revision: int = 1,
    hard_blockers: Sequence[str] | None = None,
    warnings: Sequence[str] | None = None,
    require_factor_coverage: bool = False,
    projection_sha256: str | None = None,
    proposed_split_boundary_ms: int | None = None,
) -> dict[str, Any]:
    if route not in {"route_1", "route_2"}:
        raise ValueError("route must be route_1 or route_2")
    name, version, skill_sha = _skill_metadata(skill_file)
    for key, digest in input_digests.items():
        _validate_digest(f"input_digests[{key}]", digest)
    candidates = [deepcopy(dict(item)) for item in candidate_regions]
    if len(candidates) > 2:
        raise ValueError("Invocation A cannot plan more than two generated regions")
    for candidate in candidates:
        _validate_candidate(candidate, require_factor_coverage=require_factor_coverage)
    proposed_split_boundary_ms = _validate_proposed_split_boundary(
        candidates,
        proposed_split_boundary_ms,
    )
    canonical_lines = validate_line_contracts(line_contracts)
    _validate_line_carriers(candidates, canonical_lines)
    canonical_factor_coverage = _validate_factor_coverage(
        candidates,
        factor_coverage,
        required=require_factor_coverage,
    )
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "profile": PROFILE,
        "route": route,
        "revision": int(revision),
        "compiler": {
            "skill": name,
            "version": version,
            "skill_sha256": skill_sha,
            "input_digests": dict(sorted(input_digests.items())),
        },
        "candidate_regions": candidates,
        "line_contracts": [deepcopy(dict(item)) for item in canonical_lines],
        "factor_coverage": canonical_factor_coverage,
        "hard_blockers": list(hard_blockers or []),
        "warnings": list(warnings or []),
        "created_at": datetime.now(UTC).isoformat(),
    }
    if projection_sha256 is not None:
        artifact["projection_sha256"] = _validate_digest(
            "projection_sha256",
            projection_sha256,
        )
    if proposed_split_boundary_ms is not None:
        artifact["proposed_split_boundary_ms"] = proposed_split_boundary_ms
    artifact["compiler"]["output_sha256"] = _sha(_content_without_hash(artifact))
    return artifact


def validate_prescript_artifact(
    artifact: Mapping[str, Any],
    skill_file: Any,
    input_digests: Mapping[str, str],
    *,
    require_factor_coverage: bool = False,
    projection_sha256: str | None = None,
) -> None:
    if not isinstance(artifact, Mapping):
        raise ValueError("prescript artifact must be an object")
    if artifact.get("schema_version") != SCHEMA_VERSION or artifact.get("profile") != PROFILE:
        raise ValueError("unsupported Invocation A profile/schema")
    if artifact.get("route") not in {"route_1", "route_2"}:
        raise ValueError("route must be route_1 or route_2")
    recorded_projection = artifact.get("projection_sha256")
    if recorded_projection is not None:
        recorded_projection = _validate_digest(
            "projection_sha256",
            recorded_projection,
        )
        if projection_sha256 is None:
            raise ValueError("Invocation A/B projection digest is required")
        expected_projection = _validate_digest(
            "projection_sha256",
            projection_sha256,
        )
        if recorded_projection != expected_projection:
            raise ValueError("Invocation A/B projection digest mismatch")
    elif projection_sha256 is not None:
        _validate_digest("projection_sha256", projection_sha256)
        raise ValueError("Invocation A artifact is missing the projection digest")
    compiler = artifact.get("compiler")
    if not isinstance(compiler, Mapping):
        raise ValueError("compiler provenance is required")
    name, version, sha = _skill_metadata(skill_file)
    if compiler.get("skill") != name or compiler.get("version") != version or compiler.get("skill_sha256") != sha:
        raise ValueError("Invocation A/B Seedance-20 skill snapshot mismatch")
    recorded_inputs = dict(compiler.get("input_digests") or {})
    if recorded_inputs != dict(sorted(input_digests.items())):
        raise ValueError("Invocation A input digest mismatch")
    _validate_digest("compiler.output_sha256", compiler.get("output_sha256"))
    if compiler["output_sha256"] != _sha(_content_without_hash(artifact)):
        raise ValueError("Invocation A output digest mismatch")
    candidates = artifact.get("candidate_regions")
    if not isinstance(candidates, list) or len(candidates) > 2:
        raise ValueError("Invocation A must contain at most two candidate regions")
    region_ids = set()
    for candidate in candidates:
        _validate_candidate(candidate, require_factor_coverage=require_factor_coverage)
        region_id = candidate["candidate_region_id"]
        if region_id in region_ids:
            raise ValueError("candidate_region_id values must be unique")
        region_ids.add(region_id)
    _validate_proposed_split_boundary(
        candidates,
        artifact.get("proposed_split_boundary_ms"),
    )
    lines = artifact.get("line_contracts") or []
    canonical_lines = validate_line_contracts(lines)
    _validate_line_carriers(candidates, canonical_lines)
    _validate_factor_coverage(
        candidates,
        artifact.get("factor_coverage"),
        required=require_factor_coverage,
    )
    if artifact.get("route") == "route_1" and artifact.get("route_1_mutations"):
        raise ValueError("Route 1 Invocation A is read-only and cannot mutate approved script")


def rebind_candidate_regions(artifact: dict[str, Any], segments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be mutable JSON object")
    by_cut: dict[str, tuple[str, int, int]] = {}
    for segment in segments:
        segment_id = segment.get("segment_id")
        start = segment.get("start_ms")
        end = segment.get("end_ms")
        if not isinstance(segment_id, str) or not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ValueError("segment plan bounds are invalid")
        for cut_id in segment.get("cut_ids") or []:
            if cut_id in by_cut:
                raise ValueError("a Cut cannot belong to two segments")
            by_cut[str(cut_id)] = (segment_id, start, end)
    for candidate in artifact.get("candidate_regions") or []:
        cut_ids = candidate.get("cut_ids") or []
        matches = {by_cut.get(cut_id, (None, None, None))[0] for cut_id in cut_ids}
        if None in matches or len(matches) != 1:
            raise ValueError(f"candidate region crosses a segment boundary: {candidate.get('candidate_region_id')}")
        segment_id = next(iter(matches))
        segment_start = by_cut[cut_ids[0]][1]
        segment_end = by_cut[cut_ids[-1]][2]
        output_start = candidate.get("output_global_start_ms")
        output_end = candidate.get("output_global_end_ms")
        if (
            output_start is not None
            and output_end is not None
            and (output_start != segment_start or output_end != segment_end)
        ):
            raise ValueError(
                f"candidate global bounds differ from the final segment: {candidate.get('candidate_region_id')}"
            )
        candidate["segment_id"] = segment_id
        candidate["segment_start_ms"] = segment_start
        candidate["segment_end_ms"] = segment_end
    return artifact


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate or build a Seedance-20 Invocation A sidecar")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--skill-file", type=Path, required=True)
    parser.add_argument("--input-digests", type=Path)
    parser.add_argument("--projection-sha256")
    args = parser.parse_args()
    inputs = json.loads(args.input_digests.read_text(encoding="utf-8")) if args.input_digests else {}
    validate_prescript_artifact(
        json.loads(args.artifact.read_text(encoding="utf-8")),
        args.skill_file,
        inputs,
        projection_sha256=args.projection_sha256,
    )
    print("prescript is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
