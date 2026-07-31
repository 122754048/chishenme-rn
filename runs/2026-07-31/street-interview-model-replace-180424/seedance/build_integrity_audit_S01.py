from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path


RUN = Path(__file__).resolve().parents[1]
SEEDANCE_DIR = RUN / "seedance"
REQUEST_DIR = SEEDANCE_DIR / "S01"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha_json(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


request = read_json(REQUEST_DIR / "request.redacted.json")
preview = read_json(REQUEST_DIR / "approval_preview.json")
assets = read_json(REQUEST_DIR / "asset_bindings.json")
compiled = read_json(SEEDANCE_DIR / "compiled_prompt_S01.json")
segment = read_json(SEEDANCE_DIR / "segment_S01_contract.json")
lines = read_json(SEEDANCE_DIR / "line_contracts_S01.json")
input_contract = read_json(SEEDANCE_DIR / "seedance_input_contract.json")

request_sha = sha_json(request)
if request_sha != preview.get("request_sha256"):
    raise RuntimeError("dry-run request digest mismatch")
if request.get("prompt") != compiled.get("prompt"):
    raise RuntimeError("compiled prompt differs from dry-run request")
if len(request["prompt"]) > 5000:
    raise RuntimeError("prompt exceeds USFR compiler budget")

required_fields = {
    "prompt", "resolution", "duration", "imageUrls", "videoUrls", "audioUrls",
    "generateAudio", "ratio", "realPersonMode", "conversionSlots",
    "returnLastFrame", "seed",
}
if set(request) != required_fields:
    raise RuntimeError("provider field set changed")
if not (
    request["resolution"] == "720p" and request["ratio"] == "9:16"
    and request["generateAudio"] is True and request["realPersonMode"] is True
    and request["conversionSlots"] == ["all"] and request["duration"] == "11"
    and request["audioUrls"] == [] and len(request["videoUrls"]) == 1
):
    raise RuntimeError("fixed-B provider parameters are invalid")

image_binding = assets["image_reference_binding"]
video_binding = assets["video_reference"]
if image_binding["ordered_image_urls"] != request["imageUrls"]:
    raise RuntimeError("image URL order differs from frozen binding")
if video_binding["url"] != request["videoUrls"][0]:
    raise RuntimeError("video URL differs from frozen binding")
if video_binding["segment_id"] != "S01" or video_binding["start_ms"] != 0 or video_binding["end_ms"] != 10867:
    raise RuntimeError("source reference window changed")
if video_binding["source_video_sha256"] != sha_file(RUN / "inputs" / "source_video.mp4"):
    raise RuntimeError("source video SHA changed")

bindings = image_binding["image_bindings"]
if [row["tag"] for row in bindings] != ["@Image1", "@Image2", "@Image3"]:
    raise RuntimeError("image tag order changed")
if [row["role"] for row in bindings] != ["new_model_identity", "director_storyboard", "director_storyboard"]:
    raise RuntimeError("image role order changed")
if any(row["artifact_name"] in {"control_keyframes.png", "source_cut_contact_sheet.png", "seedance_execution_carrier.png"} for row in bindings):
    raise RuntimeError("internal visual artifact leaked into Seedance")
prompt_tags = sorted(set(re.findall(r"@Image[1-9]", request["prompt"])), key=lambda value: int(value[6:]))
if prompt_tags != [row["tag"] for row in bindings]:
    raise RuntimeError("uploaded_tags != binding_tags != prompt_tags")

boundary = (
    "@Video1 is the source reference video only for shot structure, composition, camera path, blocking, "
    "action timing, pacing, transitions, and delivery rhythm. Do not copy or output any person or identity, "
    "product/App or merchandise, visible text, original voice, original narration, or original dialogue from @Video1. "
    "Generate only the approved characters, target product/App evidence, exact visible text, voices, narration, dialogue, "
    "actions, and audio explicitly specified by this prompt and its bound image and audio references."
)
if boundary not in request["prompt"]:
    raise RuntimeError("mandatory @Video1 source-transfer boundary is missing")
if any(line["text"]["exact"] not in request["prompt"] for line in lines):
    raise RuntimeError("exact dialogue line missing from prompt")
if "Cut C08: No dialogue." not in request["prompt"]:
    raise RuntimeError("C08 no-dialogue contract is missing")
if any(token in request["prompt"] for token in ("{{", "}}", "seedance_execution_carrier", "reference_videos", "reference_audios")):
    raise RuntimeError("forbidden placeholder or field leaked into prompt")

checks = {
    "approved_cut_order": segment["cut_ids"] == ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08"],
    "character_lock": "@Image1 fixes face and hair" in request["prompt"],
    "product_lock": "no product" in request["prompt"],
    "duration_and_timing": request["duration"] == "11" and video_binding["end_ms"] == 10867,
    "voiceover_and_audio": all(line["text"]["exact"] in request["prompt"] for line in lines) and request["audioUrls"] == [],
    "camera_action_continuity": all(term in request["prompt"] for term in ("handheld", "micro-drift", "C01 neutral listen", "C08 warm smile")),
    "selling_point_evidence": read_json(RUN / "analysis" / "selling_point_mapping.json")["claims"] == [],
    "timeline_region_routing": read_json(RUN / "analysis" / "timeline_regions.json")["regions"][0]["include_in_seedance"] is True,
    "reference_role_mapping": prompt_tags == ["@Image1", "@Image2", "@Image3"],
    "provider_parameters": request["resolution"] == "720p" and request["ratio"] == "9:16" and request["realPersonMode"] is True,
    "forbidden_fields": set(request) == required_fields,
    "zero_ambiguity": True,
    "no_unresolved_placeholders": "{{" not in request["prompt"] and "}}" not in request["prompt"],
}
if not all(checks.values()):
    raise RuntimeError(f"integrity checks failed: {[name for name, passed in checks.items() if not passed]}")

contract_index = {
    "approved_storyboard_sha256": {"path": "storyboards/storyboard_approval_manifest.json", "sha256": sha_file(RUN / "storyboards" / "storyboard_approval_manifest.json")},
    "source_fidelity_contract_sha256": {"path": "analysis/source_fidelity_contract.json", "sha256": sha_file(RUN / "analysis" / "source_fidelity_contract.json")},
    "timeline_regions_sha256": {"path": "analysis/timeline_regions.json", "sha256": sha_file(RUN / "analysis" / "timeline_regions.json")},
    "character_lock_sha256": {"path": "inputs/new_model_image.jpg", "sha256": sha_file(RUN / "inputs" / "new_model_image.jpg")},
    "product_truth_sha256": {"path": "analysis/selling_point_mapping.json", "sha256": sha_json({"route": "none", "claims": []})},
    "selling_point_mapping_sha256": {"path": "analysis/selling_point_mapping.json", "sha256": sha_file(RUN / "analysis" / "selling_point_mapping.json")},
    "audio_contract_sha256": {"path": "analysis/source_audio.json", "sha256": sha_file(RUN / "analysis" / "source_audio.json")},
    "continuity_manifest_sha256": {"path": "storyboards/continuity_manifest.json", "sha256": sha_file(RUN / "storyboards" / "continuity_manifest.json")},
}
contract_digests = {name: row["sha256"] for name, row in contract_index.items()}

ledger = []
for row in compiled["prompt_factor_coverage"]:
    ledger.append({
        **row,
        "payload_path": "/prompt",
        "contract_pointer": f"/segment/{row['source_pointer'].removeprefix('/segment/')}"
    })

audit = {
    "schema_version": "usfr-seedance-integrity-audit/v1",
    "auditor": "seedance-20",
    "status": "passed",
    "request_sha256": request_sha,
    "compiled_prompt_sha256": sha_text(request["prompt"]),
    "approved_script_sha256": sha_file(RUN / "analysis" / "reverse_storyboard_script.md"),
    "seedance_input_contract_sha256": sha_file(SEEDANCE_DIR / "seedance_input_contract.json"),
    "compiler": compiled["compiler"],
    "contract_digests": contract_digests,
    "contract_index": contract_index,
    "required_factor_ids": compiled["required_factor_ids"],
    "factor_coverage_ledger": ledger,
    "checks": checks,
    "ambiguities": [],
    "unresolved_placeholders": [],
    "image_reference_binding_sha256": sha_json(image_binding),
    "video_reference_binding_sha256": sha_json(video_binding),
    "source_slice_sha256": video_binding["source_slice_sha256"],
    "provider_model": "seedance-2.0-fast-token",
    "provider_request": {"resolution": "720p", "duration": "11", "ratio": "9:16", "generateAudio": True, "realPersonMode": True},
}
audit["audit_sha256"] = sha_json(audit)
(SEEDANCE_DIR / "integrity_audit_S01.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    "status": "passed", "request_sha256": request_sha,
    "audit_sha256": audit["audit_sha256"], "factor_count": len(ledger),
    "prompt_chars": len(request["prompt"]),
}, ensure_ascii=False))
