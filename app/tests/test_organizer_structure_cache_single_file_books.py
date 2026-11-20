"""Folder Forge structure cache: single-file books in their own folders are indexed (#549),
and a series' existing Vol./Book label carries over to new books in it."""
import json
import tempfile
import unittest
from pathlib import Path

from app.tests.script_loader import load_script

ORGANIZER = load_script("organizer_v3_13_structure_cache_single_file", "organize-audiobooks-by-metadata-v3_13.py")


def add_book(folder: Path, filename: str, *, title: str, author: str, series: str, sequence: str) -> Path:
    """A finished single-file book: one m4b plus the fixer's folder-level libraforge.json."""
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / filename
    audio.write_bytes(b"")
    (folder / "libraforge.json").write_text(json.dumps({"book": {
        "title": title, "author": author, "series": series, "sequence": sequence,
    }}), encoding="utf-8")
    return audio


def series_entries(cache: dict, series_key: str) -> list[dict]:
    return [entry for entry in cache["entries"] if entry.get("series_key") == series_key]


class SingleFileBookIndexingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "library"
        self.series_dir = self.root / "Ada Writer" / "Deep Delve"
        for number, code in ((1, 101), (2, 102), (3, 103)):
            add_book(self.series_dir / f"Vol. {number} - Deep Delve {code}", f"Deep Delve {code}.m4b",
                     title=f"Deep Delve {code}", author="Ada Writer", series="Deep Delve", sequence=str(number))
        self.cache_path = Path(self._tmp.name) / "structure-cache.json"

    def tearDown(self):
        self._tmp.cleanup()

    def build(self) -> dict:
        return ORGANIZER.build_structure_cache(self.root, self.cache_path, progress_every=0)

    def test_single_file_book_folders_are_indexed(self):
        entries = series_entries(self.build(), ORGANIZER.normalize_series_key("Deep Delve"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], str(self.series_dir))
        self.assertEqual(entries[0]["book_count"], 3)
        self.assertEqual(entries[0]["source_paths"], sorted(str(p) for p in self.series_dir.iterdir()))

    def test_a_file_beside_book_folders_is_not_read_as_its_own_book_folder(self):
        # "Other Series" holds one stray m4b next to a proper book folder. The stray file's
        # parent is the series folder, so it must not be indexed with the author as its series.
        other = self.root / "Jane Doe" / "Other Series"
        add_book(other / "Book 1 - First", "First.m4b", title="First", author="Jane Doe", series="Other Series", sequence="1")
        (other / "stray.m4b").write_bytes(b"")
        entries = series_entries(self.build(), ORGANIZER.normalize_series_key("Other Series"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source_paths"], [str(other / "Book 1 - First")])
        self.assertNotIn("Jane Doe", entries[0]["series_aliases"])

    def test_a_book_without_a_series_folder_does_not_alias_the_author(self):
        # Author/Book layout: the book's tags name a series, but the folder above the
        # book is the author's, not a series folder.
        add_book(self.root / "Sam Solo" / "Standalone Saga", "Standalone Saga.m4b",
                 title="Standalone Saga", author="Sam Solo", series="Standalone Saga", sequence="1")
        entries = series_entries(self.build(), ORGANIZER.normalize_series_key("Standalone Saga"))
        self.assertEqual(len(entries), 1)
        self.assertNotIn("Sam Solo", entries[0]["series_aliases"])

    def test_entry_counts_the_labels_already_on_disk(self):
        entry = series_entries(self.build(), ORGANIZER.normalize_series_key("Deep Delve"))[0]
        self.assertEqual(entry["sequence_labels"], {"Vol.": 3})


class SeriesLabelCarriesOverTests(unittest.TestCase):
    def metadata(self, label: str) -> dict:
        return {
            "title": "Deep Delve 303", "author": "Ada Writer", "author_primary": "Ada Writer",
            "series": "Deep Delve", "book_number": "11", "sequence_label": label,
        }

    def cache(self, labels: dict) -> dict:
        cache = ORGANIZER.empty_structure_cache(Path("/library"))
        cache["entries"].append({
            "series": "Deep Delve", "series_key": ORGANIZER.normalize_series_key("Deep Delve"),
            "path": "/library/Ada Writer/Deep Delve", "canonical_author": "Ada Writer",
            "author_aliases": ["Ada Writer"], "author_keys": ORGANIZER.people_keys("Ada Writer"),
            "series_aliases": ["Deep Delve"], "book_count": sum(labels.values()) or 3,
            "source_paths": [], "sequence_labels": labels,
        })
        return cache

    def target_name(self, labels: dict, label: str = "Book") -> str:
        result = ORGANIZER.build_cached_target_dir(Path("/library"), self.metadata(label), self.cache(labels),
                                                   use_default_scheme=True)
        self.assertEqual(result.status, "existing")
        return result.target_dir.name

    def test_new_book_follows_the_series_existing_label(self):
        self.assertTrue(self.target_name({"Vol.": 10}).startswith("Vol. 11 - "), self.target_name({"Vol.": 10}))

    def test_clear_majority_wins(self):
        self.assertTrue(self.target_name({"Vol.": 9, "Book": 1}).startswith("Vol. 11 - "))

    def test_split_series_keeps_the_book_own_label(self):
        self.assertTrue(self.target_name({"Vol.": 2, "Book": 2}).startswith("Book 11 - "))

    def test_a_single_existing_book_is_not_enough(self):
        self.assertTrue(self.target_name({"Vol.": 1}).startswith("Book 11 - "))

    def test_cache_without_label_counts_keeps_the_book_own_label(self):
        cache = self.cache({})
        del cache["entries"][0]["sequence_labels"]
        result = ORGANIZER.build_cached_target_dir(Path("/library"), self.metadata("Book"), cache, use_default_scheme=True)
        self.assertTrue(result.target_dir.name.startswith("Book 11 - "))

    def test_an_override_label_beats_the_series_folders(self):
        overrides = {"series": {"Deep Delve": {"sequence_label": "Book"}}}
        cache = ORGANIZER.apply_overrides_to_cache(self.cache({"Vol.": 10}), overrides)
        metadata = ORGANIZER.apply_overrides_to_metadata(self.metadata("Vol."), overrides)
        result = ORGANIZER.build_cached_target_dir(Path("/library"), metadata, cache, use_default_scheme=True)
        self.assertTrue(result.target_dir.name.startswith("Book 11 - "), result.target_dir.name)

    def test_side_stories_and_novels_keep_their_own_numbering(self):
        labels = {"Book": 18, "Side Story": 14, "Novel": 2}
        self.assertTrue(self.target_name(labels, "Side Story").startswith("Side Story 11 - "))
        self.assertTrue(self.target_name(labels, "Novel").startswith("Novel 11 - "))

    def test_side_story_folders_do_not_count_toward_the_series_wording(self):
        # 3 Vol. against 1 Book is a clear Vol. series; the 5 side stories are a separate track.
        self.assertTrue(self.target_name({"Vol.": 3, "Book": 1, "Side Story": 5}).startswith("Vol. 11 - "))

    def test_books_without_a_number_are_unaffected(self):
        metadata = dict(self.metadata("Book"), book_number="")
        result = ORGANIZER.build_cached_target_dir(Path("/library"), metadata, self.cache({"Vol.": 10}), use_default_scheme=True)
        self.assertFalse(result.target_dir.name.startswith("Vol."))


if __name__ == "__main__":
    unittest.main()
