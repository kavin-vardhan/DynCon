"""Build a clean, history-free, ready-to-run copy of this project for an internal git.

Why this exists
---------------
The project is developed in one repository and carried into an internal network as a fresh
tree with no history: the person carrying it in runs `git init`, commits and pushes there
under their office identity. Four things have to be true of what leaves.

1. **Only files the repository actually tracks, plus a named list of build outputs.** The
   tree is built out of `git archive HEAD`, so an untracked or ignored file is not merely
   skipped but impossible to include by accident. On top of that, and only on top of that,
   comes the *prebuilt payload*: the packaged game, the bundled interpreter and the content
   packs, each one enumerated in `PREBUILT` below with where it comes from and why it is
   there. Nothing else from the working tree can get in.

2. **Nothing in it may carry personal identity or anything about how it was written.** That
   is the first half of the guard below, which is run over every byte of the staged export -
   text, binary, compressed - and refuses to produce the zip if it finds anything.

3. **Nothing in it may name the machine it was built on.** That is the second half of the
   guard: no drive-rooted path into this project or into the engine, no Steam library path,
   no user name, no machine name. Every script finds its own paths instead (see
   `tools/dc_paths.ps1` and `tools/dc_paths.py`).

4. **It must run straight after a pull, on a machine with no internet.** Hence the prebuilt
   payload, and hence `Start-Demo.bat` / `Stop-Demo.bat` at the root and `README.txt` next
   to them.

The export carries no Markdown at all: the documentation set is written for the development
repository and the office adds its own. `README.txt` is the plain-text guide that replaces
it for someone who has never seen the project.

What it produces
----------------
    <out>\\                                 the folder, with no .git, no venv, no __pycache__
    <out>.zip                               the same tree zipped
    DynamicContents_office_build.zip        only with --no-lfs: the files over 95 MB

Both are replaced on each run. Neither is inside the repository.

Usage
-----
    python tools/make_office_export.py                 build the folder and the zip
    python tools/make_office_export.py --no-zip        build the folder only
    python tools/make_office_export.py --no-lfs        no Git LFS; big files in a side zip
    python tools/make_office_export.py --no-prebuilt   tracked files only (a quick check)
    python tools/make_office_export.py --out DIR       build somewhere else
    python tools/make_office_export.py --scan DIR      only run the guard, over DIR

Exit code 0 means the export is complete and the guard found nothing. Exit code 1 means the
guard found something: the offending files are listed and no zip is written.

Run it with an interpreter that has `zstandard` installed - the bundled one in `_prebuilt\\
python\\python.exe` has it, as does `server\\.venv`. Blender saves a .blend as a Zstandard
frame, and the guard refuses to finish rather than leave a compressed file unsearched.
Python 3.14 and later can do it with the standard library alone, so the dependency will fall
away in time.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUT = Path(os.environ.get("DC_EXPORT_OUT") or
                   (REPO_DIR.parent / "DynamicContents_office"))

# ---------------------------------------------------------------------------------------
# What is dropped from the export
# ---------------------------------------------------------------------------------------
# `*.md`: the whole documentation set. It is written for the development repository and
#   references a workflow the office does not share; `README.txt` replaces it.
# This script: it only has a job in the development repository, and it is the one file that
#   must contain the guard's search terms verbatim, so leaving it in would be both pointless
#   and self-defeating.
DROP_SUFFIXES = (".md",)
DROP_PATHS = ("tools/make_office_export.py",)

# The one guide the office gets, written for somebody who has never seen the project. It
# lives under tools/ in the development repository - one README at a root is enough - and
# is moved to the root of the export under the name the office looks for.
README_SOURCE = "tools/office_README.txt"
README_DEST = "README.txt"

# ---------------------------------------------------------------------------------------
# The prebuilt payload: what the copy carries so that a pull runs without building anything
# ---------------------------------------------------------------------------------------
# Each entry is (name, source, destination, what to take, what to leave, why it is needed).
# A missing source is a hard error - a copy that cannot run is the one thing this must never
# produce - with a sentence saying which command makes it.
PREBUILT: list[dict[str, object]] = [
    {
        "name": "the game",
        "src": "unreal/_build/archive/Windows",
        "dest": "game",
        "globs": None,                      # the whole tree
        "exclude": ("Engine/Extras/Redist/en-us/vc_redist.arm64.exe",),
        "why": "a fresh Shipping stage: the exe, the base-game pak, and the engine's "
               "prerequisites installer. No .pdb, no crash reporter.",
        "make": "unreal\\Tools\\package.ps1  then  unreal\\Tools\\stage_packs.ps1",
    },
    {
        "name": "the interpreter",
        "src": "_prebuilt/python",
        "dest": "python",
        "globs": None,
        "exclude": ("__pycache__",),
        "why": "CPython, embeddable, with every package the server, the tests and the "
               "contact-sheet tools need already installed. No pip: nothing in the copy "
               "can reach a package index, because nothing in the copy may need to.",
        "make": "tools\\make_python_bundle.py",
    },
    {
        "name": "the content packs",
        "src": "server/demo_files",
        "dest": "server/demo_files",
        # Only the real cooked packs and the two built-to-fail files. The 15-40 MB fake
        # copies of the same pieces stay behind: a real pack always wins over a fake one
        # for the same piece-version (Service._pick_demo_file), so the demo never offers
        # one, and they are 400 MB.
        "globs": ("*.real.dcpack", "content2_v1_engine53.dcpack",
                  "content2_v1_rated18.dcpack"),
        "exclude": (),
        "why": "what the server serves: one real cooked pack per piece-version, plus the "
               "two files the tour has to be able to reject.",
        "make": "server\\tools\\make_fake_packs.py --real --force  and  --only-bad --force",
    },
]

# ---------------------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------------------
# Every term that must not appear anywhere in the export: not in a file's text, not in a
# comment, not in a file or folder name, and not inside a binary. Matching is
# case-insensitive.
#
# This machine's user name and computer name are read from the environment at run time and
# never written down, here or anywhere else that leaves.
#
# The last column is whether a match inside a binary has to look like part of a real string
# to count. The reason is arithmetic: a short term matched either case will turn up in
# compressed bytes by chance now and again - four letters roughly once every 300 MB
# searched - and this export is searched three ways over every file. One such coincidence is
# already known (inside a Blender file, in bytes that decompress to nothing of the kind).
# Anything of six letters or more has a chance match about once in ten thousand exports, so
# those are taken literally wherever they appear.
_USER = os.environ.get("USERNAME") or "\x00no-such-user\x00"
_MACHINE = os.environ.get("COMPUTERNAME") or "\x00no-such-machine\x00"

# Two folders in the export are somebody else's build: `game/` is staged out of the Unreal
# engine and `python/` is CPython from python.org with packages from PyPI. Hundreds of
# megabytes of binaries and source written by other people, and the terms below divide into
# two kinds accordingly.
#
# IDENTITY_TERMS are about how THIS PROJECT was written, so they are checked over what this
# project wrote. Inside the two folders above they are reported instead: the engine's audio
# code names the Opus codec, Pillow credits a contributor called Jean-Claude, and every
# package on PyPI records its author's e-mail address. None of that is this project.
#
# PERSONAL_TERMS are about a person or a machine, and those are checked everywhere, third
# party or not: a third-party binary has no business naming this machine either, and if one
# ever did we would want the export to stop.
THIRD_PARTY_TREES = ("game/", "python/")

IDENTITY_TERMS: list[tuple[str, re.Pattern[str], bool]] = [
    ("claude", re.compile(r"claude", re.I), False),
    ("anthropic", re.compile(r"anthropic", re.I), False),
    ("gmail", re.compile(r"gmail", re.I), False),
    ("cowork", re.compile(r"cowork", re.I), False),
    ("Co-Authored-By", re.compile(r"co-authored-by", re.I), False),
    ("opus (as a word)", re.compile(r"(?<![A-Za-z])opus(?![A-Za-z])", re.I), True),
]

PERSONAL_TERMS: list[tuple[str, re.Pattern[str], bool]] = [
    ("kavinvardhan", re.compile(r"kavinvardhan", re.I), False),
    ("kavin-vardhan", re.compile(r"kavin-vardhan", re.I), False),
    ("dyncon", re.compile(r"dyncon", re.I), False),
    ("mrtocsik", re.compile(r"mrtocsik", re.I), False),
    # An e-mail address belonging to whoever is logged in here, whatever the domain.
    ("an address of this machine's user",
     re.compile(re.escape(_USER) + r"[\w.+-]*@", re.I), False),
    # This machine's folders. A drive letter in front of the project or the engine folder is
    # what makes these paths rather than words - "DynamicContents" on its own is the
    # plugin's name and is in the game's own binaries by design, and "EpicGames" on its own
    # is in Epic's own engine strings (see ADVISORY_TERMS). The lookbehind is what keeps a
    # URL out: "https://epicgames.com" is a letter, a colon and two slashes too.
    ("a path into this project",
     re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]{1,2}DynamicContents", re.I), False),
    ("a path into the engine",
     re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]{1,2}EpicGames", re.I), False),
    ("a Steam library path", re.compile(r"steamapps", re.I), False),
    ("this machine's user folder",
     re.compile(r"C:[\\/]{1,2}Users[\\/]{1,2}" + re.escape(_USER), re.I), False),
    ("this machine's user name", re.compile(re.escape(_USER), re.I), len(_USER) < 6),
    ("this machine's name", re.compile(re.escape(_MACHINE), re.I), len(_MACHINE) < 6),
]

GUARD_TERMS = IDENTITY_TERMS + PERSONAL_TERMS

# Reported in full on every run, and not a reason to refuse.
#
# Both of these are shapes that *would* name a machine if this project had put them there,
# and in every case below somebody else's build did. They are listed rather than quietly
# matched away, so that a new one cannot appear without being seen:
#
#   EpicGames, with no drive letter in front of it. Three kinds, all from the engine:
#   Epic's own reverse-DNS identifiers and web addresses compiled into every Unreal binary
#   (`com.epicgames.purchase.failure`, `udn.epicgames.com`), and the engine-relative
#   `../../../../../EpicGames/UE_5.7/Engine/` that UnrealBuildTool bakes into any build made
#   against a launcher install. None of them says which machine or which folder: the last
#   one is a route from the project to the engine, and it is the same route on every
#   launcher install there has ever been.
#
#   C:\\Users\\<somebody>. Four kinds, all from third-party packages in the interpreter: a
#   docstring in `click` explaining where Windows keeps application data, a comment in
#   `pip`, a docstring in `platformdirs`, and the Rust source paths inside the compiled
#   halves of `cryptography` and `pydantic-core`, which were built on a hosted runner. This
#   machine's own user folder is a hard term above and is not this.
ADVISORY_TERMS: list[tuple[str, re.Pattern[str]]] = [
    ("EpicGames, with no drive letter", re.compile(r"(?<![:\\/])EpicGames", re.I)),
    ("somebody else's C:\\Users\\ path", re.compile(r"C:[\\/]{1,2}Users[\\/]{1,2}", re.I)),
]

# How many printable characters in a row a match has to sit inside, in a binary, for the
# terms marked above. A string a tool or a person left in a file - a name, a path, a version
# line - has punctuation or neighbouring words around it and clears this easily; four
# letters thrown up by a compressor are bounded by bytes that are not printable.
MIN_STRING_RUN = 8

# A zip member bigger than this is read in full but nothing more is read after the running
# total passes it: enough to search the whole standard library in the bundled interpreter
# without a malformed archive being able to ask for all the memory there is.
ZIP_BUDGET_BYTES = 256 * 1024 * 1024


class Hit:
    """One term found in one place."""

    def __init__(self, rel: str, term: str, where: str, context: str) -> None:
        self.rel, self.term, self.where, self.context = rel, term, where, context

    def __str__(self) -> str:
        return f"{self.rel}: [{self.term}] in {self.where}: {self.context}"


def _snippet(text: str, match: re.Match[str]) -> str:
    """The match with a little around it, printable."""
    start, end = max(0, match.start() - 40), min(len(text), match.end() + 40)
    raw = text[start:end]
    clean = "".join(ch if 32 <= ord(ch) < 127 else "." for ch in raw)
    return repr(clean)


def _string_run(text: str, match: re.Match[str]) -> int:
    """How many printable characters in a row the match is part of."""
    start, end = match.start(), match.end()
    while start > 0 and 32 <= ord(text[start - 1]) < 127:
        start -= 1
    while end < len(text) and 32 <= ord(text[end]) < 127:
        end += 1
    return end - start


def third_party(rel: str) -> bool:
    """Is this file part of somebody else's build? See THIRD_PARTY_TREES."""
    return any(rel == tree.rstrip("/") or rel.startswith(tree)
               for tree in THIRD_PARTY_TREES)


def _search(text: str, rel: str, where: str, hits: list[Hit], advisories: list[Hit],
            *, textual: bool = True) -> None:
    """Every term, hard and advisory, over one view of one file.

    `textual` says the view is something a person reads - a source file, a declared text
    chunk - so a match counts wherever it falls. A view of binary bytes is held to the
    string test above for the terms that ask for it.
    """
    outside = not third_party(rel)
    for term, pattern, needs_string in GUARD_TERMS:
        hard = outside or (term, pattern, needs_string) in PERSONAL_TERMS
        for match in pattern.finditer(text):
            if needs_string and not textual and _string_run(text, match) < MIN_STRING_RUN:
                continue               # a few letters of compressor output, not a string
            where_from = where if hard else f"{where} (third-party: {term})"
            (hits if hard else advisories).append(
                Hit(rel, term if hard else f"{term}, in somebody else's build",
                    where_from, _snippet(text, match)))
            break                      # one example per term per view is enough
    for term, pattern in ADVISORY_TERMS:
        match = pattern.search(text)
        if match:
            advisories.append(Hit(rel, term, where, _snippet(text, match)))


def _png_text_chunks(data: bytes) -> list[str]:
    """Every tEXt / zTXt / iTXt chunk in a PNG, decompressed where it is compressed.

    Raw UTF-8 scanning already sees an uncompressed chunk; this is for the compressed ones,
    where the string an image-writing tool left behind would otherwise be hidden.
    """
    out: list[str] = []
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return out
    pos = 8
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length             # 4 length + 4 type + body + 4 CRC
        if length > len(data):
            break
        if kind == b"tEXt":
            out.append(body.decode("latin-1", "ignore"))
        elif kind == b"zTXt":
            key, _, rest = body.partition(b"\x00")
            try:
                out.append(key.decode("latin-1", "ignore")
                           + zlib.decompress(rest[1:]).decode("utf-8", "ignore"))
            except zlib.error:
                pass
        elif kind == b"iTXt":
            parts = body.split(b"\x00", 1)
            if len(parts) == 2 and parts[1][:1] == b"\x01":
                try:
                    out.append(zlib.decompress(parts[1][2:]).decode("utf-8", "ignore"))
                except zlib.error:
                    pass
            else:
                out.append(body.decode("utf-8", "ignore"))
        if kind == b"IEND":
            break
    return out


def _inflated_streams(data: bytes) -> list[str]:
    """Every zlib stream in the file, decompressed as far as it will go.

    This is what reaches a PDF's compressed page text and its XMP metadata packet, and the
    compressed blocks of any other container that stores strings that way.
    """
    out: list[str] = []
    for match in re.finditer(rb"\x78[\x01\x5e\x9c\xda]", data):
        try:
            blob = zlib.decompressobj().decompress(data[match.start():], 4_000_000)
        except zlib.error:
            continue
        if len(blob) > 8:
            out.append(blob.decode("utf-8", "ignore"))
    return out


def _zip_members(path: Path) -> list[tuple[str, str]]:
    """(member name, member text) for every member of a zip archive.

    A zip's members are raw deflate, not zlib streams, so `_inflated_streams` above walks
    straight past them. That mattered the moment the export started carrying a bundled
    interpreter: the whole Python standard library travels inside `python313.zip`, and an
    unsearched 11 MB archive is exactly the hole this guard exists to close.
    """
    out: list[tuple[str, str]] = []
    budget = ZIP_BUDGET_BYTES
    try:
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                out.append((info.filename, info.filename))
                if info.is_dir() or budget <= 0:
                    continue
                try:
                    blob = zf.read(info)
                except (RuntimeError, zipfile.BadZipFile, zlib.error, OSError):
                    continue
                budget -= len(blob)
                out.append((info.filename, blob.decode("utf-8", "ignore")))
    except (zipfile.BadZipFile, OSError):
        return out
    return out


def _unzstd(data: bytes) -> bytes:
    """Decompress a Zstandard frame. Blender saves every .blend as one of these.

    Python 3.14 has this in the standard library; before that it needs the `zstandard`
    package. Rather than quietly leave a compressed file unsearched, this stops the run.
    """
    try:
        from compression import zstd                   # Python 3.14 and later
        return zstd.decompress(data)
    except ImportError:
        pass
    try:
        import zstandard
    except ImportError:
        raise SystemExit(
            "this file is a Zstandard frame and cannot be searched inside with this\n"
            "interpreter. Run the export with one that has the 'zstandard' package\n"
            "(the bundled interpreter and server\\.venv both have it), or with Python\n"
            "3.14 or later:\n"
            "    _prebuilt\\python\\python.exe tools\\make_office_export.py")
    # A .blend has no frame content size in its header, so stream it rather than asking for
    # a one-shot decompress.
    return zstandard.ZstdDecompressor().decompressobj().decompress(data)


def _decompressed_whole_file(data: bytes) -> str:
    """A whole-file container that is gzip- or zstd-compressed, e.g. a saved .blend."""
    if data.startswith(b"\x1f\x8b"):
        try:
            return zlib.decompress(data, 16 + zlib.MAX_WBITS).decode("utf-8", "ignore")
        except zlib.error:
            return ""
    if data.startswith(b"\x28\xb5\x2f\xfd"):
        return _unzstd(data).decode("utf-8", "ignore")
    return ""


def scan_file(path: Path, rel: str) -> tuple[list[Hit], list[Hit]]:
    """Run every term over one file: its name, its text, and inside its bytes."""
    hits: list[Hit] = []
    advisories: list[Hit] = []
    _search(rel, rel, "the path", hits, advisories)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"could not read {rel}: {exc}")

    # A file whose every byte is valid UTF-8 is one somebody wrote; anything else is a
    # binary, and a short match in it has to look like part of a string (see GUARD_TERMS).
    try:
        data.decode("utf-8")
        textual = True
    except UnicodeDecodeError:
        textual = False

    # UTF-8. Invalid bytes are dropped, never consumed as part of a sequence, so every run
    # of ASCII in a binary survives into the decoded text.
    _search(data.decode("utf-8", "ignore"), rel, "UTF-8", hits, advisories, textual=textual)

    # UTF-16LE, at both alignments: .uasset and other engine formats store wide strings
    # that way, and a string can start on an odd byte.
    for offset in (0, 1):
        _search(data[offset:].decode("utf-16-le", "ignore"), rel,
                f"UTF-16LE+{offset}", hits, advisories, textual=False)

    suffix = path.suffix.lower()
    if suffix == ".png":
        # tEXt / zTXt / iTXt are declared text, so they are read as text.
        for n, chunk in enumerate(_png_text_chunks(data)):
            _search(chunk, rel, f"PNG text chunk {n}", hits, advisories, textual=True)
    if suffix in (".pdf", ".fbx", ".glb"):
        for n, blob in enumerate(_inflated_streams(data)):
            _search(blob, rel, f"compressed stream {n}", hits, advisories, textual=False)
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        for name, text in _zip_members(path):
            _search(text, rel, f"zip member {name}", hits, advisories, textual=True)
    whole = _decompressed_whole_file(data)
    if whole:
        _search(whole, rel, "decompressed container", hits, advisories, textual=False)
    return hits, advisories


def guard(root: Path) -> tuple[list[Hit], list[Hit]]:
    """Every hit anywhere under `root`, folder names included."""
    hits: list[Hit] = []
    advisories: list[Hit] = []
    files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        for name in dirnames:
            rel = (here / name).relative_to(root).as_posix() + "/"
            _search(rel, rel, "the folder name", hits, advisories)
        for name in sorted(filenames):
            path = here / name
            rel = path.relative_to(root).as_posix()
            found, advised = scan_file(path, rel)
            hits.extend(found)
            advisories.extend(advised)
            files += 1
            if files % 400 == 0:
                print(f"    searched {files} files...", flush=True)
    folders = sum(1 for p in root.rglob("*") if p.is_dir())
    print(f"    searched {files} files, {folders} folders", flush=True)
    return hits, advisories


# ---------------------------------------------------------------------------------------
# Building the export
# ---------------------------------------------------------------------------------------
def git(*args: str) -> str:
    done = subprocess.run(("git", "-C", str(REPO_DIR)) + args,
                          capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"git {' '.join(args)} failed:\n{done.stderr}")
    return done.stdout


def stage_from_git_archive(dest: Path) -> list[str]:
    """Extract `git archive HEAD` into `dest`. Returns every path it wrote."""
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / "head.tar"
        git("archive", "--format=tar", "-o", str(tar_path), "HEAD")
        with tarfile.open(tar_path) as tar:
            members = [m for m in tar.getmembers() if m.isfile()]
            try:
                tar.extractall(dest, members=members, filter="data")
            except TypeError:                     # Python without the filter argument
                tar.extractall(dest, members=members)
            return [m.name for m in members]


def copy_prebuilt(root: Path) -> list[str]:
    """Copy the build outputs the copy needs in order to run. Returns one line each."""
    lines: list[str] = []
    for entry in PREBUILT:
        src = REPO_DIR / str(entry["src"])
        dest = root / str(entry["dest"])
        if not src.exists():
            raise SystemExit(
                f"{entry['name']} is not built: there is nothing at {src}.\n"
                f"A copy of this tree that cannot run is the one thing this must never\n"
                f"produce, so this is a hard stop. Make it with:\n"
                f"    {entry['make']}\n"
                f"or pass --no-prebuilt to build the text-only export anyway.")
        exclude = tuple(entry["exclude"] or ())
        files = 0
        total = 0
        globs = entry["globs"]
        if globs:
            dest.mkdir(parents=True, exist_ok=True)
            for pattern in globs:                       # type: ignore[union-attr]
                for path in sorted(src.glob(pattern)):
                    shutil.copy2(path, dest / path.name)
                    files += 1
                    total += path.stat().st_size
        else:
            for path in sorted(src.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(src).as_posix()
                if any(rel == skip or rel.startswith(skip.rstrip("/") + "/")
                       or f"/{skip}/" in f"/{rel}" for skip in exclude):
                    continue
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                files += 1
                total += path.stat().st_size
        lines.append(f"{entry['dest']}/  <- {entry['src']}  "
                     f"{files} file(s), {total / 1024 / 1024:.1f} MiB")
        if exclude:
            lines.append(f"    left out: {', '.join(exclude)}")
    return lines


def drop_unwanted(root: Path) -> list[str]:
    """Remove what the office copy does not carry. Returns the paths removed."""
    dropped: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if path.suffix.lower() in DROP_SUFFIXES or rel in DROP_PATHS:
            path.unlink()
            dropped.append(rel)
    # Anything a tool leaves behind rather than a person writing it. `git archive` cannot
    # produce these; the prebuilt payload could.
    for junk in ("__pycache__", ".venv", ".pytest_cache", ".git", ".idea", ".vscode"):
        for path in sorted(root.rglob(junk)):
            if path.is_dir():
                shutil.rmtree(path)
                dropped.append(path.relative_to(root).as_posix() + "/")
    # Folders left empty by the drop are not worth carrying.
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            dropped.append(path.relative_to(root).as_posix() + "/ (left empty)")
    return dropped


GITIGNORE_TEXT = """\
# Anything a build, a cook, an export or a test run produces, and anything that belongs to
# one machine rather than to the project. Nothing listed here is source.
#
# Two things are deliberately NOT here:
#   *.md            the documentation this tree ships with is the office's own, and it has
#                   to be committable.
#   server/demo_files/*.dcpack  and  game/  and  python/
#                   these are build outputs everywhere else, and in this tree they are what
#                   makes it run without being built. They are committed on purpose.

__pycache__/
*.pyc
*.log
*.blend1
Thumbs.db
desktop.ini
.vscode/
.idea/

# What a run of the demo writes: logs, the browser profile, the pack caches, the preview
# copy's saved folder, and the list of what Start-Demo started.
_logs/
_run/

# The server's own state: the signing keys, the sqlite database, the stored packs and the
# client caches. All of it is made on first run - delete the folder and the next run makes
# a new key pair and seeds the packs again.
server/data/
server/.venv/
server/.pytest_cache/

# A rebuilt interpreter bundle, if anyone ever remakes it here.
_prebuilt/

# Generated art. The per-piece previews and the QA close-ups are rebuilt from the Blender
# scripts by `art/build.ps1`, so only the summary sheets in art/previews/ are committed.
art/_qa/
art/previews/*_ext.png
art/previews/*_int.png
art/previews/*_top.png
!art/previews/contact_sheet.png
!art/previews/contact_ext.png
!art/previews/swap_pairs.png
!art/previews/env_contact.png

# The environment kit's per-piece previews, same rule: two palettes x 23 pieces of PNG,
# rebuilt by `art/build.ps1 -EnvOnly`. art/previews/env_contact.png is the one that stays.
art/previews_env/

# The UE project. The C++ sources, Config/ and Content/ are committed; everything the
# engine regenerates is not.
unreal/DCDemo/Binaries/
unreal/DCDemo/Intermediate/
unreal/DCDemo/Saved/
unreal/DCDemo/DerivedDataCache/
unreal/DCDemo/Plugins/*/Binaries/
unreal/DCDemo/Plugins/*/Intermediate/
unreal/DCDemo/*.sln
unreal/DCDemo/.vs/
unreal/DCDemo/.vsconfig
unreal/DCDemo/Build/Windows/FileOpenOrder/

# A packaging run's own output. The copy of it that this tree carries is in game/ and is
# committed; this is where a rebuild would put a new one.
unreal/_build/
unreal/_packs/

# A packaged run writes two screenshots of about a megabyte per pack. Only the contact
# sheet built from them is committed.
unreal/spike/shots/*.png
!unreal/spike/shots/engine_contact.png
unreal/spike/shots/spike_result.txt

# The menu and X-ray exit test: 22 screenshots at 1600x900 and at 1080p come to tens of
# megabytes a run, and `unreal/Tools/make_menu_sheet.py` rebuilds both contact sheets out
# of them. Same rule as the art previews - the sheets are committed, the shots are not.
unreal/spike/shots/018/menu_1600x900/*.png
unreal/spike/shots/018/xray_1920x1080/*.png
# The five slot thumbnails and the two pinned maps are committed full size under
# server/config/maps/, and summed up in slotmap_contact.png.
unreal/spike/shots/018/A_A*.png
unreal/spike/shots/018/B_B*.png
unreal/spike/shots/018/A_map_pins.png
unreal/spike/shots/018/B_map_pins.png

# The portal's exit-test screenshots, same rule as the art previews: the per-screen PNGs
# are megabytes a run and `booth/portal_exit_test.py` rebuilds all of them in under a
# minute, so only the contact sheet is committed.
portal/_shots/*/[0-9]*.png
portal/_shots/*/*.log
portal/_shots/*/audit.txt
!portal/_shots/*/contact_sheet.png

# The preview window's exit test, same rule again: the per-beat portal shots and the full
# desktop captures are rebuilt by `booth/preview_exit_test.py`, so what is committed is the
# two contact sheets and the three crops of the preview window's own rectangle.
booth/_shots/*/[0-9]*.png
booth/_shots/*/desktop_*.png
booth/_shots/*/*.log
!booth/_shots/*/contact_sheet*.png
!booth/_shots/*/previewarea_*.png
!booth/_shots/*/mainwindow_*.png
"""

# Everything in this tree that is a binary, so git never tries to be clever with it. The
# first line is the one that was already here and matters most: no end-of-line conversion
# anywhere, for anything.
LFS_SUFFIXES = ("exe", "dll", "pak", "ucas", "utoc", "uasset", "umap", "dcpack", "zip",
                "fbx", "glb", "blend", "png", "pdf")

GITATTRIBUTES_HEAD = """\
# No end-of-line conversion, for anything. A .uasset, a .pak and a cooked container are all
# binaries that happen to contain bytes git would otherwise read as newlines.
* -text
"""

GITATTRIBUTES_LFS = """
# Git LFS. This tree carries the packaged game, a bundled interpreter and the cooked content
# packs, which is a few hundred megabytes of binaries that never change line by line and
# that a normal git server will refuse or choke on. `git lfs install` once per machine, then
# clone and pull as usual.
#
# If the office git has no LFS, export with --no-lfs instead: these rules go away and every
# file over 95 MB travels in DynamicContents_office_build.zip beside the tree.
"""


def write_gitignore(root: Path) -> None:
    (root / ".gitignore").write_text(GITIGNORE_TEXT, encoding="utf-8", newline="\n")


def write_gitattributes(root: Path, *, lfs: bool) -> str:
    text = GITATTRIBUTES_HEAD
    if lfs:
        text += GITATTRIBUTES_LFS
        for suffix in LFS_SUFFIXES:
            text += f"*.{suffix} filter=lfs diff=lfs merge=lfs -text\n"
    else:
        text += ("\n# Exported with --no-lfs: no LFS rules, and the files over 95 MB are in\n"
                 "# DynamicContents_office_build.zip beside this folder. Unzip it over the\n"
                 "# top of this folder after cloning, and do not commit what it contains.\n")
    (root / ".gitattributes").write_text(text, encoding="utf-8", newline="\n")
    return text


BIG_FILE_BYTES = 95 * 1024 * 1024          # what a git server without LFS will not take
REPORT_FILE_BYTES = 50 * 1024 * 1024       # what is worth naming in the report either way


def move_big_files(root: Path, zip_path: Path) -> list[tuple[str, int]]:
    """With --no-lfs: every file over 95 MB goes into a zip beside the tree."""
    big = sorted((p for p in root.rglob("*")
                  if p.is_file() and p.stat().st_size > BIG_FILE_BYTES),
                 key=lambda p: p.stat().st_size, reverse=True)
    if not big:
        return []
    if zip_path.exists():
        zip_path.unlink()
    moved: list[tuple[str, int]] = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in big:
            rel = path.relative_to(root).as_posix()
            zf.write(path, rel)
            moved.append((rel, path.stat().st_size))
            path.unlink()
    return moved


# ---------------------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------------------
def inventory(root: Path) -> tuple[dict[str, tuple[int, int]], int, int]:
    """(files, bytes) per top-level folder, plus the totals."""
    per: dict[str, tuple[int, int]] = {}
    files = total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        top = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        size = path.stat().st_size
        count, acc = per.get(top, (0, 0))
        per[top] = (count + 1, acc + size)
        files += 1
        total += size
    return per, files, total


BRIEF_RE = re.compile(r"\bbrief\s+0*\d+", re.I)


def count_change_notes(root: Path) -> int:
    """How many "brief NNN" mentions are left. They read as change numbers, so they stay;
    the count is reported so it can be checked rather than assumed."""
    found = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_bytes().decode("utf-8", "ignore")
        except OSError:
            continue
        found += len(BRIEF_RE.findall(text))
    return found


def make_zip(root: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root).as_posix())


def report_advisories(advisories: list[Hit]) -> None:
    print(f"\nadvisory: {len(advisories)} hit(s) - shapes that would name a machine if this "
          f"project had written them, and that somebody else's build did")
    by_term: dict[str, list[Hit]] = {}
    for hit in advisories:
        by_term.setdefault(hit.term, []).append(hit)
    for term, found in by_term.items():
        files = sorted({hit.rel for hit in found})
        print(f"  {term}: {len(found)} hit(s) in {len(files)} file(s)")
        for rel in files[:12]:
            print(f"      {rel}")
        if len(files) > 12:
            print(f"      ... and {len(files) - 12} more")


def report_hits(hits: list[Hit]) -> int:
    if not hits:
        print("guard: 0 hits")
        return 0
    print(f"\nGUARD FAILED: {len(hits)} hit(s)")
    for hit in hits:
        print(f"  {hit}")
    return 1


# ---------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"where to write the export folder (default {DEFAULT_OUT})")
    ap.add_argument("--no-zip", action="store_true", help="build the folder only")
    ap.add_argument("--no-lfs", action="store_true",
                    help="no Git LFS rules; move every file over 95 MB into a side zip")
    ap.add_argument("--no-prebuilt", action="store_true",
                    help="tracked files only: no game, no interpreter, no packs. The copy "
                         "will not run; this is for checking the text of the export.")
    ap.add_argument("--scan", type=Path, default=None,
                    help="do not export; only run the guard over this folder")
    args = ap.parse_args(argv)

    if args.scan is not None:
        root = args.scan.resolve()
        if not root.is_dir():
            raise SystemExit(f"not a folder: {root}")
        print(f"searching {root} for anything that must not leave")
        hits, advisories = guard(root)
        if advisories:
            report_advisories(advisories)
        return report_hits(hits)

    out = args.out.resolve()
    if out == REPO_DIR or REPO_DIR in out.parents or out in REPO_DIR.parents:
        raise SystemExit(f"the export must be outside the repository, not {out}")
    zip_path = out.with_suffix(".zip")
    build_zip_path = out.parent / "DynamicContents_office_build.zip"

    head = git("rev-parse", "--short", "HEAD").strip()
    dirty = git("status", "--porcelain").strip()
    print(f"exporting HEAD {head}"
          + (f" (working tree has {len(dirty.splitlines())} uncommitted change(s) - they "
             f"are NOT in the export)" if dirty else ""))

    for stale in (out, zip_path, build_zip_path):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()
    out.mkdir(parents=True)

    written = stage_from_git_archive(out)
    print(f"  staged {len(written)} tracked file(s) from git archive")

    if args.no_prebuilt:
        print("  --no-prebuilt: no game, no interpreter, no packs. This copy will NOT run.")
    else:
        print("  the prebuilt payload:")
        for line in copy_prebuilt(out):
            print(f"    {line}")

    dropped = drop_unwanted(out)
    print(f"  dropped {len(dropped)}:")
    for rel in dropped:
        print(f"    - {rel}")

    write_gitignore(out)
    attributes = write_gitattributes(out, lfs=not args.no_lfs)
    print(f"  wrote .gitignore and .gitattributes "
          f"({'with' if not args.no_lfs else 'without'} Git LFS rules, "
          f"{len(attributes.splitlines())} lines)")

    source = out / README_SOURCE
    readme = out / README_DEST
    if not source.is_file():
        raise SystemExit(f"{README_SOURCE} is not in HEAD - it is the only guide the office "
                         f"gets, so this is a hard stop")
    shutil.move(str(source), str(readme))
    print(f"  {README_SOURCE} -> {README_DEST} ({readme.stat().st_size:,} B)")

    for gone in (".git", "__pycache__"):
        assert not list(out.rglob(gone)), f"{gone} is still in the export"
    assert not list(out.rglob("*.md")), "a .md file is still in the export"
    assert not (out / DROP_PATHS[0]).exists(), "this script is still in the export"

    moved: list[tuple[str, int]] = []
    if args.no_lfs:
        moved = move_big_files(out, build_zip_path)
        if moved:
            print(f"  --no-lfs: moved {len(moved)} file(s) over "
                  f"{BIG_FILE_BYTES / 1024 / 1024:.0f} MB into {build_zip_path.name}")
            for rel, size in moved:
                print(f"    {size / 1024 / 1024:>8.1f} MiB  {rel}")
            # And name them in .gitignore. Without this, unzipping the side zip over the
            # tree - which is step one of using the copy, and is what README.txt says to
            # do - leaves two files of a few hundred megabytes showing as untracked, and
            # the next `git add .` puts them straight into the git that has no LFS to hold
            # them. That is the exact thing --no-lfs exists to avoid.
            with (out / ".gitignore").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    "\n# Exported with --no-lfs: these travel in "
                    "DynamicContents_office_build.zip beside this folder, not in git,\n"
                    "# because they are too big for a git server without LFS. Unzip that "
                    "over the top of\n# this folder after cloning. They are ignored here so "
                    "that doing so does not put them\n# into the repository by the back "
                    "door.\n")
                for rel, _size in moved:
                    handle.write(f"/{rel}\n")
            print(f"    and named them in .gitignore, so unzipping it back over the tree "
                  f"cannot commit them by accident")

    print("  searching every file for anything that must not leave")
    hits, advisories = guard(out)
    if hits:
        print(f"\nNO ZIP WRITTEN. The folder {out} is left in place so the files below "
              f"can be looked at.")
        if advisories:
            report_advisories(advisories)
        return report_hits(hits)
    print("  guard: 0 hits")
    if advisories:
        report_advisories(advisories)

    per, files, total = inventory(out)
    if not args.no_zip:
        make_zip(out, zip_path)

    print(f"\nexport: {out}")
    print(f"{'folder':<28}{'files':>8}{'size':>14}")
    for top in sorted(per):
        count, size = per[top]
        print(f"{top:<28}{count:>8}{size:>13,} B")
    print(f"{'TOTAL':<28}{files:>8}{total:>13,} B  ({total / 1024 / 1024:.1f} MiB)")
    print(f"markdown files: {len(list(out.rglob('*.md')))}")
    print(f'"brief NNN" mentions left: {count_change_notes(out)}')

    big = sorted(((p.relative_to(out).as_posix(), p.stat().st_size) for p in out.rglob("*")
                  if p.is_file() and p.stat().st_size > REPORT_FILE_BYTES),
                 key=lambda row: row[1], reverse=True)
    print(f"\nfiles over {REPORT_FILE_BYTES / 1024 / 1024:.0f} MB in the tree: {len(big)}")
    for rel, size in big:
        print(f"  {size / 1024 / 1024:>8.1f} MiB  {rel}")

    produced: list[tuple[str, int]] = []
    if not args.no_zip:
        produced.append((str(zip_path), zip_path.stat().st_size))
    if moved and build_zip_path.is_file():
        produced.append((str(build_zip_path), build_zip_path.stat().st_size))
    for path, size in produced:
        print(f"\nzip: {path}  {size:,} B  ({size / 1024 / 1024:.1f} MiB)")
    over_fat32 = [(p, s) for p, s in produced if s > 4 * 1024 ** 3 - 1]
    if produced:
        if over_fat32:
            print("a FAT32 stick will NOT take this: a single file cannot be 4 GB or more "
                  "on FAT32. Use an exFAT or NTFS stick, or export with --no-lfs, which "
                  "splits it in two.")
        else:
            print("every file produced is under 4 GB, so a FAT32 stick will take it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
