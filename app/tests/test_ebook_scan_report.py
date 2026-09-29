import tempfile
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch

import app.main as main_module
from app.main import scan_ebook_units_for_report


def ol_product(title, author, series="", sequence="", cover="https://x/y.jpg", summary="...", year="2022"):
    """An Open Library result as the fixer's abs_search returns it."""
    return {
        "asin": "", "title": title, "subtitle": "", "authors": [{"name": author}], "narrators": [],
        "series": [{"title": series, "sequence": sequence}] if series else [],
        "publisher_summary": summary, "product_images": {"500": cover}, "runtime_length_min": None,
        "release_date": year, "_abs_provider": "openlibrary", "_abs_isbn": "", "_abs_genres": [],
    }


@contextmanager
def providers(open_library=()):
    """Stub the fixer's provider calls; Goodreads is not configured."""
    fixer = main_module.load_fixer_module(main_module.default_fixer_script())
    with patch.object(fixer, "abs_search", return_value=list(open_library)), \
         patch.object(main_module, "_get_abs_url", return_value="http://abs"), \
         patch.object(main_module, "_get_abs_api_key", return_value="key"), \
         patch.object(main_module, "_load_abs_tract_config", return_value={"url": "", "kindle_region": "us"}):
        yield


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
        self._touch("Linux/EPUB/Kubernetes Up and Running.epub")
        candidate = ol_product("Kubernetes Up and Running", "Kelsey Hightower", "", "", cover="https://x/y.jpg", summary="...")
        with providers([candidate]):
            items = scan_ebook_units_for_report(self.root, open_library=True)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["status"], "matched")
        self.assertIsNotNone(item["match"])
        self.assertIsNotNone(item["score"])
        self.assertEqual(item["media_type"], "ebook")
        self.assertEqual(item["formats"], ["epub"])
        self.assertNotIn("write_action", item)

    def test_no_candidate_is_status_unmatched(self):
        self._touch("Linux/PDF/totally-unrecoverable-name.pdf")
        with providers():
            items = scan_ebook_units_for_report(self.root, open_library=True)
        self.assertEqual(items[0]["status"], "unmatched")
        self.assertIsNone(items[0]["match"])

    def test_low_similarity_candidate_is_treated_as_unmatched(self):
        self._touch("Linux/EPUB/Kubernetes Up and Running.epub")
        wrong_candidate = ol_product("The Hobbit", "J. R. R. Tolkien", year="1937")
        with providers([wrong_candidate]):
            items = scan_ebook_units_for_report(self.root, open_library=True)
        self.assertEqual(items[0]["status"], "unmatched")
        self.assertIsNone(items[0]["match"])

    def test_local_reflects_existing_sidecar_when_present(self):
        epub_path = self._touch("Linux/EPUB/Kubernetes Up and Running.epub")
        import app.main as main_module
        fixer_module = main_module.load_fixer_module(main_module.default_fixer_script())
        fixer_module.write_ebook_sidecar(
            epub_path, source_formats=["epub"], source_files={"epub": str(epub_path)},
            book={"title": "Kubernetes Up and Running", "subtitle": "", "author": "Kelsey Hightower",
                  "narrator": "", "series": "", "sequence": "", "year": "2022", "summary": "",
                  "genre": "", "isbn": "", "cover_url": ""},
        )
        with providers():
            items = scan_ebook_units_for_report(self.root, open_library=True)
        self.assertEqual(items[0]["local"]["title"], "Kubernetes Up and Running")

    def test_a_redundant_book_number_suffix_is_cleaned_from_the_candidates_series(self):
        # Regression guard: Open Library/Goodreads series text gets the same
        # cleanup as every audiobook provider's. Goodreads especially is
        # known for exactly this kind of messy series text.
        self._touch("Linux/EPUB/Kubernetes Up and Running.epub")
        candidate = ol_product("Kubernetes Up and Running", "Kelsey Hightower", "K8s Guides, Book 1", "", cover="https://x/y.jpg", summary="...")
        with providers([candidate]):
            items = scan_ebook_units_for_report(self.root, open_library=True)
        match = items[0]["match"]
        self.assertEqual(match["series"], "K8s Guides")
        self.assertEqual(match["sequence"], "1")

    def test_a_clean_series_is_left_alone(self):
        self._touch("Linux/EPUB/Kubernetes Up and Running.epub")
        candidate = ol_product("Kubernetes Up and Running", "Kelsey Hightower", "K8s Guides", "1", cover="https://x/y.jpg", summary="...")
        with providers([candidate]):
            items = scan_ebook_units_for_report(self.root, open_library=True)
        match = items[0]["match"]
        self.assertEqual(match["series"], "K8s Guides")
        self.assertEqual(match["sequence"], "1")

    def test_sources_left_off_are_never_searched(self):
        # Goodreads and Open Library are opt-in for batch runs, as for audiobooks.
        self._touch("Linux/EPUB/Kubernetes Up and Running.epub")
        fixer = main_module.load_fixer_module(main_module.default_fixer_script())
        with providers([ol_product("Kubernetes Up and Running", "Kelsey Hightower")]), \
             patch.object(fixer, "abs_tract_search") as gr_mock, \
             patch.object(fixer, "abs_search") as ol_mock:
            items = scan_ebook_units_for_report(self.root)
        gr_mock.assert_not_called()
        ol_mock.assert_not_called()
        self.assertEqual(items[0]["status"], "unmatched")
        self.assertIn("Goodreads and Open Library are both off", items[0]["skip_reason"])

    def test_never_writes_to_the_sidecar(self):
        epub_path = self._touch("Linux/EPUB/Kubernetes Up and Running.epub")
        candidate = ol_product("Kubernetes Up and Running", "Kelsey Hightower", "", "", cover="", summary="")
        with providers([candidate]):
            scan_ebook_units_for_report(self.root, open_library=True)
        import app.main as main_module
        fixer_module = main_module.load_fixer_module(main_module.default_fixer_script())
        self.assertIsNone(fixer_module.read_book_sidecar(epub_path))


if __name__ == "__main__":
    unittest.main()
