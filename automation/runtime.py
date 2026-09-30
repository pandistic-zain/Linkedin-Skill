"""Bounded subprocesses and process locks for scheduled and manual runs."""
from contextlib import contextmanager
import errno
import os
import subprocess


def run_hidden(*args, **kwargs):
    """Prevent console children of pythonw.exe from flashing on Windows."""
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(*args, **kwargs)


def run_command(*args, **kwargs):
    """Return a regular failure on timeout so existing reporting paths run."""
    try:
        return run_hidden(*args, **kwargs)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args[0], 124, stdout="",
                                           stderr=f"command timed out after {kwargs.get('timeout')}s")


@contextmanager
def single_instance(path):
    """OS-owned lock releases on crash; the persistent file is not a stale lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
