# Demo server — spec v1 (the stand-in cloud)

*Written 2026-10-25 by chat Claude for Claude Code. Derived from demo plan v6 §5, §9, §13, §14. Status: DONE (spec);
build QUEUED. This covers the server and a fake game client. The portal and the UE side get their own specs.*

## 1. Shape

- **Python 3.13** (what this PC has) + **FastAPI** + uvicorn, in `server/` with its own venv (`server/.venv`, git-ignored).
  Package `dcserver`. Listens on **127.0.0.1:8700** in local mode.
- **Timestamp-driven, no background timers or threads.** Every rule (auction close, rival counter-bid, block expiry, attract
  rotation) is evaluated lazily from stored timestamps when a request arrives. That is what lets the same code run in Lambda.
  The clock is injectable (`Clock` object) so tests can move time.
- **Storage behind two small interfaces** so AWS mode is a config change:
  - Data: `Repo` — SQLite implementation now (`server/data/db.sqlite`); DynamoDB later.
  - Files: `Blobs` — `fs` implementation now: the server stores pack files under `server/data/packs/` and serves them itself
    through **signed, expiring URLs** (HMAC-SHA256 over path + expiry) with HTTP Range support. `s3` implementation later
    (boto3 presigned URLs — works for S3 and for MinIO). *Decision: no MinIO on the booth PC — one process fewer, and no
    AGPL question. The links are still real signed links.*
- **Signing:** RSA-2048, RS256 (PKCS#1 v1.5 + SHA-256) via `cryptography`. Key pair generated on first run into
  `server/data/keys/` (git-ignored); the public key is served at `/client-config`. Rationale: the UE client can verify RS256
  with the engine's built-in OpenSSL-backed crypto — verify that when the UE side starts.
- Config in `server/config/demo.json` (committed). All tunables from plan v6 §9 live there, not in code.

## 2. Config (`server/config/demo.json`) — starting values

- `regions`: `r1` "Japan", `r2` "India", `r3` "Europe" (display labels are config; IDs stay neutral). Booth main screen = r1,
  preview default = r2.
- `size_classes`: S 7×7×5, L 14×14×9, T 14×14×20 (metres) — identical to `specs/content_assets_spec_v1.md`.
- `games`: `A` (label "Game A") slots A1 L, A2 T, A3 S; `B` ("Game B") slots B1 L, B2 S.
- `footfall` (views per demo hour): A1 1200/900/600 · A2 800/600/400 · A3 300/250/150 · B1 700/500/350 · B2 250/200/120.
- `rivals`: r1 `#1FA39A` triangle, pieces rival1 / rivalsmall · r2 `#F28C28` ring, rival2 / rivalsmall ·
  r3 `#7B5CD6` diamond, rival3 / rivalsmall. (Large pieces for S slots are never chosen: S slot → rivalsmall.)
- `brand_presets`: colours `#E23D3D #2F6FEB #2EA44F #F2C230 #E0559B #1EB8D0 #8CC63F #23395B`; emblems circle, triangle, square,
  diamond, star, ring, chevron, hexagon.
- `auction`: opening = footfall(slot, region) × 0.25 rounded to 25 · min_raise 25 · rival_max = 2 × opening ·
  rival_delay_s 3 · clock_s 45 · soft_close: a bid with ≤ 10 s left resets the clock to 10 s.
- `wallet` 2000 · `block_demo_hours` 3 · `demo_seconds_per_real_second` 60 (1 demo hour = 1 real minute).
- `packs`: max_bytes 100 MB · engine_version "5.7" · allowed_ratings ["all"] · local pacing: each pack download takes ~4 s
  (rate = size / 4 s, minimum 2 MB/s).
- `telemetry`: view = on screen ≥ 1 s within 30 m (client-side rule; server just counts).
- `idle_reset_s` 60.

## 3. Packs (what gets uploaded)

A pack is uploaded as one zip file, extension **`.dcpack`**, containing `dcpack.json` plus the UE container files
(`.pak` — or `.pak` + `.utoc` + `.ucas`; the server does not care what they are). `dcpack.json`:
`{ piece, version, engine_version, rating, size_class, bounds: {x, y, z}, class_path, state_schema, files: [names] }`.

**Checks, in this order** (each reported back with ok / detail so the portal can animate them):
1. **package** — valid zip, `dcpack.json` valid, every listed file present, total ≤ max_bytes, engine_version matches.
2. **rating** — in allowed_ratings.
3. **fit** — bounds within the declared size class.
4. **sign** — SHA-256 per file; the server signs the pack record. Only signed packs become biddable; the game never mounts an
   unsigned pack.
Rejection returns the failing check with a human sentence ("Made for engine 5.3 — this game runs 5.7").

Until real cooked packs exist, `server/tools/make_fake_packs.py` builds a `.dcpack` per piece-version from the art manifests
(`art/export/*/manifest.json` when present; otherwise the piece table in the asset spec) with **seeded random filler** of a
realistic size (15–40 MB) standing in for the containers, plus the two built-to-fail files (`engine 5.3`, `rating 18+`). They
go into `server/demo_files/` — the folder that plays "the brand's computer".

## 4. Endpoints

All JSON. Times are ISO-8601 UTC plus `demo_time` where the portal shows it.

**Game client**
- `GET /client-config` → poll_interval_s (1.5), prefetch_radius_m, public_key_pem, demo clock params.
- `GET /changes?game=A&region=r1` → `{server_time, demo_time, slots: {A1: "<alloc_key>", …}}`. The client resolves a slot when
  its key changes. Keys are stable while nothing changes.
- `GET /resolve?game=A&slot=A1&region=r1` → signed manifest:
  `{slot, game, region, alloc_key, is_default, content: {piece, version, size_class, class_path, state_schema},
  pack: {id, files: [{name, size, sha256, url}]}, brand: {colour, emblem} | null, valid_until, server_time, signature}`.
  `signature` = RS256 over the canonical JSON (sorted keys, no whitespace) of everything else. URLs are signed + expiring.
- `GET /files/{pack_id}/{name}?exp=…&sig=…` → the bytes, Range supported, paced in local mode.
- `POST /telemetry` → batch `[{game, region, slot, alloc_key, type: view|visit|dwell|interaction, value, ts}]`.
- `POST /games/register` → from the UE slot-map tool: map image, thumbnails, slot list with pixel positions. **DONE in brief
  013** — it is a portal/developer route rather than a game-client one, and it stores the capture in `server/config/maps/`,
  committed, so a clean checkout serves the real pictures. The registered pin positions replace `demo.json`'s `px` values.
  A game that was never registered keeps the drawn SVG placeholders.

**Portal**
- `GET /config/public` — regions, presets, labels, clock.
- `POST /brand {colour, emblem}` → the visitor's brand (one visitor at a time; creating a new one replaces the old).
- `GET /wallet` → `{available, held, charged}`.
- `GET /demo-files` → the list in `server/demo_files/`; `GET /demo-files/{name}` → bytes. The portal fetches the bytes and
  re-uploads them with a real progress bar — a real HTTP upload with no file picker.
- `POST /content` (multipart `.dcpack`) → `{content_id, version, status: approved|rejected, checks: [...]}`;
  `GET /content` → my content with `fits: {slot_id: {ok, reason}}`.
- `POST /content/{id}/versions` → push an update (same checks; version + 1; the live allocation picks it up).
- `GET /games` → `[{id, label, slot_count, players_online (simulated), live_at_booth: bool}]`.
- `GET /games/{id}` → `{map_image_url, slots: [{id, size_class, limits, px: {x, y}, thumb_url, footfall: {r1…},
  lots: {r1: {lot_id, state, highest, holder: rival|you, closes_in_s, opening}}}]}`.
- `POST /bids {slot, content_id, bids: [{region, amount}]}` → per-region `{accepted, reason, lot}`. Rejections: below
  highest + min_raise, not enough available credits, content doesn't fit, lot closed.
- `GET /lots?slot=A1` / `GET /lots/{id}` → live lot state (countdown, highest, holder, history).
- `GET /status/live` → per game / slot / region: what is showing now (piece, version, brand or rival or default, ends_at).
- `GET /report` → per region: views, visits, dwell_s, interactions, charged, cost_per_view, time_left_s; plus totals.
- `POST /campaign/pause {paused}`.
- `GET|POST /preview/region` — the region the preview copy of the game plays as; it polls this.
- `GET /clock` → `{demo_time, label: "demo time"}`.

**Admin (booth staff; key-protected header in AWS mode)**
- `POST /admin/reset` — wipes the visitor's brand, wallet, uploads, bids, lots, allocations, counters, saved state; tells
  clients to purge the visitor's packs from cache (rival and default packs stay).
- `POST /admin/sabotage {mode: corrupt|freeze}` — corrupt: the next pack download has one byte flipped (hash mismatch → client
  falls back to default and retries). freeze: the next download stalls ~5 s halfway, then the connection drops; the client
  must resume with Range from where it stopped.
- `POST /admin/close-auction {lot_id | "all"}` — sets close_at = now.
- `GET /admin/health`.

## 5. Rules (all lazy, all from timestamps)

- **Lot** = slot × region × the next block. One open lot per slot-region for the visitor. States: `open` (rival holds at the
  opening price, no clock) → `running` (first visitor bid sets close_at = now + 45 s) → `closed`.
- **Rival:** rival_delay_s after the visitor's **first** bid, the rival raises once to min(visitor bid + min_raise,
  rival_max) — only if that beats the visitor. Never bids again. The visitor can always beat rival_max within the wallet.
- **Soft close:** a bid with ≤ 10 s left sets close_at = now + 10 s.
- **Credits:** a leading bid holds credits; outbid releases them; a win charges them.
- **Allocation:** on close, the winner gets the slot-region for one block starting at close_at (3 real minutes).
- **What shows (resolve) at time t:** visitor allocation active and not paused → the visitor's content (latest approved
  version, visitor brand) · else the block right after a visitor allocation → that region's rival (the "next winner") · else
  the attract rotation: block index k = floor((t − epoch) / block_s); `(k + slot_index)` even → the region's rival piece in the
  rival's colours, odd → `default`.
- `alloc_key` = short hash of (allocation id, piece, version, brand) — changes exactly when what should show changes.
- **Footfall shown** = seed × (demo hours elapsed) + real counted views, labelled "simulated + live".
- **Idle reset** after idle_reset_s without portal input (the portal calls reset; the server only exposes it).

## 6. Fake game client (`server/tools/fake_client.py`)

Plays the game's side without UE: polls `/changes` for a game + region, resolves changed slots, verifies the manifest
signature with the public key, downloads every file with Range resume, verifies SHA-256, keeps an LRU cache folder keyed by
pack id + version, then prints `MOUNT A1 content1 v2 brand #E23D3D star` (or `FALLBACK A1 default (reason)`). Posts a few
synthetic telemetry events. This is the stage-1 exit test until the UE client exists.

## 7. Tests (pytest, `server/tests/`, all with the fake clock)

Auction: first bid → rival counter → raise → soft close → win / lose; credits held / released / charged; can't overspend;
every A1 region winnable inside 2000 · fit: content3 only fits A2, content4 fits all · upload: good pack approved, both
built-to-fail packs rejected with the right check · resolve: signature verifies, URLs expire, alloc_key changes on win, on
push-update, on block end, on pause · files: Range resume, pacing ~4 s (time it with a real clock in one test), corrupt
sabotage → hash mismatch once then clean · reset wipes everything visitor-side and keeps rival / default · attract rotation
flips at block boundaries.

**Stage-1 exit test (plan §14 step 1):** a script writes an allocation by hand ten times (different slots / regions /
pieces); the fake client shows the right MOUNT line every time — 10 / 10.
