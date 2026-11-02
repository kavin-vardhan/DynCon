"""`GET /preview/region`: what the second copy of the game asks about itself.

The region preview window (plan v6 §7, §11) is a second copy of the same build that plays as
a player in another region. It polls this one endpoint for the two things it cannot know by
itself: **which region it is** (the portal's region check flips it) and **which slot to look
at** — "the slot just auctioned".

The focus rules are tested in the order the server applies them, because the point of having
three is that there is always an answer: a bid beats an allocation beats the busiest slot of
the game being played at the booth.

The region labels are tested against `portal/strings.js` for the same reason
`test_rival_identity.py` tests the art kit's preview table: the game draws its caption on the
HUD canvas and cannot import the portal's string table, so the two have to be kept honest by
a test rather than by memory. The demo is **English only** since 2026-11-02 (Kavin's ruling),
so what is compared is the English names — `label` and `neutral_label` — against the list of
region names the portal has been written for. There used to be a `label_jp` in both places.
"""
from __future__ import annotations

import re

import pytest

from conftest import CONFIG_PATH, REPO_DIR
from dcserver.config import Config

STRINGS_JS = REPO_DIR / "portal" / "strings.js"


def preview(env) -> dict:
    return env.ok(env.client.get("/preview/region"))


# --------------------------------------------------------------------------- the region

def test_it_starts_as_the_configured_preview_region(env) -> None:
    answer = preview(env)
    assert answer["region"] == env.config.preview_region == "r2"
    assert answer["label"] == "India"
    assert answer["neutral_label"] == "Mock region 2"
    assert answer["main_region"] == "r1"
    assert "label_jp" not in answer          # English only, 2026-11-02


def test_the_portal_can_flip_it_and_the_label_follows(env) -> None:
    answer = env.ok(env.client.post("/preview/region", json={"region": "r1"}))
    assert (answer["region"], answer["label"]) == ("r1", "Japan")
    assert preview(env)["region"] == "r1"


def test_an_unknown_region_is_a_404(env) -> None:
    env.ok(env.client.post("/preview/region", json={"region": "r9"}), 404)


def test_a_reset_puts_the_preview_back_to_its_default_region(env) -> None:
    env.ok(env.client.post("/preview/region", json={"region": "r3"}))
    env.ok(env.client.post("/admin/reset"))
    assert preview(env)["region"] == "r2"


# --------------------------------------------------------------------------- the focus

def test_with_nothing_bid_it_frames_the_busiest_slot_of_the_booth_game(env) -> None:
    focus = preview(env)["focus"]
    assert (focus["game"], focus["slot"]) == ("A", "A1")      # 1,200 footfall in Japan
    assert "busiest" in focus["reason"]


def test_an_allocation_moves_the_focus_to_that_slot(env) -> None:
    content = env.upload("content3_v1.dcpack")["content_id"]
    env.allocate("A", "A2", "r1", content)
    focus = preview(env)["focus"]
    assert (focus["game"], focus["slot"]) == ("A", "A2")
    assert "allocation" in focus["reason"]


def test_a_bid_beats_an_allocation_because_it_is_the_newer_intent(env) -> None:
    content = env.upload("content4_v1.dcpack")["content_id"]
    env.allocate("A", "A2", "r1", content)
    env.brand()
    env.bid("A3", content, {"r1": 200})
    focus = preview(env)["focus"]
    assert (focus["game"], focus["slot"]) == ("A", "A3")
    assert "bid" in focus["reason"]


def test_the_focus_follows_the_slot_the_visitor_bid_on_last(env) -> None:
    content = env.upload("content4_v1.dcpack")["content_id"]
    env.brand()
    env.bid("A3", content, {"r1": 200})
    env.bid("B2", content, {"r1": 200})
    assert preview(env)["focus"]["slot"] == "B2"
    assert preview(env)["focus"]["game"] == "B"


def test_the_rivals_own_bidding_never_moves_the_focus(env) -> None:
    """The attract loop's rivals bid against each other all day. The window must keep
    looking at the visitor's slot, not wander off to whichever lot last ticked over."""
    content = env.upload("content1_v1.dcpack")["content_id"]
    env.brand()
    env.bid("A1", content, {"r1": 300})
    env.clock.advance(5)                       # long enough for the rival to answer
    env.ok(env.client.get("/lots"))            # a poll is what makes a due bid happen
    assert preview(env)["focus"]["slot"] == "A1"


def test_a_reset_forgets_the_focus_with_everything_else(env) -> None:
    content = env.upload("content4_v1.dcpack")["content_id"]
    env.brand()
    env.bid("A3", content, {"r1": 200})
    assert preview(env)["focus"]["slot"] == "A3"
    env.ok(env.client.post("/admin/reset"))
    assert preview(env)["focus"]["slot"] == "A1"


# --------------------------------------------------------------------- the live flip

def test_there_is_no_flip_to_start_with(env) -> None:
    assert env.ok(env.client.get("/preview/flip"))["flip"] is None
    assert env.changes()["live_flip"] is None


def test_a_flip_rides_on_the_poll_every_copy_of_the_game_already_makes(env) -> None:
    answer = env.ok(env.client.post("/preview/flip",
                                    json={"region": "r2", "seconds": 20}))
    assert answer["flip"]["region"] == "r2"
    assert answer["flip"]["label"] == "India"
    assert answer["flip"]["back_to"] == "r1"
    flip = env.changes()["live_flip"]
    assert flip["region"] == "r2" and 0 < flip["seconds_left"] <= 20


def test_a_flip_ends_by_itself_when_its_time_is_up(env) -> None:
    env.ok(env.client.post("/preview/flip", json={"region": "r2", "seconds": 20}))
    env.clock.advance(19)
    assert env.changes()["live_flip"]["region"] == "r2"
    env.clock.advance(2)
    assert env.changes()["live_flip"] is None


def test_a_flip_can_be_cancelled(env) -> None:
    env.ok(env.client.post("/preview/flip", json={"region": "r3", "seconds": 20}))
    assert env.ok(env.client.post("/preview/flip",
                                  json={"region": "r3", "seconds": 0}))["flip"] is None
    assert env.changes()["live_flip"] is None


def test_an_unknown_region_cannot_be_flipped_to(env) -> None:
    env.ok(env.client.post("/preview/flip", json={"region": "r9", "seconds": 20}), 404)


def test_a_reset_cancels_a_flip(env) -> None:
    env.ok(env.client.post("/preview/flip", json={"region": "r2", "seconds": 60}))
    env.ok(env.client.post("/admin/reset"))
    assert env.changes()["live_flip"] is None


def test_the_flip_does_not_change_what_a_region_is_showing(env) -> None:
    """It is an instruction to the *game*, not a change to the platform's answers: the
    same slot in the same region shows the same thing before and after."""
    content = env.upload("content1_v1.dcpack")["content_id"]
    env.allocate("A", "A1", "r1", content)
    before = env.key("A", "A1", "r1")
    env.ok(env.client.post("/preview/flip", json={"region": "r2", "seconds": 20}))
    assert env.key("A", "A1", "r1") == before
    assert env.key("A", "A1", "r2") != before


# ---------------------------------------------------- the region labels, in two places

@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config.load(CONFIG_PATH)


def read_region_labels() -> list[str]:
    """`REGION_LABELS` out of portal/strings.js, without a JavaScript engine."""
    text = STRINGS_JS.read_text(encoding="utf-8")
    block = re.search(r"export const REGION_LABELS = \[(.*?)\n\];", text, re.S)
    assert block, f"REGION_LABELS is not in {STRINGS_JS}"
    return re.findall(r"'([^']+)'", block.group(1))


def test_every_region_has_an_english_name_in_the_config(cfg: Config) -> None:
    for region in cfg.regions:
        assert cfg.region_label(region), f"{region} has no label"
        assert cfg.data["regions"][region].get("neutral_label"), \
            f"{region} has no neutral_label"


def test_the_config_and_the_portals_table_agree(cfg: Config) -> None:
    """The portal draws whatever name the server sends, so every name the server can send
    has to be one the portal has been written for — that is this list."""
    table = read_region_labels()
    for region in cfg.regions:
        label = cfg.region_label(region)
        assert label in table, \
            f"portal/strings.js REGION_LABELS has no entry for {label!r}"


def test_the_neutral_labels_are_in_the_table_too(cfg: Config) -> None:
    """Management material uses the neutral labels (CLAUDE.md rule 3), and the portal has
    to be able to draw those as well."""
    table = read_region_labels()
    for region in cfg.regions:
        neutral = cfg.data["regions"][region].get("neutral_label")
        assert neutral and neutral in table, neutral


def test_nothing_in_the_config_carries_a_japanese_label_any_more(env, cfg: Config) -> None:
    """English only, Kavin's ruling 2026-11-02 (`specs/DECISIONS.md`)."""
    regions = env.ok(env.client.get("/config/public"))["regions"]
    assert regions["r2"] == {"label": "India", "neutral_label": "Mock region 2"}
    for region in cfg.regions:
        assert "label_jp" not in cfg.data["regions"][region]
