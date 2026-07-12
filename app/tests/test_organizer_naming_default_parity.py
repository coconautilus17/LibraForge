import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_naming_default_parity", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


DESTINATION_ROOT = Path("/library")


def _rendered_path(metadata: dict) -> Path:
    tokens = ORGANIZER.resolve_naming_tokens(metadata)
    folders, filename, reasons = ORGANIZER.render_naming_template(
        ORGANIZER.DEFAULT_NAMING_TEMPLATE, tokens
    )
    assert filename is None, "default template must never rename files"
    assert reasons == [], reasons
    return DESTINATION_ROOT.joinpath(*folders)


CASES = {
    "series_with_number_and_distinct_title": {
        "title": "Bold Beginnings",
        "author": "G.D. Brooks",
        "author_primary": "G.D. Brooks",
        "series": "Dashing Devil",
        "edition_tag": "",
        "book_number": "5",
        "sequence_label": "",
    },
    "no_series_standalone": {
        "title": "The Hobbit",
        "author": "J.R.R. Tolkien",
        "author_primary": "J.R.R. Tolkien",
        "series": "",
        "edition_tag": "",
        "book_number": "",
        "sequence_label": "",
    },
    "no_series_with_edition_tag": {
        "title": "The Hobbit",
        "author": "J.R.R. Tolkien",
        "author_primary": "J.R.R. Tolkien",
        "series": "",
        "edition_tag": "Dramatized",
        "book_number": "",
        "sequence_label": "",
    },
    "series_with_edition_tag": {
        "title": "Bold Beginnings",
        "author": "G.D. Brooks",
        "author_primary": "G.D. Brooks",
        "series": "Dashing Devil",
        "edition_tag": "GraphicAudio",
        "book_number": "5",
        "sequence_label": "",
    },
    "redundant_title_collapses_to_prefix": {
        "title": "Book 5",
        "author": "G.D. Brooks",
        "author_primary": "G.D. Brooks",
        "series": "Dashing Devil",
        "edition_tag": "",
        "book_number": "5",
        "sequence_label": "",
    },
    "omnibus_range": {
        "title": "Cradle, Books 1-3",
        "author": "Will Wight",
        "author_primary": "Will Wight",
        "series": "Cradle",
        "edition_tag": "",
        "book_number": "001-003",
        "sequence_label": "",
    },
}


class DefaultTemplateParityTests(unittest.TestCase):
    def test_matches_build_default_target_dir_for_every_case(self):
        for name, metadata in CASES.items():
            with self.subTest(case=name):
                expected = ORGANIZER.build_default_target_dir(DESTINATION_ROOT, metadata)
                actual = _rendered_path(metadata)
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
