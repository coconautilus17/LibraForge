"""Endpoint tests for the Author names settings and the first-run install state."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import author_names, install_state, main

client = TestClient(main.app)


class AuthorNamesApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.state_file = base / ".install-state.json"
        self.patches = [
            mock.patch.object(author_names, "LOCAL_POLICY_FILE", base / "author-names.local.json"),
            mock.patch.object(author_names, "STATE_FILE", self.state_file),
        ]
        for patch in self.patches:
            patch.start()
        os.environ.pop("LIBRAFORGE_AUTHOR_SCHEME", None)

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def test_get_lists_known_patterns_and_defaults_to_scheme_off(self):
        data = client.get("/api/settings/author-names").json()
        self.assertEqual({e["name"] for e in data["names"] if e["source"] == "default"}, {"Mashton XX", "Mashton XY"})
        self.assertFalse(data["scheme_enabled"])
        self.assertFalse(data["notice_pending"])

    def test_put_saves_private_patterns_and_the_switch(self):
        response = client.put("/api/settings/author-names", json={
            "disabled_defaults": ["mashton-xy"],
            "custom_names": [{"name": "TJ Klune", "spelling": "TJ Klune"}],
            "scheme_enabled": True,
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["scheme_enabled"])
        custom = [e for e in data["names"] if e["source"] == "custom"]
        self.assertEqual([(e["name"], e["spelling"]) for e in custom], [("TJ Klune", "TJ Klune")])
        self.assertFalse(next(e for e in data["names"] if e["id"] == "mashton-xy")["enabled"])
        self.assertTrue(author_names.scheme_enabled())
        self.assertEqual(author_names.format_person_name("T J Klune"), "TJ Klune")

    def test_a_partial_put_leaves_everything_else_alone(self):
        client.put("/api/settings/author-names", json={
            "disabled_defaults": ["mashton-xy"], "custom_names": [{"name": "TJ Klune", "spelling": "TJ Klune"}]})
        toggled = client.put("/api/settings/author-names", json={"scheme_enabled": True}).json()
        self.assertTrue(toggled["scheme_enabled"])
        self.assertEqual([e["name"] for e in toggled["names"] if e["source"] == "custom"], ["TJ Klune"])
        self.assertFalse(next(e for e in toggled["names"] if e["id"] == "mashton-xy")["enabled"])
        after = client.put("/api/settings/author-names", json={"custom_names": []}).json()
        self.assertTrue(after["scheme_enabled"])
        self.assertEqual([e for e in after["names"] if e["source"] == "custom"], [])
        self.assertFalse(next(e for e in after["names"] if e["id"] == "mashton-xy")["enabled"])

    def test_bad_pattern_is_a_400(self):
        response = client.put("/api/settings/author-names", json={
            "custom_names": [{"name": "TJ Klune", "spelling": "Somebody Else"}]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("same letters", response.json()["detail"])

    def test_upgrade_notice_is_reported_then_acknowledged(self):
        base = Path(self.tmp.name)
        reports, auth, config = base / "reports", base / "auth", base / "config"
        for d in (reports, auth, config):
            d.mkdir()
        (reports / "old.report.json").write_text("{}")
        install_state.init_install_state("0.2.5", reports, auth, [config], self.state_file)
        view = client.get("/api/install-state").json()
        self.assertEqual((view["origin"], view["author_scheme_enabled"], view["author_notice_pending"]), ("upgraded", False, True))
        self.assertTrue(client.get("/api/settings/author-names").json()["notice_pending"])
        acked = client.post("/api/install-state/ack-author-notice").json()
        self.assertFalse(acked["author_notice_pending"])
        self.assertFalse(acked["author_scheme_enabled"])


if __name__ == "__main__":
    unittest.main()
