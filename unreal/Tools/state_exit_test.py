"""Exit test for demo plan v6 §14 step 6: **state kept across a swap, ten times out of ten.**

    python\\python.exe unreal\\Tools\\state_exit_test.py
    python\\python.exe unreal\\Tools\\state_exit_test.py --rounds 3 --plan push,end,push

Step 9 of the demo, ten times, in one packaged Shipping build that contains none of the
content:

    the Player walks into A1's content, opens the door, turns light B on, sets the screen to
    image 3 -> the backend replaces what is in the slot while they are standing inside -> the
    strip shows SWAP PENDING and the old version stays -> the Player walks out -> the new one
    mounts -> they walk back in and the door, the lights and the screen are exactly as they
    left them.

Three of the ten rounds are the **block ending** instead of a version being pushed: the
visitor's three demo hours run out while the Player is inside, the next winner (the region's
rival) waits the same way, and when it does swap in it must **not** be wearing the state the
Player left on somebody else's content.

How the two halves talk to each other
-------------------------------------
The game drives itself: `-DCStateTest=<rounds>` walks, uses the door, the switches and the
screen through the same `UDCInteractor` a visitor's button press goes through, and writes
`-DCStateFile=` on every phase change. This script watches that file and does the one thing
the game cannot do for itself - it is the *backend* that replaces the content:

    phase "waiting"  ->  make sure the visitor's content is allocated to the slot
    phase "armed"    ->  push a new version, or end the block

The game is never told which it was, or what to expect: it works that out from what actually
turns up, which is the rule under test. The pass table comes from the game's own
`dc_state_test.json`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parent.parent.parent
SERVER_DIR = REPO / "server"
sys.path.insert(0, str(REPO / "tools"))
import dc_paths                                                          # noqa: E402

PYTHON = dc_paths.demo_python()
EXE = dc_paths.game_exe()
OUT_DIR = REPO / "unreal" / "_build" / "runtime" / "state_test"
LOG_DIR = REPO / "unreal" / "_build" / "logs"

MAP = "/Game/Maps/GameA"
GAME = "A"
SLOT = "A1"
REGION = "r1"
BASE_PIECE = "content1"
BRAND = {"colour": "#E23D3D", "emblem": "star"}

# The visitor's block has to outlast the whole test, except when a round deliberately ends it.
LONG_MINUTES = 90.0

# What the visitor "uploads" each time they push an update. Alternating v2 / v1 is not a
# trick: each one is a real new version of the same content (version_n goes up every time),
# and alternating is what makes the point that it is the *content* the kept state belongs to,
# not the version - version 1 coming back after version 2 restores it just the same.
PUSH_FILES = ["content1_v2.real.dcpack", "content1_v1.real.dcpack"]

# Rounds 3, 6 and 9 end the block instead; each is followed by a push round, so the record
# also has to survive a block of somebody else's content standing in the slot.
DEFAULT_PLAN = ["push", "push", "end", "push", "push", "end", "push", "push", "end", "push"]


class StateExitTest:
    def __init__(self, args: argparse.Namespace):
        self.port = args.port
        self.url = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.url, timeout=120.0)
        self.keep_server_data = args.keep_server_data
        self.server_data = Path(args.server_data
                                or (Path(os.environ["TEMP"]) / "dc_state_test_data"))
        self.out = OUT_DIR
        self.shot_dir = self.out / "shots"
        self.cache_dir = self.out / "packcache"
        self.status_file = self.out / "dc_status.json"
        self.state_file = self.out / "dc_state.json"
        self.quit_file = self.out / "dc_quit"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.dc_log = LOG_DIR / f"state_test_{stamp}_dc.log"
        self.server_log = LOG_DIR / f"state_test_{stamp}_server.log"
        self.server: subprocess.Popen | None = None
        self.game: subprocess.Popen | None = None
        self.content_id = ""
        self.res_x, self.res_y = args.res_x, args.res_y
        self.warmup = args.warmup
        self.plan = [p.strip() for p in args.plan.split(",") if p.strip()] if args.plan \
            else list(DEFAULT_PLAN)
        self.rounds = args.rounds or len(self.plan)
        while len(self.plan) < self.rounds:
            self.plan.append("push")
        self.pushes = 0
        self.actions: list[dict[str, Any]] = []

    # ---- the server -------------------------------------------------------------------

    def api(self, method: str, path: str, **kw) -> dict[str, Any]:
        response = self.http.request(method, path, **kw)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {response.status_code} {response.text[:300]}")
        return response.json()

    def start_server(self) -> None:
        if not self.keep_server_data and self.server_data.exists():
            shutil.rmtree(self.server_data, ignore_errors=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, DCSERVER_DATA=str(self.server_data))
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
                missing = [p for p, v in health["system_packs"].items() if not v["pack_id"]]
                if missing:
                    raise RuntimeError(f"the server has no pack for {', '.join(missing)}")
                print(f"server ok: mode={health['mode']} key={health['key_fingerprint']}",
                      flush=True)
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
        return result

    def setup(self) -> None:
        self.api("POST", "/admin/reset")
        self.api("POST", "/preview/region", json={"region": REGION})
        self.api("POST", "/brand", json=BRAND)
        first = self.upload("content1_v1.real.dcpack")
        self.content_id = first["content_id"]
        print(f"  uploaded content1 v1 -> {self.content_id} (pack {first['pack']['id']})",
              flush=True)
        self.allocate()

    def allocate(self) -> dict[str, Any]:
        written = self.api("POST", "/admin/allocate",
                           json={"game": GAME, "slot": SLOT, "region": REGION,
                                 "content_id": self.content_id, "minutes": LONG_MINUTES})
        return written

    def showing(self) -> dict[str, Any]:
        for row in self.api("GET", "/status/live")["showing"]:
            if row["game"] == GAME and row["slot"] == SLOT and row["region"] == REGION:
                return row
        return {}

    # ---- the game ---------------------------------------------------------------------

    def start_game(self) -> None:
        if not EXE.is_file():
            raise RuntimeError(f"no packaged build at {EXE} - run unreal\\Tools\\package.ps1")
        for path in (self.shot_dir, self.cache_dir):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)
        for path in (self.status_file, self.state_file, self.quit_file):
            path.unlink(missing_ok=True)

        args = [
            str(EXE),
            f"-DCMap={MAP}",
            "-windowed", f"-ResX={self.res_x}", f"-ResY={self.res_y}",
            f"-DCBackend={self.url}", f"-DCGame={GAME}", f"-DCRegion={REGION}",
            f"-DCStateTest={self.rounds}", f"-DCStateSlot={SLOT}",
            f"-DCStateBase={BASE_PIECE}", f"-DCWarmup={self.warmup}",
            f"-DCStateFile={self.state_file}",
            f"-DCShotDir={self.shot_dir}", f"-DCStatusFile={self.status_file}",
            f"-DCCacheDir={self.cache_dir}", f"-DCLogFile={self.dc_log}",
            f"-DCQuitWhenFileExists={self.quit_file}", "-DCRunSeconds=3600",
        ]
        print(f"starting the packaged game: {self.rounds} round(s) on {SLOT}, "
              f"plan {','.join(self.plan[:self.rounds])}", flush=True)
        self.game = subprocess.Popen(args)

    def stop_game(self) -> int:
        if not self.game:
            return 0
        if self.game.poll() is None:
            self.quit_file.write_text("stop", encoding="utf-8")
        try:
            return self.game.wait(timeout=180)
        except subprocess.TimeoutExpired:
            print("the game would not stop - killing it", flush=True)
            self.game.kill()
            return self.game.wait(timeout=30)

    def read_json(self, path: Path) -> dict[str, Any]:
        """Both files are written aside and moved into place, so a torn read just retries."""
        for _ in range(12):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
        return {}

    # ---- what the backend does when the game says it is ready -------------------------

    def do_push(self, n: int) -> dict[str, Any]:
        filename = PUSH_FILES[self.pushes % len(PUSH_FILES)]
        self.pushes += 1
        before = self.api("GET", "/changes",
                          params={"game": GAME, "region": REGION})["slots"][SLOT]
        result = self.upload(filename, content_id=self.content_id)
        after = self.api("GET", "/changes",
                         params={"game": GAME, "region": REGION})["slots"][SLOT]
        if before == after:
            raise RuntimeError("alloc_key did not change when the update was pushed")
        print(f"    round {n}: pushed {filename} as version n={result['version_n']} "
              f"({result['piece']} {result['version']}); alloc_key {before} -> {after}",
              flush=True)
        return {"round": n, "what": "push", "file": filename,
                "version": result["version"], "version_n": result["version_n"],
                "alloc_key": [before, after]}

    def do_end_block(self, n: int) -> dict[str, Any]:
        before = self.api("GET", "/changes",
                          params={"game": GAME, "region": REGION})["slots"][SLOT]
        ended = self.api("POST", "/admin/end-block",
                         json={"game": GAME, "slot": SLOT, "region": REGION})
        after = self.api("GET", "/changes",
                         params={"game": GAME, "region": REGION})["slots"][SLOT]
        print(f"    round {n}: ended the block; {ended['was']['piece']} "
              f"{ended['was']['version']} -> {ended['now']['piece']} "
              f"{ended['now']['version']} ({ended['now']['kind']}); "
              f"alloc_key {before} -> {after}", flush=True)
        return {"round": n, "what": "end", "was": ended["was"], "now": ended["now"],
                "alloc_key": [before, after]}

    def on_waiting(self, n: int) -> None:
        showing = self.showing()
        if showing.get("piece") == BASE_PIECE and showing.get("kind") == "visitor":
            return
        written = self.allocate()
        print(f"    round {n}: allocated {written['piece']} {written['version']} to {SLOT} "
              f"(was {showing.get('piece')} {showing.get('kind')})", flush=True)

    # ---- driving -----------------------------------------------------------------------

    def drive(self) -> None:
        """Watch the game's phase file and answer it. Returns when the game is finished."""
        handled: set[tuple[str, int]] = set()
        deadline = time.monotonic() + 60 * 60
        last_seen = ""
        while time.monotonic() < deadline:
            if self.game and self.game.poll() is not None:
                print(f"the game exited (code {self.game.returncode})", flush=True)
                return
            state = self.read_json(self.state_file)
            phase = str(state.get("phase", ""))
            n = int(state.get("round", 0) or 0)
            if phase in ("done", "finished"):
                print("the game says it is done", flush=True)
                return
            key = (phase, n)
            if phase and key not in handled:
                handled.add(key)
                if f"{phase}{n}" != last_seen:
                    last_seen = f"{phase}{n}"
                try:
                    if phase == "waiting" and n > 0:
                        self.on_waiting(n)
                    elif phase == "armed" and n > 0:
                        what = self.plan[(n - 1) % len(self.plan)]
                        self.actions.append(self.do_end_block(n) if what == "end"
                                            else self.do_push(n))
                except Exception as bad:                         # noqa: BLE001
                    print(f"    round {n}: the backend step failed: {bad}", flush=True)
            time.sleep(0.2)
        print("gave up waiting for the game", flush=True)

    # ---- the report --------------------------------------------------------------------

    def report(self) -> int:
        result_path = self.shot_dir / "dc_state_test.json"
        if not result_path.is_file():
            print(f"NO RESULT FILE at {result_path}", flush=True)
            return 1
        result = json.loads(result_path.read_text(encoding="utf-8"))
        rounds = result.get("rounds", [])
        passed = sum(1 for r in rounds if r["ok"])

        lines = ["", "=" * 124,
                 f"{'rd':>2}  {'what the backend did':<22} {'before':<16} {'after':<16} "
                 f"{'kind':<19} {'pend':>5} {'swap':>5}  {'left -> found':<34} ok",
                 "-" * 124]
        by_round = {a["round"]: a for a in self.actions}
        for r in rounds:
            action = by_round.get(r["n"], {})
            what = {"push": "pushed a new version", "end": "ended the block"}.get(
                action.get("what", ""), "-")
            left = state_words(r["left"])
            found = state_words(r["found"])
            lines.append(
                f"{r['n']:>2}  {what:<22} "
                f"{r['before_piece'] + ' ' + r['before_version']:<16} "
                f"{r['after_piece'] + ' ' + r['after_version']:<16} "
                f"{r['kind']:<19} {r['swap_pending_s']:>5.1f} {r['swap_s']:>5.1f}  "
                f"{left + ' -> ' + found:<34} {'PASS' if r['ok'] else 'FAIL'}")
            if r.get("note"):
                lines.append(f"      note: {r['note']}")
        lines.append("=" * 124)
        lines.append(f"STATE EXIT TEST: {passed}/{len(rounds)} rounds")

        ends = [r for r in rounds if r["kind"] == "different content"]
        lines.append(f"  block-end rounds (a different winner took the block while the Player "
                     f"was inside): {len(ends)} - "
                     + ", ".join(f"#{r['n']} {r['after_piece']}" for r in ends))
        kept = [r for r in rounds if r.get("restored_on_return")]
        if kept:
            lines.append(f"  the record outlived somebody else's block and came back on "
                         f"rounds: " + ", ".join(f"#{r['n']}" for r in kept))
        use = result.get("interaction", {})
        lines.append(f"  interactions: {use.get('uses', 0)} "
                     f"(door {use.get('door', 0)}, lights A {use.get('light_a', 0)}, "
                     f"lights B {use.get('light_b', 0)}, screen {use.get('screen', 0)}); "
                     f"the prompt already showed the right thing "
                     f"{use.get('prompt_agreed', 0)}/{use.get('prompt_checked', 0)} times")
        for line in result.get("state_store", []):
            lines.append(f"  state store: {line}")

        # Telemetry, as the portal's report sees it.
        try:
            region = next(r for r in self.api("GET", "/report")["regions"]
                          if r["region"] == REGION)
            lines.append(f"  /report {region['region']}: views {region['views']} "
                         f"({region['views_simulated']} simulated + {region['views_live']} "
                         f"counted)  visits {region['visits']}  dwell {region['dwell_s']} s  "
                         f"interactions {region['interactions']}  mounts {region['mounts']}  "
                         f"blocks {region['blocks']}")
        except Exception as bad:                                 # noqa: BLE001
            lines.append(f"  /report could not be read: {bad}")

        text = "\n".join(lines)
        print(text, flush=True)
        (self.out / "state_exit_test_result.txt").write_text(text + "\n", encoding="utf-8")
        print(f"\nwrote {self.out / 'state_exit_test_result.txt'}", flush=True)
        print(f"shots in {self.shot_dir}", flush=True)
        print(f"DC log  {self.dc_log}", flush=True)
        return 0 if rounds and passed == len(rounds) else 1

    def go(self) -> int:
        started = time.time()
        self.out.mkdir(parents=True, exist_ok=True)
        try:
            self.start_server()
            self.setup()
            self.start_game()
            self.drive()
        except Exception:                                        # noqa: BLE001
            # Say why before the finally block tidies up and reports: a headless run that
            # only prints "NO RESULT FILE" has thrown the actual reason away.
            traceback.print_exc()
        finally:
            code = self.stop_game()
            print(f"game exit {code} after {time.time() - started:.0f}s", flush=True)
            try:
                return self.report()
            finally:
                self.stop_server()


def state_words(state: dict[str, Any]) -> str:
    return (f"A{'+' if state.get('light_a_on') else '-'}"
            f"B{'+' if state.get('light_b_on') else '-'}"
            f" door {'open' if state.get('door_open') else 'shut'}"
            f" scr {state.get('screen_image_index')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--rounds", type=int, default=0, help="default: as many as the plan has")
    ap.add_argument("--plan", default="", help="comma list of push / end, one per round")
    ap.add_argument("--server-data", default="")
    ap.add_argument("--keep-server-data", action="store_true")
    ap.add_argument("--res-x", type=int, default=1600)
    ap.add_argument("--res-y", type=int, default=900)
    ap.add_argument("--warmup", type=float, default=14.0,
                    help="seconds to let the slots fill before round 1")
    return StateExitTest(ap.parse_args(argv)).go()


if __name__ == "__main__":
    raise SystemExit(main())
