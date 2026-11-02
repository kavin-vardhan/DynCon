"""Stage-1 exit test, UE side (demo plan v6 §14 step 1, brief 011).

*"A hand-written allocation makes the content appear, ten times out of ten."* - this time in
the real packaged game instead of the fake client.

What it does:

1. starts the demo server on a clean data folder, so every pack it serves is one of the real
   cooked packs in `server\\demo_files\\*.real.dcpack`;
2. uploads the four visitor pieces and sets a brand;
3. starts the **packaged Shipping build**, which contains none of the content, pointed at the
   server, and leaves it running for the whole test - one process, no restarts;
4. writes ten allocations by hand through `POST /admin/allocate` (and one brand change, one
   version-2 push, one region switch and one corrupt-pack sabotage), and after each one waits
   for the game's own status file to say that the right piece, version and brand went on
   screen in the right slot;
5. times **allocation written -> visible in game** for every round;
6. tells the game to stop, stops the server, and prints the table.

    python\\python.exe unreal\\Tools\\ue_exit_test.py
    python\\python.exe unreal\\Tools\\ue_exit_test.py --port 8701 --keep-server-data
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

REPO = Path(__file__).resolve().parent.parent.parent
SERVER_DIR = REPO / "server"
sys.path.insert(0, str(REPO / "tools"))
import dc_paths                                                          # noqa: E402

PYTHON = dc_paths.demo_python()
EXE = dc_paths.game_exe()
OUT_DIR = REPO / "unreal" / "_build" / "runtime" / "exit_test"
LOG_DIR = REPO / "unreal" / "_build" / "logs"

MAP = "/Game/Maps/DCRuntime"
LONG_MINUTES = 30.0          # rounds must not expire while the test is still running
BRAND1 = {"colour": "#E23D3D", "emblem": "star"}
BRAND2 = {"colour": "#2F6FEB", "emblem": "chevron"}

# Which piece the test uploads for each slot class. content3 only fits the tall slot, content4
# is the only visitor piece that fits the small one, by the config's size classes.
UPLOADS = ["content1_v1.real.dcpack", "content2_v1.real.dcpack",
           "content3_v1.real.dcpack", "content4_v1.real.dcpack"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(text: str) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class Round:
    n: int
    what: str
    slot: str
    region: str
    piece: str
    version: str
    brand: str = ""
    emblem: str = ""
    before: Callable[["ExitTest"], None] | None = None
    expect_fallback: str = ""

    ok: bool = False
    detail: str = ""
    seconds_to_visible: float = 0.0
    shot: str = ""
    activation: dict[str, Any] = field(default_factory=dict)
    fallback: dict[str, Any] = field(default_factory=dict)


class ExitTest:
    def __init__(self, args: argparse.Namespace):
        self.port = args.port
        self.url = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.url, timeout=120.0)
        self.keep_server_data = args.keep_server_data
        self.server_data = Path(args.server_data or (Path(os.environ["TEMP"]) / "dc_exit_test_data"))
        self.shot_dir = OUT_DIR / "shots"
        self.cache_dir = OUT_DIR / "packcache"
        self.status_file = OUT_DIR / "dc_status.json"
        self.quit_file = OUT_DIR / "dc_quit"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.dc_log = LOG_DIR / f"exit_test_{stamp}_dc.log"
        self.server_log = LOG_DIR / f"exit_test_{stamp}_server.log"
        self.server: subprocess.Popen | None = None
        self.game: subprocess.Popen | None = None
        self.content: dict[str, str] = {}
        self.res_x, self.res_y = args.res_x, args.res_y
        # When the thing that should make the content change was actually sent: what
        # "allocation written -> visible in game" is measured from.
        self.trigger_at: datetime | None = None

    def mark(self) -> None:
        self.trigger_at = utcnow()

    # ---- the server -------------------------------------------------------------------

    def api(self, method: str, path: str, **kw) -> dict[str, Any]:
        response = self.http.request(method, path, **kw)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {response.status_code} {response.text[:300]}")
        return response.json()

    def start_server(self) -> None:
        if not self.keep_server_data and self.server_data.exists():
            shutil.rmtree(self.server_data, ignore_errors=True)
        env = dict(os.environ, DCSERVER_DATA=str(self.server_data))
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        print(f"starting the server on 127.0.0.1:{self.port}  (data: {self.server_data})",
              flush=True)
        handle = open(self.server_log, "wb")
        self.server = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "dcserver.asgi:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "info"],
            cwd=str(SERVER_DIR), env=env, stdout=handle, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                health = self.api("GET", "/admin/health")
                packs = {p: v["version"] for p, v in health["system_packs"].items()}
                missing = [p for p, v in health["system_packs"].items() if not v["pack_id"]]
                if missing:
                    raise RuntimeError(f"the server has no pack for {', '.join(missing)}")
                print(f"server ok: mode={health['mode']} key={health['key_fingerprint']} "
                      f"system packs {packs}", flush=True)
                return
            except (httpx.HTTPError, RuntimeError):
                time.sleep(0.4)
        raise RuntimeError(f"the server never answered /admin/health - see {self.server_log}")

    def stop_server(self) -> None:
        if self.server and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.server.kill()
            print("server stopped", flush=True)

    def upload(self, filename: str, content_id: str | None = None) -> dict[str, Any]:
        path = SERVER_DIR / "demo_files" / filename
        if not path.is_file():
            raise RuntimeError(f"{path} is missing - run "
                               f"server\\tools\\make_fake_packs.py --real --force")
        files = {"file": (filename, path.read_bytes(), "application/octet-stream")}
        where = f"/content/{content_id}/versions" if content_id else "/content"
        result = self.api("POST", where, files=files)
        if result["status"] != "approved":
            raise RuntimeError(f"{filename} was rejected: {result.get('reason')}")
        if not content_id:
            self.content[filename] = result["content_id"]
        print(f"  uploaded {filename:28} -> {result['content_id']} {result['piece']} "
              f"{result['version']} ({result['pack']['total_bytes'] / 1024:.0f} KB, "
              f"pack {result['pack']['id']})", flush=True)
        return result

    def allocate(self, slot: str, region: str, content_id: str) -> dict[str, Any]:
        self.mark()
        return self.api("POST", "/admin/allocate",
                        json={"game": "A", "slot": slot, "region": region,
                              "content_id": content_id, "minutes": LONG_MINUTES})

    # ---- the game ---------------------------------------------------------------------

    def start_game(self) -> None:
        if not EXE.is_file():
            raise RuntimeError(f"no packaged build at {EXE} - run unreal\\Tools\\package.ps1")
        for path in (self.shot_dir, self.cache_dir):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)
        self.status_file.unlink(missing_ok=True)
        self.quit_file.unlink(missing_ok=True)

        args = [
            str(EXE),
            f"-DCMap={MAP}",
            "-windowed", f"-ResX={self.res_x}", f"-ResY={self.res_y}",
            f"-DCBackend={self.url}", "-DCGame=A", "-DCRegion=r1", "-DCFollowRegion",
            f"-DCShotDir={self.shot_dir}", f"-DCStatusFile={self.status_file}",
            f"-DCCacheDir={self.cache_dir}", f"-DCLogFile={self.dc_log}",
            f"-DCQuitWhenFileExists={self.quit_file}", "-DCRunSeconds=900",
        ]
        print("starting the packaged game (it contains none of the content)", flush=True)
        self.game = subprocess.Popen(dc_paths.game_cmdline(args))

    def stop_game(self) -> int:
        if not self.game:
            return 0
        self.quit_file.write_text("stop", encoding="utf-8")
        try:
            return self.game.wait(timeout=120)
        except subprocess.TimeoutExpired:
            print("the game would not stop - killing it", flush=True)
            self.game.kill()
            return self.game.wait(timeout=30)

    def status(self) -> dict[str, Any]:
        """The game's status file. It is written aside and moved into place, so a read that
        catches the move just gets retried."""
        for _ in range(12):
            try:
                return json.loads(self.status_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
        return {}

    def wait_for(self, predicate: Callable[[dict[str, Any]], Any], seconds: float,
                 what: str) -> Any:
        deadline = time.monotonic() + seconds
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            if self.game and self.game.poll() is not None:
                raise RuntimeError(f"the game exited (code {self.game.returncode}) while "
                                   f"waiting for {what}")
            last = self.status()
            found = predicate(last)
            if found:
                return found
            time.sleep(0.2)
        slots = {k: f"{v['state']} {v['piece']} {v['version']}"
                 for k, v in (last.get("slots") or {}).items()}
        raise TimeoutError(f"timed out after {seconds:.0f}s waiting for {what}; slots={slots}")

    # ---- the ten rounds ---------------------------------------------------------------

    def build_rounds(self) -> list[Round]:
        b1, e1 = BRAND1["colour"], BRAND1["emblem"]
        b2, e2 = BRAND2["colour"], BRAND2["emblem"]

        def alloc(slot: str, region: str, file: str):
            def go(test: "ExitTest"):
                test.allocate(slot, region, test.content[file])
            return go

        def switch_to_r2_then_alloc(test: "ExitTest"):
            test.api("POST", "/preview/region", json={"region": "r2"})
            print("    the portal moved this copy to region r2", flush=True)
            test.wait_for(lambda s: s.get("region") == "r2", 20, "the game to follow to r2")
            # Let the switch finish before the stopwatch starts: all three slots re-resolve
            # for the new region, and timing the allocation through the middle of that would
            # be timing the region change instead.
            time.sleep(3.0)
            test.wait_for(
                lambda s: len(s.get("slots", {})) == 3
                and all(v["state"] == "ACTIVE" for v in s["slots"].values()),
                120, "region r2 to settle in every slot")
            test.allocate("A1", "r2", test.content["content1_v1.real.dcpack"])

        def push_v2(test: "ExitTest"):
            before = test.api("GET", "/changes", params={"game": "A", "region": "r2"})["slots"]["A1"]
            test.mark()
            test.upload("content1_v2.real.dcpack",
                        content_id=test.content["content1_v1.real.dcpack"])
            after = test.api("GET", "/changes", params={"game": "A", "region": "r2"})["slots"]["A1"]
            if before == after:
                raise RuntimeError("alloc_key did not change when version 2 was pushed")
            print(f"    alloc_key A1/r2 {before} -> {after} (changed by the push)", flush=True)

        def change_brand(test: "ExitTest"):
            before = test.api("GET", "/changes", params={"game": "A", "region": "r2"})["slots"]["A1"]
            test.mark()
            test.api("POST", "/brand", json=BRAND2)
            after = test.api("GET", "/changes", params={"game": "A", "region": "r2"})["slots"]["A1"]
            if before == after:
                raise RuntimeError("alloc_key did not change when the brand changed")
            print(f"    alloc_key A1/r2 {before} -> {after} (changed by the new brand)", flush=True)

        def sabotage(test: "ExitTest"):
            # Version 2 of the small piece, so the round is a *real* download: version 1's
            # pack is already in the cache from round 3 and a cache hit would never give the
            # sabotage a download to corrupt.
            test.upload("content4_v2.real.dcpack",
                        content_id=test.content["content4_v1.real.dcpack"])
            # Put the developer's default up first, so "the default stays up" is literal.
            test.allocate("A3", "r2", "sys_default")
            test.wait_for(
                lambda s: (s.get("slots", {}).get("A3", {}).get("piece") == "default"
                           and s["slots"]["A3"]["state"] == "ACTIVE"),
                120, "the default to be showing in A3")
            armed = test.api("POST", "/admin/sabotage", json={"mode": "corrupt"})
            print(f"    default is up in A3; sabotage armed: {armed['armed']}", flush=True)
            test.allocate("A3", "r2", test.content["content4_v1.real.dcpack"])

        def rival(test: "ExitTest"):
            written = test.allocate("A3", "r2", "sys_rivalsmall")
            print(f"    allocation {written['allocation_id']} -> {written['kind']} "
                  f"{written['piece']} {written['version']}", flush=True)

        return [
            Round(1, "hand allocation, large slot", "A1", "r1", "content1", "v1", b1, e1,
                  before=alloc("A1", "r1", "content1_v1.real.dcpack")),
            Round(2, "tall piece in the tall slot", "A2", "r1", "content3", "v1", b1, e1,
                  before=alloc("A2", "r1", "content3_v1.real.dcpack")),
            Round(3, "small piece in the small slot", "A3", "r1", "content4", "v1", b1, e1,
                  before=alloc("A3", "r1", "content4_v1.real.dcpack")),
            Round(4, "swap: another piece into a slot that is already full", "A1", "r1",
                  "content2", "v1", b1, e1,
                  before=alloc("A1", "r1", "content2_v1.real.dcpack")),
            Round(5, "second region, and the pack is a cache hit", "A1", "r2",
                  "content1", "v1", b1, e1, before=switch_to_r2_then_alloc),
            Round(6, "tall piece, second region", "A2", "r2", "content3", "v1", b1, e1,
                  before=alloc("A2", "r2", "content3_v1.real.dcpack")),
            Round(7, "push version 2 onto the live allocation", "A1", "r2",
                  "content1", "v2", b1, e1, before=push_v2),
            Round(8, "new brand on the same allocation", "A1", "r2",
                  "content1", "v2", b2, e2, before=change_brand),
            Round(9, "corrupt pack: the default stays up, then a clean retry", "A3", "r2",
                  "content4", "v2", b2, e2, before=sabotage,
                  expect_fallback="sha256 mismatch"),
            Round(10, "rival block written by hand (identity from config)", "A3", "r2",
                  "rivalsmall", "v1", "#F28C28", "ring", before=rival),
        ]

    def run_round(self, r: Round) -> None:
        status = self.status()
        seq_before = max([a["seq"] for a in status.get("activations", [])] or [0])
        fseq_before = max([f["seq"] for f in status.get("fallbacks", [])] or [0])

        self.trigger_at = None
        if r.before:
            r.before(self)
        written_at = self.trigger_at or utcnow()

        def match(s: dict[str, Any]):
            for a in s.get("activations", []):
                if (a["seq"] > seq_before and a["slot"] == r.slot and a["piece"] == r.piece
                        and a["version"] == r.version
                        and (not r.brand or a.get("brand") == r.brand)
                        and (not r.emblem or a.get("emblem") == r.emblem)):
                    return a
            return None

        activation = self.wait_for(match, 120,
                                   f"{r.piece} {r.version} {r.brand} in {r.slot}")
        r.activation = activation
        visible = parse_utc(activation.get("visible_utc", ""))
        r.seconds_to_visible = (visible - written_at).total_seconds() if visible else -1.0

        if r.expect_fallback:
            hit = None
            for f in self.status().get("fallbacks", []):
                if (f["seq"] > fseq_before and f["slot"] == r.slot
                        and r.expect_fallback in f["reason"]):
                    hit = f
                    break
            if hit is None:
                r.ok, r.detail = False, f"no '{r.expect_fallback}' fallback was recorded"
                return
            r.fallback = hit
            print(f"    fallback as asked for: {hit['reason']}", flush=True)

        # The game points the camera and presses the shutter a second and a half later.
        seq = activation["seq"]

        def shot(s: dict[str, Any]):
            for a in s.get("activations", []):
                if a["seq"] == seq and a.get("shot"):
                    return a["shot"]
            return None

        try:
            r.shot = self.wait_for(shot, 40, f"the screenshot of round {r.n}")
        except TimeoutError:
            r.shot = ""

        r.ok = True
        r.detail = (f"{r.piece} {r.version} {activation.get('brand') or 'no-brand'} "
                    f"{activation.get('emblem') or ''}".strip()
                    + f"  in {r.seconds_to_visible:.1f}s")

    # ---- driving -----------------------------------------------------------------------

    def setup(self) -> None:
        self.api("POST", "/admin/reset")
        # The preview region starts at r2 in config; this copy of the game follows it, so
        # park it on r1 before the game starts or it would switch out from under round 1.
        self.api("POST", "/preview/region", json={"region": "r1"})
        self.api("POST", "/brand", json=BRAND1)
        print("uploading the visitor's content (real cooked packs):", flush=True)
        for name in UPLOADS:
            self.upload(name)

    def go(self) -> int:
        started = time.time()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        rounds = self.build_rounds()
        exit_code = 0
        try:
            self.start_server()
            self.setup()
            self.start_game()

            self.wait_for(lambda s: s.get("backend_status") == "ok", 120,
                          "the game to reach the backend")
            self.wait_for(
                lambda s: len(s.get("slots", {})) == 3
                and all(v["state"] == "ACTIVE" for v in s["slots"].values()),
                180, "all three slots to fill from the attract rotation")
            warm = self.status()
            print("the game is up; attract rotation filled every slot:", flush=True)
            for slot, v in warm["slots"].items():
                print(f"    {slot} {v['size_class']}  {v['state']:12} {v['piece']} {v['version']} "
                      f"{v['brand'] or 'no-brand'} {v['emblem']}", flush=True)

            for r in rounds:
                print(f"\n--- round {r.n}/10 · {r.what} · A/{r.slot}/{r.region}", flush=True)
                try:
                    self.run_round(r)
                except Exception as e:
                    r.ok, r.detail = False, f"{type(e).__name__}: {e}"
                print(f"    {'PASS' if r.ok else 'FAIL'}: {r.detail}", flush=True)
        finally:
            code = self.stop_game()
            print(f"game exit {code}", flush=True)
            self.stop_server()

        passed = sum(1 for r in rounds if r.ok)
        lines = ["", "=" * 108,
                 f"{'rd':>2}  {'slot':<4} {'rgn':<4} {'what':<52} {'appeared':<34} {'s':>6}  shot",
                 "-" * 108]
        for r in rounds:
            appeared = (f"{r.activation.get('piece', '-')} {r.activation.get('version', '')} "
                        f"{r.activation.get('brand') or 'no-brand'} "
                        f"{r.activation.get('emblem') or ''}").strip() if r.ok else "FAILED"
            lines.append(f"{r.n:>2}  {r.slot:<4} {r.region:<4} {r.what[:52]:<52} "
                         f"{appeared:<34} {r.seconds_to_visible:>6.1f}  {r.shot or '-'}")
        lines.append("=" * 108)
        lines.append(f"UE STAGE-1 EXIT TEST: {passed}/10 in {time.time() - started:.0f}s")
        times = [r.seconds_to_visible for r in rounds if r.ok and r.seconds_to_visible > 0]
        if times:
            lines.append(f"allocation written -> visible in game: "
                         f"min {min(times):.1f}s  median {sorted(times)[len(times) // 2]:.1f}s  "
                         f"max {max(times):.1f}s  over {len(times)} rounds")
        for failed in (r for r in rounds if not r.ok):
            lines.append(f"  round {failed.n} failed: {failed.detail}")
        report = "\n".join(lines)
        print(report, flush=True)
        (OUT_DIR / "ue_exit_test_result.txt").write_text(report + "\n", encoding="utf-8")
        print(f"\nwrote {OUT_DIR / 'ue_exit_test_result.txt'}", flush=True)
        print(f"shots in {self.shot_dir}", flush=True)
        print(f"DC log  {self.dc_log}", flush=True)

        if passed != len(rounds):
            exit_code = 1
        return exit_code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--server-data", default="")
    ap.add_argument("--keep-server-data", action="store_true")
    ap.add_argument("--res-x", type=int, default=1600)
    ap.add_argument("--res-y", type=int, default=900)
    args = ap.parse_args(argv)
    return ExitTest(args).go()


if __name__ == "__main__":
    raise SystemExit(main())
