"""Clear the absolute source paths that imported assets carry in their import data.

    "<engine>\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      "unreal\\DCDemo\\DCDemo.uproject" ^
      -run=pythonscript -script="<full path to unreal\\Tools\\clear_import_paths.py>" ^
      -unattended -nosplash

Why this exists
---------------
When the editor imports an FBX or a TGA it remembers where the file came from, in the
asset's `AssetImportData`. It is only ever used to offer a re-import, so it is of no value
in a copy of this tree that someone else unzips - and if it is an absolute path it is a
path on whichever machine did the import, which is exactly the kind of thing a copy of this
tree must not carry.

Everything this project imports itself comes from `art/export*/`, and the editor stores
those as paths relative to the project (`../../../../../art/export/.../x.fbx`), which is
fine and is left alone. What is not fine is the content that came in with the engine's own
templates: the mannequin's animation set and the grid-checker texture still name a folder
on the desktop of whoever at Epic authored them.

What it does
------------
1. Reads every `.uasset` / `.umap` under the project's `Content/` **as bytes** and keeps the
   ones that hold a drive-rooted or UNC path ending in a source-file extension. The bytes
   are the only honest answer to "what is stored in this file": `extract_filenames()`
   resolves a relative path against the running editor's working directory, so through that
   API a perfectly relative path comes back looking absolute.
2. For each of those, replaces exactly the source filenames whose resolved value *is* one
   of the literal absolute strings found in the file with the bare file name. Nothing is
   ever re-imported from these, so the name is all that is worth keeping.
3. Saves the asset and re-reads the file to prove the path has gone.

Everything it looked at goes into `unreal/_build/logs/import_paths.json`. Safe to re-run:
the second run finds nothing to do.
"""
import json
import os
import re

import unreal

# unreal/Tools/ -> the root of this copy of the tree.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTENT_DIR = os.path.join(REPO, "unreal", "DCDemo", "Content")
REPORT_PATH = os.path.join(REPO, "unreal", "_build", "logs", "import_paths.json")

# What an imported source file can be. Anchoring on these keeps the byte scan from firing
# on the three or four bytes of compressed mesh data that happen to read as "o:/bRl.v-".
SOURCE_EXTENSIONS = ("fbx", "obj", "abc", "usd", "usda", "usdc", "gltf", "glb", "dae",
                     "tga", "png", "psd", "bmp", "jpg", "jpeg", "exr", "tif", "tiff",
                     "hdr", "dds", "wav", "aif", "aiff", "mp3", "ogg", "flac")

# A drive-rooted path (C:\..., C:/...) or a UNC one (\\host\...), as stored, ending in one
# of the extensions above.
ABSOLUTE_BYTES = re.compile(
    (r"(?:[A-Za-z]:[\\/]|\\\\)[A-Za-z0-9_\-.,() \\/]{4,200}\.(?:" +
     "|".join(SOURCE_EXTENSIONS) + r")").encode("ascii"), re.IGNORECASE)

# The same shape, for a string.
ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//)")

LOG = []


def log(msg):
    line = "[import_paths] %s" % msg
    LOG.append(line)
    unreal.log(line)


def warn(msg):
    line = "[import_paths] WARNING %s" % msg
    LOG.append(line)
    unreal.log_warning(line)


def norm(path):
    return str(path).replace("\\", "/").lower()


def stored_absolute_paths(file_path):
    """The literal drive-rooted paths this asset file holds, as text."""
    with open(file_path, "rb") as handle:
        data = handle.read()
    return sorted({m.decode("latin-1") for m in ABSOLUTE_BYTES.findall(data)})


def candidates():
    """(package name, asset name, file path, the absolute paths stored in it)."""
    out = []
    scanned = 0
    for dirpath, _dirnames, filenames in os.walk(CONTENT_DIR):
        for name in filenames:
            if not (name.endswith(".uasset") or name.endswith(".umap")):
                continue
            scanned += 1
            path = os.path.join(dirpath, name)
            found = stored_absolute_paths(path)
            if not found:
                continue
            rel = os.path.relpath(path, CONTENT_DIR).replace("\\", "/")
            package = "/Game/" + rel.rsplit(".", 1)[0]
            out.append((package, package.rsplit("/", 1)[-1], path, found))
    log("%d asset file(s) scanned on disk, %d hold an absolute source path"
        % (scanned, len(out)))
    return sorted(out)


def clean_one(package, asset_name, file_path, stored):
    """Returns a row for the report."""
    row = {"package": package, "stored": stored, "status": "", "resolved_before": [],
           "resolved_after": [], "still_stored": []}
    asset = unreal.EditorAssetLibrary.load_asset("%s.%s" % (package, asset_name))
    if asset is None:
        row["status"] = "could not load"
        return row
    try:
        import_data = asset.get_editor_property("asset_import_data")
    except Exception as exc:                                        # noqa: BLE001
        row["status"] = "no asset_import_data (%s)" % exc
        return row
    if import_data is None:
        row["status"] = "no import data"
        return row

    wanted = {norm(s) for s in stored}
    before = [str(name) for name in import_data.extract_filenames()]
    row["resolved_before"] = before

    changed = 0
    for index, name in enumerate(before):
        if norm(name) not in wanted:
            continue                      # a relative path the editor resolved for us
        import_data.scripted_add_filename(os.path.basename(name.replace("\\", "/")),
                                          index, "")
        changed += 1
    if not changed:
        row["status"] = "nothing matched the stored path"
        return row

    unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
    row["resolved_after"] = [str(name) for name in import_data.extract_filenames()]
    row["still_stored"] = stored_absolute_paths(file_path)
    row["status"] = "cleaned" if not row["still_stored"] else "STILL THERE after saving"
    return row


def main():
    rows = []
    cleaned = failed = 0
    for package, asset_name, file_path, stored in candidates():
        row = clean_one(package, asset_name, file_path, stored)
        rows.append(row)
        if row["status"] == "cleaned":
            cleaned += 1
            log("%-62s %s -> %s" % (package, stored, row["resolved_after"]))
        elif row["status"] == "nothing matched the stored path":
            # Three or four bytes of compressed data that read as a path. Not an asset
            # problem, and the guard over the export checks the real shapes anyway.
            log("%-62s no source file matches %s - left alone" % (package, stored))
        else:
            failed += 1
            warn("%-62s %s (%s)" % (package, row["status"], stored))

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"looked_at": len(rows), "cleaned": cleaned, "failed": failed,
                   "assets": rows, "log": LOG}, handle, indent=1)
        handle.write("\n")
    log("cleaned %d, failed %d; report -> %s" % (cleaned, failed, REPORT_PATH))
    if failed:
        warn("%d asset(s) still hold an absolute path" % failed)


main()
