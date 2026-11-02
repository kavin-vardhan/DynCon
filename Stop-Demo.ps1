<#
    Stop-Demo.ps1 - stop exactly what Start-Demo started, and nothing else.

        .\Stop-Demo.bat

    `Start-Demo.ps1` writes `_run\demo_run.json` as it goes: one entry per process it
    started, with the pid, the process name and the moment it started. This reads that and
    stops those processes, checking the name and the start time first - a pid on its own is
    not proof, because Windows reuses them and the one in the file could by now belong to
    something a person is working in.

    Each is stopped with its whole tree (`taskkill /T`), which matters for the game: the
    packaged `DCDemo.exe` is a launcher that starts `DCDemo-Win64-Shipping.exe`, and ending
    the launcher on its own leaves the real game running. One was found still up twenty
    minutes after the run that started it had finished.

    Afterwards it says whether anything is still listening on the port, so "nothing is left
    running" is something it tells you rather than something you hope.

    -Any also stops a game, a server or a pad helper it did not start - for the case where
    the state file has been lost, or a previous run was ended by closing its window. It
    never touches a browser it did not start.
#>
param(
    [int]$Port = 8700,
    [switch]$Any,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tools\dc_paths.ps1')

$repo = Get-DCRepoRoot
$stateFile = Join-Path $repo '_run\demo_run.json'

function Say([string]$line) { if (-not $Quiet) { Write-Host $line } }

function Get-Descendants([int]$root) {
    <#  Every process under this one, deepest first.

        Not `taskkill /T`: taskkill writes to stderr when one member of a tree will not die
        - a browser's crash handler, for instance - and in PowerShell a native command's
        stderr becomes an error record, which with $ErrorActionPreference = 'Stop' throws.
        The first run of the office exit test ended with the server still listening because
        of exactly that: the browser kept one child alive, taskkill complained, the script
        stopped, and the two things after it in the list were never stopped at all.
    #>
    $all = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId |
        ForEach-Object { @{ pid = [int]$_.ProcessId; parent = [int]$_.ParentProcessId } }
    $byParent = @{}
    foreach ($row in $all) {
        if (-not $byParent.ContainsKey($row.parent)) { $byParent[$row.parent] = @() }
        $byParent[$row.parent] += $row.pid
    }
    # Not $pid: that is PowerShell's own read-only variable for this process.
    $order = New-Object System.Collections.ArrayList
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($root)
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        [void]$order.Add($current)
        foreach ($child in ($byParent[$current] | Where-Object { $_ -and $order -notcontains $_ })) {
            $queue.Enqueue($child)
        }
    }
    $order.Reverse()
    return $order
}


function Stop-Tree($proc, [string]$what) {
    Say ("  stopping {0,-22} pid {1}" -f $what, $proc.Id)
    $stubborn = @()
    foreach ($id in (Get-Descendants $proc.Id)) {
        $child = Get-Process -Id $id -ErrorAction SilentlyContinue
        if (-not $child) { continue }
        try {
            Stop-Process -Id $id -Force -ErrorAction Stop
        } catch {
            # Already going, or a protected process. Either way it is not worth stopping
            # everything else over; the check at the end of this script has the last word.
            $stubborn += "$($child.ProcessName) (pid $id)"
        }
    }
    if (-not $proc.WaitForExit(20000)) {
        Say "    it did not go within 20 s"
        $stubborn += "$($proc.ProcessName) (pid $($proc.Id))"
    }
    if ($stubborn) {
        Say ("    would not stop: {0}" -f (($stubborn | Select-Object -Unique) -join ', '))
    }
}

$stopped = 0
if (Test-Path $stateFile) {
    $state = Get-Content $stateFile -Raw | ConvertFrom-Json
    Say ("stopping the {0}-mode demo started at {1}" -f $state.mode, $state.started_utc)
    # Reverse order: the game and the browser first, the server last, so nothing is left
    # staring at a socket that has gone.
    $rows = @($state.processes)
    [array]::Reverse($rows)
    foreach ($row in $rows) {
        $proc = Get-Process -Id $row.pid -ErrorAction SilentlyContinue
        if (-not $proc) {
            Say ("  already gone  {0,-22} pid {1}" -f $row.what, $row.pid)
            continue
        }
        # Same pid, but is it the same process? The name and the start time say so.
        $sameName = $proc.ProcessName -ieq $row.name
        $sameStart = $false
        try { $sameStart = ([datetime]$row.started_at - $proc.StartTime).Duration().TotalSeconds -lt 2 }
        catch { $sameStart = $false }
        if (-not ($sameName -and $sameStart)) {
            Write-Warning ("  pid {0} is now '{1}' started {2}, not the {3} this started - " +
                           "leaving it alone" -f $proc.Id, $proc.ProcessName,
                           $proc.StartTime.ToString('s'), $row.what)
            continue
        }
        Stop-Tree $proc $row.what
        $stopped++
    }
    Remove-Item $stateFile -Force
    Say ("  {0} of them were still running" -f $stopped)
} else {
    Say "there is no $stateFile - nothing was started from this folder, or it has already been stopped."
}

if ($Any) {
    Say ''
    Say '-Any: looking for a game, a server or a pad helper this folder did not start'
    foreach ($name in @('DCDemo', 'DCDemo-Win64-Shipping')) {
        foreach ($proc in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
            Stop-Tree $proc "$name (not ours)"
            $stopped++
        }
    }
    foreach ($conn in @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Tree $proc "whatever holds port $Port"
            $stopped++
        }
    }
}

# ------------------------------------------------------------------- did it actually stop?
Start-Sleep -Milliseconds 600
$left = @()
$busy = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
foreach ($conn in $busy) {
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    $left += ("port {0} is still held by {1} (pid {2})" -f $Port,
        ($(if ($proc) { $proc.ProcessName } else { '?' })), $conn.OwningProcess)
}
foreach ($proc in @(Get-Process -Name 'DCDemo*' -ErrorAction SilentlyContinue)) {
    $left += ("{0} (pid {1}) is still running" -f $proc.ProcessName, $proc.Id)
}

Say ''
if ($left) {
    foreach ($line in $left) { Write-Warning $line }
    Write-Host 'something is still running. Stop-Demo.bat -Any stops it.' -ForegroundColor Yellow
    exit 1
}
Write-Host ("nothing of the demo is running: port {0} is free and no game is up." -f $Port) `
    -ForegroundColor Green
