# Brand portal — spec v1 (right monitor, controller 2)

*Written 2026-10-25 by chat Claude for Claude Code. Derived from demo plan v6 §4, §10.4, §11 and `server_spec_v1.md`.
Status: DONE (spec); build DONE (briefs 014–015).*

> **Override: English only, Kavin's ruling 2026-11-02** (brief 018E). Everything below about
> Japanese — §1's "every string in Japanese and English", the bundled Noto Sans JP, and §4's
> "every string has JP + EN" — no longer holds. The portal draws one English line per string,
> at the size the Japanese line used to have, and there is no bundled font. `specs/DECISIONS.md`
> records the call; the rest of this spec stands as written.

## 1. Shape

- Static web app in `portal/` (HTML + CSS + vanilla JS ES modules, **no build step, no framework, no CDN**), served by the
  demo server at `http://127.0.0.1:8700/portal/` — same origin, no CORS. Runs in Edge kiosk mode on the right monitor.
- **Ten-foot, console-store UI, not a web form.** Dark theme, large type (body ≥ 28 px, headings ≥ 48 px at 1080p), one
  obvious focus ring, everything reachable with the D-pad. Noto Sans JP bundled locally (OFL licence) in `portal/fonts/`.
- **Every string in Japanese and English at the same time** — JP line on top, EN smaller below. No language toggle. All
  strings live in `portal/strings.js` (one table, keyed), so a human can review the JP in one place. JP is machine-drafted
  and must be marked "needs native review" in that file's header.
- **Input:** the pad helper (booth plumbing, its own spec) reads controller 2 in the background and sends events over a
  WebSocket `ws://127.0.0.1:8701`. The portal also accepts keyboard (arrows / Enter / Esc / Tab) for the hidden emergency
  keyboard. The portal never needs window focus to receive pad input.
- Polls the server: lots every 0.5 s while an auction screen is open, everything else every 1 s.
- No names anywhere: Game A / Game B, slots A1–B2, Content 1–4, "You" / "Rival". Money words never appear except
  **"demo credits — not real money"**, shown under every credit figure the first time it appears on a screen.

## 2. Pad mapping

| Button | Meaning |
|---|---|
| D-pad / left stick | Move focus |
| A | Select / confirm |
| B | Back |
| Y | The screen's main action (Upload, Place bid, Push update) — always labelled on screen |
| LB / RB | Bid −25 / +25 on the focused region row |
| LT / RT | Bid −100 / +100 |
| Start | Menu: pause campaign, show / hide region preview |
| Staff combos (hold 3 s) | LB+RB+Back = reset · LB+RB+X = close auction now · LB+RB+Y = sabotage corrupt · LB+RB+B = sabotage freeze |

A button-hint bar is always visible at the bottom of the screen.

## 3. Screens (in tour order)

Header on every screen after step 1: your brand's colour + emblem chip · wallet **available / held** · demo clock
"14:00 demo time".

0. **Attract** — live ticker of the rivals' auctions and what each slot shows now; "Press A to start". Returns here after reset.
1. **Create your brand** — 8 colours × 8 emblems grid; live preview of the sign; "Wallet: 2,000 demo credits".
2. **Upload** — "Your computer" list (from `/demo-files`, with sizes). Pick → real upload with a progress bar → the four checks
   tick one by one (package · rating · fit · sign) → Approved, or Rejected with the reason sentence → My content.
3. **Pick a game** — two big tiles: slot count, players online; Game A carries the badge "Playing at this booth".
4. **Slot map** — the map image with a pin per slot, pins coloured by footfall (low → high), D-pad hops between pins. Side card
   for the focused slot: eye-level thumbnail, size class rules in plain words, footfall per region, highest bid + holder,
   "closes in mm:ss", credits per 1,000 views. Slots your content doesn't fit are greyed with the reason ("Too tall for this
   slot — 17 m, limit 9 m").
5. **Regions and bid** — one row per region: tick · footfall · highest · your bid (LB/RB) · status. Optional "total across
   ticked regions" split by footfall, then adjust rows. Y = Place bid → credits held.
6. **Auction** — big countdown, per-region rows with Leading / Outbid. When the rival counter-bids: a clear "Outbid in Japan"
   banner and the cursor jumps to that row. Soft-close bids show "+10 s". Ends in a Won / Lost card per region.
7. **Live** — "Your content is live" with the slot and region; a four-step strip resolve → download → verify → mount driven
   by `/status/live` (the game reports mount via telemetry); "The player's screen shows a marker to it".
8. **Region check** — Start-menu item shows the region preview window (the pad helper raises it) and flips its region; the
   portal says in plain words "This is the same game for a player in India."
9. **Report** — per region: views, visits, dwell, interactions, credits charged, credits per view; time-left bar; Pause; Y =
   Push an update; "Book the next block".
10. **Push an update** — pick version 2 from "Your computer" → upload → checks → "Will swap when the player walks out" →
    "Swapped — lights, door and screen kept as they were".
11. **Summary** — at block end: credits spent, views, visits, dwell, cost per view by region → auto-reset after 20 s or A.

Idle 60 s without input → server reset → Attract.

## 4. Acceptance

A tester using only a pad (or the keyboard fallback) goes from Attract to a won A1 / Japan lot, uploads, pushes an update and
reaches the Summary without touching a mouse; every screen readable from 2 m on a 27" 1080p monitor; every string has JP + EN.
