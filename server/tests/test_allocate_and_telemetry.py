"""Writing an allocation by hand (also how part 2's auction will write one), and telemetry."""
from __future__ import annotations

from dcserver.clock import parse_iso


def test_an_allocation_lasts_one_block_by_default(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    allocation = env.allocate("A", "A1", "r1", content["content_id"])
    start = parse_iso(allocation["start_at"])
    end = parse_iso(allocation["end_at"])
    assert (end - start).total_seconds() == env.config.block_seconds
    assert allocation["kind"] == "visitor"
    assert allocation["showing"]["kind"] == "visitor"
    assert allocation["showing"]["piece"] == "content1"


def test_a_piece_that_does_not_fit_is_refused_with_the_reason(env) -> None:
    content = env.upload("content3_v1.dcpack")           # 17 m tall
    error = env.allocate("A", "A1", "r1", content["content_id"], expect=400)["error"]
    assert error == "content3 does not fit slot A1 — too tall, 17.0 m against a 9.0 m limit."
    assert env.allocate("A", "A2", "r1", content["content_id"])["kind"] == "visitor"


def test_a_rival_or_default_block_can_be_written_by_hand(env) -> None:
    rival = env.allocate("A", "A1", "r3", "sys_rival3")
    assert rival["kind"] == "rival"
    manifest = env.resolve("A", "A1", "r3")
    assert manifest["content"]["piece"] == "rival3"
    assert manifest["brand"] == {"colour": "#7B5CD6", "emblem": "diamond"}
    assert manifest["is_default"] is False

    default = env.allocate("A", "A2", "r1", "sys_default")
    assert default["kind"] == "default"
    assert env.resolve("A", "A2", "r1")["is_default"] is True


def test_a_rival_large_piece_cannot_be_put_in_a_small_slot(env) -> None:
    error = env.allocate("A", "A3", "r1", "sys_rival1", expect=400)["error"]
    assert error.startswith("rival1 does not fit slot A3")
    assert env.allocate("A", "A3", "r1", "sys_rivalsmall")["kind"] == "rival"


def test_allocating_things_that_do_not_exist(env) -> None:
    assert env.allocate("A", "A1", "r1", "c99", expect=404)["error"] == "There is no content c99."
    assert env.allocate("Z", "A1", "r1", "sys_default", expect=404)["error"] == \
        "There is no game Z."
    assert env.allocate("A", "B2", "r1", "sys_default", expect=404)["error"] == \
        "Game A has no slot B2."
    assert env.allocate("A", "A1", "r7", "sys_default", expect=404)["error"] == \
        "There is no region r7."
    assert env.allocate("A", "A1", "r1", "sys_default", minutes=0, expect=400)["error"] == \
        "An allocation has to last longer than zero minutes."


def test_a_later_allocation_wins_the_overlap(env) -> None:
    """Part 2 writes one allocation per block; if two overlap, the newest is what shows."""
    env.brand()
    first = env.upload("content1_v1.dcpack")
    second = env.upload("content2_v1.dcpack")
    env.allocate("A", "A1", "r1", first["content_id"], minutes=5)
    env.allocate("A", "A1", "r1", second["content_id"], minutes=5)
    assert env.resolve("A", "A1", "r1")["content"]["piece"] == "content2"


def test_telemetry_is_counted_and_nonsense_is_turned_away(env) -> None:
    env.brand()
    content = env.upload("content4_v1.dcpack")
    env.allocate("A", "A3", "r1", content["content_id"])
    key = env.key("A", "A3", "r1")
    events = [
        {"game": "A", "region": "r1", "slot": "A3", "alloc_key": key, "type": "mount", "value": 1},
        {"game": "A", "region": "r1", "slot": "A3", "alloc_key": key, "type": "view", "value": 1},
        {"game": "A", "region": "r1", "slot": "A3", "alloc_key": key, "type": "visit", "value": 1},
        {"game": "A", "region": "r1", "slot": "A3", "alloc_key": key, "type": "dwell", "value": 12.5},
        {"game": "A", "region": "r1", "slot": "A3", "alloc_key": key, "type": "interaction",
         "value": 3},
        {"game": "A", "region": "r1", "slot": "A3", "type": "cartwheel", "value": 1},
    ]
    result = env.ok(env.client.post("/telemetry", json=events))
    assert result["accepted"] == 5
    assert len(result["rejected"]) == 1
    counts = env.svc.repo.telemetry_counts("r1")
    assert counts["view"] == 1 and counts["dwell_total"] == 12.5
    assert env.ok(env.client.get("/admin/health"))["counts"]["telemetry"] == 5


def test_telemetry_accepts_the_batch_in_either_shape(env) -> None:
    one = [{"game": "A", "region": "r1", "slot": "A1", "type": "view", "value": 1}]
    assert env.ok(env.client.post("/telemetry", json=one))["accepted"] == 1
    assert env.ok(env.client.post("/telemetry", json={"events": one}))["accepted"] == 1
    assert env.client.post("/telemetry", json={"events": "nope"}).status_code == 400


def test_client_config_tells_the_game_what_it_needs(env) -> None:
    config = env.ok(env.client.get("/client-config"))
    assert config["poll_interval_s"] == 1.5
    assert config["prefetch_radius_m"] == 60.0
    assert config["public_key_pem"].startswith("-----BEGIN PUBLIC KEY-----")
    assert config["clock"]["demo_seconds_per_real_second"] == 60
    assert config["clock"]["block_seconds"] == 180.0
    assert config["telemetry"]["view_min_seconds"] == 1.0
    assert config["telemetry"]["view_radius_m"] == 30.0
    assert config["games"] == {"A": ["A1", "A2", "A3"], "B": ["B1", "B2"]}
    assert config["mode"] == "local"


def test_the_public_config_is_what_the_portal_draws_from(env) -> None:
    public = env.ok(env.client.get("/config/public"))
    # English only since 2026-11-02: there is no `label_jp` here any more.
    assert public["regions"]["r1"] == {"label": "Japan", "neutral_label": "Mock region 1"}
    assert public["games"]["A"]["slots"][0]["id"] == "A1"
    assert public["footfall"]["A1"]["r1"] == 1200
    assert public["wallet"] == 2000
    assert "public_key_pem" not in public
