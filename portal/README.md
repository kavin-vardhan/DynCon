# The brand portal — what is here and how to run it

*The right-hand monitor of the booth, driven by controller 2. Built to `specs/portal_spec_v1.md`
— with one override: **English only, Kavin's ruling 2026-11-02** (brief 018E).
**DONE**: the whole tour — the app shell and steps 0–4 (brief 014), steps 5–11 plus the Start
menu and the idle reset (brief 015), the region preview window's show/hide and the
rectangle it lands on (brief 017), and the English-only pass over every screen (brief 018E).
Nothing here is QUEUED.*

## Run it

```powershell
.\server\run_local.ps1                 # the server serves the portal at /portal/
start msedge --kiosk "http://127.0.0.1:8700/portal/" --edge-kiosk-type=fullscreen
py -3 booth\pad_helper.py              # controller 2 -> the portal (booth\README.md)
```

There is nothing to build and nothing to install: the portal is static files (HTML + CSS +
vanilla JS ES modules) that the demo server mounts at `/portal/`, which is the same origin as
the API — so no CORS, no base URL to configure, and one process at the booth instead of two.
Nothing is fetched from the internet at runtime, and since the English-only ruling there is
no bundled font either - the stack is the platform's own UI face.

Open it with `?pad=8702` to listen to a pad helper on another port (that is what the exit test
does, so it can run while the booth's own helper is up), and with `?idle=5` to shorten the idle
reset from sixty seconds to five while rehearsing. The booth URL has no query at all.

## What is in here

| Path | What |
|---|---|
| `index.html` | the shell: a header, a main area and the button-hint bar |
| `app.js` | state, routing, the header, the hint bar, the demo clock, the 60-second idle reset |
| `menu.js` | the Start menu: the region preview control (tour step 8), pause, summary |
| `strings.js` | **every word the portal can draw**, English only (Kavin's ruling 2026-11-02). One table, so a professionally translated language can be added later without touching a screen |
| `ui.js` | the only way text gets on screen (`tx()` / `txText()`), plus emblems, button glyphs, toasts |
| `api.js` | every call to the server, including the real upload with progress |
| `input.js` | the pad WebSocket client and the keyboard fallback |
| `screens/` | one module per screen: `attract` `brand` `upload` `games` `slotmap` `regions` `auction` `live` `report` `update` `summary` |
| `style.css` | the whole look. 1rem = 16px at 1080p, so every size reads as "px at 1080p" |
| `_shots/014/`, `_shots/015/`, `_shots/018E/` | the exit tests' contact sheets (the per-screen PNGs are git-ignored and rebuilt by the test) |

The region preview window's own exit test lives in `booth/preview_exit_test.py` and writes
to `booth/_shots/017/`, because it is two copies of the game as well as the portal.

## The rules this app keeps

1. **English only — Kavin's ruling, 2026-11-02.** The portal used to draw every line twice,
   Japanese over English; a machine-drafted Japanese line that nobody had reviewed was judged
   too risky to show at the booth, so it is gone, and the bundled JP font with it. Plan v6 §10
   item 4 still says "every string in JP and EN"; this is the override, and `specs/DECISIONS.md`
   records it. What has not changed: there is no way to draw text except `tx()` / `txText()`,
   every word comes from `strings.js`, and sentences the *server* writes (the four checks, a
   rejection, a fit refusal) are the server's own words, drawn as they arrive.
2. **No names.** Game A / Game B, slots A1–B2, "Content 1", "another brand" for the rivals.
   Credits are always labelled *demo credits — not real money* (the hint bar says it on every
   screen). "Dynamic Contents" is the platform's own wordmark, which is the one proper noun here.
3. **Ten feet, not ten inches.** Body text is 30px at 1080p, the smallest caption is 20px, there
   is exactly one focus ring on screen, and the button-hint bar is always visible. The exit test
   fails the build if any of that stops being true. English now takes the size the Japanese line
   used to have, so with one line per block every tier went *up* a notch rather than down, and
   the boxes that had been squeezed to fit two languages are back at an ordinary spacing.
4. **The pad never needs focus.** Presses arrive over a WebSocket from `booth/pad_helper.py`, so
   the browser window can be behind anything. The keyboard is the emergency fallback. The same
   socket carries one message the other way — show or hide the region preview window — because
   a web page cannot move another program's window and the helper can.

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
   played at the booth. The same piece of content works in either. Since brief 018 the
   badge **follows a switch**: the Player can change game from their own pause menu, the
   platform learns which one from the poll the game already makes, and this screen's
   two-second refresh moves the badge without being reopened.
4. **Slot map** — the map image the developer's own editor tool captured and registered, a pin
   per slot coloured by footfall, D-pad hops pin to pin. The side card is the slot contract: the
   eye-level photograph of the empty spot, what fits in plain words, footfall per region, the
   highest bid and who holds it, the countdown, and credits per 1,000 views. A slot the chosen
   content does not fit is greyed out and the card says why, in the server's words.

5. **Regions and bid** — one row per region: tick, footfall, the highest bid and who holds it,
   your bid (LB/RB ±25, LT/RT ±100), status. A total across the ticked regions is split by
   footfall by the server (`/bids/split`) and then any row can be adjusted by hand. Y places
   every ticked bid at once, and the header's held credits move.
6. **Auction** — polled twice a second, because both of the things it exists to show are sudden:
   the rival's single counter-bid three seconds after your first bid (a banner, and the cursor
   jumps to that row) and the soft close (a bid inside the last ten seconds puts the clock back
   to ten, and the row shows "+10 s"). It ends in a Won / Lost card per region. The server has
   no timers: this screen's own polling is what makes a due counter-bid or a due close happen.
7. **Live** — there is no publish button. Four steps: resolve (the platform now answers this slot
   with your signed manifest — from `/status/live`), download and verify (on the player's
   machine; the portal cannot see them and says so), and mount (the game's own telemetry, counted
   per region by `/report`). Beside it, what each region is showing right now.
8. **Region check** — in the Start menu: pick the region the second copy of the game plays as,
   and it says in plain words "this is the same game, for a player in India". Opening this
   step **shows the preview window** and leaving it hides it again: the portal cannot move
   another program's window, so it asks the pad helper over the WebSocket the pad already
   arrives on (`{"type":"preview","show":true}`), and the helper answers with what it did.
   The menu's panel sits in the **left half** of the screen and the right half is left empty
   for the window — `.preview-reserve` in `style.css` is exactly the rectangle it lands on:
   the right half of the monitor, vertically centred, half its width and height, which is
   the same rule the game computes from the monitor it is on. While the window is missing
   (the second copy is not running), that rectangle says so instead.

   The menu's second row is the **fallback** for the same step (plan v6 §11): *"Play the
   main game as this region"* posts `/preview/flip`, and the **main** game plays as the
   chosen region for twenty seconds — the slot swaps in front of the Player and swaps back.
   It is there whether or not the preview window is running, because it is also the quickest
   way for staff to show the same thing on one screen.
9. **Report** — per region: views as two columns, simulated and counted, never added up into one
   number; visits, dwell, interactions, credits charged and credits per 1,000 views; the time
   left in the block; Pause (which takes your content down and puts the game's own back); "book
   the next block", which is screen 5 again one sequence number later.
10. **Push an update** — version 2 of what is live: the same four checks, then "it will swap when
    the player walks out", then "swapped — lights, door and screen kept as they were" when the
    game reports the mount. The portal never claims the swap happened on its own.
11. **Summary** — what the block spent and bought, then the booth resets itself: twenty seconds,
    or A.

Sixty seconds without a press on any screen after the attract one resets the demo and goes back
to Attract.

## The exit test

```powershell
server\.venv\Scripts\python.exe booth\portal_exit_test.py
```

It starts its own server, its own pad helper **and a real game client**, walks the whole tour
**through the pad helper's `--simulate`** (not by clicking) plus the 90-second express version
and the idle reset, screenshots every screen at 1920×1080 into `_shots/018E/`, builds a contact
sheet per tour, and audits each screen: **no Japanese character anywhere on it**, every word on
screen came from the string table, nothing is clipped or off screen or spilling out of its box,
and nothing is smaller than 20px. See `booth/README.md`.
