"""Report how M_DC_Sign and M_DC_Screen are actually wired, and what their instances set."""

import os

import unreal

# unreal/Tools/ -> the root of this copy of the tree.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "unreal", "_build", "logs", "check_sign_material.txt")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
LINES = []


def say(text):
    LINES.append(str(text))
    unreal.log("[sign] %s" % text)


MEL = unreal.MaterialEditingLibrary

PROPERTIES = [
    ("BaseColor", unreal.MaterialProperty.MP_BASE_COLOR),
    ("Emissive", unreal.MaterialProperty.MP_EMISSIVE_COLOR),
    ("Roughness", unreal.MaterialProperty.MP_ROUGHNESS),
    ("Opacity", unreal.MaterialProperty.MP_OPACITY),
]

for name in ("M_DC_Sign", "M_DC_Screen", "M_DC_Master"):
    path = "/Game/DCCore/Materials/%s" % name
    mat = unreal.EditorAssetLibrary.load_asset(path)
    say("==== %s ====" % name)
    if mat is None:
        say("  MISSING")
        continue
    for label, prop in PROPERTIES:
        try:
            node = MEL.get_material_property_input_node(mat, prop)
            say("  %-10s <- %s" % (label, node.get_name() if node else "NOT CONNECTED"))
        except Exception as exc:                                # noqa: BLE001
            say("  %-10s ? (%s)" % (label, exc))

for piece, emblem in (("content4_v1", "circle"), ("content1_v1", "diamond")):
    path = "/Game/DCContent/%s/MI_%s_M_Sign" % (piece, piece)
    mi = unreal.EditorAssetLibrary.load_asset(path)
    say("==== MI_%s_M_Sign ====" % piece)
    if mi is None:
        say("  MISSING")
        continue
    parent = mi.get_editor_property("parent")
    say("  parent -> %s" % (parent.get_name() if parent else "NONE"))
    try:
        colour = MEL.get_material_instance_vector_parameter_value(mi, "BrandColor")
        say("  BrandColor = %s" % colour)
    except Exception as exc:                                    # noqa: BLE001
        say("  BrandColor ? (%s)" % exc)
    try:
        tex = MEL.get_material_instance_texture_parameter_value(mi, "Emblem")
        say("  Emblem = %s" % (tex.get_name() if tex else "NONE"))
    except Exception as exc:                                    # noqa: BLE001
        say("  Emblem ? (%s)" % exc)

tex = unreal.EditorAssetLibrary.load_asset("/Game/DCCore/Emblems/T_Emblem_circle")
if tex:
    say("==== T_Emblem_circle ====")
    say("  compression = %s" % tex.get_editor_property("compression_settings"))
    say("  srgb = %s" % tex.get_editor_property("srgb"))
    say("  size = %sx%s" % (tex.blueprint_get_size_x(), tex.blueprint_get_size_y()))

with open(OUT, "w", encoding="utf-8") as handle:
    handle.write("\n".join(LINES))
