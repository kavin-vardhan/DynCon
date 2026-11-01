# The region preview window: frame time with and without it

*10 minutes of the main game's scripted tour on Game A at 1600 x 900, run twice. Written by `unreal/Tools/preview_frametime_test.py` on 2026-11-02 02:02.*

| | frames | average | median | worst 1 % | worst | over 16 ms | over 25 ms | laps |
|---|---|---|---|---|---|---|---|---|
| solo | 37,475 | **16.00 ms** (62 fps) | 15.91 ms | **22.72 ms** | 68.19 ms | 18,037 | 108 | 7 |
| with the preview | 31,961 | **18.80 ms** (53 fps) | 18.78 ms | **27.69 ms** | 35.46 ms | 24,571 | 1,178 | 7 |

## The pass line (plan v6 §11, brief 018)

* solo average at or under 15 ms: **16.00 ms** — FAIL
* worst 1 % with the preview under 25 ms: **27.69 ms** — FAIL
* average within 15% of solo (16.00 ms → at most 18.40 ms): **18.80 ms** (+17.5%) — FAIL

**FAIL**

### solo

* 63 / 63 walk legs arrived over 7 lap(s) in 609 s
* slots: A1 content1 v1, A2 content3 v1, A3 content4 v1

### with_preview

* 63 / 63 walk legs arrived over 7 lap(s) in 610 s
* slots: A1 content1 v1, A2 content3 v1, A3 content4 v1
* the preview window played as India (r2), framing A3 (the visitor's newest allocation)
* it showed: A1 rival2, A2 default, A3 rivalsmall
* its own frames: 18581 at 33.35 ms average; telemetry sent 0, dropped 12 (a preview is not a player)
* its window: 960 x 540 at (960, 270)
