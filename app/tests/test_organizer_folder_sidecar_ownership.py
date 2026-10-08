"""Folder Forge must not give one book another book's folder-level libraforge.json.

Seen on a real dry run: Finnegans Wake.m4b sits in a folder with a dozen
study-guide ebooks, and the folder's libraforge.json names the m4b. Every
ebook inherited "Finnegans Wake / James Joyce" from it, all resolved to one
target and blocked each other. Walrus King's Tunnel Rat 02 and 03 inherited
book 01's sequence the same way (#351).
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "organize-audiobooks-by-metadata-v3_13.py"
SPEC = importlib.util.spec_from_file_location("organizer_v3_13_ownership", SCRIPT_PATH)
ORGANIZER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = ORGANIZER
SPEC.loader.exec_module(ORGANIZER)


def loose(path: Path, media_type: str = "audiobook"):
    return ORGANIZER.BookItem("loose_file", path, [path], path, media_type=media_type)


def folder_sidecar(folder: Path, source_file: str, title: str, sequence: str = "1") -> None:
    (folder / "libraforge.json").write_text(json.dumps({
        "marker": {"source_file": source_file,
                   "audible": {"title": title, "author": "Some Author", "series": "Some Series", "sequence": sequence}},
    }))


class FolderSidecarOwnershipTests(unittest.TestCase):
    def test_a_book_sharing_the_folder_does_not_inherit_the_owners_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            for name in ("Finnegans Wake.m4b", "Reader's Guide.pdf", "Restored.epub"):
                (folder / name).touch()
            folder_sidecar(folder, "Finnegans Wake.m4b", "Finnegans Wake")

            self.assertIsNone(ORGANIZER.metadata_from_sidecar(loose(folder / "Reader's Guide.pdf", "ebook")))
            owner = ORGANIZER.metadata_from_sidecar(loose(folder / "Finnegans Wake.m4b"))
            self.assertEqual(owner["title"], "Finnegans Wake")

    def test_per_file_sidecar_wins_over_a_foreign_folder_sidecar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            for name in ("Tunnel Rat 01.m4b", "Tunnel Rat 02.m4b"):
                (folder / name).touch()
            folder_sidecar(folder, "Tunnel Rat 01.m4b", "Tunnel Rat", "1")
            (folder / "Tunnel Rat 02.m4b.libraforge.json").write_text(json.dumps({
                "marker": {"audible": {"title": "Tunnel Rat 2", "author": "Walrus King",
                                       "series": "Tunnel Rat", "sequence": "2"}},
            }))

            got = ORGANIZER.metadata_from_sidecar(loose(folder / "Tunnel Rat 02.m4b"))
            self.assertEqual(got["book_number"], ORGANIZER.normalize_book_number("2"))

    def test_the_only_book_in_a_folder_keeps_its_folder_sidecar_after_a_rename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "Renamed.m4b").touch()
            folder_sidecar(folder, "Original Name.m4b", "The Real Title")

            got = ORGANIZER.metadata_from_sidecar(loose(folder / "Renamed.m4b"))
            self.assertEqual(got["title"], "The Real Title")


if __name__ == "__main__":
    unittest.main()
