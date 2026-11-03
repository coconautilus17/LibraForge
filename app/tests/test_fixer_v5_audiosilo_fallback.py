"""AudioSilo's community database is searched when Audible finds no full match,
before Goodreads, and its pick's ASIN is confirmed on Audible.

Hellstrom's Hive (B002V59S5K) is sold only in the US and Canada: Audible's search
hides it from anywhere else, while a lookup by its ASIN still returns it."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.fixer import search as search_module
from app.goodreads_shelves import GoodreadsPacer
from app.tests.script_loader import load_module

FIXER = load_module("fixer_v5_audiosilo_fallback", "scripts/audible-metadata-fixer-v5.py")

AUDIOSILO_MATCH = {
    "title": "Hellstrom's Hive", "author": "Frank Herbert", "narrator": "Scott Brick",
    "publisher": "Tantor Audio", "asin": "b002v59s5k", "language": "en", "duration": 730,
}
AUDIBLE_PRODUCT = {
    "asin": "B002V59S5K", "title": "Hellstrom's Hive", "authors": [{"name": "Frank Herbert"}],
    "narrators": [{"name": "Scott Brick"}], "series": [], "runtime_length_min": 730,
    "publisher_name": "Tantor Media", "release_date": "2008-04-08",
}
CLUES = {"title": "Hellstrom's Hive", "author": "Frank Herbert", "local_duration_minutes": 730.33}


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _reset():
    # A fresh pacer with no gap: no test waits, and none inherits another's open breaker.
    search_module.AUDIOSILO_PACER = GoodreadsPacer(gap_s=0, fail_threshold=3, cooldown_s=60)
    search_module._ABS_TRACT_BREAKER.update(
        {"consecutive_failures": 0, "open_until": 0.0, "logged_open": False, "ever_opened": False}
    )


class AudioSiloSearchTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_results_keep_runtime_narrator_and_asin(self):
        sent = {}

        def fake_open(req, timeout=10):
            sent["url"] = req.full_url
            return _Resp({"matches": [AUDIOSILO_MATCH]})

        with patch("urllib.request.urlopen", fake_open):
            products = search_module.audiosilo_search("Hellstrom's Hive", "Frank Herbert", "http://silo:8080/", 10)
        self.assertTrue(sent["url"].startswith("http://silo:8080/abs/search?query=Hellstrom"))
        self.assertIn("author=Frank+Herbert", sent["url"])
        product = products[0]
        self.assertEqual(product["asin"], "B002V59S5K")
        self.assertEqual(product["runtime_length_min"], 730)
        self.assertEqual(product["narrators"], [{"name": "Scott Brick"}])
        self.assertEqual(product["_abs_provider"], "audiosilo")

    def test_a_service_that_keeps_failing_is_paused(self):
        calls = []

        def down(req, timeout=10):
            calls.append(1)
            raise OSError("connection refused")

        log = []
        with patch("urllib.request.urlopen", down):
            for _ in range(5):
                self.assertEqual(search_module.audiosilo_search("x", "", "http://silo", 10, log), [])
        self.assertEqual(len(calls), 3)
        self.assertIn("AudioSilo paused after failed requests", log[-1])


class AudioSiloFallbackTests(unittest.TestCase):
    def setUp(self):
        _reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Path(self.tmp.name) / "Hellstrom's Hive.m4b"
        self.book.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def _call(self, audiosilo_matches, audible_lookup, goodreads=None):
        args = SimpleNamespace(
            aggressive=False, force=False, min_score=0.7, force_original=False, reprobe=False,
            backup=False, ignore_folder=[], skip_pattern=[], limit=10, api_delay_ms=0,
            abs_agg_url="", abs_tract_url="", trust_abs_metadata=False, weight_abs_metadata=False,
            provider="audible", abs_provider="audible", abs_url="", abs_api_key="",
            audiosilo_url="http://silo", enable_goodreads_fallback=True,
        )
        key = FIXER.get_search_context_cache_key(self.book, {})
        goodreads = goodreads or (lambda *a, **k: (None, 0.0, None, ""))
        with patch.object(FIXER, "get_thread_client", return_value=object()), \
                patch.object(FIXER, "cached_audible_search", return_value=[]), \
                patch("urllib.request.urlopen", lambda req, timeout=10: _Resp({"matches": audiosilo_matches})), \
                patch.object(FIXER, "audible_lookup_by_asin", side_effect=audible_lookup), \
                patch.object(FIXER, "find_goodreads_match", side_effect=goodreads) as gr:
            result = FIXER.search_item(
                index=1, file_path=self.book, total=1, multi_part_group_map={},
                args=args, auth_file="", auth_password=None,
                search_context_cache={key: (["Hellstrom's Hive Frank Herbert"], dict(CLUES))},
                search_context_lock=threading.Lock(),
                match_cache={}, match_cache_lock=threading.Lock(),
                search_cache={}, search_cache_lock=threading.Lock(),
                search_in_flight={}, folder_audio_counts=None, abs_index=None,
            )
        return result, gr

    def test_a_book_audible_search_hides_is_found_and_confirmed_on_audible(self):
        result, goodreads = self._call([AUDIOSILO_MATCH], lambda client, asin: dict(AUDIBLE_PRODUCT))
        self.assertEqual(result.metadata["asin"], "B002V59S5K")
        self.assertEqual(result.metadata["edit_mode"], "full")
        self.assertTrue(result.used_query.startswith("audiosilo:"))
        self.assertEqual(result.source_provider, "")  # the details are Audible's listing
        goodreads.assert_not_called()

    def test_an_asin_audible_does_not_know_is_not_written(self):
        result, goodreads = self._call([AUDIOSILO_MATCH], lambda client, asin: None)
        self.assertEqual(result.metadata["edit_mode"], "full")
        self.assertEqual(result.metadata["asin"], "")
        self.assertEqual(result.source_provider, "audiosilo")
        goodreads.assert_not_called()

    def test_goodreads_still_runs_when_audiosilo_has_nothing(self):
        result, goodreads = self._call([], lambda client, asin: None)
        goodreads.assert_called_once()
        self.assertEqual(result.status, "skipped")


if __name__ == "__main__":
    unittest.main()
