"""An untagged book's Author/ folder is an author clue (#387).

In a tag-stripped comparison run, 12 correct matches sat at 0.50 because the
book had no author tag even though it lived under Author/Title/. The folder
only fills a missing author and never vetoes a candidate.
"""
import unittest
from pathlib import Path

from app.fixer.parsing import library_author_folder
from app.fixer.scoring import has_author_identity_conflict, score_product_for_metadata
from app.tests.script_loader import load_script

FIXER = load_script("fixer_v5_author_folder", "audible-metadata-fixer-v5.py")
ROOT = Path("/audiobooks")


def clues_for(rel: str, tags: dict) -> dict:
    return FIXER.build_search_clues_from_file(ROOT / rel, tags=tags)


class LibraryAuthorFolderTests(unittest.TestCase):
    def test_first_folder_below_the_root_when_nested(self):
        self.assertEqual(library_author_folder(ROOT / "Herman Melville/Moby Dick", [ROOT]), "Herman Melville")
        self.assertEqual(library_author_folder(ROOT / "Will Wight/Cradle/01 Unsouled", [ROOT]), "Will Wight")

    def test_book_folder_directly_in_the_root_has_none(self):
        self.assertEqual(library_author_folder(ROOT / "Moby Dick", [ROOT]), "")

    def test_first_containing_root_wins(self):
        scan = ROOT / "Herman Melville"
        self.assertEqual(library_author_folder(scan / "Moby Dick", [ROOT, scan]), "Herman Melville")
        self.assertEqual(library_author_folder(Path("/elsewhere/A/B"), [ROOT]), "")


class FolderAuthorClueTests(unittest.TestCase):
    def setUp(self):
        self._saved = list(FIXER.LIBRARY_ROOTS)
        FIXER.LIBRARY_ROOTS[:] = [ROOT]

    def tearDown(self):
        FIXER.LIBRARY_ROOTS[:] = self._saved

    def test_untagged_book_gets_its_author_folder(self):
        clues = clues_for("Herman Melville/Moby Dick/Moby Dick.m4b", {"title": "Moby Dick"})
        self.assertEqual(clues["author"], "Herman Melville")
        self.assertEqual(clues["author_source"], "folder")

    def test_author_tag_always_wins(self):
        clues = clues_for("Herman Melville/Moby Dick/Moby Dick.m4b",
                          {"title": "Moby Dick", "artist": "H. Melville"})
        self.assertEqual(clues["author"], "H. Melville")
        self.assertNotEqual(clues.get("author_source"), "folder")

    def test_an_author_tag_holding_the_series_name_gives_way_to_the_folder(self):
        # Kyle West's Starsea Cycle rips (#408): artist and album are the series.
        tags = {"title": "The Starsea Cycle - Book 001 - The Mages of Starsea", "artist": "The Starsea Cycle",
                "album": "The Starsea Cycle", "composer": "Rob Brinkmann"}
        clues = clues_for("Kyle West/The Starsea Cycle/Book 1 - The Mages of Starsea/"
                          "The Starsea Cycle - Book 001 - The Mages of Starsea.m4b", tags)
        self.assertEqual(clues["author"], "Kyle West")
        self.assertEqual(clues["author_source"], "folder")
        self.assertEqual(clues["title"], "The Mages of Starsea")

    def test_author_folder_beats_a_title_subtitle_folder_name(self):
        # Untagged, "The X-Files - Cold Cases" alone parses as author "Cold Cases".
        clues = clues_for("Joe Harris/The X-Files - Cold Cases/The X-Files Cold Cases.m4b", {})
        self.assertEqual(clues["author"], "Joe Harris")
        self.assertEqual(clues["author_source"], "folder")

    def test_folder_name_author_still_beats_a_non_person_folder(self):
        clues = clues_for("Classics/Dune - Frank Herbert/Dune.m4b", {})
        self.assertEqual(clues["author"], "Frank Herbert")
        self.assertNotEqual(clues.get("author_source"), "folder")

    def test_staging_folder_is_not_an_author(self):
        clues = clues_for("_unorganized/Poetics/Poetics.m4b", {"title": "Poetics"})
        self.assertEqual(clues.get("author", ""), "")

    def test_folder_author_counts_when_it_agrees(self):
        product = {"asin": "B0038GOF7C", "title": "Moby Dick", "authors": [{"name": "Herman Melville"}],
                   "narrators": [{"name": "William Hootkins"}], "runtime_length_min": 1309}
        clues = clues_for("Herman Melville/Moby Dick/Moby Dick.m4b", {"title": "Moby Dick"})
        with_folder = score_product_for_metadata(clues, product, 1309.0)
        without = score_product_for_metadata({**clues, "author": "", "author_source": ""}, product, 1309.0)
        self.assertEqual(with_folder, 1.0)
        self.assertLess(without, with_folder)

    def test_folder_that_is_not_an_author_never_rejects(self):
        product = {"asin": "B0X", "title": "Moby Dick", "authors": [{"name": "Herman Melville"}],
                   "narrators": [], "runtime_length_min": 1309}
        clues = clues_for("Classics/Moby Dick/Moby Dick.m4b", {"title": "Moby Dick"})
        self.assertEqual(clues["author"], "Classics")
        self.assertFalse(has_author_identity_conflict(clues, product))
        self.assertTrue(has_author_identity_conflict({**clues, "author_source": ""}, product))
        self.assertGreater(score_product_for_metadata(clues, product, 1309.0), 0.0)


if __name__ == "__main__":
    unittest.main()
