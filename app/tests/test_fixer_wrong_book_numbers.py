"""Two wrong books from the matching benchmark, both a tie at 1.0 broken on runtime.

#495: the file states book 3 ("The End: Zombie Fallout, Book 3"); book 4, "The End
Has Come and Gone", was forgiven as one number off and won on runtime.
#496: "What If? 2" was taken for "What If?", whose title names no number.
"""
import unittest

from app.fixer.scoring import (
    main_title,
    pick_best_match_for_metadata,
    same_series_other_title,
    score_product_for_metadata,
    title_adds_a_number,
)


def listing(asin, title, minutes, series=None, sequence="", author="Mark Tufo", narrator="Sean Runnette"):
    return {
        "asin": asin, "title": title, "runtime_length_min": minutes,
        "authors": [{"name": author}], "narrators": [{"name": narrator}],
        "series": [{"title": series, "sequence": sequence}] if series else [],
    }


THE_END = {"title": "The End", "raw_title": "The End: Zombie Fallout, Book 3", "series": "Zombie Fallout",
           "book_number": "3", "book_number_source": "title", "author": "Mark Tufo"}
BOOK_3 = listing("B07YXFFFQ6", "The End", 639, "Zombie Fallout", "3")
BOOK_4 = listing("B083XL9H4F", "The End Has Come and Gone", 655, "Zombie Fallout", "4")

WHAT_IF = {"title": "What If?: Serious Scientific Answers to Absurd Hypothetical Questions",
           "raw_title": "What If?: Serious Scientific Answers to Absurd Hypothetical Questions",
           "author": "Randall Munroe"}
WHAT_IF_2 = listing("B09R2JQVCN", "What If? 2", 395, author="Randall Munroe", narrator="Wil Wheaton")
WHAT_IF_ORIGINAL = listing("B00LV6V4UW", "What If?", 396, author="Randall Munroe", narrator="Wil Wheaton")


class SameSeriesOtherBookTests(unittest.TestCase):
    def test_main_title_drops_the_subtitle_and_punctuation(self):
        self.assertEqual(main_title("The End: Zombie Fallout, Book 3"), "the end")
        self.assertEqual(main_title("What If?: Serious Scientific Answers"), "what if")

    def test_the_next_book_of_the_series_is_not_forgiven_as_one_number_off(self):
        self.assertTrue(same_series_other_title(THE_END, BOOK_4))
        self.assertEqual(score_product_for_metadata(THE_END, BOOK_4, 653.0), 0.0)

    def test_the_book_itself_wins_even_with_the_further_runtime(self):
        product, score, _ = pick_best_match_for_metadata(THE_END, [BOOK_4, BOOK_3], 653.0)
        self.assertEqual(product["asin"], "B07YXFFFQ6")
        self.assertGreater(score, 0.0)

    def test_a_sub_series_listing_keeps_the_numbering_allowance(self):
        clues = {"title": "Of Dawn and Darkness", "series": "The Elder Empire", "book_number": "3",
                 "book_number_source": "title", "author": "Will Wight"}
        sea = listing("B0X", "Of Dawn and Darkness", 600, "The Elder Empire: Sea", "2", author="Will Wight")
        self.assertFalse(same_series_other_title(clues, sea))

    def test_the_same_title_numbered_one_apart_keeps_the_allowance(self):
        clues = {"title": "Super Sales on Super Heroes 2", "series": "Super Sales on Super Heroes",
                 "book_number": "2", "book_number_source": "title", "author": "William D. Arand"}
        same = listing("B0Y", "Super Sales on Super Heroes 2", 700, "Super Sales on Super Heroes", "1",
                       author="William D. Arand")
        self.assertFalse(same_series_other_title(clues, same))

    def test_a_subtitle_alone_is_not_another_book(self):
        clues = {"title": "Dragon Emperor 5", "series": "Dragon Emperor", "book_number": "5",
                 "book_number_source": "title", "author": "Eric Vall"}
        subtitled = listing("B0Z", "Dragon Emperor 5: From Human to Dragon to God", 540, "Dragon Emperor", "5",
                            author="Eric Vall")
        self.assertFalse(same_series_other_title(clues, subtitled))


class NumberedLaterBookTests(unittest.TestCase):
    def test_a_sequel_is_not_the_first_book(self):
        self.assertTrue(title_adds_a_number(WHAT_IF, WHAT_IF_2))
        self.assertTrue(title_adds_a_number(WHAT_IF, listing("B09RG8MD3N", "What If?2", 394, author="Randall Munroe")))
        self.assertEqual(score_product_for_metadata(WHAT_IF, WHAT_IF_2, 396.9), 0.0)

    def test_the_first_book_still_matches(self):
        self.assertFalse(title_adds_a_number(WHAT_IF, WHAT_IF_ORIGINAL))
        self.assertGreater(score_product_for_metadata(WHAT_IF, WHAT_IF_ORIGINAL, 396.9), 0.7)

    def test_a_file_that_names_its_number_is_left_to_the_number_checks(self):
        numbered = dict(WHAT_IF, title="What If? 2", raw_title="What If? 2")
        self.assertFalse(title_adds_a_number(numbered, WHAT_IF_2))
        by_folder = dict(WHAT_IF, book_number="2", book_number_source="path")
        self.assertFalse(title_adds_a_number(by_folder, WHAT_IF_2))

    def test_a_title_that_is_a_number_itself_is_not_a_sequel(self):
        clues = {"title": "Fahrenheit 451", "author": "Ray Bradbury"}
        self.assertFalse(title_adds_a_number(clues, listing("B1", "Fahrenheit 451", 300, author="Ray Bradbury")))


if __name__ == "__main__":
    unittest.main()
