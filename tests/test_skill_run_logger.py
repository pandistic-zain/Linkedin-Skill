"""The dashboard event logger must never slow down or break a skill run.

These prove the two halves of that promise: it is a true no-op with either env
var unset, and when both are set, it posts the right shape to `/api/events`
with the right bearer header. The daemon-thread dispatch is captured by a
threading.Event set from inside a tiny local HTTP server rather than a sleep,
so the test is not a race.
"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from lib.skill_run_logger import finish_run, start_run


class _CapturingHandler(BaseHTTPRequestHandler):
    received: list[dict] = []
    event = threading.Event()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.received.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "json": json.loads(body),
            }
        )
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")
        self.event.set()

    def log_message(self, *args):
        pass  # silence test output


def _serve_one_request() -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    return server, port


class NoOpWithoutConfig(unittest.TestCase):
    def test_start_run_never_makes_a_network_call_without_env(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("urllib.request.urlopen") as urlopen:
                run_id = start_run("linkedin-post-writer")
                self.assertTrue(run_id)  # still returns an id
                urlopen.assert_not_called()

    def test_finish_run_never_makes_a_network_call_without_env(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("urllib.request.urlopen") as urlopen:
                finish_run("some-id", "linkedin-post-writer", "completed")
                urlopen.assert_not_called()


class PostsToIngestEndpoint(unittest.TestCase):
    def setUp(self):
        _CapturingHandler.received = []
        _CapturingHandler.event = threading.Event()
        self.server, self.port = _serve_one_request()
        self.env = mock.patch.dict(
            "os.environ",
            {
                "DASHBOARD_EVENTS_URL": f"http://127.0.0.1:{self.port}",
                "EVENTS_INGEST_SECRET": "test-secret",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.server.server_close()

    def test_start_run_posts_running_status_with_bearer_auth(self):
        run_id = start_run("linkedin-post-writer", input_summary="Q3 hiring post")
        self.assertTrue(_CapturingHandler.event.wait(timeout=2), "server never received a request")

        [call] = _CapturingHandler.received
        self.assertEqual(call["path"], "/api/events")
        self.assertEqual(call["authorization"], "Bearer test-secret")
        self.assertEqual(call["json"]["id"], run_id)
        self.assertEqual(call["json"]["skill"], "linkedin-post-writer")
        self.assertEqual(call["json"]["status"], "running")
        self.assertEqual(call["json"]["inputSummary"], "Q3 hiring post")

    def test_finish_run_posts_outcome_and_decision(self):
        finish_run(
            "run-123",
            "linkedin-post-writer",
            "completed",
            decision="PAS formula",
            outcome="approved",
        )
        self.assertTrue(_CapturingHandler.event.wait(timeout=2), "server never received a request")

        [call] = _CapturingHandler.received
        self.assertEqual(call["json"]["id"], "run-123")
        self.assertEqual(call["json"]["status"], "completed")
        self.assertEqual(call["json"]["decision"], "PAS formula")
        self.assertEqual(call["json"]["outcome"], "approved")


if __name__ == "__main__":
    unittest.main()
