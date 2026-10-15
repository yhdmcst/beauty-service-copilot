param(
    [string]$HostAlias = 'amax-server',
    [ValidateRange(1024, 65535)]
    [int]$LocalPort = 11436
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'connect_remote_model.ps1'
$terminal = Get-Command wt.exe -ErrorAction SilentlyContinue
if ($terminal) {
    & $terminal.Source -w new new-tab --title 'Beauty Copilot - Remote Model SSH' `
        powershell.exe -NoProfile -NoExit -ExecutionPolicy Bypass `
        -File $script -HostAlias $HostAlias -LocalPort $LocalPort
} else {
    $quoted = '"' + $script + '"'
    Start-Process -FilePath powershell.exe -WindowStyle Normal `
        -ArgumentList @('-NoProfile', '-NoExit', '-ExecutionPolicy', 'Bypass',
                        '-File', $quoted, '-HostAlias', $HostAlias, '-LocalPort', "$LocalPort")
}
if (-not ('BeautyRemoteWindow' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class BeautyRemoteWindow {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
}
'@
}
$found = $false
for ($attempt = 0; $attempt -lt 15; $attempt++) {
    $windows = Get-Process -Name WindowsTerminal,powershell -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like '*Beauty Copilot - Remote Model SSH*' }
    if ($windows) {
        foreach ($window in $windows) {
            [void][BeautyRemoteWindow]::ShowWindow($window.MainWindowHandle, 9)
            [void][BeautyRemoteWindow]::SetForegroundWindow($window.MainWindowHandle)
        }
        $found = $true
        break
    }
    Start-Sleep -Milliseconds 200
}
if ($found) {
    Write-Output 'Verified a visible SSH terminal titled Beauty Copilot - Remote Model SSH.'
} else {
    Write-Output 'Window visibility could not be verified. Run start_remote_model.cmd from the project folder.'
}
