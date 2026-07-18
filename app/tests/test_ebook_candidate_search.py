"""search_ebook_candidates: Open Library primary, Goodreads (abs-tract)
backfill for missing cover_url/summary. Live-tested against the real
Linux ebook folder before this was written -- see docs/superpowers/specs/
2026-07-18-ebook-support-design.md for the raw results that motivated the
backfill-on-blank-fields (not just backfill-on-zero-results) behavior."""
import unittest
from unittest.mock import patch

import app.main as main_module
from app.main import search_ebook_candidates


def _ol_result(**overrides):
    base = {
        "asin": "abs-openlibrary-0", "isbn": "", "title": "Efficient Linux at the Command Line",
        "subtitle": "", "authors": ["Daniel J. Barrett"], "narrators": [], "series": "", "sequence": "",
        "duration_minutes": None, "year": "2022", "cover_url": "", "summary": "",
    }
    base.update(overrides)
    return base


def _gr_result(**overrides):
    base = {
        "asin": "", "title": "Efficient Linux at the Command Line", "subtitle": "",
        "authors": ["Daniel J. Barrett"], "narrators": [], "series": "", "sequence": "",
        "duration_minutes": None, "year": "2022",
        "cover_url": "https://i.gr-assets.com/cover.jpg", "summary": "A practical book...",
    }
    base.update(overrides)
    return base


class SearchEbookCandidatesTests(unittest.TestCase):
    def test_returns_none_when_both_sources_have_nothing(self):
        with patch.object(main_module, "search_abs_candidates", return_value={"queries": [], "results": []}), \
             patch.object(main_module, "_load_abs_tract_config", return_value={"url": "http://abs-tract:5555", "kindle_region": "us"}), \
             patch.object(main_module, "search_abs_tract_candidates", return_value={"queries": [], "results": []}):
            self.assertIsNone(search_ebook_candidates(title="Nonexistent Book"))

    def test_open_library_result_with_full_fields_is_used_as_is(self):
        with patch.object(main_module, "search_abs_candidates", return_value={"queries": [], "results": [_ol_result(cover_url="https://x/y.jpg", summary="Something")]}), \
             patch.object(main_module, "search_abs_tract_candidates") as gr_mock:
            result = search_ebook_candidates(title="Efficient Linux at the Command Line")
            self.assertEqual(result["title"], "Efficient Linux at the Command Line")
            self.assertEqual(result["cover_url"], "https://x/y.jpg")
            gr_mock.assert_not_called()

    def test_blank_cover_and_summary_are_backfilled_from_goodreads(self):
        with patch.object(main_module, "search_abs_candidates", return_value={"queries": [], "results": [_ol_result()]}), \
             patch.object(main_module, "_load_abs_tract_config", return_value={"url": "http://abs-tract:5555", "kindle_region": "us"}), \
             patch.object(main_module, "search_abs_tract_candidates", return_value={"queries": [], "results": [_gr_result()]}):
            result = search_ebook_candidates(title="Efficient Linux at the Command Line")
            self.assertEqual(result["cover_url"], "https://i.gr-assets.com/cover.jpg")
            self.assertEqual(result["summary"], "A practical book...")
            # Identity fields stay whatever Open Library reported.
            self.assertEqual(result["authors"], ["Daniel J. Barrett"])

    def test_zero_open_library_results_falls_through_entirely_to_goodreads(self):
        with patch.object(main_module, "search_abs_candidates", return_value={"queries": [], "results": []}), \
             patch.object(main_module, "_load_abs_tract_config", return_value={"url": "http://abs-tract:5555", "kindle_region": "us"}), \
             patch.object(main_module, "search_abs_tract_candidates", return_value={"queries": [], "results": [_gr_result(title="Kubernetes")]}):
            result = search_ebook_candidates(title="Kubernetes Up and Running")
            self.assertEqual(result["title"], "Kubernetes")

    def test_abs_tract_not_configured_skips_backfill_without_raising(self):
        with patch.object(main_module, "search_abs_candidates", return_value={"queries": [], "results": [_ol_result()]}), \
             patch.object(main_module, "_load_abs_tract_config", return_value={"url": "", "kindle_region": "us"}), \
             patch.object(main_module, "search_abs_tract_candidates") as gr_mock:
            result = search_ebook_candidates(title="Efficient Linux at the Command Line")
            self.assertEqual(result["cover_url"], "")
            gr_mock.assert_not_called()

    def test_open_library_unreachable_falls_through_to_goodreads(self):
        from fastapi import HTTPException
        with patch.object(main_module, "search_abs_candidates", side_effect=HTTPException(status_code=502, detail="unreachable")), \
             patch.object(main_module, "_load_abs_tract_config", return_value={"url": "http://abs-tract:5555", "kindle_region": "us"}), \
             patch.object(main_module, "search_abs_tract_candidates", return_value={"queries": [], "results": [_gr_result()]}):
            result = search_ebook_candidates(title="Efficient Linux at the Command Line")
            self.assertEqual(result["cover_url"], "https://i.gr-assets.com/cover.jpg")

    def test_goodreads_unreachable_does_not_raise(self):
        from fastapi import HTTPException
        with patch.object(main_module, "search_abs_candidates", return_value={"queries": [], "results": [_ol_result()]}), \
             patch.object(main_module, "_load_abs_tract_config", return_value={"url": "http://abs-tract:5555", "kindle_region": "us"}), \
             patch.object(main_module, "search_abs_tract_candidates", side_effect=HTTPException(status_code=502, detail="unreachable")):
            result = search_ebook_candidates(title="Efficient Linux at the Command Line")
            self.assertEqual(result["title"], "Efficient Linux at the Command Line")
            self.assertEqual(result["cover_url"], "")


if __name__ == "__main__":
    unittest.main()
