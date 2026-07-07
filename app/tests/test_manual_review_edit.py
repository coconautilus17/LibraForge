"""POST /api/manual-review/edit -- direct field editing without a prior
match/search. Reuses _write_book_metadata (shared with
apply_manual_review_result) with write_policy always "overwrite" (blank
field always clears that tag -- there is no match value to fall back to)
and score always 1.0 (a direct user edit is definitionally full-confidence).
See docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main


class ManualReviewEditTests(unittest.TestCase):
    def _context(self, is_grouped=False, group_search=None):
        return {
            "source_path": "/library/Book/book.m4b",
            "display_path": "/library/Book",
            "is_grouped": is_grouped,
            "group_search": group_search or {},
            "metadata": {
                "title": "Old Title",
                "author": "Old Author",
                "asin": "B0OLDASIN01",
            },
        }

    def _fixer(self, written: dict, mutagen_candidate: bool = True):
        return SimpleNamespace(
            FILL_FIELDS=("title", "author", "series", "sequence", "narrator", "year", "asin", "genre", "subtitle"),
            clean_text=lambda value: value,
            clean_author_value=lambda value: value,
            normalize_book_number=lambda value: value,
            should_write_json_sidecar=lambda source, clues: bool(
                (clues.get("group_search") or {}).get("applied")
            ),
            is_mutagen_mp4_candidate=lambda source: mutagen_candidate,
            is_mutagen_mp3_candidate=lambda source: False,
            write_audiobookshelf_metadata_json=lambda source, metadata, clues, alone, fill_missing=False, skip_blank_fields=False: (
                written.setdefault("meta_json_skip_blank", skip_blank_fields),
                Path("/library/Book/metadata.json"),
            )[1],
            write_tags=lambda source, metadata, **kwargs: written.update(
                tags_metadata=metadata, tags_field_policy=kwargs.get("field_policy")
            ),
            write_m4b_tool_metadata_sidecar=lambda source, metadata, clues, score, field_policy="legacy": (
                written.update(sidecar_metadata=metadata, sidecar_field_policy=field_policy),
                Path("/library/Book/libraforge.json"),
            )[1],
            write_marker=lambda **kwargs: written.update(marker_kwargs=kwargs),
        )

    def _request(self, **overrides) -> "main.ManualReviewEditRequest":
        fields = {
            "path": "/library/Book",
            "title": "New Title",
            "author": "New Author",
            "subtitle": "",
            "narrator": "",
            "series": "",
            "sequence": "",
            "year": "",
            "asin": "",
            "isbn": "",
            "publisher": "",
            "genre": "",
            "summary": "",
            "cover_url": "",
        }
        fields.update(overrides)
        return main.ManualReviewEditRequest(**fields)

    def test_requires_title_and_author(self):
        req = self._request(title="")
        with patch.object(main, "inspect_manual_review_target", return_value=self._context()):
            with self.assertRaises(main.HTTPException) as ctx:
                main.edit_manual_review_book(req)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_blank_field_clears_tag_single_file(self):
        written = {}
        req = self._request(title="New Title", author="New Author", asin="")
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            result = main.edit_manual_review_book(req)

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["output_kind"], "tags")
        self.assertEqual(written["tags_field_policy"], "overwrite")
        self.assertEqual(written["tags_metadata"]["asin"], "")
        self.assertEqual(written["tags_metadata"]["title"], "New Title")
        self.assertFalse(written["meta_json_skip_blank"])
        self.assertEqual(written["marker_kwargs"]["field_policy"], "overwrite")
        self.assertEqual(written["marker_kwargs"]["score"], 1.0)
        self.assertEqual(written["marker_kwargs"]["mode"], "manual_edit")

    def test_grouped_book_writes_sidecar_only(self):
        written = {}
        req = self._request(title="New Title", author="New Author")
        ctx = self._context(
            is_grouped=True,
            group_search={"applied": True, "folder": "/library/Book", "file_count": 12},
        )
        with (
            patch.object(main, "inspect_manual_review_target", return_value=ctx),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            result = main.edit_manual_review_book(req)

        self.assertEqual(result["output_kind"], "json_sidecar")
        self.assertNotIn("tags_metadata", written)
        self.assertEqual(written["sidecar_field_policy"], "overwrite")

    def test_ffmpeg_fallback_surfaces_warning(self):
        written = {}
        req = self._request(title="New Title", author="New Author")
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written, mutagen_candidate=False)),
        ):
            result = main.edit_manual_review_book(req)

        self.assertIn("warning", result)
        self.assertIn("Full Overwrite", result["warning"])

    def test_cover_url_threads_replace_cover(self):
        written = {}
        req = self._request(title="New Title", author="New Author", cover_url="file:///tmp/cover.jpg")
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.edit_manual_review_book(req)

        self.assertEqual(written["tags_metadata"]["cover_url"], "file:///tmp/cover.jpg")

    def test_no_cover_url_does_not_touch_cover(self):
        written = {}
        req = self._request(title="New Title", author="New Author")
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.edit_manual_review_book(req)

        self.assertEqual(written["tags_metadata"]["cover_url"], "")


if __name__ == "__main__":
    unittest.main()
