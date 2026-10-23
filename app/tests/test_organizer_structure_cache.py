"""Folder Forge's structure cache: how an existing Author/Series/Book library is
read into canonical authors and series (so new books join the right folders)
and how a series is matched against an entry."""
import tempfile
import unittest
from pathlib import Path
from app.tests.script_loader import load_script

ORG = load_script("organizer_structure_cache", "organize-audiobooks-by-metadata-v3_13.py")


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def book(self, rel, parts=2):
        for number in range(1, parts + 1):
            path = self.root / rel / f"Chapter {number:02d}.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

    def item(self, rel):
        return next(i for i in ORG.build_book_items(self.root, self.root) if i.source_path == self.root / rel)


class EntryMatchesSeriesTests(unittest.TestCase):
    ENTRY = {"series_key": "cradle", "series_aliases": ["Cradle", "The Cradle Saga!"]}

    def test_a_near_identical_alias_matches_but_a_different_series_does_not(self):
        entry = {"series_key": "zzz", "series_aliases": ["Dungeon Crawler Carls"]}
        self.assertTrue(ORG.entry_matches_series(entry, "Dungeon Crawler Carl"))
        self.assertFalse(ORG.entry_matches_series(entry, "Dungeon Master"))

    def test_blank_series_never_match(self):
        self.assertFalse(ORG.entry_matches_series(self.ENTRY, ""))
        self.assertFalse(ORG.entry_matches_series({"series_key": "", "series_aliases": []}, "!!!"))

if __name__ == "__main__":
    unittest.main()
