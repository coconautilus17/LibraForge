import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import title_noise_policy


class TitleNoisePolicyTests(unittest.TestCase):
    def test_defaults_match_and_remove_generic_subtitles(self):
        title_noise_policy.clear_title_noise_cache()

        self.assertTrue(title_noise_policy.is_title_noise("A Humorous Isekai LitRPG"))
        self.assertEqual(
            title_noise_policy.remove_trailing_title_noise(
                "Arrival - A Humorous Isekai LitRPG"
            ),
            "Arrival",
        )
        self.assertFalse(title_noise_policy.is_title_noise("The Opus"))

    def test_local_policy_can_disable_defaults_and_add_custom_pattern(self):
        with tempfile.TemporaryDirectory() as temporary:
            local_file = Path(temporary) / "title-noise.local.json"
            with patch.object(title_noise_policy, "LOCAL_POLICY_FILE", local_file):
                saved = title_noise_policy.save_title_noise_policy(
                    disabled_defaults=["generic-genre-marketing-subtitle"],
                    custom_patterns=[
                        {
                            "id": "custom-academy",
                            "label": "Academy subtitle",
                            "pattern": r"(?:a|an)\s+academy\s+litrpg",
                            "enabled": True,
                        }
                    ],
                )

                self.assertIn(
                    "generic-genre-marketing-subtitle",
                    saved["disabled_defaults"],
                )
                self.assertTrue(title_noise_policy.is_title_noise("An Academy LitRPG"))
                payload = json.loads(local_file.read_text(encoding="utf-8"))
                self.assertEqual(payload["custom_patterns"][0]["id"], "custom-academy")
        title_noise_policy.clear_title_noise_cache()

    def test_descriptor_that_completes_a_title_is_kept(self):
        # Regression (#352): "a LitRPG Apocalypse" is the object of "of", so
        # dropping it leaves a sentence fragment.
        title_noise_policy.clear_title_noise_cache()
        for title in (
            "Apocalypse BREAKER 2: Book 2 of a LitRPG Apocalypse",
            "Apocalypse BREAKER: Book 1 of a LitRPG Apocalypse",
            "Book 3 of a LitRPG Apocalypse",
        ):
            self.assertEqual(title_noise_policy.remove_trailing_title_noise(title), title)

    def test_descriptor_after_a_complete_title_is_still_removed(self):
        title_noise_policy.clear_title_noise_cache()
        self.assertEqual(
            title_noise_policy.remove_trailing_title_noise("Slime Keeper a LitRPG Adventure"),
            "Slime Keeper",
        )

    def test_dangling_end_word_detection(self):
        self.assertTrue(title_noise_policy.ends_with_dangling_word("Book 2 of"))
        self.assertTrue(title_noise_policy.ends_with_dangling_word("Carter &"))
        self.assertFalse(title_noise_policy.ends_with_dangling_word("Book 2"))
        self.assertFalse(title_noise_policy.ends_with_dangling_word(""))


class PolicyLoadingAndSavingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.default_file = self.dir / "default.json"
        self.local_file = self.dir / "local.json"
        self.patches = [
            patch.object(title_noise_policy, "DEFAULT_POLICY_FILE", self.default_file),
            patch.object(title_noise_policy, "LOCAL_POLICY_FILE", self.local_file),
        ]
        for p in self.patches:
            p.start()
        title_noise_policy.clear_title_noise_cache()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        title_noise_policy.clear_title_noise_cache()
        self.tmp.cleanup()

    def test_default_entries_without_an_id_or_pattern_or_not_objects_are_dropped(self):
        self.default_file.write_text(json.dumps({"patterns": [
            {"id": "ok", "pattern": "foo"}, {"id": "", "pattern": "x"}, {"id": "no-pattern"},
            {"pattern": "no-id"}, "not-a-dict"]}))
        loaded = title_noise_policy.load_title_noise_policy()
        self.assertEqual([p["id"] for p in loaded["patterns"] if p["source"] == "default"], ["ok"])

    def test_custom_entries_without_an_id_or_pattern_or_not_objects_are_dropped(self):
        self.default_file.write_text(json.dumps({"patterns": []}))
        self.local_file.write_text(json.dumps({"custom_patterns": [
            {"id": "custom-ok", "pattern": "foo"}, {"id": "custom-a"}, {"pattern": "p"}, 7]}))
        loaded = title_noise_policy.load_title_noise_policy()
        self.assertEqual([p["id"] for p in loaded["custom_patterns"]], ["custom-ok"])

    def test_a_disabled_default_is_marked_disabled_and_the_rest_enabled(self):
        self.default_file.write_text(json.dumps({"patterns": [
            {"id": "a", "pattern": "x"}, {"id": "b", "pattern": "y"}]}))
        self.local_file.write_text(json.dumps({"disabled_defaults": ["a"]}))
        enabled = {p["id"]: p["enabled"] for p in title_noise_policy.load_title_noise_policy()["patterns"] if p["source"] == "default"}
        self.assertEqual(enabled, {"a": False, "b": True})

    def test_saved_custom_pattern_label_defaults_to_its_id(self):
        self.default_file.write_text(json.dumps({"patterns": []}))
        saved = title_noise_policy.save_title_noise_policy(
            disabled_defaults=[],
            custom_patterns=[{"id": "foo", "pattern": "x+", "label": ""}, {"id": "bar", "pattern": "y+", "label": "Bar label"}])
        labels = {p["id"]: p["label"] for p in saved["custom_patterns"]}
        self.assertEqual(labels, {"custom-foo": "custom-foo", "custom-bar": "Bar label"})

    def test_saved_policy_file_is_versioned_and_round_trips(self):
        self.default_file.write_text(json.dumps({"patterns": []}))
        title_noise_policy.save_title_noise_policy(disabled_defaults=[], custom_patterns=[{"id": "foo", "pattern": "x+"}])
        payload = json.loads(self.local_file.read_text())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["custom_patterns"][0]["id"], "custom-foo")


class CloseDanglingBracketEdgeTests(unittest.TestCase):
    def test_opener_followed_only_by_whitespace_is_dropped_not_closed(self):
        self.assertEqual(title_noise_policy.close_dangling_bracket("Title ("), "Title")
        self.assertEqual(title_noise_policy.close_dangling_bracket("Title (   "), "Title")

    def test_opener_with_text_after_it_is_closed(self):
        self.assertEqual(title_noise_policy.close_dangling_bracket("Title (Part"), "Title (Part)")
        self.assertEqual(title_noise_policy.close_dangling_bracket("Title [a (b"), "Title [a (b)]")


if __name__ == "__main__":
    unittest.main()


class CloseDanglingBracketTests(unittest.TestCase):
    def test_closes_a_bracket_group_that_was_opened_and_never_closed(self):
        close = title_noise_policy.close_dangling_bracket
        self.assertEqual(close("Critias (Atlantis"), "Critias (Atlantis)")
        self.assertEqual(close("Last Day Of Socrates \u00a6 Crito (Justice"), "Last Day Of Socrates \u00a6 Crito (Justice)")
        self.assertEqual(close("Foo [Part 2"), "Foo [Part 2]")
        self.assertEqual(close("Foo (Part 1) (Bar"), "Foo (Part 1) (Bar)")

    def test_leaves_balanced_and_unrelated_titles_alone(self):
        close = title_noise_policy.close_dangling_bracket
        for title in ("Gorgias (Rhetoric)", "Plain Title", "Foo [Bar] (Baz)", "Smile :) later", ""):
            self.assertEqual(close(title), title)

    def test_drops_an_opening_bracket_with_nothing_after_it(self):
        self.assertEqual(title_noise_policy.close_dangling_bracket("Ion ("), "Ion")
