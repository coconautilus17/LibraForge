"""A book Audible's search hides is found through its series' own listing.

From outside the US, no search returns Theft of Swords (B007KSJKI8), sold only
in the US and Canada; it returns the dramatized edition (B09PQ951KX) of the same
series instead. The series' listing (Riyria Revelations, B0081WUWRK) names every
member, and a lookup by ASIN returns them all."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.fixer import search as search_module
from app.tests.script_loader import load_module

FIXER = load_module("fixer_v5_series_members", "scripts/audible-metadata-fixer-v5.py")

SERIES = [{"asin": "B0081WUWRK", "title": "Riyria Revelations", "sequence": "1"}]
DRAMATIZED = {
    "asin": "B09PQ951KX", "title": "Theft of Swords [Dramatized Adaptation]",
    "authors": [{"name": "Michael J. Sullivan"}], "narrators": [{"name": "Amanda Forstrom"}],
    "series": SERIES, "runtime_length_min": 1019,
}
THEFT = {
    "asin": "B007KSJKI8", "title": "Theft of Swords", "authors": [{"name": "Michael J. Sullivan"}],
    "narrators": [{"name": "Tim Gerard Reynolds"}], "series": SERIES, "runtime_length_min": 1358,
}
RISE = {
    "asin": "B0081IIZ6Y", "title": "Rise of Empire", "authors": [{"name": "Michael J. Sullivan"}],
    "narrators": [{"name": "Tim Gerard Reynolds"}],
    "series": [{"asin": "B0081WUWRK", "title": "Riyria Revelations", "sequence": "2"}], "runtime_length_min": 1440,
}
CLUES = {
    "raw_title": "Theft of Swords: Riyria Revelations, Volume 1",
    "title": "Theft of Swords: Riyria Revelations, Volume 1", "book_number": "1",
    "book_number_source": "title", "author": "Michael J. Sullivan", "album": "Theft of Swords",
    "local_duration_minutes": 1358.6,
}


class FakeClient:
    """Audible's catalog: the series' listing and the batch lookup by ASIN."""

    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path == "catalog/products/B0081WUWRK":
            return {"product": {"asin": "B0081WUWRK", "relationships": [
                {"asin": a, "relationship_type": "series", "relationship_to_product": "child"}
                for a in ("B007KSJKI8", "B09PQ951KX", "B0081IIZ6Y")
            ] + [{"asin": "B0OTHERXXX", "relationship_type": "component", "relationship_to_product": "child"}]}}
        if path == "catalog/products" and "asins" in (params or {}):
            listings = {p["asin"]: p for p in (THEFT, DRAMATIZED, RISE)}
            return {"products": [dict(listings[a]) for a in params["asins"].split(",") if a in listings]}
        return {}


class SeriesHelperTests(unittest.TestCase):
    def setUp(self):
        search_module._SERIES_MEMBERS.clear()

    def test_members_are_the_series_children_and_are_cached(self):
        client = FakeClient()
        self.assertEqual(search_module.audible_series_members(client, "b0081wuwrk"),
                         ["B007KSJKI8", "B09PQ951KX", "B0081IIZ6Y"])
        search_module.audible_series_members(client, "B0081WUWRK")
        self.assertEqual(len(client.calls), 1)

    def test_only_the_books_own_series_is_followed(self):
        other = {"asin": "B0X", "series": [{"asin": "B0OTHERSER", "title": "The Frozen River"}]}
        self.assertEqual(FIXER.series_asins_for_book([DRAMATIZED, other], dict(CLUES)), ["B0081WUWRK"])
        self.assertEqual(FIXER.series_asins_for_book([DRAMATIZED], {"title": "Fourth Wing", "author": "x"}), [])
        tagged = {"title": "Theft of Swords", "series": "Riyria Revelations, Book 1", "author": "Michael J. Sullivan"}
        self.assertEqual(FIXER.series_asins_for_book([DRAMATIZED], tagged), ["B0081WUWRK"])


class SeriesFallbackTests(unittest.TestCase):
    def setUp(self):
        search_module._SERIES_MEMBERS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Path(self.tmp.name) / "Theft of Swords.m4b"
        self.book.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def _call(self, clues, search):
        args = SimpleNamespace(
            aggressive=False, force=False, min_score=0.7, force_original=False, reprobe=False,
            backup=False, ignore_folder=[], skip_pattern=[], limit=10, api_delay_ms=0,
            abs_agg_url="", abs_tract_url="", trust_abs_metadata=False, weight_abs_metadata=False,
            provider="audible", abs_provider="audible", abs_url="", abs_api_key="",
            audiosilo_url="", enable_goodreads_fallback=False,
        )
        client = FakeClient()
        key = FIXER.get_search_context_cache_key(self.book, {})
        with patch.object(FIXER, "get_thread_client", return_value=client), \
                patch.object(FIXER, "cached_audible_search", side_effect=search):
            return FIXER.search_item(
                index=1, file_path=self.book, total=1, multi_part_group_map={},
                args=args, auth_file="", auth_password=None,
                search_context_cache={key: ([clues["title"] + " Michael J. Sullivan"], dict(clues))},
                search_context_lock=threading.Lock(),
                match_cache={}, match_cache_lock=threading.Lock(),
                search_cache={}, search_cache_lock=threading.Lock(),
                search_in_flight={}, folder_audio_counts=None, abs_index=None,
            )

    def test_the_hidden_book_is_found_among_its_series_members(self):
        result = self._call(CLUES, lambda *a, **k: [dict(DRAMATIZED)])
        self.assertEqual(result.metadata["asin"], "B007KSJKI8")
        self.assertEqual(result.metadata["edit_mode"], "full")
        self.assertEqual(result.used_query, "series:B0081WUWRK")

    def test_a_search_for_the_series_name_finds_the_series_when_nothing_else_does(self):
        sent = []

        def search(client, query, *a, **k):
            sent.append(query)
            return [dict(DRAMATIZED)] if query == "Riyria Revelations Michael J. Sullivan" else []

        clues = {"raw_title": "Rise of Empire: Riyria Revelations, Volume 2",
                 "title": "Rise of Empire: Riyria Revelations, Volume 2", "book_number": "2",
                 "book_number_source": "title", "author": "Michael J. Sullivan", "album": "Rise of Empire",
                 "local_duration_minutes": 1440.4}
        result = self._call(clues, search)
        self.assertIn("Riyria Revelations Michael J. Sullivan", sent)
        self.assertEqual(result.metadata["asin"], "B0081IIZ6Y")
        self.assertEqual(result.metadata["edit_mode"], "full")


if __name__ == "__main__":
    unittest.main()
