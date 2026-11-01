# DynamicContents — CLAUDE.md (read this first, every brief)

## What this folder is

The home-PC working folder for **DynamicContents** (internal term **LBDR** — Logically-Bounded Dynamically-Replaceable regions):
runtime in-game dynamic content for Unreal. A shipped map has fixed **dynamic slots**; when a player nears one, a client plugin asks a
backend what belongs there, downloads a signed, versioned pak, verifies it, mounts it at runtime and spawns it at the slot — no restart,
no loading screen, no client patch. Brands upload content and bid for slots through a web portal. It began as a hackathon project at
Kavin's employer and is now in patent filing.

Two workstreams:
1. **Patent figure set** — the six figures in `diagrams/` (invention-disclosure drawings, not an engineering design doc).
2. **Tokyo booth demo** — plan in `DemoPlan/DynamicContents_Tokyo_demo_plan_v6.md` (current; v3 and v4 are superseded history).

Start with `README.md` (cold-reader overview of the system + Claude's read), then the v6 demo plan.

## Folder map

| Path | What |
|---|---|
| `README.md` | System overview, cold-reader handoff (2026-09-09) |
| `DemoPlan/` | Demo plans v3 / v4 / v6 + `build_demo_flow*.py` |
| `diagrams/` | The six patent figures (PNG); `diagrams/demo/` = demo-flow diagrams (.drawio / .svg / .png) + `make_demo_flow.py` |
| `DynamicContents_DemoFlow_overview.png` | Non-technical demo-flow picture made for management sign-off |
| `output/pdf/` | Rendered demo-flow PDFs / PNGs / SVG |
| `specs/` | Build specs chat writes for you (start with `specs/content_assets_spec_v1.md`) + `DECISIONS.md`, the log of calls chat made |
| `art/` | Generated content art: Blender scripts, .blend, FBX / GLB exports, manifests, previews (see the asset spec) |
| `server/` | The demo server (stand-in cloud): FastAPI, tests, tools, registered maps — see `server/README.md` |
| `unreal/` | UE 5.7 project `DCDemo` + the `DynamicContents` plugin (runtime + editor), tools, packs — see `unreal/README.md` |
| `portal/` | The brand portal (static web app served by the server at `/portal/`) — see `portal/README.md` |
| `booth/` | Booth plumbing: pad helper, exit tests, start scripts — see `booth/README.md` |
| `docs/handoffs/` | Cold-reader handoffs written by chat at the end of each session |
| `_mailbox/` | The chat ↔ Code bridge. **Never read or write it.** |

## Current position (2026-11-02)

- Built so far (briefs 002–018): all 13 content pieces + the environment kit (Blender), every piece as a runtime pack, the
  server (delivery, auctions, report, game registration), the UE runtime client (game ↔ server, slot lifecycle), Game A and
  Game B maps with a Player, the slot-map tool, the whole portal + the pad helper, interaction with state kept across a
  swap, the region preview window, and — brief 018 — the lighting budget, the title menu and game switching, the attract
  camera and the X-ray view. Shipping builds only (MSVC 14.44 missing).
- Still FUTURE: the "press ✕ on the player pad" lock, the one-button start script and the watchdog (plan v6 §10 item 6).
- Unreal is the launcher install at `E:\EpicGames\UE_5.7` (read-only).
- Who does what: **Kavin** is the owner — he rules on product/scope and does playtests and human errands. **Chat Claude** makes the
  design/technical calls and writes your briefs. **You (Claude Code)** implement. You never talk to Kavin directly; chat does.

## Standing rules for this project

1. **Confidentiality.** Work only from what is in this folder. Never ask for, fetch or reconstruct office material — patent
   spec or claims text, docket details, the team's code or builds, office logs or data. If a task truly needs any of it, stop and
   raise it as NEEDS-KAVIN.
2. **No real names.** Do not write the employer's name, docket numbers, or real product / studio names into anything here.
3. **The demo is name-agnostic.** No game titles, no building / brand / shop names, real or invented: Game A / Game B, slots A1–A3 and
   B1–B2, Content 1–4, "the rival". A brand is a colour plus a simple emblem. In anything meant for management, regions are
   "Mock region 1" / "Mock region 2", and it says the regions are simulated on one PC.
4. **Diagrams** always ship in three formats: SVG + editable `.drawio` + high-res PNG. Never put figure numbers or reference numerals
   on them — Kavin adds those himself.
5. **Documents** are written for a cold reader in plain words, and mark every item **DONE / QUEUED / FUTURE**.
6. **Never overwrite or delete a superseded version** (plans, figures). A new version gets a new file name. If something must go,
   move it to `_to_delete\` and list it in your report — Kavin deletes.

## Mailbox mode (headless runs)

Most of the time you are run headless by the mailbox watcher (`claude -p`, permissions pre-approved), resuming one long-lived
session. Chat Claude writes each brief and reads every report before writing the next one.

1. **Nobody can answer mid-run.** Every question for Kavin becomes a **NEEDS-KAVIN** item in your final message; every
   design / technical choice you want chat to rule on goes under **NEEDS-DECISION**. Finish everything that does not depend on the
   answer, then STOP. Don't guess on a decision that changes scope.
2. **Never touch `_mailbox\`** (it is the watcher's).
3. **Git.** This folder is a git repo with a **private** remote: `origin` =
   `https://github.com/kavin-vardhan/DynCon.git` (private — the project is patent-pending and must never be public).
   **Commit *and* push at the end of every brief**: commit with message `NNN: <summary>` (NNN = brief number), then
   `git push origin main`, and quote the pushed hash in your report. Never force-push, never rewrite pushed history, never
   force anything, never `git clean` / `reset --hard`. If a push is rejected (the remote moved), stop and report — do not
   merge or force. `_mailbox/` is git-ignored.
   - Auth: the `gh` CLI is logged in as `kavin-vardhan`, so a push works without a prompt via
     `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push origin main`.
     Set `GIT_TERMINAL_PROMPT=0` first so a missing credential fails fast instead of hanging a headless run.
   - Before any push, confirm the remote is still private (`gh repo view kavin-vardhan/DynCon --json visibility`, and an
     anonymous `curl -s -o NUL -w "%{http_code}" https://api.github.com/repos/kavin-vardhan/DynCon` must not return 200).
     Never push anything from `server/data/`, `_mailbox/` or the UE build outputs — `.gitignore` already keeps them out.
4. **Stay in scope.** Useful things you notice outside the brief go under *Suggestions*; don't do them.
5. **Shell:** your Bash tool fails in headless runs on this PC (`/c/ClaudeTemp/...-cwd: No such file or directory`). Use
   PowerShell from the start; don't spend a retry on Bash.
6. **Leave nothing running, and never end on a promise.** A headless run ENDS the moment you send your final message —
   nobody resumes you, and any background task is killed with the session. So run long jobs in the **foreground** (split them
   into stages that fit the tool timeout), or wait until every background task has finished, *then* write the report.
   A final message like "still running, I'll pick it up" loses the work (it happened in brief 003).
7. **Final message = the report**, verbatim. Use this shape:
   - Line 1: a one-line headline of the outcome.
   - `## Done` — what you did, with file paths.
   - `## Verification` — how you checked it (commands run, what you opened or rendered).
   - `## Commits` — hash + message.
   - `## NEEDS-DECISION` — items for chat, or `none`.
   - `## NEEDS-KAVIN` — human actions or questions, or `none`.
   - `## Suggestions` — optional.
   - Last line, exactly one of: `VERDICT: GREEN` (all done, nothing open) · `VERDICT: NEEDS-DECISION` · `VERDICT: RED` (failed or
     blocked). A report with no VERDICT line is UNDECLARED and holds the next brief.
