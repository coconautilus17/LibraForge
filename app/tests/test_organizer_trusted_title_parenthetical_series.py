import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_trusted_paren", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


class TrustedTitleParentheticalSeriesTests(unittest.TestCase):
    """Trusted (Audible/fixer-confirmed) titles can bake a redundant
    "(Series Book N)" annotation directly into the chosen title, e.g.
    "Rebirth (Dread Knight Book 4)". clean_book_title()'s trusted branch
    only stripped leading series prefixes and trailing marketing
    descriptors, so this trailing parenthetical survived untouched while
    sibling books in the same series (with plain chosen titles) organized
    correctly.
    """

    def test_trailing_series_book_parenthetical_is_stripped(self):
        result = ORGANIZER.clean_book_title(
            "Rebirth (Dread Knight Book 4)",
            "Dread Knight",
            ORGANIZER.normalize_book_number("4"),
            trusted=True,
        )
        self.assertEqual(result, "Rebirth")

    def test_series_number_sign_parenthetical_is_still_stripped(self):
        result = ORGANIZER.clean_book_title(
            "End of Trials (Paths of Akashic #2)",
            "Paths of Akashic",
            ORGANIZER.normalize_book_number("2"),
            trusted=True,
        )
        self.assertEqual(result, "End of Trials")

    def test_doubled_nested_parenthetical_collapses_to_series(self):
        # "The Duelist 12 (The Duelist (Completed Series))" -- the trailing
        # annotation itself contains a nested parenthetical, which the old
        # single-level bracket regex could not recognize as one unit, so it
        # only stripped the leading "The Duelist 12" prefix and left the
        # untouched "(The Duelist (Completed Series))" fragment as the title.
        result = ORGANIZER.clean_book_title(
            "The Duelist 12 (The Duelist (Completed Series))",
            "The Duelist",
            ORGANIZER.normalize_book_number("12"),
            trusted=True,
        )
        self.assertEqual(result, "The Duelist")

    def test_bracketed_series_comma_number_collapses_to_series(self):
        # "Dragon Emperor 22 [Dragon Emperor, 22]" -- a doubled
        # series+number annotation using square brackets instead of parens.
        result = ORGANIZER.clean_book_title(
            "Dragon Emperor 22 [Dragon Emperor, 22]",
            "Dragon Emperor",
            ORGANIZER.normalize_book_number("22"),
            trusted=True,
        )
        self.assertEqual(result, "Dragon Emperor")

    def test_multiple_distinct_trailing_parentheticals_only_strip_last(self):
        # Guard against the nested-bracket regex over-matching across
        # separate, unrelated trailing bracket groups.
        result = ORGANIZER.strip_series_sequence_parenthetical(
            "Real Title (Something) (Series #2)",
            "Series",
            ORGANIZER.normalize_book_number("2"),
        )
        self.assertEqual(result, "Real Title (Something)")


class RebirthReportRegressionTests(unittest.TestCase):
    """End-to-end reproduction of the organizer report bug for
    Sarah Hawke's "Dread Knight" series: book 4's target folder came out as
    "Book 4 - Rebirth (Dread Knight Book 4)" instead of "Book 4 - Rebirth".
    """

    def test_book_folder_name_drops_redundant_series_annotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book_dir = root / "2025 - Book 4 - Rebirth {Richard Brock, Raya Kane}"
            book_dir.mkdir(parents=True, exist_ok=True)
            audio = book_dir / "Rebirth_-_Sarah_Hawke.m4b"
            audio.touch()
            marker = book_dir / "libraforge.json"
            marker.write_text(
                json.dumps(
                    {
                        "marker": {
                            "audible": {
                                "title": "Rebirth (Dread Knight Book 4)",
                                "chosen_title": "Rebirth (Dread Knight Book 4)",
                                "author": "Sarah Hawke",
                                "narrator": "",
                                "series": "Dread Knight",
                                "sequence": "4",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
            metadata = ORGANIZER.infer_metadata(item, root)
            self.assertEqual(metadata["title"], "Rebirth")
            self.assertEqual(
                ORGANIZER.build_book_folder_name(metadata), "Book 4 - Rebirth"
            )


class DuelistReportRegressionTests(unittest.TestCase):
    """End-to-end reproduction of the organizer report bug for Eric Vall's
    "The Duelist" series: book 12's target folder came out as
    "Book 12 - (The Duelist (Completed Series))" instead of "Book 12".
    """

    def test_book_folder_name_drops_doubled_nested_annotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book_dir = root / "The Duelist 12"
            book_dir.mkdir(parents=True, exist_ok=True)
            audio = book_dir / "Eric Vall - [The Duelist-12] - The Duelist 12.m4b"
            audio.touch()
            marker = book_dir / "libraforge.json"
            marker.write_text(
                json.dumps(
                    {
                        "marker": {
                            "audible": {
                                "title": "The Duelist 12 (The Duelist (Completed Series))",
                                "chosen_title": "The Duelist 12 (The Duelist (Completed Series))",
                                "author": "Eric Vall",
                                "narrator": "",
                                "series": "The Duelist",
                                "sequence": "12",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
            metadata = ORGANIZER.infer_metadata(item, root)
            self.assertEqual(metadata["title"], "The Duelist")
            self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Book 12")


if __name__ == "__main__":
    unittest.main()
