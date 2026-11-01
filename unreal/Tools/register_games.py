"""Run the slot-map tool on both demo maps, in one headless editor session (brief 013).

    "E:\\EpicGames\\UE_5.7\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      "E:\\DynamicContents\\unreal\\DCDemo\\DCDemo.uproject" ^
      -run=pythonscript -script="E:\\DynamicContents\\unreal\\Tools\\register_games.py" ^
      -AllowCommandletRendering -unattended -nosplash

**-AllowCommandletRendering is not optional.** A commandlet runs with rendering switched off
unless it is asked for, and this tool's whole job is to render two kinds of picture. Without
it `UDCSlotMapTool` refuses rather than writing a black PNG.

Options come in through **environment variables**, not the command line:

    DC_REGISTER_BACKEND       where to POST /games/register   (default http://127.0.0.1:8700)
    DC_REGISTER_POST          "0" to capture only and leave the files on disk
    DC_REGISTER_OUT           where the PNGs and the JSON go
    DC_REGISTER_GAMES         which maps                      (default "A,B")
    DC_REGISTER_MAP_PIXELS    the map capture's long side      (default 2048)
    DC_REGISTER_THUMB_WIDTH   a thumbnail's width              (default 960)

Not the command line, because `UPythonScriptCommandlet` does not forward one: it parses
`-Script=` with `FParse::Token`, which stops at the first space, and everything after `--`
on the editor's command line never reaches `sys.argv`. That cost one run of this tool to
find out, so the argument channel is the one that cannot be silently empty.
`unreal\\Tools\\register_games.ps1` sets them.

The same work is reachable one map at a time from the commandlet
`-run=DynamicContentsEditor.DCRegisterGameCommandlet`, and from the editor's own
Tools -> "Register this game with Dynamic Contents..." menu entry. This script exists
because loading the editor twice costs a minute more than loading it once.

It writes `unreal/_build/logs/register_games.json` - every line the tool logged, the slot
table and the backend's answer - which is what the overlay check and the report read.
"""

import json
import os
import sys

import unreal

REPO = r"E:\DynamicContents"
REPORT_PATH = os.path.join(REPO, "unreal", "_build", "logs", "register_games.json")
DEFAULT_OUT = os.path.join(REPO, "unreal", "_build", "slotmap")

MAPS = {
    "A": "/Game/Maps/GameA",
    "B": "/Game/Maps/GameB",
}


def env(name, default):
    value = os.environ.get(name, "")
    return value if value else default


def main():
    backend = env("DC_REGISTER_BACKEND", "http://127.0.0.1:8700")
    out_root = env("DC_REGISTER_OUT", DEFAULT_OUT)
    games = [g.strip().upper()
             for g in env("DC_REGISTER_GAMES", "A,B").split(",") if g.strip()]
    map_pixels = int(env("DC_REGISTER_MAP_PIXELS", "2048"))
    thumb_width = int(env("DC_REGISTER_THUMB_WIDTH", "960"))
    post = env("DC_REGISTER_POST", "1") != "0"
    unreal.log("[register_games] backend=%s games=%s post=%s out=%s"
               % (backend, ",".join(games), post, out_root))

    unknown = [g for g in games if g not in MAPS]
    if unknown:
        unreal.log_error("[register_games] unknown game(s): %s" % ", ".join(unknown))
        raise SystemExit(2)

    level_sub = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    report = {"backend": backend if post else None, "out_root": out_root, "games": {}}
    failures = []

    for game in games:
        path = MAPS[game]
        unreal.log("[register_games] loading %s" % path)
        level_sub.load_level(path)

        options = unreal.DCSlotMapOptions()
        options.set_editor_property("game", game)
        options.set_editor_property("backend", backend)
        options.set_editor_property("out_dir", os.path.join(out_root, game))
        options.set_editor_property("map_long_side_pixels", map_pixels)
        options.set_editor_property("thumb_width_pixels", thumb_width)
        options.set_editor_property("post_to_backend", post)

        result = unreal.DCSlotMapTool.register_current_level(options)

        slots = []
        for row in result.get_editor_property("slots"):
            px = row.get_editor_property("px")
            slots.append(dict(id=row.get_editor_property("id"),
                              size_class=row.get_editor_property("size_class"),
                              px=[round(px.x, 4), round(px.y, 4)],
                              thumb=row.get_editor_property("thumb_file")))
        size = result.get_editor_property("map_image_size")
        entry = dict(
            ok=bool(result.get_editor_property("ok")),
            summary=result.get_editor_property("summary"),
            message=result.get_editor_property("message"),
            map_package=result.get_editor_property("map_package"),
            map_image=result.get_editor_property("map_image_path"),
            map_image_size=[int(size.x), int(size.y)],
            json=result.get_editor_property("json_path"),
            post_status=int(result.get_editor_property("post_status")),
            post_response=result.get_editor_property("post_response"),
            slots=slots,
            log=[str(line) for line in result.get_editor_property("log")],
        )
        report["games"][game] = entry

        for line in entry["log"]:
            unreal.log("[register_games] %s" % line)
        if entry["ok"]:
            unreal.log("[register_games] %s: %s" % (game, entry["summary"]))
        else:
            unreal.log_error("[register_games] %s FAILED: %s" % (game, entry["message"]))
            failures.append(game)

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=1)
        fh.write("\n")
    unreal.log("[register_games] wrote %s" % REPORT_PATH)

    if failures:
        unreal.log_error("[register_games] %d game(s) failed: %s"
                         % (len(failures), ", ".join(failures)))
        raise SystemExit(1)


main()
