"""Server-owned Seedance-20 Invocation A/B bridge.

The bridge deliberately performs only deterministic compilation and parity
checks.  It does not create assets or provider tasks.  A provider worker may
inject a prompt compiler, but the exact contract and the packaged
``seedance-20`` bytes are validated here before the existing paid-request
integrity gate is allowed to run.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Sequence

from .bundle_resolver import ImmutableBundleResolver
from .errors import ReplicationError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_PROMPT_TERMS = (
    "reference_videos",
    "reference_audios",
    "ui_demo",
    "opaque_ui_demo",
    "opaque_ui_video",
    "ui_demo_video",
    "generated_ui_demo",
    "generated_ui",
    "ui_render_contract",
    "ui_truth_card",
    "ui_qc_report",
    "ui_media",
    "ui_rendered_media",
    "ui_media_sha256",
    "ui_ocr_evidence",
    "ui_layout_evidence",
    "animation_interval_evidence",
    "tail_video",
    "tail_card",
    "tail_card_video",
    "app_tail_card_video",
    "opaque_app_tail_card",
    "opaque_tail",
    "append_opaque_tail",
    "tail_truth_card",
    "tail_render_contract",
    "tail_qc_report",
    "tail_media",
    "tail_media_sha256",
    "rendered_media",
    "media_sha256",
    "qc_report",
    "transition_render_receipt",
    "transition_render_receipts",
    "excluded_app_end_card",
    "omit_source_end_card",
    "excluded_region",
    "source_interval",
    "source_ui_keep",
    "source_ui_frames",
    "transition_shell",
    "ui_operation_video",
)


def _load_script_module(filename: str, module_name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / filename
    if not path.is_file():
        raise ReplicationError(
            "CONTRACT_INVALID",
            f"packaged {filename} is unavailable",
            category="contract",
            user_action_required=True,
            http_status=422,
        )
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ReplicationError("CONTRACT_INVALID", f"packaged {filename} cannot be loaded", category="contract", http_status=422)
    # ``seedance_prescript.py`` intentionally imports the sibling exact-line
    # validator by its bundled module name.  Load that dependency from the
    # same package instead of relying on the worker's current working
    # directory or ``PYTHONPATH``.
    if filename == "seedance_prescript.py" and "line_contract" not in sys.modules:
        dependency = path.with_name("line_contract.py")
        dep_spec = importlib.util.spec_from_file_location("line_contract", dependency)
        if dep_spec is None or dep_spec.loader is None:
            raise ReplicationError("CONTRACT_INVALID", "packaged line_contract.py cannot be loaded", category="contract", http_status=422)
        dep_module = importlib.util.module_from_spec(dep_spec)
        sys.modules["line_contract"] = dep_module
        try:
            dep_spec.loader.exec_module(dep_module)
        except Exception:
            sys.modules.pop("line_contract", None)
            raise
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ReplicationError("CONTRACT_INVALID", f"packaged {filename} failed to load", category="contract", details={"reason": str(exc)}, http_status=422) from exc
    return module


def _sha_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _route_tokens(value: str) -> list[str]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    separated = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", separated)
    return re.findall(r"[a-z0-9]+", separated.casefold())


def _prompt_route_leakage(value: str) -> list[str]:
    tokens = _route_tokens(value)
    if not tokens:
        return []
    token_set = set(tokens)
    matches: list[str] = []
    for term in _FORBIDDEN_PROMPT_TERMS:
        term_tokens = _route_tokens(term)
        width = len(term_tokens)
        compact = "".join(term_tokens)
        if compact in token_set or any(
            tokens[index : index + width] == term_tokens
            for index in range(len(tokens) - width + 1)
        ):
            matches.append(term)
    return matches


def _integer_ms(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer number of milliseconds")
    return value


def _normalize_segment_plan(
    value: Mapping[str, Any] | None,
    *,
    expected_cut_ids: set[str],
) -> list[dict[str, Any]]:
    """Validate the final Stage-7 segment authority used by Invocation B."""

    if not isinstance(value, Mapping):
        raise ValueError("final segment plan is required")
    raw_segments = value.get("segments")
    if (
        not isinstance(raw_segments, Sequence)
        or isinstance(raw_segments, (str, bytes, bytearray))
        or not 1 <= len(raw_segments) <= 2
    ):
        raise ValueError("final segment plan must contain one or two segments")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_cuts: set[str] = set()
    previous_end: int | None = None
    for index, raw in enumerate(raw_segments, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"segment_plan.segments[{index}] must be an object")
        segment_id = raw.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id.strip() or segment_id in seen_ids:
            raise ValueError("final segment IDs must be unique non-empty strings")
        start_ms = _integer_ms(raw.get("start_ms"), f"segment_plan.segments[{index}].start_ms")
        end_ms = _integer_ms(raw.get("end_ms"), f"segment_plan.segments[{index}].end_ms")
        duration_ms = _integer_ms(raw.get("duration_ms"), f"segment_plan.segments[{index}].duration_ms")
        if start_ms < 0 or end_ms <= start_ms or duration_ms != end_ms - start_ms:
            raise ValueError("final segment bounds or derived duration are invalid")
        if not 4000 <= duration_ms <= 15000:
            raise ValueError("final generated segment duration must be between 4000 and 15000 milliseconds")
        if previous_end is not None and start_ms < previous_end:
            raise ValueError("final segments overlap or are out of order")
        cut_ids = raw.get("cut_ids")
        if (
            not isinstance(cut_ids, Sequence)
            or isinstance(cut_ids, (str, bytes, bytearray))
            or not cut_ids
            or any(not isinstance(cut_id, str) or not cut_id.strip() for cut_id in cut_ids)
            or len(cut_ids) != len(set(cut_ids))
        ):
            raise ValueError("each final segment requires unique non-empty Cut IDs")
        duplicate_cuts = seen_cuts.intersection(cut_ids)
        if duplicate_cuts:
            raise ValueError(f"final segment plan repeats Cut IDs: {sorted(duplicate_cuts)}")
        seen_ids.add(segment_id)
        seen_cuts.update(str(cut_id) for cut_id in cut_ids)
        previous_end = end_ms
        normalized.append(
            {
                "segment_id": segment_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": duration_ms,
                "cut_ids": [str(cut_id) for cut_id in cut_ids],
            }
        )
    if expected_cut_ids and seen_cuts != expected_cut_ids:
        raise ValueError(
            "final segment plan Cut coverage differs from Invocation A; "
            f"missing={sorted(expected_cut_ids - seen_cuts)}, extra={sorted(seen_cuts - expected_cut_ids)}"
        )
    return normalized


def _validate_approved_segment_plan(
    prescript_artifact: Mapping[str, Any],
    normalized_segments: Sequence[Mapping[str, Any]],
) -> str | None:
    if prescript_artifact.get("projection_sha256") is None:
        return None
    expected: list[dict[str, Any]] = []
    for index, candidate in enumerate(
        prescript_artifact.get("candidate_regions") or [],
        start=1,
    ):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"Invocation A candidate {index} must be an object")
        canonical = candidate.get("canonical_segment")
        if not isinstance(canonical, Mapping):
            raise ValueError(
                f"Invocation A candidate {index} is missing its approved canonical segment"
            )
        expected.append(
            {
                "start_ms": canonical.get("start_ms"),
                "end_ms": canonical.get("end_ms"),
                "duration_ms": canonical.get("duration_ms"),
                "cut_ids": [str(item) for item in canonical.get("cut_ids") or []],
            }
        )
    observed = [
        {
            "start_ms": segment.get("start_ms"),
            "end_ms": segment.get("end_ms"),
            "duration_ms": segment.get("duration_ms"),
            "cut_ids": [str(item) for item in segment.get("cut_ids") or []],
        }
        for segment in normalized_segments
    ]
    if observed != expected:
        raise ValueError(
            "final segment plan differs from the approved segment plan frozen by Invocation A"
        )
    return _sha_json(expected)


def _local_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    time = value.get("time") if isinstance(value, Mapping) else None
    if not isinstance(time, Mapping):
        raise ValueError("line time contract is missing")
    events: dict[str, list[dict[str, Any]]] = {}
    for collection in ("proof_events", "foley_events", "silence_windows"):
        events[collection] = [
            {
                "id": item.get("id"),
                "time_base": item.get("time_base"),
                "output_global_start_ms": item.get("output_global_start_ms"),
                "output_global_end_ms": item.get("output_global_end_ms"),
                "segment_start_ms": item.get("segment_start_ms"),
                "segment_end_ms": item.get("segment_end_ms"),
            }
            for item in (value.get(collection) or [])
        ]
    return {
        "segment_id": value.get("segment_id"),
        "time_base": time.get("time_base"),
        "output_global_start_ms": time.get("output_global_start_ms"),
        "output_global_end_ms": time.get("output_global_end_ms"),
        "segment_start_ms": time.get("segment_start_ms"),
        "segment_end_ms": time.get("segment_end_ms"),
        "events": events,
    }


def _require_exact_rebound_lines(
    provided: Sequence[Mapping[str, Any]],
    expected: Sequence[Mapping[str, Any]],
    *,
    line_module: Any,
) -> list[dict[str, Any]]:
    expected_by_id = {str(line["line_id"]): dict(line) for line in expected}
    approved_global = []
    for line in expected:
        value = deepcopy(dict(line))
        value["time"]["time_base"] = "output_global_ms"
        approved_global.append(value)
    canonical = line_module.validate_line_contracts(provided, approved_lines=approved_global)
    if {line["line_id"] for line in canonical} != set(expected_by_id):
        raise ValueError("final segment line set differs from the deterministic rebound line set")
    for line in canonical:
        expected_line = expected_by_id[line["line_id"]]
        if _local_binding(line) != _local_binding(expected_line):
            raise ValueError(
                f"line was not rebound to the final segment-local plan: {line['line_id']}"
            )
    return canonical


def _prompt_profile_binding_sha(
    profile: Mapping[str, Any] | None,
) -> str:
    """Return a stable profile evidence digest even for local active fixtures."""

    if isinstance(profile, Mapping):
        declared = str(profile.get("snapshot_sha256") or "").lower()
        if _SHA256.fullmatch(declared):
            return declared
        return _sha_json(dict(profile))
    return _sha_json({"profile": "high_fidelity_hybrid_v1"})


def _build_prompt_approval_binding(
    *,
    prompt_module: Any,
    skill_files: Mapping[str, Any],
    prescript_artifact: Mapping[str, Any],
    input_digests: Mapping[str, str],
    segment: Mapping[str, Any],
    line_contracts: Sequence[Mapping[str, Any]],
    factors: Mapping[str, Any] | None,
    compiler_checks: Mapping[str, Any],
    segment_plan_sha256: str,
    profile_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Bind B's prompt bytes to the server-owned approved evidence set."""

    plan = prompt_module.build_skill_plan(factors or {}, skill_files=skill_files)
    normalized_inputs = dict(sorted((str(k), str(v).lower()) for k, v in input_digests.items()))
    compiler = prescript_artifact.get("compiler") or {}
    binding = {
        "schema_version": prompt_module.APPROVAL_BINDING_SCHEMA,
        "profile": "high_fidelity_hybrid_v1",
        "route": str(prescript_artifact.get("route") or ""),
        "input_digests": normalized_inputs,
        "input_digests_sha256": _sha_json(normalized_inputs),
        "prescript_sha256": str(compiler.get("output_sha256") or ""),
        "segment_plan_sha256": str(segment_plan_sha256),
        "profile_snapshot_sha256": _prompt_profile_binding_sha(profile_snapshot),
        "segment_id": segment.get("segment_id"),
        "cut_ids": list(segment.get("cut_ids") or []),
        "duration_ms": segment.get("duration_ms"),
        "segment_contract_sha256": _sha_json(segment),
        "locks_sha256": _sha_json(segment.get("locks") or []),
        "reference_roles_sha256": _sha_json(segment.get("reference_roles") or []),
        "shots_sha256": _sha_json(segment.get("shots") or []),
        "line_contract_sha256": _sha_json(list(line_contracts)),
        "factors_sha256": _sha_json(dict(factors or {})),
        "compiler_checks_sha256": _sha_json(
            {name: compiler_checks.get(name) for name in prompt_module.COMPILER_CHECKS}
        ),
        "compiler_skill_sha256": str(
            (plan.get("dependency_snapshot") or {}).get("seedance-20", {}).get("sha256") or ""
        ),
        "compiler_route_sha256": str(plan.get("route_sha256") or ""),
        "character_lock_sha256": normalized_inputs.get(
            "character_lock_sha256",
            _sha_json(segment.get("character_locks", segment.get("character_lock", []))),
        ),
        "product_truth_sha256": normalized_inputs.get(
            "product_truth_sha256",
            _sha_json(segment.get("product_locks", segment.get("product_lock", []))),
        ),
        "voiceover_contract_sha256": _sha_json(list(line_contracts)),
        "cut_order_sha256": _sha_json(list(segment.get("cut_ids") or [])),
        "duration_sha256": _sha_json(segment.get("duration_ms")),
    }
    return binding


def _prepare_prompt_request(
    value: Mapping[str, Any],
    *,
    active_profile: bool,
    current_segment: Mapping[str, Any] | None,
    current_rebound_lines: Sequence[Mapping[str, Any]],
    approved_lines: Sequence[Mapping[str, Any]],
    line_module: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(value, Mapping):
        raise ValueError("Invocation B prompt request must be an object")
    allowed = {"segment", "line_contracts", "performance_lines", "factors", "compiler_checks"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"Invocation B prompt request contains unknown fields: {unknown}")
    request = deepcopy(dict(value))
    segment = request.get("segment")
    if active_profile:
        if not isinstance(segment, Mapping) or current_segment is None:
            raise ValueError("active Invocation B requires a structured segment")
        segment = deepcopy(dict(segment))
        if segment.get("segment_id") != current_segment["segment_id"]:
            raise ValueError("prompt segment_id differs from the final segment plan")
        if segment.get("duration_ms") != current_segment["duration_ms"]:
            raise ValueError("prompt duration differs from the final segment plan")
        supplied_cut_ids = segment.get("cut_ids")
        if supplied_cut_ids is not None and list(supplied_cut_ids) != current_segment["cut_ids"]:
            raise ValueError("prompt Cut order differs from the final segment plan")
        supplied_origin = segment.get("output_global_start_ms")
        if supplied_origin is not None and supplied_origin != current_segment["start_ms"]:
            raise ValueError("prompt global origin differs from the final segment plan")
        segment["cut_ids"] = list(current_segment["cut_ids"])
        segment["output_global_start_ms"] = current_segment["start_ms"]
        segment["output_global_end_ms"] = current_segment["end_ms"]
        request["segment"] = segment
        requested_lines = request.get("line_contracts")
        if requested_lines is None:
            canonical_lines = deepcopy(list(current_rebound_lines))
        else:
            canonical_lines = _require_exact_rebound_lines(
                requested_lines,
                current_rebound_lines,
                line_module=line_module,
            )
    else:
        requested_lines = request.get("line_contracts")
        if requested_lines is None:
            requested_lines = approved_lines
        canonical_lines = line_module.validate_line_contracts(
            requested_lines,
            approved_lines=approved_lines,
        )
        if {line["line_id"] for line in canonical_lines} != {
            line["line_id"] for line in line_module.validate_line_contracts(approved_lines)
        }:
            raise ValueError("final line set differs from the approved Invocation A line set")
    request["line_contracts"] = deepcopy(canonical_lines)
    return request, canonical_lines


def _validate_projection_segment_parity(
    prescript_artifact: Mapping[str, Any],
    current_segment: Mapping[str, Any] | None,
    prompt_segment: Mapping[str, Any] | None,
) -> None:
    """Keep the rich dynamics projection immutable from A through B.

    Legacy prescripts have no projection digest and remain compatible.  Once
    the canonical envelope digest is present, B may bind the provisional
    segment ID/global origin but may not rewrite any shot-level source fact or
    factor allocation approved by Invocation A.
    """

    if prescript_artifact.get("projection_sha256") is None:
        return
    if not isinstance(current_segment, Mapping) or not isinstance(prompt_segment, Mapping):
        raise ValueError("projection-bound Invocation B requires a structured current segment")
    current_cut_ids = [str(item) for item in current_segment.get("cut_ids") or []]
    matches = [
        candidate
        for candidate in prescript_artifact.get("candidate_regions") or []
        if isinstance(candidate, Mapping)
        and [str(item) for item in candidate.get("cut_ids") or []] == current_cut_ids
    ]
    if len(matches) != 1:
        raise ValueError("Invocation B segment cannot be bound to exactly one canonical Invocation A region")
    candidate = matches[0]
    canonical = candidate.get("canonical_segment")
    if not isinstance(canonical, Mapping):
        raise ValueError("projection-bound Invocation A candidate is missing canonical_segment")
    canonical_start = canonical.get("start_ms")
    canonical_end = canonical.get("end_ms")
    canonical_duration = canonical.get("duration_ms")
    if canonical_start is not None or canonical_end is not None:
        if (
            current_segment.get("start_ms") != canonical_start
            or current_segment.get("end_ms") != canonical_end
            or current_segment.get("duration_ms") != canonical_duration
        ):
            raise ValueError("Invocation A/B projection global bounds differ")
    expected_shots = canonical.get("shots")
    observed_shots = prompt_segment.get("shots")
    if not isinstance(expected_shots, list) or not isinstance(observed_shots, list):
        raise ValueError("Invocation A/B projection shots are required")
    if len(expected_shots) != len(observed_shots):
        raise ValueError("Invocation A/B projection shot count differs")
    parity_fields = (
        "shot_id",
        "cut_id",
        "start_ms",
        "end_ms",
        "duration_ms",
        "output_global_start_ms",
        "output_global_end_ms",
        "scene",
        "camera",
        "lighting",
        "performance",
        "action",
        "endpoint",
        "product_or_ui_truth",
        "commercial_proof",
        "transition",
        "continuity",
        "audio",
        "factor_ids",
    )
    for index, (expected, observed) in enumerate(zip(expected_shots, observed_shots), start=1):
        if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
            raise ValueError(f"Invocation A/B projection shot {index} must be an object")
        changed = [field for field in parity_fields if observed.get(field) != expected.get(field)]
        if changed:
            raise ValueError(
                f"Invocation A/B projection shot {index} differs: {', '.join(changed)}"
            )
    expected_factors = [str(item) for item in candidate.get("required_factor_ids") or []]
    observed_factors = [
        str(factor_id)
        for shot in observed_shots
        if isinstance(shot, Mapping)
        for factor_id in shot.get("factor_ids") or []
    ]
    if sorted(observed_factors) != sorted(expected_factors):
        raise ValueError("Invocation A/B projection factor set differs")


class SeedanceInvocationAdapter:
    """Run the non-provider A/B Seedance compiler boundary in a worker."""

    def __init__(
        self,
        *,
        skill_file: Path | Any | None = None,
        bundle_resolver: Any | None = None,
        production: bool = False,
        profile_snapshot: Mapping[str, Any] | None = None,
        profile_dependency_paths: Any | None = None,
        prompt_compiler: Callable[..., str] | None = None,
        prompt_skill_files: Mapping[str, Any] | None = None,
        skill_files: Mapping[str, Any] | None = None,
        activation_evidence_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self.profile_snapshot = deepcopy(dict(profile_snapshot)) if isinstance(profile_snapshot, Mapping) else None
        self.profile_dependency_paths = profile_dependency_paths
        self.prompt_compiler = prompt_compiler
        self.activation_evidence_verifier = activation_evidence_verifier
        self.production = bool(
            production
            or (
                self.profile_snapshot
                and self.profile_snapshot.get("profile") == "high_fidelity_hybrid_v1"
                and str(self.profile_snapshot.get("activation_mode") or "").casefold()
                in {"active", "production", "default"}
            )
        )
        self.bundle_resolver = bundle_resolver
        if self.production:
            if not isinstance(bundle_resolver, ImmutableBundleResolver):
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "production Seedance Invocation A/B requires an immutable bundle resolver",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            if skill_file is not None:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "production Seedance Invocation A/B rejects client/local Skill paths",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            if profile_dependency_paths is not None and profile_dependency_paths is not bundle_resolver and not isinstance(profile_dependency_paths, ImmutableBundleResolver):
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "production profile dependencies must come from the immutable bundle resolver",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            try:
                self.skill_file = bundle_resolver.get("seedance-20")
            except Exception as exc:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "immutable bundle is missing the seedance-20 dependency",
                    category="contract",
                    details={"reason": str(exc)},
                    http_status=422,
                ) from exc
        elif bundle_resolver is not None:
            if not bool(getattr(bundle_resolver, "immutable", False)) and not hasattr(bundle_resolver, "skill_files"):
                raise ReplicationError("CONTRACT_INVALID", "bundle resolver is invalid", category="contract", http_status=422)
            self.skill_file = bundle_resolver.get("seedance-20") if hasattr(bundle_resolver, "get") else bundle_resolver.skill_files(["seedance-20"])["seedance-20"]
        else:
            if skill_file is None:
                raise ReplicationError("CONTRACT_INVALID", "packaged seedance-20 skill file is missing", category="contract", http_status=422)
            self.skill_file = Path(skill_file).resolve()
            if not self.skill_file.is_file():
                raise ReplicationError("CONTRACT_INVALID", "packaged seedance-20 skill file is missing", category="contract", http_status=422)
        if prompt_skill_files is not None and skill_files is not None and dict(prompt_skill_files) != dict(skill_files):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "prompt_skill_files and skill_files cannot disagree",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        effective_skill_files = prompt_skill_files if prompt_skill_files is not None else skill_files
        if effective_skill_files is None and bundle_resolver is not None:
            effective_skill_files = bundle_resolver.skill_files()
        if self.production and effective_skill_files:
            if any(isinstance(path, Path) or not hasattr(path, "read_bytes") for path in effective_skill_files.values()):
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "production prompt Skill dependencies must be immutable bundle entries",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
        self.prompt_skill_files = {
            str(name): (path if hasattr(path, "read_bytes") and not isinstance(path, Path) else Path(path).resolve())
            for name, path in (effective_skill_files or {}).items()
        }
        if self.prompt_skill_files:
            root = self.prompt_skill_files.get("seedance-20")
            if root is None or not hasattr(root, "read_bytes") or root.read_bytes() != self.skill_file.read_bytes():
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "prompt Skill dependency map must contain the pinned seedance-20 bytes",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
        if self.profile_snapshot and self.profile_snapshot.get("profile") == "high_fidelity_hybrid_v1":
            profile_module = _load_script_module("high_fidelity_profile.py", "replication_high_fidelity_profile")
            dependencies = profile_dependency_paths or bundle_resolver or {"seedance-20": self.skill_file}
            try:
                profile_module.validate_profile_snapshot(
                    self.profile_snapshot,
                    dependencies,
                    activation_evidence_verifier=self.activation_evidence_verifier,
                )
            except Exception as exc:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "high-fidelity profile snapshot does not match packaged dependencies",
                    category="contract",
                    user_action_required=True,
                    details={"reason": str(exc)},
                    http_status=422,
                ) from exc

    def _profile_guard(self, context: Any | None) -> None:
        if context is None:
            return
        context_profile = getattr(context, "profile_snapshot", None)
        if not context_profile:
            return
        if not self.profile_snapshot and (
            context_profile.get("snapshot_sha256") or context_profile.get("dependencies")
        ):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "active high-fidelity context requires a pinned Invocation A/B profile snapshot",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        if not self.profile_snapshot:
            return
        expected = context_profile.get("snapshot_sha256")
        actual = self.profile_snapshot.get("snapshot_sha256")
        if expected and actual and expected != actual:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "worker context profile snapshot differs from Invocation A/B snapshot",
                category="contract",
                user_action_required=True,
                http_status=422,
            )

    @staticmethod
    def _raise(code: str, message: str, **details: Any) -> None:
        raise ReplicationError(
            code,
            message,
            category="contract",
            user_action_required=True,
            details=details or None,
            http_status=422,
        )

    def invoke_a(
        self,
        *,
        route: str,
        candidate_regions: Sequence[Mapping[str, Any]],
        line_contracts: Sequence[Mapping[str, Any]],
        factor_coverage: Sequence[Mapping[str, Any]],
        input_digests: Mapping[str, str],
        context: Any | None = None,
        revision: int = 1,
        hard_blockers: Sequence[str] | None = None,
        warnings: Sequence[str] | None = None,
        projection_sha256: str | None = None,
        canonical_segments: Sequence[Mapping[str, Any]] | None = None,
        proposed_split_boundary_ms: int | None = None,
    ) -> dict[str, Any]:
        self._profile_guard(context)
        if not candidate_regions:
            return {
                "status": "skipped",
                "reason": "no_generated_regions",
                "profile": "seedance20_prescript_v1",
                "route": route,
                **({"projection_sha256": projection_sha256} if projection_sha256 else {}),
            }
        module = _load_script_module("seedance_prescript.py", "replication_seedance_prescript")
        context_profile = getattr(context, "profile_snapshot", None) if context is not None else None
        strict_factor_coverage = bool(
            self.production
            or (
                isinstance(context_profile, Mapping)
                and context_profile.get("profile") == "high_fidelity_hybrid_v1"
            )
            or (
                isinstance(self.profile_snapshot, Mapping)
                and self.profile_snapshot.get("profile") == "high_fidelity_hybrid_v1"
            )
        )
        try:
            artifact = module.build_prescript_artifact(
                route=route,
                candidate_regions=candidate_regions,
                line_contracts=line_contracts,
                factor_coverage=factor_coverage,
                skill_file=self.skill_file,
                input_digests=input_digests,
                revision=revision,
                hard_blockers=hard_blockers,
                warnings=warnings,
                require_factor_coverage=strict_factor_coverage,
                projection_sha256=projection_sha256,
                proposed_split_boundary_ms=proposed_split_boundary_ms,
            )
            module.validate_prescript_artifact(
                artifact,
                self.skill_file,
                input_digests,
                require_factor_coverage=strict_factor_coverage,
                projection_sha256=projection_sha256,
            )
            if canonical_segments is not None:
                if not isinstance(canonical_segments, Sequence) or isinstance(canonical_segments, (str, bytes, bytearray)):
                    raise ValueError("canonical_segments must be an array")
                observed = [dict(item) for item in canonical_segments if isinstance(item, Mapping)]
                expected = [
                    dict(region.get("canonical_segment"))
                    for region in candidate_regions
                    if isinstance(region.get("canonical_segment"), Mapping)
                ]
                if observed != expected:
                    raise ValueError("canonical segment projection differs from Invocation A candidates")
        except Exception as exc:
            self._raise("CONTRACT_INVALID", "Invocation A produced an invalid prescript artifact", reason=str(exc))
        return artifact

    def invoke_b(
        self,
        *,
        prescript_artifact: Mapping[str, Any],
        input_digests: Mapping[str, str],
        compiled_prompt: str | None = None,
        final_cut_ids: Sequence[str] | None = None,
        segment_plan: Mapping[str, Any] | None = None,
        segment_id: str | None = None,
        context: Any | None = None,
        prompt_compiler: Callable[..., str] | None = None,
        prompt_request: Mapping[str, Any] | None = None,
        compiled_prompt_artifact: Mapping[str, Any] | None = None,
        approved_prompt_request: Mapping[str, Any] | None = None,
        projection_sha256: str | None = None,
        performance_line_contract_sha256: str | None = None,
        source_content_timeline_sha256: str | None = None,
    ) -> dict[str, Any]:
        self._profile_guard(context)
        if (performance_line_contract_sha256 is None) != (source_content_timeline_sha256 is None):
            self._raise(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B source-audio binding requires both performance and timeline digests",
            )
        if performance_line_contract_sha256 is not None:
            performance_line_contract_sha256 = str(performance_line_contract_sha256).lower()
            source_content_timeline_sha256 = str(source_content_timeline_sha256).lower()
            if _SHA256.fullmatch(performance_line_contract_sha256) is None:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B performance line contract digest must be a lowercase SHA-256",
                )
            if _SHA256.fullmatch(source_content_timeline_sha256) is None:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B source-content timeline digest must be a lowercase SHA-256",
                )
        module = _load_script_module("seedance_prescript.py", "replication_seedance_prescript_b")
        context_profile = getattr(context, "profile_snapshot", None) if context is not None else None
        strict_factor_coverage = bool(
            self.production
            or (
                isinstance(context_profile, Mapping)
                and context_profile.get("profile") == "high_fidelity_hybrid_v1"
            )
            or (
                isinstance(self.profile_snapshot, Mapping)
                and self.profile_snapshot.get("profile") == "high_fidelity_hybrid_v1"
            )
        )
        try:
            module.validate_prescript_artifact(
                prescript_artifact,
                self.skill_file,
                input_digests,
                require_factor_coverage=strict_factor_coverage,
                projection_sha256=projection_sha256,
            )
        except Exception as exc:
            self._raise("PROMPT_INTEGRITY_FAILED", "Invocation A snapshot cannot be consumed by Invocation B", reason=str(exc))
        expected_cuts = {
            str(cut_id)
            for region in (prescript_artifact.get("candidate_regions") or [])
            for cut_id in (region.get("cut_ids") or [])
        }
        observed_cuts = {str(cut_id) for cut_id in (final_cut_ids or [])}
        if expected_cuts and not expected_cuts.issubset(observed_cuts):
            self._raise(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B final prompt is missing an Invocation A Cut",
                expected_cut_ids=sorted(expected_cuts),
                observed_cut_ids=sorted(observed_cuts),
            )
        active_profile = bool(
            (
                isinstance(context_profile, Mapping)
                and context_profile.get("profile") == "high_fidelity_hybrid_v1"
            )
            or (
                isinstance(self.profile_snapshot, Mapping)
                and self.profile_snapshot.get("profile") == "high_fidelity_hybrid_v1"
            )
        )
        normalized_segments: list[dict[str, Any]] = []
        current_segment: dict[str, Any] | None = None
        current_rebound_lines: list[dict[str, Any]] = []
        segment_plan_sha256: str | None = None
        approved_segment_signature_sha256: str | None = None
        line_module = None
        if active_profile:
            try:
                normalized_segments = _normalize_segment_plan(
                    segment_plan,
                    expected_cut_ids=expected_cuts,
                )
                approved_segment_signature_sha256 = _validate_approved_segment_plan(
                    prescript_artifact,
                    normalized_segments,
                )
                requested_segment = prompt_request.get("segment") if isinstance(prompt_request, Mapping) else None
                request_segment_id = (
                    requested_segment.get("segment_id")
                    if isinstance(requested_segment, Mapping)
                    else None
                )
                if segment_id is not None and request_segment_id is not None and segment_id != request_segment_id:
                    raise ValueError("Invocation B segment_id differs from prompt_request.segment.segment_id")
                selected_segment_id = segment_id or request_segment_id
                if selected_segment_id is None and len(normalized_segments) == 1:
                    selected_segment_id = normalized_segments[0]["segment_id"]
                matches = [item for item in normalized_segments if item["segment_id"] == selected_segment_id]
                if len(matches) != 1:
                    raise ValueError("Invocation B requires exactly one final segment_id")
                current_segment = matches[0]
                line_module = _load_script_module("line_contract.py", "replication_line_contract_stage7")
                rebound = line_module.rebind_line_contracts(
                    prescript_artifact.get("line_contracts") or [],
                    normalized_segments,
                )
                current_rebound_lines = [
                    line for line in rebound if line.get("segment_id") == current_segment["segment_id"]
                ]
                segment_plan_sha256 = _sha_json({"segments": normalized_segments})
            except Exception as exc:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B requires a valid final segment plan and deterministic segment-local rebind",
                    reason=str(exc),
                )
        compiler_artifact: Mapping[str, Any] | None = None
        if approved_prompt_request is not None and compiled_prompt_artifact is None:
            self._raise(
                "PROMPT_INTEGRITY_FAILED",
                "approved_prompt_request is only valid when verifying a packaged prompt artifact",
            )
        if compiled_prompt_artifact is not None:
            if prompt_request is not None or compiled_prompt is not None:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B accepts exactly one packaged prompt compilation input",
                )
            if active_profile and approved_prompt_request is None:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "active Invocation B packaged prompt artifacts require the server-approved prompt request",
                )
            if not self.prompt_skill_files:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "compiled prompt artifact requires packaged Seedance Skill dependencies",
                )
            prompt_module = _load_script_module(
                "seedance_prompt_compiler.py",
                "replication_seedance_prompt_compiler_artifact",
            )
            approved_lines = prescript_artifact.get("line_contracts") or []
            artifact_lines = compiled_prompt_artifact.get("line_contracts")
            validation_lines = artifact_lines if isinstance(artifact_lines, list) else approved_lines
            try:
                if line_module is None:
                    line_module = _load_script_module(
                        "line_contract.py",
                        "replication_line_contract_artifact",
                    )
                expected_source_contract = None
                expected_approval_binding = None
                expected_compiler_artifact = None
                if active_profile:
                    if not isinstance(artifact_lines, list):
                        raise ValueError("active compiled prompt artifact requires rebound line_contracts")
                    validation_lines = _require_exact_rebound_lines(
                        artifact_lines,
                        current_rebound_lines,
                        line_module=line_module,
                    )
                    assert current_segment is not None
                    marker = (
                        f"Segment {current_segment['segment_id']}. "
                        f"Duration {current_segment['duration_ms'] / 1000:.2f}s."
                    )
                    if marker not in str(compiled_prompt_artifact.get("prompt") or ""):
                        raise ValueError("compiled prompt artifact does not match the final segment plan")
                    approved_request, approved_request_lines = _prepare_prompt_request(
                        approved_prompt_request,
                        active_profile=True,
                        current_segment=current_segment,
                        current_rebound_lines=current_rebound_lines,
                        approved_lines=approved_lines,
                        line_module=line_module,
                    )
                    _validate_projection_segment_parity(
                        prescript_artifact,
                        current_segment,
                        approved_request.get("segment"),
                    )
                    expected_source_contract = {
                        "segment": approved_request.get("segment"),
                        "factors": approved_request.get("factors") or {},
                        "compiler_checks": approved_request.get("compiler_checks"),
                        "performance_lines": approved_request.get("performance_lines") or [],
                    }
                    expected_approval_binding = _build_prompt_approval_binding(
                        prompt_module=prompt_module,
                        skill_files=self.prompt_skill_files,
                        prescript_artifact=prescript_artifact,
                        input_digests=input_digests,
                        segment=approved_request["segment"],
                        line_contracts=approved_request_lines,
                        factors=approved_request.get("factors") or {},
                        compiler_checks=approved_request.get("compiler_checks") or {},
                        segment_plan_sha256=str(segment_plan_sha256),
                        profile_snapshot=context_profile or self.profile_snapshot,
                    )
                    expected_compiler_artifact = prompt_module.compile_prompt(
                        segment=approved_request["segment"],
                        line_contracts=approved_request_lines,
                        factors=approved_request.get("factors") or {},
                        skill_files=self.prompt_skill_files,
                        compiler_checks=approved_request.get("compiler_checks") or {},
                        performance_lines=approved_request.get("performance_lines") or [],
                        approval_binding=expected_approval_binding,
                    )
                elif isinstance(artifact_lines, list):
                    line_module.validate_line_contracts(
                        artifact_lines,
                        approved_lines=approved_lines,
                    )
                prompt_module.validate_compiled_prompt(
                    compiled_prompt_artifact,
                    skill_files=self.prompt_skill_files,
                    line_contracts=validation_lines,
                    expected_source_contract=expected_source_contract,
                    expected_approval_binding=expected_approval_binding,
                    expected_performance_lines=approved_request.get("performance_lines") or [],
                )
                if expected_compiler_artifact is not None and dict(compiled_prompt_artifact) != expected_compiler_artifact:
                    raise ValueError("packaged prompt artifact differs from the server-approved deterministic compilation")
            except Exception as exc:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B packaged compiler artifact is invalid",
                    reason=str(exc),
                )
            compiler_artifact = deepcopy(dict(compiled_prompt_artifact))
            compiled_prompt = compiler_artifact.get("prompt")

        if prompt_request is not None:
            if compiled_prompt is not None:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B cannot accept both a raw prompt and a structured prompt request",
                )
            if not self.prompt_skill_files:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B structured compilation requires packaged Seedance Skill dependencies",
                )
            approved_lines = prescript_artifact.get("line_contracts") or []
            if line_module is None:
                line_module = _load_script_module("line_contract.py", "replication_line_contract_b")
            try:
                request, canonical_lines = _prepare_prompt_request(
                    prompt_request,
                    active_profile=active_profile,
                    current_segment=current_segment,
                    current_rebound_lines=current_rebound_lines,
                    approved_lines=approved_lines,
                    line_module=line_module,
                )
                _validate_projection_segment_parity(
                    prescript_artifact,
                    current_segment,
                    request.get("segment"),
                )
                prompt_module = _load_script_module(
                    "seedance_prompt_compiler.py",
                    "replication_seedance_prompt_compiler",
                )
                approval_binding = None
                if active_profile:
                    assert current_segment is not None and segment_plan_sha256 is not None
                    approval_binding = _build_prompt_approval_binding(
                        prompt_module=prompt_module,
                        skill_files=self.prompt_skill_files,
                        prescript_artifact=prescript_artifact,
                        input_digests=input_digests,
                        segment=request["segment"],
                        line_contracts=canonical_lines,
                        factors=request.get("factors") or {},
                        compiler_checks=request.get("compiler_checks") or {},
                        segment_plan_sha256=segment_plan_sha256,
                        profile_snapshot=context_profile or self.profile_snapshot,
                    )
                compiler_artifact = prompt_module.compile_prompt(
                    segment=request.get("segment"),
                    line_contracts=canonical_lines,
                    factors=request.get("factors") or {},
                    skill_files=self.prompt_skill_files,
                    compiler_checks=request.get("compiler_checks"),
                    performance_lines=request.get("performance_lines") or [],
                    approval_binding=approval_binding,
                )
                prompt_module.validate_compiled_prompt(
                    compiler_artifact,
                    skill_files=self.prompt_skill_files,
                    line_contracts=canonical_lines,
                    expected_source_contract=(
                        {
                            "segment": request.get("segment"),
                            "factors": request.get("factors") or {},
                            "compiler_checks": request.get("compiler_checks"),
                            "performance_lines": request.get("performance_lines") or [],
                        }
                        if active_profile
                        else None
                    ),
                    expected_approval_binding=approval_binding,
                    expected_performance_lines=request.get("performance_lines") or [],
                )
            except Exception as exc:
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B packaged Seedance-20 prompt compilation failed",
                    reason=str(exc),
                )
            if (compiler_artifact.get("compiler") or {}).get("skill_sha256") != (
                prescript_artifact.get("compiler") or {}
            ).get("skill_sha256"):
                self._raise(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation A/B Seedance-20 compiler snapshot differs",
                )
            compiled_prompt = compiler_artifact.get("prompt")

        if active_profile and self.prompt_skill_files and compiler_artifact is None:
            self._raise(
                "PROMPT_INTEGRITY_FAILED",
                "active high-fidelity Invocation B must use the packaged Seedance-20 prompt compiler",
            )

        compiler = prompt_compiler or self.prompt_compiler
        if compiled_prompt is None and compiler is not None:
            try:
                compiled_prompt = compiler(prescript_artifact=prescript_artifact, context=context)
            except TypeError:
                compiled_prompt = compiler(prescript_artifact)
        if not isinstance(compiled_prompt, str) or not compiled_prompt.strip():
            self._raise("PROMPT_INTEGRITY_FAILED", "Invocation B requires a non-empty compiled prompt")
        if len(compiled_prompt) > 5000:
            self._raise("PROMPT_INTEGRITY_FAILED", "compiled Seedance prompt exceeds 5000 characters")
        leaked = _prompt_route_leakage(compiled_prompt)
        if leaked:
            self._raise("PROMPT_INTEGRITY_FAILED", "compiled prompt leaks route-excluded media fields", leaked_fields=leaked)
        final_prompt_lines = current_rebound_lines if active_profile else (prescript_artifact.get("line_contracts") or [])
        for line in final_prompt_lines:
            text = line.get("text")
            if isinstance(text, Mapping):
                text = text.get("exact")
            if text and str(text) not in compiled_prompt:
                self._raise("PROMPT_INTEGRITY_FAILED", "compiled prompt does not contain an approved exact line", line_id=line.get("line_id"))
        result = {
            "status": "ready",
            "compiled_prompt": compiled_prompt,
            "compiled_prompt_sha256": hashlib.sha256(compiled_prompt.encode("utf-8")).hexdigest(),
            "prescript_sha256": str((prescript_artifact.get("compiler") or {}).get("output_sha256")),
            "skill_sha256": str((prescript_artifact.get("compiler") or {}).get("skill_sha256")),
            "input_digests": dict(sorted(input_digests.items())),
            "cut_ids": sorted(expected_cuts),
            "profile_snapshot_sha256": (self.profile_snapshot or {}).get("snapshot_sha256"),
        }
        if prescript_artifact.get("projection_sha256") is not None:
            result["projection_sha256"] = str(prescript_artifact["projection_sha256"])
        if performance_line_contract_sha256 is not None:
            result["performance_line_contract_sha256"] = performance_line_contract_sha256
            result["source_content_timeline_sha256"] = source_content_timeline_sha256
        if active_profile:
            assert current_segment is not None and segment_plan_sha256 is not None
            result["segment_id"] = current_segment["segment_id"]
            result["segment_plan_sha256"] = segment_plan_sha256
            result["segment_cut_ids"] = list(current_segment["cut_ids"])
            if approved_segment_signature_sha256 is not None:
                result["approved_segment_signature_sha256"] = (
                    approved_segment_signature_sha256
                )
        if compiler_artifact is not None:
            result["compiler"] = deepcopy(dict(compiler_artifact.get("compiler") or {}))
            result["prompt_artifact_sha256"] = str(
                (compiler_artifact.get("compiler") or {}).get("output_sha256")
            )
            result["compiler_artifact_sha256"] = result["prompt_artifact_sha256"]
        return result


__all__ = ["SeedanceInvocationAdapter"]
