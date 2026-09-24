#!/usr/bin/env python3
"""Daily LinkedIn pipeline. Run by Windows Task Scheduler.

  1. refresh the evidence log from local + GitHub repos
  2. ask Claude Code (headless) to draft today's post using the bundle's skills
  3. save the draft to drafts/YYYY-MM-DD.md
  4. publish, or queue for approval, per AUTOPUBLISH
  5. report the run to the dashboard, if one is configured

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
RUN_ID = ""  # set at the top of main(); module-level default for report() calls before that

sys.path.insert(0, str(ROOT))
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
            r = subprocess.run([name, "--version"], capture_output=True,
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

Pick the topic from the evidence log - something I actually shipped recently,
with a real date. Never invent a number or a build history. If the evidence log
has nothing worth a post today, say exactly that and write no draft; standing
aside is a valid outcome.

Before you output, re-read your own draft against the evidence lines you used.
Check every date, interval and count you wrote: "four days apart" must match the
actual gap between the commits you cited. A contradiction between the hook and
the body is a failure, not a style issue. Fix it before output.

Output the post body and NOTHING before it. No preamble, no "Final output:",
no character count, no commentary about your own draft. The very first character
of your output is the first character of the post. Then a line containing --- , then exactly two lines:

FORMULA: <which hook formula you used, and which evidence line it came from>
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



PREAMBLE_MARKERS = (
    "final output", "here is the post", "here's the post", "here is the draft",
    "here's the draft", "draft:", "post:", "output:",
)


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
            r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
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


def main() -> int:
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
    log("step 1/4  refreshing evidence log")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "mine_evidence.py"),
                        "--days", "30"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT)
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

    log("step 2/4  drafting with Claude Code")
    draft_started = datetime.now().astimezone().isoformat()
    r = subprocess.run([cb, "-p", PROMPT], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, timeout=900)
    draft_finished = datetime.now().astimezone().isoformat()
    if r.returncode != 0 or not r.stdout.strip():
        log(f"  FAILED: {(r.stderr or 'empty output').strip()[:300]}")
        _emit("step_finished", {"runId": RUN_ID, "stepKey": "draft", "status": "failed",
                                 "startedAt": draft_started, "finishedAt": draft_finished,
                                 "errorText": (r.stderr or "empty output").strip()[:2000]})
        _emit("run_finished", {"runId": RUN_ID, "status": "failed",
                                "finishedAt": draft_finished, "errorText": "draft failed"})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "status": "failed", "errorText": "draft failed"})
        return 1

    out = r.stdout.strip()
    body, _, note = out.partition("\n---")
    body, note = body.strip(), note.strip()

    body = _strip_preamble(body)

    if not body or "no draft" in body.lower()[:200]:
        log("step 3/4  skill stood aside - no post worth making today")
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
    log(f"step 3/4  draft saved: {path.name} ({len(body)} chars)")
    # From here on, a draft exists for today - any reboot-triggered rerun
    # must not draft and potentially publish a second, different post.
    _mark_handled_today(today)
    _emit("step_finished", {"runId": RUN_ID, "stepKey": "draft", "status": "completed",
                             "startedAt": draft_started, "finishedAt": draft_finished})
    _emit("draft_saved", {"runId": RUN_ID, "contentMd": body, "noteMd": note,
                           "localPath": f"drafts/{today}.md", "charCount": len(body)})

    # 3. publish or queue
    auto = os.getenv("AUTOPUBLISH", "false").strip().lower() in {"1", "true", "yes"}
    if not auto:
        log("step 4/4  AUTOPUBLISH is off - queued for your approval")
        _emit("run_finished", {"runId": RUN_ID, "status": "completed",
                                "verdict": "awaiting approval",
                                "finishedAt": datetime.now().astimezone().isoformat()})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "finishedAt": datetime.now().astimezone().isoformat(), "status": "completed",
                "decision": note[:200], "outcome": "awaiting approval",
                "inputSummary": f"drafts/{today}.md"})
        return 0

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

    problem = _looks_like_commentary(body)
    if problem:
        log(f"step 4/4  REFUSING to publish - {problem}")
        log(f"  draft kept at {path} for you to review")
        _emit("run_finished", {"runId": RUN_ID, "status": "failed",
                                "finishedAt": datetime.now().astimezone().isoformat(),
                                "errorText": f"publish blocked: {problem}"})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "status": "failed", "outcome": "blocked",
                "errorText": f"publish blocked: {problem}"})
        return 1

    # A late run means the laptop was asleep at 07:00 and Windows fired the task
    # on wake. Publishing at 4pm is worse than not publishing: the draft keeps,
    # the posting slot does not.
    cutoff = int(os.getenv("PUBLISH_BEFORE_HOUR", "11"))
    if datetime.now().hour >= cutoff:
        log(f"step 4/4  too late to publish (after {cutoff}:00) - draft kept for tomorrow")
        log(f"  post it by hand with: python post_now.py")
        _emit("run_finished", {"runId": RUN_ID, "status": "completed",
                                "verdict": "held - ran too late",
                                "finishedAt": datetime.now().astimezone().isoformat()})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "finishedAt": datetime.now().astimezone().isoformat(), "status": "completed",
                "decision": note[:200], "outcome": "held - ran too late",
                "inputSummary": f"drafts/{today}.md"})
        return 0

    log("step 4/4  AUTOPUBLISH is on - publishing via Publora")
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
        if isinstance(res, dict) and res.get("status") == "draft":
            log("  WARNING: Publora still reports status=draft - not published")
        log(f"  published: {str(res)[:200]}")
        if isinstance(res, dict):
            _emit("publish_result", {
                "runId": RUN_ID, "status": res.get("status") or "published",
                "postGroupId": res.get("postGroupId"), "scheduledFor": res.get("scheduledTime"),
                "providerRaw": res,
            })
        _emit("run_finished", {"runId": RUN_ID, "status": "completed",
                                "verdict": "published",
                                "finishedAt": datetime.now().astimezone().isoformat()})
        report({"skill": "linkedin-post-writer", "startedAt": started,
                "finishedAt": datetime.now().astimezone().isoformat(), "status": "completed",
                "decision": note[:200], "outcome": "published"})
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
