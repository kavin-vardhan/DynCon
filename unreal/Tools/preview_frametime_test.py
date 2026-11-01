"""The region preview window's pass/fail test (demo plan v6 §11, §14 step 5).

    server\\.venv\\Scripts\\python.exe unreal\\Tools\\preview_frametime_test.py
    ... --minutes 10          how long each run's scripted tour keeps going
    ... --only solo           just one of the two runs (solo | with)
    ... --keep-server-data    reuse the server folder from the last run

The question, in plan v6's words: "the main game must hold its frame rate with the preview
alive through a soak run. If not, drop the preview and do step 7 as a live flip."

So: the same ten-minute scripted tour of Game A, twice.

  run 1  solo            the main game on its own
  run 2  with the preview a second copy of the same build is up as a player in another
                          region, shown on screen and rendering the whole time

**Pass = the main game's worst 1 % stays under 25 ms and its average is within 15 % of
solo.** Both numbers come from the game's own `dc_tour.json`, which is the same sampler the
status file carries: every frame after the first four seconds, minus any frame within half a
second of a screenshot (a shutter costs 100 ms and says nothing about the preview).

The tour is laps rather than a camera left standing: `-DCTourFor=<seconds>` starts the round
again when it ends, so ten minutes is about seven walks round the plaza, in and out of all
three pieces of content - which is the expensive thing a visitor actually does. Only the
first lap photographs anything.

Nothing is left running: the preview copy is given `-DCRunSeconds`, the main game quits
itself when the tour is done, and both are killed if they outstay that.

**Leave the PC alone while this runs.** A soak measures the machine as well as the build:
the first attempt at this test was made while the same PC was searching the engine's source
tree, and the main game's worst 1 % went from 19 ms to 29 ms with no preview window in
sight. Both copies are given their own `-UserDir`, so a run starts from the build's own
settings and leaves none of its own behind.
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
PYTHON = SERVER_DIR / ".venv" / "Scripts" / "python.exe"
EXE = REPO / "unreal" / "_build" / "archive" / "Windows" / "DCDemo.exe"
OUT_ROOT = REPO / "unreal" / "_build" / "preview"
LOG_DIR = REPO / "unreal" / "_build" / "logs"

BRAND = {"colour": "#E23D3D", "emblem": "star"}
LONG_MINUTES = 90.0

# One piece per slot of Game A, as in map_check.py: content3 only fits the tall slot and
# content4 is the only visitor piece a small one takes.
PLAN = [("A1", "content1_v1.real.dcpack"),
        ("A2", "content3_v1.real.dcpack"),
        ("A3", "content4_v1.real.dcpack")]

# Plan v6 §11's pass line.
WORST_1_LIMIT_MS = 25.0
AVERAGE_SLACK = 0.15


class FrameTimeTest:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.port = args.port
        self.url = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.url, timeout=120.0)
        self.server_data = Path(args.server_data
                                or (Path(os.environ["TEMP"]) / "dc_frametime_data"))
        self.out = OUT_ROOT / "frametime"
        self.server: subprocess.Popen | None = None
        self.content: dict[str, str] = {}
        self.stamp = time.strftime("%Y%m%d_%H%M%S")

    # ---- the server -------------------------------------------------------------------

    def api(self, method: str, path: str, **kw) -> dict[str, Any]:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        return r.json()

    def start_server(self) -> None:
        if not self.args.keep_server_data and self.server_data.exists():
            shutil.rmtree(self.server_data, ignore_errors=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = LOG_DIR / f"frametime_{self.stamp}_server.log"
        env = dict(os.environ, DCSERVER_DATA=str(self.server_data))
        print(f"starting the server on 127.0.0.1:{self.port} (data {self.server_data})",
              flush=True)
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
            print("server stopped", flush=True)

    def setup(self) -> None:
        """One visitor allocation per slot in the main game's region. The preview's region
        gets nothing, so what it shows is the attract rotation's own local winner - which is
        the point of the window and also the heavier case: two regions, two sets of packs."""
        self.api("POST", "/admin/reset")
        self.api("POST", "/preview/region", json={"region": self.args.preview_region})
        self.api("POST", "/brand", json=BRAND)
        for _slot, filename in PLAN:
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
        for slot, filename in PLAN:
            written = self.api("POST", "/admin/allocate",
                               json={"game": "A", "slot": slot, "region": self.args.region,
                                     "content_id": self.content[filename],
                                     "minutes": LONG_MINUTES})
            print(f"  allocated {slot} <- {written['piece']} {written['version']}", flush=True)

    # ---- the two runs -----------------------------------------------------------------

    def run(self, label: str, with_preview: bool) -> dict[str, Any]:
        seconds = int(self.args.minutes * 60)
        where = self.out / label
        shots = where / "shots"
        for path in (shots, where / "packcache", where / "preview_packcache",
                     where / "preview_userdir", where / "main_userdir"):
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)
        quit_file = where / "dc_quit"
        quit_file.unlink(missing_ok=True)

        preview: subprocess.Popen | None = None
        try:
            if with_preview:
                # Started BEFORE the main game on purpose: creating a window takes focus,
                # and the main game must end up with it (plan v6 §11). Everything after
                # boot moves this window with SWP_NOACTIVATE and cannot steal focus.
                preview_args = [
                    str(EXE), "-DCMap=/Game/Maps/GameA",
                    "-windowed", "-ResX=960", "-ResY=540",
                    "-DCPreview", "-DCPreviewShown", "-DCFollowRegion", "-nosound",
                    # Not optional: without its own Saved folder the preview's lowest
                    # scalability and half resolution are persisted into the
                    # GameUserSettings.ini the main game reads next time it starts - which
                    # would make the second run of this very test measure the wrong thing.
                    f"-UserDir={where / 'preview_userdir'}",
                    f"-DCBackend={self.url}", "-DCGame=A",
                    f"-DCRegion={self.args.preview_region}",
                    f"-DCCacheDir={where / 'preview_packcache'}",
                    f"-DCStatusFile={where / 'preview_status.json'}",
                    f"-DCLogFile={LOG_DIR / f'frametime_{self.stamp}_{label}_preview.log'}",
                    f"-DCPreviewFile={where / 'dc_preview_window.json'}",
                    f"-DCRunSeconds={seconds + 240}",
                ]
                print("  starting the region preview window", flush=True)
                preview = subprocess.Popen(preview_args)
                time.sleep(12)          # long enough to place its window and fill its slots

            game_args = [
                str(EXE), "-DCMap=/Game/Maps/GameA",
                "-windowed", f"-ResX={self.args.res_x}", f"-ResY={self.args.res_y}",
                # The main game gets its own Saved folder too, so the measurement starts
                # from the build's own settings every time instead of from whatever the
                # last run of anything left in GameUserSettings.ini.
                f"-UserDir={where / 'main_userdir'}",
                f"-DCBackend={self.url}", "-DCGame=A", f"-DCRegion={self.args.region}",
                f"-DCTour={self.args.warmup}", f"-DCTourFor={seconds}",
                f"-DCShotDir={shots}", f"-DCStatusFile={where / 'dc_status.json'}",
                f"-DCCacheDir={where / 'packcache'}",
                f"-DCLogFile={LOG_DIR / f'frametime_{self.stamp}_{label}_main.log'}",
                f"-DCQuitWhenFileExists={quit_file}",
                f"-DCRunSeconds={seconds + 300}",
            ]
            print(f"  {label}: the main game, {self.args.minutes:.0f} minutes of the "
                  f"scripted tour at {self.args.res_x}x{self.args.res_y}", flush=True)
            started = time.time()
            proc = subprocess.Popen(game_args)
            try:
                code = proc.wait(timeout=seconds + 420)
            except subprocess.TimeoutExpired:
                print("  the game outstayed its welcome - stopping it", flush=True)
                quit_file.write_text("stop", encoding="utf-8")
                try:
                    code = proc.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    code = proc.wait(timeout=30)
            print(f"  game exit {code} after {time.time() - started:.0f}s", flush=True)
        finally:
            if preview is not None and preview.poll() is None:
                preview.terminate()
                try:
                    preview.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    preview.kill()
                print("  preview window stopped", flush=True)

        tour_path = shots / "dc_tour.json"
        if not tour_path.is_file():
            raise RuntimeError(f"no tour report at {tour_path}")
        tour = json.loads(tour_path.read_text(encoding="utf-8"))
        result = {"label": label, "with_preview": with_preview, **tour["frame_ms"],
                  "rounds": tour.get("rounds"), "seconds": tour.get("seconds"),
                  "walks": len(tour.get("walks", [])),
                  "walks_arrived": sum(1 for w in tour.get("walks", []) if w["arrived"]),
                  "slots": tour.get("slots", [])}
        if with_preview:
            status = where / "preview_status.json"
            if status.is_file():
                preview_status = json.loads(status.read_text(encoding="utf-8"))
                result["preview"] = {
                    "region": preview_status.get("region"),
                    "label": preview_status.get("region_label"),
                    "focus": preview_status.get("focus"),
                    "frames": preview_status.get("frame_ms", {}).get("frames"),
                    "average": preview_status.get("frame_ms", {}).get("average"),
                    "telemetry_sent": preview_status.get("telemetry_sent"),
                    "telemetry_dropped": preview_status.get("telemetry_dropped"),
                    "slots": {k: v.get("piece") for k, v in
                              (preview_status.get("slots") or {}).items()},
                }
            window = where / "dc_preview_window.json"
            if window.is_file():
                result["window"] = json.loads(window.read_text(encoding="utf-8"))
        return result

    # ---- the table --------------------------------------------------------------------

    def report(self, runs: list[dict[str, Any]]) -> int:
        solo = next((r for r in runs if not r["with_preview"]), None)
        withp = next((r for r in runs if r["with_preview"]), None)

        lines = ["# The region preview window: frame time with and without it", "",
                 f"*{self.args.minutes:.0f} minutes of the main game's scripted tour on "
                 f"Game A at {self.args.res_x} x {self.args.res_y}, run twice. Written by "
                 f"`unreal/Tools/preview_frametime_test.py` on "
                 f"{time.strftime('%Y-%m-%d %H:%M')}.*", "",
                 "| | frames | average | median | worst 1 % | worst | over 16 ms | "
                 "over 25 ms | laps |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for r in runs:
            name = "with the preview" if r["with_preview"] else "solo"
            lines.append(
                f"| {name} | {r['frames']:,} | **{r['average']:.2f} ms** "
                f"({r['average_fps']:.0f} fps) | {r['median']:.2f} ms | "
                f"**{r['worst_1_percent']:.2f} ms** | {r['worst']:.2f} ms | "
                f"{r.get('over_16ms', 0):,} | {r.get('over_25ms', 0):,} | {r['rounds']} |")

        verdict = "INCOMPLETE"
        passed = False
        if solo and withp:
            worst_ok = withp["worst_1_percent"] < WORST_1_LIMIT_MS
            limit = solo["average"] * (1.0 + AVERAGE_SLACK)
            average_ok = withp["average"] <= limit
            passed = worst_ok and average_ok
            verdict = "PASS" if passed else "FAIL"
            lines += ["", "## The pass line (plan v6 §11)", "",
                      f"* worst 1 % under {WORST_1_LIMIT_MS:.0f} ms: "
                      f"**{withp['worst_1_percent']:.2f} ms** — "
                      f"{'pass' if worst_ok else 'FAIL'}",
                      f"* average within {AVERAGE_SLACK:.0%} of solo "
                      f"({solo['average']:.2f} ms → at most {limit:.2f} ms): "
                      f"**{withp['average']:.2f} ms** "
                      f"({(withp['average'] / solo['average'] - 1.0):+.1%}) — "
                      f"{'pass' if average_ok else 'FAIL'}",
                      "", f"**{verdict}**"]
        for r in runs:
            lines += ["", f"### {r['label']}", "",
                      f"* {r['walks_arrived']} / {r['walks']} walk legs arrived over "
                      f"{r['rounds']} lap(s) in {r['seconds']:.0f} s",
                      "* slots: " + ", ".join(
                          f"{s['slot']} {s['piece']} {s['version']}" for s in r["slots"])]
            if r.get("preview"):
                p = r["preview"]
                lines += [f"* the preview window played as {p['label']} ({p['region']}), "
                          f"framing {(p.get('focus') or {}).get('slot')} "
                          f"({(p.get('focus') or {}).get('reason')})",
                          f"* it showed: " + ", ".join(
                              f"{k} {v}" for k, v in sorted((p.get("slots") or {}).items())),
                          f"* its own frames: {p.get('frames')} at "
                          f"{(p.get('average') or 0):.2f} ms average; telemetry sent "
                          f"{p.get('telemetry_sent')}, dropped {p.get('telemetry_dropped')} "
                          f"(a preview is not a player)"]
            if r.get("window"):
                home = r["window"]["home"]
                lines.append(f"* its window: {home['w']} x {home['h']} at "
                             f"({home['x']}, {home['y']})")

        text = "\n".join(lines) + "\n"
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "frametime.md").write_text(text, encoding="utf-8")
        (self.out / "frametime.json").write_text(json.dumps(runs, indent=2),
                                                 encoding="utf-8")
        print("\n" + text, flush=True)
        print(f"wrote {self.out / 'frametime.md'}", flush=True)
        return 0 if passed else 1

    def go(self) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        runs: list[dict[str, Any]] = []
        try:
            self.start_server()
            self.setup()
            if self.args.only in ("all", "solo"):
                runs.append(self.run("solo", with_preview=False))
            if self.args.only in ("all", "with"):
                runs.append(self.run("with_preview", with_preview=True))
        finally:
            self.stop_server()
        return self.report(runs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--only", default="all", choices=["all", "solo", "with"])
    ap.add_argument("--port", type=int, default=8703)
    ap.add_argument("--region", default="r1", help="the main game's region")
    ap.add_argument("--preview-region", default="r2")
    ap.add_argument("--res-x", type=int, default=1600)
    ap.add_argument("--res-y", type=int, default=900)
    ap.add_argument("--warmup", type=float, default=16.0)
    ap.add_argument("--server-data", default="")
    ap.add_argument("--keep-server-data", action="store_true")
    return FrameTimeTest(ap.parse_args(argv)).go()


if __name__ == "__main__":
    raise SystemExit(main())
