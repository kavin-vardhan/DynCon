# DynamicContents — Tokyo demo plan (v3)

*Cold-reader document, written 2026-09-21 by Claude (chat session, DynamicContents Project) at Kavin's request. Companion to `README.md` (system overview + Claude's read) and the six figures in `diagrams/`.*

**Status: the plan is DONE. Every build item in it is FUTURE — nothing is in flight.**
Build tooling (Kavin's call, 2026-09-21): Codex Astra plus Claude. Build time is not the constraint; a proper demo is.

---

## 1. The demo in one paragraph

One PC, two monitors, two controllers. **One controller per role.** Controller 1 is the **Player** (left screen, the game). Controller 2 is the **Brand** (right screen, the portal). The Brand sets up a campaign, bids for a slot, and publishes a building; the Player walks round the corner and into it seconds later, shops in a store, and then watches the building get updated underneath them without losing their progress. Every crucial promise in the patent figures gets its own moment, in a watered-down, play-money form. The game build starts in the morning and never restarts.

**Plain-words glossary**

| Word | Meaning here |
|---|---|
| Slot | A fixed spot in the street where a building can be swapped in at runtime |
| Pack | The downloadable content package for one building (a pak / container set) |
| House campaign | A built-in campaign that always holds a slot, so there is always something to outbid and something to fall back to |
| Window | A time slice for the auction. 2 minutes in attract mode |
| Status strip | Small always-on strip on the left screen showing what the slot is doing right now |
| X-ray view | Optional overlay: pre-fetch ring on the ground, the manifest, the cache list |

---

## 2. The fixed kit and the booth

Planned **only** around what is guaranteed: **1 PC, 2 monitors, 2 controllers.** No tablet, no second PC, no router, no venue network. A keyboard and mouse stay hidden under the table as emergency backup; visitors never touch them.

| | Player seat (left) | Brand seat (right) |
|---|---|---|
| Screen | Left monitor: the game, full screen | Right monitor: brand portal, live stats, Player B window |
| Input | Controller 1: walk, enter, try on, buy | Controller 2: pick, bid, publish, push update |
| Who | A visitor | A second visitor, or a staffer, or the same visitor swapping pads |

Everything runs on the one PC: the game, a small second copy of the game (Player B), the brand screen (a web page), the local server + storage (the stand-in cloud), the pad helper, and a start script with a watchdog. The only other device involved is the visitor's own phone for a QR code, on its own mobile data.

---

## 3. The world

One street, three slots, one packaged build.

- **Corner slot** — where the visitor's building lands. House campaign: the ramen shop.
- **Plaza slot** — always holds the clothing store (a house campaign, delivered the same dynamic way as everything else), so the shopping act is always available.
- **Lane slot** — small. Holds small stalls. Used for Player B's comparison and for the "too tall" rejection.

Empty or failed slots show a placeholder: a construction hoarding reading "Coming soon".

A strip on the left screen shows, all day: **build number · uptime · restarts: 0 · loading screens: 0.**

---

## 4. The flow — full tour, about 5 minutes

| Act | Brand seat (pad 2, right screen) | Player seat (pad 1, left screen) | Patent promise shown |
|---|---|---|---|
| **0. Attract** (idle) | House campaigns re-auction every 2-minute window; allocation grid updates | Buildings swap on the empty street; "pick up a controller" prompt | Time-window allocation, live refresh, immediate swap |
| **1. Arrive** 0:00 | Player B window: same street, different profile, low-spec → different stall in the Lane slot, lite pack | Picks 1 of 3 profile cards. One is a returning player who spawns already wearing a jacket bought "last session" | Context-driven variation, device-aware variants, entitlement across sessions |
| **2. Be the brand** 0:30 | My content → building → slot, audience, bid, budget → submit. Checklist: package ✓ fits slot ✓ rating ✓ signed ✓. Auction card: your score vs the house. Allocation grid updates | Free roam | Portal, the validate → moderate → sign gate, auction, allocation |
| **3. It appears** 1:30 | Impressions, dwell and spend tick live | Crosses the pre-fetch ring; strip ticks resolving → downloading → verifying → mounting; building materialises; walks in and uses its interaction | Full runtime sequence, no loading screen, telemetry |
| **4. Shop** 2:30 | Changes a price; watches the funnel (seen → tried → bought); quality score nudges up | Try-on (walk out and it's gone). Buy in the simulated platform store with credits → receipt → redeem → item permanent. Physical item → order ref + QR | The whole commerce figure; performance feeds quality |
| **5. The swap** 3:45 | Presses "push Season 2 update" on their own building | Is inside, mid-interaction (say 3 of 5 tokens). Strip: swap pending. Walks out → swap. Walks back in → 3 of 5 still there, jacket still on | Post-deployment replacement, deferred swap, state preservation |
| **6. Budget out** 4:45 | Credits hit zero → the house wins the slot back. Summary card of the campaign | Watches the building hand back | Spend accounting, budget, the full loop |

Then automatic reset back to Act 0.

### Act notes

**Act 0 — Attract.** Runs whenever both pads are idle for 60 s. Each window the server re-runs the auction among house campaigns with different budgets, so winners change and buildings swap. This is the allocation schedule doing its job, not just a timer.

**Act 1 — Arrive.** Profile cards: *Gamer (new)*, *Music fan (new)*, *Film buff (returning — owns the jacket)*. The game asks the server for the player's entitlements at session start; the returning card has one pre-seeded, which is how "persists across sessions" is shown without restarting anything. Player B always gets a different profile from the one the player picked and reports itself as low-spec. Players appear everywhere only as a pseudonymous ID (e.g. Player #A41F).

**Act 2 — Be the brand.** Everything on the pad. "Signed in as Demo Brand". The default bid always beats the house, so the normal path never disappoints. A curious visitor can lowball and see "outbid — slot stays with the ramen shop", and nothing changes in the world. Two library items are built to fail so rejection-with-reason is always showable: a tower that is **too tall** for the Corner slot ("try the Plaza slot"), and an **18+ trailer** building aimed at an all-ages slot.

**Act 3 — It appears.** The X-ray view shows the pre-fetch ring, the real manifest fields (pack ID, version, hash, URL, class path) and the cache list. Publishing the same building again in the same visit is instant and the strip says **cache hit**. A short "materialise" effect on the placeholder hides the spawn frame.

**Act 4 — Shop.** Play money only: "demo credits", no currency symbols, no card fields, nothing typed. The player starts with 1,000 credits. The pop-up is clearly labelled **simulated platform store**. No payment data ever enters the game or a pack — the game only carries a receipt token from the simulated store to the server.

**Act 5 — The swap.** This is the patent's strongest idea and the headline act. Each publishable building has a Season 2 version (a re-skin) and one interaction with saveable progress. The new version is queued while the player is inside, swaps only when they leave, and their progress is restored into the new version.

**Act 6 — Budget out.** Spend accrues at a fixed rate per second the building is in view, tuned so 1,000 credits lasts roughly 3 minutes of viewing. Running out triggers an immediate re-auction of that slot. The Brand can also press "end campaign"; staff can force it. If the player is inside at that moment, the deferred swap handles it gracefully.

### Express version (90 seconds, for crowds)
Act 2 on defaults (three button presses), then Act 3.

### Staff tricks (for "what if it fails?")
- **Corrupt pack:** a button combo makes the server send one corrupted pack → hash mismatch → placeholder stays → retry with backoff → success.
- **Frozen download:** a second combo pauses the server mid-download for a few seconds → the download resumes from where it stopped rather than starting over.

---

## 5. Patent coverage map

| Figure | Covered? | Where in the flow |
|---|---|---|
| Detailed system architecture | Yes | Every client module runs for real; backend is the local server or AWS |
| Runtime sequence | Yes, all 22 steps | Act 3; cache-hit branch on a re-publish |
| Slot lifecycle state machine | Yes, every state | Normal path in Act 3; swap pending + unload & preserve in Act 5; immediate swap in Acts 0 and 6; error / fallback in the staff tricks |
| Commerce & entitlement | Yes, step by step | Act 4; "across sessions" in Act 1 |
| Advertiser portal & bid-to-slot | Yes, basic | Act 2; windows in Act 0; spend and reporting in Acts 3–6 |
| Context-aware resolution engine | Simplest policy only | Acts 1–2 and the "why this building?" panel. Learned and adaptive policies stay on a poster — they do not exist yet |

The demo also settles the one disagreement between the bid-pipeline and context-engine figures: **the auction decides per slot per audience at publish time and at each window; resolve just looks the answer up.**

---

## 6. Where it is watered down

Say these out loud at the booth. Honesty helps.

| Real thing | Demo version |
|---|---|
| Brand uploads and cooks content | "Upload" = pick from a library of pre-cooked packs |
| Human moderation + policy review | Four automatic rule checks; two items built to fail |
| Live auction among many bidders | One fixed formula, numbers on screen, house campaigns as rivals, default bid always wins |
| Context engine with learned policies | Three visible signals (profile, device tier, day/night toggle) + developer rules as hard gates + a "why this building?" panel. Decisions cached for 30 s |
| Platform store + real payment | Simulated store, demo credits, signed demo receipt |
| Fulfilment | A fake brand shop returns a reference; QR opens a static mock page with no forms |
| Accounts, privacy | "Signed in as Demo Brand"; players are pseudonymous IDs; brands see totals only |
| HTTPS + CDN | Local mode: plain HTTP on the same PC, real presigned links from the local storage. AWS mode: genuine HTTPS + S3 presigned URLs |
| Multiplayer | Not shown |

---

## 7. How the pieces work (starting values — tune in testing)

### The local server (the stand-in cloud)
One small program plus S3-compatible storage (MinIO) on the same PC. The game talks to it exactly as it would talk to the real backend.

| Call | Purpose |
|---|---|
| `GET /resolve` | Slot + context in → signed manifest out (pack ID, version, hash, URL, class path) |
| `GET /changes` | Game polls every 1–2 s to learn a slot's allocation changed |
| `POST /publish` | Brand submits a campaign: building, slot, audience, bid, budget → ingest checks → auction |
| `GET /catalog` | Store asks for items, prices, variants |
| `POST /redeem` | Receipt + SKU + player ID → verify → record entitlement → grant |
| `GET /entitlements` | Game asks at session start what the player already owns |
| `POST /telemetry` | Impressions, dwell, interactions, try-on, conversion |
| `POST /admin/reset`, `/admin/sabotage` | Booth housekeeping and the staff tricks |

Pack downloads are paced in local mode so they take 3–5 seconds. Still a real HTTP download and a real hash check.

### Bidding rules
- Score = **bid × quality × relevance.** All three shown on screen.
- Brand budget: 1,000 credits. Corner house campaign holds at 300. Default bid: 450.
- Quality: fixed per building (about 0.8–1.2). Nudges up +0.01 per try-on and +0.05 per purchase, capped at 1.5, reset per visitor.
- Relevance: 1.0 when the audience matches the player's profile, 0.5 when it doesn't. Night-only campaigns get ×1.5 at night.
- Ingest checks, in order: package (exists, size, engine version tag) → fits the slot (bounds) → content rating vs the slot's rule → sign (hash + signature with a demo key). Only content that passes becomes biddable.

### Context rules
- Signals: player profile (user), device tier (system), day/night toggle (external), developer rules (hard gates such as "Plaza: all-ages only", "Corner: max height").
- Lane slot stalls: game kiosk (matches gamer), record stall (matches music), night-market stall (night). A film-buff player matches neither, so the highest bid × quality wins — visible in the "why this building?" panel.
- Low-spec clients are given the lite variant of a pack.
- Decision cache: 30 s per slot × context. A publish clears it.

### Commerce rules
Catalog comes from the server → try-on is local and temporary → buy opens the simulated store → the store returns a signed receipt → game posts it to `/redeem` → server verifies and records a durable entitlement → digital item applied permanently; physical item "forwarded" to a fake brand shop that returns a reference, shown with a QR.

### Swap and saved progress
Progress is a small record keyed by slot + building + schema version. Saved on unload, restored on spawn. Season 1 and Season 2 of a building share the schema. If schemas ever differ: migrate or discard, never crash.

### Telemetry definitions
- Impression: building on screen, within 30 m, at least 1 s, not blocked (simple line check).
- Dwell: seconds inside the slot's bounds.
- Interaction: each use of the building's interaction.

### Reset
Triggered by 60 s idle or a 3-second staff combo on pad 2. Wipes: the visitor's campaign, new-player entitlements, quality nudges, counters, saved progress, decision cache, and the visitor-publishable packs from the local cache (so every visitor sees a real download; house packs stay cached).

---

## 8. What gets built (all FUTURE)

1. **Game** — 3 slots, status strip + uptime stamp, X-ray view, per-building saved progress, swap path, attract mode, resets, entitlement fetch at start.
2. **Player B view** — second copy of the same build: fixed camera, other profile, low-spec flag, no input, no audio.
3. **Brand screen** — My content, campaign setup, checklist, auction card, allocation grid, live funnel and spend, "why this building?", price editor, push-update button, end-campaign button, summary card. Every string in JP and EN.
4. **Server** — everything in section 7. One codebase, runs local or on AWS.
5. **Booth plumbing** — pad helper, start script, watchdog.
6. **Content** — see section 10.

---

## 9. Technical calls already made

- **The game keeps window focus all day.** The brand screen is driven through the pad helper, not by clicking, so nobody clicks outside the game.
- **Insurance anyway:** borderless windowed (never exclusive fullscreen), no frame-rate throttle and no audio mute when unfocused — so an emergency mouse click on the right screen is survivable.
- **Controllers wired by USB, never Bluetooth.** At startup: "press ✕ on the player pad" → the game locks to that pad, the helper takes the other.
- **Pad helper** reads pad 2 with background input enabled and relays to the brand screen over localhost. This path never goes through the cloud.
- **Player B budget:** 30 fps cap, half resolution, lowest settings, below-normal process priority, its own pack cache folder. Main game at high priority.
- **Player B pass/fail:** the main game must hold its frame rate with B alive through a soak run. If not, drop B and do Act 1 as a live flip: the Brand presses "switch player profile" and the Lane stall swaps in front of the player.
- **One-button start:** storage → server → brand screen on the right monitor → game on the left → Player B, in order, with health checks; a watchdog restarts anything that dies.
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
| Publishable buildings | 4 × 2 versions | Game lounge, music venue, film pop-up, arcade. Season 2 = re-skin. Each has one interaction with saveable progress |
| Clothing store | 1 | Plaza house campaign, commerce-enabled |
| Ramen shop | 1 | Corner house campaign |
| Lane stalls | 3 | Game kiosk, record stall, night-market stall. Small |
| Lite variants | 1–2, optional | For the low-spec Player B |
| Built-to-fail items | 2 | Too-tall tower, 18+ trailer. Thumbnail + manifest only; never cooked |

Brands: the company's own family of brands plus playful generic ones. No third-party trademarks.

**Minimum set if art time gets tight:** 2 publishable × 2 versions, the store, the ramen shop, 2 stalls.

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

- The game and brand screen read one setting: the backend address. Switch only at reset, never mid-visitor.
- The start script health-checks the cloud and falls back to local if there's no answer.
- Use AWS mode for the viability demo at the office and for "now it's coming from the Tokyo region" moments when the venue link is good. Internet is **not** on the guaranteed list, so the booth must never depend on it.
- Tokyo region for the expo, Mumbai for office testing. Publish endpoint protected with a key; bucket private.

---

## 12. Order of work, each with an exit test

1. **Publish → appear.** Server, storage, polling, status strip, day-1 checks. *Exit: publish and the building appears, ten times out of ten.*
2. **Bidding + checklist + allocation + Player B.** *Exit: a pair of strangers completes Acts 1–3 unaided. This is the minimum viability demo — record a clean capture that day; it is the submission video and the permanent fallback.*
3. **Commerce end to end.** *Exit: try-on → buy → receipt → entitlement → item persists; physical branch shows a reference and QR.*
4. **Swap with saved progress, budget-out, attract windows.** *Exit: Act 5 works ten times out of ten, including when the budget runs out while the player is inside.*
5. **Hardening, then feature freeze.** Three overnight soak runs: a scripted bot cycles publish / mount / swap / unmount 500+ times while logging memory and frame time — pass = flat memory, no stutter. Failure drills: kill the server mid-download, serve a corrupt pack, unplug a pad. The visitor must only ever see the placeholder, never an error. Staff cue cards (JP/EN), pack list.

Step 5 is not optional however fast the code gets written. Fast-written code is exactly what a soak test is for.

---

## 13. When something breaks on the floor

| What breaks | What happens |
|---|---|
| Download or verify fails | Placeholder stays, quiet retry with backoff. No error shown |
| A program crashes | Watchdog restarts it; booth drops into attract mode |
| A pad dies (there is no spare) | Staffer drives the brand screen with the hidden mouse; the game is set up to survive that |
| Cloud unreachable (AWS mode) | Start script falls back to local mode |
| The PC dies | USB folder onto any borrowed PC (about 15 minutes); backup video covers the gap |

---

## 14. Deliberately not shown

Real money or real payment of any kind · a real platform store · human moderation · live uploads or live cooking · learned or adaptive scoring · multiplayer · brand logins. Anything money-like is labelled "simulated".

---

## 15. Open items

- 🔴 **ACT — patent timing.** Act 5 (replacement + state preservation) is now the headline act and is exactly what the spec was flagged as not describing. It needs to be in the spec before filing, and the filing needs to land before any public showing. Ask the patent team to confirm both, and that what is on the booth is covered. Not legal advice; it is the one item here that cannot be fixed afterwards.
- 🔴 **ACT — AWS account.** If AWS mode is wanted, use a company-approved account only, never a personal one. The approval may take longer than the code.
- 🔴 **DECIDE — dates.** The viability-review date and the Tokyo date are still unknown. They turn section 12 into a calendar.
- 🟡 **Content is the long pole, not code.** Art and cooking time do not shrink with coding agents. Kitbash and re-skin; fall back to the minimum set if needed.
- 🟡 **PC strength is unknown.** The Player B pass/fail test answers it; the live-flip fallback needs no extra work.
- 🟡 **Single points of failure:** one PC, no spare pad. Mitigations are in section 13.

**Next artifact (FUTURE):** the build spec for the coding agents — endpoints with data shapes, the rule tables, and one acceptance test per act.

---

*If this document and a patent figure disagree about how the real system works, the figure wins. This document describes the demo, which is a deliberately simplified version of it.*
