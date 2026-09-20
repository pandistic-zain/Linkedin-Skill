# Show the most recent draft.   .\draft.ps1        -> print it
#                               .\draft.ps1 -Edit  -> open in VS Code / Notepad
param([switch]$Edit)

$dir = Join-Path $PSScriptRoot 'drafts'
if (-not (Test-Path $dir)) { Write-Host "No drafts folder yet."; exit }

$latest = Get-ChildItem $dir -Filter *.md | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) { Write-Host "No drafts yet. Next run: weekdays 07:00."; exit }

if ($Edit) {
    if (Get-Command code -ErrorAction SilentlyContinue) { code $latest.FullName } else { notepad $latest.FullName }
    exit
}

Write-Host ""
Write-Host "  $($latest.Name)   written $($latest.LastWriteTime.ToString('ddd HH:mm'))" -ForegroundColor DarkGray
Write-Host ("  " + ("-" * 60)) -ForegroundColor DarkGray
Write-Host ""
Get-Content $latest.FullName | ForEach-Object { "  $_" }
Write-Host ""
Write-Host "  Copy to clipboard:  Get-Content '$($latest.FullName)' | Set-Clipboard" -ForegroundColor DarkGray
Write-Host ""
