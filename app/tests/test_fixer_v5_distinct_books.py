"""A folder of full-length books must not be grouped as one multi-part book.

Run 20260928-194730: "Walrus King - Tunnel Rat Books 1 thru 3" held three
complete MP3 books (12-16 h each); MP3 skips the embedded-chapter check, so
they were grouped and matched as Book 1. Big files whose own album tags name
different books are separate books; a long book split into big parts (a
Shadow Slave volume) shares one album and still groups.
"""
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
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_distinct_books", "scripts/audible-metadata-fixer-v5.py")
MB = 1_000_000


def group(files, albums, size_mb):
    return FIXER.build_multi_part_group_map(
        files,
        chapter_count_reader=lambda _p: 0,
        tag_reader=lambda p: {"album": albums[files.index(p)]} if albums[files.index(p)] else {},
        size_reader=lambda _p: size_mb * MB,
    )


class DistinctBooksFolderTests(unittest.TestCase):
    def test_big_files_naming_different_books_are_not_grouped(self):
        files = [Path(f"/t/Walrus King - Tunnel Rat 0{i}.mp3") for i in (1, 2, 3)]
        self.assertEqual(group(files, ["Tunnel Rat", "Tunnel Rat 2", "Tunnel Rat 3"], 350), {})

    def test_big_parts_of_one_book_still_group(self):
        files = [Path(f"/s/Shadow Slave Volume 2 - 0{i}.mp3") for i in (1, 2, 3)]
        self.assertEqual(
            group(files, ["Shadow Slave: Volume 2"] * 3, 900), {Path("/s"): files}
        )

    def test_part_markers_in_albums_are_the_same_book(self):
        files = [Path(f"/m/Age of Myth - 0{i}.mp3") for i in (1, 2)]
        albums = ["Age of Myth (1 of 2)", "Age of Myth (2 of 2)"]
        self.assertEqual(group(files, albums, 900), {Path("/m"): files})

    def test_small_parts_are_not_checked(self):
        files = [Path(f"/c/Book - 0{i}.mp3") for i in (1, 2, 3)]
        self.assertEqual(
            group(files, ["Chapter 1", "Chapter 2", "Chapter 3"], 40), {Path("/c"): files}
        )

    def test_missing_album_keeps_grouping(self):
        files = [Path(f"/x/Book - 0{i}.mp3") for i in (1, 2)]
        self.assertEqual(group(files, ["Book", ""], 900), {Path("/x"): files})

    def test_unnumbered_long_works_with_own_titles_are_not_one_book(self):
        names = ["Charmides", "Cratylus", "Gorgias", "Laches", "Symposium"]
        files = [Path(f"/philosophy/Plato Dramatized Audio/{name}.mp3") for name in names]
        groups = FIXER.build_multi_part_group_map(
            files,
            tag_reader=lambda path: {"title": path.stem},
            size_reader=lambda _path: 100 * MB,
        )
        self.assertEqual(groups, {})
        self.assertEqual(len(FIXER.build_processing_items(files, groups)), len(files))

    def test_unnumbered_chapters_with_shared_album_stay_grouped(self):
        files = [Path(f"/book/{name}.mp3") for name in (
            "Arrival", "Discovery", "Conflict", "Return", "Epilogue",
        )]
        groups = FIXER.build_multi_part_group_map(
            files,
            tag_reader=lambda path: {"title": path.stem, "album": "One Book"},
            size_reader=lambda _path: 100 * MB,
        )
        self.assertEqual(groups[Path("/book")], sorted(files, key=FIXER.natural_audio_sort_key))

    def test_short_unnumbered_chapters_stay_grouped_without_album(self):
        files = [Path(f"/book/{name}.mp3") for name in (
            "Arrival", "Discovery", "Conflict", "Return", "Epilogue",
        )]
        groups = FIXER.build_multi_part_group_map(
            files,
            tag_reader=lambda path: {"title": path.stem},
            size_reader=lambda _path: 20 * MB,
        )
        self.assertEqual(groups[Path("/book")], sorted(files, key=FIXER.natural_audio_sort_key))


if __name__ == "__main__":
    unittest.main()
