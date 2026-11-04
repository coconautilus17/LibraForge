"""The hand-made folder layout "Author; Series; Book NN; Title" (#502): its series is
read when the name has exactly that shape and its first part is the book's author,
into a clue of its own that picks among a listing's series and names the series
search. Nothing else changes: the layout's titles are the library's own short forms,
its numbers are read as before, and a listing's score never meets the folder's name."""
import unittest
from pathlib import Path

from app.fixer.clues import apply_structured_path_override
from app.fixer.parsing import parse_structured_book_text, semicolon_layout_series
from app.fixer.scoring import get_primary_series, score_product_for_metadata, with_preferred_series


def book(name):
    return Path(f"/books/Author/{name}/{name}.m4b")


class SemicolonLayoutTests(unittest.TestCase):
    def test_the_series_is_read(self):
        self.assertEqual(semicolon_layout_series(book("Larry Correia; The Malcontents; Book 01; Into the Storm"),
                                                 known_author="Larry Correia"), "The Malcontents")

    def test_an_unnumbered_book_or_a_collection_still_names_its_series(self):
        self.assertEqual(semicolon_layout_series(book("B.V. Larson; Star Force; Book XX; Army of One"),
                                                 known_author="B.V. Larson"), "Star Force")
        self.assertEqual(semicolon_layout_series(book("Adrian J. Smith; The Extinction; Book 01-03; New Zealand"),
                                                 known_author="Adrian J. Smith"), "The Extinction")

    def test_a_co_authored_books_credit_still_fits(self):
        self.assertEqual(semicolon_layout_series(book("Larry Correia; Monster Hunter Memoirs; Book 01; Grunge"),
                                                 known_author="Larry Correia, John Ringo"), "Monster Hunter Memoirs")

    def test_a_first_part_that_is_not_the_books_author_is_not_this_layout(self):
        self.assertEqual(semicolon_layout_series(book("Some Series; Other; Book 02; A Title"),
                                                 known_author="Larry Correia"), "")

    def test_other_semicolon_names_are_not_this_layout(self):
        for name in ("Larry Correia; Into the Storm", "Larry Correia; The Malcontents; Into the Storm",
                     "Larry Correia; The Malcontents; Book 01; Into the Storm; Extra",
                     "Larry Correia; The Malcontents; Chapter 01; Into the Storm"):
            self.assertEqual(semicolon_layout_series(book(name), known_author="Larry Correia"), "", name)

    def test_the_folders_series_is_its_own_clue_and_nothing_else_changes(self):
        clues = {"raw_title": "Zombie Fallout: Zero", "title": "Zombie Fallout: Zero", "series": "",
                 "book_number": "0.5", "book_number_source": "title", "author": "Mark Tufo"}
        out = apply_structured_path_override(dict(clues), book("Mark Tufo; Zombie Fallout; Book 00; Zero"))
        self.assertEqual(out["folder_series"], "Zombie Fallout")
        self.assertEqual({k: v for k, v in out.items() if k != "folder_series"}, clues)

    def test_a_listing_the_library_names_another_way_scores_as_before(self):
        # "Robert Bevan; D6; Book 08; 8D6": Audible files 8d6 under Caverns and Creatures.
        listing = {"asin": "B09G3KCM7S", "title": "8d6", "subtitle": "Caverns and Creatures",
                   "authors": [{"name": "Robert Bevan"}], "runtime_length_min": 450,
                   "series": [{"title": "Caverns and Creatures", "sequence": ""}]}
        clues = {"title": "8d6: Caverns and Creatures", "raw_title": "8d6: Caverns and Creatures",
                 "author": "Robert Bevan", "local_duration_minutes": 450.4}
        before = score_product_for_metadata(clues, listing, 450.4)
        after = score_product_for_metadata({**clues, "folder_series": "D6"}, listing, 450.4)
        self.assertEqual(before, after)

    def test_the_folders_series_picks_among_a_listings_series(self):
        storm = {"title": "Into the Storm", "series": [{"title": "War Machine", "sequence": "5"},
                                                       {"title": "The Malcontents", "sequence": "1"}]}
        chosen = with_preferred_series(storm, {"title": "Into the Storm", "folder_series": "The Malcontents"})
        self.assertEqual(get_primary_series(chosen), ("The Malcontents", "1"))

    def test_the_strict_parser_itself_is_unchanged(self):
        self.assertEqual(parse_structured_book_text("Larry Correia; The Malcontents; Book 01; Into the Storm",
                                                    known_author="Larry Correia"), {})


if __name__ == "__main__":
    unittest.main()
