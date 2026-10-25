"""
dc_kit — shared Blender-side library for DynamicContents walk-in content.

Everything in `art/` is generated: no hand-modelled geometry, no downloaded models or textures.
This module holds the parts every piece shares, so a piece script is mostly composition:

    import dc_kit as K

    def build(version):
        P = K.Piece("content4", version, "S", palette={...})
        ... P.plinth(...) / P.wall_run(...) / P.roof_prism(...) / P.standard_interior(...) ...
        return P.finish()

Conventions (spec v1 §4)
  * metres, Z up, unit scale 1.0
  * origin = slot anchor = centre of the footprint at ground level (z = 0); nothing below z = 0
  * the front (main door side) faces -Y
  * geometry is authored from solid boxes and extruded profiles — construction, never booleans
  * every sub-object (Door / Switch / Screen / Sign) is authored around its own local origin and
    *placed* with an object transform that equals its socket, so the preview shows a whole building
    while each exported mesh still has the origin UE needs.

Run inside Blender only:  blender -b --factory-startup -P art/blender/build_all.py
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time

import bpy
from mathutils import Vector

# --------------------------------------------------------------------------------------
# constants — the slot contract (spec v1 §2) and the budgets (§4)
# --------------------------------------------------------------------------------------

CLASS_LIMITS = {
    "S": (7.0, 7.0, 5.0),
    "L": (14.0, 14.0, 9.0),
    "T": (14.0, 14.0, 20.0),
}
SLOT_CLASS = {"A1": "L", "A2": "T", "A3": "S", "B1": "L", "B2": "S"}
ALL_SLOTS = ("A1", "A2", "A3", "B1", "B2")

SCHEMA_VERSION = 1
FRONT_AXIS = "-Y"

WALL_MIN = 0.20          # metres, minimum wall thickness
DOOR_MIN_W = 1.6         # door clear opening
DOOR_MIN_H = 2.6
INTERIOR_MIN_H = 3.5     # interior clear height
FLOOR_TOP_MAX = 0.15     # floor top above ground
CAPSULE_R = 0.42         # player capsule radius
TRI_BUDGET = 60000
MAX_MATERIAL_SLOTS = 13

BEVEL_WIDTH = 0.03       # spec asks for 0.02 - 0.05 m bevels
BEVEL_ANGLE = math.radians(32.0)

# sign and screen sizes per class (spec fixes the sign; the screen size is a kit call)
SIGN_SIZE = {"S": (1.6, 0.8), "L": (3.0, 1.5), "T": (3.0, 1.5)}
SCREEN_SIZE = {"S": (2.40, 1.35), "L": (4.00, 2.25), "T": (4.00, 2.25)}

# how far in front of the piece SOCKET_ThumbCam sits, per class
THUMBCAM_DIST = {"S": 11.0, "L": 15.0, "T": 20.0}
THUMBCAM_EYE = 1.70

MATERIAL_SLOTS = (
    "M_Wall",
    "M_WallInterior",
    "M_Floor",
    "M_Roof",
    "M_Trim",
    "M_Glass",
    "M_Metal",
    "M_Door",
    "M_Switch",
    "M_LightEmissive",
    "M_BrandAccent",
    "M_Sign",
    "M_Screen",
)

# Neutral defaults. A piece's `palette` overrides any of these so pieces are told apart by
# shape and tone — never by theme. M_BrandAccent / M_Sign / M_Screen stay deliberately
# neutral here: the brand colour, emblem and screen image are runtime inputs.
DEFAULT_MATERIALS = {
    "M_Wall":          dict(color="#D8D3CA", roughness=0.55, metallic=0.0),
    "M_WallInterior":  dict(color="#EFEBE4", roughness=0.72, metallic=0.0),
    "M_Floor":         dict(color="#9C968D", roughness=0.45, metallic=0.0),
    "M_Roof":          dict(color="#6F6B66", roughness=0.62, metallic=0.0),
    "M_Trim":          dict(color="#4A4845", roughness=0.42, metallic=0.0),
    "M_Glass":         dict(color="#CBDDE5", roughness=0.07, metallic=0.0, alpha=0.20),
    "M_Metal":         dict(color="#B6BABE", roughness=0.28, metallic=0.90),
    "M_Door":          dict(color="#8B8478", roughness=0.45, metallic=0.0),
    "M_Switch":        dict(color="#F3F1EE", roughness=0.34, metallic=0.0),
    "M_LightEmissive": dict(color="#FFF4DE", roughness=0.50, metallic=0.0, emissive=4.0),
    "M_BrandAccent":   dict(color="#AFAFAF", roughness=0.40, metallic=0.0),
    "M_Sign":          dict(color="#C7C7C7", roughness=0.46, metallic=0.0),
    "M_Screen":        dict(color="#191B1E", roughness=0.18, metallic=0.0),
}

STATE_SCHEMA = ["light_a_on", "light_b_on", "door_open", "screen_image_index"]

# sample brand identity used for previews only (never baked into an export)
PREVIEW_BRAND_COLOR = "#1F8FC6"
PREVIEW_EMBLEM = "hexagon"

_ART = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def art_path(*parts: str) -> str:
    return os.path.join(_ART, *parts)


# --------------------------------------------------------------------------------------
# colour
# --------------------------------------------------------------------------------------

def hex_to_linear(h: str):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    out = []
    for c in srgb:
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


# --------------------------------------------------------------------------------------
# geometry builder — plain vert/face lists, deterministic, outward normals checked
# --------------------------------------------------------------------------------------

def _face_normal(pts):
    a, b, c = pts[0], pts[1], pts[2]
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    e2 = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
    return (
        e1[1] * e2[2] - e1[2] * e2[1],
        e1[2] * e2[0] - e1[0] * e2[2],
        e1[0] * e2[1] - e1[1] * e2[0],
    )


def _oriented(pts, want):
    """Return pts, reversed if needed, so the face normal points the same way as `want`."""
    n = _face_normal(pts)
    if n[0] * want[0] + n[1] * want[1] + n[2] * want[2] < 0.0:
        return list(reversed(pts))
    return list(pts)


def _signed_area(poly2d):
    s = 0.0
    n = len(poly2d)
    for i in range(n):
        u0, v0 = poly2d[i]
        u1, v1 = poly2d[(i + 1) % n]
        s += u0 * v1 - u1 * v0
    return 0.5 * s


def _ccw(poly2d):
    return list(poly2d) if _signed_area(poly2d) > 0 else list(reversed(poly2d))


_AXIS_VEC = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _rot_from_normal(normal):
    """Z rotation that turns the authoring front (-Y) into `normal`."""
    n = Vector(normal).normalized()
    return (0.0, 0.0, math.atan2(n[0], -n[1]))


class MeshBuilder:
    """Accumulates polygons with a material name each, then bakes one Blender mesh."""

    def __init__(self):
        self.verts: list[tuple] = []
        self.faces: list[tuple] = []        # (indices, material name, uvs or None)
        self._vmap: dict[tuple, int] = {}
        self._group = 0

    # -- low level ----------------------------------------------------------------
    def _new_group(self):
        """Vertices are welded inside one primitive and never between primitives.

        Each box / extrusion therefore stays its own closed solid: the bevel modifier sees
        clean 90-degree edges and the junction between two abutting parts reads as a reveal,
        instead of the two being merged into a non-manifold lump the bevel can push around.
        """
        self._group += 1

    def _v(self, p):
        key = (self._group, round(p[0], 6), round(p[1], 6), round(p[2], 6))
        i = self._vmap.get(key)
        if i is None:
            i = len(self.verts)
            self._vmap[key] = i
            self.verts.append((key[1], key[2], key[3]))
        return i

    def poly(self, pts, mat, uvs=None):
        idx = tuple(self._v(p) for p in pts)
        if len(set(idx)) < 3:
            return
        self.faces.append((idx, mat, uvs))

    # -- primitives ---------------------------------------------------------------
    def box(self, lo, hi, mat, faces=None):
        """Axis-aligned solid box. `faces` overrides the material per side, e.g. {'+y': 'M_WallInterior'}."""
        x0, y0, z0 = min(lo[0], hi[0]), min(lo[1], hi[1]), min(lo[2], hi[2])
        x1, y1, z1 = max(lo[0], hi[0]), max(lo[1], hi[1]), max(lo[2], hi[2])
        if x1 - x0 < 1e-6 or y1 - y0 < 1e-6 or z1 - z0 < 1e-6:
            return
        faces = faces or {}
        self._new_group()
        sides = {
            "-x": [(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)],
            "+x": [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
            "-y": [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
            "+y": [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)],
            "-z": [(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)],
            "+z": [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
        }
        for key, pts in sides.items():
            self.poly(pts, faces.get(key, mat))

    def quad(self, pts, mat, uv01=True, normal_hint=None):
        """A single flat quad. uv01 gives it UVs exactly 0-1 (needed by Screen and Sign)."""
        self._new_group()
        if normal_hint:
            pts = _oriented(pts, normal_hint)
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)] if uv01 else None
        self.poly(pts, mat, uvs)

    def extrude(self, poly2d, plane, a, b, side_mat, cap_mat=None, cap_a_mat=None, cap_b_mat=None):
        """Extrude a 2-D profile into a closed solid.

        plane 'xz' -> profile is (x, z), extruded along Y from a to b
        plane 'xy' -> profile is (x, y), extruded along Z from a to b
        plane 'yz' -> profile is (y, z), extruded along X from a to b
        """
        self._new_group()
        cap_mat = cap_mat or side_mat
        cap_a_mat = cap_a_mat or cap_mat
        cap_b_mat = cap_b_mat or cap_mat
        poly = _ccw(poly2d)
        n = len(poly)

        if plane == "xz":
            mk = lambda uv, w: (uv[0], w, uv[1])
            axis = (0.0, 1.0, 0.0)
        elif plane == "xy":
            mk = lambda uv, w: (uv[0], uv[1], w)
            axis = (0.0, 0.0, 1.0)
        elif plane == "yz":
            mk = lambda uv, w: (w, uv[0], uv[1])
            axis = (1.0, 0.0, 0.0)
        else:
            raise ValueError(plane)

        neg = tuple(-c for c in axis)
        self.poly(_oriented([mk(p, a) for p in poly], neg), cap_a_mat)
        self.poly(_oriented([mk(p, b) for p in poly], axis), cap_b_mat)

        for i in range(n):
            p = poly[i]
            q = poly[(i + 1) % n]
            du, dv = q[0] - p[0], q[1] - p[1]
            if abs(du) < 1e-9 and abs(dv) < 1e-9:
                continue
            out2 = (dv, -du)   # outward normal of a CCW polygon edge
            want = mk((out2[0], out2[1]), 0.0)
            if plane == "xz":
                want = (out2[0], 0.0, out2[1])
            elif plane == "xy":
                want = (out2[0], out2[1], 0.0)
            else:
                want = (0.0, out2[0], out2[1])
            self.poly(_oriented([mk(p, a), mk(q, a), mk(q, b), mk(p, b)], want), side_mat)

    # -- round things -------------------------------------------------------------
    @staticmethod
    def circle2d(cx, cy, r, segs, start_deg=0.0):
        return [
            (cx + r * math.cos(math.radians(start_deg) + 2 * math.pi * i / segs),
             cy + r * math.sin(math.radians(start_deg) + 2 * math.pi * i / segs))
            for i in range(segs)
        ]

    def disc(self, center2d, r, plane, a, b, mat, segs=24, cap_mat=None):
        self.extrude(self.circle2d(center2d[0], center2d[1], r, segs), plane, a, b, mat, cap_mat)

    def annulus(self, center2d, r_in, r_out, plane, a, b, mat, segs=24, face_mat=None):
        """Ring solid: two cylindrical skins plus two flat ring faces."""
        self._new_group()
        face_mat = face_mat or mat
        inner = self.circle2d(center2d[0], center2d[1], r_in, segs)
        outer = self.circle2d(center2d[0], center2d[1], r_out, segs)
        if plane == "xz":
            mk = lambda uv, w: (uv[0], w, uv[1])
            axis = (0.0, 1.0, 0.0)
        elif plane == "xy":
            mk = lambda uv, w: (uv[0], uv[1], w)
            axis = (0.0, 0.0, 1.0)
        else:
            mk = lambda uv, w: (w, uv[0], uv[1])
            axis = (1.0, 0.0, 0.0)
        neg = tuple(-c for c in axis)
        for i in range(segs):
            j = (i + 1) % segs
            # ring faces
            self.poly(_oriented([mk(inner[i], a), mk(outer[i], a), mk(outer[j], a), mk(inner[j], a)], neg), face_mat)
            self.poly(_oriented([mk(inner[i], b), mk(outer[i], b), mk(outer[j], b), mk(inner[j], b)], axis), face_mat)
            # outer skin (normal away from centre), inner skin (normal toward centre)
            mid_o = ((outer[i][0] + outer[j][0]) * 0.5 - center2d[0], (outer[i][1] + outer[j][1]) * 0.5 - center2d[1])
            w_o = mk(mid_o, 0.0)
            w_o = (mid_o[0], 0.0, mid_o[1]) if plane == "xz" else ((mid_o[0], mid_o[1], 0.0) if plane == "xy" else (0.0, mid_o[0], mid_o[1]))
            self.poly(_oriented([mk(outer[i], a), mk(outer[j], a), mk(outer[j], b), mk(outer[i], b)], w_o), mat)
            w_i = tuple(-c for c in w_o)
            self.poly(_oriented([mk(inner[i], a), mk(inner[j], a), mk(inner[j], b), mk(inner[i], b)], w_i), mat)

    # -- bake ---------------------------------------------------------------------
    def material_names(self):
        seen = []
        for _, mat, _ in self.faces:
            if mat not in seen:
                seen.append(mat)
        return seen

    def to_object(self, name, materials: dict):
        mat_names = self.material_names()
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([list(v) for v in self.verts], [], [list(f[0]) for f in self.faces])
        mesh.update()

        for mn in mat_names:
            mesh.materials.append(materials[mn])
        index_of = {mn: i for i, mn in enumerate(mat_names)}

        uv = mesh.uv_layers.new(name="UVMap")
        for poly, (idx, mat, uvs) in zip(mesh.polygons, self.faces):
            poly.material_index = index_of[mat]
            poly.use_smooth = False
            if uvs is not None:
                for k, li in enumerate(poly.loop_indices):
                    uv.data[li].uv = uvs[k % len(uvs)]
            else:
                n = poly.normal
                ax = max(range(3), key=lambda i: abs(n[i]))
                pick = {0: (1, 2), 1: (0, 2), 2: (0, 1)}[ax]
                for li in poly.loop_indices:
                    co = mesh.vertices[mesh.loops[li].vertex_index].co
                    uv.data[li].uv = (co[pick[0]], co[pick[1]])

        ob = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(ob)
        return ob


# --------------------------------------------------------------------------------------
# scene / materials
# --------------------------------------------------------------------------------------

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    sc.unit_settings.length_unit = "METERS"
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x = 1600
    sc.render.resolution_y = 900
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.compression = 90      # PNG is lossless; this just shrinks the file
    try:
        bpy.context.preferences.filepaths.save_version = 0   # no .blend1 backups in the repo
    except Exception:
        pass
    for vt in ("Standard", "Filmic", "AgX"):
        try:
            sc.view_settings.view_transform = vt
            break
        except TypeError:
            continue
    sc.view_settings.look = "None"
    try:
        sc.eevee.taa_render_samples = 64
        sc.eevee.use_shadows = True
        sc.eevee.use_raytracing = True
    except Exception:
        pass
    return sc


def view_transform_used():
    return bpy.context.scene.view_settings.view_transform


def make_materials(palette=None):
    palette = palette or {}
    specs = {}
    mats = {}
    for slot in MATERIAL_SLOTS:
        spec = dict(DEFAULT_MATERIALS[slot])
        spec.update(palette.get(slot, {}))
        specs[slot] = spec

        m = bpy.data.materials.new(slot)
        m.use_nodes = True
        nt = m.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        lin = hex_to_linear(spec["color"])
        bsdf.inputs["Base Color"].default_value = (lin[0], lin[1], lin[2], 1.0)
        bsdf.inputs["Roughness"].default_value = float(spec.get("roughness", 0.5))
        bsdf.inputs["Metallic"].default_value = float(spec.get("metallic", 0.0))
        alpha = float(spec.get("alpha", 1.0))
        bsdf.inputs["Alpha"].default_value = alpha
        em = float(spec.get("emissive", 0.0))
        if em > 0.0:
            bsdf.inputs["Emission Color"].default_value = (lin[0], lin[1], lin[2], 1.0)
            bsdf.inputs["Emission Strength"].default_value = em
        if alpha < 1.0:
            for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
                try:
                    setattr(m, attr, val)
                    break
                except (AttributeError, TypeError):
                    continue
            try:
                m.use_transparent_shadow = True
            except AttributeError:
                pass
        mats[slot] = m
    return mats, specs


def materials_table(specs, used):
    out = []
    for slot in MATERIAL_SLOTS:
        if slot not in used:
            continue
        s = specs[slot]
        lin = hex_to_linear(s["color"])
        out.append(dict(
            slot=slot,
            base_color_hex=s["color"].upper(),
            base_color_linear=[round(c, 5) for c in lin],
            roughness=round(float(s.get("roughness", 0.5)), 3),
            metallic=round(float(s.get("metallic", 0.0)), 3),
            alpha=round(float(s.get("alpha", 1.0)), 3),
            emissive_strength=round(float(s.get("emissive", 0.0)), 3),
            runtime_input=slot in ("M_BrandAccent", "M_Sign", "M_Screen"),
        ))
    return out


# --------------------------------------------------------------------------------------
# the Piece
# --------------------------------------------------------------------------------------

class Piece:
    def __init__(self, pid, version, size_class, palette=None, bevel=True):
        self.id = pid
        self.version = version
        self.size_class = size_class
        self.limits = CLASS_LIMITS[size_class]
        self.bevel = bevel
        self.t0 = time.time()

        self.mats, self.mat_specs = make_materials(palette)
        self.sb = MeshBuilder()                 # the Shell
        self.sockets: list[dict] = []
        self.sub: dict[str, dict] = {}          # role -> {builder, loc, rot}
        self.interior = None                    # (lo, hi) of the walkable interior
        self.door_info = None
        self.clearances = {}
        self.light_a = 0
        self.light_b = 0
        self.notes: list[str] = []
        self.preview_int = None                 # (camera loc, target) override
        self.objects: dict[str, bpy.types.Object] = {}

    # -- naming -------------------------------------------------------------------
    def oname(self, role):
        return "SM_%s_%s_%s" % (self.id, self.version, role)

    # -- sockets ------------------------------------------------------------------
    def socket(self, name, loc, rot=(0.0, 0.0, 0.0)):
        full = name if name.startswith(("SOCKET_", "VOLUME_")) else "SOCKET_" + name
        self.sockets.append(dict(name=full, loc=tuple(float(c) for c in loc),
                                 rot=tuple(float(c) for c in rot)))
        return full

    def socket_loc(self, name):
        for s in self.sockets:
            if s["name"] == name:
                return s["loc"]
        return None

    # -- shell shorthand ----------------------------------------------------------
    def box(self, lo, hi, mat, faces=None):
        self.sb.box(lo, hi, mat, faces)

    def extrude(self, poly2d, plane, a, b, side_mat, cap_mat=None, cap_a_mat=None, cap_b_mat=None):
        self.sb.extrude(poly2d, plane, a, b, side_mat, cap_mat, cap_a_mat, cap_b_mat)

    # ---------------------------------------------------------------- floor / plinth
    def plinth(self, half_x, half_y, *, skirt=0.15, base_h=0.09, deck_h=0.05, mat="M_Trim", deck_mat="M_Floor"):
        """Base slab + deck. Returns the floor top z (must stay <= FLOOR_TOP_MAX)."""
        self.box((-half_x - skirt, -half_y - skirt, 0.0), (half_x + skirt, half_y + skirt, base_h), mat)
        top = base_h + deck_h
        self.box((-half_x, -half_y, base_h), (half_x, half_y, top),
                 deck_mat, faces={"+z": deck_mat})
        self.clearances["floor_top_z"] = round(top, 4)
        return top

    # ---------------------------------------------------------------- wall runs
    def wall_run(self, *, along, outer, out_sign, t, a, b, z0, z1,
                 openings=(), mat="M_Wall", in_mat="M_WallInterior", reveal_mat="M_Trim"):
        """A straight wall built from segments — openings are left as real holes.

        along     'x' or 'y': the wall's length axis
        outer     coordinate of the OUTER face on the other horizontal axis
        out_sign  +1 if outside lies in the + direction of that axis
        t         thickness; a,b length extents; z0,z1 bottom/top
        openings  [{'center':..,'width':..,'sill':..,'head':..}, ...] along the length axis
        """
        inner = outer - out_sign * t
        p0, p1 = min(outer, inner), max(outer, inner)
        in_key = "+" + ("y" if along == "x" else "x") if out_sign < 0 else "-" + ("y" if along == "x" else "x")
        out_key = "-" + ("y" if along == "x" else "x") if out_sign < 0 else "+" + ("y" if along == "x" else "x")
        face_mats = {in_key: in_mat, out_key: mat}

        def emit(u0, u1, zz0, zz1):
            if u1 - u0 < 1e-6 or zz1 - zz0 < 1e-6:
                return
            if along == "x":
                self.box((u0, p0, zz0), (u1, p1, zz1), mat, faces=face_mats)
            else:
                self.box((p0, u0, zz0), (p1, u1, zz1), mat, faces=face_mats)

        ops = sorted(openings, key=lambda o: o["center"])
        cursor = a
        for o in ops:
            ow = o["width"]
            u0 = o["center"] - ow * 0.5
            u1 = o["center"] + ow * 0.5
            sill = max(z0, o.get("sill", z0))
            head = min(z1, o.get("head", z1))
            emit(cursor, u0, z0, z1)
            emit(u0, u1, z0, sill)          # under-sill panel
            emit(u0, u1, head, z1)          # over-head panel
            cursor = u1
        emit(cursor, b, z0, z1)

        # optional reveal: a surround standing proud of the outer face, framing the opening
        for o in ops:
            if not o.get("reveal", False):
                continue
            ow = o["width"]
            u0, u1 = o["center"] - ow * 0.5, o["center"] + ow * 0.5
            sill = max(z0, o.get("sill", z0))
            head = min(z1, o.get("head", z1))
            d = o.get("reveal_proud", 0.05)
            lo_p, hi_p = sorted((outer - out_sign * 0.02, outer + out_sign * d))
            for (ua, ub, za, zb) in (
                (u0 - 0.10, u0, sill, head),
                (u1, u1 + 0.10, sill, head),
                (u0 - 0.10, u1 + 0.10, head, head + 0.12),
            ):
                if along == "x":
                    self.box((ua, lo_p, za), (ub, hi_p, zb), reveal_mat)
                else:
                    self.box((lo_p, ua, za), (hi_p, ub, zb), reveal_mat)
        return inner

    def window(self, *, along, outer, out_sign, t, center, width, sill, head,
               glass="M_Glass", frame="M_Trim", surround=0.10, proud=0.05, mullions=1):
        """Glass pane, frame and an outer surround for an opening already left by wall_run."""
        inner = outer - out_sign * t
        mid = (outer + inner) * 0.5
        u0, u1 = center - width * 0.5, center + width * 0.5
        sa, sb = sorted((outer - out_sign * 0.02, outer + out_sign * proud))

        def bx(ua, ub, za, zb, p0, p1, mat):
            if along == "x":
                self.box((ua, p0, za), (ub, p1, zb), mat)
            else:
                self.box((p0, ua, za), (p1, ub, zb), mat)

        bx(u0, u1, sill, head, mid - 0.02, mid + 0.02, glass)
        # frame inside the opening
        for (ua, ub, za, zb) in ((u0, u0 + 0.06, sill, head), (u1 - 0.06, u1, sill, head),
                                 (u0, u1, sill, sill + 0.06), (u0, u1, head - 0.06, head)):
            bx(ua, ub, za, zb, mid - 0.04, mid + 0.04, frame)
        # glazing bars
        for i in range(1, mullions + 1):
            g = u0 + (u1 - u0) * i / (mullions + 1)
            bx(g - 0.03, g + 0.03, sill, head, mid - 0.03, mid + 0.03, frame)
        # surround standing proud of the facade
        for (ua, ub, za, zb) in (
            (u0 - surround, u0, sill - surround, head + surround),
            (u1, u1 + surround, sill - surround, head + surround),
            (u0, u1, sill - surround, sill),
            (u0, u1, head, head + surround),
        ):
            bx(ua, ub, za, zb, sa, sb, frame)

    # A round window is built from a square opening in the wall plus a ring that hides it.
    # The ring must cover the square completely: inner radius under half the opening width
    # (so the straight edges are behind it) and outer radius past the corners.
    ROUND_WIN_OPENING = 1.24        # square opening left by wall_run
    ROUND_WIN_APERTURE = 0.60       # what you actually see through
    ROUND_WIN_FRAME_OUT = 0.98
    ROUND_WIN_GLASS = 0.92

    def round_window(self, *, along, outer, out_sign, t, center, z,
                     r_glass=None, r_frame_in=None, r_frame_out=None, segs=32):
        """A circular window set into a square opening — no booleans, no holes, no leaks."""
        r_glass = self.ROUND_WIN_GLASS if r_glass is None else r_glass
        r_frame_in = self.ROUND_WIN_APERTURE if r_frame_in is None else r_frame_in
        r_frame_out = self.ROUND_WIN_FRAME_OUT if r_frame_out is None else r_frame_out
        inner = outer - out_sign * t
        mid = (outer + inner) * 0.5
        plane = "xz" if along == "x" else "yz"
        c2 = (center, z)
        self.sb.disc(c2, r_glass, plane, mid - 0.02, mid + 0.02, "M_Glass", segs=segs)
        o0, o1 = min(outer, inner), max(outer, inner)
        self.sb.annulus(c2, r_frame_in, r_frame_out, plane, o1 - 0.02, o1 + 0.06, "M_Trim", segs=segs)
        self.sb.annulus(c2, r_frame_in, r_frame_out, plane, o0 - 0.06, o0 + 0.02, "M_Trim", segs=segs)

    def round_window_opening(self, z):
        """The wall_run opening a round_window at height `z` needs."""
        h = self.ROUND_WIN_OPENING / 2
        return dict(center=0.0, width=self.ROUND_WIN_OPENING, sill=z - h, head=z + h)

    def glazed_run(self, *, along, outer, out_sign, t, a, b, z0, z1, door=None,
                   pane_max=1.7, mullion=0.09, frame=0.14, transom=None):
        """Full-height glazing: rails, mullions, glass, and an optional door opening."""
        inner = outer - out_sign * t
        p0, p1 = min(outer, inner), max(outer, inner)
        mid = (outer + inner) * 0.5
        transom = transom if transom is not None else (door["head"] if door else None)

        def bx(u0, u1, zz0, zz1, m, q0=None, q1=None):
            q0 = p0 if q0 is None else q0
            q1 = p1 if q1 is None else q1
            if along == "x":
                self.box((u0, q0, zz0), (u1, q1, zz1), m)
            else:
                self.box((q0, u0, zz0), (q1, u1, zz1), m)

        # outer frame — the bottom rail stops either side of the door so there is no step
        if door:
            bx(a, door["center"] - door["width"] * 0.5, z0, z0 + frame, "M_Trim")
            bx(door["center"] + door["width"] * 0.5, b, z0, z0 + frame, "M_Trim")
        else:
            bx(a, b, z0, z0 + frame, "M_Trim")
        bx(a, b, z1 - frame, z1, "M_Trim")
        bx(a, a + frame, z0, z1, "M_Trim")
        bx(b - frame, b, z0, z1, "M_Trim")

        # mullion positions, forced to include the door jambs
        hard = []
        if door:
            hard = [door["center"] - door["width"] * 0.5, door["center"] + door["width"] * 0.5]
        stops = sorted(set([a + frame] + hard + [b - frame]))
        grid = []
        for i in range(len(stops) - 1):
            u0, u1 = stops[i], stops[i + 1]
            is_door = bool(hard) and abs(u0 - hard[0]) < 1e-6 and abs(u1 - hard[1]) < 1e-6
            n = 1 if is_door else max(1, int(math.ceil((u1 - u0 - 1e-6) / pane_max)))
            for k in range(n + 1):
                grid.append(u0 + (u1 - u0) * k / n)
        grid = sorted(set(round(g, 5) for g in grid))

        for g in grid[1:-1]:
            bx(g - mullion * 0.5, g + mullion * 0.5, z0 + frame, z1 - frame, "M_Trim")

        if transom:
            bx(a + frame, b - frame, transom - 0.06, transom + 0.06, "M_Trim")

        for i in range(len(grid) - 1):
            u0, u1 = grid[i] + mullion * 0.5, grid[i + 1] - mullion * 0.5
            if u1 - u0 < 0.05:
                continue
            in_door = door is not None and u0 >= hard[0] - 1e-4 and u1 <= hard[1] + 1e-4
            spans = []
            if in_door:
                spans.append((max(z0 + frame, transom + 0.06), z1 - frame))
            else:
                if transom:
                    spans.append((z0 + frame, transom - 0.06))
                    spans.append((transom + 0.06, z1 - frame))
                else:
                    spans.append((z0 + frame, z1 - frame))
            for (za, zb) in spans:
                if zb - za > 0.05:
                    bx(u0, u1, za, zb, "M_Glass", mid - 0.015, mid + 0.015)
        return inner

    # ---------------------------------------------------------------- roofs
    def flat_roof(self, half_x, half_y, z_bottom, z_top, *, overhang=0.0, parapet=None,
                  mat="M_Roof", trim="M_Trim"):
        hx, hy = half_x + overhang, half_y + overhang
        self.box((-hx, -hy, z_bottom), (hx, hy, z_top), mat, faces={"-z": "M_WallInterior"})
        if overhang > 0:
            self.box((-hx, -hy, z_bottom - 0.08), (hx, hy, z_bottom), trim)
        if parapet:
            h, tt = parapet
            top = z_top + h
            self.box((-hx, -hy, z_top), (hx, -hy + tt, top), mat, faces={"+z": trim})
            self.box((-hx, hy - tt, z_top), (hx, hy, top), mat, faces={"+z": trim})
            self.box((-hx, -hy + tt, z_top), (-hx + tt, hy - tt, top), mat, faces={"+z": trim})
            self.box((hx - tt, -hy + tt, z_top), (hx, hy - tt, top), mat, faces={"+z": trim})
            return top
        return z_top

    def roof_prism(self, profile, plane, a, b, *, mat="M_Roof", cap_mat="M_Wall"):
        """A solid roof form (gable, mono-pitch, sawtooth, fold) sitting on the wall tops.

        Solid, so there is never a gap between wall top and roof underside, and the end caps
        read as gables — hence cap_mat defaults to the wall colour.
        """
        self.extrude(profile, plane, a, b, mat, cap_mat=cap_mat)

    def ceiling(self, lo, hi, z0, z1, *, mat="M_Trim", under="M_WallInterior"):
        self.box((lo[0], lo[1], z0), (hi[0], hi[1], z1), mat, faces={"-z": under})

    # ---------------------------------------------------------------- fittings
    def light_a_fixture(self, x, y, z_under, *, size=0.46, h=0.09):
        self.box((x - size / 2, y - size / 2, z_under), (x + size / 2, y + size / 2, z_under + h),
                 "M_LightEmissive", faces={"+z": "M_Metal"})
        self.light_a += 1
        self.socket("SOCKET_LightA_%d" % self.light_a, (x, y, z_under - 0.02))

    def light_b_fixture(self, center, normal, *, depth=0.13, width=0.13, height=0.52):
        """Wall fixture whose back face sits exactly on the wall surface at `center`."""
        n = Vector(normal).normalized()
        c = Vector(center) + n * (depth * 0.5)
        half = Vector((width / 2, width / 2, height / 2))
        for i in range(3):
            if abs(n[i]) > 0.5:
                half[i] = depth / 2
        lo = tuple(c[i] - half[i] for i in range(3))
        hi = tuple(c[i] + half[i] for i in range(3))
        back = ("-x", "+x") if abs(n[0]) > 0.5 else ("-y", "+y")
        self.box(lo, hi, "M_LightEmissive", faces={(back[0] if n[0] + n[1] > 0 else back[1]): "M_Metal"})
        self.light_b += 1
        self.socket("SOCKET_LightB_%d" % self.light_b, tuple(c), _rot_from_normal(n))

    def furniture_block(self, lo, hi, *, mat="M_Trim", top="M_Floor"):
        self.box(lo, hi, mat, faces={"+z": top})

    def bench(self, center, *, length=1.8, depth=0.5, seat_z=0.45, axis="x", mat="M_Trim"):
        x, y, z = center
        hl, hd = length / 2, depth / 2
        if axis == "x":
            self.box((x - hl, y - hd, seat_z - 0.07), (x + hl, y + hd, seat_z), mat, faces={"+z": "M_Door"})
            for sx in (x - hl + 0.12, x + hl - 0.24):
                self.box((sx, y - hd + 0.06, z), (sx + 0.12, y + hd - 0.06, seat_z - 0.07), mat)
        else:
            self.box((x - hd, y - hl, seat_z - 0.07), (x + hd, y + hl, seat_z), mat, faces={"+z": "M_Door"})
            for sy in (y - hl + 0.12, y + hl - 0.24):
                self.box((x - hd + 0.06, sy, z), (x + hd - 0.06, sy + 0.12, seat_z - 0.07), mat)

    # ---------------------------------------------------------------- sub-objects
    def add_door(self, *, hinge, width, height, thickness=0.08, open_sign=1, leaf_gap=0.02):
        """Door leaf authored at its hinge (origin on the hinge axis at floor level)."""
        b = MeshBuilder()
        w = width - leaf_gap * 2
        h = height - leaf_gap
        hs = 1.0 if open_sign >= 0 else -1.0
        x0 = hs * leaf_gap          # equal gap at both jambs
        x1 = x0 + hs * w
        b.box((x0, -thickness / 2, 0.0), (x1, thickness / 2, h), "M_Door")
        # recessed panel + handle
        ins = 0.16
        b.box((x0 + hs * ins, -thickness / 2 - 0.025, 0.30), (x1 - hs * ins, thickness / 2 + 0.025, h - 0.30),
              "M_Door", faces={"-y": "M_Trim", "+y": "M_Trim"})
        hx = x1 - hs * 0.18
        b.box((hx - 0.03, -thickness / 2 - 0.07, 1.00), (hx + 0.03, thickness / 2 + 0.07, 1.14), "M_Metal")
        self.sub["Door"] = dict(builder=b, loc=tuple(hinge), rot=(0.0, 0.0, 0.0))
        self.socket("SOCKET_Door", hinge)
        self.door_info = dict(
            hinge_socket="SOCKET_Door", open_axis="Z", open_degrees=90, open_sign=int(hs),
            clear_width=round(width, 4), clear_height=round(height, 4),
            leaf_size=[round(w, 4), round(thickness, 4), round(h, 4)],
            swings="inward",
        )
        self.clearances["door_clear_width"] = round(width, 4)
        self.clearances["door_clear_height"] = round(height, 4)

    def add_switch(self):
        """One switch (plate + rocker). Mounting plane is local y = 0; the body stands in -Y."""
        b = MeshBuilder()
        b.box((-0.075, -0.022, -0.105), (0.075, 0.0, 0.105), "M_Switch")
        b.box((-0.045, -0.036, -0.05), (0.045, -0.018, 0.05), "M_Trim")
        self.sub["Switch"] = dict(builder=b, loc=(0, 0, 0), rot=(0, 0, 0))

    def add_switches(self, a_center, b_center, normal):
        """Two switch sockets on a wall surface; `normal` points into the room."""
        rot = _rot_from_normal(normal)
        self.add_switch()
        self.sub["Switch"]["loc"] = tuple(a_center)
        self.sub["Switch"]["rot"] = rot
        self.socket("SOCKET_SwitchA", a_center, rot)
        self.socket("SOCKET_SwitchB", b_center, rot)

    def _panel(self, role, mat, center, normal, size, back_depth, embed, frame_margin):
        """Shared build for Screen and Sign: a 0-1 UV quad standing proud of a backing box."""
        w, h = size
        n = Vector(normal).normalized()
        rot = _rot_from_normal(n)
        c = Vector(center)
        back_lo = c - n * embed
        back_hi = c + n * (back_depth - embed)
        quad_at = back_hi + n * 0.015

        b = MeshBuilder()
        b.quad([(-w / 2, 0.0, -h / 2), (w / 2, 0.0, -h / 2), (w / 2, 0.0, h / 2), (-w / 2, 0.0, h / 2)],
               mat, uv01=True, normal_hint=(0.0, -1.0, 0.0))
        self.sub[role] = dict(builder=b, loc=tuple(quad_at), rot=rot)
        self.socket("SOCKET_" + role, tuple(quad_at), rot)

        if frame_margin is not None:
            half = []
            for i in range(3):
                if abs(n[i]) > 0.5:
                    half.append(0.0)
                else:
                    half.append((w / 2 if i != 2 else h / 2) + frame_margin)
            lo = tuple(min(back_lo[i], back_hi[i]) - half[i] for i in range(3))
            hi = tuple(max(back_lo[i], back_hi[i]) + half[i] for i in range(3))
            self.box(lo, hi, "M_Trim")
        return quad_at, rot

    def add_screen(self, center, normal=(0.0, -1.0, 0.0), *, size=None, bezel=0.08,
                   depth=0.10, embed=0.05):
        """16:9 display quad on a wall. `center` is on the wall face, `normal` points into the room."""
        size = size or SCREEN_SIZE[self.size_class]
        self.screen_size = size
        return self._panel("Screen", "M_Screen", center, normal, size, depth, embed, bezel)

    def add_sign(self, center, normal=(0.0, -1.0, 0.0), *, size=None, band=0.10,
                 depth=0.11, embed=0.02):
        """2:1 sign panel. `center` is on the facade, `normal` points outward (-Y at the front)."""
        size = size or SIGN_SIZE[self.size_class]
        self.sign_size = size
        return self._panel("Sign", "M_Sign", center, normal, size, depth, embed, band)

    # ---------------------------------------------------------------- volumes / markers
    def interior_volume(self, lo, hi):
        self.interior = (tuple(lo), tuple(hi))
        c = [(lo[i] + hi[i]) / 2 for i in range(3)]
        self.socket("VOLUME_Interior", c)
        self.clearances["interior_clear_height"] = round(hi[2] - lo[2], 4)
        return c

    def standard_markers(self, *, roof_top, front_y):
        self.socket("SOCKET_Waypoint", (0.0, front_y * 0.45, roof_top + 0.9))
        d = THUMBCAM_DIST[self.size_class]
        self.socket("SOCKET_ThumbCam", (0.0, -d, THUMBCAM_EYE), (0.0, 0.0, 0.0))

    def standard_interior(self, *, lo, hi, door_center_x=0.0, wall_t=0.22,
                          lights_a=(2, 1), light_b_z=2.25, furniture=True,
                          switch_surface=None, inside_offset=None):
        """Ceiling fixtures, wall fixtures, screen on the wall facing the door, two switches
        beside the door, simple furniture and the interior volume — the parts every walk-in
        piece shares. `lo`/`hi` are the interior box (floor top .. ceiling underside)."""
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        cx = (x0 + x1) / 2

        nx, ny = lights_a
        for i in range(nx):
            for j in range(ny):
                lx = x0 + (x1 - x0) * (i + 1) / (nx + 1)
                ly = y0 + (y1 - y0) * (j + 1) / (ny + 1)
                self.light_a_fixture(lx, ly, z1 - 0.09)

        # screen on the wall facing the door (+Y), looking back into the room
        sc_w, sc_h = SCREEN_SIZE[self.size_class]
        sc_z = z0 + min(1.80, (z1 - z0) * 0.45)
        self.add_screen((cx, y1, sc_z), (0.0, -1.0, 0.0))

        # wall fixtures flanking the screen
        for sx in (cx - sc_w / 2 - 0.55, cx + sc_w / 2 + 0.55):
            self.light_b_fixture((sx, y1, light_b_z), (0.0, -1.0, 0.0))

        # two switches next to the door at 1.2 m, facing into the room.
        # switch_surface = (x_of_first, y_of_mounting_face) when the door wall is not solid there.
        if switch_surface is None:
            sw_x0, sw_y = door_center_x + 1.05, y0
        else:
            sw_x0, sw_y = switch_surface
        self.add_switches((sw_x0, sw_y, 1.20), (sw_x0 + 0.38, sw_y, 1.20), (0.0, 1.0, 0.0))

        if furniture:
            # kept off the door -> screen path (|x - cx| < 0.95 stays clear) and close enough
            # to the middle that the interior preview actually shows it
            w, dpt = x1 - x0, y1 - y0
            self.bench((cx - w * 0.26, y0 + dpt * 0.45, z0),
                       length=min(2.2, dpt * 0.40), depth=0.52, seat_z=z0 + 0.46, axis="y")
            pw, pd = min(1.20, w * 0.17), min(1.20, dpt * 0.17)
            px = cx + w * 0.17
            self.furniture_block((px, y0 + dpt * 0.30, z0), (px + pw, y0 + dpt * 0.30 + pd, z0 + 0.80))
            qx = cx + w * 0.31
            self.furniture_block((qx, y1 - dpt * 0.26 - pd * 0.8, z0),
                                 (qx + pw * 0.7, y1 - dpt * 0.26, z0 + 1.10))
            if w > 8.0:
                tx = cx - w * 0.30
                self.furniture_block((tx, y1 - dpt * 0.34, z0), (tx + pw * 1.3, y1 - dpt * 0.34 + pd, z0 + 0.52),
                                     top="M_WallInterior")

        self.interior_volume(lo, hi)
        ins = inside_offset if inside_offset is not None else min(1.9, (y1 - y0) * 0.30)
        self.socket("SOCKET_Inside", (cx, y0 + ins, z0), (0.0, 0.0, math.pi))
        self.preview_int = ((cx - 0.40, y0 + 0.45, z0 + 1.72), (cx + 0.15, y1 - 0.1, z0 + 1.15))

    # ---------------------------------------------------------------- bake
    def finish(self):
        shell_name = self.oname("Shell")
        shell = self.sb.to_object(shell_name, self.mats)
        self.objects["Shell"] = shell
        if self.bevel:
            _apply_bevel(shell)

        for role, info in self.sub.items():
            ob = info["builder"].to_object(self.oname(role), self.mats)
            ob.location = info["loc"]
            ob.rotation_euler = info["rot"]
            if self.bevel and role in ("Door", "Switch"):
                _apply_bevel(ob, width=0.012)
            self.objects[role] = ob

        # sockets, parented to the Shell
        for s in self.sockets:
            e = bpy.data.objects.new(s["name"], None)
            bpy.context.scene.collection.objects.link(e)
            e.empty_display_type = "ARROWS"
            e.empty_display_size = 0.45
            e.location = s["loc"]
            e.rotation_euler = s["rot"]
            if s["name"] == "VOLUME_Interior" and self.interior:
                lo, hi = self.interior
                e.empty_display_type = "CUBE"
                e.empty_display_size = 1.0
                e.scale = tuple(max(1e-3, (hi[i] - lo[i]) / 2) for i in range(3))
            e.parent = shell
            e.matrix_parent_inverse = shell.matrix_world.inverted()
            s["object"] = e

        bpy.context.view_layer.update()
        return self._metadata()

    def mesh_objects(self):
        return [self.objects[r] for r in ("Shell", "Door", "Switch", "Screen", "Sign")
                if r in self.objects]

    def socket_objects(self):
        return [s["object"] for s in self.sockets if "object" in s]

    # ---------------------------------------------------------------- metadata
    def _metadata(self):
        mesh_objs = self.mesh_objects()
        lo = [1e9] * 3
        hi = [-1e9] * 3
        tris = {}
        used_mats = []
        for ob in mesh_objs:
            n = 0
            for p in ob.data.polygons:
                n += max(0, len(p.vertices) - 2)
            tris[ob.name] = n
            for m in ob.data.materials:
                if m.name not in used_mats:
                    used_mats.append(m.name)
            for c in ob.bound_box:
                w = ob.matrix_world @ Vector(c)
                for i in range(3):
                    lo[i] = min(lo[i], w[i])
                    hi[i] = max(hi[i], w[i])

        lo = [round(v, 4) for v in lo]
        hi = [round(v, 4) for v in hi]
        size = [round(hi[i] - lo[i], 4) for i in range(3)]

        # The class footprint is centred on the origin (spec v1 section 2), so the test is
        # "does the bounding box sit inside the centred box", not just "is it small enough".
        fits = []
        for slot in ALL_SLOTS:
            lx, ly, lz = CLASS_LIMITS[SLOT_CLASS[slot]]
            if (max(abs(lo[0]), abs(hi[0])) <= lx / 2 + 1e-6
                    and max(abs(lo[1]), abs(hi[1])) <= ly / 2 + 1e-6
                    and hi[2] <= lz + 1e-6 and lo[2] >= -1e-6):
                fits.append(slot)

        sockets = []
        for s in self.sockets:
            fwd = s["object"].matrix_world.to_3x3() @ Vector((0.0, -1.0, 0.0))
            fwd.normalize()
            sockets.append(dict(
                name=s["name"],
                location=[round(c, 4) for c in s["loc"]],
                rotation_euler_deg=[round(math.degrees(c), 3) for c in s["rot"]],
                forward=[round(c, 4) for c in fwd],
            ))

        objects = []
        for role in ("Shell", "Door", "Switch", "Screen", "Sign"):
            ob = self.objects.get(role)
            if ob is None:
                continue
            objects.append(dict(
                name=ob.name, role=role, triangles=tris[ob.name],
                location=[round(c, 4) for c in ob.location],
                rotation_euler_deg=[round(math.degrees(c), 3) for c in ob.rotation_euler],
                materials=[m.name for m in ob.data.materials],
            ))

        interactables = dict(
            door="Door" in self.objects,
            screen="Screen" in self.objects,
            sign="Sign" in self.objects,
            switches=2 if "Switch" in self.objects else 0,
            lights_a=self.light_a,
            lights_b=self.light_b,
            state_schema_version=SCHEMA_VERSION,
        )

        iv = None
        if self.interior:
            ilo, ihi = self.interior
            iv = dict(
                min=[round(c, 4) for c in ilo], max=[round(c, 4) for c in ihi],
                center=[round((ilo[i] + ihi[i]) / 2, 4) for i in range(3)],
                size=[round(ihi[i] - ilo[i], 4) for i in range(3)],
            )

        return dict(
            schema_version=SCHEMA_VERSION,
            id=self.id,
            version=self.version,
            size_class=self.size_class,
            class_limits=dict(zip(("x", "y", "z"), self.limits)),
            front_axis=FRONT_AXIS,
            bounds=dict(min=lo, max=hi, size=size),
            fits_slots=fits,
            triangles=sum(tris.values()),
            triangles_by_object=tris,
            objects=objects,
            materials=materials_table(self.mat_specs, used_mats),
            material_slot_count=len(used_mats),
            sockets=sockets,
            interior_volume=iv,
            door=self.door_info,
            clearances={k: self.clearances[k] for k in sorted(self.clearances)},
            interactables=interactables,
            state_schema=STATE_SCHEMA if interactables["door"] else [],
            notes=self.notes,
            build_seconds=None,
        )


def _apply_bevel(ob, width=BEVEL_WIDTH, segments=1):
    md = ob.modifiers.new("Bevel", "BEVEL")
    md.width = width
    md.segments = segments
    md.limit_method = "ANGLE"
    md.angle_limit = BEVEL_ANGLE
    md.use_clamp_overlap = True
    md.miter_outer = "MITER_SHARP"
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.ops.object.modifier_apply(modifier=md.name)
    ob.select_set(False)


# --------------------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------------------

def _select(objects):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in objects:
        o.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]


def export_piece(meta, objects, sockets, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    stem = "%s_%s" % (meta["id"], meta["version"])
    sel = list(objects) + list(sockets)
    _select(sel)

    fbx = os.path.join(out_dir, stem + ".fbx")
    bpy.ops.export_scene.fbx(
        filepath=fbx, use_selection=True, object_types={"MESH", "EMPTY"},
        apply_unit_scale=True, global_scale=1.0, apply_scale_options="FBX_SCALE_NONE",
        use_mesh_modifiers=True, mesh_smooth_type="FACE", use_triangles=False,
        bake_space_transform=False, bake_anim=False, path_mode="AUTO",
        embed_textures=False, use_custom_props=True,
    )

    _select(sel)
    glb = os.path.join(out_dir, stem + ".glb")
    bpy.ops.export_scene.gltf(
        filepath=glb, export_format="GLB", use_selection=True,
        export_apply=True, export_cameras=False, export_lights=False,
        export_extras=True, export_yup=True, export_animations=False,
    )
    return fbx, glb


# --------------------------------------------------------------------------------------
# preview rendering
# --------------------------------------------------------------------------------------

def _mat_nodes(mat):
    mat.use_nodes = True
    return mat.node_tree, mat.node_tree.nodes.get("Principled BSDF")


def preview_dress(piece, *, brand=PREVIEW_BRAND_COLOR, emblem=PREVIEW_EMBLEM,
                  screen_image=None, lights_a_on=True, lights_b_on=False):
    """Apply the runtime inputs (brand colour, emblem, screen image) and switch light group A on.

    Called only AFTER export, so nothing brand-specific is ever baked into an asset.
    """
    lin = hex_to_linear(brand)

    accent = piece.mats["M_BrandAccent"]
    nt, bsdf = _mat_nodes(accent)
    bsdf.inputs["Base Color"].default_value = (lin[0], lin[1], lin[2], 1.0)

    # sign: brand colour with the emblem (white, left half) over it
    sign = piece.mats["M_Sign"]
    nt, bsdf = _mat_nodes(sign)
    emb_path = art_path("emblems", "%s.png" % emblem)
    if os.path.exists(emb_path):
        img = bpy.data.images.load(emb_path, check_existing=True)
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.extension = "CLIP"
        tex.interpolation = "Cubic"
        uvn = nt.nodes.new("ShaderNodeUVMap")
        mapn = nt.nodes.new("ShaderNodeMapping")
        mapn.inputs["Scale"].default_value = (2.0, 1.0, 1.0)
        mapn.inputs["Location"].default_value = (-0.12, 0.0, 0.0)
        nt.links.new(uvn.outputs["UV"], mapn.inputs["Vector"])
        nt.links.new(mapn.outputs["Vector"], tex.inputs["Vector"])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs[6].default_value = (lin[0], lin[1], lin[2], 1.0)
        mix.inputs[7].default_value = (0.92, 0.92, 0.92, 1.0)
        nt.links.new(tex.outputs["Alpha"], mix.inputs[0])
        nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (lin[0], lin[1], lin[2], 1.0)

    # screen: a sample image, lightly emissive so it reads in a lit room
    screen = piece.mats["M_Screen"]
    nt, bsdf = _mat_nodes(screen)
    if screen_image and os.path.exists(screen_image):
        img = bpy.data.images.load(screen_image, check_existing=True)
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.extension = "EXTEND"
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.6
    else:
        bsdf.inputs["Base Color"].default_value = (0.05, 0.22, 0.38, 1.0)
        bsdf.inputs["Emission Color"].default_value = (0.05, 0.22, 0.38, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 1.6

    # a second switch instance at SOCKET_SwitchB (preview only — the asset ships one)
    extra = []
    sw = piece.objects.get("Switch")
    if sw is not None:
        for s in piece.sockets:
            if s["name"] == "SOCKET_SwitchB":
                dup = bpy.data.objects.new(sw.name + "_previewB", sw.data)
                bpy.context.scene.collection.objects.link(dup)
                dup.location = s["loc"]
                dup.rotation_euler = s["rot"]
                extra.append(dup)

    # real lights at the light-group sockets
    for s in piece.sockets:
        grp = None
        if s["name"].startswith("SOCKET_LightA_") and lights_a_on:
            grp = ("A", 90.0, 1.1)
        elif s["name"].startswith("SOCKET_LightB_") and lights_b_on:
            grp = ("B", 35.0, 0.5)
        if not grp:
            continue
        lt = bpy.data.lights.new("PV_Light%s" % grp[0], type="AREA")
        lt.shape = "SQUARE"
        lt.size = grp[2]
        lt.energy = grp[1]
        lt.color = (1.0, 0.94, 0.85)
        lo = bpy.data.objects.new(lt.name, lt)
        bpy.context.scene.collection.objects.link(lo)
        lo.location = s["loc"]
        lo.rotation_euler = (math.pi, 0.0, 0.0) if grp[0] == "A" else (math.pi / 2, 0.0, 0.0)
        extra.append(lo)
    bpy.context.view_layer.update()
    return extra


def preview_world(*, sun=True, ground=True, ground_size=240.0):
    sc = bpy.context.scene
    world = bpy.data.worlds.new("PV_World")
    world.use_nodes = True
    sc.world = world
    nt = world.node_tree
    bg = nt.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.42, 0.52, 0.62, 1.0)
    bg.inputs["Strength"].default_value = 1.0

    extra = []
    if sun:
        lt = bpy.data.lights.new("PV_Sun", type="SUN")
        lt.energy = 3.2
        lt.angle = math.radians(5.0)
        lt.color = (1.0, 0.97, 0.92)
        lo = bpy.data.objects.new("PV_Sun", lt)
        bpy.context.scene.collection.objects.link(lo)
        lo.rotation_euler = (math.radians(52.0), math.radians(8.0), math.radians(-128.0))
        extra.append(lo)
    if ground:
        m = bpy.data.materials.new("PV_Ground")
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        b.inputs["Base Color"].default_value = (0.26, 0.26, 0.25, 1.0)
        b.inputs["Roughness"].default_value = 0.92
        mb = MeshBuilder()
        h = ground_size / 2
        mb.poly([(-h, -h, 0.0), (h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0)], "PV_Ground")
        mesh = bpy.data.meshes.new("PV_Ground")
        mesh.from_pydata([list(v) for v in mb.verts], [], [list(mb.faces[0][0])])
        mesh.update()
        mesh.materials.append(m)
        ob = bpy.data.objects.new("PV_Ground", mesh)
        bpy.context.scene.collection.objects.link(ob)
        extra.append(ob)
    return extra


def class_frame(size_class, z=0.03, w=0.07):
    """The size-class limit drawn as a frame on the ground (top view)."""
    lx, ly, _ = CLASS_LIMITS[size_class]
    m = bpy.data.materials.new("PV_ClassFrame")
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.75, 0.02, 0.35, 1.0)
    b.inputs["Roughness"].default_value = 0.4
    b.inputs["Emission Color"].default_value = (0.9, 0.03, 0.42, 1.0)
    b.inputs["Emission Strength"].default_value = 1.2
    mb = MeshBuilder()
    hx, hy = lx / 2, ly / 2
    mb.box((-hx, -hy, 0.0), (hx, -hy + w, z), "PV_ClassFrame")
    mb.box((-hx, hy - w, 0.0), (hx, hy, z), "PV_ClassFrame")
    mb.box((-hx, -hy, 0.0), (-hx + w, hy, z), "PV_ClassFrame")
    mb.box((hx - w, -hy, 0.0), (hx, hy, z), "PV_ClassFrame")
    ob = mb.to_object("PV_ClassFrame", {"PV_ClassFrame": m})
    return ob


def _camera(name, lens=35.0, ortho=None):
    cd = bpy.data.cameras.new(name)
    if ortho:
        cd.type = "ORTHO"
        cd.ortho_scale = ortho
    else:
        cd.lens = lens
    ob = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _look_at(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def _fit_distance(cam_dir, target, corners, lens, res_x, res_y, margin=1.03):
    """Smallest camera distance along -cam_dir that keeps every bbox corner in frame."""
    sensor = 36.0
    hfov = 2 * math.atan((sensor / 2) / lens)
    vfov = 2 * math.atan((sensor / 2) * (res_y / res_x) / lens)
    th, tv = math.tan(hfov / 2), math.tan(vfov / 2)
    d = Vector(cam_dir).normalized()
    up0 = Vector((0.0, 0.0, 1.0))
    right = d.cross(up0)
    if right.length < 1e-6:
        right = Vector((1.0, 0.0, 0.0))
    right.normalize()
    up = right.cross(d).normalized()
    need = 1.0
    for c in corners:
        v = Vector(c) - Vector(target)
        need = max(need, abs(v.dot(right)) / th - v.dot(d), abs(v.dot(up)) / tv - v.dot(d))
    return need * margin


def _bbox_corners(meta):
    lo, hi = meta["bounds"]["min"], meta["bounds"]["max"]
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def render_previews(piece, meta, out_dir, *, samples=64):
    os.makedirs(out_dir, exist_ok=True)
    sc = bpy.context.scene
    try:
        sc.eevee.taa_render_samples = samples
    except Exception:
        pass
    stem = "%s_%s" % (meta["id"], meta["version"])
    lo, hi = meta["bounds"]["min"], meta["bounds"]["max"]
    centre = (0.0, 0.0, (lo[2] + hi[2]) / 2)
    out = {}

    def shoot(key, path):
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        out[key] = path

    # --- exterior three-quarter FRONT (the front of a piece is -Y) ---------------------
    cam = _camera("PV_Ext", lens=35.0)
    sc.camera = cam
    az, el = math.radians(-34.0), math.radians(22.0)
    # unit vector from the target towards the camera: in front (-Y), to one side, above
    to_cam = Vector((-math.sin(az), -math.cos(az), math.tan(el))).normalized()
    aim = (0.0, 0.0, lo[2] + (hi[2] - lo[2]) * 0.46)
    dist = _fit_distance(-to_cam, aim, _bbox_corners(meta), 35.0,
                         sc.render.resolution_x, sc.render.resolution_y)
    cam.location = Vector(aim) + to_cam * dist
    _look_at(cam, aim)
    shoot("ext", os.path.join(out_dir, stem + "_ext.png"))

    # --- interior, from just inside the door, looking at the screen --------------------
    cam_i = _camera("PV_Int", lens=20.0)
    sc.camera = cam_i
    if piece.preview_int:
        loc, tgt = piece.preview_int
    else:
        ilo, ihi = piece.interior if piece.interior else (lo, hi)
        cx = (ilo[0] + ihi[0]) / 2
        loc = (cx - 0.35, ilo[1] + 0.45, ilo[2] + 1.72)
        tgt = (cx, ihi[1] - 0.1, ilo[2] + 1.20)
    cam_i.location = Vector(loc)
    _look_at(cam_i, tgt)
    shoot("int", os.path.join(out_dir, stem + "_int.png"))

    # --- top, orthographic, with the class limit frame ---------------------------------
    frame = class_frame(meta["size_class"])
    lx, ly, _ = CLASS_LIMITS[meta["size_class"]]
    aspect = sc.render.resolution_x / sc.render.resolution_y
    cam_t = _camera("PV_Top", ortho=max(lx, ly * aspect) * 1.08)
    sc.camera = cam_t
    cam_t.location = (0.0, 0.0, max(hi[2] + 12.0, 24.0))
    cam_t.rotation_euler = (0.0, 0.0, 0.0)
    shoot("top", os.path.join(out_dir, stem + "_top.png"))

    bpy.data.objects.remove(frame, do_unlink=True)
    return out


# --------------------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------------------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(meta, out_dir, *, piece_script, exports, previews, build_seconds, render_info):
    meta = dict(meta)
    meta["exports"] = {k: os.path.relpath(v, _ART).replace("\\", "/") for k, v in exports.items()}
    meta["previews"] = {k: os.path.relpath(v, _ART).replace("\\", "/") for k, v in previews.items()}
    meta["build_seconds"] = round(build_seconds, 2)
    meta["render"] = render_info
    meta["generator"] = dict(
        dc_kit_sha256=sha256_file(os.path.join(os.path.dirname(__file__), "dc_kit.py")),
        piece_script=os.path.relpath(piece_script, _ART).replace("\\", "/"),
        piece_sha256=sha256_file(piece_script),
        blender=bpy.app.version_string,
        built_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    path = os.path.join(out_dir, "manifest.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=1, sort_keys=False)
        fh.write("\n")
    return path
