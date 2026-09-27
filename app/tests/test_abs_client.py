"""Tests for app.abs_client: the direct-ABS-API metadata sync module.

Pure-function tests only for the payload/index/blank-check helpers (no
network mocking needed); sync_book_metadata's three-way branch is exercised
with plain fake lookup/fallback/GET/PATCH callables.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import abs_client


class BuildItemIndexTests(unittest.TestCase):
    def test_indexes_by_asin_and_path_and_rel_path(self):
        items = [
            {
                "id": "li1", "path": "/audiobooks/A/Book", "relPath": "A/Book", "updatedAt": 111,
                "media": {"metadata": {"asin": "b0abc12345", "title": "Book"}},
            },
            {
                "id": "li2", "path": "/audiobooks/Linux/EPUB", "relPath": "Linux/EPUB", "updatedAt": 222,
                "media": {"metadata": {"asin": "", "title": "Efficient Linux"}},
            },
        ]
        index = abs_client.build_item_index(items)
        self.assertIn("B0ABC12345", index["by_asin"])
        self.assertEqual(index["by_asin"]["B0ABC12345"]["library_item_id"], "li1")
        self.assertIn("/audiobooks/Linux/EPUB", index["by_path"])
        self.assertIn("Linux/EPUB", index["by_path"])
        self.assertNotIn("", index["by_asin"])

    def test_item_with_no_asin_is_only_path_indexed(self):
        items = [{"id": "li1", "path": "/x", "relPath": "x", "updatedAt": 1, "media": {"metadata": {}}}]
        index = abs_client.build_item_index(items)
        self.assertEqual(index["by_asin"], {})
        self.assertIn("/x", index["by_path"])

    def test_placeholder_asin_shared_by_several_items_is_never_a_lookup_key(self):
        """LibraForge #291: NOREALASIN and abs-agg-* are sentinel values the
        fixer stores when no real ASIN exists. Many unrelated books share the
        exact same placeholder -- indexing by it caused one book's edit to
        silently PATCH a different, arbitrary book in ABS."""
        items = [
            {"id": f"li{i}", "path": f"/audiobooks/Book{i}", "relPath": f"Book{i}", "updatedAt": i,
             "media": {"metadata": {"asin": "NOREALASIN"}}}
            for i in range(3)
        ] + [
            {"id": f"gc{i}", "path": f"/audiobooks/GC{i}", "relPath": f"GC{i}", "updatedAt": i,
             "media": {"metadata": {"asin": "abs-agg-graphicaudio-0"}}}
            for i in range(2)
        ]
        index = abs_client.build_item_index(items)
        self.assertNotIn("NOREALASIN", index["by_asin"])
        self.assertNotIn("ABS-AGG-GRAPHICAUDIO-0", index["by_asin"])
        # Every item is still reachable by its own unambiguous path.
        for i in range(3):
            self.assertIn(f"/audiobooks/Book{i}", index["by_path"])
        for i in range(2):
            self.assertIn(f"/audiobooks/GC{i}", index["by_path"])

    def test_two_items_sharing_a_real_shaped_asin_are_never_indexable_by_it(self):
        """Never guess among duplicates, even if both ASINs look real (e.g. a
        genuine duplicate edition) -- drop the key entirely and let callers
        fall through to the always-unambiguous path."""
        items = [
            {"id": "li1", "path": "/a", "relPath": "a", "updatedAt": 1,
             "media": {"metadata": {"asin": "B0ABC12345"}}},
            {"id": "li2", "path": "/b", "relPath": "b", "updatedAt": 2,
             "media": {"metadata": {"asin": "b0abc12345"}}},
        ]
        index = abs_client.build_item_index(items)
        self.assertNotIn("B0ABC12345", index["by_asin"])
        self.assertIn("/a", index["by_path"])
        self.assertIn("/b", index["by_path"])


class LookupItemInIndexTests(unittest.TestCase):
    def setUp(self):
        self.index = abs_client.build_item_index([
            {"id": "li1", "path": "/p", "relPath": "p", "updatedAt": 1,
             "media": {"metadata": {"asin": "B0ABC12345"}}},
        ])

    def test_path_beats_asin_when_both_match_different_items(self):
        """The caller always knows the book's own current folder -- that must
        win even when a (real, unique) ASIN match points somewhere else, e.g.
        because a book was copied/duplicated. Never let ASIN override an
        exact path hit (LibraForge #291)."""
        other_item_index = abs_client.build_item_index([
            {"id": "li1", "path": "/p", "relPath": "p", "updatedAt": 1,
             "media": {"metadata": {"asin": "B0ABC12345"}}},
            {"id": "li2", "path": "/somewhere/else", "relPath": "somewhere/else", "updatedAt": 2,
             "media": {"metadata": {}}},
        ])
        record = abs_client.lookup_item_in_index(other_item_index, asin="b0abc12345", path="/somewhere/else")
        self.assertEqual(record["library_item_id"], "li2")

    def test_falls_back_to_asin_when_path_misses(self):
        record = abs_client.lookup_item_in_index(self.index, asin="b0abc12345", path="/moved/elsewhere")
        self.assertEqual(record["library_item_id"], "li1")

    def test_falls_back_to_path_when_no_asin(self):
        record = abs_client.lookup_item_in_index(self.index, asin="", path="/p")
        self.assertEqual(record["library_item_id"], "li1")

    def test_falls_back_to_rel_path(self):
        record = abs_client.lookup_item_in_index(self.index, asin="", rel_path="p")
        self.assertEqual(record["library_item_id"], "li1")

    def test_miss_returns_none(self):
        self.assertIsNone(abs_client.lookup_item_in_index(self.index, asin="NOPE", path="/nope"))


class IsRealAsinTests(unittest.TestCase):
    def test_real_shaped_asin_is_accepted(self):
        self.assertTrue(abs_client._is_real_asin("B0ABC12345"))

    def test_norealasin_placeholder_is_rejected(self):
        self.assertFalse(abs_client._is_real_asin("NOREALASIN"))

    def test_abs_agg_placeholder_is_rejected(self):
        self.assertFalse(abs_client._is_real_asin("ABS-AGG-GRAPHICAUDIO-0"))

    def test_blank_is_rejected(self):
        self.assertFalse(abs_client._is_real_asin(""))


class BuildMediaPatchPayloadTests(unittest.TestCase):
    def test_splits_authors_and_narrators_into_lists(self):
        payload = abs_client.build_media_patch_payload({
            "title": "T", "author": "A. Author, B. Author", "narrator": "N. Narrator",
            "series": "", "sequence": "", "genre": "", "year": "", "summary": "",
        })
        self.assertEqual(payload["metadata"]["authors"], [{"name": "A. Author"}, {"name": "B. Author"}])
        self.assertEqual(payload["metadata"]["narrators"], ["N. Narrator"])

    def test_blank_series_produces_empty_list_not_a_blank_entry(self):
        payload = abs_client.build_media_patch_payload({"title": "T", "series": "", "sequence": ""})
        self.assertEqual(payload["metadata"]["series"], [])

    def test_series_and_sequence_become_one_entry(self):
        payload = abs_client.build_media_patch_payload({"title": "T", "series": "Blight", "sequence": "1"})
        self.assertEqual(payload["metadata"]["series"], [{"name": "Blight", "sequence": "1"}])

    def test_genre_is_split_via_split_genre_string(self):
        payload = abs_client.build_media_patch_payload({"title": "T", "genre": "Fantasy, LitRPG"})
        self.assertEqual(payload["metadata"]["genres"], ["Fantasy", "LitRPG"])

    def test_explicit_only_included_when_present_in_metadata(self):
        payload = abs_client.build_media_patch_payload({"title": "T"})
        self.assertNotIn("explicit", payload["metadata"])
        payload = abs_client.build_media_patch_payload({"title": "T", "explicit": False})
        self.assertIs(payload["metadata"]["explicit"], False)

    def test_tags_included_only_when_passed(self):
        payload = abs_client.build_media_patch_payload({"title": "T"})
        self.assertNotIn("tags", payload)
        payload = abs_client.build_media_patch_payload({"title": "T"}, tags=["a"])
        self.assertEqual(payload["tags"], ["a"])


class NormalizeAbsMediaToInternalTests(unittest.TestCase):
    def test_round_trips_series_and_sequence_suffix(self):
        internal = abs_client.normalize_abs_media_to_internal(
            {"metadata": {"title": "T", "seriesName": "Blight #4"}}
        )
        self.assertEqual(internal["series"], "Blight")
        self.assertEqual(internal["sequence"], "4")

    def test_blank_series_name_yields_blank_series_and_sequence(self):
        internal = abs_client.normalize_abs_media_to_internal({"metadata": {"title": "T", "seriesName": ""}})
        self.assertEqual(internal["series"], "")
        self.assertEqual(internal["sequence"], "")

    def test_book_n_wording_is_cleaned_even_without_abs_hash_suffix(self):
        """A human typing the series field directly into Audiobookshelf isn't
        guaranteed to use ABS's own "#N" shorthand -- "Blight, Book 4" needs
        the same Pattern-A cleanup every audiobook provider already shares."""
        internal = abs_client.normalize_abs_media_to_internal(
            {"metadata": {"title": "T", "seriesName": "Blight, Book 4"}}
        )
        self.assertEqual(internal["series"], "Blight")
        self.assertEqual(internal["sequence"], "4")

    def test_splits_flattened_author_and_narrator_names(self):
        internal = abs_client.normalize_abs_media_to_internal(
            {"metadata": {"authorName": "A, B", "narratorName": "N"}}
        )
        self.assertEqual(internal["author"], "A, B")
        self.assertEqual(internal["narrator"], "N")

    def test_genres_list_joined_to_comma_string(self):
        internal = abs_client.normalize_abs_media_to_internal({"metadata": {"genres": ["Fantasy", "LitRPG"]}})
        self.assertEqual(internal["genre"], "Fantasy, LitRPG")


class MergeSeriesEntriesTests(unittest.TestCase):
    def test_replaces_matching_entry_case_insensitively_keeps_others(self):
        current = [{"name": "blight", "sequence": "0"}, {"name": "Other Series", "sequence": "2"}]
        merged = abs_client.merge_series_entries(current, "Blight", "1")
        self.assertIn({"name": "Blight", "sequence": "1"}, merged)
        self.assertIn({"name": "Other Series", "sequence": "2"}, merged)
        self.assertEqual(len(merged), 2)

    def test_appends_when_no_existing_entry_matches(self):
        merged = abs_client.merge_series_entries([{"name": "Other Series", "sequence": "2"}], "Blight", "1")
        self.assertIn({"name": "Blight", "sequence": "1"}, merged)
        self.assertIn({"name": "Other Series", "sequence": "2"}, merged)

    def test_blank_series_name_leaves_current_list_untouched(self):
        current = [{"name": "Other Series", "sequence": "2"}]
        merged = abs_client.merge_series_entries(current, "", "")
        self.assertEqual(merged, current)


class ComputeSelectivePatchFieldsTests(unittest.TestCase):
    def test_fill_missing_only_includes_currently_blank_abs_fields(self):
        current_media = {"metadata": {"title": "Existing Title", "description": ""}}
        new_payload = {"title": "New Title", "description": "New description"}
        fields = abs_client.compute_selective_patch_fields(current_media, new_payload, fill_missing=True)
        self.assertNotIn("title", fields)
        self.assertEqual(fields["description"], "New description")

    def test_fill_missing_series_fraction_special_case(self):
        current_media = {"metadata": {"series": [{"name": "Blight", "sequence": "1/1"}]}}
        new_payload = {"series": [{"name": "Blight", "sequence": "1"}]}
        fields = abs_client.compute_selective_patch_fields(current_media, new_payload, fill_missing=True)
        self.assertEqual(fields["series"], [{"name": "Blight", "sequence": "1"}])

    def test_fill_missing_keeps_old_series_when_new_is_not_clean_numeric(self):
        current_media = {"metadata": {"series": [{"name": "Blight", "sequence": "1/1"}]}}
        new_payload = {"series": [{"name": "Blight", "sequence": "one"}]}
        fields = abs_client.compute_selective_patch_fields(current_media, new_payload, fill_missing=True)
        self.assertNotIn("series", fields)

    def test_skip_blank_fields_drops_blank_new_values(self):
        current_media = {"metadata": {"title": "Existing Title"}}
        new_payload = {"title": "", "description": "New description"}
        fields = abs_client.compute_selective_patch_fields(current_media, new_payload, skip_blank_fields=True)
        self.assertNotIn("title", fields)
        self.assertEqual(fields["description"], "New description")

    def test_neither_flag_returns_everything_verbatim(self):
        new_payload = {"title": "New Title", "description": ""}
        fields = abs_client.compute_selective_patch_fields({"metadata": {}}, new_payload)
        self.assertEqual(fields, new_payload)

    def test_both_flags_raises(self):
        with self.assertRaises(AssertionError):
            abs_client.compute_selective_patch_fields({"metadata": {}}, {}, fill_missing=True, skip_blank_fields=True)


class SyncBookMetadataTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {
            "title": "T", "author": "A", "narrator": "N", "series": "Blight", "sequence": "1",
            "genre": "", "year": "", "summary": "", "isbn": "", "asin": "ASIN1", "language": "",
        }
        self.fallback_calls = []

    def _fallback(self):
        self.fallback_calls.append(True)

    def test_no_api_key_calls_fallback_and_never_looks_up(self):
        result = abs_client.sync_book_metadata(
            metadata=self.metadata, abs_url="http://x", abs_api_key="",
            lookup_item=lambda a, p: (_ for _ in ()).throw(AssertionError("should not be called")),
            write_file_fallback=self._fallback,
        )
        self.assertEqual(result["branch"], "file")
        self.assertEqual(result["reason"], "no_api_key")
        self.assertEqual(len(self.fallback_calls), 1)

    def test_lookup_miss_calls_fallback(self):
        result = abs_client.sync_book_metadata(
            metadata=self.metadata, abs_url="http://x", abs_api_key="key",
            lookup_item=lambda a, p: None, write_file_fallback=self._fallback,
        )
        self.assertEqual(result["branch"], "file")
        self.assertEqual(result["reason"], "unknown_to_abs")
        self.assertEqual(len(self.fallback_calls), 1)

    def test_lookup_hit_patches_and_never_calls_fallback(self):
        record = {
            "library_item_id": "li1", "path": "/x", "rel_path": "x", "updated_at": 100,
            "media": {"metadata": {"series": []}},
        }
        sync_calls = []
        with patch.object(abs_client, "abs_get_json", return_value={"media": {"metadata": {"series": []}}}), \
             patch.object(abs_client, "abs_patch_json") as patch_mock:
            result = abs_client.sync_book_metadata(
                metadata=self.metadata, abs_url="http://x", abs_api_key="key",
                lookup_item=lambda a, p: record, write_file_fallback=self._fallback,
                record_sync=lambda payload: sync_calls.append(payload),
            )
        self.assertEqual(result["branch"], "patch")
        self.assertEqual(len(self.fallback_calls), 0)
        patch_mock.assert_called_once()
        self.assertEqual(patch_mock.call_args[0][0], "/api/items/li1/media")
        self.assertEqual(sync_calls, [{"library_item_id": "li1", "abs_updated_at": 100}])

    def test_series_in_result_triggers_live_get_and_preserves_other_series(self):
        record = {
            "library_item_id": "li1", "path": "/x", "rel_path": "x", "updated_at": 100,
            "media": {"metadata": {}},
        }
        with patch.object(
            abs_client, "abs_get_json",
            return_value={"media": {"metadata": {"series": [{"name": "Other Series", "sequence": "2"}]}}},
        ) as get_mock, patch.object(abs_client, "abs_patch_json") as patch_mock:
            abs_client.sync_book_metadata(
                metadata=self.metadata, abs_url="http://x", abs_api_key="key",
                lookup_item=lambda a, p: record, write_file_fallback=self._fallback,
            )
        get_mock.assert_called_once()
        sent_series = patch_mock.call_args[0][1]["metadata"]["series"]
        self.assertIn({"name": "Blight", "sequence": "1"}, sent_series)
        self.assertIn({"name": "Other Series", "sequence": "2"}, sent_series)

    def test_never_combines_fill_missing_and_skip_blank_fields(self):
        with self.assertRaises(AssertionError):
            abs_client.sync_book_metadata(
                metadata=self.metadata, abs_url="http://x", abs_api_key="key",
                fill_missing=True, skip_blank_fields=True,
                lookup_item=lambda a, p: None, write_file_fallback=self._fallback,
            )

    def test_lookup_miss_calls_record_bootstrap(self):
        calls = []
        abs_client.sync_book_metadata(
            metadata=self.metadata, abs_url="http://x", abs_api_key="key",
            lookup_item=lambda a, p: None, write_file_fallback=self._fallback,
            record_bootstrap=lambda: calls.append(True),
        )
        self.assertEqual(len(calls), 1)

    def test_no_api_key_never_calls_record_bootstrap(self):
        calls = []
        abs_client.sync_book_metadata(
            metadata=self.metadata, abs_url="http://x", abs_api_key="",
            lookup_item=lambda a, p: (_ for _ in ()).throw(AssertionError("should not be called")),
            write_file_fallback=self._fallback,
            record_bootstrap=lambda: calls.append(True),
        )
        self.assertEqual(calls, [])

    def test_resolved_item_path_mismatch_refuses_patch_and_falls_back(self):
        """Last-line defense (LibraForge #291): if the lookup ever resolves to
        an item other than the one the caller is actually editing, refuse the
        PATCH rather than silently overwriting the wrong book."""
        record = {
            "library_item_id": "li1", "path": "/some/other/book", "rel_path": "some/other/book",
            "updated_at": 100, "media": {"metadata": {"series": []}},
        }
        with patch.object(abs_client, "abs_patch_json") as patch_mock:
            result = abs_client.sync_book_metadata(
                metadata=self.metadata, expected_path="/the/actual/book",
                abs_url="http://x", abs_api_key="key",
                lookup_item=lambda a, p: record, write_file_fallback=self._fallback,
            )
        self.assertEqual(result["branch"], "file")
        self.assertEqual(result["reason"], "path_mismatch")
        self.assertEqual(len(self.fallback_calls), 1)
        patch_mock.assert_not_called()

    def test_resolved_item_matching_rel_path_is_not_a_mismatch(self):
        record = {
            "library_item_id": "li1", "path": "/x", "rel_path": "the/actual/book",
            "updated_at": 100, "media": {"metadata": {"series": []}},
        }
        with patch.object(abs_client, "abs_get_json", return_value={"media": {"metadata": {"series": []}}}), \
             patch.object(abs_client, "abs_patch_json") as patch_mock:
            result = abs_client.sync_book_metadata(
                metadata=self.metadata, expected_path="the/actual/book",
                abs_url="http://x", abs_api_key="key",
                lookup_item=lambda a, p: record, write_file_fallback=self._fallback,
            )
        self.assertEqual(result["branch"], "patch")
        self.assertEqual(len(self.fallback_calls), 0)
        patch_mock.assert_called_once()

    def test_lookup_hit_never_calls_record_bootstrap(self):
        record = {"library_item_id": "li1", "path": "/x", "rel_path": "x", "updated_at": 100, "media": {"metadata": {"series": []}}}
        calls = []
        with patch.object(abs_client, "abs_get_json", return_value={"media": {"metadata": {"series": []}}}), \
             patch.object(abs_client, "abs_patch_json"):
            abs_client.sync_book_metadata(
                metadata=self.metadata, abs_url="http://x", abs_api_key="key",
                lookup_item=lambda a, p: record, write_file_fallback=self._fallback,
                record_bootstrap=lambda: calls.append(True),
            )
        self.assertEqual(calls, [])


class BootstrapRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reports_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_then_load_round_trips(self):
        abs_client.upsert_bootstrapped_file(self.reports_dir, Path("/lib/book/metadata.json"), "ASIN1", "/lib/book")
        registry = abs_client.load_bootstrap_registry(self.reports_dir)
        self.assertEqual(registry["/lib/book/metadata.json"], {"asin": "ASIN1", "path": "/lib/book"})

    def test_upsert_same_file_refreshes_not_duplicates(self):
        abs_client.upsert_bootstrapped_file(self.reports_dir, Path("/lib/book/metadata.json"), "ASIN1", "/lib/book")
        abs_client.upsert_bootstrapped_file(self.reports_dir, Path("/lib/book/metadata.json"), "ASIN2", "/lib/book")
        registry = abs_client.load_bootstrap_registry(self.reports_dir)
        self.assertEqual(len(registry), 1)
        self.assertEqual(registry["/lib/book/metadata.json"]["asin"], "ASIN2")

    def test_load_missing_registry_returns_empty_dict(self):
        self.assertEqual(abs_client.load_bootstrap_registry(self.reports_dir), {})

    def test_remove_bootstrapped_file_drops_entry(self):
        abs_client.upsert_bootstrapped_file(self.reports_dir, Path("/lib/book/metadata.json"), "ASIN1", "/lib/book")
        abs_client.remove_bootstrapped_file(self.reports_dir, Path("/lib/book/metadata.json"))
        self.assertEqual(abs_client.load_bootstrap_registry(self.reports_dir), {})

    def test_remove_nonexistent_entry_is_a_no_op(self):
        abs_client.remove_bootstrapped_file(self.reports_dir, Path("/lib/book/metadata.json"))
        self.assertEqual(abs_client.load_bootstrap_registry(self.reports_dir), {})


class MetadataJsonTitleMatchesAbsMediaTests(unittest.TestCase):
    def test_matching_titles_case_insensitive(self):
        self.assertTrue(abs_client.metadata_json_title_matches_abs_media(
            {"title": "The Book"}, {"metadata": {"title": "the book"}}
        ))

    def test_mismatched_titles(self):
        self.assertFalse(abs_client.metadata_json_title_matches_abs_media(
            {"title": "The Book"}, {"metadata": {"title": "A Different Book"}}
        ))

    def test_blank_file_title_never_matches(self):
        self.assertFalse(abs_client.metadata_json_title_matches_abs_media(
            {"title": ""}, {"metadata": {"title": ""}}
        ))


class ReconcileBootstrapRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reports_dir = Path(self.tmp.name)
        self.book_dir = self.reports_dir / "book"
        self.book_dir.mkdir()
        self.metadata_json = self.book_dir / "metadata.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_metadata_json(self, title: str):
        import json
        self.metadata_json.write_text(json.dumps({"title": title}), encoding="utf-8")

    def test_empty_registry_is_a_cheap_no_op(self):
        result = abs_client.reconcile_bootstrap_registry(
            self.reports_dir, abs_url="http://x", abs_api_key="key",
            fetch_items=lambda: (_ for _ in ()).throw(AssertionError("should not fetch when registry is empty")),
        )
        self.assertEqual(result, {"checked": 0, "reconciled": 0, "skipped_mismatch": 0})

    def test_lookup_hit_with_matching_title_deletes_file_and_registry_entry(self):
        self._write_metadata_json("The Book")
        abs_client.upsert_bootstrapped_file(self.reports_dir, self.metadata_json, "ASIN1", str(self.book_dir))
        items = [{
            "id": "li1", "path": str(self.book_dir), "relPath": "book", "updatedAt": 100,
            "media": {"metadata": {"asin": "ASIN1", "title": "The Book"}},
        }]
        result = abs_client.reconcile_bootstrap_registry(
            self.reports_dir, abs_url="http://x", abs_api_key="key", fetch_items=lambda: items,
        )
        self.assertEqual(result["reconciled"], 1)
        self.assertFalse(self.metadata_json.exists())
        self.assertEqual(abs_client.load_bootstrap_registry(self.reports_dir), {})

    def test_lookup_hit_with_mismatched_title_leaves_file_and_entry_in_place(self):
        self._write_metadata_json("The Book")
        abs_client.upsert_bootstrapped_file(self.reports_dir, self.metadata_json, "ASIN1", str(self.book_dir))
        items = [{
            "id": "li1", "path": str(self.book_dir), "relPath": "book", "updatedAt": 100,
            "media": {"metadata": {"asin": "ASIN1", "title": "A Totally Different Book"}},
        }]
        result = abs_client.reconcile_bootstrap_registry(
            self.reports_dir, abs_url="http://x", abs_api_key="key", fetch_items=lambda: items,
        )
        self.assertEqual(result["skipped_mismatch"], 1)
        self.assertTrue(self.metadata_json.exists())
        self.assertIn(str(self.metadata_json), abs_client.load_bootstrap_registry(self.reports_dir))

    def test_lookup_miss_leaves_file_and_entry_in_place(self):
        self._write_metadata_json("The Book")
        abs_client.upsert_bootstrapped_file(self.reports_dir, self.metadata_json, "ASIN1", str(self.book_dir))
        result = abs_client.reconcile_bootstrap_registry(
            self.reports_dir, abs_url="http://x", abs_api_key="key", fetch_items=lambda: [],
        )
        self.assertEqual(result["reconciled"], 0)
        self.assertTrue(self.metadata_json.exists())
        self.assertIn(str(self.metadata_json), abs_client.load_bootstrap_registry(self.reports_dir))


if __name__ == "__main__":
    unittest.main()


class MetadataJsonDiffTests(unittest.TestCase):
    ABS = {"title": "T", "subtitle": "", "authors": [{"id": "a1", "name": "A"}], "narrators": ["N"],
           "series": [{"id": "s1", "name": "S", "sequence": "1"}], "genres": ["Fantasy"],
           "publishedYear": "2020", "publisher": "", "description": "Desc  text", "isbn": None,
           "asin": "B0TEST1234", "language": "english", "explicit": False}

    def test_identical_content_in_file_shape_has_no_diff(self):
        f = {"title": "T", "subtitle": "", "authors": ["A"], "narrators": ["N"], "series": ["S #1"],
             "genres": ["Fantasy", "Audiobook"], "publishedYear": "2020", "publisher": "",
             "description": "Desc text", "isbn": None, "asin": "B0TEST1234", "language": "english", "explicit": False}
        self.assertEqual(abs_client.metadata_json_diff(f, self.ABS), {})

    def test_blank_file_values_never_count_as_differences(self):
        self.assertEqual(abs_client.metadata_json_diff({"title": "", "genres": [], "asin": None, "authors": []}, self.ABS), {})

    def test_differences_come_back_in_patch_shape(self):
        f = {"authors": ["A", "B"], "series": ["Other #2"], "genres": ["Horror"], "publisher": "P"}
        self.assertEqual(abs_client.metadata_json_diff(f, self.ABS), {
            "authors": [{"name": "A"}, {"name": "B"}], "series": [{"name": "Other", "sequence": "2"}],
            "genres": ["Horror"], "publisher": "P"})

    def test_author_and_narrator_order_alone_is_not_a_difference(self):
        # ABS reorders co-authors itself; seen on 7 Dune books in the real-library dry run.
        abs_meta = dict(self.ABS, authors=[{"name": "Brian Herbert"}, {"name": "Kevin J. Anderson"}], narrators=["N1", "N2"])
        f = {"authors": ["Kevin J. Anderson", "Brian Herbert"], "narrators": ["N2", "N1"]}
        self.assertEqual(abs_client.metadata_json_diff(f, abs_meta), {})

    def test_audiobook_only_genre_file_is_not_a_difference(self):
        self.assertEqual(abs_client.metadata_json_diff({"genres": ["Audiobook"]}, self.ABS), {})


class ReconcileLegacyMetadataJsonTests(unittest.TestCase):
    def setUp(self):
        import json as _json
        self._json = _json
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "A" / "B"; self.folder.mkdir(parents=True)
        self.item = {"id": "i1", "path": str(self.folder), "isFile": False, "updatedAt": 2_000_000,
                     "media": {"metadata": {"title": "T", "genres": ["Fantasy"], "authors": [{"name": "A"}],
                                            "series": [{"name": "S", "sequence": "1"}], "narrators": ["N"]}}}
        self.patches = []

    def write(self, data):
        (self.folder / "metadata.json").write_text(self._json.dumps(data), encoding="utf-8")

    def run_it(self, mtime_s, patch_fn=None):
        return abs_client.reconcile_legacy_metadata_json(
            str(self.folder), self.item, abs_url="u", abs_api_key="k",
            patch_fn=patch_fn or (lambda path, body, *a, **k: self.patches.append((path, body))),
            mtime_fn=lambda p: mtime_s)

    def test_identical_file_is_deleted_without_patching(self):
        self.write({"title": "T", "genres": ["Fantasy", "Audiobook"], "authors": ["A"], "series": ["S #1"], "narrators": ["N"]})
        r = self.run_it(mtime_s=1_000)
        self.assertEqual(r["action"], "deleted_identical"); self.assertEqual(self.patches, [])
        self.assertFalse((self.folder / "metadata.json").exists())

    def test_abs_newer_wins_and_file_is_deleted(self):
        self.write({"title": "T", "genres": ["Audiobook", "Horror"]})
        r = self.run_it(mtime_s=1_000)  # 1_000 s = 1_000_000 ms, older than updatedAt 2_000_000 ms
        self.assertEqual(r["action"], "deleted_abs_newer"); self.assertEqual(self.patches, [])
        self.assertFalse((self.folder / "metadata.json").exists())

    def test_file_newer_pushes_differences_then_deletes(self):
        self.write({"title": "T", "genres": ["Horror"], "publisher": "P", "subtitle": ""})
        r = self.run_it(mtime_s=3_000)
        self.assertEqual(r["action"], "consolidated_then_deleted")
        self.assertEqual(self.patches, [("/api/items/i1/media", {"metadata": {"genres": ["Horror"], "publisher": "P"}})])
        self.assertFalse((self.folder / "metadata.json").exists())

    def test_patch_failure_keeps_the_file(self):
        self.write({"title": "T2"})
        def boom(*a, **k): raise OSError("down")
        r = self.run_it(mtime_s=3_000, patch_fn=boom)
        self.assertEqual(r["action"], "kept_patch_failed"); self.assertTrue((self.folder / "metadata.json").exists())

    def test_unreadable_file_is_kept(self):
        (self.folder / "metadata.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_it(3_000)["action"], "kept_unreadable")
        self.assertTrue((self.folder / "metadata.json").exists())

    def test_single_file_items_are_never_touched(self):
        self.write({"title": "Other"}); self.item["isFile"] = True
        self.assertEqual(self.run_it(3_000)["action"], "none"); self.assertTrue((self.folder / "metadata.json").exists())

    def test_folder_that_is_not_the_items_own_path_is_never_touched(self):
        self.write({"title": "Other"}); self.item["path"] = str(self.folder.parent)
        self.assertEqual(self.run_it(3_000)["action"], "none"); self.assertTrue((self.folder / "metadata.json").exists())

    def test_no_file_is_none(self):
        self.assertEqual(self.run_it(3_000)["action"], "none")


class SyncBookMetadataLegacyJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "Book"; self.folder.mkdir()
        self.record = {"library_item_id": "li1", "path": str(self.folder), "rel_path": "Book", "updated_at": 100,
                       "media": {"metadata": {"title": "Old"}}}
        self.item = {"id": "li1", "path": str(self.folder), "isFile": False, "updatedAt": 2_000_000,
                     "media": {"metadata": {"title": "Old", "genres": []}}}
        self.metadata = {"title": "New", "author": "", "narrator": "", "series": "", "sequence": "",
                         "genre": "", "year": "", "summary": "", "isbn": "", "asin": "", "language": ""}

    def call(self, calls):
        with patch.object(abs_client, "abs_patch_json", side_effect=lambda path, body, *a, **k: calls.append(("patch", body))):
            return abs_client.sync_book_metadata(
                metadata=self.metadata, expected_path=str(self.folder), abs_url="u", abs_api_key="k",
                lookup_item=lambda a, p: self.record, write_file_fallback=lambda: None,
                get_item=lambda item_id: self.item)

    def test_patch_branch_deletes_identical_legacy_file(self):
        (self.folder / "metadata.json").write_text('{"title": "Old"}', encoding="utf-8")
        calls = []
        result = self.call(calls)
        self.assertEqual(result["legacy_metadata_json"]["action"], "deleted_identical")
        self.assertFalse((self.folder / "metadata.json").exists())

    def test_newer_file_is_consolidated_before_our_patch(self):
        import os
        f = self.folder / "metadata.json"; f.write_text('{"publisher": "P"}', encoding="utf-8")
        os.utime(f, (3_000, 3_000))
        calls = []
        self.call(calls)
        self.assertEqual(calls[0], ("patch", {"metadata": {"publisher": "P"}}))
        self.assertEqual(calls[1][1]["metadata"]["title"], "New")

    def test_file_fallback_branch_never_deletes(self):
        (self.folder / "metadata.json").write_text('{"title": "Old"}', encoding="utf-8")
        abs_client.sync_book_metadata(metadata=self.metadata, expected_path=str(self.folder), abs_url="u", abs_api_key="",
                                      lookup_item=lambda a, p: self.record, write_file_fallback=lambda: None,
                                      get_item=lambda item_id: self.item)
        self.assertTrue((self.folder / "metadata.json").exists())


class LegacyMetadataJsonReviewFixTests(unittest.TestCase):
    """Final-review fixes: malformed list fields, mtime errors, fill_missing
    after a consolidation, and kept files being logged."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "Book"; self.folder.mkdir()

    def test_string_list_fields_are_one_value_not_characters(self):
        diff = abs_client.metadata_json_diff(
            {"genres": "Fantasy", "authors": "Jane Doe", "narrators": "Bob", "series": "Saga #2"},
            {"genres": [], "authors": [], "narrators": [], "series": []})
        self.assertEqual(diff["genres"], ["Fantasy"])
        self.assertEqual(diff["authors"], [{"name": "Jane Doe"}])
        self.assertEqual(diff["narrators"], ["Bob"])
        self.assertEqual(diff["series"], [{"name": "Saga", "sequence": "2"}])

    def test_non_list_non_string_list_fields_are_ignored(self):
        self.assertEqual(abs_client.metadata_json_diff({"genres": 5, "authors": {"x": 1}}, {"genres": []}), {})

    def test_mtime_error_keeps_the_file_instead_of_raising(self):
        (self.folder / "metadata.json").write_text('{"publisher": "P"}', encoding="utf-8")
        item = {"id": "i1", "path": str(self.folder), "isFile": False, "updatedAt": 1, "media": {"metadata": {}}}

        def boom(p):
            raise OSError("stale NFS handle")

        r = abs_client.reconcile_legacy_metadata_json(str(self.folder), item, abs_url="u", abs_api_key="k",
                                                      patch_fn=lambda *a, **k: None, mtime_fn=boom)
        self.assertEqual(r["action"], "kept_unreadable")
        self.assertTrue((self.folder / "metadata.json").exists())

    def _sync(self, calls, *, fill_missing=False, metadata=None, record_media=None, live_meta=None):
        record = {"library_item_id": "li1", "path": str(self.folder), "rel_path": "Book", "updated_at": 100,
                  "media": {"metadata": record_media if record_media is not None else {"title": "T"}}}
        item = {"id": "li1", "path": str(self.folder), "isFile": False, "updatedAt": 1,
                "media": {"metadata": live_meta if live_meta is not None else {"title": "T"}}}
        md = {"title": "T", "author": "", "narrator": "", "series": "", "sequence": "", "genre": "", "year": "",
              "summary": "", "isbn": "", "asin": "", "language": ""}
        md.update(metadata or {})
        with patch.object(abs_client, "abs_patch_json", side_effect=lambda path, body, *a, **k: calls.append(body)):
            return abs_client.sync_book_metadata(
                metadata=md, expected_path=str(self.folder), fill_missing=fill_missing, abs_url="u", abs_api_key="k",
                lookup_item=lambda a, p: record, write_file_fallback=lambda: None, get_item=lambda i: item)

    def test_fill_missing_never_overwrites_a_value_just_consolidated_from_a_newer_file(self):
        import os
        f = self.folder / "metadata.json"; f.write_text('{"publisher": "From File"}', encoding="utf-8")
        os.utime(f, (3_000, 3_000))
        calls = []
        self._sync(calls, fill_missing=True, metadata={"publisher": "From Meta Forge"})
        self.assertEqual(calls[0], {"metadata": {"publisher": "From File"}})
        self.assertTrue(all("publisher" not in c["metadata"] for c in calls[1:]), calls)

    def test_series_merge_starts_from_the_consolidated_series(self):
        import os
        f = self.folder / "metadata.json"; f.write_text('{"series": ["Other #3"]}', encoding="utf-8")
        os.utime(f, (3_000, 3_000))
        calls = []
        self._sync(calls, metadata={"series": "Saga", "sequence": "1"}, live_meta={"title": "T", "series": []})
        names = {s["name"] for s in calls[-1]["metadata"]["series"]}
        self.assertEqual(names, {"Other", "Saga"})

    def test_a_kept_legacy_file_is_logged_as_a_revert_risk(self):
        (self.folder / "metadata.json").write_text("{broken", encoding="utf-8")
        with self.assertLogs("app.abs_client", level="WARNING") as logs:
            result = self._sync([])
        self.assertEqual(result["legacy_metadata_json"]["action"], "kept_unreadable")
        self.assertIn("metadata.json", logs.output[0])
        self.assertIn(str(self.folder), logs.output[0])
