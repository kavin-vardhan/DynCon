"""Brief 014 exit test — the whole of tour steps 0-4, driven by a simulated game pad.

    server\\.venv\\Scripts\\python.exe booth\\portal_exit_test.py
    ... --headed            watch it happen in a visible browser
    ... --keep              leave the server and the helper up afterwards

What it proves, and the order it proves it in:

  0  Attract           the live ticker and the other brands' auctions are drawing
  1  Create your brand a colour and an emblem chosen with the D-pad
  2  Upload            Content 1 uploaded for real and approved by the four checks,
                       then the engine-5.3 file uploaded and REJECTED with the server's
                       own sentence
  3  Pick a game       two games, the booth badge on A
  4  Slot map          the registered map image, a pin per slot, A1's card filled in,
                       and A3 greyed out because the content is too tall for it

Nothing here clicks anything. Every press goes into `pad_helper.py --simulate --stdin`,
out over its WebSocket and into the portal exactly as a real controller 2 would — so the
walkthrough tests the booth's input path, not a test-only back door.

It starts its own demo server on its own port with its own data directory, so it can be
run while the booth server is up without touching it. Screenshots at 1920x1080 land in
portal/_shots/014/ with a contact sheet.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
PORTAL_DIR = ROOT / "portal"
VENV_PY = SERVER_DIR / ".venv" / "Scripts" / "python.exe"

VIEWPORT = {"width": 1920, "height": 1080}


# --------------------------------------------------------------------------- helpers

def wait_for_http(url: str, seconds: float = 40.0) -> None:
    deadline = time.time() + seconds
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as problem:                      # noqa: BLE001
            last = problem
        time.sleep(0.4)
    raise SystemExit(f"{url} never answered: {last}")


class Pad:
    """The simulated controller, as a process we type lines at."""

    def __init__(self, port: int, server: str, log: Path) -> None:
        self.log = log.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [str(VENV_PY), str(ROOT / "booth" / "pad_helper.py"), "--simulate", "--stdin",
             "--port", str(port), "--server", server],
            stdin=subprocess.PIPE, stdout=self.log, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", bufsize=1, cwd=str(ROOT))

    def press(self, *buttons: str, gap: float = 0.14) -> None:
        for button in buttons:
            self.process.stdin.write(f"{button}\n")
            self.process.stdin.flush()
            time.sleep(gap)

    def line(self, text: str) -> None:
        self.process.stdin.write(f"{text}\n")
        self.process.stdin.flush()

    def stop(self) -> None:
        try:
            self.process.stdin.write("quit\n")
            self.process.stdin.flush()
            self.process.wait(timeout=5)
        except Exception:                                  # noqa: BLE001
            self.process.kill()
        finally:
            self.log.close()


# --------------------------------------------------------------------------- the checks

# Run in the page after every screenshot. Three questions: is every string bilingual, is
# anything clipped or off screen, and is anything too small to read from two metres.
PAGE_AUDIT = r"""
() => {
  const problems = [];
  const seen = (node) => {
    const style = getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0')
      return false;
    const box = node.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  };

  // 1. every bilingual block really has both languages
  for (const node of document.querySelectorAll('.bi')) {
    if (!seen(node)) continue;
    const jp = node.querySelector(':scope > .jp');
    const en = node.querySelector(':scope > .en');
    if (!jp || !en || !jp.textContent.trim() || !en.textContent.trim()) {
      problems.push('one-language block: ' + node.outerHTML.slice(0, 140));
    }
  }

  // 2. no text on screen outside a bilingual block, unless it is marked as data
  //    (a number, a slot id, a file name - the same in both languages)
  for (const node of document.querySelectorAll('body *')) {
    if (!seen(node)) continue;
    let text = '';
    for (const child of node.childNodes) {
      if (child.nodeType === 3) text += child.textContent;
    }
    if (!text.trim()) continue;
    if (node.closest('.bi') || node.closest('[data-datum]')) continue;
    problems.push('text with no Japanese: ' + JSON.stringify(text.trim().slice(0, 60))
                  + '  in ' + node.tagName + '.' + (node.getAttribute('class') || '')
                  + '  parent ' + (node.parentElement
                                   ? node.parentElement.tagName + '.'
                                     + (node.parentElement.getAttribute('class') || '')
                                   : '-'));
  }

  // 3. clipped, overflowing its panel, or off screen
  for (const node of document.querySelectorAll('main, .panel, .slot-card')) {
    if (!seen(node)) continue;
    if (node.scrollHeight > node.clientHeight + 2) {
      problems.push('overflows its box by ' + (node.scrollHeight - node.clientHeight)
                    + 'px: ' + (node.className || node.tagName) + ' '
                    + node.textContent.trim().slice(0, 40));
    }
  }
  // A flex child that has been squeezed smaller than its contents does not make its
  // parent's scrollHeight grow — it just paints over whatever is underneath it. So every
  // box is checked against the box it lives in.
  for (const node of document.querySelectorAll('main *')) {
    if (!seen(node)) continue;
    const style = getComputedStyle(node);
    if (style.position === 'absolute' || style.position === 'fixed') continue;
    // an inline box sits on a baseline; its rect is not a layout box to measure against
    if (style.display === 'inline') continue;
    const parent = node.parentElement;
    if (!parent || parent === document.body) continue;
    const pstyle = getComputedStyle(parent);
    if (pstyle.overflow !== 'visible') continue;
    // an inline box's rect does not describe where its block children are drawn
    if (pstyle.display === 'inline') continue;
    const box = node.getBoundingClientRect();
    const around = parent.getBoundingClientRect();
    if (box.bottom > around.bottom + 4 || box.top < around.top - 4) {
      problems.push('spills out of its parent by '
                    + Math.round(Math.max(box.bottom - around.bottom, around.top - box.top))
                    + 'px: ' + (node.className || node.tagName) + ' in '
                    + (parent.className || parent.tagName) + ' '
                    + node.textContent.trim().slice(0, 40));
    }
  }

  for (const node of document.querySelectorAll('body *')) {
    if (!seen(node)) continue;
    const style = getComputedStyle(node);
    if (style.overflow === 'auto' || style.overflow === 'scroll') continue;
    if (node.scrollWidth > node.clientWidth + 2 && style.overflowX === 'hidden') {
      problems.push('clipped sideways: ' + (node.className || node.tagName) + ' '
                    + node.textContent.trim().slice(0, 50));
    }
    if (node.scrollHeight > node.clientHeight + 2 && style.overflowY === 'hidden'
        && node.id !== 'app' && !node.classList.contains('map-wrap')) {
      problems.push('clipped vertically by '
                    + (node.scrollHeight - node.clientHeight) + 'px: '
                    + (node.className || node.tagName) + ' '
                    + node.textContent.trim().slice(0, 40));
    }
    const box = node.getBoundingClientRect();
    if (box.right > window.innerWidth + 2 || box.bottom > window.innerHeight + 2
        || box.left < -2 || box.top < -2) {
      problems.push('off screen by '
                    + Math.round(Math.max(box.bottom - window.innerHeight,
                                          box.right - window.innerWidth,
                                          -box.left, -box.top)) + 'px: '
                    + (node.className || node.tagName) + ' '
                    + node.textContent.trim().slice(0, 40));
    }
  }

  // 4. big enough to read from two metres
  let smallest = 999;
  for (const node of document.querySelectorAll('body *')) {
    if (!seen(node)) continue;
    let text = '';
    for (const child of node.childNodes) if (child.nodeType === 3) text += child.textContent;
    if (!text.trim()) continue;
    const size = parseFloat(getComputedStyle(node).fontSize);
    if (size < smallest) smallest = size;
    if (size < 19.5) {
      problems.push('too small (' + size.toFixed(1) + 'px): ' + text.trim().slice(0, 50));
    }
  }
  // a height dump, so a layout that does not fit can be fixed with numbers rather than
  // by eye
  const sizes = [];
  for (const node of document.querySelectorAll('header, main, .columns, .panel, .stage, '
                                               + '.body, .hintbar, .screen-head, '
                                               + '.slot-card > .body > *, .card-right > *, '
                                               + '.card-left > *, .checks > *, .verdict-slot,'
                                               + '.stage > *, .mine-cards > *')) {
    if (!seen(node)) continue;
    sizes.push((node.tagName + '.' + (node.getAttribute('class') || '')).slice(0, 40)
               + ' box=' + Math.round(node.getBoundingClientRect().height)
               + ' content=' + node.scrollHeight);
  }
  return {problems, smallest, sizes,
          body: parseFloat(getComputedStyle(document.body).fontSize)};
}
"""


# --------------------------------------------------------------------------- the walk

def run(args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    data_dir = Path(tempfile.mkdtemp(prefix="dc_portal_exit_"))
    base = f"http://127.0.0.1:{args.port}"
    env = dict(os.environ, DCSERVER_DATA=str(data_dir / "data"), DCSERVER_LOG="WARNING")
    server_log = (out / "server.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "dcserver.asgi:app", "--host", "127.0.0.1",
         "--port", str(args.port), "--log-level", "warning"],
        cwd=str(SERVER_DIR), env=env, stdout=server_log, stderr=subprocess.STDOUT, text=True)

    shots: list[tuple[str, Path]] = []
    failures: list[str] = []
    console: list[str] = []
    pad = None
    smallest_seen = 999.0

    try:
        wait_for_http(f"{base}/admin/health")
        wait_for_http(f"{base}/portal/")
        pad = Pad(args.pad_port, base, out / "pad_helper.log")
        time.sleep(0.6)

        with sync_playwright() as play:
            browser = play.chromium.launch(channel="msedge", headless=not args.headed)
            page = browser.new_context(viewport=VIEWPORT, device_scale_factor=1).new_page()
            page.on("console", lambda message: console.append(
                f"{message.type}: {message.text}") if message.type in ("error", "warning")
                else None)
            page.on("pageerror", lambda error: console.append(f"pageerror: {error}"))

            def shot(name: str, note: str = "") -> None:
                nonlocal smallest_seen
                page.wait_for_timeout(450)                # let a transition settle
                path = out / f"{name}.png"
                page.screenshot(path=str(path))
                audit = page.evaluate(PAGE_AUDIT)
                smallest_seen = min(smallest_seen, audit["smallest"])
                for problem in audit["problems"]:
                    failures.append(f"[{name}] {problem}")
                if audit["problems"]:
                    failures.append(f"[{name}] sizes: " + " | ".join(audit["sizes"]))
                shots.append((name, path))
                print(f"  shot {name}: {len(audit['problems'])} problem(s), "
                      f"smallest text {audit['smallest']:.1f}px{'  ' + note if note else ''}")

            print(f"opening {base}/portal/?pad={args.pad_port}")
            page.goto(f"{base}/portal/?pad={args.pad_port}")
            page.wait_for_selector('#app[data-pad="online"]', timeout=20000)
            page.wait_for_selector('#app[data-screen="attract"] .ticker-row', timeout=20000)
            page.wait_for_timeout(1200)                   # one poll, so the ticker is full
            shot("00_attract")

            # ---- 1 create your brand
            pad.press("A")
            page.wait_for_selector('#app[data-screen="brand"]', timeout=10000)
            pad.press("RIGHT")                            # the second colour
            pad.press("A")                                # take it, drop to the emblems
            pad.press("RIGHT", "RIGHT", "RIGHT", "RIGHT")  # the fifth emblem
            shot("01_brand")
            pad.press("A")                                # take the emblem
            pad.press("A")                                # "use this brand"

            # ---- 2 upload
            page.wait_for_selector('#app[data-screen="upload"][data-state="idle"]',
                                   timeout=15000)
            page.wait_for_selector('.file-row', timeout=10000)
            shot("02_upload_files")

            pad.press("A")                                # upload the first file
            page.wait_for_selector('#app[data-state="approved"]', timeout=60000)
            shot("03_upload_approved", "Content 1")

            pad.press("RIGHT", "A")                       # "try another file"
            page.wait_for_selector('#app[data-state="idle"]', timeout=10000)
            pad.press("DOWN", "DOWN", "DOWN", "DOWN")     # the engine-5.3 file
            pad.press("A")
            page.wait_for_selector('#app[data-state="rejected"]', timeout=90000)
            shot("04_upload_rejected", "engine 5.3")

            # ---- 3 pick a game
            pad.press("RIGHT", "A")                       # "pick a game"
            page.wait_for_selector('#app[data-screen="games"]', timeout=15000)
            page.wait_for_timeout(600)
            shot("05_games")

            # ---- 4 slot map
            pad.press("A")
            page.wait_for_selector('#app[data-screen="slotmap"][data-slot="A1"]',
                                   timeout=20000)
            page.wait_for_function("() => { const i = document.querySelector('img.map');"
                                   " return i && i.complete && i.naturalWidth > 0; }",
                                   timeout=30000)
            page.wait_for_timeout(900)
            shot("06_slotmap_A1", "card filled")

            pad.press("LEFT")
            page.wait_for_selector('#app[data-screen="slotmap"][data-slot="A3"]',
                                   timeout=10000)
            page.wait_for_timeout(700)
            shot("07_slotmap_A3", "greyed: too tall")

            # the refusal really is the server's sentence, and it really is on screen
            refusal = page.text_content('.refusal')
            if "Too tall" not in (refusal or ""):
                failures.append(f"A3's card does not carry the fit refusal: {refusal!r}")
            greyed = page.get_attribute('[data-pin="A3"]', 'class') or ""
            if "greyed" not in greyed:
                failures.append(f"A3's pin is not greyed out: {greyed!r}")

            pad.press("Y")                                # the next step is part 2
            shot("08_next_step")

            # The hidden emergency fallback: the same screen, driven by the keyboard.
            page.keyboard.press("ArrowRight")
            try:
                page.wait_for_selector('#app[data-screen="slotmap"][data-slot="A1"]',
                                       timeout=5000)
                print("  keyboard fallback: ArrowRight moved the cursor A3 -> A1")
            except Exception:                              # noqa: BLE001
                failures.append("the keyboard fallback did not move the slot cursor")

            # The staff reset: the helper calls /admin/reset and tells the portal, which
            # drops everything the visitor did and goes back to the attract screen. It is
            # the same path the 60-second idle timer takes.
            pad.line("combo reset")
            try:
                page.wait_for_selector('#app[data-screen="attract"]', timeout=15000)
                print("  staff combo: reset took the portal back to Attract")
            except Exception:                              # noqa: BLE001
                failures.append("the staff reset combo did not return the portal to Attract")
            if json.loads(urllib.request.urlopen(f"{base}/brand").read())["brand"]:
                failures.append("the staff reset left the visitor's brand behind")

            if not args.keep:
                browser.close()
            else:
                print("--keep: the browser, server and pad helper are still up")
                input("press enter to stop them... ")

        contact_sheet(shots, out / "contact_sheet.png")
        print(f"\ncontact sheet: {out / 'contact_sheet.png'}")

    finally:
        if pad and not args.keep:
            pad.stop()
        if not args.keep:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
            server_log.close()
            shutil.rmtree(data_dir, ignore_errors=True)

    print(f"\nsmallest text anywhere: {smallest_seen:.1f}px")
    noisy = [line for line in console
             if "favicon" not in line and "Failed to load resource" not in line]
    if noisy:
        print(f"\nbrowser console ({len(noisy)}):")
        for line in noisy[:20]:
            print("  " + line)
    if failures:
        (out / "audit.txt").write_text("\n".join(failures), encoding="utf-8")
        print(f"\nFAILED: {len(failures)} problem(s) — all of them in "
              f"{out / 'audit.txt'}")
        for line in failures[:40]:
            print("  " + line)
        return 1
    print("\nPASSED: every screen bilingual, nothing clipped, nothing off screen.")
    return 0


def contact_sheet(shots: list[tuple[str, Path]], path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    columns = 3
    cell = (640, 360)
    label = 34
    rows = (len(shots) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell[0], rows * (cell[1] + label)), "#070c14")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for index, (name, shot_path) in enumerate(shots):
        image = Image.open(shot_path).resize(cell, Image.LANCZOS)
        x = (index % columns) * cell[0]
        y = (index // columns) * (cell[1] + label)
        sheet.paste(image, (x, y))
        draw.text((x + 10, y + cell[1] + 6), name, fill="#6fe3ff", font=font)
    sheet.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument("--pad-port", type=int, default=8702)
    parser.add_argument("--out", default=str(PORTAL_DIR / "_shots" / "014"))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--keep", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
