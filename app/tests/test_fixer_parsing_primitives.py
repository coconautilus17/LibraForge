"""Direct tests of the small text helpers in app.fixer.parsing. Most were only
exercised through bigger scenarios before, where a flipped branch could pass
unnoticed because the scenario happened to take another route."""
import unittest
from pathlib import Path

from app.fixer import parsing as p


class SanitizeTechnicalLabelsTests(unittest.TestCase):
    def test_release_group_publisher_format_and_codec_brackets_are_removed(self):
        for raw in ("Title [PZG]", "Title [Yen Audio]", "Title (Audiobook)", "Title [mp3]"):
            with self.subTest(raw=raw):
                self.assertEqual(p.sanitize_technical_labels(raw), "Title")

    def test_a_meaningful_parenthetical_survives(self):
        self.assertEqual(p.sanitize_technical_labels("Title (Real Part)"), "Title (Real Part)")

    def test_the_label_removal_applies_repeatedly_for_more_than_two_trailing_blocks(self):
        self.assertEqual(p.sanitize_technical_labels("Title [PZG] [mp3] [Yen Audio]"), "Title")


class ParentheticalTests(unittest.TestCase):
    def test_the_first_group_of_two_or_more_characters_is_returned_cleaned(self):
        self.assertEqual(p.extract_first_parenthetical("A (Book Two) B (More)"), "Book Two")

    def test_a_single_character_or_missing_group_is_empty_string(self):
        for raw in ("A (x)", "A", "", None):
            self.assertEqual(p.extract_first_parenthetical(raw), "")


class LooksLikePersonNameTests(unittest.TestCase):
    def test_ordinary_names_pass(self):
        for name in ("Will Wight", "J. R. R. Tolkien", "Brandon Sanderson Jr", "Jean-Paul Sartre", "Patrick O'Brian"):
            with self.subTest(name=name):
                self.assertIs(p.looks_like_person_name(name), True)

    def test_titles_numbers_and_wrong_lengths_fail(self):
        for name in ("Will", "A B C D E F", "The Cradle Man", "Book One Man", "Will Wight 2020", "Cradle [1]", "",
                     "Lord of Darkness", "Cradle Of Fire", "Sir of the Rings Man"):
            with self.subTest(name=name):
                self.assertIs(p.looks_like_person_name(name), False)

    def test_two_to_five_words_are_the_allowed_range(self):
        self.assertIs(p.looks_like_person_name("Ann Lee"), True)
        self.assertIs(p.looks_like_person_name("Ann Beth Cole Dana Eve"), True)
        self.assertIs(p.looks_like_person_name("Ann Beth Cole Dana Eve Fay"), False)

    def test_function_words_are_only_forbidden_in_the_middle(self):
        self.assertIs(p.looks_like_person_name("Ludwig van Beethoven"), True)
        self.assertIs(p.looks_like_person_name("Ann of Lee"), False)


class IsNeverSeriesTests(unittest.TestCase):
    def test_genres_marketing_formats_numbers_and_publishers_are_never_series(self):
        for value in ("LitRPG", "A LitRPG Series", "Standalone", "Box Set", "3", "Book 3", "Tantor Audio", "Fantasy"):
            with self.subTest(value=value):
                self.assertIs(p.is_never_series(value), True)

    def test_real_series_names_and_blank_are_not(self):
        for value in ("Cradle", "Wheel of Time", "", None):
            with self.subTest(value=value):
                self.assertIs(p.is_never_series(value), False)


class NormalizeBookNumberTests(unittest.TestCase):
    def test_leading_zeros_and_whitespace_go_and_decimals_lose_trailing_zeros(self):
        for raw, expected in (("1", "1"), ("01", "1"), (" 3 ", "3"), ("1.50", "1.5"), ("2.5", "2.5"),
                              ("1.05", "1.05"), ("1.0", "1.0"), ("007.250", "7.25")):
            with self.subTest(raw=raw):
                self.assertEqual(p.normalize_book_number(raw), expected)

    def test_blank_and_non_numeric_values_pass_through_trimmed(self):
        self.assertEqual(p.normalize_book_number(""), "")
        self.assertEqual(p.normalize_book_number(None), "")
        self.assertEqual(p.normalize_book_number("abc"), "abc")
        self.assertEqual(p.normalize_book_number(" abc "), "abc")


class BookNumberRangeTests(unittest.TestCase):
    def test_dash_to_through_and_ampersand_ranges(self):
        for raw, expected in (("Books 1-3", (1, 3)), ("Book 5 to 7", (5, 7)), ("Volumes 2 – 4", (2, 4)),
                              ("10 through 12", (10, 12)), ("Books 1 & 2", (1, 2)), ("Books 011 012", (11, 12))):
            with self.subTest(raw=raw):
                self.assertEqual(p.parse_book_number_range(raw), expected)

    def test_no_range_backwards_or_implausibly_wide_ranges_are_none(self):
        for raw in ("Book 1", "", None, "7-3", "1-100"):
            with self.subTest(raw=raw):
                self.assertIsNone(p.parse_book_number_range(raw))

    def test_a_span_of_exactly_fifty_is_accepted_and_fifty_one_is_not(self):
        self.assertEqual(p.parse_book_number_range("1-51"), (1, 51))
        self.assertIsNone(p.parse_book_number_range("1-52"))

    def test_equal_ends_are_a_valid_range(self):
        self.assertEqual(p.parse_book_number_range("3-3"), (3, 3))


class PickValueTests(unittest.TestCase):
    def test_most_common_ignores_blanks_and_empty_input_is_empty_string(self):
        self.assertEqual(p.pick_most_common_value(["a", "b", "a"]), "a")
        self.assertEqual(p.pick_most_common_value(["", "a"]), "a")
        self.assertEqual(p.pick_most_common_value([]), "")
        self.assertEqual(p.pick_most_common_value(["", ""]), "")

    def test_majority_needs_more_than_half_of_the_total(self):
        self.assertEqual(p.pick_majority_value(["a", "a", "b"], 3), "a")
        self.assertEqual(p.pick_majority_value(["a", "a"], 3), "a")
        self.assertEqual(p.pick_majority_value(["a", "b"], 3), "")
        self.assertEqual(p.pick_majority_value(["a", "a"], 4), "")
        self.assertEqual(p.pick_majority_value([], 3), "")


class GenericChapterTitleTests(unittest.TestCase):
    def test_numbered_and_structural_labels_are_generic(self):
        for title in ("Chapter 1", "Track 02", "Opening Credits", "Part 3", "Intro"):
            with self.subTest(title=title):
                self.assertIs(p.is_generic_chapter_title(title), True)

    def test_real_titles_are_not(self):
        for title in ("Real Title", "Prologue", "The Warlock"):
            with self.subTest(title=title):
                self.assertIs(p.is_generic_chapter_title(title), False)


class SearchNoiseTests(unittest.TestCase):
    def test_a_listening_to_prefix_and_trailing_by_author_are_removed(self):
        self.assertEqual(p.strip_title_search_noise("Listening to Dirk Gently by Douglas Adams", "Douglas Adams"), "Dirk Gently")
        self.assertEqual(p.strip_title_search_noise("Unsouled by Will Wight", "Will Wight"), "Unsouled")

    def test_a_by_clause_naming_someone_else_is_kept(self):
        self.assertEqual(p.strip_title_search_noise("Foo by Someone Else", "Will Wight"), "Foo by Someone Else")

    def test_a_clean_title_and_a_missing_author_are_fine(self):
        self.assertEqual(p.strip_title_search_noise("Unsouled", ""), "Unsouled")
        self.assertEqual(p.strip_title_search_noise("Unsouled", "Will Wight"), "Unsouled")


class GoodreadsTitleVariantsTests(unittest.TestCase):
    def test_a_padded_book_number_gets_a_plain_variant_first_and_the_original_second(self):
        self.assertEqual(p.goodreads_title_query_variants("Cradle - Book 001 - Unsouled"),
                         ["Cradle - 1 - Unsouled", "Cradle - Book 001 - Unsouled"])

    def test_a_plain_title_is_its_own_only_variant_and_empty_gives_none(self):
        self.assertEqual(p.goodreads_title_query_variants("Unsouled"), ["Unsouled"])
        self.assertEqual(p.goodreads_title_query_variants(""), [])


class BookNumberFromTextTests(unittest.TestCase):
    def test_each_explicit_notation_is_read(self):
        for raw, expected in (("Cradle Book 3", "3"), ("Cradle, Book 4", "4"), ("Vol. 2", "2"), ("Volume 7.5", "7.5"),
                              ("V2 Title", "2"), ("Title #5", "5"), ("Book #12 of stuff", "12")):
            with self.subTest(raw=raw):
                self.assertEqual(p.extract_book_number_from_text(raw), expected)

    def test_ranges_and_numberless_text_give_an_empty_string(self):
        for raw in ("Books 1-3", "Title #5-6", "Title", ""):
            with self.subTest(raw=raw):
                self.assertEqual(p.extract_book_number_from_text(raw), "")


class BookNumberFromPathTests(unittest.TestCase):
    def test_the_file_name_the_folder_and_the_grandparent_are_searched_in_that_order(self):
        for path, expected in (("/lib/A/S/Book 3 - X/f.m4b", "3"), ("/lib/A/Series Name Book 2/f.m4b", "2"),
                               ("/lib/Series 5/Sub/f.m4b", "5"), ("/lib/A/B/Title Vol 4.m4b", "4"),
                               ("/lib/A/Book 6/x/f.m4b", "6")):
            with self.subTest(path=path):
                self.assertEqual(p.extract_book_number_from_path(Path(path)), expected)

    def test_a_file_name_number_beats_a_folder_number(self):
        self.assertEqual(p.extract_book_number_from_path(Path("/lib/Book 9/Title Book 2.m4b")), "2")

    def test_nothing_numbered_gives_an_empty_string(self):
        self.assertEqual(p.extract_book_number_from_path(Path("/lib/plain/plain/plain.m4b")), "")


class LocalNumberIdentityTests(unittest.TestCase):
    def test_a_path_or_title_sourced_number_is_a_candidate_and_duplicates_collapse(self):
        got = p.get_local_number_identity_candidates(
            {"book_number": "03", "book_number_source": "path", "title": "Cradle Book 3"})
        self.assertEqual(got, ["3"])

    def test_a_track_sourced_number_is_not(self):
        self.assertEqual(p.get_local_number_identity_candidates({"book_number": "03", "book_number_source": "track", "title": "Plain"}), [])

    def test_numbers_named_in_several_fields_are_all_listed_once(self):
        got = p.get_local_number_identity_candidates({"title": "Cradle Book 3", "raw_title": "Cradle Book 4", "series": "Cradle Book 3"})
        self.assertEqual(got, ["3", "4"])

    def test_no_clues_no_candidates(self):
        self.assertEqual(p.get_local_number_identity_candidates({}), [])


class SearchNoiseEdgeTests(unittest.TestCase):
    def test_blank_input_is_returned_as_given(self):
        self.assertEqual(p.strip_title_search_noise("", "x"), "")
        self.assertIsNone(p.strip_title_search_noise(None, "x"))

    def test_a_by_clause_with_a_book_number_is_noise_even_for_an_unknown_author(self):
        self.assertEqual(p.strip_title_search_noise("Dirk by Douglas Adams 1", "Other"), "Dirk")

    def test_a_by_clause_in_a_real_title_survives(self):
        self.assertEqual(p.strip_title_search_noise("Death by Black Hole", "Neil Tyson"), "Death by Black Hole")


class GenericTitleBlankTests(unittest.TestCase):
    def test_a_blank_title_is_generic(self):
        self.assertIs(p.is_generic_chapter_title(""), True)
        self.assertIs(p.is_generic_chapter_title("   "), True)

    def test_a_chapter_of_total_label_is_generic(self):
        self.assertIs(p.is_generic_chapter_title("Chapter 3 of 40"), True)


class TitleIdentityNumberTests(unittest.TestCase):
    def test_a_number_that_is_part_of_the_title_is_identity_evidence(self):
        for raw, expected in (("The Lost Bloodline 5", "5"), ("Overpowered Wizard 3: A Progression LitRPG Epic", "3"),
                              ("All the Skills 6", "6"), ("Title 5 by Someone", "5"),
                              ("Title [B0ABCDEFGH] 4", "4"), ("Series 2.5", "2.5")):
            with self.subTest(raw=raw):
                self.assertEqual(p.extract_title_identity_number(raw), expected)

    def test_years_ranges_percentages_and_numberless_titles_give_nothing(self):
        for raw in ("Dune", "100% Pure", "Books 1-3 here", "Title (2020)", "1177 B.C.", ""):
            with self.subTest(raw=raw):
                self.assertEqual(p.extract_title_identity_number(raw), "")

    def test_a_title_only_number_still_becomes_a_local_identity_candidate(self):
        self.assertEqual(p.get_local_number_identity_candidates({"title": "The Lost Bloodline 5"}), ["5"])
        self.assertEqual(p.get_local_number_identity_candidates({"series": "All the Skills 6", "title": "x"}), ["6"])


class DescriptiveBookTextTests(unittest.TestCase):
    def parse(self, value, known=""):
        return p.parse_descriptive_book_text(value, known)

    def test_a_read_by_credit_names_the_narrator_and_leaves_author_and_title(self):
        got = self.parse("Virgil - The Aeneid (Read by David Collins)")
        self.assertEqual((got["author"], got["title"], got["narrator"], got["year"], got["series"]),
                         ("Virgil", "The Aeneid", "David Collins", "", ""))
        self.assertEqual(got["raw_title"], "Virgil - The Aeneid (Read by David Collins)")

    def test_title_author_and_a_numbered_trailing_segment_is_title_author_series(self):
        got = self.parse("Unsouled - Will Wight - Book 1")
        self.assertEqual((got["title"], got["author"], got["book_number"], got["narrator"]), ("Unsouled", "Will Wight", "1", ""))
        got = self.parse("Unsouled - Will Wight - Cradle 1")
        self.assertEqual((got["title"], got["author"], got["series"], got["book_number"]), ("Unsouled", "Will Wight", "Cradle 1", "1"))

    def test_three_segments_need_a_person_in_the_middle(self):
        self.assertEqual(self.parse("Unsouled - Cradle Of Fire - Book 1"), {})

    def test_author_year_title_narrator_form(self):
        got = self.parse("Will Wight (2016) Unsouled (Travis Baldree)")
        self.assertEqual((got["author"], got["title"], got["year"], got["narrator"]),
                         ("Will Wight", "Unsouled", "2016", "Travis Baldree"))

    def test_an_unabridged_note_in_that_form_is_not_a_narrator(self):
        got = self.parse("Will Wight (2016) Unsouled (Unabridged)")
        self.assertEqual((got["title"], got["narrator"]), ("Unsouled", ""))

    def test_the_year_form_without_a_narrator_has_an_empty_narrator_string(self):
        got = self.parse("Will Wight (2016) Unsouled")
        self.assertEqual((got["title"], got["narrator"]), ("Unsouled", ""))

    def test_the_year_form_rejects_a_generic_title_or_a_non_person_author(self):
        self.assertEqual(self.parse("Will Wight (2016) Chapter 1"), {})
        self.assertEqual(self.parse("Cradle Of Fire (2016) Unsouled"), {})

    def test_two_segments_use_the_known_author_to_decide_which_side_is_which(self):
        for text in ("Will Wight - Unsouled", "Unsouled - Will Wight"):
            with self.subTest(text=text):
                got = self.parse(text, "Will Wight")
                self.assertEqual((got["author"], got["title"]), ("Will Wight", "Unsouled"))

    def test_two_segments_without_a_known_author_fall_back_to_which_side_looks_like_a_person(self):
        for text in ("Will Wight - Unsouled", "Unsouled - Will Wight"):
            with self.subTest(text=text):
                got = self.parse(text)
                self.assertEqual((got["author"], got["title"]), ("Will Wight", "Unsouled"))

    def test_a_known_author_that_matches_neither_side_gives_up(self):
        self.assertEqual(self.parse("Unsouled - Will Wight", "Someone Different"), {})
        self.assertEqual(self.parse("Unsouled - Cradle", "Will Wight"), {})

    def test_nothing_recognisable_gives_an_empty_dict(self):
        for text in ("Hello - World", "", "Just a title"):
            self.assertEqual(self.parse(text), {})


if __name__ == "__main__":
    unittest.main()
