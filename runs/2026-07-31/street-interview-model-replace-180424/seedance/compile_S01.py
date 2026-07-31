from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


RUN = Path(__file__).resolve().parents[1]
COMPILER_PATH = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\seedance_prompt_compiler.py")


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


spec = importlib.util.spec_from_file_location("usfr_seedance_prompt_compiler", COMPILER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Seedance prompt compiler cannot be loaded")
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)

segment_path = RUN / "seedance" / "segment_S01_contract.json"
lines_path = RUN / "seedance" / "line_contracts_S01.json"
segment_plan_path = RUN / "analysis" / "segment_plan.json"
segment = read_json(segment_path)
line_contracts = read_json(lines_path)
segment_plan = read_json(segment_plan_path)

skill_root = Path(r"C:\Users\zhaocx04\.codex\skills\seedance-20")
skill_files = {
    "seedance-20": skill_root / "SKILL.md",
    "seedance-prompt": skill_root / "skills" / "seedance-prompt" / "SKILL.md",
    "seedance-antislop": skill_root / "skills" / "seedance-antislop" / "SKILL.md",
    "seedance-camera": skill_root / "skills" / "seedance-camera" / "SKILL.md",
    "seedance-motion": skill_root / "skills" / "seedance-motion" / "SKILL.md",
    "seedance-lighting": skill_root / "skills" / "seedance-lighting" / "SKILL.md",
    "seedance-characters": skill_root / "skills" / "seedance-characters" / "SKILL.md",
    "seedance-audio": skill_root / "skills" / "seedance-audio" / "SKILL.md",
    "seedance-sequence": skill_root / "skills" / "seedance-sequence" / "SKILL.md",
}

factors = {
    "camera": True,
    "motion": True,
    "lighting": True,
    "performance": True,
    "audio": True,
    "continuity": True,
}
checks = {name: True for name in compiler.COMPILER_CHECKS}

review_bindings = {
    "output_language": None,
    "approved_script_sha256": sha_file(RUN / "analysis" / "reverse_storyboard_script.md"),
    "approved_storyboard_manifest_sha256": sha_file(RUN / "storyboards" / "storyboard_approval_manifest.json"),
    "approved_storyboard_cut_sha256s": [
        "440f6627908dd5df90d0e7082bfb4b12ccc9e04e9c8c78b00c9b62208bf50b26",
        "440f6627908dd5df90d0e7082bfb4b12ccc9e04e9c8c78b00c9b62208bf50b26",
        "440f6627908dd5df90d0e7082bfb4b12ccc9e04e9c8c78b00c9b62208bf50b26",
        "440f6627908dd5df90d0e7082bfb4b12ccc9e04e9c8c78b00c9b62208bf50b26",
        "8fcbe1d8ba97e8adae815a0596a605284650c217aa4752c270abbe0199115927",
        "8fcbe1d8ba97e8adae815a0596a605284650c217aa4752c270abbe0199115927",
        "8fcbe1d8ba97e8adae815a0596a605284650c217aa4752c270abbe0199115927",
        "8fcbe1d8ba97e8adae815a0596a605284650c217aa4752c270abbe0199115927"
    ],
    "segment_plan_sha256": sha_json(segment_plan),
}

factor_ids = [factor_id for shot in segment["shots"] for factor_id in shot["factor_ids"]]
seedance_input_contract = {
    "schema_version": "usfr-seedance-input-contract/v1",
    "segment_id": "S01",
    "segment_plan_sha256": sha_json(segment_plan),
    "approved_script_sha256": review_bindings["approved_script_sha256"],
    "approved_storyboard_manifest_sha256": review_bindings["approved_storyboard_manifest_sha256"],
    "source_fidelity_contract_sha256": sha_file(RUN / "analysis" / "source_fidelity_contract.json"),
    "timeline_regions_sha256": sha_file(RUN / "analysis" / "timeline_regions.json"),
    "character_lock_sha256": sha_file(RUN / "inputs" / "new_model_image.jpg"),
    "product_truth_sha256": sha_json({"route": "none", "claims": []}),
    "selling_point_mapping_sha256": sha_file(RUN / "analysis" / "selling_point_mapping.json"),
    "audio_contract_sha256": sha_file(RUN / "analysis" / "source_audio.json"),
    "continuity_manifest_sha256": sha_file(RUN / "storyboards" / "continuity_manifest.json"),
    "required_factor_ids": factor_ids,
    "required_checks": [
        "approved_cut_order", "character_lock", "product_lock", "duration_and_timing",
        "voiceover_and_audio", "camera_action_continuity", "selling_point_evidence",
        "timeline_region_routing", "reference_role_mapping", "provider_parameters",
        "forbidden_fields", "zero_ambiguity", "no_unresolved_placeholders"
    ],
    "image_role_manifest_sha256": sha_file(RUN / "seedance" / "image_role_manifest_S01.json"),
    "source_video_sha256": sha_file(RUN / "inputs" / "source_video.mp4"),
    "output_language": None,
}
(RUN / "seedance" / "seedance_input_contract.json").write_text(
    json.dumps(seedance_input_contract, ensure_ascii=False, indent=2), encoding="utf-8"
)

artifact = compiler.compile_prompt(
    segment=segment,
    line_contracts=line_contracts,
    factors=factors,
    skill_files=skill_files,
    compiler_checks=checks,
    review_bindings=review_bindings,
)
compiler.validate_compiled_prompt(
    artifact,
    skill_files=skill_files,
    line_contracts=line_contracts,
    expected_review_bindings=review_bindings,
)
(RUN / "seedance" / "compiled_prompt_S01.json").write_text(
    json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
)
(RUN / "seedance" / "prompt_S01.txt").write_text(artifact["prompt"], encoding="utf-8")
print(json.dumps({
    "status": "passed",
    "prompt_chars": len(artifact["prompt"]),
    "compiler_output_sha256": artifact["compiler"]["output_sha256"],
    "loaded_modules": artifact["compiler"]["loaded_modules"],
    "required_factor_count": len(artifact["required_factor_ids"]),
    "segment_plan_sha256": review_bindings["segment_plan_sha256"],
}, ensure_ascii=False))
