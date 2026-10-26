"""The service layer: everything the routes do, with no HTTP in it.

One `Service` holds the config, the clock, the Repo, the Blobs and the key store, and every
rule is read through them. Routes are a thin shell around this file, which is what lets the
tests drive the whole server with a fake clock and no sockets.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import rules
from .blobs import Blobs, FsBlobs
from .clock import Clock, DemoClock, RealClock, iso, parse_iso
from .config import Config
from .packs import AXIS_WORDS, ParsedPack, fit_failure, fits_slots, peek_dcpack, run_checks
from .repo import Repo, SqliteRepo
from .signing import KeyStore, canonical_json, sha256_hex

log = logging.getLogger("dcserver")

SABOTAGE_MODES = ("corrupt", "freeze", "none")


class ServiceError(Exception):
    """Something the caller did wrong, with a sentence and an HTTP status."""

    def __init__(self, status: int, sentence: str, **extra: Any):
        super().__init__(sentence)
        self.status = status
        self.sentence = sentence
        self.extra = extra


@dataclass
class Paths:
    data_dir: Path
    demo_files: Path

    @property
    def db(self) -> Path:
        return self.data_dir / "db.sqlite"

    @property
    def keys(self) -> Path:
        return self.data_dir / "keys"

    @property
    def packs(self) -> Path:
        return self.data_dir / "packs"


class Service:
    def __init__(self, config: Config, *, clock: Clock | None = None, repo: Repo | None = None,
                 blobs: Blobs | None = None, keys: KeyStore | None = None,
                 data_dir: str | Path | None = None, demo_files: str | Path | None = None,
                 base_url: str = ""):
        here = Path(__file__).resolve().parent.parent          # server/
        self.paths = Paths(
            data_dir=Path(data_dir) if data_dir else here / "data",
            demo_files=Path(demo_files) if demo_files else here / "demo_files",
        )
        self.config = config
        self.clock = clock or RealClock()
        self.keys = keys or KeyStore(self.paths.keys)
        self.keys.ensure()
        self.repo = repo or SqliteRepo(self.paths.db)
        self.blobs = blobs or FsBlobs(self.paths.packs, self.keys.url_signer, base_url=base_url)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ lifecycle

    def startup(self) -> "Service":
        self.repo.init_schema()
        self.repo.seed_games(
            [{"id": g, "label": self.config.game_label(g)} for g in self.config.games],
            [{"id": s.id, "game": s.game, "size_class": s.size_class,
              "slot_index": s.index, "px": s.px} for s in self.config.slots],
        )
        if not self.repo.meta_get("epoch"):
            self.repo.meta_set("epoch", iso(self.now().replace(microsecond=0)))
        if self.repo.meta_get("wallet") is None:
            self._reset_wallet()
        if self.repo.meta_get("reset_generation") is None:
            self.repo.meta_set("reset_generation", 0)
        self.seed_system_packs()
        return self

    def _reset_wallet(self) -> None:
        self.repo.meta_set("wallet", {"available": self.config.wallet_start, "held": 0, "charged": 0})

    # ------------------------------------------------------------------ time

    def now(self) -> datetime:
        return self.clock.now()

    def demo(self) -> DemoClock:
        epoch = parse_iso(self.repo.meta_get("epoch") or iso(self.now()))
        return DemoClock(epoch, self.config.demo_start_for(epoch),
                         self.config.demo_factor, self.config.block_seconds)

    def clock_block(self) -> dict[str, Any]:
        now, demo = self.now(), self.demo()
        k = demo.block_index(now)
        return {
            "server_time": iso(now),
            "demo_time": iso(demo.demo_time(now)),
            "label": self.config.demo_clock_label,
            "demo_seconds_per_real_second": self.config.demo_factor,
            "block_seconds": demo.block_s,
            "block_index": k,
            "block_ends_in_s": round((demo.block_end(k) - now).total_seconds(), 3),
            "demo_hours_elapsed": round(demo.demo_hours_elapsed(now), 4),
            "epoch": iso(demo.epoch),
        }

    # ------------------------------------------------------------------ system packs

    def _system_kind(self, piece: str) -> str:
        return rules.KIND_RIVAL if piece in self.config.rival_pieces() else rules.KIND_DEFAULT

    def seed_system_packs(self) -> list[dict[str, Any]]:
        """Register the rival and default packs from demo_files/ — the developer's own
        content, which the visitor never uploads. Prefers a real pack over a fake one."""
        out: list[dict[str, Any]] = []
        for piece in self.config.system_pieces():
            if self.repo.find_system_content(piece):
                continue
            path = self._find_demo_file(piece)
            if not path:
                log.warning("no .dcpack for system piece %s in %s — the slot will fall back",
                            piece, self.paths.demo_files)
                out.append({"piece": piece, "status": "missing"})
                continue
            try:
                blob = path.read_bytes()
            except OSError as e:
                out.append({"piece": piece, "status": "unreadable", "detail": str(e)})
                continue
            result = self._ingest(blob, kind="system", piece=piece,
                                  source={"kind": "seed", "file": path.name})
            out.append({"piece": piece, "status": result["status"], "file": path.name,
                        "content_id": result.get("content_id")})
            if result["status"] != "approved":
                log.warning("system pack %s was rejected: %s", path.name, result.get("reason"))
        return out

    def _find_demo_file(self, piece: str) -> Path | None:
        if not self.paths.demo_files.is_dir():
            return None
        candidates = sorted(self.paths.demo_files.glob(f"{piece}_*.dcpack"))
        if not candidates:
            return None
        # a real pack wins over a fake one; otherwise the last version alphabetically
        real = [p for p in candidates if ".real." in p.name]
        return (real or candidates)[-1]

    # ------------------------------------------------------------------ uploads

    def _store(self, parsed: ParsedPack, content_id: str, kind: str) -> dict[str, Any]:
        record_hash = sha256_hex(canonical_json(parsed.record))
        pack_id = "pk_" + sha256_hex(f"{content_id}|{record_hash}".encode("utf-8"))[:12]
        for entry in parsed.files:
            self.blobs.put(pack_id, entry["name"], parsed.iter_file(entry["name"]))
        if not self.repo.get_pack(pack_id):
            self.repo.add_pack({
                "id": pack_id, "content_id": content_id, "piece": parsed.piece,
                "version": parsed.version, "kind": kind, "files": parsed.files,
                "total_bytes": parsed.total_bytes, "record": parsed.record,
                "signature": parsed.signature,
            }, self.now())
        return {"id": pack_id, "total_bytes": parsed.total_bytes, "files": parsed.files,
                "signature": parsed.signature}

    def _ingest(self, blob: bytes, *, kind: str, piece: str | None = None,
                content_id: str | None = None, source: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the four checks and, if they pass, store the pack as a new content version."""
        expect_piece = piece
        existing = self.repo.get_content(content_id) if content_id else None
        if content_id and not existing:
            raise ServiceError(404, f"There is no content {content_id}.")
        if existing:
            expect_piece = existing["piece"]

        parsed, checks = run_checks(blob, self.config, self.keys, expect_piece=expect_piece)
        if parsed is None:
            failed = next(r for r in checks if r["ok"] is False)
            return {"content_id": content_id, "version": None, "status": "rejected",
                    "checks": checks, "failed_check": failed["check"], "reason": failed["detail"]}

        now = self.now()
        if existing:
            target_id = existing["id"]
            version_n = max((int(v["version_n"]) for v in self.repo.versions(target_id)), default=0) + 1
        else:
            if kind == "system":
                target_id = f"sys_{parsed.piece}"
                if not self.repo.get_content(target_id):
                    self.repo.add_content(target_id, parsed.piece, "system", parsed.size_class,
                                          source or {}, now)
            else:
                target_id = self.repo.next_visitor_content_id()
                self.repo.add_content(target_id, parsed.piece, "visitor", parsed.size_class,
                                      source or {}, now)
            version_n = max((int(v["version_n"]) for v in self.repo.versions(target_id)), default=0) + 1

        pack = self._store(parsed, target_id, "system" if kind == "system" else "visitor")
        self.repo.add_version(target_id, version_n, {
            "version": parsed.version, "pack_id": pack["id"], "status": "approved",
            "rating": parsed.rating, "engine_version": parsed.engine_version,
            "size_class": parsed.size_class, "bounds": parsed.bounds,
            "class_path": parsed.class_path, "state_schema": parsed.state_schema,
            "state_schema_version": parsed.state_schema_version, "checks": checks,
        }, now)
        return {"content_id": target_id, "piece": parsed.piece, "version": parsed.version,
                "version_n": version_n, "status": "approved", "checks": checks,
                "pack": {"id": pack["id"], "total_bytes": pack["total_bytes"],
                         "files": pack["files"]},
                "size_class": parsed.size_class, "bounds": parsed.bounds,
                "fits": fits_slots(parsed.bounds, self.config)}

    def upload_content(self, blob: bytes, filename: str | None = None) -> dict[str, Any]:
        return self._ingest(blob, kind="visitor",
                            source={"kind": "upload", "file": filename or "upload.dcpack"})

    def upload_version(self, content_id: str, blob: bytes,
                       filename: str | None = None) -> dict[str, Any]:
        content = self.repo.get_content(content_id)
        if not content:
            raise ServiceError(404, f"There is no content {content_id}.")
        if content["kind"] != "visitor":
            raise ServiceError(400, "That content belongs to the game, not to you.")
        return self._ingest(blob, kind="visitor", content_id=content_id,
                            source={"kind": "version", "file": filename or "upload.dcpack"})

    def my_content(self) -> dict[str, Any]:
        out = []
        for content in self.repo.list_content("visitor"):
            versions = self.repo.versions(content["id"])
            latest = self.repo.latest_approved(content["id"])
            bounds = (latest or {}).get("bounds")
            out.append({
                "content_id": content["id"], "piece": content["piece"],
                "size_class": content["size_class"], "created_at": content["created_at"],
                "versions": [{"version": v["version"], "version_n": v["version_n"],
                              "status": v["status"], "pack_id": v["pack_id"],
                              "created_at": v["created_at"]} for v in versions],
                "latest_approved": ({"version": latest["version"], "version_n": latest["version_n"],
                                     "pack_id": latest["pack_id"], "class_path": latest["class_path"]}
                                    if latest else None),
                "bounds": bounds,
                "fits": fits_slots(bounds, self.config) if bounds else {},
            })
        return {"brand": self.repo.get_brand(), "content": out}

    # ------------------------------------------------------------------ demo files

    def demo_files(self) -> list[dict[str, Any]]:
        """"The brand's computer": the packs a visitor can upload. The rival and default
        packs live in the same folder but are the game's own content, so they are not listed."""
        if not self.paths.demo_files.is_dir():
            return []
        system = set(self.config.system_pieces())
        out = []
        for path in sorted(self.paths.demo_files.glob("*.dcpack")):
            meta = peek_dcpack(path) or {}
            piece = meta.get("piece")
            if piece in system:
                continue
            row = {"name": path.name, "bytes": path.stat().st_size,
                   "piece": piece, "version": meta.get("version"),
                   "size_class": meta.get("size_class"),
                   "engine_version": meta.get("engine_version"), "rating": meta.get("rating")}
            note = None
            if meta.get("engine_version") and str(meta["engine_version"]) != self.config.engine_version:
                note = f"built for engine {meta['engine_version']}"
            elif meta.get("rating") and meta["rating"] not in self.config.allowed_ratings:
                note = f"rated {meta['rating']}"
            row["note"] = note
            out.append(row)
        return out

    def demo_file_path(self, name: str) -> Path:
        safe = Path(name).name
        path = self.paths.demo_files / safe
        if not path.is_file() or path.suffix != ".dcpack":
            raise ServiceError(404, f"There is no file called {safe} on the brand's computer.")
        return path

    # ------------------------------------------------------------------ brand / wallet

    def set_brand(self, colour: str, emblem: str) -> dict[str, Any]:
        presets = self.config.data["brand_presets"]
        if colour not in presets["colours"]:
            raise ServiceError(400, f"{colour} is not one of this demo's brand colours.")
        if emblem not in presets["emblems"]:
            raise ServiceError(400, f"{emblem} is not one of this demo's emblems.")
        return self.repo.set_brand(colour, emblem, self.now())

    def wallet(self) -> dict[str, Any]:
        return self.repo.meta_get("wallet") or {"available": self.config.wallet_start,
                                                "held": 0, "charged": 0}

    # ------------------------------------------------------------------ what shows

    def showing(self, game: str, slot: str, region: str) -> rules.Showing | None:
        self._require_slot(game, slot, region)
        return rules.resolve_showing(self.config, self.repo, self.demo(), game, slot, region, self.now())

    def _require_slot(self, game: str, slot: str, region: str) -> None:
        if game not in self.config.games:
            raise ServiceError(404, f"There is no game {game}.")
        if not self.config.has_slot(slot) or self.config.slot(slot).game != game:
            raise ServiceError(404, f"Game {game} has no slot {slot}.")
        if not self.config.has_region(region):
            raise ServiceError(404, f"There is no region {region}.")

    def changes(self, game: str, region: str) -> dict[str, Any]:
        if game not in self.config.games:
            raise ServiceError(404, f"There is no game {game}.")
        if not self.config.has_region(region):
            raise ServiceError(404, f"There is no region {region}.")
        now, demo = self.now(), self.demo()
        slots: dict[str, str] = {}
        for slot in self.config.slots_of(game):
            showing = rules.resolve_showing(self.config, self.repo, demo, game, slot.id, region, now)
            slots[slot.id] = showing.alloc_key if showing else "no-content"
        k = demo.block_index(now)
        return {
            "server_time": iso(now), "demo_time": iso(demo.demo_time(now)),
            "game": game, "region": region, "slots": slots,
            "poll_interval_s": self.config.poll_interval_s,
            "block_ends_in_s": round((demo.block_end(k) - now).total_seconds(), 3),
            "reset_generation": int(self.repo.meta_get("reset_generation") or 0),
            "purge_packs": list(self.repo.meta_get("purge_packs") or []),
        }

    def manifest(self, game: str, slot: str, region: str) -> dict[str, Any]:
        showing = self.showing(game, slot, region)
        if showing is None:
            raise ServiceError(503, "No default pack is registered on this server — run "
                                    "tools/make_fake_packs.py and restart it.")
        now = self.now()
        pack = self.repo.get_pack(showing.pack_id)
        assert pack is not None
        ttl = self.config.url_ttl_s
        files = [{
            "name": f["name"], "size": int(f["size"]), "sha256": f["sha256"],
            "url": self.blobs.signed_url(pack["id"], f["name"], now=now, ttl_s=ttl),
        } for f in pack["files"]]
        payload: dict[str, Any] = {
            "slot": slot, "game": game, "region": region,
            "alloc_key": showing.alloc_key, "is_default": showing.is_default,
            "content": {
                "piece": showing.piece, "version": showing.version,
                "size_class": showing.size_class, "class_path": showing.class_path,
                "state_schema": showing.state_schema,
                "state_schema_version": showing.state_schema_version,
            },
            "pack": {"id": pack["id"], "total_bytes": int(pack["total_bytes"]), "files": files},
            "brand": showing.brand,
            "showing": {"kind": showing.kind, "source": showing.source,
                        "ends_at": iso(showing.ends_at), "reason": showing.reason},
            "valid_until": iso(now + timedelta(seconds=ttl)),
            "server_time": iso(now),
            "signature_alg": "RS256-canonical-json-v1",
        }
        return {**payload, "signature": self.keys.sign(payload)}

    # ------------------------------------------------------------------ allocations

    def allocate(self, game: str, slot: str, region: str, content_id: str,
                 minutes: float | None = None, source: str = "admin") -> dict[str, Any]:
        self._require_slot(game, slot, region)
        content = self.repo.get_content(content_id)
        if not content:
            raise ServiceError(404, f"There is no content {content_id}.")
        version = self.repo.latest_approved(content_id)
        if not version:
            raise ServiceError(400, f"{content_id} has no approved version to show.")
        bounds = version.get("bounds") or {}
        limits = self.config.limits(self.config.slot(slot).size_class)
        bad = fit_failure({a: float(bounds.get(a, 0.0)) for a in ("x", "y", "z")}, limits)
        if bad:
            axis, tail = bad
            raise ServiceError(400, f"{content['piece']} does not fit slot {slot} — too "
                                    f"{AXIS_WORDS[axis]}, {tail}.")
        if content["kind"] == "visitor":
            kind = rules.KIND_VISITOR
        else:
            kind = self._system_kind(content["piece"])
        now = self.now()
        block_minutes = self.config.block_seconds / 60.0
        length = float(minutes) if minutes is not None else block_minutes
        if length <= 0:
            raise ServiceError(400, "An allocation has to last longer than zero minutes.")
        end = now + timedelta(minutes=length)
        alloc_id = self.repo.add_allocation(game, slot, region, kind, content_id, now, end,
                                            source, now)
        showing = self.showing(game, slot, region)
        return {
            "allocation_id": alloc_id, "game": game, "slot": slot, "region": region,
            "kind": kind, "content_id": content_id, "piece": content["piece"],
            "version": version["version"], "start_at": iso(now), "end_at": iso(end),
            "minutes": length,
            "alloc_key": showing.alloc_key if showing else None,
            "showing": self.describe(showing),
        }

    def describe(self, showing: rules.Showing | None) -> dict[str, Any] | None:
        if not showing:
            return None
        return {"kind": showing.kind, "piece": showing.piece, "version": showing.version,
                "brand": showing.brand, "alloc_key": showing.alloc_key,
                "ends_at": iso(showing.ends_at), "source": showing.source,
                "reason": showing.reason, "is_default": showing.is_default,
                "pack_id": showing.pack_id}

    def set_paused(self, paused: bool) -> dict[str, Any]:
        n = self.repo.set_paused_all_visitor(paused)
        return {"paused": bool(paused), "allocations": n}

    def live_status(self) -> list[dict[str, Any]]:
        now, demo = self.now(), self.demo()
        out = []
        for game in self.config.games:
            for slot in self.config.slots_of(game):
                for region in self.config.regions:
                    showing = rules.resolve_showing(self.config, self.repo, demo, game,
                                                    slot.id, region, now)
                    row = {"game": game, "slot": slot.id, "region": region}
                    row.update(self.describe(showing) or {"kind": "none"})
                    out.append(row)
        return out

    # ------------------------------------------------------------------ telemetry

    def telemetry(self, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
        allowed = set(self.config.telemetry_types)
        good, bad = [], []
        for event in events:
            if not isinstance(event, dict) or event.get("type") not in allowed:
                bad.append({"event": event, "reason": f"type must be one of {sorted(allowed)}"})
                continue
            good.append(event)
        n = self.repo.add_telemetry(good, self.now())
        return {"accepted": n, "rejected": bad}

    # ------------------------------------------------------------------ admin

    def reset(self) -> dict[str, Any]:
        result = self.repo.wipe_visitor_side()
        for pack_id in result["purge_packs"]:
            self.blobs.delete_pack(pack_id)
        self._reset_wallet()
        generation = int(self.repo.meta_get("reset_generation") or 0) + 1
        self.repo.meta_set("reset_generation", generation)
        self.repo.meta_set("purge_packs", result["purge_packs"])
        self.repo.meta_set("sabotage", None)
        return {"ok": True, "reset_generation": generation,
                "purge_packs": result["purge_packs"], "wiped": result["wiped"],
                "wallet": self.wallet(), "server_time": iso(self.now())}

    def arm_sabotage(self, mode: str) -> dict[str, Any]:
        if mode not in SABOTAGE_MODES:
            raise ServiceError(400, f"Sabotage mode must be one of {', '.join(SABOTAGE_MODES)}.")
        with self._lock:
            self.repo.meta_set("sabotage", None if mode == "none" else mode)
        return {"armed": None if mode == "none" else mode}

    def consume_sabotage(self) -> str | None:
        """Pop the armed sabotage — it applies to the next file response and then it is gone."""
        with self._lock:
            mode = self.repo.meta_get("sabotage")
            if mode:
                self.repo.meta_set("sabotage", None)
            return mode

    def health(self) -> dict[str, Any]:
        seeded = {}
        for piece in self.config.system_pieces():
            content = self.repo.find_system_content(piece)
            version = self.repo.latest_approved(content["id"]) if content else None
            seeded[piece] = {"content_id": content["id"] if content else None,
                             "version": version["version"] if version else None,
                             "pack_id": version["pack_id"] if version else None}
        return {
            "ok": True, "mode": self.config.mode, "clock": self.clock_block(),
            "counts": self.repo.counts(), "wallet": self.wallet(),
            "brand": self.repo.get_brand(),
            "reset_generation": int(self.repo.meta_get("reset_generation") or 0),
            "sabotage_armed": self.repo.meta_get("sabotage"),
            "key_fingerprint": self.keys.fingerprint(),
            "system_packs": seeded,
            "demo_files": len(self.demo_files()),
            "paths": {"config": str(self.config.path), "data": str(self.paths.data_dir),
                      "demo_files": str(self.paths.demo_files)},
        }

    # ------------------------------------------------------------------ client config

    def client_config(self) -> dict[str, Any]:
        return {
            "poll_interval_s": self.config.poll_interval_s,
            "prefetch_radius_m": float(self.config.data["client"]["prefetch_radius_m"]),
            "public_key_pem": self.keys.public_pem,
            "signature_alg": "RS256-canonical-json-v1",
            "clock": self.clock_block(),
            "telemetry": {k: v for k, v in self.config.data["telemetry"].items()},
            "regions": self.config.regions,
            "games": {g: [s.id for s in self.config.slots_of(g)] for g in self.config.games},
            "pacing_seconds": self.config.pacing_seconds,
            "cache_packs": int(self.config.data.get("client_cache_packs", 8)),
            "reset_generation": int(self.repo.meta_get("reset_generation") or 0),
            "purge_packs": list(self.repo.meta_get("purge_packs") or []),
            "mode": self.config.mode,
        }

    def public_config(self) -> dict[str, Any]:
        d = self.config.data
        return {
            "regions": {r: {"label": d["regions"][r]["label"],
                            "neutral_label": d["regions"][r].get("neutral_label")}
                        for r in self.config.regions},
            "booth": d.get("booth", {}),
            "size_classes": d["size_classes"],
            "brand_presets": d["brand_presets"],
            "wallet": d["wallet"],
            "auction": d["auction"],
            "footfall": d["footfall"],
            "games": {g: {"label": self.config.game_label(g),
                          "slots": [{"id": s.id, "size_class": s.size_class,
                                     "px": {"x": s.px[0], "y": s.px[1]}}
                                    for s in self.config.slots_of(g)]}
                      for g in self.config.games},
            "clock": self.clock_block(),
            "idle_reset_s": d["idle_reset_s"],
        }
