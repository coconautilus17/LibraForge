"""Folder Forge title cleaning, one stripper at a time and then end to end
through clean_book_title(). Each row is a title as found in the wild, the series
and number the organizer knows, and the title it must end up with."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_title_cleaning", SCRIPT_PATH)
ORG = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORG
SPEC.loader.exec_module(ORG)


class SequenceLabelForSeriesTests(unittest.TestCase):
    def test_the_spelling_used_in_the_title_wins(self):
        for title, expected in (("Cradle Vol. 3", "Vol."), ("Cradle Volume 3", "Volume"), ("Cradle Vol 3", "Vol."), ("Cradle V3", "Vol.")):
            with self.subTest(title=title):
                self.assertEqual(ORG.title_sequence_label_for_series(title, "Cradle", "003"), expected)

    def test_the_number_pattern_ignores_zero_padding_and_accepts_ranges(self):
        for number, expected in (("3", "0*3"), ("003", "0*3"), ("3.5", r"0*3(?:\.0*5)?"), ("1-2", r"0*1\s*[-+]\s*0*2"),
                                 ("1+2", r"0*1\s*[-+]\s*0*2"), ("abc", "abc"), ("", "")):
            with self.subTest(number=number):
                self.assertEqual(ORG.number_match_pattern(number), expected)


class CleanBookTitleTests(unittest.TestCase):
    def clean(self, title, series="", number="", trusted=False, **kw):
        return ORG.clean_book_title(title, series, number, trusted=trusted, **kw)

    def test_trusted_titles_lose_marketing_suffixes_and_release_tokens(self):
        self.assertEqual(self.clean("1% Lifesteal: A LitRPG Adventure", "1% Lifesteal", "001", True), "1% Lifesteal")
        self.assertEqual(self.clean("Unsouled (128k)", "Cradle", "001", True), "Unsouled")
        self.assertEqual(self.clean("Unsouled [WEB]", "Cradle", "001", True), "Unsouled")
        self.assertEqual(self.clean("Unsouled (A series, Book 7)", "Cradle", "007", True), "Unsouled")

    def test_an_empty_trusted_title_uses_the_fallback(self):
        self.assertEqual(self.clean("", "Cradle", "001", True), "Unknown Title")
        self.assertEqual(self.clean("", "Cradle", "001", True, fallback="Nothing"), "Nothing")


class StripAuthorNarratorNoiseTests(unittest.TestCase):
    def strip(self, title, author, narrator="", trusted=False):
        return ORG.strip_author_narrator_noise_from_title(title, author, narrator, trusted)

    def test_a_trailing_by_clause_is_removed_only_for_a_known_author(self):
        self.assertEqual(self.strip("Title by Will Wight", "Will Wight"), "Title")
        self.assertEqual(self.strip("Title by Someone Else", "Will Wight"), "Title by Someone Else")

class SeriesSuffixNumberTests(unittest.TestCase):
    def test_years_other_series_and_bare_titles_have_no_suffix_number(self):
        for title, series in (("Cradle 2016", "Cradle"), ("Cradle", "Cradle"), ("Other 03", "Cradle"), ("Cradle 12345", "Cradle"),
                              ("", "Cradle"), ("Cradle 3", "")):
            with self.subTest(title=title, series=series):
                self.assertEqual(ORG.metadata_series_suffix_number(title, series), "")

    def test_the_small_variant_only_accepts_one_or_two_digits(self):
        self.assertEqual(ORG.small_series_suffix_number_from_text("Cradle 2", "Cradle"), "002")
        self.assertEqual(ORG.small_series_suffix_number_from_text("Cradle 12", "Cradle"), "012")
        self.assertEqual(ORG.small_series_suffix_number_from_text("Cradle 2.5", "Cradle"), "002.5")

class DistinctBookTitleTests(unittest.TestCase):
    def test_restating_the_series_or_the_number_is_not_distinct(self):
        for title in ("Cradle", "Book 1", "1", "Cradle Book 1", "Book One", "Volume 1"):
            with self.subTest(title=title):
                self.assertFalse(ORG.has_distinct_book_title(title, "Cradle", "001"), title)

if __name__ == "__main__":
    unittest.main()
