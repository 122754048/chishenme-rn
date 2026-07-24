"""Deterministic Invocation-B prompt compiler.

The worker still uses the packaged ``seedance-20`` skill as the authoritative
prompt/compiler rule set.  This module supplies the server-safe boundary around
that skill: it selects only declared specialists, renders the frozen segment
and exact line contracts, records byte-level provenance, and rejects route
leakage or mutation before a paid request can be authorized.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


MAX_PROMPT_CHARS = 5000
RULE_ENGINE_VERSION = "seedance20-rules/v2"
ROUTE_LEAKAGE_TERMS = (
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
ROUTE_LEAKAGE_EXACT_KEYS = {
    "ui_truth",
    "tail_truth",
    "ui_render",
    "tail_render",
    "ui_qc",
    "tail_qc",
}
_PERFORMANCE_MODES = {"spoken", "sung", "singing", "instrumental", "inaudible"}
COMPILER_CHECKS = (
    "professional_gate",
    "capability_check",
    "allocation_check",
    "reference_role_check",
    "directing_coherence_check",
    "anti_slop_check",
    "route_exclusion_check",
    "line_parity_check",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
APPROVAL_BINDING_SCHEMA = "seedance20-prompt-approval-binding/v1"
_APPROVAL_BINDING_SHA_FIELDS = (
    "input_digests_sha256",
    "prescript_sha256",
    "segment_plan_sha256",
    "profile_snapshot_sha256",
    "segment_contract_sha256",
    "locks_sha256",
    "reference_roles_sha256",
    "shots_sha256",
    "line_contract_sha256",
    "factors_sha256",
    "compiler_checks_sha256",
    "compiler_skill_sha256",
    "compiler_route_sha256",
    "character_lock_sha256",
    "product_truth_sha256",
    "voiceover_contract_sha256",
    "cut_order_sha256",
    "duration_sha256",
)
REVIEW_OUTPUT_LANGUAGES = {"en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"}
REQUIRED_REVIEW_BINDINGS = {
    "output_language",
    "approved_script_sha256",
    "approved_storyboard_manifest_sha256",
    "approved_storyboard_cut_sha256s",
    "segment_plan_sha256",
}


def _validate_review_bindings(value: Mapping[str, Any], *, cut_ids: Sequence[str], lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("review bindings must be an object")
    missing = REQUIRED_REVIEW_BINDINGS - set(value)
    if missing:
        raise ValueError(f"review binding missing: {', '.join(sorted(missing))}")
    result = deepcopy(dict(value))
    language = result.get("output_language")
    if language is not None and language not in REVIEW_OUTPUT_LANGUAGES:
        raise ValueError("review binding output_language is invalid")
    for field in ("approved_script_sha256", "approved_storyboard_manifest_sha256", "segment_plan_sha256"):
        _validate_sha256(f"review binding {field}", result[field])
    cut_shas = result.get("approved_storyboard_cut_sha256s")
    if not isinstance(cut_shas, list) or len(cut_shas) != len(cut_ids):
        raise ValueError("review binding Cut SHA list does not match approved Cut order")
    for index, digest in enumerate(cut_shas):
        _validate_sha256(f"review binding Cut SHA {index}", digest)
    if language is not None:
        for line in lines:
            bcp47 = str((line.get("language") or {}).get("bcp47") or "")
            if not bcp47.casefold().startswith(f"{language.casefold()}-") and bcp47.casefold() != language.casefold():
                raise ValueError("review binding output_language does not match exact line rows")
    return result


def _load_line_contract_module():
    try:
        from line_contract import render_line_for_prompt, canonical_line

        return render_line_for_prompt, canonical_line
    except ImportError:
        import importlib.util

        path = Path(__file__).with_name("line_contract.py")
        spec = importlib.util.spec_from_file_location("replication_line_contract", path)
        if spec is None or spec.loader is None:
            raise ValueError("packaged line_contract.py is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.render_line_for_prompt, module.canonical_line


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical(value))


def _validate_sha256(name: str, value: Any) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _truthy(factors: Mapping[str, Any], *keys: str) -> bool:
    return any(factors.get(key) is True for key in keys)


def _skill_metadata(name: str, path: Any) -> dict[str, str]:
    is_virtual = hasattr(path, "read_bytes") and not isinstance(path, Path)
    if not is_virtual and not Path(path).is_file():
        raise ValueError(f"missing Skill dependency: {name}")
    text = path.read_text(encoding="utf-8") if is_virtual else Path(path).read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*([^\n]+)\s*$", text)
    if not match or match.group(1).strip().strip("\"'") != name:
        raise ValueError(f"Skill snapshot name mismatch: {name}")
    version_match = re.search(r"(?m)^\s*version:\s*([^\n]+)\s*$", text)
    version = version_match.group(1).strip().strip("\"'") if version_match else "unknown"
    raw = bytes(path.read_bytes()) if is_virtual else Path(path).read_bytes()
    package_path = (
        "dependencies/seedance-20/SKILL.md"
        if name == "seedance-20"
        else f"dependencies/seedance-20/skills/{name}/SKILL.md"
    )
    return {
        "name": name,
        "source": "injected",
        "version": version,
        "sha256": _sha_bytes(raw),
        # Never persist the host path.  The deployment maps this logical path
        # to its immutable container/artifact dependency.
        "package_path": package_path,
        "digest_required": True,
    }


def build_skill_plan(
    factors: Mapping[str, Any] | None,
    *,
    skill_files: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the ordered root/core/specialist Skill plan."""

    if not isinstance(skill_files, Mapping):
        raise ValueError("skill_files must be a mapping")
    factors = dict(factors or {})
    modules = ["seedance-20", "seedance-prompt", "seedance-antislop"]
    specialist_order = (
        ("camera", "seedance-camera"),
        ("motion", "seedance-motion"),
        ("lighting", "seedance-lighting"),
        ("performance", "seedance-characters"),
        ("characters", "seedance-characters"),
        ("audio", "seedance-audio"),
        ("style", "seedance-style"),
        ("vfx", "seedance-vfx"),
    )
    for key, module in specialist_order:
        if _truthy(factors, key) and module not in modules:
            modules.append(module)
    if _truthy(factors, "multi_shot", "sequence", "continuity"):
        modules.append("seedance-sequence")
    if len(modules) != len(set(modules)):
        raise ValueError("Skill plan contains duplicate modules")
    snapshot = {name: _skill_metadata(name, skill_files[name]) for name in modules if name in skill_files}
    missing = [name for name in modules if name not in snapshot]
    if missing:
        raise ValueError(f"missing Skill dependencies: {', '.join(missing)}")
    payload = {
        "analysis_pass_count": 1,
        "modules": modules,
        "dependency_snapshot": snapshot,
    }
    payload["route_sha256"] = _sha_json(payload)
    return payload


def _validate_checks(checks: Mapping[str, Any] | None) -> dict[str, bool]:
    if not isinstance(checks, Mapping):
        raise ValueError("compiler_checks must be a mapping")
    result: dict[str, bool] = {}
    for name in COMPILER_CHECKS:
        if checks.get(name) is not True:
            raise ValueError(f"compiler check failed: {name}")
        result[name] = True
    return result


def _skill_bytes(path: Any) -> bytes:
    if hasattr(path, "read_bytes") and not isinstance(path, Path):
        return bytes(path.read_bytes())
    return Path(path).read_bytes()


def _contains_slop(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_slop(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_slop(child) for child in value)
    if isinstance(value, str):
        folded = value.casefold()
        # A single craft word such as ``cinematic`` can be intentional.  The
        # anti-slop gate targets stacked empty superlatives and known filler
        # phrases, while allowing a negative constraint such as ``no epic
        # filler`` to remain an explicit constraint.
        phrases = (
            "cinematic beautiful",
            "beautiful high quality",
            "stunning masterpiece",
            "ultra realistic masterpiece",
            "epic cinematic",
            "high quality cinematic",
        )
        return any(phrase in folded and not folded.startswith("no ") for phrase in phrases)
    return False


def derive_compiler_checks(
    *,
    segment: Mapping[str, Any],
    canonical_lines: Sequence[Mapping[str, Any]],
    factors: Mapping[str, Any] | None,
    prompt: str,
    skill_files: Mapping[str, Any],
) -> dict[str, bool]:
    """Recompute the Seedance gates from the frozen request and Skill bytes.

    The caller's check map is metadata only.  This function is the authority
    used by both compilation and validation, so a caller cannot mark a generic
    or route-leaking prompt as audited by sending eight ``true`` booleans.
    """

    _validate_segment_contract(segment)
    reference_ok = True
    try:
        _format_reference_roles(segment.get("reference_roles") or [])
    except ValueError:
        reference_ok = False
    shots = segment.get("shots") or []
    factors_ok = bool(shots) and all(
        isinstance(shot.get("factor_ids"), list)
        and bool(shot.get("factor_ids"))
        and len(shot.get("factor_ids")) == len(set(shot.get("factor_ids")))
        for shot in shots
        if isinstance(shot, Mapping)
    )
    directing_ok = not _contains_slop(segment)
    anti_slop_ok = not _contains_slop(prompt)
    route_ok = True
    try:
        _reject_route_leakage(segment)
        _reject_route_leakage(factors)
        _reject_route_leakage(prompt)
    except ValueError:
        route_ok = False
    line_ok = True
    render_line_for_prompt, _canonical_line = _load_line_contract_module()
    for line in canonical_lines:
        exact = ((line.get("text") or {}).get("exact") if isinstance(line.get("text"), Mapping) else None)
        if exact and str(exact) not in prompt:
            line_ok = False
        try:
            if render_line_for_prompt(line) not in prompt:
                line_ok = False
        except Exception:
            line_ok = False
    # The root Skill bytes are part of the audit input.  A missing root entry
    # is never silently replaced by caller-supplied metadata.
    root = skill_files.get("seedance-20") if isinstance(skill_files, Mapping) else None
    root_ok = root is not None and bool(_skill_bytes(root))
    return {
        "professional_gate": bool(root_ok),
        "capability_check": True,
        "allocation_check": factors_ok,
        "reference_role_check": reference_ok,
        "directing_coherence_check": directing_ok,
        "anti_slop_check": anti_slop_ok,
        "route_exclusion_check": route_ok,
        "line_parity_check": line_ok,
    }


def build_rule_audit(*, skill_files: Mapping[str, Any], checks: Mapping[str, bool]) -> dict[str, Any]:
    root = skill_files.get("seedance-20") if isinstance(skill_files, Mapping) else None
    if root is None:
        raise ValueError("seedance-20 Skill bytes are required for rule audit")
    raw = _skill_bytes(root)
    return {
        "engine": "seedance-20",
        "version": RULE_ENGINE_VERSION,
        "skill_sha256": _sha_bytes(raw),
        "checks_sha256": _sha_json({name: bool(checks.get(name)) for name in COMPILER_CHECKS}),
        "source": "immutable_skill_bytes_and_compiler_rules",
    }


def _format_reference_roles(roles: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    if len(roles) > 4:
        raise ValueError("segment cannot use more than four reference roles")
    seen_slots: set[int] = set()
    for role in roles:
        if not isinstance(role, Mapping):
            raise ValueError("reference role must be an object")
        slot = role.get("slot")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot not in {1, 2, 3, 4}:
            raise ValueError("reference role slot must be an integer from 1 through 4")
        if slot in seen_slots:
            raise ValueError("reference role slots must be unique")
        seen_slots.add(slot)
        raw_tag = role.get("tag")
        if raw_tag is not None and (
            not isinstance(raw_tag, str) or not raw_tag.strip()
        ):
            raise ValueError("reference role tag must be a non-empty string")
        tag = raw_tag or f"@Image{slot}"
        if tag not in {f"@Image{slot}", f"@图片{slot}", f"@图像{slot}"}:
            raise ValueError("reference role tag must match its fixed image slot")
        raw_purpose = role.get("role")
        if raw_purpose is not None and (
            not isinstance(raw_purpose, str) or not raw_purpose.strip()
        ):
            raise ValueError("reference role purpose must be a non-empty string")
        purpose = raw_purpose or "reference"
        lines.append(f"Reference {tag} (slot {slot}): {purpose}.")
    return lines


def _validate_ui_render_contract(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError("ui_render_contract must be an object")
    if value.get("route") != "generated_ui_demo":
        raise ValueError("ui_render_contract route must be generated_ui_demo")
    if value.get("carrier") not in {
        "deterministic_ui_render",
        "deterministic_composite",
        "postproduction",
    }:
        raise ValueError("generated readable UI requires a deterministic UI carrier")
    if value.get("ocr_required") is not True:
        raise ValueError("generated readable UI requires deterministic UI OCR validation")
    readable = value.get("readable_text") or []
    if (
        not isinstance(readable, Sequence)
        or isinstance(readable, (str, bytes, bytearray))
        or any(not isinstance(item, str) or not item.strip() for item in readable)
    ):
        raise ValueError("ui_render_contract.readable_text must contain exact non-empty strings")
    ocr_target = value.get("ocr_target", 100)
    if isinstance(ocr_target, bool) or not isinstance(ocr_target, (int, float)) or float(ocr_target) != 100.0:
        raise ValueError("generated readable UI requires OCR target 100")


def _validate_segment_contract(segment: Mapping[str, Any]) -> int:
    if not isinstance(segment, Mapping):
        raise ValueError("segment must be an object")
    segment_id = segment.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id.strip():
        raise ValueError("segment_id is required")
    duration = segment.get("duration_ms")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 4000 <= duration <= 15000:
        raise ValueError("segment duration must be between 4000 and 15000 milliseconds")
    opening_state = segment.get("opening_state")
    if opening_state is not None and (
        not isinstance(opening_state, str) or not opening_state.strip()
    ):
        raise ValueError("opening_state must be a non-empty string")
    for field in ("locks", "negative_constraints"):
        values = segment.get(field) or []
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes, bytearray))
            or any(not isinstance(item, str) or not item.strip() for item in values)
        ):
            raise ValueError(f"{field} must be an array of non-empty strings")
    shots = segment.get("shots")
    if not isinstance(shots, Sequence) or isinstance(shots, (str, bytes, bytearray)) or not shots:
        raise ValueError("segment.shots must be a non-empty array")
    expected_start = 0
    seen_shots: set[str] = set()
    seen_factors: set[str] = set()
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, Mapping):
            raise ValueError(f"shots[{index}] must be an object")
        raw_shot_id = shot.get("shot_id")
        if raw_shot_id is not None and (
            not isinstance(raw_shot_id, str) or not raw_shot_id.strip()
        ):
            raise ValueError(f"shots[{index}].shot_id must be a non-empty string")
        shot_id = raw_shot_id or str(index)
        if shot_id in seen_shots:
            raise ValueError("shot_id values must be unique")
        seen_shots.add(shot_id)
        shot_scale = shot.get("shot_scale")
        if shot_scale is not None and (
            not isinstance(shot_scale, str) or not shot_scale.strip()
        ):
            raise ValueError(f"shots[{index}].shot_scale must be a non-empty string")
        start_ms = shot.get("start_ms")
        end_ms = shot.get("end_ms")
        if (
            isinstance(start_ms, bool)
            or not isinstance(start_ms, int)
            or isinstance(end_ms, bool)
            or not isinstance(end_ms, int)
            or start_ms != expected_start
            or end_ms <= start_ms
            or end_ms > duration
        ):
            raise ValueError("segment shots create a gap or overlap, or exceed the segment duration")
        for field in (
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
        ):
            if not isinstance(shot.get(field), str) or not shot[field].strip():
                raise ValueError(f"shots[{index}].{field} is required")
        factor_ids = shot.get("factor_ids")
        if (
            not isinstance(factor_ids, list)
            or not factor_ids
            or any(not isinstance(factor_id, str) or not factor_id.strip() for factor_id in factor_ids)
            or len(factor_ids) != len(set(factor_ids))
        ):
            raise ValueError(f"shots[{index}].factor_ids must be a unique non-empty string array")
        duplicated = seen_factors.intersection(factor_ids)
        if duplicated:
            raise ValueError(f"segment factor_ids must be carried exactly once: {sorted(duplicated)}")
        seen_factors.update(factor_ids)
        expected_start = end_ms
    if expected_start != duration:
        raise ValueError("segment shots create a gap or overlap, or do not cover the segment duration")
    _format_reference_roles(segment.get("reference_roles") or [])
    _validate_ui_render_contract(segment.get("ui_render_contract"))
    return duration


def _line_bounds_for_segment(line: Mapping[str, Any], segment: Mapping[str, Any]) -> tuple[int, int]:
    time = line.get("time")
    if not isinstance(time, Mapping):
        raise ValueError("line time contract is missing")
    if time.get("time_base") == "segment_local_ms" and isinstance(time.get("segment_start_ms"), int):
        return int(time["segment_start_ms"]), int(time["segment_end_ms"])
    start = int(time.get("start_ms", -1))
    end = int(time.get("end_ms", -1))
    origin = segment.get("output_global_start_ms", segment.get("start_ms", 0))
    if isinstance(origin, bool) or not isinstance(origin, int):
        origin = 0
    return start - origin, end - origin


def _validate_line_windows(
    lines: Sequence[Mapping[str, Any]],
    segment: Mapping[str, Any],
    duration_ms: int,
) -> None:
    for line in lines:
        start, end = _line_bounds_for_segment(line, segment)
        if start < 0 or end <= start or end > duration_ms:
            raise ValueError(f"approved line is outside segment: {line.get('line_id')}")
        for collection in ("proof_events", "foley_events", "silence_windows"):
            for event in line.get(collection) or []:
                if isinstance(event.get("segment_start_ms"), int) and isinstance(event.get("segment_end_ms"), int):
                    event_start = int(event["segment_start_ms"])
                    event_end = int(event["segment_end_ms"])
                else:
                    event_start = int(event.get("start_ms", -1)) - int(segment.get("output_global_start_ms", segment.get("start_ms", 0)) or 0)
                    event_end = int(event.get("end_ms", -1)) - int(segment.get("output_global_start_ms", segment.get("start_ms", 0)) or 0)
                if event_start < 0 or event_end <= event_start or event_end > duration_ms:
                    raise ValueError(
                        f"approved {collection} event is outside segment: {event.get('id')}"
                    )


def _validate_no_speech_contracts(
    value: Any,
    *,
    segment_cut_ids: Sequence[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if value is None:
        value = []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("no_speech_contracts must be an array")
    allowed_cut_ids = set(segment_cut_ids or [])
    seen: set[str] = set()
    contracts: list[dict[str, Any]] = []
    renderings: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"no_speech_contracts[{index}] must be an object")
        cut_id = item.get("cut_id")
        if not isinstance(cut_id, str) or not cut_id.strip() or cut_id in seen:
            raise ValueError("no_speech cut IDs must be unique non-empty strings")
        if allowed_cut_ids and cut_id not in allowed_cut_ids:
            raise ValueError(f"no-speech Cut is outside segment: {cut_id}")
        if item.get("speech_mode") != "none":
            raise ValueError("no-speech contract must declare speech_mode=none")
        allowed = item.get("allowed_audio")
        forbidden = item.get("forbidden_audio")
        for label, items, allow_empty in (
            ("allowed_audio", allowed, True),
            ("forbidden_audio", forbidden, False),
        ):
            if (
                not isinstance(items, list)
                or (not allow_empty and not items)
                or any(not isinstance(entry, str) or not entry.strip() for entry in items)
            ):
                raise ValueError(f"no-speech {label} is invalid")
        canonical = {
            "cut_id": cut_id,
            "speech_mode": "none",
            "allowed_audio": list(allowed),
            "forbidden_audio": list(forbidden),
        }
        contracts.append(canonical)
        seen.add(cut_id)
        allowed_text = ", ".join(allowed) if allowed else "contract-approved non-speech audio only"
        renderings.append(
            f"Cut {cut_id}: No dialogue. Allowed audio: {allowed_text}. "
            f"Forbidden audio: {', '.join(forbidden)}."
        )
    return contracts, renderings


def _validate_speech_coverage(
    segment: Mapping[str, Any],
    lines: Sequence[Mapping[str, Any]],
    no_speech_contracts: Sequence[Mapping[str, Any]],
) -> None:
    cut_ids = segment.get("cut_ids")
    if cut_ids is None:
        return
    if (
        not isinstance(cut_ids, Sequence)
        or isinstance(cut_ids, (str, bytes, bytearray))
        or not cut_ids
        or any(not isinstance(cut_id, str) or not cut_id.strip() for cut_id in cut_ids)
        or len(cut_ids) != len(set(cut_ids))
    ):
        raise ValueError("segment.cut_ids must be a unique non-empty string array")
    spoken: set[str] = set()
    for line in lines:
        time = line.get("time") or {}
        line_cuts = time.get("cut_ids") or [line.get("cut_id")]
        spoken.update(str(cut_id) for cut_id in line_cuts if cut_id)
    silent = {str(item["cut_id"]) for item in no_speech_contracts}
    if spoken & silent:
        raise ValueError("a Cut cannot contain both approved dialogue and a no-speech contract")
    declared = set(cut_ids)
    if spoken | silent != declared:
        missing = sorted(declared - spoken - silent)
        extra = sorted((spoken | silent) - declared)
        raise ValueError(f"segment speech coverage is incomplete or invalid; missing={missing}, extra={extra}")


def _format_shot(shot: Mapping[str, Any], index: int) -> str:
    start_ms = int(shot.get("start_ms", 0))
    end_ms = int(shot.get("end_ms", 0))
    if end_ms <= start_ms:
        raise ValueError(f"shots[{index}] time range is invalid")
    return (
        f"Shot {shot.get('shot_id', index)}, {start_ms/1000:.2f}-{end_ms/1000:.2f}s, "
        f"{shot.get('shot_scale', 'stable framing')}. "
        f"Scene: {shot['scene']}. Camera: {shot['camera']}. Lighting: {shot['lighting']}. "
        f"Performance: {shot['performance']}. Action: {shot['action']}. "
        f"Endpoint: {shot['endpoint']}. Product/UI truth: {shot['product_or_ui_truth']}. "
        f"Commercial proof: {shot['commercial_proof']}. Transition: {shot['transition']}. "
        f"Continuity: {shot['continuity']}. Audio: {shot['audio']}."
    )


def _format_segment(segment: Mapping[str, Any]) -> list[str]:
    duration_ms = _validate_segment_contract(segment)
    segment_id = str(segment["segment_id"])
    lines = [f"Segment {segment_id}. Duration {duration_ms / 1000:.2f}s."]
    opening = segment.get("opening_state")
    if opening:
        lines.append(f"Opening state: {opening}")
    lines.extend(_format_reference_roles(segment.get("reference_roles") or []))
    shots = segment.get("shots")
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, Mapping):
            raise ValueError(f"shots[{index}] must be an object")
        lines.append(_format_shot(shot, index))
    for lock in segment.get("locks") or []:
        lines.append(f"Lock: {lock}.")
    for constraint in segment.get("negative_constraints") or []:
        lines.append(f"Constraint: {constraint}.")
    return lines


def _factor_coverage(segment: Mapping[str, Any], prompt: str) -> tuple[list[str], list[dict[str, Any]]]:
    required: list[str] = []
    coverage: list[dict[str, Any]] = []
    for shot_index, shot in enumerate(segment.get("shots") or []):
        rendered = _format_shot(shot, shot_index + 1)
        start = prompt.find(rendered)
        if start < 0:
            raise ValueError(f"compiled prompt is missing shot rendering: {shot.get('shot_id')}")
        end = start + len(rendered)
        for factor_index, factor_id in enumerate(shot.get("factor_ids") or []):
            required.append(str(factor_id))
            coverage.append(
                {
                    "factor_id": str(factor_id),
                    "source_pointer": f"/segment/shots/{shot_index}/factor_ids/{factor_index}",
                    "carrier": "prompt_carried",
                    "status": "passed",
                    "shot_id": str(shot.get("shot_id") or shot_index + 1),
                    "prompt_span": {"start": start, "end": end},
                }
            )
    return required, coverage


def _route_tokens(value: str) -> list[str]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    separated = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", separated)
    return re.findall(r"[a-z0-9]+", separated.casefold())


def _canonical_route_key(value: str) -> str:
    return "_".join(_route_tokens(value))


def _route_leakage_matches(value: str) -> list[str]:
    tokens = _route_tokens(value)
    if not tokens:
        return []
    token_set = set(tokens)
    matches: list[str] = []
    for term in ROUTE_LEAKAGE_TERMS:
        term_tokens = _route_tokens(term)
        width = len(term_tokens)
        compact = "".join(term_tokens)
        if compact in token_set or any(
            tokens[index : index + width] == term_tokens
            for index in range(len(tokens) - width + 1)
        ):
            matches.append(term)
    return matches


def _reject_route_leakage(value: Any, *, parent_key: str | None = None) -> None:
    # Factor identifiers are immutable audit labels, not semantic Prompt
    # content.  They legitimately use names such as
    # ``HFH.C01.TRANSITION.SHELL``; scanning their punctuation-folded form as
    # natural language would create a false route-leakage failure.
    if parent_key in {"factor_ids", "required_factor_ids"}:
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                if _canonical_route_key(key) in ROUTE_LEAKAGE_EXACT_KEYS:
                    raise ValueError(f"route leakage: {key}")
                leaked = _route_leakage_matches(key)
                if leaked:
                    raise ValueError(f"route leakage: {', '.join(leaked)}")
            _reject_route_leakage(
                child,
                parent_key=key if isinstance(key, str) else None,
            )
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_route_leakage(child, parent_key=parent_key)
    elif isinstance(value, str):
        leaked = _route_leakage_matches(value)
        if leaked:
            raise ValueError(f"route leakage: {', '.join(leaked)}")


def _content_without_hash(artifact: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(artifact))
    compiler = dict(result.get("compiler") or {})
    compiler.pop("output_sha256", None)
    result["compiler"] = compiler
    return result


def _source_contract(
    *,
    segment: Mapping[str, Any],
    factors: Mapping[str, Any] | None,
    compiler_checks: Mapping[str, Any],
    performance_lines: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Freeze every deterministic input that can change prompt semantics."""

    if not isinstance(segment, Mapping):
        raise ValueError("segment must be an object")
    if factors is not None and not isinstance(factors, Mapping):
        raise ValueError("factors must be an object")
    return {
        "segment": deepcopy(dict(segment)),
        "factors": deepcopy(dict(factors or {})),
        "compiler_checks": deepcopy(dict(compiler_checks)),
        "performance_lines": deepcopy(list(performance_lines or [])),
    }


def _validate_performance_lines(
    value: Sequence[Mapping[str, Any]] | None,
    *,
    segment: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("performance_lines must be an array")
    if not value:
        return []
    allowed_cut_ids = [str(item) for item in segment.get("cut_ids") or []]
    if not allowed_cut_ids:
        raise ValueError("performance_lines require segment Cut IDs")
    by_cut: dict[str, dict[str, Any]] = {}
    required = {
        "cut_id", "source_time", "segment_time", "performance_mode",
        "exact_sung_text", "lyric_status", "beat_anchors_ms", "no_beat_reason",
        "lip_sync", "action", "expression", "emotion", "end_pose",
        "criticality", "final_audio_carrier",
    }
    for index, item in enumerate(value, start=1):
        if not isinstance(item, Mapping) or set(item) != required:
            raise ValueError(f"performance_lines[{index}] has an invalid contract shape")
        cut_id = item.get("cut_id")
        if not isinstance(cut_id, str) or cut_id not in allowed_cut_ids or cut_id in by_cut:
            raise ValueError("performance line Cut coverage is invalid")
        for label in ("source_time", "segment_time"):
            window = item.get(label)
            if not isinstance(window, Mapping) or set(window) != {"start_ms", "end_ms"}:
                raise ValueError(f"performance line {label} is invalid")
            if any(isinstance(window.get(key), bool) or not isinstance(window.get(key), int) for key in ("start_ms", "end_ms")) or window["end_ms"] <= window["start_ms"]:
                raise ValueError(f"performance line {label} bounds are invalid")
        if item["segment_time"]["start_ms"] < 0 or item["segment_time"]["end_ms"] > int(segment["duration_ms"]):
            raise ValueError("performance line falls outside the segment")
        lyric_status = item.get("lyric_status")
        lyric = item.get("exact_sung_text")
        if lyric_status not in {"verified", "instrumental", "inaudible"} or not isinstance(lyric, str) or not lyric.strip():
            raise ValueError("performance line lyric contract is invalid")
        performance_mode = item.get("performance_mode")
        if performance_mode not in _PERFORMANCE_MODES:
            raise ValueError("performance line performance_mode is invalid")
        if performance_mode in {"spoken", "sung", "singing"} and lyric_status != "verified":
            raise ValueError("spoken or sung performance requires verified exact text")
        if performance_mode in {"instrumental", "inaudible"} and lyric_status != performance_mode:
            raise ValueError("non-verbal performance mode must match lyric_status")
        beats = item.get("beat_anchors_ms")
        if not isinstance(beats, list) or any(isinstance(beat, bool) or not isinstance(beat, int) for beat in beats):
            raise ValueError("performance line beat anchors are invalid")
        if not beats and not isinstance(item.get("no_beat_reason"), str):
            raise ValueError("performance line requires beat anchors or a no-beat reason")
        for label, keys in (
            ("lip_sync", ("face_visibility", "articulation", "end_state")),
            ("action", ("start", "beat_action", "end")),
            ("expression", ("start", "peak", "end")),
        ):
            nested = item.get(label)
            if not isinstance(nested, Mapping) or set(nested) != set(keys) or any(not isinstance(nested[key], str) or not nested[key].strip() for key in keys):
                raise ValueError(f"performance line {label} is invalid")
        for label in ("performance_mode", "emotion", "end_pose", "criticality", "final_audio_carrier"):
            if not isinstance(item.get(label), str) or not item[label].strip():
                raise ValueError(f"performance line {label} is invalid")
        by_cut[cut_id] = deepcopy(dict(item))
    if set(by_cut) != set(allowed_cut_ids):
        raise ValueError("performance line Cut coverage is incomplete")
    return [by_cut[cut_id] for cut_id in allowed_cut_ids]


def _render_performance_line(line: Mapping[str, Any]) -> str:
    source = line["source_time"]
    local = line["segment_time"]
    lyric = line["exact_sung_text"]
    performance_mode = line["performance_mode"]
    if line["lyric_status"] == "verified":
        verb = "speaks" if performance_mode == "spoken" else "sings"
        speech = f'{verb} exactly, "{lyric}"'
    else:
        speech = f"performs {line['lyric_status']} with no invented words"
    beat = ", ".join(f"{item / 1000:.2f}s" for item in line["beat_anchors_ms"]) or str(line["no_beat_reason"])
    return (
        f"Performance Cut {line['cut_id']}, source-audio global {source['start_ms'] / 1000:.2f}-{source['end_ms'] / 1000:.2f}s, "
        f"segment-local {local['start_ms'] / 1000:.2f}-{local['end_ms'] / 1000:.2f}s: {speech}. "
        f"Lip sync: {line['lip_sync']['face_visibility']}; {line['lip_sync']['articulation']}; {line['lip_sync']['end_state']}. "
        f"Beat anchors: {beat}. Action: {line['action']['start']}; {line['action']['beat_action']}; {line['action']['end']}. "
        f"Expression: {line['expression']['start']}; {line['expression']['peak']}; {line['expression']['end']}. "
        f"Emotion: {line['emotion']}. End pose: {line['end_pose']}. Final audio carrier: {line['final_audio_carrier']}."
    )


def _validate_approval_binding(
    value: Any,
    *,
    source_contract: Mapping[str, Any],
    canonical_lines: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("prompt approval binding must be an object")
    binding = deepcopy(dict(value))
    if binding.get("schema_version") != APPROVAL_BINDING_SCHEMA:
        raise ValueError("prompt approval binding schema is invalid")
    if binding.get("profile") != "high_fidelity_hybrid_v1":
        raise ValueError("prompt approval binding profile is invalid")
    if binding.get("route") not in {"route_1", "route_2"}:
        raise ValueError("prompt approval binding route is invalid")
    for field in _APPROVAL_BINDING_SHA_FIELDS:
        _validate_sha256(f"approval_binding.{field}", binding.get(field))
    input_digests = binding.get("input_digests")
    if not isinstance(input_digests, Mapping):
        raise ValueError("prompt approval binding input_digests must be an object")
    normalized_inputs: dict[str, str] = {}
    for key, digest in sorted(input_digests.items()):
        if not isinstance(key, str) or not key.strip():
            raise ValueError("prompt approval binding input digest names must be non-empty strings")
        normalized_inputs[key] = _validate_sha256(
            f"approval_binding.input_digests[{key}]",
            digest,
        )
    binding["input_digests"] = normalized_inputs
    if binding["input_digests_sha256"] != _sha_json(normalized_inputs):
        raise ValueError("prompt approval binding input digest set changed")

    segment = source_contract.get("segment")
    factors = source_contract.get("factors")
    checks = source_contract.get("compiler_checks")
    if not isinstance(segment, Mapping) or not isinstance(factors, Mapping) or not isinstance(checks, Mapping):
        raise ValueError("prompt source contract is invalid")
    if binding.get("segment_id") != segment.get("segment_id"):
        raise ValueError("prompt approval binding segment_id changed")
    if binding.get("duration_ms") != segment.get("duration_ms"):
        raise ValueError("prompt approval binding duration changed")
    cut_ids = segment.get("cut_ids") or []
    if binding.get("cut_ids") != list(cut_ids):
        raise ValueError("prompt approval binding Cut order changed")
    derived = {
        "segment_contract_sha256": _sha_json(segment),
        "locks_sha256": _sha_json(segment.get("locks") or []),
        "reference_roles_sha256": _sha_json(segment.get("reference_roles") or []),
        "shots_sha256": _sha_json(segment.get("shots") or []),
        "line_contract_sha256": _sha_json(list(canonical_lines)),
        "factors_sha256": _sha_json(factors),
        "compiler_checks_sha256": _sha_json(checks),
        "compiler_route_sha256": str(plan.get("route_sha256") or ""),
        "character_lock_sha256": normalized_inputs.get(
            "character_lock_sha256",
            _sha_json(segment.get("character_locks", segment.get("character_lock", []))),
        ),
        "product_truth_sha256": normalized_inputs.get(
            "product_truth_sha256",
            _sha_json(segment.get("product_locks", segment.get("product_lock", []))),
        ),
        "voiceover_contract_sha256": _sha_json(list(canonical_lines)),
        "cut_order_sha256": _sha_json(list(cut_ids)),
        "duration_sha256": _sha_json(segment.get("duration_ms")),
    }
    for field, expected in derived.items():
        if binding.get(field) != expected:
            raise ValueError(f"prompt approval binding {field} changed")
    root = (plan.get("dependency_snapshot") or {}).get("seedance-20") or {}
    if binding.get("compiler_skill_sha256") != root.get("sha256"):
        raise ValueError("prompt approval binding compiler Skill changed")
    return binding


def compile_prompt(
    *,
    segment: Mapping[str, Any],
    line_contracts: Sequence[Mapping[str, Any]],
    factors: Mapping[str, Any] | None,
    skill_files: Mapping[str, Any],
    compiler_checks: Mapping[str, Any],
    performance_lines: Sequence[Mapping[str, Any]] | None = None,
    approval_binding: Mapping[str, Any] | None = None,
    review_bindings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile one frozen segment and exact line contract into an auditable artifact."""

    duration_ms = _validate_segment_contract(segment)
    _reject_route_leakage(segment)
    _reject_route_leakage(factors or {})
    plan = build_skill_plan(factors, skill_files=skill_files)
    declared_checks = _validate_checks(compiler_checks)
    render_line_for_prompt, canonical_line = _load_line_contract_module()
    canonical_lines = [canonical_line(line) for line in line_contracts]
    canonical_performance_lines = _validate_performance_lines(
        performance_lines,
        segment=segment,
    )
    normalized_review_bindings = None
    if review_bindings is not None:
        normalized_review_bindings = _validate_review_bindings(
            review_bindings,
            cut_ids=segment.get("cut_ids") or [],
            lines=canonical_lines,
        )
    _validate_line_windows(canonical_lines, segment, duration_ms)
    no_speech_contracts, no_speech_renderings = _validate_no_speech_contracts(
        segment.get("no_speech_contracts"),
        segment_cut_ids=segment.get("cut_ids"),
    )
    _validate_speech_coverage(segment, canonical_lines, no_speech_contracts)
    prompt_lines = _format_segment(segment)
    for line in canonical_lines:
        prompt_lines.append(render_line_for_prompt(line))
    for line in canonical_performance_lines:
        prompt_lines.append(_render_performance_line(line))
    prompt_lines.extend(no_speech_renderings)
    prompt = " ".join(part.strip() for part in prompt_lines if part and part.strip()).strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("compiled prompt exceeds 5000 characters")
    _reject_route_leakage(prompt)
    checks = derive_compiler_checks(
        segment=segment,
        canonical_lines=canonical_lines,
        factors=factors,
        prompt=prompt,
        skill_files=skill_files,
    )
    failed_recomputed = [name for name in COMPILER_CHECKS if checks.get(name) is not True]
    if failed_recomputed:
        raise ValueError(f"recomputed Seedance compiler check failed: {', '.join(failed_recomputed)}")
    if declared_checks != checks:
        raise ValueError("caller compiler_checks do not match recomputed Seedance rules")
    rule_audit = build_rule_audit(skill_files=skill_files, checks=checks)
    root = plan["dependency_snapshot"]["seedance-20"]
    required_factor_ids, prompt_factor_coverage = _factor_coverage(segment, prompt)
    source_contract = _source_contract(
        segment=segment,
        factors=factors,
        compiler_checks=checks,
        performance_lines=canonical_performance_lines,
    )
    if approval_binding is not None:
        _validate_approval_binding(
            approval_binding,
            source_contract=source_contract,
            canonical_lines=canonical_lines,
            plan=plan,
        )
    artifact: dict[str, Any] = {
        "schema_version": "seedance20-prompt/v1",
        "prompt": prompt,
        "compiler": {
            "contract": "seedance20-prompt-compiler/v1",
            "profile": "high_fidelity_hybrid_v1",
            "skill": "seedance-20",
            "version": root["version"],
            "skill_sha256": root["sha256"],
            "loaded_modules": list(plan["modules"]),
            "required_specialists": list(plan["modules"][3:]),
            "dependency_snapshot": deepcopy(plan["dependency_snapshot"]),
            "route_sha256": plan["route_sha256"],
            "checks": checks,
            "rule_audit": rule_audit,
            **({"review_bindings": normalized_review_bindings} if normalized_review_bindings is not None else {}),
            **{
                name: checks[name]
                for name in (
                    "professional_gate",
                    "capability_check",
                    "allocation_check",
                "reference_role_check",
                "directing_coherence_check",
                "anti_slop_check",
                "route_exclusion_check",
                "line_parity_check",
            )
            },
        },
        "line_contracts": deepcopy(canonical_lines),
        "line_contract_sha256": _sha_json(canonical_lines),
        "performance_line_contracts": deepcopy(canonical_performance_lines),
        "performance_line_contract_sha256": _sha_json(canonical_performance_lines),
        "no_speech_contracts": no_speech_contracts,
        "no_speech_contract_sha256": _sha_json(no_speech_contracts),
        "required_factor_ids": required_factor_ids,
        "required_factor_ids_sha256": _sha_json(required_factor_ids),
        "prompt_factor_coverage": prompt_factor_coverage,
        "prompt_factor_coverage_sha256": _sha_json(prompt_factor_coverage),
        "source_contract": source_contract,
    }
    if approval_binding is not None:
        artifact["approval_binding"] = deepcopy(dict(approval_binding))
    artifact["compiler"]["output_sha256"] = _sha_json(_content_without_hash(artifact))
    return artifact


def validate_compiled_prompt(
    artifact: Mapping[str, Any],
    *,
    skill_files: Mapping[str, Path],
    line_contracts: Sequence[Mapping[str, Any]],
    expected_performance_lines: Sequence[Mapping[str, Any]] | None = None,
    expected_source_contract: Mapping[str, Any] | None = None,
    expected_approval_binding: Mapping[str, Any] | None = None,
    expected_review_bindings: Mapping[str, Any] | None = None,
) -> None:
    if not isinstance(artifact, Mapping) or artifact.get("schema_version") != "seedance20-prompt/v1":
        raise ValueError("invalid compiled prompt artifact")
    compiler = artifact.get("compiler")
    if not isinstance(compiler, Mapping) or compiler.get("skill") != "seedance-20":
        raise ValueError("seedance-20 compiler provenance is missing")
    _validate_checks(compiler.get("checks"))
    for name in COMPILER_CHECKS:
        if compiler.get(name) is not True:
            raise ValueError(f"compiler check failed: {name}")
    modules = compiler.get("loaded_modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError("loaded_modules is missing")
    required_specialists = compiler.get("required_specialists")
    if required_specialists != modules[3:]:
        raise ValueError("required specialist snapshot changed")
    plan = build_skill_plan(
        {name.replace("seedance-", ""): True for name in modules if name.startswith("seedance-")},
        skill_files=skill_files,
    )
    if list(modules) != plan["modules"]:
        raise ValueError("skill snapshot module plan changed")
    if compiler.get("route_sha256") != plan["route_sha256"]:
        raise ValueError("skill route snapshot changed")
    if compiler.get("dependency_snapshot") != plan["dependency_snapshot"]:
        raise ValueError("dependency snapshot changed")
    root = plan["dependency_snapshot"]["seedance-20"]
    if compiler.get("skill_sha256") != root["sha256"]:
        raise ValueError("skill snapshot hash changed")
    rule_audit = compiler.get("rule_audit")
    expected_rule_audit = build_rule_audit(
        skill_files=skill_files,
        checks={name: compiler.get("checks", {}).get(name) for name in COMPILER_CHECKS},
    )
    if not isinstance(rule_audit, Mapping) or dict(rule_audit) != expected_rule_audit:
        raise ValueError("Seedance packaged rule audit changed")
    prompt = artifact.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("compiled prompt length is invalid")
    _reject_route_leakage(prompt)
    _render, canonical_line = _load_line_contract_module()
    canonical_lines = [canonical_line(line) for line in line_contracts]
    stored_review_bindings = compiler.get("review_bindings")
    if stored_review_bindings is not None or expected_review_bindings is not None:
        if not isinstance(stored_review_bindings, Mapping):
            raise ValueError("review binding is missing")
        normalized_review_bindings = _validate_review_bindings(
            stored_review_bindings,
            cut_ids=(artifact.get("source_contract") or {}).get("segment", {}).get("cut_ids") or [],
            lines=canonical_lines,
        )
        if expected_review_bindings is not None:
            expected_review = _validate_review_bindings(
                expected_review_bindings,
                cut_ids=(artifact.get("source_contract") or {}).get("segment", {}).get("cut_ids") or [],
                lines=canonical_lines,
            )
            if normalized_review_bindings != expected_review:
                raise ValueError("review binding does not match approved evidence")
    source_contract = artifact.get("source_contract")
    if not isinstance(source_contract, Mapping):
        raise ValueError("compiled prompt source contract is missing")
    source_contract = _source_contract(
        segment=source_contract.get("segment"),
        factors=source_contract.get("factors"),
        compiler_checks=source_contract.get("compiler_checks"),
        performance_lines=source_contract.get("performance_lines"),
    )
    if expected_source_contract is not None:
        expected_source = _source_contract(
            segment=expected_source_contract.get("segment"),
            factors=expected_source_contract.get("factors"),
            compiler_checks=expected_source_contract.get("compiler_checks"),
            performance_lines=expected_source_contract.get("performance_lines"),
        )
        if source_contract != expected_source:
            raise ValueError("compiled prompt source contract does not match approved inputs")
    source_segment = source_contract["segment"]
    source_factors = source_contract["factors"]
    source_checks = source_contract["compiler_checks"]
    canonical_performance_lines = _validate_performance_lines(
        source_contract.get("performance_lines"),
        segment=source_segment,
    )
    if expected_performance_lines is not None:
        expected_performance = _validate_performance_lines(
            expected_performance_lines,
            segment=source_segment,
        )
        if canonical_performance_lines != expected_performance:
            raise ValueError("compiled prompt performance contract does not match approved evidence")
    _validate_segment_contract(source_segment)
    _reject_route_leakage(source_segment)
    _reject_route_leakage(source_factors)
    _validate_checks(source_checks)
    source_plan = build_skill_plan(source_factors, skill_files=skill_files)
    if compiler.get("loaded_modules") != source_plan["modules"]:
        raise ValueError("compiled prompt compiler route does not match approved factors")
    if compiler.get("route_sha256") != source_plan["route_sha256"]:
        raise ValueError("compiled prompt compiler route does not match approved factors")
    stored_binding = artifact.get("approval_binding")
    if stored_binding is not None or expected_approval_binding is not None:
        if stored_binding is None:
            raise ValueError("compiled prompt approval binding is missing")
        binding = _validate_approval_binding(
            stored_binding,
            source_contract=source_contract,
            canonical_lines=canonical_lines,
            plan=source_plan,
        )
        if expected_approval_binding is not None and binding != dict(expected_approval_binding):
            raise ValueError("compiled prompt approval binding does not match approved evidence")
    if artifact.get("line_contract_sha256") != _sha_json(canonical_lines):
        raise ValueError("line contract snapshot changed")
    stored_lines = artifact.get("line_contracts")
    if not isinstance(stored_lines, list) or stored_lines != canonical_lines:
        raise ValueError("line contract snapshot changed")
    if artifact.get("performance_line_contracts") != canonical_performance_lines:
        raise ValueError("performance line contract snapshot changed")
    if artifact.get("performance_line_contract_sha256") != _sha_json(canonical_performance_lines):
        raise ValueError("performance line contract digest changed")
    for line in canonical_lines:
        exact = line["text"]["exact"]
        if exact not in prompt:
            raise ValueError(f"approved exact line missing: {line['line_id']}")
        rendered = _render(line)
        if rendered not in prompt:
            raise ValueError(f"approved line rendering changed: {line['line_id']}")
    for line in canonical_performance_lines:
        rendered = _render_performance_line(line)
        if rendered not in prompt:
            raise ValueError(f"approved performance rendering changed: {line['cut_id']}")
    no_speech_contracts, renderings = _validate_no_speech_contracts(
        artifact.get("no_speech_contracts") or []
    )
    if artifact.get("no_speech_contract_sha256") != _sha_json(no_speech_contracts):
        raise ValueError("no-speech contract snapshot changed")
    for rendering in renderings:
        if rendering not in prompt:
            raise ValueError("approved no-speech rendering changed")
    required_factor_ids, prompt_factor_coverage = _factor_coverage(source_segment, prompt)
    if artifact.get("required_factor_ids") != required_factor_ids:
        raise ValueError("required high-fidelity factor set changed")
    if artifact.get("required_factor_ids_sha256") != _sha_json(required_factor_ids):
        raise ValueError("required high-fidelity factor digest changed")
    if artifact.get("prompt_factor_coverage") != prompt_factor_coverage:
        raise ValueError("prompt high-fidelity factor coverage changed")
    if artifact.get("prompt_factor_coverage_sha256") != _sha_json(prompt_factor_coverage):
        raise ValueError("prompt high-fidelity factor coverage digest changed")
    # Re-render from the frozen source contract.  A caller must not be able to
    # append a conflicting instruction and make it look valid by recalculating
    # the artifact digest.
    expected_artifact = compile_prompt(
        segment=source_segment,
        line_contracts=canonical_lines,
        performance_lines=canonical_performance_lines,
        factors=source_factors,
        skill_files=skill_files,
        compiler_checks=source_checks,
        approval_binding=stored_binding if isinstance(stored_binding, Mapping) else None,
        review_bindings=stored_review_bindings if isinstance(stored_review_bindings, Mapping) else None,
    )
    if expected_artifact.get("prompt") != prompt:
        raise ValueError("deterministic compiled prompt differs from the approved source contract")
    if expected_artifact.get("source_contract") != source_contract:
        raise ValueError("compiled prompt source contract is not canonical")
    if compiler.get("output_sha256") != _sha_json(_content_without_hash(artifact)):
        raise ValueError("compiled prompt artifact digest is stale")


__all__ = [
    "COMPILER_CHECKS",
    "MAX_PROMPT_CHARS",
    "ROUTE_LEAKAGE_TERMS",
    "build_skill_plan",
    "derive_compiler_checks",
    "build_rule_audit",
    "compile_prompt",
    "validate_compiled_prompt",
]
