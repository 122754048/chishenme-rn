"""Immutable contracts for source-audio performance replication.

The module is deliberately stage-neutral.  It does not introduce an input
slot, call a Provider, materialize media, or alter workflow state.  Existing
stage ports can build and validate these JSON-compatible contracts from their
already-authoritative source/dynamics/ASR/timeline evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ReplicationError


SOURCE_AUDIO_REPLICATE_V1 = "source_audio_replicate_v1"
REFERENCE_AUDIO_MIGRATE_V1 = "reference_audio_migrate_v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_REGION_TYPES = frozenset(
    {
        "opaque_ui_demo",
        "generated_ui_demo",
        "generated_ui",
        "ui_demo",
        "tail_card",
        "opaque_tail",
    }
)
_PERFORMANCE_FIELDS = frozenset(
    {
        "cut_id",
        "source_time",
        "segment_time",
        "performance_mode",
        "lyric_status",
        "beat_anchors_ms",
        "lip_sync",
        "action",
        "expression",
        "emotion",
        "end_pose",
        "criticality",
    }
)
_FORBIDDEN_SPLICE_OPERATIONS = (
    "atempo",
    "loop",
    "stretch",
    "freeze",
    "black_padding",
    "audio_padding",
    "unsupported_mixing",
)


def canonical_json_sha256(value: Any) -> str:
    """Return the contract digest over canonical UTF-8 JSON bytes."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _blocked(code: str, message: str, **details: Any) -> None:
    raise ReplicationError(
        code,
        f"{code}: {message}",
        category="contract",
        user_action_required=True,
        details=details,
        http_status=422,
    )


def _sha256(value: Any, *, field: str) -> str:
    digest = str(value or "").lower()
    if not _SHA256.fullmatch(digest):
        _blocked("PERFORMANCE_AUDIO_SOURCE_REQUIRED", f"{field} must be a SHA-256")
    return digest


def _ms(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        _blocked("PERFORMANCE_TIMELINE_REQUIRED", f"{field} must be an integer millisecond")
    try:
        result = int(value)
    except (TypeError, ValueError):
        _blocked("PERFORMANCE_TIMELINE_REQUIRED", f"{field} must be an integer millisecond")
    if result < 0:
        _blocked("PERFORMANCE_TIMELINE_REQUIRED", f"{field} must not be negative")
    return result


def _window(value: Any, *, field: str, upper_bound_ms: int | None = None) -> dict[str, int]:
    if not isinstance(value, Mapping):
        _blocked("PERFORMANCE_TIMELINE_REQUIRED", f"{field} must be an object")
    start = _ms(value.get("start_ms"), field=f"{field}.start_ms")
    end = _ms(value.get("end_ms"), field=f"{field}.end_ms")
    if end <= start:
        _blocked("PERFORMANCE_TIMELINE_REQUIRED", f"{field} must have end_ms after start_ms")
    if upper_bound_ms is not None and end > upper_bound_ms:
        _blocked("PERFORMANCE_TIMELINE_REQUIRED", f"{field} exceeds source duration")
    return {"start_ms": start, "end_ms": end}


def _region_window(region: Mapping[str, Any], *, source_duration_ms: int) -> dict[str, int]:
    return _window(
        {
            "start_ms": region.get("source_start_ms", region.get("start_ms")),
            "end_ms": region.get("source_end_ms", region.get("end_ms")),
        },
        field=f"region {str(region.get('region_id') or '') or '<unnamed>'}",
        upper_bound_ms=source_duration_ms,
    )


def _is_opaque(region: Mapping[str, Any]) -> bool:
    kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
    return kind in _OPAQUE_REGION_TYPES


def _audio_segments(audio_contract: Mapping[str, Any], *, source_duration_ms: int) -> list[dict[str, Any]]:
    nested = audio_contract.get("audio_contract")
    source = nested if isinstance(nested, Mapping) else audio_contract
    raw = source.get("segments")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        _blocked("AUDIO_LYRIC_EVIDENCE_REQUIRED", "ASR/audio segments are required")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            _blocked("AUDIO_LYRIC_EVIDENCE_REQUIRED", f"audio segment {index} must be an object")
        window = _window(item, field=f"audio segment {index}", upper_bound_ms=source_duration_ms)
        text = str(item.get("text") or "").strip()
        kind = str(item.get("kind") or item.get("type") or "speech").strip().lower()
        if not text:
            text = "instrumental" if kind in {"instrumental", "music"} else "inaudible"
        confidence = item.get("confidence", item.get("avg_logprob_confidence", 1.0))
        if confidence is None:
            confidence = 0.0
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            _blocked("AUDIO_LYRIC_EVIDENCE_REQUIRED", f"audio segment {index} confidence is invalid")
        anchors = item.get("beat_anchors_ms") or []
        if not isinstance(anchors, Sequence) or isinstance(anchors, (str, bytes, bytearray)):
            _blocked("AUDIO_LYRIC_EVIDENCE_REQUIRED", f"audio segment {index} beat anchors are invalid")
        normalized_anchors = [_ms(anchor, field=f"audio segment {index} beat anchor") for anchor in anchors]
        if normalized_anchors and any(anchor < window["start_ms"] or anchor > window["end_ms"] for anchor in normalized_anchors):
            _blocked("AUDIO_LYRIC_EVIDENCE_REQUIRED", f"audio segment {index} beat anchor is outside its window")
        rows.append(
            {
                "segment_id": str(item.get("segment_id") or f"A{index:03d}"),
                **window,
                "text": text,
                "confidence": confidence,
                "kind": kind,
                "beat_anchors_ms": normalized_anchors,
                "emotion": str(item.get("emotion") or "unclassified"),
            }
        )
    return rows


def _require_nonempty_string(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", f"{field} is required")
    return text


def _validate_performance_line(
    line: Mapping[str, Any],
    *,
    source_duration_ms: int,
    audio_segments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    missing = sorted(field for field in _PERFORMANCE_FIELDS if field not in line)
    if missing:
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "per-Cut performance fields are missing", missing=missing)
    source_time = _window(line["source_time"], field="performance line source_time", upper_bound_ms=source_duration_ms)
    segment_time = _window(line["segment_time"], field="performance line segment_time")
    lyric_status = _require_nonempty_string(line["lyric_status"], field="performance line lyric_status").lower()
    lyric = str(line.get("exact_sung_text") or "").strip()
    if lyric_status not in {"verified", "instrumental", "inaudible"}:
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "lyric_status must be verified, instrumental, or inaudible")
    if lyric_status == "verified" and not lyric:
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "verified performance lines require exact_sung_text")
    if lyric_status in {"instrumental", "inaudible"}:
        lyric = lyric_status
    anchors = line["beat_anchors_ms"]
    if not isinstance(anchors, Sequence) or isinstance(anchors, (str, bytes, bytearray)):
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "beat_anchors_ms must be an array")
    normalized_anchors = [_ms(anchor, field="performance line beat anchor") for anchor in anchors]
    if not normalized_anchors and not str(line.get("no_beat_reason") or "").strip():
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "a beat anchor or no_beat_reason is required")
    for nested, keys in (
        ("lip_sync", ("face_visibility", "articulation", "end_state")),
        ("action", ("start", "beat_action", "end")),
        ("expression", ("start", "peak", "end")),
    ):
        value = line[nested]
        if not isinstance(value, Mapping):
            _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", f"{nested} must be an object")
        for key in keys:
            _require_nonempty_string(value.get(key), field=f"{nested}.{key}")
    criticality = _require_nonempty_string(line["criticality"], field="performance line criticality").upper()
    overlaps = [
        item for item in audio_segments
        if max(source_time["start_ms"], int(item["start_ms"])) < min(source_time["end_ms"], int(item["end_ms"]))
    ]
    if not overlaps:
        _blocked("AUDIO_LYRIC_EVIDENCE_REQUIRED", "performance line has no source-audio evidence", cut_id=line.get("cut_id"))
    if lyric_status == "verified":
        source_lyric = " ".join(
            str(item.get("text") or "").strip()
            for item in overlaps
            if str(item.get("text") or "").strip()
            not in {"instrumental", "inaudible"}
        ).strip()
        def normalize(text: str) -> str:
            return re.sub(r"\s+", " ", text).strip().casefold()

        if source_lyric and normalize(lyric) != normalize(source_lyric):
            _blocked(
                "AUDIO_LYRIC_EVIDENCE_REQUIRED",
                "verified lyric differs from the authorized source-audio evidence",
                cut_id=line.get("cut_id"),
            )
    if criticality == "H" and lyric_status == "verified" and any(float(item["confidence"]) < 0.80 for item in overlaps):
        _blocked("AUDIO_LYRIC_EVIDENCE_REQUIRED", "high-criticality lyric confidence is below 0.80", cut_id=line.get("cut_id"))
    return {
        "cut_id": _require_nonempty_string(line["cut_id"], field="performance line cut_id"),
        "source_time": source_time,
        "segment_time": segment_time,
        "performance_mode": _require_nonempty_string(line["performance_mode"], field="performance line performance_mode"),
        "exact_sung_text": lyric,
        "lyric_status": lyric_status,
        "beat_anchors_ms": normalized_anchors,
        "no_beat_reason": str(line.get("no_beat_reason") or "").strip() or None,
        "lip_sync": dict(line["lip_sync"]),
        "action": dict(line["action"]),
        "expression": dict(line["expression"]),
        "emotion": _require_nonempty_string(line["emotion"], field="performance line emotion"),
        "end_pose": _require_nonempty_string(line["end_pose"], field="performance line end_pose"),
        "criticality": criticality,
        "final_audio_carrier": "source_audio_global_window_postproduction",
    }


def build_audio_evidence_contracts(
    *,
    source_audio_sha256: str,
    source_duration_ms: int,
    audio_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the Stage 3 evidence sidecars without requiring a Cut script.

    The source digest is deliberately the digest of the canonical extracted
    audio stream, not the enclosing source-video bytes.  Stage 6 adds
    per-Cut performance instructions later, after the existing intent/script
    workflow has selected generated Cuts.
    """

    source_sha = _sha256(source_audio_sha256, field="source_audio_sha256")
    duration = _ms(source_duration_ms, field="source_duration_ms")
    if duration <= 0:
        _blocked("PERFORMANCE_AUDIO_SOURCE_REQUIRED", "source_duration_ms must be positive")
    if not isinstance(audio_contract, Mapping):
        _blocked("AUDIO_LYRIC_EVIDENCE_REQUIRED", "audio_contract is required")
    segments = _audio_segments(audio_contract, source_duration_ms=duration)
    source = audio_contract.get("audio_contract") if isinstance(audio_contract.get("audio_contract"), Mapping) else audio_contract
    language = str(source.get("audio_language") or source.get("language") or "und").strip() or "und"
    result = {
        "performance_audio_source_contract": {
            "contract": "performance-audio-source/v1",
            "mode": SOURCE_AUDIO_REPLICATE_V1,
            "authorization": {"status": "user_default_authorized", "scope": "current_run_only"},
            "source_audio_sha256": source_sha,
            "audio_language": language,
            "music_role": "performance_master",
            "provider_reference_audio": "forbidden",
            "final_audio_carrier": "deterministic_postproduction",
        },
        "audio_lyrics_beat_contract": {
            "contract": "audio-lyrics-beat/v1",
            "source_audio_sha256": source_sha,
            "audio_language": language,
            "segments": segments,
        },
    }
    result["contract_sha256"] = canonical_json_sha256(result)
    return result


def build_source_audio_contracts(
    *,
    source_audio_sha256: str,
    source_duration_ms: int,
    audio_contract: Mapping[str, Any],
    timeline_regions: Sequence[Mapping[str, Any]],
    performance_lines: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create validated current-run source-audio performance contracts.

    ``reference_audio_migrate_v1`` deliberately has no runtime entry point yet:
    no present API may pass a reference audio file to fixed Provider B.
    """

    evidence = build_audio_evidence_contracts(
        source_audio_sha256=source_audio_sha256,
        source_duration_ms=source_duration_ms,
        audio_contract=audio_contract,
    )
    source_sha = str(evidence["performance_audio_source_contract"]["source_audio_sha256"])
    duration = _ms(source_duration_ms, field="source_duration_ms")
    if not isinstance(timeline_regions, Sequence) or isinstance(timeline_regions, (str, bytes, bytearray)):
        _blocked("PERFORMANCE_TIMELINE_REQUIRED", "timeline_regions must be an array")
    if not isinstance(performance_lines, Sequence) or isinstance(performance_lines, (str, bytes, bytearray)):
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "performance_lines must be an array")
    segments = list(evidence["audio_lyrics_beat_contract"]["segments"])
    generated: list[dict[str, Any]] = []
    opaque: list[dict[str, Any]] = []
    for index, item in enumerate(timeline_regions, start=1):
        if not isinstance(item, Mapping):
            _blocked("PERFORMANCE_TIMELINE_REQUIRED", f"timeline region {index} must be an object")
        window = _region_window(item, source_duration_ms=duration)
        region_id = _require_nonempty_string(item.get("region_id") or f"R{index:02d}", field="timeline region region_id")
        if _is_opaque(item):
            opaque.append({"region_id": region_id, "source_start_ms": window["start_ms"], "source_end_ms": window["end_ms"], "audio_mode": "opaque_audio_keep"})
        else:
            generated.append({"region_id": region_id, "source_start_ms": window["start_ms"], "source_end_ms": window["end_ms"], "segment_id": _require_nonempty_string(item.get("segment_id") or region_id, field="generated region segment_id"), "audio_mode": "source_master"})
    if not generated:
        _blocked("PERFORMANCE_TIMELINE_REQUIRED", "source-audio replication requires at least one generated region")
    lines = [
        _validate_performance_line(line, source_duration_ms=duration, audio_segments=segments)
        for line in performance_lines
        if isinstance(line, Mapping)
    ]
    if len(lines) != len(performance_lines):
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "performance_lines must contain only objects")
    contracts = {
        "performance_audio_source_contract": dict(evidence["performance_audio_source_contract"]),
        "performance_timeline_contract": {
            "contract": "performance-timeline/v1",
            "clock": "source_audio_global_ms",
            "performance_windows": generated,
            "opaque_windows": opaque,
        },
        "audio_lyrics_beat_contract": dict(evidence["audio_lyrics_beat_contract"]),
        "performance_line_contract": {
            "contract": "performance-line/v1",
            "source_audio_sha256": source_sha,
            "cuts": lines,
        },
        "audio_splice_policy": {
            "contract": "audio-splice-policy/v1",
            "source_audio_sha256": source_sha,
            "generated_audio": "mute_then_replace_with_exact_source_global_window",
            "opaque_audio": "keep_original_only",
            "boundary_fades": "only_if_explicitly_evidence_approved",
            "forbidden_operations": list(_FORBIDDEN_SPLICE_OPERATIONS),
        },
    }
    contracts["contract_sha256"] = canonical_json_sha256(contracts)
    return contracts


__all__ = [
    "REFERENCE_AUDIO_MIGRATE_V1",
    "SOURCE_AUDIO_REPLICATE_V1",
    "build_audio_evidence_contracts",
    "build_source_audio_contracts",
    "canonical_json_sha256",
]
