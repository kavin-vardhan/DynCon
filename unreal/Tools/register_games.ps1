<#
    register_games.ps1 - run the slot-map tool on both maps and register them (brief 013).

        powershell -ExecutionPolicy Bypass -File unreal\Tools\register_games.ps1

    What it does:

      1. starts the demo server on a **clean data folder** but its **real config folder**,
         so the captures land in `server\config\maps\` - which is committed, so a clean
         checkout serves the real map and thumbnails with no Unreal anywhere in sight;
      2. runs the headless editor with `unreal\Tools\register_games.py`, which loads
         /Game/Maps/GameA and /Game/Maps/GameB in turn, captures each one and POSTs it to
         `/games/register`;
      3. prints what the server stored and stops the server.

    -AllowCommandletRendering is passed to the editor and is **not optional**: a commandlet
    runs with rendering switched off unless it is asked for, and the tool's whole job is to
    render two kinds of picture.

    -NoPost captures without registering, which is how to look at the pictures before
    letting them near the config folder.
#>
param(
    [string]$Engine  = 'E:\EpicGames\UE_5.7',
    [string]$Project = 'E:\DynamicContents\unreal\DCDemo\DCDemo.uproject',
    [string]$Repo    = 'E:\DynamicContents',
    [int]   $Port    = 8700,
    [int]   $MapPixels = 2048,
    [int]   $ThumbWidth = 960,
    [string]$Games   = 'A,B',
    [switch]$NoPost
)

$ErrorActionPreference = 'Stop'
$serverDir = Join-Path $Repo 'server'
$python = Join-Path $serverDir '.venv\Scripts\python.exe'
$logDir = Join-Path $Repo 'unreal\_build\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$serverLog = Join-Path $logDir "register_${stamp}_server.log"
$editorLog = Join-Path $logDir "register_${stamp}_editor.log"
$url = "http://127.0.0.1:$Port"

$server = $null
try {
    if (-not $NoPost) {
        $data = Join-Path $env:TEMP 'dc_register_data'
        if (Test-Path $data) { Remove-Item $data -Recurse -Force }
        $env:DCSERVER_DATA = $data
        Write-Host "starting the server on $url (data $data, config $serverDir\config)"
        $server = Start-Process -FilePath $python `
            -ArgumentList @('-m', 'uvicorn', 'dcserver.asgi:app', '--host', '127.0.0.1',
                            '--port', "$Port", '--log-level', 'info') `
            -WorkingDirectory $serverDir -PassThru -NoNewWindow `
            -RedirectStandardOutput $serverLog -RedirectStandardError "$serverLog.err"

        $deadline = (Get-Date).AddSeconds(90)
        $ready = $false
        while ((Get-Date) -lt $deadline) {
            try {
                $health = Invoke-RestMethod "$url/admin/health" -TimeoutSec 5
                Write-Host "server ok: key=$($health.key_fingerprint), maps=$($health.paths.maps)"
                $ready = $true
                break
            } catch { Start-Sleep -Milliseconds 400 }
        }
        if (-not $ready) { throw "the server never answered - see $serverLog" }
    }

    # Through the environment, not the command line: UPythonScriptCommandlet parses
    # -Script= with FParse::Token and nothing after it ever reaches sys.argv.
    $env:DC_REGISTER_BACKEND    = $url
    $env:DC_REGISTER_GAMES      = $Games
    $env:DC_REGISTER_MAP_PIXELS = "$MapPixels"
    $env:DC_REGISTER_THUMB_WIDTH = "$ThumbWidth"
    $env:DC_REGISTER_POST       = if ($NoPost) { '0' } else { '1' }
    $env:DC_REGISTER_OUT        = Join-Path $Repo 'unreal\_build\slotmap'

    Write-Host "running the slot-map tool in the headless editor (log: $editorLog)"
    $started = Get-Date
    $script = Join-Path $Repo 'unreal\Tools\register_games.py'
    cmd /c "`"$Engine\Engine\Binaries\Win64\UnrealEditor-Cmd.exe`" `"$Project`" -run=pythonscript -script=`"$script`" -AllowCommandletRendering -unattended -nosplash > `"$editorLog`" 2>&1"
    $exit = $LASTEXITCODE
    Write-Host ("editor exit {0} after {1:N1} min" -f $exit, ((Get-Date) - $started).TotalMinutes)

    $report = Join-Path $logDir 'register_games.json'
    if (Test-Path $report) {
        $j = Get-Content $report -Raw | ConvertFrom-Json
        foreach ($game in ($j.games.PSObject.Properties.Name | Sort-Object)) {
            $g = $j.games.$game
            Write-Host ""
            Write-Host ("game {0}: ok={1}  {2}" -f $game, $g.ok, $g.summary)
            foreach ($s in $g.slots) {
                Write-Host ("  {0,-3} {1,-2}  px ({2}, {3})  {4}" -f `
                    $s.id, $s.size_class, $s.px[0], $s.px[1], $s.thumb)
            }
            if ($g.post_status) { Write-Host ("  POST -> {0}" -f $g.post_status) }
        }
    } else {
        Write-Warning "no report at $report"
    }

    Select-String -Path $editorLog -Pattern 'LogDCSlotMap: Warning|Error:' |
        Select-Object -First 20 | ForEach-Object { $_.Line.Trim() }
    if ($exit -ne 0) { throw "the slot-map tool failed, see $editorLog" }
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
        Write-Host 'server stopped'
    }
    foreach ($name in @('DCSERVER_DATA', 'DC_REGISTER_BACKEND', 'DC_REGISTER_GAMES',
                        'DC_REGISTER_MAP_PIXELS', 'DC_REGISTER_THUMB_WIDTH',
                        'DC_REGISTER_POST', 'DC_REGISTER_OUT')) {
        Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
    }
}
