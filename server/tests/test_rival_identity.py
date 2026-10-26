"""The server config is the single source of truth for rival identity and region mapping.

`art/blender/dc_kit.py` carries a `PREVIEW_IDENTITY` table so a rival's *preview* is rendered
in the colours it will really wear at the booth. That table is preview-only — nothing is baked
into an FBX — but if the two ever disagree, the previews quietly lie about the demo. This test
is what stops that: it reads the art kit's table with `ast` (no Blender needed) and compares
it with `server/config/demo.json`.

The rule, both ways:
  * every rival piece in the config appears in the art table, and every piece in the art
    table is a rival piece in the config;
  * a piece only one region uses (rival1 / rival2 / rival3) must carry exactly that region's
    colour and emblem;
  * a piece several regions share (rivalsmall) is previewed in the dress of the *first*
    region that uses it — the config's own region order decides, so there is still exactly
    one right answer.
"""
from __future__ import annotations

import ast

import pytest

from conftest import CONFIG_PATH, REPO_DIR
from dcserver.config import Config

DC_KIT = REPO_DIR / "art" / "blender" / "dc_kit.py"


def read_preview_identity() -> dict[str, tuple[str, str]]:
    tree = ast.parse(DC_KIT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PREVIEW_IDENTITY":
                    return {k: tuple(v) for k, v in ast.literal_eval(node.value).items()}
    raise AssertionError(f"PREVIEW_IDENTITY is not in {DC_KIT}")


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config.load(CONFIG_PATH)


@pytest.fixture(scope="module")
def preview() -> dict[str, tuple[str, str]]:
    return read_preview_identity()


def test_the_two_tables_cover_the_same_pieces(cfg: Config, preview) -> None:
    assert sorted(preview) == sorted(cfg.rival_pieces()), (
        "art/blender/dc_kit.py PREVIEW_IDENTITY and demo.json 'rivals' name different pieces")


def test_every_rival_piece_is_previewed_in_its_configured_identity(cfg: Config, preview) -> None:
    for piece, (colour, emblem) in preview.items():
        regions = cfg.regions_using_piece(piece)
        assert regions, f"{piece} is previewed as a rival but no region uses it"
        owner = regions[0]
        rival = cfg.rival(owner)
        assert (colour.upper(), emblem) == (rival["colour"].upper(), rival["emblem"]), (
            f"{piece}: the art previews it as {colour}/{emblem} but region {owner} dresses "
            f"its rival in {rival['colour']}/{rival['emblem']}")


def test_each_region_has_its_own_colour_and_emblem(cfg: Config) -> None:
    identities = [(cfg.rival(r)["colour"].upper(), cfg.rival(r)["emblem"]) for r in cfg.regions]
    assert len(set(identities)) == len(identities), "two regions' rivals look the same"


def test_a_rival_identity_is_not_a_visitor_preset(cfg: Config) -> None:
    """The rival must never turn up wearing a colour the visitor could have picked."""
    presets = {c.upper() for c in cfg.data["brand_presets"]["colours"]}
    for region in cfg.regions:
        assert cfg.rival(region)["colour"].upper() not in presets, region
