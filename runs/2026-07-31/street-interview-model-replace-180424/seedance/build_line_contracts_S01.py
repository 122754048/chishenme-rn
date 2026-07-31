from __future__ import annotations

import importlib.util
import json
from pathlib import Path


RUN = Path(__file__).resolve().parents[1]
LINE_MODULE_PATH = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\line_contract.py")
spec = importlib.util.spec_from_file_location("usfr_line_contract", LINE_MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("line contract module cannot be loaded")
line_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(line_module)

TIMELINE_SHA = "7ae251a9ea25e27680f9caa8cdf612c0ff7611adc5f73f9bb1ccdadd7d1b97f2"
MODEL_SHA = "062bbad5bb388fa16040e5254cb755ccd7584a38cf7d489944982fc50dec3e25"
AUDIO_SHA = "b1d67debce29bc015dfa3a14472db4529e73681fa71b9bf1c7fb79577d5b122f"


def make_line(*, line_id: str, cut_id: str, cut_ids: list[str], start_ms: int, end_ms: int,
              text: str, speaker_id: str, role: str, visibility: str, tone: str,
              pace: str, emphasis: list[str], breath: str, mic_distance: str,
              priority: str, face_visibility: str, head_motion: str,
              articulation: str, tolerance: int, cross_cut_reason: str | None = None,
              pronunciation_notes: list[str] | None = None) -> dict:
    evidence_sha = MODEL_SHA if visibility == "on_camera" else AUDIO_SHA
    face_ref = "@Image1" if visibility == "on_camera" else "INTERVIEWER_OFF_CAMERA"
    speaker_check = "CHARACTER_A visible face" if visibility == "on_camera" else "off-camera interviewer"
    hard_fail = ["word_change", "wrong_speaker", "mouth_desync"] if visibility == "on_camera" else ["word_change", "wrong_speaker", "copied_source_voice"]
    normalized = line_module.normalize_text(text).lower()
    return {
        "line_id": line_id,
        "cut_id": cut_id,
        "source_content_timeline_sha256": TIMELINE_SHA,
        "content_type": "spoken",
        "speaker_assignment": {
            "status": "CONFIRMED", "speaker_id": speaker_id, "role": role,
            "visibility": visibility, "confidence": 0.99, "evidence_sha256": evidence_sha,
        },
        "speaker": {
            "id": speaker_id, "role": role, "visibility": visibility,
            "voice_policy": "generic rights-cleared Japanese voice",
        },
        "language": {"bcp47": "ja-JP", "script": "Jpan"},
        "time": {
            "time_base": "output_global_ms", "start_ms": start_ms, "end_ms": end_ms,
            "duration_ms": end_ms - start_ms, "duration_is_derived": True,
            "cut_ids": cut_ids, "cross_cut_reason": cross_cut_reason,
            "planned_safe_margin_ms": 100,
        },
        "text": {"exact": text, "normalized": normalized, "pronunciation_notes": pronunciation_notes or []},
        "delivery": {
            "tone": tone, "pace": pace, "emphasis": emphasis, "volume": "natural",
            "breath": "one phrase", "mic_distance": "near microphone", "accent_or_locale": "ja-JP",
        },
        "lip_sync": {
            "priority": priority, "face_visibility": "visible mouth" if visibility == "on_camera" else "off camera",
            "occlusion": "none" if visibility == "on_camera" else "n/a",
            "head_motion_limit": "small" if visibility == "on_camera" else "n/a", "articulation": "clear",
            "allowed_tolerance_ms": tolerance, "speaker_face_ref": face_ref,
        },
        "proof_events": [], "foley_events": [], "silence_windows": [],
        "music_policy": {"mode": "none", "windows": []},
        "claim_ids": [],
        "qc_contract": {
            "asr_profile": "ja-JP-canonical-v1", "speaker_check": speaker_check,
            "language_check": "BCP-47 ja-JP", "line_tolerance_ms": 250,
            "proof_sync_tolerance_ms": 250, "foley_sync_tolerance_ms": 250,
            "hard_fail_flags": hard_fail,
        },
        "criticality": "H",
    }


lines = [
    make_line(
        line_id="DIA-001", cut_id="C01", cut_ids=["C01", "C02"], start_ms=0, end_ms=1620,
        text="\u4eca\u8a71\u984c\u306e\u300eSUGO\u300f\u77e5\u3063\u3066\u308b\uff1f",
        speaker_id="INTERVIEWER", role="interviewer", visibility="off_camera",
        tone="casual street-interview question", pace="brisk", emphasis=["SUGO"],
        breath="single phrase", mic_distance="off-camera close", priority="low",
        face_visibility="speaker off camera", head_motion="not applicable",
        articulation="clear off-camera speech", tolerance=200,
        cross_cut_reason="one continuous off-camera question spans the first two performance phases",
        pronunciation_notes=["SUGO is pronounced \u30b9\u30b4"],
    ),
    make_line(
        line_id="DIA-002", cut_id="C03", cut_ids=["C03"], start_ms=1620, end_ms=2550,
        text="\u3082\u3061\u308d\u3093\uff01", speaker_id="CHARACTER_A", role="interviewee", visibility="on_camera",
        tone="bright confident reply", pace="brisk", emphasis=["\u3082\u3061\u308d\u3093"],
        breath="single short phrase", mic_distance="one forearm from microphone", priority="high",
        face_visibility="clear three-quarter frontal mouth", head_motion="small nod only",
        articulation="clear short vowel shapes", tolerance=160,
    ),
    make_line(
        line_id="DIA-003", cut_id="C04", cut_ids=["C04"], start_ms=2550, end_ms=4500,
        text="\u79c1\u3001\u3082\u3046\u6cbc\u3063\u3066\u308b\u3088\uff01", speaker_id="CHARACTER_A", role="interviewee", visibility="on_camera",
        tone="playful amused confession", pace="natural", emphasis=["\u6cbc\u3063\u3066\u308b"],
        breath="single phrase with laugh tail", mic_distance="one forearm from microphone", priority="high",
        face_visibility="clear three-quarter frontal mouth", head_motion="small tilt and sway",
        articulation="clear conversational mouth shapes", tolerance=180,
    ),
    make_line(
        line_id="DIA-004", cut_id="C05", cut_ids=["C05"], start_ms=4500, end_ms=6000,
        text="\u3076\u3063\u3061\u3083\u3051\u3001\u3069\u3046\uff1f", speaker_id="INTERVIEWER", role="interviewer", visibility="off_camera",
        tone="casual teasing follow-up", pace="brisk", emphasis=["\u3069\u3046"],
        breath="single phrase", mic_distance="off-camera close", priority="low",
        face_visibility="speaker off camera", head_motion="not applicable",
        articulation="clear off-camera speech", tolerance=200,
    ),
    make_line(
        line_id="DIA-005", cut_id="C06", cut_ids=["C06"], start_ms=6000, end_ms=8450,
        text="\u6bce\u65e5\u523a\u6fc0\u7684\u3059\u304e\u3066\u3001", speaker_id="CHARACTER_A", role="interviewee", visibility="on_camera",
        tone="animated playful answer", pace="natural", emphasis=["\u523a\u6fc0\u7684"],
        breath="first clause", mic_distance="one forearm from microphone", priority="high",
        face_visibility="clear three-quarter frontal mouth", head_motion="small lean and head motion",
        articulation="clear conversational mouth shapes", tolerance=180,
    ),
    make_line(
        line_id="DIA-006", cut_id="C07", cut_ids=["C07"], start_ms=8450, end_ms=10350,
        text="\u6b63\u76f4\u3084\u3070\u3044\u3002", speaker_id="CHARACTER_A", role="interviewee", visibility="on_camera",
        tone="playful embarrassed punchline", pace="natural", emphasis=["\u3084\u3070\u3044"],
        breath="short punchline with laugh", mic_distance="one forearm from microphone", priority="high",
        face_visibility="clear three-quarter frontal mouth", head_motion="small chin dip",
        articulation="clear punchline mouth shapes", tolerance=180,
    ),
]

for line in lines:
    line_module.canonical_line(line)

output = RUN / "seedance" / "line_contracts_S01.json"
output.write_text(json.dumps(lines, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": "passed", "line_count": len(lines)}, ensure_ascii=False))
