from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


RUN = Path(__file__).resolve().parents[1]
RAW = RUN / "storyboards" / "segment_01_v1_raw.png"
APPROVAL = RUN / "storyboards" / "segment_01_v1.png"
CARRIER = RUN / "storyboards" / "segment_01_v1_seedance_visual_carrier.png"
RECEIPT = RUN / "storyboards" / "segment_01_v1_layout_receipt.json"
GENERATION_RECEIPT = RUN / "storyboards" / "segment_01_v1_generation_receipt.json"
TEMPLATE = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\references\daohuo_storyboard_prompt.md")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


raw = Image.open(RAW).convert("RGB")
w, h = raw.size
if abs((w / h) - (16 / 9)) > 0.02:
    raise RuntimeError(f"director board is not 16:9: {w}x{h}")

board = raw.copy()
draw = ImageDraw.Draw(board)
jp_font = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", max(18, round(h * 0.018)))
logo_font = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", max(15, round(h * 0.015)))

# Image2 produced the fixed board at 2048x1152. These normalized boxes bind the
# seven ordered Cut images inside the central STORYBOARD region.
image_boxes_n = [
    (0.285, 0.159, 0.538, 0.258),
    (0.285, 0.266, 0.538, 0.364),
    (0.285, 0.371, 0.538, 0.469),
    (0.285, 0.476, 0.538, 0.573),
    (0.285, 0.580, 0.538, 0.678),
    (0.285, 0.685, 0.538, 0.782),
    (0.285, 0.789, 0.538, 0.863),
]
boxes = [(round(x1*w), round(y1*h), round(x2*w), round(y2*h)) for x1,y1,x2,y2 in image_boxes_n]

overlays = [
    ("今話題の『SUGO』知ってる？", "#29a9ff", "sugo"),
    ("もちろん！", "#ff4f91", "shy"),
    ("私もう沼ってるよ！", "#ff4f91", "cry"),
    ("ぶっちゃけ...", "#29a9ff", "think"),
    ("毎日刺激的すぎ！", "#ff3f86", "fire"),
    ("正直ヤバいwww", "#ff3f86", "laugh"),
    ("正直ヤバいwww", "#ff3f86", "laugh"),
]

def draw_icon(cx: int, cy: int, size: int, kind: str) -> None:
    if kind == "fire":
        draw.polygon([(cx,cy-size),(cx+size//2,cy-size//5),(cx+size//3,cy+size),(cx-size//3,cy+size),(cx-size//2,cy-size//5)], fill="#ff6a00", outline="white")
        draw.polygon([(cx,cy-size//2),(cx+size//4,cy),(cx,cy+size//2),(cx-size//4,cy)], fill="#ffd32a")
        return
    draw.ellipse((cx-size,cy-size,cx+size,cy+size), fill="#ffd83d", outline="white", width=2)
    eye_y = cy-size//4
    draw.ellipse((cx-size//2,eye_y-2,cx-size//3,eye_y+2), fill="#382812")
    draw.ellipse((cx+size//3,eye_y-2,cx+size//2,eye_y+2), fill="#382812")
    if kind in {"laugh", "cry"}:
        draw.arc((cx-size//2,cy-size//8,cx+size//2,cy+size//2), 10, 170, fill="#382812", width=2)
        draw.line((cx-size//2-2,eye_y+5,cx-size//2-5,cy+size//2), fill="#36a9ff", width=3)
        draw.line((cx+size//2+2,eye_y+5,cx+size//2+5,cy+size//2), fill="#36a9ff", width=3)
    elif kind == "think":
        draw.line((cx-size//3,cy+size//3,cx+size//3,cy+size//4), fill="#382812", width=2)
        draw.ellipse((cx+size//2,cy+size//3,cx+size,cy+size), fill="#f1b75c", outline="white")
    else:
        draw.arc((cx-size//3,cy,cx+size//3,cy+size//2), 10, 170, fill="#382812", width=2)
        draw.ellipse((cx+size//5,cy+size//5,cx+size,cy+size), fill="#f1b75c", outline="white")

def centered_text(box: tuple[int,int,int,int], text: str, color: str, icon: str, y_ratio: float = 0.68) -> None:
    x1, y1, x2, y2 = box
    bbox = draw.textbbox((0, 0), text, font=jp_font, stroke_width=2)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    icon_space = 0 if icon == "sugo" else max(24, round((y2-y1)*0.24))
    tx = (x1 + x2 - tw + icon_space) // 2
    ty = round(y1 + (y2-y1) * y_ratio - th/2)
    draw.rounded_rectangle((tx-8, ty-4, tx+tw+8, ty+th+5), radius=8, fill=(0,0,0,155))
    draw.text((tx, ty), text, font=jp_font, fill=color, stroke_width=2, stroke_fill="white")
    if icon != "sugo":
        draw_icon(tx-icon_space//2-5, ty+th//2, max(9, icon_space//3), icon)

for index, (box, (text, color, icon)) in enumerate(zip(boxes, overlays), start=1):
    centered_text(box, text, color, icon, 0.66 if icon == "sugo" else 0.72)
    if icon == "sugo":
        x1, y1, x2, y2 = box
        cx = round(x1 + (x2-x1) * 0.80)
        cy = round(y1 + (y2-y1) * 0.28)
        bw = round((x2-x1) * 0.13)
        bh = round((y2-y1) * 0.30)
        draw.rounded_rectangle((cx-bw, cy-bh//2, cx, cy+bh//2), radius=bh//2, fill="#ff5aa8", outline="white", width=2)
        draw.rounded_rectangle((cx-bw//3, cy-bh//2, cx+bw*2//3, cy+bh//2), radius=bh//2, fill="#3eb8ff", outline="white", width=2)
        label = "SUGO"
        tb = draw.textbbox((0, 0), label, font=logo_font)
        draw.text((cx - (tb[2]-tb[0])//2, cy - (tb[3]-tb[1])//2 - 1), label, font=logo_font, fill="white", stroke_width=1, stroke_fill="#404040")

# RunningHub returns a near-16:9 2736x1536 canvas. Preserve the complete raw
# Image2 artifact unchanged, while center-cropping only the publication board
# by a few border pixels to an exact 16:9 integer canvas.
approval_h = (h // 18) * 18
approval_w = approval_h * 16 // 9
left = (w - approval_w) // 2
top = (h - approval_h) // 2
board = board.crop((left, top, left + approval_w, top + approval_h))
board.save(APPROVAL, format="PNG")

# Build a labels-free execution carrier only from the seven scene-image ROIs of
# the template-bound Image2 director board. It is not the replacement-control sheet.
carrier = Image.new("RGB", (1600, 900), "#0a0a0a")
cell_w, cell_h = 400, 450
for idx, box in enumerate(boxes):
    crop = raw.crop(box)
    crop.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
    cell_x = (idx % 4) * cell_w
    cell_y = (idx // 4) * cell_h
    x = cell_x + (cell_w - crop.width)//2
    y = cell_y + (cell_h - crop.height)//2
    carrier.paste(crop, (x, y))
carrier.save(CARRIER, format="PNG")

generation = json.loads(GENERATION_RECEIPT.read_text(encoding="utf-8-sig"))
template_sha = sha256(TEMPLATE)
if generation.get("daohuo_storyboard_prompt_sha256") != template_sha:
    raise RuntimeError("template SHA mismatch between generation and approval publication")

approval_sha = sha256(APPROVAL)
carrier_sha = sha256(CARRIER)
raw_sha = sha256(RAW)
if len({approval_sha, carrier_sha, raw_sha, sha256(RUN / 'reference_frames' / 'replacement_control_sheet.png')}) != 4:
    raise RuntimeError("raw board, approval board, execution carrier and control sheet must have distinct SHA-256 values")

receipt = {
    "schema_version": "usfr-storyboard-layout-receipt/v1",
    "status": "passed",
    "layout_id": "daohuo-professional-director-board/v1",
    "segment_id": "S01",
    "board_width": board.width,
    "board_height": board.height,
    "raw_board_width": w,
    "raw_board_height": h,
    "aspect_ratio": "16:9",
    "daohuo_storyboard_prompt_path": str(TEMPLATE),
    "daohuo_storyboard_prompt_sha256": template_sha,
    "compiled_prompt_sha256": generation.get("compiled_prompt_sha256"),
    "required_regions": [
        "shared_creative_header",
        "character_identity_and_detail_column",
        "ordered_storyboard_cut_cards",
        "target_evidence_or_none",
        "top_down_camera_movement_plan",
        "lighting_footer",
        "camera_footer",
        "palette_footer",
        "audio_tone_footer",
        "mood_footer",
        "cinematography_notes_footer"
    ],
    "cut_count": 7,
    "cut_ids": ["C01", "C02", "C03", "C04", "C05", "C06", "C07"],
    "cut_image_boxes_normalized": image_boxes_n,
    "visual_provenance": {
        "source_cut_contact_sheet_sha256": sha256(RUN / "reference_frames" / "source_cut_contact_sheet.png"),
        "replacement_control_sheet_sha256": sha256(RUN / "reference_frames" / "replacement_control_sheet.png"),
        "raw_director_board_sha256": raw_sha,
        "approval_board_sha256": approval_sha,
        "execution_carrier_sha256": carrier_sha
    },
    "deterministic_overlay_board_receipt": {
        "schema_version": "usfr-board-overlay-render/v1",
        "status": "passed",
        "route": "deterministic_overlay",
        "overlays_by_cut": [
            {"cut_id": "C01", "window_ms": [0, 1600], "exact_text": "今話題の『SUGO』知ってる？", "graphic": "SUGO pink-blue speech bubbles"},
            {"cut_id": "C02", "window_ms": [1800, 2400], "exact_text": "🤭もちろん！"},
            {"cut_id": "C03", "window_ms": [2400, 4270], "exact_text": "😭私もう沼ってるよ！"},
            {"cut_id": "C04", "window_ms": [4470, 5600], "exact_text": "🤔ぶっちゃけ..."},
            {"cut_id": "C05", "window_ms": [6300, 8600], "exact_text": "🔥毎日刺激的すぎ！"},
            {"cut_id": "C06", "window_ms": [8600, 9740], "exact_text": "🤣正直ヤバいwww"},
            {"cut_id": "C07", "window_ms": [9740, 10400], "exact_text": "🤣正直ヤバいwww"}
        ],
        "output_sha256": approval_sha
    }
}
RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"approval": str(APPROVAL), "approval_sha256": approval_sha, "carrier_sha256": carrier_sha}, ensure_ascii=False))
