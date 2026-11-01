"""Build every environment piece: fresh scene -> .blend -> FBX + GLB -> preview -> manifest.

    blender -b --factory-startup -P art/blender/env/build_env.py
    blender -b --factory-startup -P art/blender/env/build_env.py -- --only tree_tall,bench
    blender -b --factory-startup -P art/blender/env/build_env.py -- --no-render

One FBX per piece: the geometry does not depend on the palette. Previews are rendered once
per palette, because the palette is the whole point of having two maps, and the two sheets
are what a cold reader looks at to see that Game B is not a re-skin of Game A.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback

import bpy

ENV_DIR = os.path.dirname(os.path.abspath(__file__))
BLENDER_DIR = os.path.abspath(os.path.join(ENV_DIR, ".."))
ART = os.path.abspath(os.path.join(BLENDER_DIR, ".."))
for _p in (BLENDER_DIR, ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dc_kit as K      # noqa: E402
import env_kit as E     # noqa: E402

MODULES = ("ground", "buildings", "props")


def registry():
    out = []
    for mod_name in MODULES:
        mod = importlib.import_module(mod_name)
        importlib.reload(mod)
        for pid in mod.PIECES:
            out.append((pid, mod_name, mod.BUILDERS[pid]))
    return out


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser(prog="build_env")
    ap.add_argument("--only", default="", help="comma list of piece ids")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--samples", type=int, default=32)
    return ap.parse_args(argv)


def build_one(pid, mod_name, builder, args):
    t0 = time.time()
    previews = {}

    meta = None
    fbx = glb = None
    for palette in sorted(E.PALETTES):
        K.reset_scene()
        piece = builder(palette)
        m = piece.finish()
        if palette == E.DEFAULT_PALETTE:
            meta = m
            blend_dir = os.path.join(ART, "blend_env")
            os.makedirs(blend_dir, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=os.path.join(blend_dir, "%s.blend" % pid),
                                        compress=True)
            out_dir = os.path.join(E.EXPORT_ROOT, pid)
            fbx, glb = E.export_env_piece(m, piece.mesh_objects(), out_dir)
        if not args.no_render:
            E.preview_world(palette)
            previews[palette] = E.render_preview(m, os.path.join(E.PREVIEW_ROOT, palette),
                                                 samples=args.samples)

    if args.no_render:
        # Carry forward whatever the last full build left on disk, exactly as the content
        # build does: --no-render is for re-exporting unchanged geometry.
        old = os.path.join(E.EXPORT_ROOT, pid, "manifest.json")
        if os.path.exists(old):
            try:
                with open(old, "r", encoding="utf-8") as fh:
                    prev = json.load(fh)
                for key, rel in (prev.get("previews") or {}).items():
                    abs_path = os.path.join(ART, rel.replace("/", os.sep))
                    if os.path.exists(abs_path):
                        previews[key] = abs_path
            except (OSError, ValueError):
                pass

    elapsed = time.time() - t0
    manifest = E.write_env_manifest(
        meta, os.path.join(E.EXPORT_ROOT, pid),
        piece_script=os.path.join(ENV_DIR, mod_name + ".py"),
        exports=dict(fbx=fbx, glb=glb),
        previews=previews,
        build_seconds=elapsed,
    )
    b = meta["bounds"]["size"]
    over = "" if meta["triangles"] <= meta["triangle_budget"] else "  OVER BUDGET"
    print("BUILT  %-14s %-9s %5.2f x %5.2f x %5.2f m  %6d/%-6d tris  %d mats  %4.1fs%s"
          % (pid, meta["category"], b[0], b[1], b[2], meta["triangles"],
             meta["triangle_budget"], meta["material_slot_count"], elapsed, over))
    return meta


def main():
    args = parse_args()
    todo = registry()
    if args.only:
        picks = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = picks - {pid for pid, _, _ in todo}
        if unknown:
            raise SystemExit("unknown env piece(s): %s" % ", ".join(sorted(unknown)))
        todo = [t for t in todo if t[0] in picks]

    os.makedirs(E.EXPORT_ROOT, exist_ok=True)
    ok, failed = [], []
    for pid, mod_name, builder in todo:
        try:
            build_one(pid, mod_name, builder, args)
            ok.append(pid)
        except Exception:                                   # noqa: BLE001
            traceback.print_exc()
            print("FAIL   %s" % pid)
            failed.append(pid)

    # The palette table the map builder reads, so colours live in exactly one place.
    with open(os.path.join(E.EXPORT_ROOT, "palettes.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        json.dump(dict(schema_version=E.SCHEMA_VERSION,
                       material_slots=list(E.ENV_MATERIAL_SLOTS),
                       palettes=E.all_palette_tables()), fh, indent=1)
        fh.write("\n")

    print("\nbuilt %d, failed %d" % (len(ok), len(failed)))
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
