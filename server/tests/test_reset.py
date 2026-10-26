"""Reset: everything the visitor made goes, the game's own content stays."""
from __future__ import annotations


def test_reset_wipes_the_visitor_and_keeps_the_rivals(env) -> None:
    env.brand("#2EA44F", "square")
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])
    env.ok(env.client.post("/telemetry", json=[{"game": "A", "region": "r1", "slot": "A1",
                                                "type": "view", "value": 1}]))
    visitor_pack = content["pack"]["id"]
    assert env.svc.blobs.exists(visitor_pack, content["pack"]["files"][0]["name"])
    before = env.ok(env.client.get("/admin/health"))["counts"]

    result = env.ok(env.client.post("/admin/reset"))
    assert result["purge_packs"] == [visitor_pack]
    assert result["reset_generation"] == 1
    assert result["wallet"] == {"available": env.config.wallet_start, "held": 0, "charged": 0}

    after = env.ok(env.client.get("/admin/health"))
    assert after["brand"] is None
    assert env.ok(env.client.get("/content"))["content"] == []
    assert after["counts"]["allocations"] == 0
    assert after["counts"]["telemetry"] == 0
    # the five system packs (3 rivals + the small rival + default) are untouched
    assert after["counts"]["packs"] == before["packs"] - 1
    assert all(row["pack_id"] for row in after["system_packs"].values())
    assert not env.svc.blobs.exists(visitor_pack, content["pack"]["files"][0]["name"])


def test_the_slots_go_back_to_the_rotation_after_a_reset(env) -> None:
    env.brand()
    content = env.upload("content4_v1.dcpack")
    env.allocate("A", "A3", "r1", content["content_id"])
    assert env.resolve("A", "A3", "r1")["showing"]["kind"] == "visitor"
    env.ok(env.client.post("/admin/reset"))
    showing = env.resolve("A", "A3", "r1")["showing"]
    assert showing["kind"] == "rival"
    assert showing["source"].startswith("rotation:")


def test_the_purge_list_and_generation_reach_the_client_through_changes(env) -> None:
    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])
    first = env.changes("A", "r1")
    assert first["reset_generation"] == 0 and first["purge_packs"] == []
    env.ok(env.client.post("/admin/reset"))
    after = env.changes("A", "r1")
    assert after["reset_generation"] == 1
    assert after["purge_packs"] == [content["pack"]["id"]]
    assert env.ok(env.client.get("/client-config"))["reset_generation"] == 1


def test_content_ids_start_again_after_a_reset(env) -> None:
    first = env.upload("content1_v1.dcpack")
    assert first["content_id"] == "c1"
    env.ok(env.client.post("/admin/reset"))
    again = env.upload("content1_v1.dcpack")
    assert again["content_id"] == "c1"


def test_the_demo_clock_keeps_running_across_a_reset(env) -> None:
    """A reset is about the visitor, not about the booth's day."""
    before = env.ok(env.client.get("/clock"))
    env.ok(env.client.post("/admin/reset"))
    after = env.ok(env.client.get("/clock"))
    assert after["epoch"] == before["epoch"]
    assert after["block_index"] == before["block_index"]


def test_two_brands_in_a_row_replace_each_other(env) -> None:
    env.brand("#E23D3D", "star")
    second = env.brand("#1EB8D0", "ring")
    assert (second["brand"]["colour"], second["brand"]["emblem"]) == ("#1EB8D0", "ring")
    live = env.ok(env.client.get("/brand"))["brand"]
    assert (live["colour"], live["emblem"]) == ("#1EB8D0", "ring")


def test_a_brand_has_to_come_from_the_presets(env) -> None:
    response = env.client.post("/brand", json={"colour": "#123456", "emblem": "star"})
    assert response.status_code == 400
    assert response.json()["error"] == "#123456 is not one of this demo's brand colours."
    response = env.client.post("/brand", json={"colour": "#E23D3D", "emblem": "octagon"})
    assert response.status_code == 400
    assert response.json()["error"] == "octagon is not one of this demo's emblems."
