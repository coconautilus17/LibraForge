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


class StripLeadingSequenceLabelTests(unittest.TestCase):
    def test_a_label_naming_this_books_own_number_is_dropped(self):
        for title, number, expected in (("Book 1 - Title", "001", "Title"), ("Vol. 2: Title", "2", "Title"),
                                        ("Part 3. Title", "003", "Title"), ("Book 1.5 - Title", "001.5", "Title"),
                                        ("# 4 – Title", "4", "Title")):
            with self.subTest(title=title):
                self.assertEqual(ORG.strip_leading_sequence_label(title, number), expected)

    def test_a_different_number_a_missing_number_or_a_bare_number_title_is_left_alone(self):
        self.assertEqual(ORG.strip_leading_sequence_label("Book 2 - Title", "1"), "Book 2 - Title")
        self.assertEqual(ORG.strip_leading_sequence_label("Book 1 - Title", ""), "Book 1 - Title")
        self.assertEqual(ORG.strip_leading_sequence_label("1984", "001"), "1984")
        self.assertEqual(ORG.strip_leading_sequence_label("7 Habits", "007"), "7 Habits")

    def test_a_label_with_nothing_after_it_is_left_alone(self):
        self.assertEqual(ORG.strip_leading_sequence_label("Book 1 -", "001"), "Book 1 -")


class StripSeriesDescriptorTests(unittest.TestCase):
    def test_a_trailing_parenthetical_mentioning_series_is_removed(self):
        self.assertEqual(ORG.strip_series_descriptor_parenthetical("Title (A LitRPG series, Book 7)"), "Title")
        self.assertEqual(ORG.strip_series_descriptor_parenthetical("Title (The Dark Sorcerer's series)"), "Title")
        self.assertEqual(ORG.strip_series_descriptor_parenthetical("Title - (series) "), "Title")

    def test_other_parentheticals_and_titles_that_would_become_empty_are_kept(self):
        self.assertEqual(ORG.strip_series_descriptor_parenthetical("Title (Not a thing)"), "Title (Not a thing)")
        self.assertEqual(ORG.strip_series_descriptor_parenthetical("(series)"), "(series)")

    def test_a_series_parenthetical_in_the_middle_is_kept(self):
        self.assertEqual(ORG.strip_series_descriptor_parenthetical("Title (series) Part Two"), "Title (series) Part Two")


class StripSeriesPrefixTests(unittest.TestCase):
    def test_a_series_name_followed_by_a_separator_or_number_is_dropped(self):
        for title, series, expected in (("Cradle - Unsouled", "Cradle", "Unsouled"), ("Cradle 1 Unsouled", "Cradle", "1 Unsouled"),
                                        ("The Cradle: Unsouled", "Cradle", "Unsouled"), ("Cradle, Unsouled", "Cradle", "Unsouled")):
            with self.subTest(title=title):
                self.assertEqual(ORG.strip_series_prefix(title, series), expected)

    def test_a_long_series_name_can_be_dropped_without_punctuation(self):
        self.assertEqual(ORG.strip_series_prefix("Dashing Devil Bold Beginnings", "Dashing Devil"), "Bold Beginnings")
        self.assertEqual(ORG.strip_series_prefix("Cradle Unsouled Beginnings", "Cradle"), "Unsouled Beginnings")

    def test_possessives_run_on_words_and_short_series_are_part_of_the_title(self):
        for title, series in (("The Spellmonger's Yule", "Spellmonger"), ("Spellmongers wedding", "Spellmonger"),
                              ("It Ends With Us", "It"), ("The Bright Lord", "The Bright"),
                              ("Shortest History of Reality", "Shortest History")):
            with self.subTest(title=title):
                self.assertEqual(ORG.strip_series_prefix(title, series), title)

    def test_nothing_is_stripped_when_the_title_is_the_series_or_there_is_no_series(self):
        self.assertEqual(ORG.strip_series_prefix("Cradle", "Cradle"), "Cradle")
        self.assertEqual(ORG.strip_series_prefix("Title", ""), "Title")


class SequenceLabelForSeriesTests(unittest.TestCase):
    def test_the_spelling_used_in_the_title_wins(self):
        for title, expected in (("Cradle Vol. 3", "Vol."), ("Cradle Volume 3", "Volume"), ("Cradle Vol 3", "Vol."), ("Cradle V3", "Vol.")):
            with self.subTest(title=title):
                self.assertEqual(ORG.title_sequence_label_for_series(title, "Cradle", "003"), expected)

    def test_a_book_label_or_an_unrelated_series_gives_nothing(self):
        self.assertEqual(ORG.title_sequence_label_for_series("Cradle Book 3", "Cradle", "003"), "")
        self.assertEqual(ORG.title_sequence_label_for_series("Threads of Destiny Vol 1", "Destiny Cycle", "001"), "")

    def test_missing_inputs_give_nothing(self):
        self.assertEqual(ORG.title_sequence_label_for_series("Cradle Vol. 3", "Cradle", ""), "")
        self.assertEqual(ORG.title_sequence_label_for_series("", "Cradle", "003"), "")
        self.assertEqual(ORG.title_sequence_label_for_series("Cradle Vol. 3", "", "003"), "")

    def test_a_title_that_starts_with_the_series_is_required(self):
        self.assertTrue(ORG.title_starts_with_series("Cradle Book 1", "Cradle"))
        self.assertFalse(ORG.title_starts_with_series("The Cradle", "Cradle"))
        self.assertFalse(ORG.title_starts_with_series("Cradle", ""))
        self.assertFalse(ORG.title_starts_with_series("", "Cradle"))

    def test_the_number_pattern_ignores_zero_padding_and_accepts_ranges(self):
        for number, expected in (("3", "0*3"), ("003", "0*3"), ("3.5", r"0*3(?:\.0*5)?"), ("1-2", r"0*1\s*[-+]\s*0*2"),
                                 ("1+2", r"0*1\s*[-+]\s*0*2"), ("abc", "abc"), ("", "")):
            with self.subTest(number=number):
                self.assertEqual(ORG.number_match_pattern(number), expected)


class StripTrailingPartsTests(unittest.TestCase):
    def test_a_trailing_sequence_annotation_for_this_book_is_removed(self):
        for title in ("Unsouled (Book 1)", "Unsouled - Book 1", "Unsouled Vol. 1", "Unsouled, Book 1"):
            with self.subTest(title=title):
                self.assertEqual(ORG.strip_trailing_sequence_from_title(title, "001"), "Unsouled")

    def test_an_annotation_for_another_number_a_bare_number_or_no_number_is_kept(self):
        for title, number in (("Unsouled (Book 2)", "001"), ("Unsouled 1", "001"), ("Unsouled", "001"), ("Unsouled Book 1", "")):
            with self.subTest(title=title):
                self.assertEqual(ORG.strip_trailing_sequence_from_title(title, number), title)

    def test_a_series_name_trailing_a_separator_is_removed(self):
        for title in ("Unsouled - Cradle", "Unsouled: Cradle"):
            with self.subTest(title=title):
                self.assertEqual(ORG.strip_trailing_series_from_title(title, "Cradle"), "Unsouled")

    def test_a_run_on_trailing_series_a_bracketed_one_and_a_title_equal_to_the_series_are_kept(self):
        for title in ("Unsouled Cradle", "Unsouled (Cradle)", "Unsouled", "Cradle"):
            with self.subTest(title=title):
                self.assertEqual(ORG.strip_trailing_series_from_title(title, "Cradle"), title)

    def test_a_book_n_title_that_only_repeats_the_series_collapses_to_the_series(self):
        self.assertEqual(ORG.strip_redundant_series_sequence_title("Cradle Book 1", "Cradle", "001"), "Cradle")
        self.assertEqual(ORG.strip_redundant_series_sequence_title("Cradle 1", "Cradle", "001"), "Cradle")

    def test_a_real_subtitle_or_another_number_is_not_redundant(self):
        for title in ("Cradle Book 2", "Cradle - Unsouled", "Book 1"):
            with self.subTest(title=title):
                self.assertEqual(ORG.strip_redundant_series_sequence_title(title, "Cradle", "001"), title)


class CleanBookTitleTests(unittest.TestCase):
    def clean(self, title, series="", number="", trusted=False, **kw):
        return ORG.clean_book_title(title, series, number, trusted=trusted, **kw)

    def test_both_modes_strip_a_redundant_series_book_annotation(self):
        for trusted in (True, False):
            with self.subTest(trusted=trusted):
                self.assertEqual(self.clean("Rebirth (Dread Knight Book 4)", "Dread Knight", "004", trusted), "Rebirth")
                self.assertEqual(self.clean("Dashing Devil 5 - Bold Beginnings", "Dashing Devil", "005", trusted), "Bold Beginnings")
                self.assertEqual(self.clean("Book 1 - Unsouled", "Cradle", "001", trusted), "Unsouled")

    def test_a_trailing_book_annotation_without_the_series_name_is_stripped(self):
        self.assertEqual(self.clean("The Subtle Knife (Book 2)", "His Dark Materials", "002", True), "The Subtle Knife")

    def test_trusted_titles_lose_marketing_suffixes_and_release_tokens(self):
        self.assertEqual(self.clean("1% Lifesteal: A LitRPG Adventure", "1% Lifesteal", "001", True), "1% Lifesteal")
        self.assertEqual(self.clean("Unsouled (128k)", "Cradle", "001", True), "Unsouled")
        self.assertEqual(self.clean("Unsouled [WEB]", "Cradle", "001", True), "Unsouled")
        self.assertEqual(self.clean("Unsouled (A series, Book 7)", "Cradle", "007", True), "Unsouled")

    def test_a_trusted_title_that_starts_like_the_series_but_is_one_title_stays_whole(self):
        self.assertEqual(self.clean("The Bright Lord", "The Bright", "002", True), "The Bright Lord")

    def test_a_title_that_is_only_the_series_and_a_number_collapses_to_the_series(self):
        self.assertEqual(self.clean("Cradle Book 1", "Cradle", "001", False), "Cradle")
        self.assertEqual(self.clean("Cradle Book 1", "Cradle", "001", True), "Cradle")

    def test_an_exposed_trailing_series_name_is_removed_too(self):
        self.assertEqual(self.clean("Morningwood - Everybody Loves Large Chests (Vol.1)", "Morningwood", "001", True),
                         "Everybody Loves Large Chests")

    def test_a_marketing_only_title_falls_back_to_the_series_when_untrusted(self):
        self.assertEqual(self.clean("A Slice-of-Life LitRPG", "Cradle", "001", False), "Cradle")
        self.assertEqual(self.clean("", "Cradle", "001", False), "Cradle")

    def test_an_empty_trusted_title_uses_the_fallback(self):
        self.assertEqual(self.clean("", "Cradle", "001", True), "Unknown Title")
        self.assertEqual(self.clean("", "Cradle", "001", True, fallback="Nothing"), "Nothing")

    def test_a_plain_title_is_unchanged(self):
        self.assertEqual(self.clean("Unsouled", "", "", False), "Unsouled")
        self.assertEqual(self.clean("Dune", "", "", True), "Dune")

    def test_a_leading_book_number_is_removed_from_an_untrusted_title(self):
        self.assertEqual(self.clean("007 Casino Royale", "Bond", "007", False), "Casino Royale")


class PersonSegmentMatchTests(unittest.TestCase):
    def test_exact_and_slightly_misspelled_names_match(self):
        self.assertTrue(ORG.person_segment_matches("Will Wight", ["Will Wight"]))
        self.assertTrue(ORG.person_segment_matches("Andre Rowe", ["Andrew Rowe"]))
        self.assertTrue(ORG.person_segment_matches("Wil Wight", ["Will Wight"]))

    def test_any_listed_person_can_match(self):
        self.assertTrue(ORG.person_segment_matches("Bob Roe", ["Will Wight", "Bob Roe"]))

    def test_a_partial_name_or_a_long_title_containing_a_name_does_not(self):
        for segment in ("Will", "Wight", "A Long Title Segment Containing Will Wight Inside", "Totally Different", ""):
            with self.subTest(segment=segment):
                self.assertFalse(ORG.person_segment_matches(segment, ["Will Wight"]))

    def test_blank_or_missing_people_never_match(self):
        self.assertFalse(ORG.person_segment_matches("abc", [""]))
        self.assertFalse(ORG.person_segment_matches("abc", []))


class StripAuthorNarratorNoiseTests(unittest.TestCase):
    def strip(self, title, author, narrator="", trusted=False):
        return ORG.strip_author_narrator_noise_from_title(title, author, narrator, trusted)

    def test_a_leading_author_dash_is_removed(self):
        self.assertEqual(self.strip("Ryan Eisenhower - Starship Tigress", "Ryan Eisenhower"), "Starship Tigress")

    def test_a_trailing_author_or_author_and_narrator_dash_is_removed_even_with_a_typo(self):
        self.assertEqual(self.strip("Starship Tigress - Ryan Eisenhower", "Ryan Eisenhower"), "Starship Tigress")
        self.assertEqual(self.strip("How to Defeat - Andre Rowe - Narrator", "Andrew Rowe", "Narrator"), "How to Defeat")

    def test_a_trailing_parenthetical_credit_is_removed_for_known_people_or_person_shaped_text(self):
        self.assertEqual(self.strip("The Grinding (Jeff Hays, Annie Ellicott)", "Someone", "Jeff Hays, Annie Ellicott"), "The Grinding")
        self.assertEqual(self.strip("Title (Some Reader)", "Someone"), "Title")

    def test_a_parenthetical_with_a_number_or_a_non_name_is_kept(self):
        self.assertEqual(self.strip("Title (Book 2)", "Someone"), "Title (Book 2)")
        self.assertEqual(self.strip("Title (Part 3 Special)", "Someone"), "Title (Part 3 Special)")
        self.assertEqual(self.strip("Title (special edition)", "Someone"), "Title (special edition)")

    def test_a_trailing_by_clause_is_removed_only_for_a_known_author(self):
        self.assertEqual(self.strip("Title by Will Wight", "Will Wight"), "Title")
        self.assertEqual(self.strip("Title by Someone Else", "Will Wight"), "Title by Someone Else")

    def test_an_author_name_stuck_to_the_end_is_removed_when_a_real_title_remains(self):
        self.assertEqual(self.strip("Feedback Dennis E. Taylor", "Dennis E. Taylor"), "Feedback")

    def test_nothing_is_removed_when_that_would_leave_no_title(self):
        self.assertEqual(self.strip("Dennis E. Taylor", "Dennis E. Taylor"), "Dennis E. Taylor")
        self.assertEqual(self.strip("Will Wight - Will Wight", "Will Wight"), "Will Wight")

    def test_without_known_people_or_a_title_there_is_nothing_to_do(self):
        self.assertEqual(self.strip("Title", ""), "Title")
        self.assertEqual(self.strip("", "Will Wight"), "")

    def test_trusted_titles_keep_genre_words_that_cleanup_would_wipe(self):
        self.assertEqual(self.strip("The Fifth Law of Cultivation", "Will Wight", trusted=True), "The Fifth Law of Cultivation")

    @unittest.expectedFailure
    def test_a_co_author_prefix_should_be_removed_as_the_docstring_promises(self):
        # KNOWN BUG, issue #376: the docstring lists
        # "Dan Raxor, Jace Cannon - Supers of Vault 12" as handled, but the leading
        # segment is compared with each author separately, so a two-author prefix
        # (ratio ~0.44 against either) never matches and the title keeps it.
        self.assertEqual(self.strip("Dan Raxor, Jace Cannon - Supers of Vault 12", "Dan Raxor, Jace Cannon"), "Supers of Vault 12")


class SeriesSuffixNumberTests(unittest.TestCase):
    def test_a_bare_one_to_four_digit_suffix_after_the_series_is_the_number(self):
        self.assertEqual(ORG.metadata_series_suffix_number("Cradle 03", "Cradle"), "003")
        self.assertEqual(ORG.metadata_series_suffix_number("Cradle 3.5", "Cradle"), "003.5")

    def test_years_other_series_and_bare_titles_have_no_suffix_number(self):
        for title, series in (("Cradle 2016", "Cradle"), ("Cradle", "Cradle"), ("Other 03", "Cradle"), ("Cradle 12345", "Cradle"),
                              ("", "Cradle"), ("Cradle 3", "")):
            with self.subTest(title=title, series=series):
                self.assertEqual(ORG.metadata_series_suffix_number(title, series), "")

    def test_the_small_variant_only_accepts_one_or_two_digits(self):
        self.assertEqual(ORG.small_series_suffix_number_from_text("Cradle 2", "Cradle"), "002")
        self.assertEqual(ORG.small_series_suffix_number_from_text("Cradle 12", "Cradle"), "012")
        self.assertEqual(ORG.small_series_suffix_number_from_text("Cradle 2.5", "Cradle"), "002.5")

    def test_the_small_variant_ignores_course_numbers_years_and_other_series(self):
        for value, series in (("Cradle 204", "Cradle"), ("Cradle 2016", "Cradle"), ("", "Cradle"), ("Cradle 2", ""), ("Other 2", "Cradle")):
            with self.subTest(value=value, series=series):
                self.assertEqual(ORG.small_series_suffix_number_from_text(value, series), "")


class DistinctBookTitleTests(unittest.TestCase):
    def test_a_title_with_content_beyond_the_series_and_number_is_distinct(self):
        self.assertTrue(ORG.has_distinct_book_title("Unsouled", "Cradle", "001"))
        self.assertTrue(ORG.has_distinct_book_title("Cradle - Unsouled", "Cradle", "001"))
        self.assertTrue(ORG.has_distinct_book_title("Unsouled", "", "001"))

    def test_restating_the_series_or_the_number_is_not_distinct(self):
        for title in ("Cradle", "Book 1", "1", "Cradle Book 1", "Book One", "Volume 1"):
            with self.subTest(title=title):
                self.assertFalse(ORG.has_distinct_book_title(title, "Cradle", "001"), title)

    def test_a_roman_numeral_label_for_this_number_is_not_distinct(self):
        self.assertFalse(ORG.has_distinct_book_title("Book III", "Cradle", "003"))

    def test_a_label_for_another_number_is_still_a_bare_label(self):
        self.assertFalse(ORG.has_distinct_book_title("Book 2", "Cradle", "001"))

    def test_an_empty_title_is_not_distinct(self):
        self.assertFalse(ORG.has_distinct_book_title("", "Cradle", "001"))


if __name__ == "__main__":
    unittest.main()
