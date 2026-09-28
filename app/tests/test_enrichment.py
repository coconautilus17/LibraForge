"""Tests for app.enrichment: ABS series discovery and grouping."""
import json
import re
import tempfile
import unittest
from pathlib import Path

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
            {"key": "scholomance", "name": "Scholomance", "book_count": 2, "standalone": False},
            {"key": "dungeon core", "name": "Dungeon Core", "book_count": 1, "standalone": False},
        ])

    def test_query_filters_case_insensitively(self):
        groups = {
            "scholomance": [{"media": {"metadata": {"seriesName": "Scholomance #1"}}}],
            "dungeon core": [{"media": {"metadata": {"seriesName": "Dungeon Core #1"}}}],
        }
        summary = enrichment.list_series_summary(groups, query="scho")
        self.assertEqual(summary, [{"key": "scholomance", "name": "Scholomance", "book_count": 1, "standalone": False}])


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
            "existing_genres": [],
            "existing_tags": ["Fantasy", "LitRPG"],
            "has_audio": True,
            "description": "",
            "series_name": "",
            "existing_narrator": "Andrea Parsneau",
            "existing_explicit": False,
            "sequence": None,
        }])

    def test_existing_genres_come_from_the_genres_field_and_tags_are_separate(self):
        # LibraForge #300: the genres field is what Enrichment Forge overwrites,
        # so it is what "existing genres" must show; tags stay a separate input.
        item = {"id": "1", "path": "/a", "isFile": False,
                "media": {"numAudioFiles": 1, "tags": ["Epic"],
                          "metadata": {"title": "T", "seriesName": "S #1", "genres": ["Fantasy"]}}}
        [book] = enrichment.get_series_books({"s": [item]}, "S", _fake_normalize_series)
        self.assertEqual(book["existing_genres"], ["Fantasy"])
        self.assertEqual(book["existing_tags"], ["Epic"])
        self.assertTrue(book["has_audio"])

    def test_ebook_only_item_has_no_audio(self):
        item = {"id": "2", "path": "/b", "isFile": False,
                "media": {"numAudioFiles": 0, "tags": [],
                          "metadata": {"title": "Missing X Books", "seriesName": "S #0"}}}
        [book] = enrichment.get_series_books({"s": [item]}, "S", _fake_normalize_series)
        self.assertFalse(book["has_audio"])

    def test_captures_sequence_from_series_name(self):
        groups = {
            "scholomance": [
                {
                    "id": "item-1",
                    "path": "/audiobooks/Scholomance 2",
                    "isFile": False,
                    "media": {
                        "metadata": {
                            "title": "Scholomance 2",
                            "seriesName": "Scholomance #2",
                        },
                        "tags": [],
                    },
                }
            ]
        }
        books = enrichment.get_series_books(groups, "Scholomance", _fake_normalize_series)
        self.assertEqual(books[0]["sequence"], "2")

    def test_orders_books_by_sequence_number_ascending(self):
        groups = {
            "scholomance": [
                {"id": "item-4", "path": "/x/4", "isFile": False, "media": {"metadata": {"title": "Scholomance 4", "seriesName": "Scholomance #4"}, "tags": []}},
                {"id": "item-1", "path": "/x/1", "isFile": False, "media": {"metadata": {"title": "Scholomance", "seriesName": "Scholomance #1"}, "tags": []}},
                {"id": "item-2", "path": "/x/2", "isFile": False, "media": {"metadata": {"title": "Scholomance 2", "seriesName": "Scholomance #2"}, "tags": []}},
            ]
        }
        books = enrichment.get_series_books(groups, "Scholomance", _fake_normalize_series)
        self.assertEqual([b["id"] for b in books], ["item-1", "item-2", "item-4"])

    def test_books_without_a_sequence_sort_after_numbered_ones(self):
        groups = {
            "scholomance": [
                {"id": "no-seq", "path": "/x/n", "isFile": False, "media": {"metadata": {"title": "Scholomance Extra", "seriesName": "Scholomance"}, "tags": []}},
                {"id": "item-2", "path": "/x/2", "isFile": False, "media": {"metadata": {"title": "Scholomance 2", "seriesName": "Scholomance #2"}, "tags": []}},
                {"id": "item-1", "path": "/x/1", "isFile": False, "media": {"metadata": {"title": "Scholomance", "seriesName": "Scholomance #1"}, "tags": []}},
            ]
        }
        books = enrichment.get_series_books(groups, "Scholomance", _fake_normalize_series)
        self.assertEqual([b["id"] for b in books], ["item-1", "item-2", "no-seq"])

    def test_unknown_series_returns_empty(self):
        books = enrichment.get_series_books({}, "Nonexistent", _fake_normalize_series)
        self.assertEqual(books, [])


class ExtractSeriesSequenceTests(unittest.TestCase):
    def test_extracts_integer_sequence(self):
        self.assertEqual(enrichment.extract_series_sequence("Scholomance #4"), "4")

    def test_extracts_decimal_sequence(self):
        self.assertEqual(enrichment.extract_series_sequence("Scholomance #4.5"), "4.5")

    def test_no_suffix_returns_none(self):
        self.assertIsNone(enrichment.extract_series_sequence("Scholomance"))

    def test_blank_returns_none(self):
        self.assertIsNone(enrichment.extract_series_sequence(""))


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
    """Direct Goodreads shelves (app/goodreads_shelves.py), one result per book."""

    def test_fetches_every_audio_book_with_first_author_and_shares_the_pacer(self):
        books = [{"id": "1", "title": "Cradle - Book 001 - Unsouled", "author": "Will Wight, Someone Else"},
                 {"id": "2", "title": "T2", "author": "A2"},
                 {"id": "3", "title": "Missing Books", "author": "A3", "has_audio": False}]
        calls = []
        pacer = object()

        def fetch(title, author, *, pacer):
            calls.append((title, author, pacer))
            return {"status": "found", "title": title, "shelves": [("fantasy", 5)]}

        result = enrichment.search_series_goodreads(books, fetch, pacer)
        self.assertEqual(sorted(c[:2] for c in calls), [("Cradle - Book 001 - Unsouled", "Will Wight"), ("T2", "A2")])
        self.assertTrue(all(c[2] is pacer for c in calls))
        self.assertEqual(result["1"]["status"], "found")
        self.assertEqual(result["3"]["status"], "skipped")

    def test_an_exception_is_a_failed_result_not_a_crash(self):
        def fetch(title, author, *, pacer):
            raise RuntimeError("boom")

        result = enrichment.search_series_goodreads([{"id": "1", "title": "T", "author": "A"}], fetch, None)
        self.assertEqual(result["1"]["status"], "failed")


class SearchSeriesAbsTests(unittest.TestCase):
    def test_uses_existing_abs_search_function_for_every_book(self):
        books = [{"id": "1", "title": "T1", "author": "A1"}, {"id": "2", "title": "T2", "author": "A2"}]
        calls = []

        def abs_search(**kwargs):
            calls.append((kwargs["title"], kwargs["provider"]))
            return {"results": [{"title": kwargs["title"], "genre": "Fantasy"}]}

        result = enrichment.search_series_abs(books, abs_search, provider="audible")
        self.assertCountEqual(calls, [("T1", "audible"), ("T2", "audible")])
        self.assertEqual(result["1"]["genre"], "Fantasy")
        self.assertEqual(result["2"]["title"], "T2")

    def test_abs_failure_yields_none_not_exception(self):
        books = [{"id": "1", "title": "T", "author": "A"}]

        def abs_search(**kwargs):
            raise RuntimeError("abs unavailable")

        result = enrichment.search_series_abs(books, abs_search)
        self.assertEqual(result, {"1": None})


class AudibleCategoryLadderGenresTests(unittest.TestCase):
    def test_keeps_every_level_below_the_root_deduped(self):
        # LibraForge #302: the leaf alone loses the parent genre ("Space Opera"
        # without "Science Fiction") and the children's/teen audience.
        product = {"category_ladders": [
            {"ladder": [{"name": "Science Fiction & Fantasy"}, {"name": "Science Fiction"}, {"name": "Space Opera"}]},
            {"ladder": [{"name": "Science Fiction & Fantasy"}, {"name": "Science Fiction"}, {"name": "Military"}]},
            {"ladder": [{"name": "Children's Audiobooks"}, {"name": "Literature & Fiction"}, {"name": "Fantasy & Magic"}]},
            {"ladder": [{"name": "Literature & Fiction"}, {"name": "Genre Fiction"}, {"name": "Coming of Age"}]},
        ]}
        self.assertEqual(enrichment.audible_category_ladder_genres(product),
                         ["Science Fiction", "Space Opera", "Military", "Children's Audiobooks", "Fantasy & Magic", "Coming of Age"])

    def test_single_node_ladder_keeps_its_node(self):
        product = {"category_ladders": [{"ladder": [{"name": "Fantasy"}]}]}
        self.assertEqual(enrichment.audible_category_ladder_genres(product), ["Fantasy"])

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
            "1": {"status": "found", "shelves": [("fantasy", 100), ("young-adult", 40)]},
            "2": {"status": "found", "shelves": [("fantasy", 10), ("erotica", 4)]},
        }
        compiled = enrichment.compile_series_enrichment(
            books, audible_results, goodreads_results, self._clean_genres
        )
        self.assertEqual(compiled["genre_union"], ["Fantasy", "Young Adult", "Erotica"])
        self.assertEqual(compiled["books"][1]["goodreads_explicit"]["votes"], 4)
        self.assertEqual(compiled["books"][0]["goodreads_explicit"]["votes"], 0)
        self.assertEqual(compiled["narrator"], "Andrea Parsneau")
        self.assertEqual(compiled["explicit_flagged_count"], 1)
        self.assertEqual(compiled["explicit_total_count"], 2)
        self.assertIn("1 of 2 books", compiled["explicit_evidence_note"])
        self.assertEqual(compiled["books"][0]["flagged_explicit"], False)
        self.assertEqual(compiled["books"][1]["flagged_explicit"], True)
        self.assertEqual(compiled["books"][0]["path"], "/audiobooks/Scholomance")
        self.assertEqual(compiled["books"][0]["is_file"], False)
        self.assertEqual(compiled["books"][0]["existing_genres"], ["Fantasy"])

    def test_evidence_note_counts_significant_goodreads_explicit_shelving(self):
        books = [{"id": "1", "title": "A", "existing_genres": [], "existing_narrator": "", "existing_explicit": False},
                 {"id": "2", "title": "B", "existing_genres": [], "existing_narrator": "", "existing_explicit": False}]
        gr = {"1": {"status": "found", "shelves": [("fantasy", 27), ("erotica", 4), ("nsfw", 2)]},
              "2": {"status": "found", "shelves": [("sci-fi", 24246), ("adult-fiction", 261)]}}
        compiled = enrichment.compile_series_enrichment(books, {}, gr, self._clean_genres)
        self.assertIn("1 of 2 books", compiled["explicit_evidence_note"])
        self.assertIn("Goodreads", compiled["explicit_evidence_note"])
        self.assertEqual(compiled["explicit_goodreads_count"], 1)

    def test_not_found_or_failed_goodreads_results_add_no_genres(self):
        books = [{"id": "1", "title": "T", "existing_genres": [], "existing_narrator": "", "existing_explicit": False}]
        compiled = enrichment.compile_series_enrichment(
            books, {}, {"1": {"status": "failed", "shelves": [("horror", 99)]}}, self._clean_genres)
        self.assertEqual(compiled["genre"], [])
        self.assertIsNone(compiled["books"][0]["goodreads_explicit"])

    def test_missing_audible_and_goodreads_results_do_not_crash(self):
        books = [{"id": "1", "title": "T", "existing_genres": [], "existing_narrator": "", "existing_explicit": False}]
        compiled = enrichment.compile_series_enrichment(books, {}, {}, self._clean_genres)
        self.assertEqual(compiled["genre"], [])
        self.assertEqual(compiled["narrator"], "")
        self.assertEqual(compiled["explicit_flagged_count"], 0)

    def test_abs_results_feed_genres_and_narrators_when_audible_missing(self):
        books = [{"id": "1", "title": "T", "existing_genres": ["Local Fantasy"], "existing_narrator": "", "existing_explicit": False}]
        abs_results = {"1": {"genre": "Fantasy, Adventure", "narrators": ["ABS Narrator"]}}
        compiled = enrichment.compile_series_enrichment(
            books, {}, {}, self._clean_genres, abs_results=abs_results
        )
        self.assertEqual(compiled["genre_union"], ["Fantasy", "Adventure", "Local Fantasy"])
        self.assertEqual(compiled["narrator"], "ABS Narrator")
        self.assertEqual(compiled["books"][0]["audible_genres"], ["Fantasy", "Adventure"])
        self.assertEqual(compiled["books"][0]["existing_genres"], ["Local Fantasy"])

    def test_existing_genres_used_when_audible_and_goodreads_empty(self):
        books = [
            {"id": "1", "title": "Dashing Devil", "existing_genres": ["Romance", "Fantasy"], "existing_narrator": "", "existing_explicit": False},
        ]
        compiled = enrichment.compile_series_enrichment(books, {}, {}, self._clean_genres)
        self.assertEqual(compiled["genre_union"], ["Romance", "Fantasy"])
        self.assertEqual(compiled["books"][0]["audible_genres"], [])

    def test_tags_still_feed_the_union_and_are_returned_separately(self):
        books = [{"id": "1", "title": "T", "existing_genres": ["Fantasy"], "existing_tags": ["Epic"],
                  "existing_narrator": "", "existing_explicit": False}]
        compiled = enrichment.compile_series_enrichment(books, {}, {}, self._clean_genres)
        self.assertEqual(compiled["genre_union"], ["Fantasy", "Epic"])
        self.assertEqual(compiled["books"][0]["existing_tags"], ["Epic"])
        self.assertEqual(compiled["books"][0]["existing_genres"], ["Fantasy"])

    def test_existing_genres_are_unioned_in_even_when_audible_found_some(self):
        # Local genres are part of the full genre equation, not a
        # last-resort fallback gated on every other source coming up empty --
        # a book can have accurate local tags Audible/Goodreads simply don't
        # carry (or vice versa), so all three sources always contribute.
        books = [
            {"id": "1", "title": "T", "existing_genres": ["Local Only"], "existing_narrator": "", "existing_explicit": False},
        ]
        audible_results = {"1": {"category_ladders": [{"ladder": [{"name": "Fantasy"}]}]}}
        compiled = enrichment.compile_series_enrichment(books, audible_results, {}, self._clean_genres)
        self.assertEqual(compiled["genre_union"], ["Fantasy", "Local Only"])

    def test_sequence_range_spans_min_to_max(self):
        books = [
            {"id": "1", "title": "T1", "existing_genres": [], "existing_narrator": "", "existing_explicit": False, "sequence": "1"},
            {"id": "2", "title": "T2", "existing_genres": [], "existing_narrator": "", "existing_explicit": False, "sequence": "4"},
            {"id": "3", "title": "T3", "existing_genres": [], "existing_narrator": "", "existing_explicit": False, "sequence": "2"},
        ]
        compiled = enrichment.compile_series_enrichment(books, {}, {}, self._clean_genres)
        self.assertEqual(compiled["sequence_range"], "1 to 4")

    def test_sequence_range_single_value_when_all_match(self):
        books = [
            {"id": "1", "title": "T1", "existing_genres": [], "existing_narrator": "", "existing_explicit": False, "sequence": "1"},
        ]
        compiled = enrichment.compile_series_enrichment(books, {}, {}, self._clean_genres)
        self.assertEqual(compiled["sequence_range"], "1")

    def test_sequence_range_blank_when_no_sequences_found(self):
        books = [{"id": "1", "title": "T", "existing_genres": [], "existing_narrator": "", "existing_explicit": False}]
        compiled = enrichment.compile_series_enrichment(books, {}, {}, self._clean_genres)
        self.assertEqual(compiled["sequence_range"], "")

    def test_sequence_range_ignores_missing_sequences_among_present_ones(self):
        books = [
            {"id": "1", "title": "T1", "existing_genres": [], "existing_narrator": "", "existing_explicit": False, "sequence": "1"},
            {"id": "2", "title": "T2", "existing_genres": [], "existing_narrator": "", "existing_explicit": False, "sequence": None},
            {"id": "3", "title": "T3", "existing_genres": [], "existing_narrator": "", "existing_explicit": False, "sequence": "3"},
        ]
        compiled = enrichment.compile_series_enrichment(books, {}, {}, self._clean_genres)
        self.assertEqual(compiled["sequence_range"], "1 to 3")

    def test_sequence_range_formats_whole_number_decimals_without_trailing_zero(self):
        books = [
            {"id": "1", "title": "T1", "existing_genres": [], "existing_narrator": "", "existing_explicit": False, "sequence": "1.0"},
            {"id": "2", "title": "T2", "existing_genres": [], "existing_narrator": "", "existing_explicit": False, "sequence": "4.5"},
        ]
        compiled = enrichment.compile_series_enrichment(books, {}, {}, self._clean_genres)
        self.assertEqual(compiled["sequence_range"], "1 to 4.5")


class ResolveMetadataJsonPathTests(unittest.TestCase):
    def test_folder_item(self):
        result = enrichment.resolve_metadata_json_path("/audiobooks/Author/Book", is_file=False)
        self.assertEqual(str(result), "/audiobooks/Author/Book/metadata.json")

    def test_loose_file_item(self):
        result = enrichment.resolve_metadata_json_path("/audiobooks/Author/Book/Book.m4b", is_file=True)
        self.assertEqual(str(result), "/audiobooks/Author/Book/Book.m4b.metadata.json")


class MergeMetadataJsonTests(unittest.TestCase):
    def test_blank_genre_and_narrator_leave_existing_untouched(self):
        existing = {"genres": ["Fantasy"], "narrators": ["Andrea Parsneau"], "explicit": False}
        merged = enrichment.merge_metadata_json(existing, genre=[], narrator="", explicit_checked=False)
        self.assertEqual(merged, existing)

    def test_non_blank_genre_overwrites_existing(self):
        existing = {"genres": ["Fantasy"]}
        merged = enrichment.merge_metadata_json(existing, genre=["Fantasy", "LitRPG"], narrator="", explicit_checked=False)
        self.assertEqual(merged["genres"], ["Fantasy", "LitRPG"])

    def test_narrator_splits_on_comma(self):
        merged = enrichment.merge_metadata_json({}, genre=[], narrator="A, B", explicit_checked=False)
        self.assertEqual(merged["narrators"], ["A", "B"])

    def test_explicit_checked_writes_true(self):
        merged = enrichment.merge_metadata_json({"explicit": False}, genre=[], narrator="", explicit_checked=True)
        self.assertTrue(merged["explicit"])

    def test_explicit_unchecked_never_writes_false_over_existing_true(self):
        merged = enrichment.merge_metadata_json({"explicit": True}, genre=[], narrator="", explicit_checked=False)
        self.assertTrue(merged["explicit"])

    def test_other_existing_fields_preserved(self):
        existing = {"title": "Scholomance", "isbn": "123", "genres": ["Fantasy"]}
        merged = enrichment.merge_metadata_json(existing, genre=["LitRPG"], narrator="", explicit_checked=False)
        self.assertEqual(merged["title"], "Scholomance")
        self.assertEqual(merged["isbn"], "123")


class WriteMetadataJsonPartialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_creates_new_file_when_absent(self):
        path = Path(self.tmp.name) / "book" / "metadata.json"
        result = enrichment.write_metadata_json_partial(path, genre=["Fantasy"], narrator="A", explicit_checked=False)
        self.assertTrue(path.exists())
        self.assertEqual(json.loads(path.read_text()), result)
        self.assertEqual(result["genres"], ["Fantasy"])
        self.assertEqual(result["narrators"], ["A"])

    def test_merges_onto_existing_file(self):
        path = Path(self.tmp.name) / "metadata.json"
        path.write_text(json.dumps({"title": "Scholomance", "genres": ["Fantasy"]}))
        result = enrichment.write_metadata_json_partial(path, genre=["Fantasy", "LitRPG"], narrator="", explicit_checked=False)
        self.assertEqual(result["title"], "Scholomance")
        self.assertEqual(result["genres"], ["Fantasy", "LitRPG"])

    def test_corrupt_existing_file_raises_and_is_left_untouched(self):
        path = Path(self.tmp.name) / "metadata.json"
        original_content = "{not valid json"
        path.write_text(original_content)
        with self.assertRaises(ValueError):
            enrichment.write_metadata_json_partial(path, genre=["Fantasy"], narrator="", explicit_checked=False)
        self.assertEqual(path.read_text(), original_content)


if __name__ == "__main__":
    unittest.main()


class NonAudioItemsTests(unittest.TestCase):
    """LibraForge #301: ebook-only / placeholder items ("Missing Dune Books")
    were searched like audiobooks and their random matches' genres leaked
    into the whole series."""

    BOOK = {"id": "x", "title": "Missing Dune Books", "author": "Frank Herbert", "asin": "", "has_audio": False}

    def test_audible_search_skips_non_audio_books(self):
        calls = []
        out = enrichment.search_series_audible([self.BOOK], lambda *a, **k: calls.append(1) or [{"asin": "B0X"}],
                                               lambda *a, **k: calls.append(1), client=None)
        self.assertEqual(calls, [])
        self.assertIsNone(out["x"])

    def test_abs_search_skips_non_audio_books(self):
        calls = []
        out = enrichment.search_series_abs([self.BOOK], lambda **k: calls.append(1) or {"results": [{}]})
        self.assertEqual(calls, [])
        self.assertIsNone(out["x"])

    def test_non_audio_rows_default_to_excluded_and_add_nothing_to_the_union(self):
        books = [dict(self.BOOK, existing_genres=["Fantasy"], existing_tags=[]),
                 {"id": "y", "title": "Dune", "has_audio": True, "existing_genres": [], "existing_tags": []}]
        audible = {"x": {"category_ladders": [{"ladder": [{"name": "Literature & Fiction"}, {"name": "Literary Fiction"}]}]},
                   "y": {"category_ladders": [{"ladder": [{"name": "Science Fiction & Fantasy"}, {"name": "Science Fiction"}]}]}}
        out = enrichment.compile_series_enrichment(books, audible, {}, lambda g: [x for x in g if x])
        rows = {r["id"]: r for r in out["books"]}
        self.assertFalse(rows["x"]["default_include"])
        self.assertTrue(rows["y"]["default_include"])
        self.assertNotIn("Literary Fiction", out["genre"])
        self.assertNotIn("Fantasy", out["genre"])


def _item(item_id, series, author, title=None):
    return {"id": item_id, "path": "/audiobooks/" + item_id, "isFile": False,
            "media": {"numAudioFiles": 1, "tags": [],
                      "metadata": {"title": title or item_id, "seriesName": series, "authorName": author}}}


class StableSeriesKeyTests(unittest.TestCase):
    """LibraForge #304: a listed series must always be compilable."""

    def test_summary_rows_carry_a_key_that_resolves_even_for_odd_names(self):
        groups = enrichment.group_items_by_series([_item("1", "Life Lines, Book-5 #1 #1", "BBC")], _fake_normalize_series)
        [row] = enrichment.list_series_summary(groups)
        self.assertIn("key", row)
        self.assertEqual(len(enrichment.get_series_books(groups, row["key"], _fake_normalize_series, by_key=True)), 1)

    def test_name_lookup_still_works(self):
        groups = enrichment.group_items_by_series([_item("1", "Dune #1", "Frank Herbert")], _fake_normalize_series)
        self.assertEqual(len(enrichment.get_series_books(groups, "Dune", _fake_normalize_series)), 1)


class SplitGroupByAuthorTests(unittest.TestCase):
    """LibraForge #305: same-named series by different authors were merged."""

    def test_two_authors_with_two_plus_books_each_and_no_shared_credit_split(self):
        groups = enrichment.split_group_by_author([
            _item("n1", "Scholomance #1", "Naomi Novik"), _item("n2", "Scholomance #2", "Naomi Novik"),
            _item("l1", "Scholomance #1", "Logan Jacobs"), _item("l2", "Scholomance #2", "Logan Jacobs")])
        self.assertEqual(sorted(groups), ["Logan Jacobs", "Naomi Novik"])
        self.assertEqual(len(groups["Naomi Novik"]), 2)

    def test_continuation_authors_with_a_shared_credit_do_not_split(self):
        groups = enrichment.split_group_by_author([
            _item("a", "Dune #1", "Brian Herbert, Kevin J. Anderson"), _item("b", "Dune #2", "Brian Herbert, Kevin J. Anderson"),
            _item("c", "Dune #3", "Kevin J. Anderson, Brian Herbert"), _item("d", "Dune #4", "Kevin J. Anderson, Brian Herbert")])
        self.assertEqual(list(groups), [""])

    def test_a_single_stray_book_by_another_author_does_not_split(self):
        groups = enrichment.split_group_by_author([
            _item("a", "HP #1", "J.K. Rowling"), _item("b", "HP #2", "J.K. Rowling"), _item("c", "HP #3", "Eliezer Yudkowsky")])
        self.assertEqual(list(groups), [""])

    def test_role_suffixes_are_ignored(self):
        groups = enrichment.split_group_by_author([
            _item("a", "D #1", "Terry Pratchett"), _item("b", "D #2", "Terry Pratchett"),
            _item("c", "D #3", "Ben Aaranovitch - introduction")])
        self.assertEqual(list(groups), [""])

    def test_summary_lists_split_groups_separately_and_keys_resolve(self):
        items = [_item("n1", "Scholomance #1", "Naomi Novik"), _item("n2", "Scholomance #2", "Naomi Novik"),
                 _item("l1", "Scholomance #1", "Logan Jacobs"), _item("l2", "Scholomance #2", "Logan Jacobs")]
        groups = enrichment.group_items_by_series(items, _fake_normalize_series)
        rows = enrichment.list_series_summary(groups)
        self.assertEqual(sorted(r["name"] for r in rows), ["Scholomance [Logan Jacobs]", "Scholomance [Naomi Novik]"])
        for r in rows:
            books = enrichment.get_series_books(groups, r["key"], _fake_normalize_series, by_key=True)
            self.assertEqual({b["author"] for b in books}, {r["name"].split("[")[1].rstrip("]")})


class StandaloneUnitsTests(unittest.TestCase):
    """Enrichment Forge v2: books with no series are units of their own."""

    def setUp(self):
        placeholder = _item("p1", "", "Nobody", title="Notes")
        placeholder["media"]["numAudioFiles"] = 0
        self.items = [_item("s1", "", "Dean Koontz", title="Intensity"), _item("b1", "Dune #1", "Frank Herbert", title="Dune"), placeholder]
        self.groups = enrichment.group_items_by_series(self.items, _fake_normalize_series)

    def test_standalones_listed_after_series_and_resolvable(self):
        standalones = enrichment.standalone_items(self.items)
        self.assertEqual([it["id"] for it in standalones], ["s1"])  # no-audio items are not units
        rows = enrichment.list_series_summary(self.groups, "", standalones=standalones)
        self.assertEqual([r["standalone"] for r in rows], [False, True])
        self.assertEqual(rows[1]["name"], "Intensity [Dean Koontz]")
        books = enrichment.get_series_books(self.groups, rows[1]["key"], _fake_normalize_series, by_key=True, items=self.items)
        self.assertEqual([b["id"] for b in books], ["s1"])

    def test_query_matches_standalone_title_or_author(self):
        standalones = enrichment.standalone_items(self.items)
        self.assertEqual([r["name"] for r in enrichment.list_series_summary(self.groups, "koontz", standalones=standalones)], ["Intensity [Dean Koontz]"])
        self.assertEqual(len(enrichment.list_series_summary(self.groups, "intens", standalones=standalones)), 1)

    def test_books_carry_description_for_keyword_votes(self):
        self.items[0]["media"]["metadata"]["description"] = "A thriller."
        books = enrichment.get_series_books(self.groups, enrichment.STANDALONE_KEY_PREFIX + "s1", _fake_normalize_series, by_key=True, items=self.items)
        self.assertEqual(books[0]["description"], "A thriller.")


def _vbook(book_id, **kw):
    book = {"id": book_id, "title": f"Book {book_id}", "has_audio": True, "existing_genres": [], "existing_tags": [],
            "description": "", "path": "", "is_file": False}
    book.update(kw)
    return book


_EPIC = {"category_ladders": [{"ladder": [{"name": "Science Fiction & Fantasy"}, {"name": "Fantasy"}, {"name": "Epic"}]}]}
_NO_SERIES = {"labels": [], "evidence": [], "pf_progression": False}


class BuildBookVotersTests(unittest.TestCase):
    def test_each_source_votes_under_its_own_name(self):
        gr = {"status": "found", "shelves": [("fantasy", 1000), ("litrpg", 300)]}
        voters = enrichment.build_book_voters(
            _vbook("b", existing_tags=["Horror"], description="A cultivation saga"),
            {**_EPIC, "publisher_summary": "<p>The LitRPG hit</p>"}, None, gr,
            {"status": "found", "labels": ["fantasy"]}, {"status": "not_found", "labels": []})
        self.assertEqual(set(voters), {"audible", "goodreads", "audiosilo", "abs_existing", "keywords"})
        self.assertIn("litrpg", voters["goodreads"])
        self.assertEqual(sorted(voters["keywords"]), ["cultivation", "litrpg"])
        self.assertEqual(voters["abs_existing"], ["horror"])

    def test_abs_provider_fallback_genre_and_description(self):
        voters = enrichment.build_book_voters(_vbook("b"), None, {"genre": "Thriller, Suspense", "description": "a harem romp"}, {}, None, None)
        self.assertEqual(voters["audible"], ["thriller", "suspense"])
        self.assertEqual(voters["keywords"], ["harem"])

    def test_no_audio_book_has_no_voters(self):
        self.assertEqual(enrichment.build_book_voters(_vbook("p", has_audio=False, existing_tags=["Horror"]), _EPIC, None, {}, None, None), {})


class CompileVotingTests(unittest.TestCase):
    def test_votes_evidence_and_chip_prefill(self):
        books = [_vbook(f"b{i}", description="A LitRPG tale") for i in range(3)]
        audible = {f"b{i}": _EPIC for i in range(3)}
        extra = {"audiosilo": {f"b{i}": {"status": "found", "labels": ["fantasy"]} for i in range(3)}, "openlibrary": {}}
        out = enrichment.compile_series_enrichment(books, audible, {}, lambda g: g, extra_results=extra, series_sources=_NO_SERIES)
        self.assertEqual(out["main_genres"], ["Fantasy", "LitRPG"])
        self.assertEqual(out["genre_evidence"]["Fantasy"]["audible"], 3)
        self.assertEqual(out["genre_evidence"]["LitRPG"], {"keywords": 3})
        self.assertEqual(out["genre"][:2], ["Fantasy", "LitRPG"])
        self.assertIn("Epic Fantasy", out["sub_genres"])
        self.assertIn("keywords", out["books"][0]["sources"])
        self.assertEqual(out["books"][0]["book_main"], ["Fantasy", "LitRPG"])
        self.assertEqual(out["agreement"], "ok")

    def test_series_sources_flow_into_the_vote(self):
        books = [_vbook(f"b{i}") for i in range(4)]
        extra = {"audiosilo": {f"b{i}": {"status": "found", "labels": ["fantasy"]} for i in range(4)}}
        out = enrichment.compile_series_enrichment(books, {f"b{i}": _EPIC for i in range(4)}, {}, lambda g: g, extra_results=extra,
                                                   series_sources={"labels": ["haremlit"], "evidence": ["HaremLit wiki: X"], "pf_progression": False})
        self.assertIn("Harem", out["main_genres"])
        self.assertEqual(out["series_evidence"], ["HaremLit wiki: X"])

    def test_no_agreement_keeps_the_old_union_for_the_chips(self):
        books = [_vbook("p", has_audio=False, existing_genres=["Horror"])]
        out = enrichment.compile_series_enrichment(books, {}, {}, lambda g: g, extra_results={}, series_sources=_NO_SERIES)
        self.assertEqual((out["main_genres"], out["agreement"]), ([], "none"))

    def test_standalone_ignores_series_sources(self):
        out = enrichment.compile_series_enrichment([_vbook("s")], {"s": _EPIC}, {}, lambda g: g, extra_results={},
                                                   series_sources={"labels": ["haremlit"], "evidence": ["x"], "pf_progression": False}, standalone=True)
        self.assertNotIn("Harem", out["main_genres"])


class CompileSuggestionsTests(unittest.TestCase):
    def test_suggestions_are_taxonomy_names_not_raw_labels(self):
        books = [_vbook(f"b{i}") for i in range(5)]
        audible = {f"b{i}": _EPIC for i in range(5)}
        audible["b0"] = {"category_ladders": [{"ladder": [{"name": "Literature & Fiction"}, {"name": "Romance"}, {"name": "Romantic Comedy"}]}]}
        extra = {"audiosilo": {f"b{i}": {"status": "found", "labels": ["fantasy"]} for i in range(5)}}
        out = enrichment.compile_series_enrichment(books, audible, {}, lambda g: g, extra_results=extra, series_sources=_NO_SERIES)
        self.assertIn("Romance", out["genre_suggestions"])
        self.assertNotIn("Literature & Fiction", out["genre_suggestions"])
        self.assertNotIn("Epic", out["genre_suggestions"])
