# Brief 018 exit test - 1600x900

*2026-11-02 16:31, one packaged Shipping run, 90 s, exit 0.*

* **PASS** - 0 problem(s) inside the game
* game switches: **4**
* the strip at the end: restarts **0**, content loading screens **0**, uptime 82 s, 5 pack(s) mounted

## The steps

```
  14.0 s  step  0  wait for the backend to fill the slots
  14.0 s  step  1  attract
  15.1 s  step  2  a button on the player pad
  16.0 s  step  3  the title menu
  16.8 s  step  4  pick Game B
  22.6 s  step  5  Game B is up
  26.4 s  step  6  walk to B1
  26.4 s  step  7  pause
  27.0 s  step  8  X-ray on
  28.1 s  step  9  the X-ray with the pause menu
  29.1 s  step 10  resume
  30.3 s  step 11  the X-ray from third person
  31.4 s  step 12  pause again
  32.0 s  step 13  switch to Game A
  34.0 s  step 14  Game A is up
  39.1 s  step 15  walk to A1's door
  39.8 s  step 16  open A1's door
  42.0 s  step 17  walk into A1
  43.8 s  step 18  lights B on in A1
  44.8 s  step 19  walk across to A1's screen
  45.7 s  step 20  the screen on in A1
  45.8 s  step 21  A1 as the Player leaves it
  46.9 s  step 22  pause
  47.4 s  step 23  switch to Game B
  49.3 s  step 24  Game B is up again
  51.4 s  step 25  pause
  51.9 s  step 26  switch back to Game A
  53.8 s  step 27  Game A is up again
  60.0 s  step 28  walk back into A1
        A1 came back as: lights A on / B on, door open, screen 3
  61.5 s  step 29  A1 is as it was left
  61.6 s  step 30  A1 on the way back
  76.6 s  step 31  the idle timeout
  79.6 s  step 32  attract again
```

## The status strip at the end

```
build Shipping  ·  uptime 00:01:21  ·  restarts: 0  ·  content loading screens: 0
backend http://127.0.0.1:8705  game A  region r1  ·  ok  ·  polls 59  changes 13  packs mounted 5
A1  L  ACTIVE        content1 v1 #E23D3D star
A2  T  ACTIVE        content3 v1 #E23D3D star
A3  S  ACTIVE        content4 v1 #E23D3D star
```

## The portal's "playing at this booth" badge

```
   0.1 s  badge -> game A
  23.8 s  badge -> game B
  39.1 s  badge -> game A
  54.3 s  badge -> game B
  58.9 s  badge -> game A
```

## Screenshots

* `01_01_attract.png`
* `01_03_xray_pause.png`
* `01_06_a1_as_left.png`
* `01_07_a1_as_found.png`
* `02_02_title.png`
* `02_04_xray_world.png`
* `02_08_attract_again.png`
* `03_05_loading.png`

**PASS**

