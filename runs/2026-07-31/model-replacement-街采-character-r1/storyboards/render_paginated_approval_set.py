from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


RUN = Path(__file__).resolve().parents[1]
STORYBOARDS = RUN / "storyboards"
TEMPLATE = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\references\daohuo_storyboard_prompt.md")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


font = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", 34)
logo_font = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", 27)


page_specs = [
    {
        "page": 1,
        "cut_ids": ["C01", "C02", "C03"],
        "boxes_n": [(0.193,0.158,0.397,0.746),(0.402,0.158,0.601,0.746),(0.605,0.158,0.807,0.746)],
        "overlays": [
            ("今話題の『SUGO』知ってる？", "#29a9ff", "sugo"),
            ("もちろん！", "#ff4f91", "shy"),
            ("私もう沼ってるよ！", "#ff4f91", "cry"),
        ],
    },
    {
        "page": 2,
        "cut_ids": ["C04", "C05", "C06", "C07"],
        "boxes_n": [(0.143,0.159,0.330,0.858),(0.331,0.159,0.513,0.858),(0.514,0.159,0.696,0.858),(0.697,0.159,0.850,0.858)],
        "overlays": [
            ("ぶっちゃけ...", "#29a9ff", "think"),
            ("毎日刺激的すぎ！", "#ff3f86", "fire"),
            ("正直ヤバいwww", "#ff3f86", "laugh"),
            ("正直ヤバいwww", "#ff3f86", "laugh"),
        ],
    },
]


def draw_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, kind: str) -> None:
    if kind == "fire":
        draw.polygon([(cx,cy-size),(cx+size//2,cy-size//5),(cx+size//3,cy+size),(cx-size//3,cy+size),(cx-size//2,cy-size//5)], fill="#ff6a00", outline="white")
        draw.polygon([(cx,cy-size//2),(cx+size//4,cy),(cx,cy+size//2),(cx-size//4,cy)], fill="#ffd32a")
        return
    draw.ellipse((cx-size,cy-size,cx+size,cy+size), fill="#ffd83d", outline="white", width=2)
    eye_y = cy-size//4
    draw.ellipse((cx-size//2,eye_y-2,cx-size//3,eye_y+2), fill="#382812")
    draw.ellipse((cx+size//3,eye_y-2,cx+size//2,eye_y+2), fill="#382812")
    if kind in {"laugh", "cry"}:
        draw.arc((cx-size//2,cy-size//8,cx+size//2,cy+size//2), 10, 170, fill="#382812", width=3)
        draw.line((cx-size//2-2,eye_y+5,cx-size//2-6,cy+size//2), fill="#36a9ff", width=4)
        draw.line((cx+size//2+2,eye_y+5,cx+size//2+6,cy+size//2), fill="#36a9ff", width=4)
    elif kind == "think":
        draw.line((cx-size//3,cy+size//3,cx+size//3,cy+size//4), fill="#382812", width=3)
        draw.ellipse((cx+size//2,cy+size//3,cx+size,cy+size), fill="#f1b75c", outline="white")
    else:
        draw.arc((cx-size//3,cy,cx+size//3,cy+size//2), 10, 170, fill="#382812", width=3)
        draw.ellipse((cx+size//5,cy+size//5,cx+size,cy+size), fill="#f1b75c", outline="white")


def draw_overlay(draw: ImageDraw.ImageDraw, box: tuple[int,int,int,int], text: str, color: str, icon: str) -> None:
    x1,y1,x2,y2 = box
    tb = draw.textbbox((0,0), text, font=font, stroke_width=3)
    tw, th = tb[2]-tb[0], tb[3]-tb[1]
    icon_space = 0 if icon == "sugo" else 44
    tx = (x1+x2-tw+icon_space)//2
    ty = round(y1+(y2-y1)*0.62-th/2)
    draw.rounded_rectangle((tx-12,ty-7,tx+tw+12,ty+th+8), radius=12, fill="#101010")
    draw.text((tx,ty), text, font=font, fill=color, stroke_width=3, stroke_fill="white")
    if icon == "sugo":
        cx = round(x1+(x2-x1)*0.77)
        cy = round(y1+(y2-y1)*0.20)
        bw, bh = 110, 48
        draw.rounded_rectangle((cx-bw,cy-bh//2,cx,cy+bh//2),radius=24,fill="#ff5aa8",outline="white",width=2)
        draw.rounded_rectangle((cx-bw//3,cy-bh//2,cx+bw*2//3,cy+bh//2),radius=24,fill="#3eb8ff",outline="white",width=2)
        lb=draw.textbbox((0,0),"SUGO",font=logo_font)
        draw.text((cx-(lb[2]-lb[0])//2,cy-(lb[3]-lb[1])//2-2),"SUGO",font=logo_font,fill="white",stroke_width=1,stroke_fill="#404040")
    else:
        draw_icon(draw, tx-icon_space//2-5, ty+th//2, 17, icon)


template_sha = sha256(TEMPLATE)
control_sha = sha256(RUN / "reference_frames" / "replacement_control_sheet.png")
pages_manifest = []
for spec in page_specs:
    stem = f"segment_01_page_{spec['page']:02d}_v4"
    raw_path = STORYBOARDS / f"{stem}_raw.png"
    output_path = STORYBOARDS / f"{stem}.png"
    generation_path = STORYBOARDS / f"{stem}_generation_receipt.json"
    generation = json.loads(generation_path.read_text(encoding="utf-8-sig"))
    if generation["daohuo_storyboard_prompt_sha256"] != template_sha:
        raise RuntimeError(f"page {spec['page']} template SHA mismatch")
    if generation["reference_1_sha256"] != control_sha:
        raise RuntimeError(f"page {spec['page']} control provenance mismatch")
    raw = Image.open(raw_path).convert("RGB")
    w,h = raw.size
    board = raw.copy()
    draw = ImageDraw.Draw(board)
    boxes = [(round(x1*w),round(y1*h),round(x2*w),round(y2*h)) for x1,y1,x2,y2 in spec["boxes_n"]]
    for box, overlay in zip(boxes, spec["overlays"]):
        draw_overlay(draw, box, *overlay)
    approval_h = (h//18)*18
    approval_w = approval_h*16//9
    left=(w-approval_w)//2
    top=(h-approval_h)//2
    board=board.crop((left,top,left+approval_w,top+approval_h))
    board.save(output_path,format="PNG")
    final_sha=sha256(output_path)
    raw_sha=sha256(raw_path)
    if raw_sha==final_sha:
        raise RuntimeError(f"page {spec['page']} overlay publication did not change bytes")
    pages_manifest.append({
        "page_index": spec["page"],
        "page_count": 2,
        "cut_ids": spec["cut_ids"],
        "path": f"storyboards/{output_path.name}",
        "sha256": final_sha,
        "raw_path": f"storyboards/{raw_path.name}",
        "raw_sha256": raw_sha,
        "reference_1_sha256": control_sha,
        "daohuo_storyboard_prompt_sha256": template_sha,
        "width": board.width,
        "height": board.height,
    })

manifest = {
    "schema_version": "usfr-director-storyboard-approval-set/v1",
    "status": "awaiting_confirmation",
    "revision": 4,
    "segment_id": "S01",
    "page_count": 2,
    "user_visible_artifact_kinds": ["director_storyboard_png"],
    "internal_artifacts_excluded": ["replacement_control_sheet"],
    "daohuo_storyboard_prompt_path": str(TEMPLATE),
    "daohuo_storyboard_prompt_sha256": template_sha,
    "pagination_policy": "maximum_two_pages_3_plus_4_portrait_fit_contain",
    "pages": pages_manifest,
}
(STORYBOARDS / "segment_01_v4_approval_set.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(manifest,ensure_ascii=False))
