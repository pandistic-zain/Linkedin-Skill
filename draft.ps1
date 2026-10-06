# Show the most recent draft.   .\draft.ps1        -> print it
#                               .\draft.ps1 -Edit  -> open in VS Code / Notepad
param([switch]$Edit)

$dir = Join-Path $PSScriptRoot 'drafts'
if (-not (Test-Path $dir)) { Write-Host "No drafts folder yet."; exit }

$latest = Get-ChildItem $dir -Filter *.md | Where-Object { $_.BaseName -match '^\d{4}-\d{2}-\d{2}$' } | Sort-Object Name -Descending | Select-Object -First 1
if (-not $latest) { Write-Host "No drafts yet. Next run: weekdays 07:00."; exit }

if ($Edit) {
    if (Get-Command code -ErrorAction SilentlyContinue) { code $latest.FullName } else { notepad $latest.FullName }
    exit
}

Write-Host ""
Write-Host "  $($latest.Name)   written $($latest.LastWriteTime.ToString('ddd HH:mm'))" -ForegroundColor DarkGray
Write-Host ("  " + ("-" * 60)) -ForegroundColor DarkGray
Write-Host ""
$manifest = [IO.Path]::ChangeExtension($latest.FullName, '.json')
if (Test-Path -LiteralPath $manifest) {
    $post = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    $localBody = Get-Content -LiteralPath $latest.FullName -Raw -Encoding UTF8
    Write-Host $localBody
    if ($localBody.Trim() -ne $post.body.Trim()) {
        Write-Host '  Local text changed after review. Publishing is held until this revision is reviewed.' -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  Review: $($post.delivery) | $($post.error)" -ForegroundColor DarkGray
    Write-Host "  Image: $($post.media.localPath)" -ForegroundColor DarkGray
    Write-Host "  Sources and audit: $manifest" -ForegroundColor DarkGray
} else {
    Get-Content $latest.FullName | ForEach-Object { "  $_" }
}
Write-Host ""
Write-Host "  Copy to clipboard:  Get-Content '$($latest.FullName)' | Set-Clipboard" -ForegroundColor DarkGray
Write-Host ""
