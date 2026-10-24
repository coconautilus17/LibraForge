"""Audible mode sends a structured title + author search before the keyword
queries (#409), the way ABS mode does (#382)."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.tests.script_loader import load_module

FIXER = load_module("fixer_v5_audible_structured", "scripts/audible-metadata-fixer-v5.py")

POSTWAR = {
    "asin": "B078GVB8P3", "title": "Postwar", "subtitle": "A History of Europe Since 1945",
    "authors": [{"name": "Tony Judt"}], "narrators": [{"name": "Ralph Cosham"}], "series": [],
    "runtime_length_min": 2581, "runtime_length_sec": 2581 * 60,
}


class AudibleStructuredQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Path(self.tmp.name) / "Postwar.m4b"
        self.book.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def _call(self, clues, queries, fake_search):
        args = SimpleNamespace(
            aggressive=False, force=False, min_score=0.7, force_original=False, reprobe=False,
            backup=False, ignore_folder=[], skip_pattern=[], limit=10, api_delay_ms=0,
            abs_agg_url="", abs_tract_url="", trust_abs_metadata=False, weight_abs_metadata=False,
            provider="audible", abs_provider="audible", abs_url="", abs_api_key="",
        )
        key = FIXER.get_search_context_cache_key(self.book, {})
        with patch.object(FIXER, "get_thread_client", return_value=object()), \
                patch.object(FIXER, "cached_audible_search", side_effect=fake_search):
            return FIXER.search_item(
                index=1, file_path=self.book, total=1, multi_part_group_map={},
                args=args, auth_file="", auth_password=None,
                search_context_cache={key: (queries, clues)}, search_context_lock=threading.Lock(),
                match_cache={}, match_cache_lock=threading.Lock(),
                search_cache={}, search_cache_lock=threading.Lock(),
                search_in_flight={}, folder_audio_counts=None, abs_index=None,
            )

    def test_title_and_first_author_are_searched_first(self):
        sent = []

        def fake(client, query, limit, delay, cache, lock, in_flight, title="", author=""):
            sent.append((query, title, author))
            return [dict(POSTWAR)] if title else []

        clues = {"title": "Postwar", "author": "Tony Judt, Ralph Cosham", "local_duration_minutes": 2581.0}
        result = self._call(clues, ["Postwar A History of Europe Since 1945 Tony Judt"], fake)
        self.assertEqual(sent[0], ("Postwar - Tony Judt", "Postwar", "Tony Judt"))
        self.assertEqual(result.metadata["asin"], "B078GVB8P3")

    def test_no_author_means_keyword_queries_only(self):
        sent = []

        def fake(client, query, limit, delay, cache, lock, in_flight, title="", author=""):
            sent.append((query, title, author))
            return []

        self._call({"title": "Postwar", "author": "", "local_duration_minutes": 2581.0}, ["Postwar"], fake)
        self.assertEqual(sent, [("Postwar", "", "")])


if __name__ == "__main__":
    unittest.main()
