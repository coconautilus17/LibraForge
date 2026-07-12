import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_title_redundancy", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class TitleIsRedundantWithSequenceTests(unittest.TestCase):
    def test_title_equal_to_prefix_is_redundant(self):
        self.assertTrue(
            ORGANIZER.title_is_redundant_with_sequence("Book 5", "Dashing Devil", "", "5")
        )

    def test_title_equal_to_series_is_redundant(self):
        self.assertTrue(
            ORGANIZER.title_is_redundant_with_sequence("Dashing Devil", "Dashing Devil", "", "5")
        )

    def test_distinct_title_is_not_redundant(self):
        self.assertFalse(
            ORGANIZER.title_is_redundant_with_sequence("Bold Beginnings", "Dashing Devil", "", "5")
        )

    def test_no_series_or_number_is_never_redundant(self):
        self.assertFalse(ORGANIZER.title_is_redundant_with_sequence("Book 5", "", "", ""))
        self.assertFalse(ORGANIZER.title_is_redundant_with_sequence("Book 5", "Dashing Devil", "", ""))

    def test_bare_number_restatement_is_redundant(self):
        self.assertTrue(
            ORGANIZER.title_is_redundant_with_sequence("Dashing Devil 5", "Dashing Devil", "", "5")
        )

    def test_roman_numeral_restatement_is_redundant(self):
        # "Dao of Magic V" is the series name plus the roman numeral for the
        # book number (5) -- it restates the sequence, so it's redundant the
        # same way the arabic "Dao of Magic 5" already is.
        self.assertTrue(
            ORGANIZER.title_is_redundant_with_sequence("Dao of Magic V", "Dao of Magic", "", "5")
        )

    def test_roman_numeral_with_leading_article_is_redundant(self):
        self.assertTrue(
            ORGANIZER.title_is_redundant_with_sequence("The Dao of Magic V", "Dao of Magic", "", "5")
        )

    def test_roman_numeral_not_matching_number_is_not_redundant(self):
        # IV is 4, not 5 -- a real mismatch must not be collapsed away.
        self.assertFalse(
            ORGANIZER.title_is_redundant_with_sequence("Dao of Magic IV", "Dao of Magic", "", "5")
        )

    def test_trailing_non_roman_letter_is_not_treated_as_number(self):
        # A remainder that isn't a valid roman numeral (or doesn't equal the
        # number) stays a distinct title -- e.g. a subtitle word.
        self.assertFalse(
            ORGANIZER.title_is_redundant_with_sequence("Dao of Magic Zenith", "Dao of Magic", "", "5")
        )


class BuildBookFolderNameStillCollapsesTests(unittest.TestCase):
    def test_refactor_preserves_existing_collapse_behavior(self):
        metadata = {
            "title": "Book 5",
            "series": "Dashing Devil",
            "book_number": "5",
            "sequence_label": "",
        }
        self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Book 5")

    def test_refactor_preserves_existing_distinct_title_behavior(self):
        metadata = {
            "title": "Bold Beginnings",
            "series": "Dashing Devil",
            "book_number": "5",
            "sequence_label": "",
        }
        self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Book 5 - Bold Beginnings")


if __name__ == "__main__":
    unittest.main()
