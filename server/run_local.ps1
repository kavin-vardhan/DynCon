# Start the demo server on 127.0.0.1:8700 (local mode).
#
#   .\server\run_local.ps1                 # install if needed, then run
#   .\server\run_local.ps1 -Port 8701      # a second instance for a test
#   .\server\run_local.ps1 -Packs          # build the fake packs first, then run
#   .\server\run_local.ps1 -NoInstall      # skip the pip check (implied when this
#                                        # copy of the tree carries its own python\)
#
# First run generates the RS256 key pair and the URL secret into server\data\keys\ and
# registers the rival and default packs it finds in server\demo_files\. Both data\ and
# demo_files\*.dcpack are git-ignored.
[CmdletBinding()]
param(
    [int]$Port = 8700,
    [string]$Bind = "127.0.0.1",          # 127.0.0.1 only: the demo never listens outward
    [switch]$NoInstall,
    [switch]$Packs,
    [switch]$Reload,
    [string]$Data = "",
    [string]$DemoFiles = ""
)

$ErrorActionPreference = "Stop"
$serverDir = $PSScriptRoot
. (Join-Path $serverDir "..\tools\dc_paths.ps1")

# The interpreter: python\python.exe carried inside this copy of the tree if there is one,
# else a development virtual environment in server\.venv, else whatever is on PATH. A copy
# that carries its own interpreter already has every package installed, so -NoInstall is
# implied for it: nothing may reach the network.
$python = Find-DemoPython
$carried = Join-Path (Get-DCRepoRoot) "python\python.exe"
if ((Test-Path -LiteralPath $carried) -and
    ($python -ieq (Resolve-Path -LiteralPath $carried).Path)) {
    $NoInstall = $true
}
Write-Host "python: $python" -ForegroundColor DarkGray

if (-not $NoInstall) {
    Write-Host "checking dependencies..." -ForegroundColor Cyan
    & $python -m pip install --disable-pip-version-check -q -r (Join-Path $serverDir "requirements.txt")
}

if ($Packs) {
    # Two passes, and the order matters. First the fake packs (every piece-version, plus the
    # two built-to-fail files) — they are the fallback on a machine with no UE build output.
    # Then the real cooked packs out of unreal\_packs\, wrapped as <id>_<v>.real.dcpack,
    # which the curated "Your computer" list prefers whenever one exists. A clean checkout
    # has no unreal\_packs\ (it is git-ignored), so that pass simply reports what it skipped
    # and the demo runs on fakes until the UE side has packaged.
    Write-Host "building the fake demo packs..." -ForegroundColor Cyan
    & $python (Join-Path $serverDir "tools\make_fake_packs.py")
    Write-Host "wrapping the real cooked packs (skipped where there is no build output)..." -ForegroundColor Cyan
    & $python (Join-Path $serverDir "tools\make_fake_packs.py") --real
}

if ($Data) { $env:DCSERVER_DATA = $Data }
if ($DemoFiles) { $env:DCSERVER_DEMO_FILES = $DemoFiles }

$uvicornArgs = @("-m", "uvicorn", "dcserver.asgi:app", "--host", $Bind, "--port", "$Port",
                 "--log-level", "info")
if ($Reload) { $uvicornArgs += "--reload" }

Write-Host ("http://{0}:{1}  (Ctrl+C to stop)" -f $Bind, $Port) -ForegroundColor Green
Push-Location $serverDir
try { & $python @uvicornArgs } finally { Pop-Location }
