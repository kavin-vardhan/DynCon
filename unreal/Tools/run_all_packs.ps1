<#
    run_all_packs.ps1 - one packaged run that mounts every pack in turn.

    The build does not contain any of the content: the packs live in unreal\_packs\ and are
    handed to the game on the command line. ADCSpikeGameMode mounts each one, loads its
    Blueprint, spawns it at a slot of a fitting size class, photographs it from outside and
    from inside, takes it away again, and quits itself after the last one - so nothing is left
    running. Then this script builds the contact sheet and prints the per-piece table.

        powershell -ExecutionPolicy Bypass -File unreal\Tools\run_all_packs.ps1
        powershell -ExecutionPolicy Bypass -File unreal\Tools\run_all_packs.ps1 -Only content4_v1,default_v1
#>
param(
    [string]$Exe      = 'E:\DynamicContents\unreal\_build\archive\Windows\DCDemo.exe',
    [string]$Packs    = 'E:\DynamicContents\unreal\_packs',
    [string]$ShotDir  = 'E:\DynamicContents\unreal\spike\shots',
    [string]$ChunkIds = 'E:\DynamicContents\unreal\Tools\chunk_ids.json',
    [string[]]$Only   = @(),
    # Console variables to force before the run, "r.Name=Value,r.Other=Value". A Shipping
    # build has no console and ignores a user Engine.ini, so this is the only way in; see
    # ADCSpikeGameMode::ApplyCvarOverrides.
    [string]$Cvars    = '',
    [int]$ResX = 1280,
    [int]$ResY = 720,
    [int]$TimeoutSeconds = 600,
    [string]$LogDir = 'E:\DynamicContents\unreal\_build\logs',
    [switch]$NoSheet
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Exe)) { throw "no packaged exe at $Exe" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Pack order = the chunk table's order, so the sheet is always laid out the same way.
$table = Get-Content $ChunkIds -Raw | ConvertFrom-Json
$entries = @()
$skipped = @()
foreach ($row in $table.packs) {
    $name = "$($row.id)_$($row.version)"
    if ($Only.Count -gt 0 -and $Only -notcontains $name) { continue }

    $dir = Join-Path $Packs $name
    if (-not (Test-Path $dir)) { $skipped += $name; continue }

    # Size class decides which slot the piece goes in; it is in the pack's own pack.json,
    # which is what the server will hand the client too.
    $sizeClass = ''
    $packJson = Join-Path $dir 'pack.json'
    if (Test-Path $packJson) { $sizeClass = (Get-Content $packJson -Raw | ConvertFrom-Json).size_class }

    $class = "/Game/DCContent/$name/BP_DC_$name.BP_DC_${name}_C"
    $entries += "$dir;$class;$sizeClass"
}
if ($skipped) { Write-Warning "no pack staged for: $($skipped -join ', ')" }
if ($entries.Count -eq 0) { throw "nothing to run: no packs found under $Packs" }
$mount = $entries -join '+'

New-Item -ItemType Directory -Force -Path $ShotDir | Out-Null
Get-ChildItem $ShotDir -File -Filter '*.png' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne 'engine_contact.png' } | Remove-Item -Force

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$dcLog = Join-Path $LogDir "006_run_${stamp}_dc.log"

$gameSaved = Join-Path (Split-Path $Exe -Parent) 'DCDemo\Saved'
$gameLog = Join-Path $gameSaved 'Logs\DCDemo.log'
if (Test-Path $gameLog) { Remove-Item $gameLog -Force }

$gameArgs = @(
    '-windowed', "-ResX=$ResX", "-ResY=$ResY",
    '-log', '-stdout', '-FullStdOutLogOutput',
    "-DCSpikeMount=$mount",
    "-DCSpikeShotDir=$ShotDir",
    "-DCLogFile=$dcLog"
)
if ($Cvars) { $gameArgs += "-DCCvars=$Cvars" }

Write-Host ("running {0} over {1} pack(s)" -f $Exe, $entries.Count)
$started = Get-Date
$proc = Start-Process -FilePath $Exe -ArgumentList $gameArgs -PassThru
if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
    Write-Warning "timed out after $TimeoutSeconds s - killing it so nothing is left running"
    $proc.Kill()
    $proc.WaitForExit(15000)
}
$seconds = ((Get-Date) - $started).TotalSeconds
Write-Host ("exit code {0} after {1:N1} s" -f $proc.ExitCode, $seconds)

# The plugin's own log: this is the one that exists in a Shipping build, where UE_LOG is gone.
if (Test-Path $dcLog) {
    Write-Host ("DC log: {0} ({1:N0} lines)" -f $dcLog, (Get-Content $dcLog | Measure-Object -Line).Lines)
} else {
    Write-Warning "no DC log at $dcLog"
}
if (Test-Path $gameLog) {
    Copy-Item $gameLog (Join-Path $LogDir "006_run_${stamp}_engine.log") -Force
}

$result = Join-Path $ShotDir 'spike_result.txt'
if (Test-Path $result) {
    Write-Host ''
    Write-Host '---- spike_result.txt ----'
    Get-Content $result | ForEach-Object { $_ }
} else {
    Write-Warning "no result file at $result"
}

$shots = @(Get-ChildItem $ShotDir -File -Filter '*.png' | Where-Object { $_.Name -ne 'engine_contact.png' })
Write-Host ''
Write-Host ("---- {0} screenshots ----" -f $shots.Count)
$shots | Sort-Object Name | ForEach-Object { "  {0,-34} {1,10:N0} B" -f $_.Name, $_.Length }

$expected = $entries.Count * 2
if ($shots.Count -ne $expected) { Write-Warning "expected $expected shots, got $($shots.Count)" }

if (-not $NoSheet) {
    Write-Host ''
    Write-Host 'building the contact sheet...'
    python 'E:\DynamicContents\unreal\Tools\make_engine_sheet.py' --shots $ShotDir `
        --out (Join-Path $ShotDir 'engine_contact.png')
    if ($LASTEXITCODE -ne 0) { Write-Warning "contact sheet failed (exit $LASTEXITCODE)" }
}
