"""Build the interpreter a copy of this tree carries with it.

    python tools/make_python_bundle.py                  build it into _prebuilt/python
    python tools/make_python_bundle.py --check          only look at what is already there
    python tools/make_python_bundle.py --out DIR

Why
---
A copy of this tree has to run on a machine that has no Python, no pip, and - this is the
part that decides the shape of the answer - **no way out to the internet**. So the
interpreter travels with it, with every package already installed.

Not a virtual environment: a venv records the absolute path of the interpreter it was made
from, in `pyvenv.cfg` and in every script in its `Scripts\\` folder, so it only works in the
folder it was created in and it names the machine that created it. The embeddable
distribution of CPython from python.org has neither problem - it is a folder of files that
runs wherever it is put - which is why that is what this downloads.

What it makes
-------------
    _prebuilt/python/python.exe          the interpreter
    _prebuilt/python/python313.zip       the standard library
    _prebuilt/python/Lib/site-packages/  the packages below

`_prebuilt/` is git-ignored: this is a build output, like the packaged game. The export
that goes to another machine carries the same folder at its root as `python\\`, and both
`Find-DemoPython` (PowerShell) and `dc_paths.demo_python()` (Python) look there first, ahead
of anything installed on the machine.

What is in it, and what is not
------------------------------
Everything in `server/requirements.txt` - which is the server, the signing, the upload
parsing and `pytest`, so the server's own tests run - plus Pillow, which every contact-sheet
tool and both exit tests need.

**Playwright is deliberately not in it.** It drives a real browser for
`booth/portal_exit_test.py`, the browser binaries are hundreds of megabytes, and installing
them is itself a download - which is the one thing the office copy must never need. Those
two tests stay in the tree and are documented as optional.

After installing, `Scripts\\` is deleted. pip writes a launcher there for every console
entry point and each one embeds the full path of the interpreter that installed it, which
is a path on the machine that ran this. Nothing needs them: every caller in this tree runs
`python -m <module>`.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_DIR / "_prebuilt" / "python"

# Pinned, so two runs of this produce the same interpreter. 3.13 because that is what the
# project is developed against; the wheels below are cp313 ones.
PYTHON_VERSION = "3.13.1"
EMBED_URL = (f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
             f"python-{PYTHON_VERSION}-embed-amd64.zip")
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# Not a server dependency and not in requirements.txt: Pillow is what every contact sheet
# in this tree is drawn with, and what both exit tests compare screenshots with.
EXTRA_PACKAGES = ["pillow==13.0.0"]

# Anything that would say which machine built the bundle, and nothing that would say which
# machine built it: both halves of the pattern are worked out at run time, from the name of
# the folder this tree happens to sit in and from the environment, so this file carries
# neither written down. (The export's own guard searches for the same shapes over
# everything; this is the earlier, narrower check, so a bad bundle is caught here rather
# than at the end of an export.)
#
# THIS_MACHINE must find nothing. A .pyc holds the absolute path of the source it was
# compiled from, so one careless import while building the bundle writes this folder into
# hundreds of files; everything here runs with -B, and `scrub` deletes every __pycache__
# anyway.
THIS_MACHINE = re.compile(
    (r"(?i)(?:[A-Za-z]:[\\/]{1,2}" + re.escape(REPO_DIR.name) +
     r"|C:[\\/]{1,2}Users[\\/]{1,2}" +
     re.escape(os.environ.get("USERNAME") or "\x00no-such-user\x00") + ")").encode("utf-8"))

# Somebody ELSE's user folder, which third-party packages carry and nothing can be done
# about: a docstring in `click` that explains where Windows keeps application data, a
# comment in `pip`, and the Rust build paths inside the compiled halves of `cryptography`
# and `pydantic-core`, which were built on a hosted runner. Counted and listed, never
# ignored silently, but not a reason to refuse: none of it says anything about this machine.
OTHER_MACHINES = re.compile(rb"(?i)C:[\\/]{1,2}Users[\\/]{1,2}")

# Installed to install the packages, then removed. The office copy must never be able to
# reach a package index, and `pip` is the only thing in the bundle that knows how; its
# vendored wheel launchers are also the only files in it that carry somebody's build path.
REMOVE_AFTER_INSTALL = ("pip", "pkg_resources", "setuptools", "wheel", "_distutils_hack")


def say(*parts: object) -> None:
    print(*parts, flush=True)


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        say(f"  have {dest.name} ({dest.stat().st_size:,} B)")
        return dest
    say(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        dest.write_bytes(response.read())
    say(f"  wrote {dest.name} ({dest.stat().st_size:,} B)")
    return dest


def enable_site_packages(root: Path) -> None:
    """The embeddable distribution ships with `site` disabled; the packages need it on.

    Its `python3NN._pth` replaces sys.path wholesale, and a line of `import site` is what
    turns the normal site machinery - and so `Lib\\site-packages` - back on.
    """
    pth_files = sorted(root.glob("python*._pth"))
    if not pth_files:
        raise SystemExit(f"no python*._pth in {root} - is this the embeddable zip?")
    pth = pth_files[0]
    lines = [line.rstrip() for line in pth.read_text(encoding="utf-8").splitlines()]
    wanted = ["Lib\\site-packages", "import site"]
    for line in wanted:
        if line not in lines:
            lines.append(line)
    # `import site` has to be the last line, so everything else is on sys.path first.
    lines = [line for line in lines if line != "import site"] + ["import site"]
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    say(f"  {pth.name}: " + " | ".join(lines))


def requirement_lines() -> list[str]:
    text = (REPO_DIR / "server" / "requirements.txt").read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def scrub(root: Path) -> list[str]:
    """Remove what pip leaves behind that is of no use or names this machine."""
    removed: list[str] = []
    scripts = root / "Scripts"
    if scripts.is_dir():
        removed.append(f"Scripts/ ({len(list(scripts.iterdir()))} launcher(s))")
        shutil.rmtree(scripts)
    for name in ("__pycache__", ".cache"):
        for path in sorted(root.rglob(name)):
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(path.relative_to(root).as_posix() + "/")
    # pip records where a wheel came from for a local install; it never does for a
    # downloaded one, but a stray one would carry a file:// path.
    for path in sorted(root.rglob("direct_url.json")):
        path.unlink()
        removed.append(path.relative_to(root).as_posix())

    site_packages = root / "Lib" / "site-packages"
    for name in REMOVE_AFTER_INSTALL:
        for path in sorted(list(site_packages.glob(name)) +
                           list(site_packages.glob(name + "-*.dist-info")) +
                           list(site_packages.glob(name + "-*.egg-info")) +
                           list(site_packages.glob(name + ".py")) +
                           list(site_packages.glob(name + ".pth"))):
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(path.relative_to(root).as_posix() + "/")
            else:
                path.unlink()
                removed.append(path.relative_to(root).as_posix())
    for stray in sorted(site_packages.glob("distutils-precedence.pth")):
        stray.unlink()
        removed.append(stray.relative_to(root).as_posix())
    return removed


def check(root: Path) -> int:
    """Does it run, does it import everything, and does it name this machine anywhere?"""
    exe = root / "python.exe"
    if not exe.is_file():
        say(f"no interpreter at {exe}")
        return 1

    # -B throughout: importing a module writes a .pyc next to it, and a .pyc holds the
    # absolute path of the source it was compiled from (co_filename). Checking the bundle
    # must not be what puts this machine's folder into 340 files of it.
    done = subprocess.run([str(exe), "-B", "-c", "import sys; print(sys.version)"],
                          capture_output=True, text=True)
    say(f"  python -V: {done.stdout.strip() or done.stderr.strip()}")
    if done.returncode:
        return 1

    modules = ["fastapi", "uvicorn", "cryptography", "multipart", "httpx", "pytest",
               "PIL", "sqlite3", "ctypes", "ssl", "zlib", "lzma", "hashlib", "json"]
    code = ("import importlib, sys\n"
            "bad = []\n"
            f"for name in {modules!r}:\n"
            "    try: importlib.import_module(name)\n"
            "    except Exception as exc: bad.append(f'{name}: {exc}')\n"
            "print('MISSING ' + '; '.join(bad) if bad else 'all imports ok')\n"
            "sys.exit(1 if bad else 0)\n")
    done = subprocess.run([str(exe), "-B", "-c", code], capture_output=True, text=True)
    say("  " + (done.stdout.strip() or done.stderr.strip()))
    imports_ok = done.returncode == 0

    mine = 0
    theirs: list[str] = []
    files = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        files += 1
        data = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        for view in (data, data.decode("utf-16-le", "ignore").encode("utf-8", "ignore")):
            match = THIS_MACHINE.search(view)
            if match:
                mine += 1
                say(f"  THIS MACHINE in {rel}: "
                    f"{view[max(0, match.start() - 30):match.start() + 80]!r}")
                break
        match = OTHER_MACHINES.search(data)
        if match:
            theirs.append(f"{rel}: {data[match.start():match.start() + 70]!r}")

    total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    say(f"  {files} file(s), {total / 1024 / 1024:.1f} MiB")
    say(f"  this machine's folders: {mine}  (must be 0)")
    say(f"  somebody else's C:\\Users\\ path, in a third-party package: {len(theirs)}")
    for line in theirs:
        say(f"      {line}")
    return 0 if (imports_ok and mine == 0) else 1


def build(out: Path, cache: Path) -> int:
    if out.exists():
        say(f"removing {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    say(f"CPython {PYTHON_VERSION}, embeddable, x64")
    embed_zip = download(EMBED_URL, cache / Path(EMBED_URL).name)
    with zipfile.ZipFile(embed_zip) as zf:
        zf.extractall(out)
    say(f"  extracted {len(list(out.iterdir()))} item(s) into {out}")

    enable_site_packages(out)

    say("pip")
    get_pip = download(GET_PIP_URL, cache / "get-pip.py")
    done = subprocess.run([str(out / "python.exe"), str(get_pip),
                           "--no-warn-script-location", "--no-cache-dir"],
                          capture_output=True, text=True)
    if done.returncode:
        say(done.stdout[-3000:])
        say(done.stderr[-3000:])
        raise SystemExit("could not install pip into the bundle")
    say("  pip installed")

    packages = requirement_lines() + EXTRA_PACKAGES
    say(f"packages ({len(packages)}): " + ", ".join(packages))
    done = subprocess.run([str(out / "python.exe"), "-m", "pip", "install",
                           "--no-warn-script-location", "--no-cache-dir", *packages],
                          capture_output=True, text=True)
    if done.returncode:
        say(done.stdout[-5000:])
        say(done.stderr[-5000:])
        raise SystemExit("could not install the packages into the bundle")
    say("  " + done.stdout.strip().splitlines()[-1])

    say("scrubbing")
    for line in scrub(out):
        say(f"  removed {line}")

    say("checking")
    result = check(out)

    # pip and the check both compile as they go, however carefully they are asked not to.
    leftovers = scrub(out)
    if leftovers:
        say("scrubbing again")
        for line in leftovers:
            say(f"  removed {line}")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--cache", type=Path, default=REPO_DIR / "_prebuilt" / "_downloads",
                    help="where the downloaded zip and get-pip.py are kept")
    ap.add_argument("--check", action="store_true",
                    help="do not build; only check what is already in --out")
    args = ap.parse_args(argv)

    out = args.out.resolve()
    if args.check:
        return check(out)
    return build(out, args.cache.resolve())


if __name__ == "__main__":
    sys.exit(main())
