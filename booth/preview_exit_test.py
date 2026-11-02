"""The region preview window's exit test (brief 017) — the whole beat, end to end.

    python\\python.exe booth\\preview_exit_test.py
    ... --keep              leave everything up afterwards
    ... --headless          no visible browser (then the desktop shots show only the games)

What it proves, in the order the booth does it (plan v6 §4 step 7, §7, §11):

  1. a portal-driven visit, every press through `pad_helper.py --simulate`: brand, Content 1
     approved, Game A, slot A1, Japan and India ticked and bid, the rival's counter-bid, a
     raise in Japan only, the staff close-auction combo — **won in Japan, lost in India**;
  2. the Start menu's **Region check** opens. The portal asks the pad helper over its own
     WebSocket, the helper moves the window onto the rectangle the portal leaves free, and
     the second copy of the game is there, as a player in India, showing **the India
     rival's building in A1** — not the visitor's;
  3. the region is flipped to Japan from the portal. The same window, the same slot, the
     same moment: now it shows **the visitor's own content**;
  4. the step is left. The window goes away and the portal has the whole screen back;
  5. the **live-flip fallback** (plan v6 §11): the menu's second row makes the *main* game
     play as India for twenty seconds, A1 swaps to the India rival in front of the Player,
     and it swaps back by itself;
  6. through all of it the **main game keeps focus** (so it keeps pad 1), and at the end it
     is deliberately put in the background to show it is still running and still drawing.
     Its frame time is reported for each phase, from its own status file.

Three real programs, not stand-ins: the packaged Shipping build twice (the main game and
the preview), and the pad helper. Nothing is clicked.

The frame-time table it prints is of the main game while all this happens, phase by phase,
from its own cumulative counters. It is not the **pass/fail** test — that is ten minutes a
side and lives in `unreal/Tools/preview_frametime_test.py`; this one is a few minutes and
says whether anything fell over while the window came and went.

**One monitor, one screen.** The booth has two monitors; this PC has one, so the portal, the
main game and the preview window share it: the preview sits topmost over the portal's
reserved rectangle (which is what the booth does too), and the main game is parked in the
bottom-left where it cannot cover that rectangle. Every beat is therefore captured twice —
the **desktop** (what a camera would see, including the preview window) and the **portal
page** (what the browser is drawing under it) — and the preview rectangle is cropped out of
the desktop shot on its own. On the booth's two screens nothing overlaps at all.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(ROOT / "tools"))
import dc_paths                                                          # noqa: E402

VENV_PY = dc_paths.demo_python()
EXE = dc_paths.game_exe()
LOG_DIR = ROOT / "unreal" / "_build" / "logs"

sys.path.insert(0, str(ROOT / "booth"))
import pad_helper                                          # noqa: E402
import portal_exit_test as pet                             # noqa: E402

# Where the main game's window goes on this one-monitor PC: the bottom-left, which is the
# half of the screen the preview window's home rectangle never touches.
MAIN_WINDOW = (0, 540, 960, 540)

BRAND_COLOUR = "#E23D3D"          # the first preset colour; the India rival is #F28C28


# --------------------------------------------------------------------------- win32

user32 = ctypes.WinDLL("user32", use_last_error=True)


def window_for_pid(pid: int) -> int | None:
    """The first top-level visible window belonging to a process."""
    found: list[int] = []

    def visit(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(pad_helper.ENUM_WINDOWS_PROC(visit), 0)
    return found[0] if found else None


def window_title(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, len(buffer))
    return buffer.value


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    box = pad_helper.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box)):
        return None
    return (box.left, box.top, box.right - box.left, box.bottom - box.top)


def foreground() -> tuple[int, str, int]:
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(hwnd), window_title(int(hwnd)), int(pid.value)


def window_titled(fragment: str) -> int | None:
    """The first visible top-level window whose title contains this."""
    found: list[int] = []
    buffer = ctypes.create_unicode_buffer(512)

    def visit(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            if fragment.lower() in buffer.value.lower():
                found.append(int(hwnd))
                return False
        return True

    user32.EnumWindows(pad_helper.ENUM_WINDOWS_PROC(visit), 0)
    return found[0] if found else None


def take_focus(hwnd: int) -> bool:
    """Make a window the foreground one from a process that is not in the foreground.

    Windows refuses `SetForegroundWindow` to a process that has not received input
    recently; the documented way round it is to synthesise a key event first, so this
    thread counts as having had input. The key is ALT, pressed and released, because it
    does nothing on its own in either the game or the browser.
    """
    KEYEVENTF_KEYUP, VK_MENU = 0x0002, 0x12
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    return bool(user32.SetForegroundWindow(wintypes.HWND(hwnd)))


# --------------------------------------------------------------------------- the run

class PreviewRun:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out = Path(args.out)
        self.base = f"http://127.0.0.1:{args.port}"
        self.stamp = time.strftime("%Y%m%d_%H%M%S")
        self.work = Path(tempfile.mkdtemp(prefix="dc_preview_exit_"))
        self.main_status = self.work / "main_status.json"
        self.preview_status = self.work / "preview_status.json"
        self.window_file = self.work / "dc_preview_window.json"
        self.quit_file = self.work / "dc_quit"
        self.failures: list[str] = []
        self.notes: list[str] = []
        self.desktop_shots: list[tuple[str, Path]] = []
        self.phases: list[dict[str, Any]] = []
        self.main: subprocess.Popen | None = None
        self.preview: subprocess.Popen | None = None
        self.main_hwnd: int | None = None
        self._main_pid: int | None = None

    # ---- bookkeeping ------------------------------------------------------------------

    def fail(self, line: str) -> None:
        self.failures.append(line)
        print(f"  FAIL  {line}", flush=True)

    def note(self, line: str) -> None:
        self.notes.append(line)
        print(f"  {line}", flush=True)

    def api(self, path: str) -> Any:
        with urllib.request.urlopen(f"{self.base}{path}", timeout=8) as response:
            return json.loads(response.read())

    def post(self, path: str, body: dict | None = None) -> Any:
        data = json.dumps(body or {}).encode("utf-8")
        request = urllib.request.Request(f"{self.base}{path}", data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")

    def status(self, path: Path) -> dict[str, Any]:
        for _ in range(12):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(0.12)      # it is rewritten four times a second
        return {}

    # ---- the desktop ------------------------------------------------------------------

    def shot_desktop(self, name: str) -> None:
        """What a camera pointed at the screen would see, plus the preview rectangle on its
        own - the booth's "right monitor's relevant area"."""
        from PIL import ImageGrab

        time.sleep(0.6)
        image = ImageGrab.grab(all_screens=True)
        path = self.out / f"desktop_{name}.png"
        image.save(path)
        self.desktop_shots.append((name, path))

        home = self.preview_home()
        if home:
            x, y, w, h = home
            crop = image.crop((max(x, 0), max(y, 0), min(x + w, image.width),
                               min(y + h, image.height)))
            if crop.width > 8 and crop.height > 8:
                crop_path = self.out / f"previewarea_{name}.png"
                crop.save(crop_path)
                self.desktop_shots.append((f"{name} (the preview's rectangle)", crop_path))
        print(f"  desktop shot {name}", flush=True)

    def preview_home(self) -> tuple[int, int, int, int] | None:
        try:
            data = json.loads(self.window_file.read_text(encoding="utf-8"))
            box = data["home"]
            return (int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"]))
        except Exception:                                  # noqa: BLE001
            return None

    def preview_window_state(self) -> dict:
        return pad_helper.PreviewWindow(state_file=self.window_file).state()

    # ---- frame time -------------------------------------------------------------------

    def mark_phase(self, name: str) -> None:
        """One reading of the main game's cumulative frame counters."""
        frames = self.status(self.main_status).get("frame_ms", {})
        self.phases.append({"name": name, "at": time.time(), **frames})

    def phase_table(self) -> list[str]:
        rows = ["| phase | seconds | frames | average | worst 1 % (run) | over 16 ms | "
                "over 25 ms |", "|---|---|---|---|---|---|---|"]
        for before, after in zip(self.phases, self.phases[1:]):
            frames = int(after.get("frames", 0)) - int(before.get("frames", 0))
            total = float(after.get("sum_ms", 0.0)) - float(before.get("sum_ms", 0.0))
            over16 = int(after.get("over_16ms", 0)) - int(before.get("over_16ms", 0))
            over25 = int(after.get("over_25ms", 0)) - int(before.get("over_25ms", 0))
            seconds = after["at"] - before["at"]
            average = total / frames if frames else 0.0
            rows.append(f"| {after['name']} | {seconds:.0f} s | {frames} | "
                        f"**{average:.2f} ms** ({1000.0 / average if average else 0:.0f} fps) "
                        f"| {float(after.get('worst_1_percent', 0.0)):.2f} ms | {over16} | "
                        f"**{over25}** |")
        return rows

    def main_pid(self) -> int | None:
        """The pid of the process that owns the main game's window.

        Not the pid Popen gave us: the archived build's `DCDemo.exe` is a launcher that
        starts the real executable, so the window belongs to a child. The game writes its
        own pid into its status file, which is the only honest source for it.
        """
        # Read once and keep it: the status file is rewritten four times a second, and a
        # read that lands mid-write comes back empty - which, asked twice in one
        # comparison, makes a window its own pid "not the main game".
        if self._main_pid is None:
            pid = self.status(self.main_status).get("pid")
            self._main_pid = int(pid) if pid else None
        return self._main_pid

    def check_focus(self, when: str) -> None:
        _hwnd, title, pid = foreground()
        mine = self.main_pid() is not None and pid == self.main_pid()
        if mine:
            self.note(f"focus {when}: the main game ({title!r})")
        else:
            self.fail(f"focus {when}: {title!r} (pid {pid}), not the main game "
                      f"(pid {self.main_pid()})")

    # ---- starting things --------------------------------------------------------------

    def start_server(self) -> subprocess.Popen:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.out.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, DCSERVER_DATA=str(self.work / "data"),
                   DCSERVER_LOG="WARNING")
        log = (self.out / "server.log").open("w", encoding="utf-8")
        process = subprocess.Popen(
            [str(VENV_PY), "-m", "uvicorn", "dcserver.asgi:app", "--host", "127.0.0.1",
             "--port", str(self.args.port), "--log-level", "warning"],
            cwd=str(SERVER_DIR), env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
        pet.wait_for_http(f"{self.base}/admin/health")
        pet.wait_for_http(f"{self.base}/portal/")
        return process

    def seed_the_rival(self) -> None:
        """Put the India rival in A1 for the length of the test.

        The booth's attract rotation alternates the region's rival and the developer's
        default block by block, so on a server one minute old A1 in India could be showing
        either. The beat under test is "the India rival's building is there, not yours", so
        the test writes that block itself with the same admin call a rehearsal uses. Its
        kind is `rival`, so it never becomes the preview's focus - that follows the visitor.
        """
        health = self.api("/admin/health")
        rival = (health.get("system_packs") or {}).get("rival2") or {}
        content_id = rival.get("content_id")
        if not content_id:
            self.fail("the server has no rival2 content to put in A1")
            return
        written = self.post("/admin/allocate", {
            "game": "A", "slot": "A1", "region": "r2", "content_id": content_id,
            "minutes": 45.0})
        self.note(f"A1 in India: {written['piece']} {written['version']} "
                  f"({written['kind']})")

    def start_preview(self) -> subprocess.Popen:
        args = [
            str(EXE), "-DCMap=/Game/Maps/GameA",
            "-windowed", "-ResX=960", "-ResY=540",
            "-DCPreview", "-DCFollowRegion", "-nosound",
            # Its own Saved folder, or the lowest scalability it is about to apply is
            # persisted into the GameUserSettings.ini the *main* game reads next time.
            f"-UserDir={self.work / 'preview_userdir'}",
            f"-DCBackend={self.base}", "-DCGame=A", "-DCRegion=r2",
            f"-DCCacheDir={self.work / 'preview_packcache'}",
            f"-DCStatusFile={self.preview_status}",
            f"-DCLogFile={LOG_DIR / f'previewexit_{self.stamp}_preview.log'}",
            f"-DCPreviewFile={self.window_file}",
            f"-DCQuitWhenFileExists={self.quit_file}",
            f"-DCRunSeconds={self.args.seconds}",
        ]
        print("starting the region preview window (before the main game, so the main game "
              "ends up with the focus)", flush=True)
        return subprocess.Popen(args)

    def start_main(self) -> subprocess.Popen:
        x, y, w, h = MAIN_WINDOW
        args = [
            str(EXE), "-DCMap=/Game/Maps/GameA",
            "-windowed", f"-ResX={w}", f"-ResY={h}", f"-WinX={x}", f"-WinY={y}",
            # Its own Saved folder as well, so a test run starts from the build's own
            # settings and leaves none of its own behind.
            f"-UserDir={self.work / 'main_userdir'}",
            f"-DCBackend={self.base}", "-DCGame=A", "-DCRegion=r1",
            f"-DCCacheDir={self.work / 'main_packcache'}",
            f"-DCStatusFile={self.main_status}",
            f"-DCShotDir={self.work / 'main_shots'}",
            # The Player walks the plaza and goes in and out of the content for the whole
            # run (`-DCTourFor` starts the round again when it ends). Two reasons: the
            # frame-time table below is then of the booth's expensive case rather than of a
            # camera standing still, and a moving picture is what makes "it is still
            # rendering while it is not the foreground window" a thing that can be checked.
            "-DCTour=16", f"-DCTourFor={self.args.seconds}",
            f"-DCLogFile={LOG_DIR / f'previewexit_{self.stamp}_main.log'}",
            f"-DCQuitWhenFileExists={self.quit_file}",
            f"-DCRunSeconds={self.args.seconds}",
        ]
        print("starting the main game", flush=True)
        return subprocess.Popen(args)

    def wait_for_slot(self, status_path: Path, slot: str, piece: str,
                      seconds: float = 45.0) -> dict[str, Any]:
        """Wait until a copy of the game really has that piece on screen in that slot."""
        deadline = time.monotonic() + seconds
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = (self.status(status_path).get("slots") or {}).get(slot) or {}
            if last.get("piece") == piece and last.get("state") == "ACTIVE":
                return last
            time.sleep(0.5)
        return last

    # ---- the portal ------------------------------------------------------------------

    def move_to_region(self, run: "pet.Run", region: str, tries: int = 4) -> bool:
        """Put the cursor on a region's row. `pet.Run.focus_on` only ever presses UP."""
        for _ in range(tries):
            if run.page.get_attribute("#app", "data-focus") == region:
                return True
            run.pad.press("DOWN")
            run.page.wait_for_timeout(180)
        if run.page.get_attribute("#app", "data-focus") != region:
            self.fail(f"could not put the cursor on {region}")
            return False
        return True

    def win_a1_for_japan(self, run: "pet.Run") -> None:
        """Steps 1-6 of the tour, ending in "won in Japan, lost in India"."""
        page, pad = run.page, run.pad

        run.expect('#app[data-screen="attract"]', 25000, "the attract screen")
        page.wait_for_timeout(900)
        run.shot("00_attract")

        pad.press("A")
        run.expect('#app[data-screen="brand"]', 10000, "the brand screen")
        pad.press("A", "A", "A")                  # first colour, first emblem, use it

        run.expect('#app[data-screen="upload"][data-state="idle"]', 15000, "upload")
        run.expect(".file-row", 10000, "the file list")
        pad.press("A")                            # Content 1
        run.expect('#app[data-state="approved"]', 90000, "the approval")
        run.shot("01_approved")

        pad.press("A")                            # "pick a game"
        run.expect('#app[data-screen="games"]', 15000, "the games screen")
        pad.press("A")                            # Game A
        run.expect('#app[data-screen="slotmap"][data-slot="A1"]', 25000, "the slot map")
        page.wait_for_timeout(700)
        run.shot("02_slotmap_A1")

        pad.press("Y")
        run.expect('#app[data-screen="regions"]', 15000, "the regions screen")
        # A screen's enter() is a round trip to the server, and a press that lands during
        # it is lost. Japan is ticked already (it is the booth's own region), so a lost
        # DOWN would mean the next A unticks Japan instead of ticking India - which is
        # exactly what happened the first time this test was run, and the visitor then bid
        # on nothing at all. Wait for the screen, then check the cursor really moved.
        page.wait_for_timeout(900)
        self.move_to_region(run, "r2")
        pad.press("A")                            # tick India
        page.wait_for_timeout(400)
        ticks = page.locator('[data-ticked="1"]').count()
        if ticks != 2:
            self.fail(f"expected Japan and India ticked, got {ticks} ticked row(s)")
        run.shot("03_regions_japan_and_india")

        pad.press("Y")                            # place both bids
        run.expect('#app[data-screen="auction"]', 15000, "the auction")
        # The rival answers once, three seconds after the first bid. Raising Japan only is
        # what makes the result "won in Japan, lost in India".
        run.expect(".banner:not(.hidden)", 30000, "the rival's counter-bid")
        run.focus_on("r1")
        pad.press("Y")
        page.wait_for_timeout(700)
        run.shot("04_auction_raised_japan")

        pad.line("combo close-auction")           # the staff combo, held three seconds
        run.expect('#app[data-screen="auction"][data-state="settled"]', 25000, "the result")
        page.wait_for_timeout(500)
        run.shot("05_auction_result")
        won = page.locator(".result-card.won").count()
        lost = page.locator(".result-card.lost").count()
        if (won, lost) != (1, 1):
            self.fail(f"expected one region won and one lost, got {won} won / {lost} lost")
        else:
            self.note("the auction: won in Japan, lost in India")

    def region_check(self, run: "pet.Run") -> None:
        page, pad = run.page, run.pad

        # Live, then the report - the two screens between the auction and the Start menu.
        pad.press("A")
        run.expect('#app[data-screen="live"]', 15000, "the live screen")
        self.note("waiting for the main game to mount the visitor's content in A1")
        shown = self.wait_for_slot(self.main_status, "A1", "content1", 90.0)
        if shown.get("piece") != "content1":
            self.fail(f"the main game never put content1 in A1: {shown}")
        else:
            self.note(f"the main game shows A1 = {shown.get('piece')} "
                      f"{shown.get('version')} {shown.get('brand')} {shown.get('emblem')}")
        run.shot("06_live")
        self.mark_phase("before the region check")

        # ---- the window appears -------------------------------------------------------
        pad.press("START")
        run.expect('#app[data-menu="open"]', 12000, "the Start menu")
        # The portal asked the pad helper the moment the menu opened; the helper answers
        # with what it did, and the page records it.
        if not run.expect('#app[data-preview="shown"]', 12000, "the helper's show answer"):
            self.fail("the pad helper never reported the preview window as shown")
        page.wait_for_timeout(1200)

        # The rectangle the portal leaves free, in the page's own coordinates. On a kiosk
        # browser filling a 1920 x 1080 monitor those ARE the monitor's coordinates, which
        # is what makes the window and the gap the portal leaves coincide at the booth.
        # Checked here rather than by eye, because on this PC the browser is an ordinary
        # window with a tab bar and the two are offset by the height of that chrome.
        reserve = page.evaluate(
            "() => { const n = document.querySelector('.preview-reserve');"
            " if (!n) return null; const b = n.getBoundingClientRect();"
            " return [Math.round(b.x), Math.round(b.y), Math.round(b.width),"
            " Math.round(b.height)]; }")
        self.note(f"the portal leaves {reserve} free (page coordinates, 1920 x 1080)")
        if reserve != [960, 270, 960, 540]:
            self.fail(f"the portal's reserved rectangle is {reserve}, not the right half of "
                      f"the monitor, vertically centred")

        state = self.preview_window_state()
        home = self.preview_home()
        self.note(f"the preview window: {state}")
        if not state.get("found"):
            self.fail("no preview window on the desktop at all")
        elif not state.get("shown"):
            self.fail(f"the preview window is still off-screen: {state}")
        elif home and state.get("rect") and tuple(state["rect"]) != tuple(home):
            self.fail(f"the preview window is at {state['rect']}, not its home {home}")
        else:
            self.note(f"it is on its home rectangle {home} - the rectangle the portal's "
                      f"Region-check step leaves free")

        india = self.wait_for_slot(self.preview_status, "A1", "rival2", 60.0)
        if india.get("piece") != "rival2":
            self.fail(f"the preview window does not show the India rival in A1: {india}")
        else:
            self.note(f"the preview shows A1 = {india.get('piece')} {india.get('version')} "
                      f"{india.get('brand')} {india.get('emblem')} - the India rival's "
                      f"building, not the visitor's")
        if india.get("brand") and india["brand"].upper() == BRAND_COLOUR:
            self.fail("the preview is showing the visitor's own brand colour in India")
        preview_status = self.status(self.preview_status)
        self.note(f"the preview plays as {preview_status.get('region_label')} "
                  f"({preview_status.get('region')}), framing "
                  f"{(preview_status.get('focus') or {}).get('slot')} because "
                  f"{(preview_status.get('focus') or {}).get('reason')}")
        if (preview_status.get("focus") or {}).get("slot") != "A1":
            self.fail("the preview is not framing the slot that was just auctioned")
        if int(preview_status.get("telemetry_sent") or 0) != 0:
            self.fail("the preview window posted telemetry - it is not a player")

        self.check_focus("while the window is shown")
        run.shot("07_region_check_india")
        self.shot_desktop("07_region_check_india")

        # ---- flip it to Japan ---------------------------------------------------------
        pad.press("LEFT")                         # the region pills: India -> Japan
        page.wait_for_timeout(250)
        pad.press("A")                            # apply it
        japan = self.api("/preview/region")
        self.note(f"the portal set the preview's region to {japan['region']} "
                  f"({japan['label']})")
        if japan["region"] != "r1":
            self.fail(f"the portal set the preview to {japan['region']}, not Japan")

        yours = self.wait_for_slot(self.preview_status, "A1", "content1", 90.0)
        if yours.get("piece") != "content1":
            self.fail(f"the preview window never showed the visitor's content: {yours}")
        else:
            self.note(f"the same window, the same slot: A1 = {yours.get('piece')} "
                      f"{yours.get('version')} {yours.get('brand')} {yours.get('emblem')} "
                      f"- the visitor's own")
        if (yours.get("brand") or "").upper() != BRAND_COLOUR:
            self.fail(f"A1 in the preview is not wearing the visitor's colour: "
                      f"{yours.get('brand')}")
        self.check_focus("after the flip")
        run.shot("08_region_check_japan")
        self.shot_desktop("08_region_check_japan")
        self.mark_phase("the region check, window shown")

        # ---- leave the step -----------------------------------------------------------
        pad.press("START")                        # close the menu
        page.wait_for_timeout(1500)
        state = self.preview_window_state()
        self.note(f"after leaving the step: {state}")
        if state.get("shown"):
            self.fail(f"the preview window is still on screen after the step: {state}")
        else:
            self.note("the window is off-screen again and the portal has the whole "
                      "screen back")
        self.check_focus("after the window is hidden")
        run.shot("09_after_the_step")
        self.shot_desktop("09_after_the_step")
        page.wait_for_timeout(8000)               # a little frame time with it gone
        self.mark_phase("after it is hidden")

    def live_flip(self, run: "pet.Run") -> None:
        """The fallback of plan v6 §11, which the frame-time test's verdict calls for:
        no second window, the **main** game plays as another region for twenty seconds and
        the slot swaps in front of the Player.

        Driven from the portal exactly as the region check is - the menu's second row -
        and checked in the main game's own status file: it has to go to the other region's
        content and come back by itself.
        """
        page, pad = run.page, run.pad
        pad.press("START")
        run.expect('#app[data-menu="open"]', 12000, "the Start menu")
        page.wait_for_timeout(800)
        # Row 0 is the region picker, and it opens on whatever the preview window is
        # playing as - which the step before this one left on Japan, the main game's own
        # region. Flipping to that would be a no-op, so put the picker back on India
        # first; then row 1 is the flip.
        pad.press("RIGHT")
        page.wait_for_timeout(250)
        pad.press("DOWN")
        page.wait_for_timeout(250)
        pad.press("A")
        flip = self.api("/preview/flip").get("flip") or {}
        self.note(f"the portal asked for a live flip to {flip.get('label')} "
                  f"({flip.get('region')}) for {flip.get('seconds_left')} s")
        if flip.get("region") != "r2":
            self.fail(f"the portal asked for a flip to {flip.get('region')}, not India")
        run.shot("11_live_flip")

        flipped = self.wait_for_slot(self.main_status, "A1", "rival2", 60.0)
        status = self.status(self.main_status)
        if flipped.get("piece") != "rival2":
            self.fail(f"the main game never flipped to the India rival in A1: {flipped}")
        else:
            self.note(f"the MAIN game is now playing as {status.get('region')} and A1 is "
                      f"{flipped.get('piece')} {flipped.get('brand')} "
                      f"{flipped.get('emblem')} - the swap happened in front of the Player")
        if status.get("live_flip_back_to") != "r1":
            self.fail(f"the main game does not know where to go back to: "
                      f"{status.get('live_flip_back_to')!r}")
        self.shot_desktop("11_live_flip")

        back = self.wait_for_slot(self.main_status, "A1", "content1", 90.0)
        status = self.status(self.main_status)
        if back.get("piece") != "content1":
            self.fail(f"the main game never came back to the visitor's content: {back}")
        else:
            self.note(f"...and {status.get('region')} again by itself, with A1 back to "
                      f"{back.get('piece')} {back.get('brand')} {back.get('emblem')}")
        if status.get("live_flip_back_to"):
            self.fail("the main game still thinks it is flipped")
        pad.press("START")                        # close the menu
        page.wait_for_timeout(600)

    def grab_window(self, hwnd: int | None):
        """A picture of one window's rectangle off the desktop."""
        from PIL import ImageGrab

        box = window_rect(hwnd) if hwnd else None
        if not box:
            return None
        x, y, w, h = box
        return ImageGrab.grab(all_screens=True).crop(
            (max(x, 0), max(y, 0), max(x, 0) + w, max(y, 0) + h))

    def unfocused_check(self, run: "pet.Run") -> None:
        """Plan v6 §11, day-1 check 4: both copies keep running **and rendering** when they
        are not the foreground window.

        The preview window proves half of it by existing - it is never focused and it is
        plainly drawing. This is the other half, and it is left until last because it is the
        one thing in this test that deliberately takes focus away from the main game: the
        browser is brought to the front, and the main game's own frame counter and its
        pixels are read twice while it is in the background.
        """
        from PIL import ImageChops

        run.page.bring_to_front()
        time.sleep(1.0)
        if foreground()[2] == self.main_pid():
            browser = window_titled("brand portal")
            if browser:
                take_focus(browser)
                time.sleep(1.0)
        _hwnd, title, pid = foreground()
        if pid == self.main_pid():
            self.note("could not take focus off the main game, so this check says nothing")
            return
        self.note(f"focus handed to {title!r} on purpose - the main game is now in the "
                  f"background")

        before = self.status(self.main_status).get("frame_ms", {})
        first = self.grab_window(self.main_hwnd)
        time.sleep(5.0)
        after = self.status(self.main_status).get("frame_ms", {})
        second = self.grab_window(self.main_hwnd)

        frames = int(after.get("frames", 0)) - int(before.get("frames", 0))
        seconds = 5.0
        if frames < 60:
            self.fail(f"the unfocused main game only ticked {frames} frame(s) in "
                      f"{seconds:.0f} s - it is being throttled in the background")
        else:
            self.note(f"unfocused, the main game still ran at {frames / seconds:.0f} fps "
                      f"({frames} frames in {seconds:.0f} s)")
        if first is not None and second is not None and first.size == second.size:
            different = ImageChops.difference(first.convert("RGB"),
                                              second.convert("RGB")).getbbox()
            if different is None:
                self.fail("the unfocused main game's window did not change at all - it has "
                          "stopped drawing")
            else:
                self.note("and it was still drawing: its window is a different picture five "
                          "seconds later")
            second.save(self.out / "mainwindow_10_unfocused.png")
        else:
            self.note("could not compare two pictures of the main game's window")

    # ---- the whole thing --------------------------------------------------------------

    def go(self) -> int:
        from playwright.sync_api import sync_playwright

        if not EXE.is_file():
            print(f"no packaged build at {EXE}")
            return 2
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True, exist_ok=True)

        server = self.start_server()
        pad = None
        browser = None
        try:
            self.seed_the_rival()
            # The helper is told where the preview window writes itself down, so it can put
            # the window on its home rectangle the first time it is asked - before it has
            # ever seen it on screen.
            pad = pet.Pad(self.args.pad_port, self.base, self.out / "pad_helper.log",
                          extra=["--preview-file", str(self.window_file)])
            pad.line("preview state")

            self.preview = self.start_preview()
            time.sleep(10)                        # let it place its window and fill A1

            with sync_playwright() as play:
                launch: dict[str, Any] = {"channel": "msedge",
                                          "headless": self.args.headless}
                if not self.args.headless:
                    # Kiosk, so the page is exactly the screen and the desktop shots show
                    # the portal as the booth's browser draws it. The scale factor has to
                    # be pinned: this PC's display scaling is not 100 %, and the portal's
                    # type sizes are "px at 1080p", so without it every string on screen
                    # measures two thirds of what the ten-foot rule asks for.
                    launch["args"] = ["--kiosk", "--window-position=0,0",
                                      "--window-size=1920,1080",
                                      "--force-device-scale-factor=1",
                                      # the booth's kiosk has none of these, and a
                                      # "translate this page?" bubble over the portal is
                                      # not what the shots are of. It stays after the
                                      # English-only ruling: the booth PC may well be a
                                      # Japanese Windows, and Edge would then offer to
                                      # translate an English page instead.
                                      "--disable-features=Translate,TranslateUI",
                                      "--no-first-run", "--no-default-browser-check"]
                browser = play.chromium.launch(**launch)
                # The viewport is pinned at 1080p in both modes, because the portal's type
                # sizes are "px at 1080p" and this PC's display scaling is not 100 %: a
                # kiosk window that fills the screen is only 1280 x 720 CSS pixels, and
                # every string then measures two thirds of what it will at the booth. With
                # the viewport pinned, the page is laid out at 1920 x 1080 and drawn scaled
                # into the window - so the audit sees the booth's sizes and the screen sees
                # the booth's picture.
                # en-US: the portal has been English only since 2026-11-02, so the page
                # and the browser agree and nothing offers to translate anything. It used
                # to be ja-JP, for a Japanese page on a Japanese machine.
                context = browser.new_context(viewport=pet.VIEWPORT, device_scale_factor=1,
                                              locale="en-US")
                page = context.new_page()
                url = f"{self.base}/portal/?pad={self.args.pad_port}&idle=900"
                print(f"opening {url}", flush=True)
                page.goto(url)
                page.wait_for_selector('#app[data-pad="online"]', timeout=25000)

                # Last, so that it is the window Windows leaves focused.
                self.main = self.start_main()
                time.sleep(14)
                self.main_hwnd = window_for_pid(self.main_pid() or 0)
                if self.main_hwnd:
                    self.note(f"the main game's window: {window_title(self.main_hwnd)!r} at "
                              f"{window_rect(self.main_hwnd)}")
                self.check_focus("at the start")
                self.mark_phase("start")

                run = pet.Run(page, pad, self.out, self.base)
                self.win_a1_for_japan(run)
                self.region_check(run)
                if not self.args.no_flip:
                    self.live_flip(run)
                self.unfocused_check(run)

                self.failures += run.failures
                if run.shots:
                    pet.contact_sheet(run.shots, self.out / "contact_sheet_portal.png")
                if self.desktop_shots:
                    pet.contact_sheet(self.desktop_shots,
                                      self.out / "contact_sheet_desktop.png")

                if self.args.keep:
                    input("--keep: everything is still up; press enter to stop it... ")
                else:
                    browser.close()
                    browser = None
        finally:
            if browser is not None and not self.args.keep:
                try:
                    browser.close()
                except Exception:                          # noqa: BLE001
                    pass
            if not self.args.keep:
                # The quit file first: both copies watch for it and stop themselves, which
                # is the only way that also stops the child process the launcher started.
                game_pids = [self.status(p).get("pid") for p in
                             (self.main_status, self.preview_status)]
                self.quit_file.write_text("stop", encoding="utf-8")
                for name, process in (("main game", self.main), ("preview", self.preview)):
                    if process is None:
                        continue
                    try:
                        process.wait(timeout=40)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    print(f"{name} stopped", flush=True)
                # Belt and braces: a launcher that was killed can leave its child behind,
                # and a headless run must leave nothing running.
                for pid in [p for p in game_pids if p]:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                   capture_output=True, check=False)
                if pad:
                    pad.stop()
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                print("server stopped", flush=True)

        return self.report()

    def report(self) -> int:
        lines = ["# The region preview window: the exit test", "",
                 f"*`booth/preview_exit_test.py`, {time.strftime('%Y-%m-%d %H:%M')}. The "
                 f"packaged Shipping build twice (the main game and the preview), the demo "
                 f"server, the pad helper and the portal - every press simulated through "
                 f"the helper, nothing clicked.*", "", "## What happened", ""]
        lines += [f"* {line}" for line in self.notes]
        lines += ["", "## The main game's frame time, phase by phase", "",
                  "*Its own counters, from the status file it writes four times a second. "
                  "The worst 1 % column is over the whole run so far, which is why it only "
                  "grows.*", ""]
        lines += self.phase_table()
        if self.failures:
            lines += ["", "## Failures", ""] + [f"* {f}" for f in self.failures]
        lines += ["", f"**{'FAILED' if self.failures else 'PASSED'}**", ""]
        text = "\n".join(lines) + "\n"
        (self.out / "result.md").write_text(text, encoding="utf-8")
        print("\n" + text, flush=True)
        print(f"wrote {self.out / 'result.md'}", flush=True)
        shutil.rmtree(self.work, ignore_errors=True)
        return 1 if self.failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8797)
    ap.add_argument("--pad-port", type=int, default=8703)
    ap.add_argument("--out", default=str(ROOT / "booth" / "_shots" / "017"))
    ap.add_argument("--seconds", type=int, default=900,
                    help="how long each copy of the game is allowed to live")
    ap.add_argument("--headless", action="store_true",
                    help="no visible browser; the desktop shots then show only the games")
    ap.add_argument("--no-flip", action="store_true",
                    help="skip the live-flip fallback (plan v6 §11)")
    ap.add_argument("--keep", action="store_true")
    return PreviewRun(ap.parse_args(argv)).go()


if __name__ == "__main__":
    raise SystemExit(main())
