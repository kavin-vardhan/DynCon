"""The exit test for a copy of this tree on a machine nobody has set up.

    python\\python.exe booth\\office_exit_test.py
    python\\python.exe booth\\office_exit_test.py --fast     # do not wait out the auction
    python\\python.exe booth\\office_exit_test.py --no-shots # no pictures of the desktop

Start the demo first - `Start-Demo.bat`, no arguments - and then run this. It drives one
round of the walkthrough in README.txt against the demo that is actually running: the real
server, the real packaged game, from this folder, with nothing installed.

Why this one and not the others
-------------------------------
`booth/portal_exit_test.py` already drives the whole visitor tour, but it drives it through
a real browser with Playwright, and Playwright and its browser binaries are hundreds of
megabytes that have to be downloaded - which is the one thing a copy of this tree must never
need. So this test calls the same endpoints the portal's own screens call, in the same
order, and watches the REAL game through the status file it writes. The browser is up on
screen beside it, in every picture this takes, and is simply not what is being driven.

What it checks
--------------
   1 everything is up            the server, the game, and the game's three slots filled
   2 the brand                   a colour and an emblem, and a wallet of 2,000
   3 upload, approved            the four checks run and pass
   4 upload, rejected            the engine-5.3 file, refused, with its reason
   5 pick a game, pick a slot    Game A, the slot map, A1 in the first region
   6 bid, and the rival outbids
   7 raise, the clock closes, won
   8 the game mounts it          the real game, in the real slot, with the brand on it
   9 the region check            the live flip: the main game plays as another region for
                                 twenty seconds and comes back
  10 push version 2              the game swaps, the brand kept
  11 the report                  the views the game posted
  12 the block ends              the slot goes back to the rival, the credits are charged
  13 nothing went anywhere       every TCP connection every process of this copy opened,
                                 by owning process, sampled throughout the run

and it leaves a contact sheet of the desktop, one picture a step, and `result.json`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dc_paths                                                          # noqa: E402

BRAND = {"colour": "#2F6FEB", "emblem": "chevron"}
# Not part of the demo, and not sampled: see Connections.
BROWSERS = {"msedge.exe", "msedgewebview2.exe", "chrome.exe", "firefox.exe", "iexplore.exe"}
SLOT = "A1"
GAME = "A"
FLIP_SECONDS = 20.0


PREVIEW_TITLE = "DynamicContents region preview"


def raise_game_window() -> tuple[int, int, int, int] | None:
    """Bring the main game's window to the front and say where it is - or say it could not.

    A screen grab photographs whatever is drawn in a rectangle, not whatever window owns
    it, so a picture of "the game's rectangle" taken while something else is in front of it
    is a picture of that something else. The first run of this test produced seven of them,
    of a browser window that had nothing to do with the demo.

    So this does two things rather than one. It brings the window to the front properly -
    AttachThreadInput first, because Windows will not let a background process take the
    foreground without it - and then it CHECKS, and returns None if the game is not in
    fact in front. `shot` takes no picture at all in that case. A missing picture says
    something true; a picture of somebody's desktop does not.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    found: list[tuple[int, str, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _param):                                           # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        found.append((int(hwnd), buffer.value, int(owner.value)))
        return True

    user32.EnumWindows(visit, 0)
    names = game_process_names()
    windows = [hwnd for hwnd, title, owner in found
               if owner in names and title != PREVIEW_TITLE]
    if not windows:
        return None
    hwnd = windows[0]

    SW_SHOW, SW_RESTORE = 5, 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, SW_SHOW)
    front = user32.GetForegroundWindow()
    mine = kernel32.GetCurrentThreadId()
    theirs = user32.GetWindowThreadProcessId(front, None) if front else 0
    attached = bool(theirs) and bool(user32.AttachThreadInput(mine, theirs, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(mine, theirs, False)

    time.sleep(0.4)
    return hwnd if int(user32.GetForegroundWindow()) == hwnd else None


def window_box(hwnd: int) -> tuple[int, int, int, int] | None:
    """Where that window is, but only while it is still the one in front.

    Checked again here, immediately before the grab, and not only when it was raised: on a
    machine with other things running, something else can take the foreground back in the
    half second between the two, and the picture would then be of that instead. One of the
    seven pictures in the first good run was exactly that.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    if int(user32.GetForegroundWindow()) != hwnd:
        return None
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if rect.right - rect.left < 16 or rect.bottom - rect.top < 16:
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


def game_process_names() -> set[int]:
    """The pids of every running copy of the packaged game."""
    script = ("Get-Process -Name 'DCDemo*' -ErrorAction SilentlyContinue | "
              "Select-Object -ExpandProperty Id")
    done = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True)
    return {int(line) for line in done.stdout.split() if line.strip().isdigit()}


def first_token(command_line: str | None) -> str:
    """The program a command line asks for, lower-cased, quotes taken off."""
    text = (command_line or "").strip()
    if not text:
        return ""
    if text.startswith('"'):
        return text[1:].split('"', 1)[0].lower()
    return text.split(" ", 1)[0].lower()


# =========================================================================== what is open
class Connections:
    """Every TCP connection the server, the game and the pad helper opened.

    Sampled with `netstat -ano` in a thread - no package, no privileges - and matched
    against a process table, so "this copy's processes" is a fact rather than a guess. A
    process counts if any of these is true:

      * `Start-Demo` recorded it in `_run\\demo_run.json`
      * the program it is running lives under this folder
      * the program NAMED ON its command line lives under this folder, which is how the
        server is found when it is started through a virtual environment's launcher: the
        launcher re-executes the base interpreter, so the running image is that one and
        only the command line still says which interpreter was asked for. The first token
        of the command line, not any part of it - a shell whose arguments happen to mention
        this folder is not a process of this copy
      * its parent counts (the packaged game's exe is a launcher, and uvicorn runs its
        socket in a child)

    THE BROWSER IS DELIBERATELY NOT IN THE SET. It is a browser: it talks to whatever is on
    the page and, left to itself, to its own update and telemetry services. What is being
    checked here is that the DEMO never reaches past this machine, and the browser is not
    part of the demo - it only renders a page the demo serves. It is started with
    background networking, sync and component updates switched off, in a profile folder of
    its own inside this copy, which is as far as a start script can go.
    """

    def __init__(self, root: Path) -> None:
        self.root = str(root).lower()
        self.rows: set[tuple[str, str, str, str]] = set()      # (process, local, remote, state)
        self.samples = 0
        self.excluded: list[str] = []
        self.processes: dict[str, str] = {}
        self._seeds = self._seed_pids()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- the process table -------------------------------------------------------------

    def _seed_pids(self) -> set[int]:
        """What Start-Demo says it started, minus the browser."""
        state = self.root and (Path(self.root) / "_run" / "demo_run.json")
        try:
            rows = json.loads(Path(state).read_text(encoding="utf-8"))["processes"]
        except (OSError, ValueError, KeyError, TypeError):
            return set()
        out = set()
        for row in rows:
            if "edge" in str(row.get("what", "")).lower():
                self.excluded.append(f"{row['what']} (pid {row['pid']})")
                continue
            out.add(int(row["pid"]))
        return out

    def _table(self) -> dict[int, dict[str, Any]]:
        script = ("Get-CimInstance Win32_Process | Select-Object "
                  "ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | "
                  "ConvertTo-Json -Compress -Depth 2")
        done = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                              capture_output=True, text=True)
        try:
            rows = json.loads(done.stdout or "[]")
        except ValueError:
            return {}
        if isinstance(rows, dict):
            rows = [rows]
        return {int(row["ProcessId"]): row for row in rows if row.get("ProcessId")}

    def _processes(self) -> dict[int, tuple[str, str]]:
        """{pid: (name, why it counts)} for the demo's own processes."""
        table = self._table()
        excluded = {int(line.rsplit("pid ", 1)[1].rstrip(")")) for line in self.excluded
                    if "pid " in line}
        mine: dict[int, tuple[str, str]] = {}

        def banned(pid: int) -> bool:
            """Is this process a browser, or a child of one?

            By name as well as by pid: a browser re-launches itself at startup, so the pid
            Start-Demo recorded is often already gone and the chain up from a tab's process
            leads nowhere. The name is the thing that does not change.
            """
            seen: set[int] = set()
            while pid in table and pid not in seen:
                if pid in excluded:
                    return True
                if str(table[pid].get("Name") or "").lower() in BROWSERS:
                    return True
                seen.add(pid)
                pid = int(table[pid].get("ParentProcessId") or 0)
            return False

        for pid, row in table.items():
            exe = (row.get("ExecutablePath") or "").lower()
            why = ""
            if pid in self._seeds:
                why = "started by Start-Demo"
            elif exe.startswith(self.root):
                why = "its program is in this folder"
            elif first_token(row.get("CommandLine")).startswith(self.root):
                why = "the program on its command line is in this folder"
            if why and not banned(pid):
                mine[pid] = (row.get("Name") or "?", why)

        # ... and anything descended from one of those.
        changed = True
        while changed:
            changed = False
            for pid, row in table.items():
                if pid in mine or banned(pid):
                    continue
                parent = int(row.get("ParentProcessId") or 0)
                if parent in mine:
                    mine[pid] = (row.get("Name") or "?", f"a child of pid {parent}")
                    changed = True
        return {pid: (name, why) for pid, (name, why) in mine.items()}

    # ---- a sample ----------------------------------------------------------------------

    def sample(self) -> None:
        mine = self._processes()
        if not mine:
            return
        done = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                              text=True)
        for line in done.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4 or not parts[0].upper().startswith("TCP"):
                continue
            local, remote, state, pid = (parts[1], parts[2], parts[3],
                                         parts[4] if len(parts) > 4 else parts[3])
            if len(parts) == 4:                       # LISTENING rows have no state column
                local, remote, state, pid = parts[1], parts[2], "", parts[3]
            try:
                owner = int(pid)
            except ValueError:
                continue
            if owner in mine:
                self.rows.add((f"{mine[owner][0]} (pid {owner})", local, remote, state))
        self.processes.update({f"{name} (pid {pid})": why
                               for pid, (name, why) in mine.items()})
        self.samples += 1

    def start(self, every: float = 2.0) -> None:
        def loop() -> None:
            while not self._stop.wait(every):
                try:
                    self.sample()
                except Exception:                                      # noqa: BLE001
                    pass
        self.sample()
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        try:
            self.sample()
        except Exception:                                              # noqa: BLE001
            pass

    # ---- the answer --------------------------------------------------------------------

    @staticmethod
    def _host(address: str) -> str:
        if address.startswith("["):
            return address[1:address.rfind("]")]
        return address.rsplit(":", 1)[0] if ":" in address else address

    def outward(self) -> list[tuple[str, str, str, str]]:
        """Every row whose far end is not this machine."""
        allowed = {"127.0.0.1", "0.0.0.0", "::", "::1", "*", ""}
        return sorted(row for row in self.rows if self._host(row[2]) not in allowed)

    def table(self) -> list[str]:
        # Only the ones that opened something. The set is wider than this - it includes the
        # console hosts Windows gives a process and the shells this test runs to read the
        # process table - and a process with no socket has nothing to say here.
        opened = {row[0] for row in self.rows}
        quiet = sorted(set(self.processes) - opened)
        lines = ["the demo's own processes that opened a socket, and why each one counts:"]
        for name in sorted(opened):
            lines.append(f"  {name:38} {self.processes.get(name, '')}")
        lines.append(f"  and {len(quiet)} more in the set that never opened one")
        if self.excluded:
            lines.append("not sampled, on purpose: " + ", ".join(self.excluded)
                         + " - a browser talks to whatever is on the page, and to its own "
                           "update service; it renders the portal, it is not the demo")
        lines.append("")
        lines.append(f"{'process':38} {'local':24} {'remote':24} state")
        for process, local, remote, state in sorted(self.rows):
            lines.append(f"{process:38} {local:24} {remote:24} {state}")
        return lines


# ================================================================================ the test
class Run:
    def __init__(self, url: str, out: Path, fast: bool, shots: bool) -> None:
        self.url = url.rstrip("/")
        self.http = httpx.Client(base_url=self.url, timeout=180.0)
        self.out = out
        self.fast = fast
        self.shots_wanted = shots
        self.checks: list[tuple[bool, str, str]] = []
        self.shots: list[tuple[str, Path]] = []
        self.content_id = ""
        self.lot_id = ""
        self.won = 0
        self.status_path = ROOT / "_run" / "dc_status.json"
        self.connections = Connections(ROOT)
        self.started = time.time()

    # ---- plumbing ----------------------------------------------------------------------

    def api(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        response = self.http.request(method, path, **kw)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {response.status_code} "
                               f"{response.text[:300]}")
        return response.json()

    def step(self, number: int, title: str) -> None:
        print(f"\n=== {number} - {title} " + "=" * max(4, 60 - len(title)), flush=True)

    def say(self, text: str) -> None:
        print(f"    {text}", flush=True)

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        self.checks.append((bool(ok), label, detail))
        print(f"    [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""),
              flush=True)
        return bool(ok)

    def shot(self, name: str) -> None:
        """A picture of the GAME'S WINDOW, not of the desktop.

        Of the window on purpose, and twice over. A whole-desktop grab photographs whatever
        else is open on the machine the test is run on, which is nobody's business and would
        end up committed; and it photographs whatever is in front, which on a working
        machine is not the game. So `raise_game_window` brings the game to the front, checks
        that it got there, and only then is its own rectangle saved.
        """
        if not self.shots_wanted:
            return
        try:
            from PIL import ImageGrab
            hwnd = raise_game_window()
            box = None
            if hwnd:
                time.sleep(0.6)
                box = window_box(hwnd)
            if not box:
                self.say("no picture: the game's window is not in front, and a picture of "
                         "its rectangle would be a picture of whatever is")
                return
            image = ImageGrab.grab(bbox=box, all_screens=True)
            path = self.out / f"{len(self.shots) + 1:02d}_{name}.png"
            image.save(path)
            self.shots.append((name, path))
            self.say(f"picture {path.name}  {image.width}x{image.height}")
        except Exception as exc:                                       # noqa: BLE001
            self.say(f"no picture ({exc})")

    def status(self) -> dict[str, Any]:
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def wait_for(self, what: str, test, seconds: float = 90.0, every: float = 1.0):
        """Poll the game's status file until `test(status)` is true. Returns the status."""
        deadline = time.monotonic() + seconds
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.status()
            try:
                if last and test(last):
                    return last
            except (KeyError, TypeError):
                pass
            time.sleep(every)
        self.say(f"gave up waiting for {what} after {seconds:.0f}s")
        return last

    def slot(self, status: dict[str, Any] | None = None) -> dict[str, Any]:
        return ((status or self.status()).get("slots") or {}).get(SLOT) or {}

    # ---- the walkthrough ---------------------------------------------------------------

    def go(self) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        self.connections.start()

        # ------------------------------------------------------------------------------ 1
        self.step(1, "everything is up")
        health = self.api("GET", "/admin/health")
        self.say(f"server {health['mode']}, signing key {health['key_fingerprint']}, "
                 f"{health['demo_files']} files on the brand's computer")
        self.check(bool(health["ok"]), "the server answers",
                   f"block {health['clock']['block_seconds']:.0f}s, "
                   f"{health['clock']['block_ends_in_s']:.0f}s of this one left")
        self.check(all(row["pack_id"] for row in health["system_packs"].values()),
                   "the game's own packs are registered",
                   ", ".join(sorted(health["system_packs"])))
        self.check(all(health["registered_games"].values()),
                   "both games are registered with their maps")

        status = self.wait_for("the game to fill its slots",
                               lambda s: all(v.get("state") == "ACTIVE"
                                             for v in (s.get("slots") or {}).values())
                               and (s.get("slots") or {}),
                               seconds=180.0)
        self.check(bool(status), "the game is writing its status file",
                   str(self.status_path.relative_to(ROOT)))
        slots = status.get("slots") or {}
        self.say(f"build {status.get('build')}, region {status.get('region')}, "
                 f"{status.get('packs_mounted')} pack(s) mounted, "
                 f"backend {status.get('backend')}")
        for name, row in sorted(slots.items()):
            self.say(f"  {name} {row['state']:8} {row['piece']} {row['version']} "
                     f"({row['kind']})")
        self.check(bool(slots) and all(v["state"] == "ACTIVE" for v in slots.values()),
                   "every slot is filled, downloaded and mounted at run time",
                   f"{len(slots)} slots")
        self.check(str(status.get("backend", "")).startswith("http://127.0.0.1"),
                   "the game talks to this machine and nowhere else",
                   str(status.get("backend")))
        self.shot("attract_all_slots_mounted")

        # ------------------------------------------------------------------------------ 2
        self.step(2, "the brand")
        # First, what the staff combo does between visitors: throw away the brand, the
        # content and the allocations of whoever was here before, so the walkthrough starts
        # from the same place every time. It is also the only way this test can be run twice
        # against one server and mean the same thing both times.
        reset = self.api("POST", "/admin/reset", json={"reason": "staff"})
        self.say(f"reset for the next visitor: generation {reset['reset_generation']}")
        brand = self.api("POST", "/brand", json=BRAND)["brand"]
        purse = self.api("GET", "/wallet")
        self.check(brand["colour"] == BRAND["colour"] and brand["emblem"] == BRAND["emblem"],
                   "a brand is a colour and an emblem",
                   f"{brand['colour']} {brand['emblem']}")
        self.check(purse["available"] == 2000, "the wallet starts at 2,000", str(purse))

        # ------------------------------------------------------------------------------ 3
        self.step(3, "upload, approved")
        listing = self.api("GET", "/demo-files")["files"]
        self.say("on the brand's computer: " + ", ".join(
            f"{row['name']} ({row['bytes'] / 1048576:.1f} MB"
            + (f", {row['note']}" if row["note"] else "") + ")" for row in listing))
        self.check(len(listing) >= 2 and sum(1 for r in listing if r["note"]) == 1,
                   "the list is one file per piece plus one built to fail",
                   f"{len(listing)} files")
        good = next(row for row in listing if row["piece"] == "content1" and not row["note"])
        blob = self.http.get(f"/demo-files/{good['name']}").content
        upload = self.api("POST", "/content",
                          files={"file": (good["name"], blob, "application/octet-stream")})
        for row in upload["checks"]:
            self.say(f"check {row['check']:9} {row['state']:8} {row['detail']}")
        self.content_id = upload["content_id"]
        self.check(upload["status"] == "approved",
                   "approved, with all four checks shown",
                   f"{self.content_id} {upload['piece']} {upload['version']}")
        mine = next(row for row in self.api("GET", "/content")["content"]
                    if row["content_id"] == self.content_id)
        self.check(mine["fits"][SLOT]["ok"], f"it fits {SLOT}",
                   f"{mine['bounds']['x']:.1f} x {mine['bounds']['y']:.1f} x "
                   f"{mine['bounds']['z']:.1f} m")

        # ------------------------------------------------------------------------------ 4
        self.step(4, "upload, rejected")
        bad = next(row for row in listing if row["note"])
        blob = self.http.get(f"/demo-files/{bad['name']}").content
        refused = self.api("POST", "/content",
                           files={"file": (bad["name"], blob, "application/octet-stream")})
        for row in refused["checks"]:
            self.say(f"check {row['check']:9} {row['state']:8} {row['detail']}")
        self.check(refused["status"] == "rejected" and refused["reason"],
                   "refused, and it says why in a sentence",
                   f"{refused['failed_check']}: {refused['reason']}")

        # ------------------------------------------------------------------------------ 5
        self.step(5, f"pick the game, pick {SLOT}")
        games = self.api("GET", "/games")["games"]
        self.say(" | ".join(f"{g['label']}: {g['slot_count']} slots, "
                            f"{g['players_online']} players online" for g in games))
        card = self.api("GET", f"/games/{GAME}")
        target = next(s for s in card["slots"] if s["id"] == SLOT)
        region = sorted(target["lots"])[0]
        lot = target["lots"][region]
        self.lot_id = lot["lot_id"]
        self.say(f"{SLOT} is class {target['size_class']} - {target['limits_words']}")
        self.say(f"{lot['region_label']}: opening {lot['opening']}, held by {lot['holder']}, "
                 f"footfall {target['footfall'][region]['per_demo_hour']} a demo hour")
        self.check(lot["closes_in_s"] is None, "no clock until the first bid")
        self.shot("slot_map")

        # ------------------------------------------------------------------------------ 6
        self.step(6, "bid, and the rival outbids")
        first = self.api("POST", "/bids", json={
            "slot": SLOT, "content_id": self.content_id,
            "bids": [{"region": region, "amount": lot["opening"] + 25,
                      "lot_id": self.lot_id}]})["results"][0]
        self.say(f"bid {lot['opening'] + 25} -> {first['reason']}")
        self.check(first["accepted"] and first["lot"]["state"] == "running",
                   "the first bid starts the clock",
                   f"{first['lot']['closes_in_s']:.0f}s left")
        deadline = time.monotonic() + 20
        live = self.api("GET", f"/lots/{self.lot_id}")
        while not live["rival_has_bid"] and time.monotonic() < deadline:
            time.sleep(1.0)
            live = self.api("GET", f"/lots/{self.lot_id}")
        for row in live["history"]:
            self.say(f"  {row['at'][11:19]}  {row['bidder']:6} {row['amount']:>4}  "
                     f"{row['note']}")
        self.check(live["rival_has_bid"] and live["holder"] == "rival",
                   "the rival raised and took the lead",
                   f"{live['highest']}, its ceiling is {live['rival_max']}")

        # ------------------------------------------------------------------------------ 7
        self.step(7, "raise, the clock closes, won")
        raised = self.api("POST", "/bids", json={
            "slot": SLOT, "content_id": self.content_id,
            "bids": [{"region": region, "amount": live["next_bid"],
                      "lot_id": self.lot_id}]})["results"][0]
        self.won = live["next_bid"]
        self.check(raised["accepted"] and raised["lot"]["holder"] == "you",
                   "back in front", str(self.won))
        if self.fast:
            self.say("--fast: closing the lot with the staff control instead of waiting")
            self.api("POST", "/admin/close-auction", json={"lot_id": self.lot_id})
        else:
            live = self.api("GET", f"/lots/{self.lot_id}")
            while live["state"] != "closed":
                left = live["closes_in_s"]
                self.say(f"  {left:5.1f}s left, highest {live['highest']} "
                         f"({live['holder']})")
                time.sleep(min(6.0, max(left + 0.4, 0.5)))
                live = self.api("GET", f"/lots/{self.lot_id}")
        live = self.api("GET", f"/lots/{self.lot_id}")
        purse = self.api("GET", "/wallet")
        self.check(live["state"] == "closed" and live["won_by"] == "you",
                   "the auction closed and the visitor won",
                   f"charged {live['charged']}, allocation {live['allocation_id']}")
        self.check(purse["charged"] == self.won, "the credits were charged", str(purse))

        # ------------------------------------------------------------------------------ 8
        self.step(8, "the game mounts it")
        status = self.wait_for(
            f"{SLOT} to show the visitor's content",
            lambda s: self.slot(s).get("kind") == "visitor"
            and self.slot(s).get("state") == "ACTIVE", seconds=180.0)
        row = self.slot(status)
        self.say(f"{SLOT} {row.get('state')}: {row.get('piece')} {row.get('version')} "
                 f"{row.get('brand')} {row.get('emblem')} ({row.get('kind')})")
        self.check(row.get("kind") == "visitor" and row.get("piece") == "content1"
                   and row.get("version") == "v1",
                   f"{SLOT} is showing the visitor's own content, version 1")
        self.check(row.get("brand", "").lower() == BRAND["colour"].lower()
                   and row.get("emblem") == BRAND["emblem"],
                   "in the brand's colour, with the brand's emblem")
        self.shot("A1_visitor_v1_mounted")

        # ------------------------------------------------------------------------------ 9
        self.step(9, "the region check: the live flip")
        before = status.get("region")
        regions = self.api("GET", "/config/public")["regions"]
        other = next(rid for rid in regions if rid != before)
        label = regions[other]["label"]
        flip = self.api("POST", "/preview/flip",
                        json={"region": other, "seconds": FLIP_SECONDS})
        self.say(f"the portal asks for {label} for {FLIP_SECONDS:.0f}s: "
                 f"{json.dumps(flip['flip'])[:160]}")
        flipped = self.wait_for("the game to play as the other region",
                                lambda s: s.get("region") == other, seconds=30.0)
        self.check(flipped.get("region") == other,
                   "the main game is playing as the other region",
                   f"{before} -> {flipped.get('region')}, "
                   f"{SLOT} is {self.slot(flipped).get('piece')} "
                   f"({self.slot(flipped).get('kind')})")
        self.shot("live_flip")
        back = self.wait_for("the flip to end",
                             lambda s: s.get("region") == before,
                             seconds=FLIP_SECONDS + 40.0)
        self.check(back.get("region") == before, "and back again, on its own",
                   f"{SLOT} is {self.slot(back).get('piece')} "
                   f"{self.slot(back).get('version')} "
                   f"({self.slot(back).get('kind')})")

        # ----------------------------------------------------------------------------- 10
        self.step(10, "push version 2")
        updates = self.api("GET", "/demo-files", params={"purpose": "update"})["files"]
        self.say("the update screen offers: " + ", ".join(r["name"] for r in updates))
        pick = next(row for row in updates if row["piece"] == "content1")
        blob = self.http.get(f"/demo-files/{pick['name']}").content
        pushed = self.api("POST", f"/content/{self.content_id}/versions",
                          files={"file": (pick["name"], blob, "application/octet-stream")})
        self.check(pushed["status"] == "approved" and pushed["version_n"] == 2,
                   "version 2 approved", f"{pushed['piece']} {pushed['version']}")
        status = self.wait_for(f"{SLOT} to swap to version 2",
                               lambda s: self.slot(s).get("version") == "v2"
                               and self.slot(s).get("state") == "ACTIVE", seconds=180.0)
        row = self.slot(status)
        self.check(row.get("version") == "v2" and row.get("kind") == "visitor",
                   "the live game swapped to version 2 without restarting",
                   f"{row.get('piece')} {row.get('version')}")
        self.check(row.get("brand", "").lower() == BRAND["colour"].lower(),
                   "the brand came through the swap", str(row.get("brand")))
        self.say("the Player was not inside it, so it swapped at once. The 'push it while "
                 "somebody is inside, swap on the way out, keep what they changed' case is "
                 "unreal\\Tools\\state_exit_test.py, which drives a Player.")
        self.shot("A1_visitor_v2_swapped")

        # ----------------------------------------------------------------------------- 11
        self.step(11, "the report")
        report = self.api("GET", "/report")
        self.say(f"views are {report['views_model']}")
        for row in report["regions"]:
            self.say(f"  {row['label']:7} blocks {row['blocks']} views {row['views']:>5} "
                     f"({row['views_simulated']} simulated + {row['views_live']} live) "
                     f"visits {row['visits']} dwell {row['dwell_s']:>5.1f}s "
                     f"interactions {row['interactions']:>2} charged {row['charged']:>4}")
        ours = next(r for r in report["regions"] if r["region"] == region)
        self.check(ours["charged"] == self.won and ours["blocks"] >= 1,
                   "the report is the block the visitor bought",
                   f"{ours['blocks']} block(s), {ours['charged']} charged")
        self.check(ours["views_live"] >= 1 or ours["mounts"] >= 1,
                   "and it counts what the live game told the server",
                   f"{ours['views_live']} live view(s) from {ours['mounts']} mount(s)")
        self.shot("report")

        # ----------------------------------------------------------------------------- 12
        self.step(12, "the block ends")
        self.api("POST", "/admin/end-block",
                 json={"game": GAME, "slot": SLOT, "region": region})
        status = self.wait_for(f"{SLOT} to go back to the game's own content",
                               lambda s: self.slot(s).get("kind") != "visitor"
                               and self.slot(s).get("state") == "ACTIVE", seconds=180.0)
        row = self.slot(status)
        self.check(row.get("kind") in ("rival", "default"),
                   "the slot went back to what wins it next",
                   f"{row.get('piece')} {row.get('version')} ({row.get('kind')})")
        live = [r for r in self.api("GET", "/status/live")["showing"]
                if r["slot"] == SLOT and r["region"] == region]
        self.check(bool(live) and live[0]["kind"] != "visitor",
                   "and the server agrees about what is showing",
                   f"{live[0]['piece']} ({live[0]['kind']})" if live else "nothing")
        self.shot("block_ended")

        # ----------------------------------------------------------------------------- 13
        self.step(13, "nothing went anywhere")
        self.connections.stop()
        for line in self.connections.table():
            self.say(line)
        outward = self.connections.outward()
        self.check(not outward,
                   "every connection this copy opened was to this machine",
                   f"{self.connections.samples} samples, {len(self.connections.rows)} "
                   f"distinct connection(s)")
        for row in outward:
            self.say(f"  OUTWARD: {row}")

        return self.finish()

    # ---- the answer --------------------------------------------------------------------

    def finish(self) -> int:
        failed = [row for row in self.checks if not row[0]]
        sheet = self.contact_sheet()
        result = {
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime(self.started)),
            "seconds": round(time.time() - self.started, 1),
            "root": str(ROOT),
            "url": self.url,
            "checks": [{"ok": ok, "label": label, "detail": detail}
                       for ok, label, detail in self.checks],
            "passed": len(self.checks) - len(failed),
            "failed": len(failed),
            "shots": [{"name": name, "file": path.name} for name, path in self.shots],
            "contact_sheet": sheet.name if sheet else None,
            "connections": self.connections.table(),
            "outward_connections": [list(row) for row in self.connections.outward()],
            "samples": self.connections.samples,
        }
        (self.out / "result.json").write_text(json.dumps(result, indent=1) + "\n",
                                              encoding="utf-8", newline="\n")
        print("")
        print(f"{len(self.checks) - len(failed)} passed, {len(failed)} failed, "
              f"in {result['seconds']:.0f}s", flush=True)
        for _, label, detail in failed:
            print(f"  FAILED: {label}" + (f" - {detail}" if detail else ""), flush=True)
        print(f"result  {self.out / 'result.json'}", flush=True)
        if sheet:
            print(f"sheet   {sheet}", flush=True)
        return 1 if failed else 0

    def contact_sheet(self) -> Path | None:
        if not self.shots:
            return None
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return None
        columns = 2
        width = 900
        thumbs = []
        for name, path in self.shots:
            with Image.open(path) as image:
                scale = width / image.width
                thumbs.append((name, image.convert("RGB").resize(
                    (width, max(1, int(image.height * scale))), Image.LANCZOS)))
        rows = (len(thumbs) + columns - 1) // columns
        cell_h = max(t.height for _, t in thumbs) + 26
        sheet = Image.new("RGB", (columns * width + (columns + 1) * 10,
                                  rows * cell_h + 10), (24, 24, 28))
        draw = ImageDraw.Draw(sheet)
        for index, (name, thumb) in enumerate(thumbs):
            column, row = index % columns, index // columns
            x = 10 + column * (width + 10)
            y = 10 + row * cell_h
            draw.text((x + 2, y), f"{index + 1:02d}  {name}", fill=(220, 220, 225))
            sheet.paste(thumb, (x, y + 18))
        path = self.out / "contact_sheet.png"
        sheet.save(path)
        return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8700")
    ap.add_argument("--out", type=Path, default=ROOT / "booth" / "_shots" / "office")
    ap.add_argument("--fast", action="store_true",
                    help="close the auction with the staff control instead of waiting it out")
    ap.add_argument("--no-shots", action="store_true", help="take no pictures")
    args = ap.parse_args(argv)

    run = Run(args.url, args.out.resolve(), args.fast, not args.no_shots)
    try:
        run.api("GET", "/admin/health")
    except Exception as exc:                                           # noqa: BLE001
        print(f"nothing is answering {args.url}: {exc}", flush=True)
        print("Start the demo first: Start-Demo.bat", flush=True)
        return 2
    if not (ROOT / "_run" / "dc_status.json").is_file():
        print(f"the game is not writing {ROOT / '_run' / 'dc_status.json'} - this test "
              f"drives the demo that Start-Demo.bat started, and the game is part of it.",
              flush=True)
        return 2
    try:
        return run.go()
    finally:
        run.connections.stop()


if __name__ == "__main__":
    print(f"office exit test, in {ROOT}", flush=True)
    print(f"interpreter {dc_paths.demo_python()}", flush=True)
    sys.exit(main())
