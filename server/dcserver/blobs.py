"""Where pack bytes live.

`Blobs` is the whole of what the rest of the server knows about storage. The local
implementation (`FsBlobs`) keeps the files under data/packs/<pack_id>/<name> and hands out
signed, expiring links back to this server's own /files route. An `S3Blobs` later answers the
same four questions with boto3 presigned URLs — nothing else in the server changes.
"""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import quote

from .signing import UrlSigner

CHUNK = 256 * 1024


class Blobs(ABC):
    @abstractmethod
    def put(self, pack_id: str, name: str, data: bytes | Iterable[bytes]) -> int:
        """Store one file; returns the number of bytes stored."""

    @abstractmethod
    def exists(self, pack_id: str, name: str) -> bool: ...

    @abstractmethod
    def size(self, pack_id: str, name: str) -> int: ...

    @abstractmethod
    def read_range(self, pack_id: str, name: str, start: int, end: int) -> Iterator[bytes]:
        """Yield bytes [start, end] inclusive."""

    @abstractmethod
    def signed_url(self, pack_id: str, name: str, *, now: datetime, ttl_s: int) -> str: ...

    @abstractmethod
    def delete_pack(self, pack_id: str) -> None: ...


class FsBlobs(Blobs):
    def __init__(self, root: str | Path, url_signer: UrlSigner, base_url: str = ""):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.signer = url_signer
        self.base_url = base_url.rstrip("/")

    def path(self, pack_id: str, name: str) -> Path:
        safe = Path(name).name              # never let a listed file name escape its pack
        return self.root / pack_id / safe

    def put(self, pack_id: str, name: str, data: bytes | Iterable[bytes]) -> int:
        p = self.path(pack_id, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open(p, "wb") as fh:
            if isinstance(data, (bytes, bytearray, memoryview)):
                fh.write(data)
                written = len(data)
            else:
                for chunk in data:
                    fh.write(chunk)
                    written += len(chunk)
        return written

    def exists(self, pack_id: str, name: str) -> bool:
        return self.path(pack_id, name).is_file()

    def size(self, pack_id: str, name: str) -> int:
        return self.path(pack_id, name).stat().st_size

    def read_range(self, pack_id: str, name: str, start: int, end: int) -> Iterator[bytes]:
        remaining = end - start + 1
        if remaining <= 0:
            return
        with open(self.path(pack_id, name), "rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(CHUNK, remaining))
                if not chunk:
                    return
                remaining -= len(chunk)
                yield chunk

    def signed_url(self, pack_id: str, name: str, *, now: datetime, ttl_s: int) -> str:
        exp = int(now.timestamp()) + int(ttl_s)
        sig = self.signer.sign(pack_id, name, exp)
        return f"{self.base_url}/files/{quote(pack_id)}/{quote(name)}?exp={exp}&sig={sig}"

    def delete_pack(self, pack_id: str) -> None:
        shutil.rmtree(self.root / pack_id, ignore_errors=True)
