"""Folder Forge's structure cache: how an existing Author/Series/Book library is
read into canonical authors and series (so new books join the right folders)
and how a series is matched against an entry."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_structure_cache", SCRIPT_PATH)
ORG = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORG
SPEC.loader.exec_module(ORG)


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def book(self, rel, parts=2):
        for number in range(1, parts + 1):
            path = self.root / rel / f"Chapter {number:02d}.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

    def item(self, rel):
        return next(i for i in ORG.build_book_items(self.root, self.root) if i.source_path == self.root / rel)


class InferFromLibraryPathTests(Library):
    def infer(self, rel):
        return ORG.infer_metadata_from_library_path(self.item(rel), self.root)

    def test_author_series_book_folders_give_all_the_fields(self):
        self.book("Will Wight/Cradle/Book 1 - Unsouled")
        got = self.infer("Will Wight/Cradle/Book 1 - Unsouled")
        self.assertEqual((got["author"], got["author_primary"], got["series"], got["book_number"], got["title"], got["sequence_label"]),
                         ("Will Wight", "Will Wight", "Cradle", "001", "Unsouled", "Book"))
        self.assertEqual((got["kind"], got["metadata_source"], got["audio_count"], got["narrator"]), ("folder", "path", 2, ""))

    def test_an_author_book_folder_has_no_series_and_no_number(self):
        self.book("Will Wight/Standalone Thing")
        got = self.infer("Will Wight/Standalone Thing")
        self.assertEqual((got["author"], got["series"], got["book_number"], got["title"]), ("Will Wight", "", "", "Standalone Thing"))

    def test_the_author_folder_may_carry_a_narrator_that_is_ignored(self):
        self.book("Will Wight - Travis Baldree/Cradle/Book 1 - Unsouled")
        self.assertEqual(self.infer("Will Wight - Travis Baldree/Cradle/Book 1 - Unsouled")["author"], "Will Wight")

    def test_a_legacy_series_container_supplies_author_and_series(self):
        self.book("Cradle - Will Wight - Travis Baldree/Book 1 - Unsouled")
        got = self.infer("Cradle - Will Wight - Travis Baldree/Book 1 - Unsouled")
        self.assertEqual((got["author"], got["series"]), ("Will Wight", "Cradle"))

    def test_a_series_in_the_book_folder_name_is_used_when_the_path_has_none(self):
        self.book("Will Wight/Cradle, Book 3")
        got = self.infer("Will Wight/Cradle, Book 3")
        self.assertEqual((got["series"], got["book_number"]), ("Cradle", "003"))

    def test_initials_in_the_primary_author_are_canonicalised(self):
        self.book("J R R Tolkien/Middle Earth/Book 1 - Fellowship")
        self.assertEqual(self.infer("J R R Tolkien/Middle Earth/Book 1 - Fellowship")["author_primary"], "J.R.R. Tolkien")

    def test_a_loose_file_item_and_a_path_outside_the_root_give_nothing(self):
        loose = self.root / "Will Wight" / "Cradle" / "a.m4b"
        loose.parent.mkdir(parents=True)
        loose.write_bytes(b"x")
        item = next(i for i in ORG.build_book_items(self.root, self.root) if i.kind == "loose_file")
        self.assertIsNone(ORG.infer_metadata_from_library_path(item, self.root))
        self.book("Will Wight/Cradle/Book 1 - Unsouled")
        folder = self.item("Will Wight/Cradle/Book 1 - Unsouled")
        self.assertIsNone(ORG.infer_metadata_from_library_path(folder, self.root / "elsewhere"))

    def test_a_top_level_folder_with_no_author_level_gives_nothing(self):
        self.book("Just A Book")
        self.assertIsNone(self.infer("Just A Book"))


class BuildStructureCacheTests(Library):
    def build(self):
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            return ORG.build_structure_cache(self.root, self.root / ".structure.json", progress_every=0)

    def setUp(self):
        super().setUp()
        for rel in ("Will Wight/Cradle/Book 1 - Unsouled", "Will Wight/Cradle/Book 2 - Soulsmith", "Will Wight/Standalone Thing",
                    "Frank Herbert/Dune/Book 1 - Dune"):
            self.book(rel)

    def test_each_series_becomes_one_entry_with_its_author_path_and_book_count(self):
        cache = self.build()
        by_series = {e["series"]: e for e in cache["entries"]}
        self.assertEqual(set(by_series), {"Cradle", "Dune"})
        cradle = by_series["Cradle"]
        self.assertEqual((cradle["canonical_author"], cradle["book_count"], cradle["series_key"]), ("Will Wight", 2, "cradle"))
        self.assertEqual(cradle["path"], str(self.root / "Will Wight" / "Cradle"))
        self.assertEqual((cradle["author_keys"], cradle["series_aliases"], cradle["author_aliases"]), (["willwight"], ["Cradle"], ["Will Wight"]))
        self.assertEqual(cradle["source_paths"], sorted([str(self.root / "Will Wight" / "Cradle" / "Book 1 - Unsouled"),
                                                         str(self.root / "Will Wight" / "Cradle" / "Book 2 - Soulsmith")]))

    def test_books_without_a_series_are_not_in_the_cache(self):
        cache = self.build()
        self.assertTrue(all("Standalone" not in p for e in cache["entries"] for p in e["source_paths"]))

    def test_entries_are_sorted_by_series_key(self):
        self.assertEqual([e["series_key"] for e in self.build()["entries"]], ["cradle", "dune"])

    def test_the_cache_records_its_destination_and_is_saved_to_disk(self):
        cache = self.build()
        self.assertEqual(cache["destination_root"], str(self.root))
        saved = json.loads((self.root / ".structure.json").read_text())
        self.assertEqual([e["series"] for e in saved["entries"]], ["Cradle", "Dune"])

    def test_a_wrong_author_on_one_book_does_not_become_the_series_author(self):
        self.book("Cradle/Cradle/Book 3 - Ghostwritten")        # "author" folder equals the series name
        cache = self.build()
        cradle = [e for e in cache["entries"] if e["series"] == "Cradle"][0]
        self.assertEqual(cradle["canonical_author"], "Will Wight")
        self.assertEqual(cradle["book_count"], 3)

    def test_an_empty_library_gives_an_empty_cache(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(empty, ignore_errors=True))
        self.assertEqual(ORG.build_structure_cache(empty, empty / "c.json", progress_every=0)["entries"], [])


class EntryMatchesSeriesTests(unittest.TestCase):
    ENTRY = {"series_key": "cradle", "series_aliases": ["Cradle", "The Cradle Saga!"]}

    def test_the_key_and_the_qualified_spellings_match(self):
        for series in ("Cradle", "CRADLE", "cradle (Series)", "Cradle Series"):
            with self.subTest(series=series):
                self.assertTrue(ORG.entry_matches_series(self.ENTRY, series))

    def test_an_alias_matches_by_its_normalised_key(self):
        self.assertTrue(ORG.entry_matches_series({"series_key": "zzz", "series_aliases": ["The Cradle Saga!"]}, "cradle saga"))

    def test_a_near_identical_alias_matches_but_a_different_series_does_not(self):
        entry = {"series_key": "zzz", "series_aliases": ["Dungeon Crawler Carls"]}
        self.assertTrue(ORG.entry_matches_series(entry, "Dungeon Crawler Carl"))
        self.assertFalse(ORG.entry_matches_series(entry, "Dungeon Master"))

    def test_blank_series_never_match(self):
        self.assertFalse(ORG.entry_matches_series(self.ENTRY, ""))
        self.assertFalse(ORG.entry_matches_series({"series_key": "", "series_aliases": []}, "!!!"))

    def test_an_entry_without_aliases_matches_on_its_key_only(self):
        self.assertTrue(ORG.entry_matches_series({"series_key": "cradle"}, "Cradle"))
        self.assertFalse(ORG.entry_matches_series({"series_key": "cradle"}, "Dune"))


if __name__ == "__main__":
    unittest.main()
