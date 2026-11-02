# Pause handoff, 2026-11-02 (Tokyo demo build paused after brief 018)

*Cold-reader handoff by chat Claude (Cowork, DynamicContents Project) for Kavin and the next chat session. Everything lives in
`E:\DynamicContents`, a git repo pushed to the private remote `kavin-vardhan/DynCon`. `git log --oneline` shows every step, and
the commit messages hold Code's reports. Specs are in `specs/`, and every call chat made is in `specs/DECISIONS.md`. The previous
handoff is `docs/handoffs/2026-10-26_overnight_handoff.md`.*

**Kavin paused development on 2026-11-02, after brief 018. Nothing is queued in the mailbox, and the watcher can stay closed
until he says to resume.**

**Later the same day Kavin ruled: English only, no Japanese anywhere in the demo, because it's too risky.** He asked for one
brief to make that change, so **018E (English only)** went out. It carries 018's ACK-VERDICT line (below) and commits this
handoff. Its report and its commit message hold the result. After it, development stays paused.

## In one paragraph

The booth demo runs end to end on Kavin's home PC: one packaged UE 5.7 Shipping build with two maps, the local server, the
pad-driven portal, the pad helper and the region preview window. A visitor can go through the whole plan v6 flow:

- create a brand, upload content (one file is built to fail), pick a game and a slot
- bid per region against a scripted rival, win, and watch the content go live in the game by itself, with no loading screen
- check another region in the preview window, read the report, and push version 2 while the Player is inside (the swap waits
  for them to walk out and keeps the lights / door / screen as they left them)
- let the block end

Brief 018 added the booth's front end: an attract loop, a title menu, a pause menu with game switching, and an **X-ray view**. The
X-ray shows the pre-fetch rings, the signed manifest, the pack cache, the lifecycle log with timings, and a live frame-time
graph. It is our visual answer to the experts who will say "this is just ChunkDownloader". What is left is booth plumbing
(one-button start, watchdog, pad lock), the content sandbox, and hardening (overnight soaks, failure drills).

## Status board

| Item | Status | Brief(s) |
|---|---|---|
| Mailbox `E:\DynamicContents\_mailbox` (Code on Opus 5, xhigh) | DONE | — |
| Blender art pipeline, 13 walk-in buildings, all cooked as UE packs (chunks 100–112, frozen) | DONE | 002–006 |
| Server: delivery, signed manifests, auctions, rival script, portal API, report, preview endpoints | DONE: 212 tests | 007–009, 011–018 |
| Private GitHub remote (Code commits and pushes every brief after a privacy check) | DONE | 010 |
| UE runtime plugin: poll → resolve → download → verify (RS256) → mount, slot lifecycle, fallback | DONE: 10/10 | 011 |
| Game A + Game B maps, Player, five slots | DONE | 012 |
| Slot-map tool (editor menu, commandlet, Python) and both games registered | DONE | 013 |
| Portal (every screen, pad-driven) + pad helper | DONE | 014–015 |
| English only: every Japanese string, the JP font and `label_jp` removed (Kavin's ruling, 2026-11-02) | in flight at handoff time | 018E |
| Interactables, state kept across a swap, push update in game, waypoint marker | DONE: 10/10 | 016 |
| Region preview window + live-flip fallback | DONE | 017 |
| Lighting cost fix, title / pause menu, game switching, attract camera, X-ray view | DONE | 018 |
| **019** Booth plumbing: one-button start, watchdog, pad lock, kiosk, focus | QUEUED (first on resume) | — |
| **020** Content sandbox + hitch-free swap proof + X-ray tidy pass | QUEUED | — |
| **021** Hardening: overnight soaks, failure drills, cue cards, portable USB copy | QUEUED | — |
| Judges' proof of concept: Builder + Publish button → DLC-style pak → portal → game | FUTURE | — |
| AWS mode (Lambda + S3, Tokyo region) | FUTURE: needs a company-approved account | — |
| Preview follows a bid into the *other* game | FUTURE: reason in 018's report | — |

## Numbers on this PC (brief 018, 2 × 10 min scripted tour, 1600 × 900)

| | average | worst 1 % |
|---|---|---|
| Game alone | 16.00 ms | 22.72 ms |
| Game with the preview window alive | — | 27.69 ms (plan §11's line is 25 ms) |

- Brief 016's wall lamps cost only 0.5 ms. The real cost was Lumen re-lighting its surface cache for every lamp that adds
  indirect light, so group-B lamps now have `IndirectLightingIntensity = 0`. The before / after pictures look the same.
- Run-to-run drift on this PC is about ±1 ms over ten minutes.
- This PC fails the preview line even running solo in some runs, so **the booth PC decides** between the preview window and the
  live flip. Both are built.

## Chat's rulings on 018's NEEDS-DECISION (sent on brief 018E)

The watcher holds any brief that lacks an `# ACK-VERDICT:` line after a NEEDS-DECISION or RED report. This line went out on
018E. Brief 019 needs its own ACK-VERDICT line only if 018E itself ends NEEDS-DECISION or RED.

```
# ACK-VERDICT: 018 rulings by chat - (1) accept 16 ms solo, no change to the look; (2) same as 017: both stay, the preview window is the default if the booth PC passes plan §11's line, the live flip otherwise - the booth-PC measurement is a 021 item; (3) the stretch (preview follows a focus into the other game) stays FUTURE; (4) the foreground finding goes into 019's start script; (5) attract stays on one map, no alternation - agreed with Code's reason
```

## How to resume

1. Kavin double-clicks `E:\DynamicContents\_mailbox\start_watcher.bat`.
2. Chat reads 018E's report (`_mailbox/to_chat/018E-english-only.report.md`). Then chat writes brief 019 with
   `# EFFORT: xhigh` and `# SESSION: new-default` unless 018E's session is well under 70 % context. It gets an ACK-VERDICT line
   only if 018E asked for one.
3. Chat arms the signal Monitor on `https://raw.githubusercontent.com/mrtocsik/mailbox-signal/main/signal.json`, key
   `f500e3c7`. It fires when the count goes **above the current count**: 21 once 018E has reported. The script uses `-gt`
   because the GitHub raw cache can serve a stale value.
4. 018E commits this handoff and chat's two new lines in `specs/DECISIONS.md`.

## Next briefs (chat's plan; scope for whoever writes them)

**019: booth plumbing (plan v6 §10 item 6, §11)**

- **One command starts everything, in this order:**
  1. server, plus a health check
  2. Edge kiosk on the right monitor: `msedge --kiosk "http://127.0.0.1:8700/portal/" --edge-kiosk-type=fullscreen`
  3. pad helper
  4. preview copy, hidden, with its own `-UserDir=`
  5. main game on the left monitor, **last**
- **Ends with the game in the foreground.** 018 found that Windows will not hand the foreground to a process started unattended
  (Edge or a console kept it). The script has to make it reliable and test it, or pad 1 goes wherever focus is.
- **Startup "press ✕ on the player pad" lock:** the game locks to that pad and the helper takes the other.
- **Watchdog:** restarts anything that dies. A restarted game comes back in attract, and the strip's restart counter stays honest.
- **Staff full reset:** everything returns to attract. A portal idle reset never kicks a Player who is still playing.
- **Monitor layout from a config file**, relative paths only (plan §11: the demo is one portable folder), and a stop script.
- **Small fix:** the waypoint marker can land on an X-ray panel.
- **Exit test:** cold start with one command; kill each process in turn and it comes back; focus check; the portal tour still
  passes.

**020: content sandbox + hitch-free swap proof (the answer to "it's just ChunkDownloader")**

- **Sandbox:** a class allowlist and mount isolation, checked in three places:
  - at upload (the server rejects with a reason)
  - before serving
  - before mount (the game refuses a tampered pack and the default content stays)
- **Staff trick:** "malicious pack refused".
- **Hitch-free proof:** frame time around every mount / spawn / unload over N swaps, a table, and visible on the X-ray graph.
- **X-ray tidy pass** (chat looked at 018's contact sheets): the panels cover a lot of the screen, and the pre-fetch rings are
  thin lines that don't read at a glance. Make the panels more compact and the rings bolder.

**021: hardening (plan v6 §14 step 7, not optional)**

- Three overnight soak runs: a bot cycles bid / win / mount / update / expire 500+ times; memory and frame time must stay flat.
- Failure drills: kill the server mid-download, serve a corrupt pack, unplug a pad. The visitor only ever sees default content.
- Booth-PC frame-time test (preview window or live flip).
- Staff cue cards (English), the pack list, a portable USB copy, and a clean backup video capture.

**Later:** the judges' proof of concept (spike a DLC-style cook against the shipped release → Publish button in the editor →
Builder panel → rehearsal; publish to visible takes about 1–3 min because of the cook), then AWS mode.

## 🔴 Needs Kavin (none of these block a resume)

1. **Controllers:** plug both in and run `py -3 booth\pad_helper.py --list`. Then start the game and press everything on pad 2;
   nothing in the game should react.
2. **On the two-monitor booth PC:** check that the preview window opens on the portal's monitor, not the game's.
3. **Walk both maps by hand.** Any button leaves the attract loop, Start opens the pause menu (switch game, X-ray), and
   View / Back toggles the X-ray.
4. Optional: install MSVC 14.44 (Visual Studio Installer → Individual components → "MSVC v143 – VS 2022 C++ x64/x86 build tools
   (v14.44-17.14)"). Shipping builds work fine without it; it only buys Development builds with fuller logs.
5. Delete `E:\DynamicContents\_to_delete\` when you're happy.

**Open questions for Kavin:**

- When do the judges see the proof of concept, and is it before Tokyo?
- The Tokyo date.
- Which thumbnail went into the Oct 30 submission. Chat delivered options A–D on 2026-10-27 and doesn't know which was used.

## Pictures worth a look

- `unreal/spike/shots/018/menu_contact.png`: the booth front end in one run (attract → title menu → pause + X-ray → loading
  line → back in A1 exactly as left → attract).
- `unreal/spike/shots/018/xray_contact.png`: the X-ray view at 1080p over one lap.
- `unreal/spike/shots/018/lighting_before_after.png`: the lighting fix, which looks the same as before.
- `booth/_shots/017/`: the region preview window's exit test.

## Briefs 009–018 (001–008 are in the previous handoff)

| # | What | Result |
|---|---|---|
| 009 | Server rulings + housekeeping | GREEN |
| 010 | Push to the private GitHub remote | GREEN |
| 011 / 011R | UE runtime stage 1: game ↔ server | 011 never ran (Code's login had expired); 011R GREEN, 10/10 |
| 012 | Game A + B maps, Player, slots | GREEN |
| 013 | Slot-map tool + register endpoint | NEEDS-DECISION → ruled (slot pads get their own tone; capture lighting accepted) |
| 014 | Portal part 1 + pad helper | NEEDS-DECISION → ruled (type sizes: 24 px floor for anything a visitor must read) |
| 015 | Portal part 2: auction to summary | GREEN, full tour automated |
| 016 | Interactables, state kept across a swap, push update | GREEN, 10/10 (3 with the block ending while inside) |
| 017 | Region preview window | NEEDS-DECISION → ruled (both kept; cut the lighting cost) |
| 018 | Lighting, title / pause menu, attract, X-ray | NEEDS-DECISION → ruled above, ruling sent on 018E |
| 018E | English only: Japanese removed everywhere (Kavin's ruling) | in flight at handoff time |

Running cost (API-equivalent, not billed on Max): $1,161.54 across all briefs.
