"""--trust-abs-metadata (Folder Forge's opt-in): for a book Audiobookshelf
already has, its current record is used as the naming/organizing source
ahead of any local sidecar file -- for an existing, already-organized-but-
messy library where the user has already hand-corrected some books directly
in the Audiobookshelf UI.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_trust_abs_metadata", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


def make_folder_item(root: Path, folder: str, audio_name: str, book: dict | None = None) -> "ORGANIZER.BookItem":
    book_dir = root / folder
    book_dir.mkdir(parents=True, exist_ok=True)
    audio = book_dir / audio_name
    audio.touch()
    if book is not None:
        (book_dir / "libraforge.json").write_text(json.dumps({"book": book}), encoding="utf-8")
    return ORGANIZER.BookItem("folder", book_dir, [audio], audio)


class AbsMetadataAsSidecarCandidateTests(unittest.TestCase):
    def test_shapes_abs_media_into_the_sidecar_candidate_dict(self):
        media = {"metadata": {
            "title": "The Real Title", "authorName": "Real Author", "narratorName": "Real Narrator",
            "seriesName": "Real Series, Book 2", "asin": "B0REALASIN", "publisher": "Pub",
            "genres": ["Fantasy"], "publishedYear": "2022", "subtitle": "A Subtitle",
        }}
        candidate = ORGANIZER.abs_metadata_as_sidecar_candidate(media, "li1")
        self.assertEqual(candidate["title"], "The Real Title")
        self.assertEqual(candidate["author"], "Real Author")
        # "Real Series, Book 2" -- Pattern-A wording cleanup still applies.
        self.assertEqual(candidate["series"], "Real Series")
        self.assertEqual(candidate["book_number"], "002")
        self.assertEqual(candidate["narrator"], "Real Narrator")
        self.assertEqual(candidate["asin"], "B0REALASIN")
        self.assertEqual(candidate["publisher"], "Pub")
        self.assertEqual(candidate["genre"], "Fantasy")
        self.assertEqual(candidate["year"], "2022")
        self.assertEqual(candidate["subtitle"], "A Subtitle")
        self.assertEqual(candidate["source"], "abs:li1")


class MetadataFromSidecarAbsCandidateTests(unittest.TestCase):
    def test_abs_candidate_wins_over_local_sidecar_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = make_folder_item(
                Path(tmp), "Some Book", "book.m4b",
                {"title": "Stale Local Title", "author": "Stale Author", "series": "Stale Series"},
            )
            abs_candidate = {"title": "Fresh ABS Title", "author": "Fresh Author", "series": "", "source": "abs:li1"}
            result = ORGANIZER.metadata_from_sidecar(item, abs_candidate=abs_candidate)
            self.assertEqual(result, abs_candidate)

    def test_no_abs_candidate_falls_back_to_local_sidecar_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = make_folder_item(
                Path(tmp), "Some Book", "book.m4b",
                {"title": "Local Title", "author": "Local Author", "series": "Local Series"},
            )
            result = ORGANIZER.metadata_from_sidecar(item)
            self.assertEqual(result["title"], "Local Title")


class InferMetadataAbsIndexTests(unittest.TestCase):
    def _hit_index(self, book_dir: Path, media: dict, library_item_id: str = "li1") -> dict:
        return {
            "by_asin": {}, "by_path": {str(book_dir): {
                "library_item_id": library_item_id, "path": str(book_dir),
                "rel_path": book_dir.name, "updated_at": 100, "media": media,
            }},
        }

    def test_lookup_hit_uses_abs_data_over_local_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = make_folder_item(
                root, "Some Book", "book.m4b",
                {"title": "Stale Local Title", "author": "Stale Author", "series": "Stale Series"},
            )
            abs_index = self._hit_index(item.source_path, {"metadata": {"title": "Fresh ABS Title", "authorName": "Fresh Author"}})
            metadata = ORGANIZER.infer_metadata(item, root, abs_index=abs_index)
            self.assertEqual(metadata["title"], "Fresh ABS Title")
            self.assertEqual(metadata["author"], "Fresh Author")

    def test_lookup_miss_falls_back_to_local_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = make_folder_item(root, "Some Book", "book.m4b", {"title": "Local Title", "author": "Local Author"})
            metadata = ORGANIZER.infer_metadata(item, root, abs_index={"by_asin": {}, "by_path": {}})
            self.assertEqual(metadata["title"], "Local Title")

    def test_no_abs_index_never_looks_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = make_folder_item(root, "Some Book", "book.m4b", {"title": "Local Title", "author": "Local Author"})
            metadata = ORGANIZER.infer_metadata(item, root, abs_index=None)
            self.assertEqual(metadata["title"], "Local Title")

    def test_loose_file_item_looks_up_by_parent_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book_dir = root / "Some Book"
            book_dir.mkdir()
            audio = book_dir / "book.m4b"
            audio.touch()
            item = ORGANIZER.BookItem("loose_file", audio, [audio], audio)
            abs_index = self._hit_index(book_dir, {"metadata": {"title": "Fresh ABS Title", "authorName": "Fresh Author"}})
            metadata = ORGANIZER.infer_metadata(item, root, abs_index=abs_index)
            self.assertEqual(metadata["title"], "Fresh ABS Title")


if __name__ == "__main__":
    unittest.main()
