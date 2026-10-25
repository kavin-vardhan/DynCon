"""Build every content piece: fresh scene -> .blend -> FBX + GLB -> previews -> manifest.

    blender -b --factory-startup -P art/blender/build_all.py
    blender -b --factory-startup -P art/blender/build_all.py -- --only content4
    blender -b --factory-startup -P art/blender/build_all.py -- --only content4:v2,content1:v1

Pieces that have no script yet are reported as SKIP, so this file is already the whole list.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import time
import traceback

import bpy

BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
ART = os.path.abspath(os.path.join(BLENDER_DIR, ".."))
for _p in (BLENDER_DIR, os.path.join(BLENDER_DIR, "pieces")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dc_kit as K  # noqa: E402

# every build in spec v1 section 3 — 13 of them
REGISTRY = [
    ("default", ("v1",)),
    ("content1", ("v1", "v2")),
    ("content2", ("v1", "v2")),
    ("content3", ("v1", "v2")),
    ("content4", ("v1", "v2")),
    ("rival1", ("v1",)),
    ("rival2", ("v1",)),
    ("rival3", ("v1",)),
    ("rivalsmall", ("v1",)),
]


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser(prog="build_all")
    ap.add_argument("--only", default="", help="comma list of ids, optionally id:version")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--no-bevel", action="store_true")
    ap.add_argument("--samples", type=int, default=64)
    return ap.parse_args(argv)


def wanted(args):
    if not args.only:
        return [(pid, v) for pid, vs in REGISTRY for v in vs]
    out = []
    picks = [s.strip() for s in args.only.split(",") if s.strip()]
    known = dict(REGISTRY)
    for p in picks:
        pid, _, ver = p.partition(":")
        if pid not in known:
            raise SystemExit("unknown piece id: %s" % pid)
        out.extend([(pid, v) for v in (ver,) if ver] or [(pid, v) for v in known[pid]])
    return out


def build_one(pid, version, args):
    t0 = time.time()
    K.reset_scene()

    mod = importlib.import_module(pid)
    importlib.reload(mod)

    piece = mod.build(version)
    piece.bevel = not args.no_bevel
    meta = piece.finish()

    blend_dir = os.path.join(ART, "blend")
    os.makedirs(blend_dir, exist_ok=True)
    blend = os.path.join(blend_dir, "%s_%s.blend" % (pid, version))
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)

    out_dir = os.path.join(ART, "export", "%s_%s" % (pid, version))
    fbx, glb = K.export_piece(meta, piece.mesh_objects(), piece.socket_objects(), out_dir)

    previews = {}
    render_info = dict(engine=None, view_transform=None, samples=args.samples)
    if not args.no_render:
        K.preview_world()
        K.preview_dress(piece, screen_image=os.path.join(ART, "samples", "sample_screen.png"))
        previews = K.render_previews(piece, meta, os.path.join(ART, "previews"),
                                     samples=args.samples)
        render_info = dict(engine=bpy.context.scene.render.engine,
                           view_transform=K.view_transform_used(),
                           samples=args.samples)

    elapsed = time.time() - t0
    manifest = K.write_manifest(
        meta, out_dir,
        piece_script=os.path.join(BLENDER_DIR, "pieces", pid + ".py"),
        exports=dict(fbx=fbx, glb=glb),
        previews=previews,
        build_seconds=elapsed,
        render_info=render_info,
    )
    b = meta["bounds"]["size"]
    print("BUILT  %-12s %-3s  %5.2f x %5.2f x %5.2f m  %6d tris  %2d mats  %5.1fs  -> %s"
          % (pid, version, b[0], b[1], b[2], meta["triangles"], meta["material_slot_count"],
             elapsed, os.path.relpath(manifest, ART).replace("\\", "/")))
    return meta


def main():
    args = parse_args()
    todo = wanted(args)
    ok, skipped, failed = [], [], []
    for pid, version in todo:
        script = os.path.join(BLENDER_DIR, "pieces", pid + ".py")
        if not os.path.exists(script):
            print("SKIP   %-12s %-3s  (no piece script yet)" % (pid, version))
            skipped.append((pid, version))
            continue
        mod = importlib.import_module(pid)
        done = getattr(mod, "IMPLEMENTED", None)
        if done is not None and version not in done:
            print("SKIP   %-12s %-3s  (version not written yet)" % (pid, version))
            skipped.append((pid, version))
            continue
        try:
            build_one(pid, version, args)
            ok.append((pid, version))
        except Exception:
            traceback.print_exc()
            print("FAIL   %-12s %-3s" % (pid, version))
            failed.append((pid, version))

    print("\nbuilt %d, skipped %d, failed %d" % (len(ok), len(skipped), len(failed)))
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
