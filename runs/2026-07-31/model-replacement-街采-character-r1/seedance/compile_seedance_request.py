from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import unicodedata
from pathlib import Path


RUN = Path(__file__).resolve().parents[1]
REPO = Path(r"C:\Users\zhaocx04\Documents\New project\usfr-server")
RUNTIME = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\runtime-skills\seedance-20")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    value = "".join(c for c in value if not unicodedata.category(c).startswith("P") or c == "'")
    return re.sub(r"\s+", " ", value).strip().lower()


def spoken_line(line_id: str, cut_ids: list[str], start_ms: int, end_ms: int, text: str,
                speaker_id: str, role: str, visibility: str) -> dict:
    return {
        "line_id": line_id,
        "cut_id": cut_ids[0],
        "source_content_timeline_sha256": sha256(RUN / "analysis" / "source_dynamics_analysis.json"),
        "content_type": "spoken",
        "speaker_assignment": {
            "status": "CONFIRMED",
            "speaker_id": speaker_id,
            "role": role,
            "visibility": visibility,
            "confidence": 0.99,
            "evidence_sha256": sha256(RUN / "analysis" / "source_fidelity_contract.json"),
        },
        "speaker": {
            "id": speaker_id,
            "role": role,
            "visibility": visibility,
            "voice_policy": "preserve the exact original Japanese source audio in final postproduction",
        },
        "language": {"bcp47": "ja-JP", "script": "Jpan"},
        "time": {
            "time_base": "output_global_ms",
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_ms": end_ms - start_ms,
            "duration_is_derived": True,
            "cut_ids": cut_ids,
            "cross_cut_reason": "one continuous spoken phrase across semantic phase Cuts" if len(cut_ids) > 1 else None,
            "planned_safe_margin_ms": 0,
        },
        "text": {
            "exact": text,
            "normalized": normalize_text(text),
            "pronunciation_notes": ["Match @Video1 Japanese timing, pauses, mouth rhythm and phrase endpoint exactly."],
        },
        "delivery": {
            "tone": "natural friendly street-interview delivery",
            "pace": "match the source phrase timing exactly",
            "emphasis": [],
            "volume": "natural close interview level",
            "breath": "match source breath grouping",
            "mic_distance": "source-matched handheld interview microphone distance",
            "accent_or_locale": "natural ja-JP",
        },
        "lip_sync": {
            "priority": "high" if visibility == "on_camera" else "none",
            "face_visibility": "clear frontal three-quarter mouth" if visibility == "on_camera" else "speaker remains off camera",
            "occlusion": "none",
            "head_motion_limit": "small source-matched conversational micro-motion",
            "articulation": "match source mouth shapes and phrase endpoint" if visibility == "on_camera" else "no visible mouth",
            "allowed_tolerance_ms": 100,
            "speaker_face_ref": "CHARACTER_A" if visibility == "on_camera" else "OFF_CAMERA_INTERVIEWER",
        },
        "proof_events": [],
        "foley_events": [],
        "silence_windows": [],
        "music_policy": {"mode": "none", "windows": []},
        "claim_ids": [],
        "qc_contract": {
            "asr_profile": "ja-JP-source-preserve-v1",
            "speaker_check": "role+visibility",
            "language_check": "BCP-47 ja-JP",
            "line_tolerance_ms": 100,
            "proof_sync_tolerance_ms": 100,
            "foley_sync_tolerance_ms": 100,
            "hard_fail_flags": ["word_change", "wrong_speaker", "lip_sync_drift"],
        },
        "criticality": "H",
    }


def main() -> None:
    OUT = RUN / "seedance"
    OUT.mkdir(parents=True, exist_ok=True)
    compiler = load_module("seedance_prompt_compiler", REPO / "scripts" / "seedance_prompt_compiler.py")

    segment = {
        "segment_id": "S01",
        "start_ms": 0,
        "output_global_start_ms": 0,
        "duration_ms": 10867,
        "cut_ids": ["C01", "C02", "C03", "C04", "C05", "C06", "C07"],
        "opening_state": "Night street interview: CHARACTER_A center-right; silver microphone enters lower left.",
        "reference_roles": [
            {"slot": 1, "tag": "@Image1", "role": "approved C01-C03 visuals; ignore captions/graphics"},
            {"slot": 2, "tag": "@Image2", "role": "approved C04-C07 visuals; ignore captions/graphics"},
            {"slot": 3, "tag": "@Image3", "role": "target fair East Asian face, dark eyes, low dark-brown ponytail and wispy bangs only; exclude uniform/room"},
        ],
        "shots": [{
            "shot_id": "C01-C07",
            "start_ms": 0,
            "end_ms": 10867,
            "shot_scale": "one continuous vertical 9:16 handheld medium-full smartphone interview shot with mild wide-angle perspective",
            "scene": "@Image1/@Image2 night alley, vending-machine panel left, warm street lamps; subject center-right",
            "camera": "@Video1 timing, wide composition, microphone path and slight handheld sway; no cut/reframe",
            "lighting": "stable cool left fill and warm street practicals",
            "performance": "C01 listen; C02 bright smile; C03 speak and light laugh; C04 amused listen/head tilt; C05 conversational micro-motion; C06 playful emphasis; C07 laugh and bring hands together low",
            "action": "C01-C07 in order with source gaze, blinks, restrained motion, exact Japanese mouth timing and lower-left microphone",
            "endpoint": "10.867s: warm broad smile, both hands low near each other, microphone left, natural active final frame",
            "product_or_ui_truth": "no product/UI; @Image3 face/hair only; keep white mock-neck top, black knee-length skirt, earrings",
            "commercial_proof": "stable target identity through the exact source performance",
            "transition": "one uninterrupted take to the natural endpoint; no edit, fade, freeze, loop or filler",
            "continuity": "same face, ponytail, bangs, wardrobe, hands, gaze, microphone, alley and light",
            "audio": "exact original Japanese speakers, timing, pauses, laugh and night-street ambience from @Video1; no music, extra words or replacement voice",
            "factor_ids": [
                *[f"HFH.{cut}.{factor}" for cut in ["C01","C02","C03","C04","C05","C06","C07"] for factor in ["SCENE.TOPOLOGY","CAMERA.HANDHELD","LIGHTING.MATCH","IDENTITY.TARGET","WARDROBE.KEEP","PERFORMANCE.STATE","ACTION.ENDPOINT","CONTINUITY","AUDIO.LIPSYNC"]]
            ],
        }],
        "locks": [
            "@Video1 controls motion/timing/camera/microphone/environment, never identity; @Image3 controls face/hair only",
            "@Image1/@Image2 carry ordered C01-C07 visuals; captions/SUGO are post-only and model areas stay glyph-free",
            "one 10.867s take; keep white top, black skirt, earrings, lower-left microphone and alley",
        ],
        "negative_constraints": [
            "no generated text, caption, emoji, SUGO, logo or watermark",
            "no source face, drift, uniform, tie, vest, deformation or bad hands",
            "no new person, interviewer face, microphone change, cut, zoom, scene change, freeze, black frame or music",
        ],
        "no_speech_contracts": [{
            "cut_id": "C07",
            "speech_mode": "none",
            "allowed_audio": ["source laugh", "night-street ambience"],
            "forbidden_audio": ["new dialogue", "voiceover", "background music"],
        }],
    }

    lines = [
        spoken_line("D-C01", ["C01"], 0, 1280, "今話題の『SUGO』知ってる？", "INTERVIEWER", "off-camera male interviewer", "off_camera"),
        spoken_line("D-C02-C03", ["C02", "C03"], 1860, 3900, "もちろん！私もう沼ってるよ！", "CHARACTER_A", "on-camera interviewee", "on_camera"),
        spoken_line("D-C04", ["C04"], 4320, 5120, "ぶっちゃけどう？", "INTERVIEWER", "off-camera male interviewer", "off_camera"),
        spoken_line("D-C05-C06", ["C05", "C06"], 5920, 9740, "毎日刺激的すぎて、正直やばい。", "CHARACTER_A", "on-camera interviewee", "on_camera"),
    ]

    skill_files = {
        "seedance-20": RUNTIME / "SKILL.md",
        "seedance-prompt": RUNTIME / "skills" / "seedance-prompt" / "SKILL.md",
        "seedance-antislop": RUNTIME / "skills" / "seedance-antislop" / "SKILL.md",
        "seedance-camera": RUNTIME / "skills" / "seedance-camera" / "SKILL.md",
        "seedance-characters": RUNTIME / "skills" / "seedance-characters" / "SKILL.md",
        "seedance-motion": RUNTIME / "skills" / "seedance-motion" / "SKILL.md",
        "seedance-lighting": RUNTIME / "skills" / "seedance-lighting" / "SKILL.md",
        "seedance-audio": RUNTIME / "skills" / "seedance-audio" / "SKILL.md",
    }
    factors = {"camera": True, "characters": True, "motion": True, "lighting": True, "audio": True, "performance": True}
    checks = {name: True for name in compiler.COMPILER_CHECKS}
    artifact = compiler.compile_prompt(segment=segment, line_contracts=lines, factors=factors,
                                       skill_files=skill_files, compiler_checks=checks)
    compiler.validate_compiled_prompt(artifact, skill_files=skill_files, line_contracts=lines)
    prompt = artifact["prompt"]
    if len(prompt) > 5000:
        raise RuntimeError(f"prompt too long: {len(prompt)}")

    scope = {
        "schema_version": "usfr-timeline-scope-receipt/v1",
        "status": "not_applicable",
        "reason": "the single generated region covers C01-C07 from frame zero through the decoded endpoint; no opaque UI or end card exists",
    }
    outputs = {
        "structured_segment.json": segment,
        "line_contracts.json": lines,
        "compiled_prompt.json": artifact,
        "scope_receipt.json": scope,
    }
    for name, value in outputs.items():
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "segment_01_prompt.txt").write_text(prompt, encoding="utf-8")
    print(json.dumps({"prompt_chars": len(prompt), "compiler_output_sha256": artifact["compiler"]["output_sha256"], "loaded_modules": artifact["compiler"]["loaded_modules"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
