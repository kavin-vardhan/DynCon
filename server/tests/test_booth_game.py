"""Which game the booth is playing, and the two kinds of reset (brief 018 part 2 and §4).

Two small things the game and the portal needed from the platform once the Player could
switch games from the pause menu.

**The badge.** Plan v6 §4 step 3: on "Pick a game", the game being played at the booth is
badged. That used to be a flag in `demo.json`, written down once; now a visitor can switch
game in the middle of a visit, so it follows the poll the game already makes - and the
**preview** copy, which plays whatever map it was started on as another region, says
`preview=1` and is ignored.

**The reset.** Both the staff combo on pad 2 and the portal's own sixty-second idle timer
post `/admin/reset`. They are not the same event: the staff one is clearing the booth down
between visitors and the game drops back to its attract loop, the idle one is the *brand*
seat going quiet and must not take the game away from a Player who is still standing in it
(plan v6 §2 - two seats, possibly two visitors). So the reset carries a reason and
`/changes` hands it to every copy of the game.
"""
from __future__ import annotations


def badge(env) -> str | None:
    rows = env.ok(env.client.get("/games"))["games"]
    return next((r["id"] for r in rows if r["live_at_booth"]), None)


def test_the_badge_starts_on_the_config_s_own_game(env) -> None:
    """Nothing has polled yet, so it is whatever demo.json says - a clean checkout serves
    the right answer without Unreal ever having run."""
    assert badge(env) == "A"
    assert env.ok(env.client.get("/games/A"))["live_at_booth"] is True
    assert env.ok(env.client.get("/games/B"))["live_at_booth"] is False


def test_the_badge_follows_the_game_that_polls(env) -> None:
    env.changes("B", "r1")
    assert badge(env) == "B"
    assert env.ok(env.client.get("/games/B"))["live_at_booth"] is True
    assert env.ok(env.client.get("/games/A"))["live_at_booth"] is False

    env.changes("A", "r1")
    assert badge(env) == "A"


def test_the_preview_copy_does_not_move_the_badge(env) -> None:
    env.changes("A", "r1")
    env.ok(env.client.get("/changes", params={"game": "B", "region": "r2", "preview": 1}))
    assert badge(env) == "A", "the second copy of the game is not the booth's own screen"


def test_the_preview_focus_follows_the_booth_too(env) -> None:
    """Rule 3 of `preview_focus`: with nothing bid on, the busiest slot of the game being
    played at the booth. Switching game moves it."""
    env.changes("A", "r1")
    assert env.ok(env.client.get("/preview/region"))["focus"]["game"] == "A"
    env.changes("B", "r1")
    assert env.ok(env.client.get("/preview/region"))["focus"]["game"] == "B"


def test_the_reset_carries_who_asked_for_it(env) -> None:
    assert env.changes()["reset_reason"] == "staff"          # the default before any reset

    env.ok(env.client.post("/admin/reset", json={"reason": "idle"}))
    body = env.changes()
    assert body["reset_reason"] == "idle"
    assert body["reset_generation"] == 1

    env.ok(env.client.post("/admin/reset", json={"reason": "staff"}))
    body = env.changes()
    assert body["reset_reason"] == "staff"
    assert body["reset_generation"] == 2


def test_a_reset_with_no_body_is_a_staff_reset(env) -> None:
    """Anything that posts the bare endpoint is a staffer at the booth, which is the
    cautious reading: it clears the game down as well."""
    assert env.ok(env.client.post("/admin/reset"))["reason"] == "staff"
    assert env.changes()["reset_reason"] == "staff"


def test_a_nonsense_reason_is_read_as_staff(env) -> None:
    assert env.ok(env.client.post("/admin/reset",
                                  json={"reason": "whatever"}))["reason"] == "staff"


def test_both_kinds_of_reset_wipe_the_same_things(env) -> None:
    """The reason changes what the *game* does, and nothing about what the server wipes."""
    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])
    env.ok(env.client.post("/admin/reset", json={"reason": "idle"}))
    assert env.ok(env.client.get("/brand"))["brand"] is None
    assert env.ok(env.client.get("/content"))["content"] == []
