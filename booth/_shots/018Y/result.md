# The office exit test — a copy of this tree, on a machine nobody has set up

*Brief 018Y. Run from `C:\DC Office Test\DynamicContents`, unzipped out of the export, with
no Python anywhere on PATH and nothing installed. **PASS: 30 checks, 0 failed, 60 s.***

## What was run

```
Start-Demo.bat                     no arguments, double-click semantics, desk mode
python\python.exe booth\office_exit_test.py --fast
Stop-Demo.bat
```

`Start-Demo.bat` found `python\python.exe` inside the copy, started the server on
127.0.0.1:8700, opened the portal in Edge, skipped the pad helper (no controller plugged
in), and started the game windowed at 1600 × 900 in its attract loop. It waited for the
game's own status file before saying the demo was running.

## The walkthrough

| | step | what it checked |
|---|---|---|
| 1 | everything is up | the server answers; the game's own packs registered; both games registered; all three slots filled, downloaded and mounted at run time; the game's backend is 127.0.0.1 |
| 2 | the brand | a colour and an emblem; the wallet starts at 2,000 |
| 3 | upload, approved | the curated list is one file per piece plus one built to fail; Content 1 approved with its four checks; it fits A1 at 12.5 × 11.1 × 7.3 m |
| 4 | upload, rejected | *"Made for engine 5.3 — this game runs 5.7."* |
| 5 | pick the game, pick A1 | no clock until the first bid |
| 6 | bid, and the rival outbids | the first bid starts a 45 s clock; the rival raised to 350, ceiling 600 |
| 7 | raise, close, won | 375 took it; charged 375, allocation written |
| 8 | the game mounts it | **A1 ACTIVE content1 v1 #2F6FEB chevron** — the real game, the real slot, the brand on it |
| 9 | the region check | the live flip: r1 → r2, the slot swapped to that region's rival, and back on its own |
| 10 | push version 2 | the live game swapped to v2 with the brand kept, no restart |
| 11 | the report | 1 block, 375 charged, counted against 3 mounts |
| 12 | the block ends | the slot went back to rival1 v1, and the server agrees |
| 13 | nothing went anywhere | every TCP connection every process of the copy opened was to 127.0.0.1 — 16 samples through the run |

The browser is deliberately outside that last check: it talks to whatever is on the page
and to its own update service, and it renders the portal rather than being the demo.

## The pictures

`contact_sheet.png` — the game's own window, all seven beats, and it reads as a sequence:

1. **01 / 02 attract** — A1 `rival1 v1 #1FA39A triangle`, A2 `default v1 no-brand`, A3
   `rivalsmall v1`; three packs mounted, the manifest panel saying *signature RS256 ok,
   checked on this machine*.
2. **03** — `A1 L ACTIVE content1 v1 #2F6FEB chevron`: the visitor's own building, in the
   visitor's colour, standing in the slot. Four packs mounted.
3. **04 the live flip** — the strip says **region r2** and A1 is `DOWNLOADING` the other
   region's content while A3 already wears that region's rival colour, `#F28C28 ring`.
4. **05 / 06** — the strip reads `A1 L ACTIVE content1 v2 #2F6FEB chevron`: a new version
   in the live slot, same brand, no restart. Six packs mounted.
5. **07 the block ends** — the strip reads `A1 L ACTIVE rival1 v1 #1FA39A triangle` again.

The camera is wherever the attract loop has got to, which is not always A1; the status
strip at the top of each picture is the thing to read, and it is the game's own account of
what is mounted in every slot at that moment.

A picture is only saved when the game's window is genuinely in front, checked twice: once
after it is raised and again immediately before the grab. A screen grab photographs a
rectangle, not a window, so one taken while something else is over it is a picture of that
something else. An earlier run produced seven of those, and the check is why this one did
not.

## State kept across a swap

`state_exit_test_result.txt` — run from the same copy, 3/3 rounds. The Player opens the
door, turns light B on and sets the screen to image 3; the backend swaps the content while
they are inside; they walk out, it swaps, they walk back in and everything is as they left
it. One of the three rounds is the block ending instead, where a *different* winner takes
the slot and must **not** be wearing the state the Player left on somebody else's content.

## What a run wrote, and where

Everything inside the copy: `_logs\` (the start transcript, the server's output, the game's
own log), `_run\` (the browser profile, the pack cache, the game's `-UserDir`, the status
file and `demo_run.json`), `server\data\` (a new key pair and the registered packs), and
`__pycache__` under `python\` and `server\`.

Nothing outside it. In particular `%LOCALAPPDATA%\DCDemo` was not touched: the game is
given its own `-UserDir` inside the copy, so its settings and its crash folder stay there
too.

## Booth mode

`Start-Demo.bat -Booth`, on one monitor:

* server, Edge in kiosk, the region preview window, then the main game — in that order,
  which is the order that matters;
* the preview copy is up and **hidden**, parked at 30000,30000 (`{"found": true, "rect":
  [30000, 30000, 960, 540], "shown": false}`);
* the main game has the focus: the foreground window is `DCDemo` (the main copy), not the
  preview;
* the main copy plays region r1, the preview copy region r2;
* the main game was placed borderless at 0,0 1920 × 1080.

**Not checked, and could not be:** this machine has one monitor, so "the portal on the
right-hand screen and the game on the left" is the same rectangle twice. The two-monitor
placement and the preview window's home rectangle on the second screen are for the booth.

`Stop-Demo.bat` stopped all four and reported port 8700 free and no game running.
