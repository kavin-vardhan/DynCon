"""Building the app. `create_app()` is what the tests use; `asgi.py` is what uvicorn runs."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import routes
from .blobs import Blobs
from .clock import Clock
from .config import Config
from .repo import Repo
from .service import Service, ServiceError
from .signing import KeyStore

VERSION = "1.0 (brief 007, part 1)"
SERVER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SERVER_DIR / "config" / "demo.json"
# The brand portal is a static folder next to server/ — same origin as the API, so the
# portal needs no CORS, no build step and no second process at the booth.
PORTAL_DIR = SERVER_DIR.parent / "portal"


def create_app(config: Config | str | Path | None = None, *, clock: Clock | None = None,
               repo: Repo | None = None, blobs: Blobs | None = None,
               keys: KeyStore | None = None, data_dir: str | Path | None = None,
               demo_files: str | Path | None = None,
               maps_dir: str | Path | None = None,
               portal_dir: str | Path | None = None) -> FastAPI:
    if config is None:
        config = DEFAULT_CONFIG
    if not isinstance(config, Config):
        config = Config.load(config)

    svc = Service(config, clock=clock, repo=repo, blobs=blobs, keys=keys,
                  data_dir=data_dir, demo_files=demo_files, maps_dir=maps_dir).startup()

    app = FastAPI(title="DynamicContents demo server", version=VERSION,
                  summary="The stand-in cloud: allocations, packs, signed manifests.")
    app.state.svc = svc
    app.include_router(routes.client)
    app.include_router(routes.portal)
    app.include_router(routes.admin)

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"error": exc.sentence, **exc.extra}, status_code=exc.status)

    # The portal, mounted last so it can never shadow an API route. html=True makes
    # /portal/ serve index.html. A missing folder is not an error: the server is the
    # game's backend first, and the tests build it from a temporary directory.
    portal_path = Path(portal_dir) if portal_dir else PORTAL_DIR
    if portal_path.is_dir():
        app.mount("/portal", StaticFiles(directory=portal_path, html=True), name="portal")
        app.state.portal_dir = portal_path
    else:
        app.state.portal_dir = None
        logging.getLogger("dcserver").warning(
            "no portal folder at %s — /portal/ will 404", portal_path)

    @app.get("/", include_in_schema=False)
    def index() -> dict[str, Any]:
        return {
            "name": "DynamicContents demo server", "version": VERSION,
            "mode": svc.config.mode,
            "docs": "/docs",
            "portal_ui": "/portal/" if app.state.portal_dir else None,
            "game_client": ["/client-config", "/changes", "/resolve", "/files/{pack}/{name}",
                            "/telemetry"],
            "portal": ["/config/public", "/brand", "/wallet", "/demo-files", "/content",
                       "/content/{id}/versions", "/games", "/games/{id}",
                       "/games/{id}/map", "/games/{id}/slots/{slot}/thumb",
                       "/games/register", "/bids",
                       "/bids/split", "/lots", "/lots/{id}", "/report", "/preview/region",
                       "/campaign/pause", "/status/live", "/clock"],
            "admin": ["/admin/health", "/admin/reset", "/admin/sabotage", "/admin/allocate",
                      "/admin/close-auction"],
        }

    logging.getLogger("dcserver").info(
        "ready: config=%s data=%s demo_files=%s key=%s",
        config.path, svc.paths.data_dir, svc.paths.demo_files, svc.keys.fingerprint())
    return app
