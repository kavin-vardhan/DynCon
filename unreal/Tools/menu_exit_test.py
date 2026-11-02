"""Brief 018's exit test: the title menu, game switching, the X-ray and the attract loop.

    python\\python.exe unreal\\Tools\\menu_exit_test.py
    ... --res 1920x1080        the second pass, for the X-ray at 1080p
    ... --xray-only            skip the menu run; one lap of the tour with the X-ray on
    ... --keep                 leave the server up afterwards

One scripted run of the packaged build, in one process, with no restart:

    boot -> **attract** (shot) -> a button -> the **title menu** (shot) -> Game B ->
    walk to B1 -> pause -> **X-ray on** (shot) -> resume (shot from third person) ->
    pause -> switch to Game A (shot of the loading line) -> walk into A1, open the door,
    wall lamps on, screen to image 3 (shot) -> pause -> switch to B -> switch back to A ->
    walk back into A1: **everything as the Player left it** (shot) -> the idle timeout ->
    attract (shot).

**The input path.** The steps are driven by `-DCUiTest`, a test hook inside `UDCShell`
that calls the same `AnyButton` / `NavHorizontal` / `Confirm` / `PauseButton` the pad's
Enhanced Input bindings call - so what the script presses is what a visitor presses, one
function in. It is not a fake gamepad: the XInput driver itself is not exercised here, and
the "press X on the player pad" lock of plan v6 §11 is the next brief's.

What this script owns is the other half: the server, the allocations, the portal-side
check that the "playing at this booth" badge follows a game switch, the pass/fail table and
the contact sheet.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parent.parent.parent
SERVER_DIR = REPO / "server"
sys.path.insert(0, str(REPO / "tools"))
import dc_paths                                                          # noqa: E402

PYTHON = dc_paths.demo_python()
EXE = dc_paths.game_exe()
OUT_ROOT = REPO / "unreal" / "spike" / "shots" / "018"
WORK = REPO / "unreal" / "_build" / "menu"
LOG_DIR = REPO / "unreal" / "_build" / "logs"

BRAND = {"colour": "#E23D3D", "emblem": "star"}
LONG_MINUTES = 90.0

# One piece per slot, both games, so every ring in the X-ray has something inside it.
PLAN = [("A", "A1", "content1_v1.real.dcpack"),
        ("A", "A2", "content3_v1.real.dcpack"),
        ("A", "A3", "content4_v1.real.dcpack"),
        ("B", "B1", "content2_v1.real.dcpack"),
        ("B", "B2", "content4_v2.real.dcpack")]


class MenuExitTest:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.port = args.port
        self.url = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.url, timeout=120.0)
        self.server_data = Path(os.environ["TEMP"]) / "dc_menu_data"
        self.server: subprocess.Popen | None = None
        self.content: dict[str, str] = {}
        self.stamp = time.strftime("%Y%m%d_%H%M%S")
        self.res_x, self.res_y = (int(n) for n in args.res.lower().split("x"))
        self.tag = f"{self.res_x}x{self.res_y}"
        self.shots = OUT_ROOT / ("xray_" + self.tag if args.xray_only else "menu_" + self.tag)
        self.badge: list[str] = []
        self.problems: list[str] = []

    # ---- the server -------------------------------------------------------------------

    def api(self, method: str, path: str, **kw) -> Any:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        return r.json()

    def start_server(self) -> None:
        shutil.rmtree(self.server_data, ignore_errors=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = LOG_DIR / f"menu_{self.stamp}_server.log"
        env = dict(os.environ, DCSERVER_DATA=str(self.server_data))
        print(f"starting the server on 127.0.0.1:{self.port}", flush=True)
        self.server = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "dcserver.asgi:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"],
            cwd=str(SERVER_DIR), env=env, stdout=log.open("wb"),
            stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                self.api("GET", "/admin/health")
                print("server ok", flush=True)
                return
            except (httpx.HTTPError, RuntimeError):
                time.sleep(0.4)
        raise RuntimeError(f"the server never answered - see {log}")

    def stop_server(self) -> None:
        if self.server and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.server.kill()

    def setup(self) -> None:
        self.api("POST", "/admin/reset", json={"reason": "staff"})
        self.api("POST", "/brand", json=BRAND)
        for _game, _slot, filename in PLAN:
            if filename in self.content:
                continue
            path = SERVER_DIR / "demo_files" / filename
            if not path.is_file():
                raise RuntimeError(f"{path} is missing - run make_fake_packs.py --real")
            result = self.api("POST", "/content", files={
                "file": (filename, path.read_bytes(), "application/octet-stream")})
            if result["status"] != "approved":
                raise RuntimeError(f"{filename} was rejected: {result.get('reason')}")
            self.content[filename] = result["content_id"]
        for game, slot, filename in PLAN:
            written = self.api("POST", "/admin/allocate",
                               json={"game": game, "slot": slot, "region": "r1",
                                     "content_id": self.content[filename],
                                     "minutes": LONG_MINUTES})
            print(f"  allocated {game}/{slot} <- {written['piece']} {written['version']}",
                  flush=True)

    def booth_game(self) -> str | None:
        """Which game the portal would badge as "playing at this booth", right now."""
        try:
            rows = self.api("GET", "/games")["games"]
        except (httpx.HTTPError, RuntimeError):
            return None
        for row in rows:
            if row["live_at_booth"]:
                return row["id"]
        return None

    # ---- the run ----------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        shutil.rmtree(self.shots, ignore_errors=True)
        self.shots.mkdir(parents=True, exist_ok=True)
        for path in (WORK / "packcache", WORK / "userdir"):
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)
        quit_file = WORK / "dc_quit"
        quit_file.unlink(missing_ok=True)
        report = WORK / "dc_ui_test.json"
        report.unlink(missing_ok=True)

        common = [
            str(EXE), "-DCMap=/Game/Maps/GameA",
            "-windowed", f"-ResX={self.res_x}", f"-ResY={self.res_y}",
            f"-UserDir={WORK / 'userdir'}",
            f"-DCBackend={self.url}", "-DCGame=A", "-DCRegion=r1",
            f"-DCShotDir={self.shots}", f"-DCStatusFile={WORK / 'dc_status.json'}",
            f"-DCCacheDir={WORK / 'packcache'}",
            f"-DCLogFile={LOG_DIR / f'menu_{self.stamp}_{self.tag}.log'}",
            f"-DCQuitWhenFileExists={quit_file}",
            "-DCShell",
        ]
        if self.args.xray_only:
            # One lap of the scripted tour with the X-ray already on: an overview, a framed
            # shot of every slot, and a shot from inside each one, all with the overlay on
            # top. That is every piece of the X-ray at this resolution, cheaply.
            game_args = common + [
                "-DCStartIn=game", "-DCXray", "-DCIdleAttract=0",
                "-DCTour=16", f"-DCRunSeconds={self.args.seconds}",
            ]
        else:
            game_args = common + [
                "-DCStartIn=attract",
                f"-DCUiTest={report}",
                # Shortened so the last step takes seconds rather than a minute and a half.
                # The scripted run holds the clock down until it is the step being tested.
                f"-DCIdleAttract={self.args.idle}",
                "-DCAttractDwell=7",
                f"-DCRunSeconds={self.args.seconds}",
            ]

        print(f"  the game, {self.tag}, "
              f"{'one tour lap with the X-ray on' if self.args.xray_only else 'the menu run'}",
              flush=True)
        started = time.time()
        proc = subprocess.Popen(game_args)

        # Watch the badge while it runs: the portal's "playing at this booth" has to follow
        # a switch, and the only way to see that is to ask while the switch is happening.
        last = None
        while proc.poll() is None and time.time() - started < self.args.seconds + 120:
            now = self.booth_game()
            if now != last and now is not None:
                self.badge.append(f"{time.time() - started:6.1f} s  badge -> game {now}")
                print(f"    badge -> game {now}", flush=True)
                last = now
            if not self.args.xray_only and report.is_file():
                time.sleep(2.0)              # let the last shot land
                quit_file.write_text("stop", encoding="utf-8")
                break
            time.sleep(0.5)

        try:
            code = proc.wait(timeout=180)
        except subprocess.TimeoutExpired:
            quit_file.write_text("stop", encoding="utf-8")
            try:
                code = proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
                code = proc.wait(timeout=30)
        print(f"  game exit {code} after {time.time() - started:.0f}s", flush=True)

        out: dict[str, Any] = {"exit": code, "seconds": time.time() - started,
                               "badge": self.badge, "resolution": self.tag}
        if report.is_file():
            out["ui"] = json.loads(report.read_text(encoding="utf-8"))
        status = WORK / "dc_status.json"
        if status.is_file():
            out["status"] = json.loads(status.read_text(encoding="utf-8"))
        return out

    # ---- the verdict --------------------------------------------------------------------

    def check(self, result: dict[str, Any]) -> None:
        ui = result.get("ui") or {}
        if not self.args.xray_only:
            if not ui:
                self.problems.append("the game wrote no dc_ui_test.json")
            for problem in ui.get("problems", []):
                self.problems.append(problem)
            # A -> B (picked on the title menu), B -> A, A -> B, B -> A.
            if ui.get("game_switches") != 4:
                self.problems.append(
                    f"expected 4 game switches, got {ui.get('game_switches')}")
            if ui.get("restarts") != 0:
                self.problems.append(f"restarts is {ui.get('restarts')}, not 0")
            if ui.get("content_loading_screens") != 0:
                self.problems.append(
                    f"content loading screens is {ui.get('content_loading_screens')}, not 0 "
                    f"- a game switch must not count as one")
            if ui.get("mode") != "ATTRACT":
                self.problems.append(
                    f"the run did not end back in the attract loop (mode {ui.get('mode')})")
            badge_games = [line.split("game ")[-1] for line in self.badge]
            if "B" not in badge_games or "A" not in badge_games:
                self.problems.append(
                    f"the portal's booth badge did not follow both switches: {self.badge}")

        shots = sorted(p.name for p in self.shots.glob("*.png"))
        if len(shots) < (4 if self.args.xray_only else 8):
            self.problems.append(f"only {len(shots)} screenshot(s): {shots}")
        result["shots"] = shots
        result["problems"] = self.problems

    def write_report(self, result: dict[str, Any]) -> None:
        ui = result.get("ui") or {}
        lines = [f"# Brief 018 exit test - {result['resolution']}"
                 f"{' (X-ray pass)' if self.args.xray_only else ''}", "",
                 f"*{time.strftime('%Y-%m-%d %H:%M')}, one packaged Shipping run, "
                 f"{result['seconds']:.0f} s, exit {result['exit']}.*", ""]
        if ui:
            lines += [f"* **{'PASS' if not self.problems else 'FAIL'}** - "
                      f"{len(ui.get('problems', []))} problem(s) inside the game",
                      f"* game switches: **{ui.get('game_switches')}**",
                      f"* the strip at the end: restarts **{ui.get('restarts')}**, "
                      f"content loading screens **{ui.get('content_loading_screens')}**, "
                      f"uptime {ui.get('uptime_s', 0):.0f} s, "
                      f"{ui.get('packs_mounted')} pack(s) mounted", "",
                      "## The steps", "", "```"]
            lines += ui.get("steps", [])
            lines += ["```", "", "## The status strip at the end", "", "```"]
            lines += ui.get("strip", [])
            lines += ["```", ""]
        if self.badge:
            lines += ["## The portal's \"playing at this booth\" badge", "", "```"]
            lines += self.badge
            lines += ["```", ""]
        lines += ["## Screenshots", ""]
        lines += [f"* `{name}`" for name in result.get("shots", [])]
        if self.problems:
            lines += ["", "## Problems", ""] + [f"* {p}" for p in self.problems]
        lines += ["", f"**{'PASS' if not self.problems else 'FAIL'}**", ""]

        path = self.shots / "result.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (self.shots / "result.json").write_text(json.dumps(result, indent=2),
                                                encoding="utf-8")
        print("\n" + "\n".join(lines), flush=True)
        print(f"wrote {path}", flush=True)

    def go(self) -> int:
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        WORK.mkdir(parents=True, exist_ok=True)
        try:
            self.start_server()
            self.setup()
            result = self.run()
        finally:
            if not self.args.keep:
                self.stop_server()
        self.check(result)
        self.write_report(result)
        return 0 if not self.problems else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--res", default="1600x900")
    ap.add_argument("--xray-only", action="store_true")
    ap.add_argument("--idle", type=float, default=15.0)
    ap.add_argument("--seconds", type=int, default=600)
    ap.add_argument("--port", type=int, default=8705)
    ap.add_argument("--keep", action="store_true")
    return MenuExitTest(ap.parse_args(argv)).go()


if __name__ == "__main__":
    raise SystemExit(main())
