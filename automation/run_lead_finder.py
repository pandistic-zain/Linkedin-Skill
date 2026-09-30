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

Every run reports itself as a skill_run event for linkedin-comment-drafter,
which is what the dashboard's Skills and Activity pages read - a missing
APIFY_TOKEN shows up there as a failed (not configured) run instead of a
silent no-op.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_run_event import finish_skill_run, skill_run_id  # noqa: E402
from runtime import run_hidden, run_command  # noqa: E402


def report(skill: str, status: str, run_id: str, started: str, **fields) -> None:
    finish_skill_run(skill, status, run_id=run_id, started_at=started, **fields)

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


def emit_reply_drafted(fields: dict) -> bool:
    url = os.getenv("DASHBOARD_EVENTS_URL")
    secret = os.getenv("EVENTS_INGEST_SECRET")
    if not url or not secret:
        return False
    payload = {
        "schemaVersion": 1,
        "emittedAt": datetime.now().astimezone().isoformat(),
        "type": "reply_drafted",
        "payload": {
            "postUrl": fields.get("POST_URL"),
            "postUrn": fields.get("POST_URN"),
            "postText": fields.get("POST_TEXT"),
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
        return True
    except (URLError, OSError) as e:
        log(f"  dashboard ping failed ({type(e).__name__}) - continuing")
        return False


def claude_bin() -> str | None:
    for name in ("claude", "claude.cmd", "claude.exe"):
        try:
            r = run_hidden([name, "--version"], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return name
        except Exception:
            continue
    return None


LEAD_COMMENT_GUIDANCE = """For this hiring-lead comment, earn the offer through useful, project-specific analysis:
- Before drafting, identify the stated goal, a likely bottleneck or failure mode, and a practical first step. Base the analysis on the supplied post; distinguish assumptions from facts.
- Open with the problem insight, not an offer to work or a list of my skills. Explain why that issue matters for the outcome they want.
- Give a brief solution glimpse and its benefit, not the full solution, implementation sequence, architecture, code, or detailed steps. Demonstrate understanding without writing a tutorial or a vague teaser.
- Only after the problem insight and solution glimpse, naturally offer to help implement it. Adapt the offer to the project rather than opening with a sales pitch.
- Demonstrate fit through reasoning, not claims of superiority. Never claim hours of research, an audit, testing, access to their systems, or past work unless supplied evidence supports it.
- After the offer to help and immediately before the portfolio link, add one short credibility sentence about my relevant background. Use a verified role, specialty, or project from the filled voice-profile/story-bank; connect it to this lead's need rather than listing my resume. Never invent employers, years of experience, clients, metrics, or industry expertise. If no verified background is available, omit the sentence rather than fabricate it.
- Include exactly once, after the background sentence: Portfolio: https://webbyzain.online
  This portfolio link is explicitly requested by the user and overrides generic no-promotion/link guidance for lead comments only.
- Use verified experience only if supplied in the filled profile/story bank. Never invent projects, results, credentials, availability dates, or guarantees.
- Keep the entire comment, including the portfolio link, within 350-600 characters, using 3-5 concise sentences. This lead-specific range overrides the skill's generic 200-350 character limit. Do not pad sparse context; ask one precise scoping question when needed.
- No hashtags, generic praise, desperate sales language, or \"DM me\". An optional specific question must not replace the offer to help.
- Draft only; posting still requires approval."""


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
step, the post text is already in the data above) to draft ONE comment (350-600 chars) written as a \
senior fullstack AI engineer proposing help with their specific project.

{lead_comment_guidance}

Never fabricate a post or a poster - if nothing in the data above qualifies, output NO_ACTION.

For each kept candidate, output EXACTLY this block (repeat once per candidate), with no commentary \
before, between, or after the blocks:

---LEAD---
POST_URL: <the post's URL>
POST_URN: <urn:li:activity:... or urn:li:share:... - whatever you'd pass to Publora's create_comment as post_urn>
POST_TEXT: <the post's own full text from the data above, one paragraph, no line breaks>
AUTHOR: <name of the poster>
SNIPPET: <one line quoting or summarizing what they're asking for>
REASON: <one line: why this is a genuine lead, e.g. "founder asking for a contract React+AI dev, posted 2 days ago">
DRAFT: <the comment text, single line, no line breaks>
---END---

If nothing qualifies, output exactly: NO_ACTION
"""

LEAD_BLOCK = re.compile(r"---LEAD---\s*(.*?)\s*---END---", re.DOTALL)
FIELD_LINE = re.compile(r"^(POST_URL|POST_URN|POST_TEXT|AUTHOR|SNIPPET|REASON|DRAFT):\s*(.*)$")


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
    started = datetime.now().astimezone().isoformat()
    rid = skill_run_id("linkedin-comment-drafter", stamp=True)

    def done(status: str, **fields) -> None:
        report("linkedin-comment-drafter", status, rid, started, **fields)

    if not os.getenv("APIFY_TOKEN"):
        log("APIFY_TOKEN not set - lead search needs it. Nothing to do.")
        done("failed", error_text="not configured: APIFY_TOKEN is not set")
        return 0

    cb = claude_bin()
    if not cb:
        log("FAILED: Claude Code CLI not found on PATH.")
        done("failed", error_text="claude CLI not found on PATH")
        return 1

    sys.path.insert(0, str(ROOT))
    from lib import ApifyClient  # type: ignore

    log("=== lead finder run ===")
    done("running", input_summary=f"{len(SEARCH_KEYWORDS)} keyword search")
    client = ApifyClient()
    results: list[dict] = []
    for kw in SEARCH_KEYWORDS:
        try:
            results.extend(client.search_posts(keyword=kw, limit=10))
        except Exception as e:
            log(f"  search failed for {kw!r} ({type(e).__name__}: {e}) - continuing with other keywords")

    if not results:
        log("no search results at all - nothing to do")
        done("failed", error_text="Apify returned no posts for any search keyword")
        return 0
    log(f"  fetched {len(results)} raw post(s) across {len(SEARCH_KEYWORDS)} keyword(s)")

    prompt = PROMPT_TEMPLATE.format(results_json=json.dumps(results)[:12000], cap=MAX_LEADS_PER_RUN,
                                    lead_comment_guidance=LEAD_COMMENT_GUIDANCE)
    r = run_command([cb, "-p", prompt], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, timeout=900)
    if r.returncode != 0:
        # quota and auth errors arrive on stdout, not stderr
        reason = (r.stderr or r.stdout or "no output").strip()
        log(f"FAILED: claude exited {r.returncode}: {reason[:300]}")
        done("failed", input_summary=f"{len(results)} posts searched",
             error_text=f"claude exited {r.returncode}: {reason[:400]}")
        return 1

    out = r.stdout.strip()
    if "NO_ACTION" in out and "---LEAD---" not in out:
        log("no qualifying leads found")
        done("completed", input_summary=f"{len(results)} posts searched",
             outcome="no qualifying leads")
        return 0

    leads = parse_leads(out)
    if not leads:
        log("no lead blocks parsed from output - nothing to queue")
        log(f"  raw output (first 800 chars): {out[:800]!r}")
        done("failed", input_summary=f"{len(results)} posts searched",
             error_text="output had no parseable lead blocks")
        return 0

    for fields in leads:
        log(f"  lead: {fields.get('AUTHOR', 'unknown')} - {fields.get('POST_URL')}")
        if not emit_reply_drafted(fields):
            done("failed", error_text="lead delivery failed; check dashboard before retrying")
            return 1

    log(f"queued {len(leads)} lead comment draft(s) for approval on the dashboard")
    done("completed", input_summary=f"{len(results)} posts searched",
         decision=f"{len(leads)} qualifying lead(s)",
         outcome=f"{len(leads)} lead comment draft(s) queued")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
