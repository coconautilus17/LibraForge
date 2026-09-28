"""Direct Goodreads shelves client used by Enrichment Forge.

abs-tract filters Goodreads shelves through a ~48-entry allow-list and keeps
only the first 3, so LitRPG / progression / harem / YA / explicit evidence
never reach Enrichment Forge. This module reads the same public XML endpoint
directly (same public key abs-tract embeds) and keeps all shelves with vote
counts, paced exactly like Meta Forge's Goodreads calls: 0.5 s global gap,
breaker opens after 2 consecutive failures for 180 s.
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
