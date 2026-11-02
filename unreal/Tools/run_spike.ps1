<#
    run_spike.ps1 - run the packaged game and make it mount the packs.

    The build does not contain the content: the packs live in unreal\_packs\ and are handed to
    the game on the command line. ADCSpikeGameMode mounts each one, loads its Blueprint, spawns
    it at the next slot, screenshots it, and quits itself after the last one - so nothing is
    left running.

        powershell -ExecutionPolicy Bypass -File unreal\Tools\run_spike.ps1
#>
param(
    # Empty means "find it" - see tools\dc_paths.ps1.
    [string]$Exe = '',
    [string]$Packs = (Join-Path $PSScriptRoot '..\_packs'),
    [string]$ShotDir = (Join-Path $PSScriptRoot '..\spike\shots'),
    [string[]]$Order = @('content4_v1', 'content1_v1'),
    [int]$TimeoutSeconds = 240,
    [string]$LogCopy = (Join-Path $PSScriptRoot '..\_build\logs\010_spike_run.log')
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\tools\dc_paths.ps1')
if (-not $Exe) { $Exe = Find-DCGameExe }
New-Item -ItemType Directory -Force -Path (Split-Path $LogCopy -Parent) | Out-Null

if (-not (Test-Path $Exe)) { throw "no packaged exe at $Exe" }

$pairs = @()
foreach ($name in $Order) {
    $dir = Join-Path $Packs $name
    if (-not (Test-Path $dir)) { throw "no pack at $dir" }
    $class = "/Game/DCContent/$name/BP_DC_$name.BP_DC_${name}_C"
    $pairs += "$dir;$class"
}
$mount = $pairs -join '+'

New-Item -ItemType Directory -Force -Path $ShotDir | Out-Null
Get-ChildItem $ShotDir -File -ErrorAction SilentlyContinue | Remove-Item -Force

$gameSaved = Join-Path (Split-Path $Exe -Parent) 'DCDemo\Saved'
$gameLog = Join-Path $gameSaved 'Logs\DCDemo.log'
if (Test-Path $gameLog) { Remove-Item $gameLog -Force }

$args = @(
    '-windowed', '-ResX=1280', '-ResY=720',
    '-log', '-stdout', '-FullStdOutLogOutput',
    "-DCSpikeMount=$mount",
    "-DCSpikeShotDir=$ShotDir"
)

Write-Host "running $Exe"
Write-Host "  -DCSpikeMount=$mount"
$started = Get-Date
$proc = Start-Process -FilePath $Exe -ArgumentList $args -PassThru
if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
    Write-Warning "timed out after $TimeoutSeconds s - killing it so nothing is left running"
    $proc.Kill()
    $proc.WaitForExit(15000)
}
$seconds = ((Get-Date) - $started).TotalSeconds
Write-Host ("exit code {0} after {1:N1} s" -f $proc.ExitCode, $seconds)

if (Test-Path $gameLog) {
    Copy-Item $gameLog $LogCopy -Force
    Write-Host "log copied to $LogCopy"
    Write-Host ''
    Write-Host '---- LogDC ----'
    Select-String -Path $LogCopy -Pattern 'LogDC|LogPakFile' | ForEach-Object { $_.Line }
} else {
    Write-Warning "no game log at $gameLog"
}

Write-Host ''
Write-Host '---- screenshots ----'
Get-ChildItem $ShotDir -File | ForEach-Object { "  {0,-28} {1,10:N0} B" -f $_.Name, $_.Length }
