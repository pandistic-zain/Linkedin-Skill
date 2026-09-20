# Registers the two tasks that make the pipeline run continuously while
# the laptop is on: the Command-queue poller (dashboard approvals ->
# real actions) and the periodic engagement check (reply drafts). The
# once-daily post pipeline is registered separately by install-task.ps1.
#
# Run once, as your normal user:
#   powershell -ExecutionPolicy Bypass -File .\automation\install-continuous-tasks.ps1
# Remove later with:
#   Unregister-ScheduledTask -TaskName "LinkedIn Command Executor"
#   Unregister-ScheduledTask -TaskName "LinkedIn Engagement Check"

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw "Python not found on PATH. Install Python 3 and retry." }

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Warning "Claude Code CLI ('claude') is not on PATH. The engagement check will install but fail."
    Write-Warning "Install it with:  npm i -g @anthropic-ai/claude-code"
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
            -AllowStartIfOnBatteries -MultipleInstances IgnoreNew

# --- Command executor: every 5 minutes, indefinitely ------------------
$executorScript = Join-Path $PSScriptRoot 'dashboard_executor.py'
if (-not (Test-Path $executorScript)) { throw "dashboard_executor.py not found at $executorScript" }

$executorAction  = New-ScheduledTaskAction -Execute $python -Argument "`"$executorScript`"" -WorkingDirectory $repo
$executorTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$executorSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)

Register-ScheduledTask -TaskName "LinkedIn Command Executor" -Action $executorAction -Trigger $executorTrigger `
    -Settings $executorSettings -Description "Polls the dashboard's Command queue and executes approved actions." `
    -Force | Out-Null

# --- Engagement check: every 4 hours, indefinitely ---------------------
$engagementScript = Join-Path $PSScriptRoot 'run_engagement.py'
if (-not (Test-Path $engagementScript)) { throw "run_engagement.py not found at $engagementScript" }

$engagementAction  = New-ScheduledTaskAction -Execute $python -Argument "`"$engagementScript`"" -WorkingDirectory $repo
$engagementTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 4) -RepetitionDuration (New-TimeSpan -Days 3650)
$engagementSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "LinkedIn Engagement Check" -Action $engagementAction -Trigger $engagementTrigger `
    -Settings $engagementSettings -Description "Drafts replies to warm comment threads for dashboard approval." `
    -Force | Out-Null

Write-Host ""
Write-Host "Registered 'LinkedIn Command Executor' - polls every 5 minutes"
Write-Host "Registered 'LinkedIn Engagement Check'  - runs every 4 hours"
Write-Host ""
Write-Host "Both only do anything while this machine is on and has internet - same as"
Write-Host "'LinkedIn Daily Pipeline'. No cloud component; nothing runs when it's off."
Write-Host ""
Write-Host "Requires in .env: DASHBOARD_EVENTS_URL, EVENTS_INGEST_SECRET, LINKEDIN_HANDLE"
Write-Host ""
Write-Host "Test either now without waiting:"
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Command Executor`""
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Engagement Check`""
Write-Host ""
Write-Host "Reply drafts always need approval on the dashboard (/replies) before anything"
Write-Host "posts - this pipeline never auto-posts a reply, unlike the daily post."
