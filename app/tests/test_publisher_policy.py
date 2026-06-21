import json
import tempfile
import unittest
from pathlib import Path

from app import publisher_policy as pp


DEFAULT_SEED = {
    "schema_version": 1,
    "publishers": [
        {"id": "tantor-audio", "name": "Tantor Audio", "aliases": ["Tantor"]},
        {
            "id": "graphicaudio",
            "name": "Graphic Audio",
            "aliases": ["GraphicAudio"],
            "special_provider": "graphicaudio",
        },
        {
            "id": "soundbooth-theater",
            "name": "Soundbooth Theater",
            "special_provider": "soundbooththeater",
        },
    ],
}


class PublisherPolicyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._default = tmp / "publishers.default.json"
        self._local = tmp / "publishers.local.json"
        self._default.write_text(json.dumps(DEFAULT_SEED), encoding="utf-8")
        # Redirect the module to the temp catalog and reset its cache.
        self._orig_default = pp.DEFAULT_POLICY_FILE
        self._orig_local = pp.LOCAL_POLICY_FILE
        pp.DEFAULT_POLICY_FILE = self._default
        pp.LOCAL_POLICY_FILE = self._local
        pp.clear_publisher_cache()

    def tearDown(self):
        pp.DEFAULT_POLICY_FILE = self._orig_default
        pp.LOCAL_POLICY_FILE = self._orig_local
        pp.clear_publisher_cache()
        self._tmp.cleanup()

    def test_strip_removes_known_tokens(self):
        self.assertEqual(pp.strip_publisher_noise("John Smith, Tantor Audio"), "John Smith")
        self.assertEqual(pp.strip_publisher_noise("The Hobbit GraphicAudio"), "The Hobbit")

    def test_match_and_special_provider(self):
        self.assertEqual(pp.match_canonical_publisher("Tantor")["id"], "tantor-audio")
        self.assertEqual(pp.special_provider_for("Graphic Audio"), "graphicaudio")
        self.assertEqual(pp.special_provider_for("Soundbooth Theater"), "soundbooththeater")
        self.assertIsNone(pp.special_provider_for("Tantor Audio"))

    def test_learn_appends_unseen_publisher(self):
        self.assertIsNone(pp.match_canonical_publisher("Acme Audio"))
        result = pp.learn_publishers(["Acme Audio", "Tantor Audio"])  # second is known
        self.assertIsNotNone(result)
        # New publisher now recognized; known one was not duplicated.
        self.assertIsNotNone(pp.match_canonical_publisher("Acme Audio"))
        learned = [e for e in pp.load_publisher_policy()["custom_publishers"] if e["source"] == "learned"]
        self.assertEqual([e["name"] for e in learned], ["Acme Audio"])

    def test_save_roundtrips_disabled_and_custom(self):
        pp.save_publisher_policy(
            disabled_defaults=["tantor-audio"],
            custom_publishers=[
                {"name": "Acme Audio", "special_provider": None, "enabled": True}
            ],
        )
        policy = pp.load_publisher_policy()
        self.assertIn("tantor-audio", policy["disabled_defaults"])
        # Disabled default no longer strips.
        self.assertEqual(pp.strip_publisher_noise("X Tantor Audio"), "X Tantor Audio")
        self.assertEqual([e["name"] for e in policy["custom_publishers"]], ["Acme Audio"])

    def test_save_rejects_unknown_special_provider(self):
        with self.assertRaises(ValueError):
            pp.save_publisher_policy(
                disabled_defaults=[],
                custom_publishers=[{"name": "Bad", "special_provider": "nope"}],
            )


if __name__ == "__main__":
    unittest.main()
