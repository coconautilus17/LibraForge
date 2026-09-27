"""redact_command(): --abs-api-key must never reach a log file, a persisted
report.json, or an API response in cleartext.

Found via a real run against the live Audiobookshelf instance: GET
/api/runs/{id} returned the actual ABS API key in plaintext inside the
"command" field, and the same cleartext value was also persisted to disk in
both the run's .log.txt and .report.json. This is a real, confirmed
credential exposure, not a theoretical one -- build_command now passes
--abs-api-key on nearly every fixer/organizer run (whenever Audiobookshelf is
configured at all, not just when the user selects it as the search
provider), which made an existing narrow exposure into a routine one.
"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.main import RunState, redact_command, runs, write_final_report

client = TestClient(main.app)


class RedactCommandTests(unittest.TestCase):
    def test_abs_api_key_value_is_redacted(self):
        cmd = ["python", "-u", "script.py", "/audiobooks", "--abs-api-key", "super-secret-token"]
        redacted = redact_command(cmd)
        self.assertNotIn("super-secret-token", redacted)
        self.assertIn("--abs-api-key", redacted)
        self.assertEqual(redacted[redacted.index("--abs-api-key") + 1], "***REDACTED***")

    def test_other_flags_are_untouched(self):
        cmd = ["python", "-u", "script.py", "/audiobooks", "--apply", "--min-score", "0.7"]
        self.assertEqual(redact_command(cmd), cmd)

    def test_does_not_mutate_the_original_list(self):
        cmd = ["--abs-api-key", "secret"]
        redact_command(cmd)
        self.assertEqual(cmd, ["--abs-api-key", "secret"])

    def test_flag_as_the_last_argument_is_left_alone_not_indexed_out_of_range(self):
        cmd = ["python", "script.py", "--abs-api-key"]
        # No following value to redact -- must not raise.
        self.assertEqual(redact_command(cmd), cmd)


class WriteFinalReportRedactsCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reports_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_persisted_report_json_never_contains_the_real_key(self):
        state = RunState(id="test-run-redact")
        state.command = ["python", "-u", "script.py", "--abs-api-key", "super-secret-token"]
        with patch.object(main, "REPORTS_DIR", self.reports_dir):
            write_final_report(state)
            content = (self.reports_dir / "test-run-redact.report.json").read_text(encoding="utf-8")
        self.assertNotIn("super-secret-token", content)
        self.assertIn("***REDACTED***", content)


class GetRunEndpointRedactsCommandTests(unittest.TestCase):
    def tearDown(self):
        runs.pop("test-run-live-redact", None)

    def test_live_run_status_never_returns_the_real_key(self):
        state = RunState(id="test-run-live-redact")
        state.command = ["python", "-u", "script.py", "--abs-api-key", "super-secret-token"]
        state.started_at = time.time()
        runs["test-run-live-redact"] = state
        resp = client.get("/api/runs/test-run-live-redact")
        self.assertEqual(resp.status_code, 200)
        body_text = resp.text
        self.assertNotIn("super-secret-token", body_text)
        self.assertIn("***REDACTED***", body_text)


if __name__ == "__main__":
    unittest.main()
