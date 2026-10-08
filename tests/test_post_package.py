"""Offline behavioral checks: source integrity, exact approval, media and replay."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest import mock

from PIL import Image
from lib import post_package as pp
from lib import skill_run_logger as logger
from automation import source_post
from make_card import render_comparison


def image_bytes():
    output = BytesIO()
    Image.new('RGB', (600, 600), 'white').save(output, 'PNG')
    return output.getvalue()


def package():
    today = datetime.now(timezone.utc).date().isoformat()
    p = {'runId': 'daily-' + today, 'date': today, 'topic': 'Delivery scope', 'angle': 'Check the budget',
         'reason': 'A practical client qualification decision', 'delivery': 'ready', 'postGroupId': 'provider-id',
         'body': 'A project needs a clear acceptance boundary. ' * 10 + '\nSource: https://example.com/report',
         'sources': [{'url': 'https://example.com/report', 'publisher': 'Example', 'publishedAt': today}],
         'media': {'url': 'https://example.com/image.png', 'sha256': pp.digest(image_bytes()), 'mediaId': 'media-id',
                   'localPath': 'drafts/image.png'},
         'visual': {'kind': 'comparison'},
         'audit': {'verdict': 'pass', 'blockers': [], 'warnings': [], 'imageInspected': True}}
    p['revision'] = pp.revision(p)
    return p


class PackageValidation(unittest.TestCase):
    def test_reconciliation_uses_provider_truth_and_preserves_failures(self):
        from automation import dashboard_executor as executor
        posts = [{'draftId': 'd1', 'postGroupId': 'p1', 'status': 'scheduled'},
                 {'draftId': 'd2', 'postGroupId': 'p2', 'status': 'scheduled'}]
        with mock.patch.object(executor, 'api', return_value={'posts': posts}), \
             mock.patch('lib.publora_client.PubloraClient') as client, \
             mock.patch('lib.skill_run_logger.emit') as emit, \
             mock.patch('lib.skill_run_logger.flush'), mock.patch.object(executor, 'log'):
            client.return_value.get_post.side_effect = [
                {'status': 'published', 'posts': [{'permalink': 'https://linkedin.com/post'}]},
                ValueError('provider unavailable')]
            executor.reconcile_posts()
            emit.assert_called_once()
            self.assertEqual(emit.call_args.args[1]['status'], 'published')
            self.assertEqual(emit.call_args.args[1]['draftId'], 'd1')

    def test_shortlist_rotates_pillars_and_blocks_repeated_angles(self):
        candidates = [{'topic': topic, 'angle': topic, 'reason': 'Useful', 'pillar': pillar}
                      for topic, pillar in zip(['Client screening', 'Acceptance checks', 'Database design', 'Secure authentication'], source_post.PILLARS)]
        chosen = source_post.select_topic(candidates, [{'topic': 'Client screening', 'angle': 'Client screening', 'pillar': 'client-acquisition'}])
        self.assertEqual(chosen['pillar'], 'delivery')
        with self.assertRaises(ValueError):
            source_post.select_topic(candidates, candidates)

    def test_branded_layouts_render_different_images(self):
        from make_card import render_comparison
        hashes = []
        with tempfile.TemporaryDirectory() as tmp:
            for kind in ('checklist', 'process'):
                visual = {'kind': kind, 'title': 'Before you ship', 'items': ['Check keyboard navigation', 'Measure response time', 'Verify backup recovery'],
                          'takeaway': 'Make acceptance criteria explicit.', 'alt': 'Three checks',
                          'brand': {'name': 'Example Developer', 'website': 'example.com'}}
                path = render_comparison(visual, Path(tmp) / (kind + '.png'))
                info = pp.inspect_image(path.read_bytes())
                self.assertEqual(info['height'], 1620)
                hashes.append(info['sha256'])
            self.assertNotEqual(*hashes)

    def test_unverified_research_quote_is_held(self):
        today = datetime.now(timezone.utc).date().isoformat()
        brief = {'topic': 'Scope', 'angle': 'Acceptance', 'reason': 'Useful', 'scope': 'announcement',
                 'sources': [{'url': 'https://example.com/report', 'title': 'Report', 'publisher': 'Example',
                              'publishedAt': today, 'claim': 'A claimed change',
                              'quote': 'This claimed quotation does not appear on the original page.'}]}
        page = pp.Page(f'<time datetime="{today}"></time><p>The actual report says something else.</p>')
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(source_post, 'ask', return_value={'candidates': [{**brief, 'pillar': pillar} for pillar in source_post.PILLARS[:4]]}), \
             mock.patch.object(source_post, 'read_page', return_value=(page, 'https://example.com/report')):
            with self.assertRaisesRegex(ValueError, 'quote'):
                source_post.research('claude', Path(tmp), [])

    def test_original_publication_date_can_come_from_json_ld(self):
        page = pp.Page('<script type="application/ld+json">{"datePublished":"2026-10-06"}</script><p>Body</p>')
        self.assertEqual(page.dates, ['2026-10-06'])
        self.assertEqual(page.text, 'Body')

    def test_screenshot_preamble_and_ps_are_rejected(self):
        for text in ["Good length, roughly 1350 chars — fits medium range. That's my final draft.\n",
                     'P.S. the filter has been solid. No fourth commit needed.\n']:
            self.assertIsNotNone(pp.body_problem(text + package()['body']))

    def test_prose_around_json_is_not_recovered_as_a_post(self):
        with self.assertRaises(ValueError):
            pp.json_object('Here is the draft\n{"body":"test"}')

    def test_changes_to_body_or_media_invalidate_approval(self):
        for key in ('body', 'media'):
            p = package()
            p[key] = 'new body' if key == 'body' else {'url': 'https://example.com/new.png'}
            self.assertIsNotNone(pp.publish_problem(p))

    def test_no_image_inspection_blocks(self):
        p = package()
        self.assertIsNone(pp.publish_problem(p))
        p['audit']['imageInspected'] = False
        p['revision'] = pp.revision(p)
        self.assertIsNotNone(pp.publish_problem(p))
        p = package()
        p['body'] = p['body'].replace('https://example.com/report', '')
        p['revision'] = pp.revision(p)
        self.assertIsNone(pp.publish_problem(p))  # source links stay in the dashboard, not the post

    def test_private_mixed_dns_and_unsafe_urls_are_rejected(self):
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://localhost', 'https://example.com:444'):
            with self.assertRaises(ValueError):
                pp.public_url(url)
        with mock.patch.object(pp.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]), \
             mock.patch.object(pp.socket, 'create_connection') as connect:
            with self.assertRaises(ValueError):
                pp.PublicConnection('example.com').connect()
            connect.assert_not_called()

    def test_readable_comparison_is_an_actual_image(self):
        visual = {'kind': 'comparison', 'title': 'Qualify the project before writing a proposal',
                  'leftTitle': 'Visible need', 'rightTitle': 'Buying readiness',
                  'left': ['An outdated website', 'A slow manual workflow'],
                  'right': ['A named decision maker', 'An agreed budget and deadline'],
                  'takeaway': 'A technical problem alone does not establish a paid project.',
                  'alt': 'Comparison of visible technical needs and confirmed buying readiness.'}
        with tempfile.TemporaryDirectory() as tmp:
            out = render_comparison(visual, Path(tmp) / 'card.png', 'Sources: Example')
            self.assertEqual(pp.inspect_image(out.read_bytes())['height'], 1620)

    def test_internal_notes_cannot_be_rendered_or_published(self):
        visual = {'kind': 'process', 'title': 'Delivery checks',
                  'items': ['Define acceptance', 'Check dependencies', 'Agree on handoff'],
                  'takeaway': 'Agree on the finish line.', 'alt': 'Delivery checks'}
        note = 'Layout preview - not a researched post'
        with tempfile.TemporaryDirectory() as tmp:
            for changed, credit in [(visual, note), ({**visual, 'title': note}, '')]:
                out = Path(tmp) / 'card.png'
                with self.assertRaisesRegex(ValueError, 'drafting commentary'):
                    render_comparison(changed, out, credit)
                self.assertFalse(out.exists())
        self.assertEqual(pp.body_problem(note + package()['body']), 'post contains drafting commentary')

    def test_audit_cannot_pass_without_viewing_image(self):
        with mock.patch.object(source_post, 'ask', return_value={'verdict': 'pass', 'blockers': [],
                                                               'warnings': [], 'imageInspected': False}):
            with self.assertRaises(ValueError):
                source_post.audit('claude', Path('.'), package(), Path('card.png'))


class PublishPackage(unittest.TestCase):
    def test_default_rollout_prepares_media_but_does_not_publish(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'automation'))
        import run_daily
        p = package()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(run_daily, 'ROOT', root), mock.patch.object(run_daily, 'DRAFTS', root / 'drafts'), \
                 mock.patch.object(run_daily, 'load_env'), mock.patch.object(run_daily, 'log'), \
                 mock.patch.object(run_daily, 'claude_bin', return_value='claude'), \
                 mock.patch.object(source_post, 'flush', return_value=True), mock.patch.object(source_post, 'emit') as emit, \
                 mock.patch.object(source_post, 'research', return_value={k: p[k] for k in ('topic', 'angle', 'reason', 'sources')}), \
                 mock.patch.object(source_post, 'prepare_visual', return_value=(p['visual'], copy.deepcopy(p['media']))), \
                 mock.patch.object(source_post, 'ask', return_value={'body': p['body']}), \
                 mock.patch.object(source_post, 'audit', return_value=p['audit']), \
                 mock.patch.object(source_post, 'PubloraClient') as client, mock.patch('lib.publish') as publish, \
                 mock.patch.dict(os.environ, {'AUTOPUBLISH': 'true', 'PUBLORA_API_KEY': 'test',
                                              'LINKEDIN_PLATFORM_ID': 'linkedin-test'}, clear=True):
                client.return_value.create_post.return_value = {'success': True, 'postGroupId': 'provider-id'}
                client.return_value.upload_image.return_value = p['media']
                self.assertEqual(run_daily.main(), 0)
                publish.assert_not_called()
                client.return_value.create_post.assert_called_once()
                self.assertNotIn('scheduled_time', client.return_value.create_post.call_args.kwargs)
                saved = next(c.args[1]['package'] for c in emit.call_args_list if c.args[0] == 'package_saved')
                self.assertEqual(saved['body'], p['body'])
                self.assertEqual(saved['media']['url'], p['media']['url'])
                self.assertIsNone(pp.publish_problem(saved))

    def test_exact_package_is_scheduled_once_with_saved_media(self):
        p = package()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'drafts' / (p['date'] + '.json')
            pp.save(path, p)
            path.with_suffix('.md').write_text(p['body'], encoding='utf-8')
            (root / 'drafts' / 'image.png').write_bytes(image_bytes())
            provider = {'status': 'draft', 'media': [{'mediaId': 'media-id', 'status': 'ready'}],
                        'posts': [{'content': p['body']}]}
            with mock.patch.dict(os.environ, {'LINKEDIN_PLATFORM_ID': 'linkedin-test'}), \
                 mock.patch.object(source_post, 'fetch', return_value=(image_bytes(), 'image/png', p['media']['url'])), \
                 mock.patch.object(source_post, 'PubloraClient') as client, \
                 mock.patch('automation.dashboard_executor.api', return_value={'ok': True}), \
                 mock.patch.object(source_post, 'emit') as emit, \
                 mock.patch('lib.publish', return_value={'postGroupId': 'provider-id', 'status': 'scheduled'}) as publish:
                client.return_value.get_post.return_value = provider
                self.assertEqual(source_post.publish_package(root, p)['status'], 'scheduled')
                self.assertEqual(publish.call_args.kwargs['draft_text'], p['body'])
                self.assertEqual(publish.call_args.kwargs['media_urls'], [p['media']['url']])
                self.assertEqual(publish.call_args.kwargs['prepared_post_group_id'], 'provider-id')
                with self.assertRaises(ValueError):
                    source_post.publish_package(root, p)
                self.assertEqual(publish.call_count, 1)
                self.assertEqual(emit.call_args.args[1]['status'], 'scheduled')

    def test_changed_hosted_image_never_reaches_provider(self):
        p = package()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pp.save(root / 'drafts' / (p['date'] + '.json'), p)
            (root / 'drafts' / (p['date'] + '.md')).write_text(p['body'], encoding='utf-8')
            (root / 'drafts' / 'image.png').write_bytes(image_bytes())
            with mock.patch.object(source_post, 'fetch', return_value=(b'not an image', 'image/png', '')), \
                 mock.patch('lib.publish') as publish:
                with self.assertRaises(Exception):
                    source_post.publish_package(root, p)
                publish.assert_not_called()


class DurableEvents(unittest.TestCase):
    def test_outage_and_unknown_event_keep_the_same_event_for_replay(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(logger, 'OUTBOX', Path(tmp) / 'events.db'), \
             mock.patch.object(logger, 'load_env'), \
             mock.patch.dict(os.environ, {'DASHBOARD_EVENTS_URL': 'https://example.com', 'EVENTS_INGEST_SECRET': 'test'}), \
             mock.patch.object(logger.urllib_request, 'urlopen') as request:
            request.side_effect = OSError('offline')
            logger.emit('package_saved', {'runId': 'test'})
            with logger._outbox() as db:
                original = db.execute('SELECT id,body FROM events').fetchone()
            request.side_effect = None
            response = request.return_value.__enter__.return_value
            response.status = 202
            response.read.return_value = b'{"ok":true,"ignored":true}'
            self.assertFalse(logger.flush())
            response.status = 200
            response.read.return_value = b'{"ok":true}'
            self.assertTrue(logger.flush())
            sent = json.loads(request.call_args.args[0].data)
            self.assertEqual(sent['eventId'], original[0])
            with logger._outbox() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
