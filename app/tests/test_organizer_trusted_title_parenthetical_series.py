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


class BareSequenceAnnotationTests(unittest.TestCase):
    """Trailing "(Book N)"/"(Vol. N)" annotations that do NOT repeat the
    series name inside the brackets. strip_series_sequence_parenthetical()
    only fires when the series name appears inside the group, so these fell
    through untouched even after the earlier nested-bracket fix.
    """

    def test_bare_book_parenthetical_without_series_name_is_stripped(self):
        # "His Dark Materials: The Subtle Knife (Book 2)" -- once the leading
        # series prefix is removed, "(Book 2)" has no series name in it at
        # all, so it needs its own bracket-aware trailing-sequence stripper.
        result = ORGANIZER.clean_book_title(
            "His Dark Materials: The Subtle Knife (Book 2)",
            "His Dark Materials",
            ORGANIZER.normalize_book_number("2"),
            trusted=True,
        )
        self.assertEqual(result, "The Subtle Knife")

    def test_bare_vol_parenthetical_exposes_trailing_series_name(self):
        # "Morningwood: Everybody Loves Large Chests (Vol.1)" -- stripping
        # "(Vol.1)" alone leaves "Morningwood - Everybody Loves Large
        # Chests"; the now-trailing series name must also be stripped to
        # reach the real unique title "Morningwood".
        result = ORGANIZER.clean_book_title(
            "Morningwood: Everybody Loves Large Chests (Vol.1)",
            "Everybody Loves Large Chests",
            ORGANIZER.normalize_book_number("1"),
            trusted=True,
        )
        self.assertEqual(result, "Morningwood")


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


class SubtleKnifeReportRegressionTests(unittest.TestCase):
    """End-to-end reproduction of the organizer report bug for Philip
    Pullman's "His Dark Materials" series: book 2's target folder came out
    as "Book 2 - The Subtle Knife (Book 2)" instead of "Book 2 - The Subtle
    Knife".
    """

    def test_book_folder_name_drops_bare_book_annotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book_dir = root / "His Dark Materials The Subtle Knife (Book 2)"
            book_dir.mkdir(parents=True, exist_ok=True)
            audio = book_dir / "His Dark Materials The Subtle Knife (Book 2).m4b"
            audio.touch()
            marker = book_dir / "libraforge.json"
            marker.write_text(
                json.dumps(
                    {
                        "marker": {
                            "audible": {
                                "title": "His Dark Materials: The Subtle Knife (Book 2)",
                                "chosen_title": "His Dark Materials: The Subtle Knife (Book 2)",
                                "author": "Philip Pullman",
                                "narrator": "",
                                "series": "His Dark Materials",
                                "sequence": "2",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
            metadata = ORGANIZER.infer_metadata(item, root)
            self.assertEqual(metadata["title"], "The Subtle Knife")
            self.assertEqual(
                ORGANIZER.build_book_folder_name(metadata), "Book 2 - The Subtle Knife"
            )


class MorningwoodReportRegressionTests(unittest.TestCase):
    """End-to-end reproduction of the organizer report bug for Neven Iliev's
    "Everybody Loves Large Chests" series: volume 1's target folder came out
    as "Vol. 1 - Morningwood - Everybody Loves Large Chests (Vol.1)" instead
    of "Vol. 1 - Morningwood".
    """

    def test_book_folder_name_drops_bare_vol_annotation_and_series_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book_dir = root / "Morningwood Everybody Loves Large Chests (Vol.1)"
            book_dir.mkdir(parents=True, exist_ok=True)
            audio = book_dir / "Morningwood Everybody Loves Large Chests (Vol.1).m4b"
            audio.touch()
            marker = book_dir / "libraforge.json"
            marker.write_text(
                json.dumps(
                    {
                        "marker": {
                            "audible": {
                                "title": "Morningwood: Everybody Loves Large Chests (Vol.1)",
                                "chosen_title": "Morningwood: Everybody Loves Large Chests (Vol.1)",
                                "author": "Neven Iliev",
                                "narrator": "",
                                "series": "Everybody Loves Large Chests",
                                "sequence": "1",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
            metadata = ORGANIZER.infer_metadata(item, root)
            self.assertEqual(metadata["title"], "Morningwood")
            self.assertEqual(
                ORGANIZER.build_book_folder_name(metadata), "Vol. 1 - Morningwood"
            )


if __name__ == "__main__":
    unittest.main()
