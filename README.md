# DynamicContents — what we have, and Claude's read on it

*Cold-reader handoff, written 2026-09-09 by Claude (Cowork session) at Kavin's request: "save everything we have about this project, plus your read on it." Part 1 is drawn only from the six figures in the claude.ai Project **DynamicContents** (uploaded 2026-08-24). Part 2 is opinion — one engineer's read, not the team's, and not legal advice.*

---

## What's in this folder

| Path | What it is |
|---|---|
| `README.md` | This file. |
| `diagrams/0DetailedSystemArchitecture.png` | The big-picture box diagram: game client ↔ cloud backend ↔ brands/advertisers. |
| `diagrams/1RuntimeSequence.png` | 22-step sequence: player nears a slot → content resolved, downloaded, verified, mounted, spawned → telemetry. |
| `diagrams/2SlotLifecycle.png` | State machine for one slot (IDLE → … → ACTIVE → swap → unload), with error/fallback and state preservation. |
| `diagrams/3CommerceEntitlement.png` | 21-step sequence: in-world storefront → try-on → platform-native checkout → entitlement → digital unlock or physical order. |
| `diagrams/4AdvertiserPortal.png` | Brand portal → ingestion & validation pipeline → auction & slot allocation → metadata store → runtime. |
| `diagrams/5ContextResolution.png` | The optional context-aware resolution engine: signals → candidates → filters → pluggable scoring → manifest, plus a decision cache. |

**That is the entire record in chat.** As of today the Project holds no written spec, no claims text, no code, no Project docs and no Project instructions — just the six PNGs (each ~5000 px wide, readable at full zoom).

**Where it came from.** The platform was built by a team for an internal hackathon at Kavin's employer, won, and attracted patent-filing interest. The figures use patent-drawing language ("embodiment", "see engine figure", "see bid pipeline figure"), so treat them as an **invention-disclosure figure set**, not an engineering design doc. If a written description or claims exist, they live wherever the filing process keeps them; this README is the place to leave a pointer, not to copy them.

---

## Part 1 — What the system is (as drawn)

### The one-paragraph version

A shipped Unreal Engine game contains a fixed base map plus **dynamic slots**: trigger volumes with an anchor transform, a placeholder, and bounds. When a player approaches a slot, a **Content Delivery Plugin** in the client asks a cloud backend what should be there right now, downloads a signed, versioned `.pak` over a presigned URL, verifies its hash, mounts it at runtime, and spawns the content at the slot's transform. No level transition, no loading screen, no client patch. On the supply side, brands upload content and bid for slots through a web portal; the backend validates, moderates, signs and auctions that content, then resolves a winner per slot, optionally personalised by a context engine. The same slots can host **in-world commerce**: try-on is client-local, purchase hands off to the platform's native store, and a server-side entitlement service records the grant and either unlocks a digital item or forwards a physical order. The invariant the whole design is built around: **the shipped binary never changes; content changes after deployment without republishing.**

### The three boundaries (fig. 0)

**Game client.** The game world (base map + dynamic slots), the Content Delivery Plugin, and an In-Game Commerce Bridge. The plugin's modules: Slot Manager (slot registry and states), Trigger Listener (overlap events), Download Manager (ChunkDownloader, ranged GET, resume), Integrity Verifier (SHA-256 against the manifest), Pak Mount Subsystem (`FPakPlatformFile`, runtime), Asset Registry Scanner (discover mounted assets), Spawn Lifecycle Manager (contract validation, spawn/despawn), Slot State Store (serialize/restore interaction state), Local Pak Cache (LRU, versioned), Telemetry Emitter (impressions, dwell, interactions).

**Cloud backend, AWS-shaped.** API Gateway exposing `/resolve`, `/telemetry`, `/redeem`; a Resolution Service (Lambda) doing winner lookup and manifest building; the optional Context-Aware Resolution Engine; a Campaign Metadata Store; Telemetry & Analytics (funnel aggregation); a Content Repository (S3, versioned signed paks); and CDN edge / presigned-URL delivery.

**Brands / advertisers.** A Content Delivery Portal (web: upload UI, campaign setup, reporting dashboard) → an ingest API Gateway → Ingestion & Publishing (Lambda: validation, signing, versioning), which registers campaign metadata in the store and uploads signed paks to the repository.

**Wire contracts the figures pin down.** `GET /resolve {SlotID, Context, ClientVer}` → content manifest `{PakID, Ver, Hash, URL, BPClassPath}`. `POST /telemetry {impressions, dwell, interactions}` (commerce adds `try-on, conversion`). `GET /catalog {CampaignID, Context}` → SKU list (prices, variants, 3D asset refs). `POST /redeem {receipt, SKU, PlayerID}`. All cross-boundary traffic is HTTPS; clients only ever receive signed, versioned paks via presigned URLs.

### The runtime path (fig. 1)

Steps 1–3: the player crosses the pre-fetch boundary, the trigger volume fires `OnOverlap(SlotID, PlayerContext)`, the Slot Manager marks the slot RESOLVING. Steps 4–8: `/resolve` goes through API Gateway to the Resolution Service, which queries the active campaign for the slot in the metadata store, gets the winning entry (the bid result), and returns the manifest. Steps 9–14: the plugin looks up PakID + Version in the local cache; on a hit it uses the local pak path, on a miss or stale version the ChunkDownloader issues ranged GETs to S3/CDN in the background, reassembles, SHA-256-checks against `Manifest.Hash`, and persists the pak under an LRU policy. Steps 15–18: runtime `FPakPlatformFile` mount → asset-registry scan of the mounted pak → load the Blueprint class → validate the Slot Interface Contract → spawn the actor at the slot transform with collision, lighting and physics. Steps 19–22: the player interacts, the plugin posts telemetry, events are stored, campaign analytics update.

### The slot lifecycle (fig. 2)

| State | What it means | Leaves on |
|---|---|---|
| IDLE | Placeholder content visible; slot registered on level load | pre-fetch boundary crossed → RESOLVING |
| RESOLVING | Manifest request in flight | cache hit (current version) → MOUNTING · cache miss → DOWNLOADING |
| DOWNLOADING | ChunkDownloader, background | download complete → VERIFYING · failure → ERROR / FALLBACK |
| VERIFYING | Integrity check vs manifest | hash verified → MOUNTING · mismatch → ERROR / FALLBACK |
| MOUNTING | Pak mount, registry scan, validation | actor spawned at slot transform → ACTIVE |
| ACTIVE | Content spawned, fully interactable | new content resolved with player inside bounds → SWAP PENDING · player outside bounds → UNLOAD & PRESERVE (immediate swap) |
| SWAP PENDING | New version queued, current retained | player exits bounds (deferred swap trigger) → UNLOAD & PRESERVE |
| UNLOAD & PRESERVE | Serialize state, despawn, unmount | state serialized, slot vacated → RESOLVING |
| ERROR / FALLBACK | Retry policy, placeholder served | retry with backoff → RESOLVING · max retries → IDLE (placeholder stays) |

The promise the state machine makes: **a content swap never resets player progress or interrupts gameplay.** Interaction state is serialized to the Slot State Store on unload and restored into the replacement content on spawn.

### Commerce and entitlement (fig. 3)

The player interacts with a commerce trigger (the example is a fitting rack). The Commerce-Enabled Store Actor asks the In-Game Commerce Bridge for a catalog `{StoreID, SlotID, PlayerContext}`; the bridge calls `GET /catalog`, the Commerce API Gateway pulls active SKUs from the Brand Catalog Service, and the bridge populates an in-world storefront UI plus try-on assets. **Try-on is client-local and ephemeral** — rendered without entitlement, discarded on exit. On purchase intent the bridge hands off to the **platform-native purchase UI**; the Platform Payment Service returns a signed receipt / transaction token; the bridge posts `/redeem`; the gateway has the Entitlement Service validate the receipt and record a durable entitlement. Then two branches: a *digital good* gets a grant confirmation + unlock manifest and the item is applied permanently across sessions; *physical merchandise* is forwarded as an order `{SKU, shipping reference}` to Brand Fulfillment / E-Commerce, which returns an order confirmation / tracking ID. Telemetry (impression, try-on, conversion) feeds per-campaign, per-slot funnel analytics. Design note on the figure: **no payment data ever enters the game client or the content pak.**

### The supply side (fig. 4)

Three layers. **Advertiser Portal (web):** brand account & auth (login, roles) → content upload (pak + slot manifest) → campaign setup & bid (targeting, schedule, budget) → reporting dashboard (funnel & spend). **Ingestion & validation pipeline:** pak inspection (structure, size, engine version) → slot contract validation (interface + bounds fit) → moderation & policy review (content rating, brand rules) → sign, version & publish (tamper-proof packaging) → Content Repository. Rejections go back to the upload step with diagnostics. **Campaign & auction services:** an Auction Engine scores `bid × quality × relevance` per slot per time window, fed by performance/pricing/quality signals from the reporting side; winners go to a Slot Allocation Schedule (winner per slot per window), which writes allocations to the Campaign Metadata Store that the runtime resolver queries. Rule on the figure: **only content that passes contract validation, moderation and signing becomes biddable inventory; the runtime never mounts unsigned paks.**

### The context engine (fig. 5, marked "embodiment")

Inputs: user attributes (profile, preferences, behaviour), environmental state (location, progression, interaction), system conditions (device, performance constraints), external data (time, events, real-world signals), and developer rules (constraints, business logic, monetisation priorities). Pipeline: Context Aggregator (normalises signals into a context vector, also fed derived behavioural features from a Signal / Feature Store) → Candidate Retrieval (slot-compatible, scheduled, region/rating-filtered campaigns from the metadata store) → Constraint & Eligibility Filter (developer rules as hard gates) → Scoring & Ranking (a **pluggable policy**: weighted heuristic `bid × quality × relevance`, a learned preference model, or an adaptive policy with RL, frequency capping and diversity) → Decision & Manifest Builder, with a Decision Cache keyed by slot × context class with a TTL. Runtime telemetry (interaction & conversion) flows back into the feature store. The stated privacy posture: **context is processed server-side against pseudonymous player identifiers; no raw behavioural data is shipped to clients or advertisers.**

---

## Part 2 — My read

### The short version

This is a well-shaped system. The hard part of "live content in a shipped game" isn't downloading a file, it's everything around the file — trust, versioning, what happens when the player is standing inside the thing you want to replace, what happens when the download fails — and the figures cover exactly those parts. The state machine in fig. 2 and the "biddable only after validation + moderation + signing" gate in fig. 4 are the two ideas I'd defend hardest. What the figures don't yet answer are the questions that decide whether this ships: **who cooks the paks, how a brand's Blueprint is sandboxed, whether the design is single-player only, and how the platform holders feel about hot-loaded third-party content.** None of those is a flaw in the drawings; they're the next layer down.

### What's strong

The "binary never changes" invariant is enforced structurally rather than by policy: signed paks, presigned URLs, hash pinning in the manifest, and a Blueprint-only contract. That is the right way to make the claim true.

The lifecycle handles the cases people usually forget. Deferred swap when the player is inside the bounds, immediate swap when they're not, state preservation across swaps, hash mismatch and download failure both routing to a fallback that leaves a placeholder rather than a hole. The pre-fetch boundary being separate from the slot bounds is the detail that makes the "no loading screen" promise plausible.

The context engine is designed as an interface with a replaceable policy. That is good engineering (you can ship the weighted heuristic and grow into learned models) and, for a filing, it's the kind of "one or more embodiments" breadth a drafter wants.

Commerce keeps money out of the client. Platform-native checkout, receipt validation server-side, entitlement as a durable server record, try-on explicitly ephemeral. That's the shape platform certification teams expect.

The privacy line is drawn in the right place: server-side context, pseudonymous IDs, nothing raw leaving the backend.

### Where I'd push back — client side

**Who cooks the pak is the biggest unanswered question.** Fig. 4 has brands uploading "pak + slot manifest". In Unreal, a pak that a shipped title can mount has to be cooked against *that title's* project, on the *same engine build*, for each target platform — same class layouts, same plugins, same shader platform, and with its own asset-registry fragment so the runtime can discover what's inside (cooked builds rely on a serialized registry rather than scanning package files the way the editor does, which is why fig. 1 has an "asset registry scan" step at all). A brand cooking in their own project produces a pak the title can't safely use. The workable shapes I can see: the platform runs a cook service (brands upload source assets + Blueprints built against a stripped "brand SDK" copy of the title's project, the platform cooks and signs per platform), or the brand gets the SDK project and cooks locally, with pak inspection rejecting anything from the wrong build. Either way, "Pak Inspection: engine ver" in fig. 4 is doing far more work than one box suggests.

**A brand's Blueprint is code running inside the game process.** The figures treat moderation as content rating and brand rules. Blueprint bytecode can call any Blueprint-exposed function in the title — file I/O, networking, console commands, game-state mutation — so contract validation needs a static pass over the uploaded Blueprint graph: an allow-list of node/function classes, a ban on Latent/console/network nodes outside the contract, and a budget check (draw calls, triangles, texture memory, tick cost). Without this, the moderation gate is checking whether the billboard is tasteful while ignoring whether the actor is a keylogger. This is also the thing a platform holder's security review will ask about first.

**Runtime mount and spawn aren't free on the game thread.** Downloads are async in the design, but pak mounting, the registry append, `LoadClass`, and the spawn itself are synchronous unless deliberately made otherwise. Plan on async class loading via the streamable manager, a per-frame spawn budget, and a memory budget per slot per platform so an over-eager brand can't hitch the frame. Fig. 1's "Spawn Actor at Slot Transform (collision, lighting, physics)" also carries an implicit constraint: dynamically spawned content gets dynamic lighting only — no baked lightmaps, and nav-mesh, HLOD and precomputed visibility won't know it exists. Fine for Lumen-lit titles; worth stating for the rest.

**The download manager as drawn is custom, not stock.** Epic's ChunkDownloader fetches whole pak files and retries from scratch; byte-range resume isn't something I'd count on it providing out of the box. Either extend it or write the downloader; the figure already assumes the extended behaviour. Also note UE5 packaged builds default to IoStore containers (`.utoc/.ucas` alongside the `.pak`), so "download a pak" is usually "download a container set" — the manifest schema should allow that.

**Pak signing is the trust root, and it's per title.** Unreal's pak signing embeds a per-project public key in the executable; if the title ships with signing on, every mounted pak must be signed with that title's key. So "Sign, Version & Publish" in fig. 4 means the platform holds each title's private signing key and signs on the title's behalf. That's a key-management and multi-tenancy design that deserves its own paragraph in any spec, and it's a stronger tamper-proofing story than the SHA-256 check alone.

**Multiplayer is absent.** Everything in figs. 1 and 2 is one player, one client. In a networked title the server has to resolve and mount too, every peer needs the pak before a replicated dynamic class can spawn, and per-player personalisation (fig. 5) fights shared-world consistency the moment content has physics or collision. Either scope the filing/product to single-player and cosmetic-in-multiplayer, or add a server-authoritative resolve step with per-client cosmetic variation only.

**Anti-cheat and integrity tooling will see this as tampering.** Any title with EAC/BattlEye-style protection or its own pak-integrity checks needs the dynamic cache directory allow-listed and signature verification hooked in. Small, but it bites late.

**State preservation needs versioning.** Serialized interaction state is restored into "the replacement content" — which may be a different version with a different state schema. The Slot State Store wants a schema version per PakID+Ver and a migrate-or-discard rule, and save games that reference slot content should tolerate that content being evicted from the LRU cache.

**Offline and last-known-good.** The fallback path serves the placeholder when resolve fails. A cached, previously-verified pak is usually a better fallback than the placeholder; a "stale-OK for N hours" rule on the client-side manifest cache would cover flaky consoles and first-launch-on-a-plane.

### Where I'd push back — backend and product

**Figs. 4 and 5 disagree about where the decision is made.** Fig. 4 has the Auction Engine pre-compute "winner per slot per window" and write it to the metadata store; the runtime resolver just looks it up. Fig. 5 has the resolver retrieve *candidates* from the store, filter, score and choose at request time. Both are legitimate — offline allocation with online personalisation is a common two-stage design — but the figures should say which it is, or say explicitly that the allocation schedule produces the *eligible set* and the context engine picks within it. This is the one thing I'd fix before any claims are frozen, because claims that recite both without reconciling them are easy to attack.

**Resolve-per-overlap is chatty.** One request per slot per approach, plus a Lambda cold start on the path, is a latency and cost problem at scale. A batch resolve on level load for every slot in the level (or region), with TTLs, and re-resolve only near expiry or on a push, keeps the same architecture and fixes most of it. The Decision Cache in fig. 5 is server-side; the client wants one too.

**"Impressions" and "dwell" need a viewability definition.** Advertisers pay for viewable impressions, and the IAB / MRC guidelines for intrinsic in-game ads specify on-screen size, viewing angle, duration and occlusion. The telemetry emitter should compute those (screen-space coverage, angle to camera, unobstructed time) rather than "player was in the trigger". This is also where the "dwell" number stops being arguable.

**Budget pacing and frequency capping live in two different places.** Frequency capping is inside the adaptive scoring policy (fig. 5); budget consumption is nowhere. The auction needs telemetry-driven spend accounting so a campaign stops winning when its budget is gone, and pacing so it doesn't spend it all at 9 a.m.

**A kill switch is missing.** If a brand's content crashes clients, you need to stop serving it in seconds (resolver-side campaign disable), and the client needs a crash-loop guard (if the last session died with slot X mounted, don't mount X again until the resolver says a new version exists). Live-ops teams will ask for this on day one.

**Consent and age-gating are missing.** Fig. 5 scores on profile, preferences and behaviour. Behavioural targeting needs consent capture and regional rules (GDPR/ePrivacy, and children's-privacy law wherever the title is rated for minors), and a contextual-only fallback when consent is absent. The "pseudonymous identifier" line helps but doesn't replace the consent path.

**Physical merchandise probably can't go through the console's payment service.** Console and PC storefronts sell digital goods; physical fulfillment through the "Platform Payment Service" isn't a thing on most of them, and mobile stores actively require physical goods to use non-IAP payment. The physical branch of fig. 3 likely needs a companion-app / QR / web-checkout handoff rather than the platform-native purchase UI. The digital branch is fine.

**Platform holder policy is the real gate.** Runtime-loading third-party content that never went through the platform's own content pipeline touches certification, content-rating, and advertising-disclosure rules on every console. Technically the design can satisfy them (signed, moderated, rating-checked content), but this is a conversation to have early, and the answer shapes how much of the moderation stage has to be formal rather than heuristic.

### On the patent angle (not legal advice)

Nothing in the figure set is novel *in isolation*: runtime pak mounting, presigned CDN delivery, ad auctions, receipt-validated entitlements and context-aware ranking all exist. What reads as distinctive is the *combination*: a slot contract that lets arbitrary third-party interactive content (with collision, physics and commerce, not just a swapped billboard texture) be hot-loaded into a shipped title, governed by a lifecycle state machine that preserves interaction state across swaps, gated by validation-moderation-signing before the content is even biddable. Existing intrinsic in-game ad networks (Anzu, Bidstack, Frameplay and similar) mostly swap textures on pre-placed surfaces; user-generated-content platforms hot-load full content but own the whole runtime. The "interactive content + state-preserving swap + commerce try-on-to-entitlement" chain is where I'd expect the drafter to concentrate, and the fig. 4/fig. 5 reconciliation above matters most there.

### 🔴 DECIDE — questions only the team can answer

1. Cooking model: platform-run cook service, or brand-side cook against an SDK project?
2. Blueprint sandbox: allow-list of node classes and budgets — who owns that spec?
3. Scope: single-player only for v1, or server-authoritative resolve for multiplayer?
4. Decision point: pre-computed allocation, online context scoring, or the two-stage split?
5. Consent path: contextual-only by default, behavioural only with consent?
6. Physical merchandise: keep it in the filing with a web-checkout handoff, or drop it from v1?
7. Platform-holder conversation: who, and before or after the filing?

### What I'd do next — all FUTURE, nothing in flight

One written page per figure, in plain prose, that says what each box does, what it refuses, and what it emits. That is the "detailed description" a filing needs and the design doc an implementation needs; both are missing today. Fix the fig. 4/fig. 5 disagreement in the process.

Then, if the team wants proof it works: a vertical slice in UE5 that is deliberately small — one slot actor with the interface contract, a placeholder, the pre-fetch boundary, a downloader with resume, hash check, runtime mount of an IoStore container set, async class load, spawn, and a swap with state preservation. Backend can be a local HTTP server returning hand-written manifests. That slice answers questions 1–3 above with evidence instead of argument, and it's the kind of thing the mailbox workflow could take as a brief once the decisions are made.

---

*Everything above Part 2 is a reading of the six figures; if a figure and this text disagree, the figure wins. Diagrams copied unchanged from the Project on 2026-09-09.*
