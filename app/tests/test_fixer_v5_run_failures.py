"""Failures from the forced full Metadata Forge run 20260928-231259-50a3d3ef
on /audiobooks/_unorganized, one class per root cause."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub


def _load_fixer():
    spec = importlib.util.spec_from_file_location("fixer_v5_run_failures", ROOT / "scripts/audible-metadata-fixer-v5.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = _load_fixer()


def group_clues(folder, per_file):
    """Run the grouped-book clue builder over files whose own parsed clues are
    `per_file` (one dict per file)."""
    files = [Path(f"{folder}/{i:02d}.mp3") for i in range(1, len(per_file) + 1)]
    base = {"raw_title": "", "title": "", "series": "", "tag_series": "", "book_number": "",
            "book_number_source": "", "author": "", "narrator": "", "album": ""}
    with (
        patch.object(FIXER, "build_search_clues_from_file",
                     side_effect=[{**base, **c} for c in per_file]),
        patch.object(FIXER, "probe_file", return_value=({}, 30.0)),
        patch.object(FIXER, "validate_multi_part_group_files", return_value={}),
    ):
        return FIXER.build_multi_file_search_context(files)[1]


class PartNumbersAreNotABookNumberTests(unittest.TestCase):
    """48 Laws of Power 01..52 and 1177 B.C.'s 1..N.mp3: each part file parsed
    as "series + book N", so the group took an arbitrary part index (10) as
    its book number and the title as its series."""

    def test_distinct_part_numbers_give_no_book_number_or_series(self):
        per_file = [{"title": "48 Laws of Power", "series": "48 Laws of Power",
                     "book_number": str(n), "book_number_source": "path", "author": "Robert Greene"}
                    for n in range(1, 13)]
        clues = group_clues("/u/48 Laws of Power (Unabridged) - Robert Greene", per_file)
        self.assertEqual(clues["book_number"], "")
        self.assertEqual(clues["series"], "")

    def test_a_number_all_parts_agree_on_is_the_book_number(self):
        per_file = [{"title": "Deeper", "series": "Tunnels", "book_number": "2",
                     "book_number_source": "path"} for _ in range(4)]
        clues = group_clues("/u/Deeper", per_file)
        self.assertEqual(clues["book_number"], "2")
        self.assertEqual(clues["series"], "Tunnels")


class LeadingNumberInTitleTests(unittest.TestCase):
    """1177 B.C.: the leading "1177" was stripped as an ordering prefix."""

    def test_title_numbers_are_kept(self):
        for title in ["1177 B.C. The Year Civilization Collapsed", "2001 A Space Odyssey"]:
            with self.subTest(title=title):
                self.assertEqual(FIXER.strip_leading_sequence_from_title(title), title)

    def test_ordering_prefixes_are_still_stripped(self):
        for value, expected in [("01 Deeper", "Deeper"), ("001 Deeper", "Deeper"), ("1 - Deeper", "Deeper"),
                                ("Book 3 - Deeper", "Deeper"), ("2011 - Guns, Germs And Steel", "Guns, Germs And Steel")]:
            with self.subTest(value=value):
                self.assertEqual(FIXER.strip_leading_sequence_from_title(value), expected)


class AuthorInTitleTests(unittest.TestCase):
    """1177 B.C.: "... By Eric H. Cline" named the author, but extraction
    required a trailing book number; a name with an initial is evidence
    enough, while "Death by Black Hole" stays a title."""

    def test_name_with_an_initial_is_extracted(self):
        self.assertEqual(
            FIXER.extract_author_from_title("1177 B.C. The Year Civilization Collapsed By Eric H. Cline"),
            "Eric H. Cline",
        )

    def test_plain_words_after_by_are_not_an_author(self):
        self.assertEqual(FIXER.extract_author_from_title("Death by Black Hole"), "")

    def test_grouped_folder_title_gives_author_and_clean_title(self):
        folder = ("/u/1177 B.C. (Revised and Updated) The Year Civilization Collapsed "
                  "By Eric H. Cline Unabridged Audiobook")
        clues = group_clues(folder, [{"book_number": str(n), "book_number_source": "path"} for n in range(1, 6)])
        self.assertEqual(clues["author"], "Eric H. Cline")
        self.assertEqual(clues["title"], "1177 B.C. (Revised and Updated) The Year Civilization Collapsed")


if __name__ == "__main__":
    unittest.main()
