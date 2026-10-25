<#
.SYNOPSIS
    Build the DynamicContents content art: Blender pieces, then validate, then the contact sheet.

.EXAMPLE
    .\art\build.ps1
    .\art\build.ps1 -Only content4
    .\art\build.ps1 -Only content4:v2,content1:v1 -Samples 128
    .\art\build.ps1 -NoRender          # geometry + exports only, much faster

.NOTES
    Blender is always launched headless with --factory-startup so no add-on or open session
    can change the result. Nothing outside this folder is written.
#>
[CmdletBinding()]
param(
    [string]  $Only = "",
    [switch]  $NoRender,
    [switch]  $NoBevel,
    [int]     $Samples = 64,
    [switch]  $SkipEmblems,
    [string]  $Blender = ""
)

$ErrorActionPreference = "Stop"
$art  = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $art

function Find-Blender {
    param([string]$Explicit)
    if ($Explicit) {
        if (Test-Path $Explicit) { return $Explicit }
        throw "Blender not found at $Explicit"
    }
    $cands = @()
    $cmd = Get-Command blender -ErrorAction SilentlyContinue
    if ($cmd) { $cands += $cmd.Source }
    foreach ($drive in (Get-PSDrive -PSProvider FileSystem | Select-Object -ExpandProperty Root)) {
        $cands += "$drive`Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"
        $cands += "$drive`SteamLibrary\steamapps\common\Blender\blender.exe"
        $bf = "$drive`Program Files\Blender Foundation"
        if (Test-Path $bf) {
            $cands += (Get-ChildItem -Directory $bf | ForEach-Object { Join-Path $_.FullName "blender.exe" })
        }
    }
    $found = @()
    foreach ($c in $cands) {
        if (Test-Path $c) {
            $v = (Get-Item $c).VersionInfo.ProductVersion
            if (-not $v) { $v = "0.0" }
            $found += [pscustomobject]@{ Path = $c; Version = [version]($v -replace '[^0-9\.]', '') }
        }
    }
    if (-not $found) { throw "No Blender found. Install Blender or pass -Blender <path to blender.exe>." }
    ($found | Sort-Object Version -Descending | Select-Object -First 1).Path
}

$blender = Find-Blender -Explicit $Blender
Write-Host "Blender : $blender  ($((Get-Item $blender).VersionInfo.ProductVersion))"
Write-Host "Project : $root"

if (-not $SkipEmblems) {
    Write-Host "`n== emblems and sample screen =="
    python (Join-Path $art "tools\make_emblems.py")
    if ($LASTEXITCODE -ne 0) { throw "make_emblems.py failed" }
    python (Join-Path $art "tools\make_sample_screen.py")
    if ($LASTEXITCODE -ne 0) { throw "make_sample_screen.py failed" }
}

Write-Host "`n== blender build =="
$blArgs = @("-b", "--factory-startup", "-noaudio", "-P", (Join-Path $art "blender\build_all.py"), "--")
if ($Only)     { $blArgs += @("--only", $Only) }
if ($NoRender) { $blArgs += "--no-render" }
if ($NoBevel)  { $blArgs += "--no-bevel" }
$blArgs += @("--samples", "$Samples")

& $blender @blArgs
$buildCode = $LASTEXITCODE
if ($buildCode -ne 0) { throw "build_all.py failed (exit $buildCode)" }

Write-Host "`n== validate =="
python (Join-Path $art "tools\validate_assets.py")
$valCode = $LASTEXITCODE

Write-Host "`n== contact sheet =="
python (Join-Path $art "tools\contact_sheet.py")
if ($LASTEXITCODE -ne 0) { throw "contact_sheet.py failed" }

if ($valCode -ne 0) {
    Write-Host "`nVALIDATION FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "`nall good" -ForegroundColor Green
