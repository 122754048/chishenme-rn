import hashlib
import json
from pathlib import Path

RUN = Path(r"C:\Users\zhaocx04\Documents\New project\replication_runs\2026-07-30\character_swap_20260730_152001")
OUT = RUN / "provider" / "seedance" / "S01"
payload = json.loads((OUT / "request.redacted.json").read_text(encoding="utf-8"))
preview = json.loads((OUT / "approval_preview.json").read_text(encoding="utf-8"))
assets = json.loads((OUT / "asset_bindings.json").read_text(encoding="utf-8"))
compiled = json.loads((OUT / "compiled_prompt.json").read_text(encoding="utf-8"))
plan = json.loads((RUN / "analysis" / "segment_plan.json").read_text(encoding="utf-8"))
canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
actual = hashlib.sha256(canonical).hexdigest()
checks = {
    "request_sha_matches_approval_preview": actual == preview["request_sha256"],
    "compiled_prompt_matches_payload": compiled["prompt"] == payload["prompt"],
    "prompt_under_5000_characters": len(payload["prompt"]) < 5000,
    "all_seedance_compiler_checks_pass": all(compiled["compiler"]["checks"].values()),
    "fixed_b_model_parameters": payload["resolution"] == "720p" and payload["ratio"] == "9:16" and payload["generateAudio"] is True and payload["realPersonMode"] is True and payload["conversionSlots"] == ["all"],
    "provider_duration_rounding_is_declared": payload["duration"] == "11",
    "exactly_one_source_segment_video": len(payload["videoUrls"]) == 1 and assets["video_reference"]["segment_id"] == "S01",
    "source_segment_window_matches_frozen_plan": assets["video_reference"]["start_ms"] == plan["segments"][0]["start_ms"] and assets["video_reference"]["end_ms"] == plan["segments"][0]["end_ms"],
    "source_segment_digest_bound": assets["video_reference"]["source_video_sha256"] == "0eb8afc9c8e46c97102b2047f7dce321a502c6709d6464ad0c0a48eaed47a80e" and bool(assets["video_reference"]["source_slice_sha256"]),
    "approved_board_is_image1": len(payload["imageUrls"]) == 2 and assets["image_file_bindings"][0]["sha256"] == "5e57ecdfcd8a7b4b122f368acee46b73ad56f603382e54e671cf2bd5986655ef",
    "target_model_is_image2": assets["image_file_bindings"][1]["sha256"] == "26a3988eb3c9c14af5f144028db2a9578876e6f66f8a5c665fcbb476e912114e",
    "upstream_control_assets_excluded": all(item["sha256"] not in {"f2ac45dbbf0175034dfb2b2d8b94a00a8f67b825615e8a40cc91525a8e65b8df"} for item in assets["image_file_bindings"]),
    "no_audio_or_opaque_route_assets": payload["audioUrls"] == [] and not any("control" in str(x).lower() or "opaque" in str(x).lower() for x in [*payload["imageUrls"], *payload["videoUrls"]]),
}
if len(checks) != 13 or not all(checks.values()):
    raise SystemExit("Seedance integrity audit failed")
audit = {
    "schema_version": "usfr-seedance-integrity-audit/v1",
    "request_sha256": actual,
    "compiled_prompt_sha256": compiled["compiler"]["output_sha256"],
    "segment_id": "S01",
    "check_count": len(checks),
    "checks": checks,
    "result": "passed",
    "provider_duration_note": "The exact 10.042-second source slice is bound; the provider payload uses its required integer duration ceiling of 11 seconds.",
}
(OUT / "integrity_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
print(actual)
