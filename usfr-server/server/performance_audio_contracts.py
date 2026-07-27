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
from pathlib import Path
from typing import Any

from .errors import ReplicationError


SOURCE_AUDIO_REPLICATE_V1 = "source_audio_replicate_v1"
REFERENCE_AUDIO_MIGRATE_V1 = "reference_audio_migrate_v1"
BACKGROUND_MUSIC_VERIFIED_SINGING_V1 = "background_music_verified_singing/v1"
BACKGROUND_MUSIC_REPLACEMENT_V1 = "background_music_replacement/v1"
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
        "line_id",
        "cut_id",
        "source_content_timeline_sha256",
        "content_type",
        "speaker_assignment",
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
_CONTENT_TYPES = frozenset({"spoken", "sung", "instrumental", "inaudible"})
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


def _validated_speaker_assignment(line: Mapping[str, Any]) -> dict[str, Any]:
    assignment = line.get("speaker_assignment")
    if not isinstance(assignment, Mapping):
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "speaker_assignment must be an object")
    if assignment.get("status") == "PENDING_ASSIGNMENT":
        _blocked("PENDING_ASSIGNMENT", "speaker assignment must be confirmed before Invocation A")
    content_type = line.get("content_type")
    if content_type not in _CONTENT_TYPES:
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "performance line content_type is invalid")
    if content_type in {"spoken", "sung"}:
        required = {"status", "speaker_id", "role", "visibility", "confidence", "evidence_sha256"}
        missing = sorted(required - set(assignment))
        if missing or assignment.get("status") != "CONFIRMED":
            _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "spoken or sung performance requires CONFIRMED speaker_assignment", missing=missing)
        confidence = assignment.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
            _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "speaker_assignment.confidence is invalid")
        evidence_sha = str(assignment.get("evidence_sha256") or "").lower()
        if not _SHA256.fullmatch(evidence_sha):
            _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "speaker_assignment.evidence_sha256 must be a SHA-256")
        return {
            "status": "CONFIRMED",
            "speaker_id": _require_nonempty_string(assignment.get("speaker_id"), field="speaker_assignment.speaker_id"),
            "role": _require_nonempty_string(assignment.get("role"), field="speaker_assignment.role"),
            "visibility": _require_nonempty_string(assignment.get("visibility"), field="speaker_assignment.visibility"),
            "confidence": float(confidence),
            "evidence_sha256": evidence_sha,
        }
    if assignment.get("status") != "NOT_APPLICABLE":
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "non-verbal performance requires NOT_APPLICABLE speaker_assignment")
    return {"status": "NOT_APPLICABLE"}


def _validate_approved_line_bindings(
    lines: Sequence[Mapping[str, Any]],
    *,
    approved_lines: Sequence[Mapping[str, Any]],
    source_content_timeline_sha256: str,
    generated_regions: Sequence[Mapping[str, Any]],
) -> None:
    """Bind Invocation-A performance rows to immutable approved line rows."""

    if not isinstance(approved_lines, Sequence) or isinstance(approved_lines, (str, bytes, bytearray)):
        _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "approved line contracts must be an array")
    try:
        from scripts.line_contract import canonical_line
    except ImportError as exc:  # pragma: no cover - deployment packaging failure
        _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "canonical line contract validator is unavailable", reason=str(exc))
    canonical_approved = [canonical_line(line) for line in approved_lines]
    approved_by_id = {str(line["line_id"]): line for line in canonical_approved}
    if len(approved_by_id) != len(canonical_approved):
        _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "approved line_id values must be unique")
    timeline_sha = str(source_content_timeline_sha256 or "").lower()
    if not _SHA256.fullmatch(timeline_sha):
        _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "source_content_timeline_sha256 must be a SHA-256")
    regions_by_window = {
        (int(region["source_start_ms"]), int(region["source_end_ms"])): region
        for region in generated_regions
    }
    if len(regions_by_window) != len(generated_regions):
        _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "generated regions must have unique source windows")
    bound_line_ids: set[str] = set()
    bound_region_windows: set[tuple[int, int]] = set()
    for performance in lines:
        line_id = str(performance["line_id"])
        approved = approved_by_id.get(line_id)
        if approved is None:
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "performance line has no approved line", line_id=line_id)
        if line_id in bound_line_ids:
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "approved line is bound more than once", line_id=line_id)
        bound_line_ids.add(line_id)
        if performance["source_content_timeline_sha256"] != timeline_sha or approved.get("source_content_timeline_sha256") != timeline_sha:
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "source-content timeline SHA changed", line_id=line_id)
        if performance["cut_id"] != approved["cut_id"]:
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "performance line Cut binding changed", line_id=line_id)
        if performance["content_type"] != approved.get("content_type"):
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "performance line content type changed", line_id=line_id)
        if performance["speaker_assignment"] != approved.get("speaker_assignment"):
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "performance line speaker assignment changed", line_id=line_id)
        if performance["exact_sung_text"] != approved["text"]["exact"]:
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "performance line text changed", line_id=line_id)
        expected_source = {"start_ms": approved["time"]["start_ms"], "end_ms": approved["time"]["end_ms"]}
        if performance["source_time"] != expected_source:
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "performance line source-time changed", line_id=line_id)
        region = regions_by_window.get((expected_source["start_ms"], expected_source["end_ms"]))
        if region is None:
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "performance line crosses or falls outside a generated region", line_id=line_id)
        region_window = (expected_source["start_ms"], expected_source["end_ms"])
        if region_window in bound_region_windows:
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "generated region is bound more than once", line_id=line_id)
        bound_region_windows.add(region_window)
        expected_segment = {
            "start_ms": expected_source["start_ms"] - int(region["source_start_ms"]),
            "end_ms": expected_source["end_ms"] - int(region["source_start_ms"]),
        }
        if performance["segment_time"] != expected_segment:
            _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "performance line segment-time changed", line_id=line_id)
    if set(approved_by_id) != bound_line_ids:
        _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "approved line coverage is incomplete")
    if len(lines) != len(generated_regions):
        _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "generated region performance coverage is incomplete")
    if set(regions_by_window) != bound_region_windows:
        _blocked("PERFORMANCE_LINE_BINDING_REQUIRED", "generated region performance coverage is incomplete")


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
    timeline_sha = str(line.get("source_content_timeline_sha256") or "").lower()
    if not _SHA256.fullmatch(timeline_sha):
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "source_content_timeline_sha256 must be a SHA-256")
    content_type = line.get("content_type")
    assignment = _validated_speaker_assignment(line)
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
    expected_content_type = {
        "spoken": "spoken",
        "sung": "sung",
        "singing": "sung",
        "instrumental": "instrumental",
        "inaudible": "inaudible",
    }.get(str(line.get("performance_mode") or "").lower())
    if expected_content_type != content_type:
        _blocked("PERFORMANCE_LINE_CONTRACT_REQUIRED", "performance_mode must match content_type")
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
        "line_id": _require_nonempty_string(line["line_id"], field="performance line line_id"),
        "cut_id": _require_nonempty_string(line["cut_id"], field="performance line cut_id"),
        "source_content_timeline_sha256": timeline_sha,
        "content_type": content_type,
        "speaker_assignment": assignment,
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
    line_contracts: Sequence[Mapping[str, Any]],
    source_content_timeline_sha256: str,
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
    source_timeline_shas = {
        str(line["source_content_timeline_sha256"])
        for line in lines
    }
    if len(source_timeline_shas) != 1:
        _blocked(
            "PERFORMANCE_LINE_CONTRACT_REQUIRED",
            "performance lines must bind one source-content timeline SHA",
        )
    source_timeline_sha = next(iter(source_timeline_shas))
    _validate_approved_line_bindings(
        lines,
        approved_lines=line_contracts,
        source_content_timeline_sha256=source_content_timeline_sha256,
        generated_regions=generated,
    )
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
            "source_content_timeline_sha256": source_timeline_sha,
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


def _recovery_block(code: str, message: str, **details: Any) -> None:
    raise ReplicationError(
        code,
        message,
        category="contract",
        user_action_required=True,
        details=details or None,
        http_status=422,
    )


def _recovery_artifact_json(
    context: Any,
    *,
    kind: str,
    sha256: str,
) -> dict[str, Any]:
    """Materialize one exact, canonical worker artifact without re-analysis."""

    descriptors = [
        item
        for item in (getattr(context, "artifacts", ()) or ())
        if isinstance(item, Mapping)
        and item.get("kind") == kind
        and item.get("sha256") == sha256
    ]
    if len(descriptors) != 1:
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            (
                "frozen source-content timeline SHA differs from the approval sidecar"
                if kind == "source_content_timeline"
                else f"confirmed script recovery requires exactly one {kind} artifact"
            ),
        )
    materialize = getattr(context, "materialize_artifact", None)
    if not callable(materialize):
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            f"confirmed script recovery cannot materialize {kind}",
        )
    try:
        with materialize(kind, sha256=sha256) as media:
            raw = Path(media.path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError("materialized bytes do not match the declared SHA-256")
        value = json.loads(raw.decode("utf-8"))
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if canonical != raw or not isinstance(value, Mapping):
            raise ValueError("artifact must be canonical JSON object bytes")
        return dict(value)
    except ReplicationError:
        raise
    except Exception as exc:
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            f"confirmed script recovery {kind} artifact is invalid",
            reason=str(exc),
        )


def _confirmed_recovery_sidecar(context: Any) -> tuple[dict[str, Any], int, str]:
    snapshot = getattr(context, "snapshot", None)
    revision = getattr(snapshot, "current_script_revision", None)
    script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1 or not _SHA256.fullmatch(script_sha):
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "confirmed script recovery requires an approved current script revision",
        )
    getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
    if not callable(getter):
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "confirmed script recovery requires the JobStore approval sidecar",
        )
    sidecar = getter(getattr(context, "job_id", ""), revision)
    if not isinstance(sidecar, Mapping):
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "confirmed script recovery requires user-confirmed line contracts",
        )
    if (
        sidecar.get("contract") != "approved-script-lines/v1"
        or sidecar.get("revision") != revision
        or sidecar.get("script_sha256") != script_sha
    ):
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "approval sidecar is not bound to the exact approved script revision",
        )
    timeline_sha = str(sidecar.get("source_content_timeline_sha256") or "").lower()
    if not _SHA256.fullmatch(timeline_sha):
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "approval sidecar source-content timeline SHA is invalid",
        )
    lines = sidecar.get("line_contracts")
    if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes, bytearray)):
        _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "approval sidecar line contracts are invalid")
    try:
        from scripts.line_contract import validate_line_contracts

        canonical_lines = validate_line_contracts(lines)
    except Exception as exc:
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "PENDING_ASSIGNMENT or invalid confirmed line contracts block script recovery",
            reason=str(exc),
        )
    canonical_sha = canonical_json_sha256(canonical_lines)
    if sidecar.get("line_contracts_sha256") != canonical_sha:
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "approval sidecar line contract SHA differs from canonical lines",
        )
    if any(line.get("source_content_timeline_sha256") != timeline_sha for line in canonical_lines):
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "approved line source-content timeline SHA changed",
        )
    return {
        "contract": "approved-script-lines/v1",
        "revision": revision,
        "script_sha256": script_sha,
        "source_content_timeline_sha256": timeline_sha,
        "line_contracts": canonical_lines,
        "line_contracts_sha256": canonical_sha,
    }, revision, script_sha


def _recovery_source_audio_evidence(
    context: Any,
    *,
    candidate: Mapping[str, Any],
) -> tuple[int, list[dict[str, Any]]]:
    """Load the existing source-audio evidence used to validate a GPT draft."""

    descriptors = getattr(context, "artifacts", ()) or ()

    def materialize(kind: str) -> dict[str, Any]:
        matches = [
            item
            for item in descriptors
            if isinstance(item, Mapping) and item.get("kind") == kind
        ]
        if len(matches) != 1:
            _recovery_block(
                "APPROVED_LINE_CONTRACT_REQUIRED",
                f"confirmed script recovery requires exactly one {kind} artifact",
            )
        digest = str(matches[0].get("sha256") or "").lower()
        if _SHA256.fullmatch(digest) is None:
            _recovery_block(
                "APPROVED_LINE_CONTRACT_REQUIRED",
                f"confirmed script recovery {kind} artifact SHA is invalid",
            )
        return _recovery_artifact_json(context, kind=kind, sha256=digest)

    source = materialize("performance_audio_source_contract")
    lyrics = materialize("audio_lyrics_beat_contract")
    source_sha = _sha256(candidate.get("source_audio_sha256"), field="candidate source_audio_sha256")
    if (
        source.get("contract") != "performance-audio-source/v1"
        or source.get("mode") != SOURCE_AUDIO_REPLICATE_V1
        or source.get("source_audio_sha256") != source_sha
        or lyrics.get("contract") != "audio-lyrics-beat/v1"
        or lyrics.get("source_audio_sha256") != source_sha
    ):
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "source-audio performance candidates are not bound to the frozen audio evidence",
        )
    duration = _ms(candidate.get("source_duration_ms"), field="candidate source_duration_ms")
    if duration <= 0:
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "candidate source_duration_ms must be positive",
        )
    return duration, _audio_segments(lyrics, source_duration_ms=duration)


def _materialize_confirmed_performance_lines(
    *,
    candidate: Mapping[str, Any],
    approval: Mapping[str, Any],
    source_duration_ms: int,
    audio_segments: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if candidate.get("contract") != "performance-line-candidate/v1" or candidate.get("status") != "PENDING_CONFIRMATION":
        _recovery_block(
            "APPROVED_LINE_CONTRACT_REQUIRED",
            "GPT performance draft must remain a PENDING_CONFIRMATION candidate",
        )
    raw_cuts = candidate.get("cuts")
    approved_lines = approval["line_contracts"]
    if not isinstance(raw_cuts, Sequence) or isinstance(raw_cuts, (str, bytes, bytearray)):
        _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "GPT performance candidates are invalid")
    candidates_by_cut: dict[str, Mapping[str, Any]] = {}
    for raw in raw_cuts:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("cut_id"), str) or not raw["cut_id"]:
            _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "GPT performance candidate Cut is invalid")
        cut_id = raw["cut_id"]
        if cut_id in candidates_by_cut:
            _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "GPT performance candidates repeat a Cut")
        candidates_by_cut[cut_id] = raw
    if len({line["cut_id"] for line in approved_lines}) != len(approved_lines):
        _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "approved performance lines must map one-to-one to Cuts")
    if set(candidates_by_cut) != {line["cut_id"] for line in approved_lines}:
        _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "approved performance Cut coverage differs from the GPT draft")
    result: list[dict[str, Any]] = []
    for approved in approved_lines:
        raw = candidates_by_cut[approved["cut_id"]]
        source_time = {
            "start_ms": approved["time"]["start_ms"],
            "end_ms": approved["time"]["end_ms"],
        }
        if raw.get("source_time") != source_time:
            _recovery_block(
                "APPROVED_LINE_CONTRACT_REQUIRED",
                "GPT performance candidate source window differs from the confirmed line",
                line_id=approved["line_id"],
            )
        required = (
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
        )
        missing = [field for field in required if field not in raw]
        if missing:
            _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "GPT performance candidate fields are incomplete", missing=missing)
        content_type = approved.get("content_type")
        lyric_status = raw["lyric_status"]
        exact_text = (
            approved["text"]["exact"]
            if content_type in {"spoken", "sung"}
            else str(lyric_status).lower()
        )
        result.append(
            _validate_performance_line(
                {
                    "line_id": approved["line_id"],
                    "cut_id": approved["cut_id"],
                    "source_content_timeline_sha256": approval["source_content_timeline_sha256"],
                    "content_type": content_type,
                    "speaker_assignment": approved["speaker_assignment"],
                    "source_time": source_time,
                    "segment_time": raw["segment_time"],
                    "performance_mode": raw["performance_mode"],
                    "exact_sung_text": exact_text,
                    "lyric_status": lyric_status,
                    "beat_anchors_ms": raw["beat_anchors_ms"],
                    "no_beat_reason": raw.get("no_beat_reason"),
                    "lip_sync": raw["lip_sync"],
                    "action": raw["action"],
                    "expression": raw["expression"],
                    "emotion": raw["emotion"],
                    "end_pose": raw["end_pose"],
                    "criticality": raw["criticality"],
                },
                source_duration_ms=source_duration_ms,
                audio_segments=audio_segments,
            )
        )
    _validate_approved_line_bindings(
        result,
        approved_lines=approved_lines,
        source_content_timeline_sha256=approval["source_content_timeline_sha256"],
        generated_regions=[
            {
                "region_id": line["cut_id"],
                "source_start_ms": line["time"]["start_ms"],
                "source_end_ms": line["time"]["end_ms"],
            }
            for line in approved_lines
        ],
    )
    return result


def build_background_music_performance_contract(
    *,
    user_confirmed_intent: str,
    performance_line_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Choose the only two evidence-bound modes for an uploaded song.

    A caller that explicitly asks for singing must supply complete immutable
    performance evidence.  A background-music replacement intentionally does
    not consume lyric text or make a lip-sync claim.
    """

    intent = str(user_confirmed_intent or "").strip()
    if intent == "background_music_replacement":
        return {
            "contract": BACKGROUND_MUSIC_REPLACEMENT_V1,
            "mode": "background_music_replacement",
            "lyric_lip_sync_policy": "No lyric lip-sync",
            "performance_line_contract_sha256": None,
            "singing_lines": [],
        }
    if intent != "verified_singing":
        _blocked(
            "BACKGROUND_MUSIC_INTENT_REQUIRED",
            "user_confirmed_intent must be verified_singing or background_music_replacement",
        )
    if not isinstance(performance_line_contract, Mapping):
        _blocked("VERIFIED_SINGING_EVIDENCE_REQUIRED", "performance_line_contract is required")
    if performance_line_contract.get("contract") != "performance-line/v1":
        _blocked("VERIFIED_SINGING_EVIDENCE_REQUIRED", "performance_line_contract is invalid")
    cuts = performance_line_contract.get("cuts")
    if not isinstance(cuts, Sequence) or isinstance(cuts, (str, bytes, bytearray)) or not cuts:
        _blocked("VERIFIED_SINGING_EVIDENCE_REQUIRED", "verified singing requires at least one performance line")

    singing_lines: list[dict[str, Any]] = []
    for index, raw in enumerate(cuts, start=1):
        if not isinstance(raw, Mapping):
            _blocked("VERIFIED_SINGING_EVIDENCE_REQUIRED", "performance line must be an object", index=index)
        assignment = raw.get("speaker_assignment")
        source_time = raw.get("source_time")
        segment_time = raw.get("segment_time")
        anchors = raw.get("beat_anchors_ms")
        lyric = str(raw.get("exact_sung_text") or "").strip()
        if (
            raw.get("content_type") != "sung"
            or str(raw.get("performance_mode") or "").strip().casefold() not in {"singing", "sung"}
            or raw.get("lyric_status") != "verified"
            or not lyric
            or not isinstance(assignment, Mapping)
            or assignment.get("status") != "CONFIRMED"
            or not isinstance(assignment.get("speaker_id"), str)
            or not assignment.get("speaker_id", "").strip()
            or not _SHA256.fullmatch(str(assignment.get("evidence_sha256") or ""))
            or not isinstance(source_time, Mapping)
            or not isinstance(segment_time, Mapping)
            or not isinstance(anchors, Sequence)
            or isinstance(anchors, (str, bytes, bytearray))
            or not anchors
        ):
            _blocked(
                "VERIFIED_SINGING_EVIDENCE_REQUIRED",
                "verified singing requires confirmed performer, exact lyrics, windows, and beat evidence",
                index=index,
            )
        source_window = _window(source_time, field=f"verified singing line {index}.source_time")
        segment_window = _window(segment_time, field=f"verified singing line {index}.segment_time")
        normalized_anchors = [_ms(anchor, field=f"verified singing line {index}.beat_anchor") for anchor in anchors]
        if any(
            anchor < segment_window["start_ms"] or anchor >= segment_window["end_ms"]
            for anchor in normalized_anchors
        ):
            _blocked(
                "VERIFIED_SINGING_EVIDENCE_REQUIRED",
                "verified singing beat anchors must fall inside the confirmed segment window",
                index=index,
            )
        def prompt_detail(name: str, keys: tuple[str, ...]) -> dict[str, str]:
            value = raw.get(name)
            if not isinstance(value, Mapping):
                _blocked(
                    "VERIFIED_SINGING_EVIDENCE_REQUIRED",
                    f"verified singing line {index} requires {name} constraints",
                    index=index,
                )
            return {
                key: _require_nonempty_string(
                    value.get(key), field=f"verified singing line {index}.{name}.{key}"
                )
                for key in keys
            }

        lip_sync = prompt_detail("lip_sync", ("face_visibility", "articulation", "end_state"))
        action = prompt_detail("action", ("start", "beat_action", "end"))
        expression = prompt_detail("expression", ("start", "peak", "end"))
        singing_lines.append(
            {
                "line_id": _require_nonempty_string(raw.get("line_id"), field=f"verified singing line {index}.line_id"),
                "cut_id": _require_nonempty_string(raw.get("cut_id"), field=f"verified singing line {index}.cut_id"),
                "speaker_id": str(assignment["speaker_id"]).strip(),
                "speaker_evidence_sha256": str(assignment["evidence_sha256"]),
                "exact_sung_text": lyric,
                "source_time": source_window,
                "segment_time": segment_window,
                "beat_anchors_ms": normalized_anchors,
                "lip_sync": lip_sync,
                "action": action,
                "expression": expression,
                "emotion": _require_nonempty_string(
                    raw.get("emotion"), field=f"verified singing line {index}.emotion"
                ),
                "end_pose": _require_nonempty_string(
                    raw.get("end_pose"), field=f"verified singing line {index}.end_pose"
                ),
                "criticality": _require_nonempty_string(
                    raw.get("criticality"), field=f"verified singing line {index}.criticality"
                ).upper(),
            }
        )
    return {
        "contract": BACKGROUND_MUSIC_VERIFIED_SINGING_V1,
        "mode": "verified_singing",
        "lyric_lip_sync_policy": "Verified lyric lip-sync required",
        "performance_line_contract_sha256": canonical_json_sha256(performance_line_contract),
        "singing_lines": singing_lines,
    }


def build_background_music_performance_contract_from_route(
    *,
    uploaded_audio_route: Mapping[str, Any],
    performance_line_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Select singing from frozen source evidence, never a caller preference.

    ``pending_uploaded_lyrics`` only makes singing eligible.  Complete verified
    uploaded-lyric evidence still has to bind every line to the one confirmed
    on-camera singer and source window.  Any missing or conflicting evidence
    takes the exact BGM route instead of guessing a performance.
    """

    if not isinstance(uploaded_audio_route, Mapping):
        _blocked("BACKGROUND_MUSIC_ROUTE_REQUIRED", "uploaded_audio_route is required")
    mode = uploaded_audio_route.get("mode")
    if mode == "background_music_replacement":
        return build_background_music_performance_contract(
            user_confirmed_intent="background_music_replacement",
            performance_line_contract=None,
        )
    if mode != "pending_uploaded_lyrics":
        _blocked("BACKGROUND_MUSIC_ROUTE_REQUIRED", "uploaded_audio_route mode is invalid")
    windows = uploaded_audio_route.get("eligible_source_windows")
    if not isinstance(windows, Sequence) or isinstance(windows, (str, bytes, bytearray)) or not windows:
        return build_background_music_performance_contract(
            user_confirmed_intent="background_music_replacement",
            performance_line_contract=None,
        )
    try:
        performance = build_background_music_performance_contract(
            user_confirmed_intent="verified_singing",
            performance_line_contract=performance_line_contract,
        )
    except ReplicationError:
        return build_background_music_performance_contract(
            user_confirmed_intent="background_music_replacement",
            performance_line_contract=None,
        )
    eligible = [window for window in windows if isinstance(window, Mapping)]
    for line in performance["singing_lines"]:
        source_time = line["source_time"]
        if not any(
            window.get("speaker_id") == line["speaker_id"]
            and window.get("start_ms") <= source_time["start_ms"]
            and source_time["end_ms"] <= window.get("end_ms")
            for window in eligible
        ):
            return build_background_music_performance_contract(
                user_confirmed_intent="background_music_replacement",
                performance_line_contract=None,
            )
    return performance


def recover_confirmed_script_contracts(context: Any) -> dict[str, Any]:
    """Publish final line/performance artifacts in the existing script lease.

    This recovery consumes only the immutable script revision, source timeline,
    and JobStore approval sidecar.  It never runs GPT, source analysis, a
    Provider, or a new workflow stage.
    """

    approval, revision, script_sha = _confirmed_recovery_sidecar(context)
    timeline_sha = approval["source_content_timeline_sha256"]
    timeline = _recovery_artifact_json(
        context,
        kind="source_content_timeline",
        sha256=timeline_sha,
    )
    if timeline.get("contract") != "source-content-timeline/v1":
        _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "frozen source-content timeline artifact is invalid")
    script_revision = _recovery_artifact_json(
        context,
        kind="script_revision",
        sha256=script_sha,
    )
    exact_contract = {
        "schema_version": "exact-line-contract/v1",
        "script_revision": revision,
        "script_sha256": script_sha,
        "source_content_timeline_sha256": timeline_sha,
        "line_contracts_sha256": approval["line_contracts_sha256"],
        "lines": approval["line_contracts"],
    }
    has_source_audio = {
        str(item.get("kind") or "")
        for item in (getattr(context, "artifacts", ()) or ())
        if isinstance(item, Mapping)
    } & {"performance_audio_source_contract", "audio_lyrics_beat_contract"}
    if has_source_audio and has_source_audio != {"performance_audio_source_contract", "audio_lyrics_beat_contract"}:
        _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "source-audio evidence artifacts are incomplete")
    performance_contract: dict[str, Any] | None = None
    if has_source_audio:
        candidate = script_revision.get("performance_line_candidates")
        if not isinstance(candidate, Mapping):
            _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "source-audio recovery requires GPT performance candidates")
        source_audio_sha = str(candidate.get("source_audio_sha256") or "").lower()
        if not _SHA256.fullmatch(source_audio_sha):
            _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "GPT performance candidate source-audio SHA is invalid")
        source_duration_ms, audio_segments = _recovery_source_audio_evidence(
            context,
            candidate=candidate,
        )
        performance_contract = {
            "contract": "performance-line/v1",
            "script_revision": revision,
            "script_sha256": script_sha,
            "source_audio_sha256": source_audio_sha,
            "source_content_timeline_sha256": timeline_sha,
            "line_contracts_sha256": approval["line_contracts_sha256"],
            "cuts": _materialize_confirmed_performance_lines(
                candidate=candidate,
                approval=approval,
                source_duration_ms=source_duration_ms,
                audio_segments=audio_segments,
            ),
        }
    publisher = getattr(context, "publish_bytes", None)
    if not callable(publisher):
        _recovery_block("APPROVED_LINE_CONTRACT_REQUIRED", "confirmed script recovery requires the worker artifact publisher")
    published: list[dict[str, Any]] = []
    for kind, value in (
        ("exact_line_contract", exact_contract),
        ("performance_line_contract", performance_contract),
    ):
        if value is None:
            continue
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        published.append(
            dict(
                publisher(
                    kind=kind,
                    data=raw,
                    content_type="application/json",
                    expected_sha256=hashlib.sha256(raw).hexdigest(),
                )
            )
        )
    result: dict[str, Any] = {
        "exact_line_contract": exact_contract,
        "published_artifacts": published,
    }
    if performance_contract is not None:
        result["performance_line_contract"] = performance_contract
        result["performance_line_contract_sha256"] = published[-1]["sha256"]
    return result


__all__ = [
    "REFERENCE_AUDIO_MIGRATE_V1",
    "SOURCE_AUDIO_REPLICATE_V1",
    "build_audio_evidence_contracts",
    "build_source_audio_contracts",
    "canonical_json_sha256",
    "recover_confirmed_script_contracts",
]
