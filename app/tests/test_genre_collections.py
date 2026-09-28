"""ABS collections built from genres. LibraForge only ever modifies
collections it created (description marker); a user collection with the same
name is reported, never touched."""
import unittest

from app import genre_collections as gc

ITEMS = [{"id": "a", "media": {"metadata": {"genres": ["Fantasy", "Action & Adventure", "Audiobook"]}}},
         {"id": "b", "media": {"metadata": {"genres": ["Fantasy", "Science Fiction"]}}}]


class CollectionsTests(unittest.TestCase):
    def test_counts_split_canonical_and_never_audiobook(self):
        c = gc.genre_counts(ITEMS)
        self.assertEqual(sorted(c["Fantasy"]), ["a", "b"])
        self.assertEqual(c["Sci-Fi"], ["b"])
        self.assertIn("Action", c)
        self.assertNotIn("Audiobook", c)

    def test_plan_create_update_and_name_taken(self):
        existing = [{"id": "c1", "name": "Fantasy", "description": gc.MARKER, "books": [{"id": "a"}, {"id": "z"}]},
                    {"id": "c2", "name": "explicit", "description": None, "books": []}]
        rows = {r["genre"]: r for r in gc.plan_collections(["Fantasy", "Sci-Fi", "Explicit"], gc.genre_counts(ITEMS), existing)}
        self.assertEqual((rows["Fantasy"]["action"], rows["Fantasy"]["add"], rows["Fantasy"]["remove"]), ("update", ["b"], ["z"]))
        self.assertEqual(rows["Sci-Fi"]["action"], "create")
        self.assertEqual(rows["Explicit"]["action"], "name_taken")

    def test_in_sync_and_empty(self):
        existing = [{"id": "c1", "name": "Sci-Fi", "description": gc.MARKER, "books": [{"id": "b"}]}]
        rows = {r["genre"]: r for r in gc.plan_collections(["Sci-Fi", "Horror"], gc.genre_counts(ITEMS), existing)}
        self.assertEqual(rows["Sci-Fi"]["action"], "in_sync")
        self.assertEqual(rows["Horror"]["action"], "empty")

    def test_apply_never_touches_unmanaged_and_reports_failures(self):
        calls = []
        rows = [{"genre": "Explicit", "action": "name_taken", "collection_id": "c2", "add": [], "remove": [], "book_count": 0, "books": []},
                {"genre": "Sci-Fi", "action": "create", "collection_id": None, "add": ["b"], "remove": [], "book_count": 1, "books": ["b"]},
                {"genre": "Fantasy", "action": "update", "collection_id": "c1", "add": ["b"], "remove": ["z"], "book_count": 2, "books": ["a", "b"]},
                {"genre": "Horror", "action": "create", "collection_id": None, "add": ["h"], "remove": [], "book_count": 1, "books": ["h"]}]

        def post(path, body):
            calls.append(("post", path, body))
            if body.get("name") == "Horror":
                raise RuntimeError("ABS 500")
            return {"id": "n"}

        out = gc.apply_collection_plan(rows, library_id="L", post_fn=post, patch_fn=lambda p, b: calls.append(("patch", p, b)))
        # ABS ignores a PATCH books list (it only reorders); refreshing uses
        # the batch add/remove endpoints (verified live).
        self.assertEqual([(c[0], c[1]) for c in calls], [
            ("post", "/api/collections"), ("post", "/api/collections/c1/batch/add"),
            ("post", "/api/collections/c1/batch/remove"), ("post", "/api/collections")])
        self.assertEqual(calls[0][2], {"libraryId": "L", "name": "Sci-Fi", "description": gc.MARKER, "books": ["b"]})
        self.assertEqual((calls[1][2], calls[2][2]), ({"books": ["b"]}, {"books": ["z"]}))
        self.assertEqual((out["created"], out["updated"], out["skipped"]), (1, 1, 1))
        self.assertEqual(out["failed"], [{"genre": "Horror", "error": "ABS 500"}])


class UmbrellaTests(unittest.TestCase):
    def test_store_umbrella_shelves_are_not_collection_genres(self):
        items = [{"id": "x", "media": {"metadata": {"genres": ["Science Fiction & Fantasy", "Literature & Fiction", "Fantasy"]}}}]
        self.assertEqual(sorted(gc.genre_counts(items)), ["Fantasy"])
