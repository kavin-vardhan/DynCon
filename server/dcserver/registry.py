"""Game registration: what the developer's slot-map tool hands the platform.

`POST /games/register` is the third actor in the story. A brand uploads content and bids; the
platform resolves and delivers; and **the game developer registers the game, its slots and
the rule for each slot** — which is what makes the portal able to show a brand a picture of
the spot it is bidding on instead of a drawing of one.

What arrives is one multipart POST from `UDCSlotMapTool` (the editor half of the UE plugin):

* `data`       — the JSON the tool wrote: the capture's own geometry plus one block per slot
                 (id, size class, class limits, rating rule, pre-fetch radius, world
                 position, and the **pixel position** on the capture);
* `map_image`  — the straight-down orthographic PNG of the playable area;
* `thumbs`     — one eye-level PNG per slot, named `<game>_<slot>.png`.

Where it goes, and why there: **`server/config/maps/`**, committed to the repo, next to
`demo.json`. A registration is the developer's, not the visitor's: `POST /admin/reset`
between visitors must not wipe it, and a clean checkout has to serve the real pictures
without anyone running Unreal first. Both of those fall out of keeping it in `config/`
rather than in `data/`.

Everything here is files and plain dicts — no database — so the record and the images travel
together and a human can look at either.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# A registration is a few pictures, not a content pack. 2048 px of lit map is ~4 MB and a
# 960 px thumbnail ~1 MB, so this is generous; it is here so a mistyped request cannot fill
# the config folder.
MAX_IMAGE_BYTES = 32 * 1024 * 1024

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class RegistryError(Exception):
    """Something about the registration is wrong, with a sentence for the developer."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


def png_size(blob: bytes) -> tuple[int, int]:
    """Width and height straight out of the IHDR chunk — no image library needed."""
    if len(blob) < 24 or not blob.startswith(PNG_MAGIC):
        raise RegistryError("that is not a PNG file.")
    if blob[12:16] != b"IHDR":
        raise RegistryError("that PNG does not start with an IHDR chunk.")
    width = int.from_bytes(blob[16:20], "big")
    height = int.from_bytes(blob[20:24], "big")
    if width <= 0 or height <= 0:
        raise RegistryError("that PNG says it is zero pixels across.")
    return width, height


def _check_image(name: str, blob: bytes) -> tuple[int, int]:
    if not blob:
        raise RegistryError(f"{name} arrived empty.")
    if len(blob) > MAX_IMAGE_BYTES:
        raise RegistryError(
            f"{name} is {len(blob) / 1048576:.1f} MB; the limit is "
            f"{MAX_IMAGE_BYTES // 1048576} MB.")
    return png_size(blob)


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RegistryError(f"{what} is not a number.")
    return float(value)


def _xyz(block: Any, what: str) -> dict[str, float]:
    if not isinstance(block, dict):
        raise RegistryError(f"{what} is not an object with x, y and z in it.")
    return {k: _number(block.get(k), f"{what}.{k}") for k in ("x", "y", "z")}


@dataclass
class Registry:
    """The registrations on disk. One folder, one JSON file and its images per game."""

    maps_dir: Path

    # ---- reading -------------------------------------------------------------------

    def record_path(self, game: str) -> Path:
        return self.maps_dir / f"{game}.json"

    def record(self, game: str) -> dict[str, Any] | None:
        """The stored registration for a game, or None when it was never registered.

        Deliberately re-read per call: it is a 2 kB file, it changes when a developer runs
        the tool, and a cache that has to be invalidated is how a stale pin position outlives
        the capture it came from.
        """
        path = self.record_path(game)
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None
        return record if isinstance(record, dict) and record.get("slots") else None

    def games(self) -> list[str]:
        if not self.maps_dir.is_dir():
            return []
        return sorted(p.stem for p in self.maps_dir.glob("*.json"))

    def is_registered(self, game: str) -> bool:
        return self.record(game) is not None

    def map_image(self, game: str) -> Path | None:
        record = self.record(game)
        if not record:
            return None
        name = record.get("image")
        if not isinstance(name, str) or not SAFE_NAME.match(name):
            return None
        path = self.maps_dir / name
        return path if path.is_file() else None

    def thumb(self, game: str, slot: str) -> Path | None:
        record = self.record(game)
        if not record:
            return None
        entry = (record.get("slots") or {}).get(slot)
        name = (entry or {}).get("thumb")
        if not isinstance(name, str) or not SAFE_NAME.match(name):
            return None
        path = self.maps_dir / name
        return path if path.is_file() else None

    def slot(self, game: str, slot: str) -> dict[str, Any] | None:
        record = self.record(game)
        if not record:
            return None
        return (record.get("slots") or {}).get(slot)

    # ---- writing -------------------------------------------------------------------

    def register(self, payload: dict[str, Any], map_blob: bytes,
                 thumbs: dict[str, bytes], *, known_slots: dict[str, str],
                 now_iso: str) -> dict[str, Any]:
        """Validate, store and return what was stored.

        `known_slots` is the platform's own slot table for this game (id -> size class).
        A slot the platform has never heard of is a hard error rather than a warning: it
        means the level and the platform disagree about what this game *is*, and silently
        dropping it would leave a slot nobody can bid on and nobody can see.
        """
        if not isinstance(payload, dict):
            raise RegistryError("the registration JSON is not an object.")

        game = str(payload.get("game") or "").strip()
        if not game:
            raise RegistryError("the registration does not say which game it is for.")
        if not SAFE_NAME.match(game):
            raise RegistryError(f"'{game}' is not a usable game id.")

        slots_in = payload.get("slots")
        if not isinstance(slots_in, list) or not slots_in:
            raise RegistryError("the registration has no slots in it.")

        image_name = f"{game}.png"
        image_w, image_h = _check_image(image_name, map_blob)

        warnings: list[str] = []
        stored_slots: dict[str, Any] = {}
        files: dict[str, bytes] = {image_name: map_blob}
        order: list[str] = []

        for raw in slots_in:
            if not isinstance(raw, dict):
                raise RegistryError("a slot in the registration is not an object.")
            slot_id = str(raw.get("id") or "").strip()
            if not slot_id or not SAFE_NAME.match(slot_id):
                raise RegistryError(f"'{slot_id}' is not a usable slot id.")
            if slot_id in stored_slots:
                raise RegistryError(f"slot {slot_id} is in the registration twice.")
            if slot_id not in known_slots:
                raise RegistryError(
                    f"this platform has no slot {slot_id} in game {game}. It knows "
                    f"{', '.join(sorted(known_slots)) or 'none'} — the level and the "
                    f"platform disagree about what game {game} is.")

            size_class = str(raw.get("size_class") or "").strip()
            if size_class and size_class != known_slots[slot_id]:
                warnings.append(
                    f"slot {slot_id} is class {size_class} in the level but "
                    f"{known_slots[slot_id]} on the platform; the platform's wins")

            px = raw.get("px")
            if not isinstance(px, dict):
                raise RegistryError(f"slot {slot_id} has no pixel position.")
            px_x = _number(px.get("x"), f"slot {slot_id} px.x")
            px_y = _number(px.get("y"), f"slot {slot_id} px.y")
            if not (0.0 <= px_x <= 1.0 and 0.0 <= px_y <= 1.0):
                raise RegistryError(
                    f"slot {slot_id} lands at ({px_x:.3f}, {px_y:.3f}) on the map image, "
                    f"which is outside it — the capture does not contain the slot.")

            thumb_name = f"{game}_{slot_id}.png"
            thumb_blob = thumbs.get(thumb_name)
            if thumb_blob is None:
                raise RegistryError(
                    f"slot {slot_id} has no thumbnail; the tool should have sent "
                    f"{thumb_name}.")
            thumb_w, thumb_h = _check_image(thumb_name, thumb_blob)
            files[thumb_name] = thumb_blob

            entry: dict[str, Any] = {
                "size_class": known_slots[slot_id],
                "px": {"x": round(px_x, 6), "y": round(px_y, 6)},
                "thumb": thumb_name,
                "thumb_px": {"w": thumb_w, "h": thumb_h},
            }
            if isinstance(raw.get("limits_m"), dict):
                entry["limits_m"] = _xyz(raw["limits_m"], f"slot {slot_id} limits_m")
            if raw.get("rating_rule") is not None:
                entry["rating_rule"] = str(raw["rating_rule"])
            if raw.get("prefetch_radius_m") is not None:
                entry["prefetch_radius_m"] = _number(
                    raw["prefetch_radius_m"], f"slot {slot_id} prefetch_radius_m")
            if isinstance(raw.get("world_m"), dict):
                entry["world_m"] = _xyz(raw["world_m"], f"slot {slot_id} world_m")
            if raw.get("facing_deg") is not None:
                entry["facing_deg"] = _number(raw["facing_deg"], f"slot {slot_id} facing_deg")
            if isinstance(raw.get("thumb"), dict):
                entry["thumb_camera"] = raw["thumb"]

            stored_slots[slot_id] = entry
            order.append(slot_id)

        extra_thumbs = sorted(set(thumbs) - set(files))
        if extra_thumbs:
            warnings.append(
                f"ignored {len(extra_thumbs)} thumbnail(s) that belong to no slot: "
                f"{', '.join(extra_thumbs)}")
        missing = sorted(set(known_slots) - set(stored_slots))
        if missing:
            warnings.append(
                f"game {game} also has slot(s) {', '.join(missing)} on the platform, and "
                f"this registration does not cover them; they keep their drawn placeholder")

        record = {
            "schema_version": SCHEMA_VERSION,
            "game": game,
            "registered_utc": now_iso,
            "image": image_name,
            "image_px": {"w": image_w, "h": image_h},
            "slot_order": order,
            "slots": stored_slots,
            "source": {
                key: payload.get(key)
                for key in ("map", "captured_utc", "engine_version", "tool", "world",
                            "schema_version")
                if payload.get(key) is not None
            },
            "warnings": warnings,
        }

        # Write the images first, then the record: the record is what makes a registration
        # exist, so a run that dies halfway leaves the old one serving rather than a record
        # pointing at files that are not there yet.
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        for name, blob in files.items():
            self._write_atomic(self.maps_dir / name, blob)
        self._write_atomic(
            self.record_path(game),
            (json.dumps(record, indent=1, sort_keys=False) + "\n").encode("utf-8"))

        return {
            "ok": True,
            "game": game,
            "image": {"file": image_name, "width": image_w, "height": image_h,
                      "bytes": len(map_blob), "url": f"/games/{game}/map"},
            "slots": [
                {"id": slot_id, "size_class": stored_slots[slot_id]["size_class"],
                 "px": stored_slots[slot_id]["px"],
                 "thumb_url": f"/games/{game}/slots/{slot_id}/thumb"}
                for slot_id in order
            ],
            "warnings": warnings,
            "stored_in": str(self.maps_dir),
            "registered_utc": now_iso,
        }

    @staticmethod
    def _write_atomic(path: Path, blob: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(blob)
        tmp.replace(path)
