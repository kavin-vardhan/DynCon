"""The brand portal is served by this server, out of `portal/`, at /portal/.

Same origin as the API on purpose: the portal then needs no CORS, no base URL and no
second process at the booth. These tests are about the mount itself — that the folder is
really served, that it cannot shadow an API route, and that a checkout without the folder
still starts.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from dcserver.app import create_app
from dcserver.clock import FakeClock
from dcserver.config import Config
from dcserver.signing import KeyStore

REPO_DIR = Path(__file__).resolve().parent.parent.parent
PORTAL_DIR = REPO_DIR / "portal"


def test_the_portal_is_served_at_portal(env) -> None:
    page = env.client.get("/portal/")
    assert page.status_code == 200
    assert '<div id="app"' in page.text
    assert 'src="app.js"' in page.text


def test_the_portal_files_are_all_there(env) -> None:
    for path in ("app.js", "api.js", "input.js", "ui.js", "strings.js", "menu.js",
                 "style.css",
                 "screens/attract.js", "screens/brand.js", "screens/upload.js",
                 "screens/games.js", "screens/slotmap.js", "screens/regions.js",
                 "screens/auction.js", "screens/live.js", "screens/report.js",
                 "screens/update.js", "screens/summary.js"):
        answer = env.client.get(f"/portal/{path}")
        assert answer.status_code == 200, path
        assert answer.content, path


def test_the_japanese_font_is_not_served_any_more(env) -> None:
    """English only, Kavin's ruling 2026-11-02: the Noto Sans JP subset and its licence
    were the last thing in `portal/fonts/`, and the folder went with them."""
    assert not (PORTAL_DIR / "fonts").exists()
    assert env.client.get("/portal/fonts/NotoSansJP-subset.woff2").status_code == 404
    assert "NotoSansJP" not in env.client.get("/portal/style.css").text
    assert 'lang="en"' in env.client.get("/portal/").text


def test_the_string_table_is_one_language_and_still_covers_the_tour(env) -> None:
    """`strings.js` is the whole of what the portal can say, so it is worth a look from
    here: one entry per key, no `jp:` / `en:` pairs left, and not suspiciously small."""
    text = env.client.get("/portal/strings.js").text
    assert "jp:" not in text and "REGION_JP" not in text
    body = text.split("export const STRINGS = {", 1)[1].split("\n};", 1)[0]
    keys = re.findall(r"^\s{2}(\w+):\s*'", body, re.M)
    assert len(keys) > 100, f"the string table looks far too small: {len(keys)} entries"
    for key in ("attract_start", "upload_approved", "regions_place", "auction_closes_in",
                "live_step_mount", "report_totals", "update_swapped", "summary_now",
                "preview_window_here", "demo_credits_note"):
        assert key in keys, f"{key} is not in the string table any more"


def test_the_mount_does_not_shadow_the_api(env) -> None:
    assert env.client.get("/games").status_code == 200
    assert env.client.get("/portal/../games").status_code in (200, 404)
    index = env.ok(env.client.get("/"))
    assert index["portal_ui"] == "/portal/"


def test_a_checkout_with_no_portal_folder_still_starts(tmp_path, keys_dir,
                                                       demo_files) -> None:
    app = create_app(Config.load(REPO_DIR / "server" / "config" / "demo.json"),
                     clock=FakeClock(), data_dir=tmp_path / "data",
                     demo_files=demo_files, maps_dir=tmp_path / "maps",
                     keys=KeyStore(keys_dir), portal_dir=tmp_path / "no-portal-here")
    with TestClient(app) as client:
        assert client.get("/admin/health").status_code == 200
        assert client.get("/portal/").status_code == 404
        assert client.get("/").json()["portal_ui"] is None
    app.state.svc.repo.close()
