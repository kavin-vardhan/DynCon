"""Build the `.dcpack` files that play "the brand's computer" (server/demo_files/).

Two jobs:

**fake packs** (the default) — one `.dcpack` per piece-version described by the art
manifests, carrying *seeded random filler* in place of the Unreal containers. The filler is
15–40 MB because a brand uploading content should feel like a real upload; real cooked packs
are 0.25–1.4 MB, and the server paces a download by time, not by size, so both behave the
same at the booth. Add the two built-to-fail files the demo needs (engine 5.3, rated 18+).

**real packs** (`--real`) — wrap the real `unreal\\_packs\\<id>_<v>\\` folders produced by the
UE side (brief 006: `.pak` + `.utoc` + `.ucas` plus `pack.json`) into `.dcpack` files the
server can serve as-is. The moment every piece is cooked, run `--real --plain-name` and the
demo is serving real content with no server change.

`dcpack.json` is a superset of the spike's `pack.json`: the same piece / version / chunk id /
class path / files-with-sizes, plus the fields spec v1 §3 asks for (rating, bounds in metres,
state schema, engine version).

Examples:
    python tools\\make_fake_packs.py                       # 13 fake packs + 2 built to fail
    python tools\\make_fake_packs.py --pieces content1_v1 --force
    python tools\\make_fake_packs.py --real                # <id>_<v>.real.dcpack alongside
    python tools\\make_fake_packs.py --real --plain-name    # real packs replace the fakes
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Iterator

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent
sys.path.insert(0, str(SERVER_DIR))

from dcserver.config import Config                      # noqa: E402
from dcserver.packs import write_dcpack                 # noqa: E402

ART_EXPORT = REPO_DIR / "art" / "export"
CHUNK_TABLE = REPO_DIR / "unreal" / "Tools" / "chunk_ids.json"
REAL_PACKS = REPO_DIR / "unreal" / "_packs"
BLOCK = 4 * 1024 * 1024

# The two files the demo has to be able to reject, and why.
BAD_PACKS = [
    {"suffix": "engine53", "base": "content2_v1", "patch": {"engine_version": "5.3"},
     "why": "built for engine 5.3"},
    {"suffix": "rated18", "base": "content2_v1", "patch": {"rating": "18+"},
     "why": "rated 18+"},
]


def log(quiet: bool, *parts: Any) -> None:
    if not quiet:
        print(*parts, flush=True)


# ----------------------------------------------------------------------------------------
# inputs
# ----------------------------------------------------------------------------------------

def load_chunk_table() -> dict[str, dict[str, Any]]:
    data = json.loads(CHUNK_TABLE.read_text(encoding="utf-8-sig"))
    return {f"{row['id']}_{row['version']}": row for row in data["packs"]}


def load_manifest(key: str) -> dict[str, Any] | None:
    path = ART_EXPORT / key / "manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def class_path_for(piece: str, version: str) -> str:
    folder = f"{piece}_{version}"
    return f"/Game/DCContent/{folder}/BP_DC_{folder}.BP_DC_{folder}_C"


def container_names(chunk_id: int) -> list[str]:
    stem = f"pakchunk{chunk_id}-Windows"
    return [f"{stem}.pak", f"{stem}.utoc", f"{stem}.ucas"]


# ----------------------------------------------------------------------------------------
# dcpack.json
# ----------------------------------------------------------------------------------------

def build_meta(piece: str, version: str, chunk_row: dict[str, Any],
               manifest: dict[str, Any] | None, files: list[dict[str, Any]],
               source: dict[str, Any], *, size_class: str | None = None,
               bounds: dict[str, float] | None = None,
               class_path: str | None = None,
               state_schema: list[str] | None = None,
               units: dict[str, Any] | None = None,
               bounds_cm: dict[str, float] | None = None) -> dict[str, Any]:
    if manifest:
        size = manifest["bounds"]["size"]
        bounds = {"x": round(float(size[0]), 4), "y": round(float(size[1]), 4),
                  "z": round(float(size[2]), 4)}
        size_cm = manifest.get("bounds_cm", {}).get("size")
        if size_cm:
            bounds_cm = {"x": float(size_cm[0]), "y": float(size_cm[1]), "z": float(size_cm[2])}
        size_class = manifest["size_class"]
        state_schema = list(manifest["state_schema"])
        units = manifest.get("units")
    # `default` has an empty state schema — it has no door, switches or screen to remember.
    assert bounds and size_class and state_schema is not None, \
        "need bounds, size class and a state schema (an empty list is fine)"
    meta: dict[str, Any] = {
        "piece": piece,
        "version": version,
        "version_n": int(version.lstrip("v")) if version.lstrip("v").isdigit() else 1,
        "engine_version": "5.7",
        "rating": "all",
        "size_class": size_class,
        "bounds": bounds,
        "class_path": class_path or class_path_for(piece, version),
        "state_schema": state_schema,
        "state_schema_version": int((manifest or {}).get("schema_version", 1)),
        "chunk_id": int(chunk_row["chunk_id"]),
        "files": [{"name": f["name"], "bytes": int(f["bytes"])} for f in files],
        "total_bytes": sum(int(f["bytes"]) for f in files),
        "source": source,
    }
    if bounds_cm:
        meta["bounds_cm"] = bounds_cm
    if units:
        meta["units"] = units
    return meta


# ----------------------------------------------------------------------------------------
# fake packs
# ----------------------------------------------------------------------------------------

def filler(seed: str, total: int) -> Iterator[bytes]:
    """Deterministic incompressible-looking filler, generated a block at a time."""
    rng = random.Random(seed)
    left = total
    while left > 0:
        n = min(BLOCK, left)
        yield rng.randbytes(n)
        left -= n


def fake_sizes(key: str, min_bytes: int, max_bytes: int) -> list[int]:
    """[pak, utoc, ucas] — the real shape: a stub .pak, a small .utoc, the rest in .ucas."""
    rng = random.Random("dcpack-size:" + key)
    total = rng.randint(min_bytes, max_bytes)
    pak = 339
    utoc = rng.randrange(1400, 3900)
    return [pak, utoc, total - pak - utoc]


def make_fake(key: str, chunk_row: dict[str, Any], out_dir: Path, *, min_bytes: int,
              max_bytes: int, patch: dict[str, Any] | None = None,
              name: str | None = None, quiet: bool = False) -> Path | None:
    piece, version = key.rsplit("_", 1)
    manifest = load_manifest(key)
    if not manifest:
        log(quiet, f"  SKIP {key}: no art manifest at art/export/{key}/manifest.json — "
                   f"build the art first")
        return None
    names = container_names(int(chunk_row["chunk_id"]))
    sizes = fake_sizes(key, min_bytes, max_bytes)
    files = [{"name": n, "bytes": s} for n, s in zip(names, sizes)]
    meta = build_meta(piece, version, chunk_row, manifest, files,
                      {"kind": "fake", "filler": "seeded random", "seed": f"dcpack:{key}",
                       "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "generator": "server/tools/make_fake_packs.py"})
    if patch:
        meta.update(patch)
    out = out_dir / (name or f"{key}.dcpack")
    write_dcpack(out, meta, [(f["name"], filler(f"dcpack:{key}:{f['name']}", f["bytes"]))
                             for f in files])
    log(quiet, f"  {out.name}  {out.stat().st_size / (1024 * 1024):.1f} MB  "
               f"({meta['size_class']}, {len(files)} files, chunk {meta['chunk_id']})")
    return out


# ----------------------------------------------------------------------------------------
# real packs
# ----------------------------------------------------------------------------------------

def make_real(key: str, chunk_row: dict[str, Any], out_dir: Path, *, plain_name: bool,
              quiet: bool = False) -> Path | None:
    folder = REAL_PACKS / key
    pack_json = folder / "pack.json"
    if not pack_json.is_file():
        log(quiet, f"  SKIP {key}: no real pack at unreal/_packs/{key}/pack.json")
        return None
    spike = json.loads(pack_json.read_text(encoding="utf-8-sig"))
    piece, version = key.rsplit("_", 1)
    files = []
    for entry in spike["files"]:
        path = folder / entry["name"]
        if not path.is_file():
            log(quiet, f"  SKIP {key}: {entry['name']} is missing from the pack folder")
            return None
        files.append({"name": entry["name"], "bytes": path.stat().st_size})
    manifest = load_manifest(key)
    bounds_cm = spike.get("bounds_cm")
    bounds = None
    if not manifest and bounds_cm:
        bounds = {"x": round(bounds_cm[0] / 100.0, 4), "y": round(bounds_cm[1] / 100.0, 4),
                  "z": round(bounds_cm[2] / 100.0, 4)}
    meta = build_meta(
        piece, version, chunk_row, manifest, files,
        {"kind": "real", "from": f"unreal/_packs/{key}", "cooked_utc": spike.get("built_utc"),
         "cooked_files_in_chunk": spike.get("cooked_files_in_chunk"),
         "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "generator": "server/tools/make_fake_packs.py --real"},
        size_class=spike.get("size_class"), bounds=bounds,
        class_path=spike.get("class_path"),
        state_schema=(manifest or {}).get("state_schema"),
        units=spike.get("units"),
        bounds_cm=({"x": bounds_cm[0], "y": bounds_cm[1], "z": bounds_cm[2]}
                   if bounds_cm else None),
    )
    out = out_dir / (f"{key}.dcpack" if plain_name else f"{key}.real.dcpack")
    write_dcpack(out, meta, [(f["name"], folder / f["name"]) for f in files])
    log(quiet, f"  {out.name}  {out.stat().st_size / 1024:.0f} KB  "
               f"({meta['size_class']}, {len(files)} real files, chunk {meta['chunk_id']})")
    return out


# ----------------------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    cfg = Config.load(SERVER_DIR / "config" / "demo.json")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(SERVER_DIR / "demo_files"),
                    help="where the .dcpack files go (default server/demo_files)")
    ap.add_argument("--pieces", default="", help="comma-separated <id>_<v> keys; default all")
    ap.add_argument("--real", action="store_true", help="wrap the real packs in unreal/_packs")
    ap.add_argument("--plain-name", action="store_true",
                    help="with --real: write <id>_<v>.dcpack, replacing the fake pack")
    ap.add_argument("--min-mb", type=float,
                    default=cfg.packs["fake_filler_min_bytes"] / (1024 * 1024))
    ap.add_argument("--max-mb", type=float,
                    default=cfg.packs["fake_filler_max_bytes"] / (1024 * 1024))
    ap.add_argument("--no-bad", action="store_true", help="skip the two built-to-fail files")
    ap.add_argument("--only-bad", action="store_true", help="only the two built-to-fail files")
    ap.add_argument("--force", action="store_true", help="rebuild files that already exist")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = load_chunk_table()
    keys = [k.strip() for k in args.pieces.split(",") if k.strip()] or list(table)
    unknown = [k for k in keys if k not in table]
    if unknown:
        print(f"not in unreal/Tools/chunk_ids.json: {', '.join(unknown)}", file=sys.stderr)
        return 2

    started = time.time()
    written: list[Path] = []
    min_bytes, max_bytes = int(args.min_mb * 1024 * 1024), int(args.max_mb * 1024 * 1024)

    if not args.only_bad:
        log(args.quiet, f"{'real' if args.real else 'fake'} packs -> {out_dir}")
        for key in keys:
            name = (f"{key}.dcpack" if (not args.real or args.plain_name)
                    else f"{key}.real.dcpack")
            if (out_dir / name).exists() and not args.force:
                log(args.quiet, f"  {name} exists (--force to rebuild)")
                continue
            made = (make_real(key, table[key], out_dir, plain_name=args.plain_name,
                              quiet=args.quiet) if args.real
                    else make_fake(key, table[key], out_dir, min_bytes=min_bytes,
                                   max_bytes=max_bytes, quiet=args.quiet))
            if made:
                written.append(made)

    if not args.no_bad and not args.real:
        log(args.quiet, "built-to-fail files")
        for bad in BAD_PACKS:
            key = bad["base"]
            name = f"{key}_{bad['suffix']}.dcpack"
            if (out_dir / name).exists() and not args.force:
                log(args.quiet, f"  {name} exists (--force to rebuild)")
                continue
            made = make_fake(key, table[key], out_dir, min_bytes=min_bytes,
                             max_bytes=max_bytes, patch=bad["patch"], name=name,
                             quiet=args.quiet)
            if made:
                written.append(made)
                log(args.quiet, f"    ^ {bad['why']} — the server must reject this one")

    total = sum(p.stat().st_size for p in written)
    log(args.quiet, f"wrote {len(written)} file(s), {total / (1024 * 1024):.1f} MB, "
                    f"in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
