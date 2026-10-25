"""Generate the sample image shown on M_Screen in the previews.

Preview-only input: the real screen image is a runtime input, never baked into an asset.
Abstract on purpose — no text, no names (CLAUDE.md rule 3).

    python art/tools/make_sample_screen.py      # writes art/samples/sample_screen.png
"""

from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw

W, H = 1280, 720
SS = 2

BG_TOP = (14, 26, 38)
BG_BOTTOM = (8, 14, 22)
BARS = [(31, 143, 198), (46, 180, 196), (238, 196, 92), (226, 110, 86), (236, 240, 244)]


def build(path: str) -> str:
    w, h = W * SS, H * SS
    img = Image.new("RGB", (w, h), BG_BOTTOM)
    d = ImageDraw.Draw(img)

    # vertical gradient background
    for y in range(h):
        f = y / (h - 1)
        d.line([(0, y), (w, y)],
               fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * f) for i in range(3)))

    # a ring, off-centre
    cx, cy, r = w * 0.34, h * 0.48, h * 0.30
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(236, 240, 244), width=int(h * 0.035))
    d.ellipse((cx - r * 0.35, cy - r * 0.35, cx + r * 0.35, cy + r * 0.35), fill=(31, 143, 198))

    # colour bars on the right
    bx0 = w * 0.62
    bw = (w * 0.30) / len(BARS)
    for i, col in enumerate(BARS):
        x0 = bx0 + i * bw
        hh = h * (0.26 + 0.11 * math.sin(i * 1.1))
        d.rectangle((x0, cy - hh / 2, x0 + bw * 0.74, cy + hh / 2), fill=col)

    # a thin baseline
    d.rectangle((w * 0.08, h * 0.86, w * 0.92, h * 0.875), fill=(70, 86, 100))

    img = img.resize((W, H), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG", optimize=True)
    print("sample screen -> %s" % path)
    return path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.abspath(os.path.join(here, "..", "samples", "sample_screen.png"))
    if len(sys.argv) > 1:
        out = sys.argv[1]
    build(out)
