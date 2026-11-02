"""What the lamps inside a piece of content cost, measured one setting at a time.

    python\\python.exe unreal\\Tools\\light_sweep.py
    ... --minutes 3            how long each variant's scripted tour runs
    ... --only no_gi,baseline  just these variants
    ... --list                 print the variants and exit

Brief 018 part 1. Brief 016 gave every piece a second group of lamps the Player can switch
on at a wall switch, and the solo frame-time baseline of the ten-minute tour drifted from
12.47 ms to 17.82 ms. Three pieces of content with group B on is **eighteen extra point
lights**, so the question is which part of a point light is expensive here - the shadow, the
reach, the count, or the fact that Lumen has to light its whole surface cache with it.

Each variant is **the same scripted tour of Game A, in the same build, against the same
server, with the same allocations**; the only thing that moves between runs is one set of
`-DCLight*` switches on the command line (`DCContentActor.cpp`, "the lighting budget"). The
frame times come out of the game's own `dc_tour.json` - the sampler that drops the first four
seconds and any frame within half a second of a screenshot.

Leave the PC alone while it runs: a soak measures the machine as well as the build.
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
OUT = REPO / "unreal" / "_build" / "lights"
LOG_DIR = REPO / "unreal" / "_build" / "logs"

BRAND = {"colour": "#E23D3D", "emblem": "star"}
LONG_MINUTES = 90.0

PLAN = [("A1", "content1_v1.real.dcpack"),
        ("A2", "content3_v1.real.dcpack"),
        ("A3", "content4_v1.real.dcpack")]

# name -> (what it is, the switches). Order matters: the table reads top to bottom.
VARIANTS: list[tuple[str, str, list[str]]] = [
    ("b_off", "group B not built at all - the lower bound",
     ["-DCLightBOff"]),
    ("baseline", "brief 016 as shipped: 6 lamps, shadowless, 320 lm, r=320 cm, lighting Lumen",
     ["-DCLightBGi=1"]),
    ("b_shadows", "...and casting shadows, to price the shadow on its own",
     ["-DCLightBGi=1", "-DCLightBShadow=1"]),
    ("b_tight", "...with the reach cut from 3.2 m to 2.0 m",
     ["-DCLightBGi=1", "-DCLightBRadius=200"]),
    ("b_half", "...3 lamps at twice the lumens instead of 6",
     ["-DCLightBGi=1", "-DCLightBEvery=2"]),
    ("b_nogi", "6 lamps, shadowless, but out of the Lumen scene (indirect scale 0)",
     ["-DCLightBGi=0"]),
    ("b_nogi_tight", "out of the Lumen scene and a 2.4 m reach",
     ["-DCLightBGi=0", "-DCLightBRadius=240"]),
    ("a_one_shadow", "B out of the Lumen scene, and only one group-A fixture casting",
     ["-DCLightBGi=0", "-DCLightAShadowMax=1"]),

    # --- the second batch, once the first says the wall lamps are not where the time is.
    ("a_nogi", "both groups out of the Lumen scene",
     ["-DCLightBGi=0", "-DCLightAGi=0"]),
    ("a_half", "B out of the Lumen scene, half the ceiling fixtures at twice the lumens",
     ["-DCLightBGi=0", "-DCLightAEvery=2"]),
    ("pick", "the candidate: B out of the Lumen scene, one group-A shadow-caster, half of A",
     ["-DCLightBGi=0", "-DCLightAShadowMax=1", "-DCLightAEvery=2"]),
    ("all_off", "no lamps inside a piece at all - the floor of the whole question",
     ["-DCLightBOff", "-DCLightALumens=0"]),

    # --- and a probe of the rest of the frame, so the report can say what the 15 ms is
    # made of rather than guess. These are measurements, not proposals: each one turns off
    # something the look is built on.
    ("probe_novsm", "PROBE: virtual shadow maps off",
     ["-DCCvars=r.Shadow.Virtual.Enable=0"]),
    # Inconclusive when it was run: `r.DynamicGlobalIlluminationMethod` is a scalability
    # variable the renderer reads when the scene is built, and setting it from the command
    # line after that does not take. Kept so the next person does not repeat it.
    ("probe_nolumen", "PROBE (inconclusive): Lumen global illumination off",
     ["-DCCvars=r.DynamicGlobalIlluminationMethod=0"]),
    ("probe_norefl", "PROBE: Lumen reflections off",
     ["-DCCvars=r.ReflectionMethod=0"]),
    ("probe_lumen_half", "PROBE: Lumen's screen probes at half density",
     ["-DCCvars=r.Lumen.ScreenProbeGather.DownsampleFactor=32"]),
]


class LightSweep:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.port = args.port
        self.url = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.url, timeout=120.0)
        self.server_data = Path(os.environ["TEMP"]) / "dc_lightsweep_data"
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
        shutil.rmtree(self.server_data, ignore_errors=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = LOG_DIR / f"lightsweep_{self.stamp}_server.log"
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
        self.api("POST", "/admin/reset")
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
            self.api("POST", "/admin/allocate",
                     json={"game": "A", "slot": slot, "region": "r1",
                           "content_id": self.content[filename], "minutes": LONG_MINUTES})

    # ---- one variant ------------------------------------------------------------------

    def run(self, name: str, what: str, switches: list[str]) -> dict[str, Any]:
        seconds = int(self.args.minutes * 60)
        where = OUT / name
        shots = where / "shots"
        for path in (shots, where / "packcache", where / "userdir"):
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)
        quit_file = where / "dc_quit"
        quit_file.unlink(missing_ok=True)

        game_args = [
            str(EXE), "-DCMap=/Game/Maps/GameA",
            "-windowed", f"-ResX={self.args.res_x}", f"-ResY={self.args.res_y}",
            f"-UserDir={where / 'userdir'}",
            f"-DCBackend={self.url}", "-DCGame=A", "-DCRegion=r1",
            f"-DCTour={self.args.warmup}", f"-DCTourFor={seconds}",
            f"-DCShotDir={shots}", f"-DCStatusFile={where / 'dc_status.json'}",
            f"-DCCacheDir={where / 'packcache'}",
            f"-DCLogFile={LOG_DIR / f'lightsweep_{self.stamp}_{name}.log'}",
            f"-DCQuitWhenFileExists={quit_file}",
            f"-DCRunSeconds={seconds + 300}",
        ] + switches

        print(f"\n== {name}: {what}\n   {' '.join(switches)}", flush=True)
        started = time.time()
        proc = subprocess.Popen(dc_paths.game_cmdline(game_args))
        try:
            code = proc.wait(timeout=seconds + 420)
        except subprocess.TimeoutExpired:
            quit_file.write_text("stop", encoding="utf-8")
            try:
                code = proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                proc.kill()
                code = proc.wait(timeout=30)
        print(f"   exit {code} after {time.time() - started:.0f}s", flush=True)

        tour_path = shots / "dc_tour.json"
        if not tour_path.is_file():
            raise RuntimeError(f"no tour report at {tour_path}")
        tour = json.loads(tour_path.read_text(encoding="utf-8"))
        row = {"name": name, "what": what, "switches": switches, **tour["frame_ms"],
               "rounds": tour.get("rounds"), "seconds": tour.get("seconds")}
        print(f"   average {row['average']:.2f} ms  worst 1 % {row['worst_1_percent']:.2f} ms "
              f"over {row['frames']:,} frames", flush=True)
        return row

    # ---- the table --------------------------------------------------------------------

    def report(self, rows: list[dict[str, Any]]) -> int:
        base = next((r for r in rows if r["name"] == "baseline"), None)
        floor = next((r for r in rows if r["name"] == "b_off"), None)
        lines = ["# What the lamps cost", "",
                 f"*{self.args.minutes:.0f} minutes of the scripted tour of Game A at "
                 f"{self.args.res_x} x {self.args.res_y}, once per setting, same build and "
                 f"same server. Written by `unreal/Tools/light_sweep.py` on "
                 f"{time.strftime('%Y-%m-%d %H:%M')}.*", "",
                 "| setting | what | average | median | worst 1 % | over 16 ms | over 25 ms | "
                 "vs baseline |", "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            delta = ""
            if base and r is not base and base["average"] > 0:
                delta = f"{(r['average'] / base['average'] - 1.0):+.1%}"
            lines.append(
                f"| `{r['name']}` | {r['what']} | **{r['average']:.2f} ms** "
                f"({r['average_fps']:.0f} fps) | {r['median']:.2f} ms | "
                f"**{r['worst_1_percent']:.2f} ms** | {r.get('over_16ms', 0):,} | "
                f"{r.get('over_25ms', 0):,} | {delta} |")
        if base and floor:
            lines += ["", f"The eighteen wall lamps cost "
                          f"**{base['average'] - floor['average']:.2f} ms** of average frame "
                          f"time as brief 016 shipped them "
                          f"({floor['average']:.2f} -> {base['average']:.2f} ms)."]
        lines += ["", "## The switches each row ran with", ""]
        for r in rows:
            lines.append(f"* `{r['name']}`: `{' '.join(r['switches']) or '(none)'}`")

        text = "\n".join(lines) + "\n"
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "light_sweep.md").write_text(text, encoding="utf-8")
        (OUT / "light_sweep.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print("\n" + text, flush=True)
        return 0

    def go(self) -> int:
        wanted = [v for v in VARIANTS
                  if not self.args.only or v[0] in self.args.only.split(",")]
        rows: list[dict[str, Any]] = []
        OUT.mkdir(parents=True, exist_ok=True)
        try:
            self.start_server()
            self.setup()
            for name, what, switches in wanted:
                rows.append(self.run(name, what, switches))
        finally:
            self.stop_server()
        return self.report(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--port", type=int, default=8704)
    ap.add_argument("--res-x", type=int, default=1600)
    ap.add_argument("--res-y", type=int, default=900)
    ap.add_argument("--warmup", type=float, default=16.0)
    args = ap.parse_args(argv)
    if args.list:
        for name, what, switches in VARIANTS:
            print(f"{name:14s} {what}\n{'':14s} {' '.join(switches)}")
        return 0
    return LightSweep(args).go()


if __name__ == "__main__":
    raise SystemExit(main())
