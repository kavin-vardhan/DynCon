"""The HTTP surface. Thin: every route turns arguments into a Service call and back.

Three groups, as in spec v1 §4 — the game client, the portal, and booth admin. Part 1 of the
build carries everything the game side needs end to end; the auction routes arrive in part 2.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import (APIRouter, Body, Depends, File, Form, Header, Query, Request,
                     UploadFile)
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .service import Service, ServiceError
from .signing import UrlExpired, UrlSignatureError

client = APIRouter(tags=["game client"])
portal = APIRouter(tags=["portal"])
admin = APIRouter(prefix="/admin", tags=["admin"])


def get_svc(request: Request) -> Service:
    return request.app.state.svc


def admin_guard(request: Request, x_dc_admin_key: str | None = Header(default=None)) -> None:
    """Local mode has no key; AWS mode sets one in config and the booth UI sends it."""
    expected = get_svc(request).config.admin_key
    if expected and x_dc_admin_key != expected:
        raise ServiceError(403, "This endpoint is for booth staff.")


# ======================================================================== game client

@client.get("/client-config")
def client_config(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.client_config()


@client.get("/changes")
def changes(game: str = Query(...), region: str = Query(...),
            svc: Service = Depends(get_svc)) -> dict[str, Any]:
    svc.tick()                       # the game's poll is what closes a due auction
    return svc.changes(game, region)


@client.get("/resolve")
def resolve(game: str = Query(...), slot: str = Query(...), region: str = Query(...),
            svc: Service = Depends(get_svc)) -> dict[str, Any]:
    """The signed-payload envelope, and only that.

    There used to be a `?format=flat` that returned the manifest's fields with the signature
    alongside them, so that a client and a server could be one brief apart. The UE client is
    on the envelope now (brief 011), so the second shape is gone: two ways to sign the same
    answer is two ways to get it wrong.
    """
    svc.tick()                       # a resolve is also when a due auction gets settled
    return svc.resolve(game, slot, region)


def parse_range(header: str | None, total: int) -> tuple[int, int, bool]:
    """One byte range, inclusive. (0, total-1, False) when the client asked for the lot."""
    if not header:
        return 0, max(total - 1, 0), False
    value = header.strip()
    if not value.lower().startswith("bytes="):
        raise ServiceError(416, "Only byte ranges are supported.")
    spec = value.split("=", 1)[1].split(",")[0].strip()
    try:
        if spec.startswith("-"):                       # the last N bytes
            length = int(spec[1:])
            if length <= 0:
                raise ValueError
            start, end = max(total - length, 0), total - 1
        else:
            first, _, last = spec.partition("-")
            start = int(first)
            end = int(last) if last else total - 1
    except ValueError:
        raise ServiceError(416, f"'{header}' is not a byte range this server understands.")
    if start < 0 or start >= max(total, 1) or end < start:
        raise ServiceError(416, f"Range {start}-{end} is outside a {total}-byte file.")
    return start, min(end, total - 1), True


async def paced_stream(svc: Service, pack: dict[str, Any], name: str, file_total: int,
                       start: int, end: int, sabotage: str | None):
    """The bytes, paced so that one whole pack takes about `pacing_seconds`.

    The rate comes from the size of the **pack**, not of the file, so the three files of a
    pack together take ~4 s — a 0.3 MB real pack and a 30 MB fake one both pace the same.
    Sabotage lives here too: `corrupt` flips one byte, `freeze` stalls halfway and then
    stops short of the Content-Length it promised, which drops the connection.
    """
    pacing = svc.config.pacing_seconds
    pack_bytes = max(int(pack["total_bytes"]), 1)
    rate = pack_bytes / pacing if pacing > 0 else 0.0
    asked = end - start + 1

    flip_at = None
    if sabotage == "corrupt":
        middle = file_total // 2
        flip_at = middle if start <= middle <= end else start
    freeze_at = start + asked // 2 if sabotage == "freeze" else None

    sent = 0
    t0 = time.monotonic()
    for chunk in svc.blobs.read_range(pack["id"], name, start, end):
        pos = start + sent
        if flip_at is not None and pos <= flip_at < pos + len(chunk):
            patched = bytearray(chunk)
            patched[flip_at - pos] ^= 0x01
            chunk = bytes(patched)
        if rate:
            ahead = (sent + len(chunk)) / rate - (time.monotonic() - t0)
            if ahead > 0:
                await asyncio.sleep(ahead)
        if freeze_at is not None and pos < freeze_at <= pos + len(chunk):
            head = chunk[:freeze_at - pos]           # stop in the middle of this chunk
            if head:
                yield head
            await asyncio.sleep(svc.config.freeze_seconds)
            return                                   # short body: the connection drops
        yield chunk
        sent += len(chunk)


@client.get("/files/{pack_id}/{name}")
async def files(pack_id: str, name: str, request: Request, exp: int = Query(...),
                sig: str = Query(...), svc: Service = Depends(get_svc)):
    try:
        svc.keys.url_signer.verify(pack_id, name, exp, sig, svc.now())
    except UrlSignatureError as bad:
        return JSONResponse({"error": bad.sentence,
                             "expired": isinstance(bad, UrlExpired)}, status_code=403)
    pack = svc.repo.get_pack(pack_id)
    if not pack:
        raise ServiceError(404, f"There is no pack {pack_id} on this server.")
    entry = next((f for f in pack["files"] if f["name"] == name), None)
    if not entry or not svc.blobs.exists(pack_id, name):
        raise ServiceError(404, f"Pack {pack_id} has no file called {name}.")

    total = int(entry["size"])
    start, end, ranged = parse_range(request.headers.get("range"), total)
    length = end - start + 1
    sabotage = svc.consume_sabotage()
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "no-store",
        "X-DC-Pack": pack_id,
        "X-DC-Sha256": entry.get("sha256", ""),
    }
    if ranged:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    if sabotage:
        headers["X-DC-Sabotage"] = sabotage
    if sabotage == "freeze":
        # the body is going to stop halfway, so do not promise a length: the client sees a
        # chunked response that ends early, which is exactly what a dropped download is
        headers.pop("Content-Length")
    return StreamingResponse(
        paced_stream(svc, pack, name, total, start, end, sabotage),
        status_code=206 if ranged else 200,
        headers=headers, media_type="application/octet-stream")


@client.post("/telemetry")
def telemetry(body: Any = Body(...), svc: Service = Depends(get_svc)) -> dict[str, Any]:
    events = body.get("events", []) if isinstance(body, dict) else body
    if not isinstance(events, list):
        raise ServiceError(400, "Telemetry is a list of events.")
    return svc.telemetry(events)


# ============================================================================== portal

class BrandIn(BaseModel):
    colour: str
    emblem: str


class PauseIn(BaseModel):
    paused: bool


class PreviewIn(BaseModel):
    region: str


# The map and the thumbnails are drawn here as SVG — no image library, no binary assets in
# git — and are replaced by the real ones the moment the UE slot-map tool writes them.
PIN_COLOURS = ["#2EA44F", "#F2C230", "#E23D3D"]      # low, middle, high footfall


def placeholder_map(svc: Service, game: str) -> str:
    cfg = svc.config
    if game not in cfg.games:
        raise ServiceError(404, f"There is no game {game}.")
    w, h = 1600, 900
    slots = cfg.slots_of(game)
    ranked = sorted(slots, key=lambda s: cfg.footfall(s.id, cfg.main_region))
    rank = {s.id: i for i, s in enumerate(ranked)}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">',
        f'<rect width="{w}" height="{h}" fill="#10151c"/>',
    ]
    for x in range(0, w, 80):
        parts.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{h}" stroke="#1b232e" stroke-width="2"/>')
    for y in range(0, h, 80):
        parts.append(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}" stroke="#1b232e" stroke-width="2"/>')
    parts.append(f'<text x="40" y="70" fill="#5d6b7d" font-family="sans-serif" '
                 f'font-size="34">{cfg.game_label(game)} — placeholder map</text>')
    for slot in slots:
        px = svc.slot_px(game, slot.id)
        cx, cy = int(px["x"] * w), int(px["y"] * h)
        colour = PIN_COLOURS[min(rank[slot.id] * len(PIN_COLOURS) // max(len(slots), 1),
                                 len(PIN_COLOURS) - 1)]
        parts += [
            f'<circle cx="{cx}" cy="{cy}" r="46" fill="{colour}" fill-opacity="0.18" '
            f'stroke="{colour}" stroke-width="4"/>',
            f'<circle cx="{cx}" cy="{cy}" r="8" fill="{colour}"/>',
            f'<text x="{cx}" y="{cy + 86}" fill="#e8eef6" font-family="sans-serif" '
            f'font-size="40" text-anchor="middle">{slot.id}</text>',
            f'<text x="{cx}" y="{cy + 122}" fill="#8b9aae" font-family="sans-serif" '
            f'font-size="26" text-anchor="middle">{slot.size_class}</text>',
        ]
    parts.append("</svg>")
    return "".join(parts)


def placeholder_thumb(svc: Service, slot_id: str) -> str:
    cfg = svc.config
    slot = cfg.slot(slot_id)
    limits = cfg.limits(slot.size_class)
    w, h = 480, 270
    return "".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">',
        f'<rect width="{w}" height="{h}" fill="#141a22"/>',
        f'<rect x="12" y="12" width="{w - 24}" height="{h - 24}" fill="none" '
        f'stroke="#2b3542" stroke-width="3"/>',
        f'<rect x="150" y="120" width="180" height="110" fill="#1f2a36" stroke="#3a4a5c" '
        f'stroke-width="3"/>',
        f'<text x="{w // 2}" y="78" fill="#e8eef6" font-family="sans-serif" font-size="56" '
        f'text-anchor="middle">{slot.id}</text>',
        f'<text x="{w // 2}" y="{h - 28}" fill="#8b9aae" font-family="sans-serif" '
        f'font-size="22" text-anchor="middle">class {slot.size_class} · '
        f'{limits["x"]:.0f} x {limits["y"]:.0f} x {limits["z"]:.0f} m</text>',
        "</svg>",
    ])


@portal.get("/config/public")
def config_public(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.public_config()


@portal.get("/clock")
def clock(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.clock_block()


@portal.get("/brand")
def get_brand(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return {"brand": svc.repo.get_brand(), "wallet": svc.wallet(),
            "presets": svc.config.data["brand_presets"]}


@portal.post("/brand")
def post_brand(body: BrandIn, svc: Service = Depends(get_svc)) -> dict[str, Any]:
    brand = svc.set_brand(body.colour, body.emblem)
    return {"brand": brand, "wallet": svc.wallet()}


@portal.get("/wallet")
def wallet(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.wallet()


@portal.get("/demo-files")
def demo_files(purpose: str = Query("upload", pattern="^(upload|update)$"),
               svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return {"purpose": purpose, "files": svc.demo_files(purpose)}


@portal.get("/demo-files/{name}")
def demo_file(name: str, svc: Service = Depends(get_svc)):
    path = svc.demo_file_path(name)
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@portal.post("/content")
async def post_content(file: UploadFile = File(...),
                       svc: Service = Depends(get_svc)) -> dict[str, Any]:
    blob = await file.read()
    return svc.upload_content(blob, filename=file.filename)


@portal.get("/content")
def get_content(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.my_content()


@portal.post("/content/{content_id}/versions")
async def post_content_version(content_id: str, file: UploadFile = File(...),
                               svc: Service = Depends(get_svc)) -> dict[str, Any]:
    blob = await file.read()
    return svc.upload_version(content_id, blob, filename=file.filename)


@portal.post("/campaign/pause")
def campaign_pause(body: PauseIn, svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.set_paused(body.paused)


@portal.get("/status/live")
def status_live(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    svc.tick()
    return {"server_time": svc.clock_block()["server_time"], "showing": svc.live_status()}


# ---- games and the slot map -----------------------------------------------------------

@portal.get("/games")
def games(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.games()


@portal.get("/games/{game}")
def game(game: str, svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.game_card(game)


@portal.post("/games/register")
async def register_game(data: str = Form(...), map_image: UploadFile = File(...),
                        thumbs: list[UploadFile] = File(default=[]),
                        svc: Service = Depends(get_svc)) -> dict[str, Any]:
    """The developer's slot-map tool, arriving (`dcserver/registry.py` has the long version).

    Multipart, because two of the three parts are pictures: `data` is the JSON the tool
    wrote, `map_image` is the orthographic capture, and `thumbs` is one eye-level PNG per
    slot. Each thumbnail is matched to its slot by its **file name** (`<game>_<slot>.png`)
    rather than by its position in the request, so the order the tool sends them in cannot
    quietly mis-label them.
    """
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as bad:
        raise ServiceError(400, f"The registration JSON would not parse: {bad}")
    blobs: dict[str, bytes] = {}
    for upload in thumbs:
        name = Path(upload.filename or "").name
        if not name:
            raise ServiceError(400, "A thumbnail arrived with no file name.")
        blobs[name] = await upload.read()
    return svc.register_game(payload, await map_image.read(), blobs)


@portal.get("/games/{game}/map")
def game_map(game: str, svc: Service = Depends(get_svc)):
    """The real map image once the slot-map tool has registered one; a drawn placeholder
    until then, so the portal always has something to put a pin on."""
    real = svc.map_file(game)
    if real:
        return FileResponse(real, media_type="image/png",
                            headers={"Cache-Control": "no-store"})
    return Response(content=placeholder_map(svc, game), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@portal.get("/games/{game}/slots/{slot}/thumb")
def slot_thumb(game: str, slot: str, svc: Service = Depends(get_svc)):
    """The eye-level photograph of the empty spot, or the drawn card until it is registered."""
    real = svc.thumb_file(game, slot)
    if real:
        return FileResponse(real, media_type="image/png",
                            headers={"Cache-Control": "no-store"})
    return Response(content=placeholder_thumb(svc, slot), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


# ---- the auction ----------------------------------------------------------------------

class RegionBid(BaseModel):
    region: str
    amount: int
    lot_id: str | None = None        # what the portal was showing, if it knows


class BidsIn(BaseModel):
    slot: str
    content_id: str
    bids: list[RegionBid]


@portal.post("/bids")
def post_bids(body: BidsIn, svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.place_bids(body.slot, body.content_id,
                          [b.model_dump() for b in body.bids])


@portal.get("/bids/split")
def split_bid(slot: str = Query(...), total: int = Query(..., gt=0),
              regions: str = Query(...), svc: Service = Depends(get_svc)) -> dict[str, Any]:
    """One total across ticked regions, split by footfall — the portal's shortcut."""
    return svc.split_bid(slot, total, [r.strip() for r in regions.split(",") if r.strip()])


@portal.get("/lots")
def lots(game: str | None = Query(None), slot: str | None = Query(None),
         region: str | None = Query(None), svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.lots(game, slot, region)


@portal.get("/lots/{lot_id}")
def lot(lot_id: str, svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.lot(lot_id)


# ---- the report and the preview window ------------------------------------------------

@portal.get("/report")
def report(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.report()


@portal.get("/preview/region")
def get_preview_region(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.preview_region()


@portal.post("/preview/region")
def post_preview_region(body: PreviewIn, svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.set_preview_region(body.region)


# =============================================================================== admin

class SabotageIn(BaseModel):
    mode: str = Field(description="corrupt | freeze | none")


class AllocateIn(BaseModel):
    game: str
    slot: str
    region: str
    content_id: str
    minutes: float | None = None


class CloseAuctionIn(BaseModel):
    lot_id: str = Field(default="all", description='a lot id, or "all"')


@admin.get("/health")
def health(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.health()


@admin.post("/reset", dependencies=[Depends(admin_guard)])
def reset(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.reset()


@admin.post("/sabotage", dependencies=[Depends(admin_guard)])
def sabotage(body: SabotageIn, svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.arm_sabotage(body.mode)


@admin.post("/allocate", dependencies=[Depends(admin_guard)])
def allocate(body: AllocateIn, svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.allocate(body.game, body.slot, body.region, body.content_id, body.minutes)


@admin.post("/close-auction", dependencies=[Depends(admin_guard)])
def close_auction(body: CloseAuctionIn, svc: Service = Depends(get_svc)) -> dict[str, Any]:
    """Booth staff: settle a lot now instead of waiting for its clock."""
    return svc.close_auction(body.lot_id)
