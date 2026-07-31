from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).resolve().parent
W, H = 720, 1280
JP_FONT = Path(r"C:\Windows\Fonts\YuGothB.ttc")
EMOJI_FONT = Path(r"C:\Windows\Fonts\seguiemj.ttf")


def canvas() -> Image.Image:
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def draw_centered_text(image: Image.Image, text: str, y: int, size: int,
                       fill: str, stroke: str, stroke_width: int,
                       emoji: str | None = None, emoji_gap: int = 8) -> None:
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(JP_FONT), size=size, index=0)
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_w = box[2] - box[0]
    emoji_w = 0
    emoji_font = None
    if emoji:
        emoji_font = ImageFont.truetype(str(EMOJI_FONT), size=size + 3)
        ebox = draw.textbbox((0, 0), emoji, font=emoji_font, embedded_color=True)
        emoji_w = ebox[2] - ebox[0] + emoji_gap
    x = (W - text_w - emoji_w) // 2
    if emoji and emoji_font:
        draw.text((x + 2, y + 3), emoji, font=emoji_font, embedded_color=True)
        x += emoji_w
    draw.text((x + 3, y + 4), text, font=font, fill=(0, 0, 0, 155), stroke_width=stroke_width + 2, stroke_fill=(0, 0, 0, 120))
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke)


def make_text_overlays() -> None:
    specs = [
        ("overlay_01_question.png", "今話題の『SUGO』知ってる？", 446, 42, "#EAF8FF", "#249DF2", 4, None),
        ("overlay_02_answer.png", "もちろん！", 506, 48, "#FFF6FB", "#FF4D98", 5, "🤭"),
        ("overlay_03_hooked.png", "私もう沼ってるよ！", 486, 47, "#FFF4FA", "#FF4B92", 5, "😭"),
        ("overlay_04_followup.png", "ぶっちゃけ...", 528, 47, "#EDF8FF", "#249CF0", 5, "🤔"),
        ("overlay_05_stimulating.png", "毎日刺激的すぎ！", 486, 55, "#FFF0F7", "#FF4388", 6, "🔥"),
        ("overlay_06_punchline.png", "正直ヤバいwww", 526, 50, "#FFF1F8", "#FF4388", 6, "🤣"),
    ]
    for name, text, y, size, fill, stroke, sw, emoji in specs:
        image = canvas()
        draw_centered_text(image, text, y, size, fill, stroke, sw, emoji)
        image.save(OUT / name)


def make_sugo_logo() -> None:
    image = canvas()
    draw = ImageDraw.Draw(image)
    # Two overlapping rear bubbles and the purple foreground speech bubble.
    draw.rounded_rectangle((286, 544, 438, 620), radius=30, fill=(18, 195, 242, 255))
    draw.polygon([(304, 603), (296, 642), (340, 612)], fill=(18, 195, 242, 255))
    draw.rounded_rectangle((331, 527, 469, 606), radius=31, fill=(249, 71, 214, 255))
    draw.polygon([(431, 590), (451, 629), (414, 602)], fill=(249, 71, 214, 255))
    draw.rounded_rectangle((307, 556, 443, 631), radius=27, fill=(101, 39, 238, 255))
    draw.polygon([(327, 615), (320, 654), (358, 624)], fill=(101, 39, 238, 255))
    font = ImageFont.truetype(str(Path(r"C:\Windows\Fonts\arialbd.ttf")), 47)
    text = "SUGO"
    box = draw.textbbox((0, 0), text, font=font, stroke_width=1)
    x = 375 - (box[2] - box[0]) // 2
    draw.text((x + 2, 568 + 3), text, font=font, fill=(0, 0, 0, 75))
    draw.text((x, 568), text, font=font, fill="white", stroke_width=1, stroke_fill="white")
    image.save(OUT / "overlay_sugo_logo.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    make_text_overlays()
    make_sugo_logo()


if __name__ == "__main__":
    main()
