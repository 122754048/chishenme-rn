from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .slots import ValidatedIntake


class ExecutionMapError(ValueError):
    pass


def classify_run_mode(
    *,
    optional_slot_ids: set[str],
    output_language: str | None,
    extension_ids: set[str] | None = None,
) -> str:
    extensions = extension_ids or set()
    if output_language and not optional_slot_ids and not extensions:
        return "language_only"
    return "composite_replication"


def build_execution_map(
    *,
    intake: ValidatedIntake,
    source_contract: Mapping[str, object],
    target_truth: Mapping[str, object],
) -> dict[str, object]:
    regions = _normalized_regions(source_contract)
    optional_slot_ids = set(intake.optional_files)
    extension_ids = set(intake.extension_files)
    run_mode = classify_run_mode(
        optional_slot_ids=optional_slot_ids,
        output_language=intake.output_language,
        extension_ids=extension_ids,
    )
    changed_layers = _changed_layers(intake)
    ui_route = _ui_route(optional_slot_ids, bool(intake.app_store_url))
    tail_route = "opaque_app_tail_card" if "tail_video" in optional_slot_ids else "omit_source_end_card"
    has_visible_replacement = bool({"model", "product", "app_product"} & set(changed_layers))
    mapped_regions: list[dict[str, object]] = []
    for region in regions:
        mapped_regions.append(
            _map_region(
                region,
                run_mode=run_mode,
                ui_route=ui_route,
                tail_route=tail_route,
                changed_layers=changed_layers,
                has_visible_replacement=has_visible_replacement,
                output_language=intake.output_language,
            )
        )

    generated_segment_ids = [
        str(region["region_id"])
        for region in mapped_regions
        if region["media_origin"] == "generated"
    ]
    app_evidence = _app_evidence(
        app_store_url=intake.app_store_url,
        mapped_regions=mapped_regions,
        target_truth=target_truth,
    )
    skipped = _skipped_modules(ui_route=ui_route, tail_route=tail_route, app_evidence=app_evidence)
    result: dict[str, object] = {
        "schema_version": 1,
        "source_analysis_sha256": _sha256_json(source_contract),
        "target_truth_sha256": _sha256_json(target_truth),
        "run_mode": run_mode,
        "changed_layers": changed_layers,
        "ui_route": ui_route,
        "tail_route": tail_route,
        "app_evidence": app_evidence,
        "regions": mapped_regions,
        "generated_segment_ids": generated_segment_ids,
        "skipped": skipped,
        "audio_policy": _default_audio_policy(
            intake.output_language, ui_route, tail_route, intake.opaque_audio_policies
        ),
    }
    if "background_music" in extension_ids:
        result["background_music"] = {
            "enabled": True,
            "provider_route": "seedance_audio_reference",
            "timeline_contract_ref": "analysis/music_timeline_contract.json",
            "final_audio_source": "uploaded_exact_audio",
            "preserve_source_music_boundaries": "frame_exact",
            "allow_loop_or_time_stretch": False,
            "timeline_status": "required",
        }
    else:
        result["background_music"] = {"enabled": False}
    return result


def build_route_preview(execution_map: Mapping[str, object]) -> dict[str, object]:
    regions = list(execution_map.get("regions") or [])
    return {
        "run_mode": execution_map["run_mode"],
        "deep_analysis": "once",
        "generate_region_ids": [
            region["region_id"] for region in regions if region.get("media_origin") == "generated"
        ],
        "splice_region_ids": [
            region["region_id"]
            for region in regions
            if region.get("media_origin") in {"source_interval", "opaque_ui", "opaque_tail"}
        ],
        "skip_modules": [item["module"] for item in execution_map.get("skipped", [])],
        "ui_route": execution_map["ui_route"],
        "tail_route": execution_map["tail_route"],
        "app_evidence": execution_map["app_evidence"],
        "audio_policy": execution_map["audio_policy"],
        "background_music": _background_music_preview(execution_map),
    }


def _normalized_regions(source_contract: Mapping[str, object]) -> list[dict[str, object]]:
    raw_regions = source_contract.get("regions") or source_contract.get("cuts")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise ExecutionMapError("SOURCE_REGION_CONTRACT_REQUIRED")
    normalized: list[dict[str, object]] = []
    previous_end: int | None = None
    for index, raw_region in enumerate(raw_regions):
        if not isinstance(raw_region, Mapping):
            raise ExecutionMapError("SOURCE_REGION_CONTRACT_INVALID")
        region_id = raw_region.get("region_id") or raw_region.get("cut_id") or raw_region.get("id")
        start_ms = raw_region.get("start_ms")
        end_ms = raw_region.get("end_ms")
        if not isinstance(region_id, str) or not isinstance(start_ms, int) or not isinstance(end_ms, int):
            raise ExecutionMapError("SOURCE_REGION_CONTRACT_INVALID")
        if start_ms < 0 or end_ms <= start_ms or (previous_end is not None and start_ms != previous_end):
            raise ExecutionMapError("SOURCE_REGION_COVERAGE_INVALID")
        normalized.append(
            {
                "region_id": region_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "kind": str(raw_region.get("kind") or raw_region.get("type") or "body"),
                "visible_singer": bool(raw_region.get("visible_singer")),
            }
        )
        previous_end = end_ms
    return normalized


def _changed_layers(intake: ValidatedIntake) -> list[str]:
    layers: list[str] = []
    slot_layers = {
        "new_product_image": "product",
        "new_model_image": "model",
        "ui_screenshot": "ui",
        "ui_operation_video": "ui",
        "tail_video": "tail",
    }
    for slot_id, layer in slot_layers.items():
        if slot_id in intake.optional_files and layer not in layers:
            layers.append(layer)
    if intake.app_store_url:
        layers.append("app_product")
    if intake.output_language:
        layers.append("language")
    if "background_music" in intake.extension_files:
        layers.extend(("background_music", "singing_performance"))
    return layers


def _ui_route(optional_slot_ids: set[str], has_app_store_url: bool) -> str:
    if "ui_operation_video" in optional_slot_ids:
        return "opaque_ui_demo"
    if "ui_screenshot" in optional_slot_ids or has_app_store_url:
        return "generated_ui_demo"
    return "source_ui_keep"


def _map_region(
    region: Mapping[str, object],
    *,
    run_mode: str,
    ui_route: str,
    tail_route: str,
    changed_layers: list[str],
    has_visible_replacement: bool,
    output_language: str | None,
) -> dict[str, object]:
    kind = region["kind"]
    if kind == "ui":
        media_origin = {
            "opaque_ui_demo": "opaque_ui",
            "generated_ui_demo": "generated_ui",
            "source_ui_keep": "source_interval",
        }[ui_route]
        return _region_record(
            region,
            media_origin=media_origin,
            changed_layers=["ui"] if media_origin != "source_interval" else [],
            qa_profile="opaque_technical" if media_origin == "opaque_ui" else "generated_ui_high_risk",
        )
    if kind in {"tail", "end_card"}:
        return _region_record(
            region,
            media_origin="opaque_tail" if tail_route == "opaque_app_tail_card" else "omitted",
            changed_layers=["tail"] if tail_route == "opaque_app_tail_card" else [],
            qa_profile="opaque_technical" if tail_route == "opaque_app_tail_card" else "not_applicable",
        )
    needs_singing_generation = "singing_performance" in changed_layers and bool(region.get("visible_singer"))
    media_origin = "generated" if run_mode == "composite_replication" and (has_visible_replacement or needs_singing_generation) else "source_interval"
    regional_layers = list(changed_layers) if media_origin == "generated" else (["language"] if output_language else [])
    qa_profile = "generated_high_risk" if media_origin == "generated" else ("localized_source" if output_language else "source_technical")
    return _region_record(region, media_origin=media_origin, changed_layers=regional_layers, qa_profile=qa_profile)


def _region_record(
    region: Mapping[str, object],
    *,
    media_origin: str,
    changed_layers: list[str],
    qa_profile: str,
) -> dict[str, object]:
    return {
        "region_id": region["region_id"],
        "start_ms": region["start_ms"],
        "end_ms": region["end_ms"],
        "source_kind": region["kind"],
        "media_origin": media_origin,
        "assembly_policy": "omit" if media_origin == "omitted" else f"splice_{media_origin}",
        "changed_layers": changed_layers,
        "qa_profile": qa_profile,
        "visible_singer": bool(region.get("visible_singer")),
    }


def _app_evidence(
    *,
    app_store_url: str | None,
    mapped_regions: list[dict[str, object]],
    target_truth: Mapping[str, object],
) -> dict[str, object]:
    if not app_store_url:
        return {"required": False, "purpose": [], "status": "not_requested"}
    purposes: list[str] = []
    if any(region["media_origin"] == "generated_ui" for region in mapped_regions):
        purposes.append("generated_device_screen")
    if any(region["media_origin"] == "generated" for region in mapped_regions):
        purposes.append("claim_truth")
    if not purposes:
        return {"required": False, "purpose": [], "status": "skipped"}
    return {
        "required": True,
        "purpose": purposes,
        "status": "required",
        "existing_bundle_sha256": target_truth.get("app_evidence_bundle_sha256"),
    }


def _skipped_modules(*, ui_route: str, tail_route: str, app_evidence: Mapping[str, object]) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    if ui_route == "opaque_ui_demo":
        skipped.extend(
            (
                {"module": "ui_ocr_renderer", "reason": "ui_operation_video_supplied"},
                {"module": "ui_semantic_analysis", "reason": "ui_operation_video_supplied"},
            )
        )
    if tail_route == "opaque_app_tail_card":
        skipped.append({"module": "tail_generation", "reason": "tail_video_supplied"})
    if app_evidence.get("status") == "skipped":
        skipped.append({"module": "app_store_parser", "reason": "no_generated_evidence_carrier"})
    return skipped


def _default_audio_policy(
    output_language: str | None,
    ui_route: str,
    tail_route: str,
    selected_policies: Mapping[str, str],
) -> dict[str, str]:
    opaque_policy = "opaque_audio_mute_with_localized_voiceover" if output_language else "opaque_audio_keep"
    return {
        "ui": selected_policies.get("ui", opaque_policy) if ui_route == "opaque_ui_demo" else "generated_target_audio",
        "tail": selected_policies.get("tail", opaque_policy) if tail_route == "opaque_app_tail_card" else "omit",
    }


def _background_music_preview(execution_map: Mapping[str, object]) -> dict[str, object]:
    music = execution_map.get("background_music")
    if not isinstance(music, Mapping) or music.get("enabled") is not True:
        return {"enabled": False}
    contract = music.get("timeline_contract")
    windows: list[dict[str, object]] = []
    if isinstance(contract, Mapping) and isinstance(contract.get("windows"), list):
        for raw in contract["windows"]:
            if not isinstance(raw, Mapping):
                continue
            window = {
                key: raw[key]
                for key in ("source_start_frame", "source_end_frame", "output_start_frame", "output_end_frame")
                if key in raw
            }
            for key in ("uploaded_start_ms", "uploaded_end_ms"):
                if key in raw:
                    window[key] = raw[key]
            windows.append(window)
    visible_singers = [
        str(region.get("region_id"))
        for region in execution_map.get("regions") or []
        if isinstance(region, Mapping) and region.get("visible_singer") is True
    ]
    frozen = music.get("timeline_status") == "frozen" and bool(windows)
    risks = []
    if not frozen:
        risks.append("music_timeline_contract_required")
    if any("uploaded_start_ms" not in window or "uploaded_end_ms" not in window for window in windows):
        risks.append("uploaded_music_fragment_mapping_required")
    if visible_singers:
        risks.append("singing_alignment_and_lip_sync_required")
    return {
        "enabled": True,
        "timeline_status": "frozen" if frozen else "required",
        "source_windows": windows,
        "uploaded_music_mapping": [
            {
                key: window[key]
                for key in ("source_start_frame", "source_end_frame", "uploaded_start_ms", "uploaded_end_ms")
                if key in window
            }
            for window in windows
            if "uploaded_start_ms" in window and "uploaded_end_ms" in window
        ],
        "visible_singer_regions": visible_singers,
        "risks": risks,
        "required_receipts": ["final_mix_receipt", "final_audio_sha256"],
    }


def _sha256_json(value: Mapping[str, object]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
