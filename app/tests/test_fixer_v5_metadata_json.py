import importlib.util
import json
import sys
import tempfile
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


FIXER = load_module("fixer_v5_metadata_json", "scripts/audible-metadata-fixer-v5.py")


class MetadataJsonPathTests(unittest.TestCase):
    def test_grouped_book_uses_folder_metadata_json(self):
        source = Path("/lib/Some Book/Some Book - 01.mp3")
        clues = {"group_search": {"applied": True}}
        self.assertEqual(
            FIXER.get_audiobookshelf_metadata_path(source, clues, alone_in_folder=False),
            Path("/lib/Some Book/metadata.json"),
        )

    def test_single_file_alone_uses_folder_metadata_json(self):
        source = Path("/lib/Some Book/book.m4b")
        self.assertEqual(
            FIXER.get_audiobookshelf_metadata_path(source, {}, alone_in_folder=True),
            Path("/lib/Some Book/metadata.json"),
        )

    def test_loose_single_file_uses_companion(self):
        source = Path("/lib/Loose/book.m4b")
        self.assertEqual(
            FIXER.get_audiobookshelf_metadata_path(source, {}, alone_in_folder=False),
            Path("/lib/Loose/book.m4b.metadata.json"),
        )


class DecideWriteTests(unittest.TestCase):
    def _metadata(self):
        return {
            "title": "The Book",
            "author": "Jane Doe",
            "series": "The Series",
            "sequence": "2",
            "narrator": "Reader",
            "year": "2021",
            "asin": "B0ABCDEF12",
            "edit_mode": "full",
        }

    def test_smart_noop_when_tags_match(self):
        meta = self._metadata()
        current = {
            "title": "The Book",
            "artist": "Jane Doe",
            "grouping": "The Series",
            "genre": "Audiobook",
            "asin": "B0ABCDEF12",
            "track": "2",
            "composer": "Reader",
            "date": "2021",
        }
        _eff, skip_write, note, filled = FIXER.decide_write(current, meta, "full", "smart")
        self.assertTrue(skip_write)
        self.assertIn("Smart-skip", note)
        self.assertEqual(filled, [])

    def test_smart_writes_when_tags_differ(self):
        meta = self._metadata()
        current = {"title": "Old Title", "genre": "Audiobook"}
        _eff, skip_write, _note, _filled = FIXER.decide_write(current, meta, "full", "smart")
        self.assertFalse(skip_write)

    def test_fill_missing_reports_filled_fields(self):
        meta = self._metadata()
        current = {"title": "The Book", "artist": "Jane Doe"}  # series/asin/etc missing
        eff, skip_write, note, filled = FIXER.decide_write(current, meta, "full", "fill-missing")
        self.assertFalse(skip_write)
        self.assertIn("series", filled)
        self.assertIn("asin", filled)
        # existing fields are preserved in the merged metadata
        self.assertEqual(eff["title"], "The Book")

    def test_fill_missing_noop_when_complete(self):
        meta = self._metadata()
        current = {
            "title": "The Book",
            "artist": "Jane Doe",
            "grouping": "The Series",
            "track": "2",
            "composer": "Reader",
            "date": "2021",
            "asin": "B0ABCDEF12",
        }
        _eff, skip_write, note, filled = FIXER.decide_write(current, meta, "full", "fill-missing")
        self.assertTrue(skip_write)
        self.assertEqual(filled, [])


class MetadataJsonWriteTests(unittest.TestCase):
    def test_write_places_folder_metadata_for_alone(self):
        meta = {
            "title": "Solo Book",
            "author": "Jane Doe",
            "narrator": "Reader",
            "series": "S",
            "sequence": "1",
            "year": "2020",
            "asin": "B0SOLO0001",
            "summary": "x",
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Solo Book" / "book.m4b"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"")
            target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=True
            )
            self.assertEqual(target, source.parent / "metadata.json")
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["title"], "Solo Book")
            self.assertEqual(payload["asin"], "B0SOLO0001")

    def test_write_places_companion_for_loose(self):
        meta = {"title": "Loose Book", "author": "Jane Doe", "asin": "B0LOOSE001"}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "loose.m4b"
            source.write_bytes(b"")
            target = FIXER.write_audiobookshelf_metadata_json(
                source, meta, {}, alone_in_folder=False
            )
            self.assertEqual(target, source.with_name("loose.m4b.metadata.json"))
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
