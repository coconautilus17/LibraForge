"""Endpoint tests for Folder Forge's naming-template validate/preview routes."""
import json
import os
import tempfile
import unittest
from unittest import mock
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
        self.assertEqual(len(previews), 10)
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
        # (The multi-file book's "no template filename" guarantee is asserted
        # by test_multi_file_book_filename_shown_as_unchanged, which mocks the
        # grouping. It is intentionally NOT checked here: real grouping of the
        # bundled multi-file example needs ffprobe to read chapter counts, which
        # is present in the app's Docker image but not on the CI runner, so a
        # live assertion here would be environment-dependent.)
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


class AuthorBlockEndpointTests(unittest.TestCase):
    """The four multi-author example books (made-up names) and the author
    block options through the endpoints."""

    def previews(self, template, **extra):
        resp = client.post("/api/organizer/naming-template/example-preview", json={"template": template, **extra})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        return {p["scenario"]: p for p in body["previews"]}, body

    @staticmethod
    def top_folder(preview):
        return Path(preview["target_dir"]).relative_to(main_module.AUDIOBOOKS_ROOT).parts[0]

    def test_multi_author_scenarios(self):
        by_scenario, _body = self.previews("{+}{author}<, &>/{title}/")
        for label in ("Two authors", "Three authors with initials", "Single-name author", "Five authors (over the cap)"):
            self.assertIn(label, by_scenario)
        self.assertEqual(self.top_folder(by_scenario["Two authors"]), "Mira van der Holt & Jon Le Brun")
        self.assertEqual(self.top_folder(by_scenario["Three authors with initials"]), "Ana Pell, JK Varn, & Mara J. Holt")
        five = by_scenario["Five authors (over the cap)"]
        self.assertEqual(self.top_folder(five), "Ana Pell, Ivo Sand, Lee Doan, Mara Holt, & et al")
        self.assertIn("more than 4 authors", five["review_reasons"])

    def test_single_name_author_shows_the_readback_flag(self):
        by_scenario, _body = self.previews("{+}{author}{,}/{title}/")
        single = by_scenario["Single-name author"]
        self.assertIn("Audiobookshelf would read this author folder as different authors", single["review_reasons"])
        self.assertTrue(any(d["label"] == "Audiobookshelf reads" for d in single["review_details"]))

    def test_initials_option_changes_the_initials_example(self):
        template = "{+}{lname} {initials}{&}/{title}/"
        off, _ = self.previews(template)
        with mock.patch.dict(os.environ, {"LIBRAFORGE_AUTHOR_SCHEME": "universal"}):
            on, _ = self.previews(template, initials_follow_author_scheme=True)
        self.assertEqual(self.top_folder(off["Three authors with initials"]), "Pell & Varn JK & Holt J")
        self.assertEqual(self.top_folder(on["Three authors with initials"]), "Pell & Varn J.K. & Holt J")

    def test_shared_folder_warning_does_not_block(self):
        _by, body = self.previews("{+}{lname}{&}/{title}/")
        self.assertEqual(len(body["warnings"]), 1)
        self.assertTrue(body["previews"])
        resp = client.post("/api/organizer/naming-template/validate", json={"template": "{+}{lname}{&}/{title}/"})
        self.assertTrue(resp.json()["valid"])
        self.assertEqual(len(resp.json()["warnings"]), 1)

    def test_existing_scenarios_unchanged_for_the_default_template(self):
        by_scenario, body = self.previews(main_module.load_organizer_module(main_module.default_organizer_script()).DEFAULT_NAMING_TEMPLATE)
        self.assertEqual(body["warnings"], [])
        self.assertEqual(self.top_folder(by_scenario["No series"]), "C.B. Titus")


class AuthorBlockCommandTests(unittest.TestCase):
    def test_initials_flag_only_when_asked(self):
        base = dict(root_path="/audiobooks/_unorganized", use_default_scheme=False, naming_template="{+}{author}{&}/{title}/")
        self.assertNotIn("--initials-follow-author-scheme", main_module.build_organizer_command(main_module.OrganizerRunRequest(**base)))
        self.assertIn(
            "--initials-follow-author-scheme",
            main_module.build_organizer_command(main_module.OrganizerRunRequest(**base, initials_follow_author_scheme=True)),
        )

    def test_initials_flag_not_sent_with_the_built_in_scheme(self):
        req = main_module.OrganizerRunRequest(root_path="/audiobooks/_unorganized", use_default_scheme=True,
                                              initials_follow_author_scheme=True)
        self.assertNotIn("--initials-follow-author-scheme", main_module.build_organizer_command(req))
