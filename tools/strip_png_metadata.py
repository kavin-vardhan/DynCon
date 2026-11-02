"""Strip everything that is not the picture out of a PNG.

Some image tools attach a large metadata box to every file they write: a provenance
manifest, an embedded colour profile, a text block naming the machine that made it. None
of that is part of the picture, it is not read by anything this project runs, and it is
the kind of thing that should not travel with a figure that leaves the building.

This keeps only the chunks that define the image - IHDR, PLTE, tRNS, bKGD, gAMA, cHRM,
sRGB, iCCP, pHYs, IDAT, IEND - and drops the rest. Pixels are untouched: the kept chunks
are copied through byte for byte, so the compressed image data is identical and this is
lossless by construction.

Usage
-----
    python tools/strip_png_metadata.py FILE [FILE ...]      rewrite in place
    python tools/strip_png_metadata.py --check FILE [...]    report, change nothing
    python tools/strip_png_metadata.py --all                 every PNG git tracks

It prints one line per file and leaves a file that needs nothing alone.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zlib
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Everything that contributes to how the image decodes or is displayed. A chunk not in
# here is metadata as far as this project is concerned.
KEEP = {b"IHDR", b"PLTE", b"tRNS", b"bKGD", b"gAMA", b"cHRM", b"sRGB", b"iCCP",
        b"pHYs", b"sBIT", b"IDAT", b"IEND"}


def split_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """(type, body) for every chunk, in file order."""
    if not data.startswith(SIGNATURE):
        raise ValueError("not a PNG")
    out: list[tuple[bytes, bytes]] = []
    pos = len(SIGNATURE)
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if len(body) != length:
            raise ValueError(f"truncated {kind!r} chunk")
        stored = int.from_bytes(data[pos + 8 + length:pos + 12 + length], "big")
        if zlib.crc32(kind + body) != stored:
            raise ValueError(f"bad CRC on {kind!r}")
        out.append((kind, body))
        pos += 12 + length
        if kind == b"IEND":
            break
    return out


def rebuild(chunks: list[tuple[bytes, bytes]]) -> bytes:
    parts = [SIGNATURE]
    for kind, body in chunks:
        parts.append(len(body).to_bytes(4, "big"))
        parts.append(kind)
        parts.append(body)
        parts.append(zlib.crc32(kind + body).to_bytes(4, "big"))
    return b"".join(parts)


def strip(path: Path, write: bool) -> bool:
    """True when the file had metadata in it. Writes only when asked to."""
    data = path.read_bytes()
    chunks = split_chunks(data)
    kept = [(kind, body) for kind, body in chunks if kind in KEEP]
    dropped = [(kind.decode("latin-1"), len(body))
               for kind, body in chunks if kind not in KEEP]
    if not dropped:
        print(f"  clean   {path}")
        return False
    rebuilt = rebuild(kept)
    # The point of copying chunks through rather than re-encoding: the image data has to
    # come out the same bytes it went in as.
    before = b"".join(body for kind, body in chunks if kind == b"IDAT")
    after = b"".join(body for kind, body in kept if kind == b"IDAT")
    assert before == after, "the image data changed - refusing to write"
    assert any(kind == b"IHDR" for kind, _ in kept), "no header left"
    what = ", ".join(f"{kind} ({size} B)" for kind, size in dropped)
    if write:
        path.write_bytes(rebuilt)
        print(f"  dropped {path}: {what}  "
              f"({len(data):,} -> {len(rebuilt):,} B)")
    else:
        print(f"  WOULD DROP {path}: {what}")
    return True


def tracked_pngs() -> list[Path]:
    """Every PNG git knows about. Falls back to walking the tree outside a repository."""
    done = subprocess.run(["git", "-C", str(REPO_DIR), "ls-files", "*.png"],
                          capture_output=True, text=True)
    if done.returncode == 0:
        return [REPO_DIR / rel.replace("/", "\\") for rel in done.stdout.split()]
    print("  (not a git repository - walking the tree instead)")
    skip = {"__pycache__", ".venv", "Intermediate", "Saved", "Binaries", "_build"}
    return [p for p in sorted(REPO_DIR.rglob("*.png"))
            if not skip & set(p.relative_to(REPO_DIR).parts)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--all", action="store_true", help="every PNG git tracks")
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args(argv)

    files = list(args.files)
    if args.all:
        files += tracked_pngs()
    if not files:
        ap.error("name some files, or pass --all")

    changed = 0
    for path in files:
        try:
            if strip(path, write=not args.check):
                changed += 1
        except ValueError as exc:
            print(f"  SKIP    {path}: {exc}")
    print(f"{changed} of {len(files)} file(s) had metadata in them")
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
