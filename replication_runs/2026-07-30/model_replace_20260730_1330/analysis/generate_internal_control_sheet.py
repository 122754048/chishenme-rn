from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

skill = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication")
sys.path.insert(0, str(skill / "scripts"))
from config import load_settings
from runninghub_image2 import RunningHubClient, build_payload, image_dimensions, write_json

RUN = Path(r"C:\Users\zhaocx04\Documents\New project\replication_runs\2026-07-30\model_replace_20260730_1330")
ENV = RUN / "runninghub.env"
SOURCE_SHEET = RUN / "reference_frames" / "source_keyframes_sheet.jpg"
TARGET = RUN / "inputs" / "new_model_image.png"
OUT = RUN / "reference_frames" / "replacement_control_keyframes_v1.png"
STEM = "replacement_control_keyframes_v1"

prompt = (
    "Create exactly one ordered-panel replacement control keyframe sheet. "
    "It contains exactly 10 panels in this order: C01, C02, C03, C04, C05, C06, C07, C08, C09, C10. "
    "Use the source keyframe sheet as the non-negotiable visual base for every matching panel. "
    "Preserve source background, environment topology, image quality, lighting, color treatment, composition, "
    "camera angle, camera distance, pose, gesture, facial expression, gaze, timing state, and continuity. "
    "Replace only the adult woman's identity with the supplied target woman. Preserve the brown fitted outfit, "
    "heels, bracelets, phone, pale card, corridor, original UI pixels, subtitles, and terminal card exactly as source evidence. "
    "Do not invent scenery, change framing, add text, UI, logos, props, or people. "
    "This is an internal control sheet, not a director storyboard. Clearly label each panel only with its Cut ID."
)

settings = load_settings(ENV)
settings.require_runninghub()
client = RunningHubClient(settings.runninghub_api_key, base_url=settings.runninghub_base_url)
started = __import__("time").monotonic()
source_url = client.upload_image(SOURCE_SHEET)
target_url = client.upload_image(TARGET)
payload = build_payload(prompt, [source_url, target_url], aspect_ratio="16:9", resolution="2k", quality="medium")
task_id = client.create(payload)
OUT.parent.mkdir(parents=True, exist_ok=True)
write_json(OUT.parent / f"{STEM}.request.redacted.json", {
    "model": "gpt-image-2/image-to-image-official-stable",
    "prompt": {"characters": len(prompt)},
    "reference_images": [str(SOURCE_SHEET), str(TARGET)],
    "reference_sha256": [hashlib.sha256(SOURCE_SHEET.read_bytes()).hexdigest(), hashlib.sha256(TARGET.read_bytes()).hexdigest()],
    "aspect_ratio": "16:9", "resolution": "2k", "quality": "medium",
})
write_json(OUT.parent / f"{STEM}.create_response.json", client.last_create_response)
(OUT.parent / f"{STEM}.task_id.txt").write_text(task_id, encoding="utf-8")
result_url = client.wait_for_result(task_id, timeout=1800, poll_interval=3)
write_json(OUT.parent / f"{STEM}.status.json", client.last_status_response)
client.download_result(result_url, OUT)
digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
write_json(OUT.parent / f"{STEM}.meta.json", {
    "generator_kind": "image_model", "model": "gpt-image-2/image-to-image-official-stable",
    "task_id": task_id, "source_keyframe_sheet": str(SOURCE_SHEET), "target_reference": str(TARGET),
    "source_keyframe_sheet_sha256": hashlib.sha256(SOURCE_SHEET.read_bytes()).hexdigest(),
    "target_reference_sha256": hashlib.sha256(TARGET.read_bytes()).hexdigest(),
    "output_sha256": digest, "output_dimensions": list(image_dimensions(OUT) or ()),
    "generation_duration_seconds": round(__import__("time").monotonic() - started, 3),
    "panel_cut_ids": [f"C{i:02d}" for i in range(1, 11)],
})
print("CONTROL_STATUS=success")
print("CONTROL_OUTPUT_SHA256=" + digest)
