"""The attract rotation and the rival's "next winner" block — all from timestamps."""
from __future__ import annotations

from dcserver.clock import parse_iso


def piece_at(env, slot: str, region: str = "r1") -> str:
    return env.resolve("A", slot, region)["content"]["piece"]


def kinds(env, region: str = "r1") -> dict[str, str]:
    return {slot.id: env.resolve("A", slot.id, region)["showing"]["kind"]
            for slot in env.config.slots_of("A")}


def test_the_rotation_alternates_between_the_rival_and_the_default(env) -> None:
    """(block + slot index) even -> the region's rival, odd -> the default."""
    block = env.config.block_seconds
    assert kinds(env) == {"A1": "rival", "A2": "default", "A3": "rival"}
    env.clock.advance(block)
    assert kinds(env) == {"A1": "default", "A2": "rival", "A3": "default"}
    env.clock.advance(block)
    assert kinds(env) == {"A1": "rival", "A2": "default", "A3": "rival"}


def test_a_key_changes_exactly_at_the_block_boundary(env) -> None:
    block = env.config.block_seconds
    first = env.changes("A", "r1")
    ends_in = first["block_ends_in_s"]
    assert 0 < ends_in <= block
    env.clock.advance(ends_in - 0.5)
    assert env.changes("A", "r1")["slots"] == first["slots"]
    env.clock.advance(1.0)                                    # over the edge
    assert env.changes("A", "r1")["slots"] != first["slots"]


def test_the_rotation_ends_at_the_block_end(env) -> None:
    manifest = env.resolve("A", "A1", "r1")
    demo = env.svc.demo()
    k = demo.block_index(env.clock.now())
    assert parse_iso(manifest["showing"]["ends_at"]) == demo.block_end(k)
    assert manifest["showing"]["source"] == f"rotation:{k}"


def test_the_block_after_a_visitor_block_belongs_to_the_region_rival(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r2", content["content_id"], minutes=1)
    assert env.resolve("A", "A1", "r2")["showing"]["kind"] == "visitor"

    env.clock.advance(61)
    after = env.resolve("A", "A1", "r2")
    assert after["showing"]["kind"] == "rival"
    assert after["showing"]["source"].startswith("rival-after:")
    assert after["content"]["piece"] == "rival2"              # region 2's own rival
    assert after["brand"] == {"colour": "#F28C28", "emblem": "ring"}

    # ... and only for one block, then the rotation takes over again
    env.clock.advance(env.config.block_seconds)
    assert not env.resolve("A", "A1", "r2")["showing"]["source"].startswith("rival-after:")


def test_an_s_slot_always_gets_the_small_rival_piece(env) -> None:
    for region in env.config.regions:
        for slot in ("A3", "B2"):
            game = "A" if slot.startswith("A") else "B"
            manifest = env.resolve(game, slot, region)
            if manifest["showing"]["kind"] == "rival":
                assert manifest["content"]["piece"] == "rivalsmall"


def test_every_slot_always_shows_something(env) -> None:
    """Across four blocks and every region, no slot is ever empty."""
    for _ in range(4):
        for game in env.config.games:
            for slot in env.config.slots_of(game):
                for region in env.config.regions:
                    manifest = env.resolve(game, slot.id, region)
                    assert manifest["content"]["piece"]
                    assert manifest["pack"]["files"]
        env.clock.advance(env.config.block_seconds)


def test_an_allocation_longer_than_a_block_keeps_showing(env) -> None:
    env.brand()
    content = env.upload("content4_v1.dcpack")
    env.allocate("A", "A3", "r1", content["content_id"], minutes=10)
    key = env.key("A", "A3", "r1")
    env.clock.advance(env.config.block_seconds * 2)
    assert env.key("A", "A3", "r1") == key
    assert env.resolve("A", "A3", "r1")["showing"]["kind"] == "visitor"
