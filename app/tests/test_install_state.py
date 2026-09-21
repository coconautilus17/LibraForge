import json
import tempfile
import unittest
from pathlib import Path

from app import install_state as ins


class InstallStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.reports, self.auth, self.config, self.settings = base / "reports", base / "auth", base / "config", base / "settings"
        for directory in (self.reports, self.auth, self.config, self.settings):
            directory.mkdir()
        (self.config / "publishers.default.json").write_text("{}")
        self.state = self.reports / ".install-state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def init(self, version="0.2.5"):
        return ins.init_install_state(version, self.reports, self.auth, [self.config, self.settings], self.state)

    def test_empty_volumes_are_a_fresh_install_with_the_scheme_on(self):
        state = self.init()
        self.assertEqual(state["origin"], "fresh")
        self.assertTrue(state["author_scheme_enabled"])
        self.assertFalse(state["author_notice_pending"])

    def test_old_reports_mean_an_upgrade_with_the_scheme_off_and_a_notice(self):
        (self.reports / "20260701-abc.report.json").write_text("{}")
        state = self.init()
        self.assertEqual(state["origin"], "upgraded")
        self.assertFalse(state["author_scheme_enabled"])
        self.assertTrue(state["author_notice_pending"])

    def test_dotfile_caches_in_reports_count_as_prior_use(self):
        (self.reports / ".disk-asin-cache.json").write_text("{}")
        self.assertEqual(self.init()["origin"], "upgraded")

    def test_audible_auth_means_an_upgrade(self):
        (self.auth / "audible.json").write_text("{}")
        self.assertEqual(self.init()["origin"], "upgraded")

    def test_saved_local_settings_mean_an_upgrade(self):
        (self.config / "publishers.local.json").write_text("{}")
        self.assertEqual(self.init()["origin"], "upgraded")

    def test_settings_saved_in_the_settings_volume_mean_an_upgrade(self):
        (self.settings / "abs.json").write_text("{}")
        self.assertEqual(self.init()["origin"], "upgraded")

    def test_the_marker_itself_is_not_prior_use(self):
        self.init()
        self.assertEqual(ins.detect_origin(self.reports, self.auth, [self.config, self.settings]), "fresh")

    def test_decision_is_made_once_and_survives_later_starts(self):
        (self.reports / "old.report.json").write_text("{}")
        first = self.init("0.2.5")
        (self.reports / "another.report.json").write_text("{}")
        second = self.init("0.2.6")
        self.assertEqual(first, second)
        self.assertEqual(second["first_seen_version"], "0.2.5")

    def test_corrupt_marker_with_prior_use_is_treated_as_an_upgrade(self):
        (self.reports / "old.report.json").write_text("{}")
        self.state.write_text("{oops")
        self.assertEqual(self.init()["origin"], "upgraded")

    def test_acknowledging_the_notice_and_toggling_are_persisted(self):
        (self.reports / "old.report.json").write_text("{}")
        self.init()
        ins.update_state({"author_notice_pending": False, "author_scheme_enabled": True}, self.state)
        data = json.loads(self.state.read_text())
        self.assertFalse(data["author_notice_pending"])
        self.assertTrue(data["author_scheme_enabled"])
        self.assertEqual(data["origin"], "upgraded")


if __name__ == "__main__":
    unittest.main()
