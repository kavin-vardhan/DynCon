"""The portal's side: the games list, the slot map, the report, the preview window, and
the curated "Your computer" list."""
from __future__ import annotations

from dcserver.clock import iso


def test_the_games_list(env) -> None:
    games = env.ok(env.client.get("/games"))["games"]
    assert [g["id"] for g in games] == ["A", "B"]
    first = games[0]
    assert first["label"] == "Game A"
    assert first["slot_count"] == 3
    assert first["live_at_booth"] is True                     # Game A is the booth's game
    assert games[1]["live_at_booth"] is False
    assert first["players_online"] > 0
    assert first["map_image_url"] == "/games/A/map"


def test_players_online_is_simulated_but_not_random(env) -> None:
    first = env.ok(env.client.get("/games"))["games"][0]["players_online"]
    assert env.ok(env.client.get("/games"))["games"][0]["players_online"] == first
    env.clock.advance(120)                                    # two real minutes = 2 demo hours
    later = env.ok(env.client.get("/games"))["games"][0]["players_online"]
    assert later != first
    base = env.config.game("A")["players_online"]
    assert abs(later - base) < base * 0.2


def test_the_slot_map_card(env) -> None:
    env.brand()
    content = env.upload("content3_v1.dcpack")                # 17 m tall: A2 only
    card = env.ok(env.client.get("/games/A"))
    assert [s["id"] for s in card["slots"]] == ["A1", "A2", "A3"]
    a1 = card["slots"][0]
    assert a1["size_class"] == "L"
    assert a1["limits"] == {"x": 14.0, "y": 14.0, "z": 9.0}
    assert a1["limits_words"] == "up to 14 x 14 m on the ground and 9 m tall"
    assert a1["px"] == {"x": 0.31, "y": 0.44}
    assert a1["thumb_url"] == "/games/A/slots/A1/thumb"
    assert a1["fits"][content["content_id"]]["ok"] is False
    assert a1["fits"][content["content_id"]]["reason"].startswith("Too tall")
    assert card["slots"][1]["fits"][content["content_id"]]["ok"] is True
    assert set(a1["lots"]) == {"r1", "r2", "r3"}
    assert a1["lots"]["r1"]["opening"] == 300
    assert a1["showing"]["r1"]["kind"] in ("rival", "default", "visitor")
    assert card["wallet"] == {"available": 2000, "held": 0, "charged": 0}
    assert env.ok(env.client.get("/games/Z"), 404)["error"] == "There is no game Z."


def test_footfall_is_simulated_plus_live(env) -> None:
    card = env.ok(env.client.get("/games/A"))
    row = card["slots"][0]["footfall"]["r1"]
    assert row["per_demo_hour"] == 1200
    assert row["label"] == "simulated + live"
    assert row["simulated"] == 0 and row["live"] == 0            # nothing has happened yet

    env.clock.advance(60)                                       # one real minute = 1 demo hour
    env.ok(env.client.post("/telemetry", json=[
        {"game": "A", "region": "r1", "slot": "A1", "type": "view", "value": 1},
        {"game": "A", "region": "r1", "slot": "A1", "type": "view", "value": 1},
        {"game": "A", "region": "r2", "slot": "A1", "type": "view", "value": 1}]))
    after = env.ok(env.client.get("/games/A"))["slots"][0]["footfall"]
    assert after["r1"] == {"per_demo_hour": 1200, "simulated": 1200, "live": 2, "total": 1202,
                           "label": "simulated + live"}
    assert after["r2"]["live"] == 1


def test_the_map_and_the_thumbnails_are_drawn_placeholders(env) -> None:
    response = env.client.get("/games/A/map")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    body = response.text
    assert body.startswith("<svg") and body.endswith("</svg>")
    for slot in ("A1", "A2", "A3"):
        assert f">{slot}</text>" in body
    assert "B1" not in body                                     # only this game's slots
    thumb = env.client.get("/games/A/slots/A1/thumb")
    assert thumb.status_code == 200
    assert "class L" in thumb.text
    assert env.client.get("/games/A/slots/B1/thumb").status_code == 404
    assert env.client.get("/games/Z/map").status_code == 404


def test_your_computer_is_the_curated_list(env) -> None:
    listing = env.ok(env.client.get("/demo-files"))
    assert listing["purpose"] == "upload"
    names = [row["name"] for row in listing["files"]]
    assert names == ["content1_v1.dcpack", "content2_v1.dcpack", "content3_v1.dcpack",
                     "content4_v1.dcpack", "content2_v1_engine53.dcpack"]
    assert [row["version"] for row in listing["files"][:4]] == ["v1"] * 4
    assert listing["files"][-1]["note"] == "built for engine 5.3"
    assert all(row["bytes"] > 0 for row in listing["files"])
    # the rated-18+ pack and the game's own content are never offered
    assert not any("rated18" in n for n in names)
    assert not any(n.startswith(("rival", "default")) for n in names)


def test_the_update_list_is_the_version_two_files(env) -> None:
    listing = env.ok(env.client.get("/demo-files", params={"purpose": "update"}))
    assert listing["purpose"] == "update"
    assert [row["name"] for row in listing["files"]] == [
        "content1_v2.dcpack", "content2_v2.dcpack", "content3_v2.dcpack", "content4_v2.dcpack"]
    assert all(row["version"] == "v2" for row in listing["files"])
    assert all(row["note"] is None for row in listing["files"])


def test_a_real_pack_wins_over_a_fake_one_for_the_same_piece(make_env, demo_files,
                                                             real_demo_files, tmp_path) -> None:
    if real_demo_files is None:
        import pytest
        pytest.skip("unreal/_packs is not on this machine")
    import shutil
    mixed = tmp_path / "mixed"
    shutil.copytree(demo_files, mixed)
    shutil.copy(real_demo_files / "content1_v1.dcpack", mixed / "content1_v1.real.dcpack")
    env = make_env(files=mixed)
    listing = env.ok(env.client.get("/demo-files"))["files"]
    content1 = next(row for row in listing if row["piece"] == "content1")
    assert content1["name"] == "content1_v1.real.dcpack"
    assert content1["real"] is True
    assert next(row for row in listing if row["piece"] == "content2")["real"] is False


def test_the_demo_file_bytes_are_downloadable(env) -> None:
    listing = env.ok(env.client.get("/demo-files"))["files"]
    for row in listing:
        response = env.client.get(f"/demo-files/{row['name']}")
        assert response.status_code == 200
        assert len(response.content) == row["bytes"]


def test_the_preview_window_region(env) -> None:
    """The region half of the preview answer. Its focus half, the region labels and the
    behaviour the window itself depends on are `tests/test_preview.py`."""
    answer = env.ok(env.client.get("/preview/region"))
    assert {k: answer[k] for k in ("region", "label", "neutral_label", "main_region")} == {
        "region": "r2", "label": "India", "neutral_label": "Mock region 2",
        "main_region": "r1"}
    changed = env.ok(env.client.post("/preview/region", json={"region": "r3"}))
    assert changed["region"] == "r3" and changed["label"] == "Europe"
    assert env.ok(env.client.get("/preview/region"))["region"] == "r3"
    assert env.ok(env.client.post("/preview/region", json={"region": "r9"}), 404)["error"] == \
        "There is no region r9."
    env.ok(env.client.post("/admin/reset"))
    assert env.ok(env.client.get("/preview/region"))["region"] == "r2"   # back to the default


def test_an_empty_report_reads_as_empty(env) -> None:
    report = env.ok(env.client.get("/report"))
    assert report["brand"] is None
    assert report["totals"] == {"views": 0, "views_simulated": 0, "views_live": 0,
                                "visits": 0, "dwell_s": 0.0, "interactions": 0,
                                "charged": 0, "blocks": 0, "cost_per_view": None,
                                "cost_per_1000_views": None}
    assert [row["region"] for row in report["regions"]] == ["r1", "r2", "r3"]
    assert all(row["views"] == 0 and row["charged"] == 0 for row in report["regions"])


def test_the_report_counts_what_the_game_reported(env) -> None:
    env.brand("#2F6FEB", "chevron")
    content = env.upload("content1_v1.dcpack")
    env.bid("A1", content["content_id"], {"r1": 325})
    env.close_auction("lot_A1_r1_1")
    key = env.key("A", "A1", "r1")
    now = iso(env.clock.now())
    events = [{"game": "A", "region": "r1", "slot": "A1", "alloc_key": key, "ts": now,
               "type": kind, "value": value}
              for kind, value in (("mount", 1), ("view", 1), ("view", 1), ("visit", 1),
                                  ("dwell", 12.5), ("interaction", 3))]
    assert env.ok(env.client.post("/telemetry", json=events))["accepted"] == 6

    report = env.ok(env.client.get("/report"))
    japan = next(row for row in report["regions"] if row["region"] == "r1")
    assert japan["label"] == "Japan" and japan["neutral_label"] == "Mock region 1"
    assert japan["slots"] == ["A1"] and japan["blocks"] == 1
    # views are simulated + live: A1 is 1,200 per demo hour and a block is 3 demo hours
    assert japan["views_simulated"] == 3600
    assert japan["views_live"] == 2
    assert japan["views"] == 3602
    assert japan["views_label"] == "simulated + live"
    assert (japan["visits"], japan["interactions"]) == (1, 3)      # live only, no model
    assert japan["dwell_s"] == 12.5
    assert japan["charged"] == 325
    assert japan["cost_per_view"] == round(325 / 3602, 4)
    assert japan["cost_per_1000_views"] == round(325 / 3.602, 2)
    assert 0 < japan["time_left_s"] <= env.config.block_seconds
    assert japan["showing"]["piece"] == "content1"
    assert japan["paused"] is False
    other = next(row for row in report["regions"] if row["region"] == "r2")
    assert other["views"] == 0 and other["charged"] == 0 and other["time_left_s"] == 0.0
    assert report["totals"]["views"] == 3602 and report["totals"]["charged"] == 325
    assert report["totals"]["views_simulated"] == 3600
    assert report["wallet"] == {"available": 1675, "held": 0, "charged": 325}


def test_the_report_and_the_slot_card_agree_on_a_block_just_bought(env) -> None:
    """The portal quotes credits per 1,000 views on the slot card before the bid; the
    report has to say the same thing afterwards, or the demo contradicts itself."""
    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.bid("A1", content["content_id"], {"r1": 325})
    env.close_auction("lot_A1_r1_1")
    quoted = env.lot("lot_A1_r1_1")["credits_per_1000_views"]
    japan = next(r for r in env.ok(env.client.get("/report"))["regions"]
                 if r["region"] == "r1")
    assert japan["views_live"] == 0                       # nothing counted yet
    assert japan["views"] == japan["views_simulated"] == 3600
    assert japan["cost_per_1000_views"] == quoted == round(325 / 3.6, 2)

    # a real counted view can only make the campaign look better, never worse
    env.ok(env.client.post("/telemetry", json=[
        {"game": "A", "region": "r1", "slot": "A1", "type": "view", "value": 1,
         "ts": iso(env.clock.now())}]))
    after = next(r for r in env.ok(env.client.get("/report"))["regions"]
                 if r["region"] == "r1")
    assert after["views_live"] == 1
    assert after["cost_per_1000_views"] < quoted


def test_a_block_booked_for_later_has_not_been_seen_yet(env) -> None:
    """A queued block counts as booked, but its views only start when it starts."""
    env.brand()
    content = env.upload("content4_v1.dcpack")
    env.bid("A3", content["content_id"], {"r1": 100})     # A3 is 300 views per demo hour
    env.close_auction("lot_A3_r1_1")
    env.bid("A3", content["content_id"], {"r1": 100})     # queued behind the first
    env.close_auction("lot_A3_r1_2")
    row = next(r for r in env.ok(env.client.get("/report"))["regions"] if r["region"] == "r1")
    assert (row["blocks"], row["blocks_started"]) == (2, 1)
    assert row["views_simulated"] == 900                  # one block of 300 x 3 demo hours
    env.clock.advance(env.config.block_seconds + 1)       # the second block starts
    later = next(r for r in env.ok(env.client.get("/report"))["regions"] if r["region"] == "r1")
    assert later["blocks_started"] == 2
    assert later["views_simulated"] == 1800


def test_the_report_shows_a_paused_campaign_and_a_booked_next_block(env) -> None:
    env.brand()
    content = env.upload("content4_v1.dcpack")
    env.bid("A3", content["content_id"], {"r1": 100})
    env.close_auction("lot_A3_r1_1")
    env.bid("A3", content["content_id"], {"r1": 100})
    env.close_auction("lot_A3_r1_2")
    report = env.ok(env.client.get("/report"))
    row = next(r for r in report["regions"] if r["region"] == "r1")
    assert row["blocks"] == 2
    assert row["next_block_at"] is not None
    assert row["paused"] is False

    env.ok(env.client.post("/campaign/pause", json={"paused": True}))
    paused = env.ok(env.client.get("/report"))
    assert paused["paused"] is True
    assert next(r for r in paused["regions"] if r["region"] == "r1")["paused"] is True
    assert env.resolve("A", "A3", "r1")["is_default"] is True


def test_telemetry_from_another_block_is_not_counted(env) -> None:
    """A campaign's numbers are the events inside its own blocks."""
    env.brand()
    content = env.upload("content4_v1.dcpack")
    env.bid("A3", content["content_id"], {"r1": 100})
    env.close_auction("lot_A3_r1_1")
    stale = iso(env.clock.now())
    env.clock.advance(env.config.block_seconds + 300)            # long after the block ended
    env.ok(env.client.post("/telemetry", json=[
        {"game": "A", "region": "r1", "slot": "A3", "type": "view", "value": 1,
         "ts": iso(env.clock.now())}]))
    env.ok(env.client.post("/telemetry", json=[
        {"game": "A", "region": "r1", "slot": "A3", "type": "view", "value": 1, "ts": stale}]))
    row = next(r for r in env.ok(env.client.get("/report"))["regions"] if r["region"] == "r1")
    assert row["views_live"] == 1                                # only the one in the block
    assert row["views"] == row["views_simulated"] + 1
