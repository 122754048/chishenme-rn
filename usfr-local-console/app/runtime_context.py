from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping

from .qa_matrix import build_qa_matrix


class RuntimePacketError(ValueError):
    pass


def compile_runtime_packet(
    *,
    source_contract: Mapping[str, object],
    target_truth: Mapping[str, object],
    execution_map: Mapping[str, object],
    stage: str,
) -> dict[str, object]:
    source_sha256 = _sha256(source_contract)
    target_sha256 = _sha256(target_truth)
    projected_map = copy.deepcopy(dict(execution_map))
    _bind_or_reject(projected_map, "source_analysis_sha256", source_sha256)
    _bind_or_reject(projected_map, "target_truth_sha256", target_sha256)
    packet: dict[str, object] = {
        "schema_version": 1,
        "stage": stage,
        "source_fidelity_contract_ref": {
            "sha256": source_sha256,
            "region_ids": _region_ids(source_contract),
            "contract": copy.deepcopy(dict(source_contract)),
        },
        "target_truth": copy.deepcopy(dict(target_truth)),
        "execution_map": projected_map,
        "route_cards": _route_cards(projected_map),
        "qa_matrix": build_qa_matrix(projected_map, source_contract),
        "lineage": {
            "source_contract_sha256": source_sha256,
            "target_truth_sha256": target_sha256,
            "execution_map_sha256": _sha256(projected_map),
            "input_slots_sha256": projected_map.get("input_slots_sha256"),
        },
    }
    validate_packet_lineage(packet)
    return packet


def validate_packet_lineage(packet: Mapping[str, object]) -> None:
    try:
        source_ref = packet["source_fidelity_contract_ref"]
        target_truth = packet["target_truth"]
        execution_map = packet["execution_map"]
        lineage = packet["lineage"]
        if not all(isinstance(value, Mapping) for value in (source_ref, target_truth, execution_map, lineage)):
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
        source_contract = source_ref["contract"]
        source_sha256 = _sha256(source_contract)
        target_sha256 = _sha256(target_truth)
        map_sha256 = _sha256(execution_map)
        expected = {
            "source_contract_sha256": source_sha256,
            "target_truth_sha256": target_sha256,
            "execution_map_sha256": map_sha256,
        }
        if any(lineage.get(key) != value for key, value in expected.items()):
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
        if source_ref.get("sha256") != source_sha256:
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
        if execution_map.get("source_analysis_sha256") != source_sha256:
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
        if execution_map.get("target_truth_sha256") != target_sha256:
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
        source_region_ids = _region_ids(source_contract)
        if source_ref.get("region_ids") != source_region_ids:
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
        map_regions = execution_map.get("regions")
        if not isinstance(map_regions, list):
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
        mapped_region_ids = [
            region.get("region_id")
            for region in map_regions
            if isinstance(region, Mapping) and isinstance(region.get("region_id"), str)
        ]
        if mapped_region_ids != source_region_ids:
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
        generated_segment_ids = execution_map.get("generated_segment_ids")
        if generated_segment_ids is not None and (
            not isinstance(generated_segment_ids, list)
            or any(not isinstance(region_id, str) or region_id not in mapped_region_ids for region_id in generated_segment_ids)
        ):
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
        input_slots_sha256 = execution_map.get("input_slots_sha256")
        if not _is_sha256(input_slots_sha256) or lineage.get("input_slots_sha256") != input_slots_sha256:
            raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, RuntimePacketError):
            raise
        raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID") from error


def _bind_or_reject(value: dict[str, object], key: str, expected: str) -> None:
    current = value.get(key)
    if current in {None, ""}:
        value[key] = expected
        return
    if current != expected:
        raise RuntimePacketError("RUNTIME_PACKET_LINEAGE_INVALID")


def _route_cards(execution_map: Mapping[str, object]) -> list[dict[str, object]]:
    changed_layers = set(execution_map.get("changed_layers") or [])
    regions = execution_map.get("regions") or []
    cards: list[dict[str, object]] = []
    if "model" in changed_layers:
        cards.append({"id": "model_replace", "allowed_modules": ["seedance-characters"]})
    if "product" in changed_layers:
        cards.append({"id": "physical_product_replace", "allowed_modules": ["seedance-motion"]})
    if "background_music" in changed_layers:
        cards.append({"id": "background_music_replace_sing", "allowed_modules": ["seedance-audio"]})
    if execution_map.get("run_mode") == "language_only":
        cards.append({"id": "language_only", "allowed_modules": ["asr", "translation", "tts", "lip_sync"]})
    elif "language" in changed_layers:
        cards.append({"id": "localized_composite_layer", "allowed_modules": ["localized_lines"]})
    if any(isinstance(region, Mapping) and region.get("media_origin") in {"opaque_ui", "opaque_tail"} for region in regions):
        cards.append({"id": "opaque_ui_tail", "allowed_modules": ["timeline_splice"]})
    if any(isinstance(region, Mapping) and region.get("media_origin") == "generated_ui" for region in regions):
        cards.append({"id": "generated_ui", "allowed_modules": ["ui_renderer", "ocr"]})
    return cards


def _region_ids(source_contract: Mapping[str, object]) -> list[str]:
    regions = source_contract.get("regions") or source_contract.get("cuts") or []
    return [
        str(region.get("region_id") or region.get("cut_id") or region.get("id"))
        for region in regions
        if isinstance(region, Mapping)
    ]


def _sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
