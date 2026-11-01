"""Build one contact sheet out of the state exit test's screenshots (brief 016).

    python unreal/Tools/make_state_sheet.py
    python unreal/Tools/make_state_sheet.py --shots <dir> --out <file> --rounds 1,3,8

One row per round, four pictures across: what the Player set, the strip holding the
replacement as SWAP PENDING while they are still inside, what came up once they walked out,
and what they found on walking back in. The captions come out of the game's own
`dc_state_test.json`, so the sheet cannot disagree with the run.

The individual screenshots are ~1.6 MB each and are git-ignored; this sheet is what goes in
the repo - the same rule as the art previews and the portal's exit test.

Needs Pillow in the system Python, like the other sheets.
"""
from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
UNREAL = os.path.abspath(os.path.join(HERE, ".."))
DEFAULT_SHOTS = os.path.join(UNREAL, "_build", "runtime", "state_test", "shots")
DEFAULT_OUT = os.path.join(UNREAL, "spike", "shots", "016", "state_contact.png")

PAD = 16
GAP = 8
CAPTION_H = 40
ROW_LABEL_H = 30
HEADER_H = 104
TILE_W = 440
BG = (26, 28, 32)
CELL_BG = (34, 37, 42)
FG = (232, 236, 240)
SUB = (150, 158, 168)
ACCENT = (120, 200, 230)
PASS = (120, 210, 150)
FAIL = (240, 120, 120)

STEPS = ["set", "pending", "swapped", "back"]
STEP_WORDS = {
    "set": "inside: door open, lights B on, screen 3",
    "pending": "SWAP PENDING - the Player is inside, the old one stays",
    "swapped": "walked out - the new one is up",
    "back": "walked back in",
}


def font(size: int, bold: bool = False):
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf",
                                                          "DejaVuSans.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def state_words(state: dict) -> str:
    return ("A on" if state.get("light_a_on") else "A off") + \
           (", B on" if state.get("light_b_on") else ", B off") + \
           (", door open" if state.get("door_open") else ", door shut") + \
           ", screen %s" % state.get("screen_image_index")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", default=DEFAULT_SHOTS)
    ap.add_argument("--result", default="")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--rounds", default="", help="comma list; default every round")
    ap.add_argument("--title",
                    default="DynamicContents - state kept across a swap, one packaged run")
    args = ap.parse_args()

    result_path = args.result or os.path.join(args.shots, "dc_state_test.json")
    with open(result_path, "r", encoding="utf-8") as handle:
        result = json.load(handle)

    rounds = result.get("rounds", [])
    if args.rounds:
        want = {int(n) for n in args.rounds.split(",") if n.strip()}
        rounds = [r for r in rounds if r["n"] in want]
    rounds = [r for r in rounds if r.get("shots")]
    if not rounds:
        print("no rounds with screenshots in %s" % result_path)
        return 1

    first = None
    for row in rounds:
        for name in row["shots"]:
            path = os.path.join(args.shots, name)
            if os.path.exists(path):
                first = Image.open(path)
                break
        if first:
            break
    if first is None:
        print("none of the screenshots named in %s are on disk" % result_path)
        return 1
    tile_h = int(TILE_W * first.height / first.width)

    cols = len(STEPS)
    row_h = ROW_LABEL_H + tile_h + CAPTION_H
    width = PAD * 2 + cols * TILE_W + (cols - 1) * GAP
    height = HEADER_H + PAD * 2 + len(rounds) * row_h + (len(rounds) - 1) * GAP
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)

    f_title = font(26, bold=True)
    f_head = font(15)
    f_row = font(17, bold=True)
    f_cap = font(14)

    passed = sum(1 for r in result.get("rounds", []) if r["ok"])
    total = len(result.get("rounds", []))
    use = result.get("interaction", {})
    draw.text((PAD, 16), args.title, font=f_title, fill=FG)
    draw.text((PAD, 52),
              "build %s  ·  %s  ·  slot %s  ·  %d / %d rounds kept the state  ·  "
              "%d interactions (door %d, lights A %d, lights B %d, screen %d)"
              % (result.get("build"), result.get("map"), result.get("slot"),
                 passed, total, use.get("uses", 0), use.get("door", 0),
                 use.get("light_a", 0), use.get("light_b", 0), use.get("screen", 0)),
              font=f_head, fill=SUB)
    draw.text((PAD, 74),
              "the build contains none of this content; every piece arrived over HTTP while "
              "the game was running, and nothing restarted",
              font=f_head, fill=SUB)

    for index, row in enumerate(rounds):
        y0 = HEADER_H + PAD + index * (row_h + GAP)
        mark = "PASS" if row["ok"] else "FAIL"
        label = ("round %d  ·  %s %s -> %s %s  ·  %s  ·  left [%s]  found [%s]  ·  %s"
                 % (row["n"], row["before_piece"], row["before_version"],
                    row["after_piece"], row["after_version"], row["kind"],
                    state_words(row["left"]), state_words(row["found"]), mark))
        draw.text((PAD, y0 + 4), label, font=f_row, fill=PASS if row["ok"] else FAIL)

        for col, step in enumerate(STEPS):
            x = PAD + col * (TILE_W + GAP)
            y = y0 + ROW_LABEL_H
            draw.rectangle([x, y, x + TILE_W, y + tile_h + CAPTION_H], fill=CELL_BG)
            name = next((s for s in row["shots"] if ("_%s." % step) in s), None)
            path = os.path.join(args.shots, name) if name else ""
            if path and os.path.exists(path):
                shot = Image.open(path).convert("RGB").resize((TILE_W, tile_h), Image.LANCZOS)
                sheet.paste(shot, (x, y))
            else:
                draw.text((x + 12, y + tile_h // 2), "(no picture)", font=f_cap, fill=SUB)
            draw.text((x + 8, y + tile_h + 6), STEP_WORDS[step], font=f_cap, fill=ACCENT)
            if step == "pending":
                draw.text((x + 8, y + tile_h + 22),
                          "held %.1f s before the Player walked out" % row["swap_pending_s"],
                          font=f_cap, fill=SUB)
            if step == "swapped":
                draw.text((x + 8, y + tile_h + 22),
                          "applied %.1f s after they set off out" % row["swap_s"],
                          font=f_cap, fill=SUB)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    sheet.save(args.out)
    print("wrote %s  (%d x %d, %d round(s))" % (args.out, width, height, len(rounds)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
