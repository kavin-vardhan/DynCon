"""/resolve — the signed manifest the game mounts from, and the alloc_key it polls on."""
from __future__ import annotations

from dcserver.clock import parse_iso
from dcserver.signing import verify_with_public_pem


def floats_in(value, path="") -> list[str]:
    if isinstance(value, float):
        return [path]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in floats_in(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in floats_in(v, f"{path}[{i}]")]
    return []


def test_the_signature_verifies_with_nothing_but_the_public_key(env) -> None:
    manifest = env.resolve("A", "A1", "r1")
    signature = manifest.pop("signature")
    assert verify_with_public_pem(env.public_pem(), manifest, signature)
    assert manifest["signature_alg"] == "RS256-canonical-json-v1"
    # Nothing in the signed payload is a floating-point number, so there is nothing for a
    # verifier that is not Python (the UE client) to format differently when it rebuilds
    # the canonical bytes.
    assert floats_in(manifest) == []


def test_a_tampered_manifest_does_not_verify(env) -> None:
    manifest = env.resolve("A", "A1", "r1")
    signature = manifest.pop("signature")
    manifest["content"]["class_path"] = "/Game/Somebody/Elses/Thing.Thing_C"
    assert not verify_with_public_pem(env.public_pem(), manifest, signature)


def test_the_manifest_has_everything_the_client_needs(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])
    manifest = env.resolve("A", "A1", "r1")
    assert manifest["slot"] == "A1" and manifest["game"] == "A" and manifest["region"] == "r1"
    assert manifest["is_default"] is False
    assert manifest["content"] == {
        "piece": "content1", "version": "v1", "size_class": "L",
        "class_path": "/Game/DCContent/content1_v1/BP_DC_content1_v1.BP_DC_content1_v1_C",
        "state_schema": ["light_a_on", "light_b_on", "door_open", "screen_image_index"],
        "state_schema_version": 1}
    assert manifest["brand"] == {"colour": "#E23D3D", "emblem": "star"}
    assert manifest["showing"]["kind"] == "visitor"
    assert len(manifest["pack"]["files"]) == 3
    for entry in manifest["pack"]["files"]:
        assert entry["url"].startswith(f"/files/{manifest['pack']['id']}/")
        assert "exp=" in entry["url"] and "sig=" in entry["url"]
        assert len(entry["sha256"]) == 64 and entry["size"] > 0
    assert parse_iso(manifest["valid_until"]) > parse_iso(manifest["server_time"])


def test_the_default_shows_when_nothing_is_allocated(env) -> None:
    # A2 is the odd slot in block 0, so the rotation gives it the default
    manifest = env.resolve("A", "A2", "r1")
    assert manifest["is_default"] is True
    assert manifest["content"]["piece"] == "default"
    assert manifest["brand"] is None
    assert manifest["showing"]["kind"] == "default"


def test_the_rival_wears_what_the_config_says(env) -> None:
    manifest = env.resolve("A", "A1", "r2")          # even slot, block 0 -> the rival
    assert manifest["showing"]["kind"] == "rival"
    assert manifest["content"]["piece"] == "rival2"
    assert manifest["brand"] == {"colour": "#F28C28", "emblem": "ring"}
    small = env.resolve("A", "A3", "r3")             # an S slot takes the small rival piece
    assert small["content"]["piece"] == "rivalsmall"
    assert small["brand"] == {"colour": "#7B5CD6", "emblem": "diamond"}


def test_alloc_key_changes_on_a_win_a_push_a_pause_and_a_block_end(env) -> None:
    before = env.key("A", "A1", "r1")
    env.brand()
    content = env.upload("content1_v1.dcpack")

    allocation = env.allocate("A", "A1", "r1", content["content_id"], minutes=1)
    on_win = env.key("A", "A1", "r1")
    assert on_win != before
    assert on_win == allocation["alloc_key"]

    env.upload("content1_v2.dcpack", content_id=content["content_id"])
    on_push = env.key("A", "A1", "r1")
    assert on_push not in (before, on_win)
    assert env.resolve("A", "A1", "r1")["content"]["version"] == "v2"

    env.ok(env.client.post("/campaign/pause", json={"paused": True}))
    on_pause = env.key("A", "A1", "r1")
    assert on_pause not in (before, on_win, on_push)
    assert env.resolve("A", "A1", "r1")["is_default"] is True

    env.ok(env.client.post("/campaign/pause", json={"paused": False}))
    assert env.key("A", "A1", "r1") == on_push                 # unpausing puts it back

    env.clock.advance(61)                                      # the one-minute block ends
    after = env.key("A", "A1", "r1")
    assert after not in (on_win, on_push, on_pause)
    assert env.resolve("A", "A1", "r1")["showing"]["kind"] == "rival"   # the next winner


def test_alloc_key_changes_when_the_brand_changes(env) -> None:
    env.brand("#E23D3D", "star")
    content = env.upload("content4_v1.dcpack")
    env.allocate("A", "A3", "r1", content["content_id"])
    first = env.key("A", "A3", "r1")
    env.brand("#2F6FEB", "chevron")
    assert env.key("A", "A3", "r1") != first
    assert env.resolve("A", "A3", "r1")["brand"] == {"colour": "#2F6FEB", "emblem": "chevron"}


def test_keys_are_stable_while_nothing_changes(env) -> None:
    first = env.changes("A", "r1")["slots"]
    env.clock.advance(5)
    assert env.changes("A", "r1")["slots"] == first
    env.clock.advance(5)
    assert env.changes("A", "r1")["slots"] == first


def test_regions_do_not_affect_each_other(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])
    assert env.resolve("A", "A1", "r1")["showing"]["kind"] == "visitor"
    assert env.resolve("A", "A1", "r2")["showing"]["kind"] == "rival"
    assert env.resolve("A", "A1", "r3")["showing"]["kind"] == "rival"


def test_unknown_games_slots_and_regions_are_turned_away(env) -> None:
    assert env.resolve("Z", "A1", "r1", expect=404)["error"] == "There is no game Z."
    assert env.resolve("A", "B1", "r1", expect=404)["error"] == "Game A has no slot B1."
    assert env.resolve("A", "A1", "r9", expect=404)["error"] == "There is no region r9."
    assert env.ok(env.client.get("/changes", params={"game": "A", "region": "r9"}),
                  404)["error"] == "There is no region r9."


def test_a_slot_with_no_pack_at_all_is_honest(make_env, tmp_path) -> None:
    """No rival or default pack registered: /changes still answers, /resolve says why."""
    empty = tmp_path / "no_packs"
    empty.mkdir()
    env = make_env(files=empty)
    assert env.changes("A", "r1")["slots"] == {"A1": "no-content", "A2": "no-content",
                                               "A3": "no-content"}
    error = env.resolve("A", "A1", "r1", expect=503)["error"]
    assert "No default pack is registered" in error


def test_status_live_lists_every_game_slot_and_region(env) -> None:
    rows = env.ok(env.client.get("/status/live"))["showing"]
    assert len(rows) == len(env.config.slots) * len(env.config.regions)
    assert {r["kind"] for r in rows} <= {"rival", "default", "visitor"}
