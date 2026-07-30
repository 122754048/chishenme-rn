import importlib.util
import json
from pathlib import Path

ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
RUN = Path(r"C:\Users\zhaocx04\Documents\New project\replication_runs\2026-07-30\character_swap_20260730_152001")
spec = importlib.util.spec_from_file_location("seedance_prompt_compiler", ROOT / "scripts" / "seedance_prompt_compiler.py")
compiler = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(compiler)

data = json.loads((RUN / "analysis" / "seedance_compile_input.json").read_text(encoding="utf-8"))
seedance_root = ROOT / "runtime-skills" / "seedance-20"
skills = {
    "seedance-20": seedance_root / "SKILL.md",
    "seedance-prompt": seedance_root / "skills" / "seedance-prompt" / "SKILL.md",
    "seedance-antislop": seedance_root / "skills" / "seedance-antislop" / "SKILL.md",
    "seedance-camera": seedance_root / "skills" / "seedance-camera" / "SKILL.md",
    "seedance-motion": seedance_root / "skills" / "seedance-motion" / "SKILL.md",
    "seedance-lighting": seedance_root / "skills" / "seedance-lighting" / "SKILL.md",
    "seedance-characters": seedance_root / "skills" / "seedance-characters" / "SKILL.md",
    "seedance-audio": seedance_root / "skills" / "seedance-audio" / "SKILL.md",
}
artifact = compiler.compile_prompt(
    segment=data["segment"],
    line_contracts=[],
    factors=data["factors"],
    skill_files=skills,
    compiler_checks=data["compiler_checks"],
)
compiler.validate_compiled_prompt(artifact, skill_files=skills, line_contracts=[])

output = RUN / "provider" / "seedance" / "S01"
output.mkdir(parents=True, exist_ok=True)
(output / "compiled_prompt.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
(output / "prompt.txt").write_text(artifact["prompt"], encoding="utf-8")
contract = {
    "schema_version": "seedance-input-contract/v1",
    "segment_plan_file": str(RUN / "analysis" / "segment_plan.json"),
    "segment_id": "S01",
    "approved_storyboard": str(RUN / "storyboards" / "v4" / "segment_01_v4.png"),
    "target_model": r"C:\Users\zhaocx04\Downloads\Ssscompigliata 🫨 (2).jpg",
    "source_video": r"C:\Users\zhaocx04\Downloads\社交AI视频\简单剧情2.mp4",
    "compiled_prompt_sha256": artifact["compiler"]["output_sha256"],
    "reference_order": ["approved_director_storyboard", "new_model_image"],
    "forbidden_seedance_assets": ["source_control_keyframes", "replacement_control_keyframes", "source_contact_sheet"],
}
(RUN / "analysis" / "seedance_input_contract.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
print(len(artifact["prompt"]))
print(artifact["compiler"]["output_sha256"])
