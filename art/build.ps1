<#
.SYNOPSIS
    Build the DynamicContents art: the content pieces, then the environment kit, then
    validate both and build the contact sheets.

.EXAMPLE
    .\art\build.ps1
    .\art\build.ps1 -Only content4
    .\art\build.ps1 -Only content4:v2,content1:v1 -Samples 128
    .\art\build.ps1 -NoRender          # geometry + exports only, much faster
    .\art\build.ps1 -EnvOnly           # just the environment kit (brief 012)
    .\art\build.ps1 -SkipEnv           # just the content, as it was before brief 012

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
    [switch]  $QaShots,
    [switch]  $SkipEnv,
    [switch]  $EnvOnly,
    [string]  $OnlyEnv = "",
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
    foreach ($c in ($cands | Select-Object -Unique)) {
        if (-not (Test-Path $c)) { continue }
        # old builds report no usable product version at all, so fall back to 0.0
        $raw = (Get-Item $c).VersionInfo.ProductVersion
        $num = if ($raw) { ($raw -replace '[^0-9\.]', '').Trim('.') } else { '' }
        if ($num -notmatch '^\d+(\.\d+)*$') { $num = '0.0' }
        $found += [pscustomobject]@{ Path = $c; Version = [version]$num }
    }
    if (-not $found) { throw "No Blender found. Install Blender or pass -Blender <path to blender.exe>." }
    ($found | Sort-Object Version -Descending | Select-Object -First 1).Path
}

$blender = Find-Blender -Explicit $Blender
Write-Host "Blender : $blender  ($((Get-Item $blender).VersionInfo.ProductVersion))"
Write-Host "Project : $root"

$envCode = 0
$envValCode = 0

function Invoke-EnvBuild {
    Write-Host "`n== environment kit =="
    $envArgs = @("-b", "--factory-startup", "-noaudio", "-P",
                 (Join-Path $art "blender\env\build_env.py"), "--")
    if ($OnlyEnv)  { $envArgs += @("--only", $OnlyEnv) }
    if ($NoRender) { $envArgs += "--no-render" }
    $envArgs += @("--samples", "$([Math]::Max(16, [int]($Samples / 2)))")
    & $blender @envArgs
    $script:envCode = $LASTEXITCODE

    Write-Host "`n== validate environment =="
    python (Join-Path $art "tools\validate_env.py")
    $script:envValCode = $LASTEXITCODE

    Write-Host "`n== environment sheet =="
    python (Join-Path $art "tools\env_sheet.py")
    if ($LASTEXITCODE -ne 0) { Write-Warning "env_sheet.py failed (exit $LASTEXITCODE)" }
}

if ($EnvOnly) {
    Invoke-EnvBuild
    if ($envCode -ne 0 -or $envValCode -ne 0) {
        Write-Host "`nFAILED (env build=$envCode validate=$envValCode)" -ForegroundColor Red
        exit 1
    }
    Write-Host "`nall good" -ForegroundColor Green
    exit 0
}

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

Write-Host "`n== fbx round-trip =="
$rtArgs = @("-b", "--factory-startup", "-noaudio", "-P", (Join-Path $art "tools\fbx_roundtrip.py"), "--")
if ($Only) { $rtArgs += @("--only", $Only) }
& $blender @rtArgs
$rtCode = $LASTEXITCODE

Write-Host "`n== validate =="
python (Join-Path $art "tools\validate_assets.py")
$valCode = $LASTEXITCODE

if ($QaShots) {
    Write-Host "`n== qa shots =="
    $qaArgs = @("-b", "--factory-startup", "-noaudio", "-P", (Join-Path $art "tools\qa_shots.py"), "--")
    if ($Only) { $qaArgs += @("--only", $Only) }
    & $blender @qaArgs
    if ($LASTEXITCODE -ne 0) { throw "qa_shots.py failed" }
}

Write-Host "`n== sheets =="
python (Join-Path $art "tools\contact_sheet.py")
if ($LASTEXITCODE -ne 0) { throw "contact_sheet.py failed" }

if (-not $SkipEnv) { Invoke-EnvBuild }

if ($valCode -ne 0 -or $rtCode -ne 0 -or $envCode -ne 0 -or $envValCode -ne 0) {
    Write-Host ("`nFAILED (validate=$valCode roundtrip=$rtCode env={0} env validate={1})" -f $envCode, $envValCode) -ForegroundColor Red
    exit 1
}
Write-Host "`nall good" -ForegroundColor Green
