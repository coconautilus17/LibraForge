import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_naming_multifile", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


def make_item(audio_names: list[str]) -> "ORGANIZER.BookItem":
    book_dir = Path("/library/_unorganized/Some Book")
    audio_files = [book_dir / name for name in audio_names]
    return ORGANIZER.BookItem("folder", book_dir, audio_files, audio_files[0])


class MultiFileExclusionTests(unittest.TestCase):
    def test_multi_file_book_ignores_template_filename(self):
        item = make_item(["Chapter 01.m4b", "Chapter 02.m4b"])
        result = ORGANIZER.naming_template_filename_for_item(item, "Custom Name.m4b")
        self.assertIsNone(result)

    def test_single_file_book_uses_template_filename(self):
        # The rendered template value is an extension-less stem (the
        # template DSL has no concept of a file extension) -- the item's
        # own audio file's extension must be preserved onto it, not lost.
        item = make_item(["book.m4b"])
        result = ORGANIZER.naming_template_filename_for_item(item, "Custom Name")
        self.assertEqual(result, "Custom Name.m4b")

    def test_single_file_book_preserves_non_m4b_extension(self):
        item = make_item(["book.mp3"])
        result = ORGANIZER.naming_template_filename_for_item(item, "Custom Name")
        self.assertEqual(result, "Custom Name.mp3")

    def test_single_file_book_with_no_filename_template_keeps_original(self):
        item = make_item(["book.m4b"])
        result = ORGANIZER.naming_template_filename_for_item(item, None)
        self.assertIsNone(result)

    def test_multi_file_book_with_no_filename_template_stays_none(self):
        item = make_item(["Chapter 01.m4b", "Chapter 02.m4b"])
        result = ORGANIZER.naming_template_filename_for_item(item, None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
