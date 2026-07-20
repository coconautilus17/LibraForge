import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


class EbookLoadEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patcher = patch.object(main, "AUDIOBOOKS_ROOT", self.root)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def _touch(self, rel_path):
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
        return p

    def test_load_returns_current_and_scored_candidate(self):
        epub_path = self._touch("Linux/EPUB/kubernetes.epub")
        candidate = {
            "title": "Kubernetes Up and Running", "subtitle": "", "authors": ["Kelsey Hightower"],
            "series": "", "sequence": "", "year": "2022", "cover_url": "", "summary": "", "isbn": "",
        }
        with patch.object(main, "search_ebook_candidates", return_value=candidate):
            res = client.post("/api/manual-review/ebook/load", json={"path": str(epub_path)})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["path"], str(epub_path))
        self.assertIsNotNone(data["match"])
        self.assertEqual(data["match"]["title"], "Kubernetes Up and Running")
        self.assertGreater(data["score"], 0.35)
        self.assertEqual(data["formats"], ["epub"])

    def test_load_succeeds_with_no_candidate_found(self):
        epub_path = self._touch("Linux/EPUB/totally-unrecoverable.epub")
        with patch.object(main, "search_ebook_candidates", return_value=None):
            res = client.post("/api/manual-review/ebook/load", json={"path": str(epub_path)})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsNone(data["match"])
        self.assertIsNone(data["score"])

    def test_load_rejects_path_outside_audiobooks_root(self):
        res = client.post("/api/manual-review/ebook/load", json={"path": "/etc/passwd"})
        self.assertEqual(res.status_code, 400)

    def test_load_reflects_existing_sidecar_as_local(self):
        epub_path = self._touch("Linux/EPUB/kubernetes.epub")
        fixer_module = main.load_fixer_module(main.default_fixer_script())
        fixer_module.write_ebook_sidecar(
            epub_path, source_formats=["epub"], source_files={"epub": str(epub_path)},
            book={"title": "Existing Title", "subtitle": "", "author": "Existing Author",
                  "narrator": "", "series": "", "sequence": "", "year": "", "summary": "",
                  "genre": "", "isbn": "", "cover_url": ""},
        )
        with patch.object(main, "search_ebook_candidates", return_value=None):
            res = client.post("/api/manual-review/ebook/load", json={"path": str(epub_path)})
        self.assertEqual(res.json()["local"]["title"], "Existing Title")


if __name__ == "__main__":
    unittest.main()
