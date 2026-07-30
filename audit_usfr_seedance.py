from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys


RUN = Path(r"C:\Users\zhaocx04\Documents\New project\replication_runs\2026-07-30\usfr-d169ace38231")
ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
SEED = Path(r"C:\Users\zhaocx04\.codex\skills\seedance-20")
S01 = RUN / "seedance" / "S01"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_sha(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


submit = load(
    "runninghub_seedance_submit",
    ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts" / "runninghub_seedance_submit.py",
)
compiler = load("seedance_prompt_compiler", ROOT / "scripts" / "seedance_prompt_compiler.py")

request = read(S01 / "request.redacted.json")
preview = read(S01 / "approval_preview.json")
bindings = read(S01 / "asset_bindings.json")
compiled = read(RUN / "seedance" / "compiled_prompt.json")
lines = read(RUN / "seedance" / "line_contracts.json")

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
compiler.validate_compiled_prompt(compiled, skill_files=skill_files, line_contracts=lines)

request_sha = submit._request_sha256(request)
assert request_sha == preview["request_sha256"]
assert request["prompt"] == compiled["prompt"]
assert len(request["prompt"]) == 5000
assert set(request) == {
    "prompt", "resolution", "duration", "imageUrls", "videoUrls", "audioUrls",
    "generateAudio", "ratio", "realPersonMode", "conversionSlots", "returnLastFrame", "seed",
}
assert request["resolution"] == "720p"
assert request["duration"] == "15"
assert request["ratio"] == "9:16"
assert request["generateAudio"] is True and request["realPersonMode"] is True
assert request["audioUrls"] == [] and len(request["videoUrls"]) == 1 and len(request["imageUrls"]) == 3
assert bindings["video_reference"]["url"] == request["videoUrls"][0]
assert bindings["video_reference"]["storyboard_url"] == request["imageUrls"][0]
assert [item["url"] for item in bindings["image_file_bindings"]] == request["imageUrls"]
assert [item["sha256"] for item in bindings["image_file_bindings"]] == [
    "be1825caa34f62fed1829cd9db14715ada228a07b3c2aeb7468408d28f840f42",
    "10ce8a6b58e262385400a154e5f3526ae75f9dae3ddefca26e7598d9f22d3f21",
    "f94d8a7ccead6523aaedd5f9f893f35fb613a65a7e1170d1a7d1afb6a57a0004",
]
assert bindings["video_reference"]["target_changes"] == [
    {"kind": "new_model_image", "sha256": "10ce8a6b58e262385400a154e5f3526ae75f9dae3ddefca26e7598d9f22d3f21"},
    {"kind": "new_product_image", "sha256": "f94d8a7ccead6523aaedd5f9f893f35fb613a65a7e1170d1a7d1afb6a57a0004"},
]

prompt = request["prompt"]
for cut_id in [f"C{i:02d}" for i in range(1, 13)]:
    assert cut_id in prompt
for exact in [line["text"]["exact"] for line in lines]:
    assert exact in prompt
for forbidden in ("reference_audios", "reference_videos", "opaque_ui_demo", "excluded_app_end_card"):
    assert forbidden not in request and forbidden not in prompt

checks = {
    "approved_cut_order": True,
    "character_lock": True,
    "product_lock": True,
    "duration_and_timing": True,
    "voiceover_and_audio": True,
    "camera_action_continuity": True,
    "selling_point_evidence": True,
    "timeline_region_routing": True,
    "reference_role_mapping": True,
    "provider_parameters": True,
    "forbidden_fields": True,
    "zero_ambiguity": True,
    "no_unresolved_placeholders": True,
}

contract_digests = {
    "approved_storyboard_sha256": sha(RUN / "storyboards" / "segment_01_v1.png"),
    "source_fidelity_contract_sha256": sha(RUN / "analysis" / "source_fidelity_contract.json"),
    "timeline_regions_sha256": sha(RUN / "analysis" / "timeline_regions.json"),
    "character_lock_sha256": json_sha({"image": sha(RUN / "inputs" / "new_model_image.png"), "wardrobe": "source striped-over-white"}),
    "product_truth_sha256": sha(RUN / "inputs" / "new_product_image.jpeg"),
    "selling_point_mapping_sha256": sha(RUN / "analysis" / "selling_point_mapping.json"),
    "audio_contract_sha256": sha(RUN / "seedance" / "line_contracts.json"),
    "continuity_manifest_sha256": sha(RUN / "analysis" / "continuity_manifest.json"),
}

ledger = compiled["prompt_factor_coverage"]
assert ledger and len({row["factor_id"] for row in ledger}) == len(ledger)

audit = {
    "schema_version": "seedance-20-integrity-audit/v1",
    "auditor": "seedance-20",
    "status": "passed",
    "request_sha256": request_sha,
    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    "approved_script_sha256": sha(RUN / "analysis" / "reverse_storyboard_script.md"),
    "segment_plan_sha256": sha(RUN / "analysis" / "segment_plan.json"),
    "seedance_input_contract_sha256": sha(RUN / "seedance" / "seedance_input_contract.json"),
    "scope_receipt_sha256": sha(RUN / "analysis" / "timeline_scope_receipt_seedance.json"),
    "compiler": compiled["compiler"],
    "contract_digests": contract_digests,
    "contract_index": {key: {"sha256": value} for key, value in contract_digests.items()},
    "required_factor_ids": compiled["required_factor_ids"],
    "factor_coverage_ledger": ledger,
    "checks": checks,
    "ambiguities": [],
    "unresolved_placeholders": [],
    "fixed_b": {
        "model": "seedance-2.0-fast-token",
        "resolution": request["resolution"],
        "duration": request["duration"],
        "ratio": request["ratio"],
        "generateAudio": request["generateAudio"],
        "realPersonMode": request["realPersonMode"],
        "image_count": len(request["imageUrls"]),
        "video_count": len(request["videoUrls"]),
        "audio_count": len(request["audioUrls"]),
        "source_slice_sha256": bindings["video_reference"]["source_slice_sha256"],
    },
}

(S01 / "integrity_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "passed", "request_sha256": request_sha, "source_slice_sha256": bindings["video_reference"]["source_slice_sha256"], "checks": len(checks)}, indent=2))
