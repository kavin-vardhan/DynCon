"""The two staff tricks: serve a corrupt pack, and drop a download halfway."""
from __future__ import annotations

import hashlib

import pytest


def pack_files(env, slot: str = "A1", region: str = "r1") -> list[dict]:
    return env.resolve("A", slot, region)["pack"]["files"]


def test_corrupt_flips_exactly_one_byte_once(env) -> None:
    files = pack_files(env)
    entry = max(files, key=lambda f: f["size"])
    clean = env.fetch(entry).content

    assert env.ok(env.client.post("/admin/sabotage", json={"mode": "corrupt"}))["armed"] == "corrupt"
    response = env.fetch(entry)
    assert response.status_code == 200
    assert response.headers.get("x-dc-sabotage") == "corrupt"
    bad = response.content
    assert len(bad) == len(clean)
    assert hashlib.sha256(bad).hexdigest() != entry["sha256"]
    differences = [i for i, (a, b) in enumerate(zip(clean, bad)) if a != b]
    assert len(differences) == 1                       # one byte, nothing else

    # it is spent: the retry the client makes is clean
    again = env.fetch(entry)
    assert again.content == clean
    assert hashlib.sha256(again.content).hexdigest() == entry["sha256"]
    assert env.ok(env.client.get("/admin/health"))["sabotage_armed"] is None


def test_corrupt_only_touches_the_next_download(env) -> None:
    files = pack_files(env)
    env.ok(env.client.post("/admin/sabotage", json={"mode": "corrupt"}))
    first = env.fetch(files[0])
    second = env.fetch(files[1])
    assert first.headers.get("x-dc-sabotage") == "corrupt"
    assert second.headers.get("x-dc-sabotage") is None
    assert hashlib.sha256(second.content).hexdigest() == files[1]["sha256"]


def test_freeze_drops_the_connection_halfway_and_a_range_finishes_the_job(env) -> None:
    entry = max(pack_files(env), key=lambda f: f["size"])
    clean = env.fetch(entry).content
    env.ok(env.client.post("/admin/sabotage", json={"mode": "freeze"}))
    try:
        frozen = env.fetch(entry)
        body = frozen.content
    except Exception:                       # a real client sees the connection drop
        body = b""
    assert len(body) < entry["size"]
    have = len(body)
    rest = env.fetch(entry, headers={"Range": f"bytes={have}-"})
    assert rest.status_code == 206
    joined = body + rest.content
    assert joined == clean
    assert hashlib.sha256(joined).hexdigest() == entry["sha256"]


def test_sabotage_can_be_disarmed(env) -> None:
    env.ok(env.client.post("/admin/sabotage", json={"mode": "corrupt"}))
    assert env.ok(env.client.post("/admin/sabotage", json={"mode": "none"}))["armed"] is None
    entry = max(pack_files(env), key=lambda f: f["size"])
    assert hashlib.sha256(env.fetch(entry).content).hexdigest() == entry["sha256"]


def test_an_unknown_sabotage_mode_is_refused(env) -> None:
    response = env.client.post("/admin/sabotage", json={"mode": "setfire"})
    assert response.status_code == 400
    assert response.json()["error"] == "Sabotage mode must be one of corrupt, freeze, none."


def test_a_reset_disarms_sabotage(env) -> None:
    env.ok(env.client.post("/admin/sabotage", json={"mode": "corrupt"}))
    env.ok(env.client.post("/admin/reset"))
    assert env.ok(env.client.get("/admin/health"))["sabotage_armed"] is None


@pytest.mark.parametrize("key", ["corrupt", "freeze"])
def test_the_admin_key_is_enforced_when_it_is_set(make_env, key) -> None:
    env = make_env(server={"admin_key": "booth-staff-only"})
    assert env.client.post("/admin/sabotage", json={"mode": key}).status_code == 403
    response = env.client.post("/admin/sabotage", json={"mode": key},
                               headers={"X-DC-Admin-Key": "booth-staff-only"})
    assert response.status_code == 200
    assert env.client.get("/admin/health").status_code == 200        # health stays open
