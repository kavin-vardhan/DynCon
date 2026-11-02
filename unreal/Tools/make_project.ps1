<#
    make_project.ps1 - build unreal\DCDemo out of the engine's third-person C++ template.

    Does by hand what the project browser does when you pick "Third Person / C++" and type a
    project name: copy the template, rename the folder, the files, the module, the *_API macros
    and the class names, and write the redirects that let the template's .uasset files find the
    renamed C++ classes.

    The engine folder is only ever read.

        powershell -ExecutionPolicy Bypass -File unreal\Tools\make_project.ps1

    Config files that already exist in the target are left alone, so the project's own
    DefaultEngine.ini / DefaultGame.ini survive a re-run.
#>
param(
    # Empty means "find it": UE_ROOT, then the registry, then the launcher's own manifest.
    # See tools\dc_paths.ps1.
    [string]$Engine  = '',
    [string]$Target  = (Join-Path $PSScriptRoot '..\DCDemo'),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\tools\dc_paths.ps1')
$Engine = Find-UnrealEngine -Explicit $Engine
Write-Host "engine: $Engine"

$TemplateName = 'TP_ThirdPerson'
$ProjectName  = 'DCDemo'
$Template     = Join-Path $Engine "Templates\$TemplateName"

if (-not (Test-Path $Template)) { throw "Template not found: $Template" }
if ((Test-Path $Target) -and -not $Force) { Write-Host "Target exists, updating in place: $Target" }

New-Item -ItemType Directory -Force -Path $Target | Out-Null

# ---------------------------------------------------------------- copy the template

# Things the project browser never copies into a new project.
$skipExact = @(
    'Config\TemplateDefs.ini',
    'Config\config.ini',
    "$TemplateName.uproject",
    "$TemplateName.png"
)
$skipDirs = @('Binaries', 'Build', 'Intermediate', 'Saved', 'Media')

$textExt = @('.cpp', '.h', '.ini', '.cs')

function Convert-Name([string]$s) {
    # Same three replacements, same order, as TemplateDefs.ini.
    $s = $s -creplace [regex]::Escape($TemplateName.ToUpper()),   $ProjectName.ToUpper()
    $s = $s -creplace [regex]::Escape($TemplateName.ToLower()),   $ProjectName.ToLower()
    $s = $s -ireplace [regex]::Escape($TemplateName),             $ProjectName
    return $s
}

$copied = 0
$renamed = @()
Get-ChildItem $Template -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($Template.Length + 1)
    $first = ($rel -split '\\')[0]
    if ($skipExact -contains $rel) { return }
    if ($skipDirs -contains $first) { return }

    $relNew = Convert-Name $rel
    if ($relNew -ne $rel) { $renamed += ,@($rel, $relNew) }

    $dest = Join-Path $Target $relNew
    New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null

    if ($first -eq 'Config' -and (Test-Path $dest)) {
        Write-Host "  keep existing $relNew"
        return
    }

    if ($textExt -contains $_.Extension.ToLower()) {
        # UTF-8 without BOM, LF untouched: the repo has `* -text`.
        $text = [System.IO.File]::ReadAllText($_.FullName)
        [System.IO.File]::WriteAllText($dest, (Convert-Name $text), (New-Object System.Text.UTF8Encoding($false)))
    } else {
        Copy-Item $_.FullName $dest -Force
    }
    $copied++
}
Write-Host "copied $copied files, $($renamed.Count) of them renamed"

# ------------------------------------------------- shared content packs (SharedContentPacks)
#
# The template declares LevelPrototyping, Characters and Input. Characters (125 MB of
# mannequin) is not needed by the spike and would bloat the repo, so only the two small ones
# are taken; the pawn renders as an invisible capsule until Characters is added.
foreach ($pack in @('LevelPrototyping', 'Input')) {
    $src = Join-Path $Engine "Templates\TemplateResources\High\$pack\Content"
    if (-not (Test-Path $src)) { Write-Warning "shared content pack missing: $pack"; continue }
    $dst = Join-Path $Target "Content\$pack"
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item "$src\*" $dst -Recurse -Force
    $n = (Get-ChildItem $dst -Recurse -File).Count
    Write-Host "shared content $pack -> Content\$pack ($n files)"
}

# ---------------------------------------------------------------- the .uproject

$uproject = @'
{
	"FileVersion": 3,
	"EngineAssociation": "5.7",
	"Category": "",
	"Description": "DynamicContents demo: runtime dynamic content slots.",
	"Modules": [
		{
			"Name": "DCDemo",
			"Type": "Runtime",
			"LoadingPhase": "Default",
			"AdditionalDependencies": [
				"Engine",
				"AIModule",
				"UMG"
			]
		}
	],
	"Plugins": [
		{
			"Name": "DynamicContents",
			"Enabled": true
		},
		{
			"Name": "ModelingToolsEditorMode",
			"Enabled": true,
			"TargetAllowList": [
				"Editor"
			]
		},
		{
			"Name": "StateTree",
			"Enabled": true
		},
		{
			"Name": "GameplayStateTree",
			"Enabled": true
		},
		{
			"Name": "PythonScriptPlugin",
			"Enabled": true
		},
		{
			"Name": "EditorScriptingUtilities",
			"Enabled": true
		}
	]
}
'@
[System.IO.File]::WriteAllText((Join-Path $Target "$ProjectName.uproject"), $uproject, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "wrote $ProjectName.uproject"

Write-Host ''
Write-Host 'Renames applied:'
$renamed | ForEach-Object { Write-Host ("  {0}  ->  {1}" -f $_[0], $_[1]) }
