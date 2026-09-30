#!/usr/bin/env python3
"""Scheduled runs for the skills the daily pipeline does not own.

    python automation/run_skill.py <skill-name>

One job per skill, registered in JOBS below. Every run:

  1. emits a skill_run event with status "running" (this is the row the
     dashboard's Skills and Activity pages read),
  2. checks its precondition - a missing input is reported as a failed run
     with the reason, never a silent no-op,
  3. calls Claude Code headless once, with stdout AND stderr captured,
  4. writes the artifact under drafts/ (gitignored - these are personal),
  5. updates the same row to completed or failed.

Exit codes: 0 = completed or reported-not-configured, 1 = failed, 2 = usage.

Cost note: one Claude call per run. The cadence lives in
install-continuous-tasks.ps1, so change it there.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / "drafts"
LOG = ROOT / "automation" / "skills.log"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "automation"))
from skill_run_event import emit_skill_run, skill_run_id  # noqa: E402
from runtime import run_hidden  # noqa: E402


class NotConfigured(Exception):
    """The input this skill needs does not exist yet. Not a crash."""


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


def claude_bin() -> str | None:
    for name in ("claude", "claude.cmd", "claude.exe"):
        try:
            r = run_hidden([name, "--version"], capture_output=True,
                               text=True, timeout=30)
            if r.returncode == 0:
                return name
        except Exception:
            continue
    return None


GUARD = """You are running the {skill} skill UNATTENDED. There is no user to answer
questions and any tool call that would ask for approval is denied, so do not
ask anything and do not try to fetch anything: work from what is given below.
If an input is missing, say in the output what you could not do - never fill
the gap with an invented fact.

Never invent a number, date, name, client, metric or build history.

Read references/voice-profile.md and references/story-bank.md first when
either says "filled: yes" and write in that voice.

Output the deliverable and NOTHING before it. No preamble, no "Final output:",
no character count, no commentary about your own draft. The first character of
your output is the first character of the deliverable.

"""


def _is_filled(path: Path) -> bool:
    """Personal templates carry a `filled: no/yes` status line."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        s = line.strip().lstrip("-*").strip().lower()
        if s.startswith("filled:"):
            return "yes" in s.split(":", 1)[1]
    return True  # no status line: presence counts


def _latest_draft() -> Path | None:
    """Most recent daily draft (YYYY-MM-DD.md), ignoring the other artifacts."""
    import re
    daily = [p for p in DRAFTS.glob("*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", p.name)]
    return max(daily, key=lambda p: p.stat().st_mtime) if daily else None


def _week_tag() -> str:
    iso = datetime.now().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _month_tag() -> str:
    return datetime.now().strftime("%Y-%m")


# --------------------------------------------------------------------------
# prompts


def prepare_planner() -> dict:
    prompt = GUARD.format(skill="linkedin-content-planner") + """\
Use the linkedin-content-planner skill to write next week's 7-day content plan
as markdown.

Audience: founders and technical leads who might hire me for SaaS, AI
integration or real-time builds.

Theme: trends in freelancing and contract software work in my industry - what
clients pay for, AI tooling versus hourly billing, retainers versus projects,
pricing pressure, niching down, finding clients, what agencies get wrong. At
most one day of the week may be a shipped-work post, and only from
references/evidence-log.md.

Use the skill's default pillar mix and posting days, 3-5 posts, no hook
formula twice inside the week, and the engagement goals spread across the
days. Every posting day gets 3-5 comment targets (named archetypes) with the
comment pattern to use.

Deliverable: the skill's markdown plan - the 7-day calendar table, the daily
comment targets, and the weekly inbound-readiness check.
"""
    return {"prompt": prompt, "artifact": DRAFTS / f"plan-{_week_tag()}.md",
            "input_summary": "next week's 7-day content plan"}


def prepare_repurposer() -> dict:
    src = _latest_draft()
    if not src:
        raise NotConfigured("no daily draft in drafts/ yet - there is nothing to repurpose")
    text = src.read_text(encoding="utf-8", errors="replace")
    text = "\n".join(l for l in text.splitlines() if not l.startswith("# Draft"))
    prompt = GUARD.format(skill="linkedin-repurposer") + """\
Use the linkedin-repurposer skill on the source post below: my own LinkedIn
post, already published this week. Goal: saves.

Produce ONE new LinkedIn post of 900-1300 characters that carries the same
idea to a different angle and a different hook formula from
references/hook-formulas.md. It must not be a repost, a paraphrase, or the
source cut shorter - someone who read the original should not recognise it as
the same post.

Draft only: stop before the skill's publish step and do NOT call lib.publish.
Approval is a separate, human step.

Then a line containing ---, then exactly two lines:
FORMULA: <id and name>
SOURCE: <the source draft file name>

SOURCE POST ({name}):
{text}""".format(name=src.name, text=text.strip())
    return {"prompt": prompt, "artifact": DRAFTS / f"repurpose-{datetime.now():%Y-%m-%d}.md",
            "input_summary": f"repurposed from {src.name}"}


HOOK_KEYWORDS = (
    "freelance developer",
    "AI engineer",
    "SaaS founder",
)


def prepare_hook_extractor() -> dict:
    if not os.getenv("APIFY_TOKEN"):
        raise NotConfigured("APIFY_TOKEN is not set - the niche posts cannot be fetched")
    try:
        sys.path.insert(0, str(ROOT))
        from lib import ApifyClient  # type: ignore
        client = ApifyClient()
        posts: list[dict] = []
        for kw in HOOK_KEYWORDS:
            try:
                posts.extend(client.search_posts(keyword=kw, limit=6))
            except Exception as e:
                log(f"  search failed for {kw!r} ({type(e).__name__}: {e}) - continuing")
    except Exception as e:
        raise NotConfigured(f"Apify search unavailable ({type(e).__name__}: {e})")
    if not posts:
        raise NotConfigured("Apify returned no posts for the niche keywords")
    import json
    payload = json.dumps(posts, ensure_ascii=False)[:9000]
    prompt = GUARD.format(skill="linkedin-hook-extractor") + """\
Use the linkedin-hook-extractor skill on the posts below. They were fetched by
the runner already - do NOT call lib.ApifyClient and do NOT fetch anything;
the post text is in the data.

For each of the strongest 3 (pick by engagement signals in the data), output:

## <post #n>
- Formula: F<id> <name> (confidence: high/medium/low)
- Hook line: <first line of the post>
- Why it worked: <1-2 lines>
- Template: <the formula's {{slot}} skeleton with an angle from my own industry slotted in>

Then close with a section "What I copy this week" - three concrete moves I can
use in next week's posts.

POSTS:
{payload}""".format(payload=payload)
    return {"prompt": prompt, "artifact": DRAFTS / f"hooks-{_week_tag()}.md",
            "input_summary": f"{len(posts)} niche posts fetched via Apify"}


def prepare_profile_optimizer() -> dict:
    path = ROOT / "references" / "profile-snapshot.md"
    if not _is_filled(path):
        raise NotConfigured("references/profile-snapshot.md is not filled in - paste your profile there once")
    prompt = GUARD.format(skill="linkedin-profile-optimizer") + """\
Use the linkedin-profile-optimizer skill on my LinkedIn profile snapshot below.

Goal: win freelance clients for SaaS, AI integration and real-time builds.
Audience: founders and technical leads.

Deliverable: the skill's markdown output - the 9-section scorecard, the
ranked priority fixes, the Before -> After rewrites, and the expected uplift.
Do not ask for missing sections: score them "missing" in the scorecard.

PROFILE SNAPSHOT:
{text}""".format(text=path.read_text(encoding="utf-8", errors="replace").strip())
    return {"prompt": prompt, "artifact": DRAFTS / f"profile-audit-{_month_tag()}.md",
            "input_summary": "profile snapshot audit"}


def prepare_interviewer() -> dict:
    bank = ROOT / "references" / "story-bank.md"
    bank_text = bank.read_text(encoding="utf-8", errors="replace") if bank.is_file() else "(no story bank)"
    prompt = GUARD.format(skill="linkedin-interviewer") + """\
Use the linkedin-interviewer skill, but there is no user present: you cannot
ask me anything, and you must never invent an answer or write one into the
story bank. This is interview PREP - the questions, not the answers.

Task: read my story bank below, find its thinnest sections (a section is thin
when it says "filled: no" or holds only a placeholder), and write the
questions I should answer in our next session. Use
skills/linkedin-interviewer/references/question-bank.md for the question
phrasing where it fits.

Deliverable, and nothing else:
THIN SECTIONS: <comma-separated section names>
<then 10-16 numbered questions grouped by section; each must be concrete
enough that my answer becomes a usable detail - a number, a date, a name, a
moment. Never ask two questions in one line.>
End with the line: Answer these with linkedin-interviewer --mode bank

Do NOT write references/story-bank.md. Do not answer anything yourself.

STORY BANK:
{bank}""".format(bank=bank_text.strip())
    return {"prompt": prompt, "artifact": DRAFTS / f"interview-questions-{_week_tag()}.md",
            "input_summary": "interview questions for the thin story-bank sections"}


def prepare_advocacy() -> dict:
    path = ROOT / "references" / "team.md"
    if not _is_filled(path):
        raise NotConfigured("references/team.md is not filled in - no team roster configured")
    prompt = GUARD.format(skill="linkedin-employee-advocacy") + """\
Use the linkedin-employee-advocacy skill with the team inputs below.

Deliverable: the skill's markdown consult - the 14-day launch plan, the
operating model, the per-member cadence targets, the KPI dashboard spec and
the governance playbook. This is a planning document only: nothing publishes
and no one is contacted.

TEAM INPUTS:
{text}""".format(text=path.read_text(encoding="utf-8", errors="replace").strip())
    return {"prompt": prompt, "artifact": DRAFTS / f"advocacy-{_month_tag()}.md",
            "input_summary": "team advocacy plan"}


JOBS = {
    "linkedin-content-planner": prepare_planner,
    "linkedin-repurposer": prepare_repurposer,
    "linkedin-hook-extractor": prepare_hook_extractor,
    "linkedin-profile-optimizer": prepare_profile_optimizer,
    "linkedin-interviewer": prepare_interviewer,
    "linkedin-employee-advocacy": prepare_advocacy,
}


def main() -> int:
    load_env()
    DRAFTS.mkdir(parents=True, exist_ok=True)

    skill = sys.argv[1] if len(sys.argv) > 1 else ""
    prepare = JOBS.get(skill)
    if prepare is None:
        print(f"usage: python automation/run_skill.py <{'|'.join(sorted(JOBS))}>")
        return 2

    started = datetime.now().astimezone().isoformat()
    rid = skill_run_id(skill)
    log(f"=== {skill} ===")
    emit_skill_run(skill, "running", run_id=rid, started_at=started)

    def finish(status: str, **kw) -> None:
        emit_skill_run(skill, status, run_id=rid, started_at=started,
                       finished_at=datetime.now().astimezone().isoformat(), **kw)

    try:
        job = prepare()
    except NotConfigured as e:
        log(f"  not configured: {e}")
        finish("failed", error_text=f"not configured: {e}")
        return 0

    cb = claude_bin()
    if not cb:
        log("  FAILED: Claude Code CLI not found on PATH")
        finish("failed", error_text="claude CLI not found on PATH")
        return 1

    log(f"  input: {job['input_summary']}")
    try:
        r = run_hidden([cb, "-p", job["prompt"]], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=ROOT, timeout=900)
    except subprocess.TimeoutExpired:
        log("  FAILED: Claude Code call timed out after 900s")
        finish("failed", error_text="claude call timed out after 900s")
        return 1

    if r.returncode != 0:
        # The CLI prints quota and auth errors on stdout, which is why every
        # other script logged the useless string "no output".
        msg = (r.stderr or r.stdout or "no output").strip()[:300]
        log(f"  FAILED: claude exited {r.returncode}: {msg}")
        finish("failed", error_text=f"claude exited {r.returncode}: {msg}")
        return 1

    out = r.stdout.strip()
    if len(out) < 200:
        log(f"  FAILED: output is only {len(out)} chars - not a deliverable")
        finish("failed", error_text=f"output too short ({len(out)} chars)")
        return 1

    job["artifact"].parent.mkdir(parents=True, exist_ok=True)
    job["artifact"].write_text(
        f"# {skill} - {datetime.now():%Y-%m-%d}\n\n{out}\n", encoding="utf-8")
    log(f"  saved {job['artifact'].name} ({len(out)} chars)")
    finish("completed", input_summary=job["input_summary"],
           decision=job["artifact"].name, outcome="completed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
