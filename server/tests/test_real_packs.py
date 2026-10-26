"""The real cooked packs from the UE side, wrapped and served.

`unreal\\_packs\\` is a build output and is git-ignored, so these tests skip on a machine
that has not run the UE packaging step. On this PC they are the proof that the server can
serve what the engine actually produced (brief 006: 13 packs, chunks 100–112).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from conftest import REAL_PACKS_DIR
from dcserver.packs import peek_dcpack

CHUNK_TABLE = REAL_PACKS_DIR.parent / "Tools" / "chunk_ids.json"


@pytest.fixture
def real_env(make_env, real_demo_files):
    if real_demo_files is None:
        pytest.skip("unreal/_packs is not on this machine (it is a build output)")
    return make_env(files=real_demo_files)


def test_every_real_pack_passes_the_four_checks(real_env, real_demo_files) -> None:
    uploadable = sorted(p for p in real_demo_files.glob("content*.dcpack"))
    assert len(uploadable) == 8                       # content1-4, v1 and v2
    for path in uploadable:
        result = real_env.ok(real_env.client.post(
            "/content", files={"file": (path.name, path.read_bytes(),
                                        "application/octet-stream")}))
        assert result["status"] == "approved", f"{path.name}: {result.get('reason')}"
        assert len(result["pack"]["files"]) == 3       # pak + utoc + ucas travel together
        names = sorted(f["name"].rsplit(".", 1)[1] for f in result["pack"]["files"])
        assert names == ["pak", "ucas", "utoc"]
        assert result["pack"]["total_bytes"] < 2 * 1024 * 1024


def test_a_real_pack_is_served_byte_for_byte(real_env, real_demo_files) -> None:
    content = real_env.ok(real_env.client.post(
        "/content", files={"file": ("content1_v2.dcpack",
                                    (real_demo_files / "content1_v2.dcpack").read_bytes(),
                                    "application/octet-stream")}))
    real_env.brand()
    real_env.allocate("A", "A1", "r1", content["content_id"])
    manifest = real_env.resolve("A", "A1", "r1")
    assert manifest["content"]["class_path"] == \
        "/Game/DCContent/content1_v2/BP_DC_content1_v2.BP_DC_content1_v2_C"
    for entry in manifest["pack"]["files"]:
        source = REAL_PACKS_DIR / "content1_v2" / entry["name"]
        body = real_env.fetch(entry).content
        assert body == source.read_bytes()
        assert hashlib.sha256(body).hexdigest() == entry["sha256"]


def test_the_wrapper_keeps_the_spikes_pack_json_facts(real_demo_files) -> None:
    """dcpack.json is a superset of the spike's pack.json, chunk id included."""
    table = {f"{row['id']}_{row['version']}": row
             for row in json.loads(CHUNK_TABLE.read_text(encoding="utf-8-sig"))["packs"]}
    for key, row in table.items():
        meta = peek_dcpack(real_demo_files / f"{key}.dcpack")
        assert meta, key
        spike = json.loads((REAL_PACKS_DIR / key / "pack.json").read_text(encoding="utf-8-sig"))
        assert meta["chunk_id"] == row["chunk_id"] == spike["chunk_id"]
        assert meta["class_path"] == spike["class_path"]
        assert meta["size_class"] == spike["size_class"]
        assert meta["total_bytes"] == spike["total_bytes"]
        assert [f["name"] for f in meta["files"]] == [f["name"] for f in spike["files"]]
        assert meta["units"] == spike["units"]
        assert meta["source"]["kind"] == "real"
        # the fit check's numbers are the art's, in metres
        assert meta["bounds"]["z"] == pytest.approx(spike["bounds_cm"][2] / 100.0, abs=0.01)


def test_the_real_rival_and_default_packs_seed_themselves(real_env) -> None:
    health = real_env.ok(real_env.client.get("/admin/health"))
    assert all(row["pack_id"] for row in health["system_packs"].values())
    manifest = real_env.resolve("A", "A1", "r1")
    assert manifest["content"]["piece"] == "rival1"
    assert manifest["pack"]["total_bytes"] < 2 * 1024 * 1024       # a real pack, not filler


def test_a_real_pack_paces_like_a_fake_one(make_env, real_demo_files) -> None:
    """The point of pacing by time: 0.7 MB behaves like 30 MB at the booth."""
    import time
    if real_demo_files is None:
        pytest.skip("unreal/_packs is not on this machine")
    env = make_env(files=real_demo_files, packs={"pacing_seconds": 2.0})
    manifest = env.resolve("A", "A1", "r1")
    started = time.monotonic()
    for entry in manifest["pack"]["files"]:
        env.fetch(entry)
    took = time.monotonic() - started
    assert 1.4 <= took <= 4.0, f"a real pack took {took:.1f}s"
