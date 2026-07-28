from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .jobs import FileJobStore, VersionConflict
from .models import JobSnapshot
from .audio_routes import AudioRouteError, validate_background_music_delivery
from .qa_matrix import QaMatrixError, validate_qa_coverage
from .reviews import canonical_digest, create_script_revision, create_storyboard_revision
from .runtime_context import compile_runtime_packet


class BridgeError(ValueError):
    pass


ALLOWED_RESULT_KINDS = {
    "semantic_analysis_required": {"script_revision"},
    "storyboard_review_required": {"storyboard_revision"},
    "provider_request_ready": {"provider_request"},
    "qa_review_ready": {"qa_receipt"},
}


def input_manifest_sha256(job: JobSnapshot) -> str:
    return canonical_digest(job.inputs)


def export_codex_task(store: FileJobStore, job: JobSnapshot, *, stage: str) -> dict[str, Any]:
    if stage not in ALLOWED_RESULT_KINDS:
        raise BridgeError("CODEX_STAGE_UNSUPPORTED")
    task: dict[str, Any] = {
        "schema_version": 1,
        "job_id": job.job_id,
        "expected_job_version": job.version,
        "stage": stage,
        "input_manifest_sha256": input_manifest_sha256(job),
        "inputs": copy.deepcopy(job.inputs),
        "output_language": job.output_language,
        "route": job.route,
        "runtime_packet": _runtime_packet(store, job, stage),
        "allowed_result_kinds": sorted(ALLOWED_RESULT_KINDS[stage]),
        "skill_instruction": "Run $universal-source-fidelity-replication using the immutable job inputs and return only the required structured result package.",
    }
    task["task_sha256"] = canonical_digest(task)
    store.write_job_json(job.job_id, "codex/codex_task.json", task)
    return task


def _runtime_packet(store: FileJobStore, job: JobSnapshot, stage: str) -> dict[str, object]:
    root = store.job_dir(job.job_id)
    frozen_source_contract = root / "analysis" / "source_fidelity_contract.json"
    source_contract = _read_json(
        frozen_source_contract if frozen_source_contract.is_file() else root / "analysis" / "source_contract.pending.json"
    )
    target_truth = _read_json(root / "analysis" / "target_truth.json")
    execution_map = _read_json(root / "analysis" / "execution_map.json")
    if execution_map.get("input_slots_sha256") != input_manifest_sha256(job):
        raise BridgeError("CODEX_RUNTIME_PACKET_UNAVAILABLE")
    return compile_runtime_packet(
        source_contract=source_contract,
        target_truth=target_truth,
        execution_map=execution_map,
        stage=stage,
    )


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BridgeError("CODEX_RUNTIME_PACKET_UNAVAILABLE") from error
    if not isinstance(value, dict):
        raise BridgeError("CODEX_RUNTIME_PACKET_UNAVAILABLE")
    return value


def finalize_codex_result(payload: dict[str, Any]) -> dict[str, Any]:
    if "result" not in payload:
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    payload["result_sha256"] = canonical_digest(payload["result"])
    return payload


def import_codex_result(
    store: FileJobStore, job_id: str, expected_version: int, payload: dict[str, Any]
) -> JobSnapshot:
    job = store.get(job_id)
    try:
        _validate_result(job, expected_version, payload)
    except (KeyError, TypeError, ValueError, VersionConflict) as error:
        if isinstance(error, BridgeError):
            raise
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED") from error

    stage = payload["stage"]
    result = payload["result"]
    store.write_job_json(job_id, f"codex/import-{job.version}.json", payload)
    if stage == "semantic_analysis_required":
        return _import_script(store, job, result)
    if stage == "storyboard_review_required":
        return _import_storyboard(store, job, result)
    if stage == "provider_request_ready":
        return _import_provider_request(store, job, result)
    return _import_qa_receipt(store, job, result)


def _validate_result(job: JobSnapshot, expected_version: int, payload: dict[str, Any]) -> None:
    if job.version != expected_version:
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    if payload.get("job_id") != job.job_id:
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    if payload.get("expected_job_version") != expected_version:
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    stage = payload.get("stage")
    if stage not in ALLOWED_RESULT_KINDS:
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    if payload.get("input_manifest_sha256") != input_manifest_sha256(job):
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("kind") not in ALLOWED_RESULT_KINDS[stage]:
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    if payload.get("result_sha256") != canonical_digest(result):
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    task = {key: value for key, value in payload.items() if key not in {"result", "result_sha256", "task_sha256"}}
    if payload.get("task_sha256") != canonical_digest(task):
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")


def _import_script(store: FileJobStore, job: JobSnapshot, result: dict[str, Any]) -> JobSnapshot:
    script_text = result.get("script_text")
    if not isinstance(script_text, str):
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    source_contract = result.get("source_contract")
    if source_contract is not None:
        if not isinstance(source_contract, dict):
            raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
        job = store.freeze_source_contract(
            job.job_id,
            expected_version=job.version,
            source_contract=source_contract,
        )
    create_script_revision(store, job.job_id, job.version, script_text)
    return store.get(job.job_id)


def _import_storyboard(store: FileJobStore, job: JobSnapshot, result: dict[str, Any]) -> JobSnapshot:
    storyboard = result.get("storyboard")
    if not isinstance(storyboard, dict):
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    create_storyboard_revision(store, job.job_id, job.version, storyboard)
    return store.get(job.job_id)


def _import_provider_request(store: FileJobStore, job: JobSnapshot, result: dict[str, Any]) -> JobSnapshot:
    request = result.get("provider_request")
    if not isinstance(request, dict):
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")

    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        current["provider"] = {"state": "REQUEST_READY", "request": request}
        current["stage"] = "PROVIDER"
        return current

    return store.update(job.job_id, expected_version=job.version, mutate=mutate, event="PROVIDER_REQUEST_IMPORTED")


def _import_qa_receipt(store: FileJobStore, job: JobSnapshot, result: dict[str, Any]) -> JobSnapshot:
    receipt = result.get("receipt", {})
    if not isinstance(receipt, dict):
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    timing_ledger = receipt.get("timing_ledger")
    if timing_ledger is not None and not isinstance(timing_ledger, dict):
        raise BridgeError("CODEX_BRIDGE_RESULT_REJECTED")
    stored_receipt = copy.deepcopy(receipt)
    runtime_packet = _runtime_packet(store, job, "qa_review_ready")
    qa_matrix = runtime_packet.get("qa_matrix")
    if not isinstance(qa_matrix, Mapping):
        raise BridgeError("QA_COVERAGE_REQUIRED")
    try:
        validate_qa_coverage(qa_receipt=stored_receipt, qa_matrix=qa_matrix)
    except QaMatrixError as error:
        raise BridgeError(str(error)) from error
    finalized_execution_map: dict[str, object] | None = None
    if "background_music" in job.inputs:
        _validate_background_music_qa(job, result)
        delivery = result["background_music_delivery"]
        stored_receipt["background_music_delivery"] = copy.deepcopy(delivery)
        finalized_execution_map = _finalize_background_music_execution_map(job, delivery)

    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        current["qa_receipt"] = stored_receipt
        current["timing_ledger"] = timing_ledger
        if finalized_execution_map is not None:
            current["execution_map"] = copy.deepcopy(finalized_execution_map)
        current["stage"] = "DONE"
        return current

    updated = store.update(job.job_id, expected_version=job.version, mutate=mutate, event="QA_RECEIPT_IMPORTED")
    if finalized_execution_map is not None:
        store.write_job_json(job.job_id, "analysis/execution_map.json", finalized_execution_map)
    return updated


def _validate_background_music_qa(job: JobSnapshot, result: Mapping[str, Any]) -> None:
    delivery = result.get("background_music_delivery")
    if not isinstance(delivery, Mapping):
        raise BridgeError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
    route = delivery.get("route")
    final_audio_sha256 = delivery.get("final_audio_sha256")
    mix_receipt = delivery.get("mix_receipt")
    if not isinstance(route, Mapping) or not isinstance(final_audio_sha256, str):
        raise BridgeError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
    _validate_background_music_route(job, route)
    try:
        validate_background_music_delivery(
            route=route,
            final_audio_sha256=final_audio_sha256,
            mix_receipt=mix_receipt if isinstance(mix_receipt, Mapping) else None,
        )
    except AudioRouteError as error:
        raise BridgeError(str(error)) from error


def _validate_background_music_route(job: JobSnapshot, route: Mapping[str, Any]) -> None:
    expected_sha256 = (job.inputs.get("background_music") or {}).get("sha256")
    execution_map = job.execution_map or {}
    music = execution_map.get("background_music") if isinstance(execution_map, Mapping) else None
    if not isinstance(expected_sha256, str) or not isinstance(music, Mapping):
        raise BridgeError("BACKGROUND_MUSIC_ROUTE_UNVERIFIED")
    if music.get("timeline_status") != "frozen" or not isinstance(music.get("timeline_contract"), Mapping):
        raise BridgeError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
    if route.get("uploaded_audio_sha256") != expected_sha256:
        raise BridgeError("BACKGROUND_MUSIC_ROUTE_UNVERIFIED")
    expected_provider = {
        "provider_route": "runninghub_standard_audio_urls",
        "provider_upload": "runninghub_binary_media_upload",
        "provider_request_field": "audioUrls",
        "prompt_reference_tag": "@Audio1",
        "forbidden_provider_field": "reference_audios",
        "final_audio_source": "uploaded_exact_audio",
        "allow_loop_or_time_stretch": False,
    }
    if any(route.get(key) != value for key, value in expected_provider.items()):
        raise BridgeError("BACKGROUND_MUSIC_ROUTE_UNVERIFIED")
    _validate_singing_qa_contract(execution_map, route)
    contract_windows = music["timeline_contract"].get("windows")
    route_windows = route.get("windows")
    if not isinstance(contract_windows, list) or not isinstance(route_windows, list) or len(contract_windows) != len(route_windows):
        raise BridgeError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
    for contract_window, route_window in zip(contract_windows, route_windows):
        if not isinstance(contract_window, Mapping) or not isinstance(route_window, Mapping):
            raise BridgeError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
        for field in ("source_start_frame", "source_end_frame", "output_start_frame", "output_end_frame"):
            if route_window.get(field) != contract_window.get(field):
                raise BridgeError("BACKGROUND_MUSIC_TIMELINE_MISMATCH")


def _validate_singing_qa_contract(execution_map: Mapping[str, Any], route: Mapping[str, Any]) -> None:
    regions = execution_map.get("regions")
    if not isinstance(regions, list):
        raise BridgeError("SINGING_ALIGNMENT_REQUIRED")
    visible_singer_ids = [
        region.get("region_id")
        for region in regions
        if isinstance(region, Mapping) and region.get("visible_singer") is True
    ]
    if any(not isinstance(region_id, str) or not region_id for region_id in visible_singer_ids):
        raise BridgeError("SINGING_ALIGNMENT_REQUIRED")
    singing_qa = route.get("singing_qa")
    if not isinstance(singing_qa, Mapping):
        raise BridgeError("SINGING_ALIGNMENT_REQUIRED")
    reported_regions = singing_qa.get("regions")
    if visible_singer_ids:
        if singing_qa.get("status") != "required" or not isinstance(reported_regions, list):
            raise BridgeError("SINGING_ALIGNMENT_REQUIRED")
        reported_ids = [
            receipt.get("region_id")
            for receipt in reported_regions
            if isinstance(receipt, Mapping)
        ]
        if reported_ids != visible_singer_ids or len(reported_regions) != len(visible_singer_ids):
            raise BridgeError("SINGING_ALIGNMENT_REQUIRED")
        for receipt in reported_regions:
            if not isinstance(receipt, Mapping) or not all(
                _is_sha256(receipt.get(field))
                for field in ("alignment_receipt_sha256", "lip_sync_receipt_sha256")
            ):
                raise BridgeError("SINGING_ALIGNMENT_REQUIRED")
        return
    if (
        singing_qa.get("status") != "skipped"
        or singing_qa.get("reason") != "no_visible_singing_person"
        or reported_regions != []
    ):
        raise BridgeError("SINGING_ALIGNMENT_REQUIRED")


def _finalize_background_music_execution_map(
    job: JobSnapshot,
    delivery: Mapping[str, Any],
) -> dict[str, object]:
    execution_map = copy.deepcopy(dict(job.execution_map or {}))
    music = execution_map.get("background_music")
    route = delivery.get("route")
    final_audio_sha256 = delivery.get("final_audio_sha256")
    mix_receipt = delivery.get("mix_receipt")
    if (
        not isinstance(music, dict)
        or not isinstance(route, Mapping)
        or not _is_sha256(final_audio_sha256)
        or not isinstance(mix_receipt, Mapping)
    ):
        raise BridgeError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
    music["final_audio_sha256"] = final_audio_sha256
    music["final_mix_receipt_sha256"] = canonical_digest(mix_receipt)
    music["singing_qa"] = copy.deepcopy(dict(route["singing_qa"]))
    music["delivery_status"] = "verified"
    return execution_map


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
