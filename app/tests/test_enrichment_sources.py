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
    def test_asin_query_and_labels(self):
        seen = []

        def get(url, timeout):
            seen.append(url)
            return {"matches": [{"title": "Unsouled", "genres": ["Fantasy", "Progression Fantasy (g)"]}]}

        r = s.audiosilo_lookup(BOOK, pacer=P(), http_get=get)
        self.assertEqual(r["status"], "found")
        self.assertIn("progression fantasy", r["labels"])
        self.assertIn("query=B06XKXD6QR", seen[0])

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
            return {"matches": []} if len(seen) == 1 else {"matches": [{"title": "Unsouled", "genres": ["Fantasy"]}]}

        self.assertEqual(s.audiosilo_lookup(BOOK, pacer=P(), http_get=get)["status"], "found")
        self.assertEqual(len(seen), 2)

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

        r = s.haremlit_lookup("Dragon Emperor", ["Eric Vall"], http_get=get)
        self.assertEqual((r["status"], r["via"], r["explicit"]), ("found", "series", "Yes"))
        self.assertIn("portal fantasy", r["genres"])
        other = s.haremlit_lookup("Dragon Emperor", ["Someone Else"], http_get=lambda u, t: (
            {"query": {"search": [{"title": "Dragon Emperor (Series)"}]}} if "list=search" in u
            else {"parse": {"wikitext": {"*": self.WIKI}}} if "Dragon" in u else {"error": {"code": "missingtitle"}}))
        self.assertEqual(other["status"], "not_found")

    def test_author_page_listing(self):
        def get(url, timeout):
            if "list=search" in url:
                return {"query": {"search": []}}
            return {"parse": {"wikitext": {"*": "* [[Building Harem Town]]\n* [[Chaos God (Series)|Chaos God]]"}}}

        r = s.haremlit_lookup("Chaos God", ["Eric Vall"], http_get=get)
        self.assertEqual((r["status"], r["via"]), ("found", "author"))

    def test_network_failure_is_failed(self):
        def get(url, timeout):
            raise TimeoutError()

        self.assertEqual(s.haremlit_lookup("X", ["Y"], http_get=get)["status"], "failed")

    def test_series_level_labels(self):
        labels, ev, pfp = s.series_level_labels({"status": "found", "category": "Progression", "title": "A – B"},
                                                {"status": "found", "match": "X", "genres": ["urban fantasy"]})
        self.assertEqual((sorted(labels), pfp), (["haremlit", "urban fantasy"], True))
        self.assertEqual(len(ev), 2)
        labels, ev, pfp = s.series_level_labels({"status": "found", "category": "LitRPG", "title": "A – B"}, {"status": "not_found"})
        self.assertEqual((labels, pfp), (["litrpg"], False))
