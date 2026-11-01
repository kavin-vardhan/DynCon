"""The booth's pad helper: controller 2 -> the brand portal, and the staff combos.

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
and one helper can also do the two things a web page must never be allowed to do: talk to
the admin endpoints, and tell a staff combo apart from a visitor mashing buttons.

What it sends (one JSON object per WebSocket text frame):

    {"type": "hello",  "pad": 2, "simulate": false, "controllers": [...]}
    {"type": "button", "button": "A", "pressed": true, "repeat": false, "t": 1234.5}
    {"type": "staff",  "action": "reset", "ok": true, "detail": "..."}

Staff combos (hold all three for 3 seconds, specs/portal_spec_v1.md §2):

    LB + RB + Back  ->  POST /admin/reset
    LB + RB + X     ->  POST /admin/close-auction {"lot_id": "all"}
    LB + RB + Y     ->  POST /admin/sabotage {"mode": "corrupt"}
    LB + RB + B     ->  POST /admin/sabotage {"mode": "freeze"}

While LB and RB are both held, nothing else is relayed to the portal: a combo can never
leak into the screen as a stray press.

No third-party packages: XInput is reached with ctypes and the WebSocket server is about a
hundred lines of socket code at the bottom of this file. That matters because this has to
run on the booth PC from a clean checkout.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import queue
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes

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


# --------------------------------------------------------------------------- the helper

class PadHelper:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.xinput = XInput()
        self.server = WsServer(args.host, args.port, on_client=self.greet)
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
        }))

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
        "reset":         ({"LB", "RB", "BACK"}, "/admin/reset", {}),
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
    """One connected browser. Sending is all this needs to be good at."""

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
        """Browsers send pings and a close frame; nothing else is expected."""
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

    def __init__(self, host: str, port: int, on_client=None) -> None:
        self.host = host
        self.port = port
        self.on_client = on_client
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    helper = PadHelper(args)
    if args.list:
        helper.report_controllers()
        return 0
    return helper.run()


if __name__ == "__main__":
    sys.exit(main())
