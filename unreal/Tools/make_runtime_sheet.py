"""Build one contact sheet out of a runtime-client run's screenshots.

    python unreal/Tools/make_runtime_sheet.py
    python unreal/Tools/make_runtime_sheet.py --shots <dir> --out <file> --title "..."

One tile per activation, in the order they happened, captioned with what arrived and what
each step of the lifecycle cost. The source of truth is the game's own `dc_status.json`, so
the sheet cannot disagree with the run. The individual screenshots are ~1.6 MB each and are
git-ignored; this sheet is what goes in the repo.

Needs Pillow in the system Python, like the art-side sheets.
"""
from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
UNREAL = os.path.abspath(os.path.join(HERE, ".."))
DEFAULT_SHOTS = os.path.join(UNREAL, "_build", "runtime", "exit_test", "shots")
DEFAULT_OUT = os.path.join(UNREAL, "spike", "shots", "011", "runtime_contact.png")

PAD = 16
GAP = 10
CAPTION_H = 62
HEADER_H = 96
COLUMNS = 3
TILE_W = 520
BG = (26, 28, 32)
CELL_BG = (34, 37, 42)
FG = (232, 236, 240)
SUB = (150, 158, 168)
ACCENT = (120, 200, 230)


def font(size: int, bold: bool = False):
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf",
                                                          "DejaVuSans.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", default=DEFAULT_SHOTS)
    ap.add_argument("--status", default="")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--title", default="DynamicContents - runtime client, one packaged run")
    args = ap.parse_args()

    status_path = args.status or os.path.join(os.path.dirname(args.shots), "dc_status.json")
    with open(status_path, "r", encoding="utf-8") as handle:
        status = json.load(handle)

    rows = [a for a in status.get("activations", []) if a.get("shot")]
    if not rows:
        print("no activations with a screenshot in %s" % status_path)
        return 1

    # Every shot is the same size; measure the first one.
    first = Image.open(os.path.join(args.shots, rows[0]["shot"]))
    tile_h = int(TILE_W * first.height / first.width)
    cols = min(COLUMNS, len(rows))
    tiles = len(rows)
    lines = (tiles + cols - 1) // cols

    width = PAD * 2 + cols * TILE_W + (cols - 1) * GAP
    height = HEADER_H + PAD * 2 + lines * (tile_h + CAPTION_H) + (lines - 1) * GAP
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)

    f_title = font(26, bold=True)
    f_head = font(15)
    f_cap = font(16, bold=True)
    f_sub = font(13)

    draw.text((PAD, 18), args.title, font=f_title, fill=FG)
    draw.text((PAD, 54),
              "build %s  ·  backend %s  ·  game %s  ·  restarts %s  ·  content loading screens %s  "
              "·  packs mounted %s  ·  the build contains none of this content"
              % (status.get("build"), status.get("backend"), status.get("game"),
                 status.get("restarts"), status.get("content_loading_screens"),
                 status.get("packs_mounted")),
              font=f_head, fill=SUB)
    draw.text((PAD, 74), "crypto: %s" % status.get("crypto", ""), font=f_sub, fill=SUB)

    for index, row in enumerate(rows):
        col, line = index % cols, index // cols
        x = PAD + col * (TILE_W + GAP)
        y = HEADER_H + PAD + line * (tile_h + CAPTION_H + GAP)
        draw.rectangle([x, y, x + TILE_W, y + tile_h + CAPTION_H], fill=CELL_BG)

        path = os.path.join(args.shots, row["shot"])
        if os.path.exists(path):
            shot = Image.open(path).convert("RGB").resize((TILE_W, tile_h), Image.LANCZOS)
            sheet.paste(shot, (x, y))

        brand = ("%s %s" % (row.get("brand") or "", row.get("emblem") or "")).strip() or "no-brand"
        draw.text((x + 10, y + tile_h + 8),
                  "#%s  %s  %s %s  %s" % (row["seq"], row["slot"], row["piece"],
                                          row["version"], brand),
                  font=f_cap, fill=FG)
        draw.text((x + 10, y + tile_h + 30),
                  "resolve %.0f · download %.0f · verify %.0f · mount %.1f · load %.1f · "
                  "spawn %.1f ms   =  %.0f ms"
                  % (row["resolve_ms"], row["download_ms"], row["verify_ms"], row["mount_ms"],
                     row["load_ms"], row["spawn_ms"], row["total_ms"]),
                  font=f_sub, fill=SUB)
        draw.text((x + 10, y + tile_h + 45),
                  "%s  ·  %.0f kB over the network, %d file(s) cached, %d range request(s)"
                  % (row.get("source", ""), row.get("network_bytes", 0) / 1024.0,
                     row.get("cached_files", 0), row.get("range_requests", 0)),
                  font=f_sub, fill=ACCENT)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    sheet.save(args.out)
    print("wrote %s  (%d x %d, %d tiles)" % (args.out, width, height, tiles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
