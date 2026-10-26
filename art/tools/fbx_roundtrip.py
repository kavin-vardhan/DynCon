"""Re-import every exported FBX into an empty scene and check it against its manifest.

    blender -b --factory-startup -noaudio -P art/tools/fbx_roundtrip.py
    blender -b --factory-startup -noaudio -P art/tools/fbx_roundtrip.py -- --only content2

This is the step that catches unit, axis and scale surprises before UE ever sees the files:
a piece that is secretly 100x too big, or rotated, or that lost its sockets on the way out,
fails here rather than in the engine. Writes art/export/<id>_<v>/roundtrip.json and prints a
table; exits non-zero if anything fails.

The FBX is written in centimetres (dc_kit.FBX_UNIT_SCALE) while the manifest's primary numbers
are in metres, so everything here is compared in centimetres against the manifest's `_cm`
mirrors - which is exactly the comparison Unreal makes after import.
"""

from __future__ import annotations

import json
import os
import sys

import bpy
from mathutils import Vector

ART = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TOL_POS_CM = 2.0        # centimetres
EXPECT_FBX_UNITS = "cm"


def args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    only = []
    if "--only" in argv:
        only = [s.strip() for s in argv[argv.index("--only") + 1].split(",") if s.strip()]
    return only


def check_one(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as fh:
        m = json.load(fh)
    stem = "%s_%s" % (m["id"], m["version"])
    fbx = os.path.join(ART, m["exports"]["fbx"].replace("/", os.sep))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0
    bpy.ops.import_scene.fbx(filepath=fbx)

    meshes = {o.name: o for o in bpy.context.scene.objects if o.type == "MESH"}
    empties = {o.name: o for o in bpy.context.scene.objects if o.type == "EMPTY"}
    fails = []

    # --- object names -----------------------------------------------------------------
    want_meshes = [o["name"] for o in m["objects"]]
    for name in want_meshes:
        if name not in meshes:
            fails.append("missing mesh %s (imported: %s)" % (name, sorted(meshes)))
    extra = [n for n in meshes if n not in want_meshes]
    if extra:
        fails.append("unexpected mesh objects: %s" % extra)

    # --- units declared in the manifest -------------------------------------------------
    units = m.get("units") or {}
    if units.get("fbx") != EXPECT_FBX_UNITS:
        fails.append("manifest units.fbx is %r, expected %r" % (units.get("fbx"), EXPECT_FBX_UNITS))
    if abs(float(units.get("fbx_scale", 0)) - 100.0) > 1e-6:
        fails.append("manifest units.fbx_scale is %r, expected 100.0" % units.get("fbx_scale"))
    for key in ("min", "max", "size"):
        want = [round(c * 100.0, 2) for c in m["bounds"][key]]
        got = m.get("bounds_cm", {}).get(key)
        if got is None or any(abs(got[i] - want[i]) > 0.01 for i in range(3)):
            fails.append("bounds_cm.%s is %s, metres say %s" % (key, got, want))

    # --- sockets ----------------------------------------------------------------------
    want_sockets = {s["name"]: s for s in m["sockets"]}
    for name, s in want_sockets.items():
        if name not in empties:
            fails.append("missing socket %s" % name)
            continue
        got = empties[name].matrix_world.translation      # centimetres, from the FBX
        want = Vector(s["location_cm"])
        if (got - want).length > TOL_POS_CM:
            fails.append("socket %s at %s cm, manifest says %s cm"
                         % (name, [round(c, 2) for c in got], s["location_cm"]))
    extra_s = [n for n in empties if n not in want_sockets]
    if extra_s:
        fails.append("unexpected empties: %s" % extra_s)

    # --- material slot names ----------------------------------------------------------
    for o in m["objects"]:
        ob = meshes.get(o["name"])
        if ob is None:
            continue
        got = [ms.name.split(".")[0] for ms in ob.data.materials if ms]
        if got != o["materials"]:
            fails.append("%s material slots %s, manifest says %s" % (o["name"], got, o["materials"]))

    # --- bounds in centimetres ---------------------------------------------------------
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for ob in meshes.values():
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    mlo, mhi = m["bounds_cm"]["min"], m["bounds_cm"]["max"]
    for i, ax in enumerate("xyz"):
        if abs(lo[i] - mlo[i]) > TOL_POS_CM or abs(hi[i] - mhi[i]) > TOL_POS_CM:
            fails.append("bounds %s imported [%.2f, %.2f] cm, manifest [%.2f, %.2f] cm"
                         % (ax, lo[i], hi[i], mlo[i], mhi[i]))

    tris = 0
    for ob in meshes.values():
        tris += sum(max(0, len(p.vertices) - 2) for p in ob.data.polygons)
    if abs(tris - m["triangles"]) > 2:
        fails.append("%d triangles imported, manifest says %d" % (tris, m["triangles"]))

    report = dict(
        id=m["id"], version=m["version"], fbx=m["exports"]["fbx"],
        units="cm",
        meshes=sorted(meshes), sockets=sorted(empties),
        imported_bounds_cm=dict(min=[round(c, 2) for c in lo], max=[round(c, 2) for c in hi]),
        manifest_bounds_cm=dict(min=mlo, max=mhi),
        imported_triangles=tris, failures=fails, ok=not fails,
    )
    out = os.path.join(os.path.dirname(manifest_path), "roundtrip.json")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=1)
        fh.write("\n")
    return stem, report


def main():
    only = args()
    root = os.path.join(ART, "export")
    rows = []
    bad = 0
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name, "manifest.json")
        if not os.path.exists(p):
            continue
        if only and not any(name == o or name.startswith(o + "_") for o in only):
            continue
        stem, rep = check_one(p)
        rows.append((stem, rep))
        bad += len(rep["failures"])

    print("\nFBX ROUND-TRIP")
    print("%-14s %-7s %-7s %-9s %s" % ("piece", "meshes", "sockets", "tris", "result"))
    print("-" * 60)
    for stem, rep in rows:
        print("%-14s %-7d %-7d %-9d %s"
              % (stem, len(rep["meshes"]), len(rep["sockets"]), rep["imported_triangles"],
                 "PASS" if rep["ok"] else "FAIL (%d)" % len(rep["failures"])))
    for stem, rep in rows:
        for f in rep["failures"]:
            print("  FAIL %s: %s" % (stem, f))
    print("\n%d piece-version(s) re-imported, %d failure(s)" % (len(rows), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
