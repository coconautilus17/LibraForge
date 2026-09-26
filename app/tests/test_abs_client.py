"""Tests for app.abs_client: the direct-ABS-API metadata sync module.

Pure-function tests only for the payload/index/blank-check helpers (no
network mocking needed); sync_book_metadata's three-way branch is exercised
with plain fake lookup/fallback/GET/PATCH callables.
"""
import unittest
from unittest.mock import patch

from app import abs_client


class BuildItemIndexTests(unittest.TestCase):
    def test_indexes_by_asin_and_path_and_rel_path(self):
        items = [
            {
                "id": "li1", "path": "/audiobooks/A/Book", "relPath": "A/Book", "updatedAt": 111,
                "media": {"metadata": {"asin": "b0abc1234", "title": "Book"}},
            },
            {
                "id": "li2", "path": "/audiobooks/Linux/EPUB", "relPath": "Linux/EPUB", "updatedAt": 222,
                "media": {"metadata": {"asin": "", "title": "Efficient Linux"}},
            },
        ]
        index = abs_client.build_item_index(items)
        self.assertIn("B0ABC1234", index["by_asin"])
        self.assertEqual(index["by_asin"]["B0ABC1234"]["library_item_id"], "li1")
        self.assertIn("/audiobooks/Linux/EPUB", index["by_path"])
        self.assertIn("Linux/EPUB", index["by_path"])
        self.assertNotIn("", index["by_asin"])

    def test_item_with_no_asin_is_only_path_indexed(self):
        items = [{"id": "li1", "path": "/x", "relPath": "x", "updatedAt": 1, "media": {"metadata": {}}}]
        index = abs_client.build_item_index(items)
        self.assertEqual(index["by_asin"], {})
        self.assertIn("/x", index["by_path"])


class LookupItemInIndexTests(unittest.TestCase):
    def setUp(self):
        self.index = abs_client.build_item_index([
            {"id": "li1", "path": "/p", "relPath": "p", "updatedAt": 1, "media": {"metadata": {"asin": "ASIN1"}}},
        ])

    def test_asin_takes_priority_over_path(self):
        record = abs_client.lookup_item_in_index(self.index, asin="asin1", path="/somewhere/else")
        self.assertEqual(record["library_item_id"], "li1")

    def test_falls_back_to_path_when_no_asin(self):
        record = abs_client.lookup_item_in_index(self.index, asin="", path="/p")
        self.assertEqual(record["library_item_id"], "li1")

    def test_falls_back_to_rel_path(self):
        record = abs_client.lookup_item_in_index(self.index, asin="", rel_path="p")
        self.assertEqual(record["library_item_id"], "li1")

    def test_miss_returns_none(self):
        self.assertIsNone(abs_client.lookup_item_in_index(self.index, asin="NOPE", path="/nope"))


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


if __name__ == "__main__":
    unittest.main()
