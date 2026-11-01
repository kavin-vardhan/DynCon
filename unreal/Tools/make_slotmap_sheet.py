"""Draw the pins on the captured maps and collect brief 013's evidence.

    python unreal/Tools/make_slotmap_sheet.py

The slot-map tool writes a map capture, a thumbnail per slot and a JSON that says where each
slot lands on the capture as a fraction of its width and height. The whole thing is only
worth anything if those fractions are right, and the only way to know is to **draw them on
the picture and look**. That is what this does.

It reads what `unreal\\Tools\\register_games.ps1` left in `unreal\\_build\\slotmap\\<game>\\`
and writes, into `unreal\\spike\\shots\\013\\`:

    <game>_map_pins.png       the capture with a pin, a ring and a label per slot
    <game>_<slot>.png         the eye-level thumbnail, as captured
    slotmap_contact.png       one sheet with both maps and all five thumbnails

The pins are drawn from the JSON, not from the world positions, so a pin that sits on its
slot proves the number the portal will use - not the number this script could have worked
out for itself.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
UNREAL = os.path.abspath(os.path.join(HERE, ".."))
SLOTMAP = os.path.join(UNREAL, "_build", "slotmap")
OUT_DIR = os.path.join(UNREAL, "spike", "shots", "013")
SHEET = os.path.join(OUT_DIR, "slotmap_contact.png")

BG = (24, 26, 30)
CELL = (34, 37, 42)
FG = (234, 238, 242)
SUB = (152, 160, 170)
PIN = (226, 61, 61)
PIN_INK = (255, 255, 255)

MAP_W = 980
THUMB_W = 470
PAD = 16
GAP = 10
CAPTION_H = 30
HEADER_H = 96
BLOCK_H = 70


def font(size, bold=False):
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf",
                                                          "DejaVuSans.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def load(game):
    folder = os.path.join(SLOTMAP, game)
    meta_path = os.path.join(folder, "%s.slots.json" % game)
    image_path = os.path.join(folder, "%s.png" % game)
    if not (os.path.exists(meta_path) and os.path.exists(image_path)):
        return None
    with open(meta_path, "r", encoding="utf-8-sig") as fh:
        meta = json.load(fh)
    return dict(game=game, folder=folder, meta=meta, image=image_path)


def draw_pins(entry):
    """The capture with every pin drawn where the JSON says the slot is."""
    image = Image.open(entry["image"]).convert("RGB")
    draw = ImageDraw.Draw(image)
    w, h = image.size
    radius = max(12, int(min(w, h) * 0.022))
    f_label = font(max(20, int(min(w, h) * 0.030)), bold=True)
    f_sub = font(max(15, int(min(w, h) * 0.021)))

    for slot in entry["meta"]["slots"]:
        cx = int(slot["px"]["x"] * w)
        cy = int(slot["px"]["y"] * h)
        # a ring the size of the slot's own footprint, so "the pin sits on its slot" is
        # something a reader can actually check rather than take on trust
        metres_per_px = float(entry["meta"]["world"]["width_m"]) / w
        half = float(slot["limits_m"]["x"]) * 0.5 / max(metres_per_px, 1e-6)
        draw.rectangle([cx - half, cy - half, cx + half, cy + half],
                       outline=PIN, width=max(2, radius // 6))
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                     fill=PIN, outline=PIN_INK, width=max(2, radius // 5))
        text = "%s  %s" % (slot["id"], slot["size_class"])
        draw.text((cx + radius + 8, cy - radius - 4), text, font=f_label, fill=PIN_INK,
                  stroke_width=3, stroke_fill=(0, 0, 0))
        draw.text((cx + radius + 8, cy + radius - 10),
                  "px %.3f, %.3f" % (slot["px"]["x"], slot["px"]["y"]),
                  font=f_sub, fill=PIN_INK, stroke_width=3, stroke_fill=(0, 0, 0))

    out = os.path.join(OUT_DIR, "%s_map_pins.png" % entry["game"])
    image.save(out)
    print("wrote %s  (%d x %d, %d pin(s))" % (out, w, h, len(entry["meta"]["slots"])))
    return out


def copy_thumbs(entry):
    out = []
    for slot in entry["meta"]["slots"]:
        name = slot["thumb"]["file"]
        src = os.path.join(entry["folder"], name)
        if not os.path.exists(src):
            print("MISSING thumbnail %s" % src)
            continue
        dst = os.path.join(OUT_DIR, name)
        shutil.copyfile(src, dst)
        out.append(dst)
    return out


def sheet(entries, pins, thumbs):
    f_title = font(27, bold=True)
    f_block = font(21, bold=True)
    f_head = font(15)
    f_cap = font(15)

    blocks = []
    for entry in entries:
        pin = Image.open(pins[entry["game"]]).convert("RGB")
        map_h = int(MAP_W * pin.height / pin.width)
        shots = [Image.open(p).convert("RGB") for p in thumbs[entry["game"]]]
        thumb_h = int(THUMB_W * shots[0].height / shots[0].width) if shots else 0
        rows = (len(shots) + 1) // 2
        blocks.append(dict(entry=entry, pin=pin, map_h=map_h, shots=shots,
                           thumb_h=thumb_h, rows=rows))

    width = PAD * 2 + max(MAP_W, 2 * THUMB_W + GAP)
    height = HEADER_H + PAD
    for b in blocks:
        height += (BLOCK_H + b["map_h"] + CAPTION_H + GAP
                   + b["rows"] * (b["thumb_h"] + CAPTION_H) + (b["rows"] - 1) * GAP + PAD)

    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.text((PAD, 16), "DynamicContents - the slot map the plugin makes", font=f_title,
              fill=FG)
    draw.text((PAD, 52),
              "The developer's half of the plugin: an orthographic capture of the playable "
              "area, every slot's pixel position measured on it, and an eye-level thumbnail "
              "of each slot with its content hidden.",
              font=f_head, fill=SUB)
    draw.text((PAD, 71),
              "The pins and the footprint rings below are drawn from the JSON the tool sent "
              "to POST /games/register - the same numbers the portal puts its pins at.",
              font=f_head, fill=SUB)

    y = HEADER_H + PAD
    for b in blocks:
        entry = b["entry"]
        meta = entry["meta"]
        label = ("GAME A - the plaza (warm)" if entry["game"] == "A"
                 else "GAME B - the waterfront (cool)")
        draw.text((PAD, y), "%s   ·   %s" % (label, meta["map"]), font=f_block, fill=FG)
        draw.text((PAD, y + 26),
                  "capture %d x %d px of %.0f x %.0f m   ·   playable area from %s   ·   "
                  "camera %.0f m up, orthographic"
                  % (meta["image"]["width"], meta["image"]["height"],
                     meta["world"]["width_m"], meta["world"]["height_m"],
                     meta["world"]["playable_area_from"],
                     meta["world"]["camera_m"]["z"]),
                  font=f_head, fill=SUB)
        draw.text((PAD, y + 46),
                  "   ".join("%s %s px(%.3f, %.3f) rating %s pre-fetch %.0f m"
                             % (s["id"], s["size_class"], s["px"]["x"], s["px"]["y"],
                                s["rating_rule"], s["prefetch_radius_m"])
                             for s in meta["slots"]),
                  font=f_head, fill=SUB)
        y += BLOCK_H

        draw.rectangle([PAD, y, PAD + MAP_W, y + b["map_h"] + CAPTION_H], fill=CELL)
        image.paste(b["pin"].resize((MAP_W, b["map_h"]), Image.LANCZOS), (PAD, y))
        draw.text((PAD + 10, y + b["map_h"] + 7),
                  "%s.png with the registered pin positions drawn on it" % entry["game"],
                  font=f_cap, fill=FG)
        y += b["map_h"] + CAPTION_H + GAP

        for index, shot in enumerate(b["shots"]):
            col, line = index % 2, index // 2
            x = PAD + col * (THUMB_W + GAP)
            ty = y + line * (b["thumb_h"] + CAPTION_H + GAP)
            draw.rectangle([x, ty, x + THUMB_W, ty + b["thumb_h"] + CAPTION_H], fill=CELL)
            image.paste(shot.resize((THUMB_W, b["thumb_h"]), Image.LANCZOS), (x, ty))
            slot = meta["slots"][index]
            draw.text((x + 10, ty + b["thumb_h"] + 7),
                      "%s - eye level %.1f m, %.0f m out, content hidden"
                      % (slot["id"], slot["thumb"]["eye_height_m"],
                         slot["thumb"]["stand_off_m"]),
                      font=f_cap, fill=FG)
        y += b["rows"] * (b["thumb_h"] + CAPTION_H) + (b["rows"] - 1) * GAP + PAD

    os.makedirs(OUT_DIR, exist_ok=True)
    image.save(SHEET)
    print("wrote %s  (%d x %d)" % (SHEET, width, height))


def main():
    entries = [e for e in (load("A"), load("B")) if e]
    if not entries:
        print("nothing under %s - run unreal\\Tools\\register_games.ps1 first" % SLOTMAP)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)

    pins, thumbs = {}, {}
    for entry in entries:
        pins[entry["game"]] = draw_pins(entry)
        thumbs[entry["game"]] = copy_thumbs(entry)
    sheet(entries, pins, thumbs)

    # a plain text summary next to the pictures, so the numbers are readable without PIL
    lines = []
    for entry in entries:
        meta = entry["meta"]
        lines.append("game %s  %s" % (entry["game"], meta["map"]))
        lines.append("  capture %d x %d px of %.1f x %.1f m, camera %.0f m up, %s"
                     % (meta["image"]["width"], meta["image"]["height"],
                        meta["world"]["width_m"], meta["world"]["height_m"],
                        meta["world"]["camera_m"]["z"],
                        meta["world"]["playable_area_from"]))
        for s in meta["slots"]:
            lines.append("  %-3s %-2s  px %.4f %.4f  world %.1f %.1f %.2f m  rating %s  "
                         "pre-fetch %.0f m  thumb %s (eye %.1f m, %.0f m out)"
                         % (s["id"], s["size_class"], s["px"]["x"], s["px"]["y"],
                            s["world_m"]["x"], s["world_m"]["y"], s["world_m"]["z"],
                            s["rating_rule"], s["prefetch_radius_m"],
                            s["thumb"]["file"], s["thumb"]["eye_height_m"],
                            s["thumb"]["stand_off_m"]))
        lines.append("")
    path = os.path.join(OUT_DIR, "slotmap_result.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print("wrote %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
