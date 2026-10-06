"""Ordered skill-run logging with durable versioned event delivery.

Zero third-party dependencies (stdlib `urllib` only) so it works at every
support tier, including Tier 0 manual users who never install `requests`.
Every call completes synchronously with a small timeout. This preserves event
order and avoids losing terminal events when a scheduled process exits.
An unavailable dashboard retains versioned events in a bounded SQLite outbox.
Legacy flat skill events remain best effort for compatibility.

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
import os
import sqlite3
import time
import uuid
import warnings
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional
from urllib import request as urllib_request
from urllib.error import URLError

from ._env import load_env

_TIMEOUT_SECONDS = 2.0
OUTBOX = Path(__file__).resolve().parents[1] / 'automation' / '.events.sqlite3'


@contextmanager
def _outbox():
    OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(OUTBOX, timeout=3)
    db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, '
               'id TEXT UNIQUE NOT NULL, destination TEXT NOT NULL, body TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS replay_lock (id INTEGER PRIMARY KEY, owner TEXT, expires REAL)')
    db.execute('INSERT OR IGNORE INTO replay_lock VALUES (1, NULL, 0)')
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def flush(limit: int = 30) -> bool:
    """Replay in order; an unknown-event 202 is not successful synchronization."""
    load_env()
    base = os.getenv('DASHBOARD_EVENTS_URL', '').rstrip('/')
    secret = os.getenv('EVENTS_INGEST_SECRET')
    if not base or not secret:
        return False
    owner = str(uuid.uuid4())
    acquired = False
    try:
        with _outbox() as db:
            acquired = db.execute('UPDATE replay_lock SET owner=?, expires=? WHERE id=1 AND expires<?',
                                  (owner, time.time() + 120, time.time())).rowcount == 1
            if not acquired:
                return False
        # Keep database writes available to other scheduled producers during HTTP.
        with _outbox() as db:
            rows = db.execute('SELECT seq, body FROM events WHERE destination=? ORDER BY seq LIMIT ?',
                              (base, min(limit, 30))).fetchall()
        deadline = time.monotonic() + 20
        for seq, body in rows:
            if time.monotonic() >= deadline:
                return False
            req = urllib_request.Request(base + '/api/ingest', data=body.encode(), method='POST',
                                         headers={'Content-Type': 'application/json',
                                                  'Authorization': 'Bearer ' + secret})
            try:
                with urllib_request.urlopen(req, timeout=_TIMEOUT_SECONDS) as response:
                    result = json.loads(response.read(65536))
                    if response.status != 200 or result.get('ok') is not True or result.get('ignored'):
                        return False
            except (URLError, OSError, ValueError):
                return False
            with _outbox() as db:
                db.execute('DELETE FROM events WHERE seq=?', (seq,))
        with _outbox() as db:
            return db.execute('SELECT count(*) FROM events WHERE destination=?', (base,)).fetchone()[0] == 0
    except sqlite3.Error:
        warnings.warn('dashboard outbox is busy or unavailable; pending events retained', RuntimeWarning)
        return False
    finally:
        if acquired:
            try:
                with _outbox() as db:
                    db.execute('UPDATE replay_lock SET owner=NULL, expires=0 WHERE owner=?', (owner,))
            except sqlite3.Error:
                warnings.warn('outbox replay lease will expire automatically', RuntimeWarning)


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
            with urllib_request.urlopen(req, timeout=_TIMEOUT_SECONDS) as response:
                response.read()
        except (URLError, OSError, ValueError):
            pass  # never let logging break the calling skill

    # Ordered, bounded delivery: draft_saved must land before publish_result,
    # and process exit must not discard the final event on a daemon thread.
    _send()


def emit(event_type: str, payload: dict[str, Any]) -> None:
    """Persist a versioned event before delivery. Disk/full-queue errors are visible.

    No-op when unconfigured. Network failures retain the event for executor replay.
    """
    load_env()
    base = os.getenv('DASHBOARD_EVENTS_URL', '').rstrip('/')
    if not base or not os.getenv('EVENTS_INGEST_SECRET'):
        return
    event_id = str(uuid.uuid4())
    body = json.dumps({'schemaVersion': 1, 'eventId': event_id, 'emittedAt': _now_iso(),
                       'type': event_type, 'payload': payload})
    with _outbox() as db:
        if db.execute('SELECT count(*) FROM events').fetchone()[0] >= 10000:
            raise RuntimeError('dashboard outbox full; repair synchronization before continuing')
        db.execute('INSERT INTO events(id,destination,body) VALUES(?,?,?)', (event_id, base, body))
    flush(limit=5)


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
