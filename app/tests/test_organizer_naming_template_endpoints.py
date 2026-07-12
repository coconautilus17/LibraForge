"""Endpoint tests for Folder Forge's naming-template validate/preview routes."""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module

client = TestClient(main_module.app)


class _BaseNamingTemplateEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._orig_root = main_module.AUDIOBOOKS_ROOT
        main_module.AUDIOBOOKS_ROOT = self.root
        self.unorganized = self.root / "_unorganized"
        self.unorganized.mkdir()

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig_root
        self.tmp.cleanup()

    def _write_book(self, folder: str, audio_name: str, book: dict) -> None:
        book_dir = self.unorganized / folder
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / audio_name).touch()
        (book_dir / "libraforge.json").write_text(json.dumps({"book": book}), encoding="utf-8")


class ValidateEndpointTests(_BaseNamingTemplateEndpointTest):
    def test_valid_template_reports_valid(self):
        resp = client.post("/api/organizer/naming-template/validate", json={"template": "{author}/{title}/"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["valid"])
        self.assertEqual(body["problems"], [])

    def test_invalid_template_reports_problems(self):
        resp = client.post("/api/organizer/naming-template/validate", json={"template": "{author}/{bogus}/"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["valid"])
        self.assertTrue(any("bogus" in p for p in body["problems"]))


class PreviewEndpointTests(_BaseNamingTemplateEndpointTest):
    def test_preview_renders_real_sample_books(self):
        self._write_book("Some Book", "book.m4b", {"title": "The Title", "author": "Author Name", "series": ""})
        resp = client.post(
            "/api/organizer/naming-template/preview",
            json={
                "template": "{author}/{title}/",
                "root_path": str(self.unorganized),
                "destination_root": str(self.root),
            },
        )
        self.assertEqual(resp.status_code, 200)
        previews = resp.json()["previews"]
        self.assertEqual(len(previews), 1)
        self.assertIn("Author Name", previews[0]["target_dir"])

    def test_invalid_template_returns_400(self):
        self._write_book("Some Book", "book.m4b", {"title": "T", "author": "A", "series": ""})
        resp = client.post(
            "/api/organizer/naming-template/preview",
            json={
                "template": "{bogus}/",
                "root_path": str(self.unorganized),
                "destination_root": str(self.root),
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_root_path_outside_audiobooks_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            resp = client.post(
                "/api/organizer/naming-template/preview",
                json={
                    "template": "{author}/{title}/",
                    "root_path": outside,
                    "destination_root": str(self.root),
                },
            )
            self.assertEqual(resp.status_code, 400)


class ExamplePreviewEndpointTests(unittest.TestCase):
    """Uses the real bundled app/example_books/ fixtures -- no AUDIOBOOKS_ROOT
    patching needed, this endpoint takes no user-supplied path at all."""

    def test_valid_template_renders_all_bundled_examples(self):
        resp = client.post(
            "/api/organizer/naming-template/example-preview",
            json={"template": "{author}/{series}/{order} - {title},{edition}/{title},{asin}"},
        )
        self.assertEqual(resp.status_code, 200)
        previews = resp.json()["previews"]
        self.assertEqual(len(previews), 6)
        for preview in previews:
            self.assertTrue(preview["scenario"])

    def test_filename_cleanup_visible_on_bundled_examples(self):
        # The bundled single-file example books carry deliberately cluttered
        # source names (release junk: bracketed ASIN/year/bitrate, {narrator}
        # braces, "unabridged"/"audiobook"/"light novel" keywords, vol_NN)
        # so {original} shows the raw name while {filename} shows the
        # noise-cleaned result -- and never a "book.m4b" placeholder.
        def previews(template):
            resp = client.post(
                "/api/organizer/naming-template/example-preview",
                json={"template": template},
            )
            self.assertEqual(resp.status_code, 200)
            return {p["scenario"]: p["filename"] for p in resp.json()["previews"]}

        raw = previews("{author}/{original}")
        cleaned = previews("{author}/{series} [{edition}]/{order} - {title}/{filename}")

        # {original} preserves the clutter verbatim.
        self.assertEqual(raw["No series"], "Armor [B0B5VQ5XYF] [2024] unabridged.m4b")
        # {filename} strips it to the clean folder-derived name.
        self.assertEqual(cleaned["No series"], "Armor.m4b")
        # The two must differ for the cluttered single-file books -- proof the
        # cleanup actually fired rather than the name being clean to begin with.
        self.assertNotEqual(raw["No series"], cleaned["No series"])
        self.assertNotEqual(raw["Has publisher"], cleaned["Has publisher"])
        # Regression guard: the roman-numeral book's folder collapses the
        # redundant title to "Book 5", but its {filename} keeps the full title
        # (V and all). Its source name is clean here so it is preserved
        # verbatim; and even a noisy source would now fall back to the metadata
        # title rather than the collapsed "Book 5" folder leaf.
        self.assertEqual(cleaned["Title matches series"], "The Dao of Magic V.m4b")
        # Multi-file books never expose a template filename either way.
        self.assertIsNone(raw["Multi-file book"])
        self.assertIsNone(cleaned["Multi-file book"])
        for filename in list(raw.values()) + list(cleaned.values()):
            self.assertNotEqual(filename, "book.m4b")

    def test_invalid_template_returns_400(self):
        resp = client.post(
            "/api/organizer/naming-template/example-preview",
            json={"template": "{bogus}/"},
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
