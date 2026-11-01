"""`POST /admin/end-block` — the three demo hours are up, now (brief 016).

The counterpart of `/admin/close-auction`: a way to make a timestamp rule fire on cue instead
of waiting three real minutes for it. What has to be true afterwards is that **nothing
special** happened — the ordinary rule in `rules.resolve_showing` takes over, which is the
region's rival holding the block after the visitor's.
"""
from __future__ import annotations

from dcserver.clock import parse_iso


def test_ending_a_block_hands_it_to_the_regions_rival(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    allocation = env.allocate("A", "A1", "r1", content["content_id"])
    before_key = env.key("A", "A1", "r1")
    assert env.resolve("A", "A1", "r1")["content"]["piece"] == "content1"

    ended = env.ok(env.client.post("/admin/end-block",
                                   json={"game": "A", "slot": "A1", "region": "r1"}))
    assert ended["allocation_id"] == allocation["allocation_id"]
    assert ended["was"]["piece"] == "content1"
    assert ended["now"]["piece"] == "rival1"          # r1's large rival, from demo.json

    manifest = env.resolve("A", "A1", "r1")
    assert manifest["content"]["piece"] == "rival1"
    assert manifest["brand"] == {"colour": "#1FA39A", "emblem": "triangle"}
    assert manifest["showing"]["source"].startswith("rival-after:")
    # The key is what a game client polls on, so it has to have moved.
    assert env.key("A", "A1", "r1") != before_key


def test_the_rival_holds_exactly_one_block_after_an_ended_one(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])
    env.ok(env.client.post("/admin/end-block",
                           json={"game": "A", "slot": "A1", "region": "r1"}))
    assert env.resolve("A", "A1", "r1")["showing"]["source"].startswith("rival-after:")

    # One block later it is the attract rotation's turn again, not the rival's for ever.
    env.clock.advance(env.config.block_seconds + 1)
    assert not env.resolve("A", "A1", "r1")["showing"]["source"].startswith("rival-after:")


def test_an_ended_block_keeps_its_telemetry_and_its_charge(env) -> None:
    """The row stays - only `end_at` moves - so the report still knows the block happened."""
    env.brand()
    content = env.upload("content1_v1.dcpack")
    allocation = env.allocate("A", "A1", "r1", content["content_id"])
    key = env.key("A", "A1", "r1")
    env.ok(env.client.post("/telemetry", json=[
        {"game": "A", "region": "r1", "slot": "A1", "alloc_key": key, "type": "visit",
         "value": 1},
        {"game": "A", "region": "r1", "slot": "A1", "alloc_key": key, "type": "dwell",
         "value": 21.5},
        {"game": "A", "region": "r1", "slot": "A1", "alloc_key": key, "type": "interaction",
         "value": 1},
    ]))
    env.ok(env.client.post("/admin/end-block",
                           json={"game": "A", "slot": "A1", "region": "r1"}))

    region = next(r for r in env.report()["regions"] if r["region"] == "r1")
    assert region["blocks"] == 1 and region["blocks_started"] == 1
    assert region["visits"] == 1 and region["dwell_s"] == 21.5 and region["interactions"] == 1
    row = env.svc.repo.get_allocation(allocation["allocation_id"])
    assert parse_iso(row["end_at"]) <= env.svc.now()


def test_ending_a_block_that_is_not_there(env) -> None:
    assert env.ok(env.client.post("/admin/end-block",
                                  json={"game": "A", "slot": "A1", "region": "r1"}),
                  404)["error"].startswith("Nothing is allocated to slot A1")
    assert env.ok(env.client.post("/admin/end-block",
                                  json={"game": "A", "slot": "B2", "region": "r1"}),
                  404)["error"] == "Game A has no slot B2."
