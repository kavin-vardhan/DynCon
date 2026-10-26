"""The fake game client against a real socket — the stage-1 exit test in miniature.

These run a real uvicorn in a thread, so the pacing, the Range resume and the dropped
connection are the real thing rather than a transport shim.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fake_client import FakeClient, mount_line


def client_for(url: str, cache: Path, game: str = "A", region: str = "r1",
               slots: str = "") -> FakeClient:
    return FakeClient(url, game, region, cache=cache,
                      slots=[s for s in slots.split(",") if s], verbose=True)


def test_the_client_mounts_what_was_allocated(live_server, tmp_path) -> None:
    env, url = live_server()
    env.brand("#E23D3D", "star")
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"], minutes=30)

    client = client_for(url, tmp_path / "cache", slots="A1")
    stats = client.run_once()
    assert stats.mounts == 1 and stats.fallbacks == 0
    assert "MOUNT A1 content1 v1 brand #E23D3D star" in stats.lines
    assert client.mounted["A1"]["alloc_key"] == env.key("A", "A1", "r1")
    # every file of the pack is in the cache and was verified
    cached = sorted(p.name for p in (tmp_path / "cache" / content["pack"]["id"]).iterdir())
    assert [n for n in cached if n.endswith((".pak", ".utoc", ".ucas"))] == \
        sorted(f["name"] for f in content["pack"]["files"])
    assert env.ok(env.client.get("/admin/health"))["counts"]["telemetry"] == 5


def test_the_client_mounts_the_rotation_and_names_the_rival(live_server, tmp_path) -> None:
    env, url = live_server()
    stats = client_for(url, tmp_path / "cache").run_once()
    assert stats.mounts == 3 and stats.fallbacks == 0
    assert "MOUNT A1 rival1 v1 rival #1FA39A triangle" in stats.lines
    assert "MOUNT A2 default v1 no-brand" in stats.lines
    assert "MOUNT A3 rivalsmall v1 rival #1FA39A triangle" in stats.lines


def test_a_corrupt_pack_falls_back_and_then_mounts_clean(live_server, tmp_path) -> None:
    env, url = live_server()
    env.brand("#2F6FEB", "chevron")
    content = env.upload("content4_v1.dcpack")
    env.allocate("A", "A3", "r1", content["content_id"], minutes=30)
    env.ok(env.client.post("/admin/sabotage", json={"mode": "corrupt"}))

    stats = client_for(url, tmp_path / "cache", slots="A3").run_once()
    fallbacks = [ln for ln in stats.lines if ln.startswith("FALLBACK")]
    assert len(fallbacks) == 1
    assert fallbacks[0].startswith("FALLBACK A3 default (sha256 mismatch on pakchunk")
    assert "MOUNT A3 content4 v1 brand #2F6FEB chevron" in stats.lines
    assert stats.mounts == 1


def test_a_frozen_download_is_resumed_with_a_range(live_server, tmp_path) -> None:
    env, url = live_server(sabotage={"freeze_seconds": 0.5})
    env.brand()
    content = env.upload("content2_v1.dcpack")
    env.allocate("B", "B1", "r1", content["content_id"], minutes=30)
    env.ok(env.client.post("/admin/sabotage", json={"mode": "freeze"}))

    client = client_for(url, tmp_path / "cache", game="B", region="r1", slots="B1")
    stats = client.run_once()
    assert stats.mounts == 1 and stats.fallbacks == 0      # resumed, never fell back
    assert stats.resumes >= 1
    assert "MOUNT B1 content2 v1 brand #E23D3D star" in stats.lines


def test_the_second_poll_does_nothing_when_nothing_changed(live_server, tmp_path) -> None:
    env, url = live_server()
    client = client_for(url, tmp_path / "cache")
    client.start()
    assert len(client.poll_once()) == 3
    assert client.poll_once() == {}                        # keys unchanged -> no work
    assert client.stats.mounts == 3


def test_a_reset_purges_the_visitor_pack_from_the_cache(live_server, tmp_path) -> None:
    env, url = live_server()
    env.brand()
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"], minutes=30)
    cache = tmp_path / "cache"
    client = client_for(url, cache, slots="A1")
    client.start()
    client.poll_once()
    pack_dir = cache / content["pack"]["id"]
    assert pack_dir.is_dir()

    env.ok(env.client.post("/admin/reset"))
    client.poll_once()
    assert not pack_dir.exists()                           # the next visitor downloads afresh
    assert "A1" in client.known                            # and A1 went back to the rotation
    assert client.mounted["A1"]["kind"] in ("rival", "default")


def test_a_cached_pack_is_not_downloaded_twice(live_server, tmp_path) -> None:
    env, url = live_server()
    env.brand()
    content = env.upload("content4_v1.dcpack")
    env.allocate("A", "A3", "r1", content["content_id"], minutes=30)
    cache = tmp_path / "cache"
    first = client_for(url, cache, slots="A3").run_once()
    assert first.downloaded_bytes > 0 and first.cached_files == 0
    second = client_for(url, cache, slots="A3").run_once()
    assert second.cached_files == 3 and second.downloaded_bytes == 0
    assert second.mounts == 1


def test_the_cache_evicts_a_pack_that_is_no_longer_mounted(live_server, tmp_path) -> None:
    """What is mounted now is never evicted; what the slot has moved on from is."""
    env, url = live_server(client_cache_packs=1)
    env.brand()
    first = env.upload("content4_v1.dcpack")
    second = env.upload("content4_v2.dcpack")
    cache = tmp_path / "cache"

    env.allocate("A", "A3", "r1", first["content_id"], minutes=30)
    client = client_for(url, cache, slots="A3")
    client.start()
    client.poll_once()
    assert (cache / first["pack"]["id"]).is_dir()

    env.allocate("A", "A3", "r1", second["content_id"], minutes=30)
    client.poll_once()
    assert (cache / second["pack"]["id"]).is_dir()          # the live one stays
    assert not (cache / first["pack"]["id"]).exists()       # the old one goes


def test_a_manifest_signed_by_the_wrong_key_is_refused(live_server, tmp_path) -> None:
    from dcserver.signing import KeyStore

    env, url = live_server()
    other = KeyStore(tmp_path / "other_keys").ensure()
    client = client_for(url, tmp_path / "cache", slots="A1")
    client.start()
    client.public_pem = other.public_pem                   # a real key, but not the server's
    client.handle_slot("A1", "whatever")
    assert client.stats.mounts == 0
    assert any("signature did not verify" in ln for ln in client.stats.lines)


def test_mount_line_wording(env) -> None:
    env.brand("#8CC63F", "hexagon")
    content = env.upload("content1_v1.dcpack")
    env.allocate("A", "A1", "r1", content["content_id"])
    assert mount_line("A1", env.resolve("A", "A1", "r1")) == \
        "MOUNT A1 content1 v1 brand #8CC63F hexagon"
    assert mount_line("A2", env.resolve("A", "A2", "r1")) == "MOUNT A2 default v1 no-brand"
    assert mount_line("A1", env.resolve("A", "A1", "r2")) == \
        "MOUNT A1 rival2 v1 rival #F28C28 ring"


@pytest.mark.parametrize("game,region", [("A", "r1"), ("B", "r2")])
def test_the_client_can_poll_for_a_while_without_doing_harm(live_server, tmp_path,
                                                            game, region) -> None:
    env, url = live_server()
    client = client_for(url, tmp_path / f"cache_{game}{region}", game=game, region=region)
    stats = client.run(1.0)
    assert stats.fallbacks == 0
    assert stats.mounts == len(env.config.slots_of(game))
