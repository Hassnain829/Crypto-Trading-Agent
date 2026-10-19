# Registers the Windows scheduled tasks:
#   CryptAI-Dashboard  - the web dashboard on http://127.0.0.1:8080, started at logon and restarted after a crash.
#                        It starts the agent itself and restarts it after a crash; the agent opens TradingView in
#                        debug mode when needed.
#   CryptAI-Backup     - every day at 03:00 (this computer's time): scripts\backup.ps1 -NoKeys -Keep 14
#                        (journal, Claude's memory, config and research data to C:\CryptAI-Backups; no keys).
# Run once in PowerShell:   powershell -ExecutionPolicy Bypass -File scripts\install_startup_tasks.ps1
# Only the backup task:     powershell -ExecutionPolicy Bypass -File scripts\install_startup_tasks.ps1 -BackupOnly
# Remove them again:        powershell -ExecutionPolicy Bypass -File scripts\install_startup_tasks.ps1 -Remove
# An older CryptAI-Agent task is removed: the dashboard runs the agent now (two agents never run at once).
param([switch]$Remove, [switch]$BackupOnly)

$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run_forever.ps1"
$backup = Join-Path $PSScriptRoot "backup.ps1"

$names = if ($BackupOnly) { @("CryptAI-Backup") } else { @("CryptAI-Agent", "CryptAI-Dashboard", "CryptAI-Backup") }
foreach ($name in $names) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Removed $name"
    }
}
if ($Remove) { exit 0 }

if (-not $BackupOnly) {
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
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$backup`" -NoKeys -Keep 14" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At "03:00"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "CryptAI-Backup" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Crypt-AI trading agent: daily backup without keys to C:\CryptAI-Backups (newest 14 kept)" | Out-Null
Write-Host "Registered CryptAI-Backup (daily at 03:00 this computer's time; copy C:\CryptAI-Backups off the VPS now and then)"
