"""The three committed sheets. The per-piece previews regenerate, so only these go in git.

    python art/tools/contact_sheet.py

  art/previews/contact_sheet.png   every build, exterior over interior
  art/previews/contact_ext.png     every exterior in one grid
  art/previews/swap_pairs.png      per content ID: v1 | v2, exteriors over interiors

Reads the manifests, so a sheet always matches what was actually built.
"""

from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

PAD = 12
BG = (26, 28, 32)
CELL_BG = (34, 37, 42)
FG = (232, 236, 240)
SUB = (150, 158, 168)
MISSING = (48, 52, 58)


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
            items.append(json.load(fh))
    items.sort(key=lambda m: (m["id"] != "default", m["id"], m["version"]))
    return items


def _shot(art, m, key, w, h):
    rel = m.get("previews", {}).get(key)
    if rel:
        p = os.path.join(art, rel.replace("/", os.sep))
        if os.path.exists(p):
            return Image.open(p).convert("RGB").resize((w, h), Image.LANCZOS)
    im = Image.new("RGB", (w, h), MISSING)
    ImageDraw.Draw(im).text((12, 12), "no %s preview" % key, font=_font(15), fill=SUB)
    return im


def _label(d, x, y, m, f_label, f_small, extra=""):
    s = m["bounds"]["size"]
    d.text((x + 9, y + 5), "%s  %s" % (m["id"], m["version"]), font=f_label, fill=FG)
    info = "class %s · %s · %.1f x %.1f x %.1f m · %s tris%s" % (
        m["size_class"], m.get("palette", "-"), s[0], s[1], s[2],
        "{:,}".format(m["triangles"]), extra)
    d.text((x + 9, y + 28), info, font=f_small, fill=SUB)


# ---------------------------------------------------------------------------- sheets
def build_contact(art, out_path, cols=3, cell_w=520):
    items = collect(art)
    if not items:
        print("nothing built yet")
        return None
    shot_h = int(cell_w * 9 / 16)
    label_h, head_h = 52, 70
    cell_h = label_h + shot_h * 2
    rows = (len(items) + cols - 1) // cols
    W = PAD + cols * (cell_w + PAD)
    H = PAD + head_h + rows * (cell_h + PAD)
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    f_t, f_l, f_s = _font(25), _font(20), _font(15)
    d.text((PAD, PAD + 2), "DynamicContents — content pieces", font=f_t, fill=FG)
    d.text((PAD, PAD + 34), "exterior (top) and interior (bottom) of every built piece-version",
           font=f_s, fill=SUB)

    for i, m in enumerate(items):
        r, c = divmod(i, cols)
        x = PAD + c * (cell_w + PAD)
        y = PAD + head_h + r * (cell_h + PAD)
        d.rectangle((x, y, x + cell_w, y + cell_h), fill=CELL_BG)
        _label(d, x, y, m, f_l, f_s, "  ·  fits %s" % ",".join(m["fits_slots"]))
        for k, key in enumerate(("ext", "int")):
            sheet.paste(_shot(art, m, key, cell_w, shot_h), (x, y + label_h + k * shot_h))

    sheet.save(out_path, "PNG", optimize=True)
    print("contact_sheet (%d) -> %s  %.1f MB" % (len(items), out_path,
                                                 os.path.getsize(out_path) / 1048576))
    return out_path


def build_ext(art, out_path, cols=3, cell_w=520):
    items = collect(art)
    if not items:
        return None
    shot_h = int(cell_w * 9 / 16)
    label_h, head_h = 52, 70
    cell_h = label_h + shot_h
    rows = (len(items) + cols - 1) // cols
    W = PAD + cols * (cell_w + PAD)
    H = PAD + head_h + rows * (cell_h + PAD)
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    f_t, f_l, f_s = _font(25), _font(20), _font(15)
    d.text((PAD, PAD + 2), "DynamicContents — exteriors", font=f_t, fill=FG)
    d.text((PAD, PAD + 34), "every built piece-version, three-quarter front view",
           font=f_s, fill=SUB)

    for i, m in enumerate(items):
        r, c = divmod(i, cols)
        x = PAD + c * (cell_w + PAD)
        y = PAD + head_h + r * (cell_h + PAD)
        d.rectangle((x, y, x + cell_w, y + cell_h), fill=CELL_BG)
        _label(d, x, y, m, f_l, f_s, "  ·  fits %s" % ",".join(m["fits_slots"]))
        sheet.paste(_shot(art, m, "ext", cell_w, shot_h), (x, y + label_h))

    sheet.save(out_path, "PNG", optimize=True)
    print("contact_ext   (%d) -> %s  %.1f MB" % (len(items), out_path,
                                                 os.path.getsize(out_path) / 1048576))
    return out_path


def build_swap(art, out_path, cell_w=480):
    """One block per content ID: v1 | v2 exteriors over v1 | v2 interiors."""
    items = collect(art)
    by_id = {}
    for m in items:
        by_id.setdefault(m["id"], {})[m["version"]] = m
    pairs = [(pid, v) for pid, v in sorted(by_id.items()) if "v1" in v and "v2" in v]
    if not pairs:
        print("no v1/v2 pairs yet")
        return None

    shot_h = int(cell_w * 9 / 16)
    label_h, head_h, block_gap = 50, 70, 16
    block_h = label_h + shot_h * 2
    W = PAD + 2 * (cell_w + PAD)
    H = PAD + head_h + len(pairs) * (block_h + block_gap)
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    f_t, f_l, f_s = _font(25), _font(20), _font(15)
    d.text((PAD, PAD + 2), "DynamicContents — what an update looks like", font=f_t, fill=FG)
    d.text((PAD, PAD + 34), "left: v1    right: v2    exterior over interior, same slot",
           font=f_s, fill=SUB)

    for i, (pid, vs) in enumerate(pairs):
        y = PAD + head_h + i * (block_h + block_gap)
        d.rectangle((PAD, y, W - PAD, y + block_h), fill=CELL_BG)
        for c, ver in enumerate(("v1", "v2")):
            m = vs[ver]
            x = PAD + c * (cell_w + PAD)
            _label(d, x, y, m, f_l, f_s)
            for k, key in enumerate(("ext", "int")):
                sheet.paste(_shot(art, m, key, cell_w, shot_h), (x, y + label_h + k * shot_h))

    sheet.save(out_path, "PNG", optimize=True)
    print("swap_pairs    (%d) -> %s  %.1f MB" % (len(pairs), out_path,
                                                 os.path.getsize(out_path) / 1048576))
    return out_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    art = os.path.abspath(os.path.join(here, ".."))
    prev = os.path.join(art, "previews")
    os.makedirs(prev, exist_ok=True)
    build_contact(art, os.path.join(prev, "contact_sheet.png"))
    build_ext(art, os.path.join(prev, "contact_ext.png"))
    build_swap(art, os.path.join(prev, "swap_pairs.png"))
