"""Fail-closed audio routing checks for opaque timeline replacements."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .errors import ReplicationError


_OPAQUE_REGION_TYPES = {
    "opaque_ui_demo",
    "generated_ui_demo",
    "generated_ui",
    "excluded_app_end_card",
    "ui_demo",
    "tail_card",
    "opaque_tail",
}
_AUDIO_POLICIES = {
    "source_audio_keep",
    "generated_audio_contract",
    "opaque_audio_keep",
    "evidence_bound_mix",
    "silence_allowed",
}
_OUTPUT_LANGUAGES = {"en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"}
_SPEECH_EVENT_KINDS = {
    "dialog",
    "dialogue",
    "narration",
    "speech",
    "spoken_word",
    "voiceover",
}
_EXPLICIT_BLOCKED_STATUSES = {
    "BLOCKED_AUDIO_LAYER_DECISION",
    "AUDIO_LAYER_POLICY_REQUIRED",
}


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _audio_contract(context: Any) -> Mapping[str, Any] | None:
    direct = _mapping(getattr(context, "audio_contract", None))
    if direct is not None:
        return _mapping(direct.get("audio_contract")) or direct

    stage_outputs = _mapping(getattr(context, "stage_outputs", None))
    if stage_outputs is None:
        return None
    for stage_name in ("analyze_dynamics", "analyze_reference_video"):
        stage = _mapping(stage_outputs.get(stage_name))
        if stage is None:
            continue
        value = _mapping(stage.get("audio_contract"))
        if value is not None:
            return _mapping(value.get("audio_contract")) or value
        analysis = _mapping(stage.get("source_dynamics_analysis"))
        if analysis is not None:
            value = _mapping(analysis.get("audio_contract"))
            if value is not None:
                return value
    return None


def _seconds_to_us(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(round(float(value) * 1_000_000))
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _milliseconds_to_us(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(round(float(value) * 1_000))
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _microseconds(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _time_window(value: Mapping[str, Any]) -> tuple[int, int] | None:
    for start_key, end_key, converter in (
        ("start_us", "end_us", _microseconds),
        ("source_start_us", "source_end_us", _microseconds),
        ("start_ms", "end_ms", _milliseconds_to_us),
        ("source_start", "source_end", _seconds_to_us),
        ("start", "end", _seconds_to_us),
    ):
        start = converter(value.get(start_key))
        end = converter(value.get(end_key))
        if start is not None and end is not None and end > start:
            return start, end
    return None


def _speech_windows(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()

    raw_segments = contract.get("segments")
    if isinstance(raw_segments, Sequence) and not isinstance(
        raw_segments, (str, bytes, bytearray)
    ):
        for index, item in enumerate(raw_segments, start=1):
            if not isinstance(item, Mapping):
                continue
            window = _time_window(item)
            if window is None:
                continue
            event_id = str(item.get("segment_id") or f"segment-{index}")
            key = (window[0], window[1], event_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "event_id": event_id,
                    "start_us": window[0],
                    "end_us": window[1],
                }
            )

    for collection_name in ("events", "audio_events", "source_events"):
        values = contract.get(collection_name)
        if not isinstance(values, Sequence) or isinstance(
            values, (str, bytes, bytearray)
        ):
            continue
        for index, item in enumerate(values, start=1):
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("kind") or "").strip().lower().replace("-", "_")
            if kind not in _SPEECH_EVENT_KINDS:
                continue
            window = _time_window(item)
            if window is None:
                continue
            event_id = str(
                item.get("event_id")
                or item.get("event")
                or f"{collection_name}-{index}"
            )
            key = (window[0], window[1], event_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "event_id": event_id,
                    "start_us": window[0],
                    "end_us": window[1],
                }
            )
    return result


def _opaque_regions(regions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(regions, start=1):
        kind = str(item.get("region_type") or item.get("kind") or "").strip().lower()
        if kind not in _OPAQUE_REGION_TYPES:
            continue
        origin = str(item.get("media_origin") or "user_upload").strip().lower()
        assembly_policy = str(item.get("assembly_policy") or "").strip().lower()
        if origin in {"source_interval", "source_video"} or "omit" in assembly_policy:
            continue
        window = _time_window(item)
        if window is None:
            continue
        result.append(
            {
                "region_id": str(item.get("region_id") or f"region-{index}"),
                "region_type": kind,
                "start_us": window[0],
                "end_us": window[1],
                "audio_policy": str(
                    item.get("audio_policy") or "opaque_audio_keep"
                ).strip().lower(),
                "has_audio": item.get("has_audio"),
                "mixer_receipt": item.get("mixer_receipt"),
            }
        )
    return result


def _sha_field(value: Any, field: str) -> str:
    digest = str(value or "").lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ReplicationError(
            "AUDIO_LAYER_POLICY_REQUIRED",
            f"AUDIO_LAYER_POLICY_REQUIRED: mixer receipt {field} is invalid",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    return digest


def _validate_mixer_receipt(
    receipt: Any,
    *,
    final_output_sha256: str | None,
) -> str:
    if not isinstance(receipt, Mapping):
        raise ReplicationError(
            "AUDIO_LAYER_POLICY_REQUIRED",
            "AUDIO_LAYER_POLICY_REQUIRED: evidence_bound_mix requires a mixer receipt",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    for field in (
        "source_wav_sha256",
        "opaque_wav_sha256",
        "request_sha256",
        "output_wav_sha256",
        "final_output_sha256",
    ):
        _sha_field(receipt.get(field), field)
    if (
        final_output_sha256
        and str(receipt.get("final_output_sha256") or "").lower()
        != final_output_sha256.lower()
    ):
        raise ReplicationError(
            "AUDIO_LAYER_POLICY_REQUIRED",
            "AUDIO_LAYER_POLICY_REQUIRED: mixer receipt is stale for the final output",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    duck_curve = receipt.get("duck_curve")
    if not isinstance(duck_curve, list) or not duck_curve:
        raise ReplicationError(
            "AUDIO_LAYER_POLICY_REQUIRED",
            "AUDIO_LAYER_POLICY_REQUIRED: mixer receipt requires a duck curve",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    return _canonical_sha256(receipt)


def _route_regions(
    regions: Sequence[Mapping[str, Any]],
    *,
    output_language: str | None,
    final_output_sha256: str | None,
    defer_evidence_bound_mix_receipts: bool,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(regions, start=1):
        window = _time_window(item)
        if window is None:
            continue
        region_id = str(item.get("region_id") or f"region-{index}")
        kind = str(item.get("region_type") or item.get("kind") or "").lower()
        origin = str(item.get("media_origin") or "generated_media").lower()
        declared = item.get("audio_policy")
        if declared is None:
            if origin in {"source_interval", "source_video"}:
                policy = "source_audio_keep"
            elif kind in _OPAQUE_REGION_TYPES:
                policy = "opaque_audio_keep"
            elif item.get("generate_audio") is True:
                policy = "generated_audio_contract"
            else:
                policy = "source_audio_keep"
        else:
            policy = str(declared).strip().lower()
        if policy not in _AUDIO_POLICIES:
            raise ReplicationError(
                "AUDIO_LAYER_POLICY_REQUIRED",
                f"AUDIO_LAYER_POLICY_REQUIRED: region {region_id} has unsupported audio policy",
                category="timeline",
                user_action_required=True,
                http_status=422,
            )
        row = {
            "region_id": region_id,
            "start_us": window[0],
            "end_us": window[1],
            "audio_policy": policy,
        }
        if policy == "opaque_audio_keep" and item.get("has_audio") is False:
            raise ReplicationError(
                "AUDIO_LAYER_POLICY_REQUIRED",
                "AUDIO_LAYER_POLICY_REQUIRED: opaque_audio_keep requires target audio",
                category="timeline",
                user_action_required=True,
                http_status=422,
            )
        if policy == "generated_audio_contract":
            language = item.get("output_language", output_language)
            if language not in _OUTPUT_LANGUAGES or language != output_language:
                raise ReplicationError(
                    "AUDIO_LAYER_POLICY_REQUIRED",
                    "AUDIO_LAYER_POLICY_REQUIRED: generated audio output_language is invalid",
                    category="timeline",
                    user_action_required=True,
                    http_status=422,
                )
            windows = item.get("exact_line_windows")
            if not isinstance(windows, list) or not windows:
                raise ReplicationError(
                    "AUDIO_LAYER_POLICY_REQUIRED",
                    "AUDIO_LAYER_POLICY_REQUIRED: generated audio requires exact-line windows",
                    category="timeline",
                    user_action_required=True,
                    http_status=422,
                )
            row["output_language"] = language
            row["exact_line_windows"] = [dict(value) for value in windows if isinstance(value, Mapping)]
        if policy == "evidence_bound_mix":
            mixer_receipt = item.get("mixer_receipt")
            if mixer_receipt is None and defer_evidence_bound_mix_receipts:
                row["mixer_receipt_status"] = "pending_renderer_receipt"
            else:
                row["mixer_receipt_sha256"] = _validate_mixer_receipt(
                    mixer_receipt,
                    final_output_sha256=final_output_sha256,
                )
                assert isinstance(mixer_receipt, Mapping)
                row["mixer_receipt_status"] = "verified_prebound_receipt"
                row["mixer_final_output_sha256"] = str(
                    mixer_receipt.get("final_output_sha256") or ""
                ).lower()
        result.append(row)
    return result


def _overlaps(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return max(int(left["start_us"]), int(right["start_us"])) < min(
        int(left["end_us"]), int(right["end_us"])
    )


def validate_audio_route_contract(
    *,
    context: Any,
    regions: Sequence[Mapping[str, Any]],
    active_high_fidelity: bool,
    defer_evidence_bound_mix_receipts: bool = False,
) -> dict[str, Any] | None:
    """Reject source speech that an opaque replacement would silently discard.

    The bundled compositor has no evidence-bound source-voiceover/target-audio
    mixer.  Active high-fidelity runs therefore fail closed when a frozen
    source speech window overlaps supplied opaque UI or App-tail media.  Legacy
    runs retain their compatibility behavior unless the upstream audio contract
    already carries an explicit blocked routing decision.
    """

    opaque = _opaque_regions(regions)
    contract = _audio_contract(context)
    if contract is None:
        if active_high_fidelity and opaque:
            raise ReplicationError(
                "AUDIO_CONTRACT_REQUIRED",
                "AUDIO_CONTRACT_REQUIRED: active replacement assembly is missing "
                "the canonical source audio contract",
                category="timeline",
                user_action_required=True,
                details={
                    "opaque_region_ids": [item["region_id"] for item in opaque],
                },
                http_status=422,
            )
        return None
    status = str(contract.get("status") or "").strip().upper()
    explicit_block = status in _EXPLICIT_BLOCKED_STATUSES or bool(
        contract.get("source_voiceover_crosses_opaque_ui")
        or contract.get("source_voiceover_crosses_tail")
    )
    # Preserve an upstream fail-closed decision even when a partial or
    # malformed timeline omitted the opaque-region rows that motivated it.
    # Hiding that decision behind "not opaque" would let assembly proceed
    # without the evidence needed to resolve the audio layer.
    if explicit_block:
        raise ReplicationError(
            "AUDIO_LAYER_POLICY_REQUIRED",
            "AUDIO_LAYER_POLICY_REQUIRED: upstream analysis marked source "
            "speech/opaque audio routing as blocked",
            category="timeline",
            user_action_required=True,
            details={
                "audio_contract_sha256": _canonical_sha256(contract),
                "contract_status": status or None,
                "crossings": [],
                "opaque_region_ids": [item["region_id"] for item in opaque],
                "explicit_block": True,
            },
            http_status=422,
        )
    if not active_high_fidelity and not explicit_block:
        return None

    speech = _speech_windows(contract)
    output_language = getattr(context, "output_language", None) or contract.get(
        "output_language"
    )
    routes = _route_regions(
        regions,
        output_language=output_language,
        final_output_sha256=getattr(context, "final_output_sha256", None),
        defer_evidence_bound_mix_receipts=defer_evidence_bound_mix_receipts,
    )
    route_by_id = {item["region_id"]: item for item in routes}
    for region in opaque:
        route = route_by_id.get(region["region_id"])
        if not route or route.get("audio_policy") != "evidence_bound_mix":
            continue
        matched = sorted(
            (dict(event) for event in speech if _overlaps(event, region)),
            key=lambda item: (
                int(item["start_us"]),
                int(item["end_us"]),
                str(item["event_id"]),
            ),
        )
        if not matched:
            raise ReplicationError(
                "AUDIO_LAYER_POLICY_REQUIRED",
                "AUDIO_LAYER_POLICY_REQUIRED: evidence_bound_mix requires frozen "
                "source speech windows for its opaque region",
                category="timeline",
                user_action_required=True,
                details={"region_id": region["region_id"]},
                http_status=422,
            )
        route["speech_windows"] = matched
    crossings = [
        {
            "event_id": event["event_id"],
            "region_id": region["region_id"],
            "region_type": region["region_type"],
            "audio_policy": region["audio_policy"],
        }
        for event in speech
        for region in opaque
        if _overlaps(event, region)
        and route_by_id.get(region["region_id"], {}).get("audio_policy")
        != "evidence_bound_mix"
    ]
    if explicit_block or crossings:
        raise ReplicationError(
            "AUDIO_LAYER_POLICY_REQUIRED",
            "AUDIO_LAYER_POLICY_REQUIRED: source speech overlaps supplied opaque "
            "UI/tail media, but no evidence-bound audio compositor is deployed",
            category="timeline",
            user_action_required=True,
            details={
                "audio_contract_sha256": _canonical_sha256(contract),
                "contract_status": status or None,
                "crossings": crossings,
                "opaque_region_ids": [item["region_id"] for item in opaque],
            },
            http_status=422,
        )

    return {
        "schema_version": "audio-route-guard/v2",
        "status": (
            "pending_evidence_bound_mix"
            if any(
                item.get("mixer_receipt_status") == "pending_renderer_receipt"
                for item in routes
            )
            else "passed_no_unsupported_crossing"
        ),
        "audio_contract_sha256": _canonical_sha256(contract),
        "speech_event_count": len(speech),
        "opaque_region_count": len(opaque),
        "crossing_count": 0,
        "regions": routes,
    }


__all__ = ["validate_audio_route_contract"]
