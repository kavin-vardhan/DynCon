"""The guard on the English-only ruling: no Japanese anywhere in what ships or displays.

**Kavin ruled on 2026-11-02 that the demo is English only**, because a machine-drafted
Japanese line that nobody had reviewed was too risky to put in front of visitors in Tokyo.
Brief 018E took every Japanese string out of the portal, the game, the server's config and
the booth's scripts. This test is what keeps them out: it reads every text file in the
folders that ship or display and fails if a single Hiragana, Katakana, CJK ideograph or
full-width form has come back.

It lives in the server's test run because that is the one suite that runs on every brief
(`server\\.venv\\Scripts\\python.exe -m pytest`), and because it needs nothing but the
repository — no browser, no server, no Unreal.

**What is deliberately not scanned**, and why:

* `DemoPlan/`, `docs/handoffs/`, the older lines of `specs/DECISIONS.md` and the commit
  messages. History stays as history (CLAUDE.md rule 6): plan v6 *does* ask for every
  string in two languages, and the record of that is what the ruling overrides.
* `_shots/` folders, `*.log`, and anything a build or a cook generates. They are the output
  of a past run, not what the booth draws; the exit tests rebuild them.
* binaries — images, fonts, paks, minidumps, pipeline caches. Unreal's generated
  `Default.rc2.res` and shader archives contain CJK bytes that come from the engine, not
  from us.
"""
from __future__ import annotations

from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent

# CJK punctuation (and the ideographic space) · Hiragana · Katakana · CJK ideographs and
# extension A · full-width and half-width forms. A character in any of these is one no
# English-only demo should contain.
#
# Written as numbers, not as a character class with the endpoints in it: a file that is
# testing for Japanese must not itself contain any, or it fails on its own source.
JAPANESE_RANGES = ((0x3000, 0x303F), (0x3040, 0x309F), (0x30A0, 0x30FF),
                   (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))


def japanese_in(text: str) -> list[str]:
    """Every Japanese character in a line, in the order it appears."""
    return [ch for ch in text
            if any(low <= ord(ch) <= high for low, high in JAPANESE_RANGES)]

# Everything a visitor or a staffer can end up looking at, plus the code that draws it.
SCAN = [
    "portal",
    "booth",
    "server/dcserver",
    "server/tests",
    "server/tools",
    "server/config",
    "server/README.md",
    "server/run_local.ps1",
    "unreal/DCDemo/Plugins/DynamicContents/Source",
    "unreal/DCDemo/Config",          # the plugin has no Config/ of its own
    "unreal/Tools",
    "unreal/README.md",
    "art/blender",
    "art/tools",
    "art/build.ps1",
    "portal/README.md",
    "booth/README.md",
    "README.md",
    "specs/portal_spec_v1.md",
    "specs/server_spec_v1.md",
    "specs/unreal_spec_v1.md",
    "specs/content_assets_spec_v1.md",
]

# A generated or binary file is not something anybody wrote, and some of them carry CJK
# bytes that came out of the engine.
SKIP_DIRS = {"_shots", "__pycache__", ".venv", ".pytest_cache", "Binaries", "Intermediate",
             "Saved", "DerivedDataCache", "_build", "_packs", "node_modules"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".woff", ".woff2", ".ttf",
                 ".otf", ".blend", ".blend1", ".fbx", ".glb", ".pak", ".utoc", ".ucas",
                 ".uasset", ".umap", ".dcpack", ".zip", ".exe", ".dll", ".pdb", ".lib",
                 ".obj", ".res", ".dmp", ".bin", ".sqlite", ".db", ".log", ".mp4",
                 ".ushaderbytecode", ".stinfo", ".upipelinecache", ".drawio"}


def files_to_scan() -> list[Path]:
    found: list[Path] = []
    for entry in SCAN:
        path = REPO_DIR / entry
        if path.is_file():
            found.append(path)
            continue
        if not path.is_dir():
            continue
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            if SKIP_DIRS & set(child.relative_to(REPO_DIR).parts):
                continue
            if child.suffix.lower() in SKIP_SUFFIXES:
                continue
            found.append(child)
    return sorted(set(found))


def test_the_sweep_finds_something_to_sweep() -> None:
    """A scan that silently matched nothing would pass for ever and prove nothing."""
    files = files_to_scan()
    assert len(files) > 60, f"only {len(files)} file(s) scanned - the list has gone stale"
    names = {path.name for path in files}
    for expected in ("strings.js", "style.css", "index.html", "demo.json",
                     "DCStatusHud.cpp", "DCXray.cpp", "portal_exit_test.py"):
        assert expected in names, f"{expected} is not being scanned any more"


def test_no_japanese_anywhere_in_what_ships_or_displays() -> None:
    offenders: list[str] = []
    for path in files_to_scan():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue                      # not a text file after all
        for number, line in enumerate(text.splitlines(), start=1):
            found = japanese_in(line)
            if found:
                where = path.relative_to(REPO_DIR).as_posix()
                offenders.append(f"{where}:{number}: {len(found)} character(s)"
                                 f"  in {line.strip()[:90]!r}")
    assert not offenders, ("the demo is English only (Kavin's ruling, 2026-11-02) and "
                           f"{len(offenders)} line(s) have Japanese in them:\n"
                           + "\n".join(offenders[:40]))
