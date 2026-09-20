#!/usr/bin/env python3
"""Mine real, dated build evidence for LinkedIn drafts.

Two sources, both factual:
  * local git repos  - commit subjects with dates and short SHAs
  * GitHub public API - public repos and recent public activity

Writes references/evidence-log.md, which the writing skills read alongside the
Story Bank. That file is gitignored: it names private repo work.

This tool REPORTS. It never interprets, never estimates, never rounds a date.
If a fact is not in here or in the Story Bank, a draft must not claim it.

Usage:
  python3 scripts/mine_evidence.py                       # local repos + GitHub
  python3 scripts/mine_evidence.py --days 60
  python3 scripts/mine_evidence.py --repo /path/to/one   # repeatable
  python3 scripts/mine_evidence.py --no-github
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "references" / "evidence-log.md"
GITHUB_USER = "pandistic-zain"

# Searched when --repo is not given. Add your own roots here.
SEARCH_ROOTS = [Path.home() / "mnt", Path("Z:/automation"), Path("Z:/Agency")]
SKIP_DIRS = {"node_modules", ".venv", "venv", "_to_delete", "site-packages"}


def find_repos(roots, depth=3):
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for d in range(depth + 1):
            pattern = "/".join(["*"] * d + [".git"]) if d else ".git"
            for git in root.glob(pattern):
                repo = git.parent
                if any(p in SKIP_DIRS for p in repo.parts):
                    continue
                if repo not in found:
                    found.append(repo)
    return found


def git(repo: Path, *args):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def commits(repo: Path, days: int):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    out = git(repo, "log", f"--since={since}", "--date=short",
              "--pretty=%h|%ad|%s", "--no-merges", "-n", "40")
    rows = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            rows.append(tuple(p.strip() for p in parts))
    return rows


def first_commit(repo: Path):
    out = git(repo, "log", "--reverse", "--date=short", "--pretty=%h|%ad|%s", "-n", "1")
    parts = out.split("|", 2)
    return tuple(p.strip() for p in parts) if len(parts) == 3 else None


def languages(repo: Path):
    out = git(repo, "ls-files")
    counts = {}
    for f in out.splitlines():
        ext = Path(f).suffix.lower()
        if ext in {".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ".sql", ".sh"}:
            counts[ext] = counts.get(ext, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:4]
    return ", ".join(f"{e.lstrip('.')} ({n})" for e, n in top)


def github(user: str):
    import os
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

    def get(url):
        try:
            headers = {"User-Agent": "linkedin-skills-evidence"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except Exception as e:
            return {"__error__": f"{type(e).__name__}: {e}"}

    # With a token, /user/repos returns private repos too; without one it 401s,
    # so fall back to the public listing.
    repos = get("https://api.github.com/user/repos?sort=pushed&per_page=30&affiliation=owner") \
        if token else {"__error__": "no token"}
    if isinstance(repos, dict):
        repos = get(f"https://api.github.com/users/{user}/repos?sort=pushed&per_page=15")
    if isinstance(repos, dict):
        return None, repos.get("__error__", "unknown error")
    rows = [{
        "name": r.get("name"),
        "desc": (r.get("description") or "").strip(),
        "lang": r.get("language"),
        "stars": r.get("stargazers_count", 0),
        "pushed": (r.get("pushed_at") or "")[:10],
        "private": bool(r.get("private")),
        "url": r.get("html_url"),
    } for r in repos if not r.get("fork")]
    return rows, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--repo", action="append", default=[])
    ap.add_argument("--no-github", action="store_true")
    ap.add_argument("--user", default=GITHUB_USER)
    a = ap.parse_args()

    repos = [Path(r) for r in a.repo] if a.repo else find_repos(SEARCH_ROOTS)
    repos = [r for r in repos if r.is_dir()]

    today = datetime.now().strftime("%Y-%m-%d")
    L = [
        "# Evidence Log",
        "",
        "Dated, factual build evidence, generated by `scripts/mine_evidence.py`.",
        "Writing skills read this alongside the Story Bank.",
        "",
        "**This file is gitignored** - it names private repository work.",
        "",
        "**Rule for drafts:** a claim about what was built, when, or in what order",
        "must trace to a line in this file or to the Story Bank. Nothing here is",
        "an estimate. If it is not written down, do not write it in a post.",
        "",
        "**Client guard:** much of what follows is private and some of it is client",
        "work. This file is input, never output. Use the problem, the tradeoff and",
        "the date; never a client name, product name, internal service name or",
        "metric. See the Story Bank's \"Names you can use\" and \"Off limits\".",
        "",
        f"- generated: {today}",
        f"- window: last {a.days} days",
        f"- repositories scanned: {len(repos)}",
        "",
        "---",
        "",
        "## Local repositories",
        "",
    ]

    if not repos:
        L += ["_No git repositories found. Pass `--repo <path>` explicitly._", ""]

    for repo in repos:
        rows = commits(repo, a.days)
        first = first_commit(repo)
        branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "?"
        langs = languages(repo)
        L.append(f"### {repo.name}")
        L.append("")
        L.append(f"- path: `{repo}`")
        L.append(f"- branch: `{branch}`")
        if langs:
            L.append(f"- files by language: {langs}")
        if first:
            L.append(f"- first commit: `{first[0]}` {first[1]} — {first[2]}")
        L.append(f"- commits in window: {len(rows)}")
        L.append("")
        if rows:
            for sha, date, subj in rows:
                L.append(f"- `{sha}` {date} — {subj}")
        else:
            L.append("_No commits in this window._")
        L.append("")

    if not a.no_github:
        L += ["---", "", f"## GitHub public activity — @{a.user}", ""]
        rows, err = github(a.user)
        if err:
            L += [f"_Could not reach the GitHub API: {err}_",
                  "_Public activity omitted. Local evidence above is unaffected._", ""]
        elif not rows:
            L += ["_No public non-fork repositories returned._", ""]
        else:
            for r in rows:
                bits = [f"pushed {r['pushed']}"]
                if r["lang"]:
                    bits.append(r["lang"])
                if r["stars"]:
                    bits.append(f"{r['stars']}★")
                if r.get("private"):
                    bits.append("PRIVATE")
                L.append(f"- **{r['name']}** ({', '.join(bits)}) — {r['desc'] or 'no description'}")
                L.append(f"  {r['url']}")
            L.append("")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"  {len(repos)} local repo(s), window {a.days} days")


if __name__ == "__main__":
    sys.exit(main())
