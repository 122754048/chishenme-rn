from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any


class VoiceoverTtsFallbackError(ValueError):
    pass


_WINDOW_PREFIX = re.compile(r"^\s*\[[0-9:.]+\s*-\s*[0-9:.]+\]\s*")
_SPEAKER_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*\s*:\s*")
_ELIGIBLE_FAILURES = {
    "missing_line",
    "omitted_words",
    "wrong_words",
    "wrong_language",
    "absent_voiceover",
    "severe_timbre_drift",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sanitize_approved_voiceover_text(value: object) -> str:
    text = value if isinstance(value, str) else ""
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, list) and all(isinstance(item, Mapping) for item in parsed):
            text = " ".join(str(item.get("text", "")).strip() for item in parsed).strip()

    text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    text = _WINDOW_PREFIX.sub("", text, count=1)
    text = _SPEAKER_PREFIX.sub("", text, count=1).strip()
    if not text or "\ufffd" in text or "\x00" in text or _WINDOW_PREFIX.fullmatch(str(value).strip()):
        raise VoiceoverTtsFallbackError("approved voiceover text is empty or invalid")
    return text


def build_voiceover_tts_fallback_receipt(
    *,
    qc_receipt: Mapping[str, Any],
    approved_lines: Sequence[Mapping[str, Any]],
    attempted_block_ids: Collection[str],
) -> dict[str, Any]:
    if qc_receipt.get("contract") != "voiceover-targeted-qc/v1":
        raise VoiceoverTtsFallbackError("invalid targeted QC contract")
    if qc_receipt.get("picture_passed") is not True or qc_receipt.get("failure_scope") != "voiceover_only":
        raise VoiceoverTtsFallbackError("TTS requires a picture-passed voiceover-only failure")

    failures = set(qc_receipt.get("failure_types") or ())
    if not failures or not failures.issubset(_ELIGIBLE_FAILURES):
        raise VoiceoverTtsFallbackError("targeted QC failure is not TTS-eligible")

    assembled_sha = str(qc_receipt.get("assembled_video_sha256", ""))
    script_sha = str(qc_receipt.get("approved_script_sha256", ""))
    if not _SHA256.fullmatch(assembled_sha) or not _SHA256.fullmatch(script_sha):
        raise VoiceoverTtsFallbackError("targeted QC input SHA is invalid")

    wanted_ids = list(qc_receipt.get("line_ids") or ())
    lines_by_id = {str(line.get("line_id")): line for line in approved_lines}
    normalized_lines: list[dict[str, Any]] = []
    for line_id in wanted_ids:
        line = lines_by_id.get(str(line_id))
        if line is None:
            raise VoiceoverTtsFallbackError("targeted QC line is absent from the approved script")
        if line.get("changed") is not True or line.get("content_type") != "spoken" or line.get("visibility") != "voiceover":
            raise VoiceoverTtsFallbackError("only changed off-camera spoken voiceover is eligible")

        speaker = str(line.get("speaker", "")).strip()
        locale = str(line.get("locale", "")).strip()
        start_ms = line.get("start_ms")
        end_ms = line.get("end_ms")
        reference_start_ms = line.get("reference_start_ms")
        reference_end_ms = line.get("reference_end_ms")
        if not speaker or not locale or not all(isinstance(value, int) for value in (start_ms, end_ms, reference_start_ms, reference_end_ms)):
            raise VoiceoverTtsFallbackError("voiceover speaker, locale, or reference window is unresolved")
        if start_ms < 0 or end_ms <= start_ms or reference_start_ms < 0 or reference_end_ms <= reference_start_ms:
            raise VoiceoverTtsFallbackError("voiceover or reference window is invalid")

        plain_text = sanitize_approved_voiceover_text(line.get("text"))
        normalized_lines.append({
            "line_ids": [str(line_id)],
            "plain_text": plain_text,
            "speaker": speaker,
            "locale": locale,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "reference_start_ms": reference_start_ms,
            "reference_end_ms": reference_end_ms,
        })

    blocks: list[dict[str, Any]] = []
    for line in normalized_lines:
        previous = blocks[-1] if blocks else None
        if (
            previous is not None
            and previous["speaker"] == line["speaker"]
            and previous["locale"] == line["locale"]
            and previous["end_ms"] == line["start_ms"]
            and previous["reference_end_ms"] == line["reference_start_ms"]
        ):
            previous["line_ids"].extend(line["line_ids"])
            previous["plain_text"] = f'{previous["plain_text"]} {line["plain_text"]}'
            previous["end_ms"] = line["end_ms"]
            previous["reference_end_ms"] = line["reference_end_ms"]
        else:
            blocks.append(dict(line))

    for block in blocks:
        block_authority = {key: block[key] for key in (
            "line_ids", "speaker", "locale", "start_ms", "end_ms", "reference_start_ms", "reference_end_ms"
        )}
        block_id = _canonical_sha256(block_authority)
        if block_id in attempted_block_ids:
            raise VoiceoverTtsFallbackError("voiceover block already attempted")
        block["block_id"] = block_id
        block["attempt_count"] = 0

    if not blocks:
        raise VoiceoverTtsFallbackError("targeted QC did not identify an eligible voiceover line")

    receipt: dict[str, Any] = {
        "contract": "voiceover-tts-fallback-receipt/v1",
        "assembled_video_sha256": assembled_sha,
        "approved_script_sha256": script_sha,
        "failure_types": sorted(failures),
        "blocks": blocks,
    }
    receipt["receipt_sha256"] = _canonical_sha256(receipt)
    return receipt
