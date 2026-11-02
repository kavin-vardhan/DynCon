"""The service layer: everything the routes do, with no HTTP in it.

One `Service` holds the config, the clock, the Repo, the Blobs and the key store, and every
rule is read through them. Routes are a thin shell around this file, which is what lets the
tests drive the whole server with a fake clock and no sockets.
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import auction, rules
from .blobs import Blobs, FsBlobs
from .clock import Clock, DemoClock, RealClock, iso, parse_iso
from .config import Config
from .packs import AXIS_WORDS, ParsedPack, fit_failure, fits_slots, peek_dcpack, run_checks
from .registry import Registry, RegistryError
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
    # Where the slot-map tool's captures live. In `config/`, not in `data/`, on purpose: a
    # game registration belongs to the developer, so a reset between visitors must not touch
    # it and a clean checkout has to serve the real pictures. See `registry.py`.
    maps_dir: Path

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
                 maps_dir: str | Path | None = None, base_url: str = ""):
        here = Path(__file__).resolve().parent.parent          # server/
        config_dir = config.path.parent if config.path else here / "config"
        self.paths = Paths(
            data_dir=Path(data_dir) if data_dir else here / "data",
            demo_files=Path(demo_files) if demo_files else here / "demo_files",
            maps_dir=Path(maps_dir) if maps_dir else config_dir / "maps",
        )
        self.config = config
        self.clock = clock or RealClock()
        self.keys = keys or KeyStore(self.paths.keys)
        self.keys.ensure()
        self.repo = repo or SqliteRepo(self.paths.db)
        self.blobs = blobs or FsBlobs(self.paths.packs, self.keys.url_signer, base_url=base_url)
        self.registry = Registry(self.paths.maps_dir)
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
        if self.repo.meta_get("reset_generation") is None:
            self.repo.meta_set("reset_generation", 0)
        if self.repo.meta_get("preview_region") is None:
            self.repo.meta_set("preview_region", self.config.preview_region)
        self.seed_system_packs()
        return self

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

    def _demo_file_row(self, path: Path) -> dict[str, Any]:
        meta = peek_dcpack(path) or {}
        note = None
        if meta.get("engine_version") and str(meta["engine_version"]) != self.config.engine_version:
            note = f"built for engine {meta['engine_version']}"
        elif meta.get("rating") and meta["rating"] not in self.config.allowed_ratings:
            note = f"rated {meta['rating']}"
        return {"name": path.name, "bytes": path.stat().st_size,
                "piece": meta.get("piece"), "version": meta.get("version"),
                "size_class": meta.get("size_class"),
                "engine_version": meta.get("engine_version"), "rating": meta.get("rating"),
                "real": ".real." in path.name or (meta.get("source") or {}).get("kind") == "real",
                "note": note}

    def _pick_demo_file(self, piece: str, version: str) -> Path | None:
        """A real pack wins over a fake one for the same piece-version."""
        folder = self.paths.demo_files
        for name in (f"{piece}_{version}.real.dcpack", f"{piece}_{version}.dcpack"):
            if (folder / name).is_file():
                return folder / name
        return None

    def demo_files(self, purpose: str = "upload") -> list[dict[str, Any]]:
        """"The brand's computer" — a curated list, not whatever is in the folder.

        `upload` (the default): version 1 of each uploadable piece, plus the one
        built-to-fail file the demo shows a rejection with (engine 5.3). `update`: the
        version-2 files, which is all the push-an-update screen offers. The rival and
        default packs live in the same folder but are the game's own content, and the
        rated-18+ file stays on disk for the tests — neither is ever listed.
        """
        if not self.paths.demo_files.is_dir():
            return []
        version = "v2" if purpose == "update" else "v1"
        out = []
        for piece in self.uploadable_pieces():
            path = self._pick_demo_file(piece, version)
            if path:
                out.append(self._demo_file_row(path))
        if purpose != "update":
            bad = self.paths.demo_files / self.config.data["demo_files"]["built_to_fail"]
            if bad.is_file():
                out.append(self._demo_file_row(bad))
        return out

    def uploadable_pieces(self) -> list[str]:
        """Every piece that is not the game's own content, in config order."""
        system = set(self.config.system_pieces())
        pieces = []
        for path in sorted(self.paths.demo_files.glob("*.dcpack")):
            meta = peek_dcpack(path) or {}
            piece = meta.get("piece")
            if piece and piece not in system and piece not in pieces:
                pieces.append(piece)
        return pieces

    def demo_file_path(self, name: str) -> Path:
        safe = Path(name).name
        path = self.paths.demo_files / safe
        if not path.is_file() or path.suffix != ".dcpack":
            raise ServiceError(404, f"There is no file called {safe} on the brand's computer.")
        return path

    # ------------------------------------------------------------------ brand / wallet

    # ------------------------------------------------------------------ the auction

    def auctions(self) -> auction.AuctionCtx:
        return auction.AuctionCtx(self.config, self.repo, self.demo(), self.now())

    def tick(self) -> auction.AuctionCtx:
        """Catch the auctions up before answering. This is the whole of "no timers":
        every rival counter-bid and every close is applied by the first request after it
        fell due, which is also why the tests can simply move the clock."""
        ctx = self.auctions()
        auction.advance_all(ctx)
        return ctx

    def lot_cards(self, game: str, slot: str) -> dict[str, Any]:
        ctx = self.tick()
        return {region: auction.lot_card(ctx, lot)
                for region, lot in auction.lots_for_slot(ctx, game, slot).items()}

    def lots(self, game: str | None = None, slot: str | None = None,
             region: str | None = None) -> dict[str, Any]:
        ctx = self.tick()
        if slot:
            if not self.config.has_slot(slot):
                raise ServiceError(404, f"There is no slot {slot}.")
            game = game or self.config.slot(slot).game
            auction.lots_for_slot(ctx, game, slot)            # make sure they exist
        rows = [auction.lot_card(ctx, lot) for lot in self.repo.list_lots(game, slot, region)]
        return {"lots": rows, "wallet": auction.wallet(ctx),
                "server_time": iso(ctx.now)}

    def lot(self, lot_id: str) -> dict[str, Any]:
        ctx = self.tick()
        lot = self.repo.get_lot(lot_id)
        if not lot:
            raise ServiceError(404, f"There is no lot {lot_id}.")
        card = auction.lot_card(ctx, auction.advance_lot(ctx, lot), history=True)
        card["wallet"] = auction.wallet(ctx)
        return card

    def place_bids(self, slot: str, content_id: str,
                   bids: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.config.has_slot(slot):
            raise ServiceError(404, f"There is no slot {slot}.")
        if not bids:
            raise ServiceError(400, "A bid needs at least one region.")
        ctx = self.tick()
        return auction.place_bids(ctx, slot, content_id, bids)

    def split_bid(self, slot: str, total: int, regions: list[str]) -> dict[str, Any]:
        """The portal's "one total across ticked regions", split by footfall."""
        if not self.config.has_slot(slot):
            raise ServiceError(404, f"There is no slot {slot}.")
        unknown = [r for r in regions if not self.config.has_region(r)]
        if unknown:
            raise ServiceError(404, f"There is no region {unknown[0]}.")
        if not regions:
            raise ServiceError(400, "Tick at least one region to split a total across.")
        ctx = self.tick()
        shares = auction.split_by_footfall(self.config, slot, int(total), regions)
        out = []
        for region in regions:
            lot = auction.current_lot(ctx, self.config.slot(slot).game, slot, region)
            out.append({"region": region, "label": self.config.region_label(region),
                        "amount": shares[region],
                        "footfall": self.config.footfall(slot, region),
                        "next_bid": auction.next_bid(lot, int(ctx.auction["min_raise"])),
                        "enough": shares[region] >= auction.next_bid(
                            lot, int(ctx.auction["min_raise"]))})
        return {"slot": slot, "total": int(total), "bids": out,
                "allocated": sum(shares.values())}

    def close_auction(self, which: str) -> dict[str, Any]:
        ctx = self.tick()
        closed = auction.force_close(ctx, which)
        if not closed and which != "all":
            raise ServiceError(404, f"There is no lot {which}.")
        return {"closed": closed, "wallet": auction.wallet(self.auctions())}

    # ------------------------------------------------------------------ games

    def players_online(self, game: str) -> int:
        """Simulated, and deliberately not random: it is a function of the demo clock, so
        two screens polling at the same moment agree."""
        base = int(self.config.game(game).get("players_online") or 0)
        minutes = self.demo().demo_hours_elapsed(self.now()) * 60.0
        wobble = math.sin(minutes / 17.0) * 0.06 + math.sin(minutes / 3.3) * 0.02
        return max(0, int(round(base * (1.0 + wobble))))

    def footfall_card(self, slot: str) -> dict[str, Any]:
        """Seed × demo hours elapsed + the views really counted — "simulated + live"."""
        demo = self.demo()
        hours = max(demo.demo_hours_elapsed(self.now()), 0.0)
        live = self.repo.telemetry_counts_by_slot(slot, "view")
        out = {}
        for region in self.config.regions:
            seed = self.config.footfall(slot, region)
            simulated = int(seed * hours)
            counted = int(live.get(region, 0))
            out[region] = {"per_demo_hour": seed, "simulated": simulated, "live": counted,
                           "total": simulated + counted, "label": "simulated + live"}
        return out

    def games(self) -> dict[str, Any]:
        rows = []
        booth = self.booth_game()
        for game in self.config.games:
            record = self.registry.record(game)
            rows.append({
                "id": game, "label": self.config.game_label(game),
                "slot_count": len(self.config.slots_of(game)),
                "players_online": self.players_online(game),
                "live_at_booth": game == booth,
                "map_image_url": f"/games/{game}/map",
                "registered": record is not None,
                "registered_utc": (record or {}).get("registered_utc"),
            })
        return {"games": rows, "clock": self.clock_block()}

    def slot_px(self, game: str, slot: str) -> dict[str, float]:
        """Where the portal puts this slot's pin.

        The registered position wins over the one in `demo.json`: the config's `px` values
        are hand-guessed stand-ins for a map nobody had captured yet, and the registered one
        was measured off the capture the pin is drawn on.
        """
        entry = self.registry.slot(game, slot)
        if entry and isinstance(entry.get("px"), dict):
            return {"x": float(entry["px"]["x"]), "y": float(entry["px"]["y"])}
        definition = self.config.slot(slot)
        return {"x": definition.px[0], "y": definition.px[1]}

    def game_card(self, game: str) -> dict[str, Any]:
        if game not in self.config.games:
            raise ServiceError(404, f"There is no game {game}.")
        ctx = self.tick()
        mine = self.my_content()["content"]
        slots = []
        registered = self.registry.record(game)
        for slot in self.config.slots_of(game):
            limits = self.config.limits(slot.size_class)
            lots = {region: auction.lot_card(ctx, lot) for region, lot
                    in auction.lots_for_slot(ctx, game, slot.id).items()}
            entry = (registered or {}).get("slots", {}).get(slot.id) or {}
            slots.append({
                "id": slot.id, "size_class": slot.size_class, "limits": limits,
                "limits_words": (f"up to {limits['x']:.0f} x {limits['y']:.0f} m on the ground "
                                 f"and {limits['z']:.0f} m tall"),
                "px": self.slot_px(game, slot.id),
                "thumb_url": f"/games/{game}/slots/{slot.id}/thumb",
                # What the developer declared in the map, when it has been registered.
                "registered": bool(entry),
                "rating_rule": entry.get("rating_rule"),
                "prefetch_radius_m": entry.get("prefetch_radius_m"),
                "footfall": self.footfall_card(slot.id),
                "fits": {c["content_id"]: c["fits"].get(slot.id) for c in mine if c["fits"]},
                "lots": lots,
                "showing": {region: self.describe(self.showing(game, slot.id, region))
                            for region in self.config.regions},
            })
        return {
            "id": game, "label": self.config.game_label(game),
            "live_at_booth": game == self.booth_game(),
            "players_online": self.players_online(game),
            "map_image_url": f"/games/{game}/map",
            "registered": registered is not None,
            "registered_utc": (registered or {}).get("registered_utc"),
            "slots": slots, "regions": {r: self.config.region_label(r)
                                        for r in self.config.regions},
            "wallet": auction.wallet(ctx), "clock": self.clock_block(),
        }

    # ------------------------------------------------------------------ the slot map

    def map_file(self, game: str) -> Path | None:
        """The map image the UE slot-map tool captured, or None if it never ran.

        The registration is the only source. `demo.json` used to name a `map_image` as a
        place to drop a picture by hand; that is gone, because a map image with no slot
        positions measured on it is a picture the portal cannot put a pin on.
        """
        if game not in self.config.games:
            raise ServiceError(404, f"There is no game {game}.")
        return self.registry.map_image(game)

    def thumb_file(self, game: str, slot: str) -> Path | None:
        """The eye-level thumbnail of one slot, or None when it was never registered."""
        if not self.config.has_slot(slot) or self.config.slot(slot).game != game:
            raise ServiceError(404, f"Game {game} has no slot {slot}.")
        return self.registry.thumb(game, slot)

    def register_game(self, payload: dict[str, Any], map_blob: bytes,
                      thumbs: dict[str, bytes]) -> dict[str, Any]:
        """`POST /games/register` — the developer's slot-map tool, arriving.

        The platform's own slot table stays the authority on which slots exist, what class
        they are and what they cost; what the registration brings is everything only the map
        knows: the picture, the pin positions measured on it, a thumbnail per slot, and the
        developer's own rule for each slot.
        """
        game = str(payload.get("game") or "").strip()
        if game and game not in self.config.games:
            raise ServiceError(404, f"There is no game {game} on this platform.")
        known = {s.id: s.size_class for s in self.config.slots_of(game)} if game else {}
        try:
            with self._lock:
                result = self.registry.register(
                    payload, map_blob, thumbs, known_slots=known, now_iso=iso(self.now()))
        except RegistryError as bad:
            raise ServiceError(400, bad.sentence)
        log.info("registered game %s: %d slot(s), map %s", result["game"],
                 len(result["slots"]), result["image"]["file"])
        return result

    # ------------------------------------------------------------------ the report

    def report(self) -> dict[str, Any]:
        """Per region: what the campaign bought, what it cost, and what it got.

        **Views are simulated + live**, and the two halves are reported separately so the
        portal can say so out loud. The simulated half uses the same footfall model as the
        slot card — footfall per demo hour × the 3 demo hours in a block — counted for each
        block that has *started* (a block booked for later has not been seen by anyone yet).
        So the moment a block is won, `cost_per_1000_views` here equals the
        `credits_per_1000_views` the slot card quoted at that price, and real counted views
        can only make it better.

        Visits, dwell and interactions are live only: they are real events, and there is no
        simulated model for them to be mixed with.
        """
        ctx = self.tick()
        now = ctx.now
        block_hours = float(self.config.data["block_demo_hours"])
        allocations = self.repo.visitor_allocations()
        by_region: dict[str, list[dict[str, Any]]] = {r: [] for r in self.config.regions}
        for row in allocations:
            by_region.setdefault(row["region"], []).append(row)
        regions = []
        totals = {"views": 0, "views_simulated": 0, "views_live": 0, "visits": 0,
                  "dwell_s": 0.0, "interactions": 0, "charged": 0, "blocks": 0}
        for region in self.config.regions:
            rows = by_region.get(region, [])
            counts = self.repo.telemetry_for_allocations(rows) if rows else {}
            charged = self.repo.sum_lots_charged(region)
            active = [r for r in rows
                      if parse_iso(r["start_at"]) <= now < parse_iso(r["end_at"])]
            started = [r for r in rows if parse_iso(r["start_at"]) <= now]
            queued = [r for r in rows if parse_iso(r["start_at"]) > now]
            views_simulated = int(sum(self.config.footfall(r["slot"], region) * block_hours
                                      for r in started))
            views_live = int(counts.get("view", 0))
            views = views_simulated + views_live
            time_left = (round((parse_iso(active[0]["end_at"]) - now).total_seconds(), 1)
                         if active else 0.0)
            slots = sorted({r["slot"] for r in rows})
            per_view = round(charged / views, 4) if views else None
            regions.append({
                "region": region, "label": self.config.region_label(region),
                "neutral_label": self.config.data["regions"][region].get("neutral_label"),
                "slots": slots, "blocks": len(rows), "blocks_started": len(started),
                "views": views, "views_simulated": views_simulated, "views_live": views_live,
                "views_label": "simulated + live",
                "visits": int(counts.get("visit", 0)),
                "dwell_s": round(float(counts.get("dwell_total", 0.0)), 1),
                "interactions": int(counts.get("interaction_total", 0)),
                "mounts": int(counts.get("mount", 0)),
                "charged": charged, "cost_per_view": per_view,
                "cost_per_1000_views": round(charged / (views / 1000.0), 2) if views else None,
                "time_left_s": time_left,
                "paused": bool(active and int(active[0]["paused"] or 0)),
                "next_block_at": queued[0]["start_at"] if queued else None,
                "showing": self.describe(self.showing(
                    self.config.slot(slots[0]).game, slots[0], region)) if slots else None,
            })
            totals["views"] += views
            totals["views_simulated"] += views_simulated
            totals["views_live"] += views_live
            totals["visits"] += int(counts.get("visit", 0))
            totals["dwell_s"] += float(counts.get("dwell_total", 0.0))
            totals["interactions"] += int(counts.get("interaction_total", 0))
            totals["charged"] += charged
            totals["blocks"] += len(rows)
        totals["dwell_s"] = round(totals["dwell_s"], 1)
        totals["cost_per_view"] = (round(totals["charged"] / totals["views"], 4)
                                   if totals["views"] else None)
        totals["cost_per_1000_views"] = (round(totals["charged"] / (totals["views"] / 1000.0), 2)
                                         if totals["views"] else None)
        return {"brand": self.repo.get_brand(), "wallet": auction.wallet(ctx),
                "regions": regions, "totals": totals, "clock": self.clock_block(),
                "views_model": ("simulated footfall for every block that has started, "
                                "plus the views the game really counted"),
                "paused": any(r["paused"] for r in regions)}

    # ------------------------------------------------------------------ preview region

    def preview_region(self) -> dict[str, Any]:
        """Everything the second copy of the game needs to know about itself.

        Two answers in one, because the preview window asks one question: *what am I?* It is
        a player in some region (which the portal's region check flips), looking at some
        slot (the one the visitor has just been bidding on). The `label` is here because the
        window draws its own corner caption on the HUD canvas and cannot read the portal's
        string table. There used to be a `label_jp` next to it for the Japanese half of that
        caption; the demo is English only since 2026-11-02 (Kavin's ruling).
        """
        region = self.repo.meta_get("preview_region") or self.config.preview_region
        return {"region": region, "label": self.config.region_label(region),
                "neutral_label": self.config.data["regions"][region].get("neutral_label"),
                "main_region": self.config.main_region,
                "focus": self.preview_focus()}

    def preview_focus(self) -> dict[str, Any]:
        """Which slot the preview window should be looking at, and why.

        Three rules, in order, so there is always an answer and the best one wins:

        1. the lot the **visitor bid on** last — that is "the slot just auctioned", and it
           is right from the moment they place a bid, before the auction has even closed;
        2. failing that, their newest **allocation** — which is what a rehearsal driven by
           `POST /admin/allocate` has instead of a bid;
        3. failing that, the **busiest slot of the game being played at the booth**, so the
           window has something to frame during the attract loop.
        """
        lot = self.repo.last_visitor_bid_lot()
        if lot:
            return {"game": lot["game"], "slot": lot["slot"],
                    "reason": "the slot the visitor last bid on"}
        row = self.repo.last_visitor_allocation()
        if row:
            return {"game": row["game"], "slot": row["slot"],
                    "reason": "the visitor's newest allocation"}
        booth = self.booth_game()
        slots = sorted(self.config.slots_of(booth),
                       key=lambda s: -self.config.footfall(s.id, self.config.main_region))
        return {"game": booth, "slot": slots[0].id if slots else None,
                "reason": "nobody has bid yet, so the busiest slot of the game at the booth"}

    def set_preview_region(self, region: str) -> dict[str, Any]:
        if not self.config.has_region(region):
            raise ServiceError(404, f"There is no region {region}.")
        self.repo.meta_set("preview_region", region)
        return self.preview_region()

    # ------------------------------------------------------------------ the live flip

    def live_flip(self) -> dict[str, Any] | None:
        """The fallback for tour step 7 when there is no preview window (plan v6 §11).

        Instead of a second copy of the game playing as another region, the **main** game
        plays as that region for a few seconds: the slot swaps in front of the Player, and
        swaps back. It is the same promise shown a different way, and it costs the booth
        nothing but the twenty seconds.

        It is a timestamp, like everything else here: the flip is simply an entry with an
        `ends_at`, and the first request after that moment sees no flip.
        """
        flip = self.repo.meta_get("live_flip")
        if not isinstance(flip, dict) or not flip.get("region"):
            return None
        now = self.now()
        ends = parse_iso(flip["ends_at"])
        if ends <= now:
            return None
        region = flip["region"]
        return {"region": region, "label": self.config.region_label(region),
                "ends_at": flip["ends_at"],
                "seconds_left": round((ends - now).total_seconds(), 1),
                "back_to": flip.get("back_to") or self.config.main_region}

    def set_live_flip(self, region: str, seconds: float) -> dict[str, Any]:
        if not self.config.has_region(region):
            raise ServiceError(404, f"There is no region {region}.")
        if seconds <= 0:
            self.repo.meta_set("live_flip", None)
            return {"flip": None, "server_time": iso(self.now())}
        now = self.now()
        self.repo.meta_set("live_flip", {
            "region": region, "back_to": self.config.main_region,
            "started_at": iso(now), "ends_at": iso(now + timedelta(seconds=seconds))})
        log.info("live flip: the main game plays as %s for %.0f s", region, seconds)
        return {"flip": self.live_flip(), "server_time": iso(now)}

    def set_brand(self, colour: str, emblem: str) -> dict[str, Any]:
        presets = self.config.data["brand_presets"]
        if colour not in presets["colours"]:
            raise ServiceError(400, f"{colour} is not one of this demo's brand colours.")
        if emblem not in presets["emblems"]:
            raise ServiceError(400, f"{emblem} is not one of this demo's emblems.")
        return self.repo.set_brand(colour, emblem, self.now())

    def wallet(self) -> dict[str, Any]:
        """Derived from the lots, so it cannot drift: held = what you lead, charged = won."""
        return auction.wallet(self.tick())

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

    def changes(self, game: str, region: str, preview: bool = False) -> dict[str, Any]:
        if game not in self.config.games:
            raise ServiceError(404, f"There is no game {game}.")
        if not self.config.has_region(region):
            raise ServiceError(404, f"There is no region {region}.")
        self.note_booth_game(game, preview)
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
            # Who asked for the last reset. The staff combo on pad 2 means "clear the booth
            # down and start again", and the game drops to the attract loop; the portal's
            # own 60-second idle timer means "the brand seat has gone quiet", and it must
            # **not** kick a Player who is still playing at the other seat - the two seats
            # can be two different visitors (plan v6 §2).
            "reset_reason": self.repo.meta_get("reset_reason") or "staff",
            "purge_packs": list(self.repo.meta_get("purge_packs") or []),
            # The live flip rides on the poll every copy of the game already makes, rather
            # than on a second endpoint: it is a thing the game has to act on within a
            # second, and this is the request that happens within a second.
            "live_flip": self.live_flip(),
        }

    def note_booth_game(self, game: str, preview: bool) -> None:
        """Which game the booth's own screen is playing, from the poll it already makes.

        The main copy of the game polls `/changes` every 1.5 s and says which game it is in,
        so the platform knows without being told twice: switching game in the pause menu
        moves the portal's "playing at this booth" badge within one poll. The **preview**
        copy says `preview=1` and is ignored - it is a picture of somewhere else, and at the
        booth it is usually playing the same map as a different region.
        """
        if preview:
            return
        if self.repo.meta_get("booth_game") != game:
            self.repo.meta_set("booth_game", game)
            log.info("the booth is playing game %s", game)

    def booth_game(self) -> str:
        """What the badge follows: the game that last polled, else the config's own pick."""
        played = self.repo.meta_get("booth_game")
        if played in self.config.games:
            return str(played)
        for game in self.config.games:
            if self.config.game(game).get("live_at_booth"):
                return game
        return self.config.games[0]

    def resolve(self, game: str, slot: str, region: str) -> dict[str, Any]:
        """The signed manifest, as the **signed-payload envelope**.

        `{signed_payload: "<the canonical JSON as a string>", signature: "<RS256 over
        exactly those UTF-8 bytes>"}` — verify the string, then parse it, so no client ever
        has to reproduce canonical JSON to check a signature.

        One shape, since brief 013. The `?format=flat` alternative existed so that a client
        and a server could be one brief apart; the UE client has verified the envelope since
        brief 011, and leaving a second signing shape in is leaving a second way to get it
        wrong.
        """
        payload = self.manifest(game, slot, region)
        signature = self.keys.sign(payload)
        return {"signed_payload": canonical_json(payload).decode("utf-8"),
                "signature": signature,
                "signature_alg": payload["signature_alg"]}

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
            # `block` and `lot` are what the game's X-ray view prints under "lot / block":
            # the thing being auctioned is one slot x one region x one time block, and a
            # client that can say which one it is holding is a client that is doing more
            # than downloading a file. `lot` is empty for a block nobody bid on - the
            # attract rotation and the rival's "next block" are not sold.
            "showing": {"kind": showing.kind, "source": showing.source,
                        "ends_at": iso(showing.ends_at), "reason": showing.reason,
                        "block": self.demo().block_index(now),
                        "lot": self._lot_behind(game, slot, region, now)},
            "valid_until": iso(now + timedelta(seconds=ttl)),
            "server_time": iso(now),
            "signature_alg": "RS256-canonical-json-v1",
        }
        return payload

    def _lot_behind(self, game: str, slot: str, region: str,
                    now: datetime) -> str | None:
        """The lot an allocation was won in, if it was won rather than written by hand.

        `allocations.source` is `auction:<lot id>` when the auction engine wrote it and
        `admin` when `/admin/allocate` did, so the lot is already recorded - this only
        reads it back out.
        """
        active = self.repo.active_allocation(game, slot, region, now)
        source = str((active or {}).get("source") or "")
        return source.split(":", 1)[1] if source.startswith("auction:") else None

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

    def end_block(self, game: str, slot: str, region: str) -> dict[str, Any]:
        """Booth staff / a rehearsal: end the block that is live in this slot **now**.

        The same thing `POST /admin/close-auction` is for the auction clock — a way to make a
        timestamp-driven rule fire on demand instead of waiting three real minutes for it. The
        allocation's `end_at` is pulled back to now and nothing else is touched, so what
        happens next is the ordinary rule: `rules.resolve_showing` falls through to step 3 and
        the region's rival — the next winner — takes the block.

        It is also how the state exit test makes "the block ends while the Player is inside"
        happen at a known moment (plan v6 §14 step 6).
        """
        self._require_slot(game, slot, region)
        now = self.now()
        active = self.repo.active_allocation(game, slot, region, now)
        if not active:
            raise ServiceError(404, f"Nothing is allocated to slot {slot} in that region "
                                    f"right now, so there is no block to end.")
        before = self.describe(self.showing(game, slot, region))
        self.repo.end_allocation(int(active["id"]), now)
        after = self.describe(self.showing(game, slot, region))
        log.info("ended block %s on %s/%s/%s: %s -> %s", active["id"], game, slot, region,
                 (before or {}).get("piece"), (after or {}).get("piece"))
        return {"ok": True, "game": game, "slot": slot, "region": region,
                "allocation_id": int(active["id"]), "kind": active["kind"],
                "ended_at": iso(now), "was": before, "now": after,
                "server_time": iso(now)}

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

    def reset(self, reason: str = "staff") -> dict[str, Any]:
        """Clear the visitor's side of the booth down.

        `reason` is the one thing the game needs that the portal cannot tell it directly:

        * `staff` - the three-button combo on pad 2. The booth is being cleared between
          visitors, so the game drops back to the attract loop as well.
        * `idle` - the portal's own sixty-second timer on the **brand** seat. The two seats
          can be two different visitors (plan v6 §2), so this one wipes the brand, the
          bids and the allocations but **must not take the Player out of the game they are
          still standing in**.

        Everything else about the two is identical, which is why it is one endpoint with a
        reason rather than two endpoints that would drift apart.
        """
        reason = reason if reason in ("staff", "idle") else "staff"
        result = self.repo.wipe_visitor_side()
        for pack_id in result["purge_packs"]:
            self.blobs.delete_pack(pack_id)
        self.repo.meta_set("preview_region", self.config.preview_region)
        self.repo.meta_set("live_flip", None)
        generation = int(self.repo.meta_get("reset_generation") or 0) + 1
        self.repo.meta_set("reset_generation", generation)
        self.repo.meta_set("reset_reason", reason)
        self.repo.meta_set("purge_packs", result["purge_packs"])
        self.repo.meta_set("sabotage", None)
        log.info("reset #%d (%s): %s", generation, reason, result["wiped"])
        return {"ok": True, "reset_generation": generation, "reason": reason,
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
            "registered_games": {g: self.registry.is_registered(g) for g in self.config.games},
            "paths": {"config": str(self.config.path), "data": str(self.paths.data_dir),
                      "demo_files": str(self.paths.demo_files),
                      "maps": str(self.paths.maps_dir)},
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
                          "registered": self.registry.is_registered(g),
                          "slots": [{"id": s.id, "size_class": s.size_class,
                                     "px": self.slot_px(g, s.id)}
                                    for s in self.config.slots_of(g)]}
                      for g in self.config.games},
            "clock": self.clock_block(),
            "idle_reset_s": d["idle_reset_s"],
        }
