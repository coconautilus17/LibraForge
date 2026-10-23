import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


def make_metadata(**overrides):
    metadata = {
        "title": "Bold Beginnings",
        "author": "G.D. Brooks",
        "series": "Dashing Devil",
        "narrator": "Full Cast",
    }
    metadata.update(overrides)
    return metadata


class MatchesSkipPatternsTests(unittest.TestCase):
    def test_no_patterns_never_matches(self):
        matched, pattern = ORGANIZER.matches_skip_patterns(
            Path("/audiobooks/Casual Farming/Book 1"), make_metadata(), []
        )
        self.assertFalse(matched)
        self.assertEqual(pattern, "")

    def test_matches_the_path_title_or_author(self):
        for label, path, metadata, pattern in (
            ("path substring, case-insensitively", "/audiobooks/Casual Farming/Book 1", make_metadata(), "casual farming"),
            ("title field", "/audiobooks/Some Folder", make_metadata(title="Bold Beginnings"), "bold beginnings"),
            ("author field", "/audiobooks/Some Folder", make_metadata(author="G.D. Brooks"), "g.d. brooks"),
        ):
            with self.subTest(label):
                matched, matched_pattern = ORGANIZER.matches_skip_patterns(Path(path), metadata, [pattern])
                self.assertIs(matched, True)
                self.assertEqual(matched_pattern, pattern)

    def test_matches_series_field(self):
        matched, pattern = ORGANIZER.matches_skip_patterns(
            Path("/audiobooks/Some Folder"),
            make_metadata(series="Dashing Devil"),
            ["dashing devil"],
        )
        self.assertIs(matched, True)
        self.assertEqual(pattern, "dashing devil")

    def test_matches_narrator_field(self):
        matched, pattern = ORGANIZER.matches_skip_patterns(
            Path("/audiobooks/Some Folder"),
            make_metadata(narrator="Full Cast"),
            ["full cast"],
        )
        self.assertIs(matched, True)
        self.assertEqual(pattern, "full cast")

    def test_no_match_returns_false(self):
        matched, pattern = ORGANIZER.matches_skip_patterns(
            Path("/audiobooks/Some Folder"), make_metadata(), ["nonexistent phrase"]
        )
        self.assertFalse(matched)
        self.assertEqual(pattern, "")

    def test_returns_first_matching_pattern(self):
        matched, pattern = ORGANIZER.matches_skip_patterns(
            Path("/audiobooks/Casual Farming/Book 1"),
            make_metadata(),
            ["nonexistent", "casual farming", "bold beginnings"],
        )
        self.assertTrue(matched)
        self.assertEqual(pattern, "casual farming")


if __name__ == "__main__":
    unittest.main()
