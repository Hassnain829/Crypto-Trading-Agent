# Registers a Windows scheduled task that starts the dashboard at logon and restarts it after a crash:
#   CryptAI-Dashboard  - the web dashboard on http://127.0.0.1:8080. It starts the agent itself and restarts it
#                        after a crash; the agent opens TradingView in debug mode when needed.
# Run once in PowerShell:   powershell -ExecutionPolicy Bypass -File scripts\install_startup_tasks.ps1
# Remove it again:          powershell -ExecutionPolicy Bypass -File scripts\install_startup_tasks.ps1 -Remove
# An older CryptAI-Agent task is removed: the dashboard runs the agent now (two agents never run at once).
param([switch]$Remove)

$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run_forever.ps1"

foreach ($name in @("CryptAI-Agent", "CryptAI-Dashboard")) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Removed $name"
    }
}
if ($Remove) { exit 0 }

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`" -Command dashboard" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName "CryptAI-Dashboard" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Crypt-AI trading agent: dashboard (starts and watches the agent)" | Out-Null
Write-Host "Registered CryptAI-Dashboard (starts at logon, restarts after a crash; it starts the agent)"
Write-Host "Start it now without logging off:  Start-ScheduledTask -TaskName CryptAI-Dashboard"
