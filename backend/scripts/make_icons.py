"""Draws the app icons (the login page's meal-colour ring) into static/icons/.

Run from backend/ after changing the colours or the ring:
    .venv/bin/python scripts/make_icons.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"
BG = (11, 17, 20)  # --gate-bg #0b1114
TRACK = (255, 255, 255, 22)
CIRCUMFERENCE = 2 * math.pi * 40  # the login ring: r=40 in a 100x100 viewBox
# (colour, dash length, dash offset) from login.html, in viewBox units along the ring
ARCS = [
    ((224, 168, 58), 52, 0),     # breakfast
    ((95, 179, 111), 62, 58),    # lunch
    ((127, 151, 230), 70, 126),  # dinner
    ((217, 113, 157), 28, 202),  # snack
]
SCALE = 4  # draw large, then shrink, for smooth edges


def ring(size: int, ring_share: float) -> Image.Image:
    """A square icon of `size` px whose ring spans `ring_share` of the width."""
    big = size * SCALE
    radius = big * ring_share / 2 / (44.5 / 40)  # ring_share covers the stroke's outer edge
    width = round(radius * 9 / 40)
    box = [big / 2 - radius, big / 2 - radius, big / 2 + radius, big / 2 + radius]

    def arcs(draw: ImageDraw.ImageDraw) -> None:
        for colour, length, offset in ARCS:
            start = -90 + offset / CIRCUMFERENCE * 360
            draw.arc(box, start, start + length / CIRCUMFERENCE * 360, fill=colour, width=width)

    img = Image.new("RGBA", (big, big), BG + (255,))
    glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    arcs(ImageDraw.Draw(glow))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(width * 0.9)))
    track = Image.new("RGBA", (big, big), (0, 0, 0, 0))  # its own layer, so the faint white blends in
    ImageDraw.Draw(track).arc(box, 0, 360, fill=TRACK, width=width)
    img.alpha_composite(track)
    arcs(ImageDraw.Draw(img))
    return img.resize((size, size), Image.LANCZOS).convert("RGB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Maskable icons may be cropped to a circle of 80% of the width, so the ring stays inside it.
    for name, size, share in [
        ("icon-192.png", 192, 0.72),
        ("icon-512.png", 512, 0.72),
        ("maskable-512.png", 512, 0.56),
        ("apple-touch-icon.png", 180, 0.68),
    ]:
        ring(size, share).save(OUT / name, optimize=True)
        print(name)


if __name__ == "__main__":
    main()
