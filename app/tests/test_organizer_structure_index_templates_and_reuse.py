"""Folder Forge structure index: reading libraries laid out by other naming templates,
multi-disc and shared-folder books, and reusing unchanged books on rebuild (#550)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.tests.script_loader import load_script

ORGANIZER = load_script("organizer_v3_13_structure_index_templates", "organize-audiobooks-by-metadata-v3_13.py")

AUTHOR_SERIES_LEVEL = "{author} - {series}/{order} - {title}/"
SERIES_IN_BOOK = "{author}/{series} - {order} - {title}/"
FILES_IN_SERIES = "{author}/{series}/{order} - {title}"


def sidecar(path: Path, **book) -> None:
    path.write_text(json.dumps({"book": book}), encoding="utf-8")


def add_book(folder: Path, filename: str, **book) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / filename
    audio.write_bytes(b"")
    sidecar(folder / "libraforge.json", **book)
    return audio


def place(root: Path, template: str, **book) -> Path:
    """Lay a book out exactly where Folder Forge renders it under `template`, with its sidecar."""
    metadata = {"title": book["title"], "author": book["author"], "author_primary": book["author"],
                "series": book.get("series", ""), "book_number": book.get("sequence", ""),
                "sequence_label": book.get("sequence_label", "")}
    result = ORGANIZER.build_target_dir_for_template(root, metadata, template, filename_applies=False)
    return add_book(result.target_dir, f"{book['title']}.m4b", **book)


def entries_by_series(cache: dict) -> dict:
    return {entry["series_key"]: entry for entry in cache["entries"]}


class TemplateShapeTests(unittest.TestCase):
    def test_author_then_series_folders_can_be_read_from_the_path(self):
        for template in (ORGANIZER.DEFAULT_SCHEME_KEY, ORGANIZER.DEFAULT_NAMING_TEMPLATE,
                         "{author}/{series}/{number} - {title}/", "{author}/{series}/{order}/{filename}",
                         "{+}{author}<, &>/{series} [{edition}]/{order} - {title}/{filename}"):
            self.assertTrue(ORGANIZER.template_folders_name_author_and_series(template), template)

    def test_other_layouts_cannot(self):
        # "{lname}, {fname}" folders ("Sanderson, Brandon") are not read as an author by the
        # Author/Series path reading, so books under them are read from their metadata.
        for template in (AUTHOR_SERIES_LEVEL, SERIES_IN_BOOK, "{series}/{order} - {title}/", "{author}/{title}/",
                         "{lname}, {fname}/{series}/{order} - {title}/"):
            self.assertFalse(ORGANIZER.template_folders_name_author_and_series(template), template)


class IndexUnderTemplate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "library"
        self.root.mkdir()
        self.cache_path = self.tmp / "cache.json"

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, template: str) -> dict:
        return ORGANIZER.build_structure_cache(self.root, self.cache_path, progress_every=0, naming_template=template)


class OtherTemplateTests(IndexUnderTemplate):
    def test_author_dash_series_folders_are_not_read_as_series_dash_author(self):
        # "Deep Delve: Pacifist" renders as "Ada Writer - Deep Delve - Pacifist", which the
        # Author/Series reading takes for an older "Series - Author" folder.
        for n in (1, 2):
            place(self.root, AUTHOR_SERIES_LEVEL, title=f"Part {n}", author="Ada Writer",
                  series="Deep Delve: Pacifist", sequence=str(n), sequence_label="Vol.")
        key = ORGANIZER.normalize_series_key("Deep Delve: Pacifist")
        entries = entries_by_series(self.build(AUTHOR_SERIES_LEVEL))
        self.assertEqual(list(entries), [key])
        self.assertEqual(entries[key]["canonical_author"], "Ada Writer")
        self.assertEqual(entries[key]["book_count"], 2)
        self.assertEqual(entries[key]["sequence_labels"], {"Vol.": 2})

    def test_series_and_order_in_the_book_folder_name(self):
        books = [dict(title=f"Part {n}", sequence=str(n)) for n in (1, 2, 3)]
        books.append(dict(title="Part 4 + Part 5", sequence="4-5"))
        for book in books:
            place(self.root, SERIES_IN_BOOK, author="Ada Writer", series="Deep Delve", sequence_label="Vol.", **book)
        cache = self.build(SERIES_IN_BOOK)
        key = ORGANIZER.normalize_series_key("Deep Delve")
        self.assertEqual(list(entries_by_series(cache)), [key])
        self.assertEqual(entries_by_series(cache)[key]["book_count"], 4)
        self.assertEqual(entries_by_series(cache)[key]["sequence_labels"], {"Vol.": 4})
        result = ORGANIZER.build_cached_target_dir(
            self.root, {"title": "Part 6", "author": "Ada Writer", "author_primary": "Ada Writer",
                        "series": "Deep Delve", "book_number": "6", "sequence_label": "Book"},
            cache, naming_template=SERIES_IN_BOOK)
        self.assertEqual(result.target_dir, self.root / "Ada Writer" / "Deep Delve - Vol. 6 - Part 6")

    def test_books_stored_as_files_in_their_series_folder(self):
        series_dir = self.root / "Ada Writer" / "Deep Delve"
        series_dir.mkdir(parents=True)
        for n in (1, 2):
            audio = series_dir / f"Vol. {n} - Part {n}.m4b"
            audio.write_bytes(b"")
            sidecar(audio.with_name(audio.name + ".libraforge.json"),
                    title=f"Part {n}", author="Ada Writer", series="Deep Delve", sequence=str(n))
        entry = entries_by_series(self.build(FILES_IN_SERIES))[ORGANIZER.normalize_series_key("Deep Delve")]
        self.assertEqual(entry["book_count"], 2)
        self.assertEqual(entry["sequence_labels"], {"Vol.": 2})
        self.assertIn("Deep Delve", entry["series_aliases"])

    def test_files_sharing_a_folder_without_their_own_metadata_stay_out(self):
        shared = self.root / "Ada Writer" / "Some Folder"
        shared.mkdir(parents=True)
        for name in ("Alpha.m4b", "Beta.m4b"):
            (shared / name).write_bytes(b"")
        self.assertEqual(self.build(FILES_IN_SERIES)["entries"], [])


class PathOnlyBooksTests(IndexUnderTemplate):
    def test_books_without_metadata_are_not_read_from_folders_the_layout_does_not_name(self):
        # No sidecar and no tags: under "{author} - {series}/..." the folder names are not
        # Author/Series folders, so the index has nothing trustworthy to file them under.
        for n in (1, 2):
            book = self.root / "Ada Writer - Deep Delve - Pacifist" / f"Vol. {n} - Part {n}"
            book.mkdir(parents=True)
            (book / f"Part {n}.m4b").write_bytes(b"")
        self.assertEqual(self.build(AUTHOR_SERIES_LEVEL)["entries"], [])


class MultiDiscTests(IndexUnderTemplate):
    def test_volume_named_book_folders_are_separate_books(self):
        series_dir = self.root / "Ada Writer" / "Deep Delve"
        for n in (1, 2, 3):
            add_book(series_dir / f"Volume {n}", f"Volume {n}.m4b",
                     title=f"Volume {n}", author="Ada Writer", series="Deep Delve", sequence=str(n), sequence_label="Volume")
        entry = entries_by_series(self.build(ORGANIZER.DEFAULT_SCHEME_KEY))[ORGANIZER.normalize_series_key("Deep Delve")]
        self.assertEqual(entry["book_count"], 3)
        self.assertEqual(entry["sequence_labels"], {"Volume": 3})

    def test_a_multi_disc_book_is_one_book_in_its_series(self):
        book = self.root / "Ada Writer" / "Deep Delve" / "Book 1 - Part 1"
        for disc in ("Disc 1", "Disc 2"):
            (book / disc).mkdir(parents=True)
            (book / disc / "track.mp3").write_bytes(b"")
        sidecar(book / "libraforge.json", title="Part 1", author="Ada Writer", series="Deep Delve", sequence="1")
        add_book(self.root / "Ada Writer" / "Deep Delve" / "Book 2 - Part 2", "Part 2.m4b",
                 title="Part 2", author="Ada Writer", series="Deep Delve", sequence="2")
        cache = self.build(ORGANIZER.DEFAULT_SCHEME_KEY)
        self.assertEqual(list(entries_by_series(cache)), [ORGANIZER.normalize_series_key("Deep Delve")])
        entry = cache["entries"][0]
        self.assertEqual(entry["book_count"], 2)
        self.assertIn(str(book), entry["source_paths"])
        self.assertNotIn("Book 1 - Part 1", entry["series_aliases"])


class UsableCacheTests(IndexUnderTemplate):
    def test_only_a_cache_built_for_this_library_template_and_schema_is_usable(self):
        self.assertFalse(ORGANIZER.structure_cache_usable(self.cache_path, self.root, ORGANIZER.DEFAULT_SCHEME_KEY))
        self.build(ORGANIZER.DEFAULT_SCHEME_KEY)
        self.assertTrue(ORGANIZER.structure_cache_usable(self.cache_path, self.root, ORGANIZER.DEFAULT_SCHEME_KEY))
        self.assertFalse(ORGANIZER.structure_cache_usable(self.cache_path, self.root, ORGANIZER.DEFAULT_NAMING_TEMPLATE))
        self.assertFalse(ORGANIZER.structure_cache_usable(self.cache_path, self.tmp, ORGANIZER.DEFAULT_SCHEME_KEY))
        stale = json.loads(self.cache_path.read_text(encoding="utf-8"))
        stale["schema_version"] = ORGANIZER.STRUCTURE_CACHE_SCHEMA_VERSION - 1
        self.cache_path.write_text(json.dumps(stale), encoding="utf-8")
        self.assertFalse(ORGANIZER.structure_cache_usable(self.cache_path, self.root, ORGANIZER.DEFAULT_SCHEME_KEY))


class ReuseTests(IndexUnderTemplate):
    def setUp(self):
        super().setUp()
        self.series_dir = self.root / "Ada Writer" / "Deep Delve"
        for n in (1, 2, 3):
            add_book(self.series_dir / f"Vol. {n} - Part {n}", f"Part {n}.m4b",
                     title=f"Part {n}", author="Ada Writer", series="Deep Delve", sequence=str(n))

    def build_counting(self) -> tuple[dict, list[Path]]:
        read: list[Path] = []
        real = ORGANIZER.infer_metadata

        def counting(item, *args, **kwargs):
            read.append(item.source_path)
            return real(item, *args, **kwargs)

        with mock.patch.object(ORGANIZER, "infer_metadata", counting):
            cache = self.build(ORGANIZER.DEFAULT_SCHEME_KEY)
        return cache, read

    def test_a_rebuild_reads_only_books_that_changed(self):
        first, read = self.build_counting()
        self.assertEqual(len(read), 3)
        second, read = self.build_counting()
        self.assertEqual(read, [])
        self.assertEqual(second["entries"], first["entries"])

        changed = self.series_dir / "Vol. 2 - Part 2" / "libraforge.json"
        sidecar(changed, title="Part 2", author="Ada Writer", series="Deep Delve", sequence="2", narrator="Someone")
        stat = changed.stat()
        os.utime(changed, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        add_book(self.series_dir / "Vol. 4 - Part 4", "Part 4.m4b",
                 title="Part 4", author="Ada Writer", series="Deep Delve", sequence="4")
        third, read = self.build_counting()
        self.assertEqual(sorted(read), [self.series_dir / "Vol. 2 - Part 2", self.series_dir / "Vol. 4 - Part 4"])
        self.assertEqual(third["entries"][0]["book_count"], 4)

    def test_a_removed_book_leaves_the_index(self):
        self.build_counting()
        for p in (self.series_dir / "Vol. 3 - Part 3").iterdir():
            p.unlink()
        (self.series_dir / "Vol. 3 - Part 3").rmdir()
        cache, read = self.build_counting()
        self.assertEqual(read, [])
        self.assertEqual(cache["entries"][0]["book_count"], 2)

    def test_a_different_template_starts_over(self):
        self.build_counting()
        read: list[Path] = []
        real = ORGANIZER.infer_metadata
        with mock.patch.object(ORGANIZER, "infer_metadata", lambda item, *a, **k: read.append(item) or real(item, *a, **k)):
            self.build(ORGANIZER.DEFAULT_NAMING_TEMPLATE)
        self.assertEqual(len(read), 3)


if __name__ == "__main__":
    unittest.main()
