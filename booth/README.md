# The booth's plumbing

*The bits that sit between the hardware on the table and the two screens. **DONE**: the pad
helper (brief 014), the portal's exit test — the whole tour (brief 015) — and the region
preview window's show/hide and its exit test (brief 017). **FUTURE**: the one-button start
script and the watchdog that restarts things (plan v6 §10).*

| File | What |
|---|---|
| `pad_helper.py` | reads **controller 2** and relays it to the brand portal; runs the staff combos; shows and hides the region preview window |
| `portal_exit_test.py` | the whole visitor tour, the express version and the idle reset, driven by a simulated pad |
| `preview_exit_test.py` | brief 017's exit test: win A1 for Japan, open the region check, watch the second copy of the game appear and flip region, run the live-flip fallback, and check the main game never loses focus |

## The pad helper

```powershell
py -3 booth\pad_helper.py                      # the booth setup: controller 2, port 8701
py -3 booth\pad_helper.py --list               # which controllers are plugged in, then exit
py -3 booth\pad_helper.py --pad 1              # read controller 1 instead
py -3 booth\pad_helper.py --simulate --stdin   # a fake pad driven by typed lines
```

**Why it exists.** The portal is a web page in a kiosk browser. A browser only gets game-pad
input while its window has focus, and at a booth the focus is wherever staff last clicked. So
the pad is read *outside* the browser, here, with XInput — which is a background API, no window
and no focus needed — and every press is relayed over a WebSocket on `127.0.0.1:8701` that the
page listens to. One helper also does the two things a web page must never be allowed to do:
call the admin endpoints, and tell a staff combo apart from a visitor mashing buttons.

No third-party packages: XInput is reached with `ctypes` and the WebSocket server is about a
hundred lines of socket code at the bottom of the file. It runs from a clean checkout on the
booth PC with nothing installed.

**What it sends** (one JSON object per text frame):

```json
{"type": "hello",   "pad": 2, "simulate": false, "controllers": [ … ]}
{"type": "button",  "button": "A", "pressed": true, "repeat": false, "t": 1234.5}
{"type": "staff",   "action": "reset", "ok": true, "detail": { … }}
{"type": "preview", "found": true, "shown": true, "rect": [960, 270, 960, 540]}
```

**What it listens for** — the portal is the only thing that sends it anything:

```json
{"type": "preview", "show": true}
```

Buttons are `UP DOWN LEFT RIGHT A B X Y LB RB LT RT START BACK` (the left stick stands in for
the D-pad, with its own dead zone; the triggers have hysteresis so a resting finger cannot
chatter). A held direction repeats after 380 ms, then every 110 ms.

**Staff combos** — hold all three for 3 seconds (`specs/portal_spec_v1.md` §2):

| Combo | What it calls |
|---|---|
| LB + RB + Back | `POST /admin/reset` |
| LB + RB + X | `POST /admin/close-auction {"lot_id": "all"}` |
| LB + RB + Y | `POST /admin/sabotage {"mode": "corrupt"}` |
| LB + RB + B | `POST /admin/sabotage {"mode": "freeze"}` |

While LB and RB are both held, nothing else is relayed to the portal, so a combo can never leak
into the screen as a stray press. The portal shows a small toast when a combo fires, and goes
back to the attract screen on a reset.

**`--simulate`** is a fake pad: no XInput, the same event path. Lines come from `--script FILE`,
from `--stdin`, or both:

```
A              press and release A
+LB  -LB       press / release, for holds
wait 3300      milliseconds (held buttons still age, so combos really fire)
combo reset    run a staff combo straight away
preview show   show / hide / state the region preview window
# a comment
quit
```

## The region preview window

```powershell
py -3 booth\pad_helper.py --preview state      # is it there, and where?
py -3 booth\pad_helper.py --preview show       # ... without starting the helper
py -3 booth\pad_helper.py --no-preview-window  # never touch any window (the live-flip fallback)
```

The second copy of the game (`unreal\Tools\run_preview.ps1`) is a borderless window on the
portal's monitor. **The portal decides when it is seen and the helper moves it**, because a
web page cannot move another program's window: the portal sends `{"type":"preview","show":…}`
over this same WebSocket when the Start menu's Region-check step opens and closes.

The division of labour with the game is worth knowing:

* the **game** owns where the window belongs — it is the one that can see which monitor is
  which — makes it borderless, parks it off-screen at boot, and writes a small JSON file
  (`-DCPreviewFile=`, by default `%LOCALAPPDATA%\DCDemo\Saved\dc_preview_window.json`) saying
  where "there" is;
* the **helper** finds that window by its exact title, `DynamicContents region preview`, and
  only ever moves it between that rectangle and off-screen.

Three details that are not arbitrary:

* **hidden is off-screen, not minimised.** A minimised Unreal window stops drawing, and the
  point of this window is to be already showing the right thing the moment it appears. The
  off-screen position is 30,000 — Windows clamps a window position to 32,767, so a rounder
  number comes back as something else and "is it hidden?" reads as a bug;
* **nothing ever activates it.** Every move carries `SWP_NOACTIVATE`: the main game keeps
  focus and pad 1 all day (plan v6 §11), and a window that took focus when it appeared would
  take the Player's controller with it;
* the home rectangle, when the JSON file is missing, is worked out the same way the game and
  the portal work it out: **the right half of the right-most monitor, vertically centred,
  half the monitor's width and height** — 960 × 540 at (960, 270) on a 1920 × 1080 screen.

One thing the start script must get right, which is the game's side rather than the
helper's: the preview copy needs **`-UserDir=`** (`unreal\Tools\run_preview.ps1` passes it).
Without it the two copies share one `GameUserSettings.ini` and the preview's lowest settings
become the main game's — see `unreal/README.md`.

It still enumerates the controllers at startup and reports what it saw, so a run in a test says
as much about the hardware as a run at the booth.

## The portal's exit test

```powershell
server\.venv\Scripts\python.exe booth\portal_exit_test.py
server\.venv\Scripts\python.exe booth\portal_exit_test.py --headed       # watch it happen
server\.venv\Scripts\python.exe booth\portal_exit_test.py --keep         # leave it all running
server\.venv\Scripts\python.exe booth\portal_exit_test.py --only express # one tour only
```

It starts its own demo server (port 8796, its own temporary data folder), its own pad helper
(port 8702) **and a real game client** (`server/tools/fake_client.py` against the same server),
so it can run while the booth's server and helper are up and touch neither.

Everything it does, it does by writing lines to `pad_helper.py --simulate --stdin`. Nothing is
clicked, so what is tested is the booth's real input path — and the game side is a real client,
so the Live screen's mount step and the Report's counted views are real events rather than a
story the portal tells itself.

**Tour 1, the full visit.** Attract → brand → Content 1 approved → the engine-5.3 file rejected
with the server's own sentence → Game A → the slot map, A1's card filled in and A3 greyed out →
Japan and India ticked and bid → the rival's counter-bid, the "Outbid in India" banner and the
cursor jumping → raise Japan → **the staff close-auction combo, held for three seconds** → Won in
Japan, Lost in India → Live, waiting for the game and then mounted → the Report → the Start
menu's region check → push version 2 and watch the platform serve it and the game swap it → the
Summary → the twenty-second automatic reset back to Attract.

**Tour 2, the express visit** (the 90-second version for a crowd): preset brand, Content 1, one
slot, Japan only, and staff closing the auction before the rival ever answers.

**Then the idle reset**, with `?idle=5` so it takes five seconds instead of sixty.

Every screen is screenshotted at 1920×1080 into `portal/_shots/015/` and audited in the page:

* every bilingual block really has both languages, and no text is drawn outside one (numbers,
  slot ids, file names and button faces are marked `data-datum` and exempt — they are the same
  in both languages);
* nothing is clipped, off screen, or spilling out of the box it lives in (a flex child squeezed
  smaller than its contents does not scroll — it paints over its neighbours, which is the bug
  this check exists to catch);
* nothing on screen is smaller than 20px, and the body size is reported.

It needs `playwright` and `pillow` in the server's venv, and it drives the **installed Microsoft
Edge** (`channel="msedge"`), so there is no browser to download:

```powershell
server\.venv\Scripts\python.exe -m pip install playwright pillow
```

## The region preview window's exit test

```powershell
server\.venv\Scripts\python.exe booth\preview_exit_test.py
server\.venv\Scripts\python.exe booth\preview_exit_test.py --keep        # leave it all up
server\.venv\Scripts\python.exe booth\preview_exit_test.py --headless    # no visible browser
```

Brief 017's exit test, and the only one that runs **two copies of the packaged game at
once**. It starts its own server (port 8797), its own pad helper (port 8703), the preview
copy and the main game, and drives the portal through the helper's `--simulate`:

1. a visit: brand, Content 1 approved, Game A, slot A1, Japan and India ticked and bid, the
   rival's counter-bid, a raise in Japan only, the staff close — **won in Japan, lost in
   India**;
2. the Start menu's Region check opens → the helper moves the window onto the rectangle the
   portal leaves free → it is showing **the India rival's building in A1**;
3. the region is flipped to Japan from the portal → the same window, the same slot, now
   showing **the visitor's own content**;
4. the step is left → the window goes off-screen and the portal has the screen back;
5. the **live-flip fallback** (plan v6 §11): the menu's second row makes the *main* game
   play as India for twenty seconds, A1 swaps to the India rival in front of the Player,
   and it swaps back by itself;
6. the main game's **focus is checked at every beat**; at the end it is deliberately put in
   the background to show it is still running and still drawing; and its frame time is
   reported per phase from its own status file.

It captures both the **desktop** (what a camera would see, the preview window included) and
the **portal page** underneath it, and crops the preview's rectangle out of the desktop shot
on its own — into `booth/_shots/017/`, with `result.md` next to them. The booth has two
monitors; this PC has one, so the main game is parked in the bottom-left where it cannot
cover the preview's rectangle, and the two kinds of shot together say what one screen
cannot.
