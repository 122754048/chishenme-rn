from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


OUT = Path(__file__).resolve().parent
W, H = 720, 1280


def vertical_gradient(size: tuple[int, int], top: tuple[int, int, int, int], bottom: tuple[int, int, int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size)
    pixels = image.load()
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(4))
        for x in range(width):
            pixels[x, y] = color
    return image


def main() -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Purple CTA capsule, source-normalized from the 1080x1920 frame.
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((219, 953, 559, 1046), radius=42, fill=(132, 4, 247, 255))

    # Location pin shadow and yellow ground ellipse.
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse((61, 112, 124, 135), fill=(0, 0, 0, 90))
    sd.polygon([(58, 22), (126, 22), (92, 121)], fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))
    canvas.alpha_composite(shadow)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((61, 111, 124, 132), fill=(255, 210, 0, 255), outline=(255, 245, 83, 255), width=3)

    pin_mask = Image.new("L", (W, H), 0)
    pm = ImageDraw.Draw(pin_mask)
    pm.ellipse((54, 10, 130, 88), fill=255)
    pm.polygon([(54, 48), (130, 48), (92, 119)], fill=255)
    pm.ellipse((76, 31, 108, 65), fill=0)
    pin_gradient = vertical_gradient((W, H), (255, 61, 61, 255), (219, 0, 0, 255))
    canvas.alpha_composite(Image.composite(pin_gradient, Image.new("RGBA", (W, H)), pin_mask))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((54, 10, 130, 88), outline=(164, 0, 0, 255), width=3)
    draw.line([(55, 49), (92, 119), (129, 49)], fill=(164, 0, 0, 255), width=3)
    draw.ellipse((76, 31, 108, 65), outline=(164, 0, 0, 255), width=3)

    # Glossy upward arrow with a soft shadow.
    arrow_points = [(333, 1138), (405, 1062), (477, 1138), (452, 1147), (452, 1219), (405, 1243), (358, 1219), (358, 1147)]
    arrow_shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arrow_shadow)
    ad.polygon([(x + 3, y + 5) for x, y in arrow_points], fill=(0, 0, 0, 90))
    canvas.alpha_composite(arrow_shadow.filter(ImageFilter.GaussianBlur(7)))
    arrow_mask = Image.new("L", (W, H), 0)
    amd = ImageDraw.Draw(arrow_mask)
    amd.polygon(arrow_points, fill=255)
    amd.rounded_rectangle((358, 1122, 452, 1238), radius=25, fill=255)
    arrow_mask = arrow_mask.filter(ImageFilter.GaussianBlur(1.0))
    arrow_gradient = vertical_gradient((W, H), (255, 188, 28, 255), (255, 230, 87, 255))
    arrow = Image.composite(arrow_gradient, Image.new("RGBA", (W, H)), arrow_mask)
    highlight = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    hd.rounded_rectangle((350, 1080, 460, 1150), radius=28, fill=(255, 255, 255, 26))
    arrow.alpha_composite(Image.composite(highlight, Image.new("RGBA", (W, H)), arrow_mask))
    canvas.alpha_composite(arrow)

    canvas.save(OUT / "overlay_shapes.png")


if __name__ == "__main__":
    main()
