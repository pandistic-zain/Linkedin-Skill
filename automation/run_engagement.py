#!/usr/bin/env python3
"""Periodic engagement check. Run by Windows Task Scheduler every few
hours, separately from the once-daily run_daily.py.

  1. use linkedin-thread-monitor to find hot/warm threads (author replied
     to one of your comments within the last 72h)
  2. for each, use linkedin-reply-handler to draft ONE reply — never posts
  3. push each draft to the dashboard's Reply Queue (/replies) for a
     human approve/reject; POST /api/commands (approve_reply) is what
     actually posts it, via dashboard_executor.py

Unlike linkedin-post-writer (one planned post/day, already reviewed by
the evidence-sourcing + self-check steps before AUTOPUBLISH), replies
target threads and people this pipeline has never seen before — so
this always drafts-only, regardless of AUTOPUBLISH.

Safe to run with nothing configured: exits 0 if DASHBOARD_EVENTS_URL/
EVENTS_INGEST_SECRET are unset, same as run_daily.py's dashboard ping.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "automation" / "engagement.log"


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


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def emit_reply_drafted(fields: dict) -> None:
    url = os.getenv("DASHBOARD_EVENTS_URL")
    secret = os.getenv("EVENTS_INGEST_SECRET")
    if not url or not secret:
        return
    payload = {
        "schemaVersion": 1,
        "emittedAt": datetime.now().astimezone().isoformat(),
        "type": "reply_drafted",
        "payload": {
            "postUrl": fields.get("POST_URL"),
            "postUrn": fields.get("POST_URN"),
            "commentUrl": fields.get("COMMENT_URL"),
            "parentComment": fields.get("PARENT_COMMENT"),
            "commentAuthor": fields.get("AUTHOR"),
            "reasonNote": fields.get("REASON"),
            "draftText": fields.get("DRAFT"),
        },
    }
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/api/ingest",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except (URLError, OSError) as e:
        log(f"  dashboard ping failed ({type(e).__name__}) - continuing")


def claude_bin() -> str | None:
    for name in ("claude", "claude.cmd", "claude.exe"):
        try:
            r = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return name
        except Exception:
            continue
    return None


PROMPT_TEMPLATE = """Use the linkedin-thread-monitor skill to check comments posted by {handle} \
in the last 72 hours. Classify each thread hot/warm/cool/dormant per the skill's own timing rules.

For every thread classified hot or warm ONLY, use the linkedin-reply-handler skill to draft ONE \
reply (150-300 chars, following its voice/humanizer rules). Do NOT post anything — draft-only, \
output only. Never fabricate a thread, comment, or reply — if Apify/APIFY_TOKEN is unavailable \
or returns nothing, output NO_ACTION.

For each drafted reply, output EXACTLY this block (repeat once per reply), with no commentary \
before, between, or after the blocks:

---REPLY---
POST_URL: <the original post's URL>
POST_URN: <urn:li:activity:... or urn:li:share:... - the value you'd pass to Publora's create_comment as post_urn>
COMMENT_URL: <the parent comment's URL if you have one, else its comment_urn>
PARENT_COMMENT: <urn:li:comment:(...) - the value you'd pass as parentComment>
AUTHOR: <name of the person you are replying to>
REASON: <one line: hot/warm classification and why>
DRAFT: <the reply text, single line, no line breaks>
---END---

If there are no hot/warm threads, output exactly: NO_ACTION
"""

REPLY_BLOCK = re.compile(r"---REPLY---\s*(.*?)\s*---END---", re.DOTALL)
FIELD_LINE = re.compile(r"^(POST_URL|POST_URN|COMMENT_URL|PARENT_COMMENT|AUTHOR|REASON|DRAFT):\s*(.*)$")


def parse_replies(output: str) -> list[dict]:
    replies = []
    for block in REPLY_BLOCK.findall(output):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            m = FIELD_LINE.match(line.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
        if fields.get("POST_URL") and fields.get("DRAFT"):
            replies.append(fields)
    return replies


def main() -> int:
    load_env()
    handle = os.getenv("LINKEDIN_HANDLE")
    if not handle:
        log("LINKEDIN_HANDLE not set in .env - nothing to check. Add it (last path segment of your profile URL).")
        return 0

    cb = claude_bin()
    if not cb:
        log("FAILED: Claude Code CLI not found on PATH.")
        return 1

    log(f"=== engagement check for {handle} ===")
    prompt = PROMPT_TEMPLATE.format(handle=handle)
    r = subprocess.run([cb, "-p", prompt], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, timeout=900)
    if r.returncode != 0:
        log(f"FAILED: {(r.stderr or 'no output').strip()[:300]}")
        return 1

    out = r.stdout.strip()
    if "NO_ACTION" in out and "---REPLY---" not in out:
        log("no hot/warm threads found")
        return 0

    replies = parse_replies(out)
    if not replies:
        log("no reply blocks parsed from output - nothing to queue")
        return 0

    for fields in replies:
        log(f"  drafted reply to {fields.get('AUTHOR', 'unknown')} on {fields.get('POST_URL')}")
        emit_reply_drafted(fields)

    log(f"queued {len(replies)} reply draft(s) for approval on the dashboard")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
