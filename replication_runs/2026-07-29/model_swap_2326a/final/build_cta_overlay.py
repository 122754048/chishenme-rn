from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

out = Path(__file__).with_name("cta_overlay.png")
canvas = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
draw = ImageDraw.Draw(canvas)

# Source-locked lower CTA geometry: x=.120, y=.665, w=.760, h=.100.
left, top, width, height, radius = 130, 1277, 820, 192, 52
draw.rounded_rectangle((left, top, left + width, top + height), radius=radius, fill=(255, 255, 255, 255))

font = ImageFont.truetype(r"C:\Windows\Fonts\georgiab.ttf", 44)
line1 = "Generate a "
line1_red = "Magic Video"
line2 = "from your photos and voice"

def centered_runs(y, runs):
    widths = [draw.textlength(text, font=font) for text, _ in runs]
    x = left + (width - 110 - sum(widths)) / 2
    for (text, color), run_width in zip(runs, widths):
        draw.text((x, y), text, font=font, fill=color, stroke_width=0)
        x += run_width

centered_runs(top + 25, [(line1, (20, 20, 20, 255)), (line1_red, (220, 24, 24, 255))])
centered_runs(top + 79, [(line2, (20, 20, 20, 255))])

# Filled heart from two circles and a lower triangle, matching the source icon role.
hx, hy = left + width - 77, top + 94
draw.ellipse((hx - 27, hy - 28, hx, hy - 1), fill=(0, 0, 0, 255))
draw.ellipse((hx, hy - 28, hx + 27, hy - 1), fill=(0, 0, 0, 255))
draw.polygon([(hx - 27, hy - 13), (hx + 27, hy - 13), (hx, hy + 40)], fill=(0, 0, 0, 255))

canvas.save(out)
