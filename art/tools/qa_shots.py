"""Close-up QA renders — the shots the three shipped previews cannot show.

    blender -b --factory-startup -noaudio -P art/tools/qa_shots.py
    blender -b --factory-startup -noaudio -P art/tools/qa_shots.py -- --only content2,content3

Writes art/_qa/<id>_<v>_<shot>.png (git-ignored). Every camera is derived from the piece's own
sockets and bounding box, so a new piece gets the same QA set for free. Look at these before
reporting a piece done: switch wall, door in and out, front elevation, sign, roof edge,
entrance and a wide interior.
"""

from __future__ import annotations

import os
import sys

import bpy
from mathutils import Vector

BLENDER_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "..", "blender"))
ART = os.path.abspath(os.path.join(BLENDER_DIR, ".."))
for _p in (BLENDER_DIR, os.path.join(BLENDER_DIR, "pieces")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import importlib          # noqa: E402
import dc_kit as K        # noqa: E402

OUT = os.path.join(ART, "_qa")
RES = (1280, 720)


def parse():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    only = ""
    samples = 32
    if "--only" in argv:
        only = argv[argv.index("--only") + 1]
    if "--samples" in argv:
        samples = int(argv[argv.index("--samples") + 1])
    return only, samples


def _cam(name, lens, ortho=None):
    cd = bpy.data.cameras.new(name)
    if ortho:
        cd.type = "ORTHO"
        cd.ortho_scale = ortho
    else:
        cd.lens = lens
    ob = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _look(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def shots_for(piece, meta):
    """(name, camera location, target, lens, ortho_scale or None)."""
    lo = Vector(meta["bounds"]["min"])
    hi = Vector(meta["bounds"]["max"])
    mid = (lo + hi) / 2
    out = []

    def sock(name):
        for s in meta["sockets"]:
            if s["name"] == name:
                return Vector(s["location"])
        return None

    # straight-on front elevation, orthographic
    span = max(hi.x - lo.x, hi.z - lo.z) * 1.12
    out.append(("front_elev", Vector((0.0, lo.y - 24.0, (lo.z + hi.z) / 2)),
                Vector((0.0, 0.0, (lo.z + hi.z) / 2)), 50.0, span))

    d = sock("SOCKET_Door")
    if d:
        out.append(("door_out", Vector((d.x + 0.9, d.y - 4.6, 1.75)),
                    Vector((d.x + 0.85, d.y, 1.45)), 35.0, None))
        out.append(("door_in", Vector((d.x + 0.85, d.y + 4.0, 1.78)),
                    Vector((d.x + 0.85, d.y, 1.40)), 28.0, None))
        out.append(("entrance", Vector((d.x + 4.6, d.y - 5.4, 2.6)),
                    Vector((d.x + 0.85, d.y + 0.4, 1.3)), 35.0, None))

    s = sock("SOCKET_Sign")
    if s:
        out.append(("sign", Vector((s.x + 0.4, s.y - 5.2, s.z + 0.5)), s, 50.0, None))

    a = sock("SOCKET_SwitchA")
    b = sock("SOCKET_SwitchB")
    if a is not None and b is not None:
        c = (a + b) / 2
        out.append(("switches", Vector((c.x + 0.62, c.y + 1.15, c.z + 0.34)), c, 42.0, None))

    v = sock("VOLUME_Interior")
    iv = meta.get("interior_volume")
    if iv:
        ilo, ihi = Vector(iv["min"]), Vector(iv["max"])
        out.append(("int_wide", Vector((ilo.x + 0.55, ilo.y + 0.55, ilo.z + 1.80)),
                    Vector((ihi.x - 0.4, ihi.y - 0.4, ilo.z + 1.10)), 19.0, None))
        out.append(("int_back", Vector((ihi.x - 0.55, ihi.y - 0.75, ilo.z + 1.80)),
                    Vector((ilo.x + 0.4, ilo.y + 0.4, ilo.z + 1.20)), 19.0, None))

    # roof edge / eave, and a three-quarter rear
    out.append(("eave", Vector((hi.x + 2.4, lo.y - 2.2, hi.z - 0.9)),
                Vector((hi.x - 1.4, lo.y + 0.8, hi.z - 0.25)), 42.0, None))
    r = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
    out.append(("rear", Vector((lo.x - r * 0.75, hi.y + r * 0.95, mid.z + r * 0.55)),
                Vector((0.0, 0.0, mid.z)), 35.0, None))
    return out


def run(pid, version, samples):
    K.reset_scene()
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = RES
    mod = importlib.import_module(pid)
    importlib.reload(mod)
    piece = mod.build(version)
    meta = piece.finish()
    brand, emblem = K.preview_identity(pid)
    K.preview_world()
    K.preview_dress(piece, brand=brand, emblem=emblem,
                    screen_image=os.path.join(ART, "samples", "sample_screen.png"),
                    lights_b_on=True)
    try:
        sc.eevee.taa_render_samples = samples
    except Exception:
        pass

    os.makedirs(OUT, exist_ok=True)
    n = 0
    for (name, loc, tgt, lens, ortho) in shots_for(piece, meta):
        cam = _cam("QA_" + name, lens, ortho)
        cam.location = loc
        _look(cam, tgt)
        sc.camera = cam
        sc.render.filepath = os.path.join(OUT, "%s_%s_%s.png" % (pid, version, name))
        bpy.ops.render.render(write_still=True)
        n += 1
    print("QA  %-12s %-3s  %d shots" % (pid, version, n))


def main():
    only, samples = parse()
    sys.path.insert(0, os.path.join(BLENDER_DIR))
    import build_all                                   # noqa: E402  (shares the registry)
    todo = []
    picks = [s.strip() for s in only.split(",") if s.strip()]
    for pid, versions in build_all.REGISTRY:
        for v in versions:
            if picks and not any(p == pid or p == "%s:%s" % (pid, v) for p in picks):
                continue
            script = os.path.join(BLENDER_DIR, "pieces", pid + ".py")
            if not os.path.exists(script):
                continue
            mod = importlib.import_module(pid)
            done = getattr(mod, "IMPLEMENTED", None)
            if done is not None and v not in done:
                continue
            todo.append((pid, v))
    for pid, v in todo:
        run(pid, v, samples)
    print("QA shots -> %s" % OUT)


if __name__ == "__main__":
    main()
