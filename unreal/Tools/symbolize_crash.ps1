<#
    symbolize_crash.ps1 - turn the raw "DCDemo + 0x...." frames in a UE crash report into
    function names, using dbghelp and the build's own .pdb.

    The packaged game's crash handler writes the portable call stack (module + offset) but no
    symbols, and there is no debugger installed on this PC, so this does the lookup.

        powershell -ExecutionPolicy Bypass -File unreal\Tools\symbolize_crash.ps1 `
            -CrashXml "<...>\CrashContext.runtime-xml"
#>
param(
    [string]$CrashXml,
    [string]$Exe = (Join-Path $PSScriptRoot '..\DCDemo\Binaries\Win64\DCDemo.exe'),
    [string[]]$Offsets
)

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class DbgHelp
{
    [DllImport("dbghelp.dll", SetLastError = true, CharSet = CharSet.Ansi)]
    public static extern bool SymInitialize(IntPtr process, string searchPath, bool invadeProcess);

    [DllImport("dbghelp.dll", SetLastError = true, CharSet = CharSet.Ansi)]
    public static extern ulong SymLoadModuleEx(IntPtr process, IntPtr file, string imageName,
        string moduleName, ulong baseOfDll, uint dllSize, IntPtr data, uint flags);

    [DllImport("dbghelp.dll", SetLastError = true)]
    public static extern bool SymFromAddr(IntPtr process, ulong address, out ulong displacement, IntPtr symbol);

    [DllImport("dbghelp.dll", SetLastError = true)]
    public static extern uint SymSetOptions(uint options);

    [DllImport("dbghelp.dll", SetLastError = true)]
    public static extern bool SymGetLineFromAddr64(IntPtr process, ulong address, out uint displacement, IntPtr line);

    public const uint SYMOPT_UNDNAME = 0x00000002;
    public const uint SYMOPT_LOAD_LINES = 0x00000010;
    public const uint SYMOPT_DEFERRED_LOADS = 0x00000004;

    public static string Resolve(IntPtr process, ulong address, out string fileLine)
    {
        fileLine = "";
        int bufferSize = 88 + 1024;
        IntPtr buffer = Marshal.AllocHGlobal(bufferSize);
        try
        {
            for (int i = 0; i < bufferSize; i++) { Marshal.WriteByte(buffer, i, 0); }
            Marshal.WriteInt32(buffer, 0, 88);      // SizeOfStruct
            Marshal.WriteInt32(buffer, 80, 1024);   // MaxNameLen
            ulong displacement;
            if (!SymFromAddr(process, address, out displacement, buffer))
            {
                return null;
            }
            string name = Marshal.PtrToStringAnsi(IntPtr.Add(buffer, 84));

            IntPtr lineBuffer = Marshal.AllocHGlobal(40);
            try
            {
                for (int i = 0; i < 40; i++) { Marshal.WriteByte(lineBuffer, i, 0); }
                Marshal.WriteInt32(lineBuffer, 0, 40);
                uint lineDisplacement;
                if (SymGetLineFromAddr64(process, address, out lineDisplacement, lineBuffer))
                {
                    IntPtr filePtr = Marshal.ReadIntPtr(lineBuffer, 24);
                    int lineNumber = Marshal.ReadInt32(lineBuffer, 16);
                    string file = filePtr == IntPtr.Zero ? "" : Marshal.PtrToStringAnsi(filePtr);
                    fileLine = file + ":" + lineNumber;
                }
            }
            finally { Marshal.FreeHGlobal(lineBuffer); }

            return displacement == 0 ? name : (name + " + 0x" + displacement.ToString("x"));
        }
        finally { Marshal.FreeHGlobal(buffer); }
    }
}
'@

if (-not $Offsets -or $Offsets.Count -eq 0) {
    if (-not $CrashXml -or -not (Test-Path $CrashXml)) { throw 'pass -CrashXml or -Offsets' }
    $xml = Get-Content $CrashXml -Raw
    $block = [regex]::Match($xml, '<PCallStack>([\s\S]*?)</PCallStack>')
    if (-not $block.Success) { throw "no PCallStack in $CrashXml" }
    $Offsets = @()
    foreach ($line in $block.Groups[1].Value -split "`n") {
        $m = [regex]::Match($line, '^\s*(\S+)\s+0x([0-9a-fA-F]+)\s*\+\s*([0-9a-fA-F]+)')
        if ($m.Success) {
            $Offsets += ($m.Groups[1].Value + '!' + $m.Groups[3].Value)
        }
    }
}

$handle = [IntPtr]::new(0x1234)
[void][DbgHelp]::SymSetOptions([DbgHelp]::SYMOPT_UNDNAME -bor [DbgHelp]::SYMOPT_LOAD_LINES)
if (-not [DbgHelp]::SymInitialize($handle, (Split-Path $Exe -Parent), $false)) {
    throw "SymInitialize failed ($([ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error()).Message))"
}

$base = [uint64]0x400000000
$loaded = [DbgHelp]::SymLoadModuleEx($handle, [IntPtr]::Zero, $Exe, 'DCDemo', $base, 0, [IntPtr]::Zero, 0)
if ($loaded -eq 0) {
    throw "SymLoadModuleEx failed for $Exe"
}
Write-Host "symbols loaded for $Exe at base 0x$($base.ToString('x'))"
Write-Host ''

$frame = 0
foreach ($entry in $Offsets) {
    $parts = $entry -split '!'
    $module = if ($parts.Count -gt 1) { $parts[0] } else { 'DCDemo' }
    $hex = $parts[-1]
    if ($module -ne 'DCDemo') {
        "[{0,2}] {1} + 0x{2}  (not symbolised)" -f $frame, $module, $hex
        $frame++
        continue
    }
    $rva = [Convert]::ToUInt64($hex, 16)
    $fileLine = ''
    $name = [DbgHelp]::Resolve($handle, $base + $rva, [ref]$fileLine)
    if ($name) {
        "[{0,2}] {1}" -f $frame, $name
        if ($fileLine) { "     {0}" -f $fileLine }
    } else {
        "[{0,2}] DCDemo + 0x{1}  (no symbol)" -f $frame, $hex
    }
    $frame++
}
