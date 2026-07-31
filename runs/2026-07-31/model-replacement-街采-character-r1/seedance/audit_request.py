from __future__ import annotations

import hashlib
import json
from pathlib import Path


RUN = Path(__file__).resolve().parents[1]
SEEDANCE = RUN / "seedance"
PROVIDER = SEEDANCE / "provider"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> None:
    request = json.loads((PROVIDER / "request.redacted.json").read_text(encoding="utf-8"))
    preview = json.loads((PROVIDER / "approval_preview.json").read_text(encoding="utf-8"))
    bindings = json.loads((PROVIDER / "asset_bindings.json").read_text(encoding="utf-8"))
    compiled = json.loads((SEEDANCE / "compiled_prompt.json").read_text(encoding="utf-8"))
    prompt = (SEEDANCE / "segment_01_prompt.txt").read_text(encoding="utf-8")
    source_receipt = json.loads((PROVIDER / "source_video_references" / "source-reference-S01.json").read_text(encoding="utf-8"))

    checks = {
        "approved_cut_order": all(cut in prompt for cut in ["C01", "C02", "C03", "C04", "C05", "C06", "C07"]),
        "character_lock": all(token in prompt for token in ["@Image3", "white mock-neck top", "black knee-length skirt", "ponytail", "wispy bangs"]),
        "product_lock_not_applicable": "no product/UI" in prompt,
        "duration_timecodes": request.get("duration") == "11" and compiled["source_contract"]["segment"]["duration_ms"] == 10867,
        "voiceover_audio": all(text in prompt for text in ["今話題の『SUGO』知ってる？", "もちろん！私もう沼ってるよ！", "ぶっちゃけどう？", "毎日刺激的すぎて、正直やばい。", "No dialogue"]),
        "camera_actions_transitions": all(token in prompt for token in ["handheld", "C01-C07 in order", "one uninterrupted take"]),
        "continuity_handoff": "natural active final frame" in prompt and "both hands low near each other" in prompt,
        "selling_point_evidence_not_applicable": True,
        "timeline_region_routing": len(request.get("videoUrls", [])) == 1 and source_receipt.get("segment_id") == "S01" and source_receipt.get("start_ms") == 0 and source_receipt.get("end_ms") == 10867 and source_receipt.get("reused_source") is False,
        "reference_mapping": len(request.get("imageUrls", [])) == 3 and all(tag in prompt for tag in ["@Video1", "@Image1", "@Image2", "@Image3"]),
        "provider_parameters": request.get("resolution") == "720p" and request.get("ratio") == "9:16" and request.get("generateAudio") is True and request.get("realPersonMode") is True and request.get("conversionSlots") == ["all"],
        "negative_constraints": all(token in prompt for token in ["no generated text", "no source face", "no new person", "no music"]),
        "zero_ambiguity_no_placeholders": len(prompt) <= 5000 and "{" not in prompt and "TODO" not in prompt and "�" not in prompt,
    }
    if not all(checks.values()):
        raise RuntimeError(f"request audit failed: {[name for name, passed in checks.items() if not passed]}")
    compiler_checks = compiled["compiler"]["checks"]
    if not compiler_checks or not all(compiler_checks.values()):
        raise RuntimeError("packaged compiler checks are not all true")
    if request.get("prompt") != prompt:
        raise RuntimeError("dry-run request prompt differs from compiled prompt")
    if canonical_sha(request) != preview.get("request_sha256"):
        raise RuntimeError("dry-run request digest differs from approval preview")
    uploaded_hashes = [row["sha256"] for row in bindings["image_file_bindings"]]
    expected_hashes = [
        sha(RUN / "storyboards" / "segment_01_page_01_v4.png"),
        sha(RUN / "storyboards" / "segment_01_page_02_v4.png"),
        sha(RUN / "inputs" / "new_model_image.png"),
    ]
    forbidden_hashes = {
        sha(RUN / "reference_frames" / "replacement_control_sheet.png"),
        sha(RUN / "reference_frames" / "source_cut_contact_sheet.png"),
    }
    if forbidden_hashes.intersection(uploaded_hashes):
        raise RuntimeError("an internal control asset leaked into Seedance")
    if uploaded_hashes != expected_hashes:
        raise RuntimeError("image reference order differs from approved fixed-B mapping")

    input_contract = {
        "schema_version": "usfr-seedance-input-contract/v1",
        "segment_id": "S01",
        "approved_script_sha256": sha(RUN / "analysis" / "reverse_storyboard_script.md"),
        "approved_storyboard_manifest_sha256": sha(RUN / "storyboards" / "segment_01_v4_approval_set.json"),
        "approved_storyboard_cut_sha256s": [sha(RUN / "storyboards" / "segment_01_page_01_v4.png"), sha(RUN / "storyboards" / "segment_01_page_02_v4.png")],
        "segment_plan_sha256": sha(RUN / "analysis" / "segment_plan.json"),
        "source_fidelity_contract_sha256": sha(RUN / "analysis" / "source_fidelity_contract.json"),
        "compiled_prompt_sha256": sha(SEEDANCE / "segment_01_prompt.txt"),
        "compiled_artifact_sha256": sha(SEEDANCE / "compiled_prompt.json"),
        "provider_request_sha256": preview["request_sha256"],
        "required_factor_ids": compiled["required_factor_ids"],
        "reference_order": ["videoUrls[0]=bounded S01 source slice", "imageUrls[0]=board page 1", "imageUrls[1]=board page 2", "imageUrls[2]=target character"],
    }
    (SEEDANCE / "seedance_input_contract.json").write_text(json.dumps(input_contract, ensure_ascii=False, indent=2), encoding="utf-8")
    audit = {
        "schema_version": "usfr-seedance-request-audit/v1",
        "status": "passed",
        "check_count": len(checks),
        "checks": [{"name": name, "passed": passed} for name, passed in checks.items()],
        "compiler_checks": compiler_checks,
        "compiled_prompt_sha256": input_contract["compiled_prompt_sha256"],
        "compiled_artifact_sha256": input_contract["compiled_artifact_sha256"],
        "audited_provider_request_sha256": preview["request_sha256"],
        "required_factor_ids": compiled["required_factor_ids"],
        "review_bindings": {
            "approved_script_sha256": input_contract["approved_script_sha256"],
            "approved_storyboard_manifest_sha256": input_contract["approved_storyboard_manifest_sha256"],
            "approved_storyboard_cut_sha256s": input_contract["approved_storyboard_cut_sha256s"],
            "segment_plan_sha256": input_contract["segment_plan_sha256"],
        },
        "source_video_reference": source_receipt,
        "reference_order": input_contract["reference_order"],
        "forbidden_uploads": ["source_cut_contact_sheet", "replacement_control_sheet"],
    }
    (SEEDANCE / "request_integrity_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"request_sha256": preview["request_sha256"], "checks": len(checks), "prompt_chars": len(prompt)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
