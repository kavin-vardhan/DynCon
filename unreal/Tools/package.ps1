<#
    package.ps1 - build, cook, stage and pak the demo, chunks and all.

        powershell -ExecutionPolicy Bypass -File unreal\Tools\package.ps1

    Two things in here are not the usual BuildCookRun line, both because of this PC's C++
    toolchain (see the long comment in Source\DCDemo\DCDemo.Build.cs):

      -ubtargs=-NoLiveCoding   keeps Module.LiveCoding out of the monolithic link; it needs
                               __std_search_1/2, which no CRT installed here provides.
      -nocompileeditor         the editor target is built separately, before this runs.

    Both can go once MSVC 14.44.35207 is installed.

    Three more, which are about what the staged build is allowed to contain (brief 018Y):

      the archive folder is   UAT copies into the archive folder and never clears it, so a
      emptied first          build from months ago sat in it alongside today's - a 284 MB
                             Development exe and its 332 MB .pdb, neither of them in any
                             staging manifest. -KeepArchive leaves it alone if that is ever
                             what is wanted.
      -nodebuginfo           no .pdb in the stage. The .pdb is still written next to the exe
                             in DCDemo\Binaries\Win64\, which is where symbolize_crash.ps1
                             looks for it; it is simply not something a copy of the demo has
                             to carry 200 MB of. The exe records only the bare file name of
                             its .pdb, never a path, so nothing in it points at this folder.
      -prereqs               stages the engine's prerequisites installer, so a machine that
                             has never run an Unreal game can install what it needs without
                             going to the internet for it.

    The crash reporter is not staged, and that is config rather than a flag here:
    IncludeCrashReporter=False in Config\DefaultGame.ini, with the matching "do not send
    anything" block in Config\DefaultEngine.ini.
#>
param(
    # Empty means "find it": UE_ROOT, then the registry, then the launcher's own manifest.
    # See tools\dc_paths.ps1.
    [string]$Engine = '',
    [string]$Project = (Join-Path $PSScriptRoot '..\DCDemo\DCDemo.uproject'),
    [string]$Archive = (Join-Path $PSScriptRoot '..\_build\archive'),
    # Shipping by default because it is the only configuration that links on this PC until
    # MSVC 14.44.35207 is installed. The plugin's own file log
    # (Saved\DCLogs\) exists precisely so that costs nothing in evidence.
    [string]$Config = 'Shipping',
    [string]$LogDir = (Join-Path $PSScriptRoot '..\_build\logs'),
    [switch]$NoIoStore,
    [switch]$SkipEditorBuild,
    [switch]$KeepArchive,
    [switch]$NoPrereqs
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\tools\dc_paths.ps1')
$Engine = Find-UnrealEngine -Explicit $Engine
Write-Host "engine: $Engine"

# A fresh stage, every time. See the note at the top: the archive folder is a copy
# destination, not a build output, so UAT adds to it and never takes anything away.
$staged = Join-Path (Split-Path $Project -Parent) 'Saved\StagedBuilds'
if (-not $KeepArchive) {
    foreach ($stale in @($Archive, $staged)) {
        if (Test-Path $stale) {
            Write-Host "emptying $stale"
            Remove-Item $stale -Recurse -Force
        }
    }
}
New-Item -ItemType Directory -Force -Path $LogDir, $Archive | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$drive = (Get-Item $Archive).PSDrive
Write-Host ("free on {0} before packaging: {1:N1} GB" -f $drive.Root, ($drive.Free / 1GB))

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

$prereqs = if ($NoPrereqs) { '' } else { ' -prereqs' }

$uat = "`"$Engine\Engine\Build\BatchFiles\RunUAT.bat`" BuildCookRun" `
    + " -project=`"$Project`"" `
    + " -noP4 -utf8output -unattended" `
    + " -platform=Win64 -clientconfig=$Config" `
    + " -build -cook -stage -pak $ioStore -compressed" `
    + " -nodebuginfo" + $prereqs `
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

# What a copy of the demo must not carry. Reported here rather than left for the export's
# own guard to find, because here is where it would have come from.
$windows = Join-Path $Archive 'Windows'
$unwanted = @(Get-ChildItem $windows -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -eq '.pdb' -or $_.Name -like 'CrashReportClient*' -or
                   $_.FullName -like '*\Saved\Crashes\*' })
if ($unwanted) {
    Write-Host ''
    Write-Warning 'the stage carries files it should not:'
    $unwanted | ForEach-Object { "  {0,14:N0} B  {1}" -f $_.Length, $_.FullName.Substring($windows.Length + 1) }
} else {
    Write-Host 'stage carries no .pdb, no crash reporter and no crash folder'
}

$total = (Get-ChildItem $windows -Recurse -File | Measure-Object -Sum Length).Sum
Write-Host ("packaged build: {0:N1} MB" -f ($total / 1MB))
Write-Host ("free on {0} after packaging: {1:N1} GB" -f $drive.Root, ((Get-Item $Archive).PSDrive.Free / 1GB))
