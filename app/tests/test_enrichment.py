"""Tests for app.enrichment: ABS series discovery and grouping."""
import re
import unittest

from app import enrichment


def _fake_normalize_series(value: str) -> str:
    """Stand-in for scripts/review-libraforge-report.py's normalize_series():
    lowercases and strips a trailing ', Book N' qualifier. Real tests against
    the actual function happen in Task 5's endpoint tests, which load the
    real script via load_review_module()."""
    s = value.strip().lower()
    s = re.sub(r",?\s*book\s+\d+\s*$", "", s).strip()
    return s


class StripSequenceSuffixTests(unittest.TestCase):
    def test_strips_hash_number(self):
        self.assertEqual(
            enrichment.strip_series_sequence_suffix("Youngest Son of the Black-Hearted #1"),
            "Youngest Son of the Black-Hearted",
        )

    def test_no_suffix_unchanged(self):
        self.assertEqual(enrichment.strip_series_sequence_suffix("Scholomance"), "Scholomance")

    def test_blank_input(self):
        self.assertEqual(enrichment.strip_series_sequence_suffix(""), "")


class NormalizeAbsSeriesNameTests(unittest.TestCase):
    def test_strips_hash_then_delegates(self):
        result = enrichment.normalize_abs_series_name("Scholomance #1", _fake_normalize_series)
        self.assertEqual(result, "scholomance")


class FetchAllAbsBookItemsTests(unittest.TestCase):
    def _abs_request(self, path, params):
        if path == "/api/libraries":
            return {"libraries": [{"id": "lib1", "mediaType": "book"}]}
        if path == "/api/libraries/lib1/items":
            page = int(params["page"])
            if page == 0:
                return {"total": 2, "results": [{"id": "a"}, {"id": "b"}]}
            return {"total": 2, "results": []}
        raise AssertionError(f"unexpected path {path}")

    def test_walks_all_pages(self):
        items = enrichment.fetch_all_abs_book_items(self._abs_request)
        self.assertEqual([i["id"] for i in items], ["a", "b"])


class GroupItemsBySeriesTests(unittest.TestCase):
    def test_groups_by_normalized_name_and_skips_no_series(self):
        items = [
            {"id": "1", "media": {"metadata": {"seriesName": "Scholomance #1"}}},
            {"id": "2", "media": {"metadata": {"seriesName": "Scholomance #2"}}},
            {"id": "3", "media": {"metadata": {"seriesName": ""}}},
        ]
        groups = enrichment.group_items_by_series(items, _fake_normalize_series)
        self.assertEqual(sorted(groups.keys()), ["scholomance"])
        self.assertEqual(len(groups["scholomance"]), 2)


class ListSeriesSummaryTests(unittest.TestCase):
    def test_summary_counts_sorted_desc(self):
        groups = {
            "scholomance": [
                {"media": {"metadata": {"seriesName": "Scholomance #1"}}},
                {"media": {"metadata": {"seriesName": "Scholomance #2"}}},
            ],
            "dungeon core": [
                {"media": {"metadata": {"seriesName": "Dungeon Core #1"}}},
            ],
        }
        summary = enrichment.list_series_summary(groups)
        self.assertEqual(summary, [
            {"name": "Scholomance", "book_count": 2},
            {"name": "Dungeon Core", "book_count": 1},
        ])

    def test_query_filters_case_insensitively(self):
        groups = {
            "scholomance": [{"media": {"metadata": {"seriesName": "Scholomance #1"}}}],
            "dungeon core": [{"media": {"metadata": {"seriesName": "Dungeon Core #1"}}}],
        }
        summary = enrichment.list_series_summary(groups, query="scho")
        self.assertEqual(summary, [{"name": "Scholomance", "book_count": 1}])


class GetSeriesBooksTests(unittest.TestCase):
    def test_returns_lightweight_book_dicts(self):
        groups = {
            "scholomance": [
                {
                    "id": "item-1",
                    "path": "/audiobooks/Logan Jacobs/Scholomance/Scholomance",
                    "isFile": False,
                    "media": {
                        "metadata": {
                            "title": "Scholomance",
                            "asin": "b0xxxxxxxx",
                            "authorName": "Logan Jacobs",
                            "narratorName": "Andrea Parsneau",
                            "explicit": False,
                        },
                        # NOTE: ABS's own metadata.genres field is often just a
                        # placeholder like ["Audiobook"]; the real per-book genre
                        # data lives in media.tags. Confirmed against a live ABS
                        # instance during design (2026-07-10).
                        "tags": ["Fantasy", "LitRPG"],
                    },
                }
            ]
        }
        books = enrichment.get_series_books(groups, "Scholomance", _fake_normalize_series)
        self.assertEqual(books, [{
            "id": "item-1",
            "path": "/audiobooks/Logan Jacobs/Scholomance/Scholomance",
            "is_file": False,
            "title": "Scholomance",
            "asin": "B0XXXXXXXX",
            "author": "Logan Jacobs",
            "existing_genres": ["Fantasy", "LitRPG"],
            "existing_narrator": "Andrea Parsneau",
            "existing_explicit": False,
        }])

    def test_unknown_series_returns_empty(self):
        books = enrichment.get_series_books({}, "Nonexistent", _fake_normalize_series)
        self.assertEqual(books, [])


if __name__ == "__main__":
    unittest.main()
