"""Synchronous skill_run events for the dashboard's /api/events ingest.

Every SKILL.md tells the agent to log its own run with `lib.start_run` /
`lib.finish_run`. That never happened for the scheduled jobs: they call Claude
Code headless (`claude -p`) with tool use denied, so the call was rejected
before it was made, and the scripts never emitted an event either. Result, read
off the live database on 2026-09-29: 6 SkillRun rows total, all of them
`linkedin-post-writer`, while four other skills were running fine and showed
IDLE on the dashboard's Skills page.

So the runner emits the flat shape POST /api/events has always accepted, from
Python, on the main thread. The pipeline's versioned event logger now also
sends synchronously to preserve ordering and terminal events on process exit.

Contract, from dashboard/src/lib/ingest.ts:
  id, skill and status are required; status is running | completed | failed.

Idempotent by day: the id is `<skill>-<YYYY-MM-DD>` (see skill_run_id), so a
same-day retry upserts the same row instead of adding a second one, and two
skills can never share an id (which would make the second overwrite the
first). Skills that run more often than daily pass stamp=True for a unique id
per run.

Configuration is the same two env vars as the rest of the pipeline,
DASHBOARD_EVENTS_URL and EVENTS_INGEST_SECRET; both unset means no-op.
Callers must have loaded .env first.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime


def skill_run_id(skill: str, stamp: bool = False) -> str:
    """`<skill>-<YYYY-MM-DD>` by default: one row per skill per day, so a
    same-day retry upserts instead of duplicating.

    pass stamp=True for skills that run several times a day (engagement,
    leads, analytics) - those need a new id per run or every earlier run
    that day would be overwritten by the last one.
    """
    if stamp:
        return f"{skill}-{datetime.now():%Y-%m-%d-%H%M%S}"
    return f"{skill}-{datetime.now():%Y-%m-%d}"


def finish_skill_run(skill: str, status: str, *, run_id: str, started_at: str,
                     **fields) -> bool:
    """emit_skill_run with finished_at defaulted to now - every terminal
    status reports the moment it stopped."""
    return emit_skill_run(skill, status, run_id=run_id, started_at=started_at,
                          finished_at=None if status == "running" else datetime.now().astimezone().isoformat(),
                          **fields)



def emit_skill_run(
    skill: str,
    status: str,
    *,
    run_id: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    input_summary: str | None = None,
    decision: str | None = None,
    outcome: str | None = None,
    error_text: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """POST one skill_run event. True when it landed, False otherwise.

    Never raises: a dashboard that is down must not fail the skill run that
    was trying to report on it.
    """
    base_url = os.getenv("DASHBOARD_EVENTS_URL")
    secret = os.getenv("EVENTS_INGEST_SECRET")
    if not base_url or not secret:
        return False

    payload: dict[str, object] = {
        "id": run_id or skill_run_id(skill),
        "skill": skill,
        "status": status,
    }
    for key, value in (
        ("startedAt", started_at),
        ("finishedAt", finished_at),
        ("inputSummary", input_summary),
        ("decision", decision),
        ("outcome", outcome),
        ("errorText", error_text),
    ):
        if value:
            payload[key] = value

    try:
        req = urllib.request.Request(
            base_url.rstrip("/") + "/api/events",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {secret}",
            },
        )
        urllib.request.urlopen(req, timeout=timeout).read()
        return True
    except Exception:
        return False
