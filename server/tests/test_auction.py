"""The auction: lots, the scripted rival, the clock, credits, and the block that is won.

Every test here moves the fake clock instead of waiting, which is the point of evaluating
the rules from timestamps: the same code that makes a 45-second auction work at the booth
can be stepped through in milliseconds.
"""
from __future__ import annotations

import pytest

from dcserver.auction import opening_price, round_to, split_by_footfall
from dcserver.clock import parse_iso


@pytest.fixture
def ready(env):
    """A visitor with a brand and an approved Content 1, which fits A1, A2 and B1."""
    env.brand("#E23D3D", "star")
    content = env.upload("content1_v1.dcpack")
    return env, content["content_id"]


# ---------------------------------------------------------------------------- prices

def test_opening_prices_come_from_footfall(env) -> None:
    cfg = env.config
    assert opening_price(cfg, "A1", "r1") == 300          # 1200 x 0.25, the plan's example
    assert opening_price(cfg, "A1", "r2") == 225
    assert opening_price(cfg, "A1", "r3") == 150
    assert opening_price(cfg, "A2", "r1") == 200
    assert opening_price(cfg, "B2", "r3") == 25           # 120 x 0.25 = 30, stepped to 25
    for slot in cfg.slots:
        for region in cfg.regions:
            price = opening_price(cfg, slot.id, region)
            assert price % 25 == 0 and price >= 25


def test_rounding_is_half_up(env) -> None:
    assert (round_to(37.5, 25), round_to(62.5, 25), round_to(30, 25)) == (50, 75, 25)


def test_a_lot_opens_with_the_rival_holding_and_no_clock(ready) -> None:
    env, _ = ready
    lot = env.lot_for("A1", "r1")
    assert lot["state"] == "open"
    assert (lot["opening"], lot["highest"], lot["holder"]) == (300, 300, "rival")
    assert lot["next_bid"] == 325
    assert lot["rival_max"] == 600
    assert lot["closes_in_s"] is None                     # no clock until the first bid
    assert lot["lot_id"] == "lot_A1_r1_1"
    assert lot["views_per_block"] == 3600                 # 1200 per demo hour x 3 hours
    assert lot["credits_per_1000_views"] == pytest.approx(83.33, abs=0.01)


# ---------------------------------------------------------------- the run of an auction

def test_first_bid_rival_counter_raise_soft_close_and_win(ready) -> None:
    """The whole arc from spec §7, one step at a time."""
    env, content_id = ready
    clock_s = env.config.data["auction"]["clock_s"]

    first = env.bid("A1", content_id, {"r1": 325})["results"][0]
    assert first["accepted"] is True
    lot_id = first["lot"]["lot_id"]
    assert first["lot"]["state"] == "running"
    assert first["lot"]["closes_in_s"] == pytest.approx(clock_s, abs=0.01)
    assert env.wallet() == {"available": 2000 - 325, "held": 325, "charged": 0}

    env.clock.advance(1)                                  # the rival waits 3 s
    assert env.lot(lot_id)["holder"] == "you"
    assert env.lot(lot_id)["rival_has_bid"] is False

    env.clock.advance(2.5)                                # now it is due
    after = env.lot(lot_id)
    assert after["rival_has_bid"] is True
    assert (after["holder"], after["highest"]) == ("rival", 350)   # 325 + 25
    assert env.wallet() == {"available": 2000, "held": 0, "charged": 0}   # outbid releases
    assert [b["bidder"] for b in after["history"]] == ["rival", "you", "rival"]
    assert "counter-bid" in after["history"][-1]["note"]

    raised = env.bid("A1", content_id, {"r1": 375})["results"][0]
    assert raised["accepted"] is True
    assert raised["lot"]["holder"] == "you"
    assert env.wallet()["held"] == 375

    # the rival never bids again
    env.clock.advance(10)
    assert env.lot(lot_id)["holder"] == "you"

    # a bid with 10 s or less left resets the clock to 10 s
    env.clock.advance(clock_s - 18)              # 4.5 s left on a 45 s clock
    late = env.lot(lot_id)
    assert 0 < late["closes_in_s"] <= 10
    extended = env.bid("A1", content_id, {"r1": 400})["results"][0]
    assert extended["lot"]["closes_in_s"] == pytest.approx(10, abs=0.01)
    assert extended["lot"]["soft_closes"] == 1

    env.clock.advance(11)                                 # let it run out
    settled = env.lot(lot_id)
    assert settled["state"] == "closed"
    assert settled["won_by"] == "you"
    assert settled["charged"] == 400
    assert env.wallet() == {"available": 1600, "held": 0, "charged": 400}
    assert settled["allocation_id"]
    assert env.resolve("A", "A1", "r1")["showing"]["source"] == f"alloc:{settled['allocation_id']}"
    assert env.resolve("A", "A1", "r1")["content"]["piece"] == "content1"


def test_losing_leaves_the_rival_showing_and_the_credits_untouched(ready) -> None:
    env, content_id = ready
    lot_id = env.bid("A1", content_id, {"r1": 325})["results"][0]["lot"]["lot_id"]
    env.clock.advance(4)                                  # the rival takes it to 350
    assert env.lot(lot_id)["holder"] == "rival"
    env.clock.advance(50)                                 # the visitor does not come back
    lost = env.lot(lot_id)
    assert (lost["state"], lost["won_by"]) == ("closed", "rival")
    assert env.wallet() == {"available": 2000, "held": 0, "charged": 0}
    showing = env.resolve("A", "A1", "r1")["showing"]
    assert showing["kind"] == "rival"
    allocation = env.svc.repo.get_allocation(lost["allocation_id"])
    assert allocation["source"] == f"auction:{lot_id}"
    assert showing["source"] == f"alloc:{lost['allocation_id']}"
    assert env.resolve("A", "A1", "r1")["content"]["piece"] == "rival1"
    assert env.resolve("A", "A1", "r1")["brand"] == {"colour": "#1FA39A", "emblem": "triangle"}


def test_a_lowball_bid_loses_in_a_small_slot(env) -> None:
    """A3 / Europe opens at 50, so the rival's ceiling is 100 and 75 is not enough."""
    env.brand()
    content = env.upload("content4_v1.dcpack")
    lot_id = env.bid("A3", content["content_id"], {"r3": 75})["results"][0]["lot"]["lot_id"]
    env.clock.advance(4)
    beaten = env.lot(lot_id)
    assert (beaten["highest"], beaten["holder"]) == (100, "rival")
    env.clock.advance(60)
    assert env.lot(lot_id)["won_by"] == "rival"
    assert env.resolve("A", "A3", "r3")["content"]["piece"] == "rivalsmall"


def test_the_rival_passes_when_the_visitor_is_already_above_its_ceiling(ready) -> None:
    env, content_id = ready
    lot_id = env.bid("A1", content_id, {"r1": 600})["results"][0]["lot"]["lot_id"]
    env.clock.advance(4)
    lot = env.lot(lot_id)
    assert lot["rival_has_bid"] is True
    assert (lot["holder"], lot["highest"]) == ("you", 600)
    assert "passed" in lot["history"][-1]["note"]
    env.clock.advance(60)
    assert env.lot(lot_id)["won_by"] == "you"


def test_soft_close_extends_once_per_late_bid(ready) -> None:
    env, content_id = ready
    clock_s = env.config.data["auction"]["clock_s"]
    lot_id = env.bid("A1", content_id, {"r1": 325})["results"][0]["lot"]["lot_id"]
    env.clock.advance(clock_s - 5)                        # 5 s left
    for n, amount in enumerate((400, 425, 450), start=1):
        card = env.bid("A1", content_id, {"r1": amount})["results"][0]["lot"]
        assert card["closes_in_s"] == pytest.approx(10, abs=0.01), amount
        assert card["soft_closes"] == n
        env.clock.advance(5)                              # each bid buys exactly 10 s
    assert env.lot(lot_id)["state"] == "running"
    env.clock.advance(11)
    assert env.lot(lot_id)["state"] == "closed"


def test_an_early_bid_does_not_extend_the_clock(ready) -> None:
    env, content_id = ready
    lot_id = env.bid("A1", content_id, {"r1": 325})["results"][0]["lot"]["lot_id"]
    env.clock.advance(5)
    card = env.bid("A1", content_id, {"r1": 400})["results"][0]["lot"]
    assert card["soft_closes"] == 0
    assert card["closes_in_s"] == pytest.approx(40, abs=0.01)
    assert env.lot(lot_id)["closes_in_s"] == pytest.approx(40, abs=0.01)


# ---------------------------------------------------------------------- refusals

def test_a_bid_below_the_next_bid_is_refused_with_the_price(ready) -> None:
    env, content_id = ready
    result = env.bid("A1", content_id, {"r1": 300})["results"][0]
    assert result["accepted"] is False
    assert result["reason"] == "Japan is at 300 (the rival holds it), so the next bid is 325."
    assert env.wallet()["held"] == 0


def test_a_bid_you_cannot_afford_is_refused(ready) -> None:
    env, content_id = ready
    assert env.bid("A1", content_id, {"r1": 1900})["results"][0]["accepted"] is True
    second = env.bid("A2", content_id, {"r1": 225})["results"][0]
    assert second["accepted"] is False
    assert second["reason"] == "You have 100 credits available and this bid needs 225 more."


def test_raising_your_own_bid_only_needs_the_difference(ready) -> None:
    env, content_id = ready
    env.bid("A1", content_id, {"r1": 1900})
    raised = env.bid("A1", content_id, {"r1": 1950})["results"][0]
    assert raised["accepted"] is True                     # only 50 more was needed
    assert env.wallet() == {"available": 50, "held": 1950, "charged": 0}


def test_content_that_does_not_fit_cannot_be_bid_with(env) -> None:
    env.brand()
    tall = env.upload("content3_v1.dcpack")               # 17 m: A2 only
    refused = env.bid("A1", tall["content_id"], {"r1": 325})["results"][0]
    assert refused["accepted"] is False
    assert refused["reason"] == ("content3 does not fit slot A1 — too tall, 17.0 m against "
                                 "a 9.0 m limit.")
    assert env.bid("A2", tall["content_id"], {"r1": 225})["results"][0]["accepted"] is True


def test_a_closed_lot_cannot_be_bid_on(ready) -> None:
    env, content_id = ready
    lot_id = env.bid("A1", content_id, {"r1": 325})["results"][0]["lot"]["lot_id"]
    env.close_auction(lot_id)
    refused = env.bid("A1", content_id, {"r1": 500}, lot_ids={"r1": lot_id})["results"][0]
    assert refused["accepted"] is False
    assert refused["reason"] == "Japan's auction for this slot has closed."
    assert env.wallet()["held"] == 0
    # without a lot id the visitor is simply bidding on the next block, which is allowed
    assert env.bid("A1", content_id, {"r1": 325})["results"][0]["lot"]["lot_id"] == \
        "lot_A1_r1_2"


def test_bidding_with_something_that_is_not_yours(env) -> None:
    env.brand()
    assert env.bid("A1", "sys_rival1", {"r1": 325})["results"][0]["reason"] == \
        "That is not one of your uploads."
    assert env.bid("A1", "c99", {"r1": 325})["results"][0]["reason"] == \
        "That is not one of your uploads."
    assert env.bid("Z9", "c1", {"r1": 325}, expect=404)["error"] == "There is no slot Z9."
    env.upload("content1_v1.dcpack")
    assert env.bid("A1", "c1", {"r9": 325})["results"][0]["reason"] == "There is no region r9."


# ------------------------------------------------------------------- multi-region

def test_every_region_of_a1_is_winnable_inside_the_wallet(ready) -> None:
    """The plan's promise: a 2,000 wallet can beat the rival everywhere on A1."""
    env, content_id = ready
    opened = env.bid("A1", content_id, {"r1": 325, "r2": 250, "r3": 175})
    assert [r["accepted"] for r in opened["results"]] == [True, True, True]
    assert opened["wallet"]["held"] == 750

    env.clock.advance(4)                                  # all three rivals counter once
    cards = {r: env.lot_for("A1", r) for r in env.config.regions}
    assert [cards[r]["holder"] for r in env.config.regions] == ["rival"] * 3
    assert [cards[r]["highest"] for r in env.config.regions] == [350, 275, 200]
    assert env.wallet()["held"] == 0

    beat = env.bid("A1", content_id, {r: cards[r]["next_bid"] for r in env.config.regions})
    assert [r["accepted"] for r in beat["results"]] == [True, True, True]
    assert beat["wallet"]["held"] == 375 + 300 + 225
    assert beat["wallet"]["available"] >= 0

    env.clock.advance(60)
    for region in env.config.regions:
        assert env.resolve("A", "A1", region)["content"]["piece"] == "content1"
    purse = env.wallet()
    assert purse["charged"] == 900 and purse["held"] == 0
    assert purse["available"] == 1100


def test_a_total_is_split_by_footfall(env) -> None:
    shares = split_by_footfall(env.config, "A1", 900, ["r1", "r2", "r3"])
    assert shares == {"r1": 400, "r2": 300, "r3": 200}
    assert sum(shares.values()) == 900
    split = env.ok(env.client.get("/bids/split", params={"slot": "A1", "total": 900,
                                                         "regions": "r1,r2,r3"}))
    assert [row["amount"] for row in split["bids"]] == [400, 300, 200]
    assert all(row["enough"] for row in split["bids"])
    assert split["allocated"] == 900
    thin = env.ok(env.client.get("/bids/split", params={"slot": "A1", "total": 300,
                                                        "regions": "r1,r2,r3"}))
    assert [row["amount"] for row in thin["bids"]] == [125, 100, 75]
    assert [row["enough"] for row in thin["bids"]] == [False, False, False]
    assert [row["next_bid"] for row in thin["bids"]] == [325, 250, 175]


def test_regions_are_never_compared_with_each_other(ready) -> None:
    """A big multi-region bid does not steamroll a region it is losing."""
    env, content_id = ready
    env.bid("A1", content_id, {"r1": 325, "r2": 600})
    env.clock.advance(4)
    assert env.lot_for("A1", "r1")["holder"] == "rival"   # outbid here
    assert env.lot_for("A1", "r2")["holder"] == "you"     # still leading there
    env.clock.advance(60)
    assert env.resolve("A", "A1", "r1")["content"]["piece"] == "rival1"
    assert env.resolve("A", "A1", "r2")["content"]["piece"] == "content1"


# ------------------------------------------------------------------ closing and blocks

def test_close_auction_forces_settlement(ready) -> None:
    env, content_id = ready
    lot_id = env.bid("A1", content_id, {"r1": 325})["results"][0]["lot"]["lot_id"]
    closed = env.close_auction(lot_id)
    assert closed["closed"][0]["state"] == "closed"
    assert closed["closed"][0]["won_by"] == "you"
    assert closed["wallet"] == {"available": 1675, "held": 0, "charged": 325}
    assert env.close_auction("lot_nope", expect=404)["error"] == "There is no lot lot_nope."


def test_close_auction_all_settles_every_live_lot(ready) -> None:
    env, content_id = ready
    env.bid("A1", content_id, {"r1": 325})
    env.ok(env.client.get("/games/A"))                    # opens a lot for every slot-region
    result = env.close_auction("all")
    assert len(result["closed"]) >= 9
    assert {card["state"] for card in result["closed"]} == {"closed"}
    winners = {card["lot_id"]: card["won_by"] for card in result["closed"]}
    assert winners["lot_A1_r1_1"] == "you"
    assert all(w == "rival" for k, w in winners.items() if k != "lot_A1_r1_1")


def test_the_won_block_lasts_one_block_and_then_goes_to_the_rival(ready) -> None:
    env, content_id = ready
    env.bid("A1", content_id, {"r1": 325})
    env.close_auction("lot_A1_r1_1")
    lot = env.lot("lot_A1_r1_1")
    start = parse_iso(lot["settled_at"])
    allocation = env.svc.repo.get_allocation(lot["allocation_id"])
    assert parse_iso(allocation["start_at"]) == start
    assert (parse_iso(allocation["end_at"]) - start).total_seconds() == env.config.block_seconds
    assert allocation["source"] == "auction:lot_A1_r1_1"

    env.clock.advance(env.config.block_seconds + 1)
    after = env.resolve("A", "A1", "r1")
    assert after["showing"]["kind"] == "rival"             # the next block is the rival's
    assert after["showing"]["source"].startswith("rival-after:")


def test_a_second_win_queues_behind_the_block_you_already_hold(ready) -> None:
    """"Book the next block": the new allocation starts when the live one ends."""
    env, content_id = ready
    env.bid("A1", content_id, {"r1": 325})
    env.close_auction("lot_A1_r1_1")
    first = env.svc.repo.get_allocation(env.lot("lot_A1_r1_1")["allocation_id"])

    env.clock.advance(5)
    again = env.bid("A1", content_id, {"r1": 325})["results"][0]
    assert again["accepted"] is True
    assert again["lot"]["lot_id"] == "lot_A1_r1_2"         # a fresh lot for the next block
    env.close_auction("lot_A1_r1_2")
    second = env.svc.repo.get_allocation(env.lot("lot_A1_r1_2")["allocation_id"])
    assert second["start_at"] == first["end_at"]
    assert env.wallet()["charged"] == 650

    # the slot keeps showing the visitor across the boundary
    env.clock.advance(env.config.block_seconds)
    assert env.resolve("A", "A1", "r1")["showing"]["kind"] == "visitor"


def test_an_auction_settles_lazily_even_if_nobody_asks_for_a_while(ready) -> None:
    """No timers: the close is applied by the first request after it fell due, and the
    rival's counter-bid still lands before it, in the order it was due."""
    env, content_id = ready
    lot_id = env.bid("A1", content_id, {"r1": 325})["results"][0]["lot"]["lot_id"]
    env.clock.advance(600)                                 # ten minutes of silence
    lot = env.lot(lot_id)
    assert lot["state"] == "closed"
    assert lot["won_by"] == "rival"                        # the rival's 350 was due at 3 s
    assert lot["highest"] == 350
    assert [b["bidder"] for b in lot["history"]] == ["rival", "you", "rival", "rival"]
    assert parse_iso(lot["settled_at"]) < env.clock.now()  # closed at its own close time


def test_reset_wipes_the_lots_the_bids_and_the_credits(ready) -> None:
    env, content_id = ready
    env.bid("A1", content_id, {"r1": 325})
    env.close_auction("lot_A1_r1_1")
    assert env.wallet()["charged"] == 325
    env.ok(env.client.post("/admin/reset"))
    assert env.wallet() == {"available": 2000, "held": 0, "charged": 0}
    assert env.ok(env.client.get("/lots"))["lots"] == []
    counts = env.ok(env.client.get("/admin/health"))["counts"]
    assert counts["lots"] == 0 and counts["bids"] == 0 and counts["allocations"] == 0
    assert env.lot("lot_A1_r1_1", expect=404)["error"] == "There is no lot lot_A1_r1_1."
    # and the next visitor starts from a fresh lot at the opening price
    env.brand()
    again = env.upload("content1_v1.dcpack")
    assert env.lot_for("A1", "r1")["lot_id"] == "lot_A1_r1_1"
    assert env.lot_for("A1", "r1")["highest"] == 300
    assert again["content_id"] == "c1"


def test_lots_can_be_listed_for_the_portal(ready) -> None:
    env, content_id = ready
    env.bid("A1", content_id, {"r1": 325, "r2": 250})
    listing = env.ok(env.client.get("/lots", params={"slot": "A1"}))
    assert {row["lot_id"] for row in listing["lots"]} == {"lot_A1_r1_1", "lot_A1_r2_1",
                                                           "lot_A1_r3_1"}
    assert listing["wallet"]["held"] == 575
    one_region = env.ok(env.client.get("/lots", params={"slot": "A1", "region": "r2"}))
    assert [row["lot_id"] for row in one_region["lots"]] == ["lot_A1_r2_1"]
    assert env.ok(env.client.get("/lots", params={"slot": "ZZ"}), 404)["error"] == \
        "There is no slot ZZ."
