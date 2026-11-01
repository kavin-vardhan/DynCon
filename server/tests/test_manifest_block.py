"""The manifest says which lot and which block it is showing under (brief 018 part 4).

The X-ray view's answer to "isn't this just ChunkDownloader?" is, in one line of its
manifest panel, **lot / block**: the thing being auctioned is one slot x one region x one
time block, and a client that can name the one it is holding is doing more than fetching a
file. Both fields are inside the signed payload, like everything else the client acts on.

`lot` is deliberately empty for a block nobody bought: the attract rotation and the
rival's "block after the visitor's" are not sold, and saying they were would be a lie on
the one screen that exists to be checked.
"""
from __future__ import annotations


def test_a_block_written_by_hand_has_a_block_and_no_lot(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])

    showing = env.resolve("A", "A1", "r1")["showing"]
    assert showing["kind"] == "visitor"
    assert showing["block"] == 0                      # the demo clock's first block
    assert showing["lot"] is None                     # /admin/allocate, not an auction


def test_the_attract_rotation_has_a_block_and_no_lot(env) -> None:
    showing = env.resolve("A", "A1", "r1")["showing"]
    assert showing["source"].startswith("rotation:")
    assert showing["block"] == 0
    assert showing["lot"] is None


def test_the_block_number_follows_the_demo_clock(env) -> None:
    assert env.resolve("A", "A1", "r1")["showing"]["block"] == 0
    env.clock.advance(env.config.block_seconds + 1)
    assert env.resolve("A", "A1", "r1")["showing"]["block"] == 1
    env.clock.advance(env.config.block_seconds)
    assert env.resolve("A", "A1", "r1")["showing"]["block"] == 2


def test_a_block_won_in_an_auction_names_its_lot(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    lot = env.lot_for("A1", "r1")

    # Open, let the rival make its one counter-bid, then beat it: the lot has to be *won*,
    # because the whole point of the field is that a won block can name what it was won in.
    first = env.bid("A1", content["content_id"], {"r1": lot["opening"]})["results"][0]
    lot_id = first["lot"]["lot_id"]
    env.clock.advance(4)
    assert env.lot(lot_id)["holder"] == "rival"
    env.bid("A1", content["content_id"], {"r1": env.lot(lot_id)["highest"] + 50})
    env.close_auction("all")

    showing = env.resolve("A", "A1", "r1")["showing"]
    assert showing["kind"] == "visitor"
    assert showing["lot"] == lot_id
    assert showing["block"] == 0


def test_the_block_and_the_lot_are_inside_what_was_signed(env) -> None:
    """Not metadata bolted on next to the signature - part of the bytes it covers."""
    import json

    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])
    envelope = env.envelope("A", "A1", "r1")
    payload = json.loads(envelope["signed_payload"])
    assert "block" in payload["showing"] and "lot" in payload["showing"]
