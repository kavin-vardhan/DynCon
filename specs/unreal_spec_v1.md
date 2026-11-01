# Unreal side — spec v1 (game build, plugin, content packs)

*Written 2026-10-26 by chat Claude for Claude Code. Derived from demo plan v6 §3, §6, §10–§11, the six figures (runtime sequence,
slot lifecycle) and `server_spec_v1.md` / `content_assets_spec_v1.md`. Status: DONE (spec); §2–§5 all built, briefs 004–016.*

## 1. Shape

- **Engine:** UE 5.7.4 launcher install at `E:\EpicGames\UE_5.7`. Never touch the engine folder or any other project.
- **Project:** `unreal/DCDemo/DCDemo.uproject`, C++, started from the engine's third-person C++ template (`TP_ThirdPerson`),
  renamed. Enhanced Input. Git: commit sources, config, `Content/` (binary .uasset is fine — local repo); ignore `Binaries/`,
  `Intermediate/`, `Saved/`, `DerivedDataCache/`, packaged builds.
- **Plugin:** `unreal/DCDemo/Plugins/DynamicContents/` — runtime module `DynamicContents` (everything the shipped game needs) +
  editor module `DynamicContentsEditor` (the slot-map tool; the content import stayed as editor Python in `unreal/Tools/`,
  which is where it was already working).
- **Content packs = cook chunks.** Each piece-version lives in `/Game/DCContent/<id>_<v>/` with a `PrimaryAssetLabel` that puts
  the folder in its own chunk (ChunkId 100 + n). Packaging with chunks + IoStore yields `pakchunkN-Windows.{pak,utoc,ucas}` per
  piece-version. Those files are **removed from the packaged game's Paks folder** and wrapped into `.dcpack` files for the server;
  the shipped build carries only the base game (chunk 0) — so content truly arrives after deployment.
  *Decision: chunks in one project instead of separate DLC plugins — one packaging run builds every pack against the exact
  demo build, which is what plan v6 §12 requires; DLC plugins are the production answer, not needed for a booth.*
- The base game owns everything shared by all content: the C++ content actor class, the master materials (`M_DC_Master`,
  `M_DC_Glass`, `M_DC_Emissive`, `M_DC_Screen`, `M_DC_Sign`), the 8 emblem textures and the default screen images. A pack holds
  only its meshes, material instances and one Blueprint `BP_DC_<id>_<v>` (child of `ADCContentActor`).

## 2. First: the pack round-trip spike (prove the riskiest thing before building on it)

Exit test: **a packaged Development build that does not contain the content mounts a pack from disk at runtime, loads
`BP_DC_content4_v1`, spawns it at a slot, and the log + a screenshot prove it — then does the same for `content1_v1` without
restarting.** Steps:
1. Project + plugin skeleton as §1. A test map `/Game/Maps/Spike` with a floor, a light, the player start and two `ADCSlot`s.
2. Import `art/export/content4_v1/` and `content1_v1/` with an editor Python script (`unreal/Tools/import_content.py`,
   run via `UnrealEditor-Cmd.exe … -run=pythonscript`): static meshes (no combine; sockets kept; complex-as-simple collision),
   material instances from the manifest's colour table, the Blueprint with the meshes and socket wiring, the `PrimaryAssetLabel`.
3. `ADCContentActor` (minimal for the spike): shell + door + switches + screen + sign from sockets; brand colour + emblem as
   material parameters; point lights at `SOCKET_LightA_*` / `B_*`.
4. Package with `RunUAT BuildCookRun` (Win64, Development, chunks, IoStore, `-pak`). Move chunk ≥ 100 files to
   `unreal/_packs/<id>_<v>/`.
5. Runtime mount path in the plugin: `UDCPackMounter::Mount(path)` → `FPakPlatformFile` mount (confirm the `.utoc`/`.ucas`
   container mounts with it on 5.7 — if not, mount the IoStore container explicitly) → `StaticLoadClass` from the manifest
   class path → spawn at the slot transform. Driven in the spike by a command-line switch
   (`-DCSpikeMount=<pack dir>;<class path>`), with clear `LogDC:` lines for every step and a screenshot after spawn.
6. Run the packaged exe windowed (it is a real desktop; rendering works). If a window can't render, use `-nullrhi` for the
   logic and say so.
Report: what mounted, how (which API), timings (mount, load, spawn), pack sizes per piece, any engine warnings, and the
screenshots' paths.

## 3. Runtime plugin (DONE)

| Class | Job | Status |
|---|---|---|
| `UDCSubsystem` (GameInstanceSubsystem) | Backend address + region (command line / config), polls `/changes` every 1.5 s, resolves changed slots, owns the download manager, pack cache (LRU, versioned, its own folder per game copy), signature check (RS256 via the engine's platform crypto), telemetry batching | DONE (brief 011) |
| `ADCSlot` | Slot ID, size class, bounds box = class limits, pre-fetch radius; runs the **slot lifecycle** exactly as the figure: IDLE → RESOLVING → DOWNLOADING → VERIFYING → MOUNTING → ACTIVE → SWAP PENDING (player inside) → UNLOAD & PRESERVE; ERROR / FALLBACK with backoff, default content stays | DONE (011, 016) |
| `ADCContentActor` | Builds the interactables from sockets; state = lights A / B, door, screen index (schema 1); brand colour / emblem params | DONE (006, 016) |
| `UDCStateStore` | Saves state on unload keyed by slot + content + schema; restores on spawn; mismatched schema → discard, never crash | DONE (brief 016) |
| `UDCInteractor` | Prompted use of door / switches / screen; each use = an interaction event | DONE (brief 016) |
| UI | Status strip (build · uptime · restarts: 0 · content loading screens: 0 + per-slot state), neutral waypoint marker | DONE (011, 016, clamp 018) |
| `UDCShell` (GameInstanceSubsystem) | Attract loop · title menu (Game A / Game B as two cards) · pause menu (Resume / Switch game / X-ray) · the level load that switches game, with uptime, restarts, the pack cache, the mounted packs and the saved state carried across it · the 90 s idle timeout · the staff-vs-idle reset rule | DONE (brief 018) |
| `UDCShellInput` | The pad and the emergency keyboard, bound to the shell on the **player controller** (there is no pawn in the attract loop or on the title menu) | DONE (brief 018) |
| UI | X-ray view: pre-fetch ring per slot coloured by lifecycle state, the nearest slot's manifest (content, pack, size, SHA-256, signature, region, lot / block, valid until), the cache list in LRU order, the lifecycle log with its milliseconds, and a rolling 10 s frame-time graph ticked at every mount / spawn / unload | DONE (brief 018) |
| Telemetry | view (on screen ≥ 1 s within 30 m, line check), visit (enters slot bounds), dwell, interaction. **None of the four from the attract camera or the preview window** — neither is a Player | DONE (011, 013, 016, 018) |
| Preview mode | `-DCPreview -DCRegion=r2`: no input, no audio, auto-pilot to the slot just auctioned, 30 fps cap, lowest settings, below-normal priority, own cache folder. The attract camera shares the same auto-pilot | DONE (brief 017) |
| Lighting budget | Group B (the wall lamps) and group A (the ceiling fixtures) are kept **out of the Lumen scene** (`IndirectLightingIntensity = 0`), which is where most of the cost of a roomful of small lights goes; both still light the surfaces in front of them and group A still casts shadows | DONE (brief 018) |

The interaction is **Enhanced Input**, bound by the plugin itself: a Shipping build with the
Enhanced Input plugin on processes no legacy key bindings at all, so `UDCInteractor` pushes its
own `UEnhancedInputComponent` onto the player controller's input stack and adds its own mapping
context. The keys live in C++ and only the `UInputAction` is an asset — `FKey`'s `KeyName` is a
private UPROPERTY, so the editor's Python cannot build a key at all. `unreal/README.md` has the
long version, and plan v6 §14 step 6's exit test is `unreal/Tools/state_exit_test.py`.

The menus are the same machinery one step further: `UDCShellInput` builds **both** its actions
and its mapping context in code, because an input action with nothing on it but a name is not
worth an asset. It binds the d-pad and the left stick, the bottom and right face buttons, Start
and View, and — for the emergency keyboard under the table — the arrows, Enter, Esc and F2.
Brief 018's exit test is `unreal/Tools/menu_exit_test.py`, driven by `-DCUiTest`, a hook that
calls the very handlers those bindings call.

Day-1 checks from plan §11 (pad 1 only, background pad 2 untouched, two copies side by side, keeps running unfocused) are the
first acceptance tests once the plugin exists.

## 4. Editor module (DONE — brief 013)

The slot-map tool (plan §6): orthographic top capture → image; every `ADCSlot` → id, pixel position, limits, rules, pre-fetch
radius; eye-level thumbnail per slot; `POST /games/register`.

Built as `DynamicContentsEditor` in the same plugin, with one function — `UDCSlotMapTool::RegisterCurrentLevel` — behind
three doors: the Tools menu entry *"Register this game with Dynamic Contents…"*, the commandlet
`DCRegisterGameCommandlet`, and editor Python (`unreal/Tools/register_games.py`, which does both maps in one session).
The captures are `USceneCaptureComponent2D` into a transient render target and the tool needs **`-AllowCommandletRendering`**
on the command line. Pixel positions come out of the capture camera's own transform, and the playable area out of the
actors the map builder tagged `DCPlayableArea`. `unreal/README.md` has the long version.

## 5. Maps (FUTURE)

Game A (main, slots A1 L, A2 T, A3 S) and Game B (small, B1 L, B2 S): neutral, untitled, clearly different layout, palette and
lighting. Built from a Blender-generated environment kit in the same scripted style as the content.
