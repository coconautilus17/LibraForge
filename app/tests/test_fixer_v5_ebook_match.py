"""Ebooks match through the audio fixer's own search and scoring.

The ebook matcher used to be a separate, simpler copy: one query (the epub's
exact title), top result only, a plain title-similarity score accepted from
0.35, and an unthrottled Goodreads client. Zero-padded volume titles
("The Saga of Tanya the Evil, Vol. 04: Dabit Deus His Quoque Finem") got no
Goodreads results at all, and "Tunnel Rat 01" was accepted as "Tunnel Rat 3".
Now match_ebook reuses the fixer's clues, query variants, abs-tract client
(throttle, retries, circuit breaker) and full-match gate.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.fixer import search as fixer_search
from app.fixer.parsing import _authors_compatible, goodreads_title_query_variants

ROOT = Path(__file__).parents[2]
if "audible" not in sys.modules:
    stub = types.ModuleType("audible")
    stub.Client = stub.Authenticator = type("Stub", (), {})
    sys.modules["audible"] = stub
_spec = importlib.util.spec_from_file_location("fixer_v5_ebook_match", ROOT / "scripts/audible-metadata-fixer-v5.py")
FIXER = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = FIXER
_spec.loader.exec_module(FIXER)

TANYA_4 = {
    "title": "The Saga of Tanya the Evil, Vol. 04: Dabit Deus His Quoque Finem", "author": "Carlo Zen",
    "series": "The Saga of Tanya the Evil", "book_number": "4", "local_duration_minutes": None,
}


def product(title, author, series="", sequence="", provider="goodreads", cover="https://gr/c.jpg", summary="About."):
    return {
        "asin": "", "title": title, "subtitle": "", "authors": [{"name": author}], "narrators": [],
        "series": [{"title": series, "sequence": sequence}] if series else [],
        "publisher_summary": summary, "product_images": {"500": cover}, "runtime_length_min": None,
        "release_date": "2020", "_abs_provider": provider, "_abs_isbn": "", "_abs_genres": [],
    }


TANYA_4_GR = product("The Saga of Tanya the Evil, Vol. 4: Dabit Deus His Quoque Finem", "Carlo Zen",
                     "The Saga of Tanya the Evil", "4")


def goodreads_knows_only_unpadded(title, **_):
    # Live abs-tract behavior: "Vol. 04: <subtitle>" -> 0 results, "Vol. 4: <subtitle>" -> the book.
    return [TANYA_4_GR] if "Vol. 4" in title else []


class QueryVariantTests(unittest.TestCase):
    def test_zero_padded_volume_is_unpadded_first(self):
        variants = goodreads_title_query_variants(TANYA_4["title"])
        self.assertIn("Vol. 4", variants[0])
        self.assertNotIn("04", variants[0])

    def test_the_original_title_is_still_tried(self):
        self.assertIn(TANYA_4["title"], goodreads_title_query_variants(TANYA_4["title"]))


class AuthorMiddleNameTests(unittest.TestCase):
    # The Guns of August epub credits "Barbara Wertheim Tuchman"; Goodreads
    # and Open Library list "Barbara W. Tuchman".
    def test_middle_name_and_its_initial_are_the_same_author(self):
        self.assertTrue(_authors_compatible("Barbara Wertheim Tuchman", "Barbara W. Tuchman"))

    def test_missing_middle_name_is_the_same_author(self):
        self.assertTrue(_authors_compatible("Barbara Tuchman", "Barbara W. Tuchman"))

    def test_surname_first_credit_is_one_person(self):
        # Postwar's epub credits "Judt, Tony"; the library also has "Crash, Aaron".
        self.assertTrue(_authors_compatible("Judt, Tony", "Tony Judt"))
        self.assertTrue(_authors_compatible("Sullivan, Michael J.", "Michael J. Sullivan"))

    def test_comma_separated_co_authors_still_split(self):
        self.assertTrue(_authors_compatible("Brendan Burns, Joe Beda", "Joe Beda"))
        self.assertFalse(_authors_compatible("Judt, Tony", "Tony Blair"))

    def test_same_surname_different_first_name_is_not_the_same_author(self):
        self.assertFalse(_authors_compatible("Mary Tuchman", "Barbara W. Tuchman"))


class MatchEbookTests(unittest.TestCase):
    def setUp(self):
        with fixer_search._ABS_TRACT_BREAKER_LOCK:
            fixer_search._ABS_TRACT_BREAKER.update(consecutive_failures=0, open_until=0.0, logged_open=False)

    def match(self, clues, ol=(), gr=None, abs_tract_url="http://abs-tract:5555"):
        with patch.object(FIXER, "abs_search", return_value=list(ol)) as ol_mock, \
             patch.object(FIXER, "abs_tract_search", side_effect=gr or (lambda **_: [])) as gr_mock:
            result = FIXER.match_ebook(clues, abs_url="http://abs", abs_api_key="k", abs_tract_url=abs_tract_url)
        return result, ol_mock, gr_mock

    def test_padded_volume_matches_through_the_unpadded_query(self):
        result, _, _ = self.match(TANYA_4, gr=goodreads_knows_only_unpadded)
        self.assertEqual(result["product"]["title"], TANYA_4_GR["title"])
        self.assertEqual(result["provider"], "goodreads")
        self.assertIn("Vol. 4", result["query"])
        self.assertGreaterEqual(result["score"], 0.7)

    def test_a_different_volume_is_rejected(self):
        clues = {"title": "Tunnel Rat", "author": "Walrus King", "series": "", "book_number": "1"}
        wrong = product("Tunnel Rat 3", "Walrus King", "Tunnel Rat", "3")
        result, _, _ = self.match(clues, gr=lambda **_: [wrong])
        self.assertIsNone(result["product"])

    def test_open_circuit_breaker_skips_goodreads_and_says_so(self):
        with fixer_search._ABS_TRACT_BREAKER_LOCK:
            fixer_search._ABS_TRACT_BREAKER["open_until"] = 9e18
        result, _, gr_mock = self.match(TANYA_4, gr=goodreads_knows_only_unpadded)
        gr_mock.assert_not_called()
        self.assertIsNone(result["product"])
        self.assertTrue(result["goodreads_rate_limited"])

    def test_complete_open_library_match_needs_no_goodreads_call(self):
        clues = {"title": "The Guns of August", "author": "Barbara W. Tuchman", "series": "", "book_number": ""}
        ol = product("The Guns of August", "Barbara W. Tuchman", provider="openlibrary")
        result, _, gr_mock = self.match(clues, ol=[ol])
        gr_mock.assert_not_called()
        self.assertEqual(result["provider"], "openlibrary")

    def test_open_library_cover_and_summary_are_backfilled_from_goodreads(self):
        clues = {"title": "The Guns of August", "author": "Barbara W. Tuchman", "series": "", "book_number": ""}
        ol = product("The Guns of August", "Barbara W. Tuchman", provider="openlibrary", cover="", summary="")
        gr = product("The Guns of August", "Barbara W. Tuchman")
        result, _, _ = self.match(clues, ol=[ol], gr=lambda **_: [gr])
        self.assertEqual(result["provider"], "openlibrary")
        self.assertEqual(result["product"]["product_images"]["500"], "https://gr/c.jpg")
        self.assertEqual(result["product"]["publisher_summary"], "About.")

    def test_no_abs_tract_configured_uses_open_library_alone(self):
        clues = {"title": "The Guns of August", "author": "Barbara W. Tuchman", "series": "", "book_number": ""}
        ol = product("The Guns of August", "Barbara W. Tuchman", provider="openlibrary", cover="", summary="")
        result, _, gr_mock = self.match(clues, ol=[ol], abs_tract_url="")
        gr_mock.assert_not_called()
        self.assertEqual(result["provider"], "openlibrary")

    def test_nothing_found_anywhere(self):
        result, _, _ = self.match(TANYA_4)
        self.assertIsNone(result["product"])
        self.assertFalse(result["goodreads_rate_limited"])


if __name__ == "__main__":
    unittest.main()
