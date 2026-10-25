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


class TooBigTests(unittest.TestCase):
    """#454: ABS loads a collection's books all at once; a 2,664-book Fantasy
    collection was 49 MB and the Collections page couldn't open."""

    def setUp(self):
        n = gc.MAX_COLLECTION_BOOKS + 1
        self.counts = {"Fantasy": [f"f{i}" for i in range(n)], "Sci-Fi": [f"s{i}" for i in range(n)],
                       "Mine": [f"m{i}" for i in range(n)], "Horror": ["h"]}
        self.existing = [{"id": "c1", "name": "Sci-Fi", "description": gc.MARKER, "books": [{"id": "s0"}]},
                         {"id": "u1", "name": "Mine", "description": "my own", "books": []}]

    def test_a_genre_over_the_cap_is_never_written(self):
        rows = {r["genre"]: r for r in gc.plan_collections(["Fantasy", "Sci-Fi", "Mine", "Horror"], self.counts, self.existing)}
        self.assertEqual((rows["Fantasy"]["action"], rows["Fantasy"]["collection_id"]), ("too_big", None))
        self.assertEqual((rows["Sci-Fi"]["action"], rows["Sci-Fi"]["collection_id"]), ("too_big", "c1"))
        self.assertEqual(rows["Mine"]["action"], "name_taken")  # the user's own: never touched
        self.assertEqual(rows["Horror"]["action"], "create")

    def test_applying_removes_only_an_existing_libraforge_collection(self):
        rows = gc.plan_collections(["Fantasy", "Sci-Fi", "Mine"], self.counts, self.existing)
        posted, deleted = [], []
        out = gc.apply_collection_plan(rows, library_id="L", post_fn=lambda p, b: posted.append(p),
                                       patch_fn=lambda p, b: None, delete_fn=deleted.append)
        self.assertEqual((posted, deleted), ([], ["/api/collections/c1"]))
        self.assertEqual((out["created"], out["removed"], out["skipped"]), (0, 1, 2))


class UmbrellaTests(unittest.TestCase):
    def test_store_umbrella_shelves_are_not_collection_genres(self):
        items = [{"id": "x", "media": {"metadata": {"genres": ["Science Fiction & Fantasy", "Literature & Fiction", "Fantasy"]}}}]
        self.assertEqual(sorted(gc.genre_counts(items)), ["Fantasy"])
