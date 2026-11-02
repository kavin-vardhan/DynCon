"""Where things are, worked out rather than written down.

Every script in this tree that needs to find the tree, the interpreter or the packaged game
asks here, so that a copy of it runs wherever it is unzipped, on a machine nobody has set up.

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import dc_paths

    dc_paths.repo_root()      the root of this copy of the tree
    dc_paths.demo_python()    the interpreter the server and the helpers run on
    dc_paths.game_exe()       the packaged game's launcher exe
    dc_paths.log_dir()        where a run may write its logs

Nothing here names a folder on the machine the tree was written on.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

#: The root of this copy of the tree: tools/ sits directly under it.
REPO_ROOT = Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    return REPO_ROOT


def demo_python(explicit: str | os.PathLike[str] | None = None) -> Path:
    """The interpreter the server, the tests and the helpers run on.

    In order: an explicit path; ``DC_PYTHON``; ``python\\python.exe`` carried inside this
    copy of the tree; a development virtual environment in ``server\\.venv``; the
    interpreter running this code. The carried one comes before anything installed because
    a copy of this tree has to run on a machine with no Python and no way to install one.
    """
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"no Python at {path}")

    chosen = os.environ.get("DC_PYTHON")
    if chosen and Path(chosen).is_file():
        return Path(chosen).resolve()

    for rel in (Path("python") / "python.exe",
                Path("server") / ".venv" / "Scripts" / "python.exe"):
        path = REPO_ROOT / rel
        if path.is_file():
            return path.resolve()

    if sys.executable:
        return Path(sys.executable).resolve()
    found = shutil.which("python")
    if found:
        return Path(found).resolve()
    raise FileNotFoundError(
        "no Python found: tried DC_PYTHON, python\\python.exe inside this folder, "
        "server\\.venv, and PATH")


def game_exe() -> Path:
    """The packaged game's launcher exe.

    ``game\\DCDemo.exe`` is where a ready-to-run copy of this tree carries it;
    ``unreal\\_build\\archive\\Windows\\DCDemo.exe`` is where a packaging run on a machine
    with the engine puts it. The first that exists wins; if neither does, the first path is
    returned so the caller's own "not packaged yet" message names the right place.
    """
    candidates = (REPO_ROOT / "game" / "DCDemo.exe",
                  REPO_ROOT / "unreal" / "_build" / "archive" / "Windows" / "DCDemo.exe")
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def log_dir() -> Path:
    """Where a run may write its logs: ``_logs`` at the root of this copy of the tree.

    Inside the tree on purpose - a run must leave nothing outside the folder it was started
    from - and git-ignored, so logs are never committed.
    """
    path = REPO_ROOT / "_logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_unreal_engine(explicit: str | os.PathLike[str] | None = None,
                       version: str = "5.7") -> Path:
    """The Unreal Engine install: ``UE_ROOT``, then the registry, then the launcher manifest.

    Only needed to rebuild. Raises with both places named if it finds nothing.
    """
    def ok(root: Path) -> bool:
        return (root / "Engine" / "Binaries" / "Win64").is_dir()

    if explicit:
        root = Path(explicit)
        if ok(root):
            return root
        raise FileNotFoundError(f"no Unreal Engine at {root}")

    tried: list[str] = []
    env_root = os.environ.get("UE_ROOT")
    if env_root:
        tried.append(f"UE_ROOT={env_root}")
        if ok(Path(env_root)):
            return Path(env_root)
    else:
        tried.append("UE_ROOT (not set)")

    key = rf"SOFTWARE\EpicGames\Unreal Engine\{version}"
    tried.append(f"the registry (HKLM\\{key}, value InstalledDirectory)")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            value, _ = winreg.QueryValueEx(handle, "InstalledDirectory")
        if value and ok(Path(value)):
            return Path(value)
    except (ImportError, OSError):
        pass

    manifest = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / \
        "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"
    tried.append(f"the launcher manifest ({manifest})")
    if manifest.is_file():
        import json
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except ValueError:
            entries = {}
        for entry in entries.get("InstallationList", []):
            where = entry.get("InstallLocation")
            if entry.get("AppName") == f"UE_{version}" and where and ok(Path(where)):
                return Path(where)

    raise FileNotFoundError(
        f"Unreal Engine {version} was not found. Looked at: " + "; ".join(tried) +
        f". Install UE {version}, or set UE_ROOT to its folder (the one that contains "
        f"Engine\\Binaries\\Win64).")


def find_blender(explicit: str | os.PathLike[str] | None = None) -> Path:
    """blender.exe: ``BLENDER_EXE``, then PATH. Only needed to rebuild the art."""
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"no Blender at {path}")
    chosen = os.environ.get("BLENDER_EXE")
    if chosen:
        if Path(chosen).is_file():
            return Path(chosen).resolve()
        raise FileNotFoundError(f"BLENDER_EXE is set to {chosen}, which is not there")
    found = shutil.which("blender")
    if found:
        return Path(found).resolve()
    raise FileNotFoundError(
        "Blender was not found. Looked at: BLENDER_EXE (not set); PATH (no 'blender'). "
        "Set BLENDER_EXE to the full path of blender.exe, or put it on PATH. Blender is "
        "only needed to rebuild the art; the demo runs without it.")
