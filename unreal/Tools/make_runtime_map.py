"""Builds /Game/Maps/DCRuntime - the test map the runtime client runs in (brief 011).

Run inside the headless editor:

    "<engine>\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      "unreal\\DCDemo\\DCDemo.uproject" ^
      -run=pythonscript -script="<full path to unreal\\Tools\\make_runtime_map.py>" ^
      -unattended -nosplash

Three slots with the demo's own names and size classes - A1 (L), A2 (T), A3 (S) - on the same
flat ground and under the same light as the spike map, far enough apart that a camera lined up
on one never catches another. Nothing else: the real Game A and Game B maps are plan v6 §10
item 1 and come later.

The spike map /Game/Maps/Spike is left exactly as it is, so unreal\\Tools\\run_all_packs.ps1
still works. This map asks for ADCRuntimeGameMode in its World Settings; the runner also
passes ?game=/Script/DynamicContents.DCRuntimeGameMode on the command line, so the run is
right either way.
"""
import json
import os

import unreal

# The root of this copy of the tree, from this file's own location: unreal/Tools/.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE_MATERIALS = "/Game/DCCore/Materials"
DEFAULT_MASTER = "M_DC_Master"
MAP_PATH = "/Game/Maps/DCRuntime"
REPORT_PATH = os.path.join(REPO, "unreal", "_build", "logs", "runtime_map.json")

MEL = unreal.MaterialEditingLibrary
LOG = []


def log(msg):
    line = "[make_runtime_map] %s" % msg
    LOG.append(line)
    unreal.log(line)


def warn(msg):
    line = "[make_runtime_map] WARNING %s" % msg
    LOG.append(line)
    unreal.log_warning(line)


def load_asset(path):
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    return None


def safe_set(obj, name, value):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:                                   # property names drift
        warn("could not set %s.%s: %s" % (type(obj).__name__, name, exc))
        return False


def asset_tools():
    return unreal.AssetToolsHelpers.get_asset_tools()


# The three slots of Game A, by the names the server's config uses.
SLOTS = [
    {"id": "A1", "class": unreal.DCSizeClass.L, "loc": unreal.Vector(0, 0, 0),
     "order": 0, "view": 2700.0, "height": 650.0},
    {"id": "A2", "class": unreal.DCSizeClass.T, "loc": unreal.Vector(0, 3600, 0),
     "order": 1, "view": 4200.0, "height": 1100.0},
    {"id": "A3", "class": unreal.DCSizeClass.S, "loc": unreal.Vector(0, -3000, 0),
     "order": 2, "view": 1500.0, "height": 380.0},
]


def ground_material():
    existing = load_asset("%s/MI_DC_Ground" % CORE_MATERIALS)
    if existing is not None:
        return existing
    master = load_asset("%s/%s" % (CORE_MATERIALS, DEFAULT_MASTER))
    if master is None:
        warn("no %s - the ground keeps the engine default material" % DEFAULT_MASTER)
        return None
    made = asset_tools().create_asset(
        "MI_DC_Ground", CORE_MATERIALS, unreal.MaterialInstanceConstant,
        unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(made, master)
    MEL.set_material_instance_vector_parameter_value(
        made, "BaseColor", unreal.LinearColor(0.20, 0.21, 0.22, 1.0))
    MEL.set_material_instance_scalar_parameter_value(made, "Roughness", 0.85)
    unreal.EditorAssetLibrary.save_loaded_asset(made)
    return made


def set_default_game_mode(level_sub):
    """World Settings -> GameMode Override = ADCRuntimeGameMode.

    Tried three ways because which of them exists has moved between engine versions, and the
    command line carries the same answer anyway. Whatever happens is reported.
    """
    try:
        game_mode = unreal.DCRuntimeGameMode
    except AttributeError:
        warn("ADCRuntimeGameMode is not in this editor build - rebuild the editor target")
        return "class-missing"

    candidates = []
    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        candidates.append(unreal.GameplayStatics.get_actor_of_class(world, unreal.WorldSettings))
    except Exception as exc:
        warn("GameplayStatics.get_actor_of_class: %s" % exc)
    try:
        actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        for actor in actor_sub.get_all_level_actors():
            if isinstance(actor, unreal.WorldSettings):
                candidates.append(actor)
    except Exception as exc:
        warn("scan for WorldSettings: %s" % exc)

    for settings in candidates:
        if settings is None:
            continue
        if safe_set(settings, "default_game_mode", game_mode):
            log("World Settings GameMode Override = DCRuntimeGameMode")
            return "set"
    warn("could not reach World Settings; the runner's ?game= option is what will decide")
    return "not-set"


def main():
    report = {"map": MAP_PATH, "actors": [], "slots": []}

    level_sub = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    if unreal.EditorAssetLibrary.does_asset_exist(MAP_PATH):
        log("%s exists - reloading it and clearing it out" % MAP_PATH)
        level_sub.load_level(MAP_PATH)
        for actor in actor_sub.get_all_level_actors():
            actor_sub.destroy_actor(actor)
    else:
        log("creating %s" % MAP_PATH)
        level_sub.new_level(MAP_PATH)

    made = []

    # Ground: a big flat engine cube wearing one of our own material instances. 200 m square,
    # which covers the tall slot's stand-off as well as the three slots themselves.
    cube = load_asset("/Engine/BasicShapes/Cube")
    ground = actor_sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, -25))
    ground.set_actor_label("Ground")
    ground.set_actor_scale3d(unreal.Vector(200.0, 200.0, 0.25))
    ground.static_mesh_component.set_static_mesh(cube)
    mi = ground_material()
    if mi is not None:
        ground.static_mesh_component.set_material(0, mi)
    made.append("Ground")

    # Lighting: movable sun + real-time captured sky, so nothing needs baking. Mid-afternoon,
    # over the viewer's shoulder: the viewer stands off along a slot's +X, so yaw 150 puts the
    # sun in front of them rather than behind the content. (unreal.Rotator is positionally
    # (roll, pitch, yaw) - keywords, always.)
    sun = actor_sub.spawn_actor_from_class(
        unreal.DirectionalLight, unreal.Vector(0, 0, 2000),
        unreal.Rotator(roll=0.0, pitch=-48.0, yaw=150.0))
    sun.set_actor_label("Sun")
    safe_set(sun.light_component, "mobility", unreal.ComponentMobility.MOVABLE)
    safe_set(sun.light_component, "intensity", 5.0)
    safe_set(sun.light_component, "atmosphere_sun_light", True)
    made.append("Sun")

    sky = actor_sub.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 1200))
    sky.set_actor_label("SkyLight")
    safe_set(sky.light_component, "mobility", unreal.ComponentMobility.MOVABLE)
    safe_set(sky.light_component, "real_time_capture", True)
    safe_set(sky.light_component, "intensity", 1.0)
    made.append("SkyLight")

    atmosphere = actor_sub.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
    atmosphere.set_actor_label("SkyAtmosphere")
    made.append("SkyAtmosphere")

    # The Player starts on the approach side, facing the slot fronts.
    start = actor_sub.spawn_actor_from_class(
        unreal.PlayerStart, unreal.Vector(2800, 0, 160), unreal.Rotator(roll=0.0, pitch=0.0, yaw=180.0))
    start.set_actor_label("PlayerStart")
    made.append("PlayerStart")

    for spec in SLOTS:
        slot = actor_sub.spawn_actor_from_class(unreal.DCSlot, spec["loc"], unreal.Rotator(0, 0, 0))
        slot.set_actor_label(spec["id"])
        safe_set(slot, "slot_id", spec["id"])
        safe_set(slot, "size_class", spec["class"])
        safe_set(slot, "fill_order", spec["order"])
        safe_set(slot, "view_distance", spec["view"])
        safe_set(slot, "view_height", spec["height"])
        safe_set(slot, "content_yaw_offset", -90.0)
        made.append(spec["id"])
        report["slots"].append({
            "id": spec["id"],
            "size_class": str(spec["class"]).split(".")[-1],
            "location_cm": [spec["loc"].x, spec["loc"].y, spec["loc"].z],
            "view_distance": spec["view"],
            "view_height": spec["height"],
        })

    report["game_mode"] = set_default_game_mode(level_sub)

    level_sub.save_current_level()
    report["actors"] = made
    log("built %s with %d actors" % (MAP_PATH, len(made)))

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    report["log"] = LOG
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
    log("wrote %s" % REPORT_PATH)


main()
