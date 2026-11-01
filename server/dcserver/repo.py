"""Where the data lives.

`Repo` is the whole of what the rest of the server knows about the database. The local
implementation is SQLite (data/db.sqlite); a DynamoDB one later answers the same questions.
Nothing in here evaluates a rule — rules live in rules.py and read through this interface.

Every timestamp is stored with clock.iso(): fixed-width UTC, so string order is time order
and a range query is just a string comparison.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .clock import iso, parse_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
  id    TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  ord   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS slots (
  id         TEXT PRIMARY KEY,
  game       TEXT NOT NULL,
  size_class TEXT NOT NULL,
  slot_index INTEGER NOT NULL,
  px_x       REAL,
  px_y       REAL
);
CREATE TABLE IF NOT EXISTS brand (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  colour     TEXT NOT NULL,
  emblem     TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content (
  id         TEXT PRIMARY KEY,
  piece      TEXT NOT NULL,
  kind       TEXT NOT NULL,          -- visitor | system
  size_class TEXT,
  source     TEXT,                   -- json: where these bytes came from
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content_versions (
  content_id           TEXT NOT NULL,
  version_n            INTEGER NOT NULL,
  version              TEXT NOT NULL,   -- the piece's own label: "v1" / "v2"
  pack_id              TEXT,
  status               TEXT NOT NULL,   -- approved | rejected
  rating               TEXT,
  engine_version       TEXT,
  size_class           TEXT,
  bounds               TEXT,            -- json {x,y,z} in metres
  class_path           TEXT,
  state_schema         TEXT,            -- json list
  state_schema_version INTEGER,
  checks               TEXT,            -- json list of the four checks
  created_at           TEXT NOT NULL,
  PRIMARY KEY (content_id, version_n)
);
CREATE TABLE IF NOT EXISTS packs (
  id          TEXT PRIMARY KEY,
  content_id  TEXT NOT NULL,
  piece       TEXT NOT NULL,
  version     TEXT NOT NULL,
  kind        TEXT NOT NULL,        -- visitor | system
  files       TEXT NOT NULL,        -- json [{name, size, sha256}]
  total_bytes INTEGER NOT NULL,
  record      TEXT NOT NULL,        -- json: exactly what was signed
  signature   TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS allocations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  game       TEXT NOT NULL,
  slot       TEXT NOT NULL,
  region     TEXT NOT NULL,
  kind       TEXT NOT NULL,         -- visitor | rival | default
  content_id TEXT NOT NULL,
  start_at   TEXT NOT NULL,
  end_at     TEXT NOT NULL,
  paused     INTEGER NOT NULL DEFAULT 0,
  source     TEXT,                  -- how it was written: admin | auction:<lot>
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS allocations_lookup
  ON allocations (game, slot, region, start_at, end_at);
CREATE TABLE IF NOT EXISTS telemetry (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  game        TEXT,
  region      TEXT,
  slot        TEXT,
  alloc_key   TEXT,
  type        TEXT NOT NULL,
  value       REAL,
  ts          TEXT,
  received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lots (
  id             TEXT PRIMARY KEY,      -- lot_A1_r1_1
  game           TEXT NOT NULL,
  slot           TEXT NOT NULL,
  region         TEXT NOT NULL,
  seq            INTEGER NOT NULL,
  opening        INTEGER NOT NULL,
  rival_max      INTEGER NOT NULL,
  state          TEXT NOT NULL,         -- open | running | closed
  highest        INTEGER NOT NULL,
  holder         TEXT NOT NULL,         -- you | rival
  content_id     TEXT,                  -- what the visitor is bidding with
  first_bid_at   TEXT,
  close_at       TEXT,
  rival_bid_done INTEGER NOT NULL DEFAULT 0,
  soft_closes    INTEGER NOT NULL DEFAULT 0,
  settled_at     TEXT,
  won_by         TEXT,
  charged        INTEGER NOT NULL DEFAULT 0,
  allocation_id  INTEGER,
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lots_lookup ON lots (game, slot, region, state);
CREATE TABLE IF NOT EXISTS bids (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  lot_id     TEXT NOT NULL,
  bidder     TEXT NOT NULL,             -- you | rival
  amount     INTEGER NOT NULL,
  content_id TEXT,
  note       TEXT,
  at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bids_lot ON bids (lot_id, at);
CREATE TABLE IF NOT EXISTS saved_state (
  slot           TEXT NOT NULL,
  region         TEXT NOT NULL,
  content_id     TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  state          TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  PRIMARY KEY (slot, region, content_id)
);
"""

# Everything a reset wipes.
VISITOR_TABLES = ("allocations", "telemetry", "saved_state", "lots", "bids")


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Repo(ABC):
    # ---- lifecycle
    @abstractmethod
    def init_schema(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
    # ---- meta
    @abstractmethod
    def meta_get(self, key: str, default: Any = None) -> Any: ...
    @abstractmethod
    def meta_set(self, key: str, value: Any) -> None: ...
    # ---- games / slots
    @abstractmethod
    def seed_games(self, games: list[dict[str, Any]], slots: list[dict[str, Any]]) -> None: ...
    @abstractmethod
    def list_games(self) -> list[dict[str, Any]]: ...
    @abstractmethod
    def list_slots(self, game: str | None = None) -> list[dict[str, Any]]: ...
    # ---- brand / wallet
    @abstractmethod
    def get_brand(self) -> dict[str, Any] | None: ...
    @abstractmethod
    def set_brand(self, colour: str, emblem: str, now: datetime) -> dict[str, Any]: ...
    @abstractmethod
    def clear_brand(self) -> None: ...
    # ---- content
    @abstractmethod
    def add_content(self, content_id: str, piece: str, kind: str, size_class: str,
                    source: dict[str, Any], now: datetime) -> None: ...
    @abstractmethod
    def next_visitor_content_id(self) -> str: ...
    @abstractmethod
    def get_content(self, content_id: str) -> dict[str, Any] | None: ...
    @abstractmethod
    def list_content(self, kind: str | None = None) -> list[dict[str, Any]]: ...
    @abstractmethod
    def find_system_content(self, piece: str) -> dict[str, Any] | None: ...
    @abstractmethod
    def add_version(self, content_id: str, version_n: int, row: dict[str, Any],
                    now: datetime) -> None: ...
    @abstractmethod
    def versions(self, content_id: str) -> list[dict[str, Any]]: ...
    @abstractmethod
    def latest_approved(self, content_id: str) -> dict[str, Any] | None: ...
    @abstractmethod
    def delete_content(self, content_id: str) -> None: ...
    # ---- packs
    @abstractmethod
    def add_pack(self, row: dict[str, Any], now: datetime) -> None: ...
    @abstractmethod
    def get_pack(self, pack_id: str) -> dict[str, Any] | None: ...
    @abstractmethod
    def list_packs(self, kind: str | None = None) -> list[dict[str, Any]]: ...
    @abstractmethod
    def delete_pack_row(self, pack_id: str) -> None: ...
    # ---- allocations
    @abstractmethod
    def add_allocation(self, game: str, slot: str, region: str, kind: str, content_id: str,
                       start_at: datetime, end_at: datetime, source: str,
                       now: datetime) -> int: ...
    @abstractmethod
    def get_allocation(self, alloc_id: int) -> dict[str, Any] | None: ...
    @abstractmethod
    def active_allocation(self, game: str, slot: str, region: str,
                          at: datetime) -> dict[str, Any] | None: ...
    @abstractmethod
    def last_allocation_ended(self, game: str, slot: str, region: str, kind: str,
                              at: datetime) -> dict[str, Any] | None: ...
    @abstractmethod
    def set_paused(self, alloc_id: int, paused: bool) -> None: ...
    @abstractmethod
    def end_allocation(self, alloc_id: int, at: datetime) -> None: ...
    @abstractmethod
    def set_paused_all_visitor(self, paused: bool) -> int: ...
    @abstractmethod
    def last_allocation_end(self, game: str, slot: str, region: str) -> datetime | None: ...
    @abstractmethod
    def visitor_allocations(self) -> list[dict[str, Any]]: ...
    # ---- lots and bids (the auction)
    @abstractmethod
    def add_lot(self, row: dict[str, Any], now: datetime) -> None: ...
    @abstractmethod
    def get_lot(self, lot_id: str) -> dict[str, Any] | None: ...
    @abstractmethod
    def open_lot(self, game: str, slot: str, region: str) -> dict[str, Any] | None: ...
    @abstractmethod
    def live_lots(self) -> list[dict[str, Any]]: ...
    @abstractmethod
    def list_lots(self, game: str | None = None, slot: str | None = None,
                  region: str | None = None) -> list[dict[str, Any]]: ...
    @abstractmethod
    def update_lot(self, lot_id: str, fields: dict[str, Any]) -> None: ...
    @abstractmethod
    def next_lot_seq(self, game: str, slot: str, region: str) -> int: ...
    @abstractmethod
    def add_bid(self, lot_id: str, bidder: str, amount: int, content_id: str | None,
                note: str, at: datetime) -> None: ...
    @abstractmethod
    def bids_for(self, lot_id: str) -> list[dict[str, Any]]: ...
    @abstractmethod
    def sum_lots_held(self) -> int: ...
    @abstractmethod
    def sum_lots_charged(self, region: str | None = None) -> int: ...
    # ---- telemetry
    @abstractmethod
    def add_telemetry(self, events: Iterable[dict[str, Any]], now: datetime) -> int: ...
    @abstractmethod
    def telemetry_counts(self, region: str | None = None) -> dict[str, float]: ...
    @abstractmethod
    def telemetry_counts_by_slot(self, slot: str, event_type: str) -> dict[str, int]: ...
    @abstractmethod
    def telemetry_for_allocations(self, allocations: list[dict[str, Any]]) -> dict[str, float]: ...
    # ---- reset
    @abstractmethod
    def wipe_visitor_side(self) -> dict[str, Any]: ...
    @abstractmethod
    def counts(self) -> dict[str, int]: ...


class SqliteRepo(Repo):
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    # ---- lifecycle -----------------------------------------------------------------

    def init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ---- meta ----------------------------------------------------------------------

    def meta_get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def meta_set(self, key: str, value: Any) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))
            self.conn.commit()

    # ---- games / slots -------------------------------------------------------------

    def seed_games(self, games: list[dict[str, Any]], slots: list[dict[str, Any]]) -> None:
        with self._lock:
            for i, g in enumerate(games):
                self.conn.execute(
                    "INSERT INTO games(id, label, ord) VALUES(?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET label=excluded.label, ord=excluded.ord",
                    (g["id"], g["label"], i))
            for s in slots:
                self.conn.execute(
                    "INSERT INTO slots(id, game, size_class, slot_index, px_x, px_y) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "game=excluded.game, size_class=excluded.size_class, "
                    "slot_index=excluded.slot_index, px_x=excluded.px_x, px_y=excluded.px_y",
                    (s["id"], s["game"], s["size_class"], s["slot_index"],
                     s["px"][0], s["px"][1]))
            self.conn.commit()

    def list_games(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM games ORDER BY ord")]

    def list_slots(self, game: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM slots"
        args: tuple = ()
        if game:
            sql += " WHERE game=?"
            args = (game,)
        sql += " ORDER BY game, slot_index"
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args)]

    # ---- brand ---------------------------------------------------------------------

    def get_brand(self) -> dict[str, Any] | None:
        with self._lock:
            return _row(self.conn.execute("SELECT colour, emblem, created_at FROM brand WHERE id=1").fetchone())

    def set_brand(self, colour: str, emblem: str, now: datetime) -> dict[str, Any]:
        with self._lock:
            self.conn.execute(
                "INSERT INTO brand(id, colour, emblem, created_at) VALUES(1,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET colour=excluded.colour, emblem=excluded.emblem, "
                "created_at=excluded.created_at", (colour, emblem, iso(now)))
            self.conn.commit()
        return {"colour": colour, "emblem": emblem, "created_at": iso(now)}

    def clear_brand(self) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM brand")
            self.conn.commit()

    # ---- content -------------------------------------------------------------------

    def add_content(self, content_id: str, piece: str, kind: str, size_class: str,
                    source: dict[str, Any], now: datetime) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO content(id, piece, kind, size_class, source, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (content_id, piece, kind, size_class, json.dumps(source), iso(now)))
            self.conn.commit()

    def next_visitor_content_id(self) -> str:
        with self._lock:
            n = self.conn.execute(
                "SELECT COUNT(*) AS n FROM content WHERE kind='visitor'").fetchone()["n"]
        seq = int(self.meta_get("visitor_content_seq", 0) or 0)
        seq = max(seq, int(n)) + 1
        self.meta_set("visitor_content_seq", seq)
        return f"c{seq}"

    def get_content(self, content_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = _row(self.conn.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone())
        if row and row.get("source"):
            row["source"] = json.loads(row["source"])
        return row

    def list_content(self, kind: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM content", ()
        if kind:
            sql, args = sql + " WHERE kind=?", (kind,)
        sql += " ORDER BY created_at, id"
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(sql, args)]
        for r in rows:
            if r.get("source"):
                r["source"] = json.loads(r["source"])
        return rows

    def find_system_content(self, piece: str) -> dict[str, Any] | None:
        with self._lock:
            row = _row(self.conn.execute(
                "SELECT * FROM content WHERE kind='system' AND piece=? LIMIT 1", (piece,)).fetchone())
        if row and row.get("source"):
            row["source"] = json.loads(row["source"])
        return row

    def add_version(self, content_id: str, version_n: int, row: dict[str, Any],
                    now: datetime) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO content_versions(content_id, version_n, version, pack_id, status,"
                " rating, engine_version, size_class, bounds, class_path, state_schema,"
                " state_schema_version, checks, created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (content_id, version_n, row["version"], row.get("pack_id"), row["status"],
                 row.get("rating"), row.get("engine_version"), row.get("size_class"),
                 json.dumps(row.get("bounds")), row.get("class_path"),
                 json.dumps(row.get("state_schema")), row.get("state_schema_version"),
                 json.dumps(row.get("checks")), iso(now)))
            self.conn.commit()

    def _version_rows(self, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            d = dict(r)
            for key in ("bounds", "state_schema", "checks"):
                if d.get(key) is not None:
                    d[key] = json.loads(d[key])
            out.append(d)
        return out

    def versions(self, content_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM content_versions WHERE content_id=? ORDER BY version_n",
                (content_id,)).fetchall()
        return self._version_rows(rows)

    def latest_approved(self, content_id: str) -> dict[str, Any] | None:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM content_versions WHERE content_id=? AND status='approved' "
                "ORDER BY version_n DESC LIMIT 1", (content_id,)).fetchall()
        got = self._version_rows(rows)
        return got[0] if got else None

    def delete_content(self, content_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM content_versions WHERE content_id=?", (content_id,))
            self.conn.execute("DELETE FROM content WHERE id=?", (content_id,))
            self.conn.commit()

    # ---- packs ---------------------------------------------------------------------

    def add_pack(self, row: dict[str, Any], now: datetime) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO packs(id, content_id, piece, version, kind, files, total_bytes,"
                " record, signature, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (row["id"], row["content_id"], row["piece"], row["version"], row["kind"],
                 json.dumps(row["files"]), int(row["total_bytes"]),
                 json.dumps(row["record"]), row["signature"], iso(now)))
            self.conn.commit()

    def get_pack(self, pack_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = _row(self.conn.execute("SELECT * FROM packs WHERE id=?", (pack_id,)).fetchone())
        if row:
            row["files"] = json.loads(row["files"])
            row["record"] = json.loads(row["record"])
        return row

    def list_packs(self, kind: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM packs", ()
        if kind:
            sql, args = sql + " WHERE kind=?", (kind,)
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(sql + " ORDER BY created_at, id", args)]
        for r in rows:
            r["files"] = json.loads(r["files"])
            r["record"] = json.loads(r["record"])
        return rows

    def delete_pack_row(self, pack_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM packs WHERE id=?", (pack_id,))
            self.conn.commit()

    # ---- allocations ---------------------------------------------------------------

    def add_allocation(self, game: str, slot: str, region: str, kind: str, content_id: str,
                       start_at: datetime, end_at: datetime, source: str, now: datetime) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO allocations(game, slot, region, kind, content_id, start_at, end_at,"
                " paused, source, created_at) VALUES(?,?,?,?,?,?,?,0,?,?)",
                (game, slot, region, kind, content_id, iso(start_at), iso(end_at), source, iso(now)))
            self.conn.commit()
            return int(cur.lastrowid)

    def get_allocation(self, alloc_id: int) -> dict[str, Any] | None:
        with self._lock:
            return _row(self.conn.execute("SELECT * FROM allocations WHERE id=?", (alloc_id,)).fetchone())

    def active_allocation(self, game: str, slot: str, region: str,
                          at: datetime) -> dict[str, Any] | None:
        t = iso(at)
        with self._lock:
            return _row(self.conn.execute(
                "SELECT * FROM allocations WHERE game=? AND slot=? AND region=? "
                "AND start_at<=? AND end_at>? ORDER BY start_at DESC, id DESC LIMIT 1",
                (game, slot, region, t, t)).fetchone())

    def last_allocation_ended(self, game: str, slot: str, region: str, kind: str,
                              at: datetime) -> dict[str, Any] | None:
        t = iso(at)
        with self._lock:
            return _row(self.conn.execute(
                "SELECT * FROM allocations WHERE game=? AND slot=? AND region=? AND kind=? "
                "AND end_at<=? ORDER BY end_at DESC, id DESC LIMIT 1",
                (game, slot, region, kind, t)).fetchone())

    def set_paused(self, alloc_id: int, paused: bool) -> None:
        with self._lock:
            self.conn.execute("UPDATE allocations SET paused=? WHERE id=?",
                              (1 if paused else 0, alloc_id))
            self.conn.commit()

    def end_allocation(self, alloc_id: int, at: datetime) -> None:
        """Bring a block's end forward to `at` — "the three hours are up, now".

        Nothing else changes: the row stays, so `last_allocation_ended` finds it and the
        region's rival takes the next block exactly as it would have at the natural end.
        """
        with self._lock:
            self.conn.execute("UPDATE allocations SET end_at=? WHERE id=?", (iso(at), alloc_id))
            self.conn.commit()

    def set_paused_all_visitor(self, paused: bool) -> int:
        with self._lock:
            cur = self.conn.execute("UPDATE allocations SET paused=? WHERE kind='visitor'",
                                    (1 if paused else 0,))
            self.conn.commit()
            return cur.rowcount

    def last_allocation_end(self, game: str, slot: str, region: str) -> datetime | None:
        """When this slot-region is free again — an auction win queues behind it."""
        with self._lock:
            row = self.conn.execute(
                "SELECT MAX(end_at) AS last FROM allocations WHERE game=? AND slot=? AND region=?",
                (game, slot, region)).fetchone()
        return parse_iso(row["last"]) if row and row["last"] else None

    def visitor_allocations(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM allocations WHERE kind='visitor' ORDER BY start_at, id")]

    # ---- lots and bids -------------------------------------------------------------

    def add_lot(self, row: dict[str, Any], now: datetime) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO lots(id, game, slot, region, seq, opening, rival_max, state,"
                " highest, holder, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (row["id"], row["game"], row["slot"], row["region"], int(row["seq"]),
                 int(row["opening"]), int(row["rival_max"]), row["state"],
                 int(row["highest"]), row["holder"], iso(now)))
            self.conn.commit()

    def get_lot(self, lot_id: str) -> dict[str, Any] | None:
        with self._lock:
            return _row(self.conn.execute("SELECT * FROM lots WHERE id=?", (lot_id,)).fetchone())

    def open_lot(self, game: str, slot: str, region: str) -> dict[str, Any] | None:
        with self._lock:
            return _row(self.conn.execute(
                "SELECT * FROM lots WHERE game=? AND slot=? AND region=? AND state!='closed' "
                "ORDER BY seq DESC LIMIT 1", (game, slot, region)).fetchone())

    def live_lots(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM lots WHERE state!='closed' ORDER BY id")]

    def list_lots(self, game: str | None = None, slot: str | None = None,
                  region: str | None = None) -> list[dict[str, Any]]:
        where, args = [], []
        for column, value in (("game", game), ("slot", slot), ("region", region)):
            if value:
                where.append(f"{column}=?")
                args.append(value)
        sql = "SELECT * FROM lots"
        if where:
            sql += " WHERE " + " AND ".join(where)
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql + " ORDER BY slot, region, seq", args)]

    def update_lot(self, lot_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self.conn.execute(f"UPDATE lots SET {sets} WHERE id=?",
                              (*fields.values(), lot_id))
            self.conn.commit()

    def next_lot_seq(self, game: str, slot: str, region: str) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT MAX(seq) AS top FROM lots WHERE game=? AND slot=? AND region=?",
                (game, slot, region)).fetchone()
        return int(row["top"] or 0) + 1

    def add_bid(self, lot_id: str, bidder: str, amount: int, content_id: str | None,
                note: str, at: datetime) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO bids(lot_id, bidder, amount, content_id, note, at)"
                " VALUES(?,?,?,?,?,?)", (lot_id, bidder, int(amount), content_id, note, iso(at)))
            self.conn.commit()

    def bids_for(self, lot_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM bids WHERE lot_id=? ORDER BY at, id", (lot_id,))]

    def sum_lots_held(self) -> int:
        """Credits a leading bid is holding: every live lot the visitor is leading."""
        with self._lock:
            row = self.conn.execute(
                "SELECT SUM(highest) AS held FROM lots WHERE holder='you' AND state!='closed'"
            ).fetchone()
        return int(row["held"] or 0)

    def sum_lots_charged(self, region: str | None = None) -> int:
        sql = "SELECT SUM(charged) AS charged FROM lots WHERE won_by='you'"
        args: tuple = ()
        if region:
            sql += " AND region=?"
            args = (region,)
        with self._lock:
            row = self.conn.execute(sql, args).fetchone()
        return int(row["charged"] or 0)

    # ---- telemetry -----------------------------------------------------------------

    def add_telemetry(self, events: Iterable[dict[str, Any]], now: datetime) -> int:
        rows = [(e.get("game"), e.get("region"), e.get("slot"), e.get("alloc_key"),
                 e["type"], float(e.get("value") or 0.0), e.get("ts") or iso(now), iso(now))
                for e in events]
        if not rows:
            return 0
        with self._lock:
            self.conn.executemany(
                "INSERT INTO telemetry(game, region, slot, alloc_key, type, value, ts, received_at)"
                " VALUES(?,?,?,?,?,?,?,?)", rows)
            self.conn.commit()
        return len(rows)

    def telemetry_counts_by_slot(self, slot: str, event_type: str) -> dict[str, int]:
        """Real counted events for one slot, per region — the "live" half of footfall."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT region, COUNT(*) AS n FROM telemetry WHERE slot=? AND type=? "
                "GROUP BY region", (slot, event_type)).fetchall()
        return {r["region"]: int(r["n"]) for r in rows if r["region"]}

    def telemetry_for_allocations(self, allocations: list[dict[str, Any]]) -> dict[str, float]:
        """Everything the game reported while these allocations were the thing on screen.

        Telemetry carries the slot, the region and a timestamp, so a campaign's numbers are
        the events inside its own blocks — a minute of slack at the end covers a batch the
        client posts just after the block rolls over.
        """
        out: dict[str, float] = {}
        for row in allocations:
            start = row["start_at"]
            end = iso(parse_iso(row["end_at"]) + timedelta(seconds=60))
            with self._lock:
                counts = self.conn.execute(
                    "SELECT type, COUNT(*) AS n, SUM(value) AS total FROM telemetry "
                    "WHERE slot=? AND region=? AND ts>=? AND ts<=? GROUP BY type",
                    (row["slot"], row["region"], start, end)).fetchall()
            for count in counts:
                out[count["type"]] = out.get(count["type"], 0) + int(count["n"])
                key = f"{count['type']}_total"
                out[key] = out.get(key, 0.0) + float(count["total"] or 0.0)
        return out

    def telemetry_counts(self, region: str | None = None) -> dict[str, float]:
        sql = "SELECT type, COUNT(*) AS n, SUM(value) AS total FROM telemetry"
        args: tuple = ()
        if region:
            sql += " WHERE region=?"
            args = (region,)
        sql += " GROUP BY type"
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        out: dict[str, float] = {}
        for r in rows:
            out[r["type"]] = int(r["n"])
            out[f"{r['type']}_total"] = float(r["total"] or 0.0)
        return out

    # ---- reset ---------------------------------------------------------------------

    def wipe_visitor_side(self) -> dict[str, Any]:
        """Everything the visitor made. The rival and default packs are left alone."""
        wiped: dict[str, Any] = {}
        with self._lock:
            visitor_packs = [r["id"] for r in self.conn.execute(
                "SELECT id FROM packs WHERE kind='visitor'")]
            visitor_content = [r["id"] for r in self.conn.execute(
                "SELECT id FROM content WHERE kind='visitor'")]
            for table in VISITOR_TABLES:
                exists = self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                if not exists:
                    continue
                if table == "allocations":
                    cur = self.conn.execute("DELETE FROM allocations")
                else:
                    cur = self.conn.execute(f"DELETE FROM {table}")
                wiped[table] = cur.rowcount
            self.conn.execute("DELETE FROM packs WHERE kind='visitor'")
            self.conn.execute(
                "DELETE FROM content_versions WHERE content_id IN "
                "(SELECT id FROM content WHERE kind='visitor')")
            self.conn.execute("DELETE FROM content WHERE kind='visitor'")
            self.conn.execute("DELETE FROM brand")
            self.conn.commit()
        wiped["content"] = len(visitor_content)
        wiped["packs"] = len(visitor_packs)
        self.meta_set("visitor_content_seq", 0)
        return {"wiped": wiped, "purge_packs": visitor_packs, "content_ids": visitor_content}

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        with self._lock:
            for table in ("content", "content_versions", "packs", "allocations", "telemetry",
                          "saved_state", "lots", "bids", "games", "slots"):
                out[table] = int(self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
        return out
