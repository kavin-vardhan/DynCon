# Frame times, before and after brief 013

Same command both times, same packaged **Shipping** build on the same PC, same 1600 × 900
window, one visitor allocation per slot, the scripted tour walking the Player to every slot
and in through its door:

```powershell
server\.venv\Scripts\python.exe unreal\Tools\map_check.py --game A
server\.venv\Scripts\python.exe unreal\Tools\map_check.py --game B --region r2
```

Frame times exclude the first four seconds and any frame within half a second of a shutter.

| | | average | median | **worst 1 %** | worst | frames | walk |
|---|---|---|---|---|---|---|---|
| **Game A** | before (brief 012) | 12.47 ms (80 fps) | 12.96 ms | **19.05 ms** | 26.05 ms | 7,252 | 9 / 9 |
| | after (brief 013) | **11.35 ms (88 fps)** | 11.67 ms | **16.65 ms** | 46.69 ms | 7,951 | 9 / 9 |
| **Game B** | before (brief 012) | 11.33 ms (88 fps) | 11.10 ms | **17.66 ms** | 29.94 ms | 3,899 | 6 / 6 |
| | after (brief 013) | 12.36 ms (81 fps) | 12.62 ms | **17.61 ms** | 30.32 ms | 3,575 | 6 / 6 |

Restarts 0 and content loading screens 0 in all four runs.

## What this does and does not show

It shows the maps did not get slower when they gained a second ground tone, a patch of grass
and a dedicated 7 m pad for the S slots: Game A came out about a millisecond faster and Game
B about a millisecond slower, in both directions inside the run-to-run spread of a desktop
that is also running a browser.

It does **not** measure the group-B shadow change, and the honest reason is worth writing
down. Group B is the wall lamps, and they are **off until a visitor flips the switches**
(`bLightBOn = false`); the scripted tour walks and photographs but does not interact, so
every frame above was rendered with group B dark and therefore costing nothing either way.
The change is in the build — the log of the run above reads

```
BUILD ok  content2_v1  ... lightsA=4(on 1200lm r600) lightsB=6(off 320lm r320) shadowsA=yes shadowsB=no ...
```

— but what it is worth will only show up when the interaction of plan v6 §14 step 5 exists
and something turns six shadow-casting lamps on inside a 14 m building. On this PC the worst
1 % is where that would land, which is why the flag went in now rather than later.
