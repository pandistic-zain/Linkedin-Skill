"""Background jobs must suppress child consoles, not just their own window."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "automation"))
from runtime import run_hidden, run_command


class BackgroundProcesses(unittest.TestCase):
    def test_no_window_flag_preserves_other_flags(self):
        with mock.patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
             mock.patch.object(subprocess, "run") as run:
            run_hidden(["example"], creationflags=0x200, capture_output=True)
        self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000200)
        self.assertTrue(run.call_args.kwargs["capture_output"])

    @unittest.skipUnless(os.name == "nt", "Windows console contract")
    def test_real_child_has_no_console_and_keeps_output(self):
        result = run_command(
            [sys.executable, "-c", "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_timeout_and_exit_status_remain_intact(self):
        result = run_hidden([sys.executable, "-c", "import sys; sys.exit(7)"], timeout=10)
        self.assertEqual(result.returncode, 7)
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("example", 1)):
            self.assertEqual(run_command(["example"], timeout=1).returncode, 124)
