#!/usr/bin/env python3
"""Scheduled source-first post runner. Package implementation lives in source_post.

Research -> inspected visual -> copy -> joint audit -> prepared provider draft ->
dashboard review -> exact-revision scheduling. Review-only rollout is the default.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / 'drafts'
LOG = ROOT / 'automation' / 'run.log'
RUN_ID = ''
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib._env import load_env
from runtime import run_hidden, single_instance

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
    with single_instance(ROOT / "automation" / ".daily.lock") as acquired:
        if not acquired:
            log("daily pipeline already running - skipping concurrent invocation")
            return 0
        return _main()


def _main() -> int:
    from automation.source_post import run
    return run(sys.modules[__name__])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
