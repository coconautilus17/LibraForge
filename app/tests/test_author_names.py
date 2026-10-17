import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import author_names as an

PERSON_CASES = {
    "V A Lewis": "V.A. Lewis", "V.A. Lewis": "V.A. Lewis", "V.A Lewis": "V.A. Lewis",
    "J R R Tolkien": "J.R.R. Tolkien", "J.R.R Tolkien": "J.R.R. Tolkien", "J. R. R. Tolkien": "J.R.R. Tolkien",
    "JRR Tolkien": "J.R.R. Tolkien", "J.K.Rowling": "J.K. Rowling", "C.S.Lewis": "C.S. Lewis",
    "JK Rowling": "J.K. Rowling", "TJ Klune": "T.J. Klune", "AJ Hackwith": "A.J. Hackwith", "DJ Lucas": "D.J. Lucas",
    "Kevin J Anderson": "Kevin J. Anderson", "Kevin J. Anderson": "Kevin J. Anderson",
    "George R. R. Martin": "George R.R. Martin", "James S. A. Corey": "James S.A. Corey",
    "Ursula K Le Guin": "Ursula K. Le Guin", "E. D. deBirmingham": "E.D. deBirmingham", "A. F. Kay": "A.F. Kay",
    "P.D. James": "P.D. James", "John Smith III": "John Smith III", "William Strunk Jr": "William Strunk Jr",
    "Mashton XX": "Mashton XX", "Mashton X X": "Mashton XX", "Brian McClellan": "Brian McClellan",
    "St. John Mandel": "St. John Mandel", "Comedian0 L": "Comedian0 L", "Handle7 X Smith": "Handle7 X Smith",
    "A. F. Kay - translator": "A.F. Kay - translator", "Arthur Stone - translator": "Arthur Stone - translator", "": "",
}
CREDIT_CASES = {
    "A. F. Kay, Mikhail Yagupov - translator": "A.F. Kay, Mikhail Yagupov - translator",
    "Landon Scott, Adam Sage": "Landon Scott, Adam Sage",
    "J R R Tolkien and C S Lewis": "J.R.R. Tolkien and C.S. Lewis",
    "TheFirstDefier; JF Brink": "TheFirstDefier; J.F. Brink",
    "V A Lewis & Kevin J Anderson": "V.A. Lewis & Kevin J. Anderson",
}
# What the shipped (legacy) rule returns; generated from the pre-change function.


class WithTempPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(an, "LOCAL_POLICY_FILE", base / "author-names.local.json"),
            mock.patch.object(an, "STATE_FILE", base / ".install-state.json"),
            mock.patch.dict(os.environ, {}, clear=False),
        ]
        for patch in self.patches:
            patch.start()
        os.environ.pop("LIBRAFORGE_AUTHOR_SCHEME", None)

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()


class SchemeRuleTests(WithTempPolicy):
    def test_person_names(self):
        for raw, expected in PERSON_CASES.items():
            with self.subTest(raw=raw):
                self.assertEqual(an.format_person_name(raw), expected)

    def test_credits(self):
        for raw, expected in CREDIT_CASES.items():
            with self.subTest(raw=raw):
                self.assertEqual(an.format_author_credit(raw), expected)

    def test_idempotent(self):
        for raw in PERSON_CASES:
            once = an.format_person_name(raw)
            self.assertEqual(an.format_person_name(once), once, raw)



class PublisherAcronymTests(unittest.TestCase):
    def test_a_known_publisher_acronym_is_never_read_as_initials(self):
        self.assertEqual(
            an.format_author_credit("BBC - Andrew Marshall & John Lloyd"),
            "BBC - Andrew Marshall & John Lloyd",
        )
        self.assertEqual(
            an.format_author_credit("BBC - Paul Barnhill & Neil Warhurst"),
            "BBC - Paul Barnhill & Neil Warhurst",
        )

    def test_real_initials_that_are_not_a_known_publisher_are_unaffected(self):
        self.assertEqual(an.format_person_name("JD Kirk"), "J.D. Kirk")
        self.assertEqual(an.format_person_name("TW Brown"), "T.W. Brown")


class PatternPolicyTests(WithTempPolicy):
    def test_known_patterns_ship_with_the_real_exceptions(self):
        names = {e["name"]: e for e in an.load_author_policy()["names"] if e["source"] == "default"}
        self.assertEqual(set(names), {"Mashton XX", "Mashton XY", "Comedian0 L"})
        self.assertTrue(all(e["enabled"] for e in names.values()))

    def test_a_name_with_a_digit_is_never_read_as_initials(self):
        an.save_author_policy(["comedian0-l"], [])
        self.assertEqual(an.format_person_name("Comedian0 L"), "Comedian0 L")
        self.assertEqual(an.format_person_name("Comedian0 L - narrator"), "Comedian0 L - narrator")

    def test_private_pattern_keeps_a_spelling_for_every_variant(self):
        self.assertEqual(an.format_person_name("TJ Klune"), "T.J. Klune")
        an.save_author_policy([], [{"name": "TJ Klune", "spelling": "TJ Klune"}])
        for variant in ("TJ Klune", "T J Klune", "T.J. Klune", "tj klune"):
            self.assertEqual(an.format_person_name(variant), "TJ Klune", variant)
        self.assertEqual(an.format_person_name("TJ Klune - narrator"), "TJ Klune - narrator")

    def test_disabling_a_known_pattern_stops_it_applying(self):
        self.assertEqual(an.format_person_name("Mashton X X"), "Mashton XX")
        an.save_author_policy(["mashton-xx"], [])
        self.assertEqual(an.format_person_name("Mashton X X"), "Mashton X.X.")

    def test_disabled_private_pattern_is_ignored(self):
        an.save_author_policy([], [{"name": "TJ Klune", "spelling": "TJ Klune", "enabled": False}])
        self.assertEqual(an.format_person_name("TJ Klune"), "T.J. Klune")

    def test_a_pattern_can_only_choose_a_spelling(self):
        with self.assertRaises(ValueError):
            an.save_author_policy([], [{"name": "TJ Klune", "spelling": "Somebody Else"}])

    def test_duplicates_and_blanks_are_rejected(self):
        with self.assertRaises(ValueError):
            an.save_author_policy([], [{"name": "TJ Klune", "spelling": "TJ Klune"}, {"name": "T.J. Klune", "spelling": "T.J. Klune"}])
        with self.assertRaises(ValueError):
            an.save_author_policy([], [{"name": "", "spelling": ""}])

    def test_local_file_shape_matches_the_other_policies(self):
        an.save_author_policy(["mashton-xy"], [{"name": "TJ Klune", "spelling": "TJ Klune"}])
        data = json.loads(an.LOCAL_POLICY_FILE.read_text())
        self.assertEqual(set(data), {"schema_version", "disabled_defaults", "custom_names"})
        self.assertEqual(data["disabled_defaults"], ["mashton-xy"])


class InitialsOnlyChangeTests(unittest.TestCase):
    def test_only_formatting_differences_count(self):
        self.assertTrue(an.initials_only_change("V A Lewis", "V.A. Lewis"))
        self.assertTrue(an.initials_only_change("A. F. Kay, Yagupov", "A.F. Kay, Yagupov"))
        self.assertFalse(an.initials_only_change("V.A. Lewis", "V.A. Lewis"))
        self.assertFalse(an.initials_only_change("V A Lewis", "Brian McClellan"))
        self.assertFalse(an.initials_only_change("", "V.A. Lewis"))


class SchemeSwitchTests(WithTempPolicy):
    def test_off_by_default_and_leaves_author_text_alone(self):
        self.assertFalse(an.scheme_enabled())
        self.assertEqual(an.output_author_credit("A. F. Kay, TJ Klune"), "A. F. Kay, TJ Klune")

    def test_state_file_turns_it_on(self):
        an.STATE_FILE.write_text(json.dumps({"schema_version": 1, "author_scheme_enabled": True}))
        self.assertTrue(an.scheme_enabled())
        self.assertEqual(an.output_author_credit("A. F. Kay, TJ Klune"), "A.F. Kay, T.J. Klune")

    def test_env_override_wins_either_way(self):
        an.STATE_FILE.write_text(json.dumps({"schema_version": 1, "author_scheme_enabled": True}))
        os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = "legacy"
        self.assertFalse(an.scheme_enabled())
        os.environ["LIBRAFORGE_AUTHOR_SCHEME"] = "universal"
        an.STATE_FILE.write_text(json.dumps({"schema_version": 1, "author_scheme_enabled": False}))
        self.assertTrue(an.scheme_enabled())

    def test_unreadable_state_means_off(self):
        an.STATE_FILE.write_text("{not json")
        self.assertFalse(an.scheme_enabled())


class PolicyEntryTests(WithTempPolicy):
    def _write_default(self, payload):
        path = Path(self.tmp.name) / "default.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        patcher = mock.patch.object(an, "DEFAULT_POLICY_FILE", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_local(self, payload):
        an.LOCAL_POLICY_FILE.write_text(json.dumps(payload), encoding="utf-8")

    def test_an_entry_needs_both_a_name_and_a_spelling(self):
        self._write_default({"names": [
            {"name": "Only Name"}, {"spelling": "Only Spelling"}, {"name": "", "spelling": "X"},
            {"name": "Full Name", "spelling": "Full Name"}, "junk"]})
        self.assertEqual([e["name"] for e in an.load_author_policy()["names"]], ["Full Name"])

    def test_label_defaults_to_the_spelling_and_id_to_source_plus_name_key(self):
        self._write_default({"names": [{"name": "Ann Lee", "spelling": "Ann Lee"}]})
        entry = an.load_author_policy()["names"][0]
        self.assertEqual((entry["label"], entry["id"], entry["source"], entry["enabled"], entry["description"]),
                         ("Ann Lee", "default-" + an.name_key("Ann Lee"), "default", True, ""))

    def test_an_explicit_label_id_and_description_are_kept(self):
        self._write_default({"names": [{"name": "Ann Lee", "spelling": "Ann Lee", "label": "Ann", "id": "ann",
                                        "description": " why "}]})
        entry = an.load_author_policy()["names"][0]
        self.assertEqual((entry["label"], entry["id"], entry["description"]), ("Ann", "ann", "why"))

    def test_a_default_file_without_a_names_list_falls_back_to_the_built_in_names(self):
        self._write_default({"names": "not a list"})
        names = {e["name"] for e in an.load_author_policy()["names"]}
        self.assertIn("Mashton XX", names)
        self._write_default({})
        self.assertIn("Mashton XX", {e["name"] for e in an.load_author_policy()["names"]})

    def test_a_valid_empty_names_list_is_respected_not_replaced_by_the_built_ins(self):
        self._write_default({"names": []})
        self.assertEqual(an.load_author_policy()["names"], [])

    def test_disabled_defaults_are_marked_off_and_customs_follow_their_flag(self):
        self._write_default({"names": [{"name": "Ann Lee", "spelling": "Ann Lee", "id": "ann"}]})
        self._write_local({"disabled_defaults": ["ann"], "custom_names": [
            {"name": "Bob Ray", "spelling": "Bob Ray"}, {"name": "Cy Day", "spelling": "Cy Day", "enabled": False}, 5]})
        names = {e["name"]: e for e in an.load_author_policy()["names"]}
        self.assertIs(names["Ann Lee"]["enabled"], False)
        self.assertEqual((names["Bob Ray"]["enabled"], names["Bob Ray"]["source"]), (True, "custom"))
        self.assertIs(names["Cy Day"]["enabled"], False)
        self.assertEqual(len(names), 3)

    def test_the_policy_reports_its_schema_version(self):
        self.assertEqual(an.load_author_policy()["schema_version"], 1)


class SavePolicyTests(WithTempPolicy):
    def test_saving_returns_the_policy_it_just_wrote(self):
        policy = an.save_author_policy([], [{"name": "Ann Lee", "spelling": "Ann Lee"}])
        self.assertIn("Ann Lee", [e["name"] for e in policy["names"]])
        self.assertEqual(policy, an.load_author_policy())

    def test_saved_entries_get_a_derived_id_and_label_and_keep_explicit_ones(self):
        an.save_author_policy([], [{"name": "Ann Lee", "spelling": "Ann Lee"},
                                   {"name": "Bob Ray", "spelling": "Bob Ray", "id": "mine", "label": "B", "description": " d "}])
        saved = {e["name"]: e for e in json.loads(an.LOCAL_POLICY_FILE.read_text())["custom_names"]}
        self.assertEqual((saved["Ann Lee"]["id"], saved["Ann Lee"]["label"]), ("custom-" + an.name_key("Ann Lee"), "Ann Lee"))
        self.assertEqual((saved["Bob Ray"]["id"], saved["Bob Ray"]["label"], saved["Bob Ray"]["description"]), ("mine", "B", "d"))

    def test_nameless_or_spellingless_entries_are_rejected(self):
        for item in ({"name": "", "spelling": "X"}, {"name": "X", "spelling": ""}, {}):
            with self.subTest(item=item), self.assertRaisesRegex(ValueError, "needs a name"):
                an.save_author_policy([], [item])

    def test_file_is_versioned_sorted_unique_disabled_defaults_readable_unicode_and_newline_terminated(self):
        an.save_author_policy(["b", "a", "a"], [{"name": "Zoë Ray", "spelling": "Zoë Ray"}])
        text = an.LOCAL_POLICY_FILE.read_text(encoding="utf-8")
        payload = json.loads(text)
        self.assertEqual((payload["schema_version"], payload["disabled_defaults"]), (1, ["a", "b"]))
        self.assertIn("Zoë Ray", text)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual([p.name for p in an.LOCAL_POLICY_FILE.parent.iterdir() if p.name.endswith(".tmp")], [])


class FormatEdgeTests(WithTempPolicy):
    def test_whitespace_only_names_are_returned_untouched(self):
        for value in ("   ", "\t"):
            self.assertEqual(an.format_person_name(value), value)
        self.assertIsNone(an.format_person_name(None))

    def test_a_single_token_name_is_not_turned_into_initials(self):
        self.assertEqual(an.format_person_name("Madonna"), "Madonna")

    def test_the_last_word_is_never_treated_as_unspaced_initials(self):
        self.assertEqual(an.format_person_name("Anna JK"), "Anna JK")
        self.assertEqual(an.format_person_name("JK Anna"), "J.K. Anna")

    def test_initials_only_change_requires_same_letters_but_different_text(self):
        self.assertIs(an.initials_only_change("V A Lewis", "V.A. Lewis"), True)
        self.assertIs(an.initials_only_change("V.A. Lewis", "V.A. Lewis"), False)
        self.assertIs(an.initials_only_change("V A Lewis", "V A Smith"), False)
        self.assertIs(an.initials_only_change("", "V.A. Lewis"), False)
        self.assertIs(an.initials_only_change("V A Lewis", ""), False)

    def test_scheme_enabled_follows_the_state_file_and_is_false_without_one(self):
        self.assertIs(an.scheme_enabled(), False)
        an.STATE_FILE.write_text(json.dumps({"author_scheme_enabled": True}))
        self.assertIs(an.scheme_enabled(), True)
        an.STATE_FILE.write_text(json.dumps({"author_scheme_enabled": "yes"}))
        self.assertIs(an.scheme_enabled(), False)

    def test_scheme_enabled_ignores_a_stale_cached_answer_once_the_file_is_gone(self):
        an.STATE_FILE.write_text(json.dumps({"author_scheme_enabled": True}))
        self.assertIs(an.scheme_enabled(), True)
        an.STATE_FILE.unlink()
        self.assertIs(an.scheme_enabled(), False)


if __name__ == "__main__":
    unittest.main()
