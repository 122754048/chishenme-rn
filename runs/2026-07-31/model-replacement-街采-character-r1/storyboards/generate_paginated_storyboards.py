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
template_sha = sha256(TEMPLATE)

pages = [
    {
        "page_index": "1",
        "page_cut_range": "C01-C03",
        "cut_ids": ["C01", "C02", "C03"],
        "shot_cards": """Cut C01
画面：Full 9:16 portrait-frame view from the replacement-control sheet: night alley interview, replacement woman listening attentively, fitted white mock-neck top and black knee-length skirt, silver microphone and interviewer hand entering from lower left, vending-machine light at left and warm lamps in depth. Preserve complete body crop and source geometry.
标签：C01  0.000-1.800  LISTEN · KEEP FACE

Cut C02
画面：Full 9:16 portrait-frame view: same composition and wardrobe; she answers the first word with a bright smile and small forward facial engagement, arms relaxed low, microphone relationship unchanged.
标签：C02  1.800-2.400  ANSWER · KEEP FACE

Cut C03
画面：Full 9:16 portrait-frame view: she continues the answer with smiling and light laughter, restrained head and shoulder micro-motion, same subject scale, hands, microphone, alley and mixed practical lighting.
标签：C03  2.400-4.320  SMILE · KEEP FACE""",
        "labels": """STREET INTERVIEW — CHARACTER REPLACEMENT
SEGMENT 1/1
PAGE 1/2
C01-C03
3 SHOTS
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
LIGHTING
CAMERA
PALETTE
AUDIO / TONE
MOOD
CINEMATOGRAPHY NOTES""",
    },
    {
        "page_index": "2",
        "page_cut_range": "C04-C07",
        "cut_ids": ["C04", "C05", "C06", "C07"],
        "shot_cards": """Cut C04
画面：Large full 9:16 portrait-frame view from the replacement-control sheet: she listens to the follow-up with an amused smile, tiny head tilt and slight weight shift; preserve complete source composition, full body, hands, microphone and environment.
标签：C04  4.320-5.920  LISTEN · KEEP FACE

Cut C05
画面：Large full 9:16 portrait-frame view from the replacement-control sheet: she begins the longer reply with modest conversational head and shoulder motion, gaze toward interviewer/camera axis; preserve full source crop, low hands, microphone, night alley and wardrobe.
标签：C05  5.920-8.600  SPEAK · KEEP FACE

Cut C06
画面：Full 9:16 portrait-frame view: she delivers the punchline with a playful smile and small head/torso emphasis; mouth closes as laughter begins; preserve complete body proportions, hands, microphone and night-alley scene. Fit-contain without crop or stretch.
标签：C06  8.600-9.740  PUNCHLINE · KEEP FACE

Cut C07
画面：Full 9:16 portrait-frame view: she laughs and settles into the exact endpoint, both hands low and close together, warm smile, microphone still entering from lower left; preserve the complete final pose. Fit-contain without crop or stretch.
标签：C07  9.740-10.867  SETTLE · KEEP FACE""",
        "labels": """STREET INTERVIEW — CHARACTER REPLACEMENT
SEGMENT 1/1
PAGE 2/2
C04-C07
4 SHOTS
TARGET 9:16
CHARACTER
FACE / HAIR
WARDROBE
TARGET EVIDENCE
NONE
CAMERA MOVEMENT / TOP DOWN
STORYBOARD
C04 4.320-5.920 LISTEN · KEEP FACE
C05 5.920-8.600 SPEAK · KEEP FACE
C06 8.600-9.740 PUNCHLINE · KEEP FACE
C07 9.740-10.867 SETTLE · KEEP FACE
LIGHTING
CAMERA
PALETTE
AUDIO / TONE
MOOD
CINEMATOGRAPHY NOTES""",
    },
]

common = {
    "CONTENT_TYPE": "single-take night street interview performance replication",
    "PRODUCT_OR_SERVICE_TYPE": "none; character identity replacement only",
    "VIDEO_TITLE": "STREET INTERVIEW — CHARACTER REPLACEMENT",
    "DURATION": "10.867-second",
    "SEGMENT_INDEX": "1/1",
    "BOARD_PAGE_COUNT": "2",
    "SEGMENT_DURATION": "10.867 seconds",
    "GLOBAL_CUT_RANGE": "C01-C07",
    "TARGET_VIDEO_RATIO": "9:16",
    "CHARACTER_REFERENCE_ROLE": "Reference image 2 is the supplied adult East Asian woman's identity truth only: fair skin, large dark-brown eyes, straight dark-brown low ponytail, full wispy bangs and soft-pink lips. Do not transfer her school uniform or indoor selfie setting.",
    "PRODUCT_REFERENCE_ROLE": "none",
    "REFERENCE_VIDEO_ROLE": "Reference image 1 is the complete seven-Cut replacement-control sheet derived from the frozen source video and controls the page's selected Cut performances, full portrait composition, camera, night alley and continuity.",
    "VISUAL_STYLE": "Photorealistic live-action UGC street interview; cool vending-machine fill from frame left and warm street lamps in depth; mild wide-angle handheld smartphone look. Cut scene cards are large uncropped 9:16 portrait frames, never panorama strips.",
    "COLOR_PALETTE": "charcoal black, warm amber, cool vending-machine white-blue, clean white wardrobe",
    "ENVIRONMENT_PLAN": "One continuous night alley beside the illuminated vending-machine/storefront panel. Keep the interviewee center-right and microphone entering from lower left. Top-down plan: stationary interviewee, interviewer/camera front-left, machine wall camera-left, slight handheld sway only.",
    "CONTINUITY_MANIFEST": "Same target face, low ponytail and wispy bangs; same fitted white short-sleeve mock-neck top, black knee-length skirt and earrings; same interviewer hand and silver microphone; same alley, mixed practical lighting, screen direction, subject scale, Cut order and original Japanese audio timing. Screen captions are absent from Image2 scene pixels and restored deterministically after generation.",
    "INCOMING_CONTINUITY": "The page begins from its first listed Cut in the exact source handoff state.",
    "OUTGOING_CONTINUITY": "The page ends in its last listed Cut's exact source endpoint and hands off directly to the next page or final endpoint.",
    "ADJACENT_BOARD_ROLE": "The other page in the same Segment is a continuity neighbor; both pages form one approval set.",
    "AUDIO_NOTE": "Preserve complete original Japanese dialogue, speaker assignment, pauses, laughter and low night-street ambience at exact source timing; no added music.",
    "TRADEMARK_SAFETY_NOTE": "Do not invent or copy branding, machine labels, prices or signage. The approved SUGO screen graphic is restored only as a deterministic overlay after image generation.",
    "TASK_NEGATIVES": "school uniform transfer, tie, beige vest, indoor selfie room, missing microphone, wrong interviewer-hand side, generated Japanese captions, generated SUGO graphic, squeezed Cut strips, horizontal stretch, vertical stretch, cropped body, distorted person, plain contact sheet",
}

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
control_sha = sha256(control_sheet)
control_receipt = json.loads((RUN / "reference_frames" / "replacement_control_receipt.json").read_text(encoding="utf-8-sig"))
if control_sha != control_receipt.get("required_director_board_reference_sha256"):
    raise RuntimeError("director-board Reference image 1 does not match replacement-control receipt")

client = module.RunningHubClient(api_key, base_url=os.environ.get("RUNNINGHUB_BASE_URL", "https://www.runninghub.ai"), request_timeout=180)
for page in pages:
    mapping = dict(common)
    mapping.update({
        "BOARD_PAGE_INDEX": page["page_index"],
        "PAGE_CUT_RANGE": page["page_cut_range"],
        "SHOT_COUNT": str(len(page["cut_ids"])),
        "SHOT_CARDS": page["shot_cards"],
        "EXACT_LABELS": page["labels"],
    })
    compiled = skeleton
    for key, value in mapping.items():
        compiled = compiled.replace("{{" + key + "}}", value)
    unresolved = sorted(set(re.findall(r"\{\{[^{}]+\}\}", compiled)))
    if unresolved:
        raise RuntimeError(f"unresolved page {page['page_index']} placeholders: {unresolved}")

    stem = f"segment_01_page_{int(page['page_index']):02d}_v4"
    prompt_path = RUN / "storyboards" / f"{stem}_prompt.txt"
    raw_path = RUN / "storyboards" / f"{stem}_raw.png"
    task_path = RUN / "storyboards" / f"{stem}_task_id.txt"
    prompt_path.write_text(compiled, encoding="utf-8")

    if task_path.is_file() and task_path.read_text(encoding="utf-8").strip():
        task_id = task_path.read_text(encoding="utf-8").strip()
    else:
        uploaded_urls = [client.upload_image(control_sheet), client.upload_image(target_image)]
        payload = module.build_payload(compiled, uploaded_urls, aspect_ratio="16:9", resolution="2k", quality="medium")
        task_id = client.create(payload)
        write_json(RUN / "storyboards" / f"{stem}_create_response.json", client.last_create_response)
        task_path.write_text(task_id, encoding="utf-8")

    result_url = client.wait_for_result(task_id, timeout=1800, poll_interval=5)
    write_json(RUN / "storyboards" / f"{stem}_status.json", client.last_status_response)
    client.download_result(result_url, raw_path)
    write_json(RUN / "storyboards" / f"{stem}_generation_receipt.json", {
        "schema_version": "usfr-director-board-page-generation/v1",
        "status": "passed",
        "task_id": task_id,
        "segment_id": "S01",
        "page_index": int(page["page_index"]),
        "page_count": 2,
        "cut_ids": page["cut_ids"],
        "page_cut_range": page["page_cut_range"],
        "daohuo_storyboard_prompt_path": str(TEMPLATE),
        "daohuo_storyboard_prompt_sha256": template_sha,
        "compiled_prompt_path": str(prompt_path),
        "compiled_prompt_sha256": sha256(prompt_path),
        "reference_1_role": "internal_replacement_control_sheet",
        "reference_1_sha256": control_sha,
        "reference_2_role": "target_character_identity_only",
        "reference_2_sha256": sha256(target_image),
        "raw_path": str(raw_path),
        "raw_sha256": sha256(raw_path),
        "user_visible": False,
    })
    print(json.dumps({"page": page["page_index"], "task_id": task_id, "raw": str(raw_path), "sha256": sha256(raw_path)}, ensure_ascii=False))
