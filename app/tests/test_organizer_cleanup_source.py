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

if __name__ == "__main__":
    unittest.main()
