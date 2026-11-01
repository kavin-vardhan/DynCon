"""Reading config/demo.json. Nothing in this package reads a tunable from anywhere else."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any

from .clock import UTC


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class SlotDef:
    id: str
    game: str
    size_class: str
    index: int          # position within its game — the attract rotation uses it
    px: tuple[float, float]


class Config:
    """A thin, validated reader over demo.json."""

    def __init__(self, data: dict[str, Any], path: Path | None = None):
        self.data = data
        self.path = path
        self._slots: dict[str, SlotDef] = {}
        for game_id, game in self.data.get("games", {}).items():
            for i, (slot_id, slot) in enumerate(game.get("slots", {}).items()):
                px = slot.get("px", {})
                self._slots[slot_id] = SlotDef(
                    id=slot_id, game=game_id, size_class=slot["size_class"], index=i,
                    px=(float(px.get("x", 0.5)), float(px.get("y", 0.5))),
                )
        self.validate()

    # ---- loading -------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            raise ConfigError(f"No config at {p}")
        except json.JSONDecodeError as e:
            raise ConfigError(f"{p} is not valid JSON: {e}")
        return cls(data, p)

    def copy_with(self, **overrides: Any) -> "Config":
        """A config with some top-level keys replaced (tests use it for paths and pacing)."""
        data = json.loads(json.dumps(self.data))
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **value}
            else:
                data[key] = value
        return Config(data, self.path)

    # ---- regions, games, slots ------------------------------------------------------

    @property
    def regions(self) -> list[str]:
        return list(self.data["regions"].keys())

    def region_label(self, region: str) -> str:
        return self.data["regions"][region]["label"]

    def region_label_jp(self, region: str) -> str:
        """The Japanese name. Empty when this config has none, which is a caption in one
        language rather than a box of tofu — the game checks before it draws."""
        return self.data["regions"][region].get("label_jp") or ""

    def has_region(self, region: str) -> bool:
        return region in self.data["regions"]

    @property
    def games(self) -> list[str]:
        return list(self.data["games"].keys())

    def game(self, game: str) -> dict[str, Any]:
        return self.data["games"][game]

    def game_label(self, game: str) -> str:
        return self.data["games"][game]["label"]

    def slots_of(self, game: str) -> list[SlotDef]:
        return [s for s in self._slots.values() if s.game == game]

    @property
    def slots(self) -> list[SlotDef]:
        return list(self._slots.values())

    def slot(self, slot_id: str) -> SlotDef:
        return self._slots[slot_id]

    def has_slot(self, slot_id: str) -> bool:
        return slot_id in self._slots

    # ---- size classes ----------------------------------------------------------------

    @property
    def size_classes(self) -> list[str]:
        return list(self.data["size_classes"].keys())

    def limits(self, size_class: str) -> dict[str, float]:
        return {k: float(v) for k, v in self.data["size_classes"][size_class].items()}

    # ---- footfall, rivals, default ----------------------------------------------------

    def footfall(self, slot_id: str, region: str) -> int:
        return int(self.data["footfall"][slot_id][region])

    def rival(self, region: str) -> dict[str, Any]:
        return self.data["rivals"][region]

    def rival_piece(self, region: str, size_class: str) -> str:
        """S slots get the small rival piece; everything else gets the large one."""
        pieces = self.data["rivals"][region]["pieces"]
        return pieces["small"] if size_class == "S" else pieces["large"]

    def rival_pieces(self) -> list[str]:
        out: list[str] = []
        for region in self.regions:
            for piece in self.data["rivals"][region]["pieces"].values():
                if piece not in out:
                    out.append(piece)
        return out

    def regions_using_piece(self, piece: str) -> list[str]:
        return [r for r in self.regions
                if piece in self.data["rivals"][r]["pieces"].values()]

    @property
    def default_piece(self) -> str:
        return self.data["default_content"]["piece"]

    @property
    def default_version(self) -> str:
        return self.data["default_content"]["version"]

    def system_pieces(self) -> list[str]:
        """Pieces the server owns: the rivals and the developer's default."""
        return self.rival_pieces() + [self.default_piece]

    # ---- blocks and the demo clock ------------------------------------------------------

    @property
    def demo_factor(self) -> float:
        return float(self.data["demo_seconds_per_real_second"])

    @property
    def block_seconds(self) -> float:
        """3 demo hours at 60x = 180 real seconds."""
        return float(self.data["block_demo_hours"]) * 3600.0 / self.demo_factor

    def demo_start_for(self, epoch: datetime) -> datetime:
        """The demo wall clock that the epoch stands for: the epoch's date at 14:00."""
        hh, mm = (self.data["demo_clock"]["start_time"].split(":") + ["0"])[:2]
        return datetime.combine(epoch.astimezone(UTC).date(),
                                dtime(int(hh), int(mm)), tzinfo=UTC)

    @property
    def demo_clock_label(self) -> str:
        return self.data["demo_clock"]["label"]

    # ---- packs, telemetry, misc ----------------------------------------------------------

    @property
    def packs(self) -> dict[str, Any]:
        return self.data["packs"]

    @property
    def max_pack_bytes(self) -> int:
        return int(self.packs["max_bytes"])

    @property
    def engine_version(self) -> str:
        return str(self.packs["engine_version"])

    @property
    def allowed_ratings(self) -> list[str]:
        return list(self.packs["allowed_ratings"])

    @property
    def pacing_seconds(self) -> float:
        return float(self.packs.get("pacing_seconds", 0.0))

    @property
    def url_ttl_s(self) -> int:
        return int(self.packs.get("url_ttl_s", 300))

    @property
    def manifest_ttl_s(self) -> int:
        return int(self.packs.get("manifest_ttl_s", 300))

    @property
    def freeze_seconds(self) -> float:
        return float(self.data.get("sabotage", {}).get("freeze_seconds", 5.0))

    @property
    def telemetry_types(self) -> list[str]:
        return list(self.data["telemetry"]["types"])

    @property
    def wallet_start(self) -> int:
        return int(self.data["wallet"])

    @property
    def admin_key(self) -> str | None:
        return self.data.get("server", {}).get("admin_key")

    @property
    def poll_interval_s(self) -> float:
        return float(self.data["client"]["poll_interval_s"])

    @property
    def mode(self) -> str:
        return str(self.data.get("mode", "local"))

    @property
    def main_region(self) -> str:
        """The region the booth's main screen plays as."""
        return self.data.get("booth", {}).get("main_region") or self.regions[0]

    @property
    def preview_region(self) -> str:
        """The region the preview copy of the game starts as."""
        return (self.data.get("booth", {}).get("preview_default_region")
                or self.regions[min(1, len(self.regions) - 1)])

    # ---- validation -----------------------------------------------------------------------

    def validate(self) -> None:
        d = self.data
        for key in ("regions", "size_classes", "games", "footfall", "rivals", "default_content",
                    "brand_presets", "auction", "wallet", "block_demo_hours",
                    "demo_seconds_per_real_second", "demo_clock", "packs", "telemetry",
                    "client", "server"):
            if key not in d:
                raise ConfigError(f"config is missing '{key}'")
        if not d["regions"]:
            raise ConfigError("config has no regions")
        if not self._slots:
            raise ConfigError("config has no slots")
        for slot in self._slots.values():
            if slot.size_class not in d["size_classes"]:
                raise ConfigError(f"slot {slot.id} has unknown size class {slot.size_class}")
            if slot.id not in d["footfall"]:
                raise ConfigError(f"slot {slot.id} has no footfall row")
            missing = [r for r in self.regions if r not in d["footfall"][slot.id]]
            if missing:
                raise ConfigError(f"footfall for {slot.id} is missing regions {missing}")
        for region in self.regions:
            rival = d["rivals"].get(region)
            if not rival:
                raise ConfigError(f"region {region} has no rival")
            for key in ("colour", "emblem", "pieces"):
                if key not in rival:
                    raise ConfigError(f"rival {region} is missing '{key}'")
            for key in ("large", "small"):
                if key not in rival["pieces"]:
                    raise ConfigError(f"rival {region} has no '{key}' piece")
        booth = d.get("booth", {})
        for key in ("main_region", "preview_default_region"):
            if booth.get(key) and booth[key] not in self.regions:
                raise ConfigError(f"booth.{key} is not a region: {booth[key]}")
        if self.demo_factor <= 0:
            raise ConfigError("demo_seconds_per_real_second must be positive")
        if self.block_seconds <= 0:
            raise ConfigError("block length must be positive")
        if not self.allowed_ratings:
            raise ConfigError("packs.allowed_ratings is empty — nothing could ever be approved")
