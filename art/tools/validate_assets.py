"""Check every built piece against the content asset spec. Plain Python over the manifests.

    python art/tools/validate_assets.py            # all manifests under art/export
    python art/tools/validate_assets.py content4   # only these ids

Prints a table and exits non-zero if anything fails, so build.ps1 can gate on it.
"""

from __future__ import annotations

import json
import os
import sys

# --- the spec, restated here so the validator does not depend on Blender ----------------
CLASS_LIMITS = {"S": (7.0, 7.0, 5.0), "L": (14.0, 14.0, 9.0), "T": (14.0, 14.0, 20.0)}
SLOT_CLASS = {"A1": "L", "A2": "T", "A3": "S", "B1": "L", "B2": "S"}
ALL_SLOTS = ("A1", "A2", "A3", "B1", "B2")

MATERIAL_SLOTS = {
    "M_Wall", "M_WallInterior", "M_Floor", "M_Roof", "M_Trim", "M_Glass", "M_Metal",
    "M_Door", "M_Switch", "M_LightEmissive", "M_BrandAccent", "M_Sign", "M_Screen",
}
MAX_MATERIAL_SLOTS = 13
TRI_BUDGET = 60000
DOOR_MIN_W, DOOR_MIN_H = 1.6, 2.6
INTERIOR_MIN_H = 3.5
FLOOR_TOP_MAX = 0.15
SCHEMA_VERSION = 1
FBX_SCALE = 100.0           # metres -> centimetres; dc_kit.FBX_UNIT_SCALE, restated here
EPS = 1e-4

WALKIN_OBJECTS = ("Shell", "Door", "Switch", "Screen", "Sign")
WALKIN_SOCKETS = ("SOCKET_Door", "SOCKET_SwitchA", "SOCKET_SwitchB", "SOCKET_Screen",
                  "SOCKET_Sign", "SOCKET_Waypoint", "SOCKET_Inside", "SOCKET_ThumbCam",
                  "VOLUME_Interior")
PLACEHOLDER_SOCKETS = ("SOCKET_Waypoint", "SOCKET_ThumbCam", "VOLUME_Interior")
PLACEHOLDER_IDS = ("default",)


def load(export_root):
    out = []
    if not os.path.isdir(export_root):
        return out
    for name in sorted(os.listdir(export_root)):
        p = os.path.join(export_root, name, "manifest.json")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                out.append((p, json.load(fh)))
    return out


def check(path, m):
    fails = []
    warns = []

    def fail(msg):
        fails.append(msg)

    pid = m.get("id", "?")
    cls = m.get("size_class")
    placeholder = pid in PLACEHOLDER_IDS

    if m.get("schema_version") != SCHEMA_VERSION:
        fail("schema_version is %r, expected %d" % (m.get("schema_version"), SCHEMA_VERSION))
    if m.get("front_axis") != "-Y":
        fail("front_axis is %r, expected '-Y'" % m.get("front_axis"))

    # --- units -------------------------------------------------------------------------
    # Everything the spec talks about is in metres; the FBX ships centimetres so a piece
    # lands at true size in the engine with nothing scaling it at spawn.
    u = m.get("units") or {}
    for key, want in (("authoring", "m"), ("fbx", "cm"), ("glb", "m"), ("engine", "cm")):
        if u.get(key) != want:
            fail("units.%s is %r, expected %r" % (key, u.get(key), want))
    if abs(float(u.get("fbx_scale", 0)) - FBX_SCALE) > EPS:
        fail("units.fbx_scale is %r, expected %.1f" % (u.get("fbx_scale"), FBX_SCALE))
    if abs(float(u.get("engine_unit_scale", 0)) - 1.0) > EPS:
        fail("units.engine_unit_scale is %r, expected 1.0 (no runtime scaling)"
             % u.get("engine_unit_scale"))
    for key in ("min", "max", "size"):
        want_cm = [round(c * FBX_SCALE, 2) for c in m["bounds"][key]]
        got_cm = (m.get("bounds_cm") or {}).get(key)
        if got_cm is None or any(abs(got_cm[i] - want_cm[i]) > 0.01 for i in range(3)):
            fail("bounds_cm.%s is %s, metre bounds say %s" % (key, got_cm, want_cm))
    for s in m.get("sockets", []):
        want_cm = [round(c * FBX_SCALE, 2) for c in s["location"]]
        got_cm = s.get("location_cm")
        if got_cm is None or any(abs(got_cm[i] - want_cm[i]) > 0.01 for i in range(3)):
            fail("socket %s location_cm is %s, metres say %s" % (s["name"], got_cm, want_cm))
    if cls not in CLASS_LIMITS:
        fail("unknown size_class %r" % cls)
        return fails, warns

    # --- bounds inside the class -------------------------------------------------------
    # the class footprint is centred on the origin, so check the half-extents, not the size
    lx, ly, lz = CLASS_LIMITS[cls]
    lo = m["bounds"]["min"]
    hi = m["bounds"]["max"]
    size = m["bounds"]["size"]
    ex, ey = max(abs(lo[0]), abs(hi[0])), max(abs(lo[1]), abs(hi[1]))
    if ex > lx / 2 + EPS:
        fail("reaches %.3f m from the anchor in X; class %s allows %.2f m" % (ex, cls, lx / 2))
    if ey > ly / 2 + EPS:
        fail("reaches %.3f m from the anchor in Y; class %s allows %.2f m" % (ey, cls, ly / 2))
    if hi[2] > lz + EPS:
        fail("height %.3f m exceeds class %s limit %.1f m" % (hi[2], cls, lz))
    if lo[2] < -EPS:
        fail("geometry below ground: min z = %.3f m" % lo[2])

    # --- fits_slots agrees with the class table ----------------------------------------
    expect = []
    for slot in ALL_SLOTS:
        sx, sy, sz = CLASS_LIMITS[SLOT_CLASS[slot]]
        if ex <= sx / 2 + EPS and ey <= sy / 2 + EPS and hi[2] <= sz + EPS and lo[2] >= -EPS:
            expect.append(slot)
    if list(m.get("fits_slots", [])) != expect:
        fail("fits_slots %s, expected %s" % (m.get("fits_slots"), expect))
    if not expect:
        fail("fits no slot at all")

    # --- objects -----------------------------------------------------------------------
    roles = [o["role"] for o in m.get("objects", [])]
    need = ("Shell",) if placeholder else WALKIN_OBJECTS
    for r in need:
        if r not in roles:
            fail("missing object %s" % r)
    if placeholder:
        for r in ("Door", "Switch", "Screen", "Sign"):
            if r in roles:
                fail("placeholder must not have a %s" % r)

    # --- sockets -----------------------------------------------------------------------
    socknames = [s["name"] for s in m.get("sockets", [])]
    need_s = PLACEHOLDER_SOCKETS if placeholder else WALKIN_SOCKETS
    for s in need_s:
        if s not in socknames:
            fail("missing socket %s" % s)
    if not placeholder:
        na = len([s for s in socknames if s.startswith("SOCKET_LightA_")])
        nb = len([s for s in socknames if s.startswith("SOCKET_LightB_")])
        if na < 1:
            fail("no SOCKET_LightA_n")
        if nb < 1:
            fail("no SOCKET_LightB_n")
    else:
        for s in socknames:
            if s not in PLACEHOLDER_SOCKETS:
                fail("placeholder has unexpected socket %s" % s)
    if len(set(socknames)) != len(socknames):
        fail("duplicate socket names")

    # --- materials ---------------------------------------------------------------------
    used = [mm["slot"] for mm in m.get("materials", [])]
    for s in used:
        if s not in MATERIAL_SLOTS:
            fail("material slot %s is not one of the allowed names" % s)
    if len(used) > MAX_MATERIAL_SLOTS:
        fail("%d material slots, budget is %d" % (len(used), MAX_MATERIAL_SLOTS))
    if m.get("material_slot_count") != len(used):
        fail("material_slot_count %r disagrees with the materials table (%d)"
             % (m.get("material_slot_count"), len(used)))
    if placeholder:
        for s in ("M_BrandAccent", "M_Sign", "M_Screen"):
            if s in used:
                fail("placeholder must not use %s" % s)
    else:
        for s in ("M_BrandAccent", "M_Sign", "M_Screen"):
            if s not in used:
                fail("missing %s — brand identity must be a runtime input on every piece" % s)

    # --- budgets and clearances ---------------------------------------------------------
    tris = m.get("triangles", 0)
    if tris > TRI_BUDGET:
        fail("%d triangles, budget is %d" % (tris, TRI_BUDGET))

    cl = m.get("clearances", {})
    ft = cl.get("floor_top_z")
    if ft is None:
        fail("no floor_top_z recorded")
    elif ft > FLOOR_TOP_MAX + EPS:
        fail("floor top %.3f m is above the %.2f m limit" % (ft, FLOOR_TOP_MAX))

    ih = cl.get("interior_clear_height")
    if ih is None:
        fail("no interior_clear_height recorded")
    elif ih < INTERIOR_MIN_H - EPS:
        fail("interior clear height %.3f m is under %.1f m" % (ih, INTERIOR_MIN_H))

    if not placeholder:
        d = m.get("door") or {}
        if d.get("clear_width", 0) < DOOR_MIN_W - EPS:
            fail("door clear width %.3f m is under %.1f m" % (d.get("clear_width", 0), DOOR_MIN_W))
        if d.get("clear_height", 0) < DOOR_MIN_H - EPS:
            fail("door clear height %.3f m is under %.1f m" % (d.get("clear_height", 0), DOOR_MIN_H))
        if d.get("open_sign") not in (1, -1):
            fail("door open_sign must be +1 or -1")

    # --- exports and previews exist ------------------------------------------------------
    art = os.path.abspath(os.path.join(os.path.dirname(path), "..", ".."))
    for key, rel in list(m.get("exports", {}).items()) + list(m.get("previews", {}).items()):
        if not os.path.exists(os.path.join(art, rel)):
            fail("%s missing on disk: %s" % (key, rel))
    for key in ("ext", "int", "top"):
        if key not in m.get("previews", {}):
            warns.append("no %s preview" % key)

    return fails, warns


def roundtrip(path):
    """Result of the last fbx_roundtrip.py run for this piece, if there is one."""
    p = os.path.join(os.path.dirname(path), "roundtrip.json")
    if not os.path.exists(p):
        return None, []
    with open(p, "r", encoding="utf-8") as fh:
        r = json.load(fh)
    return bool(r.get("ok")), list(r.get("failures", []))


def cross_version(manifests):
    """v1 and v2 of the same id must share the exact socket set and interactable set."""
    fails = []
    by_id = {}
    for _, m in manifests:
        by_id.setdefault(m["id"], {})[m["version"]] = m
    for pid, vs in sorted(by_id.items()):
        if len(vs) < 2:
            continue
        ref_v = sorted(vs)[0]
        ref = vs[ref_v]
        ref_sockets = set(s["name"] for s in ref["sockets"])
        ref_act = {k: v for k, v in ref["interactables"].items()}
        for v, m in sorted(vs.items()):
            if v == ref_v:
                continue
            got = set(s["name"] for s in m["sockets"])
            if got != ref_sockets:
                miss = sorted(ref_sockets - got)
                extra = sorted(got - ref_sockets)
                fails.append("%s %s socket set differs from %s (missing %s, extra %s)"
                             % (pid, v, ref_v, miss, extra))
            if m["interactables"] != ref_act:
                fails.append("%s %s interactable set differs from %s: %s vs %s"
                             % (pid, v, ref_v, m["interactables"], ref_act))
    return fails


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    art = os.path.abspath(os.path.join(here, ".."))
    manifests = load(os.path.join(art, "export"))
    picks = [a for a in sys.argv[1:] if not a.startswith("-")]
    if picks:
        manifests = [(p, m) for p, m in manifests if m["id"] in picks]

    if not manifests:
        print("no manifests found under art/export")
        return 1

    print("%-11s %-3s %-2s %-22s %8s %5s %-14s %-9s %s"
          % ("id", "ver", "cl", "bounds x*y*z (m)", "tris", "mats", "fits", "roundtrip", "result"))
    print("-" * 108)
    bad = 0
    detail = []
    for path, m in manifests:
        fails, warns = check(path, m)
        rt_ok, rt_fails = roundtrip(path)
        rt = "-" if rt_ok is None else ("PASS" if rt_ok else "FAIL")
        if rt_ok is False:
            bad += len(rt_fails)
            for f in rt_fails:
                detail.append("  FAIL %s %s roundtrip: %s" % (m["id"], m["version"], f))
        elif rt_ok is None:
            warns.append("FBX round-trip not run yet")
        s = m["bounds"]["size"]
        result = "PASS" if not fails else "FAIL (%d)" % len(fails)
        if warns and not fails:
            result = "PASS (%d warn)" % len(warns)
        print("%-11s %-3s %-2s %-22s %8d %5d %-14s %-9s %s"
              % (m["id"], m["version"], m["size_class"],
                 "%.2f x %.2f x %.2f" % (s[0], s[1], s[2]),
                 m["triangles"], m["material_slot_count"],
                 ",".join(m["fits_slots"]), rt, result))
        for f in fails:
            detail.append("  FAIL %s %s: %s" % (m["id"], m["version"], f))
        for w in warns:
            detail.append("  warn %s %s: %s" % (m["id"], m["version"], w))
        bad += len(fails)

    xfails = cross_version(manifests)
    for f in xfails:
        detail.append("  FAIL cross-version: %s" % f)
    bad += len(xfails)

    if detail:
        print()
        for line in detail:
            print(line)

    print()
    print("%d piece-version(s) checked, %d failure(s)" % (len(manifests), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
