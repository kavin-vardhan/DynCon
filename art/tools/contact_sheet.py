"""One sheet with every piece's exterior and interior preview, labelled by functional ID.

    python art/tools/contact_sheet.py            -> art/previews/contact_sheet.png

Reads the manifests so the sheet always matches what was actually built.
"""

from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

CELL_W = 560
SHOT_H = 315                 # 16:9 at CELL_W
LABEL_H = 58
HEAD_H = 74
PAD = 14
COLS = 3
BG = (26, 28, 32)
FG = (232, 236, 240)
SUB = (150, 158, 168)


def _font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def collect(art):
    root = os.path.join(art, "export")
    items = []
    if not os.path.isdir(root):
        return items
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name, "manifest.json")
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as fh:
            m = json.load(fh)
        items.append(m)
    items.sort(key=lambda m: (m["id"] != "default", m["id"], m["version"]))
    return items


def build(art, out_path, cols=COLS):
    items = collect(art)
    if not items:
        print("nothing built yet — no manifests under art/export")
        return None

    rows = (len(items) + cols - 1) // cols
    cell_h = LABEL_H + SHOT_H * 2 + PAD
    W = PAD + cols * (CELL_W + PAD)
    H = PAD + HEAD_H + rows * (cell_h + PAD)
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)

    f_title = _font(26)
    f_label = _font(21)
    f_small = _font(16)
    d.text((PAD, PAD + 2), "DynamicContents — content pieces", font=f_title, fill=FG)
    d.text((PAD, PAD + 36), "exterior (top) and interior (bottom) of every built piece-version",
           font=f_small, fill=SUB)

    for i, m in enumerate(items):
        r, c = divmod(i, cols)
        x = PAD + c * (CELL_W + PAD)
        y = PAD + HEAD_H + r * (cell_h + PAD)

        d.rectangle((x, y, x + CELL_W, y + cell_h), fill=(34, 37, 42))
        s = m["bounds"]["size"]
        d.text((x + 10, y + 7), "%s  %s" % (m["id"], m["version"]), font=f_label, fill=FG)
        info = "class %s · %.1f x %.1f x %.1f m · %s tris · fits %s" % (
            m["size_class"], s[0], s[1], s[2], "{:,}".format(m["triangles"]),
            ",".join(m["fits_slots"]))
        d.text((x + 10, y + 34), info, font=f_small, fill=SUB)

        for k, key in enumerate(("ext", "int")):
            rel = m.get("previews", {}).get(key)
            box = (x, y + LABEL_H + k * SHOT_H, x + CELL_W, y + LABEL_H + (k + 1) * SHOT_H)
            if rel and os.path.exists(os.path.join(art, rel)):
                im = Image.open(os.path.join(art, rel)).convert("RGB")
                im = im.resize((CELL_W, SHOT_H), Image.LANCZOS)
                sheet.paste(im, (box[0], box[1]))
            else:
                d.rectangle(box, fill=(48, 52, 58))
                d.text((box[0] + 12, box[1] + 12), "no %s preview" % key, font=f_small, fill=SUB)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    print("contact sheet (%d pieces) -> %s" % (len(items), out_path))
    return out_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    art = os.path.abspath(os.path.join(here, ".."))
    out = os.path.join(art, "previews", "contact_sheet.png")
    if len(sys.argv) > 1:
        out = sys.argv[1]
    build(art, out)
