# The brand portal — what is here and how to run it

*The right-hand monitor of the booth, driven by controller 2. Built to `specs/portal_spec_v1.md`.
**DONE**: the app shell, the input path and tour steps 0–4 (attract · brand · upload · pick a game ·
slot map), brief 014. **QUEUED**: steps 5–11 (regions and bid · auction · live · region check ·
report · push an update · summary) — part 2.*

## Run it

```powershell
.\server\run_local.ps1                 # the server serves the portal at /portal/
start msedge --kiosk "http://127.0.0.1:8700/portal/" --edge-kiosk-type=fullscreen
py -3 booth\pad_helper.py              # controller 2 -> the portal (booth\README.md)
```

There is nothing to build and nothing to install: the portal is static files (HTML + CSS +
vanilla JS ES modules) that the demo server mounts at `/portal/`, which is the same origin as
the API — so no CORS, no base URL to configure, and one process at the booth instead of two.
Noto Sans JP is bundled in `fonts/`; nothing is fetched from the internet at runtime.

Open it with `?pad=8702` to listen to a pad helper on another port (that is what the exit test
does, so it can run while the booth's own helper is up).

## What is in here

| Path | What |
|---|---|
| `index.html` | the shell: a header, a main area and the button-hint bar |
| `app.js` | state, routing, the header, the hint bar, the demo clock, the 60-second idle reset |
| `strings.js` | **every word the portal can draw**, Japanese and English. One file so a native speaker can review the JP in one sitting |
| `ui.js` | the only way text gets on screen (`bi()`), plus emblems, button glyphs, toasts |
| `api.js` | every call to the server, including the real upload with progress |
| `input.js` | the pad WebSocket client and the keyboard fallback |
| `screens/` | one module per screen: `attract` `brand` `upload` `games` `slotmap` |
| `style.css` | the whole look. 1rem = 16px at 1080p, so every size reads as "px at 1080p" |
| `fonts/` | the bundled Noto Sans JP subset + `OFL.txt` + `make_subset.py` that cuts it |
| `_shots/014/` | the exit test's contact sheet (the per-screen PNGs are git-ignored and rebuilt by the test) |

## The rules this app keeps

1. **Every string is Japanese and English at the same time**, JP on top. There is no language
   toggle and no way to draw text except `bi()` / `biText()`, which always makes both lines. The
   JP is machine-drafted and `strings.js` says so at the top — **it needs a native review**.
   Sentences the *server* writes (the four checks, a rejection, a fit refusal) stay the server's
   words in English and get a Japanese line above them from the pattern table at the bottom of
   `strings.js`.
2. **No names.** Game A / Game B, slots A1–B2, "Content 1", "another brand" for the rivals.
   Credits are always labelled *demo credits — not real money* (the hint bar says it on every
   screen). "Dynamic Contents" is the platform's own wordmark, which is the one proper noun here.
3. **Ten feet, not ten inches.** Body text is 30px at 1080p, the smallest caption is 20px, there
   is exactly one focus ring on screen, and the button-hint bar is always visible. The exit test
   fails the build if any of that stops being true.
4. **The pad never needs focus.** Presses arrive over a WebSocket from `booth/pad_helper.py`, so
   the browser window can be behind anything. The keyboard is the emergency fallback.

## Keyboard fallback

| Key | Button |
|---|---|
| arrows | D-pad |
| Enter / Space | A |
| Esc / Backspace | B |
| Tab / Shift+Tab | right / left |
| `y` / `x` | Y / X |
| `-` / `=` | LB / RB (bid −25 / +25, part 2) |
| `[` / `]` | LT / RT (bid −100 / +100, part 2) |
| Home / End | Start / Back |

## The screens (plan v6 §4 steps 0–4)

0. **Attract** — what every slot of both games is showing right now, in all three regions, and
   the other brands' auctions ticking over. "Press A to start". Nothing here needs a visitor: it
   is the server's live state, polled once a second, and it changes by itself as the demo clock
   rolls from one three-minute block to the next.
1. **Create your brand** — 8 colours × 8 emblems, live sign preview, 2,000 demo credits. The
   colour and the emblem are the whole brand account; no names, nothing typed.
2. **Upload** — "Your computer" (the server's curated list) → a real HTTP read, a real multipart
   upload with the browser's own progress → the server's four checks ticking across one at a
   time (package · rating · fit · sign) → Approved, or Rejected with the server's own sentence →
   My content, with the slots each piece fits. One file in the list is built to fail.
3. **Pick a game** — two games, slot count, players online, and the badge on the one being
   played at the booth. The same piece of content works in either.
4. **Slot map** — the map image the developer's own editor tool captured and registered, a pin
   per slot coloured by footfall, D-pad hops pin to pin. The side card is the slot contract: the
   eye-level photograph of the empty spot, what fits in plain words, footfall per region, the
   highest bid and who holds it, the countdown, and credits per 1,000 views. A slot the chosen
   content does not fit is greyed out and the card says why, in the server's words.

Sixty seconds without a press on any screen after the attract one resets the demo and goes back
to Attract.

## The exit test

```powershell
server\.venv\Scripts\python.exe booth\portal_exit_test.py
```

It starts its own server and its own pad helper, walks the whole of steps 0–4 **through the pad
helper's `--simulate`** (not by clicking), screenshots every screen at 1920×1080 into
`_shots/014/`, builds the contact sheet, and audits each screen: every bilingual block really
has both languages, nothing is clipped or off screen or spilling out of its box, and nothing is
smaller than 20px. See `booth/README.md`.
