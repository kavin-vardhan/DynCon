<#
    stage_packs.ps1 - take the content chunks out of the packaged build and make packs of them.

    Packaging with chunks produces one pakchunk<N>-Windows.{pak,utoc,ucas} set per
    piece-version next to the base game's pakchunk0 in the staged build. This script moves
    every chunk >= 100 out of the build into unreal\_packs\<id>_<v>\ and writes a small
    pack.json beside it (the ancestor of the server's .dcpack). After it runs, the build on
    disk genuinely does not contain the content - which is the point of the spike.

        powershell -ExecutionPolicy Bypass -File unreal\Tools\stage_packs.ps1
#>
param(
    [string]$Archive = 'E:\DynamicContents\unreal\_build\archive\Windows',
    [string]$Cooked  = 'E:\DynamicContents\unreal\DCDemo\Saved\Cooked\Windows\DCDemo',
    [string]$Packs   = 'E:\DynamicContents\unreal\_packs',
    [hashtable]$ChunkMap = @{ 100 = 'content4_v1'; 101 = 'content1_v1' }
)

$ErrorActionPreference = 'Stop'

$paksDir = Join-Path $Archive 'DCDemo\Content\Paks'
if (-not (Test-Path $paksDir)) { throw "no staged Paks folder at $paksDir" }

Write-Host "staged Paks folder: $paksDir"
Get-ChildItem $paksDir -File | Sort-Object Name | ForEach-Object {
    "  {0,-34} {1,12:N0} B" -f $_.Name, $_.Length
}

New-Item -ItemType Directory -Force -Path $Packs | Out-Null
$moved = @()

Get-ChildItem $paksDir -Filter 'pakchunk*.pak' -File | ForEach-Object {
    if ($_.Name -notmatch '^pakchunk(\d+)') { return }
    $chunk = [int]$Matches[1]
    if ($chunk -lt 100) { return }

    $name = $ChunkMap[$chunk]
    if (-not $name) {
        Write-Warning "chunk $chunk has no name in ChunkMap, leaving it in the build"
        return
    }

    $dest = Join-Path $Packs $name
    New-Item -ItemType Directory -Force -Path $dest | Out-Null

    # The whole set: .pak plus the IoStore container halves (and a .sig if signing is on).
    $base = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
    $files = @()
    foreach ($ext in @('.pak', '.utoc', '.ucas', '.sig')) {
        $src = Join-Path $paksDir ($base + $ext)
        if (Test-Path $src) {
            $len = (Get-Item $src).Length
            Move-Item $src (Join-Path $dest ($base + $ext)) -Force
            $files += [pscustomobject]@{ name = ($base + $ext); bytes = $len }
        }
    }

    # What the cook decided belongs in this chunk - worth keeping as evidence.
    $manifest = Join-Path $Cooked ("Metadata\ChunkManifest\pakchunk$chunk.txt")
    $packages = @()
    if (Test-Path $manifest) {
        # [string] on purpose: Get-Content decorates its lines with note properties that
        # ConvertTo-Json would otherwise serialise instead of the text.
        $packages = @(Get-Content $manifest | Where-Object { $_ -ne '' } | ForEach-Object { [string]$_ })
    }

    $idParts = $name -split '_'
    $json = [ordered]@{
        id          = $idParts[0]
        version     = $idParts[1]
        pack        = $name
        chunk_id    = $chunk
        class_path  = "/Game/DCContent/$name/BP_DC_$name.BP_DC_${name}_C"
        files       = $files
        total_bytes = ($files | Measure-Object -Sum bytes).Sum
        cooked_files_in_chunk = $packages.Count
        cooked_files = $packages
        built_utc   = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
    $json | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $dest 'pack.json') -Encoding utf8

    $moved += [pscustomobject]@{
        chunk = $chunk
        pack  = $name
        bytes = $json.total_bytes
        files = ($files | ForEach-Object { "$($_.name)=$($_.bytes)" }) -join ' '
    }
}

Write-Host ''
Write-Host 'packs staged out of the build:'
$moved | Sort-Object chunk | Format-Table -AutoSize | Out-String | Write-Host

Write-Host 'Paks folder left in the build:'
Get-ChildItem $paksDir -File | Sort-Object Name | ForEach-Object {
    "  {0,-34} {1,12:N0} B" -f $_.Name, $_.Length
}

$leftovers = Get-ChildItem $paksDir -Filter 'pakchunk1*.pak' -File
if ($leftovers) { Write-Warning "content chunks still in the build: $($leftovers.Name -join ', ')" }

$total = (Get-ChildItem $Archive -Recurse -File | Measure-Object -Sum Length).Sum
Write-Host ("packaged build after removal: {0:N1} MB" -f ($total / 1MB))
Write-Host ("free on E:: {0:N1} GB" -f ((Get-PSDrive E).Free / 1GB))
