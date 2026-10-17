"""Direct tests of the small text helpers of Folder Forge
(scripts/organize-audiobooks-by-metadata-v3_13.py): book numbers, sequence
labels, author credits and generic folder names. Most were only reached through
whole-plan scenarios before."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_text_helpers", SCRIPT_PATH)
ORG = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORG
SPEC.loader.exec_module(ORG)


class NormalizeBookNumberTests(unittest.TestCase):
    def test_numbers_are_zero_padded_to_three_digits_by_default(self):
        for raw, expected in (("1", "001"), ("001", "001"), (" 7 ", "007"), ("12", "012"), ("3.5", "003.5"), ("1.50", "001.5")):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.normalize_book_number(raw), expected)

    def test_the_width_can_be_changed(self):
        self.assertEqual(ORG.normalize_book_number("7", 2), "07")
        self.assertEqual(ORG.normalize_book_number("7", 5), "00007")

    def test_every_range_separator_becomes_a_dash(self):
        for raw in ("1-2", "1+2", "1,2", "1 – 2", "01-02"):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.normalize_book_number(raw), "001-002")

    def test_ranges_with_decimal_zero_ends_are_still_ranges(self):
        self.assertEqual(ORG.normalize_book_number("1.0-2.0"), "001-002")

    def test_blank_oversized_and_non_numeric_values_pass_through(self):
        self.assertEqual(ORG.normalize_book_number(""), "")
        self.assertEqual(ORG.normalize_book_number("12345"), "12345")
        self.assertEqual(ORG.normalize_book_number("abc"), "abc")

    @unittest.expectedFailure
    def test_a_whole_number_written_with_a_zero_decimal_should_not_keep_a_dangling_dot(self):
        # KNOWN BUG (see docs/test-audit-2026-10-16.md): "1.0" becomes "001." because
        # ".0".rstrip("0") is "." (truthy), so the `or ".0"` fallback never applies.
        self.assertFalse(ORG.normalize_book_number("1.0").endswith("."))


class RomanNumeralTests(unittest.TestCase):
    def test_canonical_numerals_are_converted(self):
        for raw, expected in (("V", "5"), ("IV", "4"), ("x", "10"), ("MCMXC", "1990"), (" IX ", "9"), ("III", "3")):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.roman_numeral_value(raw), expected)

    def test_malformed_numerals_words_and_blanks_are_not_numbers(self):
        for raw in ("IIII", "VV", "abc", "", "Dim", "MMMM"):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.roman_numeral_value(raw), "")

    def test_a_label_plus_numeral_phrase_gives_the_number(self):
        for raw, expected in (("Book III", "3"), ("Vol. IV", "4"), ("Volume V", "5"), ("Side Story II", "2"), ("Novel X", "10")):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.label_roman_number(raw), expected)

    def test_other_shapes_are_not_label_numerals(self):
        for raw in ("Book", "III", "Book III extra", "Part III", ""):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.label_roman_number(raw), "")


class SequenceLabelTests(unittest.TestCase):
    def test_labels_are_normalised_to_the_folder_prefix_wording(self):
        for raw, expected in (("vol", "Vol."), ("V", "Vol."), ("Volume", "Volume"), ("volumes", "Volume"), ("Book", "Book"),
                              ("Books", "Book"), ("Side Story", "Side Story"), ("sidestories", "Side Story"),
                              ("novel", "Novel"), ("Novels", "Novel"), ("other", ""), ("", ""), (" Book: ", "Book")):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.normalize_sequence_label(raw), expected)

    def test_a_label_is_only_detected_next_to_a_number(self):
        for text, expected in (("Side Story 2", "Side Story"), ("Novel 3", "Novel"), ("Vol. 4", "Vol."), ("Vols. 1-3", "Vol."),
                               ("Volume 2", "Volume"), ("Book 1", "Book"), ("Book One", "Book"), ("Volume Three", "Volume")):
            with self.subTest(text=text):
                self.assertEqual(ORG.detect_sequence_label_from_text(text), expected)

    def test_ordinary_words_do_not_change_the_prefix(self):
        for text in ("Part 2", "Title", "A Good Book", "", "Novelty 3"):
            with self.subTest(text=text):
                self.assertEqual(ORG.detect_sequence_label_from_text(text), "")


class DetectNumberTests(unittest.TestCase):
    def test_explicit_labels_give_a_padded_number(self):
        for text, expected in (("Book 3", "003"), ("Book #12", "012"), ("Vol. 7", "007"), ("v3", "003"), ("#5", "005"),
                               ("Side Story 2", "002"), ("Novel 4", "004"), ("Book 3.5", "003.5"), ("Book One", "001"),
                               ("Volume Three", "003")):
            with self.subTest(text=text):
                self.assertEqual(ORG.detect_number_from_text(text), expected)

    def test_ascending_ranges_are_recognised_in_all_notations(self):
        for text, expected in (("Books 1-3", "001-003"), ("Books 1, 2", "001-002"), ("#5-6", "005-006"), ("Vols 2-4", "002-004"),
                               ("Books 1+2", "001-002")):
            with self.subTest(text=text):
                self.assertEqual(ORG.detect_number_from_text(text), expected)

    def test_backwards_equal_and_zero_padded_pairs_are_not_ranges(self):
        for text in ("Books 3-1", "Books 2-2", "Books 01-02"):
            with self.subTest(text=text):
                self.assertEqual(ORG.detect_number_from_text(text), "")

    def test_a_trailing_chapter_number_does_not_turn_a_book_number_into_a_range(self):
        self.assertEqual(ORG.detect_number_from_text("Book 3 - 01"), "003")

    def test_unlabelled_numbers_and_years_are_ignored(self):
        for text in ("Cradle 4", "03 Title", "2016", "Part 2", "Title", ""):
            with self.subTest(text=text):
                self.assertEqual(ORG.detect_number_from_text(text), "")


class AuthorCreditHelperTests(unittest.TestCase):
    def test_people_are_split_on_commas_ampersands_and_and_but_not_semicolons(self):
        self.assertEqual(ORG.split_people("Will Wight, Bob Roe"), ["Will Wight", "Bob Roe"])
        self.assertEqual(ORG.split_people("A & B"), ["A", "B"])
        self.assertEqual(ORG.split_people("A and B"), ["A", "B"])
        self.assertEqual(ORG.split_people("Will Wight - translator"), ["Will Wight"])
        self.assertEqual(ORG.split_people(""), [])

    def test_runs_of_initials_collapse_into_a_dotted_cluster(self):
        for raw, expected in (("J. R. R. Tolkien", "J.R.R. Tolkien"), ("J.R.R. Tolkien", "J.R.R. Tolkien"),
                              ("George R. R. Martin", "George R.R. Martin"), ("J Smith", "J. Smith"), ("Ann Lee", "Ann Lee"),
                              ("JRR Tolkien", "JRR Tolkien"), ("", "")):
            with self.subTest(raw=raw):
                self.assertEqual(ORG.canonical_author_name(raw), expected)

    def test_the_primary_author_is_the_first_real_one(self):
        self.assertEqual(ORG.primary_author("Will Wight, Bob Roe"), "Will Wight")
        self.assertEqual(ORG.primary_author("Will Wight & Bob Roe"), "Will Wight")
        self.assertEqual(ORG.primary_author("Will Wight - translator"), "Will Wight")
        self.assertEqual(ORG.primary_author(""), "Unknown Author")

    def test_generic_placeholders_are_skipped_in_favour_of_a_real_author(self):
        self.assertEqual(ORG.primary_author("Unknown Author, Will Wight"), "Will Wight")

    def test_people_keys_are_normalised_and_deduplicated(self):
        self.assertEqual(ORG.people_keys("Will Wight, Bob Roe"), ["willwight", "bobroe"])
        self.assertEqual(ORG.people_keys("Will Wight & Will Wight"), ["willwight"])
        self.assertEqual(ORG.people_keys(""), [])
        self.assertEqual(ORG.people_keys("   "), [])

    def test_keys_match_when_equal_or_nearly_equal(self):
        self.assertTrue(ORG.keys_match("willwight", "willwight"))
        self.assertTrue(ORG.keys_match("a", "a"))
        self.assertTrue(ORG.keys_match("willwightsmith", "willwightsmit"))     # ratio >= 0.92
        self.assertFalse(ORG.keys_match("willwight", "willwigth"))             # below the cut-off
        self.assertFalse(ORG.keys_match("willwight", "bobroe"))
        self.assertFalse(ORG.keys_match("", ""))
        self.assertFalse(ORG.keys_match("a", ""))
        self.assertFalse(ORG.keys_match("", "a"))

    def test_an_author_is_bad_for_a_series_when_blank_generic_or_the_series_itself(self):
        for author, series in (("", "Cradle"), ("Unknown Author", "Cradle"), ("Audiobooks", "Cradle"), ("Cradle", "Cradle"),
                               ("Reborn as a Space", "Reborn as a Space Mercenary - I Woke Up")):
            with self.subTest(author=author, series=series):
                self.assertTrue(ORG.author_is_probably_bad_for_series(author, series))
        self.assertFalse(ORG.author_is_probably_bad_for_series("Will Wight", "Cradle"))
        self.assertFalse(ORG.author_is_probably_bad_for_series("Will Wight", ""))

    def test_a_series_that_is_only_the_author_credit_is_detected(self):
        self.assertTrue(ORG.series_is_author_credit("Will Wight", "Will Wight"))
        self.assertTrue(ORG.series_is_author_credit("Will Wight Bob Roe", "Will Wight, Bob Roe"))
        self.assertTrue(ORG.series_is_author_credit("Bob Roe", "Will Wight, Bob Roe"))
        self.assertFalse(ORG.series_is_author_credit("Cradle", "Will Wight"))
        self.assertFalse(ORG.series_is_author_credit("", "Will Wight"))
        self.assertFalse(ORG.series_is_author_credit("Will Wight", ""))


class GenericStructureNameTests(unittest.TestCase):
    def test_container_and_placeholder_folder_names_are_generic(self):
        for name in ("Audiobooks", "Unknown", "Books", "Library", "", "   ", "2016", "1-3", "Chapterized", "Complete Series",
                     "My Audiobook Collection", "Audio Files"):
            with self.subTest(name=name):
                self.assertTrue(ORG.is_generic_structure_name(name), name)

    def test_real_author_and_series_names_are_not(self):
        for name in ("Will Wight", "Cradle", "Series Of Fire", "The Lost Bloodline"):
            with self.subTest(name=name):
                self.assertFalse(ORG.is_generic_structure_name(name), name)

    def test_digits_with_letters_are_not_a_bare_number(self):
        self.assertFalse(ORG.is_generic_structure_name("2016 Cradle"))
        self.assertFalse(ORG.is_generic_structure_name("12345"))      # five digits are not a book index


class ReleaseTokenTests(unittest.TestCase):
    def test_technical_bracket_tokens_are_recognised(self):
        for token in ("[mp3]", "[m4b]", "[128k]", "[2016]", "[ENG]", "[web]", "[Audible]"):
            with self.subTest(token=token):
                self.assertTrue(ORG.is_release_bracket_token(token), token)

    def test_ordinary_bracketed_text_is_not(self):
        for token in ("[Book 1]", "abc", "[The Warlock]"):
            with self.subTest(token=token):
                self.assertFalse(ORG.is_release_bracket_token(token), token)


if __name__ == "__main__":
    unittest.main()
