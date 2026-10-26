<#
    package.ps1 - build, cook, stage and pak the demo, chunks and all.

        powershell -ExecutionPolicy Bypass -File unreal\Tools\package.ps1

    Two things in here are not the usual BuildCookRun line, both because of this PC's C++
    toolchain (see the long comment in Source\DCDemo\DCDemo.Build.cs):

      -ubtargs=-NoLiveCoding   keeps Module.LiveCoding out of the monolithic link; it needs
                               __std_search_1/2, which no CRT installed here provides.
      -nocompileeditor         the editor target is built separately, before this runs.

    Both can go once MSVC 14.44.35207 is installed.
#>
param(
    [string]$Engine = 'E:\EpicGames\UE_5.7',
    [string]$Project = 'E:\DynamicContents\unreal\DCDemo\DCDemo.uproject',
    [string]$Archive = 'E:\DynamicContents\unreal\_build\archive',
    # Shipping by default because it is the only configuration that links on this PC until
    # MSVC 14.44.35207 is installed (unreal\README.md). The plugin's own file log
    # (Saved\DCLogs\) exists precisely so that costs nothing in evidence.
    [string]$Config = 'Shipping',
    [string]$LogDir = 'E:\DynamicContents\unreal\_build\logs',
    [switch]$NoIoStore,
    [switch]$SkipEditorBuild
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $LogDir, $Archive | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
Write-Host ("free on E: before packaging: {0:N1} GB" -f ((Get-PSDrive E).Free / 1GB))

if (-not $SkipEditorBuild) {
    $editorLog = Join-Path $LogDir "package_${stamp}_editor.log"
    Write-Host 'building the editor target (the cook runs in it)...'
    cmd /c "`"$Engine\Engine\Build\BatchFiles\Build.bat`" DCDemoEditor Win64 Development -Project=`"$Project`" -WaitMutex -NoLiveCoding > `"$editorLog`" 2>&1"
    if ($LASTEXITCODE -ne 0) { throw "editor build failed, see $editorLog" }
}

$ioStore = if ($NoIoStore) { '-noiostore' } else { '-iostore' }
$uatLog = Join-Path $LogDir "package_${stamp}_uat.log"

# Live coding is only in the link for Development and DebugGame; Shipping and Test leave it
# out by themselves, and passing -NoLiveCoding there would change nothing.
$ubtArgs = if ($Config -eq 'Shipping' -or $Config -eq 'Test') { '' } else { ' -ubtargs=-NoLiveCoding' }

$uat = "`"$Engine\Engine\Build\BatchFiles\RunUAT.bat`" BuildCookRun" `
    + " -project=`"$Project`"" `
    + " -noP4 -utf8output -unattended" `
    + " -platform=Win64 -clientconfig=$Config" `
    + " -build -cook -stage -pak $ioStore -compressed" `
    + " -archive -archivedirectory=`"$Archive`"" `
    + " -nocompileeditor" + $ubtArgs

Write-Host "running UAT (log: $uatLog)"
$started = Get-Date
cmd /c "$uat > `"$uatLog`" 2>&1"
$exit = $LASTEXITCODE
Write-Host ("UAT exit {0} after {1:N1} min" -f $exit, ((Get-Date) - $started).TotalMinutes)

if ($exit -ne 0) {
    Write-Host '---- errors ----'
    Select-String -Path $uatLog -Pattern 'error|Error:|LNK|Warning: Failed' | Select-Object -First 25 |
        ForEach-Object { $_.Line.Trim() }
    throw "packaging failed, see $uatLog"
}

$paks = Join-Path $Archive 'Windows\DCDemo\Content\Paks'
if (Test-Path $paks) {
    Write-Host ''
    Write-Host 'pak files produced:'
    Get-ChildItem $paks -File | Sort-Object Name | ForEach-Object {
        "  {0,-34} {1,14:N0} B" -f $_.Name, $_.Length
    }
}

$total = (Get-ChildItem (Join-Path $Archive 'Windows') -Recurse -File | Measure-Object -Sum Length).Sum
Write-Host ("packaged build: {0:N1} MB" -f ($total / 1MB))
Write-Host ("free on E: after packaging: {0:N1} GB" -f ((Get-PSDrive E).Free / 1GB))
