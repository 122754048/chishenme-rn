"""Canonical source-analysis envelope used by the high-fidelity A/B bridge.

The dynamics and ASR capability ports intentionally return provider-neutral
sidecars.  They are not interchangeable with the existing
``high-fidelity-analysis`` contract (which owns intent, claims, affordances,
and layer routes).  This module is the small immutable join point between the
two contracts.  It is deliberately a pure JSON helper so it can be used by a
worker, a deployment adapter, or a test without a local media dependency.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


CONTRACT = "high-fidelity-analysis-envelope"
CONTRACT_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPEECH_EVENT_KINDS = {
    "dialog",
    "dialogue",
    "narration",
    "speech",
    "spoken_word",
    "voiceover",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    """Return the stable digest used for A/B projection parity."""

    return hashlib.sha256(_canonical(value)).hexdigest()


def _without_digest(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = deepcopy(dict(value))
    result.pop(field, None)
    return result


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return deepcopy(dict(value))


def _require_sha(value: Any, field: str) -> str:
    digest = str(value or "").lower()
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return digest


def _validate_high_fidelity_analysis(value: Mapping[str, Any]) -> None:
    if value.get("contract") != "high-fidelity-analysis":
        raise ValueError(
            "canonical envelope.high_fidelity_analysis must use the high-fidelity-analysis contract"
        )
    if value.get("contract_version") != 1:
        raise ValueError("unsupported high-fidelity-analysis contract version")
    if value.get("profile") != "high_fidelity_hybrid_v1":
        raise ValueError("canonical envelope high-fidelity profile is invalid")


def _validate_dynamics(value: Mapping[str, Any]) -> None:
    if value.get("contract") != "reference-video-dynamics":
        raise ValueError(
            "canonical envelope.source_dynamics_analysis must use the reference-video-dynamics contract"
        )
    if value.get("contract_version") != 1:
        raise ValueError("unsupported reference-video-dynamics contract version")
    cuts = value.get("source_cuts")
    if not isinstance(cuts, list) or not cuts:
        raise ValueError("canonical envelope source dynamics requires non-empty source_cuts")
    try:
        duration = int(value.get("reference_duration_us"))
    except (TypeError, ValueError) as exc:
        raise ValueError("canonical envelope source dynamics duration is invalid") from exc
    if duration <= 0:
        raise ValueError("canonical envelope source dynamics duration must be positive")
    cursor = 0
    for index, cut in enumerate(cuts, start=1):
        if not isinstance(cut, Mapping):
            raise ValueError(f"source_cuts[{index}] must be an object")
        try:
            start = int(cut.get("start_us"))
            end = int(cut.get("end_us"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"source_cuts[{index}] timing is invalid") from exc
        if start != cursor or end <= start or end > duration:
            raise ValueError("source dynamics Cuts must cover frame zero through the exact decoded end")
        cursor = end
    if cursor != duration:
        raise ValueError("source dynamics Cuts do not cover the exact decoded end")


def _normalized_speech_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = "".join(
        char
        for char in text
        if not unicodedata.category(char).startswith("P") or char in {"'", "’"}
    )
    return re.sub(r"\s+", " ", text).strip()


def _validate_audio(
    value: Mapping[str, Any],
    *,
    duration_us: int,
    dynamics: Mapping[str, Any],
) -> None:
    segments = value.get("segments")
    if not isinstance(segments, list):
        raise ValueError("canonical envelope.audio_contract.segments must be an array")
    silence = value.get("meaningful_silence", value.get("silence_windows"))
    if not isinstance(silence, list):
        raise ValueError("canonical envelope.audio_contract requires silence_windows")
    source_duration = value.get("source_duration_ms")
    if source_duration is not None:
        try:
            source_duration = int(source_duration)
        except (TypeError, ValueError) as exc:
            raise ValueError("canonical envelope audio duration is invalid") from exc
        expected = duration_us // 1000
        if source_duration <= 0 or abs(source_duration - expected) > 1:
            raise ValueError("canonical envelope audio duration does not match source dynamics")

    duration_ms = max(1, duration_us // 1000)
    normalized_segments: list[tuple[int, int, str, str]] = []
    seen_ids: set[str] = set()
    cursor = 0
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, Mapping):
            raise ValueError(f"canonical envelope audio segment {index} must be an object")
        try:
            start_ms = int(segment.get("start_ms"))
            end_ms = int(segment.get("end_ms"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"canonical envelope audio segment {index} timing is invalid"
            ) from exc
        if start_ms < 0 or end_ms <= start_ms or end_ms > duration_ms:
            raise ValueError(
                f"canonical envelope audio segment {index} timing is invalid"
            )
        if start_ms < cursor:
            raise ValueError(
                "canonical envelope audio segments must be ordered and non-overlapping"
            )
        cursor = end_ms
        segment_id = str(segment.get("segment_id") or f"segment-{index}").strip()
        if not segment_id or segment_id in seen_ids:
            raise ValueError("canonical envelope audio segment IDs must be unique")
        seen_ids.add(segment_id)
        text = _normalized_speech_text(segment.get("text"))
        if not text:
            raise ValueError(
                f"canonical envelope audio segment {index} text is required"
            )
        normalized_segments.append((start_ms, end_ms, text, segment_id))

    source_speech: list[tuple[int, int, str, str]] = []
    events = dynamics.get("source_events")
    if isinstance(events, Sequence) and not isinstance(events, (str, bytes, bytearray)):
        for index, event in enumerate(events, start=1):
            if not isinstance(event, Mapping):
                continue
            kind = str(event.get("kind") or "").strip().lower().replace("-", "_")
            if kind not in _SPEECH_EVENT_KINDS:
                continue
            try:
                start_us = int(event.get("start_us"))
                end_us = int(event.get("end_us"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"canonical source speech event {index} timing is invalid"
                ) from exc
            if start_us < 0 or end_us <= start_us or end_us > duration_us:
                raise ValueError(
                    f"canonical source speech event {index} timing is invalid"
                )
            text = _normalized_speech_text(event.get("text"))
            if not text:
                raise ValueError(
                    f"canonical source speech event {index} text is required"
                )
            source_speech.append(
                (start_us // 1000, (end_us + 999) // 1000, text, str(event.get("event") or index))
            )

    for start_ms, end_ms, source_text, event_id in source_speech:
        overlaps = [
            segment
            for segment in normalized_segments
            if max(start_ms, segment[0]) < min(end_ms, segment[1])
        ]
        if not overlaps:
            raise ValueError(
                f"canonical source speech event {event_id} has no ASR segment"
            )
        asr_text = " ".join(segment[2] for segment in overlaps).strip()
        if asr_text != source_text:
            raise ValueError(
                f"canonical source speech text for event {event_id} does not match ASR"
            )
    if source_speech:
        for start_ms, end_ms, _text, segment_id in normalized_segments:
            if not any(
                max(start_ms, event[0]) < min(end_ms, event[1])
                for event in source_speech
            ):
                raise ValueError(
                    f"canonical ASR segment {segment_id} has no source speech event"
                )


def build_analysis_envelope(
    *,
    high_fidelity_analysis: Mapping[str, Any],
    source_dynamics_analysis: Mapping[str, Any],
    audio_contract: Mapping[str, Any],
    target_truth: Mapping[str, Any] | None = None,
    source_fidelity_contract: Mapping[str, Any] | None = None,
    timeline_regions: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    parent_digests: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Join immutable analysis outputs into one digestable envelope.

    The function does not infer missing target truth or route facts.  Optional
    sections are copied only when supplied; downstream projection decides
    whether a missing section is a blocker for the selected region.
    """

    high = _require_mapping(high_fidelity_analysis, "high_fidelity_analysis")
    dynamics = _require_mapping(source_dynamics_analysis, "source_dynamics_analysis")
    audio = _require_mapping(audio_contract, "audio_contract")
    _validate_high_fidelity_analysis(high)
    _validate_dynamics(dynamics)
    _validate_audio(
        audio,
        duration_us=int(dynamics["reference_duration_us"]),
        dynamics=dynamics,
    )

    envelope: dict[str, Any] = {
        "contract": CONTRACT,
        "contract_version": CONTRACT_VERSION,
        "high_fidelity_analysis": high,
        "source_dynamics_analysis": dynamics,
        "audio_contract": audio,
    }
    if target_truth is not None:
        envelope["target_truth"] = _require_mapping(target_truth, "target_truth")
    if source_fidelity_contract is not None:
        envelope["source_fidelity_contract"] = _require_mapping(
            source_fidelity_contract, "source_fidelity_contract"
        )
    if timeline_regions is not None:
        if isinstance(timeline_regions, Mapping):
            envelope["timeline_regions"] = deepcopy(dict(timeline_regions))
        elif isinstance(timeline_regions, Sequence) and not isinstance(
            timeline_regions, (str, bytes, bytearray)
        ):
            envelope["timeline_regions"] = {
                "regions": [deepcopy(dict(item)) for item in timeline_regions if isinstance(item, Mapping)]
            }
        else:
            raise ValueError("timeline_regions must be an object or region array")

    component_digests = {
        "high_fidelity_analysis": canonical_digest(high),
        "source_dynamics_analysis": canonical_digest(dynamics),
        "audio_contract": canonical_digest(audio),
    }
    for key in ("target_truth", "source_fidelity_contract", "timeline_regions"):
        if key in envelope:
            component_digests[key] = canonical_digest(envelope[key])
    envelope["component_digests"] = component_digests
    if parent_digests is not None:
        envelope["parent_digests"] = {
            str(key): _require_sha(value, f"parent_digests.{key}")
            for key, value in parent_digests.items()
        }
    envelope["projection_sha256"] = canonical_digest(envelope)
    return envelope


def validate_analysis_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a detached canonical envelope copy."""

    envelope = _require_mapping(value, "analysis_envelope")
    if envelope.get("contract") != CONTRACT:
        raise ValueError("invalid canonical high-fidelity analysis envelope contract")
    if envelope.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("unsupported canonical high-fidelity analysis envelope version")
    high = _require_mapping(envelope.get("high_fidelity_analysis"), "envelope.high_fidelity_analysis")
    dynamics = _require_mapping(
        envelope.get("source_dynamics_analysis"), "envelope.source_dynamics_analysis"
    )
    audio = _require_mapping(envelope.get("audio_contract"), "envelope.audio_contract")
    _validate_high_fidelity_analysis(high)
    _validate_dynamics(dynamics)
    _validate_audio(
        audio,
        duration_us=int(dynamics["reference_duration_us"]),
        dynamics=dynamics,
    )
    component_digests = envelope.get("component_digests")
    if not isinstance(component_digests, Mapping):
        raise ValueError("analysis envelope component_digests are required")
    for key, expected in component_digests.items():
        if key not in envelope:
            raise ValueError(f"analysis envelope digest references missing component: {key}")
        if _require_sha(expected, f"component_digests.{key}") != canonical_digest(envelope[key]):
            raise ValueError(f"analysis envelope component digest mismatch: {key}")
    projection_sha = _require_sha(envelope.get("projection_sha256"), "projection_sha256")
    if projection_sha != canonical_digest(_without_digest(envelope, "projection_sha256")):
        raise ValueError("analysis envelope projection digest mismatch")
    parent_digests = envelope.get("parent_digests")
    if parent_digests is not None:
        if not isinstance(parent_digests, Mapping):
            raise ValueError("analysis envelope parent_digests must be an object")
        for key, digest in parent_digests.items():
            _require_sha(digest, f"parent_digests.{key}")
    return envelope


def is_analysis_envelope(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("contract") == CONTRACT


__all__ = [
    "CONTRACT",
    "CONTRACT_VERSION",
    "build_analysis_envelope",
    "canonical_digest",
    "is_analysis_envelope",
    "validate_analysis_envelope",
]
