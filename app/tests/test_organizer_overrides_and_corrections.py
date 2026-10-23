"""Folder Forge's user overrides file and the run-wide author correction: both
rewrite metadata after it has been inferred, so each rule is pinned by value."""
import importlib.util
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

    def test_no_path_a_missing_file_bad_json_or_a_non_object_give_nothing(self):
        self.assertEqual(ORG.load_overrides(None), {})
        self.assertEqual(ORG.load_overrides(self.path), {})
        self.path.write_text("{bad")
        self.assertEqual(ORG.load_overrides(self.path), {})
        self.path.write_text("[1, 2]")
        self.assertEqual(ORG.load_overrides(self.path), {})


class OverrideForSeriesTests(unittest.TestCase):
    OVERRIDES = {"series": {"Cradle": {"series": "Cradle Saga"}, "The Lost Bloodline": {"canonical_author": "Max"}, "bad": "x"}}

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

    def test_an_alias_for_another_author_changes_nothing(self):
        got = self.apply({"author_aliases": {"Someone Else": "X"}})
        self.assertEqual((got["author"], got["author_primary"]), ("J R R Tolkien", "J R R Tolkien"))

    def test_a_series_override_renames_the_series_sets_the_primary_author_and_normalises_the_label(self):
        got = self.apply({"series": {"Cradle": {"series": "Cradle Saga", "canonical_author": "Will Wight", "sequence_label": "vol"}}})
        self.assertEqual((got["series"], got["author_primary"], got["sequence_label"]), ("Cradle Saga", "Will Wight", "Vol."))
        self.assertEqual(got["author"], "J R R Tolkien")                 # the credit itself is not rewritten

class ApplyOverridesToCacheTests(unittest.TestCase):
    CACHE = {"destination_root": "/lib", "entries": [{"series": "Cradle", "canonical_author": "Will Wight", "path": "/lib/Will Wight/Cradle"},
                                                     {"series": "Dune", "canonical_author": "Frank Herbert", "path": "/lib/Frank Herbert/Dune"}]}

    def test_renaming_the_series_and_author_rebuilds_the_entry_path(self):
        got = ORG.apply_overrides_to_cache(self.CACHE, {"series": {"Cradle": {"series": "Cradle Saga", "canonical_author": "W. Wight"}}})
        first = got["entries"][0]
        self.assertEqual((first["series"], first["canonical_author"], first["path"]), ("Cradle Saga", "W. Wight", "/lib/W. Wight/Cradle Saga"))


if __name__ == "__main__":
    unittest.main()
