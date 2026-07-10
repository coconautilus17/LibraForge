"""Tests for Enrichment Forge API fallback behavior."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main


class EnrichmentCompileEndpointFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.missing_auth = str(Path(self.tmp.name) / "missing-auth.json")
        self.books = [
            {
                "id": "1",
                "path": "/audiobooks/Series/Book",
                "is_file": False,
                "title": "Book",
                "asin": "B0TEST",
                "author": "Author",
                "existing_genres": ["Local Fantasy"],
                "existing_narrator": "",
                "existing_explicit": False,
            }
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def _base_patches(self):
        return [
            patch("app.main._get_abs_api_key", return_value="abs-key"),
            patch("app.main.load_review_module", return_value=SimpleNamespace(normalize_series=lambda value: value.lower())),
            patch("app.main.fetch_all_abs_book_items", return_value=[]),
            patch("app.main.group_items_by_series", return_value={}),
            patch("app.main.get_series_books", return_value=self.books),
        ]

    def test_missing_audible_auth_uses_abs_and_skips_unconfigured_goodreads(self):
        patches = self._base_patches() + [
            patch("app.main.search_series_abs", return_value={"1": {"genre": "Fantasy", "narrators": ["ABS Narrator"]}}),
            patch("app.main.search_series_audible", side_effect=AssertionError("direct Audible should not run")),
            patch("app.main.search_series_goodreads", side_effect=AssertionError("Goodreads should not run without abs-tract URL")),
            patch("app.main._load_abs_tract_config", return_value={"url": ""}),
        ]
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])

        result = main.enrichment_compile(
            main.EnrichmentCompileRequest(series_name="Series", auth_file=self.missing_auth)
        )

        self.assertEqual(result.source_status["audible"].state, "searched")
        self.assertIn("ABS's Audible provider", result.source_status["audible"].detail)
        self.assertNotIn("abs", result.source_status)
        self.assertEqual(result.source_status["goodreads"].state, "skipped")
        self.assertIn("abs-tract is not connected", result.source_status["goodreads"].detail)
        self.assertEqual(result.books[0].audible_genres, ["Fantasy"])
        self.assertEqual(result.books[0].existing_genres, ["Local Fantasy"])
        self.assertEqual(result.narrator, "ABS Narrator")


if __name__ == "__main__":
    unittest.main()
