"""Deterministic exact dialogue and audio-window contracts.

The module is deliberately provider-neutral.  It freezes the words, speaker,
locale and integer-millisecond windows before a Seedance prompt is compiled;
the final prompt can only render this contract, never rewrite it.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence


_STATUSES = {"succeeded", "failed", "skipped", "timeout"}
_FORBIDDEN_VOICE_TERMS = (
    "voiceprint",
    "voice print",
    "imitate source",
    "copy source",
    "clone source",
)
_VISIBILITIES = {"on_camera", "off_camera", "voiceover"}
_LIP_SYNC_PRIORITIES = {"high", "medium", "low", "none"}
_MUSIC_MODES = {"none", "preserve_source", "approved"}
_CONTENT_TYPES = {"spoken", "sung", "instrumental", "inaudible"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("line text must be a string")
    normalized = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    normalized = "".join(
        char
        for char in normalized
        if not unicodedata.category(char).startswith("P") or char in {"'", "’"}
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _int_ms(name: str, value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of milliseconds")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _window(window: Mapping[str, Any], *, name: str) -> None:
    if not isinstance(window, Mapping):
        raise ValueError(f"{name} must be an object")
    start = _int_ms(f"{name}.start_ms", window.get("start_ms"))
    end = _int_ms(f"{name}.end_ms", window.get("end_ms"))
    if end <= start:
        raise ValueError(f"{name}.end_ms must be greater than start_ms")


def _non_empty(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _validate_source_content_binding(result: Mapping[str, Any]) -> None:
    """Validate the optional, immutable link to one frozen source timeline.

    Legacy exact-line contracts remain readable, but once a source timeline is
    supplied all binding fields are mandatory and cannot be only partly set.
    """

    fields = {"source_content_timeline_sha256", "content_type", "speaker_assignment"}
    present = fields & set(result)
    if not present:
        return
    missing = sorted(fields - set(result))
    if missing:
        raise ValueError(f"source-content line binding missing: {', '.join(missing)}")
    timeline_sha = result["source_content_timeline_sha256"]
    if not isinstance(timeline_sha, str) or _SHA256.fullmatch(timeline_sha) is None:
        raise ValueError("source_content_timeline_sha256 must be a lowercase SHA-256")
    content_type = result["content_type"]
    if content_type not in _CONTENT_TYPES:
        raise ValueError("content_type is invalid")
    assignment = result["speaker_assignment"]
    if not isinstance(assignment, Mapping):
        raise ValueError("speaker_assignment must be an object")
    status = assignment.get("status")
    if status == "PENDING_ASSIGNMENT":
        raise ValueError("PENDING_ASSIGNMENT must be resolved before Invocation B")
    if content_type in {"spoken", "sung"}:
        required = {"status", "speaker_id", "role", "visibility", "confidence", "evidence_sha256"}
        missing = sorted(required - set(assignment))
        if missing or status != "CONFIRMED":
            raise ValueError("speaker_assignment must be CONFIRMED for spoken or sung content")
        if assignment["speaker_id"] != result["speaker"]["id"]:
            raise ValueError("speaker_assignment.speaker_id must match speaker.id")
        if assignment["role"] != result["speaker"]["role"]:
            raise ValueError("speaker_assignment.role must match speaker.role")
        if assignment["visibility"] != result["speaker"]["visibility"]:
            raise ValueError("speaker_assignment.visibility must match speaker.visibility")
        confidence = assignment["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
            raise ValueError("speaker_assignment.confidence must be between 0 and 1")
        evidence_sha = assignment["evidence_sha256"]
        if not isinstance(evidence_sha, str) or _SHA256.fullmatch(evidence_sha) is None:
            raise ValueError("speaker_assignment.evidence_sha256 must be a lowercase SHA-256")
    elif status != "NOT_APPLICABLE":
        raise ValueError("speaker_assignment must be NOT_APPLICABLE for non-verbal content")


def _string_list(name: str, value: Any, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{name} must be a {'non-empty ' if not allow_empty else ''}array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{name} must contain non-empty strings")
    return list(value)


def _event_id(name: str, event: Mapping[str, Any]) -> str:
    if not isinstance(event, Mapping):
        raise ValueError(f"{name} must be an object")
    return _non_empty(f"{name}.id", event.get("id"))


def _validate_proof_event(event: Any, name: str) -> None:
    if not isinstance(event, Mapping):
        raise ValueError(f"{name} must be an object")
    _event_id(name, event)
    _non_empty(f"{name}.kind", event.get("kind"))
    _string_list(f"{name}.modality", event.get("modality"), allow_empty=False)
    _window(event, name=name)
    _string_list(f"{name}.claim_ids", event.get("claim_ids"))
    if not isinstance(event.get("required"), bool) or not isinstance(event.get("hard_fail"), bool):
        raise ValueError(f"{name}.required and hard_fail must be boolean")


def _validate_foley_event(event: Any, name: str) -> None:
    if not isinstance(event, Mapping):
        raise ValueError(f"{name} must be an object")
    _event_id(name, event)
    _non_empty(f"{name}.kind", event.get("kind"))
    _window(event, name=name)
    _non_empty(f"{name}.relation", event.get("relation"))
    _int_ms(f"{name}.onset_tolerance_ms", event.get("onset_tolerance_ms"))
    if not isinstance(event.get("required"), bool):
        raise ValueError(f"{name}.required must be boolean")
    _non_empty(f"{name}.loudness_policy", event.get("loudness_policy"))


def _validate_silence_window(window: Any, name: str) -> None:
    if not isinstance(window, Mapping):
        raise ValueError(f"{name} must be an object")
    _event_id(name, window)
    _non_empty(f"{name}.kind", window.get("kind"))
    _window(window, name=name)
    quiet = window.get("min_quiet_dbfs")
    if isinstance(quiet, bool) or not isinstance(quiet, (int, float)):
        raise ValueError(f"{name}.min_quiet_dbfs must be numeric")
    if not isinstance(window.get("required"), bool):
        raise ValueError(f"{name}.required must be boolean")


def _validate_audio_contract(result: dict[str, Any]) -> None:
    delivery = result["delivery"]
    if not isinstance(delivery, Mapping):
        raise ValueError("delivery must be an object")
    for field in ("tone", "pace", "volume", "breath", "mic_distance", "accent_or_locale"):
        _non_empty(f"delivery.{field}", delivery.get(field))
    _string_list("delivery.emphasis", delivery.get("emphasis"))

    lip_sync = result["lip_sync"]
    if not isinstance(lip_sync, Mapping):
        raise ValueError("lip_sync must be an object")
    if lip_sync.get("priority") not in _LIP_SYNC_PRIORITIES:
        raise ValueError("lip_sync.priority is invalid")
    for field in ("face_visibility", "occlusion", "head_motion_limit", "articulation", "speaker_face_ref"):
        _non_empty(f"lip_sync.{field}", lip_sync.get(field))
    _int_ms("lip_sync.allowed_tolerance_ms", lip_sync.get("allowed_tolerance_ms"))

    for field, validator in (
        ("proof_events", _validate_proof_event),
        ("foley_events", _validate_foley_event),
        ("silence_windows", _validate_silence_window),
    ):
        events = result[field]
        if not isinstance(events, list):
            raise ValueError(f"{field} must be an array")
        ids: set[str] = set()
        for index, event in enumerate(events):
            event_id = _event_id(f"{field}[{index}]", event)
            if event_id in ids:
                raise ValueError(f"{field} repeats id {event_id}")
            ids.add(event_id)
            validator(event, f"{field}[{index}]")

    music = result["music_policy"]
    if not isinstance(music, Mapping) or music.get("mode") not in _MUSIC_MODES:
        raise ValueError("music_policy.mode is invalid")
    windows = music.get("windows")
    if not isinstance(windows, list):
        raise ValueError("music_policy.windows must be an array")
    for index, window in enumerate(windows):
        _window(window, name=f"music_policy.windows[{index}]")
    if music.get("mode") == "none" and windows:
        raise ValueError("music_policy=none cannot contain music windows")

    qc = result["qc_contract"]
    if not isinstance(qc, Mapping):
        raise ValueError("qc_contract must be an object")
    for field in ("asr_profile", "speaker_check", "language_check"):
        _non_empty(f"qc_contract.{field}", qc.get(field))
    for field in ("line_tolerance_ms", "proof_sync_tolerance_ms", "foley_sync_tolerance_ms"):
        _int_ms(f"qc_contract.{field}", qc.get(field))
    _string_list("qc_contract.hard_fail_flags", qc.get("hard_fail_flags"), allow_empty=False)


def _contains_forbidden_voice_reference(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in {"reference_audio", "reference_audios", "voiceprint", "source_voiceprint"}:
                return True
            if _contains_forbidden_voice_reference(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_voice_reference(item) for item in value)
    elif isinstance(value, str):
        lowered = value.lower()
        return any(term in lowered for term in _FORBIDDEN_VOICE_TERMS)
    return False


def canonical_line(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("line contract must be an object")
    required = {"line_id", "cut_id", "speaker", "language", "time", "text", "delivery", "lip_sync", "proof_events", "foley_events", "silence_windows", "music_policy", "claim_ids", "qc_contract", "criticality"}
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"line contract missing required fields: {', '.join(missing)}")
    result = deepcopy(dict(value))
    if not isinstance(result["line_id"], str) or not result["line_id"]:
        raise ValueError("line_id is required")
    if not isinstance(result["cut_id"], str) or not result["cut_id"]:
        raise ValueError("cut_id is required")
    speaker = result["speaker"]
    if not isinstance(speaker, Mapping) or not speaker.get("id") or not speaker.get("role"):
        raise ValueError("speaker id and role are required")
    if speaker.get("visibility") not in _VISIBILITIES:
        raise ValueError("speaker.visibility is invalid")
    _non_empty("speaker.voice_policy", speaker.get("voice_policy"))
    if _contains_forbidden_voice_reference(speaker):
        raise ValueError("unauthorised voiceprint or source-voice reference")
    _validate_source_content_binding(result)
    language = result["language"]
    if not isinstance(language, Mapping) or not language.get("bcp47") or not language.get("script"):
        raise ValueError("language bcp47 and script are required")
    time = result["time"]
    if not isinstance(time, Mapping):
        raise ValueError("time must be an object")
    start = _int_ms("time.start_ms", time.get("start_ms"))
    end = _int_ms("time.end_ms", time.get("end_ms"))
    if end <= start:
        raise ValueError("time.end_ms must be greater than start_ms")
    duration = _int_ms("time.duration_ms", time.get("duration_ms"))
    if duration != end - start:
        raise ValueError("time.duration_ms must be derived from start_ms and end_ms")
    if time.get("duration_is_derived") is not True:
        raise ValueError("duration_is_derived must be true")
    if time.get("time_base") not in {"output_global_ms", "segment_local_ms"}:
        raise ValueError("time.time_base is invalid")
    cut_ids = time.get("cut_ids")
    _string_list("time.cut_ids", cut_ids, allow_empty=False)
    if result["cut_id"] not in cut_ids:
        raise ValueError("time.cut_ids must contain cut_id")
    _int_ms("time.planned_safe_margin_ms", time.get("planned_safe_margin_ms"))
    cross_cut_reason = time.get("cross_cut_reason")
    if len(cut_ids) > 1:
        _non_empty("time.cross_cut_reason", cross_cut_reason)
    elif cross_cut_reason is not None and not isinstance(cross_cut_reason, str):
        raise ValueError("time.cross_cut_reason must be a string or null")
    text = result["text"]
    if not isinstance(text, Mapping) or not isinstance(text.get("exact"), str) or not text["exact"].strip():
        raise ValueError("text.exact is required")
    expected_normalized = normalize_text(text["exact"]).lower()
    if text.get("normalized") != expected_normalized:
        raise ValueError("text.normalized must be canonicalized from text.exact")
    _string_list("text.pronunciation_notes", text.get("pronunciation_notes"))
    _string_list("claim_ids", result["claim_ids"])
    if result.get("criticality") not in {"H", "M", "L"}:
        raise ValueError("criticality must be H, M, or L")
    _validate_audio_contract(result)
    if _contains_forbidden_voice_reference(result):
        raise ValueError("unauthorised voiceprint/reference audio in line contract")
    return result


def line_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_frozen_line(canonical_line(value)))).hexdigest()


def _frozen_line(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return only fields frozen at script approval.

    Segment-local coordinates and worker bookkeeping are added after approval;
    they must not invalidate the approved spoken/audio contract digest.
    """
    line = canonical_line(value)
    frozen = deepcopy(line)
    time = dict(frozen["time"])
    time = {
        key: time[key]
        for key in (
            "start_ms",
            "end_ms",
            "duration_ms",
            "duration_is_derived",
            "cut_ids",
            "cross_cut_reason",
            "planned_safe_margin_ms",
        )
    }
    frozen["time"] = time
    for collection in ("proof_events", "foley_events", "silence_windows"):
        cleaned_events = []
        for event in frozen.get(collection, []):
            item = dict(event)
            for key in (
                "output_global_start_ms",
                "output_global_end_ms",
                "segment_start_ms",
                "segment_end_ms",
                "time_base",
            ):
                item.pop(key, None)
            cleaned_events.append(item)
        frozen[collection] = cleaned_events
    for key in ("candidate_region_id", "segment_id"):
        frozen.pop(key, None)
    return frozen


def validate_line_contracts(
    lines: Sequence[Mapping[str, Any]],
    *,
    no_speech_cuts: Sequence[Mapping[str, Any]] | None = None,
    segment_bounds: Sequence[Mapping[str, Any]] | None = None,
    approved_lines: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes)):
        raise ValueError("lines must be an array")
    canonical = [canonical_line(line) for line in lines]
    ids = [line["line_id"] for line in canonical]
    if len(ids) != len(set(ids)):
        raise ValueError("line_id values must be unique")
    if approved_lines is not None:
        approved = {line["line_id"]: canonical_line(line) for line in approved_lines}
        if set(ids) != set(approved):
            missing = sorted(set(approved) - set(ids))
            extra = sorted(set(ids) - set(approved))
            raise ValueError(
                f"approved line set changed; missing={missing}, extra={extra}"
            )
        for line in canonical:
            prior = approved.get(line["line_id"])
            if prior is None:
                raise ValueError("approved line is missing from final contract")
            frozen_line = _frozen_line(line)
            frozen_prior = _frozen_line(prior)
            if frozen_line != frozen_prior:
                for field in (
                    "cut_id",
                    "source_content_timeline_sha256",
                    "content_type",
                    "speaker_assignment",
                    "speaker",
                    "language",
                    "time",
                    "text",
                    "delivery",
                    "lip_sync",
                    "proof_events",
                    "foley_events",
                    "silence_windows",
                    "music_policy",
                    "claim_ids",
                    "qc_contract",
                    "criticality",
                ):
                    if frozen_line.get(field) != frozen_prior.get(field):
                        raise ValueError(f"approved line mutation: {line['line_id']}:{field}")
                raise ValueError(f"approved line mutation: {line['line_id']}")
    if no_speech_cuts is not None:
        seen = {line["cut_id"] for line in canonical}
        for item in no_speech_cuts:
            if item.get("speech_mode") != "none":
                raise ValueError("no-speech cuts must declare speech_mode=none")
            cut_id = item.get("cut_id")
            if not isinstance(cut_id, str) or not cut_id or cut_id in seen:
                raise ValueError("no-speech cut_id is invalid or already has a line")
            if "forbidden_audio" not in item or not isinstance(item["forbidden_audio"], list):
                raise ValueError("no-speech contract must declare forbidden_audio")
    if segment_bounds is not None:
        rebind_line_contracts(canonical, segment_bounds)
    return canonical


def rebind_line_contracts(lines: Sequence[Mapping[str, Any]], segments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(segments, Sequence) or not segments:
        raise ValueError("segment plan is required")
    normalized_segments = []
    for segment in segments:
        start = _int_ms("segment.start_ms", segment.get("start_ms"))
        end = _int_ms("segment.end_ms", segment.get("end_ms"))
        if end <= start or not segment.get("segment_id"):
            raise ValueError("segment bounds are invalid")
        normalized_segments.append((start, end, str(segment["segment_id"]), set(segment.get("cut_ids") or [])))
    rebound = []
    for source in lines:
        line = canonical_line(source)
        start = line["time"]["start_ms"]
        end = line["time"]["end_ms"]
        matches = [item for item in normalized_segments if start >= item[0] and end <= item[1]]
        if len(matches) != 1:
            raise ValueError(f"line crosses or falls outside a segment: {line['line_id']}")
        seg_start, _seg_end, segment_id, cut_ids = matches[0]
        if cut_ids and line["cut_id"] not in cut_ids:
            raise ValueError(f"line cut is not covered by segment: {line['line_id']}")
        line["segment_id"] = segment_id
        line["time"]["output_global_start_ms"] = start
        line["time"]["output_global_end_ms"] = end
        line["time"]["segment_start_ms"] = start - seg_start
        line["time"]["segment_end_ms"] = end - seg_start
        line["time"]["time_base"] = "segment_local_ms"
        for collection in ("proof_events", "foley_events", "silence_windows"):
            for event in line.get(collection, []):
                event_start = event["start_ms"]
                event_end = event["end_ms"]
                event_matches = [
                    item
                    for item in normalized_segments
                    if event_start >= item[0] and event_end <= item[1]
                ]
                if len(event_matches) != 1 or event_matches[0][2] != segment_id:
                    raise ValueError(
                        f"{collection} event crosses or falls outside a segment: {event.get('id')}"
                    )
                event["output_global_start_ms"] = event_start
                event["output_global_end_ms"] = event_end
                event["segment_start_ms"] = event_start - seg_start
                event["segment_end_ms"] = event_end - seg_start
                event["time_base"] = "segment_local_ms"
        rebound.append(line)
    return rebound


def _event_local_start(event: Mapping[str, Any]) -> int:
    value = event.get("segment_start_ms")
    return value if isinstance(value, int) and not isinstance(value, bool) else event["start_ms"]


def _event_local_end(event: Mapping[str, Any]) -> int:
    value = event.get("segment_end_ms")
    return value if isinstance(value, int) and not isinstance(value, bool) else event["end_ms"]


def render_line_for_prompt(line: Mapping[str, Any]) -> str:
    value = canonical_line(line)
    text = value["text"]["exact"]
    time = value["time"]
    start_ms = time.get("segment_start_ms") if time.get("time_base") == "segment_local_ms" else time["start_ms"]
    end_ms = time.get("segment_end_ms") if time.get("time_base") == "segment_local_ms" else time["end_ms"]
    start = start_ms / 1000
    end = end_ms / 1000
    speaker_info = value["speaker"]
    speaker = speaker_info["id"]
    visibility = speaker_info["visibility"]
    locale = value["language"]["bcp47"]
    delivery = value["delivery"]
    lip_sync = value["lip_sync"]
    parts = [
        f"Dialogue {start:.2f}-{end:.2f}s ({locale}, {visibility}): {speaker} says exactly, \"{text}\".",
        f"{delivery['tone']}; {delivery['pace']}; {delivery['volume']}; {delivery['breath']}; mic distance {delivery['mic_distance']}; locale {delivery['accent_or_locale']}.",
        f"Lip-sync {lip_sync['priority']}; face {lip_sync['face_visibility']}; head motion {lip_sync['head_motion_limit']}; articulation {lip_sync['articulation']}; tolerance {lip_sync['allowed_tolerance_ms']}ms.",
    ]
    if value["proof_events"]:
        parts.append(
            "Proof windows: "
            + "; ".join(
                f"{event['id']} {_event_local_start(event)/1000:.2f}-{_event_local_end(event)/1000:.2f}s ({event['kind']})"
                for event in value["proof_events"]
            )
            + "."
        )
    if value["foley_events"]:
        parts.append(
            "Foley windows: "
            + "; ".join(
                f"{event['id']} {_event_local_start(event)/1000:.2f}-{_event_local_end(event)/1000:.2f}s ({event['kind']})"
                for event in value["foley_events"]
            )
            + "."
        )
    if value["silence_windows"]:
        parts.append(
            "Silence windows: "
            + "; ".join(
                f"{event['id']} {_event_local_start(event)/1000:.2f}-{_event_local_end(event)/1000:.2f}s at or below {event['min_quiet_dbfs']} dBFS"
                for event in value["silence_windows"]
            )
            + "."
        )
    if value["music_policy"]["mode"] == "none":
        parts.append("No music.")
    else:
        parts.append(f"Music policy: {value['music_policy']['mode']}.")
    parts.append("Do not paraphrase, add, repeat, or assign the line to another speaker.")
    return " ".join(parts)


def render_no_speech(contract: Mapping[str, Any]) -> str:
    if not isinstance(contract, Mapping) or contract.get("speech_mode") != "none":
        raise ValueError("speech_mode=none is required")
    return "No dialogue"
