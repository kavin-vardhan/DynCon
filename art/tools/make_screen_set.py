"""The base game's set of screen images — what the display screen inside a piece cycles through.

Plan v6 §3 gives every piece of content "a display screen that cycles images", and §9 keeps
the chosen image index across a content update. The images themselves belong to the **base
game**, not to a pack: a pack carries geometry and material instances, and the screen image is
a runtime input set on `M_Screen` exactly like the brand colour and the emblem. So they are
generated here, imported into `/Game/DCCore/Screens/` by `unreal/Tools/core_extras.py`, and
handed to a piece at spawn by `UDCSubsystem::GetScreenImage`.

Four of them, because four is enough to tell a swap apart at a glance and few enough to cycle
through with one button. Each one is a different dominant colour **and** a different shape, so
"the screen is on image 3" is readable in a 1600 x 900 screenshot from across a room - which
is the whole reason the exit test can check it.

Abstract on purpose, by the demo's no-names rule: no text, no names, no marks that could
read as a logo.

    python art/tools/make_screen_set.py          # writes art/samples/screens/screen_1..4.png
"""

from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw

W, H = 1280, 720
SS = 2                       # supersample, then resize down: cheap antialiasing

# One background per image, dark enough that the emissive screen material reads as a lit panel
# rather than as a white rectangle, and four clearly different hues.
IMAGES = [
    {"id": 1, "name": "rings",  "bg": ((16, 30, 44), (8, 16, 26)),  "ink": (86, 198, 230)},
    {"id": 2, "name": "bars",   "bg": ((44, 30, 12), (24, 14, 6)),  "ink": (240, 176, 64)},
    {"id": 3, "name": "wedge",  "bg": ((40, 14, 34), (20, 8, 18)),  "ink": (232, 96, 172)},
    {"id": 4, "name": "steps",  "bg": ((16, 38, 26), (8, 20, 14)),  "ink": (120, 214, 128)},
]

PALE = (236, 240, 244)


def gradient(draw: ImageDraw.ImageDraw, w: int, h: int, top, bottom) -> None:
    for y in range(h):
        f = y / max(h - 1, 1)
        draw.line([(0, y), (w, y)],
                  fill=tuple(int(top[i] + (bottom[i] - top[i]) * f) for i in range(3)))


def draw_rings(d: ImageDraw.ImageDraw, w: int, h: int, ink) -> None:
    cx, cy = w * 0.5, h * 0.5
    for i in range(5):
        r = h * (0.10 + i * 0.085)
        width = int(h * (0.030 if i % 2 == 0 else 0.016))
        colour = ink if i % 2 == 0 else PALE
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=colour, width=width)
    d.ellipse((cx - h * 0.045, cy - h * 0.045, cx + h * 0.045, cy + h * 0.045), fill=PALE)


def draw_bars(d: ImageDraw.ImageDraw, w: int, h: int, ink) -> None:
    # Six leaning bars of different heights: a shape that survives being 120 px wide.
    n = 6
    span = w * 0.76
    bw = span / (n * 1.6)
    x0 = w * 0.12
    for i in range(n):
        hh = h * (0.22 + 0.17 * (1 + math.sin(i * 1.05)))
        x = x0 + i * bw * 1.6
        lean = h * 0.05
        d.polygon([(x, h * 0.78), (x + bw, h * 0.78),
                   (x + bw + lean, h * 0.78 - hh), (x + lean, h * 0.78 - hh)],
                  fill=ink if i % 2 == 0 else PALE)
    d.rectangle((w * 0.08, h * 0.80, w * 0.92, h * 0.825), fill=PALE)


def draw_wedge(d: ImageDraw.ImageDraw, w: int, h: int, ink) -> None:
    d.polygon([(w * 0.18, h * 0.80), (w * 0.50, h * 0.14), (w * 0.82, h * 0.80)], fill=ink)
    d.polygon([(w * 0.34, h * 0.80), (w * 0.50, h * 0.46), (w * 0.66, h * 0.80)], fill=PALE)
    for i in range(3):
        y = h * (0.86 + i * 0.035)
        d.rectangle((w * (0.30 + i * 0.07), y, w * (0.70 - i * 0.07), y + h * 0.016), fill=ink)


def draw_steps(d: ImageDraw.ImageDraw, w: int, h: int, ink) -> None:
    # A staircase of blocks, left to right: nothing else in the set looks like it.
    n = 5
    bw = w * 0.74 / n
    for i in range(n):
        hh = h * (0.14 + i * 0.12)
        x = w * 0.13 + i * bw
        d.rectangle((x + bw * 0.08, h * 0.82 - hh, x + bw * 0.92, h * 0.82),
                    fill=ink if i % 2 == 0 else PALE)
    d.rectangle((w * 0.10, h * 0.83, w * 0.90, h * 0.855), fill=PALE)


SHAPES = {"rings": draw_rings, "bars": draw_bars, "wedge": draw_wedge, "steps": draw_steps}


def build_one(spec: dict, path: str) -> str:
    w, h = W * SS, H * SS
    img = Image.new("RGB", (w, h), spec["bg"][1])
    d = ImageDraw.Draw(img)
    gradient(d, w, h, spec["bg"][0], spec["bg"][1])
    SHAPES[spec["name"]](d, w, h, spec["ink"])

    # A thin inner frame on every image, so a half-lit screen still reads as a screen.
    d.rectangle((w * 0.035, h * 0.055, w * 0.965, h * 0.945),
                outline=tuple(int(c * 0.55) for c in PALE), width=int(h * 0.006))

    img = img.resize((W, H), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG", optimize=True)
    return path


def build(out_dir: str) -> list[str]:
    made = []
    for spec in IMAGES:
        path = os.path.join(out_dir, "screen_%d.png" % spec["id"])
        made.append(build_one(spec, path))
        print("screen image %d (%s) -> %s" % (spec["id"], spec["name"], path))
    return made


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.abspath(os.path.join(here, "..", "samples", "screens"))
    if len(sys.argv) > 1:
        target = sys.argv[1]
    build(target)
