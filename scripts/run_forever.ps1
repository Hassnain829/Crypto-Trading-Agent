# Runs one tradeagent command and starts it again if it stops or crashes.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\run_forever.ps1 -Command dashboard
# The dashboard starts and watches the agent itself. Use "-Command agent" only to run the agent without the
# dashboard; a second agent refuses to start while one is running.
param(
    [Parameter(Mandatory = $true)][ValidateSet("agent", "dashboard")][string]$Command,
    [int]$RestartDelaySeconds = 30
)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "$Command-supervisor.log"
$arguments = @("-m", "tradeagent", $Command)
if ($Command -eq "dashboard") { $arguments += "--no-browser" }

Set-Location $root
while ($true) {
    Add-Content $log "$(Get-Date -Format s) starting: python $($arguments -join ' ')"
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -NoNewWindow -PassThru
    $null = $process.Handle  # keeps the exit code readable after the process ends
    # Wait for this process only. Start-Process -Wait would also wait for the agent the dashboard started,
    # so a crashed dashboard would never be restarted while the agent keeps running.
    $process.WaitForExit()
    Add-Content $log "$(Get-Date -Format s) stopped with exit code $($process.ExitCode); restarting in $RestartDelaySeconds s"
    Start-Sleep -Seconds $RestartDelaySeconds
}
