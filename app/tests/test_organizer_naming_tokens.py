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
        self.assertEqual(tokens["book_number"], "5")
        self.assertEqual(tokens["narrator"], "Some Narrator")
        self.assertEqual(tokens["asin"], "B0TESTASIN")
        self.assertEqual(tokens["publisher"], "Publisher House")
        self.assertEqual(tokens["genre"], "Fantasy")
        self.assertEqual(tokens["year"], "2021")

    def test_author_token_is_canonicalized(self):
        metadata = dict(BASE_METADATA, author_primary="brooks, g.d.", author="")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(
            tokens["author"],
            ORGANIZER.sanitize_path_name(
                ORGANIZER.canonical_author_name("brooks, g.d."), "Unknown Author"
            ),
        )


class SeriesDirTokenTests(unittest.TestCase):
    def test_series_dir_matches_series_dir_label(self):
        metadata = dict(BASE_METADATA, edition_tag="GraphicAudio")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["series_dir"], ORGANIZER.series_dir_label(metadata))
        self.assertIn("[GraphicAudio]", tokens["series_dir"])

    def test_series_dir_empty_when_no_series(self):
        metadata = dict(BASE_METADATA, series="")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["series_dir"], "")


class BookFolderTokenTests(unittest.TestCase):
    def test_book_folder_matches_build_book_folder_name_when_series_present(self):
        tokens = ORGANIZER.resolve_naming_tokens(BASE_METADATA)
        self.assertEqual(tokens["book_folder"], ORGANIZER.build_book_folder_name(BASE_METADATA))

    def test_book_folder_collapses_redundant_title_like_the_existing_function(self):
        metadata = dict(BASE_METADATA, title="Book 5")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertEqual(tokens["book_folder"], "Book 5")
        self.assertNotIn(" - ", tokens["book_folder"])

    def test_edition_tag_rides_on_book_folder_when_no_series(self):
        metadata = dict(BASE_METADATA, series="", edition_tag="Dramatized")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertIn("[Dramatized]", tokens["book_folder"])
        # And must NOT also appear on series_dir, since there's no series folder.
        self.assertEqual(tokens["series_dir"], "")

    def test_edition_tag_does_not_ride_on_book_folder_when_series_present(self):
        metadata = dict(BASE_METADATA, edition_tag="GraphicAudio")
        tokens = ORGANIZER.resolve_naming_tokens(metadata)
        self.assertNotIn("[GraphicAudio]", tokens["book_folder"])
        self.assertIn("[GraphicAudio]", tokens["series_dir"])


if __name__ == "__main__":
    unittest.main()
