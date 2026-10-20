"""Offline contracts for review-preserving dashboard edit commands."""
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automation import dashboard_executor as executor
from lib import post_package as pp
from lib.publora_client import PubloraClient
from test_post_package import package, image_bytes


class DraftEdits(unittest.TestCase):
    def execute(self, *, audit_failure=False, provider_status='draft', reserved=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        original = package()
        path = root / 'drafts' / (original['date'] + '.json')
        pp.save(path, original)
        (root / original['media']['localPath']).write_bytes(image_bytes())
        body = original['body'] + '\nEdited by the operator before a fresh review.'
        client = mock.Mock()
        client.get_post.side_effect = [
            {'status': provider_status}, {'status': 'draft', 'posts': [{'content': body}]},
        ]
        with mock.patch.object(executor, 'ROOT', root), \
             mock.patch.object(executor, 'single_instance', return_value=contextlib.nullcontext(True)), \
             mock.patch.object(executor, 'api', return_value={'ok': reserved}), \
             mock.patch('lib.publora_client.PubloraClient', return_value=client), \
             mock.patch('automation.run_daily.claude_bin', return_value='test-cli'), \
             mock.patch('automation.source_post.audit', side_effect=ValueError('audit unavailable') if audit_failure else None,
                        return_value={'verdict': 'pass', 'blockers': [], 'warnings': [], 'imageInspected': True}), \
             mock.patch('lib.skill_run_logger.emit') as emit, \
             mock.patch('lib.skill_run_logger.flush', return_value=True), \
             mock.patch('lib.publish') as publish:
            result = executor.run_edit_draft({'runId': original['runId'], 'draftId': 'test-draft',
                                             'revision': original['revision'], 'body': body})
        publish.assert_not_called()
        return result, json.loads(path.read_text(encoding='utf-8')), original, client, emit

    def test_edit_updates_exact_provider_text_and_returns_for_approval(self):
        result, saved, original, client, emit = self.execute()
        self.assertEqual(result[0], 'done')
        self.assertNotEqual(saved['revision'], original['revision'])
        self.assertEqual(saved['revision'], pp.revision(saved))
        self.assertEqual(saved['delivery'], 'ready')
        client.update_draft_content.assert_called_once_with(
            post_group_id=original['postGroupId'], content=saved['body'])
        self.assertEqual(emit.call_args.args[0], 'package_saved')
        self.assertNotIn('approved', saved)

    def test_failed_audit_holds_edit_without_updating_provider(self):
        result, saved, _, client, emit = self.execute(audit_failure=True)
        self.assertEqual(result[0], 'failed')
        self.assertEqual(saved['delivery'], 'held')
        self.assertIn('audit unavailable', saved['error'])
        self.assertNotIn('audit', saved)
        client.update_draft_content.assert_not_called()
        emit.assert_called_once()

    def test_scheduled_provider_post_cannot_be_edited(self):
        result, saved, original, client, emit = self.execute(provider_status='scheduled')
        self.assertEqual(result[0], 'failed')
        self.assertEqual(saved, original)
        client.update_draft_content.assert_not_called()
        emit.assert_not_called()

    def test_rejected_reservation_cannot_overwrite_human_decision(self):
        result, saved, original, client, emit = self.execute(reserved=False)
        self.assertEqual(result[0], 'failed')
        self.assertEqual(saved, original)
        client.get_post.assert_not_called()
        emit.assert_not_called()

    def test_draft_text_update_never_schedules_or_attaches_media(self):
        client = PubloraClient.__new__(PubloraClient)
        client.timeout = 2
        client._session = mock.Mock()
        client._handle = mock.Mock(return_value={'success': True})
        client.update_draft_content(post_group_id='test', content='Operator reviewed text')
        self.assertEqual(client._session.put.call_args.kwargs['json'], {'content': 'Operator reviewed text'})
        self.assertEqual(client._session.put.call_args.kwargs['timeout'], 2)

    def test_reply_cannot_post_without_atomic_reservation(self):
        with mock.patch.object(executor, 'api', return_value={'ok': False}), \
             mock.patch('lib.publora_client.PubloraClient') as client:
            status, _ = executor.run_approve_reply({'replyDraftId': 'reply', 'postUrn': 'urn:li:share:1', 'draftText': 'Reply'})
        self.assertEqual(status, 'failed')
        client.assert_not_called()

    def test_scheduled_failure_with_exit_zero_is_not_a_successful_sync(self):
        result = mock.Mock(returncode=0, stdout='DASHBOARD_SYNC_RESULT=failed\n')
        with mock.patch.object(executor, 'run_command', return_value=result):
            self.assertEqual(executor.run_sync_audience({})[0], 'failed')

    def test_sync_requires_a_confirmed_domain_result(self):
        for output, expected in [('', 'failed'), ('DASHBOARD_SYNC_RESULT=completed\n', 'done')]:
            with self.subTest(output=output), mock.patch.object(executor, 'run_command', return_value=mock.Mock(returncode=0, stdout=output)):
                self.assertEqual(executor.run_sync_audience({})[0], expected)
