<#
.SYNOPSIS
  Start TradingView Desktop (Microsoft Store build) with the Chrome DevTools debug port,
  so the agent can read the charts.

.DESCRIPTION
  If the debug port already answers, nothing happens. Otherwise TradingView is closed
  gracefully (so it saves its layouts) and started again through Windows app activation
  with --remote-debugging-port. The port listens on localhost only.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\launch_tradingview_debug.ps1
#>
param(
    [int]$Port = 9222,
    [string]$AppId = 'TradingView.Desktop_n534cwy3pjxzj!TradingView.Desktop'
)

function Get-CdpVersion {
    try { Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 } catch { $null }
}

$version = Get-CdpVersion
if ($version) {
    Write-Output "TradingView debug port is already open: $($version.Browser)"
    exit 0
}

# 1) Close TradingView gracefully so it can save its layouts
$withWindow = Get-Process TradingView -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 }
foreach ($p in $withWindow) { [void]$p.CloseMainWindow() }
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    $open = Get-Process TradingView -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 }
    if (-not $open) { break }
    Start-Sleep -Milliseconds 500
}
$open = Get-Process TradingView -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 }
if ($open) {
    Write-Output "A TradingView window is still open (maybe a save dialog). Close it yourself, then run this script again."
    exit 2
}
$rest = Get-Process TradingView -ErrorAction SilentlyContinue
if ($rest) {
    $rest | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# 2) Start the Store app through app activation, passing the debug-port argument
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class TvLauncher {
    [ComImport, Guid("2e941141-7f97-4756-ba1d-9decde894a3d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IApplicationActivationManager {
        IntPtr ActivateApplication([In] string appUserModelId, [In] string arguments, [In] int options, [Out] out uint processId);
        IntPtr ActivateForFile([In] string appUserModelId, [In] IntPtr itemArray, [In] string verb, [Out] out uint processId);
        IntPtr ActivateForProtocol([In] string appUserModelId, [In] IntPtr itemArray, [Out] out uint processId);
    }
    [ComImport, Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
    class ApplicationActivationManager { }
    public static uint Launch(string aumid, string args) {
        var manager = (IApplicationActivationManager)new ApplicationActivationManager();
        uint processId;
        manager.ActivateApplication(aumid, args, 0, out processId);
        return processId;
    }
}
"@
$tvPid = [TvLauncher]::Launch($AppId, "--remote-debugging-port=$Port")
Write-Output "Started TradingView (pid $tvPid), waiting for the debug port..."

# 3) Wait for the DevTools endpoint
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    $version = Get-CdpVersion
    if ($version) {
        Write-Output "TradingView debug port is open: $($version.Browser)"
        exit 0
    }
    Start-Sleep -Seconds 1
}
Write-Output "TradingView started but the debug port did not answer within 45 seconds."
exit 3
