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


class InstallStateReadWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.reports, self.auth = base / "reports", base / "auth"
        self.reports.mkdir()
        self.auth.mkdir()
        self.state = self.reports / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_returns_the_state_it_wrote(self):
        state = ins.init_install_state("0.2.5", self.reports, self.auth, [], self.state)
        self.assertEqual(state["first_seen_version"], "0.2.5")
        self.assertEqual(json.loads(self.state.read_text())["first_seen_version"], "0.2.5")

    def test_a_second_init_returns_the_stored_state_not_a_new_one(self):
        ins.init_install_state("0.2.5", self.reports, self.auth, [], self.state)
        again = ins.init_install_state("9.9.9", self.reports, self.auth, [], self.state)
        self.assertEqual(again["first_seen_version"], "0.2.5")

    def test_a_state_file_with_another_schema_version_is_replaced(self):
        self.state.write_text(json.dumps({"schema_version": 2, "first_seen_version": "old"}))
        state = ins.init_install_state("0.2.5", self.reports, self.auth, [], self.state)
        self.assertEqual((state["schema_version"], state["first_seen_version"]), (1, "0.2.5"))

    def test_a_state_file_that_is_not_an_object_is_replaced(self):
        self.state.write_text("[1, 2]")
        state = ins.init_install_state("0.2.5", self.reports, self.auth, [], self.state)
        self.assertEqual(state["schema_version"], 1)

    def test_update_state_merges_persists_and_returns_the_result(self):
        ins.init_install_state("0.2.5", self.reports, self.auth, [], self.state)
        result = ins.update_state({"author_notice_pending": False, "extra": 1}, self.state)
        self.assertEqual(result["extra"], 1)
        self.assertEqual(result["first_seen_version"], "0.2.5")
        self.assertEqual(json.loads(self.state.read_text()), result)

    def test_update_state_without_a_file_starts_a_versioned_state(self):
        result = ins.update_state({"k": "v"}, self.state)
        self.assertEqual(result, {"schema_version": 1, "k": "v"})

    def test_writes_create_the_parent_folder_and_leave_no_temp_file(self):
        nested = self.reports / "deep" / "state.json"
        ins.update_state({"k": 1}, nested)
        self.assertEqual([p.name for p in nested.parent.iterdir()], ["state.json"])


if __name__ == "__main__":
    unittest.main()
