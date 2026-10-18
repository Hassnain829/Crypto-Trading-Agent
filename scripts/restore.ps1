# Restores a zip made by scripts\backup.ps1 on this computer, for example a new PC or VPS.
#
#   1. Code:     git clone https://github.com/Hassnain829/Crypto-Trading-Agent.git C:\Crypt-Ai-Trading,
#                then create the venv and install the packages (docs/VPS-SETUP.md).
#   2. Restore:  powershell -ExecutionPolicy Bypass -File scripts\restore.ps1 -Zip <path of backup-....zip>
#   3. Start:    .venv\Scripts\python -m tradeagent doctor
#                powershell -ExecutionPolicy Bypass -File scripts\install_startup_tasks.ps1
#                Start-ScheduledTask -TaskName CryptAI-Dashboard
#
# The agent and the dashboard must be stopped, and the old computer's agent too: two agents would trade the
# same account. Nothing is deleted: a journal, .env or research file that is already here is moved to
# data\transfer\restore-<time>\previous. The settings files come from git and are not touched; the backup's copy
# is in data\transfer\restore-<time>\config for comparison.

param([Parameter(Mandatory = $true)][string]$Zip)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$stamp = Get-Date -Format "yyyy-MM-dd-HHmm"

$running = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match "tradeagent" })
if ($running.Count -gt 0) {
    Write-Host "The agent or the dashboard is running (python PID $($running.ProcessId -join ', ')). Stop them first:"
    Write-Host "  Stop-ScheduledTask -TaskName CryptAI-Dashboard; Stop-Process -Id <PID>"
    exit 1
}
if (-not (Test-Path $Zip)) { Write-Host "Not found: $Zip"; exit 1 }

$out = Join-Path $root "data\transfer\restore-$stamp"
$previous = Join-Path $out "previous"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory((Resolve-Path $Zip).Path, $out)
New-Item -ItemType Directory -Force $previous | Out-Null

function Restore-File([string]$from, [string]$to) {
    New-Item -ItemType Directory -Force (Split-Path $to -Parent) | Out-Null
    if (Test-Path $to) { Move-Item $to (Join-Path $previous (Split-Path $to -Leaf)) -Force }
    Copy-Item $from $to
}

# The old journal's -wal and -shm files must go with it, or SQLite would apply them to the restored journal.
$journal = Join-Path $root "data\journal.db"
foreach ($side in @("$journal-wal", "$journal-shm")) {
    if (Test-Path $side) { Move-Item $side (Join-Path $previous (Split-Path $side -Leaf)) -Force }
}
Restore-File (Join-Path $out "journal.db") $journal
Write-Host "Journal restored: $journal"

if (Test-Path (Join-Path $out ".env")) {
    Restore-File (Join-Path $out ".env") (Join-Path $root ".env")
    Write-Host "Keys restored: .env"
}

if (Test-Path (Join-Path $out "research-data")) {
    Get-ChildItem (Join-Path $out "research-data") -File |
        ForEach-Object { Restore-File $_.FullName (Join-Path $root "data\research\$($_.Name)") }
    Write-Host "Research databases restored: data\research"
}

if (Test-Path (Join-Path $out "claude-context.zip")) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "claude_context.ps1") `
        -Import -Zip (Join-Path $out "claude-context.zip")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Claude's memory was NOT imported (see the error above). Retry with:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\claude_context.ps1 -Import -Zip `"$out\claude-context.zip`""
    }
}

Write-Host ""
Write-Host "Done. The backup's files are in $out (it may hold the keys; delete it when everything works)."
Write-Host "Next: doctor, install_startup_tasks.ps1, Start-ScheduledTask -TaskName CryptAI-Dashboard."
Write-Host "In TradingView, log in and open the four AGENT layouts (the agent also opens them itself)."
