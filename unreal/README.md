# The Unreal side — what is here and how to run it

*Written 2026-10-26 (brief 004), rewritten the same day for brief 006, and extended
2026-11-01 with the runtime client (brief 011), the two maps and the Player (brief 012), the
slot-map tool (brief 013), the interaction, the state store and the waypoint marker
(brief 016), and the region preview window (brief 017); extended again 2026-11-02 with the
lighting budget, the attract loop, the title menu, game switching and the X-ray view
(brief 018), and trimmed to **English only** the same day (brief 018E, Kavin's ruling: every
line the game draws is English, and the preview window's caption is one line). Plain-words
guide for a cold reader. Status of each item is marked **DONE / QUEUED / FUTURE**. The spec
this implements is `specs/unreal_spec_v1.md`.*

## What this folder is

`unreal/DCDemo` is the demo's Unreal project: a UE 5.7.4 C++ project made from the engine's
third-person template, plus the **DynamicContents** plugin, which is where everything specific
to this invention lives. The point of the first round of work (brief 004) was to prove one
thing end to end: **a packaged game that does not contain a piece of content can be handed that
content as a file while it is running, and put it in the world without restarting.** Brief 006
took that from two pieces to all thirteen, put the art at true size, and fixed what the first
round's screenshots showed was wrong.

| Path | What | Status |
|---|---|---|
| `DCDemo/DCDemo.uproject` | the project; plugin list, module list | DONE |
| `DCDemo/Config/` | map + game mode, the chunk settings that make content packs | DONE |
| `DCDemo/Source/DCDemo/` | the renamed third-person template (character, controller, game mode) | DONE |
| `DCDemo/Plugins/DynamicContents/` | the plugin. Two modules: the **runtime** one (file log, pack mounter, slot lifecycle, content actor, backend client, status strip, two run drivers) and the **editor** one (the slot-map tool) | DONE |
| `DCDemo/Content/DCCore/` | what the base game owns: master materials, the 8 emblems, the sample screen image and the **4-image screen set** a piece cycles through | DONE |
| `DCDemo/Content/Input/` | the template's input assets plus **`IA_DCUse`**, the Player's "use" action (the keys that trigger it are in `UDCInteractor`) | DONE |
| `DCDemo/Content/DCContent/<id>_<v>/` | one folder per piece-version = one content pack | DONE, all 13 |
| `DCDemo/Content/Maps/Spike` | brief 006's pack round-trip map: ground, sun, sky, player start, one slot per size class | DONE |
| `DCDemo/Content/Maps/DCRuntime` | brief 011's runtime-client map: the same ground and light, slots **A1 (L), A2 (T), A3 (S)** | DONE |
| `DCDemo/Content/Maps/GameA` · `GameB` | the demo's two maps: a warm plaza and a cool waterfront | DONE |
| `DCDemo/Content/DCEnv/` | the environment kit in the engine: 23 meshes and the two palettes' material instances | DONE |
| `DCDemo/Content/Player/` | `BP_DCPlayer`, `BP_DCPlayerController` and the character's one neutral material | DONE |
| `DCDemo/Content/Mannequin/` | the engine's UE4 mannequin, mesh and animations only (6.6 MB, no textures, no logo) | DONE |
| `Tools/` | the scripts below, plus `chunk_ids.json` | DONE |
| `_build/` | build outputs and logs (not in git, rebuilt by `package.ps1`) | — |
| `_packs/` | the content packs cut out of the build (not in git) | — |
| `spike/shots/engine_contact.png` | the contact sheet one pack round-trip run produces (the individual shots are git-ignored) | DONE |
| `spike/shots/004/` | brief 004's two screenshots and result file, kept as they were | — |
| `spike/shots/011/runtime_contact.png` | the contact sheet of brief 011's exit-test run | DONE |
| `spike/shots/012/maps_contact.png` | the contact sheet of both maps' walk-and-photograph runs | DONE |
| `spike/shots/013/` | the slot-map tool's evidence: both captures with the pins drawn on them, the five thumbnails, and the frame times before and after | DONE |
| `spike/shots/016/state_contact.png` | the contact sheet of the state-across-a-swap exit test | DONE |
| `spike/shots/018/` | brief 018's evidence: the lighting tables and before/after crops, the menu exit test's eight screenshots at 1600 × 900, the X-ray at 1080p, and the five re-captured slot thumbnails with the pins drawn on them | DONE |

## The five steps, in order

Each script is in `unreal/Tools/` and takes no arguments for the normal case.

1. **`make_project.ps1`** — builds `DCDemo` out of the engine's `TP_ThirdPerson` template,
   renaming it the way the project browser does (module, `*_API` macros, class redirects).
   Only needed once; it leaves an existing project's `Config` alone. **DONE**
2. **`import_content.py`** — run inside the headless editor; imports every piece listed in
   `Tools/chunk_ids.json` from `art/export/<id>_<v>/` into `/Game/DCContent/<id>_<v>/`
   (meshes, material instances from the manifest's colour table, `BP_DC_<id>_<v>`, the
   `PrimaryAssetLabel` that gives the folder its own cook chunk) and builds the test map.
   Writes `_build/logs/import_report.json` with everything it checked. **DONE**

   ```
   "E:\EpicGames\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" ^
     "E:\DynamicContents\unreal\DCDemo\DCDemo.uproject" ^
     -run=pythonscript -script="E:\DynamicContents\unreal\Tools\import_content.py" ^
     -unattended -nosplash
   ```
3. **`package.ps1`** — builds the editor, then `BuildCookRun` with chunks, pak and IoStore, and
   archives the build to `_build/archive/Windows`. **Shipping by default** — see the toolchain
   note below; `-SkipEditorBuild` if the editor is already current. **DONE**
4. **`stage_packs.ps1`** — moves the content chunks out of the packaged build into
   `_packs/<id>_<v>/` and writes a `pack.json` next to each. After this the build on disk
   genuinely does not contain the content. **DONE**
5. **`run_all_packs.ps1`** — runs the packaged game once, hands it every pack on the command
   line, and collects the log, the screenshots and the contact sheet. The game quits itself
   when it is done. **DONE**

Three more scripts belong to the runtime client (the section further down):
**`make_runtime_map.py`** builds `/Game/Maps/DCRuntime`, **`run_runtime.ps1`** runs the game
against the demo server, and **`ue_exit_test.py`** is the stage-1 exit test.
**`make_runtime_sheet.py`** turns a run's screenshots into one contact sheet.

And four belong to the two maps: **`make_maps.ps1`** (which copies the mannequin in and then
runs **`make_maps.py`**, which calls **`env_import.py`**), **`map_check.py`** (walk and
photograph one map with the server up) and **`make_maps_sheet.py`**.

Three more belong to the slot-map tool: **`register_games.ps1`** (server up, both maps
captured and registered), **`register_games.py`** (the editor Python it runs) and
**`make_slotmap_sheet.py`** (draw the pins on the captures and look at them).

Two belong to the state exit test: **`state_exit_test.py`** (plan v6 §14 step 6 — the server,
the packaged game and ten rounds of step 9) and **`make_state_sheet.py`**. And
**`core_extras.py`** is editor Python that both `import_content.py` and `make_maps.py` call,
so the base game's screen-image set and the Player's input action are defined once.

Two belong to the region preview window: **`run_preview.ps1`** (the second copy of the
build) and **`preview_frametime_test.py`** (plan v6 §11's soak: the same ten-minute tour
with and without it). And four to brief 018: **`light_sweep.py`** (what the lamps inside a
piece cost, one setting at a time), **`light_shots.py`** (the before/after crops of each
interior), **`menu_exit_test.py`** (the attract loop, the title menu, game switching and
the X-ray, in one run) and **`make_menu_sheet.py`** (its two contact sheets).

## How a content pack works

- Every piece-version lives in its own folder `/Game/DCContent/<id>_<v>/` with a
  `PrimaryAssetLabel` whose rules say "this folder is chunk 100 + n, always cook, **do not
  apply recursively**". Not applying recursively is what keeps the shared master materials,
  emblems and screen images in the base game instead of being copied into every pack.
- Which chunk belongs to which piece is **`Tools/chunk_ids.json`**, and it is frozen: a chunk
  id ends up in the file name the cook writes (`pakchunk<id>-Windows.pak`), so renumbering one
  silently re-points every pack already staged or signed. New pieces go on the end.
  `import_content.py` and `stage_packs.ps1` both read that one file, so they cannot disagree.
- Packaging therefore produces `pakchunk0-Windows.*` (the base game) plus one
  `pakchunk1NN-Windows.{pak,utoc,ucas}` set per piece-version.
- A pack is **all three files**: with IoStore on (the 5.7 default) the `.pak` is nearly empty
  and the assets live in the `.ucas`, indexed by the `.utoc`. `FPakPlatformFile::Mount` on the
  `.pak` picks up the sibling `.utoc` by itself, so the client mounts a pack with one call —
  but the server must keep the three files together.

## Units: the art is in centimetres

The art is authored in metres, because that is what the content spec's class limits and
clearances are written in, but the **FBX is written in centimetres** — Unreal's world unit — so
a piece imports at true size and nothing scales it at spawn (`ADCContentActor::ContentUnitScale`
is 1). **DONE**

Getting there took one non-obvious step. Blender's FBX exporter has no option that puts a scale
into the *vertex data*: `global_scale` and `apply_unit_scale` both put it on the exported node
transform. Unreal imports every part in its own local space — that is what makes a part's pivot
land on its socket — and in that mode `FFbxImporter::ComputeTotalMatrix` returns the geometric
transform only and throws the node transform away. A scale that lives on the node therefore
never arrives. So `dc_kit.export_piece` scales the mesh data itself by 100 for the length of the
FBX export and scales it back afterwards; the GLB is exported first and stays in metres, which
is what glTF means by its unit and what the portal's viewer expects.

Every manifest now carries a `units` block and `_cm` mirrors of its bounds and socket positions,
and both checkers compare against those: `art/tools/fbx_roundtrip.py` re-imports the FBX and
`import_content.py` reads the bounds back off every imported asset. The worst disagreement
across all 13 pieces is **0.004 cm**.

## Sockets arrive rolled 90°, and are rebuilt from the manifest

Blender writes FBX in its Y-up convention. Unreal's importer converts the mesh data back but
**not the socket rotations**, so every socket arrives with `roll = -90`. Left alone, every part
hangs off its socket lying flat: the sign and the screen are edge-on (a bright hairline across a
dark recess instead of a panel) and the door leaf lies on the floor inside its own frame. That
is what brief 004's screenshots were actually showing — it was never a material problem.

`import_content.py` therefore rewrites every socket's rotation from the manifest, which is the
authority anyway. Blender → UE is a mirror in Y, so a rotation about Z changes sign and nothing
else, and every socket in every manifest is a pure Z rotation; the importer fails loudly if that
ever stops being true. The same mirror is why the door's `open_sign` is negated on import — the
same swing is the opposite yaw in the engine.

## Logging: `Saved/DCLogs/`

Shipping compiles `UE_LOG` out, and until MSVC 14.44 is installed a Development *game* cannot be
linked on this PC at all, so no evidence this project produces can depend on the engine log.
`DC_LOG(Verbosity, …)` (in `Public/DCLog.h`) writes every line twice: through `UE_LOG`, and into
a plain text file under `<project saved dir>\DCLogs\`, opened on first use and flushed line by
line. `-DCLogFile=<path>` names the file, which is how `run_all_packs.ps1` gets a deterministic
one. Every call site in the plugin goes through it.

## Lumen: Detail Tracing, not Global Tracing

The unit change had a consequence nobody would have predicted. With the art imported at metre
scale, every mesh's distance field came out a handful of voxels across — Unreal sizes a
distance field from the asset's own bounds and assumes those are centimetres — so Lumen's
software ray tracing had almost nothing to trace. At true centimetres the distance fields are
full resolution for the first time, and the project's **Global Tracing** mode (which composes
them all into one global field) pushed this PC's GPU past its watchdog: a packaged run froze for
about 70 seconds and then died with exit code 3, leaving no crash dump, no log, and a trail of
`nvlddmkm` "GPU engine reset" entries in the Windows system log. Every piece over roughly 12,000
triangles did it; the same piece rendered fine at half resolution, which is what identified it as
GPU cost rather than as something wrong with the content.

`Config/DefaultEngine.ini` therefore sets `r.Lumen.TraceMeshSDFs=1` (Detail Tracing). Lumen
stays on and the look is unchanged. **DONE**

Two things about debugging this are worth knowing next time:

- A Shipping build has no console, so `-DCCvars="r.Name=Value,r.Other=Value"` sets console
  variables from the command line (`ADCSpikeGameMode::ApplyCvarOverrides`, and `-Cvars` on
  `run_all_packs.ps1`). It logs the before and after of each one. This is also how the booth PC
  will be tuned without a re-package.
- Do **not** try to do the same by writing an `Engine.ini` into the packaged build's
  `Saved\Config\Windows\`. The settings do not take effect, and the mere presence of the file
  makes the build fail the same way a GPU hang does — which will send you chasing the wrong
  thing. (It did.)

## What one run does

`run_all_packs.ps1` starts the packaged game once with every pack on the command line. For each
pack in turn the game mounts it, loads its Blueprint, spawns it at a slot whose size class
matches (the test map has one S, one L and one T slot), photographs it from a three-quarter view
outside and from `SOCKET_Inside` looking at the screen, destroys it, and moves on; then it writes
`spike_result.txt` and quits itself. The script builds `spike/shots/engine_contact.png` out of
the shots — that sheet is what goes in git; the individual PNGs are ignored.

## What the run proved (brief 006, 2026-10-26)

A packaged Shipping build that contains **none** of the thirteen pieces mounted all thirteen
from `_packs\`, loaded their Blueprints and spawned each one at a slot in **one run of 70
seconds**, without a restart or a loading screen. Every piece fitted its slot class, and every
piece produced both screenshots. From `spike/shots/spike_result.txt`:

| piece | chunk | slot | pak | utoc | ucas | mount | load | spawn |
|---|---|---|---|---|---|---|---|---|
| content1_v1 | 100 | L | 339 B | 3,821 B | 740,160 B | 16.5 ms | 4.6 ms | 0.7 ms |
| content1_v2 | 101 | L | 339 B | 3,749 B | 653,168 B | 15.0 ms | 3.5 ms | 0.7 ms |
| content2_v1 | 102 | L | 339 B | 3,881 B | 1,365,312 B | 14.5 ms | 5.4 ms | 0.6 ms |
| content2_v2 | 103 | L | 339 B | 3,689 B | 861,248 B | 15.4 ms | 4.2 ms | 0.6 ms |
| content3_v1 | 104 | T | 339 B | 3,881 B | 724,688 B | 14.7 ms | 4.5 ms | 0.7 ms |
| content3_v2 | 105 | T | 339 B | 3,809 B | 825,280 B | 14.2 ms | 3.6 ms | 0.6 ms |
| content4_v1 | 106 | S | 339 B | 3,485 B | 468,400 B | 20.4 ms | 2.7 ms | 0.6 ms |
| content4_v2 | 107 | S | 339 B | 3,581 B | 568,800 B | 14.8 ms | 3.3 ms | 0.6 ms |
| default_v1 | 108 | S | 339 B | 1,378 B | 63,824 B | 15.8 ms | 1.1 ms | 0.4 ms |
| rival1_v1 | 109 | L | 339 B | 3,771 B | 792,352 B | 13.8 ms | 4.0 ms | 0.6 ms |
| rival2_v1 | 110 | L | 339 B | 3,591 B | 815,936 B | 15.6 ms | 3.5 ms | 0.8 ms |
| rival3_v1 | 111 | L | 339 B | 3,759 B | 837,408 B | 16.8 ms | 4.4 ms | 0.8 ms |
| rivalsmall_v1 | 112 | S | 339 B | 3,523 B | 505,392 B | 15.3 ms | 2.8 ms | 0.6 ms |

Thirteen packs are **8.9 MB** in total; the base game is 1.24 GB. Mount is 14–20 ms whichever
pack it is (it is a file-system operation, not a read of the content), load is 1–6 ms and
scales with the piece, and the spawn — which includes building the whole piece out of its
sockets, wiring the brand into the materials and placing the lights — is under a millisecond
every time.

The picture of all of it is `spike/shots/engine_contact.png`.

---

# The runtime client (brief 011): the game talks to the server

Brief 006 proved a pack can be mounted when it is handed to the game on the command line.
Brief 011 is the real thing: the game **asks a backend what belongs in a slot**, downloads it,
checks it and puts it there, while it is running. Nothing is handed to it.

## The classes

| Class | Job | Status |
|---|---|---|
| `UDCSubsystem` (GameInstanceSubsystem) | backend address and region from the command line; `GET /client-config` once; `GET /changes` every 1.5 s; `GET /resolve` and the signature check; the downloads, the SHA-256 of every file, the LRU pack cache, the mounting; telemetry batching; the status file | DONE |
| `ADCSlot` | the slot lifecycle exactly as the figure — IDLE → RESOLVING → DOWNLOADING → VERIFYING → MOUNTING → ACTIVE, with SWAP PENDING while the Player is inside the bounds box and ERROR / FALLBACK with backoff | DONE |
| `ADCRuntimeGameMode` | starts the client, draws the status strip, and (for a test) photographs every change | DONE |
| `ADCStatusHud` | the status strip, the interaction prompt, the waypoint marker and — brief 018 — the attract line, the title menu, the pause menu and the fade | DONE |
| `FDCCrypto` | RS256 over the signed payload, SHA-256 per file | DONE |
| `FDCPackCache` | one folder per pack under `Saved\DCPacks\`, least-recently-used eviction, purge on a booth reset | DONE |
| `FDCManifest` | the parsed, verified manifest | DONE |
| `UDCInteractor`, `UDCStateStore` | brief 016: the Player uses the content, and what they do survives a replacement | DONE |
| `FDCPreviewWindow` | brief 017: the region preview window's borderless placement on the portal's monitor | DONE |
| the live flip | brief 017: the fallback for tour step 7 — the **main** game plays as another region for twenty seconds | DONE |
| `UDCShell`, `UDCShellInput` | brief 018: the attract loop, the title menu, the pause menu, game switching, and the pad and keyboard that drive them | DONE |
| `FDCXray` | brief 018: the X-ray overlay — pre-fetch rings, the manifest, the cache, the lifecycle log and the frame-time graph | DONE |

`ADCSpikeGameMode` is untouched apart from one guard (see "A Shipping build ignores the map"
below), so `run_all_packs.ps1` still does exactly what brief 006 reported.

## Run it

```powershell
# the plain runner: server + game, no allocations, so the slots show the attract rotation
powershell -ExecutionPolicy Bypass -File unreal\Tools\run_runtime.ps1 -Seconds 60

# the stage-1 exit test: ten hand-written allocations, a pass/fail table and a shot per round
server\.venv\Scripts\python.exe unreal\Tools\ue_exit_test.py

# the contact sheet of whatever the last exit test did
python unreal\Tools\make_runtime_sheet.py
```

Both start the server themselves on a clean data folder, run the packaged game against it, and
stop everything. The command line the game takes:

| Switch | What |
|---|---|
| `-DCBackend=http://127.0.0.1:8700` | where the backend is (this is the default) |
| `-DCGame=A  -DCRegion=r1` | which game and region this copy plays as (defaults) |
| `-DCFollowRegion` | follow `GET /preview/region`, so the portal can move this copy live |
| `-DCMap=/Game/Maps/DCRuntime` | which map (**not** a bare map name — see below) |
| `-DCCacheDir=<dir>` | the pack cache; default `Saved\DCPacks\` |
| `-DCStatusFile=<path>` | a JSON file, rewritten 4× a second, that a test script can watch |
| `-DCShotDir=<dir>` | photograph every change into this folder |
| `-DCQuitWhenFileExists=<path>` · `-DCRunSeconds=<n>` | how the run ends without killing a process |
| `-DCRangeBytes=<n>` | bytes per range request (default 262144; 0 = whole files) |
| `-DCUiScale=<f>` · `-DCNoStrip` | the status strip |
| `-DCPreview` | this copy is the **region preview window** — see its own section below |
| `-DCTourFor=<seconds>` | keep the scripted tour going round for at least that long |

## What the exit test proved (brief 011, 2026-11-01)

Ten allocations written by hand through `POST /admin/allocate`, against **one** packaged
Shipping build that contains none of the content, in **one run with no restart and no loading
screen**: **10 / 10**.

| # | slot | region | what | what appeared | s to visible |
|---|---|---|---|---|---|
| 1 | A1 | r1 | hand allocation, large slot | content1 v1 `#E23D3D` star | 4.7 |
| 2 | A2 | r1 | tall piece in the tall slot | content3 v1 `#E23D3D` star | 5.3 |
| 3 | A3 | r1 | small piece in the small slot | content4 v1 `#E23D3D` star | 4.4 |
| 4 | A1 | r1 | swap: another piece into a full slot | content2 v1 `#E23D3D` star | 4.4 |
| 5 | A1 | r2 | second region, pack already cached | content1 v1 `#E23D3D` star | 0.4 |
| 6 | A2 | r2 | tall piece, second region | content3 v1 `#E23D3D` star | 0.5 |
| 7 | A1 | r2 | push version 2 onto the live allocation | content1 **v2** `#E23D3D` star | 5.3 |
| 8 | A1 | r2 | new brand on the same allocation | content1 v2 **`#2F6FEB` chevron** | 0.2 |
| 9 | A3 | r2 | corrupt pack | the **default stayed up**, then content4 v2 `#2F6FEB` chevron | 7.4 |
| 10 | A3 | r2 | rival block (identity from server config) | rivalsmall v1 `#F28C28` ring | 1.2 |

**Allocation written → visible in game** splits cleanly in two, because the server paces every
download to about four seconds whatever the pack weighs:

- a pack the game has never seen: **4.4 – 5.3 s** (poll + resolve + ~4 s paced download +
  verify + mount + spawn);
- a pack already in the cache: **0.2 – 1.2 s**, which is almost all poll latency — the work
  itself is 20–45 ms.

Round 9 is 7.4 s because it is two attempts: a ~4 s download whose `.pak` fails its SHA-256, a
two-second backoff, and a retry that only has to re-fetch the 339-byte file the first attempt
threw away. The default was on screen the whole time — `16_A3_default_v1.png` catches the
status strip reading `A3 S DOWNLOADING default v1 no-brand`.

The picture of all of it is `spike/shots/011/runtime_contact.png`.

## How a slot gets its content

1. `GET /changes?game=A&region=r1` every 1.5 s returns one short key per slot. **A slot whose
   key has not changed is not asked about** — a quiet booth makes one small request and
   nothing else.
2. `GET /resolve?game=&slot=&region=` returns the **signed-payload envelope**
   (`server/README.md`): the manifest as a string, plus RS256 over the exact UTF-8 bytes of
   that string. The client verifies the bytes, *then* parses them; it never has to reproduce
   the server's canonical JSON.
3. Every file of the pack is fetched as **byte ranges** (256 kB by default), appended to a
   `.part` file. Resuming is therefore the normal path and not a special case: a dropped
   connection leaves the `.part` at a clean boundary and the next attempt carries on from
   exactly there. A file already in the cache at the right size is not fetched at all.
4. **VERIFYING** hashes every file of the pack with SHA-256 and compares it to the manifest —
   including the cached ones, so a cached file that has gone bad is caught too. A mismatch
   deletes that file (so the retry is a real download), and the slot falls back.
5. **MOUNTING** is brief 006's `UDCPackMounter`, then `StaticLoadClass` on the manifest's
   class path. A pack is mounted once per run however many slots use it.
6. The piece is spawned **deferred**, so the brand colour and emblem are set before
   `BeginPlay` builds it — otherwise the first frame would show the pack's own identity.
7. `mount` and `view` telemetry are batched and posted to `/telemetry`. A view is content on
   screen, within 30 m, for at least a second, with a line check — plan v6 §9. The 30 m is
   measured to the nearest point of the **piece's own bounds**, not to the middle of it: a T
   slot's content is 20 m tall, so a Player standing a comfortable 25 m from its door is 32 m
   from its centre, and measuring to the centre quietly threw that view away (fixed in brief
   013). The line-of-sight check still aims at the middle, which is the right place to ask
   "can it be seen from here".

Failures never reach the visitor: the slot keeps whatever is on screen, logs why, and retries
with a doubling backoff (2, 4, 8 … capped at 15 s).

## Which crypto, exactly

`specs/unreal_spec_v1.md` §3 said "RS256 via the engine's platform crypto" and left the API
open. It is the **PlatformCrypto** plugin (`Engine/Plugins/Experimental/PlatformCrypto`,
`EnabledByDefault`, OpenSSL underneath) — the same modular feature the engine's own `FRSA`
facade, the one pak signing uses, is built on:

```
IPlatformCrypto::Get().CreateContext()            -> TUniquePtr<FEncryptionContext>
FEncryptionContext::GetPublicKey_RSA(pem)         PEM_read_bio_RSA_PUBKEY - the server's
                                                  "BEGIN PUBLIC KEY" block is read as it is
FEncryptionContext::CalcSHA256(payload, digest)   and FSHA256Hasher Init/Update/Finalize for
                                                  files, a megabyte at a time
FEncryptionContext::DigestVerify_RS256(digest,    RSA_verify with NID_sha256, i.e. PKCS#1 v1.5
                                 signature, key)  + SHA-256
```

Two things are worth knowing. `DigestVerify_RS256` takes the **digest**, not the message — the
32 bytes of SHA-256 over the payload — which is why `FDCCrypto::VerifyRs256` is two steps. And
`FPlatformMisc::GetSHA256Signature` exists in `Core` but **has no Windows implementation**
(the generic one asserts and returns false), so the hashing goes through the same context.

`FDCCrypto::IsAvailable` runs a known-answer SHA-256 self-test at startup and logs the result,
so "the crypto is there" is never a guess.

Naming `PlatformCrypto` in `DynamicContents.Build.cs` is not enough: the headers resolve
through its public dependencies, but the link does not find `FEncryptionContextOpenSSL`'s
exports unless **`PlatformCryptoContext`** and **`PlatformCryptoTypes`** are named as well.

## A Shipping build ignores the map on the command line

`DCDemo.exe /Game/Maps/DCRuntime` silently loads the *default* map instead.
`UGameInstance::StartGameInstance` throws the command line away before it looks for a map:

```cpp
#if UE_BUILD_SHIPPING && !UE_SERVER && !UE_ALLOW_MAP_OVERRIDE_IN_SHIPPING && !ENABLE_PGO_PROFILE
	// In shipping don't allow a map override unless on server, or running PGO profiling
	Tmp = TEXT("");
#endif
```

`UE_ALLOW_MAP_OVERRIDE_IN_SHIPPING` would fix it, but it has to be defined when the *engine's*
`GameInstance.cpp` is compiled, and an installed engine ships that object precompiled. So:
every run starts in `GameDefaultMap`, which is the spike map, and **`-DCMap=<package path>`**
makes `ADCSpikeGameMode` travel straight out of it with
`UGameplayStatics::OpenLevel`. A client travel is not gated, and the target map's own
*GameMode Override* (World Settings) picks up `ADCRuntimeGameMode`. A run with no `-DCMap` is
brief 006's run, unchanged. The map is built by `unreal\Tools\make_runtime_map.py`, which sets
that override.

While chasing this: a Shipping build's "project saved dir" is **`%LOCALAPPDATA%\DCDemo\Saved`**,
not a folder next to the build. That is correct for a shipped game, and it is why the runners
pass `-DCLogFile=`, `-DCCacheDir=` and `-DCStatusFile=` explicitly — so the evidence of a run
lands next to the build instead of in the user profile.

---

# The two maps and the Player (brief 012)

Plan v6 §3 asks for one packaged build with **two neutral, untitled maps that clearly read as
two different games**. They are two different *places*, not one place twice, and the difference
is carried by three things at once: **layout**, **palette** and **light**. All three come out
of the same 23-piece environment kit (`art/blender/env/`, which has its own README), so
nothing had to be modelled twice.

Name-agnostic, as CLAUDE.md rule 3 requires: **no text, no signs, no logos and no names** are
placed anywhere in either map. The only lettering the demo ever shows is the status strip the
plugin draws. The engine's mannequin wears the engine's logo on its chest, so the Player's
materials are replaced with one plain neutral one and the logo asset is never copied into
this repo at all.

## Game A — the plaza (warm)

**180 × 110 m, 292 actors.** Sandstone paving, terracotta roofs, green trees, a high midday
sun at 5,900 K and the lightest of hazes.

- a **64 × 64 m plaza** of 8 m slabs, with arcades down its east and west sides, a fountain,
  benches, bollards and trees;
- **A1 (L)** stands on a raised terrace at the north of the plaza, reached by a 16 m flight of
  steps — it is the first thing you see from the spawn, 34 m dead ahead, which is right for the
  slot with the highest footfall;
- a **24 m avenue** running 60 m east between double rows of trees and lamp posts, with
  **A2 (T)** closing it as a landmark;
- a **path west into a walled garden court**, with **A3 (S)** in it;
- the spawn is on the plaza, facing A1.

## Game B — the waterfront (cool)

**106 × 80 m, 178 actors.** Slate paving, timber decking, blue water, a low late-afternoon sun
at 4,900 K and more haze — it is over water.

- a **timber boardwalk promenade** 72 m along a quay wall, with slate paving behind it;
- **B1 (L)** on the promenade;
- a **pier** running 30 m out over the water on timber piles, railed both sides, widening to a
  head where **B2 (S)** stands;
- sheds, bollards, lamps and a row of cool-grey blocks behind.

It is not a re-skin: different ground (water), different deck material, different sun angle,
different building rhythm, a different shape of place.

## Both maps

- **no dark horizon band**: a 600 m ground plane, a sky atmosphere whose *ground albedo* is set
  to the palette's own ground colour (its default is nearly black, which is what the band
  actually is), and a thin exponential height fog. The fog is there to stop the ground meeting
  the sky in a hard line, not to be weather;
- **invisible bounds**: hidden, shadowless, blocking boxes round the playable area. Game B's
  ring deliberately has **no south wall** - the quay wall and the pier's own side walls do that
  job, and a ring wall across the waterfront would also have walled off the pier;
- every slot is an `ADCSlot` of its size class, standing on a pad of its own size -
  **`slot_pad`** (14 m) for an L or a T, **`slot_pad_s`** (7 m) for an S. The packaged
  build contains **none** of the content, so between the map loading and the backend's first
  answer a slot is empty: the pad is what makes that read as a place waiting for something.
  What then fills it is the server - the attract rotation serves the developer's `default` (or
  a rival) within a few seconds of the first poll, over HTTP, exactly as at the booth.
  (An S slot used to stand on the 14 m pad scaled to 0.5, which halved the width of its kerb
  band with it and made the pad read as a model of a pad; brief 013 gave it its own piece.);
- the maps are built by **`unreal/Tools/make_maps.py`**, data plus small loops, so a layout
  change is a number and both maps are reproducible from the repo with no hand editing. The
  slot ids match `server/config/demo.json`.

## The Player

Third person with a visible character: the engine's **UE4 mannequin** out of the shared
`Mannequin` template content pack. Only the mesh, its skeleton, its physics asset and the ten
animation assets are copied - **6.6 MB, no materials and no textures**, because the mannequin's
chest-logo material is a logo and `env_import.dress_mannequin` replaces both of its material
slots anyway. That also keeps 30 MB of 4K textures and 25 MB of the second character out of
the repo.

Both slots get the **same** material instance - `MI_DC_Char_Neutral`, a light warm grey with
a slight sheen. Brief 012 gave them two different tones, which turned the Player into a
two-tone figure whose darker patch sat exactly where the engine's logo used to be: it still
read as a badge. One tone over the whole figure reads as a deliberately neutral character
rather than as an asset that has lost its textures.

`BP_DCPlayer` (a child of the template's `ADCDemoCharacter`, which carries the Enhanced Input
actions) and `BP_DCPlayerController` (which adds the input mapping contexts) are built by
`env_import.make_player_blueprints` and read back off disk afterwards, because setting a CDO
is the sort of thing that fails quietly.

`ADCRuntimeGameMode` names both of them by **soft path**
(`/Game/Player/BP_DCPlayer.BP_DCPlayer_C`, overridable with `-DCPawn=` / `-DCController=`), so
the plugin keeps no link dependency on the game module. The cook does not follow a soft path,
which is why `/Game/Player` and `/Game/Mannequin` are in `DirectoriesToAlwaysCook`.

## What the walk-and-photograph run proved (brief 012, 2026-11-01)

```powershell
server\.venv\Scripts\python.exe unreal\Tools\map_check.py --game A
server\.venv\Scripts\python.exe unreal\Tools\map_check.py --game B --region r2
python unreal\Tools\make_maps_sheet.py
```

Each run starts the demo server on a clean data folder, writes **one visitor allocation per
slot**, starts the packaged Shipping build on that map with `-DCTour`, and lets the game take
an overview shot, a framed shot of every slot, then **walk the Player from the spawn to each
slot and in through its door** with a shot from the door and one from inside. The game writes
its own `dc_tour.json` and both it and the server stop themselves.

| | Game A | Game B |
|---|---|---|
| map | 180 × 110 m, 292 actors | 106 × 80 m, 178 actors |
| slots filled | A1 content1 v1 · A2 content3 v1 · A3 content4 v1, all in the visitor's brand | B1 content2 v1 · B2 content4 v2 |
| walk | **9 / 9 legs arrived** | **6 / 6 legs arrived** |
| frame time at 1600 × 900 | average **12.47 ms (80 fps)**, median 12.96, **worst 1 % 19.05**, worst 26.05 (7,252 frames) | average **11.33 ms (88 fps)**, median 11.10, **worst 1 % 17.66**, worst 29.94 (3,899 frames) |
| restarts / loading screens | 0 / 0 | 0 / 0 |

A "leg" is one of *to the door*, *in through the door*, *back out*. The longest is A3's: 156 m
of walking out of the plaza, down the avenue, back west and into the garden. Frame times
exclude the first four seconds and any frame within half a second of a shutter.

**Headroom:** the region preview window of plan v6 §11 is a second copy of this build at 30 fps
and half resolution. The main game has 80–88 fps of its own at full resolution here, so there
is room on paper; the soak test in plan §14 step 5 is what decided it — see the preview
window's own section below.

The picture of all of it is `spike/shots/012/maps_contact.png`.

## The walk is waypoints, not a navigation mesh

`ADCSlot::ApproachPath` is a short list of world-space waypoints the map builder sets, and
`ADCRuntimeGameMode`'s tour walks them with `AddMovementInput`, sliding sideways when it stops
making progress. These maps are written by a script, so the way round the arcades and down the
avenue is known when the map is written; a navigation mesh needs a brush volume, which is
awkward to place from Python, and nothing in the demo needs path-finding at runtime.

It is also a real collision test, and it found three things a camera never would: a flight of
steps with a wall across it every four metres, a background block sitting on the garden path,
and a boundary wall across the mouth of the pier. All three are fixed in the data.

---

# The slot-map tool (brief 013): the developer's half of the plugin

Everything above is the *player's* side and the *brand's* side. Plan v6 §6 is the third actor
in the story: **the game developer**, who registers the game, its slots and the rule for each
slot. Until that happens the portal can only draw a picture of a slot map; afterwards a brand
is looking at a photograph of the spot it is bidding on.

It is a second module in the same plugin, `DynamicContentsEditor`, type **Editor** — so none
of it is compiled into the game, let alone shipped in it.

| Class | Job | Status |
|---|---|---|
| `UDCSlotMapTool::RegisterCurrentLevel` | the whole tool: the captures, the measurements, the JSON, the upload | DONE |
| `FDynamicContentsEditorModule` | the menu entry *Tools → "Register this game with Dynamic Contents…"* | DONE |
| `UDCRegisterGameCommandlet` | the headless entry, one map per run | DONE |
| `unreal/Tools/register_games.py` | editor Python: both maps in one editor session | DONE |
| `unreal/Tools/register_games.ps1` | server up, both maps captured and registered, server down | DONE |
| `unreal/Tools/make_slotmap_sheet.py` | draws the pins on the captures so a human can check them | DONE |

One function behind three doors, because plan v6 §6 asks for a button *and* a headless run:
the thing a developer presses has to be the thing that was tested.

## What one run does

```powershell
powershell -ExecutionPolicy Bypass -File unreal\Tools\register_games.ps1
powershell -ExecutionPolicy Bypass -File unreal\Tools\register_games.ps1 -NoPost   # look first
python unreal\Tools\make_slotmap_sheet.py
```

For the level that is open:

1. a straight-down **orthographic** capture of the playable area, 2048 px on the long side;
2. every `ADCSlot` read off the map: id, size class and class limits, **rating rule**,
   pre-fetch radius, world position;
3. each slot's **pixel position** on that capture;
4. an **eye-level thumbnail** per slot (1.7 m, 16:9, 960 px) with the slot's content hidden;
5. `POST /games/register` as one multipart request.

It spawns nothing into the level: the capture component and the fill lights are outered to
the world and transient, no asset is saved and no package is marked dirty.

## Five things that are not obvious

**`-AllowCommandletRendering` is not optional.** A commandlet runs with rendering switched
off unless it is asked for, and this tool's whole job is to render two kinds of picture.
Without it `FApp::CanEverRender()` is false and the tool refuses rather than writing a black
PNG. The first headless run also pays a one-off ten-minute bill compiling the editor's SM5
and SM6 shader maps into the DDC; the second takes about a minute.

**The playable area is a tag, not a guess.** `make_maps.py` puts the actor tag
**`DCPlayableArea`** on every invisible bound it builds, and the capture rectangle is the
union of those. The walls round where the Player can go *are* the playable area. A level that
has never heard of this plugin falls back to "every visible primitive under 400 m across",
which throws away the 600 m ground plane and keeps the buildings.

**Pixel positions come out of the camera, not out of a formula.** The tool asks the capture
camera's own transform where a slot is (`InverseTransformPosition` → u, v), so the number and
the picture cannot drift apart — and it picks the camera yaw that makes the long axis of the
level the long axis of the image, so a capture is landscape whichever way round the level was
built. `make_slotmap_sheet.py` then draws those numbers back onto the picture, which is the
only honest way to check them.

**There is no Lumen in a headless editor, so the tool lights its own subject.** This project's
ambient light *is* Lumen (see "Detail Tracing" above), Lumen's scene is built and maintained
by the main renderer across frames, and a commandlet has no viewport and therefore no frame
for it to live in. A scene capture on its own gets direct light and nothing else: the first
run of this tool produced pictures in which every surface the sun did not reach was **pure
black**, and Game B's low afternoon sun made a near-black photograph of a perfectly well-lit
promenade. The sky light does not rescue it either — its real-time capture belongs to the
same missing frame. So the tool adds three shadowless directional lights for the duration,
sized against the map's own sun: one overhead, one into the shadow side, one across. They are
destroyed when it returns.

**The two pictures are lit for two different jobs.** A thumbnail keeps the fog, the sky and
the cast shadows, because it has to look like the place. The **plan view turns the cast
shadows off**, which is both a necessity and a kindness: Lumen does not support an
orthographic projection at all, and Game B's sun sits at 21° above the horizon, so with
shadows on the map is mostly 60 m streaks of black. What is left is a site plan — evenly lit,
every roof and every path legible. Both let the exposure adapt (pinning it blows out the
midday plaza or blacks out the evening waterfront) but wind the adaptation speed right up, so
it settles inside the four warm-up captures instead of drifting.

## What the run produced (2026-11-01)

| | Game A | Game B |
|---|---|---|
| playable area | 196.0 × 126.0 m, from 4 tagged bounds | 94.0 × 74.2 m, from 8 tagged bounds |
| capture | 2048 × 1316 px of 201.9 × 129.7 m | 2048 × 1616 px of 96.8 × 76.4 m |
| camera | 134 m up, orthographic | 134 m up, orthographic |
| slots | A1 L (0.426, 0.546) · A2 T (0.842, 0.454) · A3 S (0.168, 0.762) | B1 L (0.376, 0.658) · B2 S (0.665, 0.109) |
| thumbnails | 3 × 960 × 540, eye level 1.7 m, 11 / 11 / 8 m out | 2 × 960 × 540, eye level 1.7 m, 11 / 8 m out |
| `POST /games/register` | **200** | **200** |

Every pin sits on its slot — `spike/shots/013/A_map_pins.png` and `B_map_pins.png` are the
captures with the registered positions and the class footprints drawn on top, and
`slotmap_contact.png` is both of them with all five thumbnails.

What the server did with it is `server/README.md`: the files land in `server/config/maps/`,
**committed**, so a clean checkout serves the real map and the real thumbnails with no Unreal
anywhere in sight, and the registered pin positions replace the hand-guessed `px` values that
were in `demo.json`.

---

# The Player uses the content, and what they do survives a swap (brief 016)

Everything up to here is about getting content into a slot. Plan v6 §14 step 6 is about what
happens **while somebody is standing in it**: the Player can use the door, the switches and
the screen, and when the backend replaces the content under them, nothing changes until they
walk out — and when they walk back in it is as they left it.

| Class | Job | Status |
|---|---|---|
| `UDCInteractor` (ActorComponent on the pawn) | what is in reach, what the prompt says, and what the button does; posts an `interaction` event per use | DONE |
| `UDCStateStore` (GameInstanceSubsystem) | saves the four things schema 1 keeps, keyed by slot + content id; restores them on any version of the same content; discards a mismatched schema | DONE |
| `ADCContentActor` | the door swings, the switches toggle their group, the screen steps through the base game's image set | DONE |
| `ADCStatusHud` | adds the context prompt and the waypoint marker to the strip | DONE |
| `ADCSlot` | saves on unload, restores on spawn, counts `visit` and `dwell`, arms the waypoint marker | DONE |
| `ADCRuntimeGameMode` | `-DCStateTest=<rounds>`: the whole of step 9, as many times as asked | DONE |

## Why the input had to be Enhanced Input, and why the keys are not an asset

A Shipping build with the Enhanced Input plugin enabled processes **no legacy key bindings at
all**. `UEnhancedPlayerInput::EvaluateInputComponentDelegates` says so in a comment — "we only
want to process enhanced input components in this subclass" — and the debug key bindings that
look like an escape hatch are behind `DEV_ONLY_KEY_BINDINGS_AVAILABLE`, which Shipping does
not have. So `InputComponent->BindKey` was never going to work, and the plugin binds the way
the engine wants: it makes its own `UEnhancedInputComponent`, binds `IA_DCUse` to
`ETriggerEvent::Started` on it, and **pushes it onto the player controller's input stack**.
On the controller rather than on the pawn, because the pawn is a Blueprint in the game
module's content and this plugin must not need to touch it.

The **keys** are in C++ (`EKeys::E` and `EKeys::Gamepad_FaceButton_Bottom`) and only the
`UInputAction` is an asset. `FKey`'s `KeyName` is a private `UPROPERTY`, so editor Python
cannot build an `FKey` at all — `unreal.Key("E")` is *"call() takes at most 0 arguments"* —
and `UInputMappingContext::MapKey` needs one. Rather than hand-author an asset nobody could
rebuild, `UDCInteractor::BindInput` makes the mapping context at runtime. Which is the better
place anyway: the keys sit next to the binding that answers them. `-DCInteractContext=<path>`
takes a project's own context instead.

`unreal\Tools\core_extras.py` builds `IA_DCUse` and imports the screen image set, and is
called by **both** `import_content.py` and `make_maps.py` so either half of the pipeline
produces them. `/Game/Input` had to join `DirectoriesToAlwaysCook` for the same reason
`/Game/Player` did: the action is loaded by soft path and the cook does not follow one.

## What is in reach, and which of two things 38 cm apart the prompt means

Reach is **5 m, measured from the Player**, not from the camera — a third-person camera is
several metres behind the character and measuring from it would put the whole room in reach.
Five metres is what it takes to be able to stand at a door: the place to stand is 2 m clear
of the front of the piece, on its centre line, the door is about a metre off that line, and
the walk that gets there accepts 1.1 m of slack.

The two light switches are **38 cm apart on the same wall**, so distance alone cannot tell
them apart from a metre and a half away — but the angle between them from there is about 14°,
which easily can. The prompt therefore picks the lowest `distance × (1 + 3(1 − cos))`, and
anything more than ~75° off the middle of the screen is not a candidate at all.

Two things this cost, both written down because they are the sort that look like nothing:

- the door's prompt is anchored on the **hinge**, not on the leaf. An open leaf has swung a
  metre into the room, which moves the thing the reach is measured to — so the first run had a
  Player standing at an open door being told it was out of reach, by **one centimetre**;
- the prompt is chosen from the **camera's** view point, and the camera is a spring arm that
  catches up a frame later. A scripted run that turns and presses in the same tick is pressing
  with the prompt still showing whatever was in front of the Player before they turned. The
  test turns, waits a tick, then presses.

## What survives, and what must not

`UDCStateStore` keeps `{lights A, lights B, door, screen image index}` — the manifest's own
`state_schema` — against a key of **slot + content id**. Three rules, and they are the class:

- **no version in the key**, because "version 2 picks up where version 1 left off" is the
  whole promise. The exit test alternates v2 / v1 / v2 on purpose: each is a real new version
  (`version_n` goes up every time) and version 1 coming back after version 2 restores the
  state just the same;
- **the slot is in the key**, because the same content in another slot is another building;
- the **schema version is in the record and checked on the way out**. A mismatch discards the
  record and logs it rather than half-applying it. v1 and v2 of everything in this demo share
  schema 1, so that path is exercised by a test and not by the demo — which is exactly why it
  has to be written down.

The restore happens **before `FinishSpawning`**, next to where the brand is set, so the piece
is built already holding what the Player left rather than showing a frame of its own defaults.
The save happens in `ADCSlot::DespawnContent` **before** `Destroy()` — UNLOAD & PRESERVE, in
that order, because once the actor is gone there is nothing left to ask.

A **different** piece arriving in the slot gets its own defaults, and the test checks that
explicitly: when the block ends and the region's rival takes it, the rival must not be
standing there with the visitor's lights on.

## The door swings; nothing else is animated

`ADCContentActor` ticks only while a leaf is moving (190°/s, so about half a second for 90°)
and turns its own tick off again when it stops. The door is the one piece of state a Player is
standing next to when they press the button, and an instant 90° reads as a glitch rather than
as a door; a slot nobody is touching still costs no tick. Every piece's manifest already said
`"swings": "inward"`, and `import_content.py` negates the sign on import because Blender → UE
is a mirror in Y — so the leaf really does swing into the room, which is what makes it safe to
stand in front of a door and open it.

## The screen's images belong to the base game

`art/samples/screens/screen_1..4.png` → `/Game/DCCore/Screens/T_DC_Screen_<n>`, handed to a
piece at spawn by `UDCSubsystem::GetScreenImage`. A pack never carries a screen image: it is a
runtime input exactly like the brand colour and the emblem. That is also what lets "which image
is showing" survive an update — the **number** survives, and the number is all the piece keeps.
Four images, each a different dominant colour *and* a different shape, so "the screen is on
image 3" is readable in a 1600 × 900 screenshot from across a room. The set is counted by
loading until one is missing, so a fifth image is a build step and nothing else.

## The waypoint marker

When a slot's content changes, `ADCSlot` arms a marker; `ADCStatusHud` draws a small diamond
at the piece's own `SOCKET_Waypoint` with the slot id and the distance under it, clamped to
the screen edge when the slot is behind the Player. It clears when they get within 22 m of the
content's bounds, or after 75 seconds, so it is never clutter. It is a **shape and a number**
and nothing else: no ad and no money language ever reaches the Player's screen (plan v6 §3),
and a wordless marker cannot become either in another language. `-DCNoMarker` turns it off;
`-DCNoStrip` now turns off only the status strip, because the prompt and the marker belong to
the game rather than to the demo's instrumentation.

## How the exit test is driven

```powershell
server\.venv\Scripts\python.exe unreal\Tools\state_exit_test.py
server\.venv\Scripts\python.exe unreal\Tools\state_exit_test.py --rounds 3 --plan push,end,push
python unreal\Tools\make_state_sheet.py
```

The game drives itself and the script drives the backend, and they meet at one file:

| the game writes | the script does |
|---|---|
| `phase: waiting`, round *n* | make sure the visitor's content is allocated to the slot |
| `phase: armed`, round *n* | push a new version, **or** `POST /admin/end-block` |

The game is told neither which it was nor what to expect. It works that out from what turns
up: **the same content, whatever its version, must come back wearing what the Player left; a
different piece must not.** That is the rule under test, so the thing under test is the only
thing that decides the answer.

Everything the Player does goes through `UDCInteractor`, the same component the key and the
pad button call. The scripted run names the thing it wants (`TryUseKind`) instead of taking
whatever the prompt happened to pick — the same reach test, the same
`ADCContentActor::Interact`, the same telemetry; what it skips is only which of two things
38 cm apart a human's head was pointing at. So it **counts how often the prompt already
agreed**, which is what still says something about that.

`POST /admin/end-block {game, slot, region}` is new on the server for this: it pulls the live
allocation's `end_at` back to now and changes nothing else, so what happens next is the
ordinary rule — the region's rival, the next winner, takes the block. It is the counterpart of
`/admin/close-auction` for the other timestamp rule, and the booth gets it too: "the block
ends while the Player is inside" is a demo beat, and a rehearsal cannot wait three real
minutes for it.

One deliberate restraint in the test: after a swap it **walks back in only through a door that
is already open**. Opening a closed one would be the Player changing the piece they came back
to look at — and on a round where somebody else's content took the block, that change would be
saved and would turn up in the next round as a state nobody set.

## Three art fixes, and the re-registration that proved them

Queued out of brief 013, all three about the **picture a brand is shown of the spot it is
bidding on** — the slot-map tool hides whatever is standing in a slot, so that picture is of
the empty pad.

- **the slot pad has its own two colours.** `M_SlotPad` and `M_SlotKerb` instead of the
  plaza's `M_Paving` and `M_Kerb`, so an empty slot is a legible shape rather than a patch of
  the paving round it. `art/blender/env/README.md` has the longer note.
- **the water is not a mirror.** `M_Water` was roughness 0.04, i.e. glass. Water that
  reflects the sky looks right from the promenade and is wrong from directly above: Game B's
  plan view came out with a **white sea**, and because that white sea is half the frame the
  plan view's histogram exposure then pulled every roof down to **black**. At 0.26 (warm) /
  0.34 (cool) it still reads as water at eye level — better, in fact — and the plan view got
  its exposure back. The plan view also turns `ReflectionEnvironment` and `Specular` off and
  has its own exposure bias (`-MapExposure`), which is a knob because what it compensates for
  is how much of a particular map is water, grass or paving.
- **`env_import` now notices when a kit piece has moved on.** The first attempt at the pad
  change did nothing visible, because `import_env_meshes` skipped every mesh whose asset
  already existed — so the asset kept the *old* material slots and the new ones were never
  assigned. `is_stale` re-imports a piece whose FBX is newer than its asset, or whose asset's
  material slots are no longer the manifest's. Importing a static mesh is still the slow part
  of that script, so everything else is still skipped.

Both games were captured and registered again (`register_games.ps1`): Game A 2048 × 1316 px
of 202 × 130 m, Game B 2048 × 1616 px of 97 × 76 m, five thumbnails, `POST /games/register`
**200** both times, and the pin positions unchanged from brief 013 to four decimal places —
the geometry did not move, only its colour. The evidence is `spike/shots/016/`: both captures
with the pins drawn back on from the JSON the tool actually sent, and the five thumbnails.
`server/config/maps/` is committed, so a clean checkout serves the new pictures.

## What the state exit test proved (brief 016, 2026-11-01)

One packaged Shipping build that contains none of the content, one run, no restart and no
loading screen. Every round is the whole of plan v6 §4 step 9: walk in, open the door, turn
light B on, set the screen to image 3, let the backend replace the content while the Player is
standing inside, watch SWAP PENDING hold it, walk out, walk back in and look.

| # | what the backend did | before | after | what came back | held | applied | state |
|---|---|---|---|---|---|---|---|
| 1 | a new version was pushed | content1 v1 | content1 v2 | A+ B+ door open screen 3 | 5.1 s | 1.8 s | **kept** |
| 2 | a new version was pushed | content1 v2 | content1 v1 | A+ B+ door open screen 3 | 1.5 s | 1.8 s | **kept** |
| 3 | the block ended | content1 v1 | rival1 v1 | A+ B- door shut screen 1 | 5.3 s | 1.8 s | **kept** |
| 4 | a new version was pushed | content1 v1 | content1 v2 | A+ B+ door open screen 3 | 0.6 s | 1.8 s | **kept** |
| 5 | a new version was pushed | content1 v2 | content1 v1 | A+ B+ door open screen 3 | 1.2 s | 1.8 s | **kept** |
| 6 | the block ended | content1 v1 | rival1 v1 | A+ B- door shut screen 1 | 0.9 s | 1.8 s | **kept** |
| 7 | a new version was pushed | content1 v1 | content1 v2 | A+ B+ door open screen 3 | 0.5 s | 1.8 s | **kept** |
| 8 | a new version was pushed | content1 v2 | content1 v1 | A+ B+ door open screen 3 | 0.9 s | 1.8 s | **kept** |
| 9 | the block ended | content1 v1 | rival1 v1 | A+ B- door shut screen 1 | 1.1 s | 1.8 s | **kept** |
| 10 | a new version was pushed | content1 v1 | content1 v2 | A+ B+ door open screen 3 | 0.6 s | 1.8 s | **kept** |

**10 / 10.** The Player left `A+ B+ door open screen 3` every time.

- **3 of the ten were the block ending** while the Player was inside (rounds 3, 6, 9). The next
  winner - the region's rival - waited in SWAP PENDING exactly the same way, and came up
  wearing **its own defaults**: a different piece never gets the state the Player left on the
  last one.
- the record **outlived a block of somebody else's content**: after rounds 3, 6, 9 the visitor's
  content was allocated again and came back wearing what had been left on it before the rival
  took the block.
- the version alternates on purpose - v1 → v2 → v1 → v2 - because the key is the *content*, not
  the version. Version 1 coming back after version 2 restores the state just the same.
- **76 interactions** in the run (door 19, lights A 0, lights B 19, screen 38), every one through
  `UDCInteractor` - the same component the key and the pad button call. The on-screen prompt
  was **already showing the thing the script went on to use 57 times out of 76**.
- telemetry the run produced on A1: **17 visits, 160 s of dwell**, plus the interactions above
  and the views - all of it on `/report`, split by region.

`GET /report` for r1 at the end of the run: *views 14,422 (14,400 simulated + 22 counted),
visits 27, dwell 238.8 s, interactions 118, mounts 7, blocks 4.* The visit, dwell and
interaction figures are **higher than the game's own counters** (17 / 160 / 76) for a reason
worth knowing: the report counts a block's telemetry over `[start, end + 60 s]`, and that
minute of slack - which exists so a batch the client posts just after a block rolls over is
not lost - counts those events into the next block as well. Four blocks in four minutes is
this test, not the demo: at the booth a block is three minutes long and the next one starts
when the auction says so, so nothing lands in two windows. Worth tightening in the hardening
step all the same.

The picture of all of it is `spike/shots/016/state_contact.png`, and `DC_LOG` writes a
`STATE save` / `STATE restore` line for every one of them:

```
A1|content1  schema 1  lights A on / B on, door open, screen 3  (saved 10, restored 10)
A1|rival1  schema 1  lights A on / B off, door closed, screen 1  (saved 3, restored 2)
A2|default  schema 1  lights A on / B off, door closed, screen 1  (saved 1, restored 0)
A3|rivalsmall  schema 1  lights A on / B off, door closed, screen 1  (saved 1, restored 0)
```
---

# The region preview window (brief 017): the same slot, another region

Plan v6 §4 step 7 is one sentence of the tour and the only one that needs a **second copy of
the game**: *"the region preview window appears: same game, same slot, a player in India →
the India rival's content is there, not yours. Flip it to Japan → yours."* It is the step
that shows the resolution engine is answering a *context*, not a question with one answer.

It is not a second program. It is **this build, started with `-DCPreview`**.

**The preview window does not follow a focus into the other map, and that is FUTURE.**
Brief 017 left it framing the first slot of the map it was started on when the visitor bids
on the other game, and brief 018 asked whether a hidden level load could fix it now that
the build can switch maps. It cannot, cheaply: `StartPreview` is a boot sequence that runs
in `BeginPlay`, and a level load runs it again — which calls `FDCPreviewWindow::HideAtBoot`
(a plain `ShowWindow(SW_HIDE)`) and then re-applies `-DCPreviewShown`, i.e. *hidden*. A
switch in the middle of the region-check step would take the window off the portal's screen
and leave it off. Making it safe means moving the window's shown/hidden state out of the
command line and into the shell so `StartPreview` can be run twice, and that is a careful
change to the one thing at the booth that must not break. It is not in the way of anything:
the window already frames whatever the visitor bid on **within** its own map, which is the
whole of tour step 7 as the plan writes it.

| Flag | What it does |
|---|---|
| `-DCPreview` | the whole mode: see the list below |
| `-DCRegion=r2 -DCFollowRegion` | which region it plays as, and that the portal may move it |
| `-DCCacheDir=<dir>` | its own pack cache, so the two copies never share a file |
| `-DCPreviewShown` | start on screen instead of parked off-screen |
| `-DCPreviewRect=x,y,w,h` · `-DCPreviewMonitor=<n>` | where the window goes, instead of the computed place |
| `-DCPreviewFile=<path>` · `-DCPreviewTitle=<text>` | how the pad helper finds it |
| `-DCPreviewFps=<n>` · `-DCPreviewDrift=<deg>` | the frame cap (30) and the drift (11°; 0 = still) |

```powershell
powershell -ExecutionPolicy Bypass -File unreal\Tools\run_preview.ps1
powershell -ExecutionPolicy Bypass -File unreal\Tools\run_preview.ps1 -Region r3 -Shown
```

`-DCPreview` alone does all of this, because at the booth it is one line of a start script:

- **no Player.** The pawn is a bare `APawn` with no mesh, not the game module's mannequin:
  nobody is playing this copy, and a character standing at the spawn point would be in the
  picture. Move and look input are ignored, and no interaction component is attached.
- **no audio** (`FApp::SetVolumeMultiplier(0)`), **no telemetry at all**, **no status strip
  and no waypoint marker** — the HUD draws one thing instead, below.
- **the budget of plan v6 §11**: a 30 fps cap (`t.MaxFPS`), the lowest scalability level,
  below-normal process priority, and half resolution — which is the window itself: 960 × 540
  is half of 1080p on each axis, a quarter of the pixels, and because the window is
  borderless it renders exactly the size it is.
- **the window**: borderless, on the portal's monitor, over the rectangle the Region-check
  step leaves free, topmost while it is shown, and **out of sight at boot**.
- **the camera**: it auto-pilots to whatever slot the backend says the visitor has just been
  bidding on, frames it from the front at eye level, and drifts slowly.
- **a tiny corner caption** saying which region it plays as, in English like everything

## Why the preview posts no telemetry

It is a camera parked in front of a piece of content for minutes at a time. Every slot it
frames is "on screen, within 30 m, for more than a second, not blocked" — so it would post a
`view` nobody had, and the brand's report would count an audience of one machine nobody is
playing. Worse, its `mount` events are what the portal's push-update screen reads as *the
game swapped it* (`specs/DECISIONS.md`). So `UDCSubsystem::QueueTelemetry` drops everything
in preview mode and counts what it dropped; the status file carries both numbers.

## The window: who owns which half

- the **game** decides where the window belongs, makes it borderless, parks it off-screen at
  boot, and writes `dc_preview_window.json` saying where "there" is;
- the **pad helper** (`booth/pad_helper.py`) moves it between there and off-screen when the
  portal's Region-check step opens and closes. A web page cannot move another program's
  window; the helper can, and it is already the thing the portal talks to.

Four things about it are deliberate:

**The home rectangle is a rule, not a number**: the right half of the portal's monitor,
vertically centred, half the monitor's width and height — 960 × 540 at (960, 270) on a
1920 × 1080 screen. It is written in three places that have to agree and cannot ask each
other: `FDCPreviewWindow::ComputeHomeRect`, the portal's `.preview-reserve` in
`portal/style.css`, and the helper's fallback in `pad_helper.py`. The Start menu's panel
moved into the left half to make room for it.

**Hidden is off-screen, not minimised.** A minimised Unreal window stops drawing, and this
window has to be already showing the right thing the instant the portal asks for it — the
visitor is looking at the screen when it appears. The off-screen position is 30,000 and not
something rounder because **Windows clamps a window position to a signed 16-bit number**:
40,000 came back as 32,767, and the "is it hidden?" test, which compared against the
constant, then said the window was still on screen. It now asks the only question that is
actually true or false — *does this window overlap a monitor?*

**Nothing ever activates it.** Every `SetWindowPos` carries `SWP_NOACTIVATE`. The main game
keeps focus and therefore pad 1 all day (plan v6 §11), and a window that took focus when it
appeared would take the Player's controller with it. Creating a window always takes focus,
which cannot be helped — so the booth's start order is **server → portal → preview → main
game**, and the main game, being last, is the one left holding it.

**It is hidden from the plugin's module startup, not from the game mode.** A Shipping build
always starts in the default map and travels (`-DCMap=`, above), so `ADCRuntimeGameMode`'s
BeginPlay is several seconds after the window exists — and for those seconds the booth would
be looking at a bordered window of the spike map. `FDynamicContentsModule` therefore hides it
on the first tick after the engine makes it, and the game mode restyles and places it two
seconds later, while it is still invisible.

## What the camera does

The slot comes from the server: `GET /preview/region` now answers with a `focus` block as
well as a region — the lot the visitor last bid on, else their newest allocation, else the
busiest slot of the game being played at the booth (`server/README.md`). "The slot just
auctioned" is therefore right from the moment a bid is placed, before the auction closes.

`FramePreviewOn` puts the camera on the slot's **front** — the slot's +X, the same direction
`GetDoorApproachPoint` measures from — at **eye level, 1.7 m**, the same height the
slot-map tool's thumbnails are taken from. The distance is whatever makes the piece fit a 65°
frame in the tighter of its two axes, plus an allowance that is worth writing down: the
camera is at eye level and aims at the middle of the piece, so it is looking *up*, and the
top of a building is further from the middle of the frame than half its height. Without that
allowance an L piece has its roof on the top edge of the window.

Then it drifts: ±11° about the front, one lap every 46 seconds, smoothed. A change of slot
more than 60 m away is a **cut**, not a fly-through — "the same slot, another region" is not
a tour of the map.

The slot it frames can be in the *other* game: a visitor is free to bid on Game B while
Game A is the one on the booth's screens. This copy plays the map it was started on, keeps
framing the slot it has, and says so in the log. Following a focus into another map would be
a level load in a window that exists to be a still of somewhere else. **QUEUED** if the booth
ever wants it.

## The caption

Bottom-left, one line:

```
A player in India
```

The word for the region comes from the server (`/preview/region`'s `label`), because the
booth's region labels already live in `server/config/demo.json` and the game cannot import
`portal/strings.js`. `server/tests/test_preview.py` fails if the config ever names a region
`portal/strings.js` has never heard of — the same guard `test_rival_identity.py` puts on the
art kit's identity table. Until the first `/preview/region` answers there is only the region
id, and the caption says that rather than guess at a name.

It used to be **two** lines, Japanese over English, and the Japanese came from a `label_jp`
next to the label. **Kavin ruled on 2026-11-02 that the demo is English only**, so the second
line, the field behind it and every other Japanese string in this build are gone (brief 018E,
`specs/DECISIONS.md`). That also retires a piece of trivia worth keeping somewhere, in case a
later brief wants CJK back: it worked on a Canvas HUD with no font asset of its own, because
`GEngine->GetMediumFont()` is `/Engine/EngineFonts/Roboto`, a **composite** font whose
fallback typeface is `DroidSansFallback`, and that face is cooked into this build (3.9 MB of
it, in pakchunk0).

## `-UserDir=` is not optional, and this is the trap of the brief

Two copies of one packaged build share one **`GameUserSettings.ini`** — in a Shipping build
that is `%LOCALAPPDATA%\DCDemo\Saved\Config\Windows\`, not a folder next to the build. The
engine persists the **scalability groups** and the **window resolution** into it. So the
preview window, which exists to run at the lowest settings and half resolution, writes
exactly that into the file the *main game* reads the next time it starts:

```
sg.ResolutionQuality=50
sg.ViewDistanceQuality=0 … sg.ShadingQuality=0
```

It happened here. The main game then ran the whole plaza at half resolution and the lowest
quality — 375 fps instead of 80 — and nothing in any log said why; it was found only because
the frame times of the soak run were implausibly good. At a booth it would have been an
afternoon of a soft-looking screen nobody could explain.

The fix is one flag: **`-UserDir=<folder>`** gives the preview its own `Saved` tree, so it
cannot write anything the main game reads. `run_preview.ps1` passes it, both test drivers
pass it for *both* copies (so a measurement starts from the build's own settings and leaves
nothing behind), and `-DCPreview` **logs a warning when it is missing** — the failure is
invisible and a day late, which is exactly the kind that has to be noticed at the time.

## Pad 1 only, and focus (plan v6 §11, day-1 checks 1, 3 and 4)

Three of the four day-1 checks are now evidence rather than expectation, and the fourth is
an errand that needs two controllers plugged in.

**Two copies run side by side** (check 3) and **both keep running and rendering when they
are not the foreground window** (check 4). The preview window is never focused and is
plainly drawing - that is half of it, and the exit test's desktop captures are the picture.
For the other half the exit test deliberately hands focus to the browser, then reads the
main game's own frame counter and compares two photographs of its window five seconds
apart: it is still ticking at full rate and the picture has changed. `t.IdleWhenNotForeground`
is set to 0 and `FApp::SetUnfocusedVolumeMultiplier(1)` is called at startup in both copies,
because the engine's default is to **silence** an unfocused game (`BaseEngine.ini` sets
`UnfocusedVolumeMultiplier=0.0`) - plan v6 §11 asks for the opposite, so that an emergency
mouse click on the other screen is survivable.

**The main game never loses focus** when the window shows or hides: every move of it carries
`SWP_NOACTIVATE`, the exit test checks the foreground window at each beat, and the booth's
start order puts the main game last.

**The game listens to pad 1 only** (check 1) is the one this PC cannot answer: no controller
is plugged into it (`py -3 booth\pad_helper.py --list` finds none). What can be said without
hardware is what the engine will do. Windows' input device mapping policy is
`PrimaryUserSharesKeyboardAndFirstGamepad` (`input.DeviceMappingPolicy=1` in the engine's
`BaseWindowsInput.ini`): the keyboard and **the first connected gamepad** are mapped to the
primary platform user, and every gamepad after that goes to the *next* platform user. This
game has one local player, so a second pad's presses belong to a platform user that has no
`ULocalPlayer` and never reach the player controller - which is where `UDCInteractor` binds.
So pad 2 should be inert in the game by construction. **NEEDS-KAVIN**: plug both pads in,
start the main game, and press every button on pad 2 - nothing in the game should move and
the interaction count in the status file should not change - then do the same on pad 1 and
watch it work. Note the engine's rule is "the first *connected*" gamepad, which is not
guaranteed to be XInput's pad 1; plan v6 §11's "press ✕ on the player pad at startup" is the
feature that makes that deterministic, and it is **FUTURE**.

## The pass / fail test (plan v6 §11, §14 step 5)

```powershell
server\.venv\Scripts\python.exe unreal\Tools\preview_frametime_test.py
server\.venv\Scripts\python.exe unreal\Tools\preview_frametime_test.py --minutes 2 --only solo
```

The same ten-minute scripted tour of Game A, twice: once alone, once with the preview window
up and rendering. **Pass = the main game's worst 1 % stays under 25 ms and its average is
within 15 % of solo.**

Ten minutes is *laps* of the tour (`-DCTourFor=600`), not a camera left standing: what costs
frames is a Player walking the plaza and going in and out of three pieces of content, and
only the first lap photographs anything. Both numbers come from the game's own sampler — every
frame after the first four seconds, minus any frame within half a second of a shutter — which
is also what the status file now carries, as cumulative counters a watching script can
difference over any window it likes.

Two things to know before reading any of these numbers:

- **the preview's own frame times are all over 25 ms, on purpose.** It is capped at 30 fps,
  so every frame it draws is 33 ms and `over_25ms` equals `frames` in its status file. The
  pass line is about the **main game**;
- **this PC has to be left alone for the ten minutes.** The first attempt at this run was
  made while the same machine was being used for file searches over the engine's source
  tree, and the main game's worst 1 % went from 19 ms to 29 ms — nothing to do with the
  preview window. A soak measures the machine as well as the build.

### What the run measured (2026-11-01, this PC, 1600 × 900)

| | frames | average | median | **worst 1 %** | worst | over 16 ms | over 25 ms | laps |
|---|---|---|---|---|---|---|---|---|
| solo | 33,682 | **17.82 ms** (56 fps) | 17.57 ms | **25.45 ms** | 37.83 ms | 26,797 | 435 | 7 |
| with the preview | 30,973 | **19.41 ms** (52 fps) | 19.32 ms | **26.39 ms** | 72.96 ms | 29,213 | 661 | 7 |

* worst 1 % under 25 ms: **26.39 ms** — **FAIL**, by 1.4 ms
* average within 15 % of solo (at most 20.50 ms): **19.41 ms**, **+8.9 %** — pass
* 63 / 63 walk legs arrived in both runs; the preview window drew 12,316 frames of its own
  at 50 ms each (below-normal priority is doing its job), posted **no telemetry**, and sat
  on 960 × 540 at (960, 270) throughout, playing as India while the main game played as
  Japan.

The full table, including what the preview window was showing, is written to
`unreal/_build/preview/frametime.md` by the run.

<!--FRAMETIME-->

## The live flip: the fallback, and what the verdict means

Plan v6 §11 wrote the rule and its consequence: *"the main game must hold its frame rate
with the preview alive through a soak run. If not, drop the preview and do step 7 as a live
flip: the portal switches the main game's region to India and the slot swaps in front of the
Player."* The run above is a **FAIL** by that rule, so the fallback is built and working.

Read the numbers before deciding which to use, though, because what failed is not quite
what the rule was aiming at: **the solo run misses the 25 ms line as well**, at 25.45 ms.
This PC does not hold a worst 1 % under 25 ms on Game A at 1600 × 900 with nothing else
running at all. Brief 012's 12.47 ms average and 19.05 ms worst 1 % were **one lap** of the
tour, before the content's light groups existed (brief 016) and before the tour started
switching light B on at every slot and leaving it on; over seven laps with eighteen extra
point lights burning, the same walk costs half as much again.

What the preview window adds on top of that is **+1.6 ms of average (8.9 %) and +0.9 ms of
worst 1 %** — inside the plan's own 15 % allowance for the average, and 3.7 % more on the
tail of a figure that was already over. So the honest reading is "this PC is a whisker short
of the line, with or without a second copy", and the booth PC — whose strength plan v6 §17
lists as an open item — is the thing that actually settles it. **NEEDS-DECISION**, with both
paths now built.

The fallback works either way, and it is a good booth trick to have even if the window
stays:

* **the portal** — the Start menu's second row, *"Play the main game as this region"*. It
  posts `/preview/flip {region, seconds}`;
* **the server** — keeps it as a timestamp like everything else (`live_flip` in meta, an
  `ends_at`), and carries it on **`/changes`**, which every copy of the game already polls
  every 1.5 s. A reset cancels it;
* **the game** — `UDCSubsystem::ApplyLiveFlip` switches this copy's region for the length of
  the flip and switches it back when the server stops reporting one. The **preview window
  ignores it**: it already is another region, and flipping it too would make both screens
  show the same thing. `-DCNoFlip` opts out.

The Player sees the slot they are standing in front of swap to the other region's content
and swap back, with no loading screen and no restart - which is the same promise as the
preview window, shown on one screen instead of two.

## A bug this found: two slots, one pack, one cache folder

The first live-flip run failed with `sha256 mismatch on pakchunk110-Windows.ucas`, and it
was not the flip's fault. **A region's large rival stands in both of that game's large
slots**, so A1 and A2 resolved to the same pack at the same instant on a cold cache, both
started downloading it into the same folder (the cache is one folder per pack), and they
wrote over each other's bytes.

It has been there since brief 011 and nothing had hit it: every scenario so far gave each
slot a different piece. The attract rotation does it every block in any region whose rival
holds two large slots, so the booth would have found it.

`UDCSubsystem::StartDownloads` now checks whether another slot's job is already fetching the
same pack. If one is, the second slot does not start a competing download: it keeps what is
on screen and falls back with the ordinary backoff, and when it tries again the pack is in
the cache and costs nothing. One download, two slots, no race.

## Things worth knowing about this PC

- The engine is the launcher install at `E:\EpicGames\UE_5.7` (5.7.4) and is **read-only**.
- The C++ toolchain is the weak point, and it is why everything runs a **Shipping** build and
  not a Development one. UE 5.7.4 wants MSVC **14.44.35207**; this PC has 14.36, 14.38 and
  14.42 (checked again 2026-11-01 — 14.44 is still not installed), and UnrealBuildTool bans
  14.40–14.43 and rejects anything below 14.38 — so it compiles with 14.38. The editor links fine (it links against the engine's DLL import
  libraries), but the **monolithic game executable** does not: the engine's precompiled
  objects call vectorised STL helpers that 14.38's CRT does not contain.
  - Four of the seven missing helpers are in 14.42's `msvcprt.lib`, which
    `Source/DCDemo/DCDemo.Build.cs` adds to the link. They are leaf SIMD functions used by
    geometry and audio code.
  - The other three come from `Module.LiveCoding` (`__std_search_1/2`) and `TraceAnalysis`
    (`__std_find_first_of_trivial_pos_1`), and **no CRT on this PC has them**. TraceAnalysis
    is gone because StateTree is switched off (which is why the StateTree / GameplayCameras /
    CameraShakePreviewer plugins are disabled in the `.uproject`, and why the Combat and
    SideScrolling template variants were moved out of the project). Live coding cannot be
    switched off safely for Development: it changes `WITH_RELOAD`, which removes members from
    the UObject registration structs that the precompiled engine still reads at full size —
    the first packaged Development build crashed in `ProcessNewlyLoadedUObjects` before it
    reached a frame. Shipping has live coding off *by default*, so the engine's own Shipping
    libraries agree with ours and nothing has to be forced.
  - So: **Shipping packages and runs; Development cannot be linked on this PC.**
  - **Installing MSVC 14.44.35207 from the Visual Studio installer undoes all of this**: the
    `msvcprt.lib` block in `DCDemo.Build.cs`, the `WITH_LIVE_CODING=1` blocks in both
    `Build.cs` files, the `-NoLiveCoding` in `package.ps1`, and the disabled plugins can all
    go, and Development packaging should work.
- `Tools/symbolize_crash.ps1` turns the raw `DCDemo + 0x...` frames in a packaged build's
  crash report into function names using the build's `.pdb` — there is no debugger installed
  on this PC, and that is how the live-coding crash above was found.
- `unreal.Rotator` in Python is `(roll, pitch, yaw)` positionally. Brief 004's test map passed
  `-42` as the *roll* and left the pitch at zero, which put the sun on the horizon and backlit
  everything. The map builder uses keywords now.
- The shared `Characters` content pack (125 MB of mannequin) was deliberately **not** copied
  into the project, so the player pawn has no visible mesh yet. Nothing here needs one.
  **QUEUED**

---

# The booth's front end (brief 018): attract, title menu, game switching, X-ray

Plan v6 §3, §4 step 0, §10 item 1 and §11. Four things, and one measurement that had to come
first because everything else is measured against it.

## The shell

`UDCShell` is a **game instance subsystem**, and that is the whole trick. A level load
destroys the world, the game mode, the HUD, the Player and every slot — and leaves the game
instance alone. So the mode, the X-ray flag, the switch count, the uptime, the pack cache,
the mounted packs and `UDCStateStore`'s record of what the Player did all live through a game
switch without anything being saved or reloaded, and **A → B → A finds A1 exactly as it was
left** as a property of where the state lives.

| State | What is on screen |
|---|---|
| **Attract** | No Player at all. The camera drifts over the map and lingers on each slot in turn; the strip stays; one line says "press any button". Content keeps changing behind it as blocks roll over, and the camera is in front of whatever is standing there *now*. |
| **Title** | Game A and Game B as two big cards, picked with the stick or d-pad and ✕. The card picture is the **plan view the slot-map tool captured and registered**, fetched back from the platform (`GET /games/<id>/map`); a game that was never registered draws a plain tinted panel instead. |
| **Playing** | What briefs 011–016 already built. |
| **Paused** | Resume · Switch to the other game · X-ray on/off. **The world keeps running** — see below. |

Switching game is a level load, with a plain black fade and a "Loading Game B" line on
it, because plan v6 §3 says switching *games* may have one and switching *content* never may.
The strip's two zeroes do not move: `restarts: 0` and `content loading screens: 0` are what
the booth claims all day, and a game switch is neither. The count of switches is in the
**X-ray**, not on the strip, so nothing invites the reading that it is one of the two.

**The pause menu does not stop the world.** It takes the pad — the Player cannot walk, and the
button that confirms a menu item cannot also open the door they are standing at — but the
slots keep polling and a block can roll over behind the menu. Freezing the world would stall
the one thing the left-hand screen exists to prove.

In the attract loop there is **no pawn**, not a hidden one: `bStartPlayersAsSpectators` at
boot and `RestartPlayer` when a game is picked. A pawn parked in the loop would be counted as
a visitor by whatever slot it happened to be standing in.

**The attract camera is brief 017's preview auto-pilot** — `TickAutoPilot`, with the slot
chosen by a rota instead of by the server and an overview leg between laps. One camera, one
set of rules for standing in front of a slot, and whatever is tuned on one is tuned on both.

**Neither the attract camera nor the preview window is a Player**: no view, no visit, no
dwell, no interaction. A mount *is* still posted from the attract loop, because that is a fact
about the booth's own machine and it is the event the portal's push-update screen is right to
believe. The check sits in `ADCSlot::UpdateViewSeconds` as well as in `QueueTelemetry`,
because a slot that queued a view and had it dropped would still have marked it reported and
never posted the one a real Player later earns.

## The input

```
d-pad / left stick      move the cursor          arrows
✕ / A                   choose                   Enter
○ / B                   back                     —
Start                   pause, or leave attract  Esc
View / Back             X-ray on / off           F2
any button              leave the attract loop
```

`UDCShellInput` is a component on the **player controller**, not on the pawn: on the title
menu and in the attract loop there is no pawn and the menus still have to answer the pad. It
is Enhanced Input for the reason in `DCInteractor.h` — a Shipping build with that plugin on
processes no legacy key bindings at all — and it builds **both** its actions and its mapping
context in code, because an input action with nothing on it but a name is not worth an asset.

One press of ✕ fires two of its actions (*any button*, which leaves the attract loop, and
*confirm*, which picks a card) and Enhanced Input does not promise which order they run in.
So every change of screen arms a **0.22 s input lock**: without it, the one press meant to
open the title menu could also choose a game off it. It doubles as the debounce a booth wants
anyway.

## The X-ray view

Off by default, toggled from the pause menu and with View on the pad. It is the answer to
"isn't this just ChunkDownloader?", and it is five things a download manager has not got:

1. a **pre-fetch ring** on the ground round every slot, at the slot's real radius, coloured by
   where that slot is in the lifecycle (idle · resolving · downloading · verifying · mounting
   · active · swap pending · fallback), with the slot's id and state on a mast above it;
2. the **manifest** of the nearest slot — content and version, the pack, its size, the SHA-256
   of the container, whether the RS256 signature checked out *on this machine*, the region,
   the **lot and block** it is showing under, the allocation key, and when it stops being
   valid;
3. the **cache**: the packs on disk with their size, what was in them, whether they are
   mounted, in least-recently-used order — which is the order the next eviction takes them in;
4. the **lifecycle log**: the last ten transitions with their milliseconds;
5. a **frame-time graph** over the last ten seconds, with lines at 16.7 and 33 ms and a tick
   at every mount, spawn and unload — so anybody can watch a swap happen and see that nothing
   spikes.

Every heading and every value is English (English only, Kavin's ruling 2026-11-02). The
headings used to carry a Japanese word in front of them; the values never did - a hash, a file
name, a state name out of the lifecycle figure and a number of milliseconds are what the client
is really doing. It is drawn on
the HUD canvas out of counters the subsystem already keeps — a graph of frame time that cost
frame time would be a liar — and the graph reduces its ten seconds to 150 columns holding the
**worst** frame in each slice, because a graph that is there to show "no spike" must not
average one away.

## The lighting budget

Everything else in brief 018 is measured against the booth's own frame time, so this came
first. The long version, both tables and the pictures are
`spike/shots/018/lighting.md` and `spike/shots/018/lighting_before_after.png`; the short
version is three findings.

**The wall lamps are not where the frame time is.** The eighteen of them — six per piece,
three pieces in Game A — cost **0.5 ms** of average frame time as brief 016 shipped them
(15.15 ms with group B never built, 15.68 ms with it on). The drift the brief recorded
against them is not something they do.

**Of the things one lamp can be, only Lumen matters.** Under Lumen, every light whose
indirect lighting scale is above zero is a light the **surface cache** has to be re-lit by,
over every card page it reaches, every frame it is on — a cost per light that has nothing
to do with how much of the screen the light covers (`LumenSceneDirectLighting.cpp` gates on
`Proxy->GetIndirectLightingScale() > 0.0f`). The shadow is worth 0.1 ms of average but 1.8 ms
of the *tail*; the reach and the count are worth about 0.15 ms each. So the change is
`IndirectLightingIntensity = 0` on group B — `ADCContentActor::bLightBAffectsGi` — and
nothing else. The lamps still light the surfaces in front of them, which is all a visitor
ever sees them do, and the before/after crops of all three interiors are the same picture.

**Two faster settings were measured and rejected by looking at them.** Taking group A out of
the Lumen scene as well is another 0.3–2 ms, but the rooms lose the bounce off their own
ceilings and go flat and grey — and the lamps-on / lamps-off contrast the brief asks to keep
gets *weaker*. Half the ceiling fixtures at twice the lumens is the fastest row on the whole
sheet, and `dc_kit.light_a_fixture` models a **fitting** at every group-A socket: half of
them would be modelled and dead, which no eye-level shot happens to show and anybody
standing in the room and looking up would.

One number worth carrying forward: **run-to-run drift on this machine is about ±1 ms over
ten minutes.** The same settings measured 13.25 ms in one batch and 15.01 ms twenty minutes
later, and "no lamps at all" came out slower than thirty-two lamps. Nothing under about a
millisecond separating two rows measured minutes apart means anything here.

### And the ten-minute run it is all measured against

Two ten-minute laps of the scripted tour at 1600 × 900, the same test brief 017 ran
(`spike/shots/018/frametime.md`):

| | average | median | worst 1 % | over 25 ms | brief 017 |
|---|---|---|---|---|---|
| solo | **16.00 ms** (62 fps) | 15.91 ms | **22.72 ms** | 108 / 37,475 | 17.82 ms avg, 25.45 ms worst 1 % |
| with the preview | **18.80 ms** (53 fps) | 18.78 ms | **27.69 ms** | 1,178 / 31,961 | 26.39 ms worst 1 % |

The tail is **2.7 ms better than brief 017's** and the solo average is 1.8 ms better, which
is more than the lamps alone are worth and is partly the machine. Two things do not meet
their line and both are honest:

* brief 018's **solo average target of 15 ms is missed at 16.00 ms.** Everything measured
  that would close the last millisecond changes the look, and the pictures are above.
* plan v6 §11's **worst 1 % under 25 ms with the preview alive is still missed, at
  27.69 ms** — the same verdict brief 017 came to, which is the condition the plan attaches
  the live-flip fallback to. Both paths are built; which the booth uses is still a call for
  the booth PC.

## Running it

```powershell
# the booth's own behaviour, by hand
powershell -ExecutionPolicy Bypass -File unreal\Tools\run_runtime.ps1 -Shell -Xray -Seconds 180

# brief 018's exit test: attract -> title -> Game B -> X-ray -> switch -> state kept -> attract
server\.venv\Scripts\python.exe unreal\Tools\menu_exit_test.py
server\.venv\Scripts\python.exe unreal\Tools\menu_exit_test.py --xray-only --res 1920x1080

# what the lamps cost, one setting at a time, and the before/after pictures
server\.venv\Scripts\python.exe unreal\Tools\light_sweep.py --minutes 3
server\.venv\Scripts\python.exe unreal\Tools\light_shots.py
```

New switches on the game:

| Switch | What |
|---|---|
| `-DCShell` · `-DCNoShell` | force the shell on / off. It is **on by default** and off whenever a scripted run owns the camera (`-DCTour`, `-DCStateTest`, `-DCPreview`, `-DCShotDir` / `-DCAutoShot`), so every test written before brief 018 behaves exactly as it did |
| `-DCStartIn=attract\|title\|game` | where a run begins (default attract) |
| `-DCIdleAttract=<s>` | untouched player pad → attract (default 90; 0 never) |
| `-DCAttractDwell=<s>` | how long the attract camera lingers on one slot (default 14) |
| `-DCMapA=` · `-DCMapB=` | which package each game card loads |
| `-DCXray` | start with the overlay on |
| `-DCUiTest[=<path>]` | the scripted menu run, and where its report goes |
| `-DCTourLightB=0` | the tour leaves the wall lamps off (the before/after crops) |
| `-DCLightBOff` · `-DCLightBGi=` · `-DCLightBShadow=` · `-DCLightBRadius=` · `-DCLightBLumens=` · `-DCLightBEvery=` | the wall lamps, one knob at a time |
| `-DCLightAGi=` · `-DCLightAShadowMax=` · `-DCLightARadius=` · `-DCLightALumens=` · `-DCLightAEvery=` | the ceiling fixtures, the same |

## The scripted exit test, and what "the input path" means

`unreal/Tools/menu_exit_test.py` drives one packaged run with no restart:

> boot → **attract** → a button → the **title menu** → Game B → walk to B1 → pause →
> **X-ray on** → resume → pause → switch to Game A (a picture of the loading line) → walk
> into A1, open the door, wall lamps on, screen to image 3 → pause → switch to B → switch
> back to A → walk back into A1: **everything as the Player left it** → the idle timeout →
> attract.

The steps come from `-DCUiTest`, a hook inside `UDCShell` that calls the same `AnyButton` /
`NavHorizontal` / `Confirm` / `PauseButton` the pad's Enhanced Input bindings call — so what
the script presses is what a visitor presses, one function in. **It is not a fake gamepad**:
the XInput driver is not exercised here, and the "press ✕ on the player pad" lock of plan v6
§11 is a later brief's. The Python side owns the server, the allocations, the check that the
portal's "playing at this booth" badge follows a switch, and the contact sheet.
