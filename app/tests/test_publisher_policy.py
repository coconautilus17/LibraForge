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

    def test_learn_skips_names_that_are_authors(self):
        # "publisher" tags that are really author/narrator names must not be learned.
        result = pp.learn_publishers(
            ["Acme Audio", "William D Arand", "Logan Jacobs"],
            exclude_names=["William D. Arand", "Logan Jacobs"],
        )
        self.assertIsNotNone(result)
        learned = [e["name"] for e in pp.load_publisher_policy()["custom_publishers"] if e["source"] == "learned"]
        self.assertEqual(learned, ["Acme Audio"])
        # The author names were not added even with punctuation/spacing differences.
        self.assertIsNone(pp.match_canonical_publisher("William D Arand"))
        self.assertIsNone(pp.match_canonical_publisher("Logan Jacobs"))

    def test_learn_keeps_author_named_company(self):
        # A real publisher that merely contains an author's name (with a company
        # suffix) is still learned -- only an exact name match is excluded.
        result = pp.learn_publishers(
            ["Michael Chatfield Publications Inc."],
            exclude_names=["Michael Chatfield"],
        )
        self.assertIsNotNone(result)
        learned = [e["name"] for e in pp.load_publisher_policy()["custom_publishers"] if e["source"] == "learned"]
        self.assertEqual(learned, ["Michael Chatfield Publications Inc."])

    def test_learned_entries_that_now_ship_as_known_patterns_show_once(self):
        self._local.write_text(json.dumps({"schema_version": 1, "disabled_defaults": [], "custom_publishers": [
            {"id": "tantor-audio-x", "name": "tantor audio", "source": "learned"},
            {"id": "tantor-graphic", "name": "Tantor Audio, Graphic Audio", "source": "learned"},
            {"id": "acme", "name": "Acme Audio", "source": "learned"},
        ]}), encoding="utf-8")
        policy = pp.load_publisher_policy()
        self.assertEqual([e["name"] for e in policy["custom_publishers"]], ["Acme Audio"])
        self.assertEqual(sum(1 for e in policy["publishers"] if e["name"].lower() == "tantor audio"), 1)

    def test_learn_never_treats_independently_published_as_a_publisher(self):
        self.assertIsNone(pp.learn_publishers(["Independently published", "Self-published"]))
        self.assertEqual(pp.load_publisher_policy()["custom_publishers"], [])

    def test_shipped_defaults_carry_the_formerly_learned_publishers(self):
        shipped = json.loads((Path(__file__).parents[2] / "config" / "publishers.default.json").read_text(encoding="utf-8"))
        names = {entry["name"] for entry in shipped["publishers"]}
        for name in ("Aethon Audio", "Mountaindale Press", "Hidden Infinity", "Seven Seas Entertainment", "Seven Seas Siren"):
            self.assertIn(name, names)
        self.assertNotIn("Independently published", names)
        self.assertNotIn("Seven Seas Entertainment, Seven Seas Siren", names)

    def test_normalize_publisher_key_ignores_punctuation(self):
        self.assertEqual(
            pp.normalize_publisher_key("William D. Arand"),
            pp.normalize_publisher_key("William D Arand"),
        )

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


class PublisherCatalogDetailTests(unittest.TestCase):
    setUp = PublisherPolicyTests.setUp
    tearDown = PublisherPolicyTests.tearDown

    def _write_local(self, payload):
        self._local.write_text(json.dumps(payload), encoding="utf-8")
        pp.clear_publisher_cache()

    def load(self):
        return pp.load_publisher_policy()

    def test_default_entry_without_an_id_gets_a_slug_of_its_name(self):
        seed = {"publishers": [{"name": "Brilliance Audio"}]}
        self._default.write_text(json.dumps(seed))
        pp.clear_publisher_cache()
        self.assertEqual(self.load()["publishers"][0]["id"], "brilliance-audio")

    def test_custom_entry_enabled_flag_is_respected_and_defaults_to_on(self):
        self._write_local({"custom_publishers": [
            {"name": "On Press"}, {"name": "Off Press", "enabled": False}]})
        by_name = {e["name"]: e["enabled"] for e in self.load()["publishers"] if e["source"] != "default"}
        self.assertEqual(by_name, {"On Press": True, "Off Press": False})

    def test_custom_entries_keep_learned_provenance_but_other_sources_become_custom(self):
        self._write_local({"custom_publishers": [
            {"name": "Learned One", "source": "learned"}, {"name": "Weird One", "source": "imported"},
            {"name": "Plain One"}]})
        sources = {e["name"]: e["source"] for e in self.load()["publishers"] if e["name"] != "Tantor Audio"
                   and e["source"] != "default"}
        self.assertEqual(sources, {"Learned One": "learned", "Weird One": "custom", "Plain One": "custom"})

    def test_a_custom_entry_that_a_default_already_ships_is_hidden(self):
        self._write_local({"custom_publishers": [{"name": "Tantor"}, {"name": "Tantor Audio, Graphic Audio"}]})
        custom = [e for e in self.load()["publishers"] if e["source"] != "default"]
        self.assertEqual(custom, [])

    def test_save_derives_the_id_from_the_name_and_rejects_duplicates_and_nameless(self):
        saved = pp.save_publisher_policy(disabled_defaults=[], custom_publishers=[{"name": "New House"}])
        self.assertEqual([e["id"] for e in saved["custom_publishers"]], ["new-house"])
        with self.assertRaisesRegex(ValueError, "Duplicate publisher id"):
            pp.save_publisher_policy(disabled_defaults=[], custom_publishers=[
                {"name": "A", "id": "x"}, {"name": "B", "id": "x"}])
        with self.assertRaisesRegex(ValueError, "needs a name"):
            pp.save_publisher_policy(disabled_defaults=[], custom_publishers=[{"name": "  "}])

    def test_save_keeps_an_explicit_id_and_the_enabled_flag(self):
        saved = pp.save_publisher_policy(disabled_defaults=[], custom_publishers=[
            {"name": "Zed", "id": "custom-zed", "enabled": False}])
        entry = saved["custom_publishers"][0]
        self.assertEqual((entry["id"], entry["enabled"]), ("custom-zed", False))

    def test_saved_entry_without_an_enabled_flag_is_enabled(self):
        saved = pp.save_publisher_policy(disabled_defaults=[], custom_publishers=[{"name": "Zed"}])
        self.assertIs(saved["custom_publishers"][0]["enabled"], True)

    def test_non_ascii_names_are_stored_readably(self):
        pp.save_publisher_policy(disabled_defaults=[], custom_publishers=[{"name": "Éditions Gallimard", "id": "gal"}])
        self.assertIn("Éditions Gallimard", self._local.read_text(encoding="utf-8"))

    def test_the_loaded_policy_reports_its_schema_version(self):
        self.assertEqual(self.load()["schema_version"], 1)

    def test_saved_catalog_file_is_versioned_pretty_json_with_a_trailing_newline(self):
        pp.save_publisher_policy(disabled_defaults=[], custom_publishers=[{"name": "Zed"}])
        text = self._local.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text)["schema_version"], 1)
        self.assertTrue(text.endswith("\n"))
        self.assertIn("\n  ", text)

    def test_learned_entries_get_a_slug_id_and_enabled_learned_provenance(self):
        result = pp.learn_publishers(["Acme Audio"])
        entry = [e for e in result["custom_publishers"] if e["name"] == "Acme Audio"][0]
        self.assertEqual((entry["id"], entry["source"], entry["enabled"], entry["aliases"]),
                         ("acme-audio", "learned", True, []))

    def test_a_name_with_no_slug_characters_still_gets_a_learned_id(self):
        result = pp.learn_publishers(["***"])
        self.assertEqual(result["custom_publishers"][0]["id"], "learned-0")

    def test_two_learned_names_with_the_same_slug_get_distinct_ids(self):
        result = pp.learn_publishers(["Acme Audio", "Acme  Audio!"])
        ids = [e["id"] for e in result["custom_publishers"]]
        self.assertEqual(len(set(ids)), len(ids))

    def test_learning_nothing_new_returns_none(self):
        self.assertIsNone(pp.learn_publishers(["Tantor Audio", "tantor", ""]))
        self.assertIsNone(pp.learn_publishers([]))

    def test_learning_skips_names_that_are_people_in_the_run(self):
        self.assertIsNone(pp.learn_publishers(["Jane Doe"], exclude_names=["Jane Doe"]))


if __name__ == "__main__":
    unittest.main()
