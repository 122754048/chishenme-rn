"""Contracts shared by the v2 split-edit driver, worker, and provider stages."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Mapping, Sequence


SPLIT_STAGE_NAMES = (
    "submit_provider_video_pass1",
    "wait_provider_video_pass1",
    "run_qc_pass1",
    "submit_provider_video_pass2",
    "wait_provider_video_pass2",
    "splice_timeline",
    "run_qc",
)
PASS1_FACTOR_IDS = ("model_replacement", "dialogue_change", "language_switch", "garment_replacement")
PASS2_FACTOR_IDS = ("product_replacement", "ui_replacement", "scene_replacement", "physical_text")
FACTOR_WEIGHTS = {
    "model_replacement": 1.0,
    "garment_replacement": 0.5,
    "scene_replacement": 1.0,
    "product_replacement": 0.5,
    "ui_replacement": 0.5,
    "physical_text": 0.5,
    "dialogue_change": 0.5,
    "language_switch": 0.0,
}

_PROVIDER_RETRY_ADJUSTMENT = "narrow_failed_change_scope"


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def split_provider_retry_dedupe(
    base_dedupe: str,
    *,
    parent_attempt_id: str,
    parent_request_sha256: str,
) -> str:
    return canonical_sha(
        {
            "base_dedupe": base_dedupe,
            "parent_attempt_id": str(parent_attempt_id),
            "parent_request_sha256": str(parent_request_sha256).lower(),
            "retry_index": 2,
        }
    )


def is_confirmed_provider_retry_row(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("confirmed") is True
        and value.get("retry_index") == 2
        and bool(str(value.get("parent_attempt_id") or ""))
        and bool(str(value.get("parent_request_sha256") or ""))
        and bool(str(value.get("evidence_sha256") or ""))
        and bool(str(value.get("adjustment") or ""))
    )


def build_split_provider_retry_audit(
    audit: Mapping[str, Any],
    *,
    failed_attempt: Any,
    failure_evidence_sha256: str,
) -> dict[str, Any]:
    """Derive one immutable pass-scoped provider retry audit."""

    if not isinstance(audit, Mapping):
        raise ValueError("provider retry audit must be an object")
    result = deepcopy(dict(audit))
    segments = result.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("provider retry audit has no segments")
    parent_attempt_id = str(getattr(failed_attempt, "attempt_id", "") or "")
    parent_request_sha256 = str(getattr(failed_attempt, "request_sha256", "") or "").lower()
    if not parent_attempt_id or not parent_request_sha256:
        raise ValueError("provider retry parent identity is missing")
    retry = {
        "parent_attempt_id": parent_attempt_id,
        "parent_request_sha256": parent_request_sha256,
        "failure_type": "provider_failure",
        "confirmed": True,
        "adjustment": _PROVIDER_RETRY_ADJUSTMENT,
        "evidence_sha256": str(failure_evidence_sha256).lower(),
        "retry_index": 2,
        "request_revision": 2,
        "review_required": True,
    }
    for raw in segments:
        if not isinstance(raw, dict):
            raise ValueError("provider retry audit segment is invalid")
        existing = raw.get("retry")
        if existing is not None and not is_confirmed_provider_retry_row(existing):
            raise ValueError("provider retry audit row is invalid")
        raw["retry"] = dict(retry)
        payload = raw.get("payload_template")
        if not isinstance(payload, dict):
            raise ValueError("provider retry payload template is invalid")
        if not str(payload.get("prompt") or ""):
            raise ValueError("provider retry prompt is missing")
    result["stage_fingerprint"] = canonical_sha(result)
    return result


def split_contract_from_output(output: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(output, Mapping):
        return None
    contract = output.get("seedance_input_contract")
    if not isinstance(contract, Mapping):
        return None
    complexity = contract.get("complexity")
    split_plan = complexity.get("split_plan") if isinstance(complexity, Mapping) else None
    if not isinstance(complexity, Mapping) or complexity.get("decision") != "split_required":
        return None
    if not isinstance(split_plan, list) or len(split_plan) != 2:
        return None
    return contract


def is_split_compile_output(output: Mapping[str, Any] | None) -> bool:
    return split_contract_from_output(output) is not None


def split_pass_score(contract: Mapping[str, Any], pass_index: int) -> float:
    complexity = contract.get("complexity")
    split_plan = complexity.get("split_plan") if isinstance(complexity, Mapping) else None
    if not isinstance(split_plan, list) or pass_index < 1 or pass_index > len(split_plan):
        raise ValueError("split plan is invalid")
    factors = split_plan[pass_index - 1].get("factor_ids") if isinstance(split_plan[pass_index - 1], Mapping) else None
    if not isinstance(factors, list):
        raise ValueError("split pass factor ids are invalid")
    score = 0.0
    dialogue_seen = False
    language_seen = False
    for factor in factors:
        if factor not in FACTOR_WEIGHTS:
            raise ValueError(f"unknown split factor: {factor}")
        dialogue_seen |= factor == "dialogue_change"
        language_seen |= factor == "language_switch"
        if factor not in {"dialogue_change", "language_switch"}:
            score += FACTOR_WEIGHTS[factor]
    if dialogue_seen or language_seen:
        score += 0.5
    return score


def load_formal_stage_output(job_store: Any, job_id: str, stage: str) -> Mapping[str, Any] | None:
    checkpoint = job_store.get_stage_checkpoint(job_id, stage)
    if checkpoint is None or checkpoint.status != "SUCCEEDED":
        return None
    matches: list[Mapping[str, Any]] = []
    for artifact_id in checkpoint.output_artifact_ids:
        artifact = job_store.get_artifact(job_id, artifact_id)
        if artifact is None or artifact.kind != "stage_output":
            continue
        metadata = artifact.metadata if isinstance(artifact.metadata, Mapping) else {}
        if metadata.get("stage") != stage:
            continue
        inline = metadata.get("inline_payload")
        if isinstance(inline, Mapping) and isinstance(inline.get("output"), Mapping):
            matches.append(dict(inline["output"]))
    if len(matches) != 1:
        return None
    return matches[0]


def resolve_split_stage_plan(
    base_plan: Sequence[Mapping[str, Any]],
    *,
    job_store: Any,
    job_id: str,
) -> list[dict[str, Any]]:
    """Resolve dynamic pass stages only after compile output is authoritative."""

    compile_output = load_formal_stage_output(job_store, job_id, "compile_seedance20_prompt")
    if not is_split_compile_output(compile_output):
        return [dict(item) for item in base_plan]
    prefix: list[dict[str, Any]] = []
    for item in base_plan:
        prefix.append(dict(item))
        if str(item.get("name") or "") == "audit_edit_request":
            break
    if not prefix or str(prefix[-1].get("name") or "") != "audit_edit_request":
        return [dict(item) for item in base_plan]

    def stage(name: str, *, kind: str, depends_on: Sequence[str], provider: bool = False, pass_index: int | None = None) -> dict[str, Any]:
        result = {
            "name": name,
            "runtime_stage": name,
            "kind": kind,
            "provider": provider,
            "depends_on": list(depends_on),
            "edit_contract": "video-edit-v2",
            "status": "ready",
            "contract_version": "video-edit-v2",
        }
        if pass_index is not None:
            result["pass_index"] = pass_index
            result["pass_identity"] = f"pass{pass_index}"
        return result

    return prefix + [
        stage("submit_provider_video_pass1", kind="provider_create", depends_on=("audit_edit_request",), provider=True, pass_index=1),
        stage("wait_provider_video_pass1", kind="provider_poll", depends_on=("submit_provider_video_pass1",), provider=True, pass_index=1),
        stage("run_qc_pass1", kind="qc", depends_on=("wait_provider_video_pass1",), pass_index=1),
        stage("submit_provider_video_pass2", kind="provider_create", depends_on=("run_qc_pass1",), provider=True, pass_index=2),
        stage("wait_provider_video_pass2", kind="provider_poll", depends_on=("submit_provider_video_pass2",), provider=True, pass_index=2),
        stage("splice_timeline", kind="assembly", depends_on=("wait_provider_video_pass2",)),
        stage("evaluate_voiceover_fallback", kind="qc", depends_on=("splice_timeline",)),
        stage(
            "replace_voiceover_audio",
            kind="provider_create",
            depends_on=("evaluate_voiceover_fallback", "splice_timeline"),
            provider=True,
        ),
        stage("run_qc", kind="qc", depends_on=("replace_voiceover_audio", "splice_timeline")),
    ]


def _prompt_parts(prompt: str) -> tuple[str, list[tuple[str, str]], list[str]]:
    prefix = prompt.split(" @Image", 1)[0].strip()
    bindings = [
        (tag.strip(), role.strip())
        for _number, tag, role in re.findall(r"@Image(\d+)\s+绑定\s+([^（]+)（([^）]+)）", prompt)
    ]
    sentences = [part.strip() for part in re.split(r"(?<=[。；.])\s*", prompt) if part.strip()]
    return prefix, bindings, sentences


def enrich_split_compile_output(output: Mapping[str, Any], *, context: Any) -> dict[str, Any]:
    """Create only static split data; pass2 runtime input remains unresolved."""

    result = deepcopy(dict(output))
    contract = split_contract_from_output(result)
    if contract is None:
        return result
    segments = contract.get("segments")
    if not isinstance(segments, list) or len(segments) != 1 or not isinstance(segments[0], Mapping):
        return result
    segment = dict(segments[0])
    compiled = segment.get("compiled_prompt")
    if not isinstance(compiled, Mapping) or not isinstance(compiled.get("prompt"), str):
        return result
    prefix, legacy_bindings, sentences = _prompt_parts(compiled["prompt"])
    raw_bindings = segment.get("asset_bindings")
    bindings: list[tuple[str, str]] = []
    if isinstance(raw_bindings, Sequence) and not isinstance(raw_bindings, (str, bytes, bytearray)):
        for index, raw in enumerate(raw_bindings, start=1):
            if not isinstance(raw, Mapping):
                bindings = []
                break
            tag = str(raw.get("asset_tag") or raw.get("tag") or "").strip()
            reference = str(raw.get("image_reference") or raw.get("reference") or "").strip()
            role = str(raw.get("asset_type") or raw.get("role") or "").strip().casefold()
            role = "app" if role == "ui" else role
            if not tag or reference != f"@Image{index}" or role not in {"model", "garment", "product", "app", "scene"}:
                bindings = []
                break
            bindings.append((tag, role))
    if not bindings:
        bindings = legacy_bindings
    if not bindings:
        return result

    pass1_bindings = [item for item in bindings if item[1] in {"model", "garment"}]
    pass2_bindings = [item for item in bindings if item[1] in {"product", "ui", "app", "scene"}]
    pass1_tags = {tag for tag, _role in pass1_bindings}
    pass2_tags = {tag for tag, _role in pass2_bindings}
    pass1_text = [
        sentence for sentence in sentences
        if any(tag in sentence for tag in pass1_tags)
        or any(token in sentence for token in ("台词", "语言切换", "approved_language_windows", "sync_to_approved_dialogue_windows"))
    ]
    pass2_text = [sentence for sentence in sentences if any(tag in sentence for tag in pass2_tags)]

    def local_bindings(items: Sequence[tuple[str, str]]) -> list[dict[str, str]]:
        return [
            {"tag": tag, "reference": f"@Image{index}"}
            for index, (tag, _role) in enumerate(items, 1)
        ]

    def renumber_references(text: str) -> str:
        next_reference = 0
        def replace_reference(_match: re.Match[str]) -> str:
            nonlocal next_reference
            next_reference += 1
            return f"@Image{next_reference}"
        return re.sub(r"@Image\d+", replace_reference, text)

    split_plan = contract["complexity"]["split_plan"]
    pass_prompts = [
        {
            "prompt": renumber_references(" ".join([prefix, *pass1_text]).strip()),
            "asset_bindings": local_bindings(pass1_bindings),
            "factor_ids": list(split_plan[0].get("factor_ids") or ()),
        },
        {
            "prompt": renumber_references(" ".join([prefix, *pass2_text]).strip()),
            "asset_bindings": local_bindings(pass2_bindings),
            "factor_ids": list(split_plan[1].get("factor_ids") or ()),
        },
    ]
    source = next(
        (item for item in context.artifacts if isinstance(item, Mapping) and item.get("kind") == "source_video"),
        None,
    )
    segment_id = str(segment.get("segment_id") or "")
    window = {
        "start_ms": segment.get("start_ms"),
        "end_ms": segment.get("end_ms"),
        "duration_ms": segment.get("duration_ms"),
    }
    approved_script_sha = str(getattr(context.snapshot, "approved_script_sha256", "") or "").lower()
    manifests: list[dict[str, Any]] = []
    template_shas: list[str] = []
    for index, pass_prompt in enumerate(pass_prompts, 1):
        manifest: dict[str, Any] = {
            "pass_index": index,
            "pass_identity": f"pass{index}",
            "factor_ids": list(pass_prompt["factor_ids"]),
            "prompt": pass_prompt["prompt"],
            "asset_bindings": list(pass_prompt["asset_bindings"]),
            "prompt_sha256": canonical_sha(pass_prompt["prompt"]),
            "asset_binding_sha256": canonical_sha(pass_prompt["asset_bindings"]),
            "approved_script_sha256": approved_script_sha,
            "segment_id": segment_id,
            "window": window,
        }
        if index == 1:
            manifest["input_video_artifact_id"] = str(source.get("artifact_id") or "") if isinstance(source, Mapping) else ""
            manifest["input_video_sha256"] = str(source.get("sha256") or "").lower() if isinstance(source, Mapping) else ""
            manifest["input_video_authority_stage"] = "source_video"
        else:
            manifest["input_video_authority_stage"] = "wait_provider_video_pass1"
        template_shas.append(canonical_sha(manifest))
        manifests.append(manifest)

    contract_copy = dict(contract)
    contract_copy["split_edit_plan"] = {
        "schema_version": "seedance-split-edit/v1",
        "pass_count": 2,
        "pass_manifests": manifests,
        "pass_prompts": pass_prompts,
        "pass_plan_sha256": canonical_sha({"split_plan": split_plan, "segment_id": segment_id, "window": window}),
        "pass_request_template_sha256s": template_shas,
    }
    result["seedance_input_contract"] = contract_copy
    result["pass_prompts"] = pass_prompts
    result["pass_manifests"] = manifests
    result["pass_plan_sha256"] = contract_copy["split_edit_plan"]["pass_plan_sha256"]
    result["pass_request_template_sha256s"] = template_shas
    return result


__all__ = [
    "PASS1_FACTOR_IDS",
    "PASS2_FACTOR_IDS",
    "SPLIT_STAGE_NAMES",
    "canonical_sha",
    "build_split_provider_retry_audit",
    "enrich_split_compile_output",
    "is_confirmed_provider_retry_row",
    "is_split_compile_output",
    "load_formal_stage_output",
    "split_provider_retry_dedupe",
    "resolve_split_stage_plan",
    "split_contract_from_output",
    "split_pass_score",
]
