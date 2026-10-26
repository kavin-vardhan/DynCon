"""Build unreal/spike/shots/engine_contact.png out of one packaged run's screenshots.

    python unreal/Tools/make_engine_sheet.py
    python unreal/Tools/make_engine_sheet.py --shots <dir> --out <file>

One row per pack, in the order of unreal/Tools/chunk_ids.json: the outside three-quarter shot
next to the shot taken from inside, with the numbers the run reported underneath. The
individual shots are git-ignored (they are ~1 MB each); this sheet is what goes in the repo.

Needs Pillow in the system Python, like the art-side sheets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
UNREAL = os.path.abspath(os.path.join(HERE, ".."))

PAD = 14
GAP = 8
LABEL_H = 54
BG = (26, 28, 32)
CELL_BG = (34, 37, 42)
FG = (232, 236, 240)
SUB = (150, 158, 168)
BAD = (226, 112, 100)
MISSING = (48, 52, 58)
SHOT_W = 540          # per shot; two per row, so the sheet is ~1100 px wide


def font(size, bold=False):
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def parse_result(path):
    """The per-step lines of spike_result.txt, keyed by pack name."""
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.search(r"\bpack=(\S+)", line)
            if not m or "mount=" not in line:
                continue
            fields = {}
            for key in ("slot", "mount", "load", "spawn", "size", "fit", "pak", "utoc", "ucas", "total"):
                hit = re.search(r"\b%s=(\S+)" % key, line)
                if hit:
                    fields[key] = hit.group(1)
            # mount=ok(FCoreDelegates::MountPak, 17.8 ms) -> ok / 17.8
            for key in ("mount", "load", "spawn"):
                hit = re.search(r"\b%s=(\w+)\([^)]*?([\d.]+) ms\)" % key, line)
                if hit:
                    fields[key] = hit.group(1)
                    fields[key + "_ms"] = hit.group(2)
            hit = re.search(r"\bsize=([\d.]+x[\d.]+x[\d.]+) cm", line)
            if hit:
                fields["size"] = hit.group(1)
            hit = re.search(r"\btotal=(\d+) B", line)
            if hit:
                fields["total"] = hit.group(1)
            rows[m.group(1)] = fields
    return rows


def pack_order(chunk_ids):
    with open(chunk_ids, "r", encoding="utf-8") as fh:
        table = json.load(fh)
    return ["%s_%s" % (r["id"], r["version"]) for r in table["packs"]]


def find_shot(shot_dir, pack, suffix):
    for name in sorted(os.listdir(shot_dir)):
        if name.endswith("_%s_%s.png" % (pack, suffix)):
            return os.path.join(shot_dir, name)
    return None


def cell(path, w, h, caption):
    if path and os.path.exists(path):
        im = Image.open(path).convert("RGB")
        im = im.resize((w, h), Image.LANCZOS)
    else:
        im = Image.new("RGB", (w, h), MISSING)
        ImageDraw.Draw(im).text((14, 14), "no %s shot" % caption, font=font(16), fill=BAD)
    return im


def human_bytes(text):
    try:
        n = int(text)
    except (TypeError, ValueError):
        return "?"
    return "%.0f kB" % (n / 1024.0) if n < 1024 * 1024 else "%.2f MB" % (n / 1048576.0)


def build(shot_dir, out_path, chunk_ids):
    packs = pack_order(chunk_ids)
    results = parse_result(os.path.join(shot_dir, "spike_result.txt"))

    # Every shot in a run is the same size; take the first one to get the aspect.
    sample = None
    for pack in packs:
        sample = find_shot(shot_dir, pack, "out") or find_shot(shot_dir, pack, "in")
        if sample:
            break
    if sample is None:
        print("no screenshots under %s" % shot_dir)
        return 1
    with Image.open(sample) as probe:
        aspect = probe.height / float(probe.width)
    shot_h = int(round(SHOT_W * aspect))

    cols_w = SHOT_W * 2 + GAP
    row_h = shot_h + LABEL_H
    head_h = 70

    width = cols_w + PAD * 2
    height = head_h + len(packs) * (row_h + PAD) + PAD
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)

    draw.text((PAD, 16), "DynamicContents - every pack mounted and spawned in one packaged run",
              font=font(22, bold=True), fill=FG)
    draw.text((PAD, 44),
              "left: three-quarter view from outside   right: from SOCKET_Inside, looking at the screen",
              font=font(14), fill=SUB)

    y = head_h
    for pack in packs:
        draw.rectangle([PAD - 4, y - 4, PAD + cols_w + 4, y + row_h + 4], fill=CELL_BG)
        sheet.paste(cell(find_shot(shot_dir, pack, "out"), SHOT_W, shot_h, "outside"), (PAD, y))
        sheet.paste(cell(find_shot(shot_dir, pack, "in"), SHOT_W, shot_h, "inside"),
                    (PAD + SHOT_W + GAP, y))

        r = results.get(pack, {})
        draw.text((PAD + 2, y + shot_h + 6), pack, font=font(18, bold=True), fill=FG)

        fit_ok = r.get("fit") == "yes"
        line = "slot %s   mount %s ms   load %s ms   spawn %s ms   %s   pack %s" % (
            r.get("slot", "?"), r.get("mount_ms", "?"), r.get("load_ms", "?"),
            r.get("spawn_ms", "?"), r.get("size", "?") + " cm", human_bytes(r.get("total")))
        draw.text((PAD + 2, y + shot_h + 30), line, font=font(13), fill=SUB)

        status = "fits" if fit_ok else "DOES NOT FIT"
        tw = draw.textlength(status, font=font(13, bold=True))
        draw.text((PAD + cols_w - tw - 4, y + shot_h + 30), status,
                  font=font(13, bold=True), fill=SUB if fit_ok else BAD)

        y += row_h + PAD

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    print("wrote %s (%d x %d, %d rows)" % (out_path, width, height, len(packs)))
    return 0


def main():
    ap = argparse.ArgumentParser(prog="make_engine_sheet")
    ap.add_argument("--shots", default=os.path.join(UNREAL, "spike", "shots"))
    ap.add_argument("--out", default=os.path.join(UNREAL, "spike", "shots", "engine_contact.png"))
    ap.add_argument("--chunk-ids", default=os.path.join(UNREAL, "Tools", "chunk_ids.json"))
    args = ap.parse_args()
    return build(args.shots, args.out, args.chunk_ids)


if __name__ == "__main__":
    sys.exit(main())
