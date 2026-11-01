<#
    run_runtime.ps1 - start the demo server, run the packaged game against it, stop both.

    This is the plain "does the client work" runner: no allocations are written, so what the
    three slots show is the server's attract rotation, and the game quits itself.

        powershell -ExecutionPolicy Bypass -File unreal\Tools\run_runtime.ps1
        powershell -ExecutionPolicy Bypass -File unreal\Tools\run_runtime.ps1 -Seconds 90 -Region r2

    The packaged build contains none of the content: every piece that appears was fetched over
    HTTP, verified and mounted while the game was running. unreal\Tools\ue_exit_test.py is the
    same idea with ten hand-written allocations and a pass/fail table.
#>
param(
    [string]$Exe       = 'E:\DynamicContents\unreal\_build\archive\Windows\DCDemo.exe',
    [string]$Backend   = 'http://127.0.0.1:8700',
    [string]$Game      = 'A',
    [string]$Region    = 'r1',
    [string]$Map       = '/Game/Maps/DCRuntime',
    [string]$ShotDir   = 'E:\DynamicContents\unreal\_build\runtime\shots',
    [string]$CacheDir  = 'E:\DynamicContents\unreal\_build\runtime\packcache',
    [string]$LogDir    = 'E:\DynamicContents\unreal\_build\logs',
    [string]$ServerData = '',
    [int]$Port         = 8700,
    [int]$Seconds      = 60,
    [int]$ResX         = 1600,
    [int]$ResY         = 900,
    [switch]$NoServer,
    [switch]$KeepServerData,
    # Brief 018: the booth's own behaviour - boot into the attract loop, any button for the
    # title menu, Start for the pause menu, View for the X-ray. It is off here by default
    # because this runner passes -DCShotDir, and a run that photographs every change wants
    # its own camera rather than the attract one; -Shell turns it on anyway.
    [switch]$Shell,
    [switch]$Xray
)

$ErrorActionPreference = 'Stop'
$repo = 'E:\DynamicContents'
$serverDir = Join-Path $repo 'server'
$python = Join-Path $serverDir '.venv\Scripts\python.exe'

if (-not (Test-Path $Exe)) { throw "no packaged exe at $Exe" }
New-Item -ItemType Directory -Force -Path $ShotDir, $CacheDir, $LogDir | Out-Null

if (-not $ServerData) { $ServerData = Join-Path $env:TEMP 'dc_runtime_data' }

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$dcLog      = Join-Path $LogDir "runtime_${stamp}_dc.log"
$serverLog  = Join-Path $LogDir "runtime_${stamp}_server.log"
$statusFile = Join-Path $ShotDir 'dc_status.json'
$quitFile   = Join-Path $ShotDir 'dc_quit'

$server = $null
try {
    if (-not $NoServer) {
        if (-not $KeepServerData -and (Test-Path $ServerData)) {
            Remove-Item $ServerData -Recurse -Force
        }
        $env:DCSERVER_DATA = $ServerData
        Write-Host "starting the server on 127.0.0.1:$Port  (data: $ServerData)"
        $server = Start-Process -FilePath $python -PassThru -WorkingDirectory $serverDir `
            -ArgumentList @('-m', 'uvicorn', 'dcserver.asgi:app', '--host', '127.0.0.1',
                            '--port', "$Port", '--log-level', 'info') `
            -RedirectStandardOutput $serverLog -RedirectStandardError "$serverLog.err" `
            -WindowStyle Hidden

        $deadline = (Get-Date).AddSeconds(60)
        $ok = $false
        while ((Get-Date) -lt $deadline) {
            try {
                $health = Invoke-RestMethod "http://127.0.0.1:$Port/admin/health" -TimeoutSec 3
                Write-Host ("server ok: mode={0} key={1} packs={2}" -f $health.mode,
                    $health.key_fingerprint, ($health.system_packs.PSObject.Properties.Count))
                $ok = $true
                break
            } catch { Start-Sleep -Milliseconds 400 }
        }
        if (-not $ok) { throw "the server never answered /admin/health - see $serverLog" }
    }

    Get-ChildItem $ShotDir -File -Filter '*.png' -ErrorAction SilentlyContinue | Remove-Item -Force
    if (Test-Path $quitFile) { Remove-Item $quitFile -Force }

    # -DCMap, not a map on the command line: a Shipping build throws a command-line map away
    # (UGameInstance::StartGameInstance), so the run starts in GameDefaultMap - the spike map -
    # and ADCSpikeGameMode travels straight out of it. See unreal\README.md.
    #
    # -DCCacheDir for the same family of reason: a Shipping build's "project saved dir" is
    # %LOCALAPPDATA%\DCDemo\Saved, not the folder the build sits in, so the pack cache is
    # named explicitly to keep the evidence of a run next to the build.
    $gameArgs = @(
        "-DCMap=$Map",
        '-windowed', "-ResX=$ResX", "-ResY=$ResY",
        "-DCBackend=$Backend", "-DCGame=$Game", "-DCRegion=$Region",
        "-DCShotDir=$ShotDir", "-DCStatusFile=$statusFile", "-DCLogFile=$dcLog",
        "-DCCacheDir=$CacheDir",
        "-DCQuitWhenFileExists=$quitFile", "-DCRunSeconds=$Seconds"
    )
    if ($Shell) { $gameArgs += '-DCShell' }
    if ($Xray)  { $gameArgs += '-DCXray' }
    Write-Host "running the game for $Seconds s"
    $started = Get-Date
    $proc = Start-Process -FilePath $Exe -ArgumentList $gameArgs -PassThru
    if (-not $proc.WaitForExit(($Seconds + 120) * 1000)) {
        Write-Warning 'the game outstayed its welcome - killing it'
        $proc.Kill(); $proc.WaitForExit(15000)
    }
    Write-Host ("game exit {0} after {1:N1} s" -f $proc.ExitCode, ((Get-Date) - $started).TotalSeconds)

    if (Test-Path $dcLog) {
        Write-Host ("DC log: {0} ({1:N0} lines)" -f $dcLog, (Get-Content $dcLog | Measure-Object -Line).Lines)
    } else {
        Write-Warning "no DC log at $dcLog"
    }
    $result = Join-Path $ShotDir 'dc_runtime_result.txt'
    if (Test-Path $result) {
        Write-Host ''
        Write-Host '---- dc_runtime_result.txt ----'
        Get-Content $result
    }
    Write-Host ''
    Get-ChildItem $ShotDir -File -Filter '*.png' | Sort-Object Name |
        ForEach-Object { "  {0,-34} {1,10:N0} B" -f $_.Name, $_.Length }
}
finally {
    if ($server -ne $null -and -not $server.HasExited) {
        Write-Host 'stopping the server'
        $server.Kill()
        $server.WaitForExit(10000)
    }
}
