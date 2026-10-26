"""The `.dcpack` upload format and the four checks.

A `.dcpack` is one zip file holding `dcpack.json` plus the Unreal container files that
travel together. With IoStore on (the 5.7 default) a pack is **three** files —
`pakchunkN-Windows.pak` (a ~340-byte stub), `.utoc` (the index) and `.ucas` (the assets) —
and the server's only job is to keep them together, hash them and sign them. It never needs
to understand what is inside them.

`dcpack.json` is a superset of the fields the brief 004 spike wrote into `pack.json`:

    piece, version, version_n, engine_version, rating, size_class,
    bounds {x, y, z}            (metres — what the fit check measures)
    bounds_cm {x, y, z}         (optional mirror, the engine's units)
    class_path                  (the Blueprint the game spawns)
    state_schema [...]          (what survives a push-update)
    state_schema_version
    chunk_id                    (which cook chunk these files came out of)
    files [{name, bytes}]       (or plain names — both are accepted)
    total_bytes, units, source  (informational)

The four checks run in this order and stop at the first failure, each with a sentence a
visitor can read: **package → rating → fit → sign**.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import Config
from .signing import KeyStore

META_NAME = "dcpack.json"
CHECK_ORDER = ("package", "rating", "fit", "sign")
REQUIRED_FIELDS = ("piece", "version", "engine_version", "rating", "size_class",
                   "bounds", "class_path", "state_schema", "files")
FIT_TOLERANCE = 1e-6
AXIS_WORDS = {"x": "wide", "y": "deep", "z": "tall"}


class PackRejected(Exception):
    """One of the four checks said no, with a sentence for the visitor."""

    def __init__(self, check: str, sentence: str):
        super().__init__(sentence)
        self.check = check
        self.sentence = sentence


@dataclass
class ParsedPack:
    meta: dict[str, Any]
    piece: str
    version: str
    engine_version: str
    rating: str
    size_class: str
    bounds: dict[str, float]
    class_path: str
    state_schema: list[str]
    state_schema_version: int
    chunk_id: int | None
    files: list[dict[str, Any]] = field(default_factory=list)   # {name, size, sha256}
    total_bytes: int = 0
    record: dict[str, Any] | None = None
    signature: str | None = None
    _zip: zipfile.ZipFile | None = None

    def file_bytes(self, name: str) -> bytes:
        assert self._zip is not None
        with self._zip.open(name) as fh:
            return fh.read()

    def iter_file(self, name: str, chunk: int = 1 << 20) -> Iterable[bytes]:
        assert self._zip is not None
        with self._zip.open(name) as fh:
            while True:
                block = fh.read(chunk)
                if not block:
                    return
                yield block


def mb(n: int | float) -> str:
    return f"{n / (1024 * 1024):.0f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


def metres(v: float) -> str:
    return f"{v:.1f} m"


# ----------------------------------------------------------------------------------------
# writing (the fake-pack generator and the tests use this)
# ----------------------------------------------------------------------------------------

def write_dcpack(path: str | Path, meta: dict[str, Any],
                 files: list[tuple[str, bytes | Path | Iterable[bytes]]]) -> Path:
    """Write a .dcpack. Containers go in uncompressed — their sizes should be honest."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(META_NAME, json.dumps(meta, indent=1))
        for name, source in files:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED
            with zf.open(info, "w") as fh:
                if isinstance(source, (bytes, bytearray, memoryview)):
                    fh.write(source)
                elif isinstance(source, Path):
                    with open(source, "rb") as src:
                        for block in iter(lambda: src.read(1 << 20), b""):
                            fh.write(block)
                else:
                    for block in source:
                        fh.write(block)
    tmp.replace(out)
    return out


def peek_dcpack(path: str | Path) -> dict[str, Any] | None:
    """dcpack.json out of a file on disk, or None if it cannot be read."""
    try:
        with zipfile.ZipFile(path) as zf:
            return json.loads(zf.read(META_NAME).decode("utf-8-sig"))
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
        return None


# ----------------------------------------------------------------------------------------
# the four checks
# ----------------------------------------------------------------------------------------

def check_package(blob: bytes, cfg: Config, expect_piece: str | None = None) -> ParsedPack:
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise PackRejected("package", "That file is not a .dcpack package — it is not a valid zip.")
    names = set(zf.namelist())
    if META_NAME not in names:
        raise PackRejected("package", f"The package has no {META_NAME}, so there is no way to tell "
                                      "what is inside it.")
    try:
        meta = json.loads(zf.read(META_NAME).decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise PackRejected("package", f"{META_NAME} is not valid JSON.")
    if not isinstance(meta, dict):
        raise PackRejected("package", f"{META_NAME} should describe one pack.")

    missing = [f for f in REQUIRED_FIELDS if f not in meta]
    if missing:
        raise PackRejected("package", f"{META_NAME} is missing: {', '.join(missing)}.")

    listed: list[str] = []
    for entry in meta["files"]:
        listed.append(entry if isinstance(entry, str) else entry.get("name", ""))
    listed = [n for n in listed if n]
    if not listed:
        raise PackRejected("package", f"{META_NAME} lists no files, so there is nothing to mount.")
    for name in listed:
        if name not in names:
            raise PackRejected("package", f"The package lists {name} but does not contain it.")

    files: list[dict[str, Any]] = []
    total = 0
    for name in listed:
        size = zf.getinfo(name).file_size
        total += size
        files.append({"name": name, "size": int(size)})
    if total > cfg.max_pack_bytes:
        raise PackRejected("package", f"This pack is {mb(total)} — the limit for the demo is "
                                      f"{mb(cfg.max_pack_bytes)}.")
    if str(meta["engine_version"]) != cfg.engine_version:
        raise PackRejected("package", f"Made for engine {meta['engine_version']} — this game runs "
                                      f"{cfg.engine_version}.")
    if meta["size_class"] not in cfg.size_classes:
        raise PackRejected("package", f"Size class '{meta['size_class']}' is not one this demo knows "
                                      f"({', '.join(cfg.size_classes)}).")
    bounds = meta["bounds"]
    if not isinstance(bounds, dict) or any(a not in bounds for a in ("x", "y", "z")):
        raise PackRejected("package", "bounds must give x, y and z in metres.")
    try:
        bounds = {a: float(bounds[a]) for a in ("x", "y", "z")}
    except (TypeError, ValueError):
        raise PackRejected("package", "bounds x, y and z must be numbers (metres).")
    if any(v <= 0 for v in bounds.values()):
        raise PackRejected("package", "bounds must be bigger than zero in every direction.")
    if not str(meta["class_path"]).startswith("/Game/"):
        raise PackRejected("package", "class_path must be a game asset path starting with /Game/.")
    if not isinstance(meta["state_schema"], list):
        raise PackRejected("package", "state_schema must be the list of things kept across an update.")
    if expect_piece is not None and str(meta["piece"]) != expect_piece:
        raise PackRejected("package", f"This update is {meta['piece']}, but this campaign's content "
                                      f"is {expect_piece}.")

    return ParsedPack(
        meta=meta, piece=str(meta["piece"]), version=str(meta["version"]),
        engine_version=str(meta["engine_version"]), rating=str(meta["rating"]),
        size_class=str(meta["size_class"]), bounds=bounds, class_path=str(meta["class_path"]),
        state_schema=[str(s) for s in meta["state_schema"]],
        state_schema_version=int(meta.get("state_schema_version", 1)),
        chunk_id=meta.get("chunk_id"), files=files, total_bytes=total, _zip=zf,
    )


def check_rating(parsed: ParsedPack, cfg: Config) -> str:
    if parsed.rating not in cfg.allowed_ratings:
        raise PackRejected("rating", f"Rated {parsed.rating} — this demo only accepts content rated "
                                     "for everyone.")
    return f"Rated {parsed.rating}."


def fit_failure(bounds: dict[str, float], limits: dict[str, float]) -> tuple[str, str] | None:
    """(axis, sentence tail) of the first axis that does not fit, or None."""
    for axis in ("z", "x", "y"):
        if bounds[axis] > limits[axis] + FIT_TOLERANCE:
            return axis, f"{metres(bounds[axis])} against a {metres(limits[axis])} limit"
    return None


def check_fit(parsed: ParsedPack, cfg: Config) -> str:
    limits = cfg.limits(parsed.size_class)
    bad = fit_failure(parsed.bounds, limits)
    if bad:
        axis, tail = bad
        raise PackRejected("fit", f"Too {AXIS_WORDS[axis]} for size class {parsed.size_class} — "
                                  f"{tail}.")
    return (f"Fits size class {parsed.size_class} "
            f"({metres(parsed.bounds['x'])} x {metres(parsed.bounds['y'])} x "
            f"{metres(parsed.bounds['z'])}).")


def check_sign(parsed: ParsedPack, cfg: Config, keys: KeyStore) -> str:
    """SHA-256 every file, then sign the record that names them."""
    for entry in parsed.files:
        digest = hashlib.sha256()
        read = 0
        try:
            for block in parsed.iter_file(entry["name"]):
                digest.update(block)
                read += len(block)
        except (OSError, zipfile.BadZipFile):
            raise PackRejected("sign", f"Could not read {entry['name']} out of the package to hash it.")
        if read != entry["size"]:
            raise PackRejected("sign", f"{entry['name']} is {read} bytes but the package says "
                                       f"{entry['size']}.")
        entry["sha256"] = digest.hexdigest()
    parsed.record = {
        "piece": parsed.piece,
        "version": parsed.version,
        "engine_version": parsed.engine_version,
        "rating": parsed.rating,
        "size_class": parsed.size_class,
        "class_path": parsed.class_path,
        "state_schema": parsed.state_schema,
        "state_schema_version": parsed.state_schema_version,
        "files": [{"name": f["name"], "size": f["size"], "sha256": f["sha256"]} for f in parsed.files],
        "total_bytes": parsed.total_bytes,
    }
    parsed.signature = keys.sign(parsed.record)
    return (f"Signed: {len(parsed.files)} file"
            f"{'s' if len(parsed.files) != 1 else ''}, {mb(parsed.total_bytes)}, "
            f"key {keys.fingerprint()}.")


def run_checks(blob: bytes, cfg: Config, keys: KeyStore,
               expect_piece: str | None = None) -> tuple[ParsedPack | None, list[dict[str, Any]]]:
    """All four, in order, stopping at the first failure.

    Returns (parsed or None, the four check rows). The rows are what the portal animates:
    ok=True passed, ok=False failed, ok=None never ran because an earlier check failed.
    """
    rows = [{"check": name, "ok": None, "state": "skipped", "detail": ""} for name in CHECK_ORDER]
    by_name = {r["check"]: r for r in rows}

    def passed(name: str, detail: str) -> None:
        by_name[name].update(ok=True, state="ok", detail=detail)

    parsed: ParsedPack | None = None
    try:
        parsed = check_package(blob, cfg, expect_piece=expect_piece)
        passed("package", f"{parsed.piece} {parsed.version}, {len(parsed.files)} files, "
                          f"{mb(parsed.total_bytes)}, engine {parsed.engine_version}.")
        passed("rating", check_rating(parsed, cfg))
        passed("fit", check_fit(parsed, cfg))
        passed("sign", check_sign(parsed, cfg, keys))
    except PackRejected as rejected:
        by_name[rejected.check].update(ok=False, state="failed", detail=rejected.sentence)
        return None, rows
    return parsed, rows


def fits_slots(bounds: dict[str, float], cfg: Config) -> dict[str, dict[str, Any]]:
    """Which slots this content could go in, with the reason when it could not."""
    out: dict[str, dict[str, Any]] = {}
    for slot in cfg.slots:
        limits = cfg.limits(slot.size_class)
        bad = fit_failure(bounds, limits)
        if bad:
            axis, tail = bad
            out[slot.id] = {"ok": False,
                            "reason": f"Too {AXIS_WORDS[axis]} for this slot — {tail}."}
        else:
            out[slot.id] = {"ok": True, "reason": f"Fits this {slot.size_class} slot."}
    return out
