"""The fake game client — the game's side of the delivery path, without Unreal.

What it does, exactly what the UE plugin will do (spec v1 §6):

1. `GET /client-config` once, for the poll interval and the **public key**;
2. `GET /changes?game=&region=` on a loop; a slot whose `alloc_key` changed needs resolving;
3. `GET /resolve` for that slot, then **verify the RS256 signature** with the public key
   before trusting a single field of it;
4. download every file of the pack with **Range resume**, checking **SHA-256**, into an LRU
   cache folder keyed by pack id;
5. print what it would mount:

       MOUNT A1 content1 v2 brand #E23D3D star
       MOUNT A3 rivalsmall v1 rival #1FA39A triangle
       MOUNT A2 default v1 no-brand
       FALLBACK B1 default (sha256 mismatch on pakchunk103-Windows.ucas)

   A FALLBACK means the slot keeps showing the developer's default; the client then retries
   the slot once, which is what the "serve a corrupt pack" trick is supposed to look like.
6. post a few telemetry events for what it mounted.

Examples:
    python tools\\fake_client.py --game A --region r1 --once
    python tools\\fake_client.py --game A --region r1 --seconds 60
    python tools\\fake_client.py --game B --region r2 --slots B2 --once --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from dcserver.signing import verify_with_public_pem      # noqa: E402

CHUNK = 1 << 20
DEFAULT_CACHE = SERVER_DIR / "data" / "client_cache"


class VerifyFailed(Exception):
    """The reason a slot fell back to default."""


def brand_words(manifest: dict[str, Any]) -> str:
    brand = manifest.get("brand")
    kind = (manifest.get("showing") or {}).get("kind", "visitor")
    if not brand:
        return "no-brand"
    return f"{'rival' if kind == 'rival' else 'brand'} {brand['colour']} {brand['emblem']}"


def mount_line(slot: str, manifest: dict[str, Any]) -> str:
    content = manifest["content"]
    return f"MOUNT {slot} {content['piece']} {content['version']} {brand_words(manifest)}"


@dataclass
class Cache:
    root: Path
    keep: int = 8

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def dir_for(self, pack_id: str) -> Path:
        p = self.root / pack_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def touch(self, pack_id: str) -> None:
        (self.dir_for(pack_id) / ".used").write_text(str(time.time()), encoding="utf-8")

    def purge(self, pack_ids: list[str]) -> list[str]:
        gone = []
        for pack_id in pack_ids:
            path = self.root / pack_id
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
                gone.append(pack_id)
        return gone

    def evict(self, protect: set[str]) -> list[str]:
        packs = [p for p in self.root.iterdir() if p.is_dir()]
        if len(packs) <= self.keep:
            return []
        used = sorted(packs, key=lambda p: (p / ".used").stat().st_mtime
                      if (p / ".used").exists() else 0.0)
        dropped = []
        for path in used:
            if len(packs) - len(dropped) <= self.keep:
                break
            if path.name in protect:
                continue
            shutil.rmtree(path, ignore_errors=True)
            dropped.append(path.name)
        return dropped


@dataclass
class Stats:
    mounts: int = 0
    fallbacks: int = 0
    resolves: int = 0
    downloaded_bytes: int = 0
    cached_files: int = 0
    resumes: int = 0
    lines: list[str] = field(default_factory=list)


class FakeClient:
    def __init__(self, url: str, game: str, region: str, *, cache: Path | None = None,
                 keep: int | None = None, slots: list[str] | None = None,
                 telemetry: bool = True, verbose: bool = False, as_json: bool = False):
        self.base = url.rstrip("/") + "/"
        self.game, self.region = game, region
        self.only_slots = slots or []
        self.telemetry_on = telemetry
        self.verbose, self.as_json = verbose, as_json
        self.http = httpx.Client(base_url=self.base, timeout=60.0)
        self.known: dict[str, str] = {}
        self.stats = Stats()
        self.config: dict[str, Any] = {}
        self.public_pem = ""
        self.generation = -1
        self.cache = Cache(Path(cache) if cache else DEFAULT_CACHE, keep or 8)
        self.mounted: dict[str, dict[str, Any]] = {}

    # ---- plumbing ------------------------------------------------------------------

    def say(self, line: str) -> None:
        self.stats.lines.append(line)
        print(line, flush=True)

    def note(self, line: str) -> None:
        if self.verbose:
            print(f"    {line}", flush=True)

    def start(self) -> None:
        self.config = self.http.get("client-config").raise_for_status().json()
        self.public_pem = self.config["public_key_pem"]
        self.cache.keep = int(self.config.get("cache_packs") or self.cache.keep)
        self.generation = int(self.config.get("reset_generation", 0))
        self.note(f"client-config: poll {self.config['poll_interval_s']}s, "
                  f"pacing {self.config.get('pacing_seconds')}s, key ok")

    # ---- the loop ------------------------------------------------------------------

    def poll_once(self) -> dict[str, str]:
        changes = self.http.get("changes", params={"game": self.game,
                                                   "region": self.region}).raise_for_status().json()
        generation = int(changes.get("reset_generation", 0))
        if generation != self.generation:
            purged = self.cache.purge(list(changes.get("purge_packs") or []))
            if purged:
                self.note(f"reset {generation}: purged {len(purged)} visitor pack(s) from cache")
            self.generation = generation
            self.known.clear()
            self.mounted.clear()
        todo = {}
        for slot, key in changes["slots"].items():
            if self.only_slots and slot not in self.only_slots:
                continue
            if self.known.get(slot) != key:
                todo[slot] = key
        for slot, key in todo.items():
            self.handle_slot(slot, key)
        return todo

    def run(self, seconds: float) -> Stats:
        self.start()
        interval = float(self.config.get("poll_interval_s") or 1.5)
        deadline = time.monotonic() + seconds
        self.poll_once()
        while time.monotonic() < deadline:
            time.sleep(min(interval, max(deadline - time.monotonic(), 0.01)))
            self.poll_once()
        return self.finish()

    def run_once(self) -> Stats:
        self.start()
        self.poll_once()
        return self.finish()

    def finish(self) -> Stats:
        s = self.stats
        self.say(f"DONE mounts={s.mounts} fallbacks={s.fallbacks} resolves={s.resolves} "
                 f"downloaded={s.downloaded_bytes / (1024 * 1024):.1f}MB "
                 f"cached={s.cached_files} resumes={s.resumes}")
        if self.as_json:
            print(json.dumps({"lines": s.lines, "mounts": s.mounts,
                              "fallbacks": s.fallbacks,
                              "mounted": self.mounted}, indent=1), flush=True)
        self.http.close()
        return s

    # ---- one slot ------------------------------------------------------------------

    def handle_slot(self, slot: str, key: str) -> None:
        try:
            manifest = self.resolve(slot)
        except (httpx.HTTPError, VerifyFailed) as first:
            self.stats.fallbacks += 1
            self.say(f"FALLBACK {slot} default ({first})")
            return
        try:
            self.fetch_pack(manifest)
        except (VerifyFailed, httpx.HTTPError) as first:
            self.stats.fallbacks += 1
            self.say(f"FALLBACK {slot} default ({first})")
            # exactly what the UE client does: keep the default up, then try the slot again
            try:
                manifest = self.resolve(slot)
                self.fetch_pack(manifest)
            except (VerifyFailed, httpx.HTTPError) as second:
                self.say(f"FALLBACK {slot} default (retry also failed: {second})")
                return
        self.known[slot] = manifest["alloc_key"]
        self.mounted[slot] = {"piece": manifest["content"]["piece"],
                              "version": manifest["content"]["version"],
                              "alloc_key": manifest["alloc_key"],
                              "pack_id": manifest["pack"]["id"],
                              "brand": manifest.get("brand"),
                              "kind": (manifest.get("showing") or {}).get("kind")}
        self.stats.mounts += 1
        self.cache.touch(manifest["pack"]["id"])
        dropped = self.cache.evict(protect={m["pack_id"] for m in self.mounted.values()})
        if dropped:
            self.note(f"cache: evicted {', '.join(dropped)}")
        self.say(mount_line(slot, manifest))
        if self.telemetry_on:
            self.post_telemetry(slot, manifest)

    def resolve(self, slot: str) -> dict[str, Any]:
        response = self.http.get("resolve", params={"game": self.game, "slot": slot,
                                                    "region": self.region})
        if response.status_code != 200:
            raise VerifyFailed(f"resolve said {response.status_code}: "
                               f"{response.json().get('error', response.text)[:120]}")
        manifest = response.json()
        self.stats.resolves += 1
        signature = manifest.pop("signature", None)
        if not signature:
            raise VerifyFailed("the manifest carries no signature")
        if not verify_with_public_pem(self.public_pem, manifest, signature):
            raise VerifyFailed("the manifest signature did not verify")
        manifest["signature"] = signature
        return manifest

    # ---- downloading ---------------------------------------------------------------

    def fetch_pack(self, manifest: dict[str, Any]) -> None:
        pack = manifest["pack"]
        folder = self.cache.dir_for(pack["id"])
        for entry in pack["files"]:
            target = folder / entry["name"]
            if target.exists() and target.stat().st_size == entry["size"]:
                if sha256_file(target) == entry["sha256"]:
                    self.stats.cached_files += 1
                    self.note(f"cached {entry['name']}")
                    continue
                target.unlink(missing_ok=True)
            self.download(entry, target)

    def download(self, entry: dict[str, Any], target: Path) -> None:
        url = urljoin(self.base, entry["url"].lstrip("/"))
        size = int(entry["size"])
        part = target.with_suffix(target.suffix + ".part")
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink(missing_ok=True)
            have = 0
        attempts = 0
        while have < size and attempts < 4:
            attempts += 1
            headers = {"Range": f"bytes={have}-"} if have else {}
            if have:
                self.stats.resumes += 1
                self.note(f"resuming {entry['name']} at {have}/{size}")
            try:
                with self.http.stream("GET", url, headers=headers) as response:
                    if response.status_code not in (200, 206):
                        detail = response.read().decode("utf-8", "replace")[:160]
                        raise VerifyFailed(f"{entry['name']} came back "
                                           f"{response.status_code}: {detail}")
                    with open(part, "ab" if have else "wb") as fh:
                        for block in response.iter_bytes(CHUNK):
                            fh.write(block)
                            self.stats.downloaded_bytes += len(block)
            except httpx.HTTPError as broken:
                self.note(f"{entry['name']} dropped: {type(broken).__name__}")
            have = part.stat().st_size if part.exists() else 0
        if have != size:
            raise VerifyFailed(f"{entry['name']} stopped at {have} of {size} bytes")
        digest = sha256_file(part)
        if digest != entry["sha256"]:
            part.unlink(missing_ok=True)
            raise VerifyFailed(f"sha256 mismatch on {entry['name']}")
        part.replace(target)
        self.note(f"verified {entry['name']} ({size} bytes)")

    # ---- telemetry -----------------------------------------------------------------

    def post_telemetry(self, slot: str, manifest: dict[str, Any]) -> None:
        now = manifest["server_time"]
        common = {"game": self.game, "region": self.region, "slot": slot,
                  "alloc_key": manifest["alloc_key"], "ts": now}
        events = [
            {**common, "type": "mount", "value": 1},
            {**common, "type": "view", "value": 1},
            {**common, "type": "visit", "value": 1},
            {**common, "type": "dwell", "value": 12.5},
            {**common, "type": "interaction", "value": 3},
        ]
        try:
            self.http.post("telemetry", json=events).raise_for_status()
        except httpx.HTTPError as e:
            self.note(f"telemetry did not post: {e}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8700")
    ap.add_argument("--game", default="A")
    ap.add_argument("--region", default="r1")
    ap.add_argument("--slots", default="", help="comma-separated; default every slot of the game")
    ap.add_argument("--once", action="store_true", help="one poll, then stop")
    ap.add_argument("--seconds", type=float, default=0.0, help="keep polling for this long")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--keep", type=int, default=0, help="packs to keep in the cache (LRU)")
    ap.add_argument("--no-telemetry", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", action="store_true", help="also print a JSON summary")
    args = ap.parse_args(argv)

    client = FakeClient(args.url, args.game, args.region, cache=Path(args.cache),
                        keep=args.keep or None,
                        slots=[s.strip() for s in args.slots.split(",") if s.strip()],
                        telemetry=not args.no_telemetry, verbose=args.verbose,
                        as_json=args.json)
    try:
        stats = client.run_once() if (args.once or not args.seconds) else client.run(args.seconds)
    except httpx.HTTPError as e:
        print(f"CANNOT REACH SERVER {args.url}: {e}", file=sys.stderr)
        return 3
    return 0 if stats.fallbacks == 0 or stats.mounts else 1


if __name__ == "__main__":
    raise SystemExit(main())
