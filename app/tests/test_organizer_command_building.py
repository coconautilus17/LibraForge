import unittest
from unittest.mock import patch

from app.main import OrganizerRunRequest, build_organizer_command


class OrganizerCommandTrustAbsMetadataTests(unittest.TestCase):
    def test_trust_abs_metadata_passes_flag_and_credentials_when_configured(self):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized", trust_abs_metadata=True)
        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._get_abs_url", return_value="http://abs"):
            cmd = build_organizer_command(req)
        self.assertIn("--trust-abs-metadata", cmd)
        self.assertIn("--abs-url", cmd)
        self.assertIn("http://abs", cmd)
        self.assertIn("--abs-api-key", cmd)
        self.assertIn("key", cmd)

    def test_trust_abs_metadata_off_by_default(self):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized")
        with patch("app.main._get_abs_api_key", return_value="key"):
            cmd = build_organizer_command(req)
        self.assertNotIn("--trust-abs-metadata", cmd)
        self.assertNotIn("--abs-url", cmd)

    def test_trust_abs_metadata_requested_but_not_configured_omits_everything(self):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized", trust_abs_metadata=True)
        with patch("app.main._get_abs_api_key", return_value=""):
            cmd = build_organizer_command(req)
        self.assertNotIn("--trust-abs-metadata", cmd)
        self.assertNotIn("--abs-url", cmd)


class OrganizerCommandSkipPatternsTests(unittest.TestCase):
    def test_no_skip_patterns_adds_no_flags(self):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized")
        cmd = build_organizer_command(req)
        self.assertNotIn("--skip-pattern", cmd)

    def test_each_skip_pattern_becomes_its_own_flag(self):
        req = OrganizerRunRequest(
            root_path="/audiobooks/_unorganized",
            skip_patterns=["Casual Farming", "Some Other Series"],
        )
        cmd = build_organizer_command(req)
        skip_flag_indices = [i for i, arg in enumerate(cmd) if arg == "--skip-pattern"]
        self.assertEqual(len(skip_flag_indices), 2)
        values = [cmd[i + 1] for i in skip_flag_indices]
        self.assertEqual(values, ["Casual Farming", "Some Other Series"])


if __name__ == "__main__":
    unittest.main()
