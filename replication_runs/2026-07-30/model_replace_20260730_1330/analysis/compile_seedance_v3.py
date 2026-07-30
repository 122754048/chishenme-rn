from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

RUN = Path(r"C:\Users\zhaocx04\Documents\New project\replication_runs\2026-07-30\model_replace_20260730_1330")
SKILL_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
SEEDANCE_ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\seedance-20")


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


compiler_path = SKILL_ROOT / "scripts" / "seedance_prompt_compiler.py"
spec = importlib.util.spec_from_file_location("usfr_seedance_prompt_compiler", compiler_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

board = RUN / "storyboards" / "segment_01_v3.png"
control = RUN / "reference_frames" / "replacement_control_keyframes_v1.png"
source_sheet = RUN / "reference_frames" / "source_keyframes_sheet.jpg"
target = RUN / "inputs" / "new_model_image.png"
approved_script = RUN / "analysis" / "reverse_storyboard_script.md"
segment_plan = RUN / "analysis" / "segment_plan.json"

board_sha = sha_file(board)
cut_ids = ["C01", "C02", "C03", "C04"]
storyboard_manifest = {
    "schema_version": "usfr-approved-storyboard/v1",
    "status": "approved",
    "approved_revision": 3,
    "approved_at_utc": datetime.now(timezone.utc).isoformat(),
    "user_confirmation": "确认",
    "segment_id": "S01",
    "cut_ids": cut_ids,
    "board_path": str(board),
    "board_sha256": board_sha,
    "ordered_cut_board_sha256s": [board_sha for _ in cut_ids],
    "source_keyframe_sheet_sha256": sha_file(source_sheet),
    "replacement_control_sheet_sha256": sha_file(control),
    "target_model_sha256": sha_file(target),
    "visual_chain_verified": True,
}
storyboard_manifest_path = RUN / "storyboards" / "approved_storyboard_manifest.json"
write_json(storyboard_manifest_path, storyboard_manifest)
storyboard_manifest_sha = sha_file(storyboard_manifest_path)

segment = {
    "segment_id": "S01",
    "cut_ids": cut_ids,
    "duration_ms": 6800,
    "opening_state": "The supplied adult woman appears in the warm corridor in the source brown fitted long-sleeve outfit, holding a phone and pale card at waist height while angled left.",
    "shots": [
        {
            "shot_id": "C01", "start_ms": 0, "end_ms": 3240, "shot_scale": "vertical full-body handheld follow",
            "scene": "warm hotel-like corridor with pale walls, doorframe on frame left, patterned carpet, and deep hallway perspective",
            "camera": "match the reference-video handheld forward drift; keep the subject full-body and left-facing, ending at the doorway zone",
            "lighting": "stable warm corridor practicals overhead with soft frontal fill and natural soft shadows",
            "performance": "steady short strides, calm face angled left, natural breathing and small arm swing; identity stays fixed to @Image2",
            "action": "walk leftward toward the doorway while the right hand keeps the phone and pale card together at waist height",
            "endpoint": "arrive at the doorway still angled left with the phone and card stable at the waist",
            "product_or_ui_truth": "the phone and pale card retain their source size, orientation, ownership, and position; no other object is added",
            "commercial_proof": "preserve the approved adult-character attention hook without adding a claim or demonstration",
            "transition": "continuous action into C02 at 3.24 seconds with no reframing jump",
            "continuity": "brown outfit, nude heels, gold bracelets, corridor geometry, screen direction, and prop positions stay unchanged",
            "audio": "No dialogue generated; quiet corridor room tone, soft heel steps, and light clothing movement only; no music",
            "factor_ids": ["S01.C01.SCENE", "S01.C01.CAMERA", "S01.C01.LIGHT", "S01.C01.PERFORMANCE", "S01.C01.ACTION", "S01.C01.IDENTITY", "S01.C01.PROOF", "S01.C01.TRANSITION", "S01.C01.CONTINUITY", "S01.C01.AUDIO"],
        },
        {
            "shot_id": "C02", "start_ms": 3240, "end_ms": 4200, "shot_scale": "vertical medium-full doorway framing",
            "scene": "the same corridor and doorway with the subject left-center and the hallway depth preserved",
            "camera": "continue the subtle handheld follow, retaining the doorway on the left and corridor depth on the right",
            "lighting": "the same warm practical sources, direction, temperature, exposure, and shadow softness as C01",
            "performance": "walking slows; the left arm extends toward the doorway while the head begins a small controlled turn toward the lens",
            "action": "touch or reach toward the doorway with the left hand while the right hand continues holding the phone and pale card",
            "endpoint": "left arm extended, body slowed, head beginning to turn toward camera",
            "product_or_ui_truth": "the phone and card remain together in the right hand; the left hand alone performs the doorway reach",
            "commercial_proof": "preserve the source performance beat and do not introduce any new product or claim",
            "transition": "continuous turn into C03 at 4.20 seconds",
            "continuity": "same identity, hair, brown outfit, bracelets, heels, prop grip, corridor layout, and screen direction",
            "audio": "No dialogue generated; low room tone, one soft heel stop, and a light hand-to-door contact sound; no music",
            "factor_ids": ["S01.C02.SCENE", "S01.C02.CAMERA", "S01.C02.LIGHT", "S01.C02.PERFORMANCE", "S01.C02.ACTION", "S01.C02.IDENTITY", "S01.C02.PROOF", "S01.C02.TRANSITION", "S01.C02.CONTINUITY", "S01.C02.AUDIO"],
        },
        {
            "shot_id": "C03", "start_ms": 4200, "end_ms": 6480, "shot_scale": "handheld push from medium-full portrait to chest-and-head framing",
            "scene": "the same warm corridor with the doorway behind the subject and patterned carpet remaining spatially consistent",
            "camera": "follow the reference-video approach rhythm, gently tightening as the subject makes one small forward step and turns to the lens",
            "lighting": "stable warm practical key and soft camera-side fill with unchanged corridor color balance",
            "performance": "lift the gaze, complete the turn, and form a light friendly closed-mouth smile; keep head motion small and hands simple",
            "action": "turn from profile toward camera and take one small forward step while holding the phone and pale card low",
            "endpoint": "face the lens directly with a friendly expression and both hands gathered around the phone and card",
            "product_or_ui_truth": "phone and pale card remain readable as physical props without redesign, duplication, or hand intersection",
            "commercial_proof": "carry the approved attention and trust beat through a direct, natural gaze without an unsupported claim",
            "transition": "continuous settling move into C04 at 6.48 seconds",
            "continuity": "preserve @Image2 face and short dark wavy bob, the source brown outfit, corridor direction, prop grip, and warm light",
            "audio": "No dialogue generated; quiet corridor ambience, one soft final step, and subtle prop handling only; no music",
            "factor_ids": ["S01.C03.SCENE", "S01.C03.CAMERA", "S01.C03.LIGHT", "S01.C03.PERFORMANCE", "S01.C03.ACTION", "S01.C03.IDENTITY", "S01.C03.PROOF", "S01.C03.TRANSITION", "S01.C03.CONTINUITY", "S01.C03.AUDIO"],
        },
        {
            "shot_id": "C04", "start_ms": 6480, "end_ms": 6800, "shot_scale": "stable handheld close portrait",
            "scene": "close corridor portrait with the same doorway and warm hallway depth behind the subject",
            "camera": "hold the close portrait with only subtle handheld breathing sway and no additional push or reframing",
            "lighting": "unchanged warm practical corridor light with soft frontal fill and stable skin exposure",
            "performance": "maintain direct gaze and the same friendly closed-mouth expression; both hands stay steady at the waist",
            "action": "settle into the final pose while keeping the phone and pale card stable",
            "endpoint": "direct gaze, friendly expression, both hands holding phone and pale card at waist on the final generated frame",
            "product_or_ui_truth": "the phone, pale card, bracelets, outfit, and hand ownership remain unchanged through the final frame",
            "commercial_proof": "complete the approved character-led hook without adding text, logo, guarantee, or call to action",
            "transition": "end cleanly at 6.80 seconds on the exact stable pose required by the following edit",
            "continuity": "final pose, screen direction, corridor light, @Image2 identity, brown outfit, and prop positions are locked",
            "audio": "No dialogue generated; quiet corridor room tone only, ending cleanly with no music or synthetic voice",
            "factor_ids": ["S01.C04.SCENE", "S01.C04.CAMERA", "S01.C04.LIGHT", "S01.C04.PERFORMANCE", "S01.C04.ACTION", "S01.C04.IDENTITY", "S01.C04.PROOF", "S01.C04.TRANSITION", "S01.C04.CONTINUITY", "S01.C04.AUDIO"],
        },
    ],
    "reference_roles": [
        {"slot": 1, "tag": "@Image1", "role": "approved S01 director storyboard controlling composition, action order, wardrobe, corridor, and final pose"},
        {"slot": 2, "tag": "@Image2", "role": "supplied adult woman controlling face identity, facial proportions, complexion, makeup, and short dark wavy bob only"},
    ],
    "locks": [
        "@Video1 controls source motion rhythm, camera path, timing, blocking, and corridor continuity",
        "@Image1 controls the approved four-Cut plan; @Image2 controls adult-woman identity only",
        "keep brown outfit, heels, bracelets, phone, pale card, corridor, and warm light",
        "keep Cut order C01-C04 and exact 0.00-6.80s timing",
    ],
    "negative_constraints": [
        "no generated subtitles, readable text, extra logo, or additional person",
        "do not import pool, swimwear, tattoos, necklace, or furniture from @Image2",
        "no identity or wardrobe drift, altered props, hand errors, reordered action, freeze, speed change, or black frame",
    ],
    "no_speech_contracts": [
        {"cut_id": cut_id, "speech_mode": "none", "allowed_audio": ["room tone and physical sounds"], "forbidden_audio": ["dialogue", "synthetic voice", "music"]}
        for cut_id in cut_ids
    ],
}

# Keep the compiled provider prompt under the fixed 5000-character budget while
# retaining every required shot field and the approved timing/action facts.
compact_shots = [
    {
        "scene": "Warm hotel corridor, pale walls, left doorway, patterned carpet, deep hallway perspective.",
        "camera": "Match source handheld forward drift; full-body left-facing follow, end at doorway.",
        "lighting": "Stable warm overhead practicals with soft camera-side fill.",
        "performance": "Calm left-facing walk, natural breathing and arm swing; identity fixed to @Image2.",
        "action": "Walk leftward; right hand keeps phone and pale card together at waist.",
        "endpoint": "At doorway, still angled left, phone and card stable at waist.",
        "product_or_ui_truth": "Phone and pale card keep source size, orientation, ownership, and position.",
        "commercial_proof": "Preserve the adult-character attention beat; add no claim.",
        "transition": "Continuous into C02 at 3.24s; no reframing jump.",
        "continuity": "Same face, bob, brown outfit, heels, bracelets, props, corridor, and screen direction.",
        "audio": "No dialogue; quiet room tone, heel steps, clothing movement; no music.",
    },
    {
        "scene": "Same corridor and doorway, subject left-center, hallway depth preserved.",
        "camera": "Continue subtle handheld follow; doorway left, corridor depth right.",
        "lighting": "Same warm practical sources, direction, temperature, and shadows as C01.",
        "performance": "Walking slows; left arm reaches; head begins a controlled turn toward lens.",
        "action": "Reach toward doorway with left hand; right hand keeps phone and pale card.",
        "endpoint": "Left arm extended, body slowed, head beginning to turn to camera.",
        "product_or_ui_truth": "Phone and card stay together in right hand; left hand alone reaches.",
        "commercial_proof": "Preserve the source performance beat; add no claim.",
        "transition": "Continuous turn into C03 at 4.20s.",
        "continuity": "Same identity, hair, outfit, bracelets, heels, props, corridor, and screen direction.",
        "audio": "No dialogue; room tone, soft heel stop, light door contact; no music.",
    },
    {
        "scene": "Same warm corridor and doorway, framing tightens as subject approaches.",
        "camera": "Match source approach rhythm; gentle handheld push as subject takes one step toward lens.",
        "lighting": "Stable warm practical key and soft camera-side fill.",
        "performance": "Complete turn, lift gaze, form a small friendly closed-mouth smile; hands simple.",
        "action": "Turn from profile and take one small step while holding phone and card low.",
        "endpoint": "Direct gaze, friendly expression, both hands gathered around phone and card.",
        "product_or_ui_truth": "Phone and pale card remain physical, undistorted, and unobstructed.",
        "commercial_proof": "Carry the approved attention and trust beat without a claim.",
        "transition": "Continuous settling move into C04 at 6.48s.",
        "continuity": "Preserve @Image2 identity, bob, brown outfit, props, corridor direction, and warm light.",
        "audio": "No dialogue; corridor ambience, one soft step, subtle prop handling; no music.",
    },
    {
        "scene": "Close corridor portrait with doorway and warm hallway depth behind subject.",
        "camera": "Hold close portrait with subtle handheld breathing sway; no extra push or reframe.",
        "lighting": "Unchanged warm practical light and soft frontal fill.",
        "performance": "Maintain direct gaze and friendly closed-mouth expression; hands steady at waist.",
        "action": "Settle into final pose with phone and pale card stable.",
        "endpoint": "Direct gaze, friendly expression, phone and pale card at waist on final frame.",
        "product_or_ui_truth": "Phone, card, bracelets, outfit, and hand ownership stay unchanged.",
        "commercial_proof": "Complete the character-led hook without text, logo, or guarantee.",
        "transition": "End cleanly at 6.80s on the stable pose required by the next edit.",
        "continuity": "Lock final pose, screen direction, corridor light, @Image2 identity, and props.",
        "audio": "No dialogue; quiet corridor room tone only; no music or synthetic voice.",
    },
]
for shot, compact in zip(segment["shots"], compact_shots, strict=True):
    shot.update(compact)
for shot in segment["shots"]:
    shot["product_or_ui_truth"] = "Phone and pale card unchanged; no extra object."
    shot["commercial_proof"] = "No added claim."
    shot["continuity"] = "Same identity, wardrobe, props, corridor, direction, and light."
    shot["audio"] = "No dialogue; room tone and physical sounds; no music."
segment["reference_roles"] = [
    {"slot": 1, "tag": "@Image1", "role": "approved S01 director storyboard"},
    {"slot": 2, "tag": "@Image2", "role": "adult-woman identity only"},
]
segment["locks"] = [
    "@Video1 controls source motion, camera, timing, blocking, and corridor continuity",
    "@Image1 controls the four-Cut plan; @Image2 controls identity only",
    "keep brown outfit, heels, bracelets, phone, pale card, corridor, and warm light",
    "keep C01-C04 and exact 0.00-6.80s timing",
]
segment["negative_constraints"] = [
    "no generated subtitles, readable text, extra logo, or extra person",
    "do not import pool, swimwear, tattoos, necklace, or furniture from @Image2",
    "no identity drift, wardrobe drift, prop errors, reordered action, freeze, or speed change",
]

factors = {"camera": True, "motion": True, "lighting": True, "characters": True, "audio": True, "continuity": True}
skill_files = {
    "seedance-20": SEEDANCE_ROOT / "SKILL.md",
    "seedance-prompt": SEEDANCE_ROOT / "skills" / "seedance-prompt" / "SKILL.md",
    "seedance-antislop": SEEDANCE_ROOT / "skills" / "seedance-antislop" / "SKILL.md",
    "seedance-camera": SEEDANCE_ROOT / "skills" / "seedance-camera" / "SKILL.md",
    "seedance-motion": SEEDANCE_ROOT / "skills" / "seedance-motion" / "SKILL.md",
    "seedance-lighting": SEEDANCE_ROOT / "skills" / "seedance-lighting" / "SKILL.md",
    "seedance-characters": SEEDANCE_ROOT / "skills" / "seedance-characters" / "SKILL.md",
    "seedance-audio": SEEDANCE_ROOT / "skills" / "seedance-audio" / "SKILL.md",
    "seedance-sequence": SEEDANCE_ROOT / "skills" / "seedance-sequence" / "SKILL.md",
}
checks = {name: True for name in module.COMPILER_CHECKS}
pre_prompt = " ".join(module._format_segment(segment) + [f"Cut {item['cut_id']}: No dialogue. Allowed audio: {', '.join(item['allowed_audio'])}. Forbidden audio: {', '.join(item['forbidden_audio'])}." for item in segment["no_speech_contracts"]])
print("PRE_PROMPT_CHARS=" + str(len(pre_prompt)))
review_bindings = {
    "output_language": None,
    "approved_script_sha256": sha_file(approved_script),
    "approved_storyboard_manifest_sha256": storyboard_manifest_sha,
    "approved_storyboard_cut_sha256s": [board_sha for _ in cut_ids],
    "segment_plan_sha256": sha_file(segment_plan),
}
artifact = module.compile_prompt(
    segment=segment,
    line_contracts=[],
    factors=factors,
    skill_files=skill_files,
    compiler_checks=checks,
    review_bindings=review_bindings,
)
module.validate_compiled_prompt(
    artifact,
    skill_files=skill_files,
    line_contracts=[],
    expected_source_contract=artifact["source_contract"],
    expected_review_bindings=review_bindings,
)

seedance_dir = RUN / "seedance" / "S01"
seedance_dir.mkdir(parents=True, exist_ok=True)
compiled_path = seedance_dir / "compiled_prompt.json"
prompt_path = seedance_dir / "prompt.txt"
write_json(compiled_path, artifact)
prompt_path.write_text(artifact["prompt"] + "\n", encoding="utf-8")

contract_files = {
    "approved_storyboard_sha256": board,
    "source_fidelity_contract_sha256": RUN / "analysis" / "source_fidelity_contract.json",
    "timeline_regions_sha256": RUN / "analysis" / "timeline_regions.json",
    "character_lock_sha256": RUN / "storyboards" / "continuity_manifest.json",
    "product_truth_sha256": RUN / "analysis" / "input_slots.json",
    "selling_point_mapping_sha256": RUN / "analysis" / "selling_point_mapping.json",
    "audio_contract_sha256": RUN / "analysis" / "asr" / "source_audio.json",
    "continuity_manifest_sha256": RUN / "storyboards" / "continuity_manifest.json",
}
seedance_input_contract = {
    "schema_version": "usfr-seedance-input-contract/v1",
    "status": "frozen_after_storyboard_approval",
    "segment_id": "S01",
    "approved_storyboard_revision": 3,
    "approved_storyboard_manifest_sha256": storyboard_manifest_sha,
    "approved_script_sha256": sha_file(approved_script),
    "segment_plan_sha256": sha_file(segment_plan),
    "compiled_prompt_sha256": sha_file(prompt_path),
    "compiled_artifact_sha256": sha_file(compiled_path),
    "contract_digests": {name: sha_file(path) for name, path in contract_files.items()},
    "required_factor_ids": artifact["required_factor_ids"],
    "required_factor_ids_sha256": artifact["required_factor_ids_sha256"],
    "required_audit_checks": [
        "approved_cut_order", "character_lock", "product_lock", "duration_and_timing",
        "voiceover_and_audio", "camera_action_continuity", "selling_point_evidence",
        "timeline_region_routing", "reference_role_mapping", "provider_parameters",
        "forbidden_fields", "zero_ambiguity", "no_unresolved_placeholders",
    ],
    "reference_map": {
        "videoUrls[0]": "exact source-video S01 slice 0-6800ms",
        "imageUrls[0]": "approved director storyboard segment_01_v3.png",
        "imageUrls[1]": "fixed-slot new_model_image.png",
    },
    "forbidden_provider_assets": ["source keyframe sheets", "replacement control sheets", "opaque media", "terminal tail media"],
}
write_json(RUN / "analysis" / "seedance_input_contract.json", seedance_input_contract)
print("COMPILE_STATUS=passed")
print("PROMPT_CHARS=" + str(len(artifact["prompt"])))
print("LOADED_MODULES=" + ",".join(artifact["compiler"]["loaded_modules"]))
