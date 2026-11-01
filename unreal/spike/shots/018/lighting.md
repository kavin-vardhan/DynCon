# What the lamps inside a piece of content cost

*Brief 018 part 1. Every row is the same scripted tour of Game A at 1600 × 900 in the same
packaged build against the same server; the only thing that moves between rows is one set
of `-DCLight*` switches on the command line. Written up from two runs of
`unreal/Tools/light_sweep.py --minutes 3` on 2026-11-02 and the six one-lap passes of
`unreal/Tools/light_shots.py`, which are the rows the pictures in
`lighting_before_after.png` come from.*

## The question

Brief 016 gave every piece a second group of lamps the Player can switch on at a wall
switch, and the brief for 018 recorded the solo baseline drifting from 12.47 ms to 17.82 ms
when they arrived. Three pieces of content with group B on is **eighteen extra point
lights**, so: is it the shadow, the reach, the count, or the fact that Lumen has to light
its whole surface cache with each of them?

## Three minutes a row

| setting | what | average | median | worst 1 % | over 16 ms | over 25 ms |
|---|---|---|---|---|---|---|
| `b_off` | group B not built at all — the lower bound | 15.15 ms | 15.37 | 21.85 | 4,060 | 9 |
| `baseline` | brief 016 as shipped: 6 lamps, shadowless, 320 lm, r = 3.2 m, lighting Lumen | **15.68 ms** | 16.01 | 21.64 | 5,643 | 7 |
| `b_shadows` | …and casting shadows, to price the shadow on its own | 15.80 ms | 15.94 | **23.42** | 5,333 | 42 |
| `b_tight` | …with the reach cut from 3.2 m to 2.0 m | 15.55 ms | 15.89 | 21.80 | 5,331 | 7 |
| `b_half` | …3 lamps at twice the lumens instead of 6 | 15.50 ms | 15.78 | 21.67 | 4,937 | 4 |
| **`b_nogi`** | **6 lamps, shadowless, out of the Lumen scene (indirect scale 0)** | **15.38 ms** | 15.43 | 21.76 | 3,986 | 10 |
| `b_nogi_tight` | out of the Lumen scene and a 2.4 m reach | 15.39 ms | 15.61 | 21.64 | 4,427 | 9 |
| `a_one_shadow` | B out of the Lumen scene, one group-A fixture casting | 15.11 ms | 15.47 | 19.91 | 4,001 | 2 |
| `a_nogi` | both groups out of the Lumen scene | 13.25 ms | 13.66 | 19.94 | 1,668 | 4 |
| `a_half` | B out of the Lumen scene, half the ceiling fixtures at twice the lumens | 14.88 ms | 15.14 | 20.58 | 3,254 | 4 |
| `pick` | B out of the Lumen scene, one group-A shadow-caster, half of A | 15.01 ms | 15.13 | 20.14 | 3,114 | 3 |
| `all_off` | no lamps inside a piece at all — the floor of the whole question | 14.96 ms | 15.30 | 19.73 | 3,523 | 2 |
| `probe_novsm` | PROBE: virtual shadow maps off | 15.53 ms | 15.78 | 21.43 | 4,967 | 12 |
| `probe_nolumen` | PROBE (inconclusive, see below): Lumen GI off | 15.22 ms | 15.33 | 21.29 | 3,657 | 7 |

## One lap a row, back to back, and these are the pictures

| setting | average | worst 1 % |
|---|---|---|
| `off` — the lamps built but switched off | 13.74 ms | 19.98 ms |
| `before` — on, both groups lighting the Lumen scene (brief 016) | 15.20 ms | 21.44 ms |
| **`b_nogi` — on, out of the Lumen scene (brief 018)** | **14.73 ms** | **20.97 ms** |
| `nogi` — on, both groups out of the Lumen scene | 15.01 ms | 20.45 ms |
| `off_nogi` — off, both groups out of the Lumen scene | 14.54 ms | 20.58 ms |
| `a_half` — half the ceiling fixtures at twice the lumens | 12.58 ms | 18.76 ms |

## What it says

1. **The wall lamps are not where the frame time is.** As brief 016 shipped them the
   eighteen of them cost **0.5 ms** of average frame time (`b_off` 15.15 → `baseline`
   15.68), not the five the brief's premise assumed. The 12.47 → 17.82 ms drift recorded
   against them is not a thing they do: with group B never built at all, this machine still
   runs the same tour at 15.15 ms.
2. **Of the things one lamp can be, only Lumen matters.** The shadow costs 0.1 ms of average
   and 1.8 ms of the *tail* (`b_shadows`, and 42 frames over 25 ms against 7). The reach and
   the count are each worth about 0.15 ms. Taking the lamps **out of the Lumen scene** —
   `IndirectLightingIntensity = 0`, which is the gate `LumenSceneDirectLighting.cpp` reads
   before it relights the surface cache with a light — is worth 0.3 ms on its own and is the
   only one of the four that changes nothing in the picture.
3. **Run-to-run drift on this machine is about ±1 ms over ten minutes**, which the two
   tables between them make plain: `a_nogi` measured 13.25 ms in one batch and `nogi` — the
   same settings — 15.01 ms twenty minutes later, and `all_off` came out *slower* than
   a configuration with thirty-two lamps in it. Nothing under about 1 ms separating two rows
   measured minutes apart should be believed, which is why the decision below rests on the
   pictures and not on the smallest number.
4. `probe_nolumen` is **inconclusive**: `r.DynamicGlobalIlluminationMethod` is a scalability
   variable the renderer reads when the scene is built, and setting it from the command line
   afterwards does not take. It is left in the table so nobody repeats it.

## The decision, and why it is not the fastest row

**Group B is taken out of the Lumen scene and nothing else changes.**
`ADCContentActor::bLightBAffectsGi = false`, `bLightAAffectsGi = true`.

The two faster options were both rejected by looking at `lighting_before_after.png`:

* **`nogi`** — group A out of the Lumen scene as well. The rooms lose the bounce off their
  own ceilings and go flat and grey: A1 turns from a cool white room into a brown one, A2
  loses its warm wash. It is a different-looking demo, and the lamps-on / lamps-off contrast
  the brief asks to keep gets *weaker* rather than stronger (compare the `nogi` and
  `off_nogi` rows — they are nearly the same picture).
* **`a_half`** — half the ceiling fixtures at twice the lumens, the fastest row on the sheet
  at 12.58 ms. `dc_kit.light_a_fixture` models a **fitting** at every group-A socket, so
  lighting one socket in two leaves half of them modelled and dead. None of these eye-level
  shots happens to look at a ceiling; a visitor standing inside one of these rooms would.

`b_nogi` is the row that is the same picture as `before` — which is the whole test — and it
is the only change made.
