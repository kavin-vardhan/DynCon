<#
    make_maps.ps1 - bring in the Player, import the environment kit, build both maps.

        powershell -ExecutionPolicy Bypass -File unreal\Tools\make_maps.ps1

    Two steps. First the engine's shared **Mannequin** template content pack is copied into
    the project, because a .uasset cannot be copied in from inside a running editor. Only
    the part the demo needs is taken:

        Animations\                 the UE4 locomotion set and ThirdPerson_AnimBP
        Character\Mesh\SK_Mannequin  the male mesh, its skeleton and its physics asset

    and nothing else. In particular **no materials and no textures**: the engine mannequin
    wears the engine's logo on its chest, the demo's no-names rule is no logos anywhere in
    this project, and `env_import.dress_mannequin` puts two plain neutral materials on the
    mesh instead. That also keeps 30 MB of 4K textures and 25 MB of the second character
    out of the repo - what lands here is about 6.7 MB.

    Then the editor runs `make_maps.py`, which imports the environment kit, makes the two
    palettes, builds BP_DCPlayer and BP_DCPlayerController, and writes /Game/Maps/GameA and
    /Game/Maps/GameB.
#>
param(
    # Empty means "find it": UE_ROOT, then the registry, then the launcher's own manifest.
    # See tools\dc_paths.ps1.
    [string]$Engine  = '',
    [string]$Project = (Join-Path $PSScriptRoot '..\DCDemo\DCDemo.uproject'),
    [string]$LogDir  = (Join-Path $PSScriptRoot '..\_build\logs'),
    [switch]$SkipMannequin
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\tools\dc_paths.ps1')
$Engine = Find-UnrealEngine -Explicit $Engine
Write-Host "engine: $Engine"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$content = Join-Path (Split-Path $Project -Parent) 'Content'

if (-not $SkipMannequin) {
    $src = Join-Path $Engine 'Templates\TemplateResources\High\Mannequin\Content'
    if (-not (Test-Path $src)) { throw "the Mannequin template content pack is not at $src" }
    $dst = Join-Path $content 'Mannequin'

    $wanted = @(
        'Animations',
        'Character\Mesh\SK_Mannequin.uasset',
        'Character\Mesh\SK_Mannequin_PhysicsAsset.uasset',
        'Character\Mesh\UE4_Mannequin_Skeleton.uasset'
    )
    $copied = 0
    foreach ($rel in $wanted) {
        $from = Join-Path $src $rel
        if (-not (Test-Path $from)) { Write-Warning "missing in the pack: $rel"; continue }
        $to = Join-Path $dst $rel
        if ((Get-Item $from).PSIsContainer) {
            # The destination folder has to exist first, or Copy-Item makes a *file* of that
            # name and the animations end up as one 10 kB blob.
            if (Test-Path $to -PathType Leaf) { Remove-Item $to -Force }
            New-Item -ItemType Directory -Force -Path $to | Out-Null
            Copy-Item "$from\*" $to -Recurse -Force
        } else {
            New-Item -ItemType Directory -Force -Path (Split-Path $to -Parent) | Out-Null
            Copy-Item $from $to -Force
        }
        $copied++
    }
    $size = (Get-ChildItem $dst -Recurse -File | Measure-Object -Sum Length).Sum
    Write-Host ("mannequin: copied {0} item(s), {1:N1} MB into Content\Mannequin" -f $copied, ($size / 1MB))
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$log = Join-Path $LogDir "make_maps_${stamp}.log"
Write-Host "running make_maps.py in the headless editor (log: $log)"
$started = Get-Date
$script = Join-Path $PSScriptRoot 'make_maps.py'
cmd /c "`"$Engine\Engine\Binaries\Win64\UnrealEditor-Cmd.exe`" `"$Project`" -run=pythonscript -script=`"$script`" -unattended -nosplash > `"$log`" 2>&1"
$exit = $LASTEXITCODE
Write-Host ("editor exit {0} after {1:N1} min" -f $exit, ((Get-Date) - $started).TotalMinutes)

$report = Join-Path $LogDir 'maps.json'
if (Test-Path $report) {
    $j = Get-Content $report -Raw | ConvertFrom-Json
    foreach ($name in @('GameA', 'GameB')) {
        $g = $j.$name
        if ($g) {
            Write-Host ("{0}: {1} actors, {2} x {3} m, game mode {4}, slots {5}" -f `
                $name, $g.actors, $g.extent_m.size[0], $g.extent_m.size[1], $g.game_mode,
                (($g.slots | ForEach-Object { $_.id }) -join ','))
        }
    }
} else {
    Write-Warning "no report at $report"
}

Select-String -Path $log -Pattern '\[env_import\] (ERROR|WARNING)' | Select-Object -First 25 |
    ForEach-Object { $_.Line.Trim() }
if ($exit -ne 0) { throw "make_maps.py failed, see $log" }
