"""Walk and photograph one of the demo maps with the server up (brief 012 §5).

    server\\.venv\\Scripts\\python.exe unreal\\Tools\\map_check.py --game A
    server\\.venv\\Scripts\\python.exe unreal\\Tools\\map_check.py --game B --keep-server-data

What it does, for one map:

1. starts the demo server on a clean data folder, so every pack it serves is one of the real
   cooked packs in `server\\demo_files\\*.real.dcpack`;
2. uploads the visitor's pieces, sets a brand, and writes **one visitor allocation per slot**
   through `POST /admin/allocate` - so each slot is showing a different brand's content and
   not just the attract rotation;
3. starts the **packaged Shipping build**, which contains none of that content, on that map
   with `-DCTour`: it takes an overview shot, a framed shot of every slot, then **walks the
   Player from the spawn to each slot and in through its door**, with a shot from the door
   and one from inside;
4. reads the game's own `dc_tour.json` - the walk results and the frame times - and prints it;
5. stops the game and the server.

The game and the server both stop themselves; nothing is left running.
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
OUT_ROOT = REPO / "unreal" / "_build" / "runtime" / "maps"
LOG_DIR = REPO / "unreal" / "_build" / "logs"

LONG_MINUTES = 40.0
BRAND = {"colour": "#E23D3D", "emblem": "star"}

# Which piece goes in which slot. content3 only fits the tall slot and content4 is the only
# visitor piece that fits a small one, by the size classes in the server's config.
PLAN = {
    "A": {"map": "/Game/Maps/GameA",
          "slots": [("A1", "content1_v1.real.dcpack"),
                    ("A2", "content3_v1.real.dcpack"),
                    ("A3", "content4_v1.real.dcpack")]},
    "B": {"map": "/Game/Maps/GameB",
          "slots": [("B1", "content2_v1.real.dcpack"),
                    ("B2", "content4_v2.real.dcpack")]},
}


class MapCheck:
    def __init__(self, args):
        self.game = args.game.upper()
        self.plan = PLAN[self.game]
        self.port = args.port
        self.url = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.url, timeout=120.0)
        self.region = args.region
        self.keep_data = args.keep_server_data
        self.server_data = Path(args.server_data
                                or (Path(os.environ["TEMP"]) / "dc_map_check_data"))
        self.out = OUT_ROOT / self.game
        self.shot_dir = self.out / "shots"
        self.cache_dir = self.out / "packcache"
        self.status_file = self.out / "dc_status.json"
        self.quit_file = self.out / "dc_quit"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.dc_log = LOG_DIR / f"map_{self.game}_{stamp}_dc.log"
        self.server_log = LOG_DIR / f"map_{self.game}_{stamp}_server.log"
        self.res_x, self.res_y = args.res_x, args.res_y
        self.warmup = args.warmup
        self.server: subprocess.Popen | None = None
        self.content: dict[str, str] = {}

    # ---- server -----------------------------------------------------------------------
    def api(self, method: str, path: str, **kw) -> dict[str, Any]:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        return r.json()

    def start_server(self) -> None:
        if not self.keep_data and self.server_data.exists():
            shutil.rmtree(self.server_data, ignore_errors=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, DCSERVER_DATA=str(self.server_data))
        print(f"starting the server on 127.0.0.1:{self.port} (data {self.server_data})",
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
                print(f"server ok: key={health['key_fingerprint']}", flush=True)
                return
            except (httpx.HTTPError, RuntimeError):
                time.sleep(0.4)
        raise RuntimeError(f"the server never answered - see {self.server_log}")

    def stop_server(self) -> None:
        if self.server and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.server.kill()
            print("server stopped", flush=True)

    def upload(self, filename: str) -> str:
        path = SERVER_DIR / "demo_files" / filename
        if not path.is_file():
            raise RuntimeError(f"{path} is missing - run make_fake_packs.py --real --force")
        files = {"file": (filename, path.read_bytes(), "application/octet-stream")}
        result = self.api("POST", "/content", files=files)
        if result["status"] != "approved":
            raise RuntimeError(f"{filename} was rejected: {result.get('reason')}")
        print(f"  uploaded {filename:30} -> {result['content_id']} "
              f"{result['piece']} {result['version']}", flush=True)
        return result["content_id"]

    def setup(self) -> None:
        self.api("POST", "/admin/reset")
        self.api("POST", "/preview/region", json={"region": self.region})
        self.api("POST", "/brand", json=BRAND)
        print("uploading the visitor's content (real cooked packs):", flush=True)
        for slot, filename in self.plan["slots"]:
            if filename not in self.content:
                self.content[filename] = self.upload(filename)
        for slot, filename in self.plan["slots"]:
            written = self.api("POST", "/admin/allocate",
                               json={"game": self.game, "slot": slot, "region": self.region,
                                     "content_id": self.content[filename],
                                     "minutes": LONG_MINUTES})
            print(f"  allocated {slot} <- {written['piece']} {written['version']} "
                  f"({written['kind']})", flush=True)

    # ---- game -------------------------------------------------------------------------
    def run_game(self) -> int:
        if not EXE.is_file():
            raise RuntimeError(f"no packaged build at {EXE}")
        for path in (self.shot_dir, self.cache_dir):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)
        self.status_file.unlink(missing_ok=True)
        self.quit_file.unlink(missing_ok=True)

        args = [
            str(EXE),
            f"-DCMap={self.plan['map']}",
            "-windowed", f"-ResX={self.res_x}", f"-ResY={self.res_y}",
            f"-DCBackend={self.url}", f"-DCGame={self.game}", f"-DCRegion={self.region}",
            f"-DCTour={self.warmup}",
            f"-DCShotDir={self.shot_dir}", f"-DCStatusFile={self.status_file}",
            f"-DCCacheDir={self.cache_dir}", f"-DCLogFile={self.dc_log}",
            f"-DCQuitWhenFileExists={self.quit_file}", "-DCRunSeconds=900",
        ]
        print(f"running the packaged game on {self.plan['map']} with the scripted tour",
              flush=True)
        started = time.time()
        proc = subprocess.Popen(args)
        try:
            code = proc.wait(timeout=960)
        except subprocess.TimeoutExpired:
            print("the game outstayed its welcome - stopping it", flush=True)
            self.quit_file.write_text("stop", encoding="utf-8")
            try:
                code = proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
                code = proc.wait(timeout=30)
        print(f"game exit {code} after {time.time() - started:.0f}s", flush=True)
        return code

    # ---- report -----------------------------------------------------------------------
    def report(self) -> int:
        tour_path = self.shot_dir / "dc_tour.json"
        if not tour_path.is_file():
            print(f"NO TOUR REPORT at {tour_path}", flush=True)
            return 1
        tour = json.loads(tour_path.read_text(encoding="utf-8"))
        f = tour["frame_ms"]

        lines = ["", "=" * 96,
                 f"GAME {self.game}  ({tour['map']})   build {tour['build']}   "
                 f"{tour['shots']} shot(s) in {tour['seconds']:.0f} s",
                 "-" * 96, "slots:"]
        for s in tour["slots"]:
            lines.append(f"  {s['slot']:<3} {s['size_class']:<2} {s['state']:<12} "
                         f"{s['piece']} {s['version']} "
                         f"{s.get('brand') or 'no-brand'} {s.get('emblem') or ''} "
                         f"({s.get('kind')})")
        lines.append("walks:")
        ok = 0
        for w in tour["walks"]:
            mark = "ok  " if w["arrived"] else "FAIL"
            if w["arrived"]:
                ok += 1
            lines.append(f"  {mark} {w['slot']:<3} {w['leg']:<22} {w['seconds']:5.1f} s  "
                         f"{w['metres']:6.1f} m walked  {w['final_gap_cm']:5.0f} cm short"
                         + (f"  {w['note']}" if w["note"] else ""))
        lines.append(f"  {ok}/{len(tour['walks'])} legs arrived")
        lines.append(f"frame time at {self.res_x}x{self.res_y}: "
                     f"average {f['average']:.2f} ms ({f['average_fps']:.0f} fps)  ·  "
                     f"median {f['median']:.2f} ms  ·  worst 1% {f['worst_1_percent']:.2f} ms"
                     f"  ·  worst {f['worst']:.2f} ms  ({f['frames']} frames)")
        lines.append("=" * 96)
        text = "\n".join(lines)
        print(text, flush=True)
        (self.out / "map_check_result.txt").write_text(text + "\n", encoding="utf-8")
        shots = sorted(p.name for p in self.shot_dir.glob("*.png"))
        print("shots: " + ", ".join(shots), flush=True)
        return 0 if ok == len(tour["walks"]) and tour["walks"] else 1

    def go(self) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        try:
            self.start_server()
            self.setup()
            self.run_game()
        finally:
            self.stop_server()
        return self.report()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default="A", choices=["A", "B", "a", "b"])
    ap.add_argument("--region", default="r1")
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--server-data", default="")
    ap.add_argument("--keep-server-data", action="store_true")
    ap.add_argument("--res-x", type=int, default=1600)
    ap.add_argument("--res-y", type=int, default=900)
    ap.add_argument("--warmup", type=float, default=16.0,
                    help="seconds to let the slots fill before the tour starts")
    return MapCheck(ap.parse_args(argv)).go()


if __name__ == "__main__":
    raise SystemExit(main())
