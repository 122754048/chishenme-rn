from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


RUN = Path(r"C:\Users\zhaocx04\Documents\New project\replication_runs\2026-07-30\usfr-d169ace38231")
ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
SEED = Path(r"C:\Users\zhaocx04\.codex\skills\seedance-20")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


router = load_module("skill_router", ROOT / "scripts" / "skill_router.py")
compiler = load_module("seedance_prompt_compiler", ROOT / "scripts" / "seedance_prompt_compiler.py")
line_contract_module = load_module("line_contract", ROOT / "scripts" / "line_contract.py")

factors = {
    "performance": True,
    "characters": True,
    "camera": True,
    "motion": True,
    "lighting": True,
    "audio": True,
    "multi_shot": True,
    "continuity": True,
}
route = router.build_skill_route(
    generated_regions=1,
    factors=factors,
    overlay_required=False,
    app_store_url_present=False,
)
dump(RUN / "seedance" / "skill_route.json", route)

skill_files = {
    "seedance-20": SEED / "SKILL.md",
    "seedance-prompt": SEED / "skills" / "seedance-prompt" / "SKILL.md",
    "seedance-antislop": SEED / "skills" / "seedance-antislop" / "SKILL.md",
    "seedance-characters": SEED / "skills" / "seedance-characters" / "SKILL.md",
    "seedance-camera": SEED / "skills" / "seedance-camera" / "SKILL.md",
    "seedance-motion": SEED / "skills" / "seedance-motion" / "SKILL.md",
    "seedance-lighting": SEED / "skills" / "seedance-lighting" / "SKILL.md",
    "seedance-audio": SEED / "skills" / "seedance-audio" / "SKILL.md",
    "seedance-sequence": SEED / "skills" / "seedance-sequence" / "SKILL.md",
}

source_timeline_sha = sha(RUN / "analysis" / "source_dynamics_analysis.json")
speaker_evidence_sha = sha(RUN / "inputs" / "new_model_image.png")


def line(line_id, cut_id, cut_ids, start, end, text, proof, foley, silence):
    return {
        "line_id": line_id,
        "cut_id": cut_id,
        "source_content_timeline_sha256": source_timeline_sha,
        "content_type": "spoken",
        "speaker_assignment": {
            "status": "CONFIRMED",
            "speaker_id": "CHARACTER_A",
            "role": "creator",
            "visibility": "on_camera",
            "confidence": 0.99,
            "evidence_sha256": speaker_evidence_sha,
        },
        "speaker": {
            "id": "CHARACTER_A",
            "role": "creator",
            "visibility": "on_camera",
            "voice_policy": "generic rights-cleared natural adult male voice",
        },
        "language": {"bcp47": "en-US", "script": "Latn"},
        "time": {
            "time_base": "output_global_ms",
            "start_ms": start,
            "end_ms": end,
            "duration_ms": end - start,
            "duration_is_derived": True,
            "cut_ids": cut_ids,
            "cross_cut_reason": "continuous action phase" if len(cut_ids) > 1 else None,
            "planned_safe_margin_ms": 80,
        },
        "text": {"exact": text, "normalized": line_contract_module.normalize_text(text).lower(), "pronunciation_notes": []},
        "delivery": {
            "tone": "close-mic natural UGC",
            "pace": "brisk source-matched cadence",
            "emphasis": [],
            "volume": "natural conversational",
            "breath": "single clean phrase",
            "mic_distance": "close",
            "accent_or_locale": "natural en-US",
        },
        "lip_sync": {
            "priority": "high",
            "face_visibility": "clear frontal mouth",
            "occlusion": "none",
            "head_motion_limit": "small source-matched movement",
            "articulation": "clear natural consonants",
            "allowed_tolerance_ms": 180,
            "speaker_face_ref": "CHARACTER_A",
        },
        "proof_events": proof,
        "foley_events": foley,
        "silence_windows": silence,
        "music_policy": {"mode": "none", "windows": []},
        "claim_ids": [],
        "qc_contract": {
            "asr_profile": "en-US-canonical-v1",
            "speaker_check": "role+visible-face",
            "language_check": "BCP-47 en-US",
            "line_tolerance_ms": 300,
            "proof_sync_tolerance_ms": 220,
            "foley_sync_tolerance_ms": 180,
            "hard_fail_flags": ["word_change", "wrong_speaker", "line_outside_window", "background_music"],
        },
        "criticality": "H",
    }


def proof(event_id, kind, start, end):
    return [{"id": event_id, "kind": kind, "modality": ["visual", "audio"], "start_ms": start, "end_ms": end, "claim_ids": [], "required": True, "hard_fail": True}]


def foley(event_id, kind, start, end, relation="under_action"):
    return [{"id": event_id, "kind": kind, "start_ms": start, "end_ms": end, "relation": relation, "onset_tolerance_ms": 120, "required": True, "loudness_policy": "audible without masking dialogue"}]


def silence(event_id, start, end, kind="meaningful_pause"):
    return [{"id": event_id, "start_ms": start, "end_ms": end, "kind": kind, "min_quiet_dbfs": -30.0, "required": True}]


lines = [
    line("VO-001", "C01", ["C01"], 0, 1400, "All right, let's open this dress.", [], [], []),
    line("VO-002", "C02", ["C02", "C03"], 2120, 3620, "Okay, listen to the box.", proof("P02", "box_foregrounding", 2400, 3500), foley("F02", "box_handling", 2600, 3620), silence("S02", 1410, 2120, "pre_line_pause")),
    line("VO-003", "C04", ["C04", "C05", "C06"], 4500, 6740, "Lid comes straight off, and there it is.", proof("P03", "lid_removal_and_dress_reveal", 4500, 6740), foley("F03", "lid_tissue_and_box_contact", 4500, 6740), silence("S03", 3620, 4500, "action_pause")),
    line("VO-004", "C08", ["C08"], 8660, 9800, "The lace looks amazing.", proof("P04", "front_lace_visibility", 8660, 9800), foley("F04", "light_fabric_rustle", 8700, 9800), []),
    line("VO-005", "C10", ["C10"], 10520, 11420, "Look at these details.", proof("P05", "lace_edge_detail", 10520, 11420), foley("F05", "gentle_lace_touch", 10520, 11420), []),
    line("VO-006", "C12", ["C12"], 12100, 14780, "If you want a full little try-on test, tell me.", proof("P06", "stable_dress_cta_hold", 12100, 14780), [], []),
]
dump(RUN / "seedance" / "line_contracts.json", lines)

cuts = [
    ("C01", 0, 1410, "direct address", "small symmetrical hand gestures beside the microphone", "opening line completes; hands hover apart"),
    ("C02", 1410, 2120, "attention shift", "lower gaze and both hands toward the closed garment box", "hands arrive ready to contact the box"),
    ("C03", 2120, 3620, "box foreground", "grip the box, draw it closer and angle it toward camera", "box is prominent at lower center"),
    ("C04", 3620, 4490, "lid separation", "lift the neutral lid cleanly and tilt it screen-right", "lid clears the base; tissue-covered dress appears"),
    ("C05", 4490, 5490, "reveal", "set lid once to screen-right while left hand steadies the open box", "open box and white lace dress are visible"),
    ("C06", 5490, 6740, "dress lift", "grip the same dress with two hands and lift its upper portion vertically", "dress clears the box and reaches chest height"),
    ("C07", 6740, 8150, "tissue removal", "stabilize dress with right hand; peel plain tissue smoothly to screen-left", "tissue separates; V-neck lace front is unobstructed"),
    ("C08", 8150, 9810, "hero presentation", "square the dress upper bodice front-on and alternate gaze dress-to-lens", "lace, V-neck and sleeve details face camera"),
    ("C09", 9810, 10480, "stable hold", "make a tiny grip adjustment without changing dress orientation", "fingers are poised near lace details"),
    ("C10", 10480, 11480, "detail demonstration", "gently trace floral lace and scalloped edge; no button pressing", "details settle back into a clear front-facing hold"),
    ("C11", 11480, 12100, "CTA setup", "steady the same dress and re-establish direct eye contact", "dress remains centered; presenter ready to speak"),
    ("C12", 12100, 15000, "CTA and smile", "deliver CTA while holding the dress still; warm smile and brief wink near end", "natural final hold with dress fully visible"),
]

phase_action = (
    "C01 0-1.41 gesture; C02 1.41-2.12 hands to box; C03 2.12-3.62 box forward; "
    "C04 3.62-4.49 lid right/reveal; C05 4.49-5.49 lid exits; C06 5.49-6.74 dress to chest; "
    "C07 6.74-8.15 tissue left; C08 8.15-9.81 front hero; C09 9.81-10.48 reset grip; "
    "C10 10.48-11.48 trace lace; C11 11.48-12.10 eye contact; C12 12.10-15 CTA/smile/wink/hold"
)
factor_ids = [
    f"HFH.{cut_id}.{factor}"
    for cut_id, *_rest in cuts
    for factor in ("SCENE", "CAMERA", "LIGHTING", "PERFORMANCE", "MOTION", "ENDPOINT", "PRODUCT", "PROOF", "CONTINUITY", "AUDIO")
]
shots = [{
    "shot_id": "SINGLE_TAKE_C01_C12",
    "start_ms": 0,
    "end_ms": 15000,
    "shot_scale": "vertical medium close-up",
    "scene": "same room/table/mic/neutral box",
    "camera": "fixed frontal continuous take",
    "lighting": "stable warm sun from right",
    "performance": "source-paced seated gaze/mouth/gestures; stable identity/wardrobe",
    "action": phase_action,
    "endpoint": "natural smiling front-facing dress hold",
    "product_or_ui_truth": "same target white lace dress; neutral box/tissue",
    "commercial_proof": "visible construction only",
    "transition": "twelve physical phases, no edit",
    "continuity": "fixed person, set, directions and dress",
    "audio": "close-mic English; room/box/tissue/fabric sound; no music/clicks",
    "factor_ids": factor_ids,
}]

segment = {
    "segment_id": "S01",
    "start_ms": 0,
    "output_global_start_ms": 0,
    "duration_ms": 15000,
    "cut_ids": [c[0] for c in cuts],
    "shots": shots,
    "reference_roles": [
        {"slot": 1, "tag": "@Image1", "role": "approved visual storyboard"},
        {"slot": 2, "tag": "@Image2", "role": "target face only"},
        {"slot": 3, "tag": "@Image3", "role": "target dress only"},
    ],
    "locks": [],
    "negative_constraints": ["no source identity/console/PIXL/package, watermark/text, duplicates, bad hands, drift, redesign, edits, camera motion, freeze, black, music, clicks, extra speech/captions/claims"],
    "no_speech_contracts": [
        {"cut_id": "C07", "speech_mode": "none", "allowed_audio": ["room tone", "tissue/fabric Foley"], "forbidden_audio": ["speech", "music", "clicks"]},
        {"cut_id": "C09", "speech_mode": "none", "allowed_audio": ["room tone", "fabric Foley"], "forbidden_audio": ["speech", "music", "clicks"]},
        {"cut_id": "C11", "speech_mode": "none", "allowed_audio": ["room tone", "fabric Foley"], "forbidden_audio": ["speech", "music", "clicks"]},
    ],
}
dump(RUN / "seedance" / "segment_contract.json", segment)

story_manifest_sha = sha(RUN / "storyboards" / "storyboard_manifest.json")
board_sha = sha(RUN / "storyboards" / "segment_01_v1.png")
review_bindings = {
    "output_language": "en",
    "approved_script_sha256": sha(RUN / "analysis" / "reverse_storyboard_script.md"),
    "approved_storyboard_manifest_sha256": story_manifest_sha,
    "approved_storyboard_cut_sha256s": [board_sha] * 12,
    "segment_plan_sha256": sha(RUN / "analysis" / "segment_plan.json"),
}
checks = {name: True for name in compiler.COMPILER_CHECKS}
preview_parts = compiler._format_segment(segment)
preview_parts.extend(line_contract_module.render_line_for_prompt(item) for item in lines)
preview_parts.extend(compiler._validate_no_speech_contracts(segment["no_speech_contracts"], segment_cut_ids=segment["cut_ids"])[1])
print("preview_prompt_chars", len(" ".join(preview_parts)))
print("segment_chars", len(" ".join(compiler._format_segment(segment))))
print("line_chars", [len(line_contract_module.render_line_for_prompt(item)) for item in lines])
artifact = compiler.compile_prompt(
    segment=segment,
    line_contracts=lines,
    factors=factors,
    skill_files=skill_files,
    compiler_checks=checks,
    review_bindings=review_bindings,
)
compiler.validate_compiled_prompt(
    artifact,
    skill_files=skill_files,
    line_contracts=lines,
    expected_review_bindings=review_bindings,
)
dump(RUN / "seedance" / "compiled_prompt.json", artifact)
(RUN / "seedance" / "prompt.txt").write_text(artifact["prompt"] + "\n", encoding="utf-8")

input_contract = {
    "schema_version": "seedance-input-contract/v1",
    "segment_id": "S01",
    "segment_plan_sha256": review_bindings["segment_plan_sha256"],
    "approved_script_sha256": review_bindings["approved_script_sha256"],
    "approved_storyboard_manifest_sha256": story_manifest_sha,
    "approved_storyboard_sha256": board_sha,
    "source_video_sha256": sha(RUN / "inputs" / "source_video.mp4"),
    "source_window": {"start_ms": 0, "end_ms": 15000, "duration_ms": 15000},
    "reference_order": [
        {"provider_slot": "videoUrls[0]", "tag": "@Video1", "path": "inputs/source_video.mp4", "role": "motion/timing/camera/performance only"},
        {"provider_slot": "imageUrls[0]", "tag": "@Image1", "path": "storyboards/segment_01_v1.png", "sha256": board_sha, "role": "approved director storyboard"},
        {"provider_slot": "imageUrls[1]", "tag": "@Image2", "path": "inputs/new_model_image.png", "sha256": sha(RUN / "inputs" / "new_model_image.png"), "role": "target character identity"},
        {"provider_slot": "imageUrls[2]", "tag": "@Image3", "path": "inputs/new_product_image.jpeg", "sha256": sha(RUN / "inputs" / "new_product_image.jpeg"), "role": "target product truth"},
    ],
    "provider": {"model": "seedance-2.0-fast-token", "resolution": "720p", "ratio": "9:16", "duration": 15, "generateAudio": True, "realPersonMode": True},
    "target_change": "Replace source presenter identity with @Image2 while keeping source wardrobe; replace source console and packaging with @Image3 white lace dress in a neutral garment box.",
    "prompt_sha256": hashlib.sha256(artifact["prompt"].encode("utf-8")).hexdigest(),
    "compiler_output_sha256": artifact["compiler"]["output_sha256"],
    "skill_route_sha256": route["route_sha256"],
    "compiler_dependency_snapshot": artifact["compiler"]["dependency_snapshot"],
}
dump(RUN / "seedance" / "seedance_input_contract.json", input_contract)

print(json.dumps({
    "prompt_chars": len(artifact["prompt"]),
    "prompt_sha256": input_contract["prompt_sha256"],
    "compiler_output_sha256": artifact["compiler"]["output_sha256"],
    "route_sha256": route["route_sha256"],
}, indent=2))
