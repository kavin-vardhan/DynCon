"""The HTTP surface. Thin: every route turns arguments into a Service call and back.

Three groups, as in spec v1 §4 — the game client, the portal, and booth admin. Part 1 of the
build carries everything the game side needs end to end; the auction routes arrive in part 2.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
    return svc.changes(game, region)


@client.get("/resolve")
def resolve(game: str = Query(...), slot: str = Query(...), region: str = Query(...),
            svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return svc.manifest(game, slot, region)


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
def demo_files(svc: Service = Depends(get_svc)) -> dict[str, Any]:
    return {"files": svc.demo_files()}


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
    return {"server_time": svc.clock_block()["server_time"], "showing": svc.live_status()}


# =============================================================================== admin

class SabotageIn(BaseModel):
    mode: str = Field(description="corrupt | freeze | none")


class AllocateIn(BaseModel):
    game: str
    slot: str
    region: str
    content_id: str
    minutes: float | None = None


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
