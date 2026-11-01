"""Build unreal/spike/shots/012/maps_contact.png out of both maps' tour runs.

    python unreal/Tools/make_maps_sheet.py

One tile per shot from `unreal\\Tools\\map_check.py --game A` and `--game B`: the overview,
then for every slot the framed shot, the shot from the door the Player walked to, and the
shot from inside the content. The caption under each map's block carries that run's walk
result and frame times, straight out of the game's own `dc_tour.json`, so the sheet cannot
disagree with the run.

The individual screenshots are ~1.5 MB each and are git-ignored; this sheet is what goes in
the repo. Needs Pillow in the system Python, like the other sheets.
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
UNREAL = os.path.abspath(os.path.join(HERE, ".."))
RUNS = os.path.join(UNREAL, "_build", "runtime", "maps")
OUT = os.path.join(UNREAL, "spike", "shots", "012", "maps_contact.png")

SHOT_W = 520
COLUMNS = 3
PAD = 16
GAP = 10
CAPTION_H = 30
HEADER_H = 92
BLOCK_H = 74
BG = (24, 26, 30)
CELL = (34, 37, 42)
FG = (234, 238, 242)
SUB = (152, 160, 170)
GOOD = (130, 200, 140)
BAD = (226, 120, 100)


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
    folder = os.path.join(RUNS, game, "shots")
    tour_path = os.path.join(folder, "dc_tour.json")
    if not os.path.isdir(folder) or not os.path.exists(tour_path):
        return None
    with open(tour_path, "r", encoding="utf-8") as fh:
        tour = json.load(fh)
    shots = sorted(p for p in os.listdir(folder) if p.lower().endswith(".png"))
    return dict(game=game, folder=folder, tour=tour, shots=shots)


def main():
    games = [g for g in (load("A"), load("B")) if g]
    if not games:
        print("no map runs under %s - run unreal\\Tools\\map_check.py first" % RUNS)
        return 1

    first = Image.open(os.path.join(games[0]["folder"], games[0]["shots"][0]))
    shot_h = int(SHOT_W * first.height / first.width)

    width = PAD * 2 + COLUMNS * SHOT_W + (COLUMNS - 1) * GAP
    height = HEADER_H + PAD
    for g in games:
        rows = (len(g["shots"]) + COLUMNS - 1) // COLUMNS
        height += BLOCK_H + rows * (shot_h + CAPTION_H) + (rows - 1) * GAP + PAD
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)

    f_title = font(27, bold=True)
    f_block = font(21, bold=True)
    f_head = font(15)
    f_cap = font(15)

    draw.text((PAD, 16), "DynamicContents - the two maps, one packaged build", font=f_title,
              fill=FG)
    draw.text((PAD, 52),
              "Game A is a warm inland plaza with an avenue and a walled garden; Game B is a "
              "cool waterfront with a promenade and a pier. One environment kit, two palettes, "
              "two layouts, two lighting rigs.",
              font=f_head, fill=SUB)
    draw.text((PAD, 71),
              "No text, no signs, no logos and no names anywhere in either map. The build "
              "contains none of the content standing in the slots: every piece arrived over "
              "HTTP while the game was running.",
              font=f_head, fill=SUB)

    y = HEADER_H + PAD
    for g in games:
        tour = g["tour"]
        f = tour["frame_ms"]
        walks = tour["walks"]
        arrived = sum(1 for w in walks if w["arrived"])
        label = ("GAME A - the plaza (warm)" if g["game"] == "A"
                 else "GAME B - the waterfront (cool)")
        draw.text((PAD, y), f"{label}   ·   {tour['map']}", font=f_block, fill=FG)
        slots = "   ".join(f"{s['slot']} {s['size_class']}: {s['piece']} {s['version']} "
                           f"{s.get('brand') or 'no-brand'} {s.get('emblem') or ''}".strip()
                           for s in tour["slots"])
        draw.text((PAD, y + 26), slots, font=f_head, fill=SUB)
        draw.text((PAD, y + 46),
                  f"walk: {arrived}/{len(walks)} legs arrived   ·   frame time at 1600x900: "
                  f"average {f['average']:.2f} ms ({f['average_fps']:.0f} fps), median "
                  f"{f['median']:.2f} ms, worst 1% {f['worst_1_percent']:.2f} ms, worst "
                  f"{f['worst']:.2f} ms over {f['frames']} frames",
                  font=f_head, fill=GOOD if arrived == len(walks) else BAD)
        y += BLOCK_H

        for index, name in enumerate(g["shots"]):
            col, line = index % COLUMNS, index // COLUMNS
            x = PAD + col * (SHOT_W + GAP)
            ty = y + line * (shot_h + CAPTION_H + GAP)
            draw.rectangle([x, ty, x + SHOT_W, ty + shot_h + CAPTION_H], fill=CELL)
            shot = Image.open(os.path.join(g["folder"], name)).convert("RGB")
            sheet.paste(shot.resize((SHOT_W, shot_h), Image.LANCZOS), (x, ty))
            draw.text((x + 10, ty + shot_h + 7), os.path.splitext(name)[0].replace("_", "  "),
                      font=f_cap, fill=FG)
        rows = (len(g["shots"]) + COLUMNS - 1) // COLUMNS
        y += rows * (shot_h + CAPTION_H) + (rows - 1) * GAP + PAD

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sheet.save(OUT)
    print("wrote %s  (%d x %d, %d shot(s))"
          % (OUT, width, height, sum(len(g["shots"]) for g in games)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
