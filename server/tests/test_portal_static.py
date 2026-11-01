"""The brand portal is served by this server, out of `portal/`, at /portal/.

Same origin as the API on purpose: the portal then needs no CORS, no base URL and no
second process at the booth. These tests are about the mount itself — that the folder is
really served, that it cannot shadow an API route, and that a checkout without the folder
still starts.
"""
from __future__ import annotations

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
                 "screens/update.js", "screens/summary.js",
                 "fonts/NotoSansJP-subset.woff2", "fonts/OFL.txt"):
        answer = env.client.get(f"/portal/{path}")
        assert answer.status_code == 200, path
        assert answer.content, path


def test_every_japanese_string_has_an_english_one(env) -> None:
    """The one rule the portal cannot be allowed to break quietly (CLAUDE.md rule 3)."""
    text = env.client.get("/portal/strings.js").text
    assert "needs native review" in text          # the header the spec asks for
    # An entry may be written on one line or two, so the check is positional: between one
    # `jp:` and the next there has to be an `en:`.
    marks = [i for i in range(len(text)) if text.startswith("jp:", i)]
    assert len(marks) > 40, "the string table looks far too small"
    for index, start in enumerate(marks):
        end = marks[index + 1] if index + 1 < len(marks) else len(text)
        assert "en:" in text[start:end], \
            f"a string with no English: {text[start:start + 70]!r}"
    assert text.count("jp:") == text.count("en:")


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
