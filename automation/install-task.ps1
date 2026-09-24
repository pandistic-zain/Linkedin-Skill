# Registers the daily LinkedIn pipeline as a Windows Scheduled Task.
# Run once, as your normal user:  powershell -ExecutionPolicy Bypass -File .\automation\install-task.ps1
# Remove later with:              Unregister-ScheduledTask -TaskName "LinkedIn Daily Pipeline"

$ErrorActionPreference = 'Stop'

$repo   = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'run_daily.py'
$name   = 'LinkedIn Daily Pipeline'
$time   = '07:00'          # local time, weekdays. Drafts land before you start work.

if (-not (Test-Path $script)) { throw "run_daily.py not found at $script" }

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw "Python not found on PATH. Install Python 3 and retry." }

# pythonw.exe (same install, no console subsystem) runs with no window at
# all instead of python.exe's brief console flash. Every script here logs
# to its own file already, so losing the console's stdout costs nothing.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (Test-Path $pythonw) { $python = $pythonw } else { Write-Warning "pythonw.exe not found next to python.exe - task will still flash a console window." }

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Warning "Claude Code CLI ('claude') is not on PATH. The task will install but fail at the draft step."
    Write-Warning "Install it with:  npm i -g @anthropic-ai/claude-code"
}

$action  = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
            -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Description "Drafts a LinkedIn post each weekday morning." -Force | Out-Null

Write-Host ""
Write-Host "Registered '$name'"
Write-Host "  runs    : weekdays at $time (local)"
Write-Host "  python  : $python"
Write-Host "  folder  : $repo"
Write-Host "  drafts  : $repo\drafts\"
Write-Host "  log     : $repo\automation\run.log"
Write-Host ""
Write-Host "Test it now without waiting:"
Write-Host "  Start-ScheduledTask -TaskName `"$name`""
Write-Host ""
Write-Host "Publishing is OFF by default. To publish unattended, set AUTOPUBLISH=true in .env"
Write-Host "and re-run set-env-vars.ps1."
