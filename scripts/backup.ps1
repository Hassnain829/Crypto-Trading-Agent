# Backs up everything the agent and Claude need to continue on another computer, in one zip.
#
#   powershell -ExecutionPolicy Bypass -File scripts\backup.ps1
#   -> C:\CryptAI-Backups\backup-<yyyy-MM-dd-HHmm>utc.zip with:
#        journal.db          the complete journal: market history, shadow book, demo account, experiments and the
#                            settings changed in the dashboard (export-journal: safe while the agent runs)
#        claude-context.zip  Claude Code's memory and chat transcripts for this project (claude_context.ps1)
#        .env                the exchange keys
#        config\             the settings files as they are now
#        research-data\      the indicator research databases from data\research (leave out with -NoResearch)
#        manifest.txt        the git commit and the uncommitted files at backup time
#   Restore it on the new computer with scripts\restore.ps1.
#
# The zip holds the keys: keep it private and never put it in git or a public share.
# The code is not in the zip (it is in git). Nothing in the project is changed or deleted.

param(
    [string]$Dest = "C:\CryptAI-Backups",
    [switch]$NoResearch
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd-HHmm") + "utc"
$stage = Join-Path ([IO.Path]::GetTempPath()) "cryptai-backup-$stamp"
$zip = Join-Path $Dest "backup-$stamp.zip"
$hasKeys = Test-Path (Join-Path $root ".env")

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force -Confirm:$false }
New-Item -ItemType Directory -Force $stage, $Dest | Out-Null
Push-Location $root
try {
    & $python -m tradeagent export-journal (Join-Path $stage "journal.db")
    if ($LASTEXITCODE -ne 0) { throw "export-journal failed" }

    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "claude_context.ps1") `
        -Export -Zip (Join-Path $stage "claude-context.zip")
    if ($LASTEXITCODE -ne 0) { Write-Host "Claude's memory was not included (see the message above)." }

    if (Test-Path ".env") { Copy-Item ".env" $stage } else { Write-Host "No .env here: the keys are not included." }
    Copy-Item "config" (Join-Path $stage "config") -Recurse
    if (-not $NoResearch -and (Test-Path "data\research")) {
        $research = New-Item -ItemType Directory -Force (Join-Path $stage "research-data")
        Get-ChildItem "data\research" -Filter *.db | Copy-Item -Destination $research
    }

    $manifest = @("Backup of $root on $env:COMPUTERNAME at $((Get-Date).ToUniversalTime().ToString('s')) UTC")
    try {
        $manifest += "git commit: $(git rev-parse --short HEAD) ($(git log -1 --format=%s))"
        $manifest += "uncommitted files at backup time:"
        $manifest += git status --short
    } catch { $manifest += "git not available: $_" }
    $manifest += ""
    $manifest += Get-ChildItem $stage -Recurse -File |
        ForEach-Object { "{0,10:N1} MB  {1}" -f ($_.Length / 1MB), $_.FullName.Substring($stage.Length + 1) }
    Set-Content (Join-Path $stage "manifest.txt") $manifest -Encoding UTF8

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)
} finally {
    Pop-Location
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force -Confirm:$false }
}

Write-Host ""
Write-Host "Backup written: $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"
if ($hasKeys) { Write-Host "It contains the exchange keys (.env): keep it private." }
Write-Host "Copy it off this computer (for example to your PC or a private cloud drive), then restore it on the new"
Write-Host "computer with scripts\restore.ps1 -Zip <the zip>."
