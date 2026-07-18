"""Endpoint tests for Manual Review's filesystem search index/status and
search routes."""
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import _ManualReviewSearchIndex

client = TestClient(main_module.app)


class _BaseIndexEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._orig_root = main_module.AUDIOBOOKS_ROOT
        main_module.AUDIOBOOKS_ROOT = self.root
        self._orig_state = main_module._manual_review_search_index
        main_module._manual_review_search_index = _ManualReviewSearchIndex()

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig_root
        main_module._manual_review_search_index = self._orig_state
        self.tmp.cleanup()

    def _set_ready(self, entries=(), book_count=None, ignored=()):
        state = main_module._manual_review_search_index
        state.status = "ready"
        state.entries = list(entries)
        state.book_count = book_count if book_count is not None else len(entries)
        state.fingerprint = main_module._library_fingerprint(self.root)
        state.ignored_signature = main_module._ignored_signature(list(ignored))


class ManualReviewSearchEbookFieldsTests(_BaseIndexEndpointTest):
    def test_ebook_entry_reports_media_type_and_formats(self):
        state = main_module._manual_review_search_index
        state.status = "ready"
        state.entries = [("/audiobooks/Linux/EPUB/kubernetes.epub", True)]
        state.ebook_formats = {"/audiobooks/Linux/EPUB/kubernetes.epub": ["epub", "pdf"]}
        state.book_count = 1
        state.ignored_signature = main_module._ignored_signature([])

        res = client.post("/api/manual-review/search", json={"query": ""})
        self.assertEqual(res.status_code, 200)
        result = res.json()["results"][0]
        self.assertEqual(result["media_type"], "ebook")
        self.assertEqual(sorted(result["formats"]), ["epub", "pdf"])

    def test_audio_entry_reports_no_media_type(self):
        state = main_module._manual_review_search_index
        state.status = "ready"
        state.entries = [("/audiobooks/Author/Book", False)]
        state.book_count = 1
        state.ignored_signature = main_module._ignored_signature([])

        res = client.post("/api/manual-review/search", json={"query": ""})
        result = res.json()["results"][0]
        self.assertEqual(result["media_type"], "")
        self.assertEqual(result["formats"], [])


class ManualReviewSearchIndexStatusEndpointTests(_BaseIndexEndpointTest):
    def test_reports_ready_state_without_error(self):
        self._set_ready(entries=[("/audiobooks/A/Book", False)])
        res = client.get("/api/manual-review/search-index/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data, {"status": "ready", "book_count": 1, "error": None})

    def test_never_built_eventually_reaches_ready(self):
        # Integration-style: empty temp dir means the real background build
        # is near-instant, so a short poll settles without flakiness.
        res = client.get("/api/manual-review/search-index/status")
        self.assertEqual(res.status_code, 200)
        self.assertIn(res.json()["status"], ("idle", "building", "ready"))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and main_module._manual_review_search_index.status != "ready":
            time.sleep(0.02)
        self.assertEqual(main_module._manual_review_search_index.status, "ready")
        self.assertEqual(main_module._manual_review_search_index.book_count, 0)


class ManualReviewSearchEndpointTests(_BaseIndexEndpointTest):
    def test_empty_query_returns_all_entries(self):
        self._set_ready(entries=[
            ("/audiobooks/Sanderson/Mistborn/The Final Empire", False),
            ("/audiobooks/Loose.m4b", True),
        ])
        res = client.post("/api/manual-review/search", json={"query": ""})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["index_status"], "ready")
        self.assertEqual(data["book_count"], 2)

    def test_filters_by_case_insensitive_substring_anywhere_in_path(self):
        self._set_ready(entries=[
            ("/audiobooks/Sanderson/Mistborn/The Final Empire", False),
            ("/audiobooks/Rowling/Harry Potter", False),
        ])
        res = client.post("/api/manual-review/search", json={"query": "sanderson"})
        results = res.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "The Final Empire")
        self.assertEqual(results[0]["path"], "/audiobooks/Sanderson/Mistborn/The Final Empire")
        self.assertFalse(results[0]["is_file"])

    def test_matches_book_name_segment_not_just_leading_segments(self):
        self._set_ready(entries=[("/audiobooks/Author/The Final Empire", False)])
        res = client.post("/api/manual-review/search", json={"query": "final empire"})
        self.assertEqual(len(res.json()["results"]), 1)

    def test_no_result_cap(self):
        entries = [(f"/audiobooks/Author/Book {i}", False) for i in range(75)]
        self._set_ready(entries=entries)
        res = client.post("/api/manual-review/search", json={"query": "Book"})
        self.assertEqual(len(res.json()["results"]), 75)

    def test_is_file_entries_reported_correctly(self):
        self._set_ready(entries=[("/audiobooks/Loose.m4b", True)])
        res = client.post("/api/manual-review/search", json={"query": ""})
        self.assertTrue(res.json()["results"][0]["is_file"])
