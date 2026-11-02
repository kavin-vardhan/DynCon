"""Build a clean, history-free copy of this project for an internal (office) git.

Why this exists
---------------
The project is developed in one repository and carried into an internal network as a
fresh tree with no history: the person carrying it in runs `git init`, commits and pushes
there under their office identity. Two things therefore have to be true of what leaves:

1. only files the repository actually tracks may leave - nothing from a working tree
   (keys, generated data, virtual environments, build outputs, cooked packs) can slip in;
2. nothing in it may carry personal identity or anything about how it was written.

Point 1 is handled by building the export out of `git archive HEAD`, so an untracked or
ignored file is not merely skipped but impossible to include. Point 2 is handled by the
guard below, which is run over every byte of the staged export - text and binary - and
refuses to produce the zip if it finds anything.

The export also carries no Markdown at all: the documentation set is written for the
development repository and the office adds its own, so `*.md` is dropped wholesale.

What it produces
----------------
    E:\\DynamicContents_office\\      the folder, with no .git, no __pycache__, no venv
    E:\\DynamicContents_office.zip    the same tree zipped

Both are replaced on each run. Neither is inside the repository.

Usage
-----
    python tools/make_office_export.py                 build the folder and the zip
    python tools/make_office_export.py --no-zip        build the folder only
    python tools/make_office_export.py --out DIR       build somewhere else
    python tools/make_office_export.py --scan DIR      only run the guard, over DIR

Exit code 0 means the export is complete and the guard found nothing. Exit code 1 means
the guard found something: the offending files are listed and no zip is written.

Run it with an interpreter that has `zstandard` installed (`server/.venv` has it). Blender
saves a .blend as a Zstandard frame, and the guard refuses to finish rather than leave a
compressed file unsearched. Python 3.14 and later can do it with the standard library
alone, so the dependency will fall away in time.
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
DEFAULT_OUT = Path(r"E:\DynamicContents_office")

# ---------------------------------------------------------------------------------------
# What is dropped from the export
# ---------------------------------------------------------------------------------------
# `*.md`: the whole documentation set. It is written for the development repository and
#   references a workflow the office does not share; the office writes its own.
# This script: it only has a job in the development repository, and it is the one file
#   that must contain the guard's search terms verbatim, so leaving it in would be both
#   pointless and self-defeating.
DROP_SUFFIXES = (".md",)
DROP_PATHS = ("tools/make_office_export.py",)

# Written fresh into the export (see `write_gitignore`). The repository's own version has
# two rules that only mean something to the development machine.
GITIGNORE_NAME = ".gitignore"

# ---------------------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------------------
# Every term that must not appear anywhere in the export: not in a file's text, not in a
# comment, not in a file or folder name, and not inside a binary. Matching is
# case-insensitive.
#
# The last column is whether a match inside a binary has to look like part of a real
# string to count. It is set only for `opus`, and the reason is arithmetic: four letters
# matched either case will turn up in compressed bytes by chance roughly once every
# 300 MB searched, and this export is 115 MB over three views of every file. One such
# coincidence is already known (inside a Blender file, in bytes that decompress to
# nothing of the kind). Every other term here is at least six letters, where the same
# arithmetic puts a chance match at about one in ten thousand exports, so those are taken
# literally wherever they appear.
GUARD_TERMS: list[tuple[str, re.Pattern[str], bool]] = [
    ("claude", re.compile(r"claude", re.I), False),
    ("anthropic", re.compile(r"anthropic", re.I), False),
    ("gmail", re.compile(r"gmail", re.I), False),
    ("kavinvardhan", re.compile(r"kavinvardhan", re.I), False),
    ("kavin-vardhan", re.compile(r"kavin-vardhan", re.I), False),
    ("dyncon", re.compile(r"dyncon", re.I), False),
    ("mrtocsik", re.compile(r"mrtocsik", re.I), False),
    ("cowork", re.compile(r"cowork", re.I), False),
    ("Co-Authored-By", re.compile(r"co-authored-by", re.I), False),
    ("opus (as a word)", re.compile(r"(?<![A-Za-z])opus(?![A-Za-z])", re.I), True),
]

# How many printable characters in a row a match has to sit inside, in a binary, for the
# terms marked above. A string a tool or a person left in a file - a name, a path, a
# version line - has punctuation or neighbouring words around it and clears this easily;
# four letters thrown up by a compressor are bounded by bytes that are not printable.
MIN_STRING_RUN = 8


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


def _search(text: str, rel: str, where: str, hits: list[Hit], *,
            textual: bool = True) -> None:
    """Every guard term, over one view of one file.

    `textual` says the view is something a person reads - a source file, a declared text
    chunk - so a match counts wherever it falls. A view of binary bytes is held to the
    string test above for the terms that ask for it.
    """
    for term, pattern, needs_string in GUARD_TERMS:
        for match in pattern.finditer(text):
            if needs_string and not textual and _string_run(text, match) < MIN_STRING_RUN:
                continue               # four letters of compressor output, not a string
            hits.append(Hit(rel, term, where, _snippet(text, match)))
            break                      # one example per term per view is enough


def _png_text_chunks(data: bytes) -> list[str]:
    """Every tEXt / zTXt / iTXt chunk in a PNG, decompressed where it is compressed.

    Raw UTF-8 scanning already sees an uncompressed chunk; this is for the compressed
    ones, where the string an image-writing tool left behind would otherwise be hidden.
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

    This is what reaches a PDF's compressed page text and its XMP metadata packet, and
    the compressed blocks of any other container that stores strings that way.
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
            "(server/.venv has it), or with Python 3.14 or later:\n"
            "    server\\.venv\\Scripts\\python.exe tools\\make_office_export.py")
    # A .blend has no frame content size in its header, so stream it rather than asking
    # for a one-shot decompress.
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


def scan_file(path: Path, rel: str) -> list[Hit]:
    """Run every guard term over one file: its name, its text, and inside its bytes."""
    hits: list[Hit] = []
    _search(rel, rel, "the path", hits)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"could not read {rel}: {exc}")

    # A file whose every byte is valid UTF-8 is one somebody wrote; anything else is a
    # binary, and a four-letter match in it has to look like part of a string (see
    # GUARD_TERMS).
    try:
        data.decode("utf-8")
        textual = True
    except UnicodeDecodeError:
        textual = False

    # UTF-8. Invalid bytes are dropped, never consumed as part of a sequence, so every
    # run of ASCII in a binary survives into the decoded text.
    _search(data.decode("utf-8", "ignore"), rel, "UTF-8", hits, textual=textual)

    # UTF-16LE, at both alignments: .uasset and other engine formats store wide strings
    # that way, and a string can start on an odd byte.
    for offset in (0, 1):
        _search(data[offset:].decode("utf-16-le", "ignore"), rel,
                f"UTF-16LE+{offset}", hits, textual=False)

    suffix = path.suffix.lower()
    if suffix == ".png":
        # tEXt / zTXt / iTXt are declared text, so they are read as text.
        for n, chunk in enumerate(_png_text_chunks(data)):
            _search(chunk, rel, f"PNG text chunk {n}", hits, textual=True)
    if suffix in (".pdf", ".fbx", ".glb"):
        for n, blob in enumerate(_inflated_streams(data)):
            _search(blob, rel, f"compressed stream {n}", hits, textual=False)
    whole = _decompressed_whole_file(data)
    if whole:
        _search(whole, rel, "decompressed container", hits, textual=False)
    return hits


def guard(root: Path) -> list[Hit]:
    """Every hit anywhere under `root`, folder names included."""
    hits: list[Hit] = []
    files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        for name in dirnames:
            rel = (here / name).relative_to(root).as_posix() + "/"
            _search(rel, rel, "the folder name", hits)
        for name in sorted(filenames):
            path = here / name
            rel = path.relative_to(root).as_posix()
            hits.extend(scan_file(path, rel))
            files += 1
            if files % 200 == 0:
                print(f"    searched {files} files...", flush=True)
    print(f"    searched {files} files, {sum(1 for _ in root.rglob('*') if _.is_dir())} "
          f"folders", flush=True)
    return hits


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
    # produce these, so this is belt and braces.
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
# Note there is no rule for *.md: the documentation this tree ships with is the office's
# own, and it has to be committable.

__pycache__/
*.pyc
*.log
*.blend1
Thumbs.db
desktop.ini
.vscode/
.idea/

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

# Packaged builds, and the runtime packs cut out of them by the staging script.
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

# The demo server: its virtual environment, everything it generates at runtime (signing
# keys, the sqlite database, stored packs, client caches) and the generated .dcpack files.
# The generator script is committed; its output is not.
server/.venv/
server/data/
server/demo_files/*.dcpack
server/.pytest_cache/

# The portal's exit-test screenshots, same rule as the art previews: the per-screen PNGs
# are megabytes a run and `booth/portal_exit_test.py` rebuilds all of them in under a
# minute, so only the contact sheet is committed.
portal/_shots/*/[0-9]*.png
portal/_shots/*/*.log
portal/_shots/*/audit.txt
!portal/_shots/*/contact_sheet.png

# The preview window's exit test, same rule again: the per-beat portal shots and the full
# desktop captures are rebuilt by `booth/preview_exit_test.py`, so what is committed is
# the two contact sheets and the three crops of the preview window's own rectangle.
booth/_shots/*/[0-9]*.png
booth/_shots/*/desktop_*.png
booth/_shots/*/*.log
!booth/_shots/*/contact_sheet*.png
!booth/_shots/*/previewarea_*.png
!booth/_shots/*/mainwindow_*.png
"""


def write_gitignore(root: Path) -> None:
    (root / GITIGNORE_NAME).write_text(GITIGNORE_TEXT, encoding="utf-8", newline="\n")


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
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root).as_posix())


# ---------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"where to write the export folder (default {DEFAULT_OUT})")
    ap.add_argument("--no-zip", action="store_true", help="build the folder only")
    ap.add_argument("--scan", type=Path, default=None,
                    help="do not export; only run the guard over this folder")
    args = ap.parse_args(argv)

    if args.scan is not None:
        root = args.scan.resolve()
        if not root.is_dir():
            raise SystemExit(f"not a folder: {root}")
        print(f"searching {root} for anything that must not leave")
        hits = guard(root)
        return report_hits(hits)

    out = args.out.resolve()
    if out == REPO_DIR or REPO_DIR in out.parents or out in REPO_DIR.parents:
        raise SystemExit(f"the export must be outside the repository, not {out}")
    zip_path = out.with_suffix(".zip")

    head = git("rev-parse", "--short", "HEAD").strip()
    dirty = git("status", "--porcelain").strip()
    print(f"exporting HEAD {head}"
          + (f" (working tree has {len(dirty.splitlines())} uncommitted change(s) - they "
             f"are NOT in the export)" if dirty else ""))

    for stale in (out, zip_path):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()
    out.mkdir(parents=True)

    written = stage_from_git_archive(out)
    print(f"  staged {len(written)} tracked file(s) from git archive")

    dropped = drop_unwanted(out)
    print(f"  dropped {len(dropped)}:")
    for rel in dropped:
        print(f"    - {rel}")

    write_gitignore(out)
    print(f"  wrote a clean {GITIGNORE_NAME}")

    for gone in (".git", "__pycache__"):
        assert not list(out.rglob(gone)), f"{gone} is still in the export"
    assert not list(out.rglob("*.md")), "a .md file is still in the export"
    assert not (out / DROP_PATHS[0]).exists(), "this script is still in the export"

    print("  searching every file for anything that must not leave")
    hits = guard(out)
    if hits:
        print(f"\nNO ZIP WRITTEN. The folder {out} is left in place so the files below "
              f"can be looked at.")
        return report_hits(hits)
    print("  guard: 0 hits")

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
    if not args.no_zip:
        zsize = zip_path.stat().st_size
        print(f"zip: {zip_path}  {zsize:,} B  ({zsize / 1024 / 1024:.1f} MiB)")
    return 0


def report_hits(hits: list[Hit]) -> int:
    if not hits:
        print("guard: 0 hits")
        return 0
    print(f"\nGUARD FAILED: {len(hits)} hit(s)")
    for hit in hits:
        print(f"  {hit}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
