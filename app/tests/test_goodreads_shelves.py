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


class CleanQueryTitleEdgeTests(unittest.TestCase):
    def test_a_long_title_with_a_colon_subtitle_keeps_only_the_main_title(self):
        long = "An Exceptionally Long Main Title That Goes On Forever: And Then A Subtitle"
        self.assertGreater(len(long), 60)
        self.assertEqual(clean_query_title(long), "An Exceptionally Long Main Title That Goes On Forever")

    def test_a_short_title_keeps_its_subtitle(self):
        self.assertEqual(clean_query_title("Dune: Messiah"), "Dune: Messiah")

    def test_a_long_title_without_a_colon_is_left_whole(self):
        long = "An Exceptionally Long Main Title That Goes On Forever And Then Some More Words"
        self.assertEqual(clean_query_title(long), long)

    def test_a_title_that_cleans_to_nothing_falls_back_to_the_original(self):
        self.assertEqual(clean_query_title("(Untitled)"), "(Untitled)")
        self.assertEqual(clean_query_title(""), "")
        self.assertEqual(clean_query_title(None), "")


class PacerEdgeTests(unittest.TestCase):
    def test_a_wait_only_covers_the_remaining_part_of_the_gap(self):
        c = FakeClock()
        p = GoodreadsPacer(clock=c.now, sleep=c.sleep)
        p.wait_turn()
        c.t += 0.2
        p.wait_turn()
        self.assertAlmostEqual(c.slept[-1], 0.3)

    def test_no_wait_when_the_gap_has_already_passed(self):
        c = FakeClock()
        p = GoodreadsPacer(clock=c.now, sleep=c.sleep)
        p.wait_turn()
        c.t += 5
        p.wait_turn()
        self.assertEqual(c.slept, [])

    def test_a_success_between_failures_resets_the_streak(self):
        c = FakeClock()
        p = GoodreadsPacer(clock=c.now, sleep=c.sleep)
        p.record(False)
        p.record(True)
        p.record(False)
        self.assertFalse(p.is_open)
        self.assertEqual(p.trips, 0)

    def test_after_tripping_the_failure_streak_starts_again_from_zero(self):
        c = FakeClock()
        p = GoodreadsPacer(clock=c.now, sleep=c.sleep)
        p.record(False)
        p.record(False)
        self.assertTrue(p.is_open)
        c.t += 181
        self.assertFalse(p.is_open)
        p.record(False)
        self.assertFalse(p.is_open)
        p.record(False)
        self.assertTrue(p.is_open)
        self.assertEqual(p.trips, 2)

    def test_the_breaker_reopens_for_exactly_the_cooldown(self):
        c = FakeClock()
        p = GoodreadsPacer(clock=c.now, sleep=c.sleep)
        p.record(False)
        p.record(False)
        c.t += 179
        self.assertTrue(p.is_open)
        c.t += 2
        self.assertFalse(p.is_open)


class FetchEdgeTests(unittest.TestCase):
    def _fetch(self, http_get, title="Unsouled", author="Will Wight", pacer=None):
        c = FakeClock()
        pacer = pacer or GoodreadsPacer(clock=c.now, sleep=c.sleep)
        return fetch_book_shelves(title, author, pacer=pacer, http_get=http_get), pacer

    def test_the_request_carries_the_cleaned_title_author_and_public_key(self):
        seen = {}
        def get(url, timeout):
            seen["url"] = url
            return XML
        self._fetch(get, title="Cradle - Book 001 - Unsouled", author="Will Wight")
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(seen["url"]).query)
        self.assertEqual((q["title"], q["author"], q["key"]), (["Unsouled"], ["Will Wight"], [GOODREADS_PUBLIC_API_KEY]))

    def test_a_missing_author_is_sent_blank(self):
        seen = {}
        def get(url, timeout):
            seen["url"] = url
            return XML
        self._fetch(get, author=None)
        self.assertIn("author=&", seen["url"])

    def test_a_successful_lookup_resets_the_breaker_and_a_failure_counts_against_it(self):
        p = GoodreadsPacer()
        def boom(url, timeout):
            raise TimeoutError()
        self._fetch(boom, pacer=p)
        self.assertEqual(p._fails, 1)
        self._fetch(lambda u, t: XML, pacer=p)
        self.assertEqual(p._fails, 0)
        self.assertEqual(p.trips, 0)
        self.assertFalse(p.is_open)

    def test_a_404_is_not_a_failure(self):
        p = GoodreadsPacer()
        def missing(url, timeout):
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        p.record(False)
        result, _ = self._fetch(missing, pacer=p)
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(p._fails, 0)

    def test_a_server_error_is_a_failure(self):
        p = GoodreadsPacer()
        def err(url, timeout):
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)
        result, _ = self._fetch(err, pacer=p)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(p._fails, 1)

    def test_garbage_xml_is_a_failure(self):
        p = GoodreadsPacer()
        result, _ = self._fetch(lambda u, t: b"<not xml", pacer=p)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(p._fails, 1)

    def test_a_response_without_a_book_is_not_found_but_still_counts_as_success(self):
        p = GoodreadsPacer()
        p.record(False)
        result, _ = self._fetch(lambda u, t: b"<GoodreadsResponse/>", pacer=p)
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(p._fails, 0)
        self.assertEqual(p.trips, 0)

    def test_a_different_book_is_not_found_and_reports_the_title_it_got(self):
        other = XML.replace(b"Unsouled (Cradle, #1)", b"Completely Different Tome").replace(b"Will Wight", b"Someone Else")
        result, _ = self._fetch(lambda u, t: other)
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["title"], "Completely Different Tome")
        self.assertEqual(result["shelves"], [])

    def test_shelf_counts_are_ints_and_a_bad_or_missing_count_is_zero(self):
        xml = (b'<GoodreadsResponse><book><title>Unsouled</title><authors><author><name>Will Wight</name></author></authors>'
               b'<popular_shelves><shelf name="Fantasy" count="12"/><shelf name="odd" count="x"/><shelf name="none"/>'
               b'<shelf name="" count="5"/></popular_shelves></book></GoodreadsResponse>')
        result, _ = self._fetch(lambda u, t: xml)
        self.assertEqual(result["shelves"], [("fantasy", 12), ("odd", 0), ("none", 0)])

    def test_an_open_breaker_skips_the_request_entirely(self):
        c = FakeClock()
        p = GoodreadsPacer(clock=c.now, sleep=c.sleep)
        p.record(False)
        p.record(False)
        called = []
        result, _ = self._fetch(lambda u, t: called.append(1) or XML, pacer=p)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(called, [])


class BreakerGateTests(unittest.TestCase):
    def test_wait_turn_reports_true_when_closed_and_exactly_false_when_open(self):
        c = FakeClock()
        p = GoodreadsPacer(clock=c.now, sleep=c.sleep)
        self.assertIs(p.wait_turn(), True)
        p.record(False)
        p.record(False)
        self.assertIs(p.wait_turn(), False)


class LongTitleBoundaryTests(unittest.TestCase):
    def test_the_subtitle_is_cut_only_above_sixty_characters(self):
        self.assertEqual(len("B" * 58 + ": x"), 61)
        self.assertEqual(clean_query_title("B" * 58 + ": x"), "B" * 58)  # 61 chars: cut
        self.assertEqual(len("B" * 57 + ": x"), 60)
        self.assertEqual(clean_query_title("B" * 57 + ": x"), "B" * 57 + ": x")  # exactly 60: kept


class ShelfThresholdTests(unittest.TestCase):
    def test_niche_shelves_need_three_votes_and_five_percent_of_the_top_broad_shelf(self):
        self.assertEqual(shelves_to_genres([("fantasy", 100), ("litrpg", 5)]), ["Fantasy", "LitRPG"])
        self.assertEqual(shelves_to_genres([("fantasy", 100), ("litrpg", 4)]), ["Fantasy"])
        self.assertEqual(shelves_to_genres([("fantasy", 100), ("litrpg", 2)]), ["Fantasy"])

    def test_audience_shelves_need_ten_percent(self):
        self.assertEqual(shelves_to_genres([("fantasy", 100), ("young-adult", 10)]), ["Fantasy", "Young Adult"])
        self.assertEqual(shelves_to_genres([("fantasy", 100), ("young-adult", 9)]), ["Fantasy"])

    def test_broad_shelves_need_fifteen_percent_of_the_top_one(self):
        self.assertEqual(shelves_to_genres([("fantasy", 100), ("romance", 15)]), ["Fantasy", "Romance"])
        self.assertEqual(shelves_to_genres([("fantasy", 100), ("romance", 14)]), ["Fantasy"])

    def test_a_genre_reached_by_two_shelves_is_listed_once_in_shelf_order(self):
        self.assertEqual(shelves_to_genres([("litrpg", 50), ("lit-rpg", 50), ("fantasy", 100)]), ["LitRPG", "Fantasy"])

    def test_no_broad_shelf_uses_a_floor_of_one_vote_for_the_share(self):
        self.assertEqual(shelves_to_genres([("litrpg", 3)]), ["LitRPG"])
        self.assertEqual(shelves_to_genres([]), [])

    def test_explicit_evidence_sums_votes_and_reports_a_rounded_share(self):
        ev = shelves_explicit_evidence([("fantasy", 300), ("erotica", 10), ("smut", 5)])
        self.assertEqual((ev["votes"], ev["share"], ev["significant"]), (15, 0.05, True))

    def test_explicit_evidence_needs_both_enough_votes_and_enough_share(self):
        few = shelves_explicit_evidence([("fantasy", 10), ("erotica", 2)])
        self.assertEqual(few["significant"], False)
        thin = shelves_explicit_evidence([("fantasy", 1000), ("erotica", 3)])
        self.assertEqual((thin["votes"], thin["significant"]), (3, False))

    def test_explicit_evidence_without_shelves_is_zero_and_not_significant(self):
        self.assertEqual(shelves_explicit_evidence([]), {"votes": 0, "share": 0.0, "significant": False})

    def test_the_share_is_rounded_to_three_decimals(self):
        ev = shelves_explicit_evidence([("fantasy", 3000), ("erotica", 10)])
        self.assertEqual(ev["share"], 0.003)
