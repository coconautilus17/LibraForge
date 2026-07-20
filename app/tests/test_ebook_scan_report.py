import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import scan_ebook_units_for_report


class ScanEbookUnitsForReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, rel_path):
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
        return p

    def test_strong_match_is_status_matched_with_score_and_no_write_action(self):
        self._touch("Linux/EPUB/kubernetes.epub")
        candidate = {
            "title": "Kubernetes Up and Running", "subtitle": "", "authors": ["Kelsey Hightower"],
            "series": "", "sequence": "", "year": "2022", "cover_url": "https://x/y.jpg",
            "summary": "...", "isbn": "",
        }
        with patch("app.main.search_ebook_candidates", return_value=candidate):
            items = scan_ebook_units_for_report(self.root)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["status"], "matched")
        self.assertIsNotNone(item["match"])
        self.assertGreater(item["score"], 0.35)
        self.assertEqual(item["media_type"], "ebook")
        self.assertEqual(item["formats"], ["epub"])
        self.assertNotIn("write_action", item)

    def test_no_candidate_is_status_unmatched(self):
        self._touch("Linux/PDF/totally-unrecoverable-name.pdf")
        with patch("app.main.search_ebook_candidates", return_value=None):
            items = scan_ebook_units_for_report(self.root)
        self.assertEqual(items[0]["status"], "unmatched")
        self.assertIsNone(items[0]["match"])

    def test_low_similarity_candidate_is_treated_as_unmatched(self):
        self._touch("Linux/EPUB/kubernetes.epub")
        wrong_candidate = {
            "title": "The Hobbit", "subtitle": "", "authors": ["J. R. R. Tolkien"],
            "series": "", "sequence": "", "year": "1937", "cover_url": "", "summary": "", "isbn": "",
        }
        with patch("app.main.search_ebook_candidates", return_value=wrong_candidate):
            items = scan_ebook_units_for_report(self.root)
        self.assertEqual(items[0]["status"], "unmatched")
        self.assertIsNone(items[0]["match"])

    def test_local_reflects_existing_sidecar_when_present(self):
        epub_path = self._touch("Linux/EPUB/kubernetes.epub")
        import app.main as main_module
        fixer_module = main_module.load_fixer_module(main_module.default_fixer_script())
        fixer_module.write_ebook_sidecar(
            epub_path, source_formats=["epub"], source_files={"epub": str(epub_path)},
            book={"title": "Kubernetes Up and Running", "subtitle": "", "author": "Kelsey Hightower",
                  "narrator": "", "series": "", "sequence": "", "year": "2022", "summary": "",
                  "genre": "", "isbn": "", "cover_url": ""},
        )
        with patch("app.main.search_ebook_candidates", return_value=None):
            items = scan_ebook_units_for_report(self.root)
        self.assertEqual(items[0]["local"]["title"], "Kubernetes Up and Running")

    def test_never_writes_to_the_sidecar(self):
        epub_path = self._touch("Linux/EPUB/kubernetes.epub")
        candidate = {
            "title": "Kubernetes Up and Running", "subtitle": "", "authors": ["Kelsey Hightower"],
            "series": "", "sequence": "", "year": "2022", "cover_url": "", "summary": "", "isbn": "",
        }
        with patch("app.main.search_ebook_candidates", return_value=candidate):
            scan_ebook_units_for_report(self.root)
        import app.main as main_module
        fixer_module = main_module.load_fixer_module(main_module.default_fixer_script())
        self.assertIsNone(fixer_module.read_book_sidecar(epub_path))


if __name__ == "__main__":
    unittest.main()
