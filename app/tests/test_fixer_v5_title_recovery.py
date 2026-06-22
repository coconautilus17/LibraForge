"""Tests for is_generic_chapter_title, is_invalid_local_title, and
normalize_for_match changes introduced to support title recovery."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    audible_stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = audible_stub


def load_fixer():
    path = ROOT / "scripts" / "audible-metadata-fixer-v5.py"
    spec = importlib.util.spec_from_file_location("audible_fixer_v5", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fixer = load_fixer()
is_generic = fixer.is_generic_chapter_title
is_invalid = fixer.is_invalid_local_title
normalize  = fixer.normalize_for_match


class GenericChapterTitleTests(unittest.TestCase):
    # ── existing patterns still work ──────────────────────────────────────
    def test_numeric_chapter_is_generic(self):
        self.assertTrue(is_generic("chapter 5"))

    def test_track_number_is_generic(self):
        self.assertTrue(is_generic("track 3"))

    def test_bare_number_is_generic(self):
        self.assertTrue(is_generic("42"))

    # ── episode patterns ──────────────────────────────────────────────────
    def test_episode_number_is_generic(self):
        self.assertTrue(is_generic("Episode 6"))

    def test_episode_number_with_subtitle_is_generic(self):
        # "Episode Six - Possession" normalizes to "episode six possession"
        self.assertTrue(is_generic("episode six possession"))

    def test_episode_word_number_is_generic(self):
        self.assertTrue(is_generic("episode six"))

    def test_episode_twelve_is_generic(self):
        self.assertTrue(is_generic("episode twelve"))

    # ── lecture patterns ──────────────────────────────────────────────────
    def test_lecture_number_is_generic(self):
        self.assertTrue(is_generic("lecture 10"))

    def test_lecture_number_with_subtitle_is_generic(self):
        self.assertTrue(is_generic("lecture 10 your plan to prevent burnout"))

    # ── word-form chapter patterns ────────────────────────────────────────
    def test_chapter_word_number_is_generic(self):
        self.assertTrue(is_generic("chapter forty-two"))

    def test_chapter_one_is_generic(self):
        self.assertTrue(is_generic("chapter one"))

    def test_chapter_thirty_three_is_generic(self):
        self.assertTrue(is_generic("chapter thirty three"))

    # ── filler/bonus patterns ─────────────────────────────────────────────
    def test_bloopers_is_generic(self):
        self.assertTrue(is_generic("bloopers"))

    def test_bonus_content_is_generic(self):
        self.assertTrue(is_generic("bonus content"))

    def test_bonus_material_is_generic(self):
        self.assertTrue(is_generic("bonus material"))

    def test_the_story_continues_is_generic(self):
        self.assertTrue(is_generic("the story continues in harry potter"))

    # ── real titles must NOT be flagged ───────────────────────────────────
    def test_real_title_not_generic(self):
        self.assertFalse(is_generic("The Name of the Wind"))

    def test_episode_as_real_title_word_not_generic(self):
        # "Episode" alone, or in a real title context, should not match
        # episode-number patterns (requires a number/word after it)
        self.assertFalse(is_generic("episode"))

    def test_chapter_alone_not_generic(self):
        # bare "chapter" with no identifier is not a pattern
        self.assertFalse(is_generic("chapter"))

    def test_short_title_not_generic(self):
        self.assertFalse(is_generic("Dune"))


class InvalidLocalTitleAuthorPrefixTests(unittest.TestCase):
    """is_invalid_local_title should catch "Author - Title" rip format."""

    def test_author_prefix_flagged(self):
        self.assertTrue(is_invalid("Dean Koontz - The Mask", "Dean Koontz"))

    def test_author_prefix_with_initials_flagged(self):
        self.assertTrue(is_invalid("Arthur C. Clarke - 2001", "Arthur C. Clarke"))

    def test_author_prefix_brandon_sanderson(self):
        self.assertTrue(is_invalid("Brandon Sanderson - Shadows of Self", "Brandon Sanderson"))

    def test_author_prefix_series_book(self):
        self.assertTrue(is_invalid("Ben Bova - Powersat", "Ben Bova"))

    def test_title_without_author_prefix_not_flagged(self):
        self.assertFalse(is_invalid("The Mask", "Dean Koontz"))

    def test_title_equal_to_author_still_flagged(self):
        # existing behavior: title == author
        self.assertTrue(is_invalid("Dean Koontz", "Dean Koontz"))

    def test_short_author_not_matched(self):
        # Author name under 4 chars should not trigger the prefix check
        # to avoid false positives on single-name / initials authors
        self.assertFalse(is_invalid("Bob the Builder", "Bob"))

    def test_unrelated_title_not_flagged(self):
        self.assertFalse(is_invalid("Dune", "Frank Herbert"))

    def test_empty_title_flagged(self):
        self.assertTrue(is_invalid("", "Anyone"))

    def test_generic_chapter_still_flagged(self):
        self.assertTrue(is_invalid("Chapter 1", "Anyone"))


class NormalizeBookNumberStripTests(unittest.TestCase):
    """normalize_for_match should strip 'Book #N' and 'Vol. #N' patterns."""

    def test_book_hash_number_stripped(self):
        # "The Grand Tour, Book #1" should normalize to "the grand tour"
        result = normalize("The Grand Tour, Book #1")
        self.assertNotIn("book", result)
        self.assertNotIn("#1", result)
        self.assertIn("grand tour", result)

    def test_book_number_without_hash_stripped(self):
        result = normalize("Mistborn, Book 3")
        self.assertNotIn("book", result)
        self.assertIn("mistborn", result)

    def test_volume_hash_number_stripped(self):
        result = normalize("Some Series, Vol. #2")
        self.assertNotIn("vol", result)
        self.assertNotIn("#2", result)

    def test_series_name_preserved(self):
        result = normalize("The Grand Tour, Book #1")
        self.assertIn("grand tour", result)

    def test_plain_title_unchanged(self):
        result = normalize("Dune")
        self.assertEqual(result, "dune")


if __name__ == "__main__":
    unittest.main()
