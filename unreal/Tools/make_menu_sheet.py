"""Contact sheets for brief 018's exit test, so the per-shot PNGs need not go in git.

    python unreal/Tools/make_menu_sheet.py

Two sheets out of `unreal/spike/shots/018/`:

  `menu_contact.png`  the eight beats of the menu run at 1600 x 900 - attract, the title
                      menu, the X-ray with the pause menu over it, the X-ray from third
                      person, the loading line, A1 as the Player left it, A1 as they found
                      it two game switches later, and the attract loop again;
  `xray_contact.png`  the X-ray at 1080p over one lap of the scripted tour.

Same rule as every other sheet here: the individual shots are ~2 MB each and are rebuilt by
the test, so only the sheet goes in the repo.
"""
from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.abspath(os.path.join(HERE, "..", "spike", "shots", "018"))

PAD, GAP = 18, 8
CAPTION_H = 34
HEADER_H = 86
BG = (26, 28, 32)
FG = (232, 236, 240)
SUB = (150, 158, 168)
ACCENT = (120, 200, 230)
PASS = (120, 210, 150)
FAIL = (240, 120, 120)

# The eight beats of the menu run, in the order they happen, with what each one is for.
MENU = [
    ("01_01_attract.png", "boot: the attract loop, no Player, the strip up"),
    ("02_02_title.png", "a button: the title menu, the registered plan views as card art"),
    ("01_03_xray_pause.png", "Game B, at B1: the pause menu with the X-ray turned on"),
    ("02_04_xray_world.png", "resumed: the X-ray from third person, rings on the ground"),
    ("03_05_loading.png", "switch game: a level load, and the one loading screen there is"),
    ("01_06_a1_as_left.png", "Game A, inside A1: door open, wall lamps on, screen 3"),
    ("01_07_a1_as_found.png", "after A -> B -> A: exactly as it was left"),
    ("02_08_attract_again.png", "the idle timeout: back in the attract loop"),
]


def font(size: int, bold: bool = False):
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def sheet(folder: str, items: list[tuple[str, str]], out: str, title: str, sub: str,
          columns: int = 2, tile_w: int = 760) -> str | None:
    tiles = []
    for name, caption in items:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        image = Image.open(path).convert("RGB")
        scale = tile_w / image.width
        tiles.append((image.resize((tile_w, int(image.height * scale)), Image.LANCZOS),
                      caption))
    if not tiles:
        print(f"nothing to put on {out}")
        return None

    tile_h = max(t.height for t, _ in tiles)
    rows = (len(tiles) + columns - 1) // columns
    width = PAD * 2 + columns * tile_w + (columns - 1) * GAP
    height = PAD * 2 + HEADER_H + rows * (tile_h + CAPTION_H + GAP)
    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas)

    draw.text((PAD, PAD), title, font=font(30, True), fill=FG)
    for n, line in enumerate(sub.split("\n")):
        draw.text((PAD, PAD + 40 + n * 22), line, font=font(17),
                  fill=ACCENT if n == 0 else SUB)

    for index, (tile, caption) in enumerate(tiles):
        x = PAD + (index % columns) * (tile_w + GAP)
        y = PAD + HEADER_H + (index // columns) * (tile_h + CAPTION_H + GAP)
        canvas.paste(tile, (x, y))
        draw.text((x, y + tile_h + 8), f"{index + 1}. {caption}", font=font(16), fill=SUB)

    canvas.save(out)
    print(f"wrote {out}  ({width} x {height}, {len(tiles)} shot(s))")
    return out


def read_result(folder: str) -> dict:
    path = os.path.join(folder, "result.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", default=SHOTS)
    args = ap.parse_args(argv)

    menu_dir = os.path.join(args.shots, "menu_1600x900")
    result = read_result(menu_dir)
    ui = result.get("ui", {})
    verdict = "PASS" if not result.get("problems") else "FAIL"
    sheet(menu_dir, MENU, os.path.join(args.shots, "menu_contact.png"),
          "Brief 018 exit test - the booth's front end, one run, no restart",
          f"{verdict}: {ui.get('game_switches', '?')} game switches, "
          f"restarts {ui.get('restarts', '?')}, content loading screens "
          f"{ui.get('content_loading_screens', '?')}, "
          f"uptime {ui.get('uptime_s', 0):.0f} s, "
          f"{ui.get('packs_mounted', '?')} packs mounted\n"
          "1600 x 900. Driven by -DCUiTest, which calls the same handlers the pad's "
          "Enhanced Input bindings call.")

    xray_dir = os.path.join(args.shots, "xray_1920x1080")
    shots = sorted(n for n in os.listdir(xray_dir) if n.endswith(".png")) \
        if os.path.isdir(xray_dir) else []
    sheet(xray_dir, [(n, n[3:-4].replace("_", " ")) for n in shots],
          os.path.join(args.shots, "xray_contact.png"),
          "Brief 018 - the X-ray view at 1920 x 1080",
          "One lap of the scripted tour with the overlay on: the pre-fetch rings, the "
          "nearest slot's manifest,\nthe pack cache in LRU order, the lifecycle log and "
          "the rolling frame-time graph.", columns=2, tile_w=760)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
