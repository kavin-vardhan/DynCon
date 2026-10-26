"""Small helpers for building the odd .dcpack a test needs."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from dcserver.packs import META_NAME, write_dcpack


def patch_dcpack(src: Path, dst: Path, drop: list[str] | None = None, **patch: Any) -> Path:
    """Copy a .dcpack with dcpack.json changed — how a test builds a pack that must fail."""
    with zipfile.ZipFile(src) as zf:
        meta = json.loads(zf.read(META_NAME).decode("utf-8-sig"))
        for key in drop or []:
            meta.pop(key, None)
        meta.update(patch)
        files = [(name, zf.read(name)) for name in zf.namelist() if name != META_NAME]
    return write_dcpack(dst, meta, files)


def build_dcpack(dst: Path, *, piece: str = "content1", version: str = "v1",
                 size_class: str = "L", bounds: dict[str, float] | None = None,
                 files: dict[str, bytes] | None = None, **patch: Any) -> Path:
    """A minimal pack built from nothing, for the cases no generated pack covers."""
    body = files if files is not None else {"pakchunk100-Windows.pak": b"x" * 64,
                                            "pakchunk100-Windows.utoc": b"y" * 32,
                                            "pakchunk100-Windows.ucas": b"z" * 256}
    meta: dict[str, Any] = {
        "piece": piece, "version": version, "version_n": 1, "engine_version": "5.7",
        "rating": "all", "size_class": size_class,
        "bounds": bounds or {"x": 12.0, "y": 10.0, "z": 6.0},
        "class_path": f"/Game/DCContent/{piece}_{version}/BP_DC_{piece}_{version}"
                      f".BP_DC_{piece}_{version}_C",
        "state_schema": ["light_a_on", "light_b_on", "door_open", "screen_image_index"],
        "state_schema_version": 1, "chunk_id": 100,
        "files": [{"name": n, "bytes": len(b)} for n, b in body.items()],
        "total_bytes": sum(len(b) for b in body.values()),
    }
    meta.update(patch)
    return write_dcpack(dst, meta, list(body.items()))


def not_a_zip(dst: Path) -> Path:
    dst.write_bytes(b"this is not a zip file, it is a sentence")
    return dst


def zip_without_meta(dst: Path) -> Path:
    with zipfile.ZipFile(dst, "w") as zf:
        zf.writestr("pakchunk100-Windows.pak", b"x" * 10)
    return dst


def zip_with_broken_meta(dst: Path) -> Path:
    with zipfile.ZipFile(dst, "w") as zf:
        zf.writestr(META_NAME, "{ not json at all")
    return dst


def upload_bytes(client, blob: bytes, name: str = "hand_made.dcpack",
                 content_id: str | None = None) -> dict:
    where = f"/content/{content_id}/versions" if content_id else "/content"
    response = client.post(where, files={"file": (name, blob, "application/octet-stream")})
    assert response.status_code == 200, response.text[:300]
    return response.json()
