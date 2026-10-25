"""Generate the eight brand emblems: 1024 px square, white shape on transparent.

A brand in this demo is a colour plus a simple emblem (CLAUDE.md rule 3), so the emblems are
deliberately abstract geometry — no text, no logos, nothing recognisable.

    python art/tools/make_emblems.py            # writes art/emblems/*.png

Needs Pillow in the system Python (already present on this PC).
"""

from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw

SIZE = 1024
SS = 4                      # supersample factor, for clean anti-aliased edges
MARGIN = 0.07               # fraction of the canvas left empty around the shape

SHAPES = ("circle", "triangle", "square", "diamond", "star", "ring", "chevron", "hexagon")


def _ngon(cx, cy, r, n, rot_deg=0.0):
    rot = math.radians(rot_deg)
    return [(cx + r * math.cos(rot + 2 * math.pi * i / n),
             cy + r * math.sin(rot + 2 * math.pi * i / n)) for i in range(n)]


def _star(cx, cy, r_out, r_in, points=5, rot_deg=-90.0):
    pts = []
    rot = math.radians(rot_deg)
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = rot + math.pi * i / points
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw_mask(shape: str, s: int) -> Image.Image:
    """White (255) where the emblem is, 0 elsewhere."""
    m = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(m)
    c = s / 2.0
    r = c * (1.0 - MARGIN)

    if shape == "circle":
        d.ellipse((c - r, c - r, c + r, c + r), fill=255)
    elif shape == "ring":
        d.ellipse((c - r, c - r, c + r, c + r), fill=255)
        ri = r * 0.56
        d.ellipse((c - ri, c - ri, c + ri, c + ri), fill=0)
    elif shape == "square":
        h = r * 0.82
        d.rectangle((c - h, c - h, c + h, c + h), fill=255)
    elif shape == "diamond":
        d.polygon([(c, c - r), (c + r, c), (c, c + r), (c - r, c)], fill=255)
    elif shape == "triangle":
        d.polygon(_ngon(c, c + r * 0.12, r, 3, -90.0), fill=255)
    elif shape == "hexagon":
        d.polygon(_ngon(c, c, r, 6, -90.0), fill=255)
    elif shape == "star":
        d.polygon(_star(c, c, r, r * 0.46), fill=255)
    elif shape == "chevron":
        # two stacked V's pointing down
        t = r * 0.30                      # arm thickness
        drop = r * 0.72                   # how far the apex sits below the arm tips
        for y0 in (c - r * 0.86, c - r * 0.34):
            d.polygon([(c - r, y0), (c, y0 + drop), (c + r, y0),
                       (c + r, y0 + t), (c, y0 + drop + t), (c - r, y0 + t)], fill=255)
    else:
        raise SystemExit("unknown emblem shape: %s" % shape)
    return m


def build(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for shape in SHAPES:
        mask = draw_mask(shape, SIZE * SS).resize((SIZE, SIZE), Image.LANCZOS)
        white = Image.new("L", (SIZE, SIZE), 255)
        img = Image.merge("RGBA", (white, white, white, mask))
        path = os.path.join(out_dir, shape + ".png")
        img.save(path, "PNG", optimize=True)
        written.append(path)
        print("emblem %-9s -> %s" % (shape, path))
    return written


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.abspath(os.path.join(here, "..", "emblems"))
    if len(sys.argv) > 1:
        out = sys.argv[1]
    build(out)
