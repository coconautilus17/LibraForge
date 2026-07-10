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


class SearchSeriesAudibleTests(unittest.TestCase):
    def test_uses_lookup_when_asin_present(self):
        books = [{"id": "1", "asin": "B0AAA", "title": "T", "author": "A"}]

        def lookup(client, asin):
            self.assertEqual(asin, "B0AAA")
            return {"asin": asin}

        def search(client, query, limit):
            raise AssertionError("should not be called when ASIN is known")

        result = enrichment.search_series_audible(books, search, lookup, client=None)
        self.assertEqual(result, {"1": {"asin": "B0AAA"}})

    def test_falls_back_to_text_search_without_asin(self):
        books = [{"id": "1", "asin": "", "title": "Scholomance", "author": "Logan Jacobs"}]

        def lookup(client, asin):
            raise AssertionError("should not be called without an ASIN")

        def search(client, query, limit):
            self.assertEqual(query, "Scholomance Logan Jacobs")
            return [{"asin": "B0BBB"}, {"asin": "B0CCC"}]

        result = enrichment.search_series_audible(books, search, lookup, client=None)
        self.assertEqual(result, {"1": {"asin": "B0BBB"}})

    def test_no_title_or_author_yields_none(self):
        books = [{"id": "1", "asin": "", "title": "", "author": ""}]
        result = enrichment.search_series_audible(
            books, lambda *a: [], lambda *a: None, client=None
        )
        self.assertEqual(result, {"1": None})

    def test_one_book_failure_does_not_affect_others(self):
        books = [
            {"id": "1", "asin": "B0AAA", "title": "", "author": ""},
            {"id": "2", "asin": "B0BBB", "title": "", "author": ""},
        ]

        def lookup(client, asin):
            if asin == "B0AAA":
                raise RuntimeError("network blip")
            return {"asin": asin}

        result = enrichment.search_series_audible(books, lambda *a: [], lookup, client=None)
        self.assertEqual(result, {"1": None, "2": {"asin": "B0BBB"}})


class SearchSeriesGoodreadsTests(unittest.TestCase):
    def test_calls_for_every_book_unconditionally(self):
        books = [{"id": "1", "title": "T1", "author": "A1"}, {"id": "2", "title": "T2", "author": "A2"}]
        calls = []

        def abs_tract(**kwargs):
            calls.append(kwargs["title"])
            return [{"title": kwargs["title"]}]

        result = enrichment.search_series_goodreads(books, abs_tract, abs_tract_url="http://abs-tract:5555")
        self.assertEqual(sorted(calls), ["T1", "T2"])
        self.assertEqual(result["1"], [{"title": "T1"}])
        self.assertEqual(result["2"], [{"title": "T2"}])

    def test_book_failure_yields_empty_list_not_exception(self):
        books = [{"id": "1", "title": "T", "author": "A"}]

        def abs_tract(**kwargs):
            raise RuntimeError("upstream blocked")

        result = enrichment.search_series_goodreads(books, abs_tract, abs_tract_url="http://abs-tract:5555")
        self.assertEqual(result, {"1": []})


class AudibleCategoryLadderGenresTests(unittest.TestCase):
    def test_takes_leaf_name_of_each_ladder(self):
        product = {
            "category_ladders": [
                {"ladder": [{"name": "Science Fiction & Fantasy"}, {"name": "Fantasy"}, {"name": "Epic"}]},
                {"ladder": [{"name": "Science Fiction & Fantasy"}, {"name": "Fantasy"}]},
            ]
        }
        self.assertEqual(enrichment.audible_category_ladder_genres(product), ["Epic", "Fantasy"])

    def test_none_product_returns_empty(self):
        self.assertEqual(enrichment.audible_category_ladder_genres(None), [])


class IsFlaggedExplicitTests(unittest.TestCase):
    def test_is_adult_product_true_flags(self):
        self.assertTrue(enrichment.is_flagged_explicit({"is_adult_product": True}))

    def test_erotica_root_category_flags(self):
        product = {"category_ladders": [{"ladder": [{"name": "Erotica"}, {"name": "Literature & Fiction"}]}]}
        self.assertTrue(enrichment.is_flagged_explicit(product))

    def test_fantasy_only_does_not_flag(self):
        product = {"is_adult_product": False, "category_ladders": [{"ladder": [{"name": "Fantasy"}]}]}
        self.assertFalse(enrichment.is_flagged_explicit(product))

    def test_none_product_does_not_flag(self):
        self.assertFalse(enrichment.is_flagged_explicit(None))


class ExplicitEvidenceNoteTests(unittest.TestCase):
    def test_zero_flagged(self):
        note = enrichment.explicit_evidence_note(0, 4)
        self.assertIn("No book in this series returned a positive Erotica/adult signal", note)
        self.assertIn("use your own judgment for the whole series", note)

    def test_all_flagged(self):
        note = enrichment.explicit_evidence_note(4, 4)
        self.assertIn("All 4 books in this series show a positive Erotica/adult signal", note)

    def test_some_flagged(self):
        note = enrichment.explicit_evidence_note(2, 4)
        self.assertIn("2 of 4 books in this series show a positive Erotica/adult signal", note)

    def test_caveat_always_present(self):
        for flagged, total in [(0, 3), (3, 3), (1, 3)]:
            note = enrichment.explicit_evidence_note(flagged, total)
            self.assertIn("that doesn't confirm the rest are clean".lower(), note.lower())


class CompileSeriesEnrichmentTests(unittest.TestCase):
    def _clean_genres(self, genres):
        return [g for g in genres if g]

    def test_compiles_union_and_flags(self):
        books = [
            {"id": "1", "path": "/audiobooks/Scholomance", "is_file": False, "title": "Scholomance", "existing_genres": ["Fantasy"], "existing_narrator": "", "existing_explicit": False},
            {"id": "2", "path": "/audiobooks/Scholomance 2", "is_file": False, "title": "Scholomance 2", "existing_genres": [], "existing_narrator": "Andrea Parsneau", "existing_explicit": False},
        ]
        audible_results = {
            "1": {
                "category_ladders": [{"ladder": [{"name": "Fantasy"}]}],
                "narrators": [{"name": "Andrea Parsneau"}],
                "is_adult_product": False,
            },
            "2": {
                "category_ladders": [{"ladder": [{"name": "Erotica"}]}],
                "narrators": [{"name": "Andrea Parsneau"}],
                "is_adult_product": True,
            },
        }
        goodreads_results = {
            "1": [{"_abs_genres": ["Young Adult"]}],
            "2": [{"_abs_genres": ["Fantasy"]}],
        }
        compiled = enrichment.compile_series_enrichment(
            books, audible_results, goodreads_results, self._clean_genres
        )
        self.assertEqual(compiled["genre"], ["Fantasy", "Young Adult", "Erotica"])
        self.assertEqual(compiled["narrator"], "Andrea Parsneau")
        self.assertEqual(compiled["explicit_flagged_count"], 1)
        self.assertEqual(compiled["explicit_total_count"], 2)
        self.assertIn("1 of 2 books", compiled["explicit_evidence_note"])
        self.assertEqual(compiled["books"][0]["flagged_explicit"], False)
        self.assertEqual(compiled["books"][1]["flagged_explicit"], True)
        self.assertEqual(compiled["books"][0]["path"], "/audiobooks/Scholomance")
        self.assertEqual(compiled["books"][0]["is_file"], False)

    def test_missing_audible_and_goodreads_results_do_not_crash(self):
        books = [{"id": "1", "title": "T", "existing_genres": [], "existing_narrator": "", "existing_explicit": False}]
        compiled = enrichment.compile_series_enrichment(books, {}, {}, self._clean_genres)
        self.assertEqual(compiled["genre"], [])
        self.assertEqual(compiled["narrator"], "")
        self.assertEqual(compiled["explicit_flagged_count"], 0)


if __name__ == "__main__":
    unittest.main()
