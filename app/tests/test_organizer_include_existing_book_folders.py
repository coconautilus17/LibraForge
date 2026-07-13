import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_include_existing", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class FolderNameMatchesNamingTemplateTests(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(
            ORGANIZER.folder_name_matches_naming_template("Book 5 - Bold Beginnings", "Book 5 - Bold Beginnings")
        )

    def test_fuzzy_match_ignores_punctuation_case_spacing(self):
        self.assertTrue(
            ORGANIZER.folder_name_matches_naming_template("book_5_Bold-Beginnings!!", "Book 5 - Bold Beginnings")
        )

    def test_distinct_names_do_not_match(self):
        self.assertFalse(
            ORGANIZER.folder_name_matches_naming_template("Random Incoming Folder", "Book 5 - Bold Beginnings")
        )


ROOT = Path("/audiobooks/_unorganized")
COMPUTED_TARGET = Path("/library/G.D. Brooks/Dashing Devil/Book 5 - Bold Beginnings")


class LikelyExistingBookFolderTests(unittest.TestCase):
    def test_matching_folder_kind_item_is_likely_existing(self):
        source = ROOT / "Book 5 - Bold Beginnings"
        audio = source / "book.m4b"
        item = ORGANIZER.BookItem("folder", source, [audio], audio)
        self.assertTrue(ORGANIZER.is_likely_existing_book_folder(item, COMPUTED_TARGET, ROOT))

    def test_non_matching_folder_is_not_likely_existing(self):
        source = ROOT / "Some Random Incoming Name"
        audio = source / "book.m4b"
        item = ORGANIZER.BookItem("folder", source, [audio], audio)
        self.assertFalse(ORGANIZER.is_likely_existing_book_folder(item, COMPUTED_TARGET, ROOT))

    def test_loose_file_with_matching_wrapper_folder_is_likely_existing(self):
        # build_book_items() gives single-file books a "loose_file" kind
        # whose source_path is the audio *file*, not its wrapper folder --
        # the common real-world shape for single-file books. The wrapper
        # folder's name is what should be compared here, not the filename.
        wrapper = ROOT / "Book 5 - Bold Beginnings"
        audio = wrapper / "Bold Beginnings.m4b"
        item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
        self.assertTrue(ORGANIZER.is_likely_existing_book_folder(item, COMPUTED_TARGET, ROOT))

    def test_loose_file_with_non_matching_wrapper_folder_is_not_likely_existing(self):
        wrapper = ROOT / "Some Random Incoming Name"
        audio = wrapper / "Bold Beginnings.m4b"
        item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
        self.assertFalse(ORGANIZER.is_likely_existing_book_folder(item, COMPUTED_TARGET, ROOT))

    def test_bare_loose_file_directly_in_root_is_never_likely_existing(self):
        # No wrapper folder at all -- nothing meaningful to compare.
        audio = ROOT / "Bold Beginnings.m4b"
        item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
        self.assertFalse(ORGANIZER.is_likely_existing_book_folder(item, COMPUTED_TARGET, ROOT))


if __name__ == "__main__":
    unittest.main()
