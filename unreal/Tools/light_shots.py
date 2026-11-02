"""The lighting budget's before/after pictures (brief 018 part 1).

    python\\python.exe unreal\\Tools\\light_shots.py
    ... --only after          one of the three passes
    ... --sheet-only          rebuild the sheet from shots that are already there

Three laps of the scripted tour of Game A, in the same build, against the same server, with
one thing different each time:

  `off`     the wall lamps are built but switched off (`-DCTourLightB=0`)
  `before`  switched on, lighting the Lumen scene - brief 016 as it shipped
  `after`   switched on, out of the Lumen scene - brief 018's lighting budget

The tour already walks into every piece and photographs the inside, so the three passes
produce the same three interiors three times over. This script crops the middle of each and
lays them out as one sheet: nine pictures, three rows, so "lights on vs off is still
obvious" and "on looks the same as it used to" are both things a person can check by
looking rather than things a report asserts.
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
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent.parent
SERVER_DIR = REPO / "server"
sys.path.insert(0, str(REPO / "tools"))
import dc_paths                                                          # noqa: E402

PYTHON = dc_paths.demo_python()
EXE = dc_paths.game_exe()
WORK = REPO / "unreal" / "_build" / "lightshots"
OUT = REPO / "unreal" / "spike" / "shots" / "018"
LOG_DIR = REPO / "unreal" / "_build" / "logs"

BRAND = {"colour": "#E23D3D", "emblem": "star"}
PLAN = [("A1", "content1_v1.real.dcpack"),
        ("A2", "content3_v1.real.dcpack"),
        ("A3", "content4_v1.real.dcpack")]

PASSES = [
    ("off", "wall lamps off, ceiling fixtures as before", ["-DCTourLightB=0", "-DCLightAGi=1"]),
    ("before", "wall lamps on, both groups lighting the Lumen scene (brief 016)",
     ["-DCLightBGi=1", "-DCLightAGi=1"]),
    ("b_nogi", "wall lamps on but out of the Lumen scene, ceiling fixtures still in it",
     ["-DCLightBGi=0", "-DCLightAGi=1"]),
    ("nogi", "wall lamps on, both groups out of the Lumen scene (brief 018)",
     ["-DCLightBGi=0", "-DCLightAGi=0"]),
    ("off_nogi", "wall lamps off, both groups out of the Lumen scene - the other half of "
                 "the on/off question", ["-DCTourLightB=0", "-DCLightAGi=0"]),
    # REJECTED, and kept here so the reason is on the sheet: it is the fastest row, and
    # `dc_kit.light_a_fixture` models a **fitting** at every group-A socket. Lighting one
    # socket in two leaves half the ceiling fittings modelled and dead - which none of
    # these eye-level shots happens to show, and anybody standing inside and looking up
    # would.
    ("a_half", "REJECTED: half the ceiling fixtures at twice the lumens - the fastest row, "
               "but the other half are modelled fittings left dark",
     ["-DCLightBGi=0", "-DCLightAGi=1", "-DCLightAEvery=2"]),
]

PAD, GAP = 18, 8
TILE_W = 520
HEADER_H = 92
LABEL_H = 34
ROW_LABEL_W = 150
BG = (26, 28, 32)
FG = (232, 236, 240)
SUB = (150, 158, 168)
ACCENT = (120, 200, 230)


def font(size: int, bold: bool = False):
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


class LightShots:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.port = args.port
        self.url = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.url, timeout=120.0)
        self.server: subprocess.Popen | None = None
        self.content: dict[str, str] = {}
        self.stamp = time.strftime("%Y%m%d_%H%M%S")

    def api(self, method: str, path: str, **kw) -> Any:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        return r.json()

    def start_server(self) -> None:
        data = Path(os.environ["TEMP"]) / "dc_lightshots_data"
        shutil.rmtree(data, ignore_errors=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = LOG_DIR / f"lightshots_{self.stamp}_server.log"
        env = dict(os.environ, DCSERVER_DATA=str(data))
        self.server = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "dcserver.asgi:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"],
            cwd=str(SERVER_DIR), env=env, stdout=log.open("wb"),
            stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                self.api("GET", "/admin/health")
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
            result = self.api("POST", "/content", files={
                "file": (filename, path.read_bytes(), "application/octet-stream")})
            self.content[filename] = result["content_id"]
        for slot, filename in PLAN:
            self.api("POST", "/admin/allocate",
                     json={"game": "A", "slot": slot, "region": "r1",
                           "content_id": self.content[filename], "minutes": 90.0})

    def run(self, name: str, switches: list[str]) -> dict[str, Any]:
        where = WORK / name
        shots = where / "shots"
        for path in (shots, where / "packcache", where / "userdir"):
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)

        args = [
            str(EXE), "-DCMap=/Game/Maps/GameA",
            "-windowed", f"-ResX={self.args.res_x}", f"-ResY={self.args.res_y}",
            f"-UserDir={where / 'userdir'}",
            f"-DCBackend={self.url}", "-DCGame=A", "-DCRegion=r1",
            "-DCTour=16", f"-DCShotDir={shots}",
            f"-DCCacheDir={where / 'packcache'}",
            f"-DCLogFile={LOG_DIR / f'lightshots_{self.stamp}_{name}.log'}",
            "-DCRunSeconds=420",
        ] + switches

        print(f"== {name}: {' '.join(switches) or '(the build defaults)'}", flush=True)
        started = time.time()
        proc = subprocess.Popen(dc_paths.game_cmdline(args))
        try:
            code = proc.wait(timeout=480)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = proc.wait(timeout=30)
        print(f"   exit {code} after {time.time() - started:.0f}s", flush=True)

        tour = shots / "dc_tour.json"
        return json.loads(tour.read_text(encoding="utf-8")) if tour.is_file() else {}

    # ---- the sheet ----------------------------------------------------------------------

    def sheet(self, frames: dict[str, Any]) -> Path:
        slots = [slot for slot, _ in PLAN]
        tiles: dict[tuple[str, str], Image.Image] = {}
        tile_h = 0
        for name, _what, _switches in PASSES:
            for slot in slots:
                found = sorted((WORK / name / "shots").glob(f"*_{slot}_inside.png"))
                if not found:
                    continue
                image = Image.open(found[0]).convert("RGB")
                # The middle of the frame: the inside shot is over the Player's shoulder,
                # so the middle is the room and the edges are the doorway and the HUD.
                w, h = image.size
                box = (int(w * 0.18), int(h * 0.10), int(w * 0.92), int(h * 0.92))
                crop = image.crop(box)
                scale = TILE_W / crop.width
                crop = crop.resize((TILE_W, int(crop.height * scale)), Image.LANCZOS)
                tiles[(name, slot)] = crop
                tile_h = max(tile_h, crop.height)
        if not tiles:
            raise RuntimeError("no interior shots to build a sheet out of")

        width = PAD * 2 + ROW_LABEL_W + len(slots) * TILE_W + (len(slots) - 1) * GAP
        height = (PAD * 2 + HEADER_H + LABEL_H
                  + len(PASSES) * (tile_h + GAP) + 30)
        sheet = Image.new("RGB", (width, height), BG)
        draw = ImageDraw.Draw(sheet)

        draw.text((PAD, PAD), "The lighting budget: the wall lamps inside each piece",
                  font=font(30, True), fill=FG)
        draw.text((PAD, PAD + 38),
                  "One lap of the scripted tour of Game A, once per setting, same build "
                  "and same server.  **b_nogi** is what brief 018 shipped: it is the one "
                  "row that is the same picture as **before**.",
                  font=font(17), fill=SUB)
        draw.text((PAD, PAD + 62),
                  "solo frame-time average over each lap:   " + "   ".join(
                      f"{name} {frames.get(name, {}).get('average', 0):.2f} ms"
                      for name, _w, _s in PASSES if name in frames),
                  font=font(17), fill=ACCENT)

        y = PAD + HEADER_H
        for slot in slots:
            x = PAD + ROW_LABEL_W + slots.index(slot) * (TILE_W + GAP)
            draw.text((x, y), f"{slot}", font=font(21, True), fill=FG)
        y += LABEL_H

        for name, what, _switches in PASSES:
            draw.text((PAD, y + 8), name, font=font(20, True), fill=ACCENT)
            words, line_no = what.split(" "), 0
            line = ""
            for word in words:
                if len(line) + len(word) + 1 > 20:
                    draw.text((PAD, y + 34 + line_no * 18), line, font=font(13), fill=SUB)
                    line_no, line = line_no + 1, word
                else:
                    line = (line + " " + word).strip()
            if line:
                draw.text((PAD, y + 34 + line_no * 18), line, font=font(13), fill=SUB)
            for index, slot in enumerate(slots):
                tile = tiles.get((name, slot))
                if tile is None:
                    continue
                x = PAD + ROW_LABEL_W + index * (TILE_W + GAP)
                sheet.paste(tile, (x, y))
            y += tile_h + GAP

        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / "lighting_before_after.png"
        sheet.save(path)
        print(f"wrote {path}", flush=True)
        return path

    def go(self) -> int:
        WORK.mkdir(parents=True, exist_ok=True)
        # Merged, not overwritten: a second run of one pass must not throw away the frame
        # times of the passes it is being compared against.
        frames: dict[str, Any] = {}
        if (WORK / "frames.json").is_file():
            frames = json.loads((WORK / "frames.json").read_text(encoding="utf-8"))
        if not self.args.sheet_only:
            try:
                self.start_server()
                self.setup()
                for name, _what, switches in PASSES:
                    if self.args.only and name not in self.args.only.split(","):
                        continue
                    tour = self.run(name, switches)
                    frames[name] = tour.get("frame_ms", {})
            finally:
                self.stop_server()
            (WORK / "frames.json").write_text(json.dumps(frames, indent=2), encoding="utf-8")
        self.sheet(frames)
        return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="")
    ap.add_argument("--sheet-only", action="store_true")
    ap.add_argument("--port", type=int, default=8706)
    ap.add_argument("--res-x", type=int, default=1600)
    ap.add_argument("--res-y", type=int, default=900)
    return LightShots(ap.parse_args(argv)).go()


if __name__ == "__main__":
    raise SystemExit(main())
