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
        rows = [{"genre": "Explicit", "name": "Explicit", "action": "name_taken", "collection_id": "c2", "add": [], "remove": [], "book_count": 0, "books": []},
                {"genre": "Sci-Fi", "name": "Sci-Fi", "action": "create", "collection_id": None, "add": ["b"], "remove": [], "book_count": 1, "books": ["b"]},
                {"genre": "Fantasy", "name": "Fantasy", "action": "update", "collection_id": "c1", "add": ["b"], "remove": ["z"], "book_count": 2, "books": ["a", "b"]},
                {"genre": "Horror", "name": "Horror", "action": "create", "collection_id": None, "add": ["h"], "remove": [], "book_count": 1, "books": ["h"]}]

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


class LargeGenreTests(unittest.TestCase):
    """#454: ABS loads a collection's books all at once; a 2,664-book Fantasy
    collection was 49 MB and the Collections page couldn't open."""

    def test_a_large_genre_becomes_numbered_parts_cut_between_authors(self):
        books = [f"b{i}" for i in range(1300)]
        # Ten authors of 130 books each.
        order = {b: (f"author {i // 130:02d}", "", b) for i, b in enumerate(books)}
        rows = gc.plan_collections(["Fantasy"], {"Fantasy": books}, [], order)
        self.assertEqual([r["name"] for r in rows], ["Fantasy 1", "Fantasy 2", "Fantasy 3"])
        self.assertTrue(all(r["book_count"] <= gc.MAX_COLLECTION_BOOKS for r in rows))
        self.assertEqual(sum(r["book_count"] for r in rows), 1300)
        authors = [{order[b][0] for b in r["books"]} for r in rows]
        self.assertFalse(authors[0] & authors[1] or authors[1] & authors[2])  # no author in two parts

    def test_litrpg_and_cultivation_books_leave_fantasy_and_sci_fi(self):
        counts = {"Fantasy": ["a", "b", "c"], "Sci-Fi": ["b", "d"], "LitRPG": ["b"], "Cultivation": ["c"]}
        rows = {r["name"]: r for r in gc.plan_collections(["Fantasy", "Sci-Fi", "LitRPG"], counts, [])}
        self.assertEqual((rows["Fantasy"]["books"], rows["Sci-Fi"]["books"], rows["LitRPG"]["books"]), (["a"], ["d"], ["b"]))

    def test_progression_fantasy_is_never_a_collection_and_an_old_one_retires(self):
        existing = [{"id": "pf", "name": "Progression Fantasy", "description": gc.MARKER, "books": [{"id": "a"}]},
                    {"id": "f", "name": "Fantasy", "description": gc.MARKER, "books": [{"id": "a"}]},
                    {"id": "mine", "name": "Fantasy 2", "description": "my own", "books": []}]
        counts = {"Progression Fantasy": ["a"], "Fantasy": [f"f{i}" for i in range(700)]}
        rows = gc.plan_collections(["Progression Fantasy", "Fantasy"], counts, existing)
        by_name = {r["name"]: r["action"] for r in rows}
        self.assertEqual(by_name["Progression Fantasy"], "retire")
        self.assertEqual(by_name["Fantasy"], "retire")  # the unsplit one, replaced by its parts
        self.assertEqual((by_name["Fantasy 1"], by_name["Fantasy 2"]), ("create", "name_taken"))
        deleted = []
        out = gc.apply_collection_plan(rows, library_id="L", post_fn=lambda p, b: None, patch_fn=lambda p, b: None,
                                       delete_fn=deleted.append)
        self.assertEqual(sorted(deleted), ["/api/collections/f", "/api/collections/pf"])
        self.assertEqual(out["removed"], 2)


class UmbrellaTests(unittest.TestCase):
    def test_store_umbrella_shelves_are_not_collection_genres(self):
        items = [{"id": "x", "media": {"metadata": {"genres": ["Science Fiction & Fantasy", "Literature & Fiction", "Fantasy"]}}}]
        self.assertEqual(sorted(gc.genre_counts(items)), ["Fantasy"])
