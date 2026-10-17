"""Folder Forge's user overrides file and the run-wide author correction: both
rewrite metadata after it has been inferred, so each rule is pinned by value."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_overrides", SCRIPT_PATH)
ORG = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORG
SPEC.loader.exec_module(ORG)


class LoadOverridesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "overrides.json"

    def test_a_valid_object_is_loaded(self):
        self.path.write_text(json.dumps({"series": {"A": {"series": "B"}}}))
        self.assertEqual(ORG.load_overrides(self.path), {"series": {"A": {"series": "B"}}})

    def test_no_path_a_missing_file_bad_json_or_a_non_object_give_nothing(self):
        self.assertEqual(ORG.load_overrides(None), {})
        self.assertEqual(ORG.load_overrides(self.path), {})
        self.path.write_text("{bad")
        self.assertEqual(ORG.load_overrides(self.path), {})
        self.path.write_text("[1, 2]")
        self.assertEqual(ORG.load_overrides(self.path), {})


class OverrideForSeriesTests(unittest.TestCase):
    OVERRIDES = {"series": {"Cradle": {"series": "Cradle Saga"}, "The Lost Bloodline": {"canonical_author": "Max"}, "bad": "x"}}

    def test_an_exact_key_matches(self):
        self.assertEqual(ORG.override_for_series(self.OVERRIDES, "Cradle"), {"series": "Cradle Saga"})

    def test_a_differently_spelled_series_matches_by_its_normalised_key(self):
        self.assertEqual(ORG.override_for_series(self.OVERRIDES, "cradle (Series)"), {"series": "Cradle Saga"})
        self.assertEqual(ORG.override_for_series(self.OVERRIDES, "CRADLE"), {"series": "Cradle Saga"})
        self.assertEqual(ORG.override_for_series(self.OVERRIDES, "Lost Bloodline"), {"canonical_author": "Max"})

    def test_a_key_that_normalises_the_same_as_the_series_matches(self):
        overrides = {"series": {"THE   LOST BLOODLINE": {"canonical_author": "Max"}}}
        self.assertEqual(ORG.override_for_series(overrides, "The Lost Bloodline"), {"canonical_author": "Max"})

    def test_unknown_series_blank_series_and_malformed_maps_give_nothing(self):
        self.assertEqual(ORG.override_for_series(self.OVERRIDES, "Dune"), {})
        self.assertEqual(ORG.override_for_series(self.OVERRIDES, ""), {})
        self.assertEqual(ORG.override_for_series({}, "Cradle"), {})
        self.assertEqual(ORG.override_for_series({"series": ["Cradle"]}, "Cradle"), {})
        self.assertEqual(ORG.override_for_series({"series": {"bad": "x"}}, "bad"), {})


class ApplyOverridesToMetadataTests(unittest.TestCase):
    META = {"author": "J R R Tolkien", "author_primary": "J R R Tolkien", "series": "Cradle", "sequence_label": "Book"}

    def apply(self, overrides, **meta):
        return ORG.apply_overrides_to_metadata({**self.META, **meta}, overrides)

    def test_no_overrides_return_the_same_object(self):
        self.assertIs(ORG.apply_overrides_to_metadata(self.META, {}), self.META)

    def test_author_aliases_rewrite_the_credit_and_the_primary_author_independently(self):
        got = self.apply({"author_aliases": {"j r r tolkien": "J.R.R. Tolkien"}})
        self.assertEqual((got["author"], got["author_primary"]), ("J.R.R. Tolkien", "J.R.R. Tolkien"))
        got = self.apply({"author_aliases": {"J R R Tolkien": "Tolkien"}}, author="J R R Tolkien, Bob Roe")
        self.assertEqual((got["author"], got["author_primary"]), ("J R R Tolkien, Bob Roe", "Tolkien"))

    def test_an_alias_for_another_author_changes_nothing(self):
        got = self.apply({"author_aliases": {"Someone Else": "X"}})
        self.assertEqual((got["author"], got["author_primary"]), ("J R R Tolkien", "J R R Tolkien"))

    def test_a_series_override_renames_the_series_sets_the_primary_author_and_normalises_the_label(self):
        got = self.apply({"series": {"Cradle": {"series": "Cradle Saga", "canonical_author": "Will Wight", "sequence_label": "vol"}}})
        self.assertEqual((got["series"], got["author_primary"], got["sequence_label"]), ("Cradle Saga", "Will Wight", "Vol."))
        self.assertEqual(got["author"], "J R R Tolkien")                 # the credit itself is not rewritten

    def test_only_the_fields_present_in_the_override_are_applied(self):
        got = self.apply({"series": {"Cradle": {"canonical_author": "Will Wight"}}})
        self.assertEqual((got["series"], got["sequence_label"], got["author_primary"]), ("Cradle", "Book", "Will Wight"))

    def test_the_input_is_not_modified(self):
        before = dict(self.META)
        self.apply({"series": {"Cradle": {"series": "X"}}})
        self.assertEqual(self.META, before)


class ApplyOverridesToCacheTests(unittest.TestCase):
    CACHE = {"destination_root": "/lib", "entries": [{"series": "Cradle", "canonical_author": "Will Wight", "path": "/lib/Will Wight/Cradle"},
                                                     {"series": "Dune", "canonical_author": "Frank Herbert", "path": "/lib/Frank Herbert/Dune"}]}

    def test_no_overrides_return_the_cache_itself(self):
        self.assertIs(ORG.apply_overrides_to_cache(self.CACHE, {}), self.CACHE)

    def test_renaming_the_series_and_author_rebuilds_the_entry_path(self):
        got = ORG.apply_overrides_to_cache(self.CACHE, {"series": {"Cradle": {"series": "Cradle Saga", "canonical_author": "W. Wight"}}})
        first = got["entries"][0]
        self.assertEqual((first["series"], first["canonical_author"], first["path"]), ("Cradle Saga", "W. Wight", "/lib/W. Wight/Cradle Saga"))

    def test_entries_without_an_override_are_unchanged(self):
        got = ORG.apply_overrides_to_cache(self.CACHE, {"series": {"Cradle": {"series": "Cradle Saga"}}})
        self.assertEqual(got["entries"][1], self.CACHE["entries"][1])

    def test_aliases_are_merged_sorted_and_blank_ones_dropped(self):
        cache = {"destination_root": "/lib", "entries": [{"series": "Cradle", "canonical_author": "A", "series_aliases": ["z alias"]}]}
        got = ORG.apply_overrides_to_cache(cache, {"series": {"Cradle": {"series_aliases": ["b alias", "", "  ", "z alias"]}}})
        self.assertEqual(got["entries"][0]["series_aliases"], ["b alias", "z alias"])

    def test_the_original_cache_is_not_modified(self):
        import copy
        before = copy.deepcopy(self.CACHE)
        ORG.apply_overrides_to_cache(self.CACHE, {"series": {"Cradle": {"series": "X"}}})
        self.assertEqual(self.CACHE, before)


class RunAuthorCorrectionTests(unittest.TestCase):
    def meta(self, series, author):
        return {"series": series, "author": author}

    def test_the_most_common_good_author_of_a_series_becomes_its_correction(self):
        items = [self.meta("Cradle", "Will Wight"), self.meta("Cradle", "Will Wight"), self.meta("Cradle", "Someone Else")]
        self.assertEqual(ORG.build_run_author_corrections(items), {ORG.normalize_series_key("Cradle"): "Will Wight"})

    def test_authors_that_are_the_series_name_or_unknown_or_generic_are_not_good(self):
        items = [self.meta("Cradle", "Cradle"), self.meta("Cradle", "Unknown Author"), self.meta("Cradle", "Audiobooks"), self.meta("Cradle", "")]
        self.assertEqual(ORG.build_run_author_corrections(items), {})

    def test_a_series_needs_one_good_author_and_books_without_a_series_are_ignored(self):
        items = [self.meta("Cradle", "Cradle"), self.meta("Cradle", "Will Wight"), self.meta("", "Frank Herbert")]
        self.assertEqual(ORG.build_run_author_corrections(items), {ORG.normalize_series_key("Cradle"): "Will Wight"})

    def test_each_series_gets_its_own_correction(self):
        items = [self.meta("Cradle", "Will Wight"), self.meta("Dune", "Frank Herbert")]
        got = ORG.build_run_author_corrections(items)
        self.assertEqual(got[ORG.normalize_series_key("Dune")], "Frank Herbert")
        self.assertEqual(len(got), 2)

    def test_a_bad_author_is_replaced_and_the_change_is_explained(self):
        corrections = {ORG.normalize_series_key("Cradle"): "Will Wight"}
        got = ORG.apply_run_author_correction({"series": "Cradle", "author": "Cradle", "review_reasons": ["x"]}, corrections)
        self.assertEqual((got["author"], got["author_primary"]), ("Will Wight", "Will Wight"))
        self.assertEqual(got["review_reasons"], ["x", "author inferred from other books in this run"])

    def test_the_reason_is_not_repeated(self):
        corrections = {ORG.normalize_series_key("Cradle"): "Will Wight"}
        once = ORG.apply_run_author_correction({"series": "Cradle", "author": "Cradle"}, corrections)
        twice = ORG.apply_run_author_correction({**once, "author": "Cradle"}, corrections)
        self.assertEqual(twice["review_reasons"].count("author inferred from other books in this run"), 1)

    def test_a_good_author_series_without_a_correction_and_a_missing_series_are_left_alone(self):
        corrections = {ORG.normalize_series_key("Cradle"): "Will Wight"}
        good = {"series": "Cradle", "author": "Bob Roe"}
        self.assertEqual(ORG.apply_run_author_correction(good, corrections), good)
        other = {"series": "Dune", "author": "Dune"}
        self.assertEqual(ORG.apply_run_author_correction(other, corrections), other)
        none = {"series": "", "author": ""}
        self.assertEqual(ORG.apply_run_author_correction(none, corrections), none)

    def test_the_input_is_not_modified(self):
        corrections = {ORG.normalize_series_key("Cradle"): "Will Wight"}
        original = {"series": "Cradle", "author": "Cradle"}
        ORG.apply_run_author_correction(original, corrections)
        self.assertEqual(original, {"series": "Cradle", "author": "Cradle"})


if __name__ == "__main__":
    unittest.main()
