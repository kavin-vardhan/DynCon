"""Check every built environment piece against the kit's own rules. Plain Python, no Blender.

    python art/tools/validate_env.py            # every manifest under art/export_env
    python art/tools/validate_env.py bench tree_tall

The content validator (`validate_assets.py`) checks the slot contract: class limits, sockets,
a door, a brand. None of that applies to the environment, which has no sockets and must never
be able to wear a brand. What does carry over is the part that matters most - **the units** -
plus budgets, the material slot list and the anchor convention the map builder relies on.

Exits non-zero if anything fails, so `art/build.ps1` can gate on it.
"""

from __future__ import annotations

import json
import os
import sys

# the kit, restated here so the validator does not depend on Blender
ENV_MATERIAL_SLOTS = {
    "M_Ground", "M_Paving", "M_PavingAlt", "M_Kerb", "M_Wall", "M_WallAlt", "M_Roof",
    "M_Trim", "M_Glass", "M_Metal", "M_Timber", "M_Foliage", "M_Trunk", "M_Water",
    "M_Emissive",
}
# the three the content uses for its runtime identity. An environment piece carrying one of
# these could be dressed in a brand colour, which is exactly what the environment must not do.
FORBIDDEN_SLOTS = {"M_BrandAccent", "M_Sign", "M_Screen"}
MAX_MATERIAL_SLOTS = 8
CATEGORY_BUDGET = {"ground": 1500, "street": 3000, "planting": 4000,
                   "building": 14000, "water": 500}
COLLISION_KINDS = {"blocking", "decoration"}
SCHEMA_VERSION = 1
FBX_SCALE = 100.0
EPS = 1e-4

# Nothing in the kit is allowed to be bigger than this: a background piece that out-measures
# the tall slot's 20 m would compete with the content instead of framing it.
MAX_SIZE = (20.0, 20.0, 22.0)


def load(root):
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name, "manifest.json")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                out.append((p, json.load(fh)))
    return out


def check(path, m):
    fails = []
    warns = []

    def fail(msg):
        fails.append(msg)

    if m.get("schema_version") != SCHEMA_VERSION:
        fail("schema_version is %r, expected %d" % (m.get("schema_version"), SCHEMA_VERSION))
    if m.get("kind") != "environment":
        fail("kind is %r, expected 'environment'" % m.get("kind"))

    cat = m.get("category")
    if cat not in CATEGORY_BUDGET:
        fail("unknown category %r" % cat)
    if m.get("collision") not in COLLISION_KINDS:
        fail("collision is %r, expected one of %s" % (m.get("collision"), sorted(COLLISION_KINDS)))

    # --- units: the one rule shared with the content ------------------------------------
    u = m.get("units") or {}
    for key, want in (("authoring", "m"), ("fbx", "cm"), ("glb", "m"), ("engine", "cm")):
        if u.get(key) != want:
            fail("units.%s is %r, expected %r" % (key, u.get(key), want))
    if abs(float(u.get("fbx_scale", 0)) - FBX_SCALE) > EPS:
        fail("units.fbx_scale is %r, expected %.1f" % (u.get("fbx_scale"), FBX_SCALE))
    if abs(float(u.get("engine_unit_scale", 0)) - 1.0) > EPS:
        fail("units.engine_unit_scale is %r, expected 1.0" % u.get("engine_unit_scale"))
    for key in ("min", "max", "size"):
        want_cm = [round(c * FBX_SCALE, 2) for c in m["bounds"][key]]
        got_cm = (m.get("bounds_cm") or {}).get(key)
        if got_cm is None or any(abs(got_cm[i] - want_cm[i]) > 0.01 for i in range(3)):
            fail("bounds_cm.%s is %s, metre bounds say %s" % (key, got_cm, want_cm))

    # --- the anchor convention the map builder relies on ---------------------------------
    lo = m["bounds"]["min"]
    hi = m["bounds"]["max"]
    size = m["bounds"]["size"]
    if lo[2] < -EPS:
        fail("geometry below the anchor: min z = %.3f m (the origin is the ground contact)" % lo[2])
    if abs(lo[2]) > 0.02:
        warns.append("sits %.3f m above its own anchor" % lo[2])
    # Centred in plan where it meets the ground, so a placement is a location and a yaw.
    # Checked on ground_bounds, not the whole box: a lamp post's arm reaches a metre out at
    # four metres up and that is not a badly anchored piece.
    gb = m.get("ground_bounds")
    if not gb:
        fail("no ground_bounds recorded")
    else:
        glo, ghi, gsize = gb["min"], gb["max"], gb["size"]
        for i, axis in ((0, "X"), (1, "Y")):
            off = abs(glo[i] + ghi[i]) / 2.0
            if off > max(0.12, gsize[i] * 0.10):
                fail("not centred in %s where it meets the ground: %.3f .. %.3f m"
                     % (axis, glo[i], ghi[i]))
    for i, axis in ((0, "X"), (1, "Y"), (2, "Z")):
        if size[i] > MAX_SIZE[i] + EPS:
            fail("%s size %.2f m is over the kit maximum %.2f m" % (axis, size[i], MAX_SIZE[i]))

    fp = m.get("footprint")
    if not fp or len(fp) != 2:
        fail("no footprint recorded")
    else:
        for i, axis in ((0, "X"), (1, "Y")):
            if size[i] > fp[i] + 0.75:
                fail("declared footprint %s (%.2f m) is well under the real %s size %.2f m"
                     % (axis, fp[i], axis, size[i]))

    # --- materials ------------------------------------------------------------------------
    used = [mm["slot"] for mm in m.get("materials", [])]
    for s in used:
        if s in FORBIDDEN_SLOTS:
            fail("uses %s - the environment must never be able to wear a brand" % s)
        elif s not in ENV_MATERIAL_SLOTS:
            fail("material slot %s is not one of the environment kit's names" % s)
    if len(used) > MAX_MATERIAL_SLOTS:
        fail("%d material slots, budget is %d" % (len(used), MAX_MATERIAL_SLOTS))
    if m.get("material_slot_count") != len(used):
        fail("material_slot_count %r disagrees with the materials table (%d)"
             % (m.get("material_slot_count"), len(used)))
    # material_slots is the mesh's own slot ORDER - what Unreal's importer sees and what the
    # map builder indexes when it swaps a palette in - while the materials table is written in
    # the kit's canonical slot order. Same set, deliberately different order.
    if set(m.get("material_slots", [])) != set(used):
        fail("material_slots %s is not the same set as the materials table %s"
             % (m.get("material_slots"), used))
    if len(m.get("material_slots", [])) != len(set(m.get("material_slots", []))):
        fail("duplicate entries in material_slots %s" % m.get("material_slots"))

    # --- budget ---------------------------------------------------------------------------
    tris = m.get("triangles", 0)
    budget = CATEGORY_BUDGET.get(cat, 0)
    if tris > budget:
        fail("%d triangles, the %s budget is %d" % (tris, cat, budget))
    if tris == 0:
        fail("no geometry at all")

    # --- both palettes, and the files on disk ------------------------------------------------
    pals = list(m.get("palettes", []))
    if sorted(pals) != ["cool", "warm"]:
        fail("palettes %s, expected both 'cool' and 'warm'" % pals)
    art = os.path.abspath(os.path.join(os.path.dirname(path), "..", ".."))
    for key, rel in list(m.get("exports", {}).items()) + list(m.get("previews", {}).items()):
        if not os.path.exists(os.path.join(art, rel)):
            fail("%s missing on disk: %s" % (key, rel))
    for key in ("fbx", "glb"):
        if key not in m.get("exports", {}):
            fail("no %s export" % key)
    for key in pals:
        if key not in m.get("previews", {}):
            warns.append("no %s preview" % key)

    return fails, warns


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    art = os.path.abspath(os.path.join(here, ".."))
    manifests = load(os.path.join(art, "export_env"))
    picks = [a for a in sys.argv[1:] if not a.startswith("-")]
    if picks:
        manifests = [(p, m) for p, m in manifests if m["id"] in picks]

    if not manifests:
        print("no manifests found under art/export_env")
        return 1

    print("%-14s %-9s %-11s %-22s %8s %5s %s"
          % ("id", "category", "collision", "size x*y*z (m)", "tris", "mats", "result"))
    print("-" * 96)
    bad = 0
    detail = []
    for path, m in manifests:
        fails, warns = check(path, m)
        s = m["bounds"]["size"]
        result = "PASS" if not fails else "FAIL (%d)" % len(fails)
        if warns and not fails:
            result = "PASS (%d warn)" % len(warns)
        print("%-14s %-9s %-11s %-22s %8d %5d %s"
              % (m.get("id"), m.get("category"), m.get("collision"),
                 "%.2f x %.2f x %.2f" % (s[0], s[1], s[2]),
                 m.get("triangles", 0), m.get("material_slot_count", 0), result))
        for f in fails:
            detail.append("  FAIL %s: %s" % (m.get("id"), f))
        for w in warns:
            detail.append("  warn %s: %s" % (m.get("id"), w))
        bad += len(fails)

    # the palette table the map builder reads
    pal = os.path.join(art, "export_env", "palettes.json")
    if not os.path.exists(pal):
        detail.append("  FAIL palettes.json is missing - the map builder reads it for colours")
        bad += 1
    else:
        with open(pal, "r", encoding="utf-8") as fh:
            table = json.load(fh)
        for name in ("warm", "cool"):
            slots = (table.get("palettes", {}).get(name) or {}).get("slots") or {}
            missing = sorted(ENV_MATERIAL_SLOTS - set(slots))
            if missing:
                detail.append("  FAIL palettes.json %s is missing %s" % (name, missing))
                bad += 1

    if detail:
        print()
        for line in detail:
            print(line)

    total = sum(m.get("triangles", 0) for _, m in manifests)
    print()
    print("%d environment piece(s) checked, %d triangle(s) in the whole kit, %d failure(s)"
          % (len(manifests), total, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
