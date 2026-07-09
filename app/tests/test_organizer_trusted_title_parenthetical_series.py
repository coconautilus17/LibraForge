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


if __name__ == "__main__":
    unittest.main()
