"""POST /api/organizer/cleanup-source deletes leftovers after books were moved
out of the scan root. It must remove exactly the leftovers it names and nothing
that still holds audio, notes or sidecars."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main_module

client = TestClient(main_module.app)


class OrganizerCleanupSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.library = Path(self.tmp.name).resolve()
        self.root = self.library / "_unorganized"
        self.root.mkdir()
        patcher = mock.patch.object(main_module, "AUDIOBOOKS_ROOT", self.library)
        patcher.start()
        self.addCleanup(patcher.stop)

    def touch(self, rel, content=b"x"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def clean(self, root=None):
        response = client.post("/api/organizer/cleanup-source", json={"root_path": str(root or self.root)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_chapter_count_caches_are_deleted_and_listed_with_their_folder(self):
        self.touch("Book A/Book A.chapter-count-cache.json")
        self.touch("Book A/Book A.m4b")
        self.touch("top.chapter-count-cache.json")
        out = self.clean()
        self.assertEqual(sorted((f["name"], f["folder"], f["status"]) for f in out["json_files"]),
                         [("Book A.chapter-count-cache.json", "Book A", "deleted"), ("top.chapter-count-cache.json", ".", "deleted")])
        self.assertTrue((self.root / "Book A" / "Book A.m4b").exists())

    def test_thumbs_db_files_are_deleted_in_any_case(self):
        self.touch("A/Thumbs.db")
        self.touch("B/thumbs.DB")
        out = self.clean()
        self.assertEqual(sorted((t["path"], t["name"], t["status"]) for t in out["thumbs_db"]),
                         [("A", "Thumbs.db", "deleted"), ("B", "thumbs.DB", "deleted")])

    def test_empty_folders_are_removed_deepest_first_but_folders_with_content_stay(self):
        (self.root / "empty" / "nested" / "deeper").mkdir(parents=True)
        self.touch("keep/book.m4b")
        (self.root / "keep" / "empty-child").mkdir()
        out = self.clean()
        self.assertEqual(out["empty_dirs_deleted"], 4)           # deeper, nested, empty, keep/empty-child
        self.assertFalse((self.root / "empty").exists())
        self.assertTrue((self.root / "keep" / "book.m4b").exists())
        self.assertFalse((self.root / "keep" / "empty-child").exists())

    def test_a_folder_emptied_by_the_file_cleanup_is_removed_in_the_same_call(self):
        self.touch("Gone/Thumbs.db")
        out = self.clean()
        self.assertEqual(out["empty_dirs_deleted"], 1)
        self.assertFalse((self.root / "Gone").exists())

    def test_the_scan_root_itself_is_never_removed(self):
        out = self.clean()
        self.assertTrue(self.root.exists())
        self.assertEqual((out["empty_dirs_deleted"], out["json_files"], out["thumbs_db"], out["root"]), (0, [], [], str(self.root)))

    def test_audio_notes_sidecars_and_covers_are_never_touched(self):
        keep = [self.touch("A/book.m4b"), self.touch("A/notes.txt"), self.touch("A/libraforge.json"), self.touch("A/cover.jpg"),
                self.touch("A/metadata.json"), self.touch("A/book.m4b.libraforge.json")]
        self.clean()
        self.assertTrue(all(path.exists() for path in keep))

    def test_a_path_outside_the_library_is_rejected(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        response = client.post("/api/organizer/cleanup-source", json={"root_path": str(outside)})
        self.assertGreaterEqual(response.status_code, 400)
        self.assertTrue(outside.exists())

    def test_a_missing_path_is_rejected(self):
        response = client.post("/api/organizer/cleanup-source", json={"root_path": str(self.library / "nope")})
        self.assertGreaterEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
