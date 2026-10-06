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
        from automation.source_post import audit
        from test_post_package import package
        for output in ({}, {'verdict': 'pass', 'blockers': ['unsupported fact'], 'warnings': [], 'imageInspected': True},
                       {'verdict': 'pass', 'blockers': [], 'warnings': [], 'imageInspected': False}):
            with self.subTest(output=output), mock.patch('automation.source_post.ask', return_value=output):
                with self.assertRaises(ValueError):
                    audit('claude', Path('.'), package(), Path('image.png'))


class PublishContract(unittest.TestCase):
    def test_approved_post_is_scheduled_not_claimed_as_published(self):
        from test_post_package import package
        p = package()
        with mock.patch('automation.source_post.publish_package', return_value={'status': 'scheduled', 'postGroupId': 'test-id'}) as publish, \
             mock.patch('lib.skill_run_logger.flush', return_value=True):
            status, message = dashboard_executor.run_approve_publish(
                {'package': p, 'revision': p['revision'], 'draftId': 'draft-1'})
        self.assertEqual(status, 'done')
        self.assertEqual(message, 'scheduled: test-id')
        self.assertEqual(publish.call_args.args[1], p)

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
        from automation import source_post
        from test_post_package import package
        p = package()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(run_daily, 'ROOT', root), \
                 mock.patch.object(run_daily, 'DRAFTS', root / 'drafts'), \
                 mock.patch.object(run_daily, 'load_env'), \
                 mock.patch.object(run_daily, 'log'), \
                 mock.patch.object(run_daily, 'claude_bin', return_value='claude'), \
                 mock.patch.object(source_post, 'flush', return_value=True), \
                 mock.patch.object(source_post, 'emit') as emit, \
                 mock.patch.object(source_post, 'research', return_value={k: p[k] for k in ('topic', 'angle', 'reason', 'sources')}), \
                 mock.patch.object(source_post, 'prepare_visual', return_value=(p['visual'], p['media'])), \
                 mock.patch.object(source_post, 'ask', return_value={'body': p['body']}), \
                 mock.patch.object(source_post, 'audit', side_effect=ValueError('audit unavailable')) as audit, \
                 mock.patch('lib.publish') as publish:
                self.assertEqual(run_daily.main(), 0)
                self.assertEqual(run_daily.main(), 0)
            publish.assert_not_called()
            self.assertEqual(audit.call_count, 1)
            self.assertEqual(len(list((root / 'drafts').glob('*.md'))), 1)
            self.assertTrue(any(call.args[0] == 'package_saved' and
                                call.args[1]['package']['delivery'] == 'held' for call in emit.call_args_list))

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
