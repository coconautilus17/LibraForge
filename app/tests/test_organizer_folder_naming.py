"""How Folder Forge turns known metadata into folder names: the sequence prefix,
when a title is redundant next to it, the book folder, and the default
Author/Series/Book path. Also the legacy collection-folder parser and the rule
that decides when two different titles are a real conflict."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_folder_naming", SCRIPT_PATH)
ORG = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORG
SPEC.loader.exec_module(ORG)


class DisplayNumberTests(unittest.TestCase):
    def test_padding_and_trailing_zero_decimals_are_removed(self):
        for raw, expected in (("001", "1"), ("003.5", "3.5"), ("001-002", "1-2"), ("001+002", "1+2"), ("010", "10"), ("000", "0"),
                              ("1.0", "1"), ("", ""), ("abc", "abc")):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.display_book_number(raw), expected)


class SequencePrefixTests(unittest.TestCase):
    def test_a_single_number_uses_the_label_defaulting_to_book(self):
        for label, number, expected in (("Book", "001", "Book 1"), ("", "001", "Book 1"), ("Vol.", "003.5", "Vol. 3.5"),
                                        ("Volume", "002", "Volume 2"), ("garbage", "001", "Book 1")):
            with self.subTest(label=label, number=number):
                self.assertEqual(ORG.build_sequence_prefix(label, number), expected)

    def test_a_range_pluralises_the_label(self):
        for label, expected in (("Book", "Books 1-2"), ("", "Books 1-2"), ("Volume", "Volumes 1-2"), ("vol", "Vol. 1-2"),
                                ("Novel", "Novels 1-2"), ("Side Story", "Side Story 1-2")):
            with self.subTest(label=label):
                self.assertEqual(ORG.build_sequence_prefix(label, "001-002"), expected)


class RedundantTitleTests(unittest.TestCase):
    def redundant(self, title, series="Cradle", label="Book", number="005"):
        return ORG.title_is_redundant_with_sequence(title, series, label, number)

    def test_titles_that_only_restate_the_sequence_or_series_are_redundant(self):
        for title in ("Book 5", "Cradle", "5", "Book Five", "cradle"):
            with self.subTest(title=title):
                self.assertTrue(self.redundant(title), title)
        self.assertTrue(self.redundant("Books 1-2", number="001-002"))
        self.assertTrue(self.redundant("Vol. 5", label="Vol."))

    def test_a_real_title_is_not(self):
        self.assertFalse(self.redundant("Unsouled", number="001"))
        self.assertFalse(self.redundant("Book 6"))

    def test_without_a_series_or_a_number_nothing_is_redundant(self):
        self.assertFalse(self.redundant("Book 5", series=""))
        self.assertFalse(self.redundant("Book 5", number=""))


class BookFolderNameTests(unittest.TestCase):
    def name(self, **meta):
        return ORG.build_book_folder_name(meta)

    def test_a_series_book_gets_its_prefix_before_the_title(self):
        self.assertEqual(self.name(title="Unsouled", series="Cradle", book_number="001", sequence_label="Book"), "Book 1 - Unsouled")
        self.assertEqual(self.name(title="Unsouled", series="Cradle", book_number="001-002"), "Books 1-2 - Unsouled")
        self.assertEqual(self.name(title="Foo: Bar?", series="S", book_number="003.5", sequence_label="Vol."), "Vol. 3.5 - Foo - Bar")

    def test_a_title_that_only_repeats_the_series_collapses_to_the_prefix(self):
        self.assertEqual(self.name(title="Cradle", series="Cradle", book_number="001"), "Book 1")

    def test_an_asin_in_the_title_slot_never_becomes_the_folder_name(self):
        self.assertEqual(self.name(title="B0ABCDEFGH", series="Cradle", book_number="002"), "Book 2")
        self.assertEqual(self.name(title="NOREALASIN"), "Unknown Title")

    def test_without_a_series_or_number_the_title_stands_alone(self):
        self.assertEqual(self.name(title="Unsouled", series="", book_number="001"), "Unsouled")
        self.assertEqual(self.name(title="Unsouled", series="Cradle", book_number=""), "Unsouled")
        self.assertEqual(self.name(title="", series="", book_number=""), "Unknown Title")


class DefaultTargetDirTests(unittest.TestCase):
    ROOT = Path("/lib")

    def target(self, **meta):
        return ORG.build_default_target_dir(self.ROOT, meta)

    def test_a_series_book_goes_under_author_series_and_book_folder(self):
        self.assertEqual(self.target(title="Unsouled", author_primary="Will Wight", series="Cradle", book_number="001"),
                         self.ROOT / "Will Wight" / "Cradle" / "Book 1 - Unsouled")

    def test_the_primary_author_beats_the_full_credit_and_initials_are_canonicalised(self):
        self.assertEqual(self.target(title="X", author="J R R Tolkien, Ann Lee", author_primary="J R R Tolkien"),
                         self.ROOT / "J.R.R. Tolkien" / "X")

    def test_a_missing_author_goes_to_unknown_author(self):
        self.assertEqual(self.target(title="Dune", author="", series=""), self.ROOT / "Unknown Author" / "Dune")

    def test_a_dramatized_series_gets_an_imprint_suffixed_series_folder(self):
        self.assertEqual(self.target(title="Unsouled", author="Will Wight", series="Cradle", book_number="001", edition_tag="GraphicAudio"),
                         self.ROOT / "Will Wight" / "Cradle [GraphicAudio]" / "Book 1 - Unsouled")

    def test_a_standalone_dramatization_tags_the_book_folder_instead(self):
        self.assertEqual(self.target(title="The Hobbit", author="Tolkien", edition_tag="Dramatized"),
                         self.ROOT / "Tolkien" / "The Hobbit [Dramatized]")

    def test_ebooks_never_share_a_folder_with_the_audiobook(self):
        self.assertEqual(self.target(title="Dune", author="Frank Herbert", media_type="ebook"), self.ROOT / "Frank Herbert" / "Dune - EBOOK")
        self.assertEqual(self.target(title="Dune", author="Frank Herbert", series="Dune", book_number="001", media_type="ebook"),
                         self.ROOT / "Frank Herbert" / "Dune - EBOOK" / "Book 1")


class SeriesDirLabelTests(unittest.TestCase):
    def label(self, **meta):
        return ORG.series_dir_label(meta)

    def test_plain_tagged_and_ebook_series_labels(self):
        self.assertEqual(self.label(series="Cradle"), "Cradle")
        self.assertEqual(self.label(series="Cradle", edition_tag="Dramatized"), "Cradle [Dramatized]")
        self.assertEqual(self.label(series="Cradle", media_type="ebook"), "Cradle - EBOOK")
        self.assertEqual(self.label(series="Cradle", edition_tag="Dramatized", media_type="ebook"), "Cradle [Dramatized] - EBOOK")
        self.assertEqual(self.label(series=""), "Unknown Series")


class LegacyContainerTests(unittest.TestCase):
    def parse(self, name):
        return ORG.parse_legacy_series_container(name)

    def test_series_author_narrator_folders(self):
        self.assertEqual(self.parse("Cradle - Will Wight - Travis Baldree"), {"series": "Cradle", "author": "Will Wight", "narrator": "Travis Baldree"})
        self.assertEqual(self.parse("A - B - C - D"), {"series": "A", "author": "B", "narrator": "C, D"})

    def test_author_series_pack_folders(self):
        self.assertEqual(self.parse("Will Wight - Cradle (#1-6)"), {"series": "Cradle", "author": "Will Wight", "narrator": ""})

    def test_series_with_a_book_range_in_parentheses(self):
        for name in ("Cradle (Book 1 & 2)", "Cradle (Books 1-3)"):
            with self.subTest(name=name):
                self.assertEqual(self.parse(name), {"series": "Cradle", "author": "", "narrator": ""})

    def test_ordinary_folders_are_not_containers(self):
        for name in ("Will Wight - Unsouled", "Cradle", "", "(Books 1-3)"):
            with self.subTest(name=name):
                self.assertEqual(self.parse(name), {})


class TitleConflictTests(unittest.TestCase):
    def conflict(self, metadata_title, path_title, series="Cradle", number="001", author="", narrator=""):
        return ORG.title_conflict_should_trigger_review(metadata_title, path_title, series, number, author, narrator)

    def test_two_genuinely_different_titles_are_a_conflict(self):
        self.assertTrue(self.conflict("Unsouled", "Totally Different Words"))
        self.assertTrue(self.conflict("Qwerty Uiop", "Qwerty Asdf", series="S"))

    def test_identical_or_contained_titles_are_not(self):
        self.assertFalse(self.conflict("Unsouled", "Unsouled"))
        self.assertFalse(self.conflict("Alpha Beta Gamma", "Alpha Beta Gamma Delta", series="S"))
        self.assertFalse(self.conflict("The Warlock", "Warlock"))

    def test_an_author_decoration_on_one_side_is_not_a_conflict(self):
        self.assertFalse(self.conflict("Unsouled", "Unsouled - Will Wight", author="Will Wight"))

    def test_a_side_that_only_restates_the_series_and_number_is_not_a_distinct_title(self):
        self.assertFalse(self.conflict("Cradle Book 1", "Book 1"))
        self.assertFalse(self.conflict("", "Unsouled"))


if __name__ == "__main__":
    unittest.main()
