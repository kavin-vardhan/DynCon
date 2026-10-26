"""Uploads: the four checks in order, with a sentence a visitor can read."""
from __future__ import annotations

import helpers
import pytest


def states(result: dict) -> dict[str, str]:
    return {row["check"]: row["state"] for row in result["checks"]}


def test_a_good_pack_is_approved(env) -> None:
    result = env.upload("content1_v1.dcpack")
    assert result["status"] == "approved"
    assert [row["check"] for row in result["checks"]] == ["package", "rating", "fit", "sign"]
    assert all(row["ok"] for row in result["checks"])
    assert result["piece"] == "content1" and result["version"] == "v1"
    assert len(result["pack"]["files"]) == 3                      # pak + utoc + ucas
    assert all(len(f["sha256"]) == 64 for f in result["pack"]["files"])
    assert result["pack"]["total_bytes"] == sum(f["size"] for f in result["pack"]["files"])
    mine = env.ok(env.client.get("/content"))["content"]
    assert [c["content_id"] for c in mine] == [result["content_id"]]
    assert mine[0]["latest_approved"]["version"] == "v1"


def test_the_engine_pack_is_rejected_at_package(env) -> None:
    result = env.upload("content2_v1_engine53.dcpack")
    assert result["status"] == "rejected"
    assert result["failed_check"] == "package"
    assert result["reason"] == "Made for engine 5.3 — this game runs 5.7."
    assert states(result) == {"package": "failed", "rating": "skipped",
                              "fit": "skipped", "sign": "skipped"}
    assert env.ok(env.client.get("/content"))["content"] == []    # nothing was stored


def test_the_rating_pack_is_rejected_at_rating(env) -> None:
    result = env.upload("content2_v1_rated18.dcpack")
    assert result["status"] == "rejected"
    assert result["failed_check"] == "rating"
    assert result["reason"] == ("Rated 18+ — this demo only accepts content rated for everyone.")
    assert states(result)["package"] == "ok"
    assert states(result)["fit"] == "skipped"


def test_a_pack_that_does_not_fit_its_own_class_is_rejected_at_fit(env, tmp_path) -> None:
    """content3 is 17 m tall; declare it as an L (9 m limit) and the fit check must catch it."""
    bad = helpers.patch_dcpack(env.demo_files / "content3_v1.dcpack",
                               tmp_path / "liar.dcpack", size_class="L")
    result = helpers.upload_bytes(env.client, bad.read_bytes(), "liar.dcpack")
    assert result["failed_check"] == "fit"
    assert result["reason"] == "Too tall for size class L — 17.0 m against a 9.0 m limit."
    assert states(result)["sign"] == "skipped"


def test_rubbish_files_are_rejected_at_package(env, tmp_path) -> None:
    cases = {
        "not a zip": (helpers.not_a_zip(tmp_path / "a.dcpack"),
                      "That file is not a .dcpack package — it is not a valid zip."),
        "no dcpack.json": (helpers.zip_without_meta(tmp_path / "b.dcpack"),
                           "The package has no dcpack.json, so there is no way to tell "
                           "what is inside it."),
        "broken json": (helpers.zip_with_broken_meta(tmp_path / "c.dcpack"),
                        "dcpack.json is not valid JSON."),
    }
    for label, (path, sentence) in cases.items():
        result = helpers.upload_bytes(env.client, path.read_bytes(), path.name)
        assert result["status"] == "rejected", label
        assert result["failed_check"] == "package", label
        assert result["reason"] == sentence, label


def test_a_missing_field_is_named(env, tmp_path) -> None:
    whole = helpers.build_dcpack(tmp_path / "whole.dcpack")
    stripped = helpers.patch_dcpack(whole, tmp_path / "stripped.dcpack",
                                    drop=["bounds", "class_path"])
    result = helpers.upload_bytes(env.client, stripped.read_bytes())
    assert result["reason"] == "dcpack.json is missing: bounds, class_path."


def test_a_file_listed_but_not_in_the_package_is_named(env, tmp_path) -> None:
    one_file = helpers.build_dcpack(tmp_path / "one.dcpack",
                                    files={"pakchunk100-Windows.pak": b"x" * 8})
    patched = helpers.patch_dcpack(
        one_file, tmp_path / "two.dcpack",
        files=[{"name": "pakchunk100-Windows.pak", "bytes": 8},
               {"name": "pakchunk100-Windows.ucas", "bytes": 99}])
    result = helpers.upload_bytes(env.client, patched.read_bytes())
    assert result["reason"] == ("The package lists pakchunk100-Windows.ucas but does not "
                                "contain it.")


def test_the_size_limit_is_enforced(make_env) -> None:
    env = make_env(packs={"max_bytes": 4096})
    result = env.upload("content4_v1.dcpack")
    assert result["failed_check"] == "package"
    assert result["reason"].startswith("This pack is ")
    assert result["reason"].endswith("the limit for the demo is 4 KB.")


def test_pushing_version_two(env) -> None:
    first = env.upload("content1_v1.dcpack")
    second = env.upload("content1_v2.dcpack", content_id=first["content_id"])
    assert second["status"] == "approved"
    assert second["content_id"] == first["content_id"]
    assert (second["version"], second["version_n"]) == ("v2", 2)
    mine = env.ok(env.client.get("/content"))["content"][0]
    assert [v["version"] for v in mine["versions"]] == ["v1", "v2"]
    assert mine["latest_approved"]["version"] == "v2"


def test_an_update_has_to_be_the_same_piece(env) -> None:
    first = env.upload("content1_v1.dcpack")
    result = env.upload("content4_v1.dcpack", content_id=first["content_id"])
    assert result["status"] == "rejected"
    assert result["failed_check"] == "package"
    assert result["reason"] == ("This update is content4, but this campaign's content is "
                                "content1.")


def test_a_rejected_update_leaves_version_one_live(env) -> None:
    first = env.upload("content1_v1.dcpack")
    env.upload("content2_v1_rated18.dcpack", content_id=first["content_id"])
    mine = env.ok(env.client.get("/content"))["content"][0]
    assert mine["latest_approved"]["version"] == "v1"


def test_pushing_a_version_of_something_that_does_not_exist(env) -> None:
    blob = (env.demo_files / "content1_v1.dcpack").read_bytes()
    response = env.client.post("/content/c99/versions",
                               files={"file": ("x.dcpack", blob, "application/octet-stream")})
    assert response.status_code == 404
    assert response.json()["error"] == "There is no content c99."


def test_system_content_cannot_be_updated_by_the_visitor(env) -> None:
    blob = (env.demo_files / "rival1_v1.dcpack").read_bytes()
    response = env.client.post("/content/sys_rival1/versions",
                               files={"file": ("x.dcpack", blob, "application/octet-stream")})
    assert response.status_code == 400
    assert "belongs to the game" in response.json()["error"]


@pytest.mark.parametrize("piece,expected_slots", [
    ("content3_v1.dcpack", {"A2"}),                                  # 17 m tall: A2 only
    ("content4_v1.dcpack", {"A1", "A2", "A3", "B1", "B2"}),          # small: everywhere
    ("content1_v1.dcpack", {"A1", "A2", "B1"}),                      # large: not the S slots
])
def test_which_slots_a_piece_fits(env, piece, expected_slots) -> None:
    result = env.upload(piece)
    fits = {slot for slot, verdict in result["fits"].items() if verdict["ok"]}
    assert fits == expected_slots
    for slot, verdict in result["fits"].items():
        assert verdict["reason"]
        if not verdict["ok"]:
            assert verdict["reason"].startswith("Too ")


def test_the_reason_a_tall_piece_is_turned_away_reads_in_plain_words(env) -> None:
    result = env.upload("content3_v1.dcpack")
    assert result["fits"]["A1"]["reason"] == ("Too tall for this slot — 17.0 m against a "
                                              "9.0 m limit.")
    assert result["fits"]["A3"]["reason"] == ("Too tall for this slot — 17.0 m against a "
                                              "5.0 m limit.")
