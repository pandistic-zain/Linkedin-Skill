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
  approve_reply     - post an approved reply via PubloraClient.create_comment
  reject_reply      - no-op here; already recorded on the dashboard
  regenerate_reply  - re-run the drafting skill for one thread/lead and
                      write the new draft back via a reply_redrafted event

Run manually (`python automation/dashboard_executor.py`) or on a
schedule (e.g. every 5 minutes) alongside the daily task. Safe to run
when DASHBOARD_EVENTS_URL/EVENTS_INGEST_SECRET are unset - it just
finds nothing to do and exits 0.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from runtime import run_hidden, run_command, single_instance
from run_lead_finder import LEAD_COMMENT_GUIDANCE

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "automation" / "executor.log"


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


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


def ingest(event_type: str, payload: dict) -> None:
    """POSTs one versioned envelope event to /api/ingest — same endpoint and
    secret run_engagement.py/run_lead_finder.py use to create drafts; this is
    how the executor writes a regenerated draft back onto its ReplyDraft row."""
    base = os.environ["DASHBOARD_EVENTS_URL"].rstrip("/")
    secret = os.environ["EVENTS_INGEST_SECRET"]
    body = {
        "schemaVersion": 1,
        "emittedAt": datetime.now().astimezone().isoformat(),
        "type": event_type,
        "payload": payload,
    }
    req = urllib.request.Request(
        base + "/api/ingest",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def claude_bin() -> str | None:
    for name in ("claude", "claude.cmd", "claude.exe"):
        try:
            r = run_hidden([name, "--version"], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return name
        except Exception:
            continue
    return None


def complete(command_id: str, status: str, result: str) -> None:
    try:
        api("/api/commands", method="POST", body={"id": command_id, "status": status, "resultText": result[:2000]})
    except (HTTPError, URLError, OSError) as e:
        log(f"  WARNING: could not report completion for {command_id}: {e}")


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

    # run_daily.py's own AUTOPUBLISH path emits this via its pipeline runId
    # so the draft shows up on /published and later feeds engager-analytics.
    # A dashboard-approved publish has no pipeline Run - only the Command's
    # draftId - so emit the same event keyed on that instead (ingest.ts
    # accepts either). Without this, a manually-approved post never gets a
    # Post row at all: invisible to /published and to any engager sync.
    from lib.skill_run_logger import emit  # type: ignore

    post_group_id = res.get("postGroupId") if isinstance(res, dict) else None
    if not post_group_id or res.get("success") is False:
        return "failed", "provider did not confirm scheduling; reconcile before retrying"
    status = res.get("status") or "scheduled"
    if status not in {"scheduled", "published"}:
        return "failed", f"provider status {status}; reconcile before retrying"
    emit("publish_result", {
        "draftId": payload.get("draftId"),
        "postGroupId": post_group_id,
        "status": status,
        "scheduledFor": res.get("scheduledTime") or when,
        "publishedAt": datetime.now(timezone.utc).isoformat() if status == "published" else None,
        "providerRaw": res if isinstance(res, dict) else None,
    })

    return "done", f"{status}: {post_group_id}"


def run_approve_reply(payload: dict) -> tuple[str, str]:
    """Posts an approved reply. Needs postUrn (not just the human-facing
    postUrl) — run_engagement.py resolves and stores it at draft time so
    the executor never has to re-resolve a URL to a URN itself."""
    post_urn = payload.get("postUrn")
    draft_text = payload.get("draftText")
    if not post_urn or not draft_text:
        return "failed", "missing postUrn or draftText in command payload"

    sys.path.insert(0, str(ROOT))
    from lib import PubloraClient  # type: ignore

    client = PubloraClient()
    res = client.create_comment(
        post_urn=post_urn,
        message=draft_text,
        platform_id=os.environ["LINKEDIN_PLATFORM_ID"],
        parent_comment=payload.get("parentComment"),
    )
    return "done", f"reply posted: {str(res)[:200]}"


REDRAFT_BLOCK = re.compile(r"---REDRAFT---\s*(.*?)\s*---END---", re.DOTALL)
REDRAFT_FIELD = re.compile(r"^(POST_TEXT|DRAFT):\s*(.*)$")

REDRAFT_REPLY_PROMPT = """Redraft ONE reply for this specific LinkedIn thread, using the \
linkedin-reply-handler skill's voice/humanizer rules (150-300 chars). Do NOT post anything - \
draft-only, output only.

Thread context (already resolved, do not re-search for the thread itself):
POST_URL: {post_url}
COMMENT_AUTHOR: {comment_author}
COMMENT_TEXT: {comment_text}
REASON: {reason}
PREVIOUS_DRAFT (write a different, better version - do not repeat it): {previous_draft}

Fetch the original post's own text via the skill's normal fetch step, then output EXACTLY this \
block, with no commentary before, between, or after it:

---REDRAFT---
POST_TEXT: <the original post's text, one paragraph, no line breaks>
DRAFT: <the new reply text, single line, no line breaks>
---END---

If you cannot produce a redraft (e.g. Apify unavailable), output exactly: NO_ACTION
"""

REDRAFT_LEAD_PROMPT = """Redraft ONE outreach comment for this specific LinkedIn post, using the \
linkedin-comment-drafter skill's steps and voice rules (350-600 chars for this lead), written as a senior \
fullstack/AI engineer proposing help with their specific project.

{lead_comment_guidance}

Post context (already resolved, do not re-search):
POST_URL: {post_url}
REASON: {reason}
PREVIOUS_DRAFT (write a different, better version - do not repeat it): {previous_draft}

Fetch the original post's own text via the skill's normal fetch step, then output EXACTLY this \
block, with no commentary before, between, or after it:

---REDRAFT---
POST_TEXT: <the original post's text, one paragraph, no line breaks>
DRAFT: <the new comment text, single line, no line breaks>
---END---

If you cannot produce a redraft, output exactly: NO_ACTION
"""


def run_regenerate_reply(payload: dict) -> tuple[str, str]:
    """Re-runs the drafting skill for one existing ReplyDraft row and writes
    the result back via reply_redrafted — keyed on the row's id, so it always
    updates in place instead of creating a duplicate (lead drafts have no
    commentUrl for reply_drafted's own upsert to key off)."""
    draft_id = payload.get("replyDraftId")
    post_url = payload.get("postUrl")
    if not draft_id or not post_url:
        return "failed", "missing replyDraftId or postUrl in command payload"

    cb = claude_bin()
    if not cb:
        return "failed", "claude CLI not found on PATH"

    reason = payload.get("reasonNote") or ""
    is_lead = reason.startswith("LEAD:")
    template = REDRAFT_LEAD_PROMPT if is_lead else REDRAFT_REPLY_PROMPT
    prompt = template.format(
        post_url=post_url,
        comment_author=payload.get("commentAuthor") or "unknown",
        comment_text=payload.get("commentText") or "",
        reason=reason or "none given",
        previous_draft=payload.get("previousDraft") or "",
        lead_comment_guidance=LEAD_COMMENT_GUIDANCE,
    )

    r = run_command([cb, "-p", prompt], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, timeout=900)
    if r.returncode != 0:
        reason_text = (r.stderr or r.stdout or "no output").strip()
        return "failed", f"claude exited {r.returncode}: {reason_text[:400]}"

    out = r.stdout.strip()
    if "NO_ACTION" in out and "---REDRAFT---" not in out:
        return "failed", "skill could not produce a redraft (NO_ACTION)"

    match = REDRAFT_BLOCK.search(out)
    if not match:
        return "failed", "output had no parseable redraft block"

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        m = REDRAFT_FIELD.match(line.strip())
        if m:
            fields[m.group(1)] = m.group(2).strip()

    if not fields.get("DRAFT"):
        return "failed", "redraft block had no DRAFT field"

    ingest("reply_redrafted", {
        "draftId": draft_id,
        "draftText": fields["DRAFT"],
        "postText": fields.get("POST_TEXT"),
    })
    return "done", "new draft written"


def run_now(payload: dict) -> tuple[str, str]:
    r = run_command(
        [sys.executable, str(ROOT / "automation" / "run_daily.py")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2400,
    )
    if r.returncode == 0:
        return "done", "run_daily.py completed"
    return "failed", f"run_daily.py exit {r.returncode}: {(r.stderr or r.stdout).strip()[:500]}"


HANDLERS = {
    "approve_publish": run_approve_publish,
    "run_now": run_now,
    "approve_reply": run_approve_reply,
    "regenerate_reply": run_regenerate_reply,
    "reject": lambda payload: ("done", "no local action needed — recorded on the dashboard"),
    "reject_reply": lambda payload: ("done", "no local action needed — recorded on the dashboard"),
}


def main() -> int:
    with single_instance(ROOT / "automation" / ".executor.lock") as acquired:
        if not acquired:
            log("executor already running - skipping concurrent invocation")
            return 0
        return _main()


def _main() -> int:
    load_env()
    if not os.getenv("DASHBOARD_EVENTS_URL") or not os.getenv("EVENTS_INGEST_SECRET"):
        log("DASHBOARD_EVENTS_URL/EVENTS_INGEST_SECRET not set — nothing to poll.")
        return 0

    try:
        result = api("/api/commands")
    except (HTTPError, URLError, OSError) as e:
        log(f"poll failed: {e}")
        return 1

    commands = result.get("commands", [])
    if not commands:
        return 0

    for cmd in commands:
        log(f"executing {cmd['type']} ({cmd['id']})")
        handler = HANDLERS.get(cmd["type"])
        if not handler:
            complete(cmd["id"], "failed", f"unknown command type {cmd['type']}")
            log(f"  failed: unknown command type {cmd['type']}")
            continue
        try:
            status, message = handler(cmd.get("payload") or {})
        except Exception as e:
            status, message = "failed", f"{type(e).__name__}: {e}"
        log(f"  {status}: {message}")
        complete(cmd["id"], status, message)

    return 0


if __name__ == "__main__":
    sys.exit(main())
