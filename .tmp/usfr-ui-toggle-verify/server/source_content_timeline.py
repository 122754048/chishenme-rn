"""One-pass, evidence-bound source text/audio/music timeline contracts.

This module deliberately does not decode media or call OCR, ASR, diarization,
or a VLM.  It joins the already-frozen dynamics and audio evidence produced by
``analyze_dynamics`` so downstream script, storyboard, Seedance and QA stages
reuse one immutable description instead of inspecting the source again.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPEECH_KINDS = frozenset({"speech", "spoken", "dialogue", "narration", "voiceover", "sung", "singing"})
_MUSIC_KINDS = frozenset({"music", "bgm", "instrumental", "song", "silence", "meaningful_silence"})
_VISIBILITIES = frozenset({"on_camera", "off_camera", "voiceover"})
_VISIBLE_TEXT_EVENT_KINDS = frozenset({"subtitle", "cta", "visible_text", "text"})


class SourceContentTimelineError(ValueError):
    """Raised when existing source evidence cannot make a safe timeline."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256(value: Any, field: str) -> str:
    result = str(value or "").strip().lower()
    if _SHA256.fullmatch(result) is None:
        raise SourceContentTimelineError(f"{field} must be a lowercase SHA-256")
    return result


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise SourceContentTimelineError(f"{field} is required")
    return result


def _ms(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceContentTimelineError(f"{field} must be a non-negative integer millisecond")
    return value


def _window(value: Mapping[str, Any], field: str, *, duration_ms: int) -> dict[str, int]:
    start = _ms(value.get("start_ms"), f"{field}.start_ms")
    end = _ms(value.get("end_ms"), f"{field}.end_ms")
    if end <= start:
        raise SourceContentTimelineError(f"{field}.end_ms must be after start_ms")
    if end > duration_ms:
        raise SourceContentTimelineError(f"{field} exceeds source duration")
    return {"start_ms": start, "end_ms": end}


def _source_cuts(analysis: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    raw = analysis.get("source_cuts", analysis.get("cuts"))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)) or not raw:
        raise SourceContentTimelineError("source_dynamics_analysis.source_cuts is required")
    cuts: list[dict[str, Any]] = []
    previous_end_us: int | None = None
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise SourceContentTimelineError(f"source Cut {index} must be an object")
        cut_id = _text(item.get("cut_id") or f"C{item.get('cut', index):02d}", f"source Cut {index}.cut_id")
        start_us = item.get("start_us")
        end_us = item.get("end_us")
        if isinstance(start_us, bool) or not isinstance(start_us, int) or start_us < 0:
            raise SourceContentTimelineError(f"source Cut {cut_id}.start_us is invalid")
        if isinstance(end_us, bool) or not isinstance(end_us, int) or end_us <= start_us:
            raise SourceContentTimelineError(f"source Cut {cut_id}.end_us is invalid")
        if (previous_end_us is not None and start_us != previous_end_us) or (previous_end_us is None and start_us != 0):
            raise SourceContentTimelineError("source Cuts must cover the decoded source contiguously")
        if any(existing["cut_id"] == cut_id for existing in cuts):
            raise SourceContentTimelineError("source Cut ids must be unique")
        cuts.append(
            {
                "cut_id": cut_id,
                "start_ms": start_us // 1000,
                "end_ms": (end_us + 999) // 1000,
            }
        )
        previous_end_us = end_us
    return cuts, (previous_end_us + 999) // 1000 if previous_end_us is not None else 0


def _cut_ids(cuts: Sequence[Mapping[str, Any]], window: Mapping[str, int]) -> list[str]:
    return [
        str(cut["cut_id"])
        for cut in cuts
        if max(int(cut["start_ms"]), int(window["start_ms"])) < min(int(cut["end_ms"]), int(window["end_ms"]))
    ]


def _confidence(value: Any, field: str, *, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise SourceContentTimelineError(f"{field} must be a number between 0 and 1")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceContentTimelineError(f"{field} must be a number between 0 and 1") from exc
    if not 0.0 <= result <= 1.0:
        raise SourceContentTimelineError(f"{field} must be a number between 0 and 1")
    return result


def _visible_tracks(analysis: Mapping[str, Any], *, duration_ms: int) -> list[dict[str, Any]]:
    raw = analysis.get("visible_person_tracks", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise SourceContentTimelineError("visible_person_tracks must be an array")
    tracks: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise SourceContentTimelineError(f"visible_person_tracks[{index}] must be an object")
        window = _window(item, f"visible_person_tracks[{index}]", duration_ms=duration_ms)
        visibility = _text(item.get("visibility"), f"visible_person_tracks[{index}].visibility")
        if visibility not in _VISIBILITIES:
            raise SourceContentTimelineError(f"visible_person_tracks[{index}].visibility is unsupported")
        tracks.append(
            {
                "speaker_id": _text(item.get("speaker_id"), f"visible_person_tracks[{index}].speaker_id"),
                "role": _text(item.get("role"), f"visible_person_tracks[{index}].role"),
                "visibility": visibility,
                **window,
                "mouth_activity_confidence": _confidence(
                    item.get("mouth_activity_confidence"),
                    f"visible_person_tracks[{index}].mouth_activity_confidence",
                ),
                "evidence_sha256": _sha256(
                    item.get("evidence_sha256"),
                    f"visible_person_tracks[{index}].evidence_sha256",
                ),
            }
        )
    return tracks


def _speaker_assignment(
    *,
    segment: Mapping[str, Any],
    window: Mapping[str, int],
    tracks: Sequence[Mapping[str, Any]],
    source_audio_sha256: str | None,
) -> dict[str, Any]:
    candidates: list[Mapping[str, Any]] = []
    duration = int(window["end_ms"]) - int(window["start_ms"])
    for track in tracks:
        overlap = max(0, min(int(track["end_ms"]), int(window["end_ms"])) - max(int(track["start_ms"]), int(window["start_ms"])))
        if overlap >= duration * 0.8 and float(track["mouth_activity_confidence"]) >= 0.8:
            candidates.append(track)
    candidates.sort(key=lambda item: str(item["speaker_id"]))
    if len(candidates) == 1:
        track = candidates[0]
        return {
            "status": "CONFIRMED",
            "speaker_id": str(track["speaker_id"]),
            "role": str(track["role"]),
            "visibility": str(track["visibility"]),
            "confidence": float(track["mouth_activity_confidence"]),
            "evidence_sha256": str(track["evidence_sha256"]),
        }
    declared = str(segment.get("speaker") or "").strip().upper()
    if declared in {"VOICEOVER", "NARRATOR", "OFF_CAMERA"} and source_audio_sha256 is not None:
        return {
            "status": "CONFIRMED",
            "speaker_id": "VOICEOVER",
            "role": "voiceover",
            "visibility": "voiceover",
            "confidence": _confidence(segment.get("confidence"), "audio segment confidence"),
            "evidence_sha256": source_audio_sha256,
        }
    return {
        "status": "PENDING_ASSIGNMENT",
        "reason": "multiple_visible_lip_sync_candidates" if candidates else "no_single_visible_lip_sync_candidate",
        "candidate_speaker_ids": [str(track["speaker_id"]) for track in candidates],
    }


def _audio_lines(
    audio: Mapping[str, Any],
    *,
    duration_ms: int,
    cuts: Sequence[Mapping[str, Any]],
    tracks: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    source_audio_sha = audio.get("source_audio_sha256")
    source_audio_sha256 = _sha256(source_audio_sha, "audio_contract.source_audio_sha256") if source_audio_sha else None
    raw = audio.get("segments", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise SourceContentTimelineError("audio_contract.segments must be an array")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise SourceContentTimelineError(f"audio_contract.segments[{index}] must be an object")
        window = _window(item, f"audio_contract.segments[{index}]", duration_ms=duration_ms)
        line_id = _text(item.get("segment_id") or f"A{index:03d}", f"audio_contract.segments[{index}].segment_id")
        if line_id in seen:
            raise SourceContentTimelineError("audio_contract segment_id values must be unique")
        seen.add(line_id)
        raw_kind = str(item.get("kind") or item.get("type") or "speech").strip().lower()
        content_type = "sung" if raw_kind in {"sung", "singing"} else "spoken" if raw_kind in _SPEECH_KINDS else "instrumental" if raw_kind in {"music", "instrumental"} else "inaudible"
        text = str(item.get("text") or "").strip()
        if content_type in {"spoken", "sung"} and not text:
            content_type = "inaudible"
        row: dict[str, Any] = {
            "line_id": line_id,
            **window,
            "cut_ids": _cut_ids(cuts, window),
            "content_type": content_type,
            "text": text if text else content_type,
            "confidence": _confidence(item.get("confidence"), f"audio_contract.segments[{index}].confidence"),
            "evidence_sha256": source_audio_sha256,
        }
        if content_type in {"spoken", "sung"}:
            row["speaker_assignment"] = _speaker_assignment(
                segment=item,
                window=window,
                tracks=tracks,
                source_audio_sha256=source_audio_sha256,
            )
        else:
            row["speaker_assignment"] = {"status": "NOT_APPLICABLE"}
        rows.append(row)
    return rows, source_audio_sha256


def _placement(item: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    explicit = item.get("placement")
    if explicit is not None:
        if not isinstance(explicit, Mapping):
            raise SourceContentTimelineError(f"{field}.placement must be an object")
        candidate = dict(explicit)
    else:
        candidate = {
            key: item[key]
            for key in (
                "bbox",
                "start_rect",
                "end_rect",
                "keyframes",
                "z_index",
                "layer_relation",
                "attachment",
                "coordinate_space",
                "start_rotation_deg",
                "end_rotation_deg",
                "start_opacity",
                "end_opacity",
                "motion_phase",
                "motion_path",
                "interpolation",
            )
            if item.get(key) is not None
        }
    try:
        return json.loads(json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise SourceContentTimelineError(f"{field}.placement must be canonical JSON") from exc


def _source_window(item: Mapping[str, Any], field: str, *, duration_ms: int) -> dict[str, int]:
    if item.get("start_ms") is not None or item.get("end_ms") is not None:
        return _window(item, field, duration_ms=duration_ms)
    start_us = item.get("start_us")
    end_us = item.get("end_us")
    if isinstance(start_us, bool) or not isinstance(start_us, int) or start_us < 0:
        raise SourceContentTimelineError(f"{field}.start_us is invalid")
    if isinstance(end_us, bool) or not isinstance(end_us, int) or end_us <= start_us:
        raise SourceContentTimelineError(f"{field}.end_us is invalid")
    return _window(
        {"start_ms": start_us // 1000, "end_ms": (end_us + 999) // 1000},
        field,
        duration_ms=duration_ms,
    )


def _source_evidence_sha256(item: Mapping[str, Any], *, field: str) -> str:
    direct = item.get("evidence_sha256")
    if direct is not None:
        return _sha256(direct, f"{field}.evidence_sha256")
    evidence_refs = item.get("evidence_refs")
    if evidence_refs is not None:
        return _canonical_sha256({"evidence_refs": evidence_refs})
    return _canonical_sha256(dict(item))


def _visible_text(
    analysis: Mapping[str, Any], *, duration_ms: int, cuts: Sequence[Mapping[str, Any]], source_overlay_contract: Mapping[str, Any] | None
) -> tuple[list[dict[str, Any]], int]:
    key = "ocr_intervals" if "ocr_intervals" in analysis else "visible_text_intervals"
    raw = analysis.get(key, [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise SourceContentTimelineError(f"{key} must be an array")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise SourceContentTimelineError(f"{key}[{index}] must be an object")
        window = _window(item, f"{key}[{index}]", duration_ms=duration_ms)
        rows.append(
            {
                "text_id": _text(item.get("text_id") or f"T{index:03d}", f"{key}[{index}].text_id"),
                "kind": _text(item.get("kind") or "visible_text", f"{key}[{index}].kind"),
                "text": _text(item.get("text"), f"{key}[{index}].text"),
                **window,
                "cut_ids": _cut_ids(cuts, window),
                "confidence": _confidence(item.get("confidence"), f"{key}[{index}].confidence"),
                "evidence_sha256": _sha256(item.get("evidence_sha256"), f"{key}[{index}].evidence_sha256"),
                "placement": _placement(item, field=f"{key}[{index}]"),
            }
        )
    source_events = analysis.get("source_events", [])
    if not isinstance(source_events, Sequence) or isinstance(source_events, (str, bytes, bytearray)):
        raise SourceContentTimelineError("source_events must be an array")
    for index, item in enumerate(source_events, start=1):
        if not isinstance(item, Mapping):
            raise SourceContentTimelineError(f"source_events[{index}] must be an object")
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in _VISIBLE_TEXT_EVENT_KINDS:
            continue
        window = _source_window(item, f"source_events[{index}]", duration_ms=duration_ms)
        raw_event_id = item.get("event")
        event_id = str(index if raw_event_id is None else raw_event_id).strip()
        if not event_id:
            raise SourceContentTimelineError(f"source_events[{index}].event is required")
        rows.append(
            {
                "text_id": f"event:{event_id}",
                "kind": kind,
                "text": _text(item.get("text"), f"source_events[{index}].text"),
                **window,
                "cut_ids": _cut_ids(cuts, window),
                "confidence": _confidence(item.get("confidence"), f"source_events[{index}].confidence"),
                "evidence_sha256": _source_evidence_sha256(item, field=f"source_events[{index}]"),
                "placement": _placement(item, field=f"source_events[{index}]"),
            }
        )
    if source_overlay_contract is not None:
        raw_cuts = source_overlay_contract.get("cuts", [])
        if not isinstance(raw_cuts, Sequence) or isinstance(raw_cuts, (str, bytes, bytearray)):
            raise SourceContentTimelineError("source_overlay_contract.cuts must be an array")
        for cut_index, cut in enumerate(raw_cuts, start=1):
            if not isinstance(cut, Mapping):
                raise SourceContentTimelineError(f"source_overlay_contract.cuts[{cut_index}] must be an object")
            overlays = cut.get("source_overlays", [])
            if not isinstance(overlays, Sequence) or isinstance(overlays, (str, bytes, bytearray)):
                raise SourceContentTimelineError(f"source_overlay_contract.cuts[{cut_index}].source_overlays must be an array")
            for overlay_index, overlay in enumerate(overlays, start=1):
                if not isinstance(overlay, Mapping):
                    raise SourceContentTimelineError(f"source overlay {cut_index}:{overlay_index} must be an object")
                observed_text = str(overlay.get("observed_text") or "").strip()
                if not observed_text:
                    continue
                field = f"source overlay {cut_index}:{overlay_index}"
                window = _source_window(overlay, field, duration_ms=duration_ms)
                overlay_id = _text(overlay.get("overlay_id") or f"{cut_index}_{overlay_index}", f"{field}.overlay_id")
                rows.append(
                    {
                        "text_id": f"overlay:{overlay_id}",
                        "kind": _text(overlay.get("kind") or "visible_text", f"{field}.kind"),
                        "text": observed_text,
                        **window,
                        "cut_ids": _cut_ids(cuts, window),
                        "confidence": _confidence(overlay.get("confidence"), f"{field}.confidence"),
                        "evidence_sha256": _source_evidence_sha256(overlay, field=field),
                        "placement": _placement(overlay, field=field),
                    }
                )
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        evidence_key = _canonical_sha256(
            {
                key: row[key]
                for key in ("kind", "text", "start_ms", "end_ms", "cut_ids", "confidence", "evidence_sha256", "placement")
            }
        )
        if evidence_key not in seen:
            seen.add(evidence_key)
            unique.append(row)
    unique.sort(key=lambda row: (row["start_ms"], row["end_ms"], row["text_id"]))
    return unique, 1 if key in analysis else 0


def _music_events(audio: Mapping[str, Any], *, duration_ms: int, cuts: Sequence[Mapping[str, Any]], source_audio_sha256: str | None) -> list[dict[str, Any]]:
    values = [audio.get("audio_events", []), audio.get("meaningful_silence", [])]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            raise SourceContentTimelineError("audio event evidence must be an array")
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, Mapping):
                raise SourceContentTimelineError("audio event must be an object")
            kind = str(item.get("kind") or "").strip().lower()
            if kind not in _MUSIC_KINDS:
                continue
            window = _window(item, "audio event", duration_ms=duration_ms)
            event_id = _text(item.get("event_id") or f"E{len(rows) + index:03d}", "audio event.event_id")
            if event_id in seen:
                continue
            seen.add(event_id)
            rows.append(
                {
                    "event_id": event_id,
                    "kind": kind,
                    **window,
                    "cut_ids": _cut_ids(cuts, window),
                    "evidence_sha256": _sha256(item.get("evidence_sha256"), "audio event.evidence_sha256") if item.get("evidence_sha256") else source_audio_sha256,
                }
            )
    return rows


def build_source_content_timeline(
    *,
    source_video_sha256: str,
    source_dynamics_analysis: Mapping[str, Any],
    audio_contract: Mapping[str, Any],
    source_overlay_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze source content observations from one completed dynamics/ASR pass."""

    if not isinstance(source_dynamics_analysis, Mapping):
        raise SourceContentTimelineError("source_dynamics_analysis is required")
    if not isinstance(audio_contract, Mapping):
        raise SourceContentTimelineError("audio_contract is required")
    if source_overlay_contract is not None and not isinstance(source_overlay_contract, Mapping):
        raise SourceContentTimelineError("source_overlay_contract must be an object")
    source_sha = _sha256(source_video_sha256, "source_video_sha256")
    cuts, duration_ms = _source_cuts(source_dynamics_analysis)
    if duration_ms <= 0:
        raise SourceContentTimelineError("source duration must be positive")
    audio_duration = audio_contract.get("source_duration_ms")
    if audio_duration is not None and _ms(audio_duration, "audio_contract.source_duration_ms") < duration_ms:
        raise SourceContentTimelineError("audio_contract.source_duration_ms ends before the decoded source")
    tracks = _visible_tracks(source_dynamics_analysis, duration_ms=duration_ms)
    visible_text, ocr_passes = _visible_text(
        source_dynamics_analysis,
        duration_ms=duration_ms,
        cuts=cuts,
        source_overlay_contract=source_overlay_contract,
    )
    audio_lines, source_audio_sha = _audio_lines(audio_contract, duration_ms=duration_ms, cuts=cuts, tracks=tracks)
    music_events = _music_events(audio_contract, duration_ms=duration_ms, cuts=cuts, source_audio_sha256=source_audio_sha)
    uncertainty = [
        {
            "line_id": line["line_id"],
            "status": "PENDING_ASSIGNMENT",
            "reason": line["speaker_assignment"]["reason"],
        }
        for line in audio_lines
        if line["speaker_assignment"].get("status") == "PENDING_ASSIGNMENT"
    ]
    timeline = {
        "contract": "source-content-timeline/v1",
        "source_video_sha256": source_sha,
        "source_duration_ms": duration_ms,
        "source_dynamics_sha256": _canonical_sha256(dict(source_dynamics_analysis)),
        "audio_contract_sha256": _canonical_sha256(dict(audio_contract)),
        "analysis_passes": {
            "dynamics": 1,
            "asr": 1,
            "ocr": ocr_passes,
            "speaker_assignment": 1 if any(line["content_type"] in {"spoken", "sung"} for line in audio_lines) else 0,
        },
        "reanalysis_forbidden": True,
        "cuts": cuts,
        "visible_text": visible_text,
        "audio_lines": audio_lines,
        "music_events": music_events,
        "uncertainties": uncertainty,
    }
    return {**timeline, "contract_sha256": _canonical_sha256(timeline)}


__all__ = ["SourceContentTimelineError", "build_source_content_timeline"]
