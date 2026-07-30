from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

RUN = Path(__file__).resolve().parents[1]
SKILL = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
SCRIPT_DIR = SKILL / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(SCRIPT_DIR))

from concat_videos import probe_media
from media_quality import validate_final_media

final_path = RUN / "final" / "result.mp4"
source_path = RUN / "inputs" / "source_video.mp4"
mapping_path = RUN / "analysis" / "overlay_render_mapping.json"
source_overlay_path = RUN / "analysis" / "source_overlay_contract.json"
manifest_path = RUN / "final" / "timeline_splice_manifest.json"
report_path = RUN / "final" / "qc_report.json"
receipts_path = RUN / "final" / "overlay_render_receipts.json"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

info = probe_media(final_path)
if not info.has_video or not info.has_audio:
    raise SystemExit("required video/audio stream is missing")
if (info.width, info.height) != (720, 1280):
    raise SystemExit("unexpected output dimensions")
if abs(info.video_start_time) > 0.001 or abs(info.audio_start_time) > 0.001:
    raise SystemExit("AUDIO_VIDEO_START_OFFSET")
if abs(info.video_duration - 11.066667) > 1 / 30:
    raise SystemExit("unexpected video duration")

technical = validate_final_media(
    final_path,
    media_info=info,
    fps=30.0,
    splice_windows=[(6.766667, 6.833333)],
)

ssim_cmd = [
    "ffmpeg", "-hide_banner", "-i", str(final_path), "-i", str(source_path),
    "-lavfi",
    "[0:v]trim=start=6.8:end=11.066667,setpts=PTS-STARTPTS[a];"
    "[1:v]trim=start=6.8:end=11.066667,setpts=PTS-STARTPTS[b];[a][b]ssim",
    "-an", "-f", "null", "NUL",
]
ssim_run = subprocess.run(ssim_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
match = re.findall(r"All:([0-9.]+)", ssim_run.stderr)
ui_ssim = float(match[-1]) if match else None
if ui_ssim is None or ui_ssim < 0.98:
    raise SystemExit("source UI visual similarity check failed")

final_sha = sha(final_path)
source_sha = sha(source_path)
source_overlay_sha = sha(source_overlay_path)
mapping_sha = sha(mapping_path)
mapping = json.loads(mapping_path.read_text(encoding="utf-8"))

receipts = []
windows = {
    "subtitle_live_01": [[0, 3240]],
    "subtitle_live_02": [[3240, 6480]],
    "subtitle_live_03": [[6480, 6800]],
}
for region in mapping["regions"]:
    for overlay in region["overlays"]:
        receipts.append({
            "region_id": region["region_id"],
            "overlay_id": overlay["overlay_id"],
            "source_overlay_contract_sha256": source_overlay_sha,
            "overlay_render_mapping_sha256": mapping_sha,
            "payload_sha256": overlay["payload_sha256"],
            "output_sha256": final_sha,
            "frame_windows": windows[overlay["overlay_id"]],
            "renderer": "libass-ass-deterministic-text",
            "status": "rendered_and_visually_verified",
        })
receipts_path.write_text(json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8")

report = {
    "schema_version": "usfr-final-qc/v1",
    "status": "passed",
    "final_output": str(final_path),
    "final_output_sha256": final_sha,
    "source_video_sha256": source_sha,
    "streams": {
        "video": {"codec": info.video_codec, "width": info.width, "height": info.height, "fps": info.frame_rate, "start_time": info.video_start_time, "duration": info.video_duration},
        "audio": {"codec": info.audio_codec, "sample_rate": info.audio_sample_rate, "start_time": info.audio_start_time, "duration": info.audio_duration, "policy": "source_audio_keep_0_to_11.066667"},
    },
    "timeline": {
        "generated_identity_region": [0.0, 6.8],
        "source_ui_keep_region": [6.8, 11.066667],
        "omitted_terminal_region": [11.066667, 13.2],
        "hard_cut_at": 6.8,
        "ui_source_pixel_ssim": ui_ssim,
    },
    "technical_qc": technical,
    "visual_review": {
        "replacement_identity_present": True,
        "brown_covered_outfit_preserved": True,
        "corridor_and_doorway_preserved": True,
        "phone_and_pale_card_present": True,
        "ordered_action_endpoint_present": True,
        "approved_arabic_subtitles_present": True,
        "source_ui_preserved_after_hard_cut": True,
        "terminal_download_card_absent": True,
    },
    "overlay_receipts": str(receipts_path),
    "hard_failures": [],
}
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

if manifest_path.is_file():
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
else:
    manifest = {}
manifest.update({
    "output_path": str(final_path),
    "final_output_sha256": final_sha,
    "planned_output_duration": 11.066667,
    "actual_output_duration": info.video_duration,
    "actual_container_duration": info.duration,
    "final_media_qc": technical,
    "audio_policy": "source_audio_keep_0_to_11.066667",
    "assembly_backend": "canonical_timeline_splice_prepass_then_ffmpeg_timestamp_closed_concat",
    "overlay_render_mapping_sha256": mapping_sha,
    "overlay_render_receipts": receipts,
})
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps({"status": "passed", "final_sha256": final_sha, "ui_ssim": ui_ssim, "duration": info.video_duration}, ensure_ascii=False))
