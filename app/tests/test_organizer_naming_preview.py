import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_naming_preview", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


def _write_book(root: Path, folder: str, audio_name: str, book: dict) -> None:
    book_dir = root / folder
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / audio_name).touch()
    (book_dir / "libraforge.json").write_text(json.dumps({"book": book}), encoding="utf-8")


class BuildBookItemsLimitTests(unittest.TestCase):
    def test_limit_stops_walk_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(20):
                _write_book(root, f"Book {i}", "book.m4b", {"title": f"Title {i}", "author": "Author", "series": ""})
            items = ORGANIZER.build_book_items(root, root, limit=3)
            self.assertGreaterEqual(len(items), 3)
            self.assertLess(len(items), 20)

    def test_no_limit_scans_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(5):
                _write_book(root, f"Book {i}", "book.m4b", {"title": f"Title {i}", "author": "Author", "series": ""})
            items = ORGANIZER.build_book_items(root, root)
            self.assertEqual(len(items), 5)


class PreviewNamingTemplateForRootTests(unittest.TestCase):
    def test_renders_default_template_against_real_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "_unorganized"
            root.mkdir()
            _write_book(
                root,
                "Some Book",
                "book.m4b",
                {"title": "The Title", "author": "Author Name", "series": "", "asin": "B0TEST"},
            )
            previews = ORGANIZER.preview_naming_template_for_root(
                root, Path(tmp), ORGANIZER.DEFAULT_NAMING_TEMPLATE
            )
            self.assertEqual(len(previews), 1)
            self.assertIn("Author Name", previews[0]["target_dir"])
            self.assertIn("The Title", previews[0]["target_dir"])
            self.assertIsNone(previews[0]["filename"])
            self.assertEqual(previews[0]["review_reasons"], [])

    def test_respects_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "_unorganized"
            root.mkdir()
            for i in range(5):
                _write_book(
                    root, f"Book {i}", "book.m4b", {"title": f"Title {i}", "author": "Author", "series": ""}
                )
            previews = ORGANIZER.preview_naming_template_for_root(
                root, Path(tmp), ORGANIZER.DEFAULT_NAMING_TEMPLATE, limit=3
            )
            self.assertEqual(len(previews), 3)

    def test_custom_template_surfaces_review_reasons(self):
        # {series},{order} are both core tokens; both empty for this
        # fixture (no series, no book_number) so this should flag.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "_unorganized"
            root.mkdir()
            _write_book(root, "Some Book", "book.m4b", {"title": "The Title", "author": "Author", "series": ""})
            previews = ORGANIZER.preview_naming_template_for_root(
                root, Path(tmp), "{author}/{series},{order}/{title}"
            )
            self.assertEqual(len(previews), 1)
            self.assertEqual(len(previews[0]["review_reasons"]), 1)

    def test_multi_file_book_filename_shown_as_unchanged(self):
        # A multi-file book must never show a rendered filename in the
        # preview -- naming_template_filename_for_item()'s exclusion has to
        # apply here too, not just in the real move-planning pipeline,
        # otherwise the preview lies about what would actually happen.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "_unorganized"
            root.mkdir()
            book_dir = root / "Multi File Book"
            book_dir.mkdir()
            audio_files = [book_dir / "Chapter 1.m4b", book_dir / "Chapter 2.m4b"]
            for f in audio_files:
                f.touch()
            item = ORGANIZER.BookItem("folder", book_dir, audio_files, audio_files[0])
            with patch.object(ORGANIZER, "build_book_items", return_value=[item]):
                with patch.object(
                    ORGANIZER,
                    "infer_metadata",
                    return_value={"title": "The Title", "author": "Author", "series": ""},
                ):
                    previews = ORGANIZER.preview_naming_template_for_root(
                        root, Path(tmp), "{author}/{title}"
                    )
            self.assertEqual(len(previews), 1)
            self.assertIsNone(previews[0]["filename"])


if __name__ == "__main__":
    unittest.main()
