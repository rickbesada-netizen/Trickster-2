"""Regenerates assets/icon.ico and assets/icon.png (an original fingerprint
mark in the app's teal on dark navy). To use your OWN icon instead, just
replace assets/icon.ico (a multi-size .ico: 16, 24, 32, 48, 64, 128, 256) and
rebuild - you don't need to run this script.

    python assets/make_icon.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
S = 1024  # draw big, shrink for crisp edges
BG_TOP, BG_BOT = (17, 28, 44), (8, 14, 24)
TEAL = (76, 227, 193)


def build() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # rounded-square background with a soft vertical gradient
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    import math
    cx, cy = S // 2, int(S * 0.50)
    w = int(S * 0.050)

    def ridge(rx, ry, a0, a1, dy=0):
        """One fingerprint ridge: an oval arc, rounded at both ends."""
        box = [cx - rx, cy + dy - ry, cx + rx, cy + dy + ry]
        d.arc(box, a0, a1, fill=TEAL, width=w)
        for ang in (a0, a1):
            ex = cx + (rx - w / 2) * math.cos(math.radians(ang))
            ey = cy + dy + (ry - w / 2) * math.sin(math.radians(ang))
            d.ellipse([ex - w / 2, ey - w / 2, ex + w / 2, ey + w / 2], fill=TEAL)

    # outer ridges: tall ovals that open at the bottom, staggered gaps
    ridge(int(S * 0.355), int(S * 0.405), 150, 392)   # 150 -> 32 degrees, over the top
    ridge(int(S * 0.285), int(S * 0.340), 168, 372)
    ridge(int(S * 0.215), int(S * 0.275), 140, 395, dy=int(S * 0.01))
    ridge(int(S * 0.145), int(S * 0.210), 175, 365, dy=int(S * 0.02))
    # whorl at the centre
    ridge(int(S * 0.075), int(S * 0.140), 190, 350, dy=int(S * 0.04))
    d.rounded_rectangle([cx - w // 2, cy + int(S * 0.05), cx + w // 2, cy + int(S * 0.30)], radius=w // 2, fill=TEAL)
    return img


if __name__ == "__main__":
    big = build()
    big.resize((256, 256), Image.LANCZOS).save(HERE / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.save(HERE / "icon.ico", sizes=[(s, s) for s in sizes])
    print("wrote", HERE / "icon.ico")
