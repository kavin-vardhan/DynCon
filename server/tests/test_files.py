"""/files — signed, expiring, Range-capable, and paced in local mode."""
from __future__ import annotations

import hashlib
import time

from dcserver.clock import iso


def first_file(env, slot: str = "A1", region: str = "r1") -> tuple[dict, dict]:
    manifest = env.resolve("A", slot, region)
    return manifest, manifest["pack"]["files"][0]


def biggest_file(env, slot: str = "A1", region: str = "r1") -> tuple[dict, dict]:
    manifest = env.resolve("A", slot, region)
    return manifest, max(manifest["pack"]["files"], key=lambda f: f["size"])


def test_the_whole_file_comes_back_and_hashes(env) -> None:
    _, entry = biggest_file(env)
    response = env.fetch(entry)
    assert response.status_code == 200
    assert len(response.content) == entry["size"]
    assert hashlib.sha256(response.content).hexdigest() == entry["sha256"]
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(entry["size"])


def test_a_range_request_comes_back_as_206(env) -> None:
    _, entry = biggest_file(env)
    whole = env.fetch(entry).content
    response = env.fetch(entry, headers={"Range": "bytes=100-199"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 100-199/{entry['size']}"
    assert response.content == whole[100:200]


def test_a_download_resumes_from_where_it_stopped(env) -> None:
    """What the client does after a drop: ask for the rest and join the two halves."""
    _, entry = biggest_file(env)
    whole = env.fetch(entry).content
    half = entry["size"] // 2
    first = env.fetch(entry, headers={"Range": f"bytes=0-{half - 1}"}).content
    rest = env.fetch(entry, headers={"Range": f"bytes={half}-"})
    assert rest.status_code == 206
    assert rest.headers["content-range"] == f"bytes {half}-{entry['size'] - 1}/{entry['size']}"
    joined = first + rest.content
    assert joined == whole
    assert hashlib.sha256(joined).hexdigest() == entry["sha256"]


def test_the_last_n_bytes_form_works(env) -> None:
    _, entry = biggest_file(env)
    whole = env.fetch(entry).content
    response = env.fetch(entry, headers={"Range": "bytes=-64"})
    assert response.status_code == 206
    assert response.content == whole[-64:]


def test_a_silly_range_is_refused(env) -> None:
    _, entry = biggest_file(env)
    for header in ("bytes=99999999-", "items=0-5", "bytes=10-5"):
        response = env.fetch(entry, headers={"Range": header})
        assert response.status_code == 416, header


def test_an_unsigned_or_tampered_link_is_refused(env) -> None:
    _, entry = biggest_file(env)
    url = entry["url"]
    assert env.client.get(url.split("&sig=")[0] + "&sig=nonsense").status_code == 403
    assert env.client.get(url.split("?")[0]).status_code == 422          # no exp / sig at all
    # the signature covers the file name, so one link does not open another file
    other = env.resolve("A", "A1", "r1")["pack"]["files"][1]["name"]
    swapped = url.replace(url.split("/")[-1].split("?")[0], other)
    assert env.client.get(swapped).status_code == 403


def test_a_link_stops_working_when_it_expires(env) -> None:
    _, entry = biggest_file(env)
    assert env.fetch(entry).status_code == 200
    env.clock.advance(env.config.url_ttl_s + 1)
    response = env.fetch(entry)
    assert response.status_code == 403
    assert response.json()["expired"] is True
    assert "expired" in response.json()["error"]
    # resolving again hands out fresh links
    _, fresh = biggest_file(env)
    assert env.fetch(fresh).status_code == 200


def test_a_file_that_is_not_in_the_pack(env) -> None:
    manifest, entry = biggest_file(env)
    pack_id = manifest["pack"]["id"]
    exp = int(env.clock.now().timestamp()) + 60
    sig = env.svc.keys.url_signer.sign(pack_id, "not_a_file.ucas", exp)
    response = env.client.get(f"/files/{pack_id}/not_a_file.ucas?exp={exp}&sig={sig}")
    assert response.status_code == 404
    assert response.json()["error"] == f"Pack {pack_id} has no file called not_a_file.ucas."
    sig = env.svc.keys.url_signer.sign("pk_nope", entry["name"], exp)
    response = env.client.get(f"/files/pk_nope/{entry['name']}?exp={exp}&sig={sig}")
    assert response.status_code == 404
    assert "There is no pack pk_nope" in response.json()["error"]


def test_a_whole_pack_takes_about_four_seconds_whatever_its_size(make_env) -> None:
    """Pacing is by time, not by size: this is the one test timed on the real clock.

    The pack here is a few tens of KB — a real cooked pack's size — and it still takes the
    spec's ~4 s, which is what "the download is paced" has to mean once the fake filler
    goes away.
    """
    env = make_env(packs={"pacing_seconds": 4.0})
    manifest = env.resolve("A", "A1", "r1")
    started = time.monotonic()
    total = 0
    for entry in manifest["pack"]["files"]:
        response = env.fetch(entry)
        assert response.status_code == 200
        total += len(response.content)
    took = time.monotonic() - started
    assert total == manifest["pack"]["total_bytes"]
    assert 3.0 <= took <= 6.5, f"a paced pack download took {took:.1f}s"


def test_pacing_off_is_instant(env) -> None:
    manifest = env.resolve("A", "A1", "r1")
    started = time.monotonic()
    for entry in manifest["pack"]["files"]:
        env.fetch(entry)
    assert time.monotonic() - started < 2.0


def test_the_demo_files_folder_is_served_as_the_brands_computer(env) -> None:
    listing = env.ok(env.client.get("/demo-files"))["files"]
    names = {row["name"] for row in listing}
    assert "content1_v1.dcpack" in names
    assert "rival1_v1.dcpack" not in names          # the game's own content is not on offer
    bad = [row for row in listing if row["note"]]
    assert {row["note"] for row in bad} == {"built for engine 5.3", "rated 18+"}
    for row in listing:
        assert row["bytes"] > 0
    first = listing[0]["name"]
    response = env.client.get(f"/demo-files/{first}")
    assert response.status_code == 200
    assert len(response.content) == dict((r["name"], r["bytes"]) for r in listing)[first]
    assert env.client.get("/demo-files/nope.dcpack").status_code == 404
    assert env.client.get("/demo-files/../config/demo.json").status_code in (404, 422)


def test_the_clock_endpoint_reads_like_a_clock(env) -> None:
    clock = env.ok(env.client.get("/clock"))
    assert clock["label"] == "demo time"
    assert clock["server_time"] == iso(env.clock.now())
    assert clock["demo_seconds_per_real_second"] == 60
    before = clock["demo_time"]
    env.clock.advance(60)                                  # one real minute
    after = env.ok(env.client.get("/clock"))
    assert after["demo_hours_elapsed"] - clock["demo_hours_elapsed"] == 1.0
    assert after["demo_time"] > before
