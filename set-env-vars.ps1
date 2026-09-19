# Reads .env beside this script and sets each key as a Windows USER environment
# variable, so the linkedin-skills plugin finds them wherever it is installed.
# Run once: right-click > Run with PowerShell, or  powershell -File .\set-env-vars.ps1
# Nothing is printed except the variable names. Restart Claude Desktop afterwards.

$envFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envFile)) { Write-Error "No .env found next to this script."; exit 1 }

$wanted = @('PUBLORA_API_KEY','LINKEDIN_PLATFORM_ID','APIFY_TOKEN','PIXFARO_TOKEN')
$set = 0

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq '' -or $line.StartsWith('#') -or ($line -notmatch '=')) { return }
    $key, $value = $line -split '=', 2
    $key = $key.Trim()
    $value = $value.Trim().Trim('"').Trim("'")
    if ($wanted -notcontains $key) { return }
    if ($value -eq '' -or $value -like '*your_*here*') {
        Write-Host "  skipped  $key (still a placeholder)"
        return
    }
    [Environment]::SetEnvironmentVariable($key, $value, 'User')
    Write-Host "  set      $key"
    $script:set++
}

Write-Host ""
Write-Host "$set variable(s) set for your Windows user account."
Write-Host "Now fully quit Claude Desktop (system tray too) and reopen it."
