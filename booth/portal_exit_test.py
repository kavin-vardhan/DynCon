"""The brand portal's exit test — the whole tour, driven by a simulated game pad.

    server\\.venv\\Scripts\\python.exe booth\\portal_exit_test.py
    ... --headed            watch it happen in a visible browser
    ... --keep              leave the server, the game and the helper up afterwards
    ... --only full         just the long tour (or: express, idle)

What it proves, in the order the booth proves it (plan v6 §4, §14 step 4):

  tour 1, the full visit
    0  Attract            the live ticker and the other brands' auctions are drawing
    1  Create your brand  a colour and an emblem chosen with the D-pad
    2  Upload             Content 1 approved by the four checks; the engine-5.3 file
                          REJECTED with the server's own sentence
    3  Pick a game        two games, the booth badge on A
    4  Slot map           A1's card filled in, A3 greyed out (too tall for it)
    5  Regions and bid    Japan and India ticked, bids stepped with the shoulders
    6  Auction            the rival counter-bids → the "Outbid" banner and the cursor
                          jumps → raise Japan → staff close → Won in Japan, Lost in India
    7  Live               resolve → download → verify → mount, the last step driven by
                          the real mount telemetry of a game client on the same server
    8  Region check       the Start menu's region control
    9  Report             views split simulated/counted, visits, dwell, charged
    10 Push an update     version 2 uploaded, the platform serving it, the game swapping
    11 Summary            and the automatic reset back to Attract

  tour 2, the express visit (the 90-second version for a crowd): brand preset, one slot,
  Japan only, staff closes the auction early.

  then the idle reset, with `?idle=5` so it takes five seconds instead of sixty.

Nothing is clicked. Every press goes into `pad_helper.py --simulate --stdin`, out over its
WebSocket and into the portal exactly as controller 2 would — so the walkthrough tests the
booth's input path, not a test-only back door. The game side is `tools/fake_client.py`
against the same server: a real resolve, a real signed download, a real hash check and
real telemetry, which is what makes the Live strip and the Report honest.
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


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read())


class Pad:
    """The simulated controller, as a process we type lines at."""

    def __init__(self, port: int, server: str, log: Path,
                 extra: list[str] | None = None) -> None:
        self.log = log.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [str(VENV_PY), str(ROOT / "booth" / "pad_helper.py"), "--simulate", "--stdin",
             "--port", str(port), "--server", server, *(extra or [])],
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

# Run in the page after every screenshot. Four questions: is every string bilingual, is
# anything clipped, does anything spill out of the box it lives in, and is anything too
# small to read from two metres.
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
                  + '  in ' + node.tagName + '.' + (node.getAttribute('class') || ''));
  }

  // 3. a box taller than its own panel
  for (const node of document.querySelectorAll('main, .panel, .slot-card, .menu')) {
    if (!seen(node)) continue;
    if (node.scrollHeight > node.clientHeight + 2) {
      problems.push('overflows its box by ' + (node.scrollHeight - node.clientHeight)
                    + 'px: ' + (node.className || node.tagName) + ' '
                    + node.textContent.trim().slice(0, 40));
    }
  }

  // 4. a flex child squeezed smaller than its contents does not make its parent's
  //    scrollHeight grow - it just paints over whatever is underneath it. So every box
  //    is checked against the box it lives in.
  for (const node of document.querySelectorAll('main *, .menu *')) {
    if (!seen(node)) continue;
    const style = getComputedStyle(node);
    if (style.position === 'absolute' || style.position === 'fixed') continue;
    if (style.display === 'inline') continue;
    const parent = node.parentElement;
    if (!parent || parent === document.body) continue;
    const pstyle = getComputedStyle(parent);
    if (pstyle.overflow !== 'visible') continue;
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

  // 5. clipped or off screen
  for (const node of document.querySelectorAll('body *')) {
    if (!seen(node)) continue;
    const style = getComputedStyle(node);
    if (style.overflow === 'auto' || style.overflow === 'scroll') continue;
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

  // 6. big enough to read from two metres
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

  const sizes = [];
  for (const node of document.querySelectorAll('header, main, .columns, .panel, .stage, '
                                               + '.body, .hintbar, .screen-head, .menu, '
                                               + '.slot-card > .body > *, .card-right > *, '
                                               + '.card-left > *, .checks > *, .steps > *, '
                                               + '.stage > *, .bid-rows > *, .rep-rows > *,'
                                               + '.panel.col > *, .steps > *')) {
    if (!seen(node)) continue;
    sizes.push((node.tagName + '.' + (node.getAttribute('class') || '')).slice(0, 40)
               + ' box=' + Math.round(node.getBoundingClientRect().height)
               + ' content=' + node.scrollHeight);
  }
  return {problems, smallest, sizes,
          body: parseFloat(getComputedStyle(document.body).fontSize)};
}
"""


class Run:
    """Everything one walkthrough needs: the page, the pad, and where shots go."""

    def __init__(self, page, pad: Pad, out: Path, base: str) -> None:
        self.page = page
        self.pad = pad
        self.out = out
        self.base = base
        self.shots: list[tuple[str, Path]] = []
        self.failures: list[str] = []
        self.smallest = 999.0

    def shot(self, name: str, note: str = "") -> None:
        self.page.wait_for_timeout(450)
        path = self.out / f"{name}.png"
        self.page.screenshot(path=str(path))
        audit = self.page.evaluate(PAGE_AUDIT)
        self.smallest = min(self.smallest, audit["smallest"])
        for problem in audit["problems"]:
            self.failures.append(f"[{name}] {problem}")
        if audit["problems"]:
            self.failures.append(f"[{name}] sizes: " + " | ".join(audit["sizes"]))
        self.shots.append((name, path))
        print(f"  shot {name}: {len(audit['problems'])} problem(s), "
              f"smallest text {audit['smallest']:.1f}px{'  ' + note if note else ''}")

    def expect(self, selector: str, timeout: int = 15000, what: str = "") -> bool:
        try:
            self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:                                  # noqa: BLE001
            self.failures.append(f"never saw {what or selector}")
            print(f"  MISSING {what or selector}")
            return False

    def focus_on(self, region: str, tries: int = 4) -> bool:
        """Move the cursor onto a region's row (the rival's counter-bid moves it)."""
        for _ in range(tries):
            if self.page.get_attribute("#app", "data-focus") == region:
                return True
            self.pad.press("UP")
            self.page.wait_for_timeout(120)
        ok = self.page.get_attribute("#app", "data-focus") == region
        if not ok:
            self.failures.append(f"could not put the cursor on {region}")
        return ok


# --------------------------------------------------------------------------- the tours

def tour_full(run: Run) -> None:
    page, pad = run.page, run.pad

    run.expect('#app[data-screen="attract"] .ticker-row', 20000, "the attract ticker")
    page.wait_for_timeout(1200)
    run.shot("00_attract")

    # ---- 1 create your brand
    pad.press("A")
    run.expect('#app[data-screen="brand"]', 10000, "the brand screen")
    pad.press("RIGHT")                            # the second colour
    pad.press("A")                                # take it, drop to the emblems
    pad.press("RIGHT", "RIGHT", "RIGHT", "RIGHT")  # the fifth emblem
    run.shot("01_brand")
    pad.press("A")                                # take the emblem
    pad.press("A")                                # "use this brand"

    # ---- 2 upload
    run.expect('#app[data-screen="upload"][data-state="idle"]', 15000, "the upload screen")
    run.expect('.file-row', 10000, "the file list")
    run.shot("02_upload_files")

    pad.press("A")                                # upload the first file
    run.expect('#app[data-state="approved"]', 60000, "the approval")
    run.shot("03_upload_approved", "Content 1")

    pad.press("RIGHT", "A")                       # "try another file"
    run.expect('#app[data-state="idle"]', 10000)
    pad.press("DOWN", "DOWN", "DOWN", "DOWN")     # the engine-5.3 file
    pad.press("A")
    run.expect('#app[data-state="rejected"]', 90000, "the rejection")
    run.shot("04_upload_rejected", "engine 5.3")

    # ---- 3 pick a game
    pad.press("RIGHT", "A")                       # "pick a game"
    run.expect('#app[data-screen="games"]', 15000, "the games screen")
    page.wait_for_timeout(600)
    run.shot("05_games")

    # ---- 4 slot map
    pad.press("A")
    run.expect('#app[data-screen="slotmap"][data-slot="A1"]', 20000, "the slot map")
    page.wait_for_function("() => { const i = document.querySelector('img.map');"
                           " return i && i.complete && i.naturalWidth > 0; }", timeout=30000)
    page.wait_for_timeout(900)
    run.shot("06_slotmap_A1", "card filled")

    pad.press("LEFT")
    run.expect('#app[data-screen="slotmap"][data-slot="A3"]', 10000, "A3")
    page.wait_for_timeout(700)
    run.shot("07_slotmap_A3", "greyed: too tall")
    refusal = page.text_content('.refusal')
    if "Too tall" not in (refusal or ""):
        run.failures.append(f"A3's card does not carry the fit refusal: {refusal!r}")
    if "greyed" not in (page.get_attribute('[data-pin="A3"]', 'class') or ""):
        run.failures.append("A3's pin is not greyed out")

    # ---- 5 regions and bid
    pad.press("RIGHT")                            # back to A1, which the content fits
    run.expect('#app[data-screen="slotmap"][data-slot="A1"]', 10000)
    pad.press("Y")
    run.expect('#app[data-screen="regions"]', 15000, "the regions screen")
    page.wait_for_timeout(600)
    run.shot("08_regions")

    pad.press("DOWN")                             # India
    pad.press("A")                                # tick it
    pad.press("RB", "RB")                         # +50 on India, with the shoulder
    page.wait_for_timeout(400)
    run.shot("09_regions_ticked", "Japan + India")

    # ---- 6 the auction
    pad.press("Y")                                # place the bid
    run.expect('#app[data-screen="auction"]', 15000, "the auction screen")
    page.wait_for_timeout(900)
    run.shot("10_auction_leading")

    # the rival answers once, three seconds after the first bid - no portal timer involved
    run.expect('.banner:not(.hidden)', 25000, "the outbid banner")
    run.shot("11_auction_outbid", "the rival counter-bid")

    run.focus_on("r1")                            # raise Japan, leave India to the rival
    pad.press("Y")
    page.wait_for_timeout(900)
    run.shot("12_auction_raised", "Japan raised")

    pad.line("combo close-auction")               # the staff combo, held for 3 s
    run.expect('#app[data-screen="auction"][data-state="settled"]', 20000, "the result")
    page.wait_for_timeout(500)
    run.shot("13_auction_result", "won Japan, lost India")
    if page.locator('.result-card.won').count() != 1:
        run.failures.append("expected exactly one won region")
    if page.locator('.result-card.lost').count() != 1:
        run.failures.append("expected exactly one lost region")

    # ---- 7 live
    pad.press("A")
    run.expect('#app[data-screen="live"]', 15000, "the live screen")
    run.expect('#app[data-state="resolved"]', 20000, "the resolve step")
    run.shot("14_live_resolved", "waiting for the game")
    run.expect('#app[data-state="mounted"]', 90000, "the game's mount")
    run.shot("15_live_mounted", "the game reported the mount")

    # ---- 9 report (8, the region check, is the Start menu below)
    pad.press("A")
    run.expect('#app[data-screen="report"]', 15000, "the report")
    page.wait_for_timeout(900)
    run.shot("16_report")

    # ---- 8 region check, from the Start menu
    pad.press("START")
    run.expect('#app[data-menu="open"]', 10000, "the menu")
    page.wait_for_timeout(500)
    run.shot("17_region_check", "the Start menu")
    pad.press("A")                                # apply the shown region
    page.wait_for_timeout(500)
    preview = get_json(f"{run.base}/preview/region")
    print(f"  preview window region: {preview['region']} ({preview['label']})")
    pad.press("START")                            # close the menu

    # ---- 10 push an update
    pad.press("Y")
    run.expect('#app[data-screen="update"][data-state="idle"]', 15000, "the update screen")
    page.wait_for_timeout(500)
    run.shot("18_update_files")
    pad.press("A")
    run.expect('#app[data-state="pushed"]', 90000, "version 2 accepted")
    run.shot("19_update_pushed", "will swap when they walk out")
    run.expect('#app[data-state="swapped"]', 120000, "the game's swap")
    run.shot("20_update_swapped", "the game swapped it")

    # ---- 11 summary, then the automatic reset
    pad.press("A")                                # back to the report
    run.expect('#app[data-screen="report"]', 15000)
    pad.press("START")
    run.expect('#app[data-menu="open"]', 10000)
    # Walk down to the summary row by name rather than by counting presses: the menu grew
    # a row in brief 017 (the live flip) and a hard-coded two DOWNs then landed on pause.
    for _ in range(6):
        if page.locator('.menu .button.focused[data-item="menu_summary"]').count():
            break
        pad.press("DOWN")
        page.wait_for_timeout(150)
    else:
        run.failures.append("could not put the cursor on the menu's summary row")
    pad.press("A")
    run.expect('#app[data-screen="summary"]', 15000, "the summary")
    page.wait_for_timeout(700)
    run.shot("21_summary")

    print("  waiting for the summary's automatic reset (20 s)")
    run.expect('#app[data-screen="attract"]', 35000, "the automatic reset")
    page.wait_for_timeout(1200)
    run.shot("22_reset_to_attract")
    if get_json(f"{run.base}/brand")["brand"]:
        run.failures.append("the automatic reset left the visitor's brand behind")


def tour_express(run: Run) -> None:
    """The 90-second version for a crowd: preset brand, one slot, Japan, staff close."""
    page, pad = run.page, run.pad

    run.expect('#app[data-screen="attract"]', 20000, "attract before the express run")
    pad.press("A")
    run.expect('#app[data-screen="brand"]', 10000)
    pad.press("A", "A", "A")                      # first colour, first emblem, go
    run.expect('#app[data-screen="upload"][data-state="idle"]', 15000)
    pad.press("A")                                # Content 1
    run.expect('#app[data-state="approved"]', 60000, "the express approval")
    pad.press("A")                                # "pick a game"
    run.expect('#app[data-screen="games"]', 15000)
    pad.press("A")                                # Game A
    run.expect('#app[data-screen="slotmap"][data-slot="A1"]', 20000)
    pad.press("Y")
    run.expect('#app[data-screen="regions"]', 15000)
    page.wait_for_timeout(500)
    run.shot("23_express_japan_only", "Japan ticked, India and Europe not")
    pad.press("Y")                                # bid Japan only
    run.expect('#app[data-screen="auction"]', 15000)
    pad.line("combo close-auction")               # staff close it early
    run.expect('#app[data-screen="auction"][data-state="settled"]', 20000,
               "the express result")
    run.shot("24_express_won")
    pad.press("A")
    run.expect('#app[data-screen="live"]', 15000)
    run.expect('#app[data-state="resolved"]', 20000)
    page.wait_for_timeout(600)
    run.shot("25_express_live")


def tour_idle(run: Run, pad_port: int) -> None:
    """The idle reset, with the ?idle=5 override so it takes five seconds."""
    page, pad = run.page, run.pad
    page.goto(f"{run.base}/portal/?pad={pad_port}&idle=5")
    run.expect('#app[data-pad="online"]', 20000, "the pad after the reload")
    run.expect('#app[data-screen="attract"]', 15000)
    pad.press("A")
    run.expect('#app[data-screen="brand"]', 10000, "the brand screen before going idle")
    print("  nobody touches the pad for 5 seconds...")
    page.wait_for_timeout(8000)
    if run.expect('#app[data-screen="attract"]', 10000, "the idle reset"):
        print("  idle reset: back at Attract with nothing of the visitor's left")
    run.shot("26_idle_reset")


# --------------------------------------------------------------------------- the runner

def run_all(args: argparse.Namespace) -> int:
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

    pad = None
    game = None
    game_log = None
    console: list[str] = []
    failures: list[str] = []
    smallest = 999.0
    groups: list[tuple[str, list[tuple[str, Path]]]] = []

    try:
        wait_for_http(f"{base}/admin/health")
        wait_for_http(f"{base}/portal/")
        # No preview window in this test: it is the portal's own tour, and brief 017's
        # `preview_exit_test.py` is the one that has a second copy of the game to move.
        pad = Pad(args.pad_port, base, out / "pad_helper.log",
                  extra=["--no-preview-window"])

        # The game side: a real client on the same server, so the Live strip's last step
        # and the Report's counted half are real events, not a story the portal tells.
        game_log = (out / "fake_client.log").open("w", encoding="utf-8")
        game = subprocess.Popen(
            [str(VENV_PY), str(SERVER_DIR / "tools" / "fake_client.py"), "--url", base,
             "--game", "A", "--region", "r1", "--seconds", str(args.game_seconds),
             "--cache", str(data_dir / "client_cache"), "--verbose"],
            cwd=str(SERVER_DIR), stdout=game_log, stderr=subprocess.STDOUT, text=True)
        time.sleep(0.8)

        with sync_playwright() as play:
            browser = play.chromium.launch(channel="msedge", headless=not args.headed)
            page = browser.new_context(viewport=VIEWPORT, device_scale_factor=1).new_page()
            page.on("console", lambda message: console.append(
                f"{message.type}: {message.text}") if message.type in ("error", "warning")
                else None)
            page.on("pageerror", lambda error: console.append(f"pageerror: {error}"))

            url = f"{base}/portal/?pad={args.pad_port}&idle=600"
            print(f"opening {url}")
            page.goto(url)
            page.wait_for_selector('#app[data-pad="online"]', timeout=20000)

            if args.only in ("all", "full"):
                print("tour 1 — the full visit")
                run = Run(page, pad, out, base)
                tour_full(run)
                failures += run.failures
                smallest = min(smallest, run.smallest)
                groups.append(("contact_sheet", run.shots))

            if args.only in ("all", "express"):
                print("tour 2 — the express visit")
                if args.only == "express":
                    page.goto(url)
                    page.wait_for_selector('#app[data-pad="online"]', timeout=20000)
                run = Run(page, pad, out, base)
                tour_express(run)
                failures += run.failures
                smallest = min(smallest, run.smallest)
                groups.append(("contact_sheet_express", run.shots))

            if args.only in ("all", "idle"):
                print("the idle reset")
                run = Run(page, pad, out, base)
                tour_idle(run, args.pad_port)
                failures += run.failures
                smallest = min(smallest, run.smallest)
                groups[-1] = (groups[-1][0], groups[-1][1] + run.shots) if groups else \
                    ("contact_sheet", run.shots)

            if args.keep:
                print("--keep: the browser, server, game and pad helper are still up")
                input("press enter to stop them... ")
            else:
                browser.close()

        for name, shots in groups:
            if shots:
                contact_sheet(shots, out / f"{name}.png")
                print(f"contact sheet: {out / name}.png")

    finally:
        if pad and not args.keep:
            pad.stop()
        if game and not args.keep:
            game.terminate()
            try:
                game.wait(timeout=10)
            except subprocess.TimeoutExpired:
                game.kill()
        if game_log:
            game_log.close()
        if not args.keep:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
            server_log.close()
            shutil.rmtree(data_dir, ignore_errors=True)

    print(f"\nsmallest text anywhere: {smallest:.1f}px")
    noisy = [line for line in console
             if "favicon" not in line and "Failed to load resource" not in line]
    if noisy:
        print(f"\nbrowser console ({len(noisy)}):")
        for line in noisy[:20]:
            print("  " + line)
    if failures:
        (out / "audit.txt").write_text("\n".join(failures), encoding="utf-8")
        print(f"\nFAILED: {len(failures)} problem(s) — all of them in {out / 'audit.txt'}")
        for line in failures[:40]:
            print("  " + line)
        return 1
    print("\nPASSED: the whole tour, every screen bilingual, nothing clipped or off screen.")
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
    parser.add_argument("--out", default=str(PORTAL_DIR / "_shots" / "015"))
    parser.add_argument("--only", default="all", choices=["all", "full", "express", "idle"])
    parser.add_argument("--game-seconds", type=float, default=600.0,
                        help="how long the game client keeps polling")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--keep", action="store_true")
    return run_all(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
