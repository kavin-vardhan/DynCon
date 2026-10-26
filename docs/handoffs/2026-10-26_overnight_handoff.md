# Overnight handoff — 2026-10-25 → 26 (Tokyo demo build, night 1)

*Cold-reader handoff by chat Claude (Cowork, DynamicContents Project) for Kavin and the next chat session. Everything lives in
`E:\DynamicContents`, now a local git repo — `git log --oneline` shows every step. Specs are in `specs/`, every call chat made is
in `specs/DECISIONS.md`.*

## In one paragraph

Kavin set up a chat ↔ Code mailbox for this project, started its watcher, and asked chat to start the Tokyo demo build
overnight — art first, in Blender — making the calls itself. By morning **all 13 walk-in buildings exist** (the default
placeholder, Content 1–4 in two versions each, three rivals, a small rival). Blender scripts generate them, they pass
validation, and **every one is now a real Unreal 5.7 content pack**. A packaged game that ships with no content in it mounts
each pack from disk while running and spawns it at a slot: about 15 ms to mount, 3–5 ms to load and under 1 ms to spawn, with
the brand colour and emblem on the sign. That was the riskiest unknown in the whole demo, and it works. The **demo server's delivery path** is built too: Python +
FastAPI, 102 tests passing. A fake game client passes plan §14 step 1 on the server side, 10 out of 10. That run includes a
real cooked pack, a version-2 push and a deliberately corrupted download, which falls back to the default and then retries
cleanly. **Server part 2 is done too.** It covers auctions with the scripted rival, soft close, credits, the portal API and the report.
143 tests pass, and plan §14 step 4 passes 35 out of 35 on the server side. A scripted visitor creates a brand, uploads,
bids, gets outbid, raises, wins, and sees their content mount for Japan while India keeps its rival. It then pushes version
2, reads the report, wins all three regions of A1 inside the 2,000 credits, and loses a lowball bid to the rival.

## Status board

| Item | Status | Where |
|---|---|---|
| Mailbox `E:\DynamicContents\_mailbox` (Code on Opus 5, xhigh) | DONE | `_mailbox/README.md`; dashboard column "DynamicContents" |
| Local git repo (no remote) | DONE | `git log` |
| Specs v1: content assets, server, portal, Unreal | DONE | `specs/` |
| Decisions log | DONE, living | `specs/DECISIONS.md` |
| Blender art pipeline + all 13 builds | DONE | `art/` — look at `art/previews/contact_ext.png` and `swap_pairs.png` |
| Runtime pack mount on UE 5.7 (spike) | DONE — works | `unreal/README.md` |
| All 13 packs, true cm, sign / door / light fixes | DONE | `unreal/_packs/`, **`unreal/spike/shots/engine_contact.png`** |
| Demo server part 1 (delivery path + fake game client) | DONE — 102 tests, exit test 10/10 | `server/README.md` |
| Demo server part 2 (auctions, portal API, report) | DONE — 143 tests, stage-4 exit test 35/35 | `server/README.md` |
| UE runtime plugin (polling, slot lifecycle, state kept, UI) | FUTURE | `specs/unreal_spec_v1.md` §3 |
| Game A / Game B maps + slot-map tool | FUTURE | `specs/unreal_spec_v1.md` §4–5 |
| Portal | FUTURE | `specs/portal_spec_v1.md` |
| Pad helper, start script, watchdog | FUTURE | plan v6 §11 |
| Hardening + soak runs | FUTURE | plan v6 §14 step 7 |

## 🔴 Needs Kavin

1. **Install MSVC 14.44** — Visual Studio Installer → Modify → Individual components → "MSVC v143 – VS 2022 C++ x64/x86 build
   tools (v14.44-17.14)". This PC's compiler (14.38) cannot link a Development game exe against UE 5.7.4, so tonight's builds
   are Shipping. Shipping works fine, but Development gives proper engine logs, and the install lets four workarounds go.
2. **Delete `E:\DynamicContents\_to_delete\`** when you're happy. It holds the template's Combat / SideScrolling variants,
   which the demo will never use.
3. Nothing else is blocking. Have a look at the two pictures named above when you have a minute. They are the night's work at
   a glance.

## The briefs, in order

| # | What | Result |
|---|---|---|
| 001 | Git repo + environment check | GREEN — Python 3.13, Node 18, no draw.io, Blender + UE found later |
| 002 | Blender pipeline + first 4 builds | GREEN — Blender 5.2.2 (Steam), EEVEE headless |
| 003 / 003R | Quality pass + Content 1 v2, 2, 3 | GREEN after a resume. Code ended 003 with a job still running in the background, which a headless run can't do. Rule added to `CLAUDE.md` |
| 004 | UE pack round-trip spike | NEEDS-DECISION → ruled. Mount works; Shipping only until MSVC 14.44 |
| 005 | Four rivals + polish | GREEN — tinted interiors, brand panel inside, twist on Content 3 v2 |
| 006 | All 13 packs, true centimetres, fixes | NEEDS-DECISION → ruled. Sign / door bug was socket rotation; a GPU hang was fixed with Lumen Detail Tracing |
| 007 | Server part 1 | NEEDS-DECISION → ruled. 102 tests, stage-1 exit test 10/10. Rulings: the portal's "Your computer" list = Content 1–4 v1 + one bad file; signed-payload envelope for the UE client |
| 008 | Server part 2 — auctions, portal API, report | NEEDS-DECISION → ruled. Real packs stay on the upload list; cost per view divides by simulated + live views |
| 009 | Small: apply the 008 rulings, commit this handoff | running at handoff time (no game windows) |

## What chat decided (overturn anything)

Full list with reasons: `specs/DECISIONS.md`. The big ones:

- **Art is generated by script**, not modelled by hand or downloaded. That keeps it licence-clean and lets us rebuild any time.
- **Size classes:** S 7×7×5 m, L 14×14×9 m, T 14×14×20 m (A1 / B1 = L, A2 = T, A3 / B2 = S).
- **Brand colour and emblem are runtime inputs**, never baked in. The same building can be "yours" or a rival's.
- **A pack = one cook chunk = `.pak` + `.utoc` + `.ucas`.** Chunk ids are frozen at 100–112.
- **Server:** Python 3.13 + FastAPI, timestamp-driven so it can move to Lambda later, no MinIO (it serves packs itself through
  signed links), RS256-signed manifests.
- **Shipping builds** until MSVC 14.44 is installed. Lumen stays on with Detail Tracing.

## Next briefs (chat's plan, in order)

1. UE runtime plugin, stage 1: poll `/changes`, resolve, download, verify, mount, and the slot lifecycle with the default
   placeholder fallback. Exit test (plan §14 step 1): a hand-written allocation makes the content appear in the running game,
   ten times out of ten.
2. Maps for Game A / Game B, built from a Blender environment kit in the same style, plus the slot-map tool.
3. The portal (pad-driven, JP + EN), then the pad helper and start script.

**Heads-up for daytime:** the UE briefs package and *run* the game to test it, so game windows open and close on the desktop
for a few minutes at a time. Chat holds the next UE brief until Kavin says the PC is free.
