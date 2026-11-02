<#
    Start-Demo.ps1 - start the whole demo, with one command, on a machine nobody has set up.

        .\Start-Demo.bat                 desk mode: one monitor, one window each
        .\Start-Demo.bat -Booth          the booth: two monitors, two controllers

    Or, if PowerShell is already open:

        powershell -ExecutionPolicy Bypass -File .\Start-Demo.ps1

    DESK MODE, the default, is for showing the demo at a desk on one screen:

        1. the server on 127.0.0.1:8700, waited for until it answers /admin/health
        2. Edge, an ordinary window, on the brand portal
        3. the pad helper, but only if a controller is actually plugged in
        4. the game, windowed at 1600 x 900, in its attract loop on Game A, with no time
           limit on it

       and no region preview window: the portal's region check falls back to the live flip,
       where the MAIN game plays as the other region for twenty seconds and swaps back. It
       is the same promise shown a different way and it costs one screen nothing.

    -BOOTH is the Tokyo setup:

        1. the server
        2. Edge in kiosk mode on the right-hand monitor
        3. the pad helper
        4. the region preview window - a second copy of the game, with its own -UserDir
        5. the main game LAST, borderless on the left-hand monitor

       The order of 4 and 5 is not a preference. A window takes focus when Windows creates
       it, and the one thing that must never happen at the booth is the main game losing
       focus and with it controller 1. So the preview copy's window is created first, and
       the main game is the last window to appear.

    Everything it writes stays inside this folder: logs in `_logs\`, run-time state in
    `_run\` (the browser profile, the two pack caches, the preview copy's saved folder, and
    `_run\demo_run.json`, which is the list of what was started). Both folders are
    git-ignored. `Stop-Demo.bat` stops exactly what this started and nothing else.

    It refuses to start a second time: if something is already listening on the port, it
    says so and stops.
#>
param(
    [switch]$Booth,
    [int]$Port = 8700,
    # How long the portal waits, with nobody touching it, before it resets itself and goes
    # back to its attract screen. Ten minutes at a desk, so a demo can be talked through;
    # the booth's own default (sixty seconds) is right for a queue of visitors.
    [int]$IdleSeconds = 0,
    [string]$Game = 'A',
    [switch]$Reset,
    [switch]$NoPortal,
    [switch]$NoPad,
    [switch]$NoGame,
    [int]$ResX = 1600,
    [int]$ResY = 900
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tools\dc_paths.ps1')

$repo    = Get-DCRepoRoot
$logDir  = Get-DCLogDir
$runDir  = Join-Path $repo '_run'
$stamp   = Get-Date -Format 'yyyyMMdd_HHmmss'
$mode    = if ($Booth) { 'booth' } else { 'desk' }
$backend = "http://127.0.0.1:$Port"
$stateFile = Join-Path $runDir 'demo_run.json'

if ($IdleSeconds -le 0) { $IdleSeconds = if ($Booth) { 60 } else { 600 } }

New-Item -ItemType Directory -Force -Path $runDir, $logDir | Out-Null
$transcript = Join-Path $logDir "demo_${stamp}_start.log"
Start-Transcript -Path $transcript | Out-Null

# What was started, so Stop-Demo can stop that and only that.
$started = New-Object System.Collections.ArrayList

function Note([string]$what, $proc) {
    if ($null -eq $proc) { return }
    [void]$started.Add([ordered]@{
        what = $what
        pid  = $proc.Id
        name = $proc.ProcessName
        # A pid is reused eventually; the start time is what tells "still our process" from
        # "something else that happens to have this number now".
        started_at = $proc.StartTime.ToString('o')
    })
    Write-Host ("  started {0}  pid {1}" -f $what, $proc.Id)
}

function Save-State([string]$note) {
    [ordered]@{
        mode = $mode; port = $Port; backend = $backend; game = $Game
        idle_seconds = $IdleSeconds
        started_utc = (Get-Date).ToUniversalTime().ToString('o')
        root = $repo; logs = $logDir; run = $runDir; log = $transcript
        note = $note
        processes = @($started)
    } | ConvertTo-Json -Depth 5 | Set-Content $stateFile -Encoding utf8
}

function Fail([string]$sentence) {
    Save-State "failed to start: $sentence"
    Write-Host ''
    Write-Host "COULD NOT START: $sentence" -ForegroundColor Red
    Write-Host "the log of this attempt is $transcript"
    Stop-Transcript | Out-Null
    exit 1
}

Write-Host ("DynamicContents demo - {0} mode" -f $mode) -ForegroundColor Cyan
Write-Host "  folder   $repo"
Write-Host "  logs     $logDir"

# ---------------------------------------------------------------------------- not twice
$busy = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($busy) {
    $owners = ($busy | ForEach-Object {
        $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        if ($p) { "$($p.ProcessName) (pid $($p.Id))" } else { "pid $($_.OwningProcess)" }
    }) -join ', '
    Fail ("something is already listening on 127.0.0.1:$Port - $owners. The demo is " +
          "probably already running: run Stop-Demo.bat first, or pass -Port with a free " +
          "port if this is something else.")
}

# ------------------------------------------------------------------------- 1. the server
$python = Find-DemoPython
Write-Host "  python   $python"
$serverDir = Join-Path $repo 'server'
$dataDir = Join-Path $serverDir 'data'
if ($Reset -and (Test-Path $dataDir)) {
    Write-Host "  -Reset: removing $dataDir (keys, database and stored packs are made again)"
    Remove-Item $dataDir -Recurse -Force
}

$serverLog = Join-Path $logDir "demo_${stamp}_server.log"
Write-Host ''
Write-Host "1. the server on 127.0.0.1:$Port"
$server = Start-Process -FilePath $python -PassThru -WorkingDirectory $serverDir `
    -ArgumentList @('-m', 'uvicorn', 'dcserver.asgi:app', '--host', '127.0.0.1',
                    '--port', "$Port", '--log-level', 'info') `
    -RedirectStandardOutput $serverLog -RedirectStandardError "$serverLog.err" `
    -WindowStyle Hidden
Note 'server' $server
Save-State 'starting'

$health = $null
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    if ($server.HasExited) {
        Fail ("the server stopped on its own (exit $($server.ExitCode)) - see $serverLog.err")
    }
    try { $health = Invoke-RestMethod "$backend/admin/health" -TimeoutSec 3; break }
    catch { Start-Sleep -Milliseconds 400 }
}
if (-not $health) { Fail "the server never answered $backend/admin/health - see $serverLog" }
$systemPacks = @($health.system_packs.PSObject.Properties).Count
$games = @($health.registered_games.PSObject.Properties | Where-Object { $_.Value }).Name
Write-Host ("  ready: mode={0}  signing key {1}  the game's own packs {2}  files on the brand's computer {3}  registered games {4}" -f `
    $health.mode, $health.key_fingerprint, $systemPacks, $health.demo_files, ($games -join '+'))

# What the game is told to play as comes out of the config, not out of this script.
$config = Get-Content (Join-Path $serverDir 'config\demo.json') -Raw | ConvertFrom-Json
$mainRegion = if ($config.booth.main_region) { $config.booth.main_region } else { 'r1' }
$previewRegion = if ($config.booth.preview_default_region) { $config.booth.preview_default_region } else { 'r2' }

# ------------------------------------------------------------------------- 2. the portal
if (-not $NoPortal) {
    Write-Host ''
    Write-Host '2. the brand portal, in Edge'
    $edge = Find-Edge
    if (-not $edge) {
        Write-Warning ('  no Microsoft Edge found - open ' +
                       "$backend/portal/?idle=$IdleSeconds in any browser by hand")
    } else {
        # Its own profile folder, inside this copy, for two reasons: nothing of the
        # visitor's own browsing is touched, and the window this starts belongs to a
        # process of ours, so Stop-Demo can close it. Started against an existing Edge
        # profile, msedge.exe hands the window to the browser that is already running and
        # exits, and there is then nothing to stop.
        $profile = Join-Path $runDir 'edge'
        New-Item -ItemType Directory -Force -Path $profile | Out-Null
        $url = "$backend/portal/?idle=$IdleSeconds"
        $edgeArgs = @("--user-data-dir=$profile", '--no-first-run',
                      '--no-default-browser-check',
                      '--disable-features=Translate,TranslateUI',
                      '--disable-background-networking', '--disable-sync',
                      '--disable-component-update', '--no-service-autorun')
        if ($Booth) {
            # The right-hand monitor, full screen, no browser furniture at all.
            $right = Get-DCMonitorRect -Which 'right'
            $edgeArgs += @('--kiosk', "--window-position=$($right.X),$($right.Y)",
                           "--window-size=$($right.Width),$($right.Height)", $url)
            Write-Host ("  kiosk on the right-hand monitor at {0},{1} {2}x{3}" -f `
                $right.X, $right.Y, $right.Width, $right.Height)
        } else {
            $edgeArgs += @('--new-window', $url)
        }
        Note 'portal (Edge)' (Start-Process -FilePath $edge -ArgumentList $edgeArgs -PassThru)
        Write-Host "  $url"
    }
    Save-State 'portal up'
}

# ---------------------------------------------------------------------- 3. the pad helper
if (-not $NoPad) {
    Write-Host ''
    Write-Host '3. the pad helper'
    $padHelper = Join-Path $repo 'booth\pad_helper.py'
    & $python $padHelper --connected --quiet | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  no controller is plugged in - not starting it. The portal''s keyboard'
        Write-Host '  controls work on their own (arrow keys, Enter, Backspace).'
    } else {
        $padLog = Join-Path $logDir "demo_${stamp}_pad.log"
        $padArgs = @($padHelper, '--server', $backend)
        # Desk mode has no preview window to show and hide, so the helper is told never to
        # look for one; the portal then asks the server for the live flip instead.
        if (-not $Booth) { $padArgs += '--no-preview-window' }
        else { $padArgs += @('--preview-file', (Join-Path $runDir 'preview\dc_preview_window.json')) }
        Note 'pad helper' (Start-Process -FilePath $python -ArgumentList $padArgs -PassThru `
            -WorkingDirectory $repo -RedirectStandardOutput $padLog `
            -RedirectStandardError "$padLog.err" -WindowStyle Hidden)
    }
    Save-State 'pad helper handled'
}

# ------------------------------------------------------- 4. the game (and the preview copy)
if (-not $NoGame) {
    $exe = Find-DCGameExe
    if (-not (Test-Path $exe)) {
        Fail ("there is no packaged game at $exe. A ready-to-run copy of this folder has " +
              "it in game\; a copy with the engine installed makes it with " +
              "unreal\Tools\package.ps1.")
    }

    if ($Booth) {
        Write-Host ''
        Write-Host '4. the region preview window (a second copy of the game)'
        $previewPid = Join-Path $runDir 'preview.pid'
        if (Test-Path $previewPid) { Remove-Item $previewPid -Force }
        $previewScript = Join-Path $repo 'unreal\Tools\run_preview.ps1'
        $previewArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $previewScript,
                         '-Exe', $exe, '-Backend', $backend, '-Game', $Game,
                         '-Region', $previewRegion,
                         '-CacheDir', (Join-Path $runDir 'preview\packcache'),
                         '-UserDir', (Join-Path $runDir 'preview\userdir'),
                         '-LogDir', $logDir,
                         '-StatusFile', (Join-Path $runDir 'preview\dc_status.json'),
                         '-WindowFile', (Join-Path $runDir 'preview\dc_preview_window.json'),
                         '-PidFile', $previewPid)
        # run_preview.ps1 waits a few seconds and reports where the window went, so this
        # runs it in the foreground and lets it finish before the main game starts.
        & powershell @previewArgs
        if (Test-Path $previewPid) {
            $p = Get-Process -Id ([int](Get-Content $previewPid -Raw).Trim()) -ErrorAction SilentlyContinue
            if ($p) { Note 'region preview window' $p }
            else { Write-Warning '  the preview copy is no longer running' }
        } else {
            Write-Warning '  the preview copy did not report a pid - see the preview log'
        }
        Save-State 'preview up'
    }

    $step = if ($Booth) { 5 } else { 4 }
    Write-Host ''
    Write-Host ("{0}. the game" -f $step)
    $gameLog = Join-Path $logDir "demo_${stamp}_game.log"
    $gameArgs = @(
        "-DCMap=/Game/Maps/Game$Game",
        '-windowed', "-ResX=$ResX", "-ResY=$ResY",
        "-DCBackend=$backend", "-DCGame=$Game", "-DCRegion=$mainRegion",
        '-DCShell', '-DCXray', "-DCStartIn=attract",
        "-DCCacheDir=$(Join-Path $runDir 'packcache')",
        "-DCStatusFile=$(Join-Path $runDir 'dc_status.json')",
        "-DCLogFile=$gameLog",
        # Its own saved folder, inside this copy. Without it a Shipping build writes to
        # %LOCALAPPDATA%\DCDemo\Saved - its window size, its scalability settings and its
        # crash folder - and a run of the demo would leave things behind outside the folder
        # it was started from. It also keeps the two copies in -Booth mode from sharing one
        # GameUserSettings.ini (see unreal\Tools\run_preview.ps1, which has the same flag
        # for the same reason, and the afternoon it cost).
        "-UserDir=$(Join-Path $runDir 'userdir')"
    )
    if ($Booth) {
        $left = Get-DCMonitorRect -Which 'left'
        $gameArgs[2] = "-ResX=$($left.Width)"
        $gameArgs[3] = "-ResY=$($left.Height)"
    }
    # No -DCRunSeconds and no -DCQuitWhenFileExists: the game runs until it is stopped.
    Note 'game' (Start-Process -FilePath $exe -PassThru `
        -ArgumentList (Get-DCGameCommandLine $gameArgs))
    Write-Host ("  map /Game/Maps/Game{0}, region {1}, attract loop, no time limit" -f `
        $Game, $mainRegion)
    Write-Host "  log $gameLog"

    # Wait for it to say it is up, rather than for a window to appear: the game writes a
    # status file (-DCStatusFile) the moment its client has talked to the server, and that
    # file is the one honest answer to "is the game running and is it connected?". A packaged
    # build takes a few seconds, and a bad command line produces a window and nothing else.
    $statusFile = Join-Path $runDir 'dc_status.json'
    if (Test-Path $statusFile) { Remove-Item $statusFile -Force }
    $deadline = (Get-Date).AddSeconds(150)
    $gameStatus = $null
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $statusFile) {
            try {
                $gameStatus = Get-Content $statusFile -Raw | ConvertFrom-Json
                if ($gameStatus.slots) { break }
            } catch { }                       # it is being rewritten; look again
        }
        Start-Sleep -Milliseconds 700
    }
    if ($gameStatus -and $gameStatus.slots) {
        $filled = @($gameStatus.slots.PSObject.Properties | ForEach-Object {
            "{0} {1} {2}" -f $_.Name, $_.Value.state, $_.Value.piece })
        Write-Host ("  the game is up: build {0}, backend {1}, slots {2}" -f `
            $gameStatus.build, $gameStatus.backend_status, ($filled -join ', '))
    } else {
        Write-Warning "  the game has not written $statusFile yet - look at $gameLog"
    }

    if ($Booth) {
        Write-Host '  placing it borderless on the left-hand monitor'
        $placed = Set-DCGameWindowBorderless -Which 'left' -ExcludeTitle 'DynamicContents region preview'
        if ($placed) { Write-Host "  placed: $placed" } else { Write-Warning '  could not find the game window to place it' }
    }
    Save-State 'all up'
}

Save-State 'all up'
Write-Host ''
Write-Host 'the demo is running.' -ForegroundColor Green
Write-Host ("  portal   {0}/portal/" -f $backend)
Write-Host ("  stop it   Stop-Demo.bat")
Write-Host ("  what is running is listed in {0}" -f $stateFile)
Stop-Transcript | Out-Null
