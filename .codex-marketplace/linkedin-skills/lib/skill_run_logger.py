"""Fire-and-forget skill-run logging to the dashboard's /api/events ingest.

Zero third-party dependencies (stdlib `urllib` only) so it works at every
support tier, including Tier 0 manual users who never install `requests`.
Every call runs on a short-lived daemon thread with a small timeout and
swallows all exceptions: a dashboard that is down, slow, or misconfigured
must never slow down or break a skill run.

Configuration is two env vars, both optional:
- DASHBOARD_EVENTS_URL: base URL of the dashboard, e.g. https://dash.example.com
- EVENTS_INGEST_SECRET: shared bearer secret, must match the dashboard's

If either is unset, every call below is a no-op.

Usage:
    from lib.skill_run_logger import start_run, finish_run

    run_id = start_run("linkedin-post-writer", input_summary="Q3 hiring post")
    ...
    finish_run(run_id, "linkedin-post-writer", "completed",
               decision="PAS formula", outcome="approved")
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib import request as urllib_request
from urllib.error import URLError

from ._env import load_env

_TIMEOUT_SECONDS = 2.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post(payload: dict[str, Any], path: str = "/api/events") -> None:
    load_env()
    import os

    base_url = os.getenv("DASHBOARD_EVENTS_URL")
    secret = os.getenv("EVENTS_INGEST_SECRET")
    if not base_url or not secret:
        return

    def _send() -> None:
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib_request.Request(
                base_url.rstrip("/") + path,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {secret}",
                },
            )
            urllib_request.urlopen(req, timeout=_TIMEOUT_SECONDS)
        except (URLError, OSError, ValueError):
            pass  # never let logging break the calling skill

    threading.Thread(target=_send, daemon=True).start()


def emit(event_type: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget send of a versioned envelope event to /api/ingest.
    Same no-op-if-unconfigured, swallow-everything behavior as `_post`.
    See dashboard/src/lib/ingest.ts for the event types understood today."""
    _post(
        {"schemaVersion": 1, "emittedAt": _now_iso(), "type": event_type, "payload": payload},
        path="/api/ingest",
    )


def start_run(
    skill: str, *, input_summary: Optional[str] = None, run_id: Optional[str] = None
) -> str:
    """Log the start of a skill run. Returns a run id to pass to `finish_run`."""
    event_id = str(uuid.uuid4())
    _post(
        {
            "id": event_id,
            "skill": skill,
            "startedAt": _now_iso(),
            "status": "running",
            "inputSummary": input_summary,
            "runId": run_id,
        }
    )
    return event_id


def finish_run(
    run_id: str,
    skill: str,
    status: str,
    *,
    decision: Optional[str] = None,
    outcome: Optional[str] = None,
    tokens_note: Optional[str] = None,
    error_text: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    pipeline_run_id: Optional[str] = None,
) -> None:
    """Log the end of a skill run. `status` is "completed" or "failed".
    `run_id` here is the event id returned by `start_run` (kept positional
    for backward compatibility); `pipeline_run_id` optionally links this
    skill run to a parent pipeline Run row."""
    _post(
        {
            "id": run_id,
            "skill": skill,
            "finishedAt": _now_iso(),
            "status": status,
            "decision": decision,
            "outcome": outcome,
            "tokensNote": tokens_note,
            "errorText": error_text,
            "meta": meta,
            "runId": pipeline_run_id,
        }
    )
