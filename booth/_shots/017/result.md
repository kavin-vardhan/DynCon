# The region preview window: the exit test

*`booth/preview_exit_test.py`, 2026-11-01 23:27. The packaged Shipping build twice (the main game and the preview), the demo server, the pad helper and the portal - every press simulated through the helper, nothing clicked.*

## What happened

* A1 in India: rival2 v1 (rival)
* the main game's window: 'DCDemo  ' at (-8, 509, 976, 579)
* focus at the start: the main game ('DCDemo  ')
* the auction: won in Japan, lost in India
* waiting for the main game to mount the visitor's content in A1
* the main game shows A1 = content1 v1 #E23D3D circle
* the portal leaves [960, 270, 960, 540] free (page coordinates, 1920 x 1080)
* the preview window: {'found': True, 'rect': (960, 270, 960, 540), 'shown': True, 'visible': True, 'minimised': False}
* it is on its home rectangle (960, 270, 960, 540) - the rectangle the portal's Region-check step leaves free
* the preview shows A1 = rival2 v1 #F28C28 ring - the India rival's building, not the visitor's
* the preview plays as India (r2), framing A1 because the slot the visitor last bid on
* focus while the window is shown: the main game ('DCDemo  ')
* the portal set the preview's region to r1 (Japan / 日本)
* the same window, the same slot: A1 = content1 v1 #E23D3D circle - the visitor's own
* focus after the flip: the main game ('DCDemo  ')
* after leaving the step: {'found': True, 'rect': (30000, 30000, 960, 540), 'shown': False, 'visible': True, 'minimised': False}
* the window is off-screen again and the portal has the whole screen back
* focus after the window is hidden: the main game ('DCDemo  ')
* the portal asked for a live flip to India (r2) for 19.9 s
* the MAIN game is now playing as r2 and A1 is rival2 #F28C28 ring - the swap happened in front of the Player
* ...and r1 again by itself, with A1 back to content1 #E23D3D circle
* focus handed to 'Dynamic Contents — brand portal - Profile 1 - Microsoft\u200b Edge' on purpose - the main game is now in the background
* unfocused, the main game still ran at 85 fps (424 frames in 5 s)
* and it was still drawing: its window is a different picture five seconds later

## The main game's frame time, phase by phase

*Its own counters, from the status file it writes four times a second. The worst 1 % column is over the whole run so far, which is why it only grows.*

| phase | seconds | frames | average | worst 1 % (run) | over 16 ms | over 25 ms |
|---|---|---|---|---|---|---|
| before the region check | 23 s | 1923 | **10.90 ms** (92 fps) | 15.95 ms | 42 | **2** |
| the region check, window shown | 11 s | 862 | **12.00 ms** (83 fps) | 16.55 ms | 9 | **0** |
| after it is hidden | 11 s | 846 | **12.75 ms** (78 fps) | 16.50 ms | 15 | **0** |

**PASSED**

