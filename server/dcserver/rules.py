"""What shows in a slot, right now — the one rule the whole demo turns on.

Everything here is evaluated lazily from stored timestamps, so there are no timers and no
background threads: the same code can run in a Lambda that only ever wakes up for a request.

At time t, for one game / slot / region (spec v1 §5):

1. a visitor allocation covering t, not paused  →  the visitor's content: the latest approved
   version, dressed in the visitor's brand;
2. paused                                       →  the developer's default (your content comes
   down; the slot is never empty);
3. the block straight after a visitor allocation →  that region's rival — the "next winner";
4. otherwise the attract rotation: block k = floor((t − epoch) / block), and
   (k + slot index) even → the region's rival in the rival's colours, odd → default.

An allocation written by hand for a rival or the default (admin, or part 2's auction) is
honoured as itself at step 1.

`alloc_key` is the short hash a game client polls on: it changes exactly when what should
show changes — a different allocation, piece, version, pack or brand, a pause, a push-update
or a block rolling over.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .clock import DemoClock, parse_iso
from .config import Config
from .repo import Repo

KIND_VISITOR = "visitor"
KIND_RIVAL = "rival"
KIND_DEFAULT = "default"


def alloc_key(source: str, piece: str, version: str, version_n: int, pack_id: str,
              brand: dict[str, Any] | None) -> str:
    brand_part = f"{brand['colour']}|{brand['emblem']}" if brand else "-"
    raw = f"{source}|{piece}|{version}|{version_n}|{pack_id}|{brand_part}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class Showing:
    kind: str
    source: str
    content_id: str
    piece: str
    version: str
    version_n: int
    size_class: str
    class_path: str
    state_schema: list[str]
    state_schema_version: int
    pack_id: str
    brand: dict[str, Any] | None
    ends_at: datetime
    reason: str

    @property
    def is_default(self) -> bool:
        return self.kind == KIND_DEFAULT

    @property
    def alloc_key(self) -> str:
        return alloc_key(self.source, self.piece, self.version, self.version_n,
                         self.pack_id, self.brand)


def visitor_brand(repo: Repo) -> dict[str, Any] | None:
    """Just the colour and the emblem — the manifest is signed, so it carries no more."""
    brand = repo.get_brand()
    return {"colour": brand["colour"], "emblem": brand["emblem"]} if brand else None


def _showing(repo: Repo, content: dict[str, Any], kind: str, source: str,
             brand: dict[str, Any] | None, ends_at: datetime, reason: str) -> Showing | None:
    """A showing of one content record, or None when it has no signed pack to serve."""
    version = repo.latest_approved(content["id"])
    if not version or not version.get("pack_id"):
        return None
    if not repo.get_pack(version["pack_id"]):
        return None
    return Showing(
        kind=kind, source=source, content_id=content["id"], piece=content["piece"],
        version=version["version"], version_n=int(version["version_n"]),
        size_class=version.get("size_class") or content.get("size_class") or "",
        class_path=version.get("class_path") or "",
        state_schema=version.get("state_schema") or [],
        state_schema_version=int(version.get("state_schema_version") or 1),
        pack_id=version["pack_id"], brand=brand, ends_at=ends_at, reason=reason)


def _rival_showing(cfg: Config, repo: Repo, region: str, size_class: str, source: str,
                   ends_at: datetime, reason: str) -> Showing | None:
    piece = cfg.rival_piece(region, size_class)
    content = repo.find_system_content(piece)
    if not content:
        return None
    rival = cfg.rival(region)
    brand = {"colour": rival["colour"], "emblem": rival["emblem"]}
    return _showing(repo, content, KIND_RIVAL, source, brand, ends_at, reason)


def _default_showing(cfg: Config, repo: Repo, source: str, ends_at: datetime,
                     reason: str) -> Showing | None:
    content = repo.find_system_content(cfg.default_piece)
    if not content:
        return None
    return _showing(repo, content, KIND_DEFAULT, source, None, ends_at, reason)


def resolve_showing(cfg: Config, repo: Repo, demo: DemoClock, game: str, slot_id: str,
                    region: str, now: datetime) -> Showing | None:
    """The four steps. None means not even a default pack is registered."""
    slot = cfg.slot(slot_id)

    def fall_back_to_default(source: str, ends_at: datetime, reason: str) -> Showing | None:
        return _default_showing(cfg, repo, source, ends_at, reason)

    # 1 / 2 — an allocation covering now
    active = repo.active_allocation(game, slot_id, region, now)
    if active:
        ends_at = parse_iso(active["end_at"])
        source = f"alloc:{active['id']}"
        if active["kind"] == KIND_VISITOR and int(active["paused"] or 0):
            return fall_back_to_default(f"{source}:paused", ends_at,
                                        "the campaign is paused, so the default is showing")
        content = repo.get_content(active["content_id"])
        if content:
            if active["kind"] == KIND_VISITOR:
                showing = _showing(repo, content, KIND_VISITOR, source, visitor_brand(repo),
                                   ends_at, "the visitor's allocation is live")
            elif active["kind"] == KIND_RIVAL:
                rival = cfg.rival(region)
                showing = _showing(repo, content, KIND_RIVAL, source,
                                   {"colour": rival["colour"], "emblem": rival["emblem"]},
                                   ends_at, "a rival holds this block")
            else:
                showing = _showing(repo, content, KIND_DEFAULT, source, None,
                                   ends_at, "the default is allocated to this block")
            if showing:
                return showing
        # allocated content with no servable pack — never leave the slot empty
        return fall_back_to_default(f"{source}:nopack", ends_at,
                                    "the allocated content has no signed pack, so the default is showing")

    # 3 — the block straight after a visitor's block belongs to the region's rival
    last = repo.last_allocation_ended(game, slot_id, region, KIND_VISITOR, now)
    if last:
        ended = parse_iso(last["end_at"])
        rival_until = ended + timedelta(seconds=demo.block_s)
        if now < rival_until:
            showing = _rival_showing(cfg, repo, region, slot.size_class,
                                     f"rival-after:{last['id']}", rival_until,
                                     "the block after the visitor's block goes to the region's rival")
            if showing:
                return showing
            return fall_back_to_default(f"rival-after:{last['id']}:nopack", rival_until,
                                        "no rival pack is registered, so the default is showing")

    # 4 — attract rotation
    k = demo.block_index(now)
    ends_at = demo.block_end(k)
    source = f"rotation:{k}"
    if (k + slot.index) % 2 == 0:
        showing = _rival_showing(cfg, repo, region, slot.size_class, source, ends_at,
                                 "attract rotation: the region's rival has this block")
        if showing:
            return showing
    return fall_back_to_default(source, ends_at, "attract rotation: the default has this block")
