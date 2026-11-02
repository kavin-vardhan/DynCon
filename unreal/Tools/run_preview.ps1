<#
    run_preview.ps1 - start the REGION PREVIEW WINDOW: a second copy of the same packaged
    build, playing as a player in another region (plan v6 §7 and §11).

        powershell -ExecutionPolicy Bypass -File unreal\Tools\run_preview.ps1
        powershell -ExecutionPolicy Bypass -File unreal\Tools\run_preview.ps1 -Region r3 -Shown

    It assumes the demo server and the main game are already up - this is the fourth thing
    the booth's start script runs, and the LAST of the two game copies to be started is the
    main game, deliberately:

        server -> portal -> THIS -> the main game

    A window takes focus when Windows creates it, and the one thing that must never happen
    at the booth is the main game losing focus and with it pad 1 (plan v6 §11). Everything
    after boot is done with SWP_NOACTIVATE and cannot steal focus; the creation of the
    window itself cannot be made not to, so it happens before the main game starts.

    What the flags do is in DCRuntimeGameMode.h; the short version:

      -DCPreview        no input, no audio, no telemetry, no status strip, no marker; a
                        30 fps cap, the lowest scalability, below-normal process priority;
                        a borderless window on the portal's monitor that starts out of
                        sight; and a camera that auto-pilots to the slot the visitor has
                        just been bidding on.
      -DCFollowRegion   GET /preview/region, so the portal's region check moves this copy.
      -DCCacheDir       its own pack cache, so the two copies never fight over a file.
      -UserDir          its own Saved folder, which is NOT optional. Two copies of one
                        packaged build share %LOCALAPPDATA%\DCDemo\Saved, and the engine
                        persists the scalability groups and the window resolution into the
                        GameUserSettings.ini in it - so without this the preview's lowest
                        settings and half resolution become the MAIN game's settings the
                        next time it starts. (They did. It is why the main game was running
                        at sg.ResolutionQuality=50 for one afternoon in brief 017.)
      -nosound          belt and braces: the flag mutes the audio device anyway.

    The pad helper shows and hides it afterwards (booth\pad_helper.py), driven by the
    portal's Region-check step.
#>
param(
    # Empty means "find it" - see tools\dc_paths.ps1.
    [string]$Exe        = '',
    [string]$Backend    = 'http://127.0.0.1:8700',
    [string]$Game       = 'A',
    [string]$Region     = 'r2',
    [string]$Map        = '/Game/Maps/GameA',
    [string]$CacheDir   = (Join-Path $PSScriptRoot '..\_build\preview\packcache'),
    [string]$UserDir    = (Join-Path $PSScriptRoot '..\_build\preview\userdir'),
    [string]$LogDir     = (Join-Path $PSScriptRoot '..\_build\logs'),
    [string]$StatusFile = (Join-Path $PSScriptRoot '..\_build\preview\dc_status.json'),
    [string]$WindowFile = (Join-Path $PSScriptRoot '..\_build\preview\dc_preview_window.json'),
    [string]$Rect       = '',
    # Where to write the pid of the copy this starts. The booth's start script asks for it,
    # because it has to be able to stop exactly what it started - and the pid cannot be read
    # back off the console of a script someone else ran.
    [string]$PidFile    = '',
    [int]$Monitor       = 0,
    [int]$Fps           = 30,
    [int]$Seconds       = 0,
    [switch]$Shown,
    [switch]$Wait
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\tools\dc_paths.ps1')
if (-not $Exe) { $Exe = Find-DCGameExe }
if (-not (Test-Path $Exe)) { throw "no packaged exe at $Exe" }
New-Item -ItemType Directory -Force -Path $CacheDir, $UserDir, $LogDir,
    (Split-Path $StatusFile), (Split-Path $WindowFile) | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$dcLog = Join-Path $LogDir "preview_${stamp}_dc.log"

# The window is created at exactly the size it will render, so nothing has to resize a back
# buffer when it is made borderless two seconds later. 960 x 540 is the default home
# rectangle on a 1920 x 1080 monitor; -Rect overrides both.
$resX, $resY = 960, 540
if ($Rect) {
    $parts = $Rect.Split(',')
    if ($parts.Count -ne 4) { throw "-Rect wants x,y,w,h" }
    $resX, $resY = [int]$parts[2], [int]$parts[3]
}

$gameArgs = @(
    "-DCMap=$Map",
    '-windowed', "-ResX=$resX", "-ResY=$resY",
    '-DCPreview', '-DCFollowRegion', '-nosound', "-UserDir=$UserDir",
    "-DCBackend=$Backend", "-DCGame=$Game", "-DCRegion=$Region",
    "-DCCacheDir=$CacheDir", "-DCStatusFile=$StatusFile", "-DCLogFile=$dcLog",
    "-DCPreviewFile=$WindowFile", "-DCPreviewFps=$Fps"
)
if ($Shown)    { $gameArgs += '-DCPreviewShown' }
if ($Rect)     { $gameArgs += "-DCPreviewRect=$Rect" }
if ($Monitor -gt 0) { $gameArgs += "-DCPreviewMonitor=$Monitor" }
if ($Seconds -gt 0) { $gameArgs += "-DCRunSeconds=$Seconds" }

Write-Host "starting the region preview window as region $Region on $Map"
Write-Host "  log         $dcLog"
Write-Host "  window file $WindowFile"
$proc = Start-Process -FilePath $Exe -PassThru `
    -ArgumentList (Get-DCGameCommandLine $gameArgs)
Write-Host ("  pid         {0}" -f $proc.Id)
if ($PidFile) {
    New-Item -ItemType Directory -Force -Path (Split-Path $PidFile -Parent) | Out-Null
    "$($proc.Id)" | Set-Content $PidFile -Encoding ascii
}

# Give it long enough to place its window, then say where it went - that is the one thing
# worth seeing on a booth start-up screen.
Start-Sleep -Seconds 6
if (Test-Path $WindowFile) {
    Write-Host '  placed:'
    Get-Content $WindowFile | Write-Host
} else {
    Write-Warning "  the window file has not appeared yet - see $dcLog"
}

if ($Wait) {
    $proc.WaitForExit()
    Write-Host ("preview exit {0}" -f $proc.ExitCode)
}
