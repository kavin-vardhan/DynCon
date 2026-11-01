"""The environment kit: the same scripted Blender style as the content, for the two maps.

The content pieces (`art/blender/pieces/`) are *content* - they arrive at runtime, they have
sockets, a door, a sign and a brand. The environment is the opposite: it is shipped with the
build, it never changes, it has no sockets and no brand, and its only job is to make two
places that read as two different games and to frame the slots without competing with them.

So this file is a smaller cousin of `dc_kit`: it reuses that file's `MeshBuilder` (the same
welded-group polygon builder, the same outward-normal checks) and its colour maths, and adds

  * its own material slot list - paving, kerb, timber, foliage, water - instead of the
    content's wall/door/sign/screen list. **No M_BrandAccent, M_Sign or M_Screen here**: a
    piece of environment must never be able to wear a brand;
  * **two palettes**, `warm` (Game A, the plaza) and `cool` (Game B, the waterfront). The
    geometry is palette-independent and is exported once; the palette is a set of material
    instances the map chooses per actor. That is why there is one FBX per piece and not two;
  * tighter triangle budgets per category - the environment is background, and a plaza puts
    a couple of hundred of these on screen at once;
  * the same units contract as the content: authored in metres, **FBX in centimetres**, GLB
    in metres, and `bounds_cm` mirrors in the manifest so the validator can prove it.

Anchor convention, which is what makes `unreal/Tools/make_maps.py` short: every piece's origin
is its **ground-contact centre** - x and y centred on the footprint, z = 0 at the bottom - and
a piece that runs in a line (kerb, railing, boardwalk, steps) runs along **+X**, so placing one
is a location and a yaw and nothing else. The validator fails a piece whose geometry dips below
z = 0.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time

import bpy

_ENV_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.abspath(os.path.join(_ENV_DIR, ".."))
_ART = os.path.abspath(os.path.join(_BLENDER_DIR, ".."))
for _p in (_BLENDER_DIR, _ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dc_kit as K  # noqa: E402

MeshBuilder = K.MeshBuilder

SCHEMA_VERSION = 1
AUTHOR_UNITS = K.AUTHOR_UNITS
FBX_UNITS = K.FBX_UNITS
GLB_UNITS = K.GLB_UNITS
FBX_UNIT_SCALE = K.FBX_UNIT_SCALE

EXPORT_ROOT = os.path.join(_ART, "export_env")
PREVIEW_ROOT = os.path.join(_ART, "previews_env")

# ---------------------------------------------------------------------------- material slots

ENV_MATERIAL_SLOTS = (
    "M_Ground",       # the big ground plane under everything
    "M_GroundAlt",    # a second ground tone: the apron the paving is laid in
    "M_Grass",        # planted ground - the garden court
    "M_Paving",       # plaza slabs / promenade deck
    "M_PavingAlt",    # the banding and the inlays that give paving a rhythm
    "M_Kerb",
    # The slot pad's own two tones. A slot pad used to be paving and kerb like any other
    # ground piece, and an *empty* slot then read as a patch of the same paving it sits in -
    # which is exactly what a brand sees in the eye-level thumbnail it is bidding on. Its own
    # ground tone and a distinctly darker kerb band make the prepared spot a shape in the
    # picture. See ground._slot_pad.
    "M_SlotPad",
    "M_SlotKerb",
    "M_Wall",         # background block walls
    "M_WallAlt",      # a second wall tone, so a row of blocks is not one colour
    "M_Roof",
    "M_Trim",         # cornices, posts, railings, bollards, street furniture
    "M_Glass",
    "M_Metal",
    "M_Timber",       # boardwalk, pier, benches, shed
    "M_Foliage",
    "M_Trunk",
    "M_Water",
    "M_Emissive",     # lamp heads. Emissive material, NOT a light - see the note below.
)

# Why lamp posts are emissive and not lights: a walk-in content piece already spawns about a
# dozen shadow-casting point lights, and three slots of content is most of this PC's light
# budget at 1600x900. The environment therefore adds no dynamic lights at all - the sun, the
# sky light and the fog do all of it, and a lamp head is a bright material.
#
# Why the water is not a mirror: M_Water used to be roughness 0.04, i.e. glass. Water that
# reflects the sky looks right at eye level and is wrong everywhere else - a straight-down
# capture of Game B's waterfront came out with a **white sea**, and because the white sea is
# half the frame the histogram exposure then pulled the roofs of every building down to black
# (brief 016). It is also the one specular surface in a kit whose whole look is flat colour.
# At 0.26 / 0.34 it is still glossy enough to read as water from the promenade.

MAX_MATERIAL_SLOTS = 8

# How much of a piece counts as "where it meets the ground" when the anchor is checked.
GROUND_BAND = 0.60

# Triangle budgets per category. The environment is background: it must never cost what the
# content costs (the content's budget is 60,000 a piece).
CATEGORY_BUDGET = {
    "ground": 1500,
    "street": 3000,
    "planting": 4000,
    "building": 14000,
    "water": 500,
}

# ---------------------------------------------------------------------------- the two palettes

PALETTES = {
    "warm": dict(
        name="warm sandstone + terracotta (Game A, the plaza)",
        M_Ground=dict(color="#B9A98C", roughness=0.92),
        M_GroundAlt=dict(color="#9C8763", roughness=0.94),
        M_Grass=dict(color="#6F8F4D", roughness=0.95),
        M_Paving=dict(color="#D9C8A6", roughness=0.78),
        M_PavingAlt=dict(color="#C2AC85", roughness=0.74),
        M_Kerb=dict(color="#A99579", roughness=0.80),
        M_SlotPad=dict(color="#C3B08C", roughness=0.84),
        M_SlotKerb=dict(color="#7E6A4E", roughness=0.78),
        M_Wall=dict(color="#E3D6BE", roughness=0.66),
        M_WallAlt=dict(color="#CDBB9C", roughness=0.68),
        M_Roof=dict(color="#A4573C", roughness=0.70),
        M_Trim=dict(color="#6B5340", roughness=0.52),
        M_Glass=dict(color="#CFE0E4", roughness=0.06, alpha=0.22),
        M_Metal=dict(color="#9C9890", roughness=0.33, metallic=0.85),
        M_Timber=dict(color="#A67E54", roughness=0.74),
        M_Foliage=dict(color="#5E8A47", roughness=0.86),
        M_Trunk=dict(color="#6E5940", roughness=0.84),
        M_Water=dict(color="#6E9BA8", roughness=0.26, alpha=0.70),
        M_Emissive=dict(color="#FFEFD0", roughness=0.40, emissive=5.0),
    ),
    "cool": dict(
        name="slate + timber + blue water (Game B, the waterfront)",
        M_Ground=dict(color="#7E858A", roughness=0.92),
        M_GroundAlt=dict(color="#646C72", roughness=0.94),
        M_Grass=dict(color="#56785F", roughness=0.95),
        M_Paving=dict(color="#9AA3A9", roughness=0.74),
        M_PavingAlt=dict(color="#7D868D", roughness=0.72),
        M_Kerb=dict(color="#69727A", roughness=0.80),
        M_SlotPad=dict(color="#889299", roughness=0.84),
        M_SlotKerb=dict(color="#454D55", roughness=0.78),
        M_Wall=dict(color="#C3CBD1", roughness=0.62),
        M_WallAlt=dict(color="#9BA7B0", roughness=0.64),
        M_Roof=dict(color="#3A454E", roughness=0.66),
        M_Trim=dict(color="#2E3940", roughness=0.48),
        M_Glass=dict(color="#C6D8E2", roughness=0.05, alpha=0.20),
        M_Metal=dict(color="#AEB5BA", roughness=0.28, metallic=0.90),
        M_Timber=dict(color="#8B7355", roughness=0.78),
        M_Foliage=dict(color="#4E7A63", roughness=0.86),
        M_Trunk=dict(color="#5A5247", roughness=0.84),
        M_Water=dict(color="#2E6B8F", roughness=0.34, alpha=0.78),
        M_Emissive=dict(color="#DCEBFF", roughness=0.40, emissive=5.0),
    ),
}

DEFAULT_PALETTE = "warm"


def palette_slots(name):
    """The per-slot spec table for one palette, with every slot present."""
    p = PALETTES[name]
    return {slot: dict(p[slot]) for slot in ENV_MATERIAL_SLOTS}


# ---------------------------------------------------------------------------- materials

def make_env_materials(palette_name=DEFAULT_PALETTE):
    """Blender materials named exactly for the slots, so the FBX carries the slot names."""
    specs = palette_slots(palette_name)
    mats = {}
    for slot in ENV_MATERIAL_SLOTS:
        spec = specs[slot]
        m = bpy.data.materials.new(slot)
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        lin = K.hex_to_linear(spec["color"])
        bsdf.inputs["Base Color"].default_value = (lin[0], lin[1], lin[2], 1.0)
        bsdf.inputs["Roughness"].default_value = float(spec.get("roughness", 0.6))
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
        mats[slot] = m
    return mats, specs


def materials_table(specs, used):
    out = []
    for slot in ENV_MATERIAL_SLOTS:
        if slot not in used:
            continue
        s = specs[slot]
        out.append(dict(
            slot=slot,
            base_color_hex=s["color"].upper(),
            base_color_linear=[round(c, 5) for c in K.hex_to_linear(s["color"])],
            roughness=round(float(s.get("roughness", 0.6)), 3),
            metallic=round(float(s.get("metallic", 0.0)), 3),
            alpha=round(float(s.get("alpha", 1.0)), 3),
            emissive_strength=round(float(s.get("emissive", 0.0)), 3),
        ))
    return out


def all_palette_tables():
    """Every palette's full slot table - the map builder's source of truth for colours."""
    out = {}
    for name in PALETTES:
        specs = palette_slots(name)
        out[name] = dict(
            name=PALETTES[name]["name"],
            slots={slot: dict(
                base_color_hex=specs[slot]["color"].upper(),
                base_color_linear=[round(c, 5) for c in K.hex_to_linear(specs[slot]["color"])],
                roughness=round(float(specs[slot].get("roughness", 0.6)), 3),
                metallic=round(float(specs[slot].get("metallic", 0.0)), 3),
                alpha=round(float(specs[slot].get("alpha", 1.0)), 3),
                emissive_strength=round(float(specs[slot].get("emissive", 0.0)), 3),
            ) for slot in ENV_MATERIAL_SLOTS},
        )
    return out


# ---------------------------------------------------------------------------- the piece

class EnvPiece:
    """One environment mesh: a builder, a category, and the metadata the map needs."""

    def __init__(self, pid, category, *, palette=DEFAULT_PALETTE, bevel=False,
                 collision="blocking", footprint=None, notes=None):
        assert category in CATEGORY_BUDGET, category
        self.id = pid
        self.category = category
        self.palette_name = palette
        self.bevel = bevel
        # "blocking"   the Player cannot walk through it (buildings, benches, railings)
        # "decoration" no collision at all - paving slabs, water, foliage canopies: they sit
        #              on the map's one big ground plane, which is what the Player stands on
        self.collision = collision
        self.footprint = footprint          # (x, y) metres, for the map's spacing maths
        self.notes = list(notes or [])
        self.t0 = time.time()

        self.mats, self.mat_specs = make_env_materials(palette)
        self.b = MeshBuilder()
        self.object = None

    # -- geometry, straight through to the builder --------------------------------------
    def box(self, lo, hi, mat, faces=None):
        self.b.box(lo, hi, mat, faces)

    def quad(self, pts, mat, **kw):
        self.b.quad(pts, mat, **kw)

    def extrude(self, *a, **kw):
        self.b.extrude(*a, **kw)

    def disc(self, *a, **kw):
        self.b.disc(*a, **kw)

    def ring(self, *a, **kw):
        self.b.ring(*a, **kw)

    def revolve(self, *a, **kw):
        self.b.revolve(*a, **kw)

    def cone(self, *a, **kw):
        self.b.cone(*a, **kw)

    def sphere(self, *a, **kw):
        self.b.sphere(*a, **kw)

    # -- small shared shapes -------------------------------------------------------------
    def slab(self, half_x, half_y, z0, z1, mat, *, inset=0.0):
        self.box((-half_x + inset, -half_y + inset, z0), (half_x - inset, half_y - inset, z1), mat)

    def post(self, x, y, z0, z1, r, mat, segs=8):
        self.disc((x, y), r, "xy", z0, z1, mat, segs=segs)

    def plank_deck(self, half_x, half_y, z0, z1, mat, *, planks=8, gap=0.02, along="y"):
        """A deck read as boards: a run of slabs with a reveal between them."""
        if along == "y":
            step = (2 * half_y) / planks
            for i in range(planks):
                y0 = -half_y + i * step + gap * 0.5
                y1 = y0 + step - gap
                self.box((-half_x, y0, z0), (half_x, y1, z1), mat)
        else:
            step = (2 * half_x) / planks
            for i in range(planks):
                x0 = -half_x + i * step + gap * 0.5
                x1 = x0 + step - gap
                self.box((x0, -half_y, z0), (x1, half_y, z1), mat)

    def window_grid(self, *, along, outer, out_sign, a, b, z0, z1, rows, cols,
                    w=1.15, h=1.60, mat="M_Glass", frame="M_Trim"):
        """A rhythm of windows on one face of a background block - two boxes each.

        `along` is 'x' or 'y' (the axis the face runs along), `outer` the face's position on
        the other axis and `out_sign` which way that face looks. A block's wall is a solid
        box, so a window recessed *into* it would be invisible; instead each window is a dark
        reveal box standing a centimetre proud of the face with the glass standing two
        centimetres proud of that. Twenty-four triangles a window, and it reads as a building
        from the far side of a plaza, which is all a background block has to do.
        """
        cw = (b - a) / cols
        rh = (z1 - z0) / rows
        for r in range(rows):
            zc = z0 + rh * (r + 0.5)
            for c in range(cols):
                uc = a + cw * (c + 0.5)
                for (half_w, half_h, d0, d1, m) in (
                        (w / 2 + 0.09, h / 2 + 0.09, -0.13, 0.012, frame),
                        (w / 2, h / 2, -0.11, 0.035, mat)):
                    o0 = outer + out_sign * d0
                    o1 = outer + out_sign * d1
                    lo_o, hi_o = min(o0, o1), max(o0, o1)
                    if along == "x":
                        self.box((uc - half_w, lo_o, zc - half_h),
                                 (uc + half_w, hi_o, zc + half_h), m)
                    else:
                        self.box((lo_o, uc - half_w, zc - half_h),
                                 (hi_o, uc + half_w, zc + half_h), m)

    def canopy_blob(self, center, r, mat, *, segs=9, rings=5, squash=0.82):
        """A faceted leaf mass. Flat shaded and low-poly on purpose - it has to read as part
        of the same architectural-model style as everything else."""
        cx, cy, cz = center
        prof = []
        for i in range(rings + 1):
            t = math.pi * i / rings
            prof.append((r * math.sin(t), cz - r * squash * math.cos(t)))
        self.b.revolve(prof, cx, cy, mat, segs=segs)

    # -- bake ----------------------------------------------------------------------------
    def finish(self):
        name = "SM_ENV_%s" % self.id
        ob = self.b.to_object(name, self.mats)
        if self.bevel:
            K._apply_bevel(ob, width=0.02)
        self.object = ob
        bpy.context.view_layer.update()
        return self._metadata()

    def mesh_objects(self):
        return [self.object]

    def _metadata(self):
        ob = self.object
        tris = 0
        for p in ob.data.polygons:
            tris += max(0, len(p.vertices) - 2)
        used = [m.name for m in ob.data.materials]

        lo = [min(v.co[i] for v in ob.data.vertices) for i in range(3)]
        hi = [max(v.co[i] for v in ob.data.vertices) for i in range(3)]
        lo = [round(v, 4) for v in lo]
        hi = [round(v, 4) for v in hi]
        size = [round(hi[i] - lo[i], 4) for i in range(3)]

        # What the piece covers where it meets the ground. This - not the whole bounding box -
        # is what the map's spacing maths uses and what the anchor convention is about: a lamp
        # post's arm reaches a metre out at four metres up, and that must not make it a
        # badly-anchored piece.
        base = [v.co for v in ob.data.vertices if v.co[2] <= GROUND_BAND]
        if base:
            glo = [round(min(c[i] for c in base), 4) for i in range(2)]
            ghi = [round(max(c[i] for c in base), 4) for i in range(2)]
        else:
            glo, ghi = [lo[0], lo[1]], [hi[0], hi[1]]

        return dict(
            schema_version=SCHEMA_VERSION,
            kind="environment",
            id=self.id,
            category=self.category,
            collision=self.collision,
            units=dict(authoring=AUTHOR_UNITS, fbx=FBX_UNITS, glb=GLB_UNITS,
                       fbx_scale=FBX_UNIT_SCALE, engine="cm", engine_unit_scale=1.0),
            bounds=dict(min=lo, max=hi, size=size),
            bounds_cm=dict(min=[round(c * FBX_UNIT_SCALE, 2) for c in lo],
                           max=[round(c * FBX_UNIT_SCALE, 2) for c in hi],
                           size=[round(c * FBX_UNIT_SCALE, 2) for c in size]),
            footprint=list(self.footprint) if self.footprint else [size[0], size[1]],
            ground_bounds=dict(min=glo, max=ghi,
                               size=[round(ghi[i] - glo[i], 4) for i in range(2)],
                               band=GROUND_BAND),
            triangles=tris,
            triangle_budget=CATEGORY_BUDGET[self.category],
            object_name=ob.name,
            materials=materials_table(self.mat_specs, used),
            material_slots=used,
            material_slot_count=len(used),
            palettes=sorted(PALETTES),
            preview_palette=self.palette_name,
            notes=self.notes,
            build_seconds=None,
        )


# ---------------------------------------------------------------------------- export

def export_env_piece(meta, objects, out_dir):
    """GLB in metres, then FBX in centimetres - exactly the content pipeline's contract."""
    os.makedirs(out_dir, exist_ok=True)
    stem = meta["id"]

    K._select(list(objects))
    glb = os.path.join(out_dir, stem + ".glb")
    bpy.ops.export_scene.gltf(
        filepath=glb, export_format="GLB", use_selection=True,
        export_apply=True, export_cameras=False, export_lights=False,
        export_extras=True, export_yup=True, export_animations=False,
    )

    K._rescale_in_place(list(objects), [], FBX_UNIT_SCALE)
    try:
        K._select(list(objects))
        fbx = os.path.join(out_dir, stem + ".fbx")
        bpy.ops.export_scene.fbx(
            filepath=fbx, use_selection=True, object_types={"MESH"},
            apply_unit_scale=False, global_scale=1.0, apply_scale_options="FBX_SCALE_NONE",
            use_mesh_modifiers=True, mesh_smooth_type="FACE", use_triangles=False,
            bake_space_transform=False, bake_anim=False, path_mode="AUTO",
            embed_textures=False, use_custom_props=True,
        )
    finally:
        K._rescale_in_place(list(objects), [], 1.0 / FBX_UNIT_SCALE)

    return fbx, glb


def write_env_manifest(meta, out_dir, *, piece_script, exports, previews, build_seconds):
    meta = dict(meta)
    meta["exports"] = {k: os.path.relpath(v, _ART).replace("\\", "/") for k, v in exports.items()}
    meta["previews"] = {k: os.path.relpath(v, _ART).replace("\\", "/") for k, v in previews.items()}
    meta["build_seconds"] = round(build_seconds, 2)
    meta["generator"] = dict(
        env_kit_sha256=K.sha256_file(os.path.join(_ENV_DIR, "env_kit.py")),
        piece_script=os.path.relpath(piece_script, _ART).replace("\\", "/"),
        piece_sha256=K.sha256_file(piece_script),
        dc_kit_sha256=K.sha256_file(os.path.join(_BLENDER_DIR, "dc_kit.py")),
        blender=bpy.app.version_string,
        built_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    path = os.path.join(out_dir, "manifest.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=1, sort_keys=False)
        fh.write("\n")
    return path


# ---------------------------------------------------------------------------- previews

def preview_world(palette_name):
    """A neutral three-quarter studio: one sun, a sky, and a ground in the palette's own
    ground colour so a piece is judged against the floor it will stand on."""
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x = 720
    sc.render.resolution_y = 480

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 3.4
    sun_data.angle = math.radians(1.5)
    sun = bpy.data.objects.new("Sun", sun_data)
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(52.0), 0.0, math.radians(135.0))

    world = bpy.data.worlds.new("EnvPreview")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.52, 0.62, 0.74, 1.0)
    bg.inputs[1].default_value = 1.25
    sc.world = world

    specs = palette_slots(palette_name)
    gm = bpy.data.materials.new("PreviewGround")
    gm.use_nodes = True
    lin = K.hex_to_linear(specs["M_Ground"]["color"])
    gm.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = \
        (lin[0], lin[1], lin[2], 1.0)
    bpy.ops.mesh.primitive_plane_add(size=120.0, location=(0.0, 0.0, -0.002))
    bpy.context.active_object.data.materials.append(gm)


def render_preview(meta, out_dir, *, samples=32, suffix=""):
    """One three-quarter shot of the piece, framed on its own bounds."""
    os.makedirs(out_dir, exist_ok=True)
    sc = bpy.context.scene
    try:
        sc.eevee.taa_render_samples = samples
    except Exception:                                   # noqa: BLE001
        pass

    size = meta["bounds"]["size"]
    lo, hi = meta["bounds"]["min"], meta["bounds"]["max"]
    centre = [(lo[i] + hi[i]) / 2.0 for i in range(3)]
    reach = max(max(size[0], size[1]) * 1.9, size[2] * 1.6) + 2.2

    cam_data = bpy.data.cameras.new("PreviewCam")
    cam_data.lens = 40.0
    cam = bpy.data.objects.new("PreviewCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    ang = math.radians(38.0)
    cam.location = (centre[0] + reach * math.cos(ang),
                    centre[1] - reach * math.sin(ang),
                    centre[2] + reach * 0.62)
    direction = (centre[0] - cam.location[0], centre[1] - cam.location[1],
                 centre[2] - cam.location[2])
    cam.rotation_euler = _look_rotation(direction)
    sc.camera = cam

    path = os.path.join(out_dir, "%s%s.png" % (meta["id"], suffix))
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def _look_rotation(direction):
    import mathutils
    v = mathutils.Vector(direction)
    return v.to_track_quat("-Z", "Y").to_euler()
