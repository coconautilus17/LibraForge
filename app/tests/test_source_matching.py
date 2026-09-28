"""Enrichment Forge matches other sources' books with Metadata Forge's own
matcher and acceptance (pick_best_match_for_metadata + determine_edit_mode),
the same decision as the fixer's Goodreads fallback."""
import unittest

from app import source_matching as sm

WARLOCK = {"title": "12 Miles Below - Book 005 - The Warlock", "author": "Mark Arrows", "series_name": "12 Miles Below",
           "sequence": "5", "existing_narrator": "", "duration_minutes": None}
UNSOULED = {"title": "Cradle - Book 001 - Unsouled", "author": "Will Wight", "series_name": "Cradle", "sequence": "1",
            "existing_narrator": "", "duration_minutes": None}


def audiosilo(title, author, series="", seq=""):
    match = {"title": title, "author": author, "series": [{"series": series, "sequence": seq}] if series else []}
    return sm.provider_product(match, "audiosilo"), title


def sparse(title, author, provider="openlibrary"):
    return sm.provider_product({"title": title, "author": author}, provider), title


class SourceMatchingTests(unittest.TestCase):
    def test_picks_the_right_book_among_other_authors_same_titles(self):
        cands = [audiosilo("The Warlock 2", "Dante King"), audiosilo("The Warlock: Book 1", "Dante King"),
                 audiosilo("12 Miles Below V: The Warlock", "Mark Arrows", "12 Miles Below", "5")]
        self.assertEqual(sm.best_candidate(WARLOCK, cands), "12 Miles Below V: The Warlock")

    def test_a_different_author_is_never_the_same_book(self):
        self.assertIsNone(sm.best_candidate(UNSOULED, [audiosilo("Unsouled", "Someone Else")]))

    def test_open_library_uses_the_fixers_sparse_source_rule(self):
        self.assertEqual(sm.best_candidate(UNSOULED, [sparse("Unsouled", "Will Wight")]), "Unsouled")
        self.assertIsNone(sm.best_candidate(UNSOULED, [sparse("Soulsmith", "Will Wight")]))
        self.assertIsNone(sm.best_candidate(UNSOULED, [sparse("Unsouled", "Someone Else")]))

    def test_goodreads_uses_the_same_rule(self):
        self.assertEqual(sm.best_candidate(UNSOULED, [sparse("Unsouled", "Will Wight", "goodreads")]), "Unsouled")

    def test_no_candidates(self):
        self.assertIsNone(sm.best_candidate(UNSOULED, []))


class TiedEditionsTests(unittest.TestCase):
    def test_identical_editions_tying_are_still_the_book(self):
        # Open Library returns several editions of the same book: a tie
        # between them is not doubt about which book it is.
        cands = [sparse("Unsouled", "Will Wight"), sparse("Unsouled", "Will Wight"), sparse("Unsouled", "Will Wight")]
        self.assertEqual(sm.best_candidate(UNSOULED, cands), "Unsouled")
