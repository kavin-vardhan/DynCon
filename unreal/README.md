# The Unreal side — what is here and how to run it

*Written 2026-10-26 (brief 004). Plain-words guide for a cold reader. Status of each item is
marked **DONE / QUEUED / FUTURE**. The spec this implements is `specs/unreal_spec_v1.md`.*

## What this folder is

`unreal/DCDemo` is the demo's Unreal project: a UE 5.7.4 C++ project made from the engine's
third-person template, plus the **DynamicContents** plugin, which is where everything specific
to this invention lives. The point of the first round of work (brief 004) was to prove one
thing end to end: **a packaged game that does not contain a piece of content can be handed that
content as a file while it is running, and put it in the world without restarting.**

| Path | What | Status |
|---|---|---|
| `DCDemo/DCDemo.uproject` | the project; plugin list, module list | DONE |
| `DCDemo/Config/` | map + game mode, the chunk settings that make content packs | DONE |
| `DCDemo/Source/DCDemo/` | the renamed third-person template (character, controller, game mode) | DONE |
| `DCDemo/Plugins/DynamicContents/` | the runtime plugin: pack mounter, slot, content actor, spike driver | DONE (spike subset) |
| `DCDemo/Content/DCCore/` | what the base game owns: master materials, the 8 emblems, the sample screen image | DONE |
| `DCDemo/Content/DCContent/<id>_<v>/` | one folder per piece-version = one content pack | DONE for content4_v1, content1_v1 |
| `DCDemo/Content/Maps/Spike` | the spike map: ground, sun, sky, player start, two slots | DONE |
| `Tools/` | the scripts below | DONE |
| `_build/` | build outputs and logs (not in git, rebuilt by `package.ps1`) | — |
| `_packs/` | the content packs cut out of the build (not in git) | — |
| `spike/shots/` | the screenshots the spike run takes | DONE |

## The four steps, in order

Each script is in `unreal/Tools/` and takes no arguments for the normal case.

1. **`make_project.ps1`** — builds `DCDemo` out of the engine's `TP_ThirdPerson` template,
   renaming it the way the project browser does (module, `*_API` macros, class redirects).
   Only needed once; it leaves an existing project's `Config` alone. **DONE**
2. **`import_content.py`** — run inside the headless editor; imports `art/export/<id>_<v>/`
   into `/Game/DCContent/<id>_<v>/` (meshes, material instances from the manifest's colour
   table, `BP_DC_<id>_<v>`, the `PrimaryAssetLabel` that gives the folder its own cook chunk)
   and builds the spike map. Writes `_build/logs/import_report.json` with everything it
   checked. **DONE**

   ```
   "E:\EpicGames\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" ^
     "E:\DynamicContents\unreal\DCDemo\DCDemo.uproject" ^
     -run=pythonscript -script="E:\DynamicContents\unreal\Tools\import_content.py" ^
     -unattended -nosplash
   ```
3. **`package.ps1`** — builds the editor, then `BuildCookRun` with chunks, pak and IoStore, and
   archives the build to `_build/archive/Windows`. Use `-Config Shipping` until the C++
   toolchain is fixed (see below); `-SkipEditorBuild` if the editor is already current.
   **DONE**
4. **`stage_packs.ps1`** — moves the content chunks out of the packaged build into
   `_packs/<id>_<v>/` and writes a `pack.json` next to each. After this the build on disk
   genuinely does not contain the content. **DONE**
5. **`run_spike.ps1`** — runs the packaged game, hands it the packs on the command line, and
   collects the log and screenshots. The game quits itself when it is done. **DONE**

## How a content pack works

- Every piece-version lives in its own folder `/Game/DCContent/<id>_<v>/` with a
  `PrimaryAssetLabel` whose rules say "this folder is chunk 100 + n, always cook, **do not
  apply recursively**". Not applying recursively is what keeps the shared master materials,
  emblems and screen images in the base game instead of being copied into every pack.
- Packaging therefore produces `pakchunk0-Windows.*` (the base game) plus one
  `pakchunk1NN-Windows.{pak,utoc,ucas}` set per piece-version.
- A pack is **all three files**: with IoStore on (the 5.7 default) the `.pak` is nearly empty
  and the assets live in the `.ucas`, indexed by the `.utoc`. `FPakPlatformFile::Mount` on the
  `.pak` picks up the sibling `.utoc` by itself, so the client mounts a pack with one call —
  but the server must keep the three files together.
- The art is authored in metres and its FBX carries metre-scale vertex data. Because each part
  is imported in its own local space (so its pivot sits on its socket), the FBX importer's
  uniform scale is thrown away, so `ADCContentActor` scales the shell by 100 at spawn
  (`ContentUnitScale`). The permanent fix is to write centimetres out of Blender, after which
  that property goes back to 1. **QUEUED (art-side decision)**

## What the spike proved (brief 004, 2026-10-26)

A packaged build that does **not** contain `content4_v1` or `content1_v1` mounted both of them
from `_packs\`, loaded their Blueprints, and spawned them at two slots in one run, without a
restart or a loading screen. Numbers from `spike/shots/spike_result.txt`:

| | content4_v1 (S, slot 1) | content1_v1 (L, slot 2) |
|---|---|---|
| pack size (.pak + .utoc + .ucas) | 248,384 B | 443,156 B |
| mount | 17.8 ms | 12.1 ms |
| load the Blueprint | 2.7 ms | 3.4 ms |
| spawn + build from sockets | 0.6 ms | 0.5 ms |
| in the build before mounting? | no | no |

Those are warm-cache numbers. On the first run after packaging, mounting took 33–37 ms and
the first content load took 650 ms; everything after that was in the tens of milliseconds.
The whole two-piece run, including the deliberate waits for the screenshots, is about 8.4 s.

- The mount API that works: **`FCoreDelegates::MountPak`**, which is `FPakPlatformFile::Mount`
  underneath. It mounts the `.pak` **and** the sibling `.utoc`/`.ucas` in one call, so the
  client needs no IoStore-specific code - but a pack is all three files (the `.pak` itself is
  339 bytes; everything is in the `.ucas`).
- Screenshots: `spike/shots/01_content4_v1.png`, `02_content1_v1.png`.
- **Known issue:** the sign panel renders dark, so the emblem is not visible (the brand colour
  is - it is on the accent band and the door surround, teal on one piece and amber on the
  other). Ruled out: the material graph wiring, the material instance's parent and parameters,
  the material assignment on the mesh, the emblem texture's alpha, backface culling, and a
  lit-only sign (it is full emissive now and still dark). Next step is a Development editor
  run where `LogDC` is readable, to print the sign component's world transform and the
  material it actually ends up with. **QUEUED**

## Things worth knowing about this PC

- The engine is the launcher install at `E:\EpicGames\UE_5.7` (5.7.4) and is **read-only**.
- The C++ toolchain is the weak point, and it is why the spike runs a **Shipping** build and
  not a Development one. UE 5.7.4 wants MSVC **14.44.35207**; this PC has 14.36, 14.38 and
  14.42, and UnrealBuildTool bans 14.40–14.43 and rejects anything below 14.38 — so it
  compiles with 14.38. The editor links fine (it links against the engine's DLL import
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
  - So: **Shipping packages and runs; Development cannot be linked on this PC.** Shipping
    compiles `UE_LOG` out, which is why `ADCSpikeGameMode` writes its own `spike_result.txt`.
  - **Installing MSVC 14.44.35207 from the Visual Studio installer undoes all of this**: the
    `msvcprt.lib` block in `DCDemo.Build.cs`, the `WITH_LIVE_CODING=1` blocks in both
    `Build.cs` files, the `-NoLiveCoding` in `package.ps1`, and the disabled plugins can all
    go, and Development packaging should work.
- `Tools/symbolize_crash.ps1` turns the raw `DCDemo + 0x...` frames in a packaged build's
  crash report into function names using the build's `.pdb` — there is no debugger installed
  on this PC, and that is how the live-coding crash above was found.
- The shared `Characters` content pack (125 MB of mannequin) was deliberately **not** copied
  into the project, so the player pawn has no visible mesh yet. The spike does not need one.
  **QUEUED**
