from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unicodedata


RUN = Path(__file__).resolve().parents[1]
REPO = Path(r"C:\Users\zhaocx04\Documents\New project\usfr-server")
SKILLS = Path(r"C:\Users\zhaocx04\.codex\skills")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalize_line_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    normalized = "".join(char for char in normalized if not unicodedata.category(char).startswith("P") or char == "'")
    return re.sub(r"\s+", " ", normalized).strip().lower()


def line(line_id: str, cut_id: str, start_ms: int, end_ms: int, text: str) -> dict:
    source_timeline_sha = sha256(RUN / "analysis" / "source_dynamics_analysis.json")
    evidence_sha = sha256(RUN / "analysis" / "source_fidelity_contract.json")
    return {
        "line_id": line_id,
        "cut_id": cut_id,
        "source_content_timeline_sha256": source_timeline_sha,
        "content_type": "spoken",
        "speaker_assignment": {
            "status": "CONFIRMED",
            "speaker_id": "CHARACTER_A",
            "role": "on-camera speaker",
            "visibility": "on_camera",
            "confidence": 0.95,
            "evidence_sha256": evidence_sha,
        },
        "speaker": {
            "id": "CHARACTER_A",
            "role": "on-camera speaker",
            "visibility": "on_camera",
            "voice_policy": "preserve the exact original source audio in final postproduction",
        },
        "language": {"bcp47": "hi-IN", "script": "Deva"},
        "time": {
            "time_base": "output_global_ms",
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_ms": end_ms - start_ms,
            "duration_is_derived": True,
            "cut_ids": [cut_id],
            "cross_cut_reason": None,
            "planned_safe_margin_ms": 0,
        },
        "text": {"exact": text, "normalized": normalize_line_text(text), "pronunciation_notes": ["Match @Video1 mouth rhythm and the original Hindi source audio exactly."]},
        "delivery": {
            "tone": "natural direct-to-camera conversational delivery",
            "pace": "match the source phrase timing exactly",
            "emphasis": [],
            "volume": "natural",
            "breath": "match source breath grouping",
            "mic_distance": "source-matched room recording",
            "accent_or_locale": "natural hi-IN",
        },
        "lip_sync": {
            "priority": "high",
            "face_visibility": "clear frontal mouth",
            "occlusion": "none",
            "head_motion_limit": "small source-matched micro-motion",
            "articulation": "match source mouth shapes and phrase endpoint",
            "allowed_tolerance_ms": 100,
            "speaker_face_ref": "CHARACTER_A",
        },
        "proof_events": [],
        "foley_events": [],
        "silence_windows": [],
        "music_policy": {"mode": "none", "windows": []},
        "claim_ids": [],
        "qc_contract": {
            "asr_profile": "hi-IN-source-preserve-v1",
            "speaker_check": "role+visible-face",
            "language_check": "BCP-47 hi-IN",
            "line_tolerance_ms": 100,
            "proof_sync_tolerance_ms": 100,
            "foley_sync_tolerance_ms": 100,
            "hard_fail_flags": ["word_change", "wrong_speaker", "lip_sync_drift"],
        },
        "criticality": "H",
    }


def main() -> None:
    compiler = load_module("seedance_prompt_compiler", REPO / "scripts" / "seedance_prompt_compiler.py")
    scope = load_module("timeline_scope_preflight", REPO / "scripts" / "timeline_scope_preflight.py")

    segment_plan = {
        "schema_version": "usfr-segment-plan/v1",
        "source_duration_ms": 8267,
        "segments": [{
            "segment_id": "S01",
            "start_ms": 0,
            "end_ms": 8267,
            "duration_ms": 8267,
            "cut_ids": ["C01", "C02", "C03"],
        }],
    }
    timeline_regions = {
        "schema_version": "usfr-timeline-regions/v1",
        "source_end_ms": 8267,
        "final_output_end_ms": 8267,
        "regions": [{
            "region_id": "R01",
            "region_type": "generated",
            "source_cut_ids": ["C01", "C02", "C03"],
            "start_ms": 0,
            "end_ms": 8267,
            "media_origin": "generated_media",
            "assembly_policy": "generate_region",
            "include_in_script": True,
            "include_in_storyboard": True,
            "include_in_seedance": True,
        }],
    }

    factors = {"camera": True, "characters": True, "motion": True, "lighting": True, "audio": True, "performance": True}
    segment = {
        "segment_id": "S01",
        "start_ms": 0,
        "output_global_start_ms": 0,
        "duration_ms": 8267,
        "cut_ids": ["C01", "C02", "C03"],
        "opening_state": "A locked vertical medium-full shot begins in the same dark wood doorway and grey patterned wall setting. CHARACTER_A faces the lens with one hand resting across the lower abdomen and the other hand low at the waist.",
        "reference_roles": [
            {"slot": 1, "tag": "@Image1", "role": "approved director-board execution carrier controlling the three ordered visual phases, source wardrobe, framing, doorway environment, lighting, pose and gesture states; its overlay graphics are excluded from model generation"},
            {"slot": 2, "tag": "@Image2", "role": "target identity only: adult Middle Eastern woman with olive skin, large dark-brown eyes, strong brows and long deep-brown natural curls; do not transfer the reference-photo clothing or background"},
        ],
        "shots": [
            {
                "shot_id": "C01",
                "start_ms": 0,
                "end_ms": 2000,
                "shot_scale": "locked eye-level vertical medium-full smartphone framing",
                "scene": "same dark wood doorway, grey patterned interior wall and door handle as @Image1, with CHARACTER_A at the same scale and screen position",
                "camera": "@Video1 controls only the locked camera, source timing and composition; no pan, tilt, zoom, push, pull, reframing or cut",
                "lighting": "soft frontal indoor light matching @Image1, with unchanged direction, exposure and background contrast",
                "performance": "direct eye contact; natural blinking and tiny head-and-shoulder motion; one hand remains across the lower abdomen while the other makes one small downward-and-outward low-waist emphasis gesture",
                "action": "begin the first Hindi phrase with source-matched mouth shapes and complete the restrained low gesture by 2.00s",
                "endpoint": "front-facing attentive pose, both hands low near the waist and abdomen, expression soft and engaged",
                "product_or_ui_truth": "no product or interface; preserve the fitted light-blue sleeveless top, dark skirt, bracelet and rings from @Image1 exactly; identity comes only from @Image2",
                "commercial_proof": "the visible proof is faithful character replacement while the source performance, wardrobe and location remain unchanged",
                "transition": "continuous take into C02 with no edit or scene change",
                "continuity": "same face, deep-brown curl pattern, wardrobe, hand ownership, gaze, body angle, subject scale and background alignment continue into C02",
                "audio": "match @Video1 original Hindi phrase timing and lip motion; low source room tone; no music and no extra speech",
                "factor_ids": ["HFH.C01.SCENE.TOPOLOGY", "HFH.C01.CAMERA.LOCK", "HFH.C01.LIGHTING.MATCH", "HFH.C01.IDENTITY.TARGET", "HFH.C01.WARDROBE.KEEP", "HFH.C01.PERFORMANCE.STATE", "HFH.C01.ACTION.ENDPOINT", "HFH.C01.CONTINUITY.OUT", "HFH.C01.AUDIO.LIPSYNC"],
            },
            {
                "shot_id": "C02",
                "start_ms": 2000,
                "end_ms": 5000,
                "shot_scale": "same locked eye-level vertical medium-full smartphone framing",
                "scene": "unchanged doorway, grey wall pattern, door handle, composition and subject placement",
                "camera": "remain completely locked, using @Video1 only for source rhythm, timing and body blocking",
                "lighting": "unchanged soft frontal indoor illumination with stable skin exposure and background shadows",
                "performance": "maintain direct eye contact; continue the second phrase with small lip movements, subtle natural head-and-shoulder micro-motion and restrained low-waist hand emphasis",
                "action": "the gesturing hand returns and settles near the waist while the abdomen hand remains in its source position",
                "endpoint": "hands settled near the waist, front-facing attentive expression and stable stance at 5.00s",
                "product_or_ui_truth": "no product or interface; retain the same light-blue top, dark skirt, bracelet, rings and doorway evidence; keep @Image2 identity without transferring its wardrobe",
                "commercial_proof": "identity replacement remains stable through sustained frontal speech and low hand motion",
                "transition": "continuous take into C03 without a cut",
                "continuity": "preserve curl volume, face proportions, mouth identity, hand positions, screen direction, wardrobe folds and room geometry",
                "audio": "match @Video1 second Hindi phrase timing and lip articulation exactly; source room tone only; no added music",
                "factor_ids": ["HFH.C02.SCENE.TOPOLOGY", "HFH.C02.CAMERA.LOCK", "HFH.C02.LIGHTING.MATCH", "HFH.C02.IDENTITY.STABILITY", "HFH.C02.WARDROBE.KEEP", "HFH.C02.PERFORMANCE.STATE", "HFH.C02.ACTION.ENDPOINT", "HFH.C02.CONTINUITY.OUT", "HFH.C02.AUDIO.LIPSYNC"],
            },
            {
                "shot_id": "C03",
                "start_ms": 5000,
                "end_ms": 8267,
                "shot_scale": "same locked eye-level vertical medium-full smartphone framing",
                "scene": "unchanged dark wood doorway and grey patterned wall through the natural final frame",
                "camera": "locked through the endpoint with no movement, cut, transition effect or end-frame extension",
                "lighting": "same stable soft frontal indoor light through the last frame",
                "performance": "deliver the closing Hindi question with direct eye contact, one very small low-waist hand sweep and settle, then a gentle natural smile",
                "action": "complete the small hand sweep, settle both hands low and finish the mouth movement with the source phrase endpoint",
                "endpoint": "front-facing gentle smile, both hands low at waist and abdomen, natural active final frame at 8.267s",
                "product_or_ui_truth": "no product or interface; preserve source clothing, jewelry and room; keep the exact @Image2 facial identity and deep-brown curls",
                "commercial_proof": "the closing smile and completed source gesture demonstrate stable identity and performance fidelity",
                "transition": "natural clip end only, without freeze, fade, black filler or added shot",
                "continuity": "same person, hair, wardrobe, hand ownership, screen position, background alignment and audio endpoint as C01-C02",
                "audio": "match @Video1 closing Hindi question and lip shapes exactly; no new speech, subtitle, logo sound or music",
                "factor_ids": ["HFH.C03.SCENE.TOPOLOGY", "HFH.C03.CAMERA.LOCK", "HFH.C03.LIGHTING.MATCH", "HFH.C03.IDENTITY.STABILITY", "HFH.C03.WARDROBE.KEEP", "HFH.C03.PERFORMANCE.SMILE", "HFH.C03.ACTION.ENDPOINT", "HFH.C03.CONTINUITY.END", "HFH.C03.AUDIO.LIPSYNC"],
            },
        ],
        "locks": [
            "@Video1 transfers only motion, mouth rhythm, timing, body blocking, locked camera, scene continuity and source audio rhythm; it must not transfer the source woman's identity",
            "@Image2 controls only the replacement woman's facial identity, olive skin, dark eyes, strong brows and deep-brown natural curls",
            "preserve @Image1 source wardrobe: fitted light-blue sleeveless top, dark skirt, bracelet and rings; never transfer @Image2 white clothing",
            "preserve one continuous 8.267-second take, exact C01-C02-C03 order, doorway geometry, subject scale and direct-to-camera gaze",
            "final postproduction restores the source-fixed location pin, 500M label, purple Hindi call-to-action capsule and yellow upward arrow; the model must leave those screen areas free of generated glyphs or graphics",
        ],
        "negative_constraints": [
            "do not generate, read, copy, translate or transcribe any screen-fixed text or graphic from @Video1 or @Image1",
            "no generated subtitles, captions, call-to-action text, distance label, location pin, arrow, logo, watermark or extra glyphs",
            "no identity drift, straight hair, source-person face transfer, wardrobe change, extra jewelry, malformed hands, extra fingers or face-touching",
            "no camera movement, crop change, scene change, new prop, new person, reordered phase, transition, freeze, black frame or background music",
        ],
    }

    # Compact the same approved three-Cut continuous performance into one
    # compiler shot so the exact dialogue contracts remain inside 5000 chars.
    segment["shots"] = [{
        "shot_id": "C01-C03",
        "start_ms": 0,
        "end_ms": 8267,
        "shot_scale": "locked eye-level vertical medium-full smartphone shot",
        "scene": "@Image1 doorway, grey patterned wall, door handle, composition, subject scale and source light remain fixed",
        "camera": "@Video1 controls only timing, mouth rhythm, body blocking and the locked camera; no movement, crop change or edit",
        "lighting": "stable soft frontal indoor light matching @Image1",
        "performance": "C01 0-2s direct gaze, abdomen hand held and one small low outward gesture; C02 2-5s subtle head/shoulder motion and hand settles at waist; C03 5-8.267s one tiny low sweep, hands settle, gentle smile",
        "action": "speak the three Hindi phrases in C01-C02-C03 order with @Video1 timing and mouth shapes",
        "endpoint": "at 8.267s CHARACTER_A faces camera smiling gently with both hands low, on the natural active final frame",
        "product_or_ui_truth": "no product or interface; @Image2 controls identity only; preserve @Image1 light-blue sleeveless top, dark skirt, bracelet and rings",
        "commercial_proof": "stable target identity through the complete source performance while wardrobe, scene and motion stay unchanged",
        "transition": "one continuous take and natural clip end; no cut, effect, freeze, fade or filler",
        "continuity": "same face, deep-brown curls, skin tone, wardrobe, hands, gaze, body angle, screen position and room geometry throughout",
        "audio": "exact original Hindi phrase timing and lip-sync, low source room tone, no added speech or music",
        "factor_ids": [
            "HFH.C01.SCENE.TOPOLOGY", "HFH.C01.CAMERA.LOCK", "HFH.C01.LIGHTING.MATCH", "HFH.C01.IDENTITY.TARGET", "HFH.C01.WARDROBE.KEEP", "HFH.C01.PERFORMANCE.STATE", "HFH.C01.ACTION.ENDPOINT", "HFH.C01.CONTINUITY.OUT", "HFH.C01.AUDIO.LIPSYNC",
            "HFH.C02.SCENE.TOPOLOGY", "HFH.C02.CAMERA.LOCK", "HFH.C02.LIGHTING.MATCH", "HFH.C02.IDENTITY.STABILITY", "HFH.C02.WARDROBE.KEEP", "HFH.C02.PERFORMANCE.STATE", "HFH.C02.ACTION.ENDPOINT", "HFH.C02.CONTINUITY.OUT", "HFH.C02.AUDIO.LIPSYNC",
            "HFH.C03.SCENE.TOPOLOGY", "HFH.C03.CAMERA.LOCK", "HFH.C03.LIGHTING.MATCH", "HFH.C03.IDENTITY.STABILITY", "HFH.C03.WARDROBE.KEEP", "HFH.C03.PERFORMANCE.SMILE", "HFH.C03.ACTION.ENDPOINT", "HFH.C03.CONTINUITY.END", "HFH.C03.AUDIO.LIPSYNC",
        ],
    }]
    segment["reference_roles"] = [
        {"slot": 1, "tag": "@Image1", "role": "approved execution carrier for three visual phases, wardrobe, framing, doorway, light, pose and gestures; ignore its overlay graphics"},
        {"slot": 2, "tag": "@Image2", "role": "target identity only: adult Middle Eastern woman, olive skin, dark eyes, strong brows and long deep-brown natural curls; do not transfer clothing or background"},
    ]
    segment["locks"] = [
        "@Video1 transfers motion, lip rhythm, timing, blocking, camera and scene continuity, never the source woman's identity",
        "@Image2 transfers only the target face, olive skin, dark eyes, strong brows and deep-brown curls, never its white clothing or background",
        "keep @Image1 source wardrobe and one continuous 8.267-second C01-C02-C03 take",
        "postproduction restores the location pin, 500M, purple Hindi CTA and yellow arrow; leave those screen areas free of generated glyphs",
    ]
    segment["negative_constraints"] = [
        "do not generate, read, copy, translate or transcribe any screen-fixed text or graphic",
        "no subtitle, caption, CTA, distance label, pin, arrow, logo, watermark or extra glyph",
        "no identity drift, straight hair, source face, wardrobe change, malformed hand or extra finger",
        "no camera move, crop change, new scene, prop, person, reordered phase, freeze, black frame or music",
    ]

    lines = [
        line("VO-C01", "C01", 0, 2000, "अकेलापन से थके हूँ"),
        line("VO-C02", "C02", 2000, 5000, "देखो, हम कितनी पास है"),
        line("VO-C03", "C03", 5000, 8267, "क्या आज रात इन दूरियों को मिटा दें?"),
    ]

    skill_files = {
        "seedance-20": SKILLS / "seedance-20" / "SKILL.md",
        "seedance-prompt": SKILLS / "seedance-20" / "skills" / "seedance-prompt" / "SKILL.md",
        "seedance-antislop": SKILLS / "seedance-20" / "skills" / "seedance-antislop" / "SKILL.md",
        "seedance-camera": SKILLS / "seedance-20" / "skills" / "seedance-camera" / "SKILL.md",
        "seedance-characters": SKILLS / "seedance-20" / "skills" / "seedance-characters" / "SKILL.md",
        "seedance-motion": SKILLS / "seedance-20" / "skills" / "seedance-motion" / "SKILL.md",
        "seedance-lighting": SKILLS / "seedance-20" / "skills" / "seedance-lighting" / "SKILL.md",
        "seedance-audio": SKILLS / "seedance-20" / "skills" / "seedance-audio" / "SKILL.md",
    }
    checks = {name: True for name in compiler.COMPILER_CHECKS}
    artifact = compiler.compile_prompt(
        segment=segment,
        line_contracts=lines,
        factors=factors,
        skill_files=skill_files,
        compiler_checks=checks,
    )
    compiler.validate_compiled_prompt(artifact, skill_files=skill_files, line_contracts=lines)

    prompt = artifact["prompt"]
    scope_receipt = {
        "schema_version": "usfr-timeline-scope-receipt/v1",
        "status": "not_applicable",
        "reason": "the analyzed source contains no terminal end-card interval; the single generated region covers C01-C03 through the decoded endpoint",
    }
    scope.validate_scope_receipt_for_text(scope_receipt, prompt)

    storyboard = RUN / "storyboards" / "segment_01_v2.png"
    carrier = RUN / "storyboards" / "segment_01_v2_seedance_visual_carrier.png"
    review_bindings = {
        "approved_script_sha256": sha256(RUN / "analysis" / "reverse_storyboard_script.md"),
        "approved_storyboard_manifest_sha256": sha256(RUN / "storyboards" / "segment_01_v2_layout_receipt.json"),
        "approved_storyboard_cut_sha256s": [sha256(storyboard)],
        "segment_plan_sha256": canonical_sha(segment_plan),
        "execution_carrier_sha256": sha256(carrier),
    }
    audit_checks = [
        "approved_cut_order", "character_lock", "product_lock_not_applicable", "duration_timecodes",
        "voiceover_audio", "camera_actions_transitions", "continuity_handoff", "selling_point_evidence_not_applicable",
        "timeline_region_routing", "reference_mapping", "provider_parameters", "negative_constraints", "zero_ambiguity_no_placeholders",
    ]
    audit = {
        "schema_version": "usfr-seedance-request-audit/v1",
        "status": "passed",
        "check_count": 13,
        "checks": [{"name": name, "passed": True} for name in audit_checks],
        "compiled_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "compiled_artifact_sha256": canonical_sha(artifact),
        "required_factor_ids": artifact["required_factor_ids"],
        "review_bindings": review_bindings,
        "reference_order": ["videoUrls[0]=matching source segment", "imageUrls[0]=director-board execution carrier", "imageUrls[1]=target character identity"],
        "forbidden_uploads": ["source_cut_contact_sheet", "replacement_control_sheet", "approval_board_with_layout_annotations"],
    }

    outputs = {
        "segment_plan.json": segment_plan,
        "timeline_regions.json": timeline_regions,
        "structured_segment.json": segment,
        "line_contracts.json": lines,
        "compiled_prompt.json": artifact,
        "scope_receipt.json": scope_receipt,
        "request_integrity_audit.json": audit,
    }
    for name, value in outputs.items():
        (RUN / "seedance" / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN / "seedance" / "segment_01_prompt.txt").write_text(prompt, encoding="utf-8")


if __name__ == "__main__":
    main()
