from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys


RUN = Path(__file__).resolve().parents[1]
SKILL = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
STORYBOARD_SKILL = SKILL / "bundled-skills" / "seedance-storyboard-replication"
TEMPLATE = STORYBOARD_SKILL / "references" / "daohuo_storyboard_prompt.md"
MODULE_PATH = STORYBOARD_SKILL / "scripts" / "runninghub_image2.py"
sys.path.insert(0, str(MODULE_PATH.parent))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


template_text = TEMPLATE.read_text(encoding="utf-8-sig")
match = re.search(r"```text\s*(Use case: infographic-diagram.*?)\s*```", template_text, re.S)
if match is None:
    raise RuntimeError("director-board authority skeleton is missing")
skeleton = match.group(1)

shot_cards = """Cut C01
画面：Night alley interview, the replacement woman listens attentively; silver microphone enters from lower left; preserve exact source pose, scale, crop and cool-left/warm-depth lighting.
标签：C01  0.000-1.800  LISTEN · KEEP FACE

Cut C02
画面：Same continuous handheld frame; she answers the first word with a bright smile and small forward facial engagement; arms remain relaxed low.
标签：C02  1.800-2.400  ANSWER · KEEP FACE

Cut C03
画面：She continues the first answer with smiling, light laughter and restrained head/shoulder micro-motion; microphone remains correctly positioned.
标签：C03  2.400-4.320  SMILE · KEEP FACE

Cut C04
画面：She listens to the follow-up with a broad amused smile, tiny head tilt and slight weight shift; same alley, wardrobe and framing.
标签：C04  4.320-5.920  LISTEN · KEEP FACE

Cut C05
画面：She begins the longer reply with modest conversational head and shoulder motion, gaze held toward interviewer/camera axis.
标签：C05  5.920-8.600  SPEAK · KEEP FACE

Cut C06
画面：She delivers the punchline with playful smile and small head/torso emphasis; mouth closes as laughter begins.
标签：C06  8.600-9.740  PUNCHLINE · KEEP FACE

Cut C07
画面：She laughs and settles into the exact endpoint, hands low and close together, warm smile, microphone still entering from lower left.
标签：C07  9.740-10.867  SETTLE · KEEP FACE"""

allowed_labels = """STREET INTERVIEW — CHARACTER REPLACEMENT
SEGMENT 1/1
CUTS C01-C07
7 SHOTS
TARGET 9:16
CHARACTER
FACE / HAIR
WARDROBE
TARGET EVIDENCE
NONE
CAMERA MOVEMENT / TOP DOWN
STORYBOARD
C01 0.000-1.800 LISTEN · KEEP FACE
C02 1.800-2.400 ANSWER · KEEP FACE
C03 2.400-4.320 SMILE · KEEP FACE
C04 4.320-5.920 LISTEN · KEEP FACE
C05 5.920-8.600 SPEAK · KEEP FACE
C06 8.600-9.740 PUNCHLINE · KEEP FACE
C07 9.740-10.867 SETTLE · KEEP FACE
LIGHTING
CAMERA
PALETTE
AUDIO / TONE
MOOD
CINEMATOGRAPHY NOTES"""

mapping = {
    "CONTENT_TYPE": "single-take night street interview performance replication",
    "PRODUCT_OR_SERVICE_TYPE": "none; character identity replacement only",
    "VIDEO_TITLE": "STREET INTERVIEW — CHARACTER REPLACEMENT",
    "DURATION": "10.867-second",
    "SEGMENT_INDEX": "1/1",
    "SEGMENT_DURATION": "10.867 seconds",
    "GLOBAL_CUT_RANGE": "C01-C07",
    "SHOT_COUNT": "7",
    "TARGET_VIDEO_RATIO": "9:16",
    "CHARACTER_REFERENCE_ROLE": "Reference image 2 is the supplied adult East Asian woman's identity truth only: fair skin, large dark-brown eyes, straight dark-brown low ponytail, full wispy bangs, soft-pink lips. Wardrobe and scene are controlled only by Reference image 1.",
    "PRODUCT_REFERENCE_ROLE": "none",
    "REFERENCE_VIDEO_ROLE": "Reference image 1 is the complete seven-Cut replacement-control sheet derived from the frozen source video; it controls Cut order, performance, composition, camera, night alley and continuity.",
    "VISUAL_STYLE": "Photorealistic live-action UGC street interview; night practical lighting; cool vending-machine fill from frame left and warm street lamps in depth; mild wide-angle handheld smartphone look.",
    "COLOR_PALETTE": "charcoal black, warm amber, cool vending-machine white-blue, clean white wardrobe",
    "ENVIRONMENT_PLAN": "One continuous night alley beside the illuminated vending-machine/storefront panel. Keep the interviewee center-right and the microphone entering from lower left. Show a simple top-down diagram with the stationary interviewee, interviewer/camera in front-left, vending-machine wall to camera-left, and only slight handheld sway—no travel, dolly, orbit or angle change.",
    "CONTINUITY_MANIFEST": "Same target facial identity, low ponytail and wispy bangs; same fitted white short-sleeve mock-neck top, black fitted knee-length skirt and earrings; same interviewer hand and silver microphone; same alley topology, mixed cool/warm practical lighting, screen direction, subject scale, source Cut order and original Japanese audio timing. All screen captions are deterministic post-production overlays and are absent from generated scene imagery.",
    "INCOMING_CONTINUITY": "Starts on the interviewee listening attentively in the exact source opening composition, microphone already entering from lower left.",
    "OUTGOING_CONTINUITY": "Ends on the warm smiling laugh-settle pose with both hands low and near each other and microphone still present; no freeze or filler.",
    "ADJACENT_BOARD_ROLE": "none; single segment",
    "SHOT_CARDS": shot_cards,
    "EXACT_LABELS": allowed_labels,
    "AUDIO_NOTE": "Preserve the complete original Japanese dialogue, speaker assignment, pauses, laughter and low night-street ambience; exact source timing; no added music.",
    "TRADEMARK_SAFETY_NOTE": "Target evidence contains no authorized brand. Do not invent or copy branding, vending-machine labels, prices, signage or logos. The approved SUGO screen graphic is restored only as a deterministic overlay after image generation.",
    "TASK_NEGATIVES": "school uniform transfer, tie, beige vest, indoor selfie room, missing microphone, wrong interviewer-hand side, readable vending-machine text, generated Japanese captions, generated SUGO graphic, changed Cut count, plain contact sheet",
}

compiled = skeleton
for key, value in mapping.items():
    compiled = compiled.replace("{{" + key + "}}", value)
unresolved = sorted(set(re.findall(r"\{\{[^{}]+\}\}", compiled)))
if unresolved:
    raise RuntimeError(f"unresolved director-board placeholders: {unresolved}")

prompt_path = RUN / "storyboards" / "segment_01_v1_prompt.txt"
prompt_path.write_text(compiled, encoding="utf-8")

spec = importlib.util.spec_from_file_location("usfr_runninghub_image2", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load bundled RunningHub Image2 adapter")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

env_file = Path(os.environ.get("SEEDANCE_ENV_FILE", ""))
if not env_file.is_file():
    raise RuntimeError("SEEDANCE_ENV_FILE is unavailable")
load_env(env_file)
api_key = os.environ.get("RUNNINGHUB_API_KEY", "")
if not api_key:
    raise RuntimeError("RUNNINGHUB_API_KEY is unavailable")

control_sheet = RUN / "reference_frames" / "replacement_control_sheet.png"
target_image = RUN / "inputs" / "new_model_image.png"
output_path = RUN / "storyboards" / "segment_01_v1_raw.png"
control_receipt = json.loads((RUN / "reference_frames" / "replacement_control_receipt.json").read_text(encoding="utf-8-sig"))
if sha256(control_sheet) != control_receipt.get("required_director_board_reference_sha256"):
    raise RuntimeError("director-board Reference image 1 does not match the replacement-control receipt")

client = module.RunningHubClient(api_key, base_url=os.environ.get("RUNNINGHUB_BASE_URL", "https://www.runninghub.ai"), request_timeout=180)
task_file = RUN / "storyboards" / "segment_01_v1_task_id.txt"
if task_file.is_file() and task_file.read_text(encoding="utf-8").strip():
    task_id = task_file.read_text(encoding="utf-8").strip()
else:
    uploaded_urls = [client.upload_image(control_sheet), client.upload_image(target_image)]
    payload = module.build_payload(compiled, uploaded_urls, aspect_ratio="16:9", resolution="2k", quality="medium")
    task_id = client.create(payload)
    write_json(RUN / "storyboards" / "segment_01_v1_create_response.json", client.last_create_response)
    task_file.write_text(task_id, encoding="utf-8")

result_url = client.wait_for_result(task_id, timeout=1800, poll_interval=5)
write_json(RUN / "storyboards" / "segment_01_v1_status.json", client.last_status_response)
client.download_result(result_url, output_path)

raw_sha = sha256(output_path)
if raw_sha in {sha256(control_sheet), sha256(target_image)}:
    raise RuntimeError("director-board output is not distinct from its references")

template_sha = sha256(TEMPLATE)
receipt = {
    "schema_version": "usfr-director-board-generation-receipt/v1",
    "status": "passed",
    "task_id": task_id,
    "model": module.MODEL_NAME,
    "model_api_id": module.MODEL_API_ID,
    "aspect_ratio": "16:9",
    "resolution": "2k",
    "quality": "medium",
    "template_path": str(TEMPLATE),
    "daohuo_storyboard_prompt_sha256": template_sha,
    "compiled_prompt_path": str(prompt_path),
    "compiled_prompt_sha256": sha256(prompt_path),
    "reference_1_role": "replacement_control_sheet",
    "reference_1_sha256": sha256(control_sheet),
    "reference_2_role": "target_character_identity_only",
    "reference_2_sha256": sha256(target_image),
    "cut_ids": ["C01", "C02", "C03", "C04", "C05", "C06", "C07"],
    "raw_output_path": str(output_path),
    "raw_output_sha256": raw_sha,
}
write_json(RUN / "storyboards" / "segment_01_v1_generation_receipt.json", receipt)
print(json.dumps({"task_id": task_id, "raw_output": str(output_path), "sha256": raw_sha, "template_sha256": template_sha}, ensure_ascii=False))
