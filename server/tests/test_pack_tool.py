"""`run_local.ps1 -Packs` is two calls to the generator; this is what those two calls do.

Pass 1 builds the fake packs for every piece-version plus the two built-to-fail files.
Pass 2 wraps whatever real cooked packs `unreal\\_packs\\` holds as `<id>_<v>.real.dcpack`.
The curated "Your computer" list then prefers the real pack wherever one exists — and on a
clean checkout, where there is no UE build output, pass 2 writes nothing and the demo runs
on the fakes.
"""
from __future__ import annotations

import pytest

import make_fake_packs
from conftest import REAL_PACKS_DIR

TINY = ["--min-mb", "0.02", "--max-mb", "0.05", "--quiet"]


def both_passes(out) -> None:
    assert make_fake_packs.main(["--out", str(out)] + TINY) == 0
    assert make_fake_packs.main(["--out", str(out), "--real", "--quiet"]) == 0


def test_the_two_passes_leave_real_packs_on_the_curated_list(make_env, tmp_path) -> None:
    if not (REAL_PACKS_DIR / "content1_v1" / "pack.json").is_file():
        pytest.skip("unreal/_packs is not on this machine (it is a build output)")
    out = tmp_path / "demo_files"
    both_passes(out)
    names = {p.name for p in out.glob("*.dcpack")}
    assert "content1_v1.dcpack" in names                  # the fake is still there
    assert "content1_v1.real.dcpack" in names             # and so is the real wrapper
    assert "content2_v1_engine53.dcpack" in names         # and the built-to-fail file

    env = make_env(files=out)
    listing = env.ok(env.client.get("/demo-files"))["files"]
    uploadable = [row for row in listing if row["note"] is None]
    assert [row["name"] for row in uploadable] == [
        "content1_v1.real.dcpack", "content2_v1.real.dcpack",
        "content3_v1.real.dcpack", "content4_v1.real.dcpack"]
    assert all(row["real"] for row in uploadable)
    assert all(row["bytes"] < 2 * 1024 * 1024 for row in uploadable)
    # the game's own content is seeded from the real packs too
    health = env.ok(env.client.get("/admin/health"))
    assert all(row["pack_id"] for row in health["system_packs"].values())
    assert env.resolve("A", "A1", "r1")["pack"]["total_bytes"] < 2 * 1024 * 1024

    # and a pack straight off that list uploads and passes the four checks
    result = env.upload(uploadable[0]["name"])
    assert result["status"] == "approved" and len(result["pack"]["files"]) == 3


def test_a_clean_checkout_falls_back_to_the_fakes(make_env, tmp_path, monkeypatch) -> None:
    """No `unreal\\_packs\\` (it is git-ignored), so pass 2 has nothing to wrap."""
    monkeypatch.setattr(make_fake_packs, "REAL_PACKS", tmp_path / "no_build_output")
    out = tmp_path / "demo_files"
    both_passes(out)
    assert not list(out.glob("*.real.dcpack"))            # pass 2 wrote nothing, and said so
    assert len(list(out.glob("*.dcpack"))) == 15          # 13 pieces + 2 built to fail

    env = make_env(files=out)
    listing = env.ok(env.client.get("/demo-files"))["files"]
    assert [row["name"] for row in listing] == [
        "content1_v1.dcpack", "content2_v1.dcpack", "content3_v1.dcpack",
        "content4_v1.dcpack", "content2_v1_engine53.dcpack"]
    assert not any(row["real"] for row in listing)
    assert env.ok(env.client.get("/admin/health"))["system_packs"]["default"]["pack_id"]


def test_the_filler_is_deterministic(tmp_path) -> None:
    """Same seed, same filler bytes, so a rebuild gives a pack the same size and content.

    (The zip itself is not byte-identical between runs — `dcpack.json` carries the time it
    was built — so this compares the container entries, which is what the seeding is for.)
    """
    import zipfile

    def containers(path):
        with zipfile.ZipFile(path) as zf:
            return {name: zf.read(name) for name in zf.namelist() if name != "dcpack.json"}

    first, second = tmp_path / "a", tmp_path / "b"
    for out in (first, second):
        assert make_fake_packs.main(["--out", str(out), "--pieces", "content4_v1",
                                     "--no-bad"] + TINY) == 0
    one, two = containers(first / "content4_v1.dcpack"), containers(second / "content4_v1.dcpack")
    assert sorted(one) == sorted(two) == ["pakchunk106-Windows.pak",
                                          "pakchunk106-Windows.ucas",
                                          "pakchunk106-Windows.utoc"]
    assert one == two
