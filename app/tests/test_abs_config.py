"""Tests for ABS API-key config management (save/disconnect)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class AbsDisconnectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "abs.json"
        self._p = patch("app.main.ABS_CONFIG_FILE", self.cfg)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()

    def test_disconnect_removes_key_but_keeps_url(self):
        self.cfg.write_text(json.dumps({"url": "http://abs", "api_key": "secret"}), encoding="utf-8")
        with patch("app.main._ABS_API_KEY_DEFAULT", ""):
            result = main.abs_disconnect()
        self.assertTrue(result["ok"])
        self.assertFalse(result["env_key_present"])
        saved = json.loads(self.cfg.read_text())
        self.assertNotIn("api_key", saved)
        self.assertEqual(saved.get("url"), "http://abs")

    def test_disconnect_reports_env_key(self):
        self.cfg.write_text(json.dumps({"url": "http://abs", "api_key": "secret"}), encoding="utf-8")
        with patch("app.main._ABS_API_KEY_DEFAULT", "env-secret"):
            result = main.abs_disconnect()
        self.assertTrue(result["env_key_present"])


if __name__ == "__main__":
    unittest.main()
