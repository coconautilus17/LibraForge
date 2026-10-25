"""Direct Goodreads shelves client used by Enrichment Forge.

abs-tract filters Goodreads shelves through a ~48-entry allow-list and keeps
only the first 3, so LitRPG / progression / harem / YA / explicit evidence
never reach Enrichment Forge. This module reads the same public XML endpoint
directly (same public key abs-tract embeds) and keeps all shelves with vote
counts, paced exactly like Meta Forge's Goodreads calls: 0.5 s global gap,
breaker opens after 2 consecutive failures for 180 s. Metadata Forge's Goodreads
search (search_books) reads the same XML.
"""
import unittest
import urllib.error

from app.goodreads_shelves import (
    GOODREADS_PUBLIC_API_KEY,
    GoodreadsPacer,
    clean_query_title,
    fetch_book_shelves,
    shelves_explicit_evidence,
    shelves_to_genres,
)

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<GoodreadsResponse><book><title>Unsouled (Cradle, #1)</title>
<authors><author><name>Will Wight</name></author></authors>
<popular_shelves>
<shelf name="to-read" count="68699"/><shelf name="fantasy" count="3015"/><shelf name="litrpg" count="282"/>
<shelf name="progression-fantasy" count="210"/><shelf name="young-adult" count="156"/>
<shelf name="cultivation" count="143"/><shelf name="sci-fi" count="75"/>
</popular_shelves></book></GoodreadsResponse>"""


def _no_sleep(_s):
    pass


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class PacerTests(unittest.TestCase):
    def test_enforces_the_global_half_second_gap(self):
        c = FakeClock()
        p = GoodreadsPacer(clock=c.now, sleep=c.sleep)
        self.assertTrue(p.wait_turn())
        self.assertTrue(p.wait_turn())
        self.assertAlmostEqual(c.slept[-1], 0.5)

    def test_two_consecutive_failures_open_the_breaker_for_180s(self):
        c = FakeClock()
        p = GoodreadsPacer(clock=c.now, sleep=c.sleep)
        p.record(False)
        self.assertFalse(p.is_open)
        p.record(False)
        self.assertTrue(p.is_open)
        self.assertFalse(p.wait_turn())
        c.t = 181
        self.assertTrue(p.wait_turn())
        self.assertEqual(p.trips, 1)

    def test_success_resets_the_failure_count(self):
        p = GoodreadsPacer(sleep=_no_sleep)
        p.record(False)
        p.record(True)
        p.record(False)
        self.assertFalse(p.is_open)


class FetchTests(unittest.TestCase):
    def test_uses_the_public_key_and_parses_shelves_with_counts(self):
        seen = {}

        def http_get(url, timeout):
            seen["url"] = url
            return XML

        r = fetch_book_shelves("Cradle - Book 001 - Unsouled", "Will Wight", pacer=GoodreadsPacer(sleep=_no_sleep), http_get=http_get)
        self.assertEqual(r["status"], "found")
        self.assertIn(("litrpg", 282), r["shelves"])
        self.assertIn("key=" + GOODREADS_PUBLIC_API_KEY, seen["url"])
        self.assertIn("title=Unsouled", seen["url"])

    def test_a_different_book_is_not_found_not_failed(self):
        p = GoodreadsPacer(sleep=_no_sleep)
        r = fetch_book_shelves("Some Other Book", "X", pacer=p, http_get=lambda url, timeout: XML)
        self.assertEqual(r["status"], "not_found")
        self.assertEqual(r["shelves"], [])
        self.assertFalse(p.is_open)

    def test_404_is_not_found_and_never_counts_against_the_breaker(self):
        p = GoodreadsPacer(sleep=_no_sleep)

        def http_get(url, timeout):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        for _ in range(3):
            self.assertEqual(fetch_book_shelves("A", "B", pacer=p, http_get=http_get)["status"], "not_found")
        self.assertFalse(p.is_open)

    def test_timeouts_count_then_calls_are_skipped_while_open(self):
        p = GoodreadsPacer(sleep=_no_sleep)

        def http_get(url, timeout):
            raise TimeoutError()

        self.assertEqual(fetch_book_shelves("A", "B", pacer=p, http_get=http_get)["status"], "failed")
        self.assertEqual(fetch_book_shelves("A", "B", pacer=p, http_get=http_get)["status"], "failed")
        self.assertEqual(fetch_book_shelves("A", "B", pacer=p, http_get=http_get)["status"], "skipped")

    def test_garbage_response_is_a_failure(self):
        p = GoodreadsPacer(sleep=_no_sleep)
        self.assertEqual(fetch_book_shelves("A", "B", pacer=p, http_get=lambda url, timeout: b"<html>nope")["status"], "failed")


class MappingTests(unittest.TestCase):
    SHELVES = [("to-read", 68699), ("fantasy", 3015), ("litrpg", 282), ("progression-fantasy", 210),
               ("young-adult", 156), ("cultivation", 143), ("sci-fi", 75)]

    def test_niche_shelves_at_five_percent_of_the_top_genre_shelf(self):
        g = shelves_to_genres(self.SHELVES)
        self.assertIn("Fantasy", g)
        self.assertIn("LitRPG", g)
        self.assertIn("Progression Fantasy", g)  # 210/3015 = 7%
        self.assertNotIn("Cultivation", g)  # 143/3015 = 4.7%, just under the 5% bar
        self.assertIn("Cultivation", shelves_to_genres([("fantasy", 1000), ("cultivation", 60)]))  # 6%

    def test_ya_needs_ten_percent(self):
        self.assertNotIn("Young Adult", shelves_to_genres(self.SHELVES))  # 156/3015 = 5%
        self.assertIn("Young Adult", shelves_to_genres([("fantasy", 262), ("young-adult", 56)]))  # 21%

    def test_broad_genres_need_fifteen_percent(self):
        self.assertNotIn("Science Fiction", shelves_to_genres(self.SHELVES))  # 75/3015 = 2.5%

    def test_niche_needs_at_least_three_votes(self):
        self.assertNotIn("Harem", shelves_to_genres([("fantasy", 20), ("harem", 2)]))
        self.assertIn("Harem", shelves_to_genres([("fantasy", 27), ("harem", 11)]))

    def test_no_bookkeeping_shelves_become_genres(self):
        self.assertNotIn("To Read", shelves_to_genres(self.SHELVES))

    def test_explicit_evidence_counts_votes_and_share(self):
        ev = shelves_explicit_evidence([("fantasy", 27), ("erotica", 4), ("nsfw", 2)])
        self.assertEqual(ev["votes"], 6)
        self.assertAlmostEqual(ev["share"], 6 / 27, places=3)

    def test_adult_fiction_is_an_audience_not_explicit_content(self):
        # Real data: Dune carries adult-fiction x261 (vs sci-fi x24246); 220
        # books in the library have that shelf. It means "not YA".
        ev = shelves_explicit_evidence([("sci-fi", 24246), ("adult", 743), ("adult-fiction", 261)])
        self.assertEqual(ev["votes"], 0)
        self.assertFalse(ev["significant"])

    def test_significant_only_at_five_percent_of_the_top_genre_shelf(self):
        self.assertTrue(shelves_explicit_evidence([("fantasy", 27), ("harem", 11), ("erotica", 4), ("nsfw", 2)])["significant"])
        self.assertFalse(shelves_explicit_evidence([("fantasy", 3000), ("smut", 20)])["significant"])

    def test_no_shelves_means_no_genres_and_no_evidence(self):
        self.assertEqual(shelves_to_genres([]), [])
        self.assertEqual(shelves_explicit_evidence([])["votes"], 0)


class TitleTests(unittest.TestCase):
    def test_clean_query_title(self):
        self.assertEqual(clean_query_title("Cradle - Book 001 - Unsouled"), "Unsouled")
        self.assertEqual(clean_query_title("Iron Gold (Part 1 of 2) (Dramatized Adaptation)"), "Iron Gold")
        self.assertEqual(clean_query_title("Azarinth Healer, Book Six"), "Azarinth Healer")
        self.assertEqual(clean_query_title("Dragon Emperor 9"), "Dragon Emperor")
        self.assertEqual(clean_query_title("Dune"), "Dune")


class GoodreadsMatchTests(unittest.TestCase):
    """Same-book decisions come from Metadata Forge's matcher (sparse rule)."""

    def test_another_authors_book_is_not_found(self):
        xml = XML.replace(b"Will Wight", b"Someone Else")
        r = fetch_book_shelves("Unsouled", "Will Wight", pacer=GoodreadsPacer(sleep=_no_sleep), http_get=lambda url, timeout: xml)
        self.assertEqual(r["status"], "not_found")


class DragonsShelfTests(unittest.TestCase):
    """Measured: real dragon books are shelved "dragons" at 12-120% of their
    top genre shelf (Eragon 12.5%, Heartstrikers 42%); noise at 0-1.3%."""

    def test_dragon_books_get_dragons(self):
        self.assertIn("Dragons", shelves_to_genres([("fantasy", 32088), ("dragons", 3995)]))  # Eragon
        self.assertIn("Dragons", shelves_to_genres([("fantasy", 18), ("dragons", 6)]))        # Dragon Breeder

    def test_a_stray_dragons_shelving_is_not_enough(self):
        self.assertNotIn("Dragons", shelves_to_genres([("fantasy", 470), ("dragons", 6)]))    # The Primal Hunter


def _work(book_id, title, author):
    return (f"<work><best_book><id>{book_id}</id><title>{title}</title>"
            f"<author><name>{author}</name></author></best_book></work>")


def _search(*works):
    return ("<GoodreadsResponse><search><results>" + "".join(works) + "</results></search></GoodreadsResponse>").encode()


def _page(title, author, extra=""):
    return (f"<GoodreadsResponse><book><title>{title}</title><authors><author><name>{author}</name><role></role></author>"
            f"</authors>{extra}</book></GoodreadsResponse>").encode()


class SearchBooksTests(unittest.TestCase):
    """Goodreads search for Metadata Forge, ebooks and manual search, read directly."""

    def run_search(self, responses, title="The Catcher in the Rye", author="J.D. Salinger", **kw):
        from app.goodreads_shelves import search_books
        urls = []

        def get(url, timeout):
            urls.append(url)
            return responses.pop(0)
        return search_books(title, author, pacer=GoodreadsPacer(gap_s=0, sleep=_no_sleep), http_get=get, **kw), urls

    def test_another_authors_results_are_never_fetched(self):
        # With the author in the query Goodreads ranks study guides first.
        found, urls = self.run_search([
            _search(_work(1, "Summary Edition: The Catcher in the Rye", "Jonathan Coupland"),
                    _work(2, "The Catcher in the Rye", "J.D. Salinger")),
            _page("The Catcher in the Rye", "J.D. Salinger"),
        ])
        self.assertIn("q=The+Catcher+in+the+Rye&", urls[0])
        self.assertIn("book/show/2.xml", urls[1])
        self.assertEqual(len(urls), 2)
        self.assertEqual([m["title"] for m in found["matches"]], ["The Catcher in the Rye"])

    def test_title_and_author_together_only_when_the_title_finds_nothing(self):
        found, urls = self.run_search([_search(), _search(_work(2, "The Catcher in the Rye", "J.D. Salinger")),
                                       _page("The Catcher in the Rye", "J.D. Salinger")])
        self.assertIn("q=The+Catcher+in+the+Rye+J.D.+Salinger&", urls[1])
        self.assertEqual(found["status"], "found")

    def test_a_book_page_becomes_a_provider_match(self):
        from app.goodreads_shelves import book_match
        import xml.etree.ElementTree as ET
        page = ET.fromstring(_page(
            "Mistborn: The Final Empire (Mistborn, #1)", "Brandon Sanderson",
            "<isbn13>9780765311788</isbn13><publication_year>2006</publication_year><language_code>eng</language_code>"
            "<image_url>https://i.gr-assets.com/books/1617768316l/68428._SX98_.jpg</image_url>"
            "<popular_shelves><shelf name=\"fantasy\" count=\"44948.0\"/></popular_shelves>")).find("book")
        match = book_match(page)
        self.assertEqual(match["title"], "Mistborn: The Final Empire")
        self.assertEqual(match["series"], [{"series": "Mistborn", "sequence": "1"}])
        self.assertEqual(match["cover"], "https://i.gr-assets.com/books/1617768316l/68428.jpg")
        self.assertEqual((match["isbn"], match["publishedYear"], match["language"]), ("9780765311788", "2006", "english"))
        self.assertEqual(match["genres"], ["Fantasy"])  # "44948.0": Goodreads now sends decimals

    def test_series_works_when_the_title_names_none(self):
        from app.goodreads_shelves import book_match
        import xml.etree.ElementTree as ET
        page = ET.fromstring(_page("Unsouled", "Will Wight", "<series_works><series_work><user_position>1</user_position>"
                                   "<series><title> Cradle </title></series></series_work></series_works>")).find("book")
        self.assertEqual(book_match(page)["series"], [{"series": "Cradle", "sequence": "1"}])

    def test_a_blocked_search_is_failed_not_empty(self):
        from app.goodreads_shelves import search_books

        def get(url, timeout):
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)
        found = search_books("T", "A", pacer=GoodreadsPacer(gap_s=0, sleep=_no_sleep), http_get=get)
        self.assertEqual(found, {"status": "failed", "matches": []})


class ManualGoodreadsSearchTests(unittest.TestCase):
    def test_goodreads_needs_no_abs_tract_and_a_rate_limit_is_a_503(self):
        from unittest.mock import patch
        from fastapi import HTTPException
        from app import main
        match = {"title": "Unsouled", "author": "Will Wight", "series": [{"series": "Cradle", "sequence": "1"}],
                 "cover": "https://c/1.jpg", "isbn": "978", "publishedYear": "2016", "genres": ["Fantasy"]}
        with patch.object(main, "search_goodreads_books", return_value={"status": "found", "matches": [match]}):
            rows = main.search_abs_tract_candidates(query="Unsouled", author="Will Wight", base_url="", provider="goodreads")["results"]
        self.assertEqual((rows[0]["title"], rows[0]["asin"], rows[0]["series"]), ("Unsouled", "", "Cradle"))
        with patch.object(main, "search_goodreads_books", return_value={"status": "skipped", "matches": []}), \
             self.assertRaises(HTTPException) as ctx:
            main.search_abs_tract_candidates(query="Unsouled", base_url="", provider="goodreads")
        self.assertEqual(ctx.exception.status_code, 503)
