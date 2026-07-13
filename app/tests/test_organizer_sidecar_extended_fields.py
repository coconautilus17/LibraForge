import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_sidecar_fields", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


def make_book_sidecar_item(root: Path, folder: str, audio_name: str, book: dict) -> "ORGANIZER.BookItem":
    book_dir = root / folder
    book_dir.mkdir(parents=True, exist_ok=True)
    audio = book_dir / audio_name
    audio.touch()
    (book_dir / "libraforge.json").write_text(json.dumps({"book": book}), encoding="utf-8")
    return ORGANIZER.BookItem("folder", book_dir, [audio], audio)


def make_marker_item(root: Path, folder: str, audio_name: str, audible: dict) -> "ORGANIZER.BookItem":
    book_dir = root / folder
    book_dir.mkdir(parents=True, exist_ok=True)
    audio = book_dir / audio_name
    audio.touch()
    marker = audio.with_name(audio.name + ".audible-metadata-fixer.json")
    marker.write_text(json.dumps({"marker": {"audible": audible}}), encoding="utf-8")
    return ORGANIZER.BookItem("folder", book_dir, [audio], audio)


class BookSidecarExtendedFieldsTests(unittest.TestCase):
    def test_extracts_asin_publisher_genre_year_from_book_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = make_book_sidecar_item(
                root,
                "Some Book",
                "book.m4b",
                {
                    "title": "The Title",
                    "author": "Author Name",
                    "series": "",
                    "asin": "B0TESTASIN",
                    "publisher": "Publisher House",
                    "genre": "Fantasy",
                    "year": "2021",
                },
            )
            meta = ORGANIZER.metadata_from_sidecar(item)
            self.assertEqual(meta["asin"], "B0TESTASIN")
            self.assertEqual(meta["publisher"], "Publisher House")
            self.assertEqual(meta["genre"], "Fantasy")
            self.assertEqual(meta["year"], "2021")

    def test_norealasin_placeholder_becomes_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = make_book_sidecar_item(
                root,
                "Some Book",
                "book.m4b",
                {"title": "The Title", "author": "Author Name", "series": "", "asin": "NOREALASIN"},
            )
            meta = ORGANIZER.metadata_from_sidecar(item)
            self.assertEqual(meta["asin"], "")

    def test_missing_extended_fields_default_to_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = make_book_sidecar_item(
                root,
                "Some Book",
                "book.m4b",
                {"title": "The Title", "author": "Author Name", "series": ""},
            )
            meta = ORGANIZER.metadata_from_sidecar(item)
            self.assertEqual(meta["asin"], "")
            self.assertEqual(meta["publisher"], "")
            self.assertEqual(meta["genre"], "")
            self.assertEqual(meta["year"], "")


class MarkerSidecarExtendedFieldsTests(unittest.TestCase):
    def test_extracts_asin_publisher_genre_year_from_marker_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = make_marker_item(
                root,
                "Some Book",
                "book.m4b",
                {
                    "chosen_title": "The Title",
                    "author": "Author Name",
                    "series": "",
                    "asin": "B0MARKERASIN",
                    "publisher": "Marker Publisher",
                    "genre": "Sci-Fi",
                    "year": "2019",
                },
            )
            meta = ORGANIZER.metadata_from_sidecar(item)
            self.assertEqual(meta["asin"], "B0MARKERASIN")
            self.assertEqual(meta["publisher"], "Marker Publisher")
            self.assertEqual(meta["genre"], "Sci-Fi")
            self.assertEqual(meta["year"], "2019")


class InferMetadataExtendedFieldsTests(unittest.TestCase):
    def test_infer_metadata_threads_extended_fields_from_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book_dir = root / "Some Book"
            book_dir.mkdir(parents=True)
            audio = book_dir / "book.m4b"
            audio.touch()
            item = ORGANIZER.BookItem("folder", book_dir, [audio], audio)
            sidecar = {
                "title": "The Title",
                "author": "Author Name",
                "series": "",
                "book_number": "",
                "sequence_label": "",
                "narrator": "",
                "asin": "B0TESTASIN",
                "publisher": "Publisher House",
                "genre": "Fantasy",
                "year": "2021",
                "source": "sidecar:libraforge.json",
            }
            with patch.object(ORGANIZER, "metadata_from_sidecar", return_value=sidecar):
                meta = ORGANIZER.infer_metadata(item, root)
            self.assertEqual(meta["asin"], "B0TESTASIN")
            self.assertEqual(meta["publisher"], "Publisher House")
            self.assertEqual(meta["genre"], "Fantasy")
            self.assertEqual(meta["year"], "2021")

    def test_infer_metadata_defaults_extended_fields_to_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book_dir = root / "Some Book"
            book_dir.mkdir(parents=True)
            audio = book_dir / "book.m4b"
            audio.touch()
            item = ORGANIZER.BookItem("folder", book_dir, [audio], audio)
            with patch.object(ORGANIZER, "metadata_from_sidecar", return_value=None):
                meta = ORGANIZER.infer_metadata(item, root)
            self.assertEqual(meta["asin"], "")
            self.assertEqual(meta["publisher"], "")
            self.assertEqual(meta["genre"], "")
            self.assertEqual(meta["year"], "")


if __name__ == "__main__":
    unittest.main()
