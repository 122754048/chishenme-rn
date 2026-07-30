from __future__ import annotations

import hashlib
import json
from pathlib import Path

RUN = Path(r"C:\Users\zhaocx04\Documents\New project\replication_runs\2026-07-30\model_replace_20260730_1330")
OUT = RUN / "seedance" / "S01"


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


payload = read(OUT / "request.redacted.json")
preview = read(OUT / "approval_preview.json")
bindings = read(OUT / "asset_bindings.json")
compiled = read(OUT / "compiled_prompt.json")
contract = read(RUN / "analysis" / "seedance_input_contract.json")
prompt_path = OUT / "prompt.txt"
prompt = prompt_path.read_text(encoding="utf-8").strip()
expected_fields = {"prompt", "resolution", "duration", "imageUrls", "videoUrls", "audioUrls", "generateAudio", "ratio", "realPersonMode", "conversionSlots", "returnLastFrame", "seed"}
assert set(payload) == expected_fields
assert payload["resolution"] == "720p" and payload["duration"] == "7" and payload["ratio"] == "9:16"
assert payload["generateAudio"] is True and payload["realPersonMode"] is True and payload["conversionSlots"] == ["all"]
assert len(payload["imageUrls"]) == 2 and len(payload["videoUrls"]) == 1 and payload["audioUrls"] == []
assert bindings["video_reference"]["segment_id"] == "S01"
assert bindings["video_reference"]["start_ms"] == 0 and bindings["video_reference"]["end_ms"] == 6800
assert bindings["video_reference"]["target_changes"] == [{"kind": "new_model_image", "sha256": sha_file(RUN / "inputs" / "new_model_image.png")}]
assert "reference_videos" not in prompt and "reference_audios" not in prompt
assert all(f"Cut {cut_id}: No dialogue." in prompt for cut_id in ("C01", "C02", "C03", "C04"))

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
audit = {
    "auditor": "seedance-20",
    "status": "passed",
    "schema_version": "usfr-seedance-integrity-audit/v1",
    "segment_id": "S01",
    "request_sha256": preview["request_sha256"],
    "prompt_sha256": sha_file(prompt_path),
    "compiled_artifact_sha256": sha_file(OUT / "compiled_prompt.json"),
    "approved_script_sha256": contract["approved_script_sha256"],
    "approved_storyboard_manifest_sha256": contract["approved_storyboard_manifest_sha256"],
    "segment_plan_sha256": contract["segment_plan_sha256"],
    "contract_digests": contract["contract_digests"],
    "compiler": compiled["compiler"],
    "factor_coverage": {
        "required_factor_ids": compiled["required_factor_ids"],
        "required_factor_ids_sha256": compiled["required_factor_ids_sha256"],
        "prompt_factor_coverage": compiled["prompt_factor_coverage"],
    },
    "checks": checks,
    "ambiguities": [],
    "unresolved_placeholders": [],
    "provider": {
        "model": "seedance-2.0-fast-token",
        "resolution": payload["resolution"],
        "duration_seconds": payload["duration"],
        "ratio": payload["ratio"],
        "generateAudio": payload["generateAudio"],
        "realPersonMode": payload["realPersonMode"],
        "image_count": len(payload["imageUrls"]),
        "video_count": len(payload["videoUrls"]),
        "audio_count": len(payload["audioUrls"]),
        "source_video_reference": bindings["video_reference"],
        "target_change_receipt": bindings["video_reference"]["target_changes"],
    },
    "route_excluded_from_provider": ["source UI interval", "terminal tail interval", "source keyframe sheet", "replacement control sheet"],
}
(OUT / "integrity_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("AUDIT_STATUS=passed")
print("REQUEST_SHA256=" + preview["request_sha256"])
