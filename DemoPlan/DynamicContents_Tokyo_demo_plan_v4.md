# DynamicContents — Tokyo demo plan (v4)

*Cold-reader document, written 2026-09-21 by Claude (chat session, DynamicContents Project) at Kavin's request. Companion to `README.md` (system overview + Claude's read) and the six figures in `diagrams/`. **Supersedes v3.***

**Status: the plan is DONE. Every build item in it is FUTURE — nothing is in flight.**
Build tooling (Kavin's call): Codex Astra plus Claude. Build time is not the constraint; a proper demo is.

### What changed from v3 (Kavin's scope ruling, 2026-09-21)
- **No wearables, no try-on, no player-side shopping.** The Player is not involved in money at all; they get a proper gameplay experience.
- **The money side lives entirely in the Brand portal**, as a slot marketplace: each slot shows its footfall, its current highest bid and the time left on the current booking; the Brand has a wallet of fake credits, picks a slot, bids, and "buys" it for X hours.
- Spend model changed from per-view spend to **time-based bookings**. A demo clock (1 demo hour = 1 real minute) makes "X hours" fit a five-minute visit, and the booking running out is the natural end of the visit.
- Removed: simulated platform store, receipts, entitlements, physical order + QR, the visitor's phone, the returning-player card, the price editor.
- Consequence: the patent's *in-world commerce and entitlement* figure is **not shown live** (see sections 5 and 15).

---

## 1. The demo in one paragraph

One PC, two monitors, two controllers. **One controller per role.** Controller 1 is the **Player** (left screen, the game). Controller 2 is the **Brand** (right screen, the portal). The Player plays a small street game. The Brand looks at a marketplace of slots, sees which ones get the most footfall and what the current highest bid is, spends fake credits to book a slot for a few hours, and publishes a building into it. The Player gets a new venue to play in seconds later — no loading screen, no restart — and later watches it get updated underneath them without losing progress. When the Brand's hours run out, the slot goes back to the next highest bidder. The game build starts in the morning and never restarts.

**Plain-words glossary**

| Word | Meaning here |
|---|---|
| Slot | A fixed spot in the street where a building can be swapped in at runtime |
| Pack | The downloadable content package for one building (a pak / container set) |
| House campaign | A built-in campaign that always holds a slot, so there is always something to outbid and something to fall back to |
| Footfall | How many views a slot gets per demo hour ("footprints") |
| Booking | A slot won for a number of demo hours |
| Demo clock | 1 demo hour = 1 real minute. Shown on the portal, labelled "demo time" |
| Window | One demo hour. The auction decides a winner per slot per window |
| Status strip | Small always-on strip on the left screen showing what the slot is doing right now |
| X-ray view | Optional overlay: pre-fetch ring on the ground, the manifest, the cache list |

---

## 2. The fixed kit and the booth

Planned **only** around what is guaranteed: **1 PC, 2 monitors, 2 controllers.** No tablet, no second PC, no router, no venue network, no visitor phones. A keyboard and mouse stay hidden under the table as emergency backup; visitors never touch them.

| | Player seat (left) | Brand seat (right) |
|---|---|---|
| Screen | Left monitor: the game, full screen | Right monitor: slot marketplace, live report, Player B window |
| Input | Controller 1: play | Controller 2: pick a slot, bid, publish, push update |
| Who | A visitor | A second visitor, or a staffer, or the same visitor swapping pads |

Everything runs on the one PC: the game, a small second copy of the game (Player B), the brand portal (a web page), the local server + storage (the stand-in cloud), the pad helper, and a start script with a watchdog.

---

## 3. The world and the game

One street, three slots, one packaged build.

- **Corner slot** — highest footfall, most expensive. House campaign: the ramen shop.
- **Plaza slot** — medium footfall. House campaign: the boutique (the hackathon clothing-store shell reused as a plain walk-in venue; no try-on).
- **Lane slot** — low footfall, cheapest, small. Holds small stalls. Used for Player B's comparison and for the "too tall" rejection.

Empty or failed slots show a placeholder: a construction hoarding reading "Coming soon".

**The Player's game: a stamp rally.** Tokens to collect along the street, and one stamp to earn inside every venue by doing its activity (collect 5 tokens inside, beat an arcade score, find the posters, play the jukebox sequence). New venues mean new stamps. When a new building lands, the Player gets an in-world "new venue on the Corner" ping — no ad or money language ever appears on the Player's screen. The Player never sees bids, prices or wallets.

A strip on the left screen shows, all day: **build number · uptime · restarts: 0 · loading screens: 0.**

---

## 4. The flow — full tour, about 5 minutes

| Act | Brand seat (pad 2, right screen) | Player seat (pad 1, left screen) | Patent promise shown |
|---|---|---|---|
| **0. Attract** (idle) | Marketplace ticks over: footfall, highest bids, allocation grid filling as house campaigns outbid each other each demo hour | Buildings swap on the empty street; "pick up a controller" prompt | Time-window allocation, live refresh, immediate swap |
| **1. Arrive** 0:00 | Player B window: same street, different profile, low-spec → a different stall in the Lane slot, lite pack | Picks a profile card and starts the stamp rally | Context-driven variation, device-aware variants |
| **2. Bid** 0:30 | Marketplace: three slots, each with footfall, current highest bid and time left. Wallet: 2,000 demo credits. Picks a slot → a building → hours → bid. Checklist: package ✓ fits slot ✓ rating ✓ signed ✓. "You won the Corner for 3 hours." Allocation grid fills | Keeps playing | Portal, the validate → moderate → sign gate, auction, allocation schedule |
| **3. It appears** 1:30 | Live report starts: views, visits, dwell | Gets the "new venue" ping; crosses the pre-fetch ring; strip ticks resolving → downloading → verifying → mounting; building materialises; walks in | Full runtime sequence, no loading screen, telemetry |
| **4. Play and measure** 2:15 | Watches what the booking is earning: views, visits, dwell, cost per view, time left. Can extend the booking or bid on a second slot with what's left in the wallet | Plays the venue's activity for its stamp | Reporting dashboard (funnel and spend); real interactive content, not a billboard |
| **5. The swap** 3:15 | Presses "push Season 2 update" on their own building | Is inside, mid-activity (say 3 of 5 tokens). Strip: swap pending. Walks out → swap. Walks back in → 3 of 5 still there | Post-deployment replacement, deferred swap, state preservation |
| **6. Booking ends** 4:30 | Hours run out → the next window re-auctions → the house wins the slot back. Summary card: credits spent, views, visits, dwell, cost per view | Building hands back; earned stamps stay earned | Time-window allocation, spend accounting, the full loop |

Then automatic reset back to Act 0.

### Act notes

**Act 0 — Attract.** Runs whenever both pads are idle for 60 s. Each demo hour the server re-runs the auction among house campaigns, so winners change and buildings swap. This is the allocation schedule doing its job, not just a timer.

**Act 1 — Arrive.** Profile cards: *Gamer*, *Music fan*, *Film buff*. Player B always gets a different profile from the one the Player picked and reports itself as low-spec. Players appear on the portal only as a pseudonymous ID (e.g. Player #A41F), and brands only ever see totals.

**Act 2 — Bid.** Everything on the pad. "Signed in as Demo Brand". Each slot card shows: where it is on a mini-map, footfall (High / Medium / Low plus views per demo hour), who holds it, the current highest bid per hour, and time left on that booking. The default bid always beats the house, so the normal path never disappoints. A curious visitor can lowball and see "Outbid — the Corner stays with the ramen shop at 300 per hour", and nothing changes in the world. Two library items are built to fail so rejection-with-reason is always showable: a tower that is **too tall** for the Corner slot ("try the Plaza slot"), and an **18+ trailer** building aimed at an all-ages slot.

**Act 3 — It appears.** The X-ray view shows the pre-fetch ring, the real manifest fields (pack ID, version, hash, URL, class path) and the cache list. Publishing the same building again in the same visit is instant and the strip says **cache hit**. A short "materialise" effect on the placeholder hides the spawn frame.

**Act 4 — Play and measure.** The two seats are doing their own thing at the same time: the Player is simply playing; the Brand is watching what their credits bought. The Player's real views and visits land on the Brand's report within a second or two — that live link between the screens is the point of the act.

**Act 5 — The swap.** This is the patent's strongest idea and the headline act. Each publishable building has a Season 2 version (a re-skin) and one activity with saveable progress. The new version is queued while the Player is inside, swaps only when they leave, and their progress is restored into the new version.

**Act 6 — Booking ends.** With the default 3-hour booking this lands about 3 real minutes after the win. If the Player is inside at that moment, the deferred swap handles it gracefully. The Brand can also press "end booking early" (unused hours are refunded); staff can force it.

### Express version (90 seconds, for crowds)
Act 2 on defaults (three button presses), then Act 3.

### Staff tricks (for "what if it fails?")
- **Corrupt pack:** a button combo makes the server send one corrupted pack → hash mismatch → placeholder stays → retry with backoff → success.
- **Frozen download:** a second combo pauses the server mid-download for a few seconds → the download resumes from where it stopped rather than starting over.

---

## 5. Patent coverage map

| Figure | Covered live? | Where in the flow |
|---|---|---|
| Detailed system architecture | Yes (minus the commerce bridge) | Every content-delivery module runs for real; backend is the local server or AWS |
| Runtime sequence | Yes, all 22 steps | Act 3; cache-hit branch on a re-publish |
| Slot lifecycle state machine | Yes, every state | Normal path in Act 3; swap pending + unload & preserve in Act 5; immediate swap in Acts 0 and 6; error / fallback in the staff tricks |
| Advertiser portal & bid-to-slot | Yes | Act 2 (portal, gate, auction, allocation); Act 0 (windows); Acts 3–6 (reporting, spend) |
| Context-aware resolution engine | Simplest policy only | Acts 1–2 and the "why this building?" panel. Learned and adaptive policies stay on a poster — they do not exist yet |
| **In-world commerce & entitlement** | **No — by decision** | Poster only. Optional: a 20-second clip of the hackathon clothing store in the attract loop on the right screen, captioned "also in the patent, not part of this demo" |

Note for the record: the patent figure set contains **two** money flows. *Brands paying for slots* (the bid-to-slot figure) is what this demo shows. *Players buying things inside a branded building* (the commerce and entitlement figure: try-on, platform checkout, receipt, entitlement, physical order) is a separate figure and is deliberately left out of the live demo.

The demo also settles the one disagreement between the bid-pipeline and context-engine figures: **the auction decides per slot per audience per window; resolve just looks the answer up.**

---

## 6. Where it is watered down

Say these out loud at the booth. Honesty helps.

| Real thing | Demo version |
|---|---|
| Brand uploads and cooks content | "Upload" = pick from a library of pre-cooked packs |
| Human moderation + policy review | Four automatic rule checks; two items built to fail |
| Live auction among many bidders | One fixed formula, numbers on screen, house campaigns as rivals, default bid always wins |
| Real money, invoicing | A wallet of 2,000 demo credits. No currency symbols, no card fields, nothing typed. Labelled "demo credits — not real money" |
| Bookings of hours or days | Demo clock: 1 demo hour = 1 real minute |
| Footfall from a real player base | A seeded, simulated crowd figure per slot plus the live Player's real views on top, labelled as such |
| Context engine with learned policies | Three visible signals (profile, device tier, day/night toggle) + developer rules as hard gates + a "why this building?" panel. Decisions cached for 30 s |
| Accounts, privacy | "Signed in as Demo Brand"; players are pseudonymous IDs; brands see totals only |
| HTTPS + CDN | Local mode: plain HTTP on the same PC, real presigned links from the local storage. AWS mode: genuine HTTPS + S3 presigned URLs |
| In-world shopping | Not shown |
| Multiplayer | Not shown |

---

## 7. How the pieces work (starting values — tune in testing)

### The local server (the stand-in cloud)
One small program plus S3-compatible storage (MinIO) on the same PC. The game talks to it exactly as it would talk to the real backend.

| Call | Purpose |
|---|---|
| `GET /resolve` | Slot + context in → signed manifest out (pack ID, version, hash, URL, class path) |
| `GET /changes` | Game polls every 1–2 s to learn a slot's allocation changed |
| `GET /slots` | Marketplace data: footfall, holder, highest bid, time left, allocation grid, wallet balance |
| `POST /bid` | Building, slot, audience, hours, bid per hour → ingest checks → auction → booking |
| `POST /booking/extend`, `/booking/end` | Add hours; end early with refund of unused hours |
| `POST /push-update` | Publish the Season 2 version of a live building |
| `GET /report` | Views, visits, dwell, interactions, credits spent, cost per view, time left |
| `POST /telemetry` | Impressions, dwell, interactions from the game |
| `POST /admin/reset`, `/admin/sabotage` | Booth housekeeping and the staff tricks |

Pack downloads are paced in local mode so they take 3–5 seconds. Still a real HTTP download and a real hash check.

### Marketplace and bidding rules
- **Wallet:** 2,000 demo credits per visit.
- **Seeds:** Corner — High footfall — house holds at 300 per hour. Plaza — Medium — 200. Lane — Low — 100.
- **A bid is:** slot, building, audience (default: everyone), hours (2, 3 or 4; default 3), bid per hour (default: current highest + 50). Total = bid × hours, and must fit the wallet.
- **Winning:** highest score per slot per window. Score = **bid × quality × relevance.** Quality is fixed per building (about 0.8–1.2) and shown in My content. Relevance is 1.0 for "everyone", or 1.0 / 0.5 for a targeted audience that does / doesn't match the player's profile; night-only campaigns get ×1.5 at night. With default settings this is simply "highest bid wins".
- **On a win:** credits for the booked hours are held from the wallet, the current window is re-auctioned immediately (the booking starts now), and the allocation grid fills for the booked hours.
- **On a loss:** "Outbid" card; wallet untouched; world unchanged.
- **On expiry:** the next window's auction runs without the visitor's campaign; the house wins the slot back.
- **Ingest checks, in order:** package (exists, size, engine version tag) → fits the slot (bounds) → content rating vs the slot's rule → sign (hash + signature with a demo key). Only content that passes becomes biddable.

### Context rules
- Signals: player profile (user), device tier (system), day/night toggle (external), developer rules (hard gates such as "Plaza: all-ages only", "Corner: max height").
- Lane slot stalls: game kiosk (matches gamer), record stall (matches music), night-market stall (night). A film-buff player matches neither, so the highest bid × quality wins — visible in the "why this building?" panel.
- Low-spec clients are given the lite variant of a pack.
- Decision cache: 30 s per slot × context. A new booking clears it.

### Swap and saved progress
Progress is a small record keyed by slot + building + schema version. Saved on unload, restored on spawn. Season 1 and Season 2 of a building share the schema. If schemas ever differ: migrate or discard, never crash. Earned stamps belong to the Player's game and survive a building leaving.

### Telemetry definitions
- View (impression): building on screen, within 30 m, at least 1 s, not blocked (simple line check).
- Visit: the Player enters the slot's bounds. Dwell: seconds inside.
- Interaction: each use of the venue's activity.

### Reset
Triggered by 60 s idle or a 3-second staff combo on pad 2. Wipes: the visitor's booking and wallet, counters, the Player's stamps and saved progress, decision cache, and the visitor-publishable packs from the local cache (so every visitor sees a real download; house packs stay cached).

---

## 8. What gets built (all FUTURE)

1. **Game** — the street and stamp rally, 3 slots, one activity per venue with saved progress, "new venue" ping, status strip + uptime stamp, X-ray view, swap path, attract mode, resets.
2. **Player B view** — second copy of the same build: fixed camera, other profile, low-spec flag, no input, no audio.
3. **Brand portal** — slot marketplace (footfall, highest bid, time left, mini-map), wallet, My content, bid form, checklist, win / outbid card, allocation grid, live report, "why this building?", extend / end booking, push-update button, summary card, demo clock. Every string in JP and EN.
4. **Server** — everything in section 7. One codebase, runs local or on AWS.
5. **Booth plumbing** — pad helper, start script, watchdog.
6. **Content** — see section 10.

---

## 9. Technical calls already made

- **The game keeps window focus all day.** The portal is driven through the pad helper, not by clicking, so nobody clicks outside the game.
- **Insurance anyway:** borderless windowed (never exclusive fullscreen), no frame-rate throttle and no audio mute when unfocused — so an emergency mouse click on the right screen is survivable.
- **Controllers wired by USB, never Bluetooth.** At startup: "press ✕ on the player pad" → the game locks to that pad, the helper takes the other.
- **Pad helper** reads pad 2 with background input enabled and relays to the portal over localhost. This path never goes through the cloud.
- **Player B budget:** 30 fps cap, half resolution, lowest settings, below-normal process priority, its own pack cache folder. Main game at high priority.
- **Player B pass/fail:** the main game must hold its frame rate with B alive through a soak run. If not, drop B and do Act 1 as a live flip: the Brand presses "switch player profile" and the Lane stall swaps in front of the Player.
- **One-button start:** storage → server → portal on the right monitor → game on the left → Player B, in order, with health checks; a watchdog restarts anything that dies.
- **Portable:** the whole demo is one self-contained folder (relative paths, no installers), copied to a USB drive next to the backup video.

**Day-1 checks (before anything else is built on top):**
1. The game listens to pad 1 only.
2. The helper reads pad 2 while the game has focus.
3. Two copies of the game run side by side.
4. The game keeps running, rendering and playing audio when unfocused.

---

## 10. Content list

| Item | Count | Notes |
|---|---|---|
| Publishable buildings | 4 × 2 versions | Game lounge, music venue, film pop-up, arcade. Season 2 = re-skin. Each has one activity with saveable progress |
| Ramen shop | 1 | Corner house campaign |
| Boutique | 1 | Plaza house campaign. Hackathon clothing-store shell, plain walk-in venue, no try-on |
| Lane stalls | 3 | Game kiosk, record stall, night-market stall. Small |
| Lite variants | 1–2, optional | For the low-spec Player B |
| Built-to-fail items | 2 | Too-tall tower, 18+ trailer. Thumbnail + manifest only; never cooked |

Brands: the company's own family of brands plus playful generic ones. No third-party trademarks.

**Minimum set if art time gets tight:** 2 publishable × 2 versions, the ramen shop, the boutique, 2 stalls.

All packs cooked against the exact demo build, sized so a paced local download takes 3–5 s and stays under roughly 100 MB for AWS mode.

---

## 11. Local mode vs AWS mode

One server codebase, two homes.

| | Local mode (floor default) | AWS mode (a switch) |
|---|---|---|
| Server | Normal program on the PC | Same code in Lambda behind API Gateway (Lambda Web Adapter, no rewrite) |
| Files | MinIO | S3 (same API; config change), presigned URLs, CloudFront optional |
| Data | Small database file | DynamoDB |
| Transport | HTTP on localhost | HTTPS |
| Download pacing | On (3–5 s) | Off — the real network provides it |

- The game and portal read one setting: the backend address. Switch only at reset, never mid-visitor.
- The start script health-checks the cloud and falls back to local if there's no answer.
- Use AWS mode for the viability demo at the office and for "now it's coming from the Tokyo region" moments when the venue link is good. Internet is **not** on the guaranteed list, so the booth must never depend on it.
- Tokyo region for the expo, Mumbai for office testing. Bid endpoint protected with a key; bucket private.

---

## 12. Order of work, each with an exit test

1. **Publish → appear.** Server, storage, polling, status strip, day-1 checks. *Exit: a booking is made and the building appears, ten times out of ten.*
2. **Marketplace, bidding, bookings, allocation grid, Player B.** *Exit: a pair of strangers completes Acts 1–3 unaided. This is the minimum viability demo — record a clean capture that day; it is the submission video and the permanent fallback.*
3. **The game itself.** Stamp rally, one activity per venue, saved progress, "new venue" ping. *Exit: someone plays for five minutes without being told what to do and without getting bored.*
4. **Swap with saved progress, booking expiry, live report, attract windows.** *Exit: Act 5 works ten times out of ten, including when the booking expires while the Player is inside.*
5. **Hardening, then feature freeze.** Three overnight soak runs: a scripted bot cycles bid / mount / swap / unmount 500+ times while logging memory and frame time — pass = flat memory, no stutter. Failure drills: kill the server mid-download, serve a corrupt pack, unplug a pad. The visitor must only ever see the placeholder, never an error. Staff cue cards (JP/EN), pack list.

Step 5 is not optional however fast the code gets written. Fast-written code is exactly what a soak test is for.

---

## 13. When something breaks on the floor

| What breaks | What happens |
|---|---|
| Download or verify fails | Placeholder stays, quiet retry with backoff. No error shown |
| A program crashes | Watchdog restarts it; booth drops into attract mode |
| A pad dies (there is no spare) | Staffer drives the portal with the hidden mouse; the game is set up to survive that |
| Cloud unreachable (AWS mode) | Start script falls back to local mode |
| The PC dies | USB folder onto any borrowed PC (about 15 minutes); backup video covers the gap |

---

## 14. Deliberately not shown

Real money of any kind · in-world shopping, try-on, wearables, entitlements · human moderation · live uploads or live cooking · learned or adaptive scoring · multiplayer · brand logins. Anything money-like is labelled "demo credits".

---

## 15. Open items

- 🔴 **ACT — patent timing.** Act 5 (replacement + state preservation) is the headline act and is exactly what the spec was flagged as not describing. It needs to be in the spec before filing, and the filing needs to land before any public showing. Ask the patent team to confirm both, and that what is on the booth is covered. Not legal advice; it is the one item here that cannot be fixed afterwards.
- 🔴 **ACT — AWS account.** If AWS mode is wanted, use a company-approved account only, never a personal one. The approval may take longer than the code.
- 🔴 **DECIDE — dates.** The viability-review date and the Tokyo date are still unknown. They turn section 12 into a calendar.
- 🔴 **DECIDE — the commerce figure.** It is out of the live demo. Poster only, or poster plus the 20-second hackathon clip in the attract loop?
- 🟡 **Content is the long pole, not code.** Art and cooking time do not shrink with coding agents. Kitbash and re-skin; fall back to the minimum set if needed.
- 🟡 **The game now has to be fun on its own.** "Proper gameplay" is a requirement, so stage 3 in section 12 gets a real playtest, not just a functional check.
- 🟡 **PC strength is unknown.** The Player B pass/fail test answers it; the live-flip fallback needs no extra work.
- 🟡 **Single points of failure:** one PC, no spare pad. Mitigations are in section 13.

**Next artifact (FUTURE):** the build spec for the coding agents — endpoints with data shapes, the rule tables, and one acceptance test per act.

---

*If this document and a patent figure disagree about how the real system works, the figure wins. This document describes the demo, which is a deliberately simplified version of it.*
