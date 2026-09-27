"""build_command's ABS-related flag wiring: --abs-url/--abs-api-key are for
direct-API metadata sync (sync_book_metadata) and the --trust-abs-metadata/
--weight-abs-metadata opt-ins -- an entirely separate concern from
req.provider (which search provider to use). Regression guard for a real bug
found while wiring the UI for these two flags: before the fix, credentials
were only passed when provider=="abs", so direct-API sync could never
activate with any other search provider selected, even with Audiobookshelf
fully configured.
"""
import unittest
from unittest.mock import patch

from app.main import RunRequest, build_command


class AbsCredentialWiringTests(unittest.TestCase):
    def _request(self, **overrides):
        base = dict(script_name="audible-metadata-fixer-v5.py", target_path="/audiobooks")
        base.update(overrides)
        return RunRequest(**base)

    def test_abs_credentials_passed_with_default_audible_provider_when_configured(self):
        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._get_abs_url", return_value="http://abs"):
            cmd, _ = build_command(self._request(provider="audible"))
        self.assertIn("--abs-url", cmd)
        self.assertIn("http://abs", cmd)
        self.assertIn("--abs-api-key", cmd)
        self.assertIn("key", cmd)
        # provider stays the default (never forced to "abs" just because
        # credentials are configured) -- explicit --provider abs is only
        # emitted when the user actually chose it as the search provider.
        self.assertNotIn("--provider", cmd)

    def test_no_abs_credentials_when_not_configured(self):
        with patch("app.main._get_abs_api_key", return_value=""):
            cmd, _ = build_command(self._request(provider="audible"))
        self.assertNotIn("--abs-url", cmd)
        self.assertNotIn("--abs-api-key", cmd)

    def test_provider_abs_still_passes_provider_flags_and_credentials(self):
        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._get_abs_url", return_value="http://abs"):
            cmd, _ = build_command(self._request(provider="abs", abs_provider="audible"))
        self.assertIn("--provider", cmd)
        self.assertIn("--abs-provider", cmd)
        self.assertIn("--abs-url", cmd)
        self.assertIn("--abs-api-key", cmd)

    def test_trust_abs_metadata_flag_passed(self):
        with patch("app.main._get_abs_api_key", return_value="key"):
            cmd, _ = build_command(self._request(trust_abs_metadata=True))
        self.assertIn("--trust-abs-metadata", cmd)
        self.assertNotIn("--weight-abs-metadata", cmd)

    def test_weight_abs_metadata_flag_passed(self):
        with patch("app.main._get_abs_api_key", return_value="key"):
            cmd, _ = build_command(self._request(weight_abs_metadata=True))
        self.assertIn("--weight-abs-metadata", cmd)
        self.assertNotIn("--trust-abs-metadata", cmd)

    def test_trust_takes_priority_if_both_somehow_set(self):
        with patch("app.main._get_abs_api_key", return_value="key"):
            cmd, _ = build_command(self._request(trust_abs_metadata=True, weight_abs_metadata=True))
        self.assertIn("--trust-abs-metadata", cmd)
        self.assertNotIn("--weight-abs-metadata", cmd)

    def test_neither_flag_by_default(self):
        with patch("app.main._get_abs_api_key", return_value="key"):
            cmd, _ = build_command(self._request())
        self.assertNotIn("--trust-abs-metadata", cmd)
        self.assertNotIn("--weight-abs-metadata", cmd)


if __name__ == "__main__":
    unittest.main()
