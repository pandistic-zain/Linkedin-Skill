#!/usr/bin/env python3
"""Freelance/client-lead discovery. Run by Windows Task Scheduler once or
twice a day, separately from run_daily.py and run_engagement.py.

  1. search LinkedIn for posts where someone is asking for freelance/contract
     fullstack or AI engineering help - done here in plain Python
     (ApifyClient.search_posts), NOT inside the headless Claude call: a
     brand-new live/paid tool call made by the model itself, with no human
     attached to answer the confirmation it (correctly) asks for, just hangs
     in headless mode - confirmed by testing. Pre-fetching in Python sidesteps
     that entirely, same as run_analytics.py already does for Publora/profile
     data.
  2. hand the raw search results to a headless Claude run: filter to genuine
     leads and draft ONE comment per candidate as a senior fullstack AI
     engineer responding to that specific need - never posts
  3. push each draft to the dashboard's Reply Queue (/replies) for a human
     approve/reject, reusing the same reply_drafted event run_engagement.py
     uses; POST /api/commands (approve_reply) is what actually posts it,
     via dashboard_executor.py - no dashboard changes needed, a lead comment
     is a top-level comment (parentComment left unset)

Capped low and draft-only on purpose: this is unsolicited outreach to
strangers' posts, and LinkedIn rate-limits/flags comment bursts from one
account (see references/algorithm-heuristics.md). A human decides which
leads are worth a comment before anything goes out.

Safe to run with nothing configured: exits 0 if DASHBOARD_EVENTS_URL/
EVENTS_INGEST_SECRET or APIFY_TOKEN are unset.
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
LOG = ROOT / "automation" / "leads.log"

#: Hard cap per run - keeps this well inside a sane daily outreach volume
#: even if the search turns up a large batch of candidates.
MAX_LEADS_PER_RUN = 4

SEARCH_KEYWORDS = (
    "looking for a freelance developer",
    "need a fullstack engineer",
    "hiring a contract developer",
    "looking for an AI engineer",
)


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
            "commentUrl": None,
            "parentComment": None,
            "commentAuthor": fields.get("AUTHOR"),
            "commentText": fields.get("SNIPPET"),
            "reasonNote": f"LEAD: {fields.get('REASON', 'candidate client post')}",
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


PROMPT_TEMPLATE = """Public LinkedIn posts already fetched via search (do not re-search, do not call \
search_posts yourself - just use this data):

{results_json}

From these results, keep ONLY posts that are genuinely someone (a founder, a company, a hiring manager - \
not a fellow freelancer or recruiter agency) asking for freelance or contract help building software, \
where the need matches: fullstack development, AI/LLM integration, or real-time systems. Skip: job board \
reposts, recruiter spam, posts older than 7 days, posts already full of "reach out" comments (10+), and \
anything where the poster is themselves offering freelance services (that's a peer, not a lead).

Read `references/story-bank.md` and `references/voice-profile.md` first (if `filled: yes`) so drafts \
sound like a real senior fullstack/AI engineer, not a template.

Keep at most {cap} candidates - the strongest fits, not everything that matched. For each, use the \
linkedin-comment-drafter skill (its steps, templates, and activity logging - just not its own fetch \
step, the post text is already in the data above) to draft ONE comment (200-350 chars) written as an \
intellectual senior fullstack AI engineer genuinely engaging with their specific problem - reference \
what they actually described needing, not a generic pitch. No hashtags, no "DM me", no mention of the \
user's own product by name. Stop the skill's own flow before its "on approval, call lib.publish" step - \
draft-only, output only, never call lib.publish here.

Never fabricate a post or a poster - if nothing in the data above qualifies, output NO_ACTION.

For each kept candidate, output EXACTLY this block (repeat once per candidate), with no commentary \
before, between, or after the blocks:

---LEAD---
POST_URL: <the post's URL>
POST_URN: <urn:li:activity:... or urn:li:share:... - whatever you'd pass to Publora's create_comment as post_urn>
AUTHOR: <name of the poster>
SNIPPET: <one line quoting or summarizing what they're asking for>
REASON: <one line: why this is a genuine lead, e.g. "founder asking for a contract React+AI dev, posted 2 days ago">
DRAFT: <the comment text, single line, no line breaks>
---END---

If nothing qualifies, output exactly: NO_ACTION
"""

LEAD_BLOCK = re.compile(r"---LEAD---\s*(.*?)\s*---END---", re.DOTALL)
FIELD_LINE = re.compile(r"^(POST_URL|POST_URN|AUTHOR|SNIPPET|REASON|DRAFT):\s*(.*)$")


def parse_leads(output: str) -> list[dict]:
    leads = []
    for block in LEAD_BLOCK.findall(output):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            m = FIELD_LINE.match(line.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
        if fields.get("POST_URL") and fields.get("DRAFT"):
            leads.append(fields)
    return leads[:MAX_LEADS_PER_RUN]


def main() -> int:
    load_env()
    if not os.getenv("APIFY_TOKEN"):
        log("APIFY_TOKEN not set - lead search needs it. Nothing to do.")
        return 0

    cb = claude_bin()
    if not cb:
        log("FAILED: Claude Code CLI not found on PATH.")
        return 1

    sys.path.insert(0, str(ROOT))
    from lib import ApifyClient  # type: ignore

    log("=== lead finder run ===")
    client = ApifyClient()
    results: list[dict] = []
    for kw in SEARCH_KEYWORDS:
        try:
            results.extend(client.search_posts(keyword=kw, limit=10))
        except Exception as e:
            log(f"  search failed for {kw!r} ({type(e).__name__}: {e}) - continuing with other keywords")

    if not results:
        log("no search results at all - nothing to do")
        return 0
    log(f"  fetched {len(results)} raw post(s) across {len(SEARCH_KEYWORDS)} keyword(s)")

    prompt = PROMPT_TEMPLATE.format(results_json=json.dumps(results)[:12000], cap=MAX_LEADS_PER_RUN)
    r = subprocess.run([cb, "-p", prompt], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, timeout=900)
    if r.returncode != 0:
        log(f"FAILED: {(r.stderr or 'no output').strip()[:300]}")
        return 1

    out = r.stdout.strip()
    if "NO_ACTION" in out and "---LEAD---" not in out:
        log("no qualifying leads found")
        return 0

    leads = parse_leads(out)
    if not leads:
        log("no lead blocks parsed from output - nothing to queue")
        log(f"  raw output (first 800 chars): {out[:800]!r}")
        return 0

    for fields in leads:
        log(f"  lead: {fields.get('AUTHOR', 'unknown')} - {fields.get('POST_URL')}")
        emit_reply_drafted(fields)

    log(f"queued {len(leads)} lead comment draft(s) for approval on the dashboard")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
