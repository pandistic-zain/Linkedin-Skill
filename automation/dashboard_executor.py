#!/usr/bin/env python3
"""Polls the dashboard's Command queue and executes approved actions.

The dashboard (Vercel) never holds publish credentials — approving or
rejecting a draft in the UI only writes a Command row. This script,
run on the same machine as automation/run_daily.py (same .env, same
Publora key), claims pending commands and actually executes them:

  approve_publish - publish the draft's saved content via lib.publish
  reject          - no-op here; the reject is already recorded as a
                    DraftAction by the dashboard itself
  run_now         - run automation/run_daily.py immediately

Run manually (`python automation/dashboard_executor.py`) or on a
schedule (e.g. every 5 minutes) alongside the daily task. Safe to run
when DASHBOARD_EVENTS_URL/EVENTS_INGEST_SECRET are unset - it just
finds nothing to do and exits 0.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    f = ROOT / ".env"
    if not f.is_file():
        return
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    base = os.environ["DASHBOARD_EVENTS_URL"].rstrip("/")
    secret = os.environ["EVENTS_INGEST_SECRET"]
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def complete(command_id: str, status: str, result: str) -> None:
    try:
        api("/api/commands", method="POST", body={"id": command_id, "status": status, "resultText": result[:2000]})
    except (HTTPError, URLError, OSError) as e:
        print(f"  WARNING: could not report completion for {command_id}: {e}")


def run_approve_publish(payload: dict) -> tuple[str, str]:
    """Publishes the draft's saved content. Reuses run_daily.py's guard
    helpers so a malformed draft never reaches Publora."""
    content_md = payload.get("contentMd")
    if not content_md or not content_md.strip():
        return "failed", "no draft content in command payload"

    spec = importlib.util.spec_from_file_location("rd", ROOT / "automation" / "run_daily.py")
    rd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rd)

    body = rd._strip_preamble(content_md.strip())
    problem = rd._looks_like_commentary(body)
    if problem:
        return "failed", f"refused to publish: {problem}"

    sys.path.insert(0, str(ROOT))
    from lib import publish  # type: ignore

    when = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = publish(
        kind="post",
        draft_text=body,
        target_url="https://www.linkedin.com/post/new/",
        platforms=[os.environ["LINKEDIN_PLATFORM_ID"]],
        scheduled_time=when,
    )
    return "done", f"published: {str(res)[:200]}"


def run_now(payload: dict) -> tuple[str, str]:
    r = subprocess.run(
        [sys.executable, str(ROOT / "automation" / "run_daily.py")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    if r.returncode == 0:
        return "done", "run_daily.py completed"
    return "failed", f"run_daily.py exit {r.returncode}: {(r.stderr or r.stdout).strip()[:500]}"


HANDLERS = {
    "approve_publish": run_approve_publish,
    "run_now": run_now,
    "reject": lambda payload: ("done", "no local action needed — recorded on the dashboard"),
}


def main() -> int:
    load_env()
    if not os.getenv("DASHBOARD_EVENTS_URL") or not os.getenv("EVENTS_INGEST_SECRET"):
        print("DASHBOARD_EVENTS_URL/EVENTS_INGEST_SECRET not set — nothing to poll.")
        return 0

    try:
        result = api("/api/commands")
    except (HTTPError, URLError, OSError) as e:
        print(f"poll failed: {e}")
        return 1

    commands = result.get("commands", [])
    if not commands:
        print("no pending commands")
        return 0

    for cmd in commands:
        print(f"executing {cmd['type']} ({cmd['id']})")
        handler = HANDLERS.get(cmd["type"])
        if not handler:
            complete(cmd["id"], "failed", f"unknown command type {cmd['type']}")
            continue
        try:
            status, message = handler(cmd.get("payload") or {})
        except Exception as e:
            status, message = "failed", f"{type(e).__name__}: {e}"
        print(f"  {status}: {message}")
        complete(cmd["id"], status, message)

    return 0


if __name__ == "__main__":
    sys.exit(main())
