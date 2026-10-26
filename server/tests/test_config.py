"""The config *is* the contract. These tests fail if a tunable drifts from spec v1 §2 or
from the size classes in the content-asset spec.
"""
from __future__ import annotations

import re

import pytest

from conftest import CONFIG_PATH, REPO_DIR
from dcserver.config import Config, ConfigError

ASSET_SPEC = REPO_DIR / "specs" / "content_assets_spec_v1.md"


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config.load(CONFIG_PATH)


def test_spec_values(cfg: Config) -> None:
    assert cfg.regions == ["r1", "r2", "r3"]
    assert [cfg.region_label(r) for r in cfg.regions] == ["Japan", "India", "Europe"]
    assert cfg.data["booth"]["main_region"] == "r1"
    assert cfg.data["booth"]["preview_default_region"] == "r2"
    assert cfg.games == ["A", "B"]
    assert {s.id: s.size_class for s in cfg.slots} == {
        "A1": "L", "A2": "T", "A3": "S", "B1": "L", "B2": "S"}
    assert cfg.wallet_start == 2000
    assert cfg.data["block_demo_hours"] == 3
    assert cfg.demo_factor == 60
    assert cfg.block_seconds == 180.0            # 3 demo hours = 3 real minutes
    assert cfg.max_pack_bytes == 100 * 1024 * 1024
    assert cfg.engine_version == "5.7"
    assert cfg.allowed_ratings == ["all"]
    assert cfg.pacing_seconds == 4.0
    assert cfg.data["idle_reset_s"] == 60
    assert cfg.data["client"]["poll_interval_s"] == 1.5


def test_footfall_matches_the_plan(cfg: Config) -> None:
    expected = {
        "A1": (1200, 900, 600), "A2": (800, 600, 400), "A3": (300, 250, 150),
        "B1": (700, 500, 350), "B2": (250, 200, 120),
    }
    for slot, row in expected.items():
        assert tuple(cfg.footfall(slot, r) for r in cfg.regions) == row


def test_auction_values(cfg: Config) -> None:
    auction = cfg.data["auction"]
    assert auction["opening_factor"] == 0.25
    assert auction["opening_round_to"] == 25
    assert auction["min_raise"] == 25
    assert auction["rival_max_factor"] == 2.0
    assert auction["rival_delay_s"] == 3
    assert auction["clock_s"] == 45
    assert auction["soft_close_s"] == 10
    # the wallet can always beat the rival: all three regions of A1 cost at most 1,350
    opening_a1 = sum(cfg.footfall("A1", r) * auction["opening_factor"] for r in cfg.regions)
    assert opening_a1 + 3 * auction["min_raise"] <= cfg.wallet_start


def test_brand_presets(cfg: Config) -> None:
    presets = cfg.data["brand_presets"]
    assert presets["colours"] == ["#E23D3D", "#2F6FEB", "#2EA44F", "#F2C230",
                                  "#E0559B", "#1EB8D0", "#8CC63F", "#23395B"]
    assert presets["emblems"] == ["circle", "triangle", "square", "diamond",
                                  "star", "ring", "chevron", "hexagon"]


def parse_asset_spec_classes() -> dict[str, tuple[float, float, float, list[str]]]:
    """The size-class table out of specs/content_assets_spec_v1.md §2."""
    out: dict[str, tuple[float, float, float, list[str]]] = {}
    for line in ASSET_SPEC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*\*\*([SLT])\*\*[^|]*\|\s*[^\d|]*([\d.]+)\s*[x×]\s*([\d.]+)\s*m"
                     r"[^|]*\|\s*[^\d|]*([\d.]+)\s*m[^|]*\|\s*([^|]+)\|", line)
        if m:
            cls, x, y, z, slots = m.groups()
            out[cls] = (float(x), float(y), float(z),
                        [s.strip() for s in slots.split(",") if s.strip()])
    return out


def test_size_classes_match_the_asset_spec(cfg: Config) -> None:
    """One set of numbers for the art and for the server's fit check."""
    table = parse_asset_spec_classes()
    assert set(table) == {"S", "L", "T"}, f"could not read the spec table: {table}"
    for cls, (x, y, z, slots) in table.items():
        limits = cfg.limits(cls)
        assert (limits["x"], limits["y"], limits["z"]) == (x, y, z), cls
        assert sorted(slots) == sorted(s.id for s in cfg.slots if s.size_class == cls), cls


def test_validate_rejects_a_broken_config(cfg: Config) -> None:
    with pytest.raises(ConfigError):
        cfg.copy_with(rivals={"r1": {"colour": "#fff"}})
    with pytest.raises(ConfigError):
        cfg.copy_with(booth={"main_region": "r9"})
    with pytest.raises(ConfigError):
        cfg.copy_with(packs={"allowed_ratings": []})


def test_rival_pieces_exist_as_art(cfg: Config) -> None:
    """Every piece the config can ask for has art committed for it."""
    for piece in cfg.system_pieces():
        folders = list((REPO_DIR / "art" / "export").glob(f"{piece}_*"))
        assert folders, f"the config names {piece} but art/export has no such piece"
        assert any((f / "manifest.json").is_file() for f in folders), piece


def test_small_slots_get_the_small_rival(cfg: Config) -> None:
    for region in cfg.regions:
        assert cfg.rival_piece(region, "S") == cfg.rival(region)["pieces"]["small"]
        for cls in ("L", "T"):
            assert cfg.rival_piece(region, cls) == cfg.rival(region)["pieces"]["large"]
