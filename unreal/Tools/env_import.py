"""Bring the environment kit and the Player into the project. Editor Python, imported by
`make_maps.py` - it is not run on its own.

Three jobs:

1. **the environment meshes** - every FBX under `art/export_env/<id>/` becomes
   `/Game/DCEnv/Meshes/SM_ENV_<id>`, in centimetres, with no Nanite, no lightmap UVs and
   complex-as-simple collision. The environment is base-game content: it is cooked into
   chunk 0 and ships with the build, unlike anything in `/Game/DCContent/`.

2. **the two palettes** - `/Game/DCEnv/Materials/MI_ENV_<palette>_<slot>`, one material
   instance per kit slot per palette, off the same master materials the content uses. The
   geometry does not know which palette it is wearing: `make_maps.py` sets the right set on
   each actor, which is how two maps come out of one kit.

3. **the Player** - the engine's own UE4 mannequin (a shared template content pack, free to
   use) plus `BP_DCPlayer` and `BP_DCPlayerController`, so the demo has a visible third
   person character. The mannequin's chest-logo material slot is replaced with a plain
   neutral one: CLAUDE.md rule 3 says no logos anywhere, and the engine's logo is still a
   logo.
"""

import json
import os

import unreal

REPO = r"E:\DynamicContents"
ART = os.path.join(REPO, "art")
ENV_EXPORT = os.path.join(ART, "export_env")

CORE_MATERIALS = "/Game/DCCore/Materials"
DEFAULT_MASTER = "M_DC_Master"
ENV_ROOT = "/Game/DCEnv"
ENV_MESHES = ENV_ROOT + "/Meshes"
ENV_MATERIALS = ENV_ROOT + "/Materials"
PLAYER_ROOT = "/Game/Player"
MANNEQUIN_ROOT = "/Game/Mannequin"

MASTER_FOR_SLOT = {"M_Glass": "M_DC_Glass", "M_Emissive": "M_DC_Emissive"}
EMISSIVE_UE_SCALE = 0.5

MEL = unreal.MaterialEditingLibrary
LOG = []


def log(msg):
    line = "[env_import] %s" % msg
    LOG.append(line)
    unreal.log(line)


def warn(msg):
    line = "[env_import] WARNING %s" % msg
    LOG.append(line)
    unreal.log_warning(line)


def fail(msg):
    line = "[env_import] ERROR %s" % msg
    LOG.append(line)
    unreal.log_error(line)


def asset_tools():
    return unreal.AssetToolsHelpers.get_asset_tools()


def load_asset(path):
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    return None


def safe_set(obj, name, value):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:                                    # noqa: BLE001
        warn("could not set %s.%s: %s" % (type(obj).__name__, name, exc))
        return False


def save(asset):
    if asset is None:
        return
    try:
        unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
    except Exception as exc:                                    # noqa: BLE001
        warn("could not save %s: %s" % (asset.get_name(), exc))


def linear_color(rgb, a=1.0):
    return unreal.LinearColor(float(rgb[0]), float(rgb[1]), float(rgb[2]), float(a))


# --------------------------------------------------------------------------- the kit on disk

def load_env_manifests():
    out = {}
    if not os.path.isdir(ENV_EXPORT):
        fail("no %s - run art\\build.ps1 -EnvOnly first" % ENV_EXPORT)
        return out
    for name in sorted(os.listdir(ENV_EXPORT)):
        path = os.path.join(ENV_EXPORT, name, "manifest.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig") as fh:
                out[name] = json.load(fh)
    return out


def load_palettes():
    path = os.path.join(ENV_EXPORT, "palettes.json")
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- materials

def make_palette_materials(palettes):
    """MI_ENV_<palette>_<slot> for every palette and slot, from the kit's own colour table."""
    made = {}
    for palette, block in sorted(palettes["palettes"].items()):
        made[palette] = {}
        for slot, spec in sorted(block["slots"].items()):
            master_name = MASTER_FOR_SLOT.get(slot, DEFAULT_MASTER)
            master = load_asset("%s/%s" % (CORE_MATERIALS, master_name))
            if master is None:
                fail("master material %s is missing" % master_name)
                continue
            mi_name = "MI_ENV_%s_%s" % (palette, slot)
            mi_path = "%s/%s" % (ENV_MATERIALS, mi_name)
            mi = load_asset(mi_path)
            if mi is None:
                mi = asset_tools().create_asset(
                    mi_name, ENV_MATERIALS, unreal.MaterialInstanceConstant,
                    unreal.MaterialInstanceConstantFactoryNew())
            MEL.set_material_instance_parent(mi, master)

            colour = linear_color(spec["base_color_linear"])
            MEL.set_material_instance_vector_parameter_value(mi, "BaseColor", colour)
            MEL.set_material_instance_scalar_parameter_value(
                mi, "Roughness", float(spec.get("roughness", 0.6)))
            if master_name == DEFAULT_MASTER:
                MEL.set_material_instance_scalar_parameter_value(
                    mi, "Metallic", float(spec.get("metallic", 0.0)))
            if master_name == "M_DC_Glass":
                MEL.set_material_instance_scalar_parameter_value(
                    mi, "Opacity", float(spec.get("alpha", 0.25)))
            if master_name == "M_DC_Emissive":
                MEL.set_material_instance_vector_parameter_value(mi, "EmissiveColor", colour)
                MEL.set_material_instance_scalar_parameter_value(
                    mi, "EmissiveStrength",
                    float(spec.get("emissive_strength", 4.0)) * EMISSIVE_UE_SCALE)
            save(mi)
            made[palette][slot] = mi
        log("palette %-5s -> %d material instances" % (palette, len(made[palette])))
    return made


# --------------------------------------------------------------------------- meshes

def import_env_fbx(fbx_path, destination):
    options = unreal.FbxImportUI()
    safe_set(options, "import_mesh", True)
    safe_set(options, "import_textures", False)
    safe_set(options, "import_materials", False)
    safe_set(options, "import_as_skeletal", False)
    safe_set(options, "mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
    safe_set(options, "automated_import_should_detect_type", False)

    sm = options.static_mesh_import_data
    safe_set(sm, "combine_meshes", True)        # one mesh per environment piece, always
    # FALSE, and this is the whole unit contract in one flag.
    #
    # The FBX already carries centimetres baked into its vertex data (dc_kit bakes the x100
    # in, because the importer throws a node-level scale away - see unreal\README.md). Its
    # header still says "one unit is one metre", though, because Blender's scene is in metres.
    # With transform_vertex_to_absolute ON the importer applies that header scale as well and
    # every piece arrives a hundred times too big: an 8 m paving slab imports as 800 m. OFF
    # keeps each object in its own local space - which is also what import_content.py does -
    # and the piece lands at true size with import_uniform_scale left at 1.
    safe_set(sm, "transform_vertex_to_absolute", False)
    safe_set(sm, "bake_pivot_in_vertex", False)
    safe_set(sm, "generate_lightmap_u_vs", False)   # everything here is lit dynamically
    safe_set(sm, "auto_generate_collision", False)
    safe_set(sm, "build_nanite", False)
    safe_set(sm, "normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS)
    safe_set(sm, "convert_scene", True)
    safe_set(sm, "force_front_x_axis", False)
    safe_set(sm, "import_uniform_scale", 1.0)   # the FBX is already in centimetres

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", fbx_path)
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    task.set_editor_property("options", options)
    task.set_editor_property("factory", unreal.FbxFactory())
    asset_tools().import_asset_tasks([task])
    return [str(p) for p in task.get_editor_property("imported_object_paths")]


def assign_materials(mesh, mi_by_slot):
    """UStaticMesh::SetMaterial is the setter that works; StaticMaterials is private."""
    entries = mesh.get_editor_property("static_materials")
    order = []
    for index, entry in enumerate(entries):
        name = str(entry.get_editor_property("imported_material_slot_name"))
        order.append(name)
        material = mi_by_slot.get(name)
        if material is not None:
            mesh.set_material(index, material)
    return order


def import_env_meshes(manifests, palette_materials, default_palette="warm", reimport=False):
    """Every piece into /Game/DCEnv/Meshes, dressed in the default palette.

    Importing a static mesh in the editor is slow - most of it is the asynchronous mesh build
    and the first compile of the new material instances - so a piece whose asset is already
    there is left alone unless `reimport` says otherwise. That is what makes a second run of
    `make_maps.ps1` quick, which matters because the map layout is what gets iterated on.
    """
    out = {}
    report = []
    for pid, manifest in sorted(manifests.items()):
        fbx = os.path.join(ENV_EXPORT, pid, "%s.fbx" % pid)
        if not os.path.exists(fbx):
            fail("no FBX for %s at %s" % (pid, fbx))
            continue

        want_name = "SM_ENV_%s" % pid
        want_path = "%s/%s" % (ENV_MESHES, want_name)

        if reimport or not unreal.EditorAssetLibrary.does_asset_exist(want_path):
            imported = import_env_fbx(fbx, ENV_MESHES)
            if not imported:
                fail("import produced nothing for %s" % pid)
                continue
            # FbxFactory names the asset after the FBX; put it where the map expects it.
            for path in imported:
                obj_path = path.split(".")[0]
                if obj_path != want_path:
                    if unreal.EditorAssetLibrary.does_asset_exist(want_path):
                        unreal.EditorAssetLibrary.delete_asset(want_path)
                    unreal.EditorAssetLibrary.rename_asset(obj_path, want_path)

        mesh = load_asset(want_path)
        if mesh is None:
            fail("%s did not end up at %s" % (pid, want_path))
            continue

        body = mesh.get_editor_property("body_setup")
        if body is not None:
            safe_set(body, "collision_trace_flag",
                     unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
        order = assign_materials(mesh, palette_materials.get(default_palette, {}))
        save(mesh)

        out[pid] = mesh
        bounds = mesh.get_bounds().box_extent
        want = manifest["bounds_cm"]["size"]
        got = [bounds.x * 2, bounds.y * 2, bounds.z * 2]
        if any(abs(got[i] - want[i]) > max(1.0, want[i] * 0.02) for i in range(3)):
            fail("%s imported at %s cm but the manifest says %s cm - the FBX unit contract "
                 "has slipped (see import_env_fbx)" % (pid, [round(c, 1) for c in got], want))
        report.append(dict(
            id=pid, asset=want_path, category=manifest.get("category"),
            collision=manifest.get("collision"),
            slot_order=order,
            manifest_slots=list(manifest.get("material_slots", [])),
            size_cm=[round(bounds.x * 2, 1), round(bounds.y * 2, 1), round(bounds.z * 2, 1)],
            manifest_size_cm=manifest["bounds_cm"]["size"],
            triangles=manifest.get("triangles"),
        ))
        log("imported %-14s %-26s slots=%s" % (pid, want_name, ",".join(order)))
    return out, report


# --------------------------------------------------------------------------- the Player

# One material, both slots. The mannequin has a body slot and a chest-logo slot, and brief
# 012 gave them two different colours - which turned the Player into a two-tone mannequin
# whose darker patch sat exactly where the engine's logo used to be, i.e. it still read as a
# badge. One plain material instance over the whole figure reads as a neutral, untextured
# character on purpose rather than as an asset that is missing its textures: a light warm
# grey with a slight sheen, so the figure catches the sun and has a silhouette.
CHAR_MATERIAL = ("MI_DC_Char_Neutral", (0.62, 0.60, 0.57), 0.38, 0.04)


def make_character_materials():
    made = {}
    master = load_asset("%s/%s" % (CORE_MATERIALS, DEFAULT_MASTER))
    if master is None:
        fail("master material %s is missing" % DEFAULT_MASTER)
        return made
    name, rgb, rough, metal = CHAR_MATERIAL
    path = "%s/%s" % (PLAYER_ROOT, name)
    mi = load_asset(path)
    if mi is None:
        mi = asset_tools().create_asset(
            name, PLAYER_ROOT, unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, master)
    MEL.set_material_instance_vector_parameter_value(mi, "BaseColor", linear_color(rgb))
    MEL.set_material_instance_scalar_parameter_value(mi, "Roughness", rough)
    MEL.set_material_instance_scalar_parameter_value(mi, "Metallic", metal)
    save(mi)
    made[name] = mi
    log("character material %s -> light warm grey, roughness %.2f" % (name, rough))
    return made


def dress_mannequin(char_materials):
    """One plain neutral material on every slot of the mannequin.

    The engine's mannequin wears the engine's logo on its chest. CLAUDE.md rule 3 is no logos
    anywhere in this project, so both of its material slots - body and chest logo - get the
    same plain material instance: no logo, and no two-tone patch where the logo used to be.
    It also drops ~23 MB of 4K textures out of the repo.
    """
    mesh = load_asset("%s/Character/Mesh/SK_Mannequin" % MANNEQUIN_ROOT)
    if mesh is None:
        warn("SK_Mannequin is not in the project - the Player will have no visible mesh")
        return None, []
    neutral = char_materials.get(CHAR_MATERIAL[0])
    if neutral is None:
        fail("the character material was not made - the mannequin would keep the engine logo")
        return mesh, []

    entries = mesh.get_editor_property("materials")
    names = []
    for entry in entries:
        names.append(str(entry.get_editor_property("material_slot_name")))
        safe_set(entry, "material_interface", neutral)
    safe_set(mesh, "materials", entries)
    save(mesh)
    log("mannequin material slots %s -> one neutral material, no logo" % names)
    return mesh, names


def make_player_blueprints(skeletal_mesh):
    """BP_DCPlayer and BP_DCPlayerController, both built from the template's C++ classes."""
    made = {}

    anim_bp = load_asset("%s/Animations/ThirdPerson_AnimBP" % MANNEQUIN_ROOT)
    anim_class = anim_bp.generated_class() if anim_bp else None

    # ---- the pawn
    bp = load_asset("%s/BP_DCPlayer" % PLAYER_ROOT)
    if bp is None:
        factory = unreal.BlueprintFactory()
        safe_set(factory, "parent_class", unreal.DCDemoCharacter)
        bp = asset_tools().create_asset("BP_DCPlayer", PLAYER_ROOT, None, factory)
    if bp is None:
        fail("could not create BP_DCPlayer")
        return made
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)

    cdo = unreal.get_default_object(bp.generated_class())
    for prop, path in (("jump_action", "/Game/Input/Actions/IA_Jump"),
                       ("move_action", "/Game/Input/Actions/IA_Move"),
                       ("look_action", "/Game/Input/Actions/IA_Look"),
                       ("mouse_look_action", "/Game/Input/Actions/IA_MouseLook")):
        asset = load_asset(path)
        if asset is None:
            warn("input action missing: %s" % path)
        else:
            safe_set(cdo, prop, asset)

    comp = None
    try:
        comp = cdo.get_editor_property("mesh")
    except Exception as exc:                                    # noqa: BLE001
        warn("no mesh component on the BP_DCPlayer CDO (%s)" % exc)
    if comp is not None:
        if skeletal_mesh is not None:
            safe_set(comp, "skeletal_mesh_asset", skeletal_mesh)
        if anim_class is not None:
            safe_set(comp, "anim_class", anim_class)
        # the template's standing offset: feet on the capsule bottom, facing +X
        safe_set(comp, "relative_location", unreal.Vector(0.0, 0.0, -89.0))
        safe_set(comp, "relative_rotation", unreal.Rotator(0.0, 0.0, -90.0))
    save(bp)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    save(bp)
    made["pawn"] = "%s/BP_DCPlayer.BP_DCPlayer_C" % PLAYER_ROOT

    # ---- the controller, which is what adds the input mapping contexts
    pc = load_asset("%s/BP_DCPlayerController" % PLAYER_ROOT)
    if pc is None:
        factory = unreal.BlueprintFactory()
        safe_set(factory, "parent_class", unreal.DCDemoPlayerController)
        pc = asset_tools().create_asset("BP_DCPlayerController", PLAYER_ROOT, None, factory)
    if pc is not None:
        unreal.BlueprintEditorLibrary.compile_blueprint(pc)
        pcdo = unreal.get_default_object(pc.generated_class())
        imc = load_asset("/Game/Input/IMC_Default")
        imc_mouse = load_asset("/Game/Input/IMC_MouseLook")
        if imc is not None:
            safe_set(pcdo, "default_mapping_contexts", [imc])
        if imc_mouse is not None:
            safe_set(pcdo, "mobile_excluded_mapping_contexts", [imc_mouse])
        save(pc)
        unreal.BlueprintEditorLibrary.compile_blueprint(pc)
        save(pc)
        made["controller"] = "%s/BP_DCPlayerController.BP_DCPlayerController_C" % PLAYER_ROOT

    return made


def readback_player():
    """Read the defaults back off the saved assets: setting a CDO fails quietly."""
    out = {}
    bp = load_asset("%s/BP_DCPlayer" % PLAYER_ROOT)
    if bp is None:
        return out
    try:
        cdo = unreal.get_default_object(bp.generated_class())
        comp = cdo.get_editor_property("mesh")
        sk = comp.get_editor_property("skeletal_mesh_asset")
        anim = comp.get_editor_property("anim_class")
        out = dict(
            skeletal_mesh=sk.get_name() if sk else None,
            anim_class=str(anim.get_name()) if anim else None,
            relative_location=str(comp.get_editor_property("relative_location")),
            move_action=(cdo.get_editor_property("move_action").get_name()
                         if cdo.get_editor_property("move_action") else None),
        )
    except Exception as exc:                                    # noqa: BLE001
        warn("could not read BP_DCPlayer back (%s)" % exc)
    return out
