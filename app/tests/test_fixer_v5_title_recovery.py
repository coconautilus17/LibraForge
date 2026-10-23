"""Tests for is_generic_chapter_title, is_invalid_local_title, and
normalize_for_match changes introduced to support title recovery."""
import unittest
from app.tests.script_loader import load_script


fixer = load_script("audible_fixer_v5", "audible-metadata-fixer-v5.py")
is_generic = fixer.is_generic_chapter_title
is_invalid = fixer.is_invalid_local_title
normalize  = fixer.normalize_for_match


class GenericChapterTitleTests(unittest.TestCase):
    # chapter, track, episode, lecture, word-form chapter and filler/bonus patterns
    def test_chapter_episode_lecture_and_credit_titles_are_generic(self):
        for title in (
            "chapter 5",
            "track 3",
            "42",
            "Episode 6",
            # "Episode Six - Possession" normalizes to "episode six possession"
            "episode six possession",
            "episode six",
            "episode twelve",
            "lecture 10",
            "lecture 10 your plan to prevent burnout",
            "chapter forty-two",
            "chapter one",
            "chapter thirty three",
            "bloopers",
            "bonus content",
            "bonus material",
            "the story continues in harry potter",
        ):
            with self.subTest(title=title):
                self.assertTrue(is_generic(title))

    def test_real_titles_are_not_generic(self):
        for title in (
            "The Name of the Wind",
            # "Episode" alone, or in a real title context, should not match
            # episode-number patterns (requires a number/word after it)
            "episode",
            # bare "chapter" with no identifier is not a pattern
            "chapter",
            "Dune",
        ):
            with self.subTest(title=title):
                self.assertFalse(is_generic(title))


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

    def test_plain_title_unchanged(self):
        result = normalize("Dune")
        self.assertEqual(result, "dune")


class TitleSeriesBareNumberParseTests(unittest.TestCase):
    """`Title - Series, N` filename parsing (bare trailing number, no "Book")."""

    def test_title_series_bare_number(self):
        result = fixer.parse_structured_book_text("The Primal Talisman - Beast Shifter, 3")
        self.assertEqual(result.get("series"), "Beast Shifter")
        self.assertEqual(result.get("book_number"), "3")
        self.assertEqual(result.get("title"), "The Primal Talisman")

    def test_existing_book_keyword_format_still_parses(self):
        # Regression guard: the "Book N - Author" variant is unchanged.
        result = fixer.parse_structured_book_text(
            "The Primal Talisman - Beast Shifter, Book 1 - Dante King"
        )
        self.assertEqual(result.get("series"), "Beast Shifter")
        self.assertEqual(result.get("book_number"), "1")
        self.assertEqual(result.get("title"), "The Primal Talisman")

    def test_year_suffix_not_treated_as_book_number(self):
        # A 4-digit trailing number (year) must not be parsed as "Series, N".
        result = fixer.parse_structured_book_text("Some Title - Some Series, 2021")
        self.assertEqual(result, {})

    def test_plain_dash_title_not_misparsed(self):
        # No trailing ", N" -> the bare-number rule must not fire.
        result = fixer.parse_structured_book_text("Author Name - Some Title")
        self.assertEqual(result, {})


class SeriesNumberAuthorParseTests(unittest.TestCase):
    """`Series N - Author Name` (e.g. grouped folders) must not stamp the
    author as the book title; series/number are salvaged instead."""

    def test_trailing_author_dropped_as_title(self):
        result = fixer.parse_structured_book_text(
            "Backyard Dungeon 18 - Logan Jacobs", known_author="Logan Jacobs"
        )
        self.assertEqual(result.get("series"), "Backyard Dungeon")
        self.assertEqual(result.get("book_number"), "18")
        self.assertFalse(result.get("title"))

    def test_multi_author_trailing_dropped(self):
        # Trailing is one entry of a multi-author tag string.
        result = fixer.parse_structured_book_text(
            "Dungeon Explorers 3 - Alex Prone",
            known_author="Alex Prone, Marcus Sloss",
        )
        self.assertEqual(result.get("series"), "Dungeon Explorers")
        self.assertEqual(result.get("book_number"), "3")
        self.assertFalse(result.get("title"))

    def test_real_title_preserved_with_known_author(self):
        # A genuine title is kept even when the author is known.
        result = fixer.parse_structured_book_text(
            "Saving Supervillains 2 - The Reckoning", known_author="Bruce Sentar"
        )
        self.assertEqual(result.get("series"), "Saving Supervillains")
        self.assertEqual(result.get("book_number"), "2")
        self.assertEqual(result.get("title"), "The Reckoning")

    def test_embedded_author_in_title_not_dropped(self):
        # Author merely embedded in a longer trailing title -> later parser wins,
        # the title is not collapsed to the author.
        result = fixer.parse_structured_book_text(
            "2025 - Book 1 - Arcane Artificer {Gary Furlong}",
            known_author="Gary Furlong",
        )
        self.assertIn("Arcane Artificer", result.get("title", ""))

    def test_no_known_author_unchanged(self):
        # Without a known author the legacy behaviour is preserved.
        result = fixer.parse_structured_book_text("Backyard Dungeon 18 - Logan Jacobs")
        self.assertEqual(result.get("series"), "Backyard Dungeon")
        self.assertEqual(result.get("title"), "Logan Jacobs")


if __name__ == "__main__":
    unittest.main()
