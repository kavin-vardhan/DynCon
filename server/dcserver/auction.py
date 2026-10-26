"""The auction — lots, the scripted rival, the clock, credits, and the allocation on close.

Like everything else here it is **lazy**: nothing runs on a timer. A lot's state is worked
out from its timestamps when a request arrives, and the two things that "happen" by
themselves — the rival's counter-bid and the close — are applied by `advance_lot` the first
time anyone asks after they were due. The same code would therefore work in a Lambda that
only wakes up for requests, and the tests can move a fake clock instead of waiting.

The rules (spec v1 §5, demo plan v6 §5 and §9):

* A **lot** is one slot × one region × the next block. One open lot per slot-region at a
  time; when one closes the next request opens a fresh one, which is what "book the next
  block" means.
* **open** — the rival holds at the opening price, no clock. Opening price =
  footfall(slot, region) × 0.25 rounded to the nearest 25, so A1 / Japan opens at 300.
* **running** — the visitor's first bid sets `close_at = now + 45 s`.
* **The rival** waits 3 s after the visitor's *first* bid and then raises **once**, to
  min(visitor + 25, 2 × opening), and only if that actually beats the visitor. Never again.
  So the visitor can always win inside the 2,000-credit wallet.
* **Soft close** — a visitor bid with 10 s or less left sets `close_at = now + 10 s`.
* **Credits** — a leading bid holds, being outbid releases, a win charges. All three are
  *derived* from the lots (held = what you are leading on, charged = what you won), so the
  wallet can never drift out of step with the auctions.
* **On close** the winner gets the slot-region for one block. The visitor's block starts at
  the close, or when their current block there ends if they already hold one. A rival win
  writes the rival's own block, so the slot visibly goes to the rival.

Bids are never compared across regions: a multi-region bid is just several bids placed at
once, each landing in its own lot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .clock import DemoClock, iso, parse_iso
from .config import Config
from .packs import AXIS_WORDS, fit_failure
from .repo import Repo

OPEN, RUNNING, CLOSED = "open", "running", "closed"
YOU, RIVAL = "you", "rival"


@dataclass
class AuctionCtx:
    config: Config
    repo: Repo
    demo: DemoClock
    now: datetime

    @property
    def auction(self) -> dict[str, Any]:
        return self.config.data["auction"]


# ---------------------------------------------------------------------------------------
# prices
# ---------------------------------------------------------------------------------------

def round_to(value: float, step: int) -> int:
    """Half-up, so 37.5 goes to 50 and the portal never shows a price it cannot step to."""
    return int(Decimal(value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * step


def opening_price(cfg: Config, slot: str, region: str) -> int:
    a = cfg.data["auction"]
    return round_to(cfg.footfall(slot, region) * float(a["opening_factor"]),
                    int(a["opening_round_to"]))


def rival_ceiling(cfg: Config, slot: str, region: str) -> int:
    return int(opening_price(cfg, slot, region) * float(cfg.data["auction"]["rival_max_factor"]))


def views_per_block(cfg: Config, slot: str, region: str) -> float:
    """A block is 3 demo hours, and footfall is per demo hour."""
    return cfg.footfall(slot, region) * float(cfg.data["block_demo_hours"])


def per_thousand_views(cfg: Config, slot: str, region: str, credits: int) -> float | None:
    views = views_per_block(cfg, slot, region)
    return round(credits / (views / 1000.0), 2) if views else None


def split_by_footfall(cfg: Config, slot: str, total: int, regions: list[str]) -> dict[str, int]:
    """One total across ticked regions, split by footfall and stepped to the min raise.

    The remainder goes to the biggest region, and every share is at least that region's
    next bid if the total can cover it — the portal lets the visitor adjust afterwards.
    """
    step = int(cfg.data["auction"]["min_raise"])
    weights = {r: cfg.footfall(slot, r) for r in regions}
    weight_sum = sum(weights.values()) or 1
    shares = {r: round_to(total * w / weight_sum, step) for r, w in weights.items()}
    drift = total - sum(shares.values())
    if drift and shares:
        biggest = max(shares, key=lambda r: weights[r])
        shares[biggest] = max(step, shares[biggest] + round_to(drift, step))
    return shares


# ---------------------------------------------------------------------------------------
# reading lots
# ---------------------------------------------------------------------------------------

def current_lot(ctx: AuctionCtx, game: str, slot: str, region: str,
                create: bool = True) -> dict[str, Any] | None:
    """The lot on offer for this slot-region, opened on demand."""
    lot = ctx.repo.open_lot(game, slot, region)
    if lot:
        return advance_lot(ctx, lot)
    if not create:
        return None
    opening = opening_price(ctx.config, slot, region)
    seq = ctx.repo.next_lot_seq(game, slot, region)
    lot_id = f"lot_{slot}_{region}_{seq}"
    ctx.repo.add_lot({
        "id": lot_id, "game": game, "slot": slot, "region": region, "seq": seq,
        "opening": opening, "rival_max": rival_ceiling(ctx.config, slot, region),
        "state": OPEN, "highest": opening, "holder": RIVAL,
    }, ctx.now)
    ctx.repo.add_bid(lot_id, RIVAL, opening, None, "opening price", ctx.now)
    return ctx.repo.get_lot(lot_id)


def lots_for_slot(ctx: AuctionCtx, game: str, slot: str) -> dict[str, dict[str, Any]]:
    return {region: current_lot(ctx, game, slot, region) for region in ctx.config.regions}


def advance_all(ctx: AuctionCtx) -> list[dict[str, Any]]:
    """Catch up every lot that is not closed. Called at the top of a request."""
    return [advance_lot(ctx, lot) for lot in ctx.repo.live_lots()]


def advance_lot(ctx: AuctionCtx, lot: dict[str, Any]) -> dict[str, Any]:
    """Apply anything that fell due since the last request: the rival's bid, then the close.

    Order matters. If no request arrives for a minute, the rival's bid was due 3 s in and
    the close 45 s in, so the rival's bid has to land *before* the lot is settled.
    """
    if lot["state"] == CLOSED:
        return lot
    if lot["state"] == RUNNING and not lot["rival_bid_done"] and lot["first_bid_at"]:
        due = parse_iso(lot["first_bid_at"]) + timedelta(seconds=float(ctx.auction["rival_delay_s"]))
        if ctx.now >= due:
            lot = _rival_counter_bid(ctx, lot, at=due)
    if lot["state"] == RUNNING and lot["close_at"] and parse_iso(lot["close_at"]) <= ctx.now:
        lot = settle(ctx, lot)
    return lot


def _rival_counter_bid(ctx: AuctionCtx, lot: dict[str, Any], at: datetime) -> dict[str, Any]:
    """Once, 3 s after the visitor's first bid, and only if it beats them."""
    amount = min(int(lot["highest"]) + int(ctx.auction["min_raise"]), int(lot["rival_max"]))
    fields: dict[str, Any] = {"rival_bid_done": 1}
    if lot["holder"] == YOU and amount > int(lot["highest"]):
        fields.update(highest=amount, holder=RIVAL)
        ctx.repo.add_bid(lot["id"], RIVAL, amount, None,
                         f"counter-bid (the rival will not go above {lot['rival_max']})", at)
    else:
        ctx.repo.add_bid(lot["id"], RIVAL, int(lot["rival_max"]), None,
                         f"passed — the rival will not go above {lot['rival_max']}", at)
    ctx.repo.update_lot(lot["id"], fields)
    return ctx.repo.get_lot(lot["id"])


# ---------------------------------------------------------------------------------------
# bidding
# ---------------------------------------------------------------------------------------

def next_bid(lot: dict[str, Any], min_raise: int) -> int:
    return int(lot["highest"]) + min_raise


def wallet(ctx: AuctionCtx) -> dict[str, Any]:
    """held = what you are leading on · charged = what you won. Both derived, never stored."""
    held = ctx.repo.sum_lots_held()
    charged = ctx.repo.sum_lots_charged()
    return {"available": ctx.config.wallet_start - held - charged,
            "held": held, "charged": charged}


def _fit_refusal(ctx: AuctionCtx, slot: str, content: dict[str, Any],
                 version: dict[str, Any]) -> str | None:
    bounds = {a: float((version.get("bounds") or {}).get(a, 0.0)) for a in ("x", "y", "z")}
    bad = fit_failure(bounds, ctx.config.limits(ctx.config.slot(slot).size_class))
    if not bad:
        return None
    axis, tail = bad
    return (f"{content['piece']} does not fit slot {slot} — too {AXIS_WORDS[axis]}, {tail}.")


def place_bids(ctx: AuctionCtx, slot: str, content_id: str,
               bids: list[dict[str, Any]]) -> dict[str, Any]:
    """One bid per region, each judged on its own lot. Partly accepted is a normal answer.

    A bid may name the `lot_id` it was made against — the portal always knows which lot it
    is showing — and then a bid that arrives after that auction closed is refused instead of
    quietly opening the next block's auction and holding credits for it.
    """
    slot_def = ctx.config.slot(slot)
    content = ctx.repo.get_content(content_id)
    version = ctx.repo.latest_approved(content_id) if content else None
    fit_problem = _fit_refusal(ctx, slot, content, version) if (content and version) else None

    results = []
    for wanted in bids:
        region = wanted.get("region")
        amount = wanted.get("amount")
        if region not in ctx.config.regions:
            results.append({"region": region, "accepted": False,
                            "reason": f"There is no region {region}.", "lot": None})
            continue
        asked_for = wanted.get("lot_id")
        lot = current_lot(ctx, slot_def.game, slot, region)
        card = lambda: lot_card(ctx, ctx.repo.get_lot(lot["id"]))      # noqa: E731
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            results.append({"region": region, "accepted": False,
                            "reason": "A bid has to be a number of credits.", "lot": card()})
            continue
        if asked_for and asked_for != lot["id"]:
            # the portal bid on the lot it was showing, and that auction has moved on
            stale = ctx.repo.get_lot(asked_for)
            label = ctx.config.region_label(region)
            reason = (f"{label}'s auction for this slot has closed." if stale
                      else f"There is no lot {asked_for}.")
            results.append({"region": region, "accepted": False, "reason": reason,
                            "lot": card()})
            continue
        refusal = _refuse(ctx, lot, slot, content, version, fit_problem, amount)
        if refusal:
            results.append({"region": region, "accepted": False, "reason": refusal,
                            "lot": card()})
            continue
        lot = _accept_bid(ctx, lot, content_id, amount)
        results.append({"region": region, "accepted": True, "amount": amount,
                        "reason": _leading_sentence(ctx, lot), "lot": lot_card(ctx, lot)})
    return {"slot": slot, "content_id": content_id, "results": results, "wallet": wallet(ctx)}


def _refuse(ctx: AuctionCtx, lot: dict[str, Any], slot: str, content: dict[str, Any] | None,
            version: dict[str, Any] | None, fit_problem: str | None, amount: int) -> str | None:
    """The four refusals from spec §4, in the order the portal explains them."""
    region_label = ctx.config.region_label(lot["region"])
    if lot["state"] == CLOSED:
        return f"{region_label}'s auction for this slot has closed."
    if not content or content["kind"] != "visitor":
        return "That is not one of your uploads."
    if not version:
        return "That content has no approved version yet."
    if fit_problem:
        return fit_problem
    need = next_bid(lot, int(ctx.auction["min_raise"]))
    if amount < need:
        holder = "you hold it" if lot["holder"] == YOU else "the rival holds it"
        return (f"{region_label} is at {lot['highest']} ({holder}), so the next bid is "
                f"{need}.")
    purse = wallet(ctx)
    already = int(lot["highest"]) if lot["holder"] == YOU else 0
    if amount - already > purse["available"]:
        return (f"You have {purse['available']} credits available and this bid needs "
                f"{amount - already} more.")
    return None


def _accept_bid(ctx: AuctionCtx, lot: dict[str, Any], content_id: str,
                amount: int) -> dict[str, Any]:
    fields: dict[str, Any] = {"highest": amount, "holder": YOU, "content_id": content_id}
    note = "bid"
    if lot["state"] == OPEN:
        fields["state"] = RUNNING
        fields["first_bid_at"] = iso(ctx.now)
        fields["close_at"] = iso(ctx.now + timedelta(seconds=float(ctx.auction["clock_s"])))
        note = f"first bid — the clock starts at {int(ctx.auction['clock_s'])} s"
    else:
        left = (parse_iso(lot["close_at"]) - ctx.now).total_seconds()
        soft = float(ctx.auction["soft_close_s"])
        if left <= soft:
            fields["close_at"] = iso(ctx.now + timedelta(seconds=soft))
            fields["soft_closes"] = int(lot["soft_closes"] or 0) + 1
            note = f"bid in the last {int(soft)} s — the clock resets to {int(soft)} s"
    ctx.repo.update_lot(lot["id"], fields)
    ctx.repo.add_bid(lot["id"], YOU, amount, content_id, note, ctx.now)
    return ctx.repo.get_lot(lot["id"])


def _leading_sentence(ctx: AuctionCtx, lot: dict[str, Any]) -> str:
    label = ctx.config.region_label(lot["region"])
    left = (parse_iso(lot["close_at"]) - ctx.now).total_seconds() if lot["close_at"] else None
    tail = f" — {math.ceil(left)} s left" if left is not None else ""
    return f"Leading in {label} at {lot['highest']}{tail}."


# ---------------------------------------------------------------------------------------
# closing
# ---------------------------------------------------------------------------------------

def settle(ctx: AuctionCtx, lot: dict[str, Any], at: datetime | None = None) -> dict[str, Any]:
    """Charge the winner, write their block, close the lot. Idempotent."""
    if lot["state"] == CLOSED:
        return lot
    closed_at = at or (parse_iso(lot["close_at"]) if lot["close_at"] else ctx.now)
    winner = lot["holder"] if lot["state"] == RUNNING else RIVAL
    block = timedelta(seconds=ctx.demo.block_s)

    # the visitor's block starts at the close, or after the block they already hold there
    last_end = ctx.repo.last_allocation_end(lot["game"], lot["slot"], lot["region"])
    start_at = max(closed_at, last_end) if last_end and last_end > closed_at else closed_at

    fields: dict[str, Any] = {"state": CLOSED, "settled_at": iso(closed_at), "won_by": winner}
    if winner == YOU:
        content_id = lot["content_id"]
        fields["charged"] = int(lot["highest"])
        alloc_id = ctx.repo.add_allocation(
            lot["game"], lot["slot"], lot["region"], "visitor", content_id,
            start_at, start_at + block, f"auction:{lot['id']}", ctx.now)
        fields["allocation_id"] = alloc_id
    else:
        piece = ctx.config.rival_piece(lot["region"], ctx.config.slot(lot["slot"]).size_class)
        rival_content = ctx.repo.find_system_content(piece)
        if rival_content:
            alloc_id = ctx.repo.add_allocation(
                lot["game"], lot["slot"], lot["region"], "rival", rival_content["id"],
                start_at, start_at + block, f"auction:{lot['id']}", ctx.now)
            fields["allocation_id"] = alloc_id
    ctx.repo.update_lot(lot["id"], fields)
    ctx.repo.add_bid(lot["id"], winner, int(lot["highest"]), lot["content_id"],
                     f"won the block ({'you' if winner == YOU else 'the rival'})", closed_at)
    return ctx.repo.get_lot(lot["id"])


def force_close(ctx: AuctionCtx, which: str) -> list[dict[str, Any]]:
    """Booth staff: close one lot or every live one, now."""
    if which == "all":
        lots = ctx.repo.live_lots()
    else:
        one = ctx.repo.get_lot(which)
        if not one:
            return []
        lots = [one]
    out = []
    for lot in lots:
        lot = advance_lot(ctx, lot)
        if lot["state"] != CLOSED:
            lot = settle(ctx, lot, at=ctx.now)
        out.append(lot_card(ctx, lot))
    return out


# ---------------------------------------------------------------------------------------
# what the portal draws
# ---------------------------------------------------------------------------------------

def lot_card(ctx: AuctionCtx, lot: dict[str, Any], history: bool = False) -> dict[str, Any]:
    min_raise = int(ctx.auction["min_raise"])
    closes_in = None
    if lot["close_at"] and lot["state"] != CLOSED:
        closes_in = round(max((parse_iso(lot["close_at"]) - ctx.now).total_seconds(), 0.0), 2)
    card: dict[str, Any] = {
        "lot_id": lot["id"], "game": lot["game"], "slot": lot["slot"], "region": lot["region"],
        "region_label": ctx.config.region_label(lot["region"]),
        "seq": lot["seq"], "state": lot["state"],
        "opening": int(lot["opening"]), "highest": int(lot["highest"]),
        "holder": lot["holder"], "next_bid": next_bid(lot, min_raise),
        "min_raise": min_raise, "rival_max": int(lot["rival_max"]),
        "your_bid": int(lot["highest"]) if lot["holder"] == YOU else None,
        "close_at": lot["close_at"], "closes_in_s": closes_in,
        "clock_s": float(ctx.auction["clock_s"]),
        "soft_closes": int(lot["soft_closes"] or 0),
        "rival_has_bid": bool(lot["rival_bid_done"]),
        "content_id": lot["content_id"],
        "won_by": lot["won_by"], "settled_at": lot["settled_at"],
        "charged": int(lot["charged"] or 0), "allocation_id": lot["allocation_id"],
        "footfall_per_demo_hour": ctx.config.footfall(lot["slot"], lot["region"]),
        "views_per_block": views_per_block(ctx.config, lot["slot"], lot["region"]),
        "credits_per_1000_views": per_thousand_views(ctx.config, lot["slot"], lot["region"],
                                                     int(lot["highest"])),
    }
    if history:
        card["history"] = [
            {"at": row["at"], "bidder": row["bidder"], "amount": int(row["amount"]),
             "note": row["note"]} for row in ctx.repo.bids_for(lot["id"])]
    return card
