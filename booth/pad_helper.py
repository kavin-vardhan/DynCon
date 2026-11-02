"""The booth's pad helper: controller 2 -> the brand portal, the staff combos, and the
show/hide of the region preview window.

    py -3 booth\\pad_helper.py                       # the booth setup: read controller 2
    py -3 booth\\pad_helper.py --pad 1               # read controller 1 instead
    py -3 booth\\pad_helper.py --list                # just say which pads are plugged in
    py -3 booth\\pad_helper.py --simulate --stdin    # a fake pad driven by typed lines
    py -3 booth\\pad_helper.py --simulate --script walk.txt

Why this exists at all
----------------------
The portal is a web page in a kiosk browser on the right-hand monitor. A browser only gets
game-pad input while its window has focus, and at a booth the focus is wherever staff last
clicked. So the pad is read *outside* the browser, here, and the presses are relayed over a
WebSocket on 127.0.0.1 that the page listens to. The portal therefore never needs focus,
and one helper can also do the three things a web page must never be allowed to do: talk to
the admin endpoints, tell a staff combo apart from a visitor mashing buttons, and move
another program's window.

What it sends (one JSON object per WebSocket text frame):

    {"type": "hello",   "pad": 2, "simulate": false, "controllers": [...]}
    {"type": "button",  "button": "A", "pressed": true, "repeat": false, "t": 1234.5}
    {"type": "staff",   "action": "reset", "ok": true, "detail": "..."}
    {"type": "preview", "shown": true, "found": true, "rect": [960, 270, 960, 540]}

What it listens for (the portal is the only thing that sends it anything):

    {"type": "preview", "show": true}        the Region-check step opened / closed

Staff combos (hold all three for 3 seconds):

    LB + RB + Back  ->  POST /admin/reset
    LB + RB + X     ->  POST /admin/close-auction {"lot_id": "all"}
    LB + RB + Y     ->  POST /admin/sabotage {"mode": "corrupt"}
    LB + RB + B     ->  POST /admin/sabotage {"mode": "freeze"}

While LB and RB are both held, nothing else is relayed to the portal: a combo can never
leak into the screen as a stray press.

No third-party packages: XInput, the window moving and the WebSocket server are all ctypes
and plain sockets. That matters because this has to run on the booth PC from a clean
checkout with nothing installed.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import queue
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path

# --------------------------------------------------------------------------- XInput

XINPUT_DLLS = ("XInput1_4.dll", "XInput1_3.dll", "XInput9_1_0.dll")
ERROR_SUCCESS = 0
ERROR_DEVICE_NOT_CONNECTED = 1167

BUTTON_BITS = {
    0x0001: "UP", 0x0002: "DOWN", 0x0004: "LEFT", 0x0008: "RIGHT",
    0x0010: "START", 0x0020: "BACK",
    0x0040: "LS", 0x0080: "RS",
    0x0100: "LB", 0x0200: "RB",
    0x1000: "A", 0x2000: "B", 0x4000: "X", 0x8000: "Y",
}
TRIGGER_ON = 60           # of 255
TRIGGER_OFF = 40          # hysteresis, so a resting trigger cannot chatter
STICK_ON = 16000          # of 32767: the stick has to mean it
STICK_OFF = 9000
REPEAT_FIRST_S = 0.38     # a held direction starts repeating after this
REPEAT_EVERY_S = 0.11
COMBO_HOLD_S = 3.0

DIRECTIONS = ("UP", "DOWN", "LEFT", "RIGHT")


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD),
                ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


class XInput:
    """Just enough of XInput to read four pads. Absent DLL is not fatal: --simulate."""

    def __init__(self) -> None:
        self.dll = None
        self.name = None
        for candidate in XINPUT_DLLS:
            try:
                self.dll = ctypes.WinDLL(candidate)
                self.name = candidate
                break
            except OSError:
                continue

    @property
    def available(self) -> bool:
        return self.dll is not None

    def state(self, index: int) -> XINPUT_GAMEPAD | None:
        """The pad at a zero-based index, or None when nothing is plugged in there."""
        if not self.dll:
            return None
        state = XINPUT_STATE()
        result = self.dll.XInputGetState(wintypes.DWORD(index), ctypes.byref(state))
        if result == ERROR_SUCCESS:
            return state.Gamepad
        return None

    def inventory(self) -> list[dict]:
        rows = []
        for index in range(4):
            pad = self.state(index)
            rows.append({
                "index": index,
                "number": index + 1,
                "connected": pad is not None,
                "buttons": f"0x{pad.wButtons:04X}" if pad is not None else None,
            })
        return rows


# ------------------------------------------------------------- the region preview window

# The title the second copy of the game gives its own window (ADCRuntimeGameMode, the
# -DCPreview block). Matched exactly, so nothing else on the desktop can be moved by this.
PREVIEW_TITLE = "DynamicContents region preview"

# Where that copy writes down what it did with its window. This is the Shipping build's own
# "project saved dir": %LOCALAPPDATA%\DCDemo\Saved, not a folder next to the build - so a
# booth run needs no path on the command line. A test passes -DCPreviewFile= and
# --preview-file to keep its evidence next to itself instead.
DEFAULT_PREVIEW_FILE = (Path(os.environ.get("LOCALAPPDATA") or ".")
                        / "DCDemo" / "Saved" / "dc_preview_window.json")

# Where "hidden" is. Far from any real desktop, so the window keeps running and rendering -
# a minimised Unreal window stops drawing, and the whole point of this window is to be
# already showing the right thing the moment it appears. 30,000 and not more because Windows
# clamps a window position to a signed 16-bit number (32,767). Agrees with
# FDCPreviewWindow::OffScreenX in the plugin.
OFFSCREEN_X = 30000
OFFSCREEN_Y = 30000

# Window-position metrics: the whole desktop, however many monitors it is made of.
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

# Win32 constants, named rather than numbered at the call sites.
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SW_SHOWNOACTIVATE = 4
MONITORINFOF_PRIMARY = 0x1


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD)]


MONITOR_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                       ctypes.POINTER(RECT), wintypes.LPARAM)
ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class PreviewWindow:
    """Shows and hides the second copy of the game (plan v6 §7 and §10, step 6 of §10's
    list: "pad helper (also shows and hides the preview window)").

    The division of labour: the **game** decides where its window belongs - it is the one
    that knows which monitor is which - makes it borderless, parks it off-screen at boot and
    writes a small JSON file saying where "there" is. This class only ever moves it between
    there and off-screen.

    It never activates anything. Every call carries SWP_NOACTIVATE, because the main game
    has to keep focus and pad 1 all day (plan v6 §11) and a window that stole focus when it
    appeared would take the Player's controller with it.
    """

    def __init__(self, state_file: Path | None = None, title: str = PREVIEW_TITLE) -> None:
        self.title = title
        self.state_file = state_file
        self.user32 = None
        if sys.platform == "win32":
            try:
                self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            except OSError:
                self.user32 = None
        self.last_home: tuple[int, int, int, int] | None = None

    # ---- finding it -------------------------------------------------------------------

    def find(self) -> int | None:
        """The window handle, by exact title. Found by title rather than by the handle in
        the JSON file because a title can never be stale: a file left behind by yesterday's
        run names a handle that is gone or, worse, reused."""
        if not self.user32:
            return None
        found: list[int] = []
        buffer = ctypes.create_unicode_buffer(256)

        def visit(hwnd, _lparam):
            self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
            if buffer.value == self.title:
                found.append(int(hwnd))
                return False
            return True

        self.user32.EnumWindows(ENUM_WINDOWS_PROC(visit), 0)
        return found[0] if found else None

    def rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        box = RECT()
        if not self.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box)):
            return None
        return (box.left, box.top, box.right - box.left, box.bottom - box.top)

    def on_screen(self, box: tuple[int, int, int, int] | None) -> bool:
        """Is any of this window on a monitor? That, and not a comparison with the
        off-screen constant, is what "shown" means - Windows clamps a window position to
        32,767, so the number that was asked for is not always the number that comes back."""
        if not box or not self.user32:
            return False
        x, y, w, h = box
        vx = self.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = self.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = self.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = self.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        return x < vx + vw and x + w > vx and y < vy + vh and y + h > vy

    def home(self, hwnd: int | None) -> tuple[int, int, int, int]:
        """Where the window belongs: what the game wrote down, else where it is now if that
        is on-screen, else the right half of the rightmost monitor - the same rule the game
        itself uses, so even with no file at all the window lands where the portal's
        Region-check screen leaves room for it."""
        written = self.read_state_file()
        if written:
            self.last_home = written
            return written
        if hwnd is not None:
            now = self.rect(hwnd)
            if self.on_screen(now):
                return now
        if self.last_home:
            return self.last_home
        return self.monitor_rect()

    def read_state_file(self) -> tuple[int, int, int, int] | None:
        if not self.state_file:
            return None
        try:
            data = json.loads(Path(self.state_file).read_text(encoding="utf-8"))
            box = data["home"]
            return (int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"]))
        except Exception:                                  # noqa: BLE001 - any failure
            return None

    def monitor_rect(self) -> tuple[int, int, int, int]:
        """The right half of the rightmost monitor, vertically centred - 960 x 540 at
        (960, 270) on a 1920 x 1080 right-hand screen. The portal's Region-check step
        reserves exactly this rectangle (portal/style.css `.preview-reserve`)."""
        monitors: list[tuple[int, int, int, int, bool]] = []
        if self.user32:
            def visit(_handle, _hdc, box, _lparam):
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if self.user32.GetMonitorInfoW(_handle, ctypes.byref(info)):
                    r = info.rcMonitor
                    monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top,
                                     bool(info.dwFlags & MONITORINFOF_PRIMARY)))
                return True

            self.user32.EnumDisplayMonitors(None, None, MONITOR_ENUM_PROC(visit), 0)
        if not monitors:
            return (960, 270, 960, 540)
        others = [m for m in monitors if not m[4]] or monitors
        left, top, width, height, _primary = max(others, key=lambda m: m[0])
        w, h = width // 2, height // 2
        return (left + width - w, top + (height - h) // 2, w, h)

    # ---- moving it --------------------------------------------------------------------

    def set_shown(self, shown: bool) -> dict:
        hwnd = self.find()
        if hwnd is None or not self.user32:
            return {"found": False, "shown": None,
                    "detail": "no window called " + self.title}
        if shown:
            x, y, w, h = self.home(hwnd)
            # A window somebody minimised by hand comes back without taking focus.
            if self.user32.IsIconic(wintypes.HWND(hwnd)):
                self.user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
            self.user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST),
                                     x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        else:
            x, y, w, h = self.home(hwnd)          # remembered for the next show
            self.last_home = (x, y, w, h)
            self.user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_NOTOPMOST),
                                     OFFSCREEN_X, OFFSCREEN_Y, 0, 0,
                                     SWP_NOACTIVATE | SWP_NOSIZE)
        return {"found": True, "shown": bool(shown), "rect": self.rect(hwnd)}

    def state(self) -> dict:
        hwnd = self.find()
        if hwnd is None:
            return {"found": False, "shown": None}
        box = self.rect(hwnd)
        return {"found": True, "rect": box,
                "shown": self.on_screen(box),
                "visible": bool(self.user32.IsWindowVisible(wintypes.HWND(hwnd))),
                "minimised": bool(self.user32.IsIconic(wintypes.HWND(hwnd)))}


def foreground_window_title() -> str:
    """Whatever window has focus right now — the main game, all being well (plan v6 §11)."""
    if sys.platform != "win32":
        return ""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except OSError:
        return ""
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(user32.GetForegroundWindow(), buffer, len(buffer))
    return buffer.value


# --------------------------------------------------------------------------- the helper

class PadHelper:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.xinput = XInput()
        self.server = WsServer(args.host, args.port, on_client=self.greet,
                               on_text=self.on_text)
        self.preview = None if args.no_preview_window else PreviewWindow(
            state_file=Path(args.preview_file) if args.preview_file else None,
            title=args.preview_title)
        self.held: set[str] = set()
        self.repeat_at: dict[str, float] = {}
        self.combo_since: dict[str, float] = {}
        self.combo_fired: set[str] = set()
        self.lines: queue.Queue[str] = queue.Queue()
        self.stopping = threading.Event()
        self.controllers: list[dict] = []

    # ---------------------------------------------------------------- reporting

    def report_controllers(self) -> list[dict]:
        if not self.xinput.available:
            self.say("XInput: no XInput DLL on this machine "
                     f"(tried {', '.join(XINPUT_DLLS)})")
            self.controllers = []
            return self.controllers
        self.controllers = self.xinput.inventory()
        self.say(f"XInput: {self.xinput.name}")
        for row in self.controllers:
            state = "connected" if row["connected"] else "not connected"
            extra = f"  buttons {row['buttons']}" if row["connected"] else ""
            mine = "  <- reading this one" if row["number"] == self.args.pad else ""
            self.say(f"  controller {row['number']}: {state}{extra}{mine}")
        if not any(r["connected"] for r in self.controllers):
            self.say("  no controller is plugged in — the portal's keyboard fallback still "
                     "works, and this helper will pick a pad up the moment it appears")
        return self.controllers

    def say(self, line: str) -> None:
        if not self.args.quiet:
            print(line, flush=True)

    # ---------------------------------------------------------------- the wire

    def greet(self, client: "WsClient") -> None:
        client.send(json.dumps({
            "type": "hello", "pad": self.args.pad, "simulate": bool(self.args.simulate),
            "server": self.args.server, "controllers": self.controllers,
            "preview_window": bool(self.preview),
        }))
        if self.preview:
            # A page that reloads mid-visit gets told where the window is, rather than
            # having to guess from whichever step it happens to come back on.
            client.send(json.dumps({"type": "preview", **self.preview.state()}))

    def on_text(self, _client: "WsClient", raw: str) -> None:
        """The one thing the portal sends: show or hide the region preview window."""
        try:
            message = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(message, dict) or message.get("type") != "preview":
            return
        self.set_preview(bool(message.get("show")), "the portal")

    def set_preview(self, shown: bool, why: str) -> dict:
        if not self.preview:
            answer = {"found": False, "shown": None, "detail": "--no-preview-window"}
        else:
            answer = self.preview.set_shown(shown)
        self.say(f"preview window {'show' if shown else 'hide'} ({why}): {answer}")
        self.broadcast({"type": "preview", **answer})
        return answer

    def broadcast(self, message: dict) -> None:
        self.server.broadcast(json.dumps(message))

    def send_button(self, button: str, pressed: bool, repeat: bool = False) -> None:
        # A staff combo is never a press as far as the portal is concerned.
        if {"LB", "RB"} <= self.held and button not in ("LB", "RB"):
            return
        self.broadcast({"type": "button", "button": button, "pressed": pressed,
                        "repeat": repeat, "t": round(time.monotonic(), 3)})
        if pressed and not self.args.quiet:
            self.say(f"  {button}{' (repeat)' if repeat else ''}")

    # ---------------------------------------------------------------- buttons

    def press(self, button: str, now: float) -> None:
        if button in self.held:
            return
        self.held.add(button)
        if button in DIRECTIONS:
            self.repeat_at[button] = now + REPEAT_FIRST_S
        self.send_button(button, True)

    def release(self, button: str) -> None:
        if button not in self.held:
            return
        self.held.discard(button)
        self.repeat_at.pop(button, None)
        self.send_button(button, False)

    def repeats(self, now: float) -> None:
        for button in DIRECTIONS:
            if button in self.held and now >= self.repeat_at.get(button, 1e18):
                self.repeat_at[button] = now + REPEAT_EVERY_S
                self.send_button(button, True, repeat=True)

    # ---------------------------------------------------------------- staff combos

    COMBOS = {
        # reason="staff": a human is clearing the booth down between visitors, so the game
        # drops back to its attract loop as well. The portal's own 60 s idle timer posts
        # the same endpoint with reason="idle" and must not kick a Player who is still
        # playing at the other seat (plan v6 §2 - two seats, possibly two visitors).
        "reset":         ({"LB", "RB", "BACK"}, "/admin/reset", {"reason": "staff"}),
        "close-auction": ({"LB", "RB", "X"}, "/admin/close-auction", {"lot_id": "all"}),
        "corrupt":       ({"LB", "RB", "Y"}, "/admin/sabotage", {"mode": "corrupt"}),
        "freeze":        ({"LB", "RB", "B"}, "/admin/sabotage", {"mode": "freeze"}),
    }

    def combos(self, now: float) -> None:
        for action, (buttons, _path, _body) in self.COMBOS.items():
            if buttons <= self.held:
                started = self.combo_since.setdefault(action, now)
                if action not in self.combo_fired and now - started >= COMBO_HOLD_S:
                    self.combo_fired.add(action)
                    self.fire(action)
            else:
                self.combo_since.pop(action, None)
                self.combo_fired.discard(action)

    def fire(self, action: str) -> None:
        """Run a staff combo: call the admin endpoint, then tell the portal."""
        _buttons, path, body = self.COMBOS[action]
        self.say(f"staff combo: {action} -> POST {path}")
        thread = threading.Thread(target=self._call_admin, args=(action, path, body),
                                  daemon=True)
        thread.start()

    def _call_admin(self, action: str, path: str, body: dict) -> None:
        url = self.args.server.rstrip("/") + path
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                answer = json.loads(response.read().decode("utf-8") or "{}")
            ok, detail = True, answer
        except urllib.error.HTTPError as problem:
            ok, detail = False, {"status": problem.code,
                                 "error": problem.read().decode("utf-8", "replace")[:200]}
        except Exception as problem:                      # noqa: BLE001 - report anything
            ok, detail = False, {"error": str(problem)}
        self.say(f"  {action}: {'ok' if ok else 'FAILED'} {detail}")
        self.broadcast({"type": "staff", "action": action, "ok": ok, "detail": detail})

    # ---------------------------------------------------------------- the real pad

    def poll_pad(self, now: float) -> None:
        pad = self.xinput.state(self.args.pad - 1)
        if pad is None:
            for button in list(self.held):
                self.release(button)
            return
        wanted: set[str] = set()
        for bit, name in BUTTON_BITS.items():
            if pad.wButtons & bit:
                wanted.add(name)
        if pad.bLeftTrigger >= (TRIGGER_OFF if "LT" in self.held else TRIGGER_ON):
            wanted.add("LT")
        if pad.bRightTrigger >= (TRIGGER_OFF if "RT" in self.held else TRIGGER_ON):
            wanted.add("RT")
        # The left stick stands in for the D-pad, with its own hysteresis.
        for name, value, positive in (("RIGHT", pad.sThumbLX, True),
                                      ("LEFT", pad.sThumbLX, False),
                                      ("UP", pad.sThumbLY, True),
                                      ("DOWN", pad.sThumbLY, False)):
            level = value if positive else -value
            if level >= (STICK_OFF if name in self.held else STICK_ON):
                wanted.add(name)

        for button in wanted - self.held:
            self.press(button, now)
        for button in self.held - wanted:
            self.release(button)

    # ---------------------------------------------------------------- the fake pad

    def feed(self, line: str) -> None:
        self.lines.put(line)

    def run_line(self, line: str) -> bool:
        """One line of the simulate language. False means "stop the helper"."""
        text = line.strip().lstrip("﻿")        # a script file may start with a BOM
        if not text or text.startswith("#"):
            return True
        head, _, tail = text.partition(" ")
        head = head.upper()
        tail = tail.strip()
        now = time.monotonic()

        if head in ("QUIT", "EXIT"):
            return False
        if head == "WAIT":
            self.sleep_ticking(max(0.0, float(tail or 0) / 1000.0))
            return True
        if head == "COMBO":
            action = tail.lower()
            if action not in self.COMBOS:
                self.say(f"  unknown combo: {action}")
                return True
            self.fire(action)
            return True
        if head == "PREVIEW":
            # So a scripted test can do by hand exactly what the portal does over the
            # socket: `preview show`, `preview hide`, `preview state`.
            word = tail.lower()
            if word in ("show", "hide"):
                self.set_preview(word == "show", "a script")
            elif word in ("", "state"):
                self.say(f"  preview window: "
                         f"{self.preview.state() if self.preview else 'off'}")
            else:
                self.say(f"  preview takes show / hide / state, not {word!r}")
            return True
        if head.startswith("+"):
            self.press(head[1:], now)
            return True
        if head.startswith("-"):
            self.release(head[1:])
            return True
        if head in BUTTON_BITS.values() or head in ("LT", "RT"):
            self.press(head, now)
            time.sleep(0.06)
            self.release(head)
            return True
        self.say(f"  cannot read this line: {text!r}")
        return True

    def sleep_ticking(self, seconds: float) -> None:
        """A wait that still ages held buttons — so a scripted three-second combo hold
        goes through exactly the code a staff member's thumbs do."""
        until = time.monotonic() + seconds
        while True:
            now = time.monotonic()
            if now >= until:
                return
            self.repeats(now)
            self.combos(now)
            time.sleep(min(0.008, until - now))

    def stdin_thread(self) -> None:
        for line in sys.stdin:
            self.lines.put(line)
        self.lines.put("quit")

    # ---------------------------------------------------------------- the loop

    def run(self) -> int:
        self.report_controllers()
        if not self.args.simulate and not self.xinput.available:
            self.say("no XInput and no --simulate: nothing to read")
            return 2

        self.server.start()
        self.say(f"listening on ws://{self.args.host}:{self.args.port}"
                 f"  (admin calls go to {self.args.server})")
        if self.args.simulate:
            self.say("simulate: this is a fake pad — no controller is being read")
        if self.preview:
            self.say(f"region preview window: {self.preview.state()}"
                     f"  home {self.preview.home(None)}")
        else:
            self.say("region preview window: not managed (--no-preview-window)")

        if self.args.script:
            with open(self.args.script, "r", encoding="utf-8-sig") as handle:
                for line in handle:
                    self.lines.put(line)
            if not self.args.stdin:
                self.lines.put("quit")
        if self.args.stdin:
            threading.Thread(target=self.stdin_thread, daemon=True).start()

        try:
            while not self.stopping.is_set():
                now = time.monotonic()
                if not self.args.simulate:
                    self.poll_pad(now)
                # Repeats and combos run in simulate mode too, so a script that holds
                # +LB +RB +BACK for three seconds goes down exactly the same path a
                # staff member's thumbs do.
                self.repeats(now)
                self.combos(now)
                try:
                    line = self.lines.get(timeout=0.008)
                except queue.Empty:
                    continue
                if not self.run_line(line):
                    break
        except KeyboardInterrupt:
            self.say("stopping")
        finally:
            self.server.stop()
        return 0


# --------------------------------------------------------------------------- WebSocket

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    header = bytearray([0x80 | opcode])
    size = len(payload)
    if size < 126:
        header.append(size)
    elif size < 65536:
        header.append(126)
        header += struct.pack(">H", size)
    else:
        header.append(127)
        header += struct.pack(">Q", size)
    return bytes(header) + payload


class WsClient:
    """One connected browser. Mostly sending; the portal sends one kind of message back."""

    def __init__(self, conn: socket.socket, server: "WsServer") -> None:
        self.conn = conn
        self.server = server
        self.alive = True
        self.lock = threading.Lock()

    def send(self, text: str) -> None:
        if not self.alive:
            return
        try:
            with self.lock:
                self.conn.sendall(ws_frame(text.encode("utf-8")))
        except OSError:
            self.close()

    def close(self) -> None:
        self.alive = False
        try:
            self.conn.close()
        except OSError:
            pass
        self.server.drop(self)

    def read_loop(self) -> None:
        """Pings, a close frame, and the portal's own show/hide of the preview window."""
        try:
            while self.alive:
                head = self.recv_exactly(2)
                if not head:
                    break
                opcode = head[0] & 0x0F
                masked = bool(head[1] & 0x80)
                size = head[1] & 0x7F
                if size == 126:
                    size = struct.unpack(">H", self.recv_exactly(2))[0]
                elif size == 127:
                    size = struct.unpack(">Q", self.recv_exactly(8))[0]
                mask = self.recv_exactly(4) if masked else b""
                payload = self.recv_exactly(size) if size else b""
                if masked and payload:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                if opcode == 0x8:                       # close
                    break
                if opcode == 0x9:                       # ping -> pong
                    with self.lock:
                        self.conn.sendall(ws_frame(payload, opcode=0xA))
                elif opcode == 0x1 and self.server.on_text:   # text
                    self.server.on_text(self, payload.decode("utf-8", "replace"))
        except OSError:
            pass
        finally:
            self.close()

    def recv_exactly(self, size: int) -> bytes:
        out = b""
        while len(out) < size:
            chunk = self.conn.recv(size - len(out))
            if not chunk:
                return b""
            out += chunk
        return out


class WsServer:
    """A WebSocket broadcaster in plain sockets — no dependency to install at the booth."""

    def __init__(self, host: str, port: int, on_client=None, on_text=None) -> None:
        self.host = host
        self.port = port
        self.on_client = on_client
        self.on_text = on_text
        self.clients: list[WsClient] = []
        self.lock = threading.Lock()
        self.sock: socket.socket | None = None
        self.stopping = threading.Event()

    def start(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(8)
        threading.Thread(target=self.accept_loop, daemon=True).start()

    def accept_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handshake, args=(conn,), daemon=True).start()

    def handshake(self, conn: socket.socket) -> None:
        conn.settimeout(10)
        try:
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = conn.recv(4096)
                if not chunk:
                    conn.close()
                    return
                request += chunk
                if len(request) > 64 * 1024:
                    conn.close()
                    return
            headers = {}
            for line in request.split(b"\r\n")[1:]:
                name, _, value = line.partition(b":")
                if value:
                    headers[name.strip().lower().decode()] = value.strip().decode()
            key = headers.get("sec-websocket-key")
            if not key:
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                conn.close()
                return
            accept = base64.b64encode(
                hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode("ascii")
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\n"
                          "Upgrade: websocket\r\n"
                          "Connection: Upgrade\r\n"
                          f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode("ascii"))
            conn.settimeout(None)
        except OSError:
            try:
                conn.close()
            except OSError:
                pass
            return

        client = WsClient(conn, self)
        with self.lock:
            self.clients.append(client)
        if self.on_client:
            self.on_client(client)
        threading.Thread(target=client.read_loop, daemon=True).start()

    def broadcast(self, text: str) -> None:
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            client.send(text)

    def drop(self, client: WsClient) -> None:
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)

    def stop(self) -> None:
        self.stopping.set()
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            client.close()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


# --------------------------------------------------------------------------- cli

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controller 2 -> the brand portal.")
    parser.add_argument("--pad", type=int, default=2,
                        help="which controller to read, 1-4 (default 2: the brand seat)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8701,
                        help="the WebSocket port the portal listens to (default 8701)")
    parser.add_argument("--server", default="http://127.0.0.1:8700",
                        help="the demo server, for the staff combos")
    parser.add_argument("--simulate", action="store_true",
                        help="no XInput: a fake pad driven by --script and/or --stdin")
    parser.add_argument("--script", help="a file of simulate lines to run at startup")
    parser.add_argument("--stdin", action="store_true",
                        help="read simulate lines from standard input, one per line")
    parser.add_argument("--list", action="store_true",
                        help="print which controllers are plugged in and exit")
    parser.add_argument("--quiet", action="store_true")
    # The region preview window (plan v6 §7). The game writes the file; this only reads it.
    parser.add_argument("--preview-file", default=str(DEFAULT_PREVIEW_FILE),
                        help="the JSON the preview copy of the game writes about its window")
    parser.add_argument("--preview-title", default=PREVIEW_TITLE,
                        help="the exact window title to move (default: %(default)s)")
    parser.add_argument("--no-preview-window", action="store_true",
                        help="do not touch any window: the live-flip fallback uses this")
    parser.add_argument("--preview", choices=["show", "hide", "state"],
                        help="do that to the preview window and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    helper = PadHelper(args)
    if args.list:
        helper.report_controllers()
        return 0
    if args.preview:
        # Without starting anything: how a start script or a rehearsal pokes the window.
        window = helper.preview or PreviewWindow()
        answer = (window.state() if args.preview == "state"
                  else window.set_shown(args.preview == "show"))
        print(json.dumps(answer))
        return 0 if answer.get("found") else 1
    return helper.run()


if __name__ == "__main__":
    sys.exit(main())
