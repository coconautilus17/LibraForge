import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_naming_tokens", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


BASE_METADATA = {
    "title": "Bold Beginnings",
    "author": "G.D. Brooks",
    "author_primary": "G.D. Brooks",
    "series": "Dashing Devil",
    "edition_tag": "",
    "book_number": "5",
    "sequence_label": "",
    "narrator": "Some Narrator",
    "asin": "B0TESTASIN",
    "publisher": "Publisher House",
    "genre": "Fantasy",
    "year": "2021",
}


class RawTokenPassthroughTests(unittest.TestCase):
    def test_raw_fields_pass_through(self):
        tokens = ORGANIZER.resolve_naming_tokens(BASE_METADATA)
        self.assertEqual(tokens["series"], "Dashing Devil")
        self.assertEqual(tokens["title"], "Bold Beginnings")
        self.assertEqual(tokens["narrator"], "Some Narrator")
        self.assertEqual(tokens["asin"], "B0TESTASIN")
        self.assertEqual(tokens["publisher"], "Publisher House")
        self.assertEqual(tokens["year"], "2021")

    def test_no_genre_or_series_dir_or_book_folder_tokens(self):
        tokens = ORGANIZER.resolve_naming_tokens(BASE_METADATA)
        self.assertNotIn("genre", tokens)
        self.assertNotIn("series_dir", tokens)
        self.assertNotIn("book_folder", tokens)
        self.assertNotIn("book_number", tokens)
        self.assertNotIn("sequence_label", tokens)
        self.assertNotIn("edition_tag", tokens)

    def test_author_token_is_canonicalized(self):
        metadata = dict(BASE_METADATA, author_primary="J. R. R. Tolkien", author="")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["author"], ORGANIZER.canonical_author_name("J. R. R. Tolkien"))

    def test_missing_author_defaults_to_unknown_author(self):
        metadata = dict(BASE_METADATA, author_primary="", author="")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["author"], "Unknown Author")

    def test_missing_narrator_is_empty_not_placeholder(self):
        metadata = dict(BASE_METADATA, narrator="")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["narrator"], "")


class EditionTokenTests(unittest.TestCase):
    def test_edition_token_reads_edition_tag_field(self):
        metadata = dict(BASE_METADATA, edition_tag="GraphicAudio")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["edition"], "GraphicAudio")

    def test_edition_token_empty_when_no_edition_tag(self):
        tokens = ORGANIZER.resolve_naming_tokens(BASE_METADATA)
        self.assertEqual(tokens["edition"], "")


class OrderTokenTests(unittest.TestCase):
    def test_order_is_sequence_prefix_when_series_and_number_present(self):
        tokens = ORGANIZER.resolve_naming_tokens(BASE_METADATA)
        self.assertEqual(tokens["order"], ORGANIZER.build_sequence_prefix("", "5"))
        self.assertEqual(tokens["order"], "Book 5")

    def test_order_uses_detected_label_from_clues(self):
        metadata = dict(BASE_METADATA, sequence_label="Vol.")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["order"], "Vol. 5")

    def test_order_empty_when_no_series(self):
        metadata = dict(BASE_METADATA, series="")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["order"], "")

    def test_order_empty_when_no_number(self):
        metadata = dict(BASE_METADATA, book_number="")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["order"], "")


class TitleRedundancyTests(unittest.TestCase):
    def test_title_empty_when_redundant_with_order(self):
        metadata = dict(BASE_METADATA, title="Book 5")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["title"], "")
        self.assertEqual(tokens["order"], "Book 5")

    def test_title_empty_when_equal_to_series(self):
        metadata = dict(BASE_METADATA, title="Dashing Devil")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["title"], "")

    def test_distinct_title_is_kept(self):
        tokens = ORGANIZER.resolve_naming_tokens(BASE_METADATA)
        self.assertEqual(tokens["title"], "Bold Beginnings")

    def test_asin_like_title_falls_back_to_series_then_empties(self):
        metadata = dict(BASE_METADATA, title="B07XYZ1234")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["title"], "")


if __name__ == "__main__":
    unittest.main()
