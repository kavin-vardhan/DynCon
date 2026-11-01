# The Unreal side — what is here and how to run it

*Written 2026-10-26 (brief 004), rewritten the same day for brief 006, and extended
2026-11-01 (brief 011) with the runtime client. Plain-words guide for a cold reader. Status of
each item is marked **DONE / QUEUED / FUTURE**. The spec this implements is
`specs/unreal_spec_v1.md`.*

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
| `DCDemo/Plugins/DynamicContents/` | the runtime plugin: file log, pack mounter, slot lifecycle, content actor, backend client, status strip, two run drivers | DONE |
| `DCDemo/Content/DCCore/` | what the base game owns: master materials, the 8 emblems, the sample screen image | DONE |
| `DCDemo/Content/DCContent/<id>_<v>/` | one folder per piece-version = one content pack | DONE, all 13 |
| `DCDemo/Content/Maps/Spike` | brief 006's pack round-trip map: ground, sun, sky, player start, one slot per size class | DONE |
| `DCDemo/Content/Maps/DCRuntime` | brief 011's runtime-client map: the same ground and light, slots **A1 (L), A2 (T), A3 (S)** | DONE |
| `Tools/` | the scripts below, plus `chunk_ids.json` | DONE |
| `_build/` | build outputs and logs (not in git, rebuilt by `package.ps1`) | — |
| `_packs/` | the content packs cut out of the build (not in git) | — |
| `spike/shots/engine_contact.png` | the contact sheet one pack round-trip run produces (the individual shots are git-ignored) | DONE |
| `spike/shots/004/` | brief 004's two screenshots and result file, kept as they were | — |
| `spike/shots/011/runtime_contact.png` | the contact sheet of brief 011's exit-test run | DONE |

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
| `ADCStatusHud` | the status strip: build · uptime · restarts · content loading screens, plus a line per slot | DONE |
| `FDCCrypto` | RS256 over the signed payload, SHA-256 per file | DONE |
| `FDCPackCache` | one folder per pack under `Saved\DCPacks\`, least-recently-used eviction, purge on a booth reset | DONE |
| `FDCManifest` | the parsed, verified manifest | DONE |
| `UDCStateStore`, interaction, X-ray view, preview mode | plan v6 §14 steps 5–6 | FUTURE |

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

## What the exit test proved (brief 011, 2026-11-01)

Ten allocations written by hand through `POST /admin/allocate`, against **one** packaged
Shipping build that contains none of the content, in **one run with no restart and no loading
screen**: **10 / 10**.

| # | slot | region | what | what appeared | s to visible |
|---|---|---|---|---|---|
| 1 | A1 | r1 | hand allocation, large slot | content1 v1 `#E23D3D` star | 4.3 |
| 2 | A2 | r1 | tall piece in the tall slot | content3 v1 `#E23D3D` star | 5.2 |
| 3 | A3 | r1 | small piece in the small slot | content4 v1 `#E23D3D` star | 4.4 |
| 4 | A1 | r1 | swap: another piece into a full slot | content2 v1 `#E23D3D` star | 4.4 |
| 5 | A1 | r2 | second region, pack already cached | content1 v1 `#E23D3D` star | 0.3 |
| 6 | A2 | r2 | tall piece, second region | content3 v1 `#E23D3D` star | 0.4 |
| 7 | A1 | r2 | push version 2 onto the live allocation | content1 **v2** `#E23D3D` star | 5.2 |
| 8 | A1 | r2 | new brand on the same allocation | content1 v2 **`#2F6FEB` chevron** | 0.3 |
| 9 | A3 | r2 | corrupt pack | the **default stayed up**, then content4 v2 `#2F6FEB` chevron | 7.5 |
| 10 | A3 | r2 | rival block (identity from server config) | rivalsmall v1 `#F28C28` ring | 1.3 |

**Allocation written → visible in game** splits cleanly in two, because the server paces every
download to about four seconds whatever the pack weighs:

- a pack the game has never seen: **4.3 – 5.2 s** (poll + resolve + ~4 s paced download +
  verify + mount + spawn);
- a pack already in the cache: **0.3 – 1.3 s**, which is almost all poll latency — the work
  itself is 20–45 ms.

Round 9 is 7.5 s because it is two attempts: a ~4 s download whose `.pak` fails its SHA-256, a
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
   screen, within 30 m, for at least a second, with a line check — plan v6 §9.

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
