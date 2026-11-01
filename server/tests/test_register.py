"""`POST /games/register` — the developer's slot-map tool arriving, and what it changes.

The pictures here are tiny PNGs written by hand (a valid header plus one IDAT), because what
is being tested is the registration, not an image library: the server never decodes a
registered image, it only checks that it *is* a PNG, reads its size out of the IHDR chunk,
and serves the bytes back.
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
REAL_MAPS = SERVER_DIR / "config" / "maps"


def png(width: int, height: int, grey: int = 128) -> bytes:
    """A real, valid PNG of one solid colour — small enough to put in a test."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)     # 8-bit RGB
    row = b"\x00" + bytes([grey, grey, grey]) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(row * height, 6)) + chunk(b"IEND", b""))


def payload(game: str = "A", slots=(("A1", "L", 0.5, 0.5), ("A2", "T", 0.75, 0.25),
                                    ("A3", "S", 0.2, 0.8))) -> dict:
    return {
        "schema_version": 1,
        "game": game,
        "map": f"/Game/Maps/Game{game}",
        "captured_utc": "2026-11-01T12:00:00Z",
        "engine_version": "5.7.4-0+++UE5",
        "tool": "DynamicContentsEditor.DCSlotMapTool",
        "world": {"playable_area_from": "3 actor(s) tagged DCPlayableArea",
                  "width_m": 200.0, "height_m": 128.0},
        "slots": [
            {"id": sid, "size_class": cls, "px": {"x": x, "y": y},
             "limits_m": {"x": 14.0, "y": 14.0, "z": 9.0},
             "rating_rule": "all", "prefetch_radius_m": 60.0,
             "world_m": {"x": 0.0, "y": 12.0, "z": 0.82}, "facing_deg": -90.0,
             "thumb": {"file": f"{game}_{sid}.png", "width": 32, "height": 18,
                       "fov_deg": 70.0, "eye_height_m": 1.7}}
            for (sid, cls, x, y) in slots
        ],
    }


def post(env, body: dict, *, map_png: bytes | None = None,
         thumbs: dict[str, bytes] | None = None, expect: int = 200) -> dict:
    game = body.get("game", "A")
    if thumbs is None:
        thumbs = {f"{game}_{s['id']}.png": png(32, 18) for s in body.get("slots", [])}
    files = [("map_image", ("map.png", map_png if map_png is not None else png(64, 40),
                            "image/png"))]
    files += [("thumbs", (name, blob, "image/png")) for name, blob in thumbs.items()]
    return env.ok(env.client.post("/games/register",
                                  data={"data": json.dumps(body)}, files=files), expect)


# ---------------------------------------------------------------- the happy path

def test_registering_a_game_stores_the_map_and_every_thumbnail(env) -> None:
    result = post(env, payload())
    assert result["ok"] is True
    assert result["game"] == "A"
    assert result["image"] == {"file": "A.png", "width": 64, "height": 40,
                               "bytes": len(png(64, 40)), "url": "/games/A/map"}
    assert [s["id"] for s in result["slots"]] == ["A1", "A2", "A3"]
    assert result["warnings"] == []

    # on disk, next to demo.json, so a clean checkout serves it and a reset cannot wipe it
    assert (env.maps_dir / "A.png").is_file()
    assert (env.maps_dir / "A.json").is_file()
    for slot in ("A1", "A2", "A3"):
        assert (env.maps_dir / f"A_{slot}.png").is_file()
    record = json.loads((env.maps_dir / "A.json").read_text(encoding="utf-8"))
    assert record["slot_order"] == ["A1", "A2", "A3"]
    assert record["slots"]["A2"]["px"] == {"x": 0.75, "y": 0.25}
    assert record["slots"]["A2"]["rating_rule"] == "all"
    assert record["source"]["map"] == "/Game/Maps/GameA"


def test_the_registered_map_and_thumbnails_are_what_gets_served(env) -> None:
    map_png = png(128, 72, grey=64)
    thumbs = {f"A_{s}.png": png(32, 18, grey=i * 20) for i, s in enumerate(("A1", "A2", "A3"))}
    post(env, payload(), map_png=map_png, thumbs=thumbs)

    got = env.client.get("/games/A/map")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert got.content == map_png

    for slot, blob in (("A1", thumbs["A_A1.png"]), ("A3", thumbs["A_A3.png"])):
        reply = env.client.get(f"/games/A/slots/{slot}/thumb")
        assert reply.status_code == 200
        assert reply.headers["content-type"] == "image/png"
        assert reply.content == blob

    # Game B was never registered, so it keeps the drawn placeholders
    assert env.client.get("/games/B/map").headers["content-type"].startswith("image/svg")
    assert env.client.get("/games/B/slots/B1/thumb").headers["content-type"] \
        .startswith("image/svg")


def test_the_registered_pin_positions_replace_the_ones_in_the_config(env) -> None:
    config_px = env.ok(env.client.get("/games/A"))["slots"][0]["px"]
    assert config_px == {"x": 0.31, "y": 0.44}                 # demo.json's hand-guessed one

    post(env, payload(slots=(("A1", "L", 0.123, 0.456), ("A2", "T", 0.6, 0.3),
                             ("A3", "S", 0.9, 0.1))))
    card = env.ok(env.client.get("/games/A"))
    assert card["registered"] is True
    assert card["slots"][0]["px"] == {"x": 0.123, "y": 0.456}
    assert card["slots"][0]["rating_rule"] == "all"
    assert card["slots"][0]["prefetch_radius_m"] == 60.0
    assert card["slots"][0]["registered"] is True

    # and everywhere else a pin position is published
    public = env.ok(env.client.get("/config/public"))
    assert public["games"]["A"]["slots"][0]["px"] == {"x": 0.123, "y": 0.456}
    assert public["games"]["A"]["registered"] is True
    assert public["games"]["B"]["registered"] is False
    assert env.ok(env.client.get("/games"))["games"][0]["registered"] is True
    assert env.ok(env.client.get("/admin/health"))["registered_games"] == {"A": True,
                                                                          "B": False}


def test_registering_again_replaces_the_last_one(env) -> None:
    post(env, payload())
    first = json.loads((env.maps_dir / "A.json").read_text(encoding="utf-8"))
    env.clock.advance(60)
    post(env, payload(slots=(("A1", "L", 0.11, 0.22), ("A2", "T", 0.6, 0.3),
                             ("A3", "S", 0.9, 0.1))),
         map_png=png(32, 20))
    second = json.loads((env.maps_dir / "A.json").read_text(encoding="utf-8"))
    assert second["registered_utc"] != first["registered_utc"]
    assert second["image_px"] == {"w": 32, "h": 20}
    assert second["slots"]["A1"]["px"] == {"x": 0.11, "y": 0.22}
    assert not list(env.maps_dir.glob("*.part"))               # nothing half-written


def test_a_reset_leaves_the_registration_alone(env) -> None:
    """A registration is the developer's, not the visitor's: `/admin/reset` runs between
    visitors all evening and must not take the game's own map down with it."""
    post(env, payload())
    env.ok(env.client.post("/admin/reset"))
    assert env.client.get("/games/A/map").headers["content-type"] == "image/png"
    assert env.ok(env.client.get("/games/A"))["registered"] is True


def test_the_other_game_registers_separately(env) -> None:
    post(env, payload(), map_png=png(64, 40, grey=10))
    post(env, payload("B", slots=(("B1", "L", 0.3, 0.6), ("B2", "S", 0.64, 0.35))),
         map_png=png(96, 54, grey=200))
    assert env.ok(env.client.get("/admin/health"))["registered_games"] == {"A": True,
                                                                          "B": True}
    assert env.ok(env.client.get("/games/B"))["slots"][1]["px"] == {"x": 0.64, "y": 0.35}
    # two games, two pictures: one registration never stands in for the other
    assert env.client.get("/games/A/map").content == png(64, 40, grey=10)
    assert env.client.get("/games/B/map").content == png(96, 54, grey=200)


# ---------------------------------------------------------------- what gets refused

def test_a_slot_the_platform_does_not_know_is_refused(env) -> None:
    body = env.ok(env.client.post("/games/register", data={"data": json.dumps(
        payload(slots=(("A1", "L", 0.5, 0.5), ("A9", "L", 0.2, 0.2))))},
        files=[("map_image", ("map.png", png(64, 40), "image/png")),
               ("thumbs", ("A_A1.png", png(8, 8), "image/png")),
               ("thumbs", ("A_A9.png", png(8, 8), "image/png"))]), 400)
    assert "no slot A9" in body["error"]
    assert not (env.maps_dir / "A.json").exists()              # nothing was stored


def test_a_pin_outside_the_image_is_refused(env) -> None:
    body = post(env, payload(slots=(("A1", "L", 1.4, 0.5),)), expect=400)
    assert "outside it" in body["error"]


def test_a_slot_with_no_thumbnail_is_refused(env) -> None:
    body = post(env, payload(), thumbs={"A_A1.png": png(8, 8)}, expect=400)
    assert "A_A2.png" in body["error"]


def test_something_that_is_not_a_png_is_refused(env) -> None:
    body = post(env, payload(), map_png=b"GIF89a this is not a png", expect=400)
    assert "not a PNG" in body["error"]


def test_an_unknown_game_is_a_404(env) -> None:
    body = post(env, payload("Z", slots=(("A1", "L", 0.5, 0.5),)), expect=404)
    assert "no game Z" in body["error"]


def test_broken_json_says_so(env) -> None:
    body = env.ok(env.client.post(
        "/games/register", data={"data": "{not json"},
        files=[("map_image", ("map.png", png(8, 8), "image/png"))]), 400)
    assert "would not parse" in body["error"]


def test_a_registration_with_no_slots_is_refused(env) -> None:
    body = env.ok(env.client.post(
        "/games/register", data={"data": json.dumps({"game": "A", "slots": []})},
        files=[("map_image", ("map.png", png(8, 8), "image/png"))]), 400)
    assert "no slots" in body["error"]


def test_a_spare_thumbnail_is_a_warning_not_a_failure(env) -> None:
    thumbs = {f"A_{s}.png": png(16, 9) for s in ("A1", "A2", "A3")}
    thumbs["A_A7.png"] = png(16, 9)
    result = post(env, payload(), thumbs=thumbs)
    assert result["ok"] is True
    assert any("belong to no slot" in w for w in result["warnings"])


def test_registering_only_some_slots_warns_about_the_rest(env) -> None:
    result = post(env, payload(slots=(("A1", "L", 0.5, 0.5),)))
    assert result["ok"] is True
    assert any("A2, A3" in w for w in result["warnings"])
    # the ones that were not registered keep the drawn card
    assert env.client.get("/games/A/slots/A1/thumb").headers["content-type"] == "image/png"
    assert env.client.get("/games/A/slots/A2/thumb").headers["content-type"] \
        .startswith("image/svg")
    assert env.ok(env.client.get("/games/A"))["slots"][1]["px"] == {"x": 0.58, "y": 0.27}


# ---------------------------------------------------------------- the committed captures

@pytest.mark.skipif(not (REAL_MAPS / "A.json").is_file(),
                    reason="server/config/maps has no registration in it yet")
def test_the_committed_registration_is_what_a_clean_checkout_serves(make_env) -> None:
    """The real thing: the captures in `server/config/maps/` are in git, so the booth (and
    anyone who clones this repo) gets the real map and the real thumbnails with no Unreal
    anywhere in sight."""
    env = make_env(maps=REAL_MAPS)
    for game in ("A", "B"):
        card = env.ok(env.client.get(f"/games/{game}"))
        assert card["registered"] is True, f"game {game} is not registered"
        image = env.client.get(f"/games/{game}/map")
        assert image.headers["content-type"] == "image/png"
        assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
        for slot in card["slots"]:
            assert slot["registered"] is True
            assert slot["rating_rule"] == "all"
            assert 0.0 <= slot["px"]["x"] <= 1.0 and 0.0 <= slot["px"]["y"] <= 1.0
            thumb = env.client.get(f"/games/{game}/slots/{slot['id']}/thumb")
            assert thumb.headers["content-type"] == "image/png"
            assert thumb.content.startswith(b"\x89PNG\r\n\x1a\n")
