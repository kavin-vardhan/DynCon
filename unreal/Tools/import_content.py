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
  /Game/Maps/Spike            the spike map: ground, lights, player start, one ADCSlot per
                              size class (S / L / T)

Which pieces, and what chunk each one gets, is unreal/Tools/chunk_ids.json - a frozen table,
because a chunk id ends up in the pack's file name.

Units: the art's FBX is written in centimetres (art/blender/dc_kit.py, FBX_UNIT_SCALE), so a
piece imports at true size with the importer's uniform scale left at 1 and nothing scaling it
at spawn. The report below checks the imported bounds against the manifest's bounds_cm rather
than assuming it.

Everything it checked goes into unreal/_build/logs/import_report.json - bounds in centimetres,
socket names / locations / rotations as imported, material slot names, and a read-back of the
Blueprint defaults.
"""

import json
import os
import sys
import traceback

import unreal

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import core_extras as CE      # noqa: E402

# --------------------------------------------------------------------------- configuration

REPO = r"E:\DynamicContents"
ART_EXPORT = os.path.join(REPO, "art", "export")
ART_EMBLEMS = os.path.join(REPO, "art", "emblems")
ART_SAMPLES = os.path.join(REPO, "art", "samples")
CHUNK_TABLE = os.path.join(REPO, "unreal", "Tools", "chunk_ids.json")
REPORT_PATH = os.path.join(REPO, "unreal", "_build", "logs", "import_report.json")

CORE_MATERIALS = "/Game/DCCore/Materials"
CORE_EMBLEMS = "/Game/DCCore/Emblems"
CORE_SCREENS = "/Game/DCCore/Screens"
CONTENT_ROOT = "/Game/DCContent"
MAP_PATH = "/Game/Maps/Spike"

EMBLEM_SHAPES = ("circle", "triangle", "square", "diamond", "star", "ring", "chevron", "hexagon")

def hex_to_srgb(text):
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def load_pieces():
    """The frozen pack table: which pieces exist, and which cook chunk each one owns."""
    with open(CHUNK_TABLE, "r", encoding="utf-8") as handle:
        table = json.load(handle)
    out = []
    for row in table["packs"]:
        out.append({
            "id": row["id"],
            "version": row["version"],
            "chunk_id": int(row["chunk_id"]),
            "brand_srgb": hex_to_srgb(row["brand_hex"]),
            "brand_hex": row["brand_hex"],
            "emblem": row["emblem"],
        })
    return out


PIECES = load_pieces()

# Which master material each of the 13 allowed material slots instances.
MASTER_FOR_SLOT = {
    "M_Glass": "M_DC_Glass",
    "M_LightEmissive": "M_DC_Emissive",
    "M_Screen": "M_DC_Screen",
    "M_Sign": "M_DC_Sign",
}
DEFAULT_MASTER = "M_DC_Master"

ROLES = ("Shell", "Door", "Switch", "Screen", "Sign")

# The "nothing is booked here" placeholder is a shell and nothing else - no door, no sign, no
# screen, no brand (content_assets_spec_v1 section 3).
PLACEHOLDER_IDS = ("default",)

# The FBX is in centimetres, so a 6.5 m cabin imports as 650 cm and nothing has to scale it.
# (It has to be done that way round: the parts are imported in their own local space so that
# each part's pivot lands on its socket, and in that mode FFbxImporter::ComputeTotalMatrix
# returns the identity and throws the importer's own scene scale away - which is why brief 004
# had to scale the shell at spawn instead. dc_kit.FBX_UNIT_SCALE is the fix.)
UNIT_SCALE = 1.0

# Blender's export leaves the sockets with a 90 degree roll: Blender writes the FBX in its
# Y-up convention and UE's importer converts the mesh data back but not the socket rotations.
# Left alone, every part hangs off its socket lying flat - the sign and the screen are then
# edge-on (a bright hairline instead of a panel) and the door leaf lies on the floor. The
# rotations are therefore rebuilt from the manifest, which is the authority anyway.
#
# Blender -> UE is a mirror in Y, so a rotation about Z changes sign and nothing else: every
# socket in every manifest is a pure Z rotation, which keeps this to one line (and
# check_socket_rotations below fails loudly if that ever stops being true).
def ue_yaw_from_blender(rot_deg):
    return -float(rot_deg[2])


# Emissive strengths in the manifest are tuned for the Blender previews (Cycles + Filmic).
# Unreal's tone mapper reaches white sooner, and a light fitting that reads as a warm glow in
# a preview reads as a blown hole on a booth screen, so they come in at half strength.
EMISSIVE_UE_SCALE = 0.5

# The sign is lit like any other surface; the glow is only there so it still reads when the
# facade is in shade. Brief 004 ran it at 1.0 (fully emissive) while chasing what turned out
# to be the socket roll above, which made the plate a flat slab of colour.
SIGN_GLOW = 0.45

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

    # The sign plate is a 2:1 quad with UVs 0-1, and the emblems are square, so sampling the
    # emblem straight off the quad's UVs would stretch it to twice its width. Scaling U by 2
    # and sliding it left puts a square emblem on the left half and leaves the right half
    # plain brand colour - the same layout as the Blender previews. The emblem textures are
    # imported with clamped addressing (see import_texture), so outside that half the
    # texture's transparent border is what gets sampled and the lerp returns BrandColor.
    uvs = MEL.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -1400, 140)
    safe_set(uvs, "u_tiling", 2.0)
    safe_set(uvs, "v_tiling", 1.0)
    uv_shift = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant2Vector, -1400, 280)
    safe_set(uv_shift, "r", -0.12)
    safe_set(uv_shift, "g", 0.0)
    uv_add = MEL.create_material_expression(mat, unreal.MaterialExpressionAdd, -1150, 180)
    connect_expr(uvs, "", uv_add, "A")
    connect_expr(uv_shift, "", uv_add, "B")
    connect_expr(uv_add, "", emblem, "UVs")

    lerp = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -500, -60)
    connect_expr(brand, "", lerp, "A")
    connect_expr(emblem_colour, "", lerp, "B")
    connect_expr(emblem, "A", lerp, "Alpha")
    connect_prop(lerp, "", unreal.MaterialProperty.MP_BASE_COLOR)

    # A lift, not a light source: the plate is lit like any other surface, and the glow is
    # only there so the sign still reads when the facade is in shade.
    glow = _scalar_param(mat, "SignGlow", SIGN_GLOW, -900, 420)
    mul = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -250, 220)
    connect_expr(lerp, "", mul, "A")
    connect_expr(glow, "", mul, "B")
    connect_prop(mul, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    rough = _scalar_param(mat, "Roughness", 0.46, -900, 540)
    connect_prop(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)


# --------------------------------------------------------------------------- texture import


def import_texture(filename, destination_path, asset_name, clamp=False):
    path = "%s/%s" % (destination_path, asset_name)
    existing = load_asset(path)
    if existing is not None:
        if clamp:
            set_clamped(existing)
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
    if clamp:
        set_clamped(tex)
    save(tex)
    return tex


def set_clamped(tex):
    """Clamp, not wrap: the sign shifts the emblem's UVs to put it on the left half of the
    plate, and with wrapping the right half would show a second copy instead of plain brand
    colour."""
    safe_set(tex, "address_x", unreal.TextureAddress.TA_CLAMP)
    safe_set(tex, "address_y", unreal.TextureAddress.TA_CLAMP)
    save(tex)


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


def rename_imported_meshes(imported_paths, piece_name, manifest):
    """
    FbxFactory names a multi-mesh import <fbx base>_<node name>, so the shell arrives as
    content4_v1_SM_content4_v1_Shell. Put the names back to what the spec says the pack
    ships: SM_<id>_<v>_<Role>.

    A one-mesh FBX (the placeholder piece) is the exception: with nothing to disambiguate,
    the factory names the asset after the file and the node name is lost, so the manifest -
    which knows the piece has exactly one object and what its role is - decides.
    """
    roles_in_manifest = [o["role"] for o in manifest.get("objects", [])]

    def rename_to_role(package, role):
        folder, asset_name = package.rsplit("/", 1)
        wanted = "SM_%s_%s" % (piece_name, role)
        target = "%s/%s" % (folder, wanted)
        if asset_name != wanted:
            if unreal.EditorAssetLibrary.does_asset_exist(target):
                unreal.EditorAssetLibrary.delete_asset(target)
            if not unreal.EditorAssetLibrary.rename_asset(package, target):
                warn("could not rename %s -> %s" % (package, target))
        return load_asset(target)

    found = {}
    unmatched = []
    for object_path in imported_paths:
        package = object_path.split(".")[0]
        asset_name = package.rsplit("/", 1)[1]
        role = next((r for r in ROLES if asset_name.endswith("_%s" % r)), None)
        if role is None:
            unmatched.append(package)
            continue
        asset = rename_to_role(package, role)
        if asset is not None:
            found[role] = asset

    if len(unmatched) == 1 and len(roles_in_manifest) == 1 and not found:
        asset = rename_to_role(unmatched[0], roles_in_manifest[0])
        if asset is not None:
            found[roles_in_manifest[0]] = asset
            log("%s: one-mesh import, named from the manifest as %s"
                % (piece_name, roles_in_manifest[0]))
    elif unmatched:
        warn("%s: %d imported object(s) matched no role: %r" % (piece_name, len(unmatched), unmatched))

    return found


def mesh_bounds_cm(mesh):
    """(min, max) of the imported asset in its own space, centimetres."""
    box = mesh.get_bounding_box()
    return ([box.min.x, box.min.y, box.min.z], [box.max.x, box.max.y, box.max.z])


def mesh_size_cm(mesh):
    lo, hi = mesh_bounds_cm(mesh)
    return tuple(hi[i] - lo[i] for i in range(3))


def check_mesh_units(meshes, manifest):
    """
    Every imported mesh against the bounds its manifest entry declares, in centimetres.

    This is the proof that the art now exports at engine scale: each part is imported in its
    own local space, so the asset's bounding box is the manifest's `bounds_local_cm` with Y
    mirrored (Blender -Y is UE +Y). Nothing scales anything at spawn, so a mismatch here is a
    mismatch in the game.
    """
    by_role = {o["role"]: o for o in manifest.get("objects", [])}
    rows = {}
    worst = 0.0
    for role, mesh in sorted(meshes.items()):
        entry = by_role.get(role)
        if entry is None or "bounds_local_cm" not in entry:
            rows[role] = {"checked": False, "why": "no bounds_local_cm in the manifest"}
            continue
        blo = entry["bounds_local_cm"]["min"]
        bhi = entry["bounds_local_cm"]["max"]
        want_min = [blo[0], -bhi[1], blo[2]]
        want_max = [bhi[0], -blo[1], bhi[2]]
        got_min, got_max = mesh_bounds_cm(mesh)
        err = max([abs(got_min[i] - want_min[i]) for i in range(3)]
                  + [abs(got_max[i] - want_max[i]) for i in range(3)])
        worst = max(worst, err)
        rows[role] = {
            "checked": True,
            "imported_min_cm": [round(c, 2) for c in got_min],
            "imported_max_cm": [round(c, 2) for c in got_max],
            "manifest_min_cm": [round(c, 2) for c in want_min],
            "manifest_max_cm": [round(c, 2) for c in want_max],
            "size_cm": [round(got_max[i] - got_min[i], 2) for i in range(3)],
            "worst_error_cm": round(err, 3),
        }
    return {"per_mesh": rows, "worst_error_cm": round(worst, 3),
            "ok": all(r.get("checked") for r in rows.values()) and worst <= 0.5}


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
        rot = socket.get_editor_property("relative_rotation")
        out[name] = {"imported_as": candidate,
                     "loc_cm": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
                     "rot_pyr": [round(rot.pitch, 1), round(rot.yaw, 1), round(rot.roll, 1)]}
    return out


def fix_socket_rotations(mesh, manifest, manifest_names):
    """Rebuild every socket's rotation from the manifest. See UNIT_SCALE / ue_yaw_from_blender
    above for why the imported ones cannot be trusted; returns what was changed."""
    by_name = {s["name"]: s for s in manifest.get("sockets", [])}
    fixed = []
    odd = []
    for name in manifest_names:
        _, socket = resolve_socket(mesh, name)
        if socket is None:
            continue
        want = by_name[name]["rotation_euler_deg"]
        if abs(want[0]) > 1e-3 or abs(want[1]) > 1e-3:
            # Only pure-Z socket rotations are authored, and only pure-Z ones convert this
            # simply. Say so rather than silently writing the wrong thing.
            odd.append({"socket": name, "rotation_euler_deg": want})
            continue
        before = socket.get_editor_property("relative_rotation")
        after = unreal.Rotator(0.0, 0.0, ue_yaw_from_blender(want))
        if (abs(before.pitch - after.pitch) > 1e-3 or abs(before.yaw - after.yaw) > 1e-3
                or abs(before.roll - after.roll) > 1e-3):
            safe_set(socket, "relative_rotation", after)
            fixed.append({"socket": name,
                          "was": [round(before.pitch, 2), round(before.yaw, 2), round(before.roll, 2)],
                          "now": [round(after.pitch, 2), round(after.yaw, 2), round(after.roll, 2)]})
    if odd:
        warn("%s has %d socket(s) with a non-Z rotation, left as imported: %r"
             % (mesh.get_name(), len(odd), odd))
    save(mesh)
    return {"rotations_rewritten": len(fixed), "detail": fixed, "unconverted": odd}


def check_sockets(mesh, manifest, manifest_names):
    """
    Confirm that every socket landed where the manifest says, in centimetres, with the
    rotation the manifest asks for. This is the one assumption the runtime makes about an
    imported pack, so it is checked rather than believed.
    """
    by_name = {s["name"]: s for s in manifest.get("sockets", [])}
    worst_pos = 0.0
    worst_rot = 0.0
    checked = 0
    missing = []
    # UE's FBX importer only turns empties named SOCKET_* into sockets. The manifest also
    # carries markers that are not sockets at all (VOLUME_Interior, the dwell-measuring box),
    # and those are not expected to arrive.
    skipped = [n for n in manifest_names if not n.startswith("SOCKET_")]
    for name in manifest_names:
        if name in skipped:
            continue
        _, socket = resolve_socket(mesh, name)
        if socket is None:
            missing.append(name)
            continue
        loc = socket.get_editor_property("relative_location")
        want = by_name[name]["location_cm"]
        # Blender -Y is UE +Y: the FBX conversion mirrors Y, so Y is compared negated.
        for got, expect in ((loc.x, want[0]), (loc.y, -want[1]), (loc.z, want[2])):
            worst_pos = max(worst_pos, abs(got - expect))
        rot = socket.get_editor_property("relative_rotation")
        want_yaw = ue_yaw_from_blender(by_name[name]["rotation_euler_deg"])
        delta = abs(((rot.yaw - want_yaw) + 180.0) % 360.0 - 180.0)
        worst_rot = max(worst_rot, delta, abs(rot.pitch), abs(rot.roll))
        checked += 1
    return {"sockets_checked": checked,
            "missing": missing,
            "not_sockets_in_ue": skipped,
            "worst_axis_error_cm": round(worst_pos, 3),
            "worst_angle_error_deg": round(worst_rot, 3)}


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
                mi, "EmissiveStrength",
                float(entry.get("emissive_strength", 4.0)) * EMISSIVE_UE_SCALE)

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

    door = manifest.get("door") or {}      # the placeholder piece has no door at all
    brand_linear = [srgb_to_linear(c) for c in piece["brand_srgb"]]

    safe_set(cdo, "content_id", piece["id"])
    safe_set(cdo, "content_version", piece["version"])
    safe_set(cdo, "state_schema_version", int(manifest.get("schema_version", 1)))
    safe_set(cdo, "content_unit_scale", UNIT_SCALE)
    safe_set(cdo, "shell_mesh", meshes.get("Shell"))
    safe_set(cdo, "door_mesh", meshes.get("Door"))
    safe_set(cdo, "switch_mesh", meshes.get("Switch"))
    safe_set(cdo, "screen_mesh", meshes.get("Screen"))
    safe_set(cdo, "sign_mesh", meshes.get("Sign"))
    safe_set(cdo, "brand_color", linear_color(brand_linear))
    safe_set(cdo, "emblem_texture", emblem_tex)
    safe_set(cdo, "screen_image", screen_tex)
    safe_set(cdo, "door_open_degrees", float(door.get("open_degrees", 90)))
    # Negated on purpose: the manifest's open_sign is a Blender Z rotation and the Blender to
    # UE conversion mirrors Y, so the same swing is the opposite yaw in the engine. A door
    # that opened outwards through its own frame would be the giveaway.
    safe_set(cdo, "door_open_sign", -int(door.get("open_sign", 1)))

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
            "door_open_sign": int(rcdo.get_editor_property("door_open_sign")),
            # UE's Python bindings drop the b prefix from a bool UPROPERTY.
            "light_a_on": bool(rcdo.get_editor_property("light_a_on")),
            "light_b_on": bool(rcdo.get_editor_property("light_b_on")),
            "light_a_intensity": float(rcdo.get_editor_property("light_a_intensity")),
            "light_b_intensity": float(rcdo.get_editor_property("light_b_intensity")),
            "light_a_radius": float(rcdo.get_editor_property("light_a_radius")),
            "light_b_radius": float(rcdo.get_editor_property("light_b_radius")),
            "lights_cast_shadows": bool(rcdo.get_editor_property("lights_cast_shadows")),
            "light_b_casts_shadows": bool(rcdo.get_editor_property("light_b_casts_shadows")),
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

    expected_cm = manifest["bounds_cm"]["size"]
    manifest_sockets = [s["name"] for s in manifest.get("sockets", [])]
    record["units"] = manifest.get("units")

    imported = import_fbx(fbx, pack_path, UNIT_SCALE)
    record["imported_object_paths"] = imported
    meshes = rename_imported_meshes(imported, name, manifest)

    if "Shell" not in meshes:
        record["problems"].append("no shell mesh after import; imported=%r" % imported)
        fail(record["problems"][-1])
        return record

    # The FBX is in centimetres, so the assets are too and nothing scales them: the read-back
    # below is the proof of the unit change, not a formality. Every mesh is checked, not just
    # the shell - a part that came in at the wrong scale would sit on its socket looking
    # almost right.
    size = mesh_size_cm(meshes["Shell"])
    record["shell_size_cm_imported"] = [round(v, 2) for v in size]
    record["piece_size_cm_expected"] = [round(v, 2) for v in expected_cm]
    record["unit_scale_used"] = UNIT_SCALE
    record["mesh_units"] = check_mesh_units(meshes, manifest)
    record["scale_ok"] = record["mesh_units"]["ok"]
    if not record["scale_ok"]:
        warn("%s: worst mesh bounds error %.3f cm; detail %r"
             % (name, record["mesh_units"]["worst_error_cm"], record["mesh_units"]["per_mesh"]))

    record["socket_fix"] = fix_socket_rotations(meshes["Shell"], manifest, manifest_sockets)
    record["socket_check"] = check_sockets(meshes["Shell"], manifest, manifest_sockets)

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

    placeholder = manifest["id"] in PLACEHOLDER_IDS
    needed_roles = ("Shell",) if placeholder else ROLES
    record["missing_roles"] = [r for r in needed_roles if r not in meshes]

    sc = record["socket_check"]
    record["sockets_ok"] = (not sc["missing"]
                            and sc["worst_axis_error_cm"] <= 1.0
                            and sc["worst_angle_error_deg"] <= 0.5)

    record["ok"] = (blueprint is not None and label is not None and record["scale_ok"]
                    and record["materials_ok"] and record["sockets_ok"]
                    and not record["missing_roles"] and bool(readback.get("shell_mesh")))
    found_sockets = sum(1 for v in record["sockets"].values() if v)
    log("piece %-14s ok=%-5s meshes=%d sockets=%d/%d (%d rotations fixed) "
        "size=%.0fx%.0fx%.0f cm err=%.2f cm / %.2f deg"
        % (name, record["ok"], len(meshes), found_sockets, len(manifest_sockets),
           record["socket_fix"]["rotations_rewritten"],
           size[0], size[1], size[2],
           sc["worst_axis_error_cm"], sc["worst_angle_error_deg"]))
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
    # 160 m square: big enough that the camera standing a long way back from the tall slot
    # still has ground under the horizon.
    ground.set_actor_scale3d(unreal.Vector(160.0, 160.0, 0.25))
    mesh_comp = ground.static_mesh_component
    mesh_comp.set_static_mesh(cube)
    if ground_mi is not None:
        mesh_comp.set_material(0, ground_mi)
    made.append("Ground")

    # Lighting: movable sun + real-time captured sky, so nothing needs baking.
    #
    # Mid-afternoon, not sunset, and coming over the camera's shoulder. Brief 004's sun sat
    # 42 degrees up and behind the slots, which backlit every piece, pushed auto-exposure up
    # and made the facades look blown even before the content's own lights were counted.
    # The camera stands off along a slot's +X, so a yaw of 150 puts the sun in front of it.
    # (unreal.Rotator is (roll, pitch, yaw) positionally - brief 004 passed -42 as the roll and
    # left the pitch at zero, which is why its sun sat on the horizon. Keywords from now on.)
    sun = actor_sub.spawn_actor_from_class(
        unreal.DirectionalLight, unreal.Vector(0, 0, 2000),
        unreal.Rotator(roll=0.0, pitch=-48.0, yaw=150.0))
    sun.set_actor_label("Sun")
    sun_comp = sun.light_component
    safe_set(sun_comp, "mobility", unreal.ComponentMobility.MOVABLE)
    safe_set(sun_comp, "intensity", 5.0)
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

    # One slot per size class, all facing +X, far enough apart that the camera lined up on one
    # never catches another. The run picks the slot whose class matches the piece.
    slots = [
        {"id": "slot_s", "loc": unreal.Vector(0, -3000, 0), "class": unreal.DCSizeClass.S,
         "order": 0, "view": 1500.0, "height": 380.0},
        {"id": "slot_l", "loc": unreal.Vector(0, 0, 0), "class": unreal.DCSizeClass.L,
         "order": 1, "view": 2700.0, "height": 650.0},
        {"id": "slot_t", "loc": unreal.Vector(0, 3400, 0), "class": unreal.DCSizeClass.T,
         "order": 2, "view": 4200.0, "height": 1100.0},
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

    # Start the content folder from scratch. A pack folder left over from an earlier import
    # can carry an asset that no longer has a source - a mesh for a role a piece has dropped,
    # or (the reason this is here) a shell still built at the old units - and it would be
    # cooked into the pack regardless. The base game's /Game/DCCore is left alone.
    if unreal.EditorAssetLibrary.does_directory_exist(CONTENT_ROOT):
        log("clearing %s before importing" % CONTENT_ROOT)
        unreal.EditorAssetLibrary.delete_directory(CONTENT_ROOT)

    for folder in (CORE_MATERIALS, CORE_EMBLEMS, CORE_SCREENS, CONTENT_ROOT, "/Game/Maps"):
        unreal.EditorAssetLibrary.make_directory(folder)

    # Emblems and the sample screen image first: the masters want them as defaults.
    emblem_textures = {}
    for shape in EMBLEM_SHAPES:
        png = os.path.join(ART_EMBLEMS, "%s.png" % shape)
        if not os.path.isfile(png):
            warn("no emblem art for %s" % shape)
            continue
        tex = import_texture(png, CORE_EMBLEMS, "T_Emblem_%s" % shape, clamp=True)
        if tex is not None:
            emblem_textures[shape] = tex
    report["emblems"] = sorted(emblem_textures.keys())

    screen_png = os.path.join(ART_SAMPLES, "sample_screen.png")
    screen_tex = import_texture(screen_png, CORE_SCREENS, "T_DC_Screen_Sample") \
        if os.path.isfile(screen_png) else None
    report["screen_sample"] = screen_tex.get_name() if screen_tex else None

    # The set the screen cycles through, and the Player's "use" button. Defined in
    # core_extras so make_maps.py produces exactly the same two things (brief 016).
    report["core_extras"] = CE.build_all()

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
    report["piece_count"] = len(report["pieces"])
    report["failed_pieces"] = [p["piece"] for p in report["pieces"] if not p.get("ok")]
    report["log"] = LOG

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)

    # The units proof, in one table: what the manifest says in centimetres against what came
    # back off the imported asset.
    log("---- units: imported asset vs manifest, centimetres ----")
    log("%-14s %-7s %-24s %-10s %-10s %s"
        % ("piece", "meshes", "shell size cm", "mesh err", "socket err", "socket angle err"))
    for p in report["pieces"]:
        got = p.get("shell_size_cm_imported")
        mu = p.get("mesh_units") or {}
        if not got:
            log("%-14s (not imported)" % p["piece"])
            continue
        sc = p.get("socket_check", {})
        log("%-14s %-7d %-24s %-10s %-10s %s"
            % (p["piece"], len(mu.get("per_mesh", {})),
               "%.1f x %.1f x %.1f" % tuple(got),
               "%.3f" % mu.get("worst_error_cm", -1),
               "%.3f" % sc.get("worst_axis_error_cm", -1),
               "%.3f deg (%d sockets, %d fixed)"
               % (sc.get("worst_angle_error_deg", -1), sc.get("sockets_checked", 0),
                  (p.get("socket_fix") or {}).get("rotations_rewritten", 0))))

    log("wrote %s" % REPORT_PATH)
    log("IMPORT_RESULT: %s  (%d/%d pieces ok)"
        % ("OK" if report["ok"] else "FAIL",
           report["piece_count"] - len(report["failed_pieces"]), report["piece_count"]))


main()

