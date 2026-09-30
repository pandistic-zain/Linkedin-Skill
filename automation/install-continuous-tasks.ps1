# Registers the tasks that make the pipeline run continuously while the
# laptop is on: the Command-queue poller (dashboard approvals -> real
# actions), the periodic engagement check (reply drafts), the lead finder
# (freelance/client-post comment drafts), the weekly analytics report, and
# the six skills that get a scheduled run through run_skill.py.
# The once-daily post pipeline is registered separately by install-task.ps1.
#
# Run once, as your normal user:
#   powershell -ExecutionPolicy Bypass -File .\automation\install-continuous-tasks.ps1
# Remove later with:
#   Unregister-ScheduledTask -TaskName "LinkedIn Command Executor"
#   Unregister-ScheduledTask -TaskName "LinkedIn Engagement Check"
#   Unregister-ScheduledTask -TaskName "LinkedIn Lead Finder"
#   Unregister-ScheduledTask -TaskName "LinkedIn Weekly Analytics"
#   (the run_skill.py tasks are listed in $skillJobs below)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw "Python not found on PATH. Install Python 3 and retry." }

# pythonw.exe (same install, no console subsystem) runs with no window at
# all instead of python.exe's brief console flash. Every script here logs
# to its own file already, so losing the console's stdout costs nothing.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (Test-Path $pythonw) { $python = $pythonw } else { throw "pythonw.exe is required for background tasks without console windows." }

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
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45)

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
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

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
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName "LinkedIn Lead Finder" -Action $leadAction -Trigger $leadTrigger `
    -Settings $leadSettings -Description "Finds freelance/client-lead posts and drafts a comment for dashboard approval (max 4/run)." `
    -Force | Out-Null

# --- Weekly analytics: Monday 08:00, indefinitely -----------------------
$analyticsScript = Join-Path $PSScriptRoot 'run_analytics.py'
if (-not (Test-Path $analyticsScript)) { throw "run_analytics.py not found at $analyticsScript" }

$analyticsAction  = New-ScheduledTaskAction -Execute $python -Argument "`"$analyticsScript`"" -WorkingDirectory $repo
$analyticsTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '08:00'
$analyticsSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45)

Register-ScheduledTask -TaskName "LinkedIn Weekly Analytics" -Action $analyticsAction -Trigger $analyticsTrigger `
    -Settings $analyticsSettings -Description "Reports who engaged with this week's post(s), segmented by ICP tier. Read-only." `
    -Force | Out-Null

# --- Scheduled skills: one claude call each, via run_skill.py ------------
# Each skill gets its own row on the dashboard's Skills page, because
# run_skill.py reports every run as a skill_run event - completed, failed, or
# "not configured: <input file>" when the input it needs has not been filled
# in yet. Cadence is lean on purpose: daily belongs to the post pipeline,
# these are weekly or monthly.
$skillScript = Join-Path $PSScriptRoot 'run_skill.py'
if (-not (Test-Path $skillScript)) { throw "run_skill.py not found at $skillScript" }

$skillSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
                 -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

# Monthly trigger, registered from the same XML Task Scheduler itself writes.
# New-ScheduledTaskTrigger has no -Monthly on PowerShell 5.1, and a hand-built
# MSFT_TaskMonthlyTrigger CIM instance is rejected with HRESULT 0x80070057 -
# this is the one form the OS accepts, and it is what gives the three
# monthly skills their 1st-of-the-month run.
function Register-MonthlyTask {
    param([string]$Name, $Action, [string]$At, [string]$Desc)

    $hour, $minute = $At.Split(':')
    $start = Get-Date -Day 1 -Hour $hour -Minute $minute -Second 0
    if ($start -lt (Get-Date)) { $start = $start.AddMonths(1) }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value

    $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>$Desc</Description>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <IdleSettings>
      <Duration>PT10M</Duration>
      <WaitTimeout>PT1H</WaitTimeout>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT20M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$($start.ToString('yyyy-MM-ddTHH:mm:ss'))</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByMonth>
        <Months>
          <January /><February /><March /><April /><May /><June />
          <July /><August /><September /><October /><November /><December />
        </Months>
        <DaysOfMonth>
          <Day>1</Day>
        </DaysOfMonth>
      </ScheduleByMonth>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>$($Action.Execute)</Command>
      <Arguments>$($Action.Arguments)</Arguments>
      <WorkingDirectory>$($Action.WorkingDirectory)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
    Register-ScheduledTask -TaskName $Name -Xml $xml -Force | Out-Null
}

$skillJobs = @(
    @{ Name = "LinkedIn Content Planner";   Skill = "linkedin-content-planner";   Cadence = "weekly";  Day = "Sunday";  At = "18:00"; Desc = "Writes next week's 7-day content plan." }
    @{ Name = "LinkedIn Hook Extractor";    Skill = "linkedin-hook-extractor";    Cadence = "weekly";  Day = "Wednesday"; At = "10:00"; Desc = "Learns what hooks are working in the niche this week." }
    @{ Name = "LinkedIn Repurposer";        Skill = "linkedin-repurposer";        Cadence = "weekly";  Day = "Thursday"; At = "10:00"; Desc = "Turns a post already published this week into a new draft." }
    @{ Name = "LinkedIn Profile Optimizer"; Skill = "linkedin-profile-optimizer"; Cadence = "monthly"; Day = $null;     At = "09:00"; Desc = "Scores references/profile-snapshot.md and drafts the fixes." }
    @{ Name = "LinkedIn Employee Advocacy"; Skill = "linkedin-employee-advocacy"; Cadence = "monthly"; Day = $null;     At = "10:00"; Desc = "Builds the team advocacy plan from references/team.md." }
    @{ Name = "LinkedIn Interviewer";       Skill = "linkedin-interviewer";       Cadence = "monthly"; Day = $null;     At = "18:00"; Desc = "Writes interview questions for the thin story-bank sections." }
)

foreach ($job in $skillJobs) {
    $skillAction = New-ScheduledTaskAction -Execute $python -Argument "`"$skillScript`" $($job.Skill)" -WorkingDirectory $repo
    $description = "$($job.Desc) Runs run_skill.py $($job.Skill)."
    if ($job.Cadence -eq 'weekly') {
        $skillTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $job.Day -At $job.At
        Register-ScheduledTask -TaskName $job.Name -Action $skillAction -Trigger $skillTrigger `
            -Settings $skillSettings -Description $description -Force | Out-Null
    } else {
        Register-MonthlyTask -Name $job.Name -Action $skillAction -At $job.At -Desc $description
    }
}

Write-Host ""
Write-Host "Registered 'LinkedIn Command Executor' - polls every 5 minutes"
Write-Host "Registered 'LinkedIn Engagement Check'  - runs every 4 hours"
Write-Host "Registered 'LinkedIn Lead Finder'       - runs every 12 hours, max 4 drafts/run"
Write-Host "Registered 'LinkedIn Weekly Analytics'  - runs Mondays at 08:00"
foreach ($job in $skillJobs) {
    $cadence = if ($job.Cadence -eq 'weekly') { "every $($job.Day) at $($job.At)" } else { "the 1st of each month at $($job.At)" }
    Write-Host ("Registered '{0,-27}' - {1}" -f $job.Name, $cadence)
}
Write-Host ""
Write-Host "All of these only do anything while this machine is on and has internet - same as"
Write-Host "'LinkedIn Daily Pipeline'. No cloud component; nothing runs when it's off."
Write-Host ""
Write-Host "Requires in .env: DASHBOARD_EVENTS_URL, EVENTS_INGEST_SECRET, LINKEDIN_HANDLE, APIFY_TOKEN"
Write-Host 'The scheduled skills also read references/profile-snapshot.md and references/team.md'
Write-Host '(fill them once, set "filled: yes"); until then those runs report "not configured".'
Write-Host ""
Write-Host "Test any now without waiting:"
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Command Executor`""
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Engagement Check`""
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Lead Finder`""
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Weekly Analytics`""
Write-Host "  Start-ScheduledTask -TaskName `"LinkedIn Content Planner`""
Write-Host ""
Write-Host "Reply and lead drafts always need approval on the dashboard (/replies) before"
Write-Host "anything posts - this pipeline never auto-posts a comment, unlike the daily post."
