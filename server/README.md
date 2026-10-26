# The demo server — what is here and how to run it

*The stand-in cloud for the Tokyo demo. Built to `specs/server_spec_v1.md`; brief 007 part 1
covers the whole game-facing delivery path and uploads. The auction (lots, rivals, bids,
credits) is **QUEUED** for part 2 and is the only thing in the spec that is missing.*

## Run it

```powershell
.\server\run_local.ps1            # venv + deps if needed, then http://127.0.0.1:8700
.\server\run_local.ps1 -Packs     # build the demo .dcpack files first
.\server\run_local.ps1 -Port 8701 # a second instance, out of the way
```

First run generates the RS256 key pair and the URL secret into `server\data\keys\`, creates
`server\data\db.sqlite`, seeds games A and B from the config, and registers every rival and
default pack it finds in `server\demo_files\`. It binds to **127.0.0.1 only**.

`GET /` lists the routes, `/docs` is the generated API page, `GET /admin/health` is the
one-line "is it alive and what does it have" check.

```powershell
.\server\.venv\Scripts\python.exe -m pytest           # from server\ — 102 tests
.\server\.venv\Scripts\python.exe tools\make_fake_packs.py          # the demo packs
.\server\.venv\Scripts\python.exe tools\fake_client.py --game A --region r1 --once
.\server\.venv\Scripts\python.exe tools\stage1_exit_test.py         # plan v6 §14 step 1
```

## What is in here

| Path | What |
|---|---|
| `config/demo.json` | **Every tunable, and the source of truth for rival identity and region mapping.** |
| `dcserver/clock.py` | `Clock` (injectable; `FakeClock` in tests) and `DemoClock` (60x, time blocks) |
| `dcserver/config.py` | reads demo.json, validates it, answers questions about slots and rivals |
| `dcserver/repo.py` | `Repo` interface + the SQLite implementation (DynamoDB later) |
| `dcserver/blobs.py` | `Blobs` interface + the local file system one, with signed expiring links (S3 later) |
| `dcserver/signing.py` | RS256 manifests and pack records; HMAC file links; canonical JSON |
| `dcserver/packs.py` | the `.dcpack` format and the four checks (package → rating → fit → sign) |
| `dcserver/rules.py` | **what shows in a slot right now** — the one rule the demo turns on |
| `dcserver/service.py` | everything the routes do, with no HTTP in it |
| `dcserver/routes.py` | the HTTP surface: game client · portal · admin |
| `tools/make_fake_packs.py` | builds the demo packs; `--real` wraps the real cooked packs |
| `tools/fake_client.py` | the game's side without Unreal: poll → resolve → verify → download → MOUNT |
| `tools/stage1_exit_test.py` | ten hand-written allocations, ten right MOUNT lines |
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

`GET /resolve` returns the manifest plus a `signature`. To check it:

1. take the JSON object, **remove the `signature` field**;
2. serialise what is left as **canonical JSON** — keys sorted at every level, no whitespace
   (`,` and `:` as separators), UTF-8, no trailing newline;
3. verify those bytes with **RS256** (PKCS#1 v1.5 + SHA-256) against the public key from
   `/client-config`.

`signature_alg` says `RS256-canonical-json-v1` so this can change later without guesswork.
The signed payload deliberately contains **no floating-point numbers** — only strings,
integers and booleans — so there is nothing for a non-Python verifier to format differently.
`tests/test_resolve.py` asserts that, and `dcserver/signing.py:verify_with_public_pem` is
exactly the 12 lines the client needs.

Then: download each file with its signed link (Range supported, resume from where you
stopped), check **SHA-256** per file, and only mount after both checks pass. On a mismatch the
client keeps the default up and retries — `tools/fake_client.py` is the worked example and
`POST /admin/sabotage {"mode": "corrupt"}` is how to make it happen on demand.

## Routes

**Game client** — `/client-config` · `/changes?game=&region=` · `/resolve?game=&slot=&region=`
· `/files/{pack}/{name}?exp=&sig=` · `POST /telemetry`

**Portal** — `/config/public` · `/clock` · `GET|POST /brand` · `/wallet` · `/demo-files` ·
`/demo-files/{name}` · `POST /content` · `GET /content` · `POST /content/{id}/versions` ·
`POST /campaign/pause` · `/status/live`

**Admin** — `/admin/health` · `POST /admin/reset` · `POST /admin/sabotage` ·
`POST /admin/allocate`

**QUEUED for part 2** — `POST /bids` · `/lots` · `/games` and `/games/{id}` (with the slot-map
image) · `POST /games/register` · `/report` · `/preview/region` · `POST /admin/close-auction`.
`POST /admin/allocate` is how an allocation gets written until the auction writes it.

## Things worth knowing

- `demo_files/` holds both the fake packs and the `.real.dcpack` wrappers. `GET /demo-files`
  only lists what a visitor could upload — the rival and default packs live in the same folder
  but are the game's own content, and the server seeds them at startup (preferring a real pack
  over a fake one).
- A reset wipes the visitor's brand, uploads, allocations, telemetry and saved state, deletes
  their pack bytes, and returns a **purge list** that `/changes` repeats to every client, so
  the next visitor gets a real download. The rival and default packs, and the demo clock,
  carry on.
- The demo clock runs at 60x from the server's epoch: one demo hour is one real minute, and a
  block is 3 demo hours = 3 real minutes.
- `saved_state` exists as a table and is wiped by a reset, but nothing writes to it yet — the
  state-across-an-update endpoints belong to the UE brief (plan v6 §14 step 6).
