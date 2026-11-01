# The environment kit — what it is and how to build it

*Written 2026-11-01 (brief 012). Plain-words guide for a cold reader. Status of each item is
marked **DONE / QUEUED / FUTURE**.*

The content pieces in `art/blender/pieces/` are **content**: they arrive at runtime, they have
sockets, a door, a sign and a brand. This folder is the opposite — the **environment**: it
ships inside the build, it never changes, it has no sockets and it can never wear a brand. Its
only job is to make two places that read as two different games, and to frame the dynamic
slots without competing with them.

```powershell
.\art\build.ps1 -EnvOnly               # the 23 pieces, both palettes, validate, sheet
.\art\build.ps1 -EnvOnly -NoRender     # geometry and exports only - seconds, not minutes
.\art\build.ps1 -EnvOnly -OnlyEnv bench,tree_tall
.\art\build.ps1                        # the content, then the environment
```

| File | What | Status |
|---|---|---|
| `env_kit.py` | the kit: material slots, the two palettes, `EnvPiece`, export, manifest, previews | DONE |
| `ground.py` | paving, kerbs, steps, boardwalk, pier deck and posts, quay wall, the slot pad | DONE |
| `buildings.py` | the three background blocks, the arcade, the shed | DONE |
| `props.py` | trees, shrub, bench, lamp post, planter, bollard, railing, fountain | DONE |
| `build_env.py` | the driver: fresh scene → .blend → FBX + GLB → previews → manifest | DONE |
| `../../tools/validate_env.py` | the checker `art/build.ps1` gates on | DONE |
| `../../tools/env_sheet.py` | `art/previews/env_contact.png` — the one picture that goes in git | DONE |

**23 pieces, 9,696 triangles in the whole kit.** The budgets are per category and deliberately
tight (ground 1,500 · street 3,000 · planting 4,000 · building 14,000): a plaza puts a couple
of hundred of these on screen at once, and a content piece's budget is 60,000 on its own.

## What it reuses, and what it does differently

It is a small cousin of `art/blender/dc_kit.py` and borrows that file's `MeshBuilder` — the
same welded-group polygon builder with the same outward-normal checks — its colour maths, its
bevel and its export plumbing. What it does differently:

- **its own material slots** — paving, kerb, timber, foliage, water — instead of the content's
  wall/door/sign/screen list. There is deliberately **no `M_BrandAccent`, `M_Sign` or
  `M_Screen`**, and `validate_env.py` fails a piece that uses one: a piece of environment must
  never be able to wear a brand;
- **two palettes**, `warm` (Game A, the plaza) and `cool` (Game B, the waterfront). The
  geometry does not depend on the palette and is exported **once**; the palette is a set of
  material instances the map chooses per actor. That is why there is one FBX per piece and not
  two, and why `art/export_env/palettes.json` exists — it is the colour table
  `unreal/Tools/env_import.py` reads;
- **no dynamic lights anywhere**. A walk-in content piece already spawns about a dozen
  shadow-casting point lights and three slots of content is most of this PC's light budget, so
  a lamp post carries an emissive material and no light component.

## The units contract is the same as the content's

Authored in metres, **FBX in centimetres**, GLB in metres, and every manifest carries
`bounds_cm` mirrors so the validator can prove it. One flag in
`unreal/Tools/env_import.py` decides whether that survives the trip:
`transform_vertex_to_absolute` must be **False**. The FBX already has the ×100 baked into its
vertex data, but its header still says "one unit is one metre" (Blender's scene is in metres),
so with that flag on the importer applies the header scale as well and an 8 m paving slab
arrives 800 m wide. It did, the first time. The importer now compares every mesh's imported
size against its manifest and fails loudly if they disagree.

## The anchor convention

Every piece's origin is its **ground-contact centre** — centred in plan, z = 0 at the bottom —
and a piece that runs in a line (kerb, railing, boardwalk, steps, quay wall) runs along **+X**.
A placement in `unreal/Tools/make_maps.py` is then a location and a yaw and nothing else.

"Centred in plan" is checked on `ground_bounds`, the footprint of everything below 0.6 m, not
on the whole bounding box: a lamp post's arm reaches a metre out at four metres up and that is
not a badly anchored piece.

## Collision

Each piece declares `blocking` or `decoration` in its manifest, and the map builder sets the
actor's collision from it. Paving slabs are **blocking** and stand about 14 cm proud of the
map's ground plane — the Player walks on the slabs and the lip where the paved area ends reads
as the edge of the plaza. Only the shrub is decoration.

Two things the first walk-through found, both fixed in the geometry rather than worked around:

- **`steps` has no cheek walls.** A flight is laid several pieces wide, and a wedge at each
  piece's edge put a 0.64 m wall across the flight every four metres — which is exactly what
  stopped the Player walking up onto Game A's terrace.
- **`slot_pad`** exists because the packaged build contains none of the content: between the
  map loading and the backend's first answer a slot has nothing in it, and a prepared paved pad
  with a kerb band reads as a place waiting for something rather than as a hole in the paving.
  It is environment, not content, so it costs nothing and carries no brand.

The picture of all of it, both palettes side by side, is `art/previews/env_contact.png`.
