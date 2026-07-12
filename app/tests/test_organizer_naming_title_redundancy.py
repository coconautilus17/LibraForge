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
