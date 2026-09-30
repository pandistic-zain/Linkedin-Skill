# LinkedIn automation operations

The eleven Windows tasks run on this machine, while the user is logged in and
network access is available. They are not an always-on cloud service.

All eleven tasks start with `pythonw.exe`. Python launches Claude, Git and
other console subprocesses with Windows `CREATE_NO_WINDOW`, preserving output
capture, timeouts and exit codes. The installers require `pythonw.exe` rather
than falling back to a visible console. Logs remain available in automation/.

## Run contract

- Lead comments, both fresh and regenerated, open with a problem insight,
  give a brief solution glimpse without implementation details, then offer help.
  Before the portfolio link, add a short relevant background sentence grounded
  in the filled profile/story bank; omit it when no verified background exists.
  Include `Portfolio: https://webbyzain.online` within 350-600 characters.
  Claims must be grounded in supplied experience. Ordinary thread replies
  retain their existing conversational style; all comments require approval.

- Daily pipeline: one draft per local date, protected against concurrent manual,
  scheduler and dashboard starts by an OS file lock. Existing handled markers
  remain authoritative. A held draft is preserved for explicit review.
- Automatic publication requires a valid humanizer PASS. Quota errors, timeouts,
  malformed output and BLOCK hold the draft. Manual dashboard approval remains
  an explicit human decision.
- Provider acceptance is `scheduled`, not proof of publication. Confirm delivery
  with `PubloraClient.get_post(post_group_id=...)`, including child-post errors.
- Publora writes are attempted once. After an ambiguous timeout, inspect provider
  state before trying again. Automatic write retries can create duplicates.
- Pipeline events are sent in order, synchronously, with bounded network waits.
  Delivery is best effort, not a durable outbox. Logs and saved drafts are the
  recovery record when the dashboard is unreachable.
- Reply/lead runs fail if their dashboard delivery fails. Analytics reports
  missing sync blocks as failure; a successfully fetched empty audience is
  handled directly rather than relying on model-generated empty JSON.
- Missing personal inputs report `not configured` in the dashboard, with exit 0
  by project convention. Scheduler exit 0 alone does not prove useful work.

## Checks

Run from the repository root:

```powershell
python -B -m unittest discover -s tests
python scripts/check_config.py --offline
python scripts/check_no_secrets.py
python scripts/selftest.py --offline
Get-ScheduledTask -TaskName 'LinkedIn*' | Get-ScheduledTaskInfo
```

Logs are `automation/run.log`, `skills.log`, `engagement.log`, `leads.log`,
`analytics.log`, and `executor.log`. Read recent errors alongside task exit
codes; inspect `drafts/` for preserved output. Never paste environment secrets
into a status report.

## Recovery

1. Quota/authentication failure: restore provider access first. Inspect today's
   saved draft and handled marker before rerunning; do not delete the marker to
   force another publication. The configured publishing cutoff still applies.
2. Audit failure: review the saved draft and approve deliberately through the
   dashboard. Do not bypass the audit automatically.
3. Unknown publishing outcome: check Publora for the original post before any
   repeat submission. A scheduled post may not be live yet.
4. Dashboard outage: retain local artifacts. A command stuck `claimed` requires
   reconciliation against Publora before an operator requeues it. There is no
   automatic lease recovery; this avoids repeating an uncertain external write.
5. Profile/advocacy configuration: fill profile-snapshot/team privately. Do not
   commit filled personal templates. Ignore rules do not hide tracked edits.

## Scheduler budgets

Daily: 40 minutes; executor: 45; engagement: 20; leads: 30; analytics: 45;
scheduled skills: 20. All use IgnoreNew. Installer changes require re-registering
tasks, or updating only their Settings to preserve existing trigger times.

## Remaining operational limits

No guarantee of exactly-once delivery across the provider and dashboard. Local
locks protect this machine, not multiple poller hosts. The dashboard's current
GET command endpoint claims work and has no atomic multi-host claim or lease
recovery; do not introduce a second executor without fixing that server flow.
Dashboard outage replay, retention/rotation of logs, and external failure alerts
are not implemented. A continuously available host and explicit deployment are
required if running only while this laptop is awake is insufficient.
