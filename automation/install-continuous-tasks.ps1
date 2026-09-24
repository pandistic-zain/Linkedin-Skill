# Registers the tasks that make the pipeline run continuously while the
# laptop is on: the Command-queue poller (dashboard approvals -> real
# actions), the periodic engagement check (reply drafts), the lead finder
# (freelance/client-post comment drafts), and the weekly analytics report.
# The once-daily post pipeline is registered separately by install-task.ps1.
#
# Run once, as your normal user:
#   powershell -ExecutionPolicy Bypass -File .\automation\install-continuous-tasks.ps1
# Remove later with:
#   Unregister-ScheduledTask -TaskName "LinkedIn Command Executor"
#   Unregister-ScheduledTask -TaskName "LinkedIn Engagement Check"
#   Unregister-ScheduledTask -TaskName "LinkedIn Lead Finder"
#   Unregister-ScheduledTask -TaskName "LinkedIn Weekly Analytics"

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw "Python not found on PATH. Install Python 3 and retry." }

# pythonw.exe (same install, no console subsystem) runs with no window at
# all instead of python.exe's brief console flash. Every script here logs
# to its own file already, so losing the console's stdout costs nothing.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (Test-Path $pythonw) { $python = $pythonw } else { Write-Warning "pythonw.exe not found next to python.exe - tasks will still flash a console window." }

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

# --- Lead finder: twice a day, indefinitely -----------------------------
$leadScript = Join-Path $PSScriptRoot 'run_lead_finder.py'
if (-not (Test-Path $leadScript)) { throw "run_lead_finder.py not found at $leadScript" }

$leadAction  = New-ScheduledTaskAction -Execute $python -Argument "`"$leadScript`"" -WorkingDirectory $repo
$leadTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 12) -RepetitionDuration (New-TimeSpan -Days 3650)
$leadSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "LinkedIn Lead Finder" -Action $leadAction -Trigger $leadTrigger `
    -Settings $leadSettings -Description "Finds freelance/client-lead posts and drafts a comment for dashboard approval (max 4/run)." `
    -Force | Out-Null

# --- Weekly analytics: Monday 08:00, indefinitely -----------------------
$analyticsScript = Join-Path $PSScriptRoot 'run_analytics.py'
if (-not (Test-Path $analyticsScript)) { throw "run_analytics.py not found at $analyticsScript" }

$analyticsAction  = New-ScheduledTaskAction -Execute $python -Argument "`"$analyticsScript`"" -WorkingDirectory $repo
$analyticsTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '08:00'
$analyticsSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "LinkedIn Weekly Analytics" -Action $analyticsAction -Trigger $analyticsTrigger `
    -Settings $analyticsSettings -Description "Reports who engaged with this week's post(s), segmented by ICP tier. Read-only." `
    -Force | Out-Null

Write-Host ""
Write-Host "Registered 'LinkedIn Command Executor' - polls every 5 minutes"
Write-Host "Registered 'LinkedIn Engagement Check'  - runs every 4 hours"
Write-Host "Registered 'LinkedIn Lead Finder'       - runs every 12 hours, max 4 drafts/run"
Write-Host "Registered 'LinkedIn Weekly Analytics'  - runs Mondays at 08:00"
Write-Host ""
Write-Host "All four only do anything while this machine is on and has internet - same as"
Write-Host "'LinkedIn Daily Pipeline'. No cloud component; nothing runs when it's off."
Write-Host ""
Write-Host "Requires in .env: DASHBOARD_EVENTS_URL, EVENTS_INGEST_SECRET, LINKEDIN_HANDLE, APIFY_TOKEN"
Write-Host ""
Write-Host "Test any now without waiting:"
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Command Executor`""
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Engagement Check`""
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Lead Finder`""
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Weekly Analytics`""
Write-Host ""
Write-Host "Reply and lead drafts always need approval on the dashboard (/replies) before"
Write-Host "anything posts - this pipeline never auto-posts a comment, unlike the daily post."
