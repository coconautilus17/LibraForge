"""Tests for app.main's periodic bootstrap-file reconciliation tick.

Only the gating logic is exercised here -- the actual reconciliation work is
app.abs_client.reconcile_bootstrap_registry, already covered directly in
test_abs_client.py.
"""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class AbsBootstrapReconcileTickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reports_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, coro):
        return asyncio.run(coro)

    def test_no_api_key_never_reconciles(self):
        with patch.object(main, "_get_abs_api_key", return_value=""), \
             patch.object(main, "REPORTS_DIR", self.reports_dir), \
             patch.object(main, "reconcile_bootstrap_registry") as reconcile_mock:
            self._run(main._abs_bootstrap_reconcile_tick())
        reconcile_mock.assert_not_called()

    def test_empty_registry_never_reconciles(self):
        with patch.object(main, "_get_abs_api_key", return_value="key"), \
             patch.object(main, "REPORTS_DIR", self.reports_dir), \
             patch.object(main, "reconcile_bootstrap_registry") as reconcile_mock:
            self._run(main._abs_bootstrap_reconcile_tick())
        reconcile_mock.assert_not_called()

    def test_configured_and_pending_calls_reconcile(self):
        from app.abs_client import upsert_bootstrapped_file
        upsert_bootstrapped_file(self.reports_dir, self.reports_dir / "book" / "metadata.json", "ASIN1", "/x")
        with patch.object(main, "_get_abs_api_key", return_value="key"), \
             patch.object(main, "_get_abs_url", return_value="http://abs"), \
             patch.object(main, "REPORTS_DIR", self.reports_dir), \
             patch.object(main, "reconcile_bootstrap_registry") as reconcile_mock:
            self._run(main._abs_bootstrap_reconcile_tick())
        reconcile_mock.assert_called_once()
        self.assertEqual(reconcile_mock.call_args[0][0], self.reports_dir)

    def test_exception_during_reconcile_is_swallowed(self):
        from app.abs_client import upsert_bootstrapped_file
        upsert_bootstrapped_file(self.reports_dir, self.reports_dir / "book" / "metadata.json", "ASIN1", "/x")
        with patch.object(main, "_get_abs_api_key", return_value="key"), \
             patch.object(main, "_get_abs_url", return_value="http://abs"), \
             patch.object(main, "REPORTS_DIR", self.reports_dir), \
             patch.object(main, "reconcile_bootstrap_registry", side_effect=RuntimeError("boom")):
            self._run(main._abs_bootstrap_reconcile_tick())  # must not raise


if __name__ == "__main__":
    unittest.main()
