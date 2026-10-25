"""
import_content.py - bring the generated content art into the UE project as content packs.

Run headless from the repo root:

    "E:\\EpicGames\\UE_5.7\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
        "E:\\DynamicContents\\unreal\\DCDemo\\DCDemo.uproject" ^
        -run=pythonscript -script="E:\\DynamicContents\\unreal\\Tools\\import_content.py" ^
        -unattended -nosplash

What it makes (unreal_spec_v1 sections 1 and 2):

  /Game/DCCore/Materials/     the five master materials the base game owns, plus a ground MI
  /Game/DCCore/Emblems/       the eight brand emblems (brand = a colour plus an emblem)
  /Game/DCCore/Screens/       the sample screen image
  /Game/DCContent/<id>_<v>/   one folder per piece-version = one content pack:
                              the five static meshes, a material instance per material slot,
                              BP_DC_<id>_<v> (a child of ADCContentActor with its meshes and
                              brand set), and PAL_<id>_<v>, the PrimaryAssetLabel that puts
                              the folder in its own cook chunk
  /Game/Maps/Spike            the spike map: ground, lights, player start, two ADCSlots

Everything it checked goes into unreal/_build/logs/import_report.json - bounds (so the metre
to centimetre conversion is verified, not assumed), socket names as imported, material slot
names, and a read-back of the Blueprint defaults.
"""

import json
import os
import traceback

import unreal

# --------------------------------------------------------------------------- configuration

REPO = r"E:\DynamicContents"
ART_EXPORT = os.path.join(REPO, "art", "export")
ART_EMBLEMS = os.path.join(REPO, "art", "emblems")
ART_SAMPLES = os.path.join(REPO, "art", "samples")
REPORT_PATH = os.path.join(REPO, "unreal", "_build", "logs", "import_report.json")

CORE_MATERIALS = "/Game/DCCore/Materials"
CORE_EMBLEMS = "/Game/DCCore/Emblems"
CORE_SCREENS = "/Game/DCCore/Screens"
CONTENT_ROOT = "/Game/DCContent"
MAP_PATH = "/Game/Maps/Spike"

EMBLEM_SHAPES = ("circle", "triangle", "square", "diamond", "star", "ring", "chevron", "hexagon")

# The pieces this brief imports, and the brand each one wears in the spike. Brand colour and
# emblem are runtime inputs - these are just the values the spike run happens to use.
PIECES = [
    {
        "id": "content4",
        "version": "v1",
        "chunk_id": 100,
        "brand_srgb": (0.11, 0.69, 0.66),   # teal
        "emblem": "circle",
        "slot": "slot1",
    },
    {
        "id": "content1",
        "version": "v1",
        "chunk_id": 101,
        "brand_srgb": (0.92, 0.55, 0.11),   # amber
        "emblem": "diamond",
        "slot": "slot2",
    },
]

# Which master material each of the 13 allowed material slots instances.
MASTER_FOR_SLOT = {
    "M_Glass": "M_DC_Glass",
    "M_LightEmissive": "M_DC_Emissive",
    "M_Screen": "M_DC_Screen",
    "M_Sign": "M_DC_Sign",
}
DEFAULT_MASTER = "M_DC_Master"

ROLES = ("Shell", "Door", "Switch", "Screen", "Sign")

# The art is authored in metres and the FBX carries metre-scale vertex data, so a 6.5 m cabin
# imports as 6.5 cm. The importer's own uniform scale cannot fix it here: the parts are
# imported in their own local space (so each part's pivot lands on its socket), and in that
# mode FFbxImporter::ComputeTotalMatrix returns the identity and throws the scene scale away.
# The conversion is therefore done in the mesh build settings, with the shell's socket
# positions scaled to match. The permanent fix belongs in the Blender export.
MESH_SCALE = 100.0

# --------------------------------------------------------------------------- small helpers

LOG = []


def log(msg):
    line = "[import_content] %s" % msg
    LOG.append(line)
    unreal.log(line)


def warn(msg):
    line = "[import_content] WARNING %s" % msg
    LOG.append(line)
    unreal.log_warning(line)


def fail(msg):
    line = "[import_content] ERROR %s" % msg
    LOG.append(line)
    unreal.log_error(line)


def srgb_to_linear(c):
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def linear_color(rgb, a=1.0):
    return unreal.LinearColor(float(rgb[0]), float(rgb[1]), float(rgb[2]), float(a))


def asset_tools():
    return unreal.AssetToolsHelpers.get_asset_tools()


def safe_set(obj, name, value):
    """set_editor_property that reports instead of exploding: property names drift."""
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:                                    # noqa: BLE001
        warn("could not set %s.%s = %r (%s)" % (type(obj).__name__, name, value, exc))
        return False


def save(asset_or_path):
    path = asset_or_path
    if not isinstance(asset_or_path, str):
        path = asset_or_path.get_path_name().split(".")[0]
    try:
        unreal.EditorAssetLibrary.save_asset(path, only_if_is_dirty=False)
    except Exception as exc:                                    # noqa: BLE001
        warn("save failed for %s (%s)" % (path, exc))


def load_asset(path):
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    return None


# --------------------------------------------------------------------------- master materials

MEL = unreal.MaterialEditingLibrary


def connect_expr(from_expression, from_output, to_expression, to_input):
    """connect_material_expressions, but it says so when a link does not take: a silently
    unconnected Lerp input leaves the sign rendering as a black panel in the game."""
    ok = MEL.connect_material_expressions(from_expression, from_output, to_expression, to_input)
    if not ok:
        warn("could not connect %s.%s -> %s.%s"
             % (type(from_expression).__name__, from_output or "RGB",
                type(to_expression).__name__, to_input))
    return ok


def connect_prop(from_expression, from_output, material_property):
    ok = MEL.connect_material_property(from_expression, from_output, material_property)
    if not ok:
        warn("could not connect %s.%s -> %s"
             % (type(from_expression).__name__, from_output or "RGB", material_property))
    return ok


def _vector_param(mat, name, value, x, y):
    node = MEL.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, x, y)
    safe_set(node, "parameter_name", name)
    safe_set(node, "default_value", value)
    return node


def _scalar_param(mat, name, value, x, y):
    node = MEL.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, x, y)
    safe_set(node, "parameter_name", name)
    safe_set(node, "default_value", float(value))
    return node


def _texture_param(mat, name, texture, x, y):
    node = MEL.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, x, y)
    safe_set(node, "parameter_name", name)
    if texture is not None:
        safe_set(node, "texture", texture)
    safe_set(node, "sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    return node


def create_material(name, build_fn):
    """Build a master material, rebuilding its graph in place if the asset already exists so
    the asset always matches this script (and keeps its path, so instances stay parented)."""
    path = "%s/%s" % (CORE_MATERIALS, name)
    mat = load_asset(path)
    verb = "rebuilt"
    if mat is None:
        mat = asset_tools().create_asset(name, CORE_MATERIALS, unreal.Material, unreal.MaterialFactoryNew())
        verb = "made"
    else:
        MEL.delete_all_material_expressions(mat)

    build_fn(mat)
    MEL.recompile_material(mat)
    save(mat)
    log("%s master material %s" % (verb, name))
    return mat


def build_master(mat):
    base = _vector_param(mat, "BaseColor", unreal.LinearColor(0.8, 0.8, 0.8, 1.0), -450, -100)
    connect_prop(base, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = _scalar_param(mat, "Roughness", 0.5, -450, 120)
    connect_prop(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    metal = _scalar_param(mat, "Metallic", 0.0, -450, 240)
    connect_prop(metal, "", unreal.MaterialProperty.MP_METALLIC)


def build_glass(mat):
    safe_set(mat, "blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    safe_set(mat, "two_sided", True)
    base = _vector_param(mat, "BaseColor", unreal.LinearColor(0.6, 0.72, 0.78, 1.0), -450, -100)
    connect_prop(base, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = _scalar_param(mat, "Roughness", 0.07, -450, 120)
    connect_prop(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    opacity = _scalar_param(mat, "Opacity", 0.25, -450, 240)
    connect_prop(opacity, "", unreal.MaterialProperty.MP_OPACITY)


def build_emissive(mat):
    base = _vector_param(mat, "BaseColor", unreal.LinearColor(1.0, 0.9, 0.73, 1.0), -700, -100)
    connect_prop(base, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = _scalar_param(mat, "Roughness", 0.5, -700, 320)
    connect_prop(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)

    colour = _vector_param(mat, "EmissiveColor", unreal.LinearColor(1.0, 0.9, 0.73, 1.0), -700, 60)
    strength = _scalar_param(mat, "EmissiveStrength", 4.0, -700, 200)
    mul = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -350, 120)
    connect_expr(colour, "", mul, "A")
    connect_expr(strength, "", mul, "B")
    connect_prop(mul, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)


def build_screen(mat, default_texture=None):
    safe_set(mat, "two_sided", True)   # same reason as the sign
    tex = _texture_param(mat, "ScreenImage", default_texture, -750, -60)
    connect_prop(tex, "", unreal.MaterialProperty.MP_BASE_COLOR)

    brightness = _scalar_param(mat, "ScreenBrightness", 1.6, -750, 260)
    mul = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -350, 140)
    connect_expr(tex, "", mul, "A")
    connect_expr(brightness, "", mul, "B")
    connect_prop(mul, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    rough = _scalar_param(mat, "Roughness", 0.2, -750, 400)
    connect_prop(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)


def build_sign(mat, default_emblem=None):
    # The sign and the screen are single quads, and which way a quad faces survives the
    # Blender -> FBX -> UE trip less reliably than a closed shell does; two-sided costs
    # nothing on two triangles and means the sign is never an invisible black hole.
    safe_set(mat, "two_sided", True)

    # Plate takes the brand colour, the emblem shape is punched over it in EmblemColor.
    brand = _vector_param(mat, "BrandColor", unreal.LinearColor(0.5, 0.5, 0.5, 1.0), -900, -160)
    emblem_colour = _vector_param(mat, "EmblemColor", unreal.LinearColor(1.0, 1.0, 1.0, 1.0), -900, -20)
    emblem = _texture_param(mat, "Emblem", default_emblem, -900, 140)

    lerp = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -500, -60)
    connect_expr(brand, "", lerp, "A")
    connect_expr(emblem_colour, "", lerp, "B")
    connect_expr(emblem, "A", lerp, "Alpha")
    connect_prop(lerp, "", unreal.MaterialProperty.MP_BASE_COLOR)

    # Full-strength emissive, not a hint of glow: the sign has to read from 20 m, and the
    # quad's normal does not survive the export reliably, so a lit-only sign can come out
    # black when the normal ends up pointing into the building.
    glow = _scalar_param(mat, "SignGlow", 1.0, -900, 420)
    mul = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -250, 220)
    connect_expr(lerp, "", mul, "A")
    connect_expr(glow, "", mul, "B")
    connect_prop(mul, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    rough = _scalar_param(mat, "Roughness", 0.46, -900, 540)
    connect_prop(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)


# --------------------------------------------------------------------------- texture import


def import_texture(filename, destination_path, asset_name):
    path = "%s/%s" % (destination_path, asset_name)
    existing = load_asset(path)
    if existing is not None:
        return existing

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", filename)
    task.set_editor_property("destination_path", destination_path)
    task.set_editor_property("destination_name", asset_name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    # Naming a factory keeps the import on the classic path. Interchange (the 5.5+ default)
    # calls into the content browser when it finishes, which asserts in a commandlet with no
    # Slate application, and it ignores the FbxImportUI options we need for the meshes.
    task.set_editor_property("factory", unreal.TextureFactory())
    asset_tools().import_asset_tasks([task])

    tex = load_asset(path)
    if tex is None:
        fail("texture import failed: %s" % filename)
        return None

    safe_set(tex, "compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)
    safe_set(tex, "srgb", True)
    save(tex)
    return tex


# --------------------------------------------------------------------------- mesh import


def import_fbx(fbx_path, destination_path, uniform_scale):
    options = unreal.FbxImportUI()
    safe_set(options, "import_mesh", True)
    safe_set(options, "import_textures", False)
    safe_set(options, "import_materials", False)
    safe_set(options, "import_as_skeletal", False)
    safe_set(options, "mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
    safe_set(options, "automated_import_should_detect_type", False)

    sm = options.static_mesh_import_data
    safe_set(sm, "combine_meshes", False)
    # Each part is exported with its origin on its socket, so keep the parts in their own
    # local space; the shell's sockets put them back where Blender had them.
    safe_set(sm, "transform_vertex_to_absolute", False)
    safe_set(sm, "bake_pivot_in_vertex", False)
    safe_set(sm, "generate_lightmap_u_vs", False)
    safe_set(sm, "auto_generate_collision", False)
    safe_set(sm, "build_nanite", False)
    safe_set(sm, "normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS)
    safe_set(sm, "convert_scene", True)
    safe_set(sm, "force_front_x_axis", False)
    safe_set(sm, "import_uniform_scale", float(uniform_scale))

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", fbx_path)
    task.set_editor_property("destination_path", destination_path)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    task.set_editor_property("options", options)
    # See import_texture: the classic FbxFactory, not Interchange - it is the one that reads
    # the FbxImportUI options above (no mesh combining, parts kept in their own local space).
    task.set_editor_property("factory", unreal.FbxFactory())

    asset_tools().import_asset_tasks([task])
    return [str(p) for p in task.get_editor_property("imported_object_paths")]


def rename_imported_meshes(imported_paths, piece_name):
    """
    FbxFactory names a multi-mesh import <fbx base>_<node name>, so the shell arrives as
    content4_v1_SM_content4_v1_Shell. Put the names back to what the spec says the pack
    ships: SM_<id>_<v>_<Role>.
    """
    found = {}
    for object_path in imported_paths:
        package = object_path.split(".")[0]
        folder, asset_name = package.rsplit("/", 1)
        for role in ROLES:
            if not asset_name.endswith("_%s" % role):
                continue
            wanted = "SM_%s_%s" % (piece_name, role)
            target = "%s/%s" % (folder, wanted)
            if asset_name != wanted:
                if unreal.EditorAssetLibrary.does_asset_exist(target):
                    unreal.EditorAssetLibrary.delete_asset(target)
                if not unreal.EditorAssetLibrary.rename_asset(package, target):
                    warn("could not rename %s -> %s" % (package, target))
            asset = load_asset(target)
            if asset is not None:
                found[role] = asset
            break
    return found


def mesh_size_cm(mesh):
    try:
        box = mesh.get_bounding_box()
        mn, mx = box.min, box.max
        return (mx.x - mn.x, mx.y - mn.y, mx.z - mn.z)
    except Exception:                                           # noqa: BLE001
        bounds = mesh.get_bounds()
        ext = bounds.box_extent
        return (ext.x * 2.0, ext.y * 2.0, ext.z * 2.0)


def resolve_socket(mesh, manifest_name):
    """UStaticMesh.Sockets is not readable from Python, so probe by name instead. The FBX
    importer drops the SOCKET_ prefix, so try the bare name first."""
    bare = manifest_name[len("SOCKET_"):] if manifest_name.startswith("SOCKET_") else manifest_name
    for candidate in (bare, manifest_name):
        socket = mesh.find_socket(candidate)
        if socket is not None:
            return candidate, socket
    return None, None


def socket_table(mesh, manifest_names):
    out = {}
    for name in manifest_names:
        candidate, socket = resolve_socket(mesh, name)
        if socket is None:
            out[name] = None
            continue
        loc = socket.get_editor_property("relative_location")
        out[name] = {"imported_as": candidate,
                     "loc_cm": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)]}
    return out


def check_socket_scale(mesh, manifest, manifest_names):
    """
    The meshes stay in the units the FBX carries (metres) and ADCContentActor scales the shell
    by MESH_SCALE, which takes the sockets and every attached part with it. Confirm here that
    the sockets really are in metres and really do match the manifest, so the one assumption
    the runtime makes is checked rather than believed.
    """
    by_name = {s["name"]: s for s in manifest.get("sockets", [])}
    worst = 0.0
    checked = 0
    for name in manifest_names:
        _, socket = resolve_socket(mesh, name)
        if socket is None:
            continue
        loc = socket.get_editor_property("relative_location")
        want = by_name[name]["location"]
        # Blender -Y is UE +Y: the FBX conversion mirrors Y, so compare |y|.
        for got, expect in ((loc.x, want[0]), (abs(loc.y), abs(want[1])), (loc.z, want[2])):
            worst = max(worst, abs(got - expect))
        checked += 1
    return {"sockets_checked": checked, "worst_axis_error_m": round(worst, 4)}


def slot_names(mesh):
    out = []
    for entry in mesh.get_editor_property("static_materials"):
        out.append(str(entry.get_editor_property("imported_material_slot_name")))
    return out


def assign_materials(mesh, mi_by_slot):
    """
    Put each piece's material instance on the slot of the same name.

    UStaticMesh.StaticMaterials is private and deprecated, and writing it through
    set_editor_property fails silently - the slots keep the importer's WorldGridMaterial and
    the content renders as grey checks in the game. UStaticMesh::SetMaterial is the setter
    that works, so the result is read back from the asset afterwards and reported.
    """
    entries = mesh.get_editor_property("static_materials")
    wanted = {}
    for index, entry in enumerate(entries):
        name = str(entry.get_editor_property("imported_material_slot_name"))
        material = mi_by_slot.get(name)
        if material is None:
            continue
        mesh.set_material(index, material)
        wanted[index] = (name, material.get_name())

    assigned = {}
    for index, entry in enumerate(mesh.get_editor_property("static_materials")):
        if index not in wanted:
            continue
        slot_name, expected = wanted[index]
        actual = entry.get_editor_property("material_interface")
        actual_name = actual.get_name() if actual else "NONE"
        assigned[slot_name] = actual_name
        if actual_name != expected:
            warn("%s slot %s kept %s instead of %s"
                 % (mesh.get_name(), slot_name, actual_name, expected))
    return assigned


def set_complex_as_simple(mesh):
    body = mesh.get_editor_property("body_setup")
    if body is None:
        warn("%s has no body setup, collision left alone" % mesh.get_name())
        return False
    return safe_set(body, "collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)


# --------------------------------------------------------------------------- one piece


def make_material_instances(piece, manifest, pack_path, emblem_tex, screen_tex):
    """One MaterialInstanceConstant per material slot in the manifest's colour table."""
    out = {}
    for entry in manifest["materials"]:
        slot = entry["slot"]
        master_name = MASTER_FOR_SLOT.get(slot, DEFAULT_MASTER)
        master = load_asset("%s/%s" % (CORE_MATERIALS, master_name))
        if master is None:
            fail("master material %s is missing" % master_name)
            continue

        mi_name = "MI_%s_%s_%s" % (piece["id"], piece["version"], slot)
        mi_path = "%s/%s" % (pack_path, mi_name)
        mi = load_asset(mi_path)
        if mi is None:
            mi = asset_tools().create_asset(
                mi_name, pack_path, unreal.MaterialInstanceConstant,
                unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, master)

        colour = linear_color(entry["base_color_linear"])
        if master_name == "M_DC_Sign":
            MEL.set_material_instance_vector_parameter_value(mi, "BrandColor", colour)
            if emblem_tex is not None:
                MEL.set_material_instance_texture_parameter_value(mi, "Emblem", emblem_tex)
        elif master_name == "M_DC_Screen":
            if screen_tex is not None:
                MEL.set_material_instance_texture_parameter_value(mi, "ScreenImage", screen_tex)
        else:
            MEL.set_material_instance_vector_parameter_value(mi, "BaseColor", colour)

        MEL.set_material_instance_scalar_parameter_value(mi, "Roughness", float(entry.get("roughness", 0.5)))
        if master_name == DEFAULT_MASTER:
            MEL.set_material_instance_scalar_parameter_value(mi, "Metallic", float(entry.get("metallic", 0.0)))
        if master_name == "M_DC_Glass":
            MEL.set_material_instance_scalar_parameter_value(mi, "Opacity", float(entry.get("alpha", 0.25)))
        if master_name == "M_DC_Emissive":
            MEL.set_material_instance_vector_parameter_value(mi, "EmissiveColor", colour)
            MEL.set_material_instance_scalar_parameter_value(
                mi, "EmissiveStrength", float(entry.get("emissive_strength", 4.0)))

        save(mi)
        out[slot] = mi
    return out


def make_blueprint(piece, pack_path, meshes, manifest, emblem_tex, screen_tex):
    bp_name = "BP_DC_%s_%s" % (piece["id"], piece["version"])
    bp_path = "%s/%s" % (pack_path, bp_name)

    bp = load_asset(bp_path)
    if bp is None:
        factory = unreal.BlueprintFactory()
        safe_set(factory, "parent_class", unreal.DCContentActor)
        bp = asset_tools().create_asset(bp_name, pack_path, None, factory)
    if bp is None:
        fail("could not create %s" % bp_path)
        return None, {}

    unreal.BlueprintEditorLibrary.compile_blueprint(bp)

    generated = bp.generated_class()
    cdo = None
    try:
        cdo = unreal.get_default_object(generated)
    except Exception:                                           # noqa: BLE001
        try:
            cdo = generated.get_default_object()
        except Exception as exc:                                # noqa: BLE001
            fail("no CDO for %s (%s)" % (bp_name, exc))
    if cdo is None:
        return bp, {}

    door = manifest.get("door", {})
    brand_linear = [srgb_to_linear(c) for c in piece["brand_srgb"]]

    safe_set(cdo, "content_id", piece["id"])
    safe_set(cdo, "content_version", piece["version"])
    safe_set(cdo, "state_schema_version", int(manifest.get("schema_version", 1)))
    safe_set(cdo, "content_unit_scale", MESH_SCALE)
    safe_set(cdo, "shell_mesh", meshes.get("Shell"))
    safe_set(cdo, "door_mesh", meshes.get("Door"))
    safe_set(cdo, "switch_mesh", meshes.get("Switch"))
    safe_set(cdo, "screen_mesh", meshes.get("Screen"))
    safe_set(cdo, "sign_mesh", meshes.get("Sign"))
    safe_set(cdo, "brand_color", linear_color(brand_linear))
    safe_set(cdo, "emblem_texture", emblem_tex)
    safe_set(cdo, "screen_image", screen_tex)
    safe_set(cdo, "door_open_degrees", float(door.get("open_degrees", 90)))
    safe_set(cdo, "door_open_sign", int(door.get("open_sign", 1)))

    save(bp)

    # Read the defaults back off the saved asset: setting them on a CDO is the sort of thing
    # that fails quietly.
    unreal.EditorAssetLibrary.save_asset(bp_path, only_if_is_dirty=False)
    reloaded = load_asset(bp_path)
    readback = {}
    try:
        rcdo = unreal.get_default_object(reloaded.generated_class())
        shell = rcdo.get_editor_property("shell_mesh")
        readback = {
            "shell_mesh": shell.get_name() if shell else None,
            "content_unit_scale": float(rcdo.get_editor_property("content_unit_scale")),
            "content_id": str(rcdo.get_editor_property("content_id")),
            "brand_color": str(rcdo.get_editor_property("brand_color")),
            "emblem": (rcdo.get_editor_property("emblem_texture").get_name()
                       if rcdo.get_editor_property("emblem_texture") else None),
        }
    except Exception as exc:                                    # noqa: BLE001
        warn("could not read the Blueprint defaults back (%s)" % exc)

    return bp, readback


def make_label(piece, pack_path):
    name = "PAL_%s_%s" % (piece["id"], piece["version"])
    path = "%s/%s" % (pack_path, name)

    label = load_asset(path)
    if label is None:
        factory = unreal.DataAssetFactory()
        safe_set(factory, "data_asset_class", unreal.PrimaryAssetLabel)
        label = asset_tools().create_asset(name, pack_path, unreal.PrimaryAssetLabel, factory)
    if label is None:
        fail("could not create %s" % path)
        return None

    # apply_recursively=False on purpose: the pack gets its own assets only. The master
    # materials, emblems and screen images it references stay in the base game (chunk 0)
    # instead of being dragged into - and duplicated across - every pack.
    rules = unreal.PrimaryAssetRules()
    safe_set(rules, "priority", 1)
    safe_set(rules, "chunk_id", int(piece["chunk_id"]))
    safe_set(rules, "apply_recursively", False)
    safe_set(rules, "cook_rule", unreal.PrimaryAssetCookRule.ALWAYS_COOK)

    safe_set(label, "rules", rules)
    safe_set(label, "label_assets_in_my_directory", True)
    safe_set(label, "is_runtime_label", False)
    save(label)
    return label


def import_piece(piece, emblem_textures, screen_tex):
    name = "%s_%s" % (piece["id"], piece["version"])
    src_dir = os.path.join(ART_EXPORT, name)
    fbx = os.path.join(src_dir, "%s.fbx" % name)
    manifest_path = os.path.join(src_dir, "manifest.json")

    record = {"piece": name, "fbx": fbx, "ok": False, "problems": []}

    if not os.path.isfile(fbx) or not os.path.isfile(manifest_path):
        record["problems"].append("missing art: %s" % src_dir)
        fail(record["problems"][-1])
        return record

    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    pack_path = "%s/%s" % (CONTENT_ROOT, name)
    unreal.EditorAssetLibrary.make_directory(pack_path)

    expected_cm = [v * 100.0 for v in manifest["bounds"]["size"]]
    manifest_sockets = [s["name"] for s in manifest.get("sockets", [])]

    imported = import_fbx(fbx, pack_path, 1.0)
    record["imported_object_paths"] = imported
    meshes = rename_imported_meshes(imported, name)

    if "Shell" not in meshes:
        record["problems"].append("no shell mesh after import; imported=%r" % imported)
        fail(record["problems"][-1])
        return record

    # The FBX is in metres, so the asset is too; ADCContentActor scales the shell by
    # MESH_SCALE at spawn. Check the imported size against the manifest at that scale.
    raw = mesh_size_cm(meshes["Shell"])
    size = [v * MESH_SCALE for v in raw]
    record["shell_size_as_imported"] = [round(v, 3) for v in raw]
    record["shell_size_cm_at_unit_scale"] = [round(v, 1) for v in size]
    record["shell_size_cm_expected"] = [round(v, 1) for v in expected_cm]
    record["scale_ok"] = all(abs(size[i] - expected_cm[i]) < max(2.0, 0.02 * expected_cm[i])
                             for i in range(3))
    if not record["scale_ok"]:
        warn("%s is %.1f x %.1f x %.1f cm at unit scale %.0f, expected %.1f x %.1f x %.1f"
             % (name, size[0], size[1], size[2], MESH_SCALE,
                expected_cm[0], expected_cm[1], expected_cm[2]))
    record["socket_check"] = check_socket_scale(meshes["Shell"], manifest, manifest_sockets)

    record["missing_roles"] = [r for r in ROLES if r not in meshes]
    record["sockets"] = socket_table(meshes["Shell"], manifest_sockets)
    record["material_slots"] = {role: slot_names(mesh) for role, mesh in meshes.items()}

    emblem_tex = emblem_textures.get(piece["emblem"])
    mi_by_slot = make_material_instances(piece, manifest, pack_path, emblem_tex, screen_tex)
    record["material_instances"] = sorted(mi_by_slot.keys())

    record["assigned"] = {}
    for role, mesh in meshes.items():
        record["assigned"][role] = assign_materials(mesh, mi_by_slot)
        set_complex_as_simple(mesh)
        save(mesh)

    blueprint, readback = make_blueprint(piece, pack_path, meshes, manifest, emblem_tex, screen_tex)
    record["blueprint"] = blueprint.get_path_name() if blueprint else None
    record["blueprint_defaults_readback"] = readback

    label = make_label(piece, pack_path)
    record["label"] = label.get_path_name() if label else None
    record["chunk_id"] = piece["chunk_id"]

    shell_assigned = record["assigned"].get("Shell", {})
    record["materials_ok"] = (len(shell_assigned) > 0
                              and all(v.startswith("MI_") for v in shell_assigned.values()))

    record["ok"] = (blueprint is not None and label is not None and record["scale_ok"]
                    and record["materials_ok"]
                    and not record["missing_roles"] and bool(readback.get("shell_mesh")))
    found_sockets = sum(1 for v in record["sockets"].values() if v)
    log("piece %s imported: ok=%s meshes=%d sockets found=%d/%d size=%.0fx%.0fx%.0f cm"
        % (name, record["ok"], len(meshes), found_sockets, len(manifest_sockets),
           size[0], size[1], size[2]))
    return record


# --------------------------------------------------------------------------- the spike map


def build_spike_map(report):
    level_sub = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    if unreal.EditorAssetLibrary.does_asset_exist(MAP_PATH):
        level_sub.load_level(MAP_PATH)
        for actor in actor_sub.get_all_level_actors():
            actor_sub.destroy_actor(actor)
    else:
        level_sub.new_level(MAP_PATH)

    made = []

    # Ground: a big flat engine cube wearing one of our own material instances.
    ground_mi = load_asset("%s/MI_DC_Ground" % CORE_MATERIALS)
    if ground_mi is None:
        ground_mi = asset_tools().create_asset(
            "MI_DC_Ground", CORE_MATERIALS, unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(ground_mi, load_asset("%s/%s" % (CORE_MATERIALS, DEFAULT_MASTER)))
        MEL.set_material_instance_vector_parameter_value(
            ground_mi, "BaseColor", unreal.LinearColor(0.20, 0.21, 0.22, 1.0))
        MEL.set_material_instance_scalar_parameter_value(ground_mi, "Roughness", 0.85)
        save(ground_mi)

    cube = load_asset("/Engine/BasicShapes/Cube")
    ground = actor_sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, -25))
    ground.set_actor_label("Ground")
    ground.set_actor_scale3d(unreal.Vector(90.0, 90.0, 0.25))
    mesh_comp = ground.static_mesh_component
    mesh_comp.set_static_mesh(cube)
    if ground_mi is not None:
        mesh_comp.set_material(0, ground_mi)
    made.append("Ground")

    # Lighting: movable sun + real-time captured sky, so nothing needs baking.
    sun = actor_sub.spawn_actor_from_class(
        unreal.DirectionalLight, unreal.Vector(0, 0, 2000), unreal.Rotator(-42.0, 0.0, -35.0))
    sun.set_actor_label("Sun")
    sun_comp = sun.light_component
    safe_set(sun_comp, "mobility", unreal.ComponentMobility.MOVABLE)
    safe_set(sun_comp, "intensity", 6.0)
    safe_set(sun_comp, "atmosphere_sun_light", True)
    made.append("Sun")

    sky_light = actor_sub.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 1200))
    sky_light.set_actor_label("SkyLight")
    sky_comp = sky_light.light_component
    safe_set(sky_comp, "mobility", unreal.ComponentMobility.MOVABLE)
    safe_set(sky_comp, "real_time_capture", True)
    safe_set(sky_comp, "intensity", 1.0)
    made.append("SkyLight")

    atmosphere = actor_sub.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
    atmosphere.set_actor_label("SkyAtmosphere")
    made.append("SkyAtmosphere")

    start = actor_sub.spawn_actor_from_class(
        unreal.PlayerStart, unreal.Vector(-1600, 0, 150), unreal.Rotator(0, 0, 0))
    start.set_actor_label("PlayerStart")
    made.append("PlayerStart")

    # Two slots, both facing +X, far enough apart to photograph one at a time.
    slots = [
        {"id": "slot1", "loc": unreal.Vector(0, -1800, 0), "class": unreal.DCSizeClass.S,
         "order": 0, "view": 1500.0, "height": 380.0},
        {"id": "slot2", "loc": unreal.Vector(0, 1800, 0), "class": unreal.DCSizeClass.L,
         "order": 1, "view": 2700.0, "height": 650.0},
    ]
    for spec in slots:
        slot = actor_sub.spawn_actor_from_class(unreal.DCSlot, spec["loc"], unreal.Rotator(0, 0, 0))
        slot.set_actor_label(spec["id"])
        safe_set(slot, "slot_id", spec["id"])
        safe_set(slot, "size_class", spec["class"])
        safe_set(slot, "fill_order", spec["order"])
        safe_set(slot, "view_distance", spec["view"])
        safe_set(slot, "view_height", spec["height"])
        safe_set(slot, "content_yaw_offset", -90.0)
        made.append(spec["id"])

    level_sub.save_current_level()
    report["map"] = {"path": MAP_PATH, "actors": made}
    log("spike map built with %d actors" % len(made))


# --------------------------------------------------------------------------- main


def main():
    report = {"pieces": [], "problems": []}

    for folder in (CORE_MATERIALS, CORE_EMBLEMS, CORE_SCREENS, CONTENT_ROOT, "/Game/Maps"):
        unreal.EditorAssetLibrary.make_directory(folder)

    # Emblems and the sample screen image first: the masters want them as defaults.
    emblem_textures = {}
    for shape in EMBLEM_SHAPES:
        png = os.path.join(ART_EMBLEMS, "%s.png" % shape)
        if not os.path.isfile(png):
            warn("no emblem art for %s" % shape)
            continue
        tex = import_texture(png, CORE_EMBLEMS, "T_Emblem_%s" % shape)
        if tex is not None:
            emblem_textures[shape] = tex
    report["emblems"] = sorted(emblem_textures.keys())

    screen_png = os.path.join(ART_SAMPLES, "sample_screen.png")
    screen_tex = import_texture(screen_png, CORE_SCREENS, "T_DC_Screen_Sample") \
        if os.path.isfile(screen_png) else None
    report["screen_sample"] = screen_tex.get_name() if screen_tex else None

    create_material("M_DC_Master", build_master)
    create_material("M_DC_Glass", build_glass)
    create_material("M_DC_Emissive", build_emissive)
    create_material("M_DC_Screen", lambda m: build_screen(m, screen_tex))
    create_material("M_DC_Sign", lambda m: build_sign(m, emblem_textures.get("circle")))

    for piece in PIECES:
        try:
            report["pieces"].append(import_piece(piece, emblem_textures, screen_tex))
        except Exception:                                       # noqa: BLE001
            trace = traceback.format_exc()
            fail("piece %s_%s blew up:\n%s" % (piece["id"], piece["version"], trace))
            report["pieces"].append({"piece": "%s_%s" % (piece["id"], piece["version"]),
                                     "ok": False, "problems": [trace]})

    try:
        build_spike_map(report)
    except Exception:                                           # noqa: BLE001
        trace = traceback.format_exc()
        fail("spike map build blew up:\n%s" % trace)
        report["problems"].append(trace)

    unreal.EditorAssetLibrary.save_directory("/Game/DCCore", only_if_is_dirty=False, recursive=True)
    unreal.EditorAssetLibrary.save_directory("/Game/DCContent", only_if_is_dirty=False, recursive=True)

    report["ok"] = all(p.get("ok") for p in report["pieces"]) and not report["problems"]
    report["log"] = LOG

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)

    log("wrote %s" % REPORT_PATH)
    log("IMPORT_RESULT: %s" % ("OK" if report["ok"] else "FAIL"))


main()

