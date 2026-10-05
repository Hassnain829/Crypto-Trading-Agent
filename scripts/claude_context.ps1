# Move Claude Code's memory and chat history for this project to another computer (for example the VPS).
#
# Claude Code keeps them per project folder in %USERPROFILE%\.claude\projects\<project path with every
# character other than a letter or digit replaced by '-'>. A new chat reads memory\MEMORY.md automatically,
# so with the memory copied, Claude knows the project's state on the new computer.
#
#   On the PC:   powershell -ExecutionPolicy Bypass -File scripts\claude_context.ps1 -Export
#                -> data\transfer\claude-context.zip (memory + chat transcripts)
#   On the VPS:  copy the zip into the project's data\transfer folder, then
#                powershell -ExecutionPolicy Bypass -File scripts\claude_context.ps1 -Import
#
# The import never deletes anything; existing files with the same name are replaced (a copy is kept as .bak).

param(
    [switch]$Export,
    [switch]$Import,
    [string]$Zip = "",
    [string]$ProjectsDir = (Join-Path $env:USERPROFILE ".claude\projects")
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$key = $root -replace '[^A-Za-z0-9]', '-'
$folder = Join-Path $ProjectsDir $key
if (-not $Zip) { $Zip = Join-Path $root "data\transfer\claude-context.zip" }

if ($Export -eq $Import) {
    Write-Host "Use -Export (on the old computer) or -Import (on the new one)."
    exit 2
}

if ($Export) {
    if (-not (Test-Path $folder)) { Write-Host "No Claude Code data for this project in $folder"; exit 1 }
    $stage = Join-Path ([IO.Path]::GetTempPath()) "claude-context-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force $stage | Out-Null
    if (Test-Path (Join-Path $folder "memory")) { Copy-Item (Join-Path $folder "memory") $stage -Recurse }
    Get-ChildItem $folder -Filter *.jsonl | Copy-Item -Destination $stage
    New-Item -ItemType Directory -Force (Split-Path $Zip -Parent) | Out-Null
    if (Test-Path $Zip) { Remove-Item $Zip -Force -Confirm:$false }
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $Zip
    Remove-Item $stage -Recurse -Force -Confirm:$false
    $files = (Get-ChildItem $folder -Filter *.jsonl).Count
    Write-Host "Written $Zip ($([math]::Round((Get-Item $Zip).Length / 1MB, 1)) MB): the memory and $files chat transcript(s)."
    Write-Host "Copy it to the new computer's <project>\data\transfer\ and run this script there with -Import."
    exit 0
}

if (-not (Test-Path $Zip)) { Write-Host "Not found: $Zip"; exit 1 }
New-Item -ItemType Directory -Force $folder | Out-Null
$stage = Join-Path ([IO.Path]::GetTempPath()) "claude-context-$([guid]::NewGuid().ToString('N'))"
Expand-Archive -Path $Zip -DestinationPath $stage
Get-ChildItem $stage -Recurse -File | ForEach-Object {
    $target = Join-Path $folder $_.FullName.Substring($stage.Length + 1)
    New-Item -ItemType Directory -Force (Split-Path $target -Parent) | Out-Null
    if (Test-Path $target) { Copy-Item $target "$target.bak" -Force }
    Copy-Item $_.FullName $target -Force
}
Remove-Item $stage -Recurse -Force -Confirm:$false
Write-Host "Imported into $folder"
Write-Host "Open this project folder in VS Code: a new Claude chat reads the memory. Older chats appear in the"
Write-Host "Claude panel's past conversations (or run 'claude --resume' in a terminal in the project folder)."
