"""Fresh and regenerated lead proposals share the user's outreach brief."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "automation"))
import run_lead_finder as leads
import dashboard_executor as executor


class LeadGuidance(unittest.TestCase):
    def test_fresh_prompt_includes_proposal_and_portfolio(self):
        prompt = leads.PROMPT_TEMPLATE.format(results_json="[]", cap=4,
                                             lead_comment_guidance=leads.LEAD_COMMENT_GUIDANCE)
        self.assertIn(leads.LEAD_COMMENT_GUIDANCE, prompt)
        self.assertIn("Open with the problem insight", prompt)
        self.assertIn("Only after the problem insight and solution glimpse", prompt)
        self.assertIn("not the full solution", prompt)
        self.assertIn("Never claim hours of research", prompt)
        self.assertIn("immediately before the portfolio link", prompt)
        self.assertIn("Use a verified role, specialty, or project", prompt)
        self.assertIn("omit the sentence rather than fabricate it", prompt)
        self.assertIn("Portfolio: https://webbyzain.online", prompt)
        self.assertIn("Never invent", prompt)

    def test_regeneration_uses_same_guidance_only_for_leads(self):
        for reason in ("LEAD: founder hiring", "warm thread"):
            with self.subTest(reason=reason), \
                 mock.patch.object(executor, "claude_bin", return_value="claude"), \
                 mock.patch.object(executor, "run_command", return_value=mock.Mock(
                     returncode=0, stdout="NO_ACTION", stderr="")) as command:
                executor.run_regenerate_reply({"replyDraftId": "test", "postUrl": "https://example.com",
                                               "reasonNote": reason})
            prompt = command.call_args.args[0][2]
            self.assertEqual(leads.LEAD_COMMENT_GUIDANCE in prompt, reason.startswith("LEAD:"))
