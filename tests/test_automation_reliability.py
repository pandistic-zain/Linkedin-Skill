"""Offline regression checks for unattended publishing boundaries."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "automation"))
import run_daily
import dashboard_executor
import runtime
import skill_run_event
from lib.publora_client import PubloraClient, PubloraError


class AuditContract(unittest.TestCase):
    def test_unstructured_or_contradictory_audit_is_not_a_pass(self):
        for output in ("Please approve tool access", "VERDICT: PASS\nVERDICT: BLOCK",
                       "VERDICT: PASS\nBLOCKERS: unsafe hook", "Looks good"):
            with self.subTest(output=output), tempfile.TemporaryDirectory() as tmp:
                with mock.patch.object(run_daily, "DRAFTS", Path(tmp)), \
                     mock.patch.object(run_daily, "emit_skill_run"), \
                     mock.patch.object(run_daily.subprocess, "run", return_value=mock.Mock(
                         returncode=0, stdout=output, stderr="")):
                    self.assertIsNone(run_daily._audit_draft("claude", "body", "2099-01-01"))


class PublishContract(unittest.TestCase):
    def test_approved_post_is_scheduled_not_claimed_as_published(self):
        with mock.patch.dict(os.environ, {"LINKEDIN_PLATFORM_ID": "linkedin-test"}), \
             mock.patch("lib.publish", return_value={"success": True, "postGroupId": "test-id"}), \
             mock.patch("lib.skill_run_logger.emit") as emit:
            status, message = dashboard_executor.run_approve_publish(
                {"contentMd": "A concrete engineering observation. " * 20, "draftId": "draft-1"})
        self.assertEqual(status, "done")
        self.assertEqual(message, "scheduled: test-id")
        self.assertEqual(emit.call_args.args[1]["status"], "scheduled")
        self.assertIsNone(emit.call_args.args[1]["publishedAt"])

    def test_manual_backend_does_not_report_success(self):
        with mock.patch.dict(os.environ, {"LINKEDIN_PLATFORM_ID": "linkedin-test"}), \
             mock.patch("lib.publish", return_value={"mode": "manual"}), \
             mock.patch("lib.skill_run_logger.emit") as emit:
            status, _ = dashboard_executor.run_approve_publish(
                {"contentMd": "A concrete engineering observation. " * 20})
        self.assertEqual(status, "failed")
        emit.assert_not_called()

    def test_write_timeout_is_not_retried(self):
        client = PubloraClient.__new__(PubloraClient)
        client.timeout = 1
        client._session = mock.Mock()
        client._session.post.side_effect = requests.Timeout("ambiguous outcome")
        with mock.patch("time.sleep"), self.assertRaises(requests.Timeout):
            client.create_post(content="test", platforms=["linkedin-test"])
        self.assertEqual(client._session.post.call_count, 1)

    def test_server_error_is_not_retried(self):
        client = PubloraClient.__new__(PubloraClient)
        client.timeout = 1
        client._session = mock.Mock()
        client._session.post.return_value = mock.Mock(status_code=503, json=lambda: {})
        with mock.patch("time.sleep"), self.assertRaises(PubloraError):
            client.create_comment(post_urn="urn:li:share:1", message="test", platform_id="linkedin-test")
        self.assertEqual(client._session.post.call_count, 1)


class RuntimeContract(unittest.TestCase):
    def test_daily_flow_holds_unavailable_audit_and_deduplicates_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "A concrete engineering observation. " * 20
            results = [mock.Mock(returncode=0, stdout="", stderr=""),
                       mock.Mock(returncode=0, stdout=body, stderr="")]
            with mock.patch.object(run_daily, "ROOT", root), \
                 mock.patch.object(run_daily, "DRAFTS", root / "drafts"), \
                 mock.patch.object(run_daily, "load_env"), \
                 mock.patch.object(run_daily, "log"), \
                 mock.patch.object(run_daily, "report"), \
                 mock.patch.object(run_daily, "_emit") as emit, \
                 mock.patch.object(run_daily, "claude_bin", return_value="claude"), \
                 mock.patch.object(run_daily, "_read_history", return_value=[]), \
                 mock.patch.object(run_daily, "_record_history"), \
                 mock.patch.object(run_daily, "_audit_draft", return_value=None), \
                 mock.patch.object(run_daily, "run_command", side_effect=results) as command, \
                 mock.patch("lib.publish") as publish, \
                 mock.patch.dict(os.environ, {"AUTOPUBLISH": "true"}):
                self.assertEqual(run_daily.main(), 0)
                self.assertEqual(run_daily.main(), 0)
            publish.assert_not_called()
            self.assertEqual(command.call_count, 2)
            self.assertEqual(len(list((root / "drafts").glob("*.md"))), 1)
            self.assertEqual(emit.call_args.args[1]["verdict"], "held - audit unavailable")

    def test_timeout_becomes_reportable_failure(self):
        with mock.patch.object(runtime.subprocess, "run", side_effect=runtime.subprocess.TimeoutExpired("test", 2)):
            result = runtime.run_command(["test"], timeout=2)
        self.assertEqual(result.returncode, 124)
        self.assertIn("2s", result.stderr)

    def test_lock_blocks_overlap_and_releases_after_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "run.lock"
            with self.assertRaises(ValueError):
                with runtime.single_instance(lock) as first:
                    self.assertTrue(first)
                    with runtime.single_instance(lock) as second:
                        self.assertFalse(second)
                    raise ValueError("crash")
            with runtime.single_instance(lock) as recovered:
                self.assertTrue(recovered)

    def test_running_event_has_no_finished_timestamp(self):
        with mock.patch.object(skill_run_event, "emit_skill_run") as emit:
            skill_run_event.finish_skill_run("test", "running", run_id="id", started_at="now")
        self.assertIsNone(emit.call_args.kwargs["finished_at"])


if __name__ == "__main__":
    unittest.main()
