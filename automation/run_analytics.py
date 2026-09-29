#!/usr/bin/env python3
"""Weekly engager-analytics report. Run by Windows Task Scheduler once a week.

  1. list posts Publora reports as published in the last 7 days
     (PubloraClient.list_posts) - has postGroupId + content, but never a
     live LinkedIn URL (verified: Publora's API doesn't return one)
  2. fetch the account's own recent posts via ApifyClient.fetch_profile_posts
     (LINKEDIN_HANDLE) - has the real URL/URN, but no postGroupId
  3. headless Claude pass #1: match each Publora post to its live URL by
     content/timing only - no live paid calls in this pass
  4. fetch engagers for each matched post here in plain Python
     (ApifyClient.fetch_post_engagers) - NOT inside a headless Claude call: a
     brand-new live/paid tool call made by the model itself, with no human
     attached to answer the confirmation it (correctly) asks for, just hangs
     in headless mode - confirmed by testing on this exact call
  5. headless Claude pass #2: use linkedin-engager-analytics (its steps and
     activity logging) to segment the pre-fetched engagers by ICP tier and
     produce the roster/action-list report - again, no live paid calls
  6. emit engagers_synced per matched post (keyed on postGroupId, so it
     lands on the same Post row /published already shows) and save the
     human-readable tiered report to drafts/analytics-YYYY-MM-DD.md

Read-only: never drafts or publishes anything.

Every run reports itself as a skill_run event for
linkedin-engager-analytics, which is what the dashboard's Skills and
Activity pages read; a missing APIFY_TOKEN/LINKEDIN_HANDLE shows up as
a failed (not configured) run instead of a silent no-op.

Safe to run with nothing configured: exits 0 if APIFY_TOKEN or
LINKEDIN_HANDLE are unset.
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
DRAFTS = ROOT / "drafts"
LOG = ROOT / "automation" / "analytics.log"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_run_event import finish_skill_run, skill_run_id  # noqa: E402
from runtime import run_command  # noqa: E402


def report(status: str, run_id: str, started: str, **fields) -> None:
    """One skill_run event per scheduled run - this is what the dashboard's
    Skills and Activity pages read instead of linkedin-engager-analytics
    showing IDLE forever."""
    finish_skill_run("linkedin-engager-analytics", status, run_id=run_id,
                     started_at=started, **fields)


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


def emit(event_type: str, payload: dict) -> bool:
    url = os.getenv("DASHBOARD_EVENTS_URL")
    secret = os.getenv("EVENTS_INGEST_SECRET")
    if not url or not secret:
        return False
    body = {
        "schemaVersion": 1,
        "emittedAt": datetime.now().astimezone().isoformat(),
        "type": event_type,
        "payload": payload,
    }
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/api/ingest",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except (URLError, OSError) as e:
        log(f"  dashboard ping failed ({type(e).__name__}) - continuing")
        return False


def claude_bin() -> str | None:
    for name in ("claude", "claude.cmd", "claude.exe"):
        try:
            r = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return name
        except Exception:
            continue
    return None


def run_claude(cb: str, prompt: str) -> tuple[str | None, str | None]:
    """(output, error) - exactly one is set. Quota and auth failures are
    printed on stdout, which is why reading only stderr used to log the
    useless string "empty output"."""
    r = run_command([cb, "-p", prompt], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, timeout=900)
    if r.returncode != 0 or not r.stdout.strip():
        reason = (r.stderr or r.stdout or "empty output").strip()
        log(f"FAILED: claude exited {r.returncode}: {reason[:300]}")
        return None, f"claude exited {r.returncode}: {reason[:400]}"
    return r.stdout.strip(), None


# ---- Pass 1: match Publora's published posts to their live URL ------------

MATCH_PROMPT = """Two lists of my own recent LinkedIn activity, both already fetched - do not \
re-fetch either, just match:

PUBLORA (published in the last 7 days - has postGroupId + content, no live URL):
{publora_json}

MY OWN RECENT POSTS FROM APIFY (real url/urn/text/date, no postGroupId):
{apify_json}

Match each Publora entry to its Apify post by content overlap and timing (within ~48h of \
scheduledTime/publishedAt). Skip any Publora entry you cannot match with confidence - never guess.

For each confident match, output EXACTLY this block (repeat once per match), with no commentary \
before, between, or after the blocks:

---MATCH---
POST_GROUP_ID: <the Publora postGroupId>
POST_URL: <the matched Apify post's url>
POST_URN: <the matched Apify post's urn, or its activity_id if that's what's present>
---END---

If nothing from Publora's list matches anything in the Apify list, output exactly: NO_MATCH
"""

MATCH_BLOCK = re.compile(r"---MATCH---\s*(.*?)\s*---END---", re.DOTALL)
MATCH_FIELD_LINE = re.compile(r"^(POST_GROUP_ID|POST_URL|POST_URN):\s*(.*)$")


def parse_matches(output: str) -> list[dict]:
    matches = []
    for block in MATCH_BLOCK.findall(output):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            m = MATCH_FIELD_LINE.match(line.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
        if fields.get("POST_GROUP_ID") and fields.get("POST_URL"):
            matches.append(fields)
    return matches


# ---- Pass 2: tier/report on pre-fetched engagers ---------------------------

REPORT_PROMPT = """Pre-fetched engagers for {n} of my own recent posts (already fetched via \
lib.ApifyClient.fetch_post_engagers - do not re-fetch, just analyze):

{engagers_json}

Use the linkedin-engager-analytics skill (its steps and activity logging - just not its own fetch \
step, the raw engager records are already in the data above) on each post: segment engagers by ICP \
tier (peer / aspirational / prospect / other) and produce the roster/tier breakdown/action lists per \
the skill.

Output, in order:
1. The full engager-analytics report for each post (roster, tiers, action lists), headed with the \
   post's postGroupId and URL.
2. Then, for each post, EXACTLY this block (repeat once per post), with no commentary before, \
   between, or after the blocks - reusing the same engager records already given above, now with a \
   `type` field assigned per record ("reaction"|"comment"|"reshare") and any headline/company you \
   parsed out:

---SYNC---
POST_GROUP_ID: <the postGroupId, matching the input above>
ENGAGERS: <a JSON array, one object per engager, each with keys name, headline, company, profileUrl, type - single line, no line breaks>
---END---
"""

SYNC_BLOCK = re.compile(r"---SYNC---\s*(.*?)\s*---END---", re.DOTALL)
SYNC_FIELD_LINE = re.compile(r"^(POST_GROUP_ID|ENGAGERS):\s*(.*)$")


def parse_syncs(output: str) -> list[dict]:
    syncs = []
    for block in SYNC_BLOCK.findall(output):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            m = SYNC_FIELD_LINE.match(line.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
        post_group_id = fields.get("POST_GROUP_ID")
        engagers_raw = fields.get("ENGAGERS")
        if not post_group_id or not engagers_raw:
            continue
        try:
            engagers = json.loads(engagers_raw)
        except json.JSONDecodeError:
            log(f"  could not parse ENGAGERS json for {post_group_id} - skipping sync")
            continue
        if isinstance(engagers, list):
            syncs.append({"postGroupId": post_group_id, "engagers": engagers})
    return syncs


def main() -> int:
    load_env()
    DRAFTS.mkdir(parents=True, exist_ok=True)
    started = datetime.now().astimezone().isoformat()
    rid = skill_run_id("linkedin-engager-analytics", stamp=True)

    handle = os.getenv("LINKEDIN_HANDLE", "").strip()
    if not handle or not os.getenv("APIFY_TOKEN"):
        missing = [n for n, v in (("LINKEDIN_HANDLE", handle), ("APIFY_TOKEN", os.getenv("APIFY_TOKEN")))
                   if not v]
        log("LINKEDIN_HANDLE or APIFY_TOKEN not set - nothing to do.")
        report("failed", rid, started, error_text=f"not configured: {', '.join(missing)} unset")
        return 0

    sys.path.insert(0, str(ROOT))
    from lib import ApifyClient, PubloraClient  # type: ignore

    today = datetime.now().strftime("%Y-%m-%d")
    log(f"=== analytics run {today} ===")
    report("running", rid, started, input_summary=f"last 7 days, handle {handle}")

    try:
        published = PubloraClient().list_posts(status="published")
    except Exception as e:
        log(f"FAILED: could not list Publora posts ({type(e).__name__}: {e})")
        report("failed", rid, started, error_text=f"Publora list_posts failed: {type(e).__name__}")
        return 1

    week_ago = datetime.now().timestamp() - 7 * 86400
    recent_published = []
    for p in published:
        ts = p.get("scheduledTime") or p.get("publishedAt") or p.get("createdAt")
        try:
            when = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() if ts else None
        except ValueError:
            when = None
        if when is None or when >= week_ago:
            recent_published.append(p)

    if not recent_published:
        log("nothing published in the last 7 days per Publora - nothing to analyze")
        report("completed", rid, started, input_summary=f"last 7 days, handle {handle}",
               outcome="nothing published in the last 7 days")
        return 0

    client = ApifyClient()
    try:
        own_posts = client.fetch_profile_posts(username=handle, limit=10)
    except Exception as e:
        log(f"FAILED: could not fetch own recent posts ({type(e).__name__}: {e})")
        report("failed", rid, started, error_text=f"fetch_profile_posts failed: {type(e).__name__}")
        return 1

    cb = claude_bin()
    if not cb:
        log("FAILED: Claude Code CLI not found on PATH.")
        report("failed", rid, started, error_text="claude CLI not found on PATH")
        return 1

    # Pass 1: match (no live paid calls in this pass).
    match_out, match_err = run_claude(cb, MATCH_PROMPT.format(
        publora_json=json.dumps(recent_published)[:8000],
        apify_json=json.dumps(own_posts)[:8000],
    ))
    if match_out is None:
        report("failed", rid, started, error_text=f"match pass: {match_err}")
        return 1
    if "NO_MATCH" in match_out and "---MATCH---" not in match_out:
        log("no confident match between Publora's published posts and Apify's recent posts")
        report("completed", rid, started, outcome="no confident post matches this week")
        return 0

    matches = parse_matches(match_out)
    if not matches:
        log("no MATCH blocks parsed - nothing to analyze this run")
        log(f"  raw output (first 800 chars): {match_out[:800]!r}")
        report("failed", rid, started, error_text="match pass produced no parseable MATCH blocks")
        return 0
    log(f"  matched {len(matches)} post(s)")

    # Fetch engagers here, in Python - the actual paid Apify call.
    engagers_by_post: dict[str, list] = {}
    for m in matches:
        try:
            raw = client.fetch_post_engagers(post_url=m["POST_URL"], max_items=50)
        except Exception as e:
            log(f"  engager fetch failed for {m['POST_GROUP_ID']} ({type(e).__name__}: {e}) - skipping")
            continue
        # Drop the account's own comments/reactions on its own post - not an
        # audience member, and syncing it would show up as a self-engager on
        # /audience. Filtered here in Python, not left to the model: the
        # first real run correctly excluded this from the tier report's text
        # but still put it in the SYNC json for that same post, proving a
        # prompt instruction alone isn't reliable enough for this.
        engagers_by_post[m["POST_GROUP_ID"]] = [
            e for e in raw
            if handle.lower() not in str((e or {}).get("profileUrl") or "").lower()
        ]

    if not engagers_by_post:
        log("matched posts but every engager fetch failed - nothing to report")
        report("failed", rid, started, error_text="every fetch_post_engagers call failed")
        return 1

    # Pass 2: tier/report on the pre-fetched data (no live paid calls in this pass either).
    report_input = [
        {"postGroupId": pgid, "postUrl": next(m["POST_URL"] for m in matches if m["POST_GROUP_ID"] == pgid),
         "engagers": engagers}
        for pgid, engagers in engagers_by_post.items()
    ]
    report_out, report_err = run_claude(cb, REPORT_PROMPT.format(
        n=len(report_input), engagers_json=json.dumps(report_input)[:12000],
    ))
    if report_out is None:
        report("failed", rid, started, error_text=f"report pass: {report_err}")
        return 1

    path = DRAFTS / f"analytics-{today}.md"
    path.write_text(f"# Engager analytics {today}\n\n{report_out}\n", encoding="utf-8")
    log(f"report saved: {path.name} ({len(report_out)} chars)")

    syncs = parse_syncs(report_out)
    # Empty fetched audiences need no model classification. Preserve that
    # distinction from a failed fetch and never accept invented post IDs.
    syncs = [s for s in syncs if s["postGroupId"] in engagers_by_post
             and engagers_by_post[s["postGroupId"]]]
    syncs.extend({"postGroupId": pgid, "engagers": []}
                 for pgid, engagers in engagers_by_post.items() if not engagers)
    for s in syncs:
        if not emit("engagers_synced", s):
            report("failed", rid, started, error_text="audience delivery failed; report saved locally")
            return 1
        log(f"  synced {len(s['engagers'])} engager(s) for postGroupId {s['postGroupId']}")

    if {s["postGroupId"] for s in syncs} != set(engagers_by_post):
        log("report generated but no parseable SYNC blocks - audience page not updated this run")
        log(f"  raw output (first 800 chars): {report_out[:800]!r}")
        report("failed", rid, started, error_text="report omitted audience sync blocks")
        return 1

    report("completed", rid, started, decision=f"{len(matches)} post(s), {len(syncs)} synced",
           outcome=f"report {path.name}, {len(syncs)} post(s) synced")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
