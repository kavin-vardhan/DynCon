"""Fixtures. Every test drives the real app with a fake clock and its own data folder.

The `.dcpack` files the tests upload are built by the real generator
(`tools/make_fake_packs.py`) with the filler turned down to a few tens of KB, so the tests
exercise the shipped generator and the shipped art manifests rather than a second copy of
the piece table.
"""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent
for extra in (SERVER_DIR, SERVER_DIR / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from dcserver.app import create_app                      # noqa: E402
from dcserver.clock import FakeClock                     # noqa: E402
from dcserver.config import Config                       # noqa: E402
from dcserver.signing import KeyStore                    # noqa: E402

import make_fake_packs                                   # noqa: E402

CONFIG_PATH = SERVER_DIR / "config" / "demo.json"
REAL_PACKS_DIR = REPO_DIR / "unreal" / "_packs"


@pytest.fixture(scope="session")
def keys_dir(tmp_path_factory) -> Path:
    """One RSA-2048 key pair for the whole session — generating it is the slow part."""
    path = tmp_path_factory.mktemp("keys")
    KeyStore(path).ensure()
    return path


@pytest.fixture(scope="session")
def demo_files(tmp_path_factory) -> Path:
    """"The brand's computer", with tiny filler: all 13 pieces plus the 2 built to fail."""
    out = tmp_path_factory.mktemp("demo_files")
    code = make_fake_packs.main(["--out", str(out), "--min-mb", "0.02", "--max-mb", "0.05",
                                 "--quiet"])
    assert code == 0
    return out


@pytest.fixture(scope="session")
def real_demo_files(tmp_path_factory) -> Path | None:
    """The real cooked packs, wrapped. None when unreal/_packs is not on this machine."""
    if not (REAL_PACKS_DIR / "content1_v1" / "pack.json").is_file():
        return None
    out = tmp_path_factory.mktemp("real_demo_files")
    assert make_fake_packs.main(["--out", str(out), "--real", "--plain-name", "--quiet"]) == 0
    return out


@dataclass
class Env:
    config: Config
    clock: FakeClock
    app: Any
    client: TestClient
    demo_files: Path
    data_dir: Path

    # ---- shortcuts the tests read better with -------------------------------------

    @property
    def svc(self):
        return self.app.state.svc

    def ok(self, response, *expected: int) -> dict:
        allowed = expected or (200,)
        assert response.status_code in allowed, f"{response.status_code}: {response.text[:400]}"
        return response.json() if response.content else {}

    def upload(self, filename: str, content_id: str | None = None) -> dict:
        blob = (self.demo_files / filename).read_bytes()
        where = f"/content/{content_id}/versions" if content_id else "/content"
        return self.ok(self.client.post(
            where, files={"file": (filename, blob, "application/octet-stream")}))

    def brand(self, colour: str = "#E23D3D", emblem: str = "star") -> dict:
        return self.ok(self.client.post("/brand", json={"colour": colour, "emblem": emblem}))

    def allocate(self, game: str, slot: str, region: str, content_id: str,
                 minutes: float | None = None, expect: int = 200) -> dict:
        body = {"game": game, "slot": slot, "region": region, "content_id": content_id}
        if minutes is not None:
            body["minutes"] = minutes
        return self.ok(self.client.post("/admin/allocate", json=body), expect)

    def changes(self, game: str = "A", region: str = "r1") -> dict:
        return self.ok(self.client.get("/changes", params={"game": game, "region": region}))

    def key(self, game: str, slot: str, region: str) -> str:
        return self.changes(game, region)["slots"][slot]

    def resolve(self, game: str = "A", slot: str = "A1", region: str = "r1",
                expect: int = 200) -> dict:
        return self.ok(self.client.get("/resolve", params={"game": game, "slot": slot,
                                                           "region": region}), expect)

    def public_pem(self) -> str:
        return self.ok(self.client.get("/client-config"))["public_key_pem"]

    def fetch(self, file_entry: dict, headers: dict | None = None):
        return self.client.get(file_entry["url"], headers=headers or {})


@pytest.fixture
def make_env(tmp_path, demo_files, keys_dir) -> Callable[..., Env]:
    """Factory so a test can ask for its own server with different tunables."""
    made: list[Env] = []

    def factory(*, files: Path | None = None, **overrides: Any) -> Env:
        config = Config.load(CONFIG_PATH)
        overrides.setdefault("packs", {}).setdefault("pacing_seconds", 0.0)
        overrides.setdefault("sabotage", {}).setdefault("freeze_seconds", 0.05)
        config = config.copy_with(**overrides)
        clock = FakeClock()
        data_dir = tmp_path / f"data{len(made)}"
        app = create_app(config, clock=clock, data_dir=data_dir,
                         demo_files=files or demo_files, keys=KeyStore(keys_dir))
        env = Env(config, clock, app, TestClient(app), files or demo_files, data_dir)
        made.append(env)
        return env

    yield factory
    for env in made:
        env.client.close()
        env.svc.repo.close()


@pytest.fixture
def env(make_env) -> Env:
    return make_env()


@pytest.fixture
def live_server(make_env):
    """A real uvicorn on a real socket — what the fake client and the exit test talk to."""
    import uvicorn

    started: list[Any] = []

    def factory(**overrides: Any):
        env = make_env(**overrides)
        config = uvicorn.Config(env.app, host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        started.append((server, thread))
        return env, f"http://127.0.0.1:{port}"

    yield factory
    for server, thread in started:
        server.should_exit = True
        thread.join(timeout=10)
