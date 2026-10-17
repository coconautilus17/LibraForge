"""Logic inside the Enrichment Forge endpoints that the HTTP-level tests do not
reach: the whole-library status rows and the genre collection plan."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import enrichment_batch as eb
from app import main


class BatchStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = eb.BatchStore(Path(self.tmp.name) / "batch.json")
        for target, value in (("_batch_store", lambda: self.store), ("_batch_running", lambda: False)):
            patcher = mock.patch.object(main, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed(self, units, **extra):
        self.store.save({"status": "done", "order": [u["key"] for u in units],
                         "units": {u["key"]: {k: v for k, v in u.items() if k != "key"} for u in units}, **extra})

    def test_counts_cover_every_state_and_the_total_follows_the_order(self):
        self.seed([{"key": "a", "state": "compiled"}, {"key": "b", "state": "failed"}, {"key": "c", "state": "applied"},
                   {"key": "d", "state": "pending"}, {"key": "e", "state": "apply_failed"}, {"key": "f", "state": "compiled"}])
        out = main.enrichment_batch_status(summary_only=True)
        self.assertEqual(out["counts"], {"pending": 1, "compiled": 2, "failed": 1, "applied": 1, "apply_failed": 1})
        self.assertEqual(out["total"], 6)
        self.assertNotIn("units", out)

    def test_units_missing_from_the_unit_map_are_skipped(self):
        self.store.save({"status": "done", "order": ["a", "ghost"], "units": {"a": {"state": "pending"}}})
        self.assertEqual(main.enrichment_batch_status(summary_only=True)["total"], 1)

    def test_degraded_counts_only_compiled_units_with_paused_sources(self):
        self.seed([{"key": "a", "state": "compiled", "result": {"degraded": ["audible"]}},
                   {"key": "b", "state": "compiled", "result": {"degraded": []}},
                   {"key": "c", "state": "applied", "result": {"degraded": ["audible"]}}])
        self.assertEqual(main.enrichment_batch_status(summary_only=True)["degraded"], 1)

    def test_the_status_current_and_timestamps_are_reported(self):
        self.seed([{"key": "a", "state": "pending"}], current="Cradle", started_at=5.0)
        out = main.enrichment_batch_status(summary_only=True)
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["current"], "Cradle")
        self.assertEqual(out["started_at"], 5.0)
        self.assertIsNotNone(out["updated_at"])

    def test_a_run_the_process_no_longer_drives_reads_as_stopped(self):
        self.store.save({"status": "running", "order": [], "units": {}})
        self.assertEqual(main.enrichment_batch_status(summary_only=True)["status"], "stopped")

    def test_full_rows_carry_each_units_review_fields(self):
        books = [{"has_audio": True, "existing_genres": ["Fantasy", "Audiobook"], "explicit": {"strength": "authoritative"}},
                 {"has_audio": False, "existing_genres": ["Romance"], "explicit": {"strength": "authoritative"}},
                 {"existing_genres": ["Sci-Fi"], "explicit": {"strength": "supporting"}}]
        self.seed([{"key": "a", "name": "Cradle", "standalone": False, "book_count": 3, "state": "compiled",
                    "result": {"main_genres": ["Fantasy"], "sub_genres": ["Epic Fantasy"], "pinned_genres": ["Mine"], "agreement": "ok",
                               "coverage": 2, "degraded": ["audible"], "books": books},
                    "applied_genres": ["Fantasy"], "failures": [{"x": 1}], "error": ""}])
        row = main.enrichment_batch_status()["units"][0]
        self.assertEqual((row["key"], row["name"], row["standalone"], row["book_count"], row["state"]), ("a", "Cradle", False, 3, "compiled"))
        self.assertEqual((row["main_genres"], row["sub_genres"], row["pinned_genres"]), (["Fantasy"], ["Epic Fantasy"], ["Mine"]))
        self.assertEqual((row["agreement"], row["coverage"], row["degraded"]), ("ok", 2, ["audible"]))
        self.assertEqual(sorted(row["current_genres"]), ["Fantasy", "Sci-Fi"])      # no Audiobook, no no-audio book
        self.assertEqual(row["explicit_suggested"], 2)                              # authoritative strength only
        self.assertEqual((row["applied_genres"], row["failures"], row["error"]), (["Fantasy"], [{"x": 1}], ""))

    def test_a_unit_without_a_result_has_empty_defaults(self):
        self.seed([{"key": "a", "state": "pending"}])
        row = main.enrichment_batch_status()["units"][0]
        for key in ("main_genres", "sub_genres", "pinned_genres", "current_genres", "applied_genres", "failures", "degraded"):
            self.assertEqual(row[key], [], key)
        self.assertEqual((row["agreement"], row["coverage"], row["explicit_suggested"], row["book_count"], row["name"]), ("", 0, 0, 0, ""))


class CollectionsPlanTests(unittest.TestCase):
    def plan(self, items, existing=None, genres=None):
        with mock.patch.object(main, "fetch_all_abs_book_items", return_value=items), \
             mock.patch.object(main, "abs_get_json", return_value={"collections": existing or []}), \
             mock.patch.object(main, "_get_abs_url", return_value="http://abs"), \
             mock.patch.object(main, "_get_abs_api_key", return_value="k"):
            return main._collections_plan(genres)

    def item(self, ident, library, *genres):
        return {"id": ident, "libraryId": library, "media": {"metadata": {"genres": list(genres)}}}

    def test_every_genre_present_is_planned_most_books_first_and_tagged_with_its_library(self):
        items = [self.item("a", "L1", "Fantasy"), self.item("b", "L1", "Fantasy"), self.item("c", "L1", "Romance")]
        rows, available = self.plan(items)
        self.assertEqual([(r["genre"], r["library_id"], r["action"], r["book_count"]) for r in rows],
                         [("Fantasy", "L1", "create", 2), ("Romance", "L1", "create", 1)])
        self.assertEqual(available, [{"genre": "Fantasy", "count": 2}, {"genre": "Romance", "count": 1}])

    def test_requested_genres_limit_the_rows_but_not_the_available_list(self):
        items = [self.item("a", "L1", "Fantasy"), self.item("c", "L1", "Romance")]
        rows, available = self.plan(items, genres=["Romance"])
        self.assertEqual([r["genre"] for r in rows], ["Romance"])
        self.assertEqual(len(available), 2)

    def test_each_library_is_planned_separately_and_totals_add_up_across_libraries(self):
        items = [self.item("a", "L1", "Fantasy"), self.item("b", "L2", "Fantasy"), self.item("c", "L2", "Fantasy")]
        rows, available = self.plan(items)
        self.assertEqual(sorted((r["library_id"], r["book_count"]) for r in rows), [("L1", 1), ("L2", 2)])
        self.assertEqual(available, [{"genre": "Fantasy", "count": 3}])

    def test_only_a_libraforge_made_collection_in_the_same_library_is_updated(self):
        from app import genre_collections as gc
        existing = [{"id": "c1", "name": "Fantasy", "description": gc.MARKER, "libraryId": "L1", "books": [{"id": "a"}]},
                    {"id": "c2", "name": "Fantasy", "description": gc.MARKER, "libraryId": "L2", "books": [{"id": "zzz"}]}]
        rows, _ = self.plan([self.item("a", "L1", "Fantasy"), self.item("b", "L1", "Fantasy")], existing)
        self.assertEqual((rows[0]["action"], rows[0]["add"], rows[0]["remove"]), ("update", ["b"], []))

    def test_equal_counts_are_ordered_by_name(self):
        rows, available = self.plan([self.item("a", "L1", "Romance"), self.item("b", "L1", "Fantasy")])
        self.assertEqual([r["genre"] for r in rows], ["Fantasy", "Romance"])
        self.assertEqual([a["genre"] for a in available], ["Fantasy", "Romance"])

    def test_no_items_means_no_plan(self):
        self.assertEqual(self.plan([]), ([], []))


if __name__ == "__main__":
    unittest.main()
