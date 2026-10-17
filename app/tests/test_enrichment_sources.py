"""Enrichment Forge v2 source adapters. Every test injects http_get, so
nothing here touches the network."""
import unittest
import urllib.error

from app import enrichment_sources as s
from app.goodreads_shelves import GoodreadsPacer


def P(**kw):
    return GoodreadsPacer(sleep=lambda _x: None, **kw)


BOOK = {"id": "b1", "title": "Cradle - Book 001 - Unsouled", "author": "Will Wight", "asin": "B06XKXD6QR", "has_audio": True}


class AudioSiloTests(unittest.TestCase):
    def test_asin_resolves_through_the_lookup_endpoint(self):
        # /abs/search treats query= as title text; the real ASIN lookup is
        # /api/v1/lookup, then the work record carries the genres (slugs).
        seen = []

        def get(url, timeout):
            seen.append(url)
            if "/api/v1/lookup" in url:
                return {"work": {"id": "unsouled", "title": "Unsouled"}}
            return {"id": "unsouled", "title": "Unsouled", "genres": ["epic-fantasy", "progression-fantasy", "science-fiction"]}

        r = s.audiosilo_lookup(BOOK, pacer=P(), http_get=get)
        self.assertEqual(r["status"], "found")
        self.assertEqual(sorted(r["labels"]), ["epic fantasy", "progression fantasy", "science fiction"])
        self.assertIn("/api/v1/lookup?asin=B06XKXD6QR", seen[0])
        self.assertIn("/api/v1/works/unsouled", seen[1])

    def test_title_query_when_asin_is_not_real(self):
        seen = []

        def get(url, timeout):
            seen.append(url)
            return {"matches": []}

        r = s.audiosilo_lookup({**BOOK, "asin": "NOREALASIN"}, pacer=P(), http_get=get)
        self.assertEqual(r["status"], "not_found")
        self.assertIn("query=Unsouled", seen[0])
        self.assertIn("author=Wight", seen[0])

    def test_asin_miss_falls_back_to_title(self):
        seen = []

        def get(url, timeout):
            seen.append(url)
            if "/api/v1/lookup" in url:
                raise urllib.error.HTTPError(url, 404, "nf", {}, None)
            return {"matches": [{"title": "Unsouled", "author": "Will Wight", "genres": ["Fantasy"],
                                 "series": [{"series": "Cradle", "sequence": "1"}]}]}

        book = {**BOOK, "series_name": "Cradle", "sequence": "1"}
        self.assertEqual(s.audiosilo_lookup(book, pacer=P(), http_get=get)["status"], "found")
        self.assertEqual(len(seen), 2)

    def test_title_search_looks_past_other_authors_books(self):
        # 12 Miles Below: "The Warlock" by Mark Arrows sits below Dante King's.
        get = lambda url, timeout: {"matches": [
            {"title": "The Warlock 2", "author": "Dante King", "genres": ["Harem"]},
            {"title": "12 Miles Below V: The Warlock", "author": "Mark Arrows", "genres": ["Fantasy"],
             "series": [{"series": "12 Miles Below", "sequence": "5"}]}]}
        book = {**BOOK, "title": "12 Miles Below - Book 005 - The Warlock", "author": "Mark Arrows", "asin": "",
                "series_name": "12 Miles Below", "sequence": "5"}
        r = s.audiosilo_lookup(book, pacer=P(), http_get=get)
        self.assertEqual((r["status"], r["title"]), ("found", "12 Miles Below V: The Warlock"))

    def test_series_and_title_is_the_last_attempt(self):
        seen = []

        def get(url, timeout):
            seen.append(url)
            if "Miles" in url:
                return {"matches": [{"title": "12 Miles Below: The Frozen Realm", "author": "Mark Arrows", "genres": ["Fantasy"],
                                     "series": [{"series": "12 Miles Below", "sequence": "1"}]}]}
            return {"matches": []}

        book = {**BOOK, "title": "The Frozen Realm", "author": "Mark Arrows", "asin": "", "series_name": "12 Miles Below",
                "sequence": "1"}
        r = s.audiosilo_lookup(book, pacer=P(), http_get=get)
        self.assertEqual(r["status"], "found")
        self.assertIn("query=12+Miles+Below+The+Frozen+Realm", seen[-1])

    def test_fuzzy_wrong_book_is_not_found(self):
        get = lambda url, timeout: {"matches": [{"title": "Blue Moon Australia", "genres": ["Mystery"]}]}
        r = s.audiosilo_lookup({**BOOK, "title": "Australia: A History", "asin": ""}, pacer=P(), http_get=get)
        self.assertEqual((r["status"], r["labels"]), ("not_found", []))

    def test_timeouts_trip_breaker_then_skip(self):
        def get(url, timeout):
            raise TimeoutError()

        p = P(fail_threshold=3)
        statuses = [s.audiosilo_lookup({**BOOK, "asin": ""}, pacer=p, http_get=get)["status"] for _ in range(4)]
        self.assertEqual(statuses, ["failed", "failed", "failed", "skipped"])


class OpenLibraryTests(unittest.TestCase):
    def test_subjects_filtered_to_known_labels(self):
        get = lambda url, timeout: {"docs": [{"title": "Unsouled", "subject": ["LitRPG", "Fiction", "Juvenile fiction", "Wizards"]}]}
        r = s.openlibrary_lookup(BOOK, pacer=P(), http_get=get)
        self.assertEqual(r["status"], "found")
        self.assertEqual(sorted(r["labels"]), ["litrpg", "young adult"])

    def test_wrong_book_is_not_found(self):
        get = lambda url, timeout: {"docs": [{"title": "Something Else Entirely", "subject": ["Horror"]}]}
        self.assertEqual(s.openlibrary_lookup(BOOK, pacer=P(), http_get=get)["status"], "not_found")

    def test_404_is_not_found(self):
        def get(url, timeout):
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)

        p = P()
        self.assertEqual(s.openlibrary_lookup(BOOK, pacer=p, http_get=get)["status"], "not_found")
        self.assertFalse(p.is_open)


class RunnerTests(unittest.TestCase):
    def test_skips_no_audio_and_honors_limit(self):
        books = [dict(BOOK, id=f"b{i}") for i in range(5)] + [dict(BOOK, id="x", has_audio=False)]
        calls = []

        def lookup(book, pacer):
            calls.append(book["id"])
            return {"status": "found", "title": "", "labels": []}

        res = s.search_series_sources(books, lookup, P(), limit=3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(res["x"]["status"], "skipped")
        st = s.summarize_status("AudioSilo", res, books)
        self.assertEqual((st["searched"], st["found"], st["state"]), (3, 3, "searched"))

    def test_lookup_exception_is_a_failure_not_a_crash(self):
        def lookup(book, pacer):
            raise RuntimeError("boom")

        res = s.search_series_sources([BOOK], lookup, P())
        self.assertEqual(res["b1"]["status"], "failed")

    def test_status_reports_rate_limited_when_skipped(self):
        res = {"b1": {"status": "failed"}, "b2": {"status": "skipped"}}
        books = [dict(BOOK, id="b1"), dict(BOOK, id="b2")]
        st = s.summarize_status("AudioSilo", res, books)
        self.assertTrue(st["rate_limited"])
        self.assertEqual(st["failed"], 1)


class ProgressionFantasyIndexTests(unittest.TestCase):
    def pages(self):
        data = {1: [{"title": {"rendered": "Will Wight &#8211; Cradle"}, "categories": [6]},
                    {"title": {"rendered": "Travis Deverell &#8211; He Who Fights With Monsters"}, "categories": [8]},
                    {"title": {"rendered": "Adastra339 &#8211; Speed Running The Multiverse"}, "categories": [8]},
                    {"title": {"rendered": "Richard Sparks"}, "categories": [8]}],
                2: []}
        calls = []

        def get(url, timeout):
            calls.append(url)
            return data[int(url.split("&page=")[1].split("&")[0])]

        return get, calls

    def test_categories_author_check_and_single_download(self):
        get, calls = self.pages()
        idx = s.ProgressionFantasyIndex(http_get=get)
        self.assertEqual(idx.lookup("Cradle", ["Will Wight"])["category"], "Progression")
        self.assertEqual(idx.lookup("He Who Fights with Monsters", ["Travis Deverell"])["category"], "LitRPG")
        self.assertEqual(idx.lookup("Speedrunning the Multiverse Series", ["Adastra339"])["category"], "LitRPG")
        self.assertEqual(idx.lookup("Cradle", ["Someone Else"])["status"], "not_found")
        self.assertEqual(idx.lookup("Dune", ["Frank Herbert"])["status"], "not_found")
        self.assertEqual(len(calls), 2)

    def test_distinctive_exact_name_matches_despite_a_pen_name(self):
        # Real data: listed as "Shirtaloon – He Who Fights With Monsters"; the
        # library credits the author's real name, Travis Deverell.
        get, _calls = self.pages()
        idx = s.ProgressionFantasyIndex(http_get=get)
        self.assertEqual(idx.lookup("Speed Running the Multiverse", ["Someone Else"])["category"], "LitRPG")
        self.assertEqual(idx.lookup("Cradle", ["Someone Else"])["status"], "not_found")

    def test_download_failure_is_failed_not_crash_and_retried_later(self):
        clock = [0.0]

        def get(url, timeout):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

        idx = s.ProgressionFantasyIndex(http_get=get, clock=lambda: clock[0])
        self.assertEqual(idx.lookup("Cradle", ["Will Wight"])["status"], "failed")
        self.assertEqual(idx.lookup("Cradle", ["Will Wight"])["status"], "failed")


class HaremLitTests(unittest.TestCase):
    WIKI = "{{Book_Series_Template|author=[[Eric Vall]]|explicit_sex=Yes|genre(s)=[[HaremLit]], [[Portal Fantasy]]}}"

    def test_series_page_with_author_check(self):
        def get(url, timeout):
            if "list=search" in url:
                return {"query": {"search": [{"title": "Dragon Emperor (Series)"}]}}
            return {"parse": {"wikitext": {"*": self.WIKI}}}

        r = s.haremlit_lookup("Dragon Emperor", ["Eric Vall"], http_get=get, pacer=P())
        self.assertEqual((r["status"], r["via"], r["explicit"]), ("found", "series", "Yes"))
        self.assertIn("portal fantasy", r["genres"])
        other = s.haremlit_lookup("Dragon Emperor", ["Someone Else"], http_get=lambda u, t: (
            {"query": {"search": [{"title": "Dragon Emperor (Series)"}]}} if "list=search" in u
            else {"parse": {"wikitext": {"*": self.WIKI}}} if "Dragon" in u else {"error": {"code": "missingtitle"}}), pacer=P())
        self.assertEqual(other["status"], "not_found")

    def test_author_page_listing(self):
        def get(url, timeout):
            if "list=search" in url:
                return {"query": {"search": []}}
            return {"parse": {"wikitext": {"*": "* [[Building Harem Town]]\n* [[Chaos God (Series)|Chaos God]]"}}}

        r = s.haremlit_lookup("Chaos God", ["Eric Vall"], http_get=get, pacer=P())
        self.assertEqual((r["status"], r["via"]), ("found", "author"))

    def test_network_failure_is_failed(self):
        def get(url, timeout):
            raise TimeoutError()

        self.assertEqual(s.haremlit_lookup("X", ["Y"], http_get=get, pacer=P())["status"], "failed")

    def test_series_level_labels(self):
        labels, ev, pfp = s.series_level_labels({"status": "found", "category": "Progression", "title": "A – B"},
                                                {"status": "found", "match": "X", "genres": ["urban fantasy"]})
        self.assertEqual((sorted(labels), pfp), (["haremlit", "urban fantasy"], True))
        self.assertEqual(len(ev), 2)
        labels, ev, pfp = s.series_level_labels({"status": "found", "category": "LitRPG", "title": "A – B"}, {"status": "not_found"})
        self.assertEqual((labels, pfp), (["litrpg"], False))


class FinalReviewFixTests(unittest.TestCase):
    def test_pf_index_stops_at_the_page_cap_and_reports_failed(self):
        calls = []

        def get(url, timeout):
            calls.append(url)
            return [{"title": {"rendered": "A – B"}, "categories": [8]}]  # a site that ignores page=

        idx = s.ProgressionFantasyIndex(http_get=get)
        self.assertEqual(idx.lookup("B", ["A"])["status"], "failed")
        self.assertLessEqual(len(calls), s.PF_MAX_PAGES)

    def test_pf_empty_first_page_is_failed_not_an_empty_catalogue(self):
        idx = s.ProgressionFantasyIndex(http_get=lambda url, timeout: [])
        self.assertEqual(idx.lookup("Cradle", ["Will Wight"])["status"], "failed")

    def test_audiosilo_title_match_by_another_author_is_not_found(self):
        get = lambda url, timeout: {"matches": [{"title": "Blackflame Rising: A Romance", "author": "Jane Doe", "genres": ["Romance"]}]}
        r = s.audiosilo_lookup({**BOOK, "title": "Blackflame", "asin": ""}, pacer=P(), http_get=get)
        self.assertEqual((r["status"], r["labels"]), ("not_found", []))

    def test_openlibrary_other_author_is_not_found(self):
        get = lambda url, timeout: {"docs": [{"title": "Unsouled", "author_name": ["Someone Else"], "subject": ["Horror"]}]}
        self.assertEqual(s.openlibrary_lookup(BOOK, pacer=P(), http_get=get)["status"], "not_found")

    def test_haremlit_author_page_needs_an_exact_series_link(self):
        def get(url, timeout):
            if "list=search" in url:
                return {"query": {"search": []}}
            return {"parse": {"wikitext": {"*": "* [[Summoner (Series)|Summoner]]\n[[Category:Fantasy Series]]"}}}

        self.assertEqual(s.haremlit_lookup("Summoner School", ["Eric Vall"], http_get=get, pacer=P())["status"], "not_found")
        self.assertEqual(s.haremlit_lookup("Fantasy", ["Eric Vall"], http_get=get, pacer=P())["status"], "not_found")
        self.assertEqual(s.haremlit_lookup("Summoner", ["Eric Vall"], http_get=get, pacer=P())["status"], "found")


class BatchReadinessTests(unittest.TestCase):
    """Before batch mode: HaremLit is paced and bounded, author matching is by word."""

    def test_haremlit_skips_while_its_breaker_is_open(self):
        calls = []
        pacer = P(fail_threshold=1)
        pacer.record(False)  # open
        r = s.haremlit_lookup("X", ["Y"], http_get=lambda u, t: calls.append(u) or {}, pacer=pacer)
        self.assertEqual((r["status"], calls), ("skipped", []))

    def test_haremlit_checks_at_most_three_author_pages(self):
        pages = []

        def get(url, timeout):
            if "list=search" in url:
                return {"query": {"search": []}}
            pages.append(url)
            return {"parse": {"wikitext": {"*": ""}}}

        s.haremlit_lookup("Anthology", [f"Author {i}" for i in range(8)], http_get=get, pacer=P())
        self.assertEqual(len(pages), 3)

    def test_author_surname_matches_whole_words_only(self):
        self.assertFalse(s._author_matches("William Wight", ["Jet Li"]))
        self.assertTrue(s._author_matches("Will Wight", ["Wight"]))


class HaremLitAuthorExplicitTests(unittest.TestCase):
    def test_author_page_match_reads_the_linked_pages_explicit_value(self):
        def get(url, timeout):
            if "list=search" in url:
                return {"query": {"search": []}}
            if "Chaos+God" in url or "Chaos%20God" in url:
                return {"parse": {"wikitext": {"*": "{{Book_Series_Template|author=[[Eric Vall]]|explicit_sex=Yes}}"}}}
            return {"parse": {"wikitext": {"*": "* [[Chaos God]]"}}}

        r = s.haremlit_lookup("Chaos God", ["Eric Vall"], http_get=get, pacer=P())
        self.assertEqual((r["status"], r["via"], r["explicit"]), ("found", "author", "Yes"))


class AudioSiloAsinShapeTests(unittest.TestCase):
    def looked_up(self, asin):
        seen = []

        def get(url, timeout):
            seen.append(url)
            if "/api/v1/lookup" in url:
                return {"work": {"id": "w", "title": "Dune: House Atreides"}}
            if "/api/v1/works/" in url:
                return {"title": "Dune: House Atreides", "genres": ["science-fiction"]}
            return {"matches": []}

        s.audiosilo_lookup({**BOOK, "asin": asin}, pacer=P(), http_get=get)
        return any("/api/v1/lookup" in u for u in seen)

    def test_older_numeric_asins_are_looked_up_too(self):
        self.assertTrue(self.looked_up("1004027907"))   # Dune: House Atreides
        self.assertTrue(self.looked_up("B06XKXD6QR"))

    def test_placeholders_are_never_looked_up(self):
        self.assertFalse(self.looked_up("NOREALASIN"))
        self.assertFalse(self.looked_up("abs-agg-graphicaudio-0"))


class SeriesNameMatchTests(unittest.TestCase):
    def test_equal_after_normalising_matches(self):
        self.assertTrue(s._series_names_match("Cradle (Series)", "cradle series"))
        self.assertTrue(s._series_names_match("Dungeon Crawler Carl 3", "Dungeon Crawler Carl"))

    def test_a_prefix_match_needs_at_least_five_characters_on_the_shorter_side(self):
        self.assertTrue(s._series_names_match("Cradles of Fire", "Cradle"))      # 'cradle' = 6
        self.assertTrue(s._series_names_match("Mage Wars Online", "Magew"))      # exactly 5
        self.assertFalse(s._series_names_match("Mageborn", "Mage"))             # only 4
    def test_unrelated_names_and_blanks_do_not_match(self):
        self.assertFalse(s._series_names_match("Dune", "Foundation"))
        self.assertFalse(s._series_names_match("", "Dune"))
        self.assertFalse(s._series_names_match("Dune", ""))
        self.assertFalse(s._series_names_match(None, None))


class AudioSiloSeriesQueryTests(unittest.TestCase):
    def _queries(self, book):
        seen = []
        def get(url, timeout):
            seen.append(url)
            return {"matches": []}
        s.audiosilo_lookup({**book, "asin": ""}, pacer=P(), http_get=get)
        return seen

    def test_a_series_prefixed_query_is_added_when_the_title_lacks_the_series(self):
        seen = self._queries({"id": "1", "title": "The Warlock", "author": "Mark Arrows", "series_name": "12 Miles Below"})
        self.assertEqual(len(seen), 2)
        self.assertIn("query=12+Miles+Below+The+Warlock", seen[1])

    def test_no_second_query_when_the_series_is_already_in_the_title(self):
        seen = self._queries({"id": "1", "title": "12 Miles Below: The Warlock", "author": "Mark Arrows",
                              "series_name": "12 miles below"})
        self.assertEqual(len(seen), 1)

    def test_no_second_query_without_a_series(self):
        self.assertEqual(len(self._queries({"id": "1", "title": "The Warlock", "author": "Mark Arrows", "series_name": ""})), 1)

    def test_the_first_non_empty_match_title_is_reported_on_a_miss(self):
        def get(url, timeout):
            return {"matches": [{"title": "Some Other Book", "author": "Zed"}]}
        r = s.audiosilo_lookup({"id": "1", "title": "The Warlock", "author": "Mark Arrows", "asin": ""}, pacer=P(), http_get=get)
        self.assertEqual((r["status"], r["title"]), ("not_found", "Some Other Book"))


class PacedGetTests(unittest.TestCase):
    def test_outcomes_and_their_effect_on_the_breaker(self):
        def raising(code):
            def get(url, timeout):
                raise urllib.error.HTTPError(url, code, "x", {}, None)
            return get
        for code, status, fails in ((404, "not_found", 0), (500, "failed", 1), (403, "failed", 1)):
            p = P()
            self.assertEqual(s._paced_get("u", p, raising(code))[0], status)
            self.assertEqual(p._fails, fails, code)

    def test_success_returns_the_data_and_resets_the_streak(self):
        p = P()
        p.record(False)
        self.assertEqual(s._paced_get("u", p, lambda url, timeout: {"a": 1}), ("ok", {"a": 1}))
        self.assertEqual(p._fails, 0)

    def test_the_timeout_is_passed_through_and_defaults_to_twenty_seconds(self):
        seen = []
        s._paced_get("u", P(), lambda url, timeout: seen.append(timeout))
        s._paced_get("u", P(), lambda url, timeout: seen.append(timeout), timeout=5)
        self.assertEqual(seen, [20, 5])

    def test_a_generic_error_is_a_failure_that_counts(self):
        p = P()
        def boom(url, timeout):
            raise OSError("down")
        self.assertEqual(s._paced_get("u", p, boom), ("failed", None))
        self.assertEqual(p._fails, 1)


class RunnerAndStatusTests(unittest.TestCase):
    def test_no_audio_books_are_reported_skipped_without_a_lookup(self):
        called = []
        books = [{"id": "a", "has_audio": False}, {"id": "b"}, {"id": "c", "has_audio": True}]
        out = s.search_series_sources(books, lambda book, pacer: called.append(book["id"]) or s._result("found"), P())
        self.assertEqual(sorted(called), ["b", "c"])
        self.assertEqual(out["a"]["status"], "skipped")

    def test_the_limit_applies_to_audio_books_only_and_zero_means_unlimited(self):
        books = [{"id": "x", "has_audio": False}, {"id": "a"}, {"id": "b"}, {"id": "c"}]
        called = []
        look = lambda book, pacer: called.append(book["id"]) or s._result("found")
        out = s.search_series_sources(books, look, P(), limit=2)
        self.assertEqual(sorted(called), ["a", "b"])
        self.assertEqual(sorted(out), ["a", "b", "x"])     # 'c' was beyond the limit: no entry, not "skipped"
        called.clear()
        s.search_series_sources(books, look, P(), limit=0)
        self.assertEqual(sorted(called), ["a", "b", "c"])

    def test_status_counts_exclude_skipped_from_searched_and_ignore_no_audio_books(self):
        books = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d", "has_audio": False}, {"id": "e"}]
        results = {"a": {"status": "found"}, "b": {"status": "failed"}, "c": {"status": "skipped"},
                   "d": {"status": "found"}}
        out = s.summarize_status("AudioSilo", results, books)
        self.assertEqual((out["searched"], out["found"], out["failed"], out["skipped"]), (2, 1, 1, 1))
        self.assertIs(out["rate_limited"], True)
        self.assertIn("AudioSilo is failing or rate-limiting", out["detail"])
        self.assertEqual(out["state"], "searched")

    def test_status_with_nothing_skipped_is_quiet(self):
        out = s.summarize_status("X", {"a": {"status": "found"}}, [{"id": "a"}])
        self.assertEqual((out["rate_limited"], out["detail"], out["searched"]), (False, "", 1))


class ProgressionIndexCacheTests(unittest.TestCase):
    POSTS = [{"title": {"rendered": "Will Wight &#8211; Cradle"}, "categories": [6]}]

    def _index(self, get, clock):
        return s.ProgressionFantasyIndex(http_get=get, clock=lambda: clock[0], ttl_s=100, failure_retry_s=50)

    def test_the_catalogue_is_reused_until_the_ttl_expires(self):
        clock, calls = [0.0], []
        def get(url, timeout):
            calls.append(url)
            return self.POSTS if "page=1&" in url else []
        idx = self._index(get, clock)
        idx.lookup("Cradle", ["Will Wight"])
        clock[0] = 99
        idx.lookup("Cradle", ["Will Wight"])
        self.assertEqual(len(calls), 2)          # page 1 + the empty page 2, once
        clock[0] = 101
        idx.lookup("Cradle", ["Will Wight"])
        self.assertEqual(len(calls), 4)          # reloaded after the ttl

    def test_a_failed_download_is_not_retried_inside_the_retry_window(self):
        clock, calls = [1000.0], []
        def get(url, timeout):
            calls.append(url)
            raise OSError("down")
        idx = self._index(get, clock)
        idx.lookup("Cradle", ["Will Wight"])
        clock[0] = 1049
        idx.lookup("Cradle", ["Will Wight"])
        self.assertEqual(len(calls), 1)
        clock[0] = 1051
        idx.lookup("Cradle", ["Will Wight"])
        self.assertEqual(len(calls), 2)

    def test_a_stale_catalogue_keeps_answering_while_a_refresh_is_failing(self):
        clock, fail = [0.0], [False]
        def get(url, timeout):
            if fail[0]:
                raise OSError("down")
            return self.POSTS if "page=1&" in url else []
        idx = self._index(get, clock)
        self.assertEqual(idx.lookup("Cradle", ["Will Wight"])["status"], "found")
        clock[0], fail[0] = 200, True
        self.assertEqual(idx.lookup("Cradle", ["Will Wight"])["status"], "found")

    def test_wordpress_answering_400_past_the_last_page_keeps_what_was_loaded(self):
        def get(url, timeout):
            if "page=1&" in url:
                return self.POSTS
            raise urllib.error.HTTPError(url, 400, "bad page", {}, None)
        idx = s.ProgressionFantasyIndex(http_get=get)
        self.assertEqual(idx.lookup("Cradle", ["Will Wight"])["status"], "found")

    def test_a_400_on_the_first_page_is_a_failure(self):
        def get(url, timeout):
            raise urllib.error.HTTPError(url, 400, "bad", {}, None)
        self.assertEqual(s.ProgressionFantasyIndex(http_get=get).lookup("Cradle", ["Will Wight"])["status"], "failed")

    def test_posts_need_the_dash_separator_and_a_known_category(self):
        posts = [{"title": {"rendered": "No Separator Here"}, "categories": [6]},
                 {"title": {"rendered": "A &#8211; Uncategorised Series"}, "categories": [99]},
                 {"title": {"rendered": "B &#8211; Good Series Name"}, "categories": [99, 8]}]
        get = lambda url, timeout: posts if "page=1&" in url else []
        idx = s.ProgressionFantasyIndex(http_get=get)
        self.assertEqual(idx.lookup("Good Series Name", ["B"])["category"], "LitRPG")
        self.assertEqual(idx.lookup("Uncategorised Series", ["A"])["status"], "not_found")
        self.assertEqual(idx.lookup("No Separator Here", ["X"])["status"], "not_found")

    def test_the_exact_name_shortcut_needs_twelve_characters(self):
        posts = [{"title": {"rendered": "Pen Name &#8211; Elevenchars"}, "categories": [6]},      # 11
                 {"title": {"rendered": "Pen Name &#8211; Twelve chars"}, "categories": [6]}]     # 11 letters+space -> 11? use below
        get = lambda url, timeout: posts if "page=1&" in url else []
        idx = s.ProgressionFantasyIndex(http_get=get)
        self.assertEqual(idx.lookup("Elevenchars", ["Someone Else"])["status"], "not_found")
        self.assertEqual(idx.lookup("Twelve chars", ["Someone Else"])["status"], "not_found")
        long_posts = [{"title": {"rendered": "Pen Name &#8211; Twelvecharsx"}, "categories": [6]}]   # 12
        idx2 = s.ProgressionFantasyIndex(http_get=lambda url, timeout: long_posts if "page=1&" in url else [])
        self.assertEqual(idx2.lookup("Twelvecharsx", ["Someone Else"])["status"], "found")

    def test_requests_ask_for_pages_of_a_hundred_with_a_thirty_second_timeout(self):
        seen = []
        def get(url, timeout):
            seen.append((url, timeout))
            return self.POSTS if "page=1&" in url else []
        s.ProgressionFantasyIndex(http_get=get).lookup("Cradle", ["Will Wight"])
        self.assertIn("per_page=100", seen[0][0])
        self.assertEqual(seen[0][1], 30)


class HaremLitDetailTests(unittest.TestCase):
    WIKI = HaremLitTests.WIKI

    def test_a_series_page_is_preferred_over_a_plain_page_for_the_same_search(self):
        titles = []
        def get(url, timeout):
            if "list=search" in url:
                return {"query": {"search": [{"title": "Dragon Emperor"}, {"title": "Dragon Emperor (Series)"}]}}
            titles.append(url)
            return {"parse": {"wikitext": {"*": self.WIKI}}}
        r = s.haremlit_lookup("Dragon Emperor", ["Eric Vall"], http_get=get, pacer=P())
        self.assertEqual(r["match"], "Dragon Emperor (Series)")
        self.assertIn("Series", titles[0])

    def test_the_wiki_is_asked_for_json_with_a_twenty_second_timeout_and_failures_count(self):
        seen = []
        pacer = P()
        def get(url, timeout):
            seen.append((url, timeout))
            return {}
        s._wiki({"action": "query"}, get, pacer)
        self.assertIn("format=json", seen[0][0])
        self.assertEqual(seen[0][1], 20)
        def boom(url, timeout):
            raise OSError("x")
        with self.assertRaises(OSError):
            s._wiki({"action": "query"}, boom, pacer)
        self.assertEqual(pacer._fails, 1)

    def test_template_values_may_contain_equals_signs(self):
        fields = s._template_fields("{{Book_Series_Template|author=[[Ann Lee]]|note=a=b|genre(s)=X}}")
        self.assertEqual((fields["author"], fields["note"]), ("Ann Lee", "a=b"))
        self.assertEqual(fields["_type"], "Book_Series_Template")
        self.assertIsNone(s._template_fields("no template here"))
