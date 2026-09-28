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
