<#
    dc_paths.ps1 - where things are, worked out rather than written down.

    Dot-source it from any script in this tree:

        . (Join-Path $PSScriptRoot '..\tools\dc_paths.ps1')      # from a top-level folder
        . (Join-Path $PSScriptRoot '..\..\tools\dc_paths.ps1')   # from unreal\Tools\

    and three things are then in scope:

        $DCRepoRoot          the root of this copy of the tree, from THIS file's location
        Find-UnrealEngine    the engine, from UE_ROOT / the registry / the launcher manifest
        Find-Blender         blender.exe, from BLENDER_EXE / PATH

    Why it exists: a copy of this tree has to run wherever it is unzipped, on a machine
    nobody has set up. No script in it may name a folder on the machine it was written on,
    so every path is derived from the location of the file asking, and the two outside
    programs are looked for in the places an installer actually records.

    The engine and Blender are needed only to REBUILD. Starting the demo needs neither.
#>

# This file's own location, which works when the file is dot-sourced ($PSScriptRoot would
# then be the caller's folder in some PowerShell versions).
$DCPathsFile = $MyInvocation.MyCommand.Path
$DCRepoRoot  = Split-Path (Split-Path $DCPathsFile -Parent) -Parent


function Get-DCRepoRoot {
    <#  The root of this copy of the tree. #>
    return $DCRepoRoot
}


function Find-DCGameExe {
    <#
        The packaged game's launcher exe.

          game\DCDemo.exe                              a ready-to-run copy of this tree
          unreal\_build\archive\Windows\DCDemo.exe     a packaging run on this machine

        The first that exists wins. If neither does, the first path is returned so the
        caller's own "not packaged yet" message names the right place.
    #>
    param([string]$Explicit = '')

    if ($Explicit) { return $Explicit }
    $candidates = @(
        (Join-Path $DCRepoRoot 'game\DCDemo.exe'),
        (Join-Path $DCRepoRoot 'unreal\_build\archive\Windows\DCDemo.exe')
    )
    foreach ($path in $candidates) { if (Test-Path $path) { return $path } }
    return $candidates[0]
}


function Get-DCGameCommandLine {
    <#
        One command-line string for the packaged game, quoted the way the ENGINE reads it.

        This exists because of one detail of how Unreal parses its own command line, and it
        cost a run of the office exit test to find. FParse::Value looks for "Key=" in the
        raw command line and only then checks whether the next character is a quote:

            -DCCacheDir="C:\DC Office Test\x"      the engine reads the whole path
            "-DCCacheDir=C:\DC Office Test\x"      the engine reads C:\DC

        The second form is what every quoting routine produces by itself - including
        Start-Process -ArgumentList with an array - because to it the argument is one string
        with a space in it, and quoting the string is the right answer for every other
        program. So the quoting is done here and the result is handed over as a single
        string, which Start-Process passes through untouched.

        The matching function for the Python side is dc_paths.game_cmdline().
    #>
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $out = foreach ($arg in $Arguments) {
        if ($arg -notmatch ' ') {
            $arg
        } elseif ($arg -match '^(-[^=]+)=(.*)$') {
            '{0}="{1}"' -f $Matches[1], $Matches[2]     # the quote goes AFTER the = sign
        } else {
            '"{0}"' -f $arg
        }
    }
    return ($out -join ' ')
}


function Get-DCLogDir {
    <#  Where a run may write its logs: _logs at the root of this copy of the tree. Inside
        the tree on purpose - a run must leave nothing outside the folder it was started
        from - and git-ignored, so logs are never committed. #>
    $path = Join-Path $DCRepoRoot '_logs'
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    return $path
}


function Find-Edge {
    <#  msedge.exe: the two places an Edge installer puts it, then PATH, then the registry's
        App Paths entry. $null if there is none - the caller decides whether that is fatal. #>
    $cands = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
    )
    foreach ($path in $cands) { if ($path -and (Test-Path $path)) { return $path } }
    $cmd = Get-Command msedge -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $key = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe'
    $reg = (Get-ItemProperty -Path $key -ErrorAction SilentlyContinue).'(default)'
    if ($reg -and (Test-Path $reg)) { return $reg }
    return $null
}


function Get-DCMonitorRect {
    <#
        A monitor's working rectangle, as @{X;Y;Width;Height}.

          -Which left    the left-most monitor  (the booth's game screen)
          -Which right   the right-most one     (the booth's portal screen)
          -Which primary the primary one

        On a single-monitor machine all three are the same rectangle, which is what makes
        -Booth testable on one screen.
    #>
    param([ValidateSet('left', 'right', 'primary')][string]$Which = 'primary')

    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    $screens = @([System.Windows.Forms.Screen]::AllScreens)
    if (-not $screens) { return @{ X = 0; Y = 0; Width = 1920; Height = 1080 } }
    $pick = switch ($Which) {
        'left'    { ($screens | Sort-Object { $_.Bounds.X })[0] }
        'right'   { ($screens | Sort-Object { $_.Bounds.X })[-1] }
        'primary' { ($screens | Where-Object { $_.Primary } | Select-Object -First 1) }
    }
    if (-not $pick) { $pick = $screens[0] }
    $b = $pick.Bounds
    return @{ X = $b.X; Y = $b.Y; Width = $b.Width; Height = $b.Height }
}


# The three calls needed to take a window's frame off and put it where it belongs. Loaded
# once per session; Add-Type refuses a second definition of the same type.
if (-not ('DCWin32' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class DCWin32
{
    [DllImport("user32.dll", SetLastError = true)]
    public static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter,
        int X, int Y, int cx, int cy, uint uFlags);

    public const int GWL_STYLE = -16;
    public const int WS_CAPTION     = 0x00C00000;
    public const int WS_THICKFRAME  = 0x00040000;
    public const int WS_MINIMIZEBOX = 0x00020000;
    public const int WS_MAXIMIZEBOX = 0x00010000;
    public const int WS_SYSMENU     = 0x00080000;
    public const uint SWP_NOZORDER   = 0x0004;
    public const uint SWP_NOACTIVATE = 0x0010;
    public const uint SWP_FRAMECHANGED = 0x0020;
    public const uint SWP_SHOWWINDOW = 0x0040;
}
'@
}


function Set-DCGameWindowBorderless {
    <#
        Find the main game's window, take its frame off and fill one monitor with it.

        By window, not by pid: the packaged DCDemo.exe is a launcher, so the window belongs
        to a child process, and the title is whatever the project is called - which is why
        this looks for "a visible window owned by a DCDemo process that is not the preview
        copy" instead of naming either.

        SWP_NOACTIVATE throughout. The main game is started last precisely so that it has
        focus and controller 1; moving its own window must not be what takes that away.

        Returns a sentence about what it did, or $null if it found no window. Waits up to
        -TimeoutSeconds for the window to appear, because a packaged build takes a few
        seconds to put one up.
    #>
    param(
        [ValidateSet('left', 'right', 'primary')][string]$Which = 'left',
        [string]$ExcludeTitle = '',
        [int]$TimeoutSeconds = 60
    )

    $rect = Get-DCMonitorRect -Which $Which
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $window = @(Get-Process -Name 'DCDemo*' -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne 0 -and
                           ($ExcludeTitle -eq '' -or $_.MainWindowTitle -ne $ExcludeTitle) } |
            Sort-Object StartTime -Descending | Select-Object -First 1)
        if ($window) {
            $handle = $window[0].MainWindowHandle
            $style = [DCWin32]::GetWindowLong($handle, [DCWin32]::GWL_STYLE)
            $strip = [DCWin32]::WS_CAPTION -bor [DCWin32]::WS_THICKFRAME -bor
                     [DCWin32]::WS_MINIMIZEBOX -bor [DCWin32]::WS_MAXIMIZEBOX -bor
                     [DCWin32]::WS_SYSMENU
            [void][DCWin32]::SetWindowLong($handle, [DCWin32]::GWL_STYLE, ($style -band (-bnot $strip)))
            $flags = [DCWin32]::SWP_NOZORDER -bor [DCWin32]::SWP_NOACTIVATE -bor
                     [DCWin32]::SWP_FRAMECHANGED -bor [DCWin32]::SWP_SHOWWINDOW
            [void][DCWin32]::SetWindowPos($handle, [IntPtr]::Zero, $rect.X, $rect.Y,
                $rect.Width, $rect.Height, $flags)
            return ("'{0}' (pid {1}) borderless at {2},{3} {4}x{5}" -f
                $window[0].MainWindowTitle, $window[0].Id, $rect.X, $rect.Y,
                $rect.Width, $rect.Height)
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}


function Find-UnrealEngine {
    <#
        The Unreal Engine 5.7 install, in this order:

          1. $env:UE_ROOT                     - set it and nothing else is consulted
          2. the registry                     - HKLM:\SOFTWARE\EpicGames\Unreal Engine\5.7,
                                                written by an engine installer
          3. the launcher's own manifest      - C:\ProgramData\Epic\UnrealEngineLauncher\
                                                LauncherInstalled.dat, which is where the
                                                Epic launcher records a 5.7 install (it does
                                                not always write the registry key above)

        -Explicit wins over all three and is what a -Engine parameter passes in.
    #>
    param([string]$Explicit = '', [string]$Version = '5.7')

    if ($Explicit) {
        if (Test-Path (Join-Path $Explicit 'Engine\Binaries\Win64')) { return $Explicit }
        throw "no Unreal Engine at $Explicit (expected $Explicit\Engine\Binaries\Win64)"
    }

    $tried = @()

    if ($env:UE_ROOT) {
        $tried += "UE_ROOT=$env:UE_ROOT"
        if (Test-Path (Join-Path $env:UE_ROOT 'Engine\Binaries\Win64')) { return $env:UE_ROOT }
    } else {
        $tried += 'UE_ROOT (not set)'
    }

    $key = "HKLM:\SOFTWARE\EpicGames\Unreal Engine\$Version"
    $tried += "the registry ($key, value InstalledDirectory)"
    $reg = (Get-ItemProperty -Path $key -Name 'InstalledDirectory' -ErrorAction SilentlyContinue).InstalledDirectory
    if ($reg -and (Test-Path (Join-Path $reg 'Engine\Binaries\Win64'))) { return $reg }

    $manifest = Join-Path $env:ProgramData 'Epic\UnrealEngineLauncher\LauncherInstalled.dat'
    $tried += "the launcher manifest ($manifest)"
    if (Test-Path $manifest) {
        $list = (Get-Content $manifest -Raw | ConvertFrom-Json).InstallationList
        foreach ($entry in $list) {
            if ($entry.AppName -eq "UE_$Version" -and $entry.InstallLocation -and
                (Test-Path (Join-Path $entry.InstallLocation 'Engine\Binaries\Win64'))) {
                return $entry.InstallLocation
            }
        }
    }

    throw ("Unreal Engine $Version was not found. Looked at: " + ($tried -join '; ') +
           ". Install UE $Version, or set the UE_ROOT environment variable to its folder " +
           "(the one that contains Engine\Binaries\Win64), or pass -Engine <path>.")
}


function Find-Blender {
    <#
        blender.exe, in this order:

          1. $env:BLENDER_EXE   - the full path to blender.exe
          2. PATH               - a `blender` on the command path

        -Explicit wins over both and is what a -Blender parameter passes in.
    #>
    param([string]$Explicit = '')

    if ($Explicit) {
        if (Test-Path $Explicit) { return (Resolve-Path $Explicit).Path }
        throw "no Blender at $Explicit"
    }

    if ($env:BLENDER_EXE) {
        if (Test-Path $env:BLENDER_EXE) { return (Resolve-Path $env:BLENDER_EXE).Path }
        throw "BLENDER_EXE is set to $env:BLENDER_EXE, which is not there"
    }

    $cmd = Get-Command blender -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    throw ("Blender was not found. Looked at: BLENDER_EXE (not set); PATH (no 'blender'). " +
           "Set the BLENDER_EXE environment variable to the full path of blender.exe, or " +
           "put blender.exe on PATH, or pass -Blender <path to blender.exe>. " +
           "Blender is only needed to rebuild the art; the demo runs without it.")
}


function Find-DemoPython {
    <#
        The interpreter the server, the tests and the helpers run on, in this order:

          1. $env:DC_PYTHON            - an interpreter chosen by hand
          2. python\python.exe         - the one carried inside this copy of the tree
          3. server\.venv\Scripts\python.exe - a development virtual environment
          4. py -3 / python on PATH

        The carried one is preferred over anything installed because a copy of this tree has
        to run on a machine with no Python and no way to install one.
    #>
    param([string]$Explicit = '')

    if ($Explicit) {
        if (Test-Path $Explicit) { return (Resolve-Path $Explicit).Path }
        throw "no Python at $Explicit"
    }
    if ($env:DC_PYTHON -and (Test-Path $env:DC_PYTHON)) {
        return (Resolve-Path $env:DC_PYTHON).Path
    }
    foreach ($rel in @('python\python.exe', 'server\.venv\Scripts\python.exe')) {
        $p = Join-Path $DCRepoRoot $rel
        if (Test-Path $p) { return (Resolve-Path $p).Path }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }

    throw ("No Python found. Looked at: DC_PYTHON; python\python.exe inside this folder; " +
           "server\.venv\Scripts\python.exe; PATH. The copy of this tree that is meant to " +
           "run anywhere carries its own interpreter in python\ - if that folder is missing, " +
           "this is not that copy.")
}
