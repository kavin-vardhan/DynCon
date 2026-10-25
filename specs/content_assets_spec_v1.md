# Content assets — spec v1 (Tokyo demo)

*Written 2026-10-25 by chat Claude for Claude Code. Source of truth for every piece of walk-in content in the demo.
Derived from `DemoPlan/DynamicContents_Tokyo_demo_plan_v6.md` §3, §9, §12. Status: DONE (spec). Every asset: QUEUED.*

## 1. What we are making and why

The demo swaps **content** into fixed **slots** at runtime. Each piece of content is a small walk-in structure that the Player
can enter, with a door, two light switches and a display screen — the things whose state is kept across a "push an update".
Brand identity is **never baked into geometry**: the sign and an accent band take the brand's colour and emblem at mount time.
So one piece of geometry can be "yours" or "the rival's".

Everything is **name-agnostic** — no text anywhere in geometry, textures or file names beyond functional IDs.
Everything is **built by script** in Blender (no hand-modelled geometry, no downloaded models or textures) so it is
licence-clean, reproducible and diffable.

## 2. Size classes = the slot contract

The single source of truth for "does this content fit this slot". The server's fit check uses the same numbers.

| Class | Footprint (X × Y, centred on origin) | Height (Z) | Slots of this class |
|---|---|---|---|
| **S** small | ≤ 7.0 × 7.0 m | ≤ 5.0 m | A3, B2 |
| **L** large | ≤ 14.0 × 14.0 m | ≤ 9.0 m | A1, B1 |
| **T** large + tall | ≤ 14.0 × 14.0 m | ≤ 20.0 m | A2 |

Fit rule: a piece fits a slot when its bounding box is inside the slot class limits. So S pieces fit every slot, L pieces fit
A1 / A2 / B1, and a piece taller than 9 m fits A2 only.

## 3. The pieces (13 builds)

| ID | Role | Class | Versions | v1 shape | v2 shape (must look clearly different) |
|---|---|---|---|---|---|
| `default` | Developer's default placeholder | S | v1 only | Open canopy: plinth ~6 × 6 m, four posts, flat roof slab ~3.6 m, a bench. Neutral greys. **No** door, switches, screen, sign or brand accent | — |
| `content1` | Uploadable | L | v1, v2 | "Hall": rectangle ~12 × 10 m, flat roof with parapet ~6 m, full-height glazed front with the door in the middle, sign band above the door | Same footprint, sawtooth (north-light) roof ~7.5 m, vertical fins instead of the glass front, entrance canopy |
| `content2` | Uploadable | L | v1, v2 | "Drum": cylinder Ø ~12 m, wall ~5.5 m, shallow dome to ~8 m, ribbon window band | 12-sided faceted prism, folded / conical roof ~8.5 m, ring of external columns |
| `content3` | Uploadable, **tall** — fits A2 only | T | v1, v2 | "Tower": walk-in base hall ~10 × 10 × 5 m with two stacked closed volumes above, total ~17 m (must be > 9 m) | Stacked volumes each rotated ~15° (twist), different window pattern, roof crown, ~18.5 m |
| `content4` | Uploadable, **small** — fits every slot | S | v1, v2 | "Cabin": ~6 × 5 m, gable roof ridge ~4.6 m, door on the gable end, a window each side | Mono-pitch (shed) roof, porch on posts, round window |
| `rival1` | Rival (region 1) | L | v1 only | L-shaped hall in a ~13 × 13 m box, flat roof ~6.5 m | — |
| `rival2` | Rival (region 2) | L | v1 only | Hexagonal pavilion ~12.5 m across, folded roof ~7.5 m | — |
| `rival3` | Rival (region 3) | L | v1 only | Barrel-vault (arched) hall ~12 × 10 m, ~7 m high | — |
| `rivalsmall` | Rival, small slots | S | v1 only | Cube kiosk ~5 × 5 m, slanted roof ~4.8 m | — |

Rival colours/emblems are runtime data (server config), not geometry. Region ↔ rival mapping lives in the server config.

## 4. Conventions (every piece)

- **Units / axes:** metres, unit scale 1.0, Z up. **Origin = slot anchor = centre of the footprint at ground level (z = 0).**
  Nothing below z = 0. **Front (main door side) faces −Y** in Blender. (The UE side applies one constant yaw offset; it is
  verified when the UE project exists.)
- **Walkable:** walls ≥ 0.20 m thick, closed geometry, no gaps a 0.42 m-radius capsule could slip through. Door clear opening
  ≥ 1.6 m wide × 2.6 m high. Interior clear height ≥ 3.5 m. Floor top ≤ 0.15 m above ground; no step > 0.15 m. Collision in UE
  will be "use complex as simple", so the render mesh *is* the collision — keep it clean.
- **Interior** (every walk-in piece): floor, interior wall finish, ceiling, light-group **A** (ceiling fixtures) and
  **B** (wall / accent fixtures), the **screen** on the wall facing the door, the **two switches** inside next to the door at
  1.2 m, and a little generic furniture (plinths, benches, a table — simple blocks) leaving a clear path door → screen.
  Rooms should feel roomy for a third-person camera: large pieces ≥ 9 × 8 m inside; small pieces as big as the class allows.
- **Detail level:** clean "architectural model" look — bevelled edges (0.02–0.05 m), mullions, trims, parapets, plinths.
  Flat colours, no textures. Each piece gets its own neutral palette (warm white, pale grey, sand, blue-grey, …) so pieces are
  told apart by shape and tone — never by theme.
- **Budgets:** ≤ 60 k triangles per piece, ≤ 13 material slots, deterministic (no unseeded randomness).

### Material slots (exact names; the only ones allowed)

`M_Wall`, `M_WallInterior`, `M_Floor`, `M_Roof`, `M_Trim`, `M_Glass`, `M_Metal`, `M_Door`, `M_Switch`,
`M_LightEmissive` (fixture glow; toggled with its light group), `M_BrandAccent` (tinted with the brand colour at runtime),
`M_Sign` (brand colour + emblem at runtime), `M_Screen` (runtime image).
Each piece's manifest records base colour / roughness / metallic / emissive per slot so UE can rebuild them as material
instances.

### Separate objects (each becomes its own static mesh in UE)

| Object | What | Rules |
|---|---|---|
| `SM_<id>_<v>_Shell` | everything static (walls, floor, roof, glass, furniture, light fixtures) | sockets are parented to it |
| `SM_<id>_<v>_Door` | door leaf | origin on the hinge axis at floor level; modelled closed; opens 90° inward about Z (manifest says which sign) |
| `SM_<id>_<v>_Switch` | one switch (plate + rocker) | placed twice via sockets |
| `SM_<id>_<v>_Screen` | display quad, 16:9 | front faces into the room; UVs exactly 0–1 so a full image maps edge to edge |
| `SM_<id>_<v>_Sign` | sign panel above the door, 2:1 | front faces −Y (outside); UVs exactly 0–1; readable from 20 m (L ≈ 3.0 × 1.5 m, S ≈ 1.6 × 0.8 m) |

`M_BrandAccent` goes on a band / frame / stripe clearly visible from the approach.

### Sockets (empties named `SOCKET_<name>`, parented to the Shell, exported with it)

`SOCKET_Door` (hinge), `SOCKET_SwitchA`, `SOCKET_SwitchB`, `SOCKET_Screen`, `SOCKET_Sign`, `SOCKET_LightA_1..n`,
`SOCKET_LightB_1..n`, `SOCKET_Waypoint` (above the roof, front side — the Player's marker), `SOCKET_Inside` (a standing point
inside, for the preview window's auto-pilot), `SOCKET_ThumbCam` (eye-level ~1.7 m, ~15 m in front, looking at the piece —
portal thumbnail). Plus `VOLUME_Interior`: an empty (cube display) whose box = the walkable interior, for visit / dwell.
`default` has only `SOCKET_Waypoint`, `SOCKET_ThumbCam` and `VOLUME_Interior` (under the canopy).

**v1 and v2 of the same ID must share the exact same socket names and interactable set** — that is the state-preservation
schema (lights A/B on/off, door open/closed, screen image index; schema version 1).

## 5. Outputs

Per piece-version, under `art/` (all committed):

- `art/blend/<id>_<v>.blend` — the generated scene, saved for anyone who wants to tweak by hand.
- `art/export/<id>_<v>/<id>_<v>.fbx` — all objects + sockets, for UE import (no mesh combining).
- `art/export/<id>_<v>/<id>_<v>.glb` — same content, for the portal's 3-D preview.
- `art/export/<id>_<v>/manifest.json` — id, version, class, bounds min/max, fits_slots, triangle count, materials table,
  sockets (location + rotation), interior volume, door hinge + open sign, `schema_version: 1`, `front_axis: "-Y"`,
  generator script hash.
- `art/previews/<id>_<v>_ext.png` (¾ front view), `_int.png` (from just inside the door, looking at the screen),
  `_top.png` (orthographic top with the size-class limit drawn as a frame) — 1600 × 900, rendered with a sample brand colour +
  emblem on the sign, light group A on, a sample image on the screen.
- `art/previews/contact_sheet.png` — every piece's ext + int view on one sheet, labelled by functional ID only.
- `art/emblems/<shape>.png` — 1024² white shape on transparent: circle, triangle, square, diamond, star, ring, chevron, hexagon.

## 6. Tooling

- `art/blender/dc_kit.py` — shared library: scene / unit setup, the material slots, construction helpers (wall runs with door
  and window openings built from segments — prefer construction over booleans), roofs, door, switch, screen, sign, fixtures,
  sockets, bevel, export, render, manifest.
- `art/blender/pieces/<id>.py` — one per ID with `build(version) -> metadata`.
- `art/blender/build_all.py` — `blender -b --factory-startup -P art/blender/build_all.py -- --only <ids>`: fresh scene per
  piece → save .blend → export FBX + GLB → render previews → manifest.
- `art/tools/validate_assets.py` — plain Python over the manifests: bounds inside class, required sockets / objects / material
  slots present, triangle budget, door clearance, v1 = v2 socket set. Non-zero exit on any failure; prints a table.
- `art/tools/contact_sheet.py` — Pillow.
- `art/build.ps1` — finds Blender and runs the lot; `-Only` filter.

## 7. Out of scope here

Map environment kits (Game A / Game B), UE import and material instances, pak cooking (needs the UE project), the
built-to-fail file (a metadata fake, not art).
