# The demo server — what is here and how to run it

*The stand-in cloud for the Tokyo demo, built to `specs/server_spec_v1.md`. **DONE**: the
game-facing delivery path and uploads (brief 007); the auctions, the portal API and the
report (brief 008); `POST /games/register` with the real map and thumbnails the UE
slot-map tool captures (brief 013); and serving the brand portal itself at `/portal/`
(brief 014). Nothing here is QUEUED.*

## Run it

```powershell
.\server\run_local.ps1            # venv + deps if needed, then http://127.0.0.1:8700
.\server\run_local.ps1 -Packs     # build the demo .dcpack files first
.\server\run_local.ps1 -Port 8701 # a second instance, out of the way
```

`-Packs` makes exactly the state the demo wants, in two passes: the **fake** packs for every
piece-version (plus the two built-to-fail files), then the **real** cooked packs out of
`unreal\_packs\` wrapped as `<id>_<v>.real.dcpack`. The curated list prefers a real pack
wherever one exists, so what a visitor uploads is real content. `unreal\_packs\` is a build
output and git-ignored, so on a clean checkout the second pass reports what it skipped and
the demo runs on the fakes until the UE side has packaged — nothing to configure either way.

First run generates the RS256 key pair and the URL secret into `server\data\keys\`, creates
`server\data\db.sqlite`, seeds games A and B from the config, and registers every rival and
default pack it finds in `server\demo_files\`. It binds to **127.0.0.1 only**.

`GET /` lists the routes, `/docs` is the generated API page, `GET /admin/health` is the
one-line "is it alive and what does it have" check, and **`/portal/` is the brand portal**
— the `portal/` folder next to this one, mounted as static files so the booth runs one
process and the portal needs no CORS (`portal/README.md`).

```powershell
.\server\.venv\Scripts\python.exe -m pytest           # from server\ — 169 tests
.\server\.venv\Scripts\python.exe tools\make_fake_packs.py          # the demo packs
.\server\.venv\Scripts\python.exe tools\fake_client.py --game A --region r1 --once
.\server\.venv\Scripts\python.exe tools\stage1_exit_test.py         # plan v6 §14 step 1
.\server\.venv\Scripts\python.exe tools\stage4_exit_test.py         # plan v6 §14 step 4
```

## What is in here

| Path | What |
|---|---|
| `config/demo.json` | **Every tunable, and the source of truth for rival identity and region mapping.** |
| `config/maps/` | the registered slot maps: `<game>.json` + `<game>.png` + `<game>_<slot>.png`, **in git** |
| `dcserver/registry.py` | `POST /games/register`: what the developer's slot-map tool sends, checked and stored |
| `dcserver/clock.py` | `Clock` (injectable; `FakeClock` in tests) and `DemoClock` (60x, time blocks) |
| `dcserver/config.py` | reads demo.json, validates it, answers questions about slots and rivals |
| `dcserver/repo.py` | `Repo` interface + the SQLite implementation (DynamoDB later) |
| `dcserver/blobs.py` | `Blobs` interface + the local file system one, with signed expiring links (S3 later) |
| `dcserver/signing.py` | RS256 manifests and pack records; HMAC file links; canonical JSON |
| `dcserver/packs.py` | the `.dcpack` format and the four checks (package → rating → fit → sign) |
| `dcserver/rules.py` | **what shows in a slot right now** — the one rule the demo turns on |
| `dcserver/auction.py` | lots, the scripted rival, the clock, credits, the block won on close |
| `dcserver/service.py` | everything the routes do, with no HTTP in it |
| `dcserver/routes.py` | the HTTP surface: game client · portal · admin |
| `dcserver/app.py` | builds the app, and mounts `portal/` at `/portal/` when it is there |
| `tools/make_fake_packs.py` | builds the demo packs; `--real` wraps the real cooked packs |
| `tools/fake_client.py` | the game's side without Unreal: poll → resolve → verify → download → MOUNT |
| `tools/stage1_exit_test.py` | ten hand-written allocations, ten right MOUNT lines |
| `tools/stage4_exit_test.py` | the whole visitor tour: brand → upload → bid → win → mount → update → report |
| `data/`, `demo_files/*.dcpack`, `.venv/` | generated, git-ignored |

## The shape of it

- **Timestamp-driven. No timers, no threads, no background work.** Every rule — which block
  it is, whether an allocation is live, what the attract rotation shows — is worked out from
  stored timestamps when a request arrives. That is what would let the same code run in a
  Lambda, and it is why the tests can move time by hand and get the same answers.
- **Storage behind two interfaces.** `Repo` and `Blobs`. AWS mode is a second implementation
  of each plus a config change, not a rewrite.
- **The config is the contract.** Region labels, rival colours and emblems, which rival piece
  belongs to which region, footfall, size classes, auction numbers, the wallet, the pacing.
  `tests/test_config.py` fails if any of it drifts from the spec, and
  `tests/test_rival_identity.py` fails if the art kit's preview identities stop agreeing with
  it.

## A content pack is three files

Brief 004 proved it and brief 006 built all thirteen: with IoStore on (the 5.7 default) a pack
is `pakchunkN-Windows.pak` + `.utoc` + `.ucas`, the `.pak` is a ~340-byte stub and the assets
live in the `.ucas`. The server keeps the three together, hashes each one, signs the set, and
hands the game three signed links.

A **`.dcpack`** is one zip: `dcpack.json` + those files. `dcpack.json` is a superset of the
spike's `pack.json` — piece, version, chunk id, class path, files with sizes, units — plus what
the spec needs: engine version, rating, bounds in metres, size class, state schema.

**Fake vs real.** Real packs are 0.25–1.4 MB. The fake packs carry 15–40 MB of seeded filler so
an upload at the booth feels like an upload, but **a download is paced by time, not by size**:
the rate is `pack bytes / 4 s`, so a 0.76 MB real pack and a 38 MB fake one both take about
four seconds (measured: 4.03 s for a real one). When every piece is cooked, run
`make_fake_packs.py --real --plain-name` and the server serves real packs with no code change.

## What shows in a slot (spec §5)

At time *t*, for one game / slot / region:

1. a visitor allocation covering *t*, not paused → the visitor's content, latest approved
   version, in the visitor's brand;
2. paused → the developer's default (**call made in brief 007**: pausing takes your content
   down, and the slot is never empty);
3. the block straight after a visitor allocation → that region's rival, the "next winner";
4. otherwise the attract rotation: block `k = floor((t − epoch) / 180 s)`, and
   `(k + slot index)` even → the region's rival, odd → default. An S slot always gets the
   small rival piece.

`alloc_key` is a 12-character hash of (allocation, piece, version, pack, brand). The game
polls `/changes` and only resolves a slot whose key changed, so it changes exactly when a win,
a push-update, a brand change, a pause or a block boundary changes what should be on screen.

## Verifying a manifest (what the UE client has to do)

`GET /resolve` returns an **envelope**:

```json
{ "signed_payload": "{\"alloc_key\":\"…\",…}", "signature": "<base64>",
  "signature_alg": "RS256-canonical-json-v1" }
```

1. verify `signature` over the **exact UTF-8 bytes of the `signed_payload` string** with
   RS256 (PKCS#1 v1.5 + SHA-256) and the public key from `/client-config`;
2. only then parse the string, and use what is inside it.

That way no client has to reproduce canonical JSON to check a signature. The string the
server signs *is* canonical JSON (keys sorted at every level, no whitespace between tokens,
UTF-8, no trailing newline) and the payload deliberately contains **no floating-point
numbers** — only strings, integers and booleans — but a verifier never has to rebuild it.

That is the **only** shape `/resolve` serves. There used to be a `?format=flat` that returned
the manifest's fields with the signature alongside them, so a client and a server could be
one brief apart; the UE client has verified the envelope since brief 011, and brief 013 took
the second shape out — two ways to sign one answer is two ways to get it wrong.
`dcserver/signing.py:verify_bytes_with_public_pem` is the whole check, and
`tools/fake_client.py:resolve` is the worked example.

Then: download each file with its signed link (Range supported, resume from where you
stopped), check **SHA-256** per file, and only mount after both checks pass. On a mismatch the
client keeps the default up and retries — `tools/fake_client.py` is the worked example and
`POST /admin/sabotage {"mode": "corrupt"}` is how to make it happen on demand.

## Routes

**Game client** — `/client-config` · `/changes?game=&region=[&preview=1]` ·
`/resolve?game=&slot=&region=` · `/files/{pack}/{name}?exp=&sig=` · `POST /telemetry`

**Portal** — `/config/public` · `/clock` · `GET|POST /brand` · `/wallet` ·
`/demo-files[?purpose=update]` · `/demo-files/{name}` · `POST /content` · `GET /content` ·
`POST /content/{id}/versions` · `/games` · `/games/{id}` · `/games/{id}/map` ·
`/games/{id}/slots/{slot}/thumb` · `POST /games/register` · `POST /bids` · `/bids/split` ·
`/lots` · `/lots/{id}` · `/report` · `GET|POST /preview/region` · `GET|POST /preview/flip` ·
`POST /campaign/pause` · `/status/live`

**Admin** — `/admin/health` · `POST /admin/reset` · `POST /admin/sabotage` ·
`POST /admin/allocate` · `POST /admin/close-auction` · `POST /admin/end-block`

**Static** — `/portal/` is the brand portal (the `portal/` folder, served as-is). It is
mounted last so it can never shadow an API route, and a checkout without the folder still
starts: `GET /` then reports `portal_ui: null` and `/portal/` is a 404.

`POST /admin/allocate` stays: it is how a block gets written by hand when the auction is not
involved.

`POST /admin/end-block {game, slot, region}` (brief 016) is the other one of that family: it
pulls the live allocation's `end_at` back to now, which is "the three demo hours are up,
now". Nothing else is touched — the row stays, so the report still counts the block and its
telemetry — and what happens next is the ordinary rule above, step 3: the region's rival, the
next winner, takes the block. It is the counterpart of `/admin/close-auction` for the other
timestamp rule, and it is what lets a rehearsal (and `unreal\Tools\state_exit_test.py`) make
"the block ends while the Player is standing inside" happen on cue instead of three real
minutes from now.

## Registering a game (`POST /games/register`)

This is the **third actor** in the story. A brand uploads content and bids; the platform
resolves and delivers; and the **game developer** registers the game, its slots and the rule
for each slot. Without it the portal can only draw a picture of a slot map; with it, a brand
is looking at a photograph of the spot it is bidding on.

What arrives is one multipart POST from the editor half of the UE plugin
(`UDCSlotMapTool`, `unreal/README.md`):

| part | what |
|---|---|
| `data` | the JSON the tool wrote: the capture's geometry, plus per slot its id, size class, class limits, rating rule, pre-fetch radius, world position and **pixel position on the capture** |
| `map_image` | the straight-down orthographic PNG of the playable area (2048 px on the long side) |
| `thumbs` | one eye-level PNG per slot, each named `<game>_<slot>.png` |

A thumbnail is matched to its slot by its **file name**, not by its position in the request,
so the order the tool sends them in can never quietly mis-label one.

The server checks that each image really is a PNG (and reads its size straight out of the
IHDR chunk — it never decodes one), that every pin lands inside the image, and that every
slot is one the platform actually has. A slot the platform has never heard of is a **400**,
not a warning: accepting it would leave a slot nobody can bid on and nobody can see.
Registering only some of a game's slots is allowed and comes back as a warning; the rest keep
their drawn placeholder.

**Where it is stored: `server/config/maps/`, and it is in git.** One `<game>.json` plus the
PNGs. In `config/` rather than `data/` for two reasons: a registration belongs to the
developer, so `POST /admin/reset` between visitors must not wipe it; and a clean checkout has
to serve the real map and thumbnails without anyone running Unreal first.

What it changes once a game is registered: `/games/{id}/map` and
`/games/{id}/slots/{slot}/thumb` serve the real PNGs instead of the drawn SVG, and **the
registered pin positions replace the `px` values in `demo.json`** everywhere a pin position
is published (`/games/{id}`, `/config/public`, and the drawn fallback map itself). The
config's `px` numbers were hand-guessed stand-ins for a map nobody had captured yet; the
registered ones were measured on the capture the pin is drawn on. The platform's own slot
table still decides which slots exist, what class they are and what they cost.

## The auction

- A **lot** is one slot × one region × the next block, opened on demand — one per
  slot-region at a time. **open**: the rival holds at the opening price
  (footfall × 0.25, stepped to 25 — A1 / Japan is 300) with no clock. The visitor's first
  bid makes it **running** and sets a 45-second clock. **closed** when that runs out.
- The **rival** waits 3 s after the visitor's first bid, then raises **once**, to
  min(visitor + 25, 2 × opening), and only if that beats them. Never again. So the
  2,000-credit wallet can win every region of A1 (1,425 at the most).
- **Soft close**: a visitor bid with 10 s or less left sets the clock back to 10 s.
- **Credits** are *derived*, never stored: `held` is what you are leading on, `charged` is
  what you won, `available` is 2,000 minus both. Being outbid releases by definition.
- **On close** the winner gets one block. The visitor's starts at the close — or when the
  block they already hold there ends, which is what "book the next block" means. A rival
  win writes the rival's own block, so the slot visibly goes to the rival.
- A bid may name the `lot_id` the portal was showing; a bid that arrives after that auction
  closed is then refused instead of quietly starting the next one.
- Nothing above runs on a timer. `Service.tick()` catches every lot up at the top of a
  request, so the rival's counter-bid and the close are applied by the first request after
  they fell due — a game client polling `/changes` every 1.5 s is what settles an auction at
  the booth, and a test just moves the clock.

## Things worth knowing

- `demo_files/` holds both the fake packs and the `.real.dcpack` wrappers, and
  `GET /demo-files` is a **curated** list, not the folder: version 1 of each uploadable piece
  plus the one built-to-fail file the tour rejects on purpose (engine 5.3).
  `?purpose=update` returns the version-2 files, which is all the push-an-update screen
  offers. The rated-18+ pack stays on disk for the tests, the rival and default packs are the
  game's own content (seeded at startup), and a `.real.dcpack` always wins over a fake one for
  the same piece-version. The curated plan is `demo_files` in `config/demo.json`.
- **The booth serves real packs** (0.5–1.3 MB), not the fake filler: the visitor feels the
  paced ~4 s download, not the megabytes, so there is no reason to upload something that is
  not the real thing. The fakes stay for the tests and as the fallback before the UE side has
  packaged.
- **The report's views are simulated + live, shown split.** The simulated half uses the same
  footfall model as the slot card — footfall per demo hour × the 3 demo hours in a block —
  counted for every block that has *started*; the live half is the views the game really
  reported inside those blocks. So `cost_per_1000_views` on the Report screen equals the
  `credits_per_1000_views` the slot card quoted at that price the moment a block is won, and
  counted views only make it better. Visits, dwell and interactions are live only: they are
  real events with no simulated model to mix with.
- **Each telemetry event counts in exactly one block.** A block's window runs from its
  `start_at` to sixty seconds past its `end_at`, because the game batches telemetry and a
  view earned half a second before a block ends can arrive after it. Where the visitor
  holds the **next** block of the same slot and region too, that slack used to lie inside
  both windows and everything in it was counted twice — brief 016's 76 interactions came
  back as 118. The windows are now half open and clamped to the start of the next block of
  the same slot and region, so the slack survives where there is nothing after it and
  cannot reach into a block with its own claim (`tests/test_block_boundary.py`).
- A reset wipes the visitor's brand, uploads, lots, bids, credits, allocations, telemetry and
  saved state, deletes their pack bytes, puts the preview window back to its default region,
  and returns a **purge list** that `/changes` repeats to every client, so the next visitor
  gets a real download. The rival and default packs, and the demo clock, carry on.
- **`POST /admin/reset` carries a `reason`**, and `/changes` hands it on as `reset_reason`.
  `"staff"` is the three-button combo on pad 2 — a human clearing the booth down between
  visitors — and the game drops back to its attract loop as well. `"idle"` is the portal's
  own sixty-second timer on the **brand** seat, and the game ignores it: the two seats can
  be two different visitors (plan v6 §2), and an idle timer on one of them must not take
  the game away from somebody still standing in it. Everything the server wipes is the same
  either way, which is why it is one endpoint with a reason rather than two that would
  drift apart. A bare `POST` with no body is read as `"staff"`, the cautious reading.
- **Which game the booth is playing is learnt from the poll the game already makes.**
  `live_at_booth` on `/games` and `/games/{id}` — plan v6 §4 step 3's badge — used to be a
  flag in `demo.json`, written down once. A visitor can now switch game from the pause menu,
  so it follows the last `GET /changes` that did **not** say `preview=1`: the second copy of
  the game plays whatever map it was started on as another region and must not move the
  badge. Nothing has polled on a fresh server, so `demo.json`'s own flag is still the answer
  a clean checkout gives.
- **The manifest names its lot and its block.** `showing.block` is the demo clock's block
  index and `showing.lot` is the lot an allocation was won in, or `null` for a block nobody
  bought (the attract rotation, and the rival's block after the visitor's). Both are inside
  the signed payload. They are there for the game's X-ray view, whose whole job is to show
  that what arrived is one slot × one region × one time block and not a file off a CDN.
- `players_online` and the simulated half of footfall are functions of the demo clock, not
  random: two screens polling at the same moment agree, and footfall is labelled
  "simulated + live" with the counted views kept separate.
- **`GET /preview/region` is everything the second copy of the game needs to know about
  itself** (plan v6 §7). It answers one question — *what am I?* — in two halves: the region
  it plays as, which the portal's region check flips with the `POST`, and a **`focus`** block
  saying which slot to look at. The focus has three rules in order, so there is always an
  answer: the lot the **visitor last bid on** ("the slot just auctioned", and right from the
  moment a bid is placed rather than when the auction closes), else their **newest
  allocation** — which is what a rehearsal driven by `/admin/allocate` has instead of a bid —
  else the **busiest slot of the game being played at the booth**, so the window has
  something to frame during the attract loop. A rival's bidding never moves it. The answer
  also carries `label_jp`, because the window draws a bilingual caption on the game's HUD
  canvas and cannot read the portal's string table; `tests/test_preview.py` fails if that
  label stops agreeing with `portal/strings.js`.
- **`POST /preview/flip {region, seconds}` is the fallback for the same step** (plan v6
  §11): no second copy of the game, the **main** one plays as that region for twenty
  seconds and the slot swaps in front of the Player. It is a timestamp like everything else
  here — an entry with an `ends_at`, and the first request after that moment sees no flip —
  and it is carried on **`/changes`**, the poll every copy of the game already makes every
  1.5 s, rather than on an endpoint of its own. It changes nothing about what any region is
  showing: it is an instruction to a game, not to the platform. A reset cancels it.
- The demo clock runs at 60x from the server's epoch: one demo hour is one real minute, and a
  block is 3 demo hours = 3 real minutes.
- `saved_state` exists as a table and is wiped by a reset, but nothing writes to it yet — the
  state-across-an-update endpoints belong to the UE brief (plan v6 §14 step 6).
- `client_cache_packs` is **12** (brief 013 raised it from 8): one short of every
  piece-version in the demo, so a booth run never evicts a pack it is about to be asked for
  again. The whole set is 8.9 MB of real cooked packs, so there is nothing to save by being
  stingy — and an eviction at the booth costs a four-second download the visitor can see.
  The game reads it from `/client-config` as `cache_packs`.
