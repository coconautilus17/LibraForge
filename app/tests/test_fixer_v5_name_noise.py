"""Name/series noise cleanup in the v5 fixer's local parsing.

Regression cases from Metadata Forge run 20260928-194730: release-group and
publisher brackets, bare "Audiobook"/"Unabridged" words, "Audiobook:"
prefixes, and genre/format parentheticals adopted as the series name
("light novel", "A LitRPG series, Book 7").
"""
import unittest

from app.fixer.parsing import (
    clean_author_value,
    clean_series_value,
    parse_title_series_number_from_metadata,
    sanitize_book_title,
)


class TitleNoiseTests(unittest.TestCase):
    def test_bare_trailing_format_words_are_removed(self):
        self.assertEqual(
            sanitize_book_title(
                "The Saga of Tanya the Evil, Vol. 05: Abyssus Abyssum Invocat Audiobook"
            ),
            "The Saga of Tanya the Evil, Vol. 05: Abyssus Abyssum Invocat",
        )
        self.assertEqual(
            sanitize_book_title(
                "1177 B.C. (Revised and Updated) The Year Civilization Collapsed "
                "By Eric H. Cline Unabridged Audiobook"
            ),
            "1177 B.C. (Revised and Updated) The Year Civilization Collapsed By Eric H. Cline",
        )

    def test_leading_audiobook_label_is_removed(self):
        self.assertEqual(
            sanitize_book_title("Audiobook: Cannabis (Seeing Through the Smoke)"),
            "Cannabis (Seeing Through the Smoke)",
        )

    def test_mid_title_format_parenthetical_and_release_brackets_are_removed(self):
        self.assertEqual(
            sanitize_book_title(
                "[PZG] The Saga of Tanya the Evil, Vol. 07 (Audiobook) [Yen Audio]"
            ),
            "The Saga of Tanya the Evil, Vol. 07",
        )

    def test_real_title_words_survive(self):
        # "Unabridged"/"Audiobook" inside a real title, not at the edges.
        self.assertEqual(
            sanitize_book_title("The Unabridged Journals of Sylvia Plath"),
            "The Unabridged Journals of Sylvia Plath",
        )
        # A bracketed word that is not a release tag or publisher stays.
        self.assertEqual(
            sanitize_book_title("Dark Age (3 of 3) [Dramatized Adaptation]"),
            sanitize_book_title("Dark Age (3 of 3) [Dramatized Adaptation]"),
        )


class AuthorNoiseTests(unittest.TestCase):
    def test_release_group_bracket_is_not_an_author(self):
        self.assertEqual(clean_author_value("[PZG]"), "")

    def test_series_hint_parenthetical_still_removed(self):
        self.assertEqual(clean_author_value("Aaron Crash (American Dragons)"), "Aaron Crash")


class SeriesNoiseTests(unittest.TestCase):
    def test_format_parenthetical_is_not_the_series(self):
        self.assertEqual(
            clean_series_value("The Saga of Tanya the Evil (light novel)"),
            "The Saga of Tanya the Evil",
        )

    def test_genre_descriptor_parenthetical_is_not_the_series(self):
        self.assertEqual(
            clean_series_value("The Idle System (A LitRPG series, Book 7)"),
            "The Idle System",
        )

    def test_reading_order_parenthetical_is_not_the_series(self):
        self.assertEqual(
            clean_series_value("A Jack Ryan Novel (publication order)"),
            "A Jack Ryan Novel",
        )

    def test_real_series_parenthetical_still_preferred(self):
        self.assertEqual(clean_series_value("Aaron Crash (American Dragons)"), "American Dragons")


class NeverASeriesTests(unittest.TestCase):
    """Values that make no sense as a series name are dropped wherever a
    series is read: genre names, marketing phrases, format/generic words,
    publishers and bare numbers."""

    def test_genre_and_marketing_values_are_not_series(self):
        for value in ["LitRPG", "Fantasy", "Science Fiction", "A LitRPG Series",
                      "A LitRPG Adventure", "An Epic Fantasy Novel"]:
            with self.subTest(value=value):
                self.assertEqual(clean_series_value(value), "")

    def test_generic_format_and_publisher_values_are_not_series(self):
        for value in ["Series", "Standalone", "Novella", "Box Set", "Light Novel",
                      "Unabridged Audiobook", "Podium Audio", "Book #1-5", "Book 3", "#2"]:
            with self.subTest(value=value):
                self.assertEqual(clean_series_value(value), "")

    def test_real_series_names_survive(self):
        for value in ["Cradle", "The Titan Series", "A Jack Ryan Novel", "Dungeon Crawler Carl",
                      "Mythos", "The Tower Series", "Detroit Free Zone (DFZ)",
                      "Star Force Universe (Jyr)", "Origins (Robinson)"]:
            with self.subTest(value=value):
                self.assertEqual(clean_series_value(value), value)

    def test_edition_descriptor_parentheticals_are_dropped(self):
        self.assertEqual(clean_series_value("Harry Potter (Full-Cast Editions)"), "Harry Potter")
        self.assertEqual(clean_series_value("Star Wars Legends (Chronological)"), "Star Wars Legends")

    def test_audible_series_that_is_a_genre_is_not_written(self):
        from app.fixer.scoring import get_primary_series

        # Audible files Arthur Stone's "The Weirdest Noob" under series "LitRPG" #1.
        self.assertEqual(
            get_primary_series({"series": [{"title": "LitRPG", "sequence": "1"}]}), ("", "")
        )
        self.assertEqual(
            get_primary_series({"series": [{"title": "Cradle", "sequence": "1"}]}), ("Cradle", "1")
        )


class AsinTagTests(unittest.TestCase):
    def test_audible_asin_tag_is_read(self):
        from app.fixer.clues import read_current_book_metadata

        current = read_current_book_metadata(
            {"album": "The Saga of Tanya the Evil, Vol. 08", "audible_asin": "b0ccf77hkv"}
        )
        self.assertEqual(current["asin"], "B0CCF77HKV")


if __name__ == "__main__":
    unittest.main()
