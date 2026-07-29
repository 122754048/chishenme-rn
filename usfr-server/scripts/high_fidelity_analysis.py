#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


CONTRACT = "high-fidelity-analysis"
CONTRACT_VERSION = 1
PROFILE = "high_fidelity_hybrid_v1"
INTENT_SEQUENCE = (
    "Attention",
    "Curiosity",
    "Understanding",
    "Belief",
    "Desire",
    "Action",
    "Loop",
)
LEGACY_INTENT_KEYS = (
    "commercial_goal",
    "attention_hook",
    "character_or_creator_appeal",
    "product_proof",
    "emotional_promise",
    "social_or_trust_signal",
    "cta_conversion",
    "pacing_and_format",
    "platform_compliance",
)
ROUTES = {
    "KEEP",
    "REPLACE",
    "COMPOSITE",
    "REMOVE",
    "REINTERPRET",
    "OPAQUE_SPLICE",
}
MIGRATION_TYPES = {"exact", "functional", "intent_only", "unsupported"}
PROOF_EQUIVALENCE = {"exact", "analogous", "none"}
CRITICALITIES = {"H", "M", "L"}
CARRIERS = {
    "source_interval",
    "opaque_media",
    "deterministic_composite",
    "seedance_generation",
    "audio_mix",
    "route_excluded",
}
EVIDENCE_ORIGINS = {"source", "slot", "official", "approved"}
EVIDENCE_KINDS = {
    "frame",
    "audio",
    "OCR",
    "ASR",
    "screenshot",
    "UI_state",
    "operation",
    "result",
}
PROVENANCE_STATES = {"observed", "inferred", "planned"}
CLAIM_CLASSES = {
    "feature",
    "mechanism",
    "benefit",
    "result",
    "comparison",
    "social_proof",
    "identity",
    "offer",
    "urgency",
}
CLAIM_RISK_CLASSES = {
    "ordinary",
    "comparative",
    "guarantee",
    "regulated_health",
    "financial",
    "safety",
    "children",
    "adult",
}
SUPPORT_STATUSES = {"supported", "unsupported", "reinterpreted"}
DISPOSITIONS = {"exact", "partial", "prohibited"}
TARGET_KINDS = {"physical_product", "app", "service", "brand", "creator", "other"}
FEASIBILITY = {"feasible", "infeasible", "unknown"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_sha256(value: Any, label: str) -> None:
    require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, f"{label} must be lowercase SHA-256")


def _validate_time_range(value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    start = value.get("start_ms")
    end = value.get("end_ms")
    require(_is_integer(start) and _is_integer(end) and 0 <= start < end, f"{label} is invalid")


def _validate_evidence(items: Any, label: str, *, allow_empty: bool = False) -> None:
    require(isinstance(items, list), f"{label} must be an array")
    if not allow_empty:
        require(bool(items), f"{label} must be non-empty")
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        prefix = f"{label}[{index}]"
        require(isinstance(item, dict), f"{prefix} must be an object")
        evidence_id = item.get("evidence_id")
        require(_non_empty_string(evidence_id), f"{prefix}.evidence_id is empty")
        require(evidence_id not in seen, f"{label} repeats evidence_id {evidence_id}")
        seen.add(evidence_id)
        require(item.get("origin") in EVIDENCE_ORIGINS, f"{prefix}.origin is invalid")
        object_key = item.get("object_key")
        require(_non_empty_string(object_key), f"{prefix}.object_key is empty")
        require(
            not DRIVE_PATH_RE.match(object_key) and not object_key.startswith(("/", "\\")),
            f"{prefix}.object_key must be object-store relative",
        )
        require(item.get("kind") in EVIDENCE_KINDS, f"{prefix}.kind is invalid")
        start = item.get("start_ms")
        end = item.get("end_ms")
        require(_is_integer(start) and _is_integer(end) and 0 <= start <= end, f"{prefix} time range is invalid")
        frame = item.get("frame")
        require(frame is None or (_is_integer(frame) and frame >= 0), f"{prefix}.frame is invalid")
        require(_non_empty_string(item.get("method")), f"{prefix}.method is empty")
        require(item.get("observed_inferred_planned") in PROVENANCE_STATES, f"{prefix} provenance is invalid")
        confidence = item.get("confidence")
        require(_is_number(confidence) and 0 <= confidence <= 1, f"{prefix}.confidence is invalid")
        state_id = item.get("state_id")
        require(state_id is None or _non_empty_string(state_id), f"{prefix}.state_id is invalid")


def _validate_common_factor(
    value: Any,
    label: str,
    *,
    evidence_field: str = "evidence",
    require_carrier: bool = False,
) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    criticality = value.get("criticality")
    require(criticality in CRITICALITIES, f"{label}.criticality is invalid")
    require(
        value.get("observed_inferred_planned") in PROVENANCE_STATES,
        f"{label}.provenance is invalid",
    )
    confidence = value.get("confidence")
    require(_is_number(confidence) and 0 <= confidence <= 1, f"{label}.confidence is invalid")
    threshold = value.get("blocker_threshold")
    require(_is_number(threshold) and 0 <= threshold <= 1, f"{label}.blocker_threshold is invalid")
    if criticality == "H" and confidence < threshold:
        raise ValueError(f"{label} high-criticality confidence is below blocker threshold")
    uncertainty = value.get("uncertainty")
    require(
        isinstance(uncertainty, list) and all(_non_empty_string(item) for item in uncertainty),
        f"{label}.uncertainty is invalid",
    )
    evidence = value.get(evidence_field)
    if criticality == "H" and (not isinstance(evidence, list) or not evidence):
        raise ValueError(f"{label} high-criticality factor requires evidence")
    _validate_evidence(evidence, f"{label}.{evidence_field}", allow_empty=criticality != "H")
    if require_carrier:
        carrier = value.get("carrier")
        if criticality == "H" and not _non_empty_string(carrier):
            raise ValueError(f"{label} high-criticality factor requires a carrier")
        require(carrier in CARRIERS, f"{label}.carrier is invalid")


def _validate_legacy_weights(weights: Any) -> dict[str, int]:
    require(isinstance(weights, dict), "legacy_intent_weights must be an object")
    require(set(weights) == set(LEGACY_INTENT_KEYS), "legacy_intent_weights must contain the exact legacy nine-key set")
    for key in LEGACY_INTENT_KEYS:
        require(_is_integer(weights[key]) and weights[key] >= 0, f"legacy intent weight {key} must be a non-negative integer")
    require(sum(weights.values()) == 100, "legacy intent weights must total 100")
    return {key: weights[key] for key in LEGACY_INTENT_KEYS}


def _validate_intent_graph(value: Any, legacy_weights: dict[str, int]) -> tuple[set[str], list[dict]]:
    require(isinstance(value, dict), "source_intent_graph must be an object")
    sequence = value.get("sequence")
    require(sequence == list(INTENT_SEQUENCE), "source intent sequence is invalid")
    nodes = value.get("nodes")
    require(isinstance(nodes, list) and len(nodes) == len(INTENT_SEQUENCE), "source intent graph must contain seven ordered nodes")
    require([node.get("stage") for node in nodes if isinstance(node, dict)] == list(INTENT_SEQUENCE), "source intent nodes are out of order")
    node_ids: set[str] = set()
    projected = Counter({key: 0 for key in LEGACY_INTENT_KEYS})
    for index, node in enumerate(nodes, start=1):
        label = f"source_intent_graph.nodes[{index}]"
        _validate_common_factor(node, label)
        node_id = node.get("node_id")
        require(_non_empty_string(node_id) and node_id not in node_ids, f"{label}.node_id is invalid or duplicated")
        node_ids.add(node_id)
        require(node.get("status") in {"active", "zero"}, f"{label}.status is invalid")
        cut_ids = node.get("cut_ids")
        require(isinstance(cut_ids, list) and len(cut_ids) == len(set(cut_ids)), f"{label}.cut_ids is invalid")
        require(all(_non_empty_string(cut_id) for cut_id in cut_ids), f"{label}.cut_ids is invalid")
        ranges = node.get("time_ranges")
        require(isinstance(ranges, list), f"{label}.time_ranges is invalid")
        for range_index, time_range in enumerate(ranges, start=1):
            _validate_time_range(time_range, f"{label}.time_ranges[{range_index}]")
        for field in (
            "audience_state_before",
            "audience_state_after",
            "commercial_job",
            "presentation_archetype",
            "attention_mechanism",
            "emotional_identity_function",
            "trust_objection_function",
            "cta_relationship",
        ):
            require(_non_empty_string(node.get(field)), f"{label}.{field} is empty")
        proof_mechanism = node.get("proof_mechanism")
        require(proof_mechanism is None or _non_empty_string(proof_mechanism), f"{label}.proof_mechanism is invalid")
        projection = node.get("legacy_projection")
        require(isinstance(projection, dict), f"{label}.legacy_projection must be an object")
        keys = projection.get("legacy_intent_keys")
        shares = projection.get("weight_share")
        allocation = projection.get("cut_allocation")
        require(isinstance(keys, list) and len(keys) == len(set(keys)), f"{label} legacy_intent_keys are invalid")
        require(isinstance(shares, dict), f"{label} weight_share is invalid")
        require(set(keys) == set(shares), f"{label} legacy_intent_keys do not match weight_share")
        require(set(shares).issubset(LEGACY_INTENT_KEYS), f"{label} uses an unknown legacy intent key")
        require(isinstance(allocation, dict), f"{label} cut_allocation is invalid")
        require(set(allocation).issubset(set(cut_ids)), f"{label} cut_allocation references an unknown Cut")
        for key, amount in shares.items():
            require(_is_integer(amount) and amount >= 0, f"{label} weight_share {key} is invalid")
            projected[key] += amount
        for cut_id, amount in allocation.items():
            require(_is_integer(amount) and amount >= 0, f"{label} cut allocation {cut_id} is invalid")
        require(sum(shares.values()) == sum(allocation.values()), f"{label} weight and Cut allocations differ")
        require(_non_empty_string(projection.get("projection_reason")), f"{label}.projection_reason is empty")
        if node.get("status") == "active":
            require(cut_ids and ranges and sum(shares.values()) > 0, f"{label} active node has no Cut, time, or weight")
        else:
            require(not cut_ids and not ranges and sum(shares.values()) == 0, f"{label} zero node must allocate zero weight")
            require(bool(node.get("uncertainty")), f"{label} zero node requires an uncertainty note")
    if {key: projected[key] for key in LEGACY_INTENT_KEYS} != legacy_weights:
        raise ValueError("source intent projection does not equal legacy weights; every point must be assigned exactly once")
    return node_ids, nodes


def _validate_target_graph(value: Any) -> set[str]:
    require(isinstance(value, dict), "target_value_graph must be an object")
    nodes = value.get("nodes")
    require(isinstance(nodes, list) and nodes, "target_value_graph.nodes must be non-empty")
    node_ids: set[str] = set()
    for index, node in enumerate(nodes, start=1):
        label = f"target_value_graph.nodes[{index}]"
        _validate_common_factor(node, label)
        node_id = node.get("node_id")
        require(_non_empty_string(node_id) and node_id not in node_ids, f"{label}.node_id is invalid or duplicated")
        node_ids.add(node_id)
        refs = node.get("target_truth_refs")
        require(isinstance(refs, list) and refs and all(_non_empty_string(ref) for ref in refs), f"{label}.target_truth_refs is invalid")
        for field in (
            "feature",
            "benefit",
            "audience_relevance",
            "objection_resolved",
            "trust_signal",
            "cta",
        ):
            require(_non_empty_string(node.get(field)), f"{label}.{field} is empty")
        mechanism = node.get("mechanism")
        require(mechanism is None or _non_empty_string(mechanism), f"{label}.mechanism is invalid")
        proof = node.get("proof")
        require(isinstance(proof, list) and proof and all(_non_empty_string(item) for item in proof), f"{label}.proof is invalid")
    return node_ids


def _validate_migrations(value: Any, source_ids: set[str], target_ids: set[str]) -> None:
    require(isinstance(value, list), "migration_edges must be an array")
    edge_ids: set[str] = set()
    mapped_source_ids: list[str] = []
    for index, edge in enumerate(value, start=1):
        label = f"migration_edges[{index}]"
        _validate_common_factor(edge, label)
        edge_id = edge.get("edge_id")
        require(_non_empty_string(edge_id) and edge_id not in edge_ids, f"{label}.edge_id is invalid or duplicated")
        edge_ids.add(edge_id)
        source_id = edge.get("source_node_id")
        target_id = edge.get("target_node_id")
        require(source_id in source_ids, f"{label}.source_node_id is unknown")
        mapped_source_ids.append(source_id)
        mapping = edge.get("mapping")
        proof_equivalence = edge.get("proof_equivalence")
        route = edge.get("route")
        fidelity = edge.get("fidelity_level")
        require(mapping in MIGRATION_TYPES, f"{label}.mapping is invalid")
        require(proof_equivalence in PROOF_EQUIVALENCE, f"{label}.proof_equivalence is invalid")
        require(route in ROUTES, f"{label}.route is invalid")
        require(fidelity in {0, 1, 2}, f"{label}.fidelity_level is invalid")
        invariant_ids = edge.get("invariant_ids")
        require(isinstance(invariant_ids, list) and len(invariant_ids) == len(set(invariant_ids)), f"{label}.invariant_ids is invalid")
        require(all(_non_empty_string(item) for item in invariant_ids), f"{label}.invariant_ids is invalid")
        require(_non_empty_string(edge.get("invariant_summary")), f"{label}.invariant_summary is empty")
        changed_form = edge.get("changed_form")
        require(changed_form is None or _non_empty_string(changed_form), f"{label}.changed_form is invalid")
        if mapping == "exact":
            require(target_id in target_ids, f"{label} exact mapping needs a target node")
            require(proof_equivalence == "exact", f"{label} exact mapping needs exact proof equivalence")
            require(fidelity in {0, 1}, f"{label} exact mapping cannot use Level 2")
            require(route in {"KEEP", "REPLACE", "COMPOSITE"}, f"{label} exact mapping route is invalid")
        elif mapping == "functional":
            require(target_id in target_ids, f"{label} functional mapping needs a target node")
            require(_non_empty_string(changed_form), f"{label} functional mapping must state changed_form")
            if proof_equivalence == "analogous":
                require(
                    fidelity == 2 and route == "REINTERPRET",
                    f"{label} analogous functional proof requires Level 2 REINTERPRET",
                )
            else:
                require(proof_equivalence == "exact" and fidelity == 1, f"{label} functional Level 1 needs equivalent proof")
        elif mapping == "intent_only":
            require(target_id in target_ids, f"{label} intent_only mapping needs a target node")
            require(_non_empty_string(changed_form), f"{label} intent_only mapping must state changed_form")
            require(fidelity == 2 and route == "REINTERPRET", f"{label} intent_only must use Level 2 REINTERPRET")
        else:
            require(target_id is None, f"{label} unsupported mapping cannot bind a target node")
            require(proof_equivalence == "none", f"{label} unsupported mapping must use proof_equivalence none")
            require(route == "REMOVE", f"{label} unsupported mapping must use REMOVE")
    require(len(mapped_source_ids) == len(set(mapped_source_ids)), "a source intent node has more than one migration edge")
    require(set(mapped_source_ids) == source_ids, "every source intent node must have exactly one migration edge")


def _validate_claims(value: Any) -> None:
    require(isinstance(value, list) and value, "claim_atoms must be non-empty")
    claim_ids: set[str] = set()
    disposition_projection = {
        "exact": "supported",
        "partial": "reinterpreted",
        "prohibited": "unsupported",
    }
    for index, claim in enumerate(value, start=1):
        label = f"claim_atoms[{index}]"
        require(isinstance(claim, dict), f"{label} must be an object")
        claim_id = claim.get("claim_id")
        require(_non_empty_string(claim_id) and claim_id not in claim_ids, f"{label}.claim_id is invalid or duplicated")
        claim_ids.add(claim_id)
        require(claim.get("claim_class") in CLAIM_CLASSES, f"{label}.claim_class is invalid")
        require(claim.get("claim_risk_class") in CLAIM_RISK_CLASSES, f"{label}.claim_risk_class is invalid")
        expression = claim.get("source_expression")
        require(isinstance(expression, dict), f"{label}.source_expression must be an object")
        cut_ids = expression.get("cut_ids")
        require(isinstance(cut_ids, list) and cut_ids and all(_non_empty_string(item) for item in cut_ids), f"{label}.source_expression.cut_ids is invalid")
        _validate_time_range(expression.get("time_range"), f"{label}.source_expression.time_range")
        modalities = expression.get("modalities")
        require(isinstance(modalities, list) and modalities and all(_non_empty_string(item) for item in modalities), f"{label}.source_expression.modalities is invalid")
        _validate_evidence(claim.get("source_evidence"), f"{label}.source_evidence")
        _validate_evidence(claim.get("target_evidence"), f"{label}.target_evidence", allow_empty=True)
        criticality = claim.get("criticality")
        require(criticality in CRITICALITIES, f"{label}.criticality is invalid")
        require(
            claim.get("observed_inferred_planned") in PROVENANCE_STATES,
            f"{label}.provenance is invalid",
        )
        uncertainty = claim.get("uncertainty")
        require(
            isinstance(uncertainty, list)
            and all(_non_empty_string(item) for item in uncertainty),
            f"{label}.uncertainty is invalid",
        )
        confidence = claim.get("confidence")
        threshold = claim.get("blocker_threshold")
        require(_is_number(confidence) and 0 <= confidence <= 1, f"{label}.confidence is invalid")
        require(_is_number(threshold) and 0 <= threshold <= 1, f"{label}.blocker_threshold is invalid")
        if criticality == "H" and confidence < threshold:
            raise ValueError(f"{label} high-criticality confidence is below blocker threshold")
        carrier = claim.get("carrier")
        if criticality == "H" and not _non_empty_string(carrier):
            raise ValueError(f"{label} high-criticality factor requires a carrier")
        require(carrier in CARRIERS, f"{label}.carrier is invalid")
        status = claim.get("support_status")
        disposition = claim.get("analysis_disposition")
        require(status in SUPPORT_STATUSES, f"{label}.support_status is invalid")
        require(disposition in DISPOSITIONS, f"{label}.analysis_disposition is invalid")
        expected_status = disposition_projection[disposition]
        require(status == expected_status, f"{label} disposition {disposition} must project to {expected_status}")
        route = claim.get("route")
        require(route in ROUTES, f"{label}.route is invalid")
        route_by_layer = claim.get("route_by_layer")
        require(isinstance(route_by_layer, dict) and route_by_layer, f"{label}.route_by_layer is invalid")
        require(all(_non_empty_string(key) and route_value in ROUTES for key, route_value in route_by_layer.items()), f"{label}.route_by_layer contains an invalid route")
        require(claim.get("proof_substitution") in PROOF_EQUIVALENCE, f"{label}.proof_substitution is invalid")
        refs = claim.get("target_truth_refs")
        require(isinstance(refs, list) and all(_non_empty_string(ref) for ref in refs), f"{label}.target_truth_refs is invalid")
        for field in (
            "feature",
            "benefit",
            "audience_relevance",
            "objection_resolved",
            "trust_signal",
            "cta",
        ):
            require(isinstance(claim.get(field), str), f"{label}.{field} must be a string")
        mechanism = claim.get("mechanism")
        require(mechanism is None or isinstance(mechanism, str), f"{label}.mechanism is invalid")
        proof = claim.get("proof")
        require(isinstance(proof, list), f"{label}.proof must be an array")
        risk_flags = claim.get("risk_flags")
        require(isinstance(risk_flags, list) and all(_non_empty_string(item) for item in risk_flags), f"{label}.risk_flags is invalid")
        if status == "unsupported":
            require(route == "REMOVE", f"{label} unsupported claim must use REMOVE")
            require(not proof and not claim.get("target_evidence"), f"{label} unsupported claim cannot carry target proof")
            require(claim.get("proof_substitution") == "none", f"{label} unsupported claim must use no proof substitution")
            require(carrier == "route_excluded", f"{label} unsupported claim carrier must be route_excluded")
        else:
            require(route not in {"REMOVE", "OPAQUE_SPLICE"}, f"{label} supported claim route is invalid")
            require(refs and proof and claim.get("target_evidence"), f"{label} supported claim requires target evidence and proof")
            if criticality == "H" and not claim.get("target_evidence"):
                raise ValueError(f"{label} high-criticality claim requires target proof evidence")


def _validate_affordances(value: Any) -> None:
    require(isinstance(value, list), "affordance_ledger must be an array")
    seen: set[str] = set()
    for index, affordance in enumerate(value, start=1):
        label = f"affordance_ledger[{index}]"
        _validate_common_factor(affordance, label, require_carrier=True)
        affordance_id = affordance.get("affordance_id")
        require(_non_empty_string(affordance_id) and affordance_id not in seen, f"{label}.affordance_id is invalid or duplicated")
        seen.add(affordance_id)
        require(affordance.get("target_kind") in TARGET_KINDS, f"{label}.target_kind is invalid")
        for field in (
            "source_primitive_id",
            "source_commercial_function",
            "target_affordance",
            "target_proof_event",
            "match_reason",
        ):
            require(_non_empty_string(affordance.get(field)), f"{label}.{field} is empty")
        source_states = affordance.get("source_state_sequence")
        require(isinstance(source_states, list) and source_states and all(_non_empty_string(item) for item in source_states), f"{label}.source_state_sequence is invalid")
        target_states = affordance.get("target_state_sequence")
        require(isinstance(target_states, list) and target_states, f"{label}.target_state_sequence is invalid")
        refs = affordance.get("target_truth_refs")
        require(isinstance(refs, list) and refs and all(_non_empty_string(ref) for ref in refs), f"{label}.target_truth_refs is invalid")
        for key in ("proof_event_ids", "audio_event_ids"):
            entries = affordance.get(key)
            require(isinstance(entries, list) and all(_non_empty_string(item) for item in entries), f"{label}.{key} is invalid")
        for key in ("physical_feasibility", "temporal_feasibility", "evidence_feasibility"):
            require(affordance.get(key) in FEASIBILITY, f"{label}.{key} is invalid")
        require(affordance.get("match_level") in MIGRATION_TYPES, f"{label}.match_level is invalid")
        require(affordance.get("fidelity_level") in {0, 1, 2}, f"{label}.fidelity_level is invalid")
        require(affordance.get("route") in ROUTES, f"{label}.route is invalid")
        require(affordance.get("fallback_route") in ROUTES, f"{label}.fallback_route is invalid")
        evidence_by_id = {item["evidence_id"]: item for item in affordance["evidence"]}
        state_ids: set[str] = set()
        for state_index, state in enumerate(target_states, start=1):
            state_label = f"{label}.target_state_sequence[{state_index}]"
            require(isinstance(state, dict), f"{state_label} must be an object")
            state_id = state.get("state_id")
            require(_non_empty_string(state_id) and state_id not in state_ids, f"{state_label}.state_id is invalid or duplicated")
            state_ids.add(state_id)
            state_refs = state.get("evidence_refs")
            require(isinstance(state_refs, list) and all(_non_empty_string(ref) for ref in state_refs), f"{state_label}.evidence_refs is invalid")
            if affordance.get("target_kind") == "app" and not state_refs:
                raise ValueError(f"{label} screenshot evidence cannot prove unseen UI state {state_id}")
            for evidence_ref in state_refs:
                require(evidence_ref in evidence_by_id, f"{state_label} references unknown evidence {evidence_ref}")
                evidence_item = evidence_by_id[evidence_ref]
                if affordance.get("target_kind") == "app":
                    matches_state = evidence_item.get("state_id") == state_id
                    proves_operation = evidence_item.get("kind") == "operation"
                    if not matches_state and not proves_operation:
                        raise ValueError(f"{label} screenshot evidence cannot prove unseen UI state {state_id}")


def _validate_layers(value: Any) -> None:
    require(isinstance(value, list) and value, "layer_ledger must be non-empty")
    cuts: set[str] = set()
    factors: set[str] = set()
    compatible_carriers = {
        "KEEP": {"source_interval", "audio_mix"},
        "REPLACE": {"deterministic_composite", "seedance_generation", "audio_mix"},
        "COMPOSITE": {"deterministic_composite", "audio_mix"},
        "REMOVE": {"deterministic_composite", "route_excluded", "audio_mix"},
        "REINTERPRET": {"deterministic_composite", "seedance_generation", "audio_mix"},
        "OPAQUE_SPLICE": {"opaque_media"},
    }
    for cut_index, cut in enumerate(value, start=1):
        label = f"layer_ledger[{cut_index}]"
        require(isinstance(cut, dict), f"{label} must be an object")
        cut_id = cut.get("cut_id")
        require(_non_empty_string(cut_id) and cut_id not in cuts, f"{label}.cut_id is invalid or duplicated")
        cuts.add(cut_id)
        layers = cut.get("layers")
        require(isinstance(layers, list) and layers, f"{label}.layers must be non-empty")
        has_opaque = False
        for layer_index, layer in enumerate(layers, start=1):
            layer_label = f"{label}.layers[{layer_index}]"
            _validate_common_factor(layer, layer_label, require_carrier=True)
            factor_id = layer.get("factor_id")
            require(_non_empty_string(factor_id) and factor_id not in factors, f"{layer_label}.factor_id is invalid or duplicated")
            factors.add(factor_id)
            require(_non_empty_string(layer.get("layer_id")), f"{layer_label}.layer_id is empty")
            route = layer.get("route")
            carrier = layer.get("carrier")
            fidelity = layer.get("fidelity_level")
            require(route in ROUTES, f"{layer_label}.route is invalid")
            require(fidelity in {0, 1, 2}, f"{layer_label}.fidelity_level is invalid")
            require(carrier in compatible_carriers[route], f"{layer_label} carrier is incompatible with route {route}")
            require(isinstance(layer.get("changes_output"), bool), f"{layer_label}.changes_output must be boolean")
            if route == "REINTERPRET":
                require(fidelity == 2, f"{layer_label} REINTERPRET requires fidelity Level 2")
            if route == "OPAQUE_SPLICE":
                has_opaque = True
        if has_opaque:
            require(all(layer.get("route") == "OPAQUE_SPLICE" for layer in layers), f"{label} opaque interval cannot mix semantic layers")


def _validate_route_exclusions(value: Any) -> None:
    require(isinstance(value, list), "route_exclusions must be an array")
    allowed_keys = {"region_id", "reason", "technical_evidence"}
    seen: set[str] = set()
    for index, exclusion in enumerate(value, start=1):
        label = f"route_exclusions[{index}]"
        require(isinstance(exclusion, dict), f"{label} must be an object")
        if set(exclusion) - allowed_keys:
            raise ValueError(f"{label} may carry technical metadata only")
        region_id = exclusion.get("region_id")
        require(
            _non_empty_string(region_id) and region_id not in seen,
            f"{label}.region_id is invalid or duplicated",
        )
        seen.add(region_id)
        require(_non_empty_string(exclusion.get("reason")), f"{label}.reason is empty")
        _validate_evidence(
            exclusion.get("technical_evidence", []),
            f"{label}.technical_evidence",
            allow_empty=True,
        )


def validate_analysis(value: dict) -> None:
    require(isinstance(value, dict), "analysis must be an object")
    require(value.get("contract") == CONTRACT, "invalid high-fidelity analysis contract")
    require(value.get("contract_version") == CONTRACT_VERSION, "unsupported high-fidelity analysis contract_version")
    require(value.get("profile") == PROFILE, "invalid high-fidelity profile")
    parent_digests = value.get("parent_digests")
    require(isinstance(parent_digests, dict) and parent_digests, "parent_digests must be non-empty")
    for name, digest in parent_digests.items():
        require(_non_empty_string(name), "parent digest name is empty")
        _validate_sha256(digest, f"parent_digests.{name}")
    legacy_weights = _validate_legacy_weights(value.get("legacy_intent_weights"))
    source_ids, _ = _validate_intent_graph(value.get("source_intent_graph"), legacy_weights)
    target_ids = _validate_target_graph(value.get("target_value_graph"))
    _validate_migrations(value.get("migration_edges"), source_ids, target_ids)
    _validate_claims(value.get("claim_atoms"))
    _validate_affordances(value.get("affordance_ledger"))
    _validate_layers(value.get("layer_ledger"))
    _validate_route_exclusions(value.get("route_exclusions"))


def project_legacy_intent(value: dict) -> dict:
    validate_analysis(value)
    rows = []
    for node in value["source_intent_graph"]["nodes"]:
        projection = node["legacy_projection"]
        rows.append(
            {
                "node_id": node["node_id"],
                "stage": node["stage"],
                "cut_ids": list(node["cut_ids"]),
                "weights": {key: projection["weight_share"][key] for key in projection["legacy_intent_keys"]},
                "cut_allocation": dict(projection["cut_allocation"]),
                "projection_reason": projection["projection_reason"],
            }
        )
    return {
        "weights": {key: value["legacy_intent_weights"][key] for key in LEGACY_INTENT_KEYS},
        "cut_allocation": rows,
    }


def project_selling_point_mapping(value: dict) -> list[dict]:
    validate_analysis(value)
    rows: list[dict] = []
    for claim in value["claim_atoms"]:
        script_eligible = claim["support_status"] in {"supported", "reinterpreted"} and claim["route"] != "REMOVE"
        rows.append(
            {
                "claim_id": claim["claim_id"],
                "source_claim": dict(claim["source_expression"]),
                "status": claim["support_status"],
                "feature": claim["feature"],
                "mechanism": claim["mechanism"],
                "benefit": claim["benefit"],
                "proof": list(claim["proof"]),
                "cta": claim["cta"],
                "route": claim["route"],
                "confidence": claim["confidence"],
                "criticality": claim["criticality"],
                "script_eligible": script_eligible,
            }
        )
    return rows


def project_script_claims(value: dict) -> list[dict]:
    return [row for row in project_selling_point_mapping(value) if row["script_eligible"]]


def aggregate_layer_ledger(layer_ledger: Iterable[dict]) -> list[dict]:
    output: list[dict] = []
    for cut in layer_ledger:
        layers = cut["layers"]
        changes_output = any(layer["changes_output"] for layer in layers)
        carriers = {layer["carrier"] for layer in layers}
        if "opaque_media" in carriers:
            media_origin = "opaque"
            assembly_policy = "splice_opaque_interval"
        elif "seedance_generation" in carriers:
            media_origin = "generated"
            assembly_policy = "generate_region"
        elif changes_output:
            media_origin = "composite"
            assembly_policy = "compose_region"
        else:
            media_origin = "source_interval"
            assembly_policy = "splice_source_interval"
        output.append(
            {
                "cut_id": cut["cut_id"],
                "media_origin": media_origin,
                "assembly_policy": assembly_policy,
                "changes_output": changes_output,
            }
        )
    return output


def project_factor_sources(value: dict) -> list[dict]:
    """Freeze the upstream source of every high-criticality layer factor.

    Invocation A may choose the final prompt/reference/payload/post-production
    carrier, but it must start from this exact factor-ID set rather than a
    caller-invented list.  The projection deliberately carries source pointers
    and evidence while leaving the final carrier decision to the existing
    Seedance executability pass.
    """

    validate_analysis(value)
    rows: list[dict] = []
    for cut in value["layer_ledger"]:
        cut_id = str(cut["cut_id"])
        for layer in cut["layers"]:
            if layer["criticality"] != "H":
                continue
            factor_id = str(layer["factor_id"])
            layer_id = str(layer["layer_id"])
            rows.append(
                {
                    "factor_id": factor_id,
                    "cut_id": cut_id,
                    "layer_id": layer_id,
                    "source_pointer": f"/layer_ledger/{cut_id}/{layer_id}/{factor_id}",
                    "upstream_carrier": layer["carrier"],
                    "route": layer["route"],
                    "fidelity_level": layer["fidelity_level"],
                    "criticality": layer["criticality"],
                    "evidence": [dict(item) for item in layer["evidence"]],
                }
            )
    return sorted(rows, key=lambda row: row["factor_id"])


def build_projection(value: dict) -> dict:
    validate_analysis(value)
    factor_sources = project_factor_sources(value)
    return {
        "legacy_intent": project_legacy_intent(value),
        "selling_point_mapping": project_selling_point_mapping(value),
        "script_claims": project_script_claims(value),
        "cut_aggregation": aggregate_layer_ledger(value["layer_ledger"]),
        "required_factor_ids": [row["factor_id"] for row in factor_sources],
        "factor_sources": factor_sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and project high-fidelity analysis sidecars.")
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--projection-output", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.json_file.read_text(encoding="utf-8"))
        projection = build_projection(value)
        if args.projection_output:
            args.projection_output.parent.mkdir(parents=True, exist_ok=True)
            args.projection_output.write_text(
                json.dumps(projection, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        print("VALID")
        return 0
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
