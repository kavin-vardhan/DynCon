"""Builds the demo's two maps: /Game/Maps/GameA and /Game/Maps/GameB (brief 012).

Run inside the headless editor:

    "E:\\EpicGames\\UE_5.7\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      "E:\\DynamicContents\\unreal\\DCDemo\\DCDemo.uproject" ^
      -run=pythonscript -script="E:\\DynamicContents\\unreal\\Tools\\make_maps.py" ^
      -unattended -nosplash

or through `unreal\\Tools\\make_maps.ps1`, which copies the mannequin in first.

Plan v6 §3 wants **two neutral, untitled maps that clearly read as two different games**. They
are two different *places*, not one place twice: Game A is a warm inland plaza with an avenue
and a walled garden; Game B is a cool waterfront with a promenade, a quay and a pier out over
the water. The difference is carried by layout, by palette and by light, and all three come
from the same 23-piece environment kit, so nothing had to be modelled twice.

Name-agnostic, as CLAUDE.md rule 3 requires: **no text, no signs, no logos, no names** are
placed anywhere in either map. The only lettering the demo ever shows is the status strip,
which the plugin draws.

Everything here is data plus small loops, so a layout change is a number, and the two maps are
reproducible from the repo with no hand editing.

Units: this file talks **metres** (the art is authored in metres) and multiplies by 100 on the
way into the engine, which is what `m()` and `v()` are for.
"""

import json
import math
import os
import sys

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import env_import as EI      # noqa: E402

REPO = r"E:\DynamicContents"
REPORT_PATH = os.path.join(REPO, "unreal", "_build", "logs", "maps.json")

MAP_A = "/Game/Maps/GameA"
MAP_B = "/Game/Maps/GameB"

CM = 100.0
LOG = EI.LOG
log, warn, fail = EI.log, EI.warn, EI.fail
load_asset, safe_set = EI.load_asset, EI.safe_set


def m(v):
    return float(v) * CM


def v3(x, y, z=0.0):
    return unreal.Vector(m(x), m(y), m(z))


def yaw(deg):
    return unreal.Rotator(roll=0.0, pitch=0.0, yaw=float(deg))


# ======================================================================= the builder

class MapBuilder:
    """One map: the actors, the light, the bounds and the slots."""

    def __init__(self, path, palette, meshes, manifests, palette_materials):
        self.path = path
        self.palette = palette
        self.meshes = meshes
        self.manifests = manifests
        self.palette_materials = palette_materials
        self.actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        self.level_sub = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        self.counts = {}
        self.slots = []
        self.extent = [1e9, 1e9, -1e9, -1e9]      # min x, min y, max x, max y, metres

    # ---------------------------------------------------------------- scene lifecycle
    def new_level(self):
        if unreal.EditorAssetLibrary.does_asset_exist(self.path):
            log("%s exists - reloading it and clearing it out" % self.path)
            self.level_sub.load_level(self.path)
            for actor in self.actor_sub.get_all_level_actors():
                self.actor_sub.destroy_actor(actor)
        else:
            log("creating %s" % self.path)
            self.level_sub.new_level(self.path)

    def save(self):
        self.level_sub.save_current_level()

    def note(self, kind):
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def grow(self, x, y):
        self.extent[0] = min(self.extent[0], x)
        self.extent[1] = min(self.extent[1], y)
        self.extent[2] = max(self.extent[2], x)
        self.extent[3] = max(self.extent[3], y)

    # ---------------------------------------------------------------- environment pieces
    def dress(self, comp, piece):
        """Put this map's palette on an actor, slot by slot, in the mesh's own slot order."""
        slots = list(self.manifests[piece].get("material_slots", []))
        table = self.palette_materials.get(self.palette, {})
        for index, slot in enumerate(slots):
            mi = table.get(slot)
            if mi is not None:
                comp.set_material(index, mi)

    def place(self, piece, x, y, z=0.0, rot=0.0, scale=1.0, label=None):
        mesh = self.meshes.get(piece)
        if mesh is None:
            fail("no mesh for environment piece %r" % piece)
            return None
        actor = self.actor_sub.spawn_actor_from_class(unreal.StaticMeshActor, v3(x, y, z),
                                                      yaw(rot))
        actor.set_actor_label(label or ("%s_%d" % (piece, self.counts.get(piece, 0))))
        comp = actor.static_mesh_component
        comp.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        comp.set_static_mesh(mesh)
        self.dress(comp, piece)
        if self.manifests[piece].get("collision") == "decoration":
            comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        if isinstance(scale, (list, tuple)):
            actor.set_actor_scale3d(unreal.Vector(*scale))
        elif abs(scale - 1.0) > 1e-6:
            actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
        self.note(piece)
        self.grow(x, y)
        return actor

    def field(self, piece, x0, y0, nx, ny, step, z=0.0, rot=0.0, skip=None):
        """A grid of the same piece - how a plaza or a promenade is paved."""
        skip = skip or (lambda cx, cy: False)
        for ix in range(nx):
            for iy in range(ny):
                cx = x0 + ix * step
                cy = y0 + iy * step
                if skip(cx, cy):
                    continue
                self.place(piece, cx, cy, z=z, rot=rot)

    def run(self, piece, x0, y0, dx, dy, n, z=0.0, rot=0.0):
        """A line of the same piece - kerbs, railings, a row of trees."""
        for i in range(n):
            self.place(piece, x0 + dx * i, y0 + dy * i, z=z, rot=rot)

    # ---------------------------------------------------------------- the big flat things
    def ground(self, cx, cy, size_x, size_y, piece_slot="M_Ground"):
        """One big ground plane with the palette's ground colour. The Player stands on this;
        the paving sits on top of it."""
        cube = load_asset("/Engine/BasicShapes/Cube")
        actor = self.actor_sub.spawn_actor_from_class(unreal.StaticMeshActor,
                                                      v3(cx, cy, -0.25))
        actor.set_actor_label("Ground")
        comp = actor.static_mesh_component
        comp.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        comp.set_static_mesh(cube)
        actor.set_actor_scale3d(unreal.Vector(size_x, size_y, 0.5))
        mi = self.palette_materials.get(self.palette, {}).get(piece_slot)
        if mi is not None:
            comp.set_material(0, mi)
        self.note("ground")
        return actor

    def ground_patch(self, cx, cy, size_x, size_y, piece_slot, top=0.01, label=None):
        """A second ground tone laid on top of the big plane.

        Two of them in Game A: the apron the paving is laid in (so the plaza's edge reads
        against something other than itself), and the grass in the garden court. `top` is
        where the patch's surface sits in metres, which is how a patch slides under the
        paving (top 0.13 against the paving's 0.14) instead of z-fighting with it.
        """
        cube = load_asset("/Engine/BasicShapes/Cube")
        actor = self.actor_sub.spawn_actor_from_class(unreal.StaticMeshActor,
                                                      v3(cx, cy, top - 0.25))
        actor.set_actor_label(label or ("Ground_%s" % piece_slot))
        comp = actor.static_mesh_component
        comp.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        comp.set_static_mesh(cube)
        actor.set_actor_scale3d(unreal.Vector(size_x, size_y, 0.5))
        mi = self.palette_materials.get(self.palette, {}).get(piece_slot)
        if mi is not None:
            comp.set_material(0, mi)
        # Deliberately not grown into `extent`: a ground tone is not a built thing, and the
        # report's extent is the size of the place, not of the paint under it.
        self.note("ground_patch")
        return actor

    def water(self, cx, cy, size_x, size_y, z):
        plane = load_asset("/Engine/BasicShapes/Plane")
        actor = self.actor_sub.spawn_actor_from_class(unreal.StaticMeshActor, v3(cx, cy, z))
        actor.set_actor_label("Water")
        comp = actor.static_mesh_component
        comp.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        comp.set_static_mesh(plane)
        actor.set_actor_scale3d(unreal.Vector(size_x, size_y, 1.0))
        comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        mi = self.palette_materials.get(self.palette, {}).get("M_Water")
        if mi is not None:
            comp.set_material(0, mi)
        self.note("water")
        return actor

    def bound(self, x0, y0, x1, y1, height=8.0, label="Bound"):
        """An invisible wall. The Player cannot leave the map and cannot fall off the pier.

        Every one of these carries the actor tag **DCPlayableArea**, which is how the
        slot-map tool knows what to photograph: the union of the walls round the part of the
        level the Player can reach *is* the playable area, and one tag is a better answer
        than a tool guessing from actor sizes.
        """
        cube = load_asset("/Engine/BasicShapes/Cube")
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        sx, sy = max(abs(x1 - x0), 0.4), max(abs(y1 - y0), 0.4)
        actor = self.actor_sub.spawn_actor_from_class(unreal.StaticMeshActor,
                                                      v3(cx, cy, height / 2.0))
        actor.set_actor_label(label)
        comp = actor.static_mesh_component
        comp.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        comp.set_static_mesh(cube)
        actor.set_actor_scale3d(unreal.Vector(sx, sy, height))
        safe_set(comp, "hidden_in_game", True)
        safe_set(comp, "cast_shadow", False)
        comp.set_collision_profile_name("BlockAll")
        safe_set(actor, "tags", [unreal.Name("DCPlayableArea")])
        self.note("bound")
        return actor

    def ring_bounds(self, x0, y0, x1, y1, height=8.0, t=1.0, sides="WENS"):
        """The wall round the playable area. `sides` leaves one out where the map has its
        own edge - Game B's water side is the quay, and a ring wall across it would also wall
        off the pier."""
        if "W" in sides:
            self.bound(x0 - t, y0 - t, x0, y1 + t, height, "Bound_W")
        if "E" in sides:
            self.bound(x1, y0 - t, x1 + t, y1 + t, height, "Bound_E")
        if "S" in sides:
            self.bound(x0 - t, y0 - t, x1 + t, y0, height, "Bound_S")
        if "N" in sides:
            self.bound(x0 - t, y1, x1 + t, y1 + t, height, "Bound_N")

    # ---------------------------------------------------------------- light
    def sky(self, *, sun_pitch, sun_yaw, sun_intensity, sun_temperature,
            sky_intensity, sky_tint, fog_density, fog_colour, fog_falloff,
            ground_albedo):
        sun = self.actor_sub.spawn_actor_from_class(
            unreal.DirectionalLight, v3(0, 0, 30),
            unreal.Rotator(roll=0.0, pitch=sun_pitch, yaw=sun_yaw))
        sun.set_actor_label("Sun")
        lc = sun.light_component
        safe_set(lc, "mobility", unreal.ComponentMobility.MOVABLE)
        safe_set(lc, "intensity", sun_intensity)
        safe_set(lc, "use_temperature", True)
        safe_set(lc, "temperature", sun_temperature)
        safe_set(lc, "atmosphere_sun_light", True)
        safe_set(lc, "dynamic_shadow_distance_movable_light", m(180.0))
        self.note("sun")

        sky = self.actor_sub.spawn_actor_from_class(unreal.SkyLight, v3(0, 0, 20))
        sky.set_actor_label("SkyLight")
        sc = sky.light_component
        safe_set(sc, "mobility", unreal.ComponentMobility.MOVABLE)
        safe_set(sc, "real_time_capture", True)
        safe_set(sc, "intensity", sky_intensity)
        safe_set(sc, "light_color", unreal.Color(*sky_tint))
        self.note("skylight")

        atmo = self.actor_sub.spawn_actor_from_class(unreal.SkyAtmosphere, v3(0, 0, 0))
        atmo.set_actor_label("SkyAtmosphere")
        # The ground albedo is why there is no black band at the horizon: the atmosphere
        # renders the planet under the horizon line, and its default albedo is almost black.
        comp = None
        for name in ("sky_atmosphere_component", "component"):
            try:
                comp = atmo.get_editor_property(name)
                break
            except Exception:                                   # noqa: BLE001
                continue
        if comp is not None:
            safe_set(comp, "ground_albedo", unreal.Color(*ground_albedo))
        self.note("skyatmosphere")

        fog = self.actor_sub.spawn_actor_from_class(unreal.ExponentialHeightFog, v3(0, 0, 0))
        fog.set_actor_label("HeightFog")
        fcomp = None
        for name in ("component", "exponential_height_fog_component"):
            try:
                fcomp = fog.get_editor_property(name)
                break
            except Exception:                                   # noqa: BLE001
                continue
        if fcomp is not None:
            safe_set(fcomp, "fog_density", fog_density)
            safe_set(fcomp, "fog_height_falloff", fog_falloff)
            safe_set(fcomp, "fog_inscattering_luminance", unreal.LinearColor(*fog_colour))
            safe_set(fcomp, "start_distance", m(8.0))
            safe_set(fcomp, "volumetric_fog", False)        # too expensive for the booth PC
        self.note("fog")

    # ---------------------------------------------------------------- slots and the Player
    def slot(self, slot_id, size_class, x, y, z, facing_deg, fill_order,
             view_distance, view_height, pad="slot_pad", pad_z=None, approach=(),
             rating_rule="all"):
        """One ADCSlot, standing on its own pad.

        `facing_deg` is the compass direction the content's door looks: ADCSlot adds a -90
        yaw offset when it spawns content (the art is authored facing -Y in Blender and
        arrives facing +Y), so the slot actor's +X *is* the door direction and the actor's yaw
        is the facing straight off.

        `pad` is a kit piece used at scale 1.0 - `slot_pad` (14 m) for an L or a T slot and
        `slot_pad_s` (7 m) for an S slot. It used to be the 14 m pad scaled to 0.5, which
        also halved the width of its kerb band and made the S slot's pad read as a model of
        a pad rather than as one.

        `rating_rule` is the developer's rule for what may appear here, and it is set on the
        actor rather than looked up anywhere: the slot-map tool reads it off the map and
        hands it to the platform with the rest of the slot (demo plan v6 §6).
        """
        self.place(pad, x, y, z=(pad_z if pad_z is not None else z - 0.17),
                   label="Pad_%s" % slot_id)
        actor = self.actor_sub.spawn_actor_from_class(unreal.DCSlot, v3(x, y, z),
                                                      yaw(facing_deg))
        actor.set_actor_label(slot_id)
        safe_set(actor, "slot_id", slot_id)
        safe_set(actor, "size_class", size_class)
        safe_set(actor, "fill_order", fill_order)
        safe_set(actor, "view_distance", view_distance)
        safe_set(actor, "view_height", view_height)
        safe_set(actor, "content_yaw_offset", -90.0)
        safe_set(actor, "rating_rule", unreal.Name(rating_rule))
        # The way in, as waypoints rather than a navigation mesh: these maps are written by a
        # script, so the route round the arcades and down the avenue is known here.
        safe_set(actor, "approach_path", [v3(px, py, 0.0) for (px, py) in approach])
        self.note("slot")
        self.slots.append(dict(id=slot_id, size_class=str(size_class).split(".")[-1],
                               location_m=[x, y, z], facing_deg=facing_deg,
                               pad=pad, rating_rule=rating_rule,
                               approach=[list(p) for p in approach]))
        return actor

    def player_start(self, x, y, z, facing_deg):
        start = self.actor_sub.spawn_actor_from_class(unreal.PlayerStart, v3(x, y, z),
                                                      yaw(facing_deg))
        start.set_actor_label("PlayerStart")
        self.note("playerstart")
        return start

    def set_game_mode(self):
        try:
            game_mode = unreal.DCRuntimeGameMode
        except AttributeError:
            warn("ADCRuntimeGameMode is not in this editor build")
            return "class-missing"
        candidates = []
        try:
            world = unreal.EditorLevelLibrary.get_editor_world()
            candidates.append(unreal.GameplayStatics.get_actor_of_class(world,
                                                                        unreal.WorldSettings))
        except Exception as exc:                                # noqa: BLE001
            warn("GameplayStatics.get_actor_of_class: %s" % exc)
        try:
            for actor in self.actor_sub.get_all_level_actors():
                if isinstance(actor, unreal.WorldSettings):
                    candidates.append(actor)
        except Exception as exc:                                # noqa: BLE001
            warn("scan for WorldSettings: %s" % exc)
        for settings in candidates:
            if settings is None:
                continue
            if safe_set(settings, "default_game_mode", game_mode):
                return "set"
        warn("could not reach World Settings for %s" % self.path)
        return "not-set"


# ======================================================================= Game A - the plaza

def build_game_a(meshes, manifests, pal_mats):
    """Warm sandstone plaza, an avenue east to the tall slot, a walled garden north-west."""
    B = MapBuilder(MAP_A, "warm", meshes, manifests, pal_mats)
    B.new_level()

    B.ground(10, 4, 600.0, 600.0)
    # Two more ground tones, so the plaza's edge reads against something other than itself:
    # an apron of compacted earth under the whole built-up area, and grass in the garden
    # court. The grass surfaces 1 cm under the paving's 0.14 m, so the slabs stand a hair
    # proud of it instead of fighting it for the same pixels.
    B.ground_patch(15, 6, 202.0, 132.0, "M_GroundAlt", top=0.01, label="Ground_Apron")
    B.ground_patch(-54, 39.5, 48.0, 37.0, "M_Grass", top=0.13, label="Ground_Garden")
    # Warm midday with a light haze. The fog is deliberately thin: it is there to stop the
    # ground meeting the sky in a hard line, not to be weather.
    B.sky(sun_pitch=-54.0, sun_yaw=145.0, sun_intensity=6.0, sun_temperature=5900.0,
          sky_intensity=1.05, sky_tint=(205, 218, 235, 255),
          fog_density=0.0022, fog_colour=(0.30, 0.28, 0.24, 1.0), fog_falloff=0.22,
          ground_albedo=(150, 136, 112, 255))

    # ---- the plaza: 64 x 64 m of paving, 8 m slabs
    B.field("paving_tile", -28, -28, 8, 8, 8.0)
    # the raised terrace in front of A1, and the flight up onto it
    for ix in range(4):
        for iy in range(2):
            B.place("paving_tile", -12 + ix * 8, 8 + iy * 8, z=0.51)
    B.run("steps", -14, 3.25, 4.0, 0.0, 8)
    for ix in range(4):                       # the terrace edge, east and west
        B.place("paving_edge", -16.3, 8 + ix * 4 - 2, z=0.51, rot=90.0)
        B.place("paving_edge", 16.3, 8 + ix * 4 - 2, z=0.51, rot=-90.0)
    B.run("paving_edge", -14, 20.3, 4.0, 0.0, 8, z=0.51, rot=180.0)

    # ---- the avenue east, 24 m wide, to the tall slot
    B.field("paving_tile", 36, -8, 8, 3, 8.0)
    B.run("kerb", 34, -12.2, 4.0, 0.0, 16)
    B.run("kerb", 34, 12.2, 4.0, 0.0, 16)

    # ---- the garden: a path west from the plaza (x -64 .. -32, so it meets both), then a court
    B.field("paving_tile", -60, 24, 4, 1, 8.0)
    B.field("paving_tile", -60, 32, 3, 3, 8.0)

    # ---- the arcades that frame the plaza
    B.place("arcade", -34.5, -8.3, rot=90.0)
    B.place("arcade", -34.5, 8.3, rot=90.0)
    B.place("arcade", 34.5, -20.0, rot=-90.0)
    B.place("arcade", 34.5, 20.0, rot=-90.0)

    # ---- background blocks. Four tones of the same kit, varied by yaw, so a row of them
    #      never reads as one repeated object.
    for (piece, x, y, r) in (
            ("block_low", -22, 46, 0), ("block_mid", 2, 49, 0), ("block_low", 26, 46, 0),
            # Nothing between y = 10 and y = 28 on the west side: that strip is the garden
            # path, and a block across it is a Player walking into a wall.
            ("block_mid", -48, -16, 90), ("block_low", -48, 2, 90), ("block_low", -70, 18, 90),
            ("block_low", 46, 28, 0), ("block_mid", 66, 30, 0), ("block_tall", 90, 30, 0),
            ("block_low", 46, -28, 0), ("block_mid", 68, -30, 0), ("block_low", 90, -28, 0),
            ("block_low", -24, -48, 0), ("block_mid", 2, -50, 0), ("block_low", 28, -48, 0),
            ("block_mid", -52, -38, 90),
            ("block_low", -76, 36, 90), ("block_low", -56, 60, 0), ("block_low", -32, 44, 0),
            ("block_tall", 104, 12, 0), ("block_tall", 104, -12, 0)):
        B.place(piece, x, y, rot=r)

    # ---- planting
    # Nothing stands on x = +-30: that is the lane the walk to the garden uses, and a tree or
    # a bench in it is a Player wedged against a bench for the rest of the tour.
    for (x, y) in ((-24, -24), (24, -24), (-24, 24), (24, 24), (-26, -7), (26, 7)):
        B.place("tree_round", x, y, z=0.14)
    for i in range(7):                        # the avenue, both sides
        B.place("tree_tall", 40 + i * 8, -11.0, z=0.14)
        B.place("tree_tall", 40 + i * 8, 11.0, z=0.14)
    for (x, y) in ((-62, 30), (-46, 30), (-62, 48), (-46, 48), (-54, 54),
                   (-68, 40), (-40, 40)):
        B.place("tree_round", x, y, z=0.14)
    for (x, y) in ((-58, 36), (-50, 36), (-58, 44), (-50, 44),
                   (-18, -18), (18, -18), (-18, 18), (18, 18)):
        B.place("shrub", x, y, z=0.14)

    # ---- street furniture
    for i in range(5):                        # the avenue
        B.place("lamp_post", 44 + i * 10, -13.6, z=0.14, rot=0.0)
        B.place("lamp_post", 44 + i * 10, 13.6, z=0.14, rot=180.0)
    for (x, y, r) in ((-30.6, -30.6, 45), (30.6, -30.6, 135), (-30.6, 30.6, -45),
                      (30.6, 30.6, -135), (0, -31.2, 90), (-31.4, 0, 0), (31.4, 0, 180)):
        B.place("lamp_post", x, y, z=0.14, rot=r)
    for (x, y, r) in ((-20, -29, 90), (20, -29, 90), (-26.5, -14, 0), (-26.5, 14, 0),
                      (26.5, -14, 180), (26.5, 14, 180), (-10, 21.4, -90), (10, 21.4, -90)):
        B.place("bench", x, y, z=0.14, rot=r)
    for (x, y, r) in ((-56, 29, 90), (-48, 29, 90), (-56, 51, -90), (-48, 51, -90)):
        B.place("bench", x, y, z=0.14, rot=r)
    for i in range(9):
        B.place("bollard", -24 + i * 6, -31.4, z=0.14)
    for (x, y) in ((-8, 2.6), (8, 2.6), (-20, 6), (20, 6), (-62, 26), (-44, 26)):
        B.place("planter", x, y, z=0.14)
    B.place("fountain", 18, -14, z=0.14)
    for i in range(6):                        # the garden court's north edge
        B.place("railing", -62 + i * 4, 55.0, z=0.14)

    # ---- the slots
    B.slot("A1", unreal.DCSizeClass.L, 0.0, 12.0, 0.82, -90.0, 0, 2700.0, 650.0,
           pad="slot_pad", pad_z=0.65,
           approach=())                       # straight across the plaza from the spawn
    B.slot("A2", unreal.DCSizeClass.T, 84.0, 0.0, 0.31, 180.0, 1, 4200.0, 1100.0,
           pad="slot_pad", pad_z=0.14,
           approach=((0.0, -4.0), (30.0, -2.0), (56.0, 0.0)))     # out of the plaza, east
    B.slot("A3", unreal.DCSizeClass.S, -52.0, 40.0, 0.31, -90.0, 2, 1500.0, 380.0,
           pad="slot_pad_s", pad_z=0.14,
           approach=((50.0, 0.0), (20.0, -4.0), (-10.0, -4.0), (-30.0, -4.0),
                     (-30.0, 24.0), (-50.0, 24.0), (-52.0, 30.0)))  # back west, into the garden

    B.player_start(0.0, -22.0, 1.2, 90.0)
    B.ring_bounds(-82, -56, 112, 68, height=14.0)
    mode = B.set_game_mode()
    B.save()
    return B, mode


# ======================================================================= Game B - waterfront

def build_game_b(meshes, manifests, pal_mats):
    """Cool slate and timber: a promenade along the water and a pier out into it."""
    B = MapBuilder(MAP_B, "cool", meshes, manifests, pal_mats)
    B.new_level()

    # Land only north of the quay line; everything south of it is water.
    B.ground(0, 102, 600.0, 216.0)
    B.water(0, -120, 800.0, 240.0, -1.6)
    # Late afternoon, low sun, a little more haze than the plaza - it is over water.
    B.sky(sun_pitch=-21.0, sun_yaw=-128.0, sun_intensity=4.2, sun_temperature=4900.0,
          sky_intensity=1.25, sky_tint=(196, 212, 236, 255),
          fog_density=0.0040, fog_colour=(0.22, 0.27, 0.34, 1.0), fog_falloff=0.26,
          ground_albedo=(118, 126, 134, 255))

    # ---- the quay edge, with a gap where the pier runs out
    for i in range(19):
        x = -36 + i * 4
        if 10.0 <= x <= 22.0:
            continue
        B.place("quay_wall", x, -5.7, z=-2.30)

    # ---- the promenade: timber along the water, slate paving behind it
    B.field("boardwalk", -34, -4, 18, 2, 4.0)
    B.field("paving_tile", -36, 6, 10, 2, 8.0)

    # ---- the pier
    for y in (-9.0, -15.0, -21.0):
        B.place("pier_deck", 16.0, y, rot=90.0)
    for x in (12.0, 16.0, 20.0):
        for y in (-27.0, -33.0):
            B.place("pier_deck", x, y, rot=90.0)
    for y in (-8.0, -14.0, -20.0, -26.0, -32.0, -35.0):
        for x in (12.2, 19.8):
            B.place("pier_post", x, y, z=-3.05)
    for x in (10.4, 21.6):
        for y in (-28.0, -34.0):
            B.place("pier_post", x, y, z=-3.05)
    for i in range(5):                          # railings down both sides of the pier walk
        B.place("railing", 13.6, -7.0 - i * 4.0, z=0.17, rot=90.0)
        B.place("railing", 18.4, -7.0 - i * 4.0, z=0.17, rot=90.0)
    for i in range(3):                          # and round the pier head
        B.place("railing", 11.0 + i * 4.0, -36.3, z=0.17)

    # ---- sheds and background blocks
    B.place("shed", -28.0, 2.0, z=0.15, rot=0.0)
    B.place("shed", 30.0, 0.0, z=0.15, rot=180.0)
    for (piece, x, y, r) in (
            ("block_low", -32, 26, 0), ("block_mid", -8, 28, 0), ("block_low", 14, 26, 0),
            ("block_mid", 36, 28, 0), ("block_low", -52, 20, 90), ("block_low", 54, 20, -90),
            ("block_mid", 16, 44, 0), ("block_low", -20, 44, 0)):
        B.place(piece, x, y, rot=r)

    # ---- planting, lamps, benches, bollards
    for (x, y) in ((-38, 14), (-2, 16), (26, 14), (42, 12)):
        B.place("tree_round", x, y, z=0.14)
    for (x, y) in ((-24, 17), (6, 17), (34, 17)):
        B.place("tree_tall", x, y, z=0.14)
    for i in range(7):
        B.place("lamp_post", -30 + i * 11, 3.0, z=0.15, rot=180.0)
    for (x, y, r) in ((-20, 3.4, 180), (-6, 3.4, 180), (24, 3.4, 180), (38, 3.4, 180)):
        B.place("bench", x, y, z=0.15, rot=r)
    for i in range(16):
        x = -34 + i * 4.6
        if 9.0 <= x <= 23.0:
            continue
        B.place("bollard", x, -5.0, z=0.15)
    for (x, y) in ((-16, 5.4), (0, 5.4), (20, 5.4), (40, 5.4)):
        B.place("planter", x, y, z=0.15)
    for i in range(4):
        B.place("shrub", -40 + i * 2.5, 8.0, z=0.14)

    # ---- the slots
    B.slot("B1", unreal.DCSizeClass.L, -12.0, 12.0, 0.31, -90.0, 0, 2700.0, 650.0,
           pad="slot_pad", pad_z=0.14,
           approach=((-26.0, 6.0), (-16.0, 4.0)))           # along the promenade
    B.slot("B2", unreal.DCSizeClass.S, 16.0, -30.0, 0.34, 90.0, 1, 1500.0, 380.0,
           pad="slot_pad_s", pad_z=0.17,
           approach=((-8.0, -1.0), (6.0, -2.0), (16.0, -3.0), (16.0, -14.0)))  # out on the pier

    B.player_start(-30.0, 8.0, 1.2, 10.0)

    # ---- bounds. The quay wall's top is flush with the promenade, so it is the invisible
    #      wall that stops a Player walking off the edge into the water - and the pier's
    #      railings are backed by one each side.
    B.ring_bounds(-46, -4.0, 46, 36, height=14.0, sides="WEN")
    B.bound(-47, -6.4, 9.8, -5.4, 3.0, "Bound_Quay_W")
    B.bound(22.2, -6.4, 47, -5.4, 3.0, "Bound_Quay_E")
    B.bound(9.4, -37.0, 10.0, -5.4, 3.0, "Bound_Pier_W")
    B.bound(22.0, -37.0, 22.6, -5.4, 3.0, "Bound_Pier_E")
    B.bound(9.4, -37.2, 22.6, -36.6, 3.0, "Bound_Pier_S")

    mode = B.set_game_mode()
    B.save()
    return B, mode


# ======================================================================= main

def main():
    report = {"log": LOG}

    manifests = EI.load_env_manifests()
    if not manifests:
        fail("no environment kit - nothing to build")
        return
    palettes = EI.load_palettes()

    reimport = "--reimport" in sys.argv
    pal_mats = EI.make_palette_materials(palettes)
    meshes, mesh_report = EI.import_env_meshes(manifests, pal_mats, reimport=reimport)
    report["environment"] = mesh_report

    char_mats = EI.make_character_materials()
    skeletal, slots = EI.dress_mannequin(char_mats)
    report["player"] = dict(mannequin_slots=slots,
                            blueprints=EI.make_player_blueprints(skeletal))
    report["player"]["readback"] = EI.readback_player()

    for name, builder in (("GameA", build_game_a), ("GameB", build_game_b)):
        B, mode = builder(meshes, manifests, pal_mats)
        report[name] = dict(
            path=B.path, palette=B.palette, game_mode=mode,
            actors=sum(B.counts.values()), counts=B.counts, slots=B.slots,
            extent_m=dict(x=[round(B.extent[0], 1), round(B.extent[2], 1)],
                          y=[round(B.extent[1], 1), round(B.extent[3], 1)],
                          size=[round(B.extent[2] - B.extent[0], 1),
                                round(B.extent[3] - B.extent[1], 1)]),
        )
        log("%s: %d actors, slots %s, game mode %s"
            % (name, report[name]["actors"],
               ",".join(s["id"] for s in B.slots), mode))

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=1)
        fh.write("\n")
    log("wrote %s" % REPORT_PATH)


main()
