"""How Folder Forge turns known metadata into folder names: the sequence prefix,
when a title is redundant next to it, the book folder, and the default
Author/Series/Book path. Also the legacy collection-folder parser and the rule
that decides when two different titles are a real conflict."""
import unittest
from app.tests.script_loader import load_script

ORG = load_script("organizer_folder_naming", "organize-audiobooks-by-metadata-v3_13.py")


class DisplayNumberTests(unittest.TestCase):
    def test_padding_and_trailing_zero_decimals_are_removed(self):
        for raw, expected in (("001", "1"), ("003.5", "3.5"), ("001-002", "1-2"), ("001+002", "1+2"), ("010", "10"), ("000", "0"),
                              ("1.0", "1"), ("", ""), ("abc", "abc")):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.display_book_number(raw), expected)


class SequencePrefixTests(unittest.TestCase):
    def test_a_range_pluralises_the_label(self):
        for label, expected in (("Book", "Books 1-2"), ("", "Books 1-2"), ("Volume", "Volumes 1-2"), ("vol", "Vol. 1-2"),
                                ("Novel", "Novels 1-2"), ("Side Story", "Side Story 1-2")):
            with self.subTest(label=label):
                self.assertEqual(ORG.build_sequence_prefix(label, "001-002"), expected)


class SeriesDirLabelTests(unittest.TestCase):
    def label(self, **meta):
        return ORG.series_dir_label(meta)


class TitleConflictTests(unittest.TestCase):
    def conflict(self, metadata_title, path_title, series="Cradle", number="001", author="", narrator=""):
        return ORG.title_conflict_should_trigger_review(metadata_title, path_title, series, number, author, narrator)

    def test_a_side_that_only_restates_the_series_and_number_is_not_a_distinct_title(self):
        self.assertFalse(self.conflict("Cradle Book 1", "Book 1"))
        self.assertFalse(self.conflict("", "Unsouled"))


class StandaloneFolderNameTests(unittest.TestCase):
    def parse(self, name):
        return ORG.parse_standalone_book_folder_name(name)

    def test_title_author_narrator_for_three_segments(self):
        self.assertEqual(self.parse("Unsouled - Will Wight - Travis Baldree"),
                         {"title": "Unsouled", "author": "Will Wight", "narrator": "Travis Baldree"})

    def test_numbered_prefixes_unrecognised_shapes_and_blanks_give_nothing(self):
        for name in ("01 - Unsouled", "Cradle 3 - Unsouled", "Unsouled", "", "Unsouled - Will Wight"):
            with self.subTest(name=name):
                self.assertEqual(self.parse(name), {})


class BookFolderNameParserTests(unittest.TestCase):
    def parse(self, name):
        return ORG.parse_book_folder_name(name)

    def test_a_light_novel_folder_with_author_year_series_volume_and_narrator(self):
        got = self.parse("Isuna Hasekura (2008) Spice and Wolf, Volume 8 - Town of Strife 1 (Narrator)")
        self.assertEqual(got, {"author": "Isuna Hasekura", "year": "2008", "series": "Spice and Wolf", "number": "008",
                               "title": "Town of Strife 1", "narrator": "Narrator", "sequence_label": "Volume"})

if __name__ == "__main__":
    unittest.main()
