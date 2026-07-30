from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import ReplicationError


_LANGUAGES = {
    "en": {"bcp47": "en-US", "script": "Latn"},
    "ja": {"bcp47": "ja-JP", "script": "Jpan"},
    "ko": {"bcp47": "ko-KR", "script": "Kore"},
    "fr": {"bcp47": "fr-FR", "script": "Latn"},
    "de": {"bcp47": "de-DE", "script": "Latn"},
    "es": {"bcp47": "es-ES", "script": "Latn"},
    "pt": {"bcp47": "pt-BR", "script": "Latn"},
    "id": {"bcp47": "id-ID", "script": "Latn"},
    "zh": {"bcp47": "zh-CN", "script": "Hans"},
    "und": {"bcp47": "und", "script": "Zyyy"},
}


def _read_json(*, object_store: Any, object_key: str, sha256: str) -> dict[str, Any]:
    if object_store is None or not callable(getattr(object_store, "download_to", None)):
        raise ReplicationError("REVIEW_NOT_ALLOWED", "审核证据暂不可用", retryable=True, http_status=503)
    with tempfile.TemporaryDirectory(prefix="usfr-public-lines-") as directory:
        destination = Path(directory) / "artifact.json"
        object_store.download_to(
            object_key=object_key,
            destination=destination,
            expected_sha256=sha256,
        )
        raw = destination.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256 or len(raw) > 4 * 1024 * 1024:
        raise ReplicationError("REVIEW_NOT_ALLOWED", "审核证据校验失败", http_status=409)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplicationError("REVIEW_NOT_ALLOWED", "审核证据格式无效", http_status=409) from exc
    if not isinstance(value, dict):
        raise ReplicationError("REVIEW_NOT_ALLOWED", "审核证据格式无效", http_status=409)
    return value


def _source_review_artifacts(job_store: Any, job_id: str) -> tuple[Any, tuple[Any, Any] | None]:
    artifacts = tuple(job_store.list_artifacts(job_id))
    by_kind = {
        kind: [item for item in artifacts if str(getattr(item, "kind", "")) == kind]
        for kind in (
            "source_content_timeline",
            "performance_audio_source_contract",
            "audio_lyrics_beat_contract",
        )
    }
    if len(by_kind["source_content_timeline"]) != 1:
        raise ReplicationError("REVIEW_NOT_ALLOWED", "文字脚本缺少唯一的源内容时间轴", http_status=409)
    audio_present = bool(by_kind["performance_audio_source_contract"] or by_kind["audio_lyrics_beat_contract"])
    if not audio_present:
        return by_kind["source_content_timeline"][0], None
    if any(len(by_kind[kind]) != 1 for kind in ("performance_audio_source_contract", "audio_lyrics_beat_contract")):
        raise ReplicationError("REVIEW_NOT_ALLOWED", "音频审核证据不完整", http_status=409)
    return by_kind["source_content_timeline"][0], (
        by_kind["performance_audio_source_contract"][0],
        by_kind["audio_lyrics_beat_contract"][0],
    )


def _candidate_lines(
    *,
    script: Mapping[str, Any],
    timeline: Mapping[str, Any],
    timeline_sha256: str,
    output_language: str,
) -> list[dict[str, Any]]:
    cuts = script.get("cuts")
    performance = script.get("performance_line_candidates")
    audio_lines = timeline.get("audio_lines")
    if (
        not isinstance(cuts, list)
        or not isinstance(performance, Mapping)
        or performance.get("contract") != "performance-line-candidate/v1"
        or performance.get("status") != "PENDING_CONFIRMATION"
        or not isinstance(performance.get("cuts"), list)
        or not isinstance(audio_lines, list)
    ):
        raise ReplicationError("REVIEW_NOT_ALLOWED", "脚本缺少可确认的音频台词", http_status=409)
    cuts_by_id = {str(item.get("cut_id") or ""): item for item in cuts if isinstance(item, Mapping)}
    language = dict(_LANGUAGES.get(output_language, _LANGUAGES["und"]))
    try:
        from scripts.line_contract import normalize_text
    except ImportError as exc:
        raise ReplicationError("REVIEW_NOT_ALLOWED", "台词校验器不可用", http_status=503) from exc
    results: list[dict[str, Any]] = []
    used_line_ids: set[str] = set()
    for index, candidate in enumerate(performance["cuts"], start=1):
        if not isinstance(candidate, Mapping):
            raise ReplicationError("REVIEW_NOT_ALLOWED", "音频台词候选无效", http_status=409)
        cut_id = str(candidate.get("cut_id") or "")
        cut = cuts_by_id.get(cut_id)
        window = candidate.get("source_time")
        if not isinstance(cut, Mapping) or not isinstance(window, Mapping):
            raise ReplicationError("REVIEW_NOT_ALLOWED", "音频台词没有对应镜头", http_status=409)
        start_ms = int(window.get("start_ms"))
        end_ms = int(window.get("end_ms"))
        matches = [
            row for row in audio_lines
            if isinstance(row, Mapping)
            and cut_id in list(row.get("cut_ids") or [])
            and max(start_ms, int(row.get("start_ms", -1))) < min(end_ms, int(row.get("end_ms", -1)))
        ]
        if len(matches) != 1:
            raise ReplicationError("REVIEW_NOT_ALLOWED", "音频台词与镜头无法唯一对应", http_status=409)
        source_line = matches[0]
        line_id = str(source_line.get("line_id") or f"LINE-{index:03d}")
        if line_id in used_line_ids:
            raise ReplicationError("REVIEW_NOT_ALLOWED", "音频台词编号重复", http_status=409)
        used_line_ids.add(line_id)
        assignment = source_line.get("speaker_assignment")
        if not isinstance(assignment, Mapping):
            raise ReplicationError("REVIEW_NOT_ALLOWED", "音频台词缺少人物归属", http_status=409)
        confirmed = assignment.get("status") == "CONFIRMED"
        speaker_id = str(assignment.get("speaker_id") or "PENDING_SPEAKER")
        role = str(assignment.get("role") or "pending")
        visibility = str(assignment.get("visibility") or "on_camera")
        exact = str(cut.get("dialogue") or candidate.get("exact_sung_text") or "").strip()
        if not exact:
            raise ReplicationError("REVIEW_NOT_ALLOWED", "音频台词文字为空", http_status=409)
        content_type = str(source_line.get("content_type") or "spoken")
        results.append(
            {
                "line_id": line_id,
                "cut_id": cut_id,
                "source_content_timeline_sha256": timeline_sha256,
                "content_type": content_type,
                "speaker_assignment": dict(assignment),
                "speaker": {
                    "id": speaker_id,
                    "role": role,
                    "visibility": visibility,
                    "voice_policy": "generic rights-cleared target voice; no source voice imitation",
                },
                "language": language,
                "time": {
                    "time_base": "output_global_ms",
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "duration_ms": end_ms - start_ms,
                    "duration_is_derived": True,
                    "segment_start_ms": None,
                    "segment_end_ms": None,
                    "cut_ids": [cut_id],
                    "cross_cut_reason": None,
                    "planned_safe_margin_ms": 0,
                },
                "text": {
                    "exact": exact,
                    "normalized": normalize_text(exact).lower(),
                    "pronunciation_notes": [],
                },
                "delivery": {
                    "tone": str(cut.get("delivery") or "natural"),
                    "pace": "source-matched",
                    "emphasis": [],
                    "volume": "natural",
                    "breath": "source-matched",
                    "mic_distance": "source-matched",
                    "accent_or_locale": "natural target locale",
                },
                "lip_sync": {
                    "priority": "high" if confirmed and visibility == "on_camera" else "medium",
                    "face_visibility": str((candidate.get("lip_sync") or {}).get("face_visibility") or visibility),
                    "occlusion": "source-matched",
                    "head_motion_limit": "source-matched",
                    "articulation": str((candidate.get("lip_sync") or {}).get("articulation") or "clear"),
                    "allowed_tolerance_ms": 200,
                    "speaker_face_ref": speaker_id,
                },
                "proof_events": [],
                "foley_events": [],
                "silence_windows": [],
                "music_policy": {"mode": "preserve_source", "windows": []},
                "claim_ids": [],
                "qc_contract": {
                    "asr_profile": f"{language['bcp47']}-canonical-v1",
                    "speaker_check": "exact speaker assignment",
                    "language_check": f"BCP-47 detector {language['bcp47']}",
                    "line_tolerance_ms": 350,
                    "proof_sync_tolerance_ms": 200,
                    "foley_sync_tolerance_ms": 200,
                    "hard_fail_flags": ["word_change", "speaker_change", "language_change"],
                },
                "criticality": str(candidate.get("criticality") or "H").upper(),
            }
        )
    return results


def script_review_line_contracts(
    *,
    job_store: Any,
    object_store: Any,
    job_id: str,
    manifest: Any,
    script: Mapping[str, Any],
) -> list[dict[str, Any]] | None:
    timeline_artifact, audio_artifacts = _source_review_artifacts(job_store, job_id)
    if audio_artifacts is None:
        return None
    timeline = _read_json(
        object_store=object_store,
        object_key=str(timeline_artifact.object_key),
        sha256=str(timeline_artifact.sha256),
    )
    request = getattr(manifest, "request", None)
    direct_patch = getattr(request, "direct_patch", None)
    if isinstance(direct_patch, Mapping) and isinstance(direct_patch.get("line_contracts"), list):
        return [dict(item) for item in direct_patch["line_contracts"] if isinstance(item, Mapping)]
    language = str(getattr(manifest, "output_language", None) or script.get("output_language") or "und")
    return _candidate_lines(
        script=script,
        timeline=timeline,
        timeline_sha256=str(timeline_artifact.sha256),
        output_language=language,
    )


def approved_script_contract(
    *,
    job_store: Any,
    object_store: Any,
    job_id: str,
    manifest: Any,
) -> dict[str, Any]:
    script = _read_json(
        object_store=object_store,
        object_key=str(manifest.object_key),
        sha256=str(manifest.sha256),
    )
    timeline_artifact, audio_artifacts = _source_review_artifacts(job_store, job_id)
    timeline = _read_json(
        object_store=object_store,
        object_key=str(timeline_artifact.object_key),
        sha256=str(timeline_artifact.sha256),
    )
    raw_locks = script.get("visible_text_locks")
    locks_sha256 = str(script.get("visible_text_locks_sha256") or "").lower()
    if not isinstance(raw_locks, list) or not locks_sha256:
        raise ReplicationError("REVIEW_NOT_ALLOWED", "文字脚本缺少可见文字确认锁", http_status=409)
    try:
        from .visible_text_contract import validate_visible_text_locks, visible_text_locks_sha256

        locks = validate_visible_text_locks(raw_locks, timeline=timeline)
        if visible_text_locks_sha256(locks) != locks_sha256:
            raise ValueError("visible text lock SHA mismatch")
    except Exception as exc:
        raise ReplicationError(
            "REVIEW_NOT_ALLOWED",
            "文字脚本中的可见文字未与源视频证据一致",
            details={"reason": str(exc)},
            http_status=409,
        ) from exc
    lines = (
        script_review_line_contracts(
            job_store=job_store,
            object_store=object_store,
            job_id=job_id,
            manifest=manifest,
            script=script,
        )
        if audio_artifacts is not None
        else []
    )
    try:
        from scripts.line_contract import validate_line_contracts

        canonical = validate_line_contracts(lines or [])
    except Exception as exc:
        raise ReplicationError(
            "REVIEW_NOT_ALLOWED",
            "请先在文字脚本中确认每句台词对应的人物",
            user_action_required=True,
            details={"reason": str(exc)},
            http_status=409,
        ) from exc
    if canonical:
        timeline_shas = {str(line.get("source_content_timeline_sha256") or "") for line in canonical}
        if timeline_shas != {str(timeline_artifact.sha256)}:
            raise ReplicationError("REVIEW_NOT_ALLOWED", "台词未绑定当前唯一声音时间轴", http_status=409)
    return {
        "line_contracts": canonical,
        "source_content_timeline_sha256": str(timeline_artifact.sha256),
        "visible_text_locks": locks,
        "visible_text_locks_sha256": locks_sha256,
    }


__all__ = ["approved_script_contract", "script_review_line_contracts"]
