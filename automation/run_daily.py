#!/usr/bin/env python3
"""Daily LinkedIn pipeline. Run by Windows Task Scheduler.

   1. refresh the evidence log from local + GitHub repos
   2. ask Claude Code (headless) to draft today's post using the bundle's skills
      (topic lane is picked first: mostly freelancing/industry trends, a build
      log only after 3 trend posts - see _pick_lane)
   3. save the draft to drafts/YYYY-MM-DD.md
   4. audit it with linkedin-humanizer (--mode audit), report that as its own
      skill run, and hold the post on a BLOCK verdict
   5. publish, or queue for approval, per AUTOPUBLISH
   6. report the run to the dashboard, if one is configured

Every step is logged. A failure in one step never silently becomes a no-op:
the script exits non-zero and says which step failed.
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

ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / "drafts"
LOG = ROOT / "automation" / "run.log"
TOPIC_HISTORY = ROOT / "automation" / ".topic-history.jsonl"
# What the feed gets: mostly trends, rarely a build log. A shipped-work post is
# only allowed after this many trend posts have gone out since the last one.
TREND_STREAK_BEFORE_BUILD = 3
RUN_ID = ""  # set at the top of main(); module-level default for report() calls before that

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_run_event import emit_skill_run  # noqa: E402
from runtime import run_hidden, run_command, single_instance  # noqa: E402
try:
    from lib.skill_run_logger import emit as _emit  # type: ignore
except ImportError:
    def _emit(event_type: str, payload: dict) -> None:  # type: ignore
        pass  # dashboard logging is optional; never hard-depend on it


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


def report(event: dict) -> None:
    """Best-effort dashboard ping. Never blocks the run.

    Adds "id" automatically from RUN_ID if the caller didn't set one, so
    every skill-run event upserts idempotently on a same-day rerun instead
    of being rejected by the ingest route (which requires "id")."""
    url = os.getenv("DASHBOARD_EVENTS_URL")
    secret = os.getenv("EVENTS_INGEST_SECRET")
    if not url or not secret:
        return
    event = {"id": RUN_ID, **event}
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/api/events",
            data=json.dumps(event).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {secret}"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3).read()
    except Exception as e:
        log(f"  dashboard ping failed ({type(e).__name__}) - continuing")


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


PROMPT = """Use the linkedin-post-writer skill to draft ONE LinkedIn post for today.

Read references/voice-profile.md, references/story-bank.md and
references/evidence-log.md first. Obey the hard rules in the voice profile and
the client/NDA guard in the skill.

Audience: founders and technical leads who might hire me for SaaS, AI
integration or real-time builds. Goal: comments and profile visits.
__RECENT__
__LANE__

Before you output, re-read your own draft against whatever you cited in it.
Check every date, interval and count you wrote: "four days apart" must match the
actual gap between the events you cited. A contradiction between the hook and
the body is a failure, not a style issue. Fix it before output.

Output the post body and NOTHING before it. No preamble, no "Final output:",
no character count, no commentary about your own draft. The very first character
of your output is the first character of the post. Then a line containing --- , then exactly two lines:

FORMULA: <which hook formula you used, and where the claim came from>
MOTIF: <ONE word - the geometric motif whose shape matches what THIS post argues.
Choose deliberately; this is the picture readers see beside your words.
  lattice  - a network under tension: many parts, one highlighted node.
             For posts about systems, pipelines, agents, dependencies.
  boundary - an open form on one side of a line, a sealed form on the other.
             For posts about a limit, a side, who controls what, access.
  gates    - a row of bars with one marked. For posts about checks, filters,
             sequential conditions, things that must all pass.
  split    - one whole bar above, a broken pair below. For posts about a
             separation, a break, one thing becoming two.
  orbit    - concentric rings with one node on an inner ring. For posts about
             cycles, iteration, returning to something, layers.
Pick by the post's ARGUMENT, not its vocabulary. State it as: MOTIF: gates>
WHY: <one short line: which shape maps to which idea in the post>"""


LANE_BLOCKS = {
    "trend": """TOPIC LANE FOR TODAY: trend.

Write about a TREND in freelancing and contract software work in my industry -
AI tooling changing what clients actually pay for, hourly billing versus
productized services or retainers, pricing and rate pressure, finding clients,
scope creep, niching down versus full-stack, remote delivery, what agencies and
freelancers keep getting wrong. I sell SaaS, AI integration and real-time
builds, so pick a trend I run into in that market, not a generic "the future of
work" headline.

Rules for a trend post:
- The TREND is the subject. My own work may appear as ONE short example that
  proves the point, never as the story itself.
- Take a position. A claim someone in the comments could disagree with; a
  neutral news roundup is a failed draft.
- Never invent a statistic, percentage, rate or market figure. A number comes
  from references/industry-benchmarks.md or references/hook-formulas.md, or it
  is my own observed experience explicitly framed as such ("the pattern in my
  inbox", "every proposal I sent last quarter").
- The evidence log is optional here and is not what this post is about. Any
  build claim you do make must still trace to a line in it.
- Standing aside is a last resort, not a way out of this lane: if no trend here
  is worth taking a position on, say exactly that and write no draft.""",
    "build": """TOPIC LANE FOR TODAY: build.

Pick the topic from the evidence log - something I actually shipped recently,
with a real date. Never invent a number or a build history. If the evidence log
has nothing worth a post today, say exactly that and write no draft; standing
aside is a valid outcome.""",
}


def _read_history() -> list[dict]:
    """Published posts, newest last: [{"date","lane","topic"}].

    Bootstraps once from drafts/ so the very first run already knows what has
    been said (those all count as build posts - historically everything was)."""
    entries: list[dict] = []
    if TOPIC_HISTORY.is_file():
        for line in TOPIC_HISTORY.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("date") and e.get("topic"):
                entries.append(e)
        return entries
    for f in sorted(DRAFTS.glob("*.md")):
        if f.stem.startswith("analytics"):
            continue
        lines = [ln.strip() for ln in f.read_text(encoding="utf-8",
                                                   errors="replace").splitlines()
                 if ln.strip() and not ln.startswith("#")]
        entries.append({"date": f.stem[:10], "lane": "build",
                        "topic": (lines[0][:160] if lines else f.stem)})
    return entries


def _pick_lane(history: list[dict]) -> str:
    streak = 0
    for e in reversed(history):
        if e.get("lane") == "build":
            break
        streak += 1
    return "build" if streak >= TREND_STREAK_BEFORE_BUILD else "trend"


def _record_history(today: str, lane: str, topic: str) -> None:
    TOPIC_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with TOPIC_HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"date": today, "lane": lane,
                             "topic": topic[:160]}) + "\n")


def build_prompt(lane: str, history: list[dict]) -> str:
    recent = ""
    if history:
        rows = "\n".join(f"- {e.get('date', '?')} [{e.get('lane', '?')}] {e['topic']}"
                         for e in history[-8:])
        recent = ("\nAlready published. A new post must be a DIFFERENT subject and a\n"
                  "different angle - rehashing one of these is a failed draft:\n"
                  f"{rows}\n")
    return (PROMPT.replace("__RECENT__", recent)
                  .replace("__LANE__", LANE_BLOCKS[lane]))



PREAMBLE_MARKERS = (
    "final output", "here is the post", "here's the post", "here is the draft",
    "here's the draft", "draft:", "post:", "output:",
)

# The model sometimes narrates a tool-use decision in first person ("I'll count
# characters manually instead â€” the draft is fine as-is... No need for the
# shell tool.") as a standalone line before the real post. It doesn't match
# PREAMBLE_MARKERS (no "draft:"/"output:" label), so it needs its own check:
# a first-person opener combined with the model talking ABOUT the draft/tooling
# rather than starting the post itself.
NARRATION_OPENERS = ("i'll ", "i will ", "let me ")
NARRATION_TOPICS = ("draft", "char", "tool", "count", "output", "publish")


def _strip_preamble(body: str) -> str:
    """Drop any meta-commentary the model emitted before the post itself.

    The model sometimes narrates ("Good enough length-wise (~950 chars). Final
    output:") before the draft. That text is not part of the post and must never
    reach LinkedIn. We cut everything up to and including the last line that
    looks like narration, then sanity-check what is left.
    """
    lines = body.splitlines()
    cut = 0
    for i, line in enumerate(lines[:6]):
        low = line.strip().lower()
        if not low:
            continue
        if any(m in low for m in PREAMBLE_MARKERS) or low.endswith(("output:", "draft:")):
            cut = i + 1
        elif low.startswith(NARRATION_OPENERS) and any(t in low for t in NARRATION_TOPICS):
            cut = i + 1
    cleaned = "\n".join(lines[cut:]).strip()
    return cleaned or body


def _looks_like_commentary(body: str) -> str | None:
    """Return a reason string if this does not look like a finished post."""
    first = body.strip().splitlines()[0].strip().lower() if body.strip() else ""
    if not body.strip():
        return "draft is empty"
    if any(m in first for m in PREAMBLE_MARKERS):
        return f"first line still looks like commentary: {first[:80]!r}"
    if first.startswith(("#", "```", "note:", "i'll ", "i will ", "let me ")):
        return f"first line is not post text: {first[:80]!r}"
    if len(body) < 300:
        return f"draft is only {len(body)} chars - too short to be the post"
    return None




GITHUB_RAW = "https://raw.githubusercontent.com/pandistic-zain/Linkedin-Skill/main/"


def _host_card(path: pathlib.Path) -> str | None:
    """Commit the card to the public repo and return its raw URL.

    Publora needs a URL it can fetch. The repo is public and already exists, so
    it costs nothing. Returns None if git fails - the post still goes out, just
    without the image.
    """
    rel = path.relative_to(ROOT).as_posix()
    try:
        for args in (["add", rel],
                     ["-c", "user.name=LinkedIn Pipeline",
                      "-c", "user.email=pandistic.zain@gmail.com",
                      "commit", "-m", f"card: {path.stem}", "--only", rel],
                     ["push", "origin", "HEAD"]):
            r = run_hidden(["git", *args], cwd=ROOT, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=120)
            if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
                log(f"  git {args[0]} failed: {(r.stderr or r.stdout).strip()[:160]}")
                return None
        url = GITHUB_RAW + rel
        log(f"  card hosted: {url}")
        return url
    except Exception as e:
        log(f"  hosting failed ({type(e).__name__}: {e})")
        return None


def _make_card(text: str, motif: str | None = None) -> str | None:
    """Render the branded card locally (free) and host it."""
    try:
        spec = importlib.util.spec_from_file_location("mc", ROOT / "make_card.py")
        mc = importlib.util.module_from_spec(spec); spec.loader.exec_module(mc)
        out = mc.render(text, ROOT / "media" / f"{datetime.now():%Y-%m-%d}.png", motif)
        log(f"  card rendered: {out.name} ({out.stat().st_size // 1024} KB)")
        return _host_card(out)
    except Exception as e:
        log(f"  card failed ({type(e).__name__}: {e}) - posting without it")
        return None


BRAND_STYLE = (
    "Flat geometric editorial illustration. Near-black #08080A background, "
    "off-white #F7F7F3 forms, exactly one crimson #D71920 accent, optional "
    "muted navy #123C69. Clean vector shapes, generous negative space, no "
    "gradients, no neon glow, no 3D render, no people, no lettering of any "
    "kind, no logos. Subject: "
)


def _motif(note: str) -> str | None:
    """The motif the drafting step chose for this post."""
    valid = {"lattice", "boundary", "gates", "split", "orbit"}
    for line in note.splitlines():
        line = line.strip()
        if line.upper().startswith("MOTIF:"):
            m = line.split(":", 1)[1].strip().split()[0].strip(".,").lower()
            if m in valid:
                return m
            log(f"  unknown motif {m!r} - falling back to keyword match")
    return None


def _image_brief(note: str) -> str | None:
    """Pull the IMAGE: line the drafting step emitted."""
    for line in note.splitlines():
        line = line.strip()
        if line.upper().startswith("IMAGE:"):
            brief = line.split(":", 1)[1].strip()
            if not brief or brief.lower().startswith("none"):
                return None
            return brief
    return None


def _make_image(brief: str):
    """Generate the post's illustration. Returns a url, or None on any failure -
    a missing image must never cost us the post.

    Model and resolution come from .env so quality is tunable without editing
    code. Defaults are the top tier: this image sits on a profile selling
    engineering work, and $0.24 is not the place to economise.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from lib import illustrate
        img = illustrate(
            BRAND_STYLE + brief,
            kind="wide",
            model=os.getenv("IMAGE_MODEL", "gpt-5-image"),
            resolution=os.getenv("IMAGE_RESOLUTION", "2K"),
            overlay={"text": "webbyzain.online", "position": "bottom-right",
                     "opacity": 0.55, "color": "#F7F7F3"},
        )
        url = img.get("url")
        log(f"  image ok ({img.get('cost')}): {url}")
        return url
    except Exception as e:
        log(f"  image failed ({type(e).__name__}: {e}) - posting without it")
        return None


def _handled_marker(today: str) -> Path:
    return ROOT / "automation" / f".handled-{today}"


def _already_handled_today(today: str) -> bool:
    return _handled_marker(today).is_file()


def _mark_handled_today(today: str) -> None:
    """Call once a draft has actually been produced for today (whether it
    ends up published, queued, blocked, or held) - not on the earlier
    infra failures (evidence refresh, missing Claude CLI), which stay
    retry-eligible. A reboot-triggered rerun later the same day must
    never draft and publish a SECOND, different post."""
    _handled_marker(today).parent.mkdir(parents=True, exist_ok=True)
    _handled_marker(today).write_text(datetime.now().isoformat(), encoding="utf-8")


AUDIT_PROMPT = """Use the linkedin-humanizer skill with `--mode audit` on the draft below.
Detection only: do not rewrite it, do not fetch anything, do not publish.

Answer in this exact shape, and nothing else. The first line is VERDICT:
PASS when there is no blocker, and VERDICT: BLOCK when there is one:

VERDICT: PASS
BLOCKERS: none
WARNINGS: none

VERDICT is BLOCK only for a real blocker from the skill's anti-patterns: an
all-caps first line; a question as the first line; a "Here is what" or "Stop
doing X, start doing Y" opener; a "The result?" / "Plot twist" reveal bridge;
"Comment X to get Y" phrasing; announced candour with no dated fact behind it;
an external link in the body; a first line over 90 characters; a post under
300 characters; or a hook line the body never delivers on.

Everything else - length suggestions, hashtag counts, tighter wording - is a
WARNING. A warning never changes VERDICT.

Write the audit to drafts/audit-<date>.md is the runner's job, not yours: your
output is the three lines only. Put one blocker or warning per line, or
"none". A blocker line must quote the offending words.

DRAFT:
{body}
"""


def _audit_draft(cb: str, body: str, today: str) -> str | None:
    """linkedin-humanizer audit, run after drafting and before publishing.

    Returns "pass", "block", or None for an unavailable or malformed audit.
    Only an explicit, valid pass allows unattended publishing.
    """
    # same day-naming as the audit file below, so id and artifact always agree
    rid = f"linkedin-humanizer-{today}"
    started = datetime.now().astimezone().isoformat()
    emit_skill_run("linkedin-humanizer", "running", run_id=rid, started_at=started,
                   input_summary=f"drafts/{today}.md")
    try:
        r = run_hidden([cb, "-p", AUDIT_PROMPT.format(body=body)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=ROOT, timeout=600)
    except subprocess.TimeoutExpired:
        emit_skill_run("linkedin-humanizer", "failed", run_id=rid, started_at=started,
                       finished_at=datetime.now().astimezone().isoformat(),
                       error_text="audit call timed out after 600s")
        return None

    finished = datetime.now().astimezone().isoformat()
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        reason = (r.stderr or r.stdout or "empty output").strip()[:300]
        emit_skill_run("linkedin-humanizer", "failed", run_id=rid, started_at=started,
                       finished_at=finished,
                       error_text=f"claude exited {r.returncode}: {reason}")
        return None

    lines = [line.strip().upper() for line in out.splitlines() if line.strip()]
    valid = (len(lines) >= 3 and lines[0] in {"VERDICT: PASS", "VERDICT: BLOCK"}
             and sum(line.startswith("VERDICT:") for line in lines) == 1
             and lines[1].startswith("BLOCKERS:")
             and any(line.startswith("WARNINGS:") for line in lines))
    if lines[0] == "VERDICT: PASS":
        valid = valid and lines[1:2] == ["BLOCKERS: NONE"] and lines[2].startswith("WARNINGS:")
    if not valid:
        emit_skill_run("linkedin-humanizer", "failed", run_id=rid, started_at=started,
                       finished_at=finished, error_text="malformed or contradictory audit verdict")
        return None
    verdict = "pass" if lines[0] == "VERDICT: PASS" else "block"
    audit_path = DRAFTS / f"audit-{today}.md"
    audit_path.write_text(f"# humanizer audit - {today}\n\n{out}\n", encoding="utf-8")
    emit_skill_run("linkedin-humanizer", "completed", run_id=rid, started_at=started,
                   finished_at=finished, input_summary=f"drafts/{today}.md",
                   decision=f"VERDICT: {verdict}",
                   outcome=f"{verdict} (drafts/{audit_path.name})")
    return verdict


def main() -> int:
    with single_instance(ROOT / "automation" / ".daily.lock") as acquired:
        if not acquired:
            log("daily pipeline already running - skipping concurrent invocation")
            return 0
        return _main()


def _main() -> int:
    global RUN_ID
    load_env()
    DRAFTS.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    if _already_handled_today(today):
        log(f"=== daily run {today} already handled - skipping (boot/retry trigger) ===")
        return 0
    # Deterministic per-day id: a same-day rerun (e.g. after a fixed error)
    # upserts the same Run/SkillRun rows instead of duplicating them.
    RUN_ID = f"daily-{today}"
    started = datetime.now().astimezone().isoformat()
    log(f"=== daily run {today} ===")
    _emit("run_started", {"runId": RUN_ID, "localDate": today,
                           "autoPublish": os.getenv("AUTOPUBLISH", "false").strip().lower()
                           in {"1", "true", "yes"}, "startedAt": started})

    # 1. evidence
    log("step 1/5  refreshing evidence log")
    r = run_command([sys.executable, str(ROOT / "scripts" / "mine_evidence.py"),
                        "--days", "30", "--run-id", RUN_ID], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, timeout=300)
    step1_finished = datetime.now().astimezone().isoformat()
    if r.returncode != 0:
        log(f"  FAILED: {r.stderr.strip()[:300]}")
        _emit("step_finished", {"runId": RUN_ID, "stepKey": "evidence", "status": "failed",
                                 "startedAt": started, "finishedAt": step1_finished,
                                 "errorText": r.stderr.strip()[:2000]})
        _emit("run_finished", {"runId": RUN_ID, "status": "failed",
                                "finishedAt": step1_finished, "errorText": "evidence refresh failed"})
        report({"skill": "pipeline", "startedAt": started, "status": "failed",
                "errorText": "evidence refresh failed"})
        return 1
    log("  ok")
    _emit("step_finished", {"runId": RUN_ID, "stepKey": "evidence", "status": "completed",
                             "startedAt": started, "finishedAt": step1_finished})

    # 2. draft
    cb = claude_bin()
    if not cb:
        log("  FAILED: Claude Code CLI not found on PATH. Install it, or run "
            "`npm i -g @anthropic-ai/claude-code`.")
        _emit("run_finished", {"runId": RUN_ID, "status": "failed",
                                "finishedAt": datetime.now().astimezone().isoformat(),
                                "errorText": "claude CLI not found"})
        report({"skill": "pipeline", "startedAt": started, "status": "failed",
                "errorText": "claude CLI not found"})
        return 1

    log(f"step 2/5  drafting with Claude Code")
    draft_started = datetime.now().astimezone().isoformat()
    history = _read_history()
    lane = _pick_lane(history)
    log(f"  topic lane: {lane} (last {min(len(history), 8)} posts: "
        f"{', '.join(e.get('lane', '?') for e in history[-8:]) or 'none'})")
    r = run_command([cb, "-p", build_prompt(lane, history)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, timeout=900)
    draft_finished = datetime.now().astimezone().isoformat()
    if r.returncode != 0 or not r.stdout.strip():
        # The CLI reports quota and auth failures on stdout, so reading only
        # stderr is how "You've hit your weekly limit" reached the log as the
        # useless string "empty output".
        reason = (r.stderr or r.stdout or "empty output").strip()
        log(f"  FAILED: claude exited {r.returncode}: {reason[:300]}")
        _emit("step_finished", {"runId": RUN_ID, "stepKey": "draft", "status": "failed",
                                 "startedAt": draft_started, "finishedAt": draft_finished,
                                 "errorText": f"claude exited {r.returncode}: {reason[:1800]}"})
        _emit("run_finished", {"runId": RUN_ID, "status": "failed",
                                "finishedAt": draft_finished,
                                "errorText": f"draft failed: {reason[:400]}"})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "status": "failed", "errorText": f"draft failed: {reason[:200]}"})
        return 1

    out = r.stdout.strip()
    body, _, note = out.partition("\n---")
    body, note = body.strip(), note.strip()

    body = _strip_preamble(body)

    if not body or "no draft" in body.lower()[:200]:
        log("step 3/5  skill stood aside - no post worth making today")
        _mark_handled_today(today)
        _emit("step_finished", {"runId": RUN_ID, "stepKey": "draft", "status": "completed",
                                 "startedAt": draft_started, "finishedAt": draft_finished})
        _emit("run_finished", {"runId": RUN_ID, "status": "completed",
                                "verdict": "abandoned", "finishedAt": draft_finished})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "finishedAt": datetime.now().astimezone().isoformat(), "status": "completed",
                "decision": "stood aside", "outcome": "abandoned"})
        return 0

    path = DRAFTS / f"{today}.md"
    path.write_text(f"# Draft {today}\n\n{body}\n\n---\n{note}\n", encoding="utf-8")
    log(f"step 3/5  draft saved: {path.name} ({len(body)} chars)")
    # From here on, a draft exists for today - any reboot-triggered rerun
    # must not draft and potentially publish a second, different post.
    _mark_handled_today(today)
    _emit("step_finished", {"runId": RUN_ID, "stepKey": "draft", "status": "completed",
                             "startedAt": draft_started, "finishedAt": draft_finished})
    _emit("draft_saved", {"runId": RUN_ID, "contentMd": body, "noteMd": note,
                           "localPath": f"drafts/{today}.md", "charCount": len(body)})

    # 4. humanizer audit - runs before the queue branch too, so a queued draft
    #    arrives with its blockers instead of a silent wait for approval
    auto = os.getenv("AUTOPUBLISH", "false").strip().lower() in {"1", "true", "yes"}
    audit_started = datetime.now().astimezone().isoformat()
    verdict = _audit_draft(cb, body, today)
    _audit_event: dict = {"runId": RUN_ID, "stepKey": "audit",
                          "status": "completed" if verdict else "failed",
                          "startedAt": audit_started,
                          "finishedAt": datetime.now().astimezone().isoformat()}
    if verdict is None:
        _audit_event["errorText"] = "humanizer audit could not run"
    _emit("step_finished", _audit_event)
    if verdict is None:
        log("step 4/5  humanizer audit unavailable - draft requires review")
    elif verdict == "block":
        log(f"step 4/5  humanizer audit BLOCKED - blockers in drafts/audit-{today}.md")
    else:
        log("step 4/5  humanizer audit passed")

    if verdict != "pass" and auto:
        hold_reason = "held - audit blockers" if verdict == "block" else "held - audit unavailable"
        log(f"step 5/5  {hold_reason}")
        log(f"  draft kept at {path}; audit at drafts/audit-{today}.md")
        _emit("run_finished", {"runId": RUN_ID, "status": "completed",
                                "verdict": hold_reason,
                                "finishedAt": datetime.now().astimezone().isoformat()})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "finishedAt": datetime.now().astimezone().isoformat(), "status": "completed",
                "decision": note[:200], "outcome": hold_reason,
                "inputSummary": f"drafts/{today}.md"})
        return 0

    # 5. publish or queue (auto was decided above)
    if not auto:
        log("step 5/5  AUTOPUBLISH is off - queued for your approval")
        _emit("run_finished", {"runId": RUN_ID, "status": "completed",
                                "verdict": "awaiting approval",
                                "finishedAt": datetime.now().astimezone().isoformat()})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "finishedAt": datetime.now().astimezone().isoformat(), "status": "completed",
                "decision": note[:200], "outcome": "awaiting approval",
                "inputSummary": f"drafts/{today}.md"})
        return 0

    cutoff = int(os.getenv("PUBLISH_BEFORE_HOUR", "11"))
    if not 0 <= cutoff <= 24:
        raise ValueError("PUBLISH_BEFORE_HOUR must be between 0 and 24")
    if datetime.now().hour >= cutoff:
        log(f"step 5/5  too late to publish (after {cutoff}:00) - draft held for review")
        _emit("run_finished", {"runId": RUN_ID, "status": "completed",
                                "verdict": "held - ran too late",
                                "finishedAt": datetime.now().astimezone().isoformat()})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "finishedAt": datetime.now().astimezone().isoformat(), "status": "completed",
                "decision": note[:200], "outcome": "held - ran too late",
                "inputSummary": f"drafts/{today}.md"})
        return 0

    problem = _looks_like_commentary(body)
    if problem:
        log(f"step 5/5  REFUSING to publish - {problem}")
        _emit("run_finished", {"runId": RUN_ID, "status": "failed",
                                "finishedAt": datetime.now().astimezone().isoformat(),
                                "errorText": f"publish blocked: {problem}"})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "status": "failed", "outcome": "blocked",
                "errorText": f"publish blocked: {problem}"})
        return 1

    media = None
    backend = os.getenv("IMAGE_BACKEND", "card").strip().lower()
    if backend == "none":
        log("  images disabled")
    elif backend == "card":
        chosen = _motif(note)
        log(f"  motif: {chosen or 'auto (post did not name one)'}")
        url = _make_card(body.splitlines()[0], chosen)
        media = [url] if url else None
        if url:
            _emit("media_generated", {"runId": RUN_ID, "kind": "quote_card", "url": url,
                                       "status": "generated"})
    else:
        brief = _image_brief(note)
        if brief:
            log(f"  image brief: {brief[:90]}")
            url = _make_image(brief)
            media = [url] if url else None
            if url:
                _emit("media_generated", {"runId": RUN_ID, "kind": "illustration", "url": url,
                                           "status": "generated", "prompt": brief[:500]})
        else:
            log("  no image brief - posting text only")

    log("step 5/5  AUTOPUBLISH is on - publishing via Publora")
    sys.path.insert(0, str(ROOT))
    try:
        from lib import publish  # type: ignore
        # scheduled_time=None creates a Publora DRAFT that never reaches
        # LinkedIn. Always pass a time.
        when = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        res = publish(kind="post", draft_text=body,
                      target_url="https://www.linkedin.com/post/new/",
                      platforms=[os.environ["LINKEDIN_PLATFORM_ID"]],
                      scheduled_time=when, media_urls=media)
        if not isinstance(res, dict) or res.get("success") is False or not res.get("postGroupId"):
            raise ValueError("provider did not confirm a postGroupId; reconcile before retrying")
        delivery_status = res.get("status") or "scheduled"
        if delivery_status not in {"scheduled", "published"}:
            raise ValueError(f"provider status {delivery_status!r}; reconcile before retrying")
        log(f"  {delivery_status}: {res['postGroupId']}")
        _record_history(today, lane, body.splitlines()[0])
        if isinstance(res, dict):
            _emit("publish_result", {
                "runId": RUN_ID, "status": delivery_status,
                "postGroupId": res.get("postGroupId"), "scheduledFor": res.get("scheduledTime"),
                "providerRaw": res,
            })
        _emit("run_finished", {"runId": RUN_ID, "status": "completed",
                                "verdict": delivery_status,
                                "finishedAt": datetime.now().astimezone().isoformat()})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "finishedAt": datetime.now().astimezone().isoformat(), "status": "completed",
                "decision": note[:200], "outcome": delivery_status})
    except Exception as e:
        log(f"  FAILED: {type(e).__name__}: {e}")
        log(f"  draft is safe at {path}")
        _emit("run_finished", {"runId": RUN_ID, "status": "failed",
                                "finishedAt": datetime.now().astimezone().isoformat(),
                                "errorText": f"publish: {type(e).__name__}"})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "status": "failed", "errorText": f"publish: {type(e).__name__}"})
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
