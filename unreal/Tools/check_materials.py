"""Print what each imported pack mesh actually has in its material slots, as saved on disk.

    UnrealEditor-Cmd.exe <project> -run=pythonscript -script=.../check_materials.py -unattended
"""

import unreal

OUT = r"E:\DynamicContents\unreal\_build\logs\check_materials.txt"
LINES = []


def say(text):
    LINES.append(text)
    unreal.log("[check] %s" % text)


PIECES = ("content4_v1", "content1_v1")
ROLES = ("Shell", "Door", "Switch", "Screen", "Sign")

for piece in PIECES:
    say("==== %s ====" % piece)
    for role in ROLES:
        path = "/Game/DCContent/%s/SM_%s_%s" % (piece, piece, role)
        if not unreal.EditorAssetLibrary.does_asset_exist(path):
            say("  %s MISSING" % path)
            continue
        mesh = unreal.EditorAssetLibrary.load_asset(path)
        slots = mesh.get_editor_property("static_materials")
        for index, entry in enumerate(slots):
            name = str(entry.get_editor_property("imported_material_slot_name"))
            material = entry.get_editor_property("material_interface")
            say("  %-8s slot %d %-20s -> %s" % (role, index, name, material.get_name() if material else "NONE"))

    mi_path = "/Game/DCContent/%s/MI_%s_M_Wall" % (piece, piece)
    if unreal.EditorAssetLibrary.does_asset_exist(mi_path):
        mi = unreal.EditorAssetLibrary.load_asset(mi_path)
        parent = mi.get_editor_property("parent")
        say("  MI_%s_M_Wall parent -> %s" % (piece, parent.get_name() if parent else "NONE"))


with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write('\n'.join(LINES))
unreal.log('[check] wrote %s' % OUT)

