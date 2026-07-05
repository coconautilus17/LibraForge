import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    audible_stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = audible_stub


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_publisher", "scripts/audible-metadata-fixer-v5.py")


class PublisherCaptureTests(unittest.TestCase):
    def test_capture_from_dedicated_tag(self):
        clues = {"author": "Jane Doe", "narrator": "Reader"}
        FIXER.capture_publisher_clue(clues, {"publisher": "Tantor Audio"})
        self.assertEqual(clues["publisher"], "Tantor Audio")
        self.assertTrue(clues["publisher_verified"])

    def test_capture_special_provider_flag(self):
        clues = {"author": "Jane Doe"}
        FIXER.capture_publisher_clue(clues, {"publisher": "GraphicAudio"})
        self.assertEqual(clues.get("publisher"), "GraphicAudio")
        self.assertEqual(FIXER.detect_special_provider(clues), "graphicaudio")

    def test_publisher_leak_stripped_from_author(self):
        clues = {"author": "Jane Doe, Tantor Audio", "narrator": "Reader"}
        FIXER.capture_publisher_clue(clues, {"publisher": "Tantor Audio"})
        self.assertEqual(clues["author"], "Jane Doe")

    def test_capture_from_adjacent_field_when_no_publisher_tag(self):
        clues = {"author": "Jane Doe"}
        FIXER.capture_publisher_clue(clues, {"album_artist": "Soundbooth Theater"})
        self.assertEqual(clues["publisher"], "Soundbooth Theater")
        self.assertEqual(FIXER.detect_special_provider(clues), "soundbooththeater")

    def test_format_descriptor_not_recorded_as_publisher(self):
        # A publisher tag that is only "Unabridged" is a format descriptor, not a publisher.
        clues = {"author": "Jane Doe"}
        FIXER.capture_publisher_clue(clues, {"publisher": "Unabridged"})
        self.assertNotIn("publisher", clues)

    def test_special_provider_from_dramatized_title(self):
        # The "Dramatized Adaptation" marker commonly sits in the title only
        # (e.g. "Storm Front (Dramatized Adaptation)"), where the publisher /
        # series / composer signals never see it. Detection must still fire.
        clues = {
            "title": "Storm Front (Dramatized Adaptation)",
            "author": "Jim Butcher",
            "series": "The Dresden Files",
        }
        self.assertEqual(FIXER.detect_special_provider(clues), "graphicaudio")

    def test_special_provider_from_dramatized_subtitle_still_detected(self):
        clues = {
            "title": "Storm Front",
            "subtitle": "Dramatized Adaptation",
            "author": "Jim Butcher",
        }
        self.assertEqual(FIXER.detect_special_provider(clues), "graphicaudio")

    def test_plain_title_is_not_special_provider(self):
        clues = {"title": "Storm Front", "author": "Jim Butcher"}
        self.assertIsNone(FIXER.detect_special_provider(clues))

    def test_full_cast_title_alone_is_not_graphicaudio(self):
        # "Full-Cast Edition" (Harry Potter / Pottermore) is not a dramatized
        # adaptation and must not be misrouted to the GraphicAudio endpoint.
        clues = {
            "title": "Harry Potter and the Goblet of Fire (Full-Cast Edition)",
            "author": "J.K. Rowling",
        }
        self.assertIsNone(FIXER.detect_special_provider(clues))


class PublisherWriteTests(unittest.TestCase):
    def _product(self):
        return {
            "asin": "B0PUB00001",
            "title": "The Book",
            "subtitle": "",
            "series": [{"title": "The Series", "sequence": "2"}],
            "authors": [{"name": "Jane Doe"}],
            "narrators": [{"name": "Reader"}],
            "runtime_length_min": 600,
            "publisher_summary": "A tale.",
        }

    def test_metadata_carries_publisher(self):
        clues = {
            "title": "The Book",
            "author": "Jane Doe",
            "publisher": "Tantor Audio",
            "local_duration_minutes": 600,
        }
        meta = FIXER.metadata_from_product(self._product(), clues, 1.0, "full")
        self.assertEqual(meta["publisher"], "Tantor Audio")
        args = FIXER.build_metadata_args(meta)
        joined = " ".join(args)
        self.assertIn("publisher=Tantor Audio", joined)

    def test_preview_includes_publisher(self):
        preview = FIXER.final_metadata_preview({"title": "X", "publisher": "Tantor Audio"})
        self.assertEqual(preview.get("publisher"), "Tantor Audio")


class FillMarkerHelperTests(unittest.TestCase):
    def test_merge_reports_filled_fields(self):
        current = {"title": "The Book", "artist": "Jane Doe"}
        metadata = {
            "title": "The Book",
            "author": "Jane Doe",
            "series": "The Series",
            "sequence": "2",
            "asin": "B0PUB00001",
            "edit_mode": "full",
        }
        _merged, filled = FIXER.merge_fill_missing_metadata(current, metadata)
        self.assertIn("series", filled)
        self.assertIn("asin", filled)

    def test_merge_complete_returns_empty(self):
        current = {
            "title": "The Book",
            "artist": "Jane Doe",
            "grouping": "The Series",
            "track": "2",
            "asin": "B0PUB00001",
        }
        metadata = {
            "title": "The Book",
            "author": "Jane Doe",
            "series": "The Series",
            "sequence": "2",
            "asin": "B0PUB00001",
            "edit_mode": "full",
        }
        _merged, filled = FIXER.merge_fill_missing_metadata(current, metadata)
        self.assertEqual(filled, [])

    def test_genre_is_filled_when_missing(self):
        # genre was missing from field_map entirely, so it never respected
        # fill-missing's "only write empty fields" contract -- it always took
        # the fresh match value regardless of what the file already had.
        current = {"title": "The Book", "artist": "Jane Doe"}
        metadata = {"title": "The Book", "author": "Jane Doe", "genre": "Fantasy", "edit_mode": "full"}
        merged, filled = FIXER.merge_fill_missing_metadata(current, metadata)
        self.assertEqual(merged["genre"], "Fantasy")
        self.assertIn("genre", filled)

    def test_genre_is_preserved_when_already_present(self):
        current = {"title": "The Book", "artist": "Jane Doe", "genre": "Horror"}
        metadata = {"title": "The Book", "author": "Jane Doe", "genre": "Fantasy", "edit_mode": "full"}
        merged, filled = FIXER.merge_fill_missing_metadata(current, metadata)
        self.assertEqual(merged["genre"], "Horror")
        self.assertNotIn("genre", filled)


if __name__ == "__main__":
    unittest.main()
