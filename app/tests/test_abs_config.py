"""Tests for ABS API-key config management (save/disconnect)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

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


class MetadataProviderUrlValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.abs_cfg = Path(self.tmp.name) / "abs.json"
        self.abs_agg_cfg = Path(self.tmp.name) / "abs-agg.json"
        self.abs_tract_cfg = Path(self.tmp.name) / "abs-tract.json"
        self.patchers = [
            patch("app.main.ABS_CONFIG_FILE", self.abs_cfg),
            patch("app.main.ABS_AGG_CONFIG_FILE", self.abs_agg_cfg),
            patch("app.main.ABS_TRACT_CONFIG_FILE", self.abs_tract_cfg),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tmp.cleanup()

    def test_abs_save_config_rejects_non_http_url(self):
        with self.assertRaises(HTTPException) as ctx:
            main.abs_save_config(main.AbsSaveConfigRequest(url="file:///etc/passwd", api_key="secret"))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_abs_agg_settings_reject_non_http_url(self):
        with self.assertRaises(HTTPException) as ctx:
            main.save_abs_agg_settings(main.AbsAggSettingsRequest(url="file:///etc/passwd"))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_abs_tract_settings_reject_non_http_url(self):
        with self.assertRaises(HTTPException) as ctx:
            main.save_abs_tract_settings(main.AbsTractSettingsRequest(url="file:///etc/passwd"))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_abs_tract_settings_allow_blank_url(self):
        result = main.save_abs_tract_settings(main.AbsTractSettingsRequest(url="", kindle_region="us"))

        self.assertEqual(result["url"], "")


if __name__ == "__main__":
    unittest.main()
