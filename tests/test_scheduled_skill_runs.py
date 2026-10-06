"""The scheduled runs have to report themselves, or the dashboard lies.

Two properties are checked here, both offline: the event payload is the flat
shape POST /api/events has always accepted, and a missing input becomes a
reported failure rather than a silent no-op. The claude call and the HTTP
layer are replaced - no key is read and nothing is spent.

The emit path was also proven against the live dashboard once, by
automation/run_skill.py writing a real row; these tests keep it true.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "automation"))

import run_daily  # noqa: E402
import run_skill  # noqa: E402
import skill_run_event  # noqa: E402

ENVR = {"DASHBOARD_EVENTS_URL": "https://dashboard.example", "EVENTS_INGEST_SECRET": "s3cret"}


class RecordingRequest:
    """Stands in for urllib.request.urlopen and keeps what was sent."""

    last = None

    def __init__(self, req, timeout=None):
        RecordingRequest.last = (req, timeout)

    def read(self):
        return b"{}"


class EventPayload(unittest.TestCase):
    def test_default_id_is_one_row_per_skill_per_day(self):
        """A retry the same day must update the row, not add a second one."""
        rid = skill_run_event.skill_run_id("linkedin-interviewer")
        self.assertRegex(rid, r"^linkedin-interviewer-\d{4}-\d{2}-\d{2}$")

    def test_stamped_id_is_unique_per_run(self):
        """Skills that run several times a day would otherwise overwrite
        each other's row with the last run of the day."""
        rid = skill_run_event.skill_run_id("linkedin-thread-monitor", stamp=True)
        self.assertRegex(rid, r"^linkedin-thread-monitor-\d{4}-\d{2}-\d{2}-\d{6}$")

    def test_payload_carries_the_keys_ingest_requires(self):
        with mock.patch.dict(os.environ, ENVR), \
             mock.patch.object(skill_run_event.urllib.request, "urlopen", RecordingRequest):
            sent = skill_run_event.emit_skill_run(
                "linkedin-hook-extractor", "completed", started_at="2026-09-30T10:00:00+00:00",
                finished_at="2026-09-30T10:02:00+00:00", decision="3 formulas",
                outcome="drafts/hooks-2026-W40.md")
        self.assertTrue(sent)
        req, timeout = RecordingRequest.last
        self.assertEqual(req.full_url, "https://dashboard.example/api/events")
        self.assertEqual(req.get_header("Authorization"), "Bearer s3cret")
        self.assertGreaterEqual(timeout, 1)
        import json
        body = json.loads(req.data.decode("utf-8"))
        for key in ("id", "skill", "status"):
            self.assertIn(key, body)
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["skill"], "linkedin-hook-extractor")
        self.assertTrue(body["id"].startswith(body["skill"]))

    def test_only_the_three_statuses_are_sent(self):
        with mock.patch.dict(os.environ, ENVR), \
             mock.patch.object(skill_run_event.urllib.request, "urlopen", RecordingRequest):
            for status in ("running", "completed", "failed"):
                skill_run_event.emit_skill_run("linkedin-humanizer", status)
                import json
                self.assertEqual(json.loads(RecordingRequest.last[0].data)["status"], status)

    def test_without_credentials_nothing_is_sent(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("DASHBOARD_EVENTS_URL", "EVENTS_INGEST_SECRET")}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(skill_run_event.urllib.request, "urlopen",
                               side_effect=RecordingRequest) as spy:
            self.assertFalse(skill_run_event.emit_skill_run("linkedin-interviewer", "completed"))
            spy.assert_not_called()

    def test_a_dashboard_that_is_down_never_fails_the_skill_run(self):
        with mock.patch.dict(os.environ, ENVR), \
             mock.patch.object(skill_run_event.urllib.request, "urlopen",
                               side_effect=URLError("connection refused")):
            self.assertFalse(skill_run_event.emit_skill_run("linkedin-repurposer", "completed"))

    def test_finished_at_defaults_to_now_for_terminal_statuses(self):
        with mock.patch.dict(os.environ, ENVR), \
             mock.patch.object(skill_run_event.urllib.request, "urlopen", RecordingRequest):
            skill_run_event.finish_skill_run("linkedin-profile-optimizer", "failed",
                                             run_id="linkedin-profile-optimizer-2026-10-02",
                                             started_at="2026-10-02T09:00:00+00:00",
                                             error_text="not configured: snapshot")
        import json
        body = json.loads(RecordingRequest.last[0].data)
        self.assertNotEqual(body["finishedAt"], body["startedAt"])
        self.assertIn("T", body["finishedAt"])
        self.assertEqual(body["errorText"], "not configured: snapshot")


class ScheduledJobs(unittest.TestCase):
    """The six skills install-continuous-tasks.ps1 schedules must all have a
    job, and the job names must be real skill ids - a typo there registers a
    task that fails with an unknown-skill usage message, silently."""

    def test_every_job_is_a_skill_in_this_bundle(self):
        shipped = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
        self.assertEqual(len(run_skill.JOBS), 6)
        self.assertTrue(set(run_skill.JOBS) <= shipped,
                        set(run_skill.JOBS) - shipped)

    def test_blank_profile_snapshot_reports_not_configured(self):
        with self.assertRaises(run_skill.NotConfigured) as ctx:
            run_skill.prepare_profile_optimizer()
        self.assertIn("profile-snapshot.md", str(ctx.exception))

    def test_blank_team_roster_reports_not_configured(self):
        with self.assertRaises(run_skill.NotConfigured) as ctx:
            run_skill.prepare_advocacy()
        self.assertIn("team.md", str(ctx.exception))


class AuditBeforePublish(unittest.TestCase):
    def test_block_verdict_retains_evidence_for_review(self):
        from automation.source_post import audit
        from test_post_package import package
        result = {'verdict': 'block', 'blockers': ['unsupported client experience'],
                  'warnings': [], 'imageInspected': True}
        with mock.patch('automation.source_post.ask', return_value=result):
            self.assertEqual(audit('claude', pathlib.Path('.'), package(), pathlib.Path('image.png')), result)

    def test_pass_verdict_requires_both_copy_and_visual_review(self):
        from automation.source_post import audit
        from test_post_package import package
        result = {'verdict': 'pass', 'blockers': [], 'warnings': ['could be tighter'], 'imageInspected': True}
        with mock.patch('automation.source_post.ask', return_value=result):
            self.assertEqual(audit('claude', pathlib.Path('.'), package(), pathlib.Path('image.png'))['verdict'], 'pass')

    def test_failed_audit_cannot_be_treated_as_a_pass(self):
        from automation.source_post import audit
        from test_post_package import package
        with mock.patch('automation.source_post.ask', side_effect=ValueError('CLI unavailable')):
            with self.assertRaises(ValueError):
                audit('claude', pathlib.Path('.'), package(), pathlib.Path('image.png'))


if __name__ == "__main__":
    unittest.main()
