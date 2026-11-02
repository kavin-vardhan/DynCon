===============================================================================
 DynamicContents - runtime dynamic content for Unreal
 A working demo. Unzip, double-click, show it.
===============================================================================

This file is written for somebody who has never seen the project. It is exported
to the root of the copy as README.txt.


-------------------------------------------------------------------------------
1. WHAT THIS IS
-------------------------------------------------------------------------------

A shipped game map has fixed empty DYNAMIC SLOTS in it. When a player walks near
one, the game asks a backend what belongs there right now, downloads a signed,
versioned content pack, checks the signature and the hashes, mounts the pack
while the game is running and spawns what is inside it at the slot.
No restart, no loading screen, no patch to the game.
Brands upload their content and bid for slots through a web portal, and the
winner's building appears in the live game minutes later.

Everything here runs on one PC: a demo server standing in for the cloud, two
game maps with three and two slots, thirteen pieces of content, and the brand
portal. The two regions it talks about are simulated on the one machine.


-------------------------------------------------------------------------------
2. WHAT THE PC NEEDS
-------------------------------------------------------------------------------

  * Windows 10 or Windows 11, 64-bit.
  * A graphics card that does DirectX 12, with its driver up to date. Anything
    that plays a current game is fine. About 8 GB of RAM free.
  * Microsoft Edge, which is already on every Windows 11 machine. The portal is
    a web page; any Chromium browser would do, but the start script looks for
    Edge.
  * About 1.5 GB of free disk space for what the demo writes while it runs.
  * NOTHING ELSE. No Python, no Unreal Engine, no internet. The interpreter the
    server runs on travels in this folder, in python\, with every package it
    needs already installed. Nothing here ever connects to anything but
    127.0.0.1 - your own machine.
  * Game controllers are OPTIONAL. One controller drives the game, a second one
    drives the portal. Without them the keyboard does both (section 4). If no
    controller is plugged in the start script simply does not start the pad
    helper.
  * The first time a game built with Unreal runs on a machine it may ask to
    install the Microsoft Visual C++ runtime. The installer for it is in this
    folder at game\Engine\Extras\Redist\en-us\vc_redist.x64.exe - run that
    once, by hand, and the game will start. It needs no internet.


-------------------------------------------------------------------------------
3. START AND STOP
-------------------------------------------------------------------------------

  Start-Demo.bat          double-click it. Starts everything, in order:
                          the server, the portal in a browser window, the pad
                          helper if a controller is plugged in, and the game.

  Stop-Demo.bat           double-click it. Stops exactly what Start-Demo.bat
                          started, and says so.

That is the whole of it. The window that opens prints what it is doing and then
closes; it does not have to stay open.

Useful variations, from a command prompt in this folder:

  Start-Demo.bat -Reset           throw away the server's state first: a new
                                  signing key, an empty database, the packs
                                  registered again. Use this between people, or
                                  if anything looks stuck.
  Start-Demo.bat -Booth           the two-monitor setup: the portal full screen
                                  on the right-hand monitor, the game
                                  borderless on the left-hand one, and a second
                                  copy of the game as the region preview
                                  window. Set the game's monitor as the primary
                                  display in Windows first.
  Start-Demo.bat -Game B          start on the second map instead of the first.
  Stop-Demo.bat -Any              stop a game or a server that was started some
                                  other way, or left over from a crash.

Where things go. Everything the demo writes stays inside this folder:

  _logs\        one log per run: the start script's own transcript, the
                server's output, and the game's own log. The game's log is the
                one worth reading: every slot change, every download, every
                signature check and every mount, with timings.
  _run\         state that belongs to this run: the browser profile, the two
                content caches, and demo_run.json, which is the list of what
                was started.
  server\data\  the server's signing keys, its database and the content packs
                it has been given. Made on first run. Delete it, or use -Reset,
                and the next run makes a new key pair - the game is handed the
                public key when it starts and trusts nothing else, so a brand
                new key works with this exact game with no rebuild.


-------------------------------------------------------------------------------
4. THE CONTROLS
-------------------------------------------------------------------------------

THE GAME (keyboard)

  Any key           wake it out of the attract loop into the title screen
  Left / Right      choose which game
  Enter             confirm - start playing, or pick a menu entry
  W A S D           walk
  Mouse             look
  Space             jump
  E                 use whatever you are standing in front of: a door, a light
                    switch, the screen on the wall
  Esc               the pause menu (and Esc again to leave it)
  F2                the X-ray view: draws the slot boundaries, what is mounted
                    in each one and where it came from

THE GAME (controller 1)

  Any button        wake it out of the attract loop
  D-pad or stick    move, and navigate a menu
  A (bottom face)   confirm, and "use"
  B (right face)    back
  Start             the pause menu
  View / Share      the X-ray view

THE PORTAL (keyboard)

  Arrow keys        move around the screen
  Enter or Space    confirm
  Esc or Backspace  back
  Tab / Shift+Tab   right / left

THE PORTAL (controller 2, when one is plugged in)

  D-pad or stick    move around the screen
  A                 confirm
  B                 back

STAFF COMBOS (controller 2, hold all three together for three seconds)

  LB + RB + Back    reset the demo for the next visitor
  LB + RB + X       close the auction now, instead of waiting for its clock
  LB + RB + Y       corrupt the next download on purpose, to show the pack
                    being refused
  LB + RB + B       freeze the next download for a few seconds, to show the
                    retry


-------------------------------------------------------------------------------
5. THE TEST WALKTHROUGH
-------------------------------------------------------------------------------

Twenty minutes, start to finish. Do it in order the first time: each step leaves
the demo in the state the next one expects. "What you should see" is the point of
each step - if that is not what happens, section 6.

  0. Start-Demo.bat -Reset

  1. ATTRACT. The game window shows the map from the air, drifting between the
     three slots, naming what is in each one.
     SEE: three slots, each with something in it already - the rival brand's
     buildings and one plain developer default. Nothing is empty. The strip
     across the bottom of the screen names the piece and its version.

  2. TITLE. Press any key.
     SEE: two cards, one per game, each with a plan view of its map. The plan
     views are the developer's own, captured from the real maps and registered
     with the platform - which is how the portal can show a brand where the
     slots are without the brand ever seeing the game.

  3. GAME A. Choose the left card and press Enter.
     SEE: you are standing in the map as a third-person character. Walk with
     WASD. The slot nearest you has a marker over it.

  4. THE BRAND. Now go to the portal window. Press any key to leave its attract
     screen, then choose a colour and an emblem for your brand.
     SEE: a brand is a colour plus a simple shape, and nothing else - no names
     anywhere in this demo, on either screen. A wallet of 2000 credits.

  5. UPLOAD, APPROVED. Choose Upload. The list headed "your computer" has one
     file per piece of content.
     SEE: pick any of the first four. Four checks run in front of you - the
     signature, the size against the slot classes, the engine version, the age
     rating - and it is approved, with its measured size in metres.

  6. UPLOAD, REJECTED. Upload again and pick the last file in the list, the one
     already marked "built for engine 5.3".
     SEE: it is refused, and the screen says exactly why, in a sentence. This is
     the point of the checks: the platform will not put something into a live
     game that was not built for it.

  7. PICK A GAME, PICK A SLOT. Choose Game A, then the slot map, then slot A1.
     SEE: the plan view of the map with the three slots pinned on it, each with
     its size class (A1 large, A2 tall, A3 small) and how many players a day
     walk past it in each region.

  8. BID. Bid for A1 in the first region. The opening price is a quarter of the
     footfall, rounded.
     SEE: a few seconds later the rival outbids you. Raise. The rival stops at
     twice the opening price, so your next raise wins. The auction clock runs
     down; the last ten seconds are a soft close, so a late bid extends it.
     WON appears, and the money moves from available to held.

  9. WALK TO IT. Back to the game. Walk to slot A1 - the marker shows where.
     SEE: the strip at the bottom goes through the whole cycle as you approach:
     RESOLVING, then DOWNLOADING with the megabytes counting up, then VERIFYING,
     then MOUNTING, then ACTIVE. Then your building is standing in the slot,
     in your colour, with your emblem on it. It was not in the game when the
     game started, and it has not restarted.

 10. GO INSIDE. Walk through the door, press E on things.
     SEE: the door opens, the light switches work, the screen on the wall
     changes picture. Three things worth noticing: the inside is lit by its own
     lights, not by the sun; the building blocks you as geometry should; and
     everything you just changed is remembered - which matters in step 12.

 11. THE REGION CHECK. On the portal, open the region check.
     SEE (one monitor): the MAIN game flips to another region for twenty
     seconds. The slot you are looking at swaps to that region's rival content
     and swaps back. Same slot, same moment, different region - which is the
     whole promise.
     SEE (-Booth, two monitors): a second small window appears on the portal's
     monitor instead, showing the other region at the same slot, and the main
     game is untouched. The window never steals focus: the controller in the
     player's hands keeps working all the way through.

 12. PUSH VERSION 2. While you are still standing inside the building, go to the
     portal and push an update to the same content.
     SEE: nothing happens yet. The game will not pull a building out from under
     somebody who is inside it. Walk out of the door.
     SEE: the moment you are outside and not looking at it, the slot swaps to
     version 2 - a different shape, the same brand - AND the door you opened is
     still open, the lights you switched are still as you left them and the
     screen is still on the same picture. State survives a content swap. Walk
     back in to check.

 13. THE REPORT. On the portal, open the report.
     SEE: how many players saw it, how many came close, how many went in, how
     many touched something. The numbers come from the game: the game told the
     server, and the server is telling the brand.

 14. THE BLOCK ENDS. Wait for the block clock to run out - three minutes of real
     time is three hours of demo time.
     SEE: the slot goes back to whatever won it next, the held money is charged,
     and the summary screen adds up the block: what was spent, what was shown,
     what was seen.

 15. SWITCH GAMES. Press Esc in the game, leave to the title screen, choose the
     right card.
     SEE: a different place - a waterfront instead of an inland plaza - with two
     slots instead of three, built out of the same kit. Your content is not in
     it: you bid for a slot in Game A. Switch back and it still is.

 16. IDLE. Leave both screens alone.
     SEE: after a minute the portal resets itself to its attract screen. After
     a minute and a half with nobody playing, the game drops back to its attract
     loop. The demo is ready for the next person without anyone touching it.

 17. Stop-Demo.bat

Two extras worth showing if there is time, both with controller 2 held as in
section 4: corrupting the next download, so you can watch the game refuse a pack
whose hash does not match and ask for it again; and freezing one, so you can
watch it resume from where it stopped rather than start over.


-------------------------------------------------------------------------------
6. IF SOMETHING IS WRONG
-------------------------------------------------------------------------------

  * "Something is already listening on 127.0.0.1:8700" - it is already running.
    Stop-Demo.bat, then Stop-Demo.bat -Any if that is not enough, then start.
  * The game window closes a second after it opens, or never appears - look at
    the newest _logs\*_game.log; also run
    game\Engine\Extras\Redist\en-us\vc_redist.x64.exe once (section 2).
  * The portal's "your computer" list is empty, or a slot stays empty in the
    game - the content packs are missing. server\demo_files\ should hold about
    fifteen .dcpack files; if it is empty the copy is incomplete.
  * Anything stuck, stale or strange - Stop-Demo.bat, then
    Start-Demo.bat -Reset. That throws away the server's whole state and starts
    from nothing, which fixes most of it.
  * Nothing at all happens - open a command prompt in this folder and run
    Start-Demo.bat from there, so the error stays on screen.


-------------------------------------------------------------------------------
7. REBUILDING IT
-------------------------------------------------------------------------------

Not needed to run it. Needed only to change the game, the art or the content.

  * Unreal Engine 5.7.4, installed through the Epic launcher. Every script finds
    it by itself: it looks at the UE_ROOT environment variable first, then the
    registry, then the launcher's own install manifest. Set UE_ROOT to the
    engine folder if it cannot.
  * Blender 5.2 or later, for the art. Set the BLENDER_EXE environment variable
    to the full path of blender.exe, or put blender.exe on PATH.
  * The order, from this folder:

      powershell -ExecutionPolicy Bypass -File art\build.ps1
          rebuild the thirteen content pieces and the environment kit, and
          check them. Only if the art changed.

      unreal\Tools\import_content.py
          bring the rebuilt art into the Unreal project. This one runs INSIDE a
          headless editor rather than on its own; the command line is written
          out at the top of the file. Only if the art changed.

      powershell -ExecutionPolicy Bypass -File unreal\Tools\package.ps1
          build, cook, stage and pak the game. About five minutes. It puts the
          result in unreal\_build\archive\Windows\.

      powershell -ExecutionPolicy Bypass -File unreal\Tools\stage_packs.ps1
          take the thirteen content chunks out of the build and make packs of
          them, so the build genuinely does not contain the content.

      python\python.exe server\tools\make_fake_packs.py --real --force
          wrap those as the .dcpack files the server serves.

      Start-Demo.bat -Reset
          and this one is NOT optional after a rebuild. A content pack is cooked
          against one exact build of the base game, and the server keeps every
          pack it has already been given. Serve yesterday's packs to today's
          build and the game dies as it mounts one, with a message about a bad
          export index that reads like a corrupt download and is nothing of the
          kind.

      Finally, copy unreal\_build\archive\Windows\ over game\ so the copy in
      this folder is the one that was just built.

  * The checks, all of which should pass before anything is committed:

      cd server && ..\python\python.exe -m pytest -q
      python\python.exe unreal\Tools\menu_exit_test.py
      python\python.exe booth\portal_exit_test.py     (see below)

    The last one drives a real browser and needs the Playwright package and its
    browser binaries, which are hundreds of megabytes and have to be downloaded.
    They are deliberately not in this copy. The test is still here, and on a
    machine with internet `python -m pip install playwright` followed by
    `python -m playwright install chromium` makes it run.


-------------------------------------------------------------------------------
8. PUTTING IT IN A FRESH GIT REPOSITORY
-------------------------------------------------------------------------------

This folder has no history: it is a clean tree, ready to be the first commit.

  1. git lfs install
         Once per machine. This tree carries a few hundred megabytes of
         binaries - the game, the interpreter, the cooked content - and
         .gitattributes puts them through Git LFS. If the server has no LFS
         support, see the note at the top of .gitattributes.
  2. cd into this folder
  3. git init
  4. git add .
  5. git commit -m "DynamicContents demo: runtime dynamic content for Unreal"
  6. git remote add origin <the repository URL>
  7. git push -u origin main
         (git branch -M main first, if git started you on master.)

What .gitignore keeps out is everything a build or a run produces: _logs\,
_run\, server\data\, __pycache__, and the engine's own intermediate folders.
What it deliberately lets IN is game\, python\ and server\demo_files\ - they are
build outputs everywhere else, and here they are what makes the copy run without
being built.


-------------------------------------------------------------------------------
9. WHAT IS IN HERE
-------------------------------------------------------------------------------

  README.txt            this
  Start-Demo.bat        start everything
  Stop-Demo.bat         stop everything
  game\                 the packaged game. Shipping build, no debug symbols, no
                        crash reporter, nothing that can send anything anywhere
  python\               the interpreter the server and the tools run on
  server\               the demo server: the backend the game talks to, its
                        config, its tools and its tests
  portal\              the brand portal: a static web page the server serves
  booth\                the pad helper, and the tests that drive the portal
  unreal\               the Unreal project and plugin: C++ sources, the content,
                        the two maps, and the tools that build and run them
  art\                  the Blender scripts that make the content, and what they
                        export
  diagrams\, output\    the drawings of how the system works
  specs\, tools\        the written specifications, and the shared helpers every
                        script uses to find its own paths
