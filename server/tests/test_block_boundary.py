"""Every telemetry event counts in exactly one block (brief 018 part 5b).

Brief 016's exit test made **76** interactions through the Player's own button and
`GET /report` came back saying **118**. Nothing was posted twice: the report counted some
of them twice, and here is why.

`Repo.telemetry_for_allocations` asked, per allocation, "how many events in
`[start_at, end_at + 60 s]`?" The sixty seconds of slack are there for a real reason - the
game batches telemetry and flushes it a second or two late, so a view that happened at
`end_at - 0.5 s` can arrive after the block is over. But when the same visitor holds the
**next** block of the same slot and region, that slack lies inside the next block's window
as well, and every event in it is counted for both.

The rule, and what these tests pin down: *each event counts in exactly one block, by its
timestamp against the allocation that was live at that moment.* The window is half open and
clamped to the start of the next block, so the slack survives where there is nothing after
it and cannot reach into a block that has its own claim.
"""
from __future__ import annotations

from datetime import timedelta

from dcserver.clock import iso, parse_iso


def post(env, key: str, kind: str, when, value: float = 1.0) -> None:
    env.ok(env.client.post("/telemetry", json=[{
        "game": "A", "region": "r1", "slot": "A1", "alloc_key": key, "type": kind,
        "value": value, "ts": iso(when)}]))


def region_row(env, region: str = "r1") -> dict:
    return next(r for r in env.report()["regions"] if r["region"] == region)


def two_touching_blocks(env) -> tuple[dict, dict]:
    """Two of the visitor's blocks in A1/r1, the second starting exactly where the first
    ends - which is what the auction does when a visitor books the next block."""
    env.brand()
    content = env.upload("content1_v1.dcpack")
    minutes = env.config.block_seconds / 60.0
    first = env.allocate("A", "A1", "r1", content["content_id"], minutes=minutes)

    # The second block starts the instant the first one ends.
    env.clock.advance(env.config.block_seconds)
    second = env.allocate("A", "A1", "r1", content["content_id"], minutes=minutes)
    assert parse_iso(second["start_at"]) == parse_iso(first["end_at"])
    return first, second


def test_an_event_in_the_slack_is_counted_once_not_twice(env) -> None:
    first, second = two_touching_blocks(env)
    key = env.key("A", "A1", "r1")

    # Ten interactions in the thirty seconds after the first block ended - which is also
    # the first thirty seconds of the second block. Before the fix every one of them was
    # counted for both blocks and the report said twenty.
    at = parse_iso(first["end_at"]) + timedelta(seconds=30)
    for _ in range(10):
        post(env, key, "interaction", at)

    row = region_row(env)
    assert row["blocks"] == 2
    assert row["interactions"] == 10, (
        "an event inside one block's slack and the next block's own window was counted "
        "for both")


def test_the_whole_of_a_run_adds_up(env) -> None:
    """The shape of brief 016's run: events scattered over two touching blocks."""
    first, second = two_touching_blocks(env)
    key = env.key("A", "A1", "r1")

    start1 = parse_iso(first["start_at"])
    start2 = parse_iso(second["start_at"])
    moments = [
        start1 + timedelta(seconds=1),      # well inside the first
        start1 + timedelta(seconds=30),
        parse_iso(first["end_at"]) - timedelta(seconds=1),
        start2 + timedelta(seconds=5),      # inside the first's old slack, and the second's
        start2 + timedelta(seconds=45),
        start2 + timedelta(seconds=90),     # well inside the second
    ]
    for when in moments:
        post(env, key, "visit", when)
        post(env, key, "dwell", when, value=4.0)

    row = region_row(env)
    assert row["visits"] == len(moments)
    assert row["dwell_s"] == len(moments) * 4.0


def test_the_slack_still_works_when_there_is_no_next_block(env) -> None:
    """The reason the slack exists: a batch the client posts just after a block ends."""
    env.brand()
    content = env.upload("content1_v1.dcpack")
    allocation = env.allocate("A", "A1", "r1", content["content_id"],
                              minutes=env.config.block_seconds / 60.0)
    key = env.key("A", "A1", "r1")

    post(env, key, "view", parse_iso(allocation["end_at"]) + timedelta(seconds=20))
    env.clock.advance(env.config.block_seconds + 60)
    assert region_row(env)["views_live"] == 1


def test_an_event_past_the_slack_belongs_to_nobody(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    allocation = env.allocate("A", "A1", "r1", content["content_id"],
                              minutes=env.config.block_seconds / 60.0)
    key = env.key("A", "A1", "r1")

    post(env, key, "view", parse_iso(allocation["end_at"]) + timedelta(seconds=120))
    env.clock.advance(env.config.block_seconds + 180)
    assert region_row(env)["views_live"] == 0


def test_two_slots_in_the_same_region_are_still_added_up(env) -> None:
    """The clamping is per slot and region: two different slots do not clamp each other."""
    env.brand()
    content = env.upload("content1_v1.dcpack")
    small = env.upload("content4_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])
    env.allocate("A", "A3", "r1", small["content_id"])
    key1 = env.key("A", "A1", "r1")
    key3 = env.key("A", "A3", "r1")

    now = env.svc.now()
    env.ok(env.client.post("/telemetry", json=[
        {"game": "A", "region": "r1", "slot": "A1", "alloc_key": key1, "type": "interaction",
         "value": 1, "ts": iso(now)},
        {"game": "A", "region": "r1", "slot": "A3", "alloc_key": key3, "type": "interaction",
         "value": 1, "ts": iso(now)},
    ]))
    assert region_row(env)["interactions"] == 2
